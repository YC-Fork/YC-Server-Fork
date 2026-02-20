#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Download Functionality of YC
"""

# Built-in modules
from asyncio import run_coroutine_threadsafe
from hashlib import sha1
import json
from json import JSONDecodeError
from os import getenv, listdir
from os.path import abspath, dirname, exists, join
from tempfile import TemporaryDirectory
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

# Local modules
from yc_colours import RESET, Foreground
from yc_logging import NO_COLOR, YTDLPLogger, logger
from yc_magic import run_with_live_output
from yc_spotify import SpotifyURLProcessor
from yc_utils import (
    cap_width_and_height,
    create_data_folder_if_not_present,
    get_audio_name,
    get_video_name,
    is_audio_already_downloaded,
    is_video_already_downloaded,
    remove_ansi_escape_codes,
    remove_whitespace,
)

# optional pip modules
try:
    from orjson import dumps
except ModuleNotFoundError:
    from json import dumps

# pip modules
from sanic import Websocket
from yt_dlp import YoutubeDL

# pylint settings
# pylint: disable=pointless-string-statement
# pylint: disable=fixme
# pylint: disable=too-many-locals
# pylint: disable=too-many-arguments
# pylint: disable=too-many-branches

DATA_FOLDER = join(dirname(abspath(__file__)), "data")
ROOT_DIR = dirname(dirname(dirname(abspath(__file__))))
CONFIG_PATH = join(ROOT_DIR, "config.json")
FFMPEG_PATH = getenv("FFMPEG_PATH", "ffmpeg")
SANJUUNI_PATH = getenv("SANJUUNI_PATH", "sanjuuni")
DISABLE_OPENCL = bool(getenv("DISABLE_OPENCL"))
DIRECT_AUDIO_EXTENSIONS = (
    ".mp3",
    ".aac",
    ".m4a",
    ".ogg",
    ".opus",
    ".flac",
    ".wav",
    ".m3u8",
)


def is_direct_audio_stream_url(url: str) -> bool:
    """Returns True if the URL points to a direct audio stream."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    path = (parsed.path or "").lower().rstrip("/")
    if any(path.endswith(ext) for ext in DIRECT_AUDIO_EXTENSIONS):
        return True
    if not path:
        return False
    last_segment = path.rsplit("/", 1)[-1]
    direct_names = {ext.lstrip(".") for ext in DIRECT_AUDIO_EXTENSIONS}
    return last_segment in direct_names


def is_direct_audio_stream_info(info: dict) -> bool:
    """Returns True if yt-dlp info looks like a direct audio stream."""
    audio_url = pick_audio_url(info)
    if audio_url and is_direct_audio_stream_url(audio_url):
        return True
    if info.get("protocol") not in ("http", "https"):
        return False
    if info.get("vcodec") and info.get("vcodec") != "none":
        return False
    if info.get("acodec") == "none":
        return False
    return info.get("duration") in (None, 0)


def load_config() -> Dict[str, Any]:
    """Loads optional config.json settings."""
    if not exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, JSONDecodeError) as exc:
        logger.warning("Failed to read config.json: %s", exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("config.json must be a JSON object")
        return {}
    return data


def live_stream_id_from_url(url: str) -> str:
    """Creates a safe ID for direct stream URLs."""
    return f"live-{sha1(url.encode('utf-8')).hexdigest()[:16]}"


def pick_audio_url(info: dict) -> Optional[str]:
    """Selects a direct audio URL from a yt-dlp info dict."""
    if info.get("url"):
        return info.get("url")

    formats = info.get("formats") or []
    audio_formats = [
        fmt
        for fmt in formats
        if fmt.get("acodec") != "none" and fmt.get("vcodec") == "none"
    ]
    if not audio_formats:
        audio_formats = [fmt for fmt in formats if fmt.get("acodec") != "none"]
    if not audio_formats:
        return None
    audio_formats.sort(
        key=lambda fmt: (fmt.get("abr") or 0, fmt.get("tbr") or 0), reverse=True
    )
    return audio_formats[0].get("url")


def download_video(
        temp_dir: str, media_id: str, resp: Websocket, loop, width: int, height: int
):
    """
    Converts the downloaded video to 32vid
    """
    run_coroutine_threadsafe(
        resp.send(
            dumps({"action": "status", "message": "Converting video to 32vid ..."})
        ),
        loop,
    )

    if NO_COLOR:
        prefix = "[Sanjuuni]"
    else:
        prefix = f"{Foreground.BRIGHT_YELLOW}[Sanjuuni]{RESET} "

    def handler(line):
        logger.debug("%s%s", prefix, line)
        run_coroutine_threadsafe(
            resp.send(dumps({"action": "status", "message": line})), loop
        )

    returncode = run_with_live_output(
        [
            SANJUUNI_PATH,
            "--width=" + str(width),
            "--height=" + str(height),
            "-i",
            join(temp_dir, listdir(temp_dir)[0]),
            "--raw",
            "-o",
            join(DATA_FOLDER, get_video_name(media_id, width, height)),
            "--disable-opencl" if DISABLE_OPENCL else "",
        ],
        handler,
    )

    if returncode != 0:
        logger.warning("Sanjuuni exited with %s", returncode)
        run_coroutine_threadsafe(
            resp.send(dumps({"action": "error", "message": "Faild to convert video!"})),
            loop,
        )


def download_audio(temp_dir: str, media_id: str, resp: Websocket, loop):
    """
    Converts the downloaded audio to dfpwm
    """
    run_coroutine_threadsafe(
        resp.send(
            dumps({"action": "status", "message": "Converting audio to dfpwm ..."})
        ),
        loop,
    )

    if NO_COLOR:
        prefix = "[FFmpeg]"
    else:
        prefix = f"{Foreground.BRIGHT_GREEN}[FFmpeg]{RESET} "

    def handler(line):
        logger.debug("%s%s", prefix, line)
        # TODO: send message to resp

    returncode = run_with_live_output(
        [
            FFMPEG_PATH,
            "-i",
            join(temp_dir, listdir(temp_dir)[0]),
            "-f",
            "dfpwm",
            "-ar",
            "48000",
            "-ac",
            "1",
            join(DATA_FOLDER, get_audio_name(media_id)),
        ],
        handler,
    )

    if returncode != 0:
        logger.warning("FFmpeg exited with %s", returncode)
        run_coroutine_threadsafe(
            resp.send(dumps({"action": "error", "message": "Faild to convert audio!"})),
            loop,
        )


def download(
        url: str,
        resp: Websocket,
        loop,
        width: int,
        height: int,
        spotify_url_processor: SpotifyURLProcessor,
) -> Tuple[Dict[str, Any], list, Optional[Dict]]:
    """
    Downloads and converts the media from the give URL
    """

    is_video = width is not None and height is not None

    # cap height and width
    if width and height:
        width, height = cap_width_and_height(width, height)

    if is_direct_audio_stream_url(url):
        if is_video:
            return (
                {"action": "error", "message": "Livestream video is not supported"},
                [],
                None,
            )
        media_id = live_stream_id_from_url(url)
        create_data_folder_if_not_present()
        out = {
            "action": "media",
            "id": media_id,
            "title": url,
            "like_count": None,
            "view_count": None,
            "is_live": True,
        }
        return out, [get_audio_name(media_id)], {"source_url": url, "media_id": media_id}

    def my_hook(info):
        """https://github.com/yt-dlp/yt-dlp#adding-logger-and-progress-hook"""
        status = info.get("status")
        if status in ("waiting", "paused"):
            run_coroutine_threadsafe(
                resp.send(
                    dumps(
                        {
                            "action": "status",
                            "message": "Waiting on YouTube ...",
                        }
                    )
                ),
                loop,
            )
            return

        if status == "downloading":
            percent = info.get("_percent_str")
            eta = info.get("_eta_str")
            if not percent or not eta:
                run_coroutine_threadsafe(
                    resp.send(
                        dumps(
                            {
                                "action": "status",
                                "message": "Waiting on YouTube ...",
                            }
                        )
                    ),
                    loop,
                )
                return

            run_coroutine_threadsafe(
                resp.send(
                    dumps(
                        {
                            "action": "status",
                            "message": remove_ansi_escape_codes(
                                f"download {remove_whitespace(percent)} " f"ETA {eta}"
                            ),
                        }
                    )
                ),
                loop,
            )

    # FIXME: Cleanup on Exception
    with TemporaryDirectory(prefix="youcube-") as temp_dir:
        config = load_config()
        cookie_file = config.get("cookie_file")
        js_runtimes = config.get("js_runtimes")
        yt_dl_options = {
            "format": "bestaudio/best",
            "outtmpl": join(temp_dir, "%(id)s.%(ext)s"),
            "default_search": "auto",
            "restrictfilenames": True,
            "extract_flat": "in_playlist",
            "progress_hooks": [my_hook],
            "logger": YTDLPLogger(),
            "extractor_args": {
                "youtube": {
                    "player_client": ["web"]
                }
            }
        }
        if cookie_file:
            yt_dl_options["cookiefile"] = cookie_file
        if js_runtimes:
            yt_dl_options["js_runtimes"] = js_runtimes

        yt_dl = YoutubeDL(yt_dl_options)

        run_coroutine_threadsafe(
            resp.send(
                dumps(
                    {"action": "status", "message": "Getting resource information ..."}
                )
            ),
            loop,
        )

        playlist_videos = []

        if spotify_url_processor:
            # Spotify FIXME: The first media key is sometimes duplicated
            processed_url = spotify_url_processor.auto(url)
            if processed_url:
                if isinstance(processed_url, list):
                    url = spotify_url_processor.auto(processed_url[0])
                    processed_url.pop(0)
                    playlist_videos = processed_url
                else:
                    url = processed_url

        data = yt_dl.extract_info(url, download=False)

        if data.get("extractor") == "generic":
            data["id"] = "g" + data.get("webpage_url_domain") + data.get("id")

        """
        If the data is a playlist, we need to get the first video and return it,
        also, we need to grep all video in the playlist to provide support.
        """
        if data.get("_type") == "playlist":
            for video in data.get("entries"):
                playlist_videos.append(video.get("id"))

            playlist_videos.pop(0)

            data = data["entries"][0]

        """
        If the video is extract from a playlist,
        the video is extracted flat,
        so we need to get missing information by running the extractor again.
        """
        if data.get("extractor") == "youtube" and (
                data.get("view_count") is None or data.get("like_count") is None
        ):
            data = yt_dl.extract_info(data.get("id"), download=False)

        if not is_video and is_direct_audio_stream_info(data):
            audio_url = pick_audio_url(data) or url
            media_id = live_stream_id_from_url(audio_url)
            create_data_folder_if_not_present()
            out = {
                "action": "media",
                "id": media_id,
                "title": data.get("title") or url,
                "like_count": data.get("like_count"),
                "view_count": data.get("view_count"),
                "is_live": True,
            }
            return (
                out,
                [get_audio_name(media_id)],
                {"source_url": audio_url, "media_id": media_id},
            )

        media_id = data.get("id")

        if data.get("is_live") or data.get("live_status") == "is_live":
            if is_video:
                return (
                    {"action": "error", "message": "Livestream video is not supported"},
                    [],
                    None,
                )
            audio_url = pick_audio_url(data)
            if not audio_url:
                return (
                    {
                        "action": "error",
                        "message": "Could not resolve livestream audio URL",
                    },
                    [],
                    None,
                )
            out = {
                "action": "media",
                "id": media_id,
                "title": data.get("title"),
                "like_count": data.get("like_count"),
                "view_count": data.get("view_count"),
                "is_live": True,
            }
            return (
                out,
                [get_audio_name(media_id)],
                {"source_url": audio_url, "media_id": media_id},
            )

        create_data_folder_if_not_present()

        audio_downloaded = is_audio_already_downloaded(media_id)
        video_downloaded = is_video_already_downloaded(media_id, width, height)

        if not audio_downloaded or (not video_downloaded and is_video):
            run_coroutine_threadsafe(
                resp.send(
                    dumps({"action": "status", "message": "Downloading resource ..."})
                ),
                loop,
            )

            yt_dl.process_ie_result(data, download=True)

        # TODO: Thread audio & video download

        if not audio_downloaded:
            download_audio(temp_dir, media_id, resp, loop)

        if not video_downloaded and is_video:
            download_video(temp_dir, media_id, resp, loop, width, height)

    out = {
        "action": "media",
        "id": media_id,
        # "fulltitle": data.get("fulltitle"),
        "title": data.get("title"),
        "like_count": data.get("like_count"),
        "view_count": data.get("view_count"),
        # "upload_date": data.get("upload_date"),
        # "tags": data.get("tags"),
        # "description": data.get("description"),
        # "categories": data.get("categories"),
        # "channel_name": data.get("channel"),
        # "channel_id": data.get("channel_id")
    }

    # Only return playlist_videos if there are videos in playlist_videos
    if len(playlist_videos) > 0:
        out["playlist_videos"] = playlist_videos

    files = []
    files.append(get_audio_name(media_id))
    if is_video:
        files.append(get_video_name(media_id, width, height))

    return out, files, None
