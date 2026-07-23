#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Download Functionality of YC
"""

# Built-in modules
from asyncio import run_coroutine_threadsafe
from hashlib import sha1
from os import getenv, listdir, remove
from os.path import abspath, dirname, exists, join, getsize, getmtime
from tempfile import TemporaryDirectory
from time import time, sleep
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

# Local modules
from yc_colours import RESET, Foreground
from yc_logging import NO_COLOR, YTDLPLogger, logger
from yc_magic import run_with_live_output
from yc_spotify import SpotifyURLProcessor
from yc_utils import (
    DATA_FOLDER,
    RAW_FOLDER,
    CONVERTED_AUDIO_FOLDER,
    CONVERTED_VIDEO_FOLDER,
    cap_width_and_height,
    create_data_folder_if_not_present,
    get_audio_name,
    get_video_name,
    get_audio_path,
    get_video_path,
    is_audio_already_downloaded,
    is_video_already_downloaded,
    load_config,
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
from yt_dlp.utils import DownloadError

# pylint settings
# pylint: disable=pointless-string-statement
# pylint: disable=fixme
# pylint: disable=too-many-locals
# pylint: disable=too-many-arguments
# pylint: disable=too-many-branches

FFMPEG_PATH = getenv("FFMPEG_PATH", "ffmpeg")
SANJUUNI_PATH = getenv("SANJUUNI_PATH", "sanjuuni")
DISABLE_OPENCL = getenv("DISABLE_OPENCL", "").lower() in ("1", "true", "yes")
DIRECT_AUDIO_EXTENSIONS = (
    ".mp3",
    ".aac",
    ".m4a",
    ".ogg",
    ".opus",
    ".flac",
    ".wav",
)
LIVE_VIDEO_BUFFER_SECONDS = int(getenv("LIVE_VIDEO_BUFFER_SECONDS", "30"))
RAW_CACHE_TTL_SECONDS = int(getenv("RAW_CACHE_TTL_SECONDS", "86400")) # 24 Hours default


def get_cached_raw_file(media_id: str) -> Optional[str]:
    """Returns absolute path to a cached raw download if it exists."""
    if not exists(RAW_FOLDER):
        return None
    try:
        for fname in listdir(RAW_FOLDER):
            if fname.startswith(f"{media_id}.") and not (
                fname.endswith(".part") or fname.endswith(".ytdl") or fname.endswith(".lock")
            ):
                fpath = join(RAW_FOLDER, fname)
                if exists(fpath) and getsize(fpath) > 0:
                    return fpath
    except OSError:
        pass
    return None


def clean_expired_raw_cache() -> None:
    """Deletes raw download cache files older than RAW_CACHE_TTL_SECONDS (default 24h)."""
    if not exists(RAW_FOLDER):
        return
    now = time()
    try:
        for fname in listdir(RAW_FOLDER):
            fpath = join(RAW_FOLDER, fname)
            if exists(fpath) and not (
                fname.endswith(".part") or fname.endswith(".ytdl") or fname.endswith(".lock")
            ):
                try:
                    if (now - getmtime(fpath)) > RAW_CACHE_TTL_SECONDS:
                        remove(fpath)
                        logger.info("Cleaned expired raw download (24h+): %s", fname)
                except OSError:
                    pass
    except OSError:
        pass


class LockFile:
    def __init__(self, path: str, timeout: int = 600):
        self.lock_path = path + ".lock"
        self.timeout = timeout

    def __enter__(self):
        start = time()
        while True:
            try:
                # Exclusive creation to act as a lock
                with open(self.lock_path, 'x'):
                    pass
                return
            except FileExistsError:
                if time() - start > self.timeout:
                    try:
                        remove(self.lock_path)
                    except FileNotFoundError:
                        pass
                    continue
                sleep(0.1)

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            remove(self.lock_path)
        except FileNotFoundError:
            pass


def update_client_status(client_state, client_id, status, **kwargs):
    """Updates the client state with a new status and optional extra fields."""
    if client_state is not None and client_id:
        state = client_state.get(client_id) or {}
        state["status"] = status
        state.update(kwargs)
        client_state[client_id] = state


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


def live_stream_id_from_url(url: str) -> str:
    """Creates a safe ID for direct stream URLs."""
    return f"live-{sha1(url.encode('utf-8')).hexdigest()[:16]}"


def is_legacy_ssl_handshake_error(err: Exception) -> bool:
    """Detects SSL handshake errors that suggest legacy-server-connect."""
    message = str(err).upper()
    return "SSLV3_ALERT_HANDSHAKE_FAILURE" in message or "LEGACY-SERVER-CONNECT" in message


def is_format_unavailable_error(err: Exception) -> bool:
    """Detects yt-dlp format-selection failures."""
    return "REQUESTED FORMAT IS NOT AVAILABLE" in str(err).upper()


def build_direct_audio_response(url: str, title: Optional[str] = None):
    """Builds a response tuple for direct audio streams."""
    media_id = live_stream_id_from_url(url)
    create_data_folder_if_not_present()
    out = {
        "action": "media",
        "id": media_id,
        "title": title or url,
        "like_count": None,
        "view_count": None,
        "is_live": True,
    }
    return (
        out,
        [get_audio_name(media_id)],
        {"source_url": url, "media_id": media_id},
    )


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
        temp_dir: str, media_id: str, resp: Websocket, loop, width: int, height: int,
        client_id: str = None, client_state = None, fps: Optional[float] = None,
        total_frames: int = 0
):
    """
    Converts the downloaded video to 32vid directly using Sanjuuni at maximum quality.
    """
    update_client_status(client_state, client_id, "Converting video...")
    run_coroutine_threadsafe(
        resp.send(
            dumps({"action": "status", "message": "Converting video to 32vid ..."})
        ),
        loop,
    )

    cached_file = get_cached_raw_file(media_id)
    if cached_file and exists(cached_file):
        input_file = cached_file
    else:
        raw_files = [f for f in listdir(temp_dir) if not f.endswith(".pre.mp4") and not f.endswith(".part") and not f.endswith(".ytdl")]
        input_file = join(temp_dir, raw_files[0]) if raw_files else None

    if not input_file or not exists(input_file):
        logger.warning("No input video file found for media_id %s in temp_dir %s", media_id, temp_dir)
        return

    if NO_COLOR:
        prefix = "[Sanjuuni]"
    else:
        prefix = f"{Foreground.BRIGHT_YELLOW}[Sanjuuni]{RESET} "

    import re

    def handler(line):
        clean_line = line
        if total_frames and total_frames > 0 and "/0" in line:
            try:
                m = re.search(r"frame\s+(\d+)/0\s+\(elapsed\s+([\d:]+)", line)
                if m:
                    curr_frame = int(m.group(1))
                    fps_match = re.search(r"([\d.]+)\s+fps", line)
                    curr_fps = float(fps_match.group(1)) if fps_match else 20.0
                    rem_frames = max(0, total_frames - curr_frame)
                    rem_sec = int(rem_frames / curr_fps) if curr_fps > 0 else 0
                    rem_min, rem_sec = divmod(rem_sec, 60)
                    rem_str = f"{rem_min:02d}:{rem_sec:02d}"
                    clean_line = re.sub(
                        r"frame\s+\d+/0\s+\(elapsed\s+[\d:]+,\s+remaining\s+[^,\)]+",
                        f"frame {curr_frame}/{total_frames} (elapsed {m.group(2)}, remaining {rem_str}",
                        line,
                    )
            except Exception:
                clean_line = line

        if any(w in clean_line.lower() for w in ("opencl", "device", "using")):
            logger.info("%s%s", prefix, clean_line)
        else:
            logger.debug("%s%s", prefix, clean_line)

        update_client_status(client_state, client_id, f"Converting: {clean_line}")

        run_coroutine_threadsafe(
            resp.send(dumps({"action": "status", "message": clean_line})), loop
        )

    def is_cancelled() -> bool:
        if resp and hasattr(resp, "closed") and resp.closed:
            return True
        if client_state is not None and client_id and client_id not in client_state:
            return True
        return False

    final_video_path = get_video_path(media_id, width, height)
    tmp_video_path = final_video_path + ".tmp"

    cmd = [
        SANJUUNI_PATH,
        "--width=" + str(width),
        "--height=" + str(height),
        "-i",
        input_file,
        "--raw",
        "--ordered",
        "-o",
        tmp_video_path,
    ]
    if DISABLE_OPENCL:
        cmd.append("--disable-opencl")

    returncode = run_with_live_output(
        cmd,
        handler,
        check_cancelled=is_cancelled,
    )

    if returncode == 0 and exists(tmp_video_path):
        from os import replace
        replace(tmp_video_path, final_video_path)
    else:
        if exists(tmp_video_path):
            try:
                remove(tmp_video_path)
            except OSError:
                pass
        if returncode != 0:
            logger.warning("Sanjuuni exited with %s", returncode)
            run_coroutine_threadsafe(
                resp.send(dumps({"action": "error", "message": "Failed to convert video!"})),
                loop,
            )


def download_audio(temp_dir: str, media_id: str, resp: Websocket, loop, client_id: str = None, client_state = None):
    """
    Converts the downloaded audio to dfpwm
    """
    update_client_status(client_state, client_id, "Converting audio...")
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

    cached_file = get_cached_raw_file(media_id)
    if cached_file and exists(cached_file):
        input_file = cached_file
    else:
        raw_files = [f for f in listdir(temp_dir) if not f.endswith(".part") and not f.endswith(".ytdl")]
        input_file = join(temp_dir, raw_files[0]) if raw_files else None

    if not input_file or not exists(input_file):
        logger.warning("No input audio file found for media_id %s in temp_dir %s", media_id, temp_dir)
        return

    final_audio_path = get_audio_path(media_id)
    tmp_audio_path = final_audio_path + ".tmp"

    returncode = run_with_live_output(
        [
            FFMPEG_PATH,
            "-i",
            input_file,
            "-f",
            "dfpwm",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-y",
            tmp_audio_path,
        ],
        handler,
    )

    if returncode == 0 and exists(tmp_audio_path):
        from os import replace
        replace(tmp_audio_path, final_audio_path)
    else:
        if exists(tmp_audio_path):
            try:
                remove(tmp_audio_path)
            except OSError:
                pass

    if returncode != 0:
        logger.warning("FFmpeg exited with %s", returncode)
        run_coroutine_threadsafe(
            resp.send(dumps({"action": "error", "message": "Faild to convert audio!"})),
            loop,
        )


def buffer_live_video(temp_dir: str, source_url: str, resp: Websocket, loop) -> bool:
    """Buffers a short segment of live video to a temp file for conversion."""
    run_coroutine_threadsafe(
        resp.send(
            dumps(
                {
                    "action": "status",
                    "message": f"Buffering live video ({LIVE_VIDEO_BUFFER_SECONDS}s) ...",
                }
            )
        ),
        loop,
    )

    out_file = join(temp_dir, "live_capture.mp4")

    if NO_COLOR:
        prefix = "[FFmpeg]"
    else:
        prefix = f"{Foreground.BRIGHT_GREEN}[FFmpeg]{RESET} "

    def handler(line):
        logger.debug("%s%s", prefix, line)

    returncode = run_with_live_output(
        [
            FFMPEG_PATH,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-analyzeduration",
            "0",
            "-probesize",
            "32768",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
            "-i",
            source_url,
            "-t",
            str(LIVE_VIDEO_BUFFER_SECONDS),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-pix_fmt",
            "yuv420p",
            "-y",
            out_file,
        ],
        handler,
    )

    if returncode != 0:
        logger.warning("FFmpeg live buffer exited with %s", returncode)
        run_coroutine_threadsafe(
            resp.send(
                dumps({"action": "error", "message": "Faild to buffer live video!"})
            ),
            loop,
        )
        return False
    return True


def download(
        url: str,
        resp: Websocket,
        loop,
        width: int,
        height: int,
        spotify_url_processor: SpotifyURLProcessor,
        client_id: str = None,
        client_state = None,
) -> Tuple[Dict[str, Any], list, Optional[Dict]]:
    """
    Downloads and converts the media from the give URL
    """
    try:
        return _download_impl(
            url, resp, loop, width, height, spotify_url_processor, client_id, client_state
        )
    except Exception as exc:
        err_msg = str(exc)
        logger.error("Unhandled error during download for client %s: %s", client_id or "unknown", exc, exc_info=True)
        update_client_status(client_state, client_id, "Download Error", title=url)
        run_coroutine_threadsafe(
            resp.send(dumps({"action": "error", "message": f"Server Error: {err_msg}"})),
            loop,
        )
        return (
            {"action": "error", "message": f"Server Error: {err_msg}"},
            [],
            None,
        )


def _download_impl(
        url: str,
        resp: Websocket,
        loop,
        width: int,
        height: int,
        spotify_url_processor: SpotifyURLProcessor,
        client_id: str = None,
        client_state = None,
) -> Tuple[Dict[str, Any], list, Optional[Dict]]:
    update_client_status(client_state, client_id, "Resolving URL...", url=url)

    is_video = width is not None and height is not None

    # cap height and width
    if width and height:
        width, height = cap_width_and_height(width, height)

    if is_direct_audio_stream_url(url):
        # Direct audio streams should always fall back to audio-only output.
        is_video = False
        width = None
        height = None
        update_client_status(client_state, client_id, "Direct Stream", title=url)
        return build_direct_audio_response(url)

    def my_hook(info):
        """https://github.com/yt-dlp/yt-dlp#adding-logger-and-progress-hook"""
        status = info.get("status")
        if status in ("waiting", "paused"):
            update_client_status(client_state, client_id, "Waiting on YouTube...")
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
                update_client_status(client_state, client_id, "Downloading...")
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

            clean_status = remove_ansi_escape_codes(f"Downloading {remove_whitespace(percent)}")
            update_client_status(client_state, client_id, clean_status)
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
        path_settings = config.get("path_settings", {}) if isinstance(config, dict) else {}
        cookie_file = path_settings.get("cookie_file")
        js_runtimes = path_settings.get("js_runtimes")
        format_selector = (
            "bestvideo[height<=720][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo[height<=720]+bestaudio/"
            "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            "bestvideo+bestaudio/best"
            if is_video
            else "bestaudio/best"
        )
        yt_dl_options = {
            "format": format_selector,
            "outtmpl": join(RAW_FOLDER, "%(id)s.%(ext)s"),
            "default_search": "auto",
            "restrictfilenames": True,
            "extract_flat": "in_playlist",
            "progress_hooks": [my_hook],
            "logger": YTDLPLogger(),
            "verbose": True,
            "force_ipv4": True,
            "concurrent_fragment_downloads": 8,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "mweb", "web"]
                }
            }
        }
        if cookie_file and not cookie_file.startswith("/path/to") and exists(cookie_file):
            yt_dl_options["cookiefile"] = cookie_file
        if js_runtimes:
            cleaned_runtimes = {}
            for rt_name, rt_conf in js_runtimes.items():
                if isinstance(rt_conf, dict):
                    rt_path = rt_conf.get("path")
                    if rt_path and not rt_path.startswith("/path/to") and exists(rt_path):
                        cleaned_runtimes[rt_name] = {"path": rt_path}
                    else:
                        cleaned_runtimes[rt_name] = {}
                else:
                    cleaned_runtimes[rt_name] = {}
            yt_dl_options["js_runtimes"] = cleaned_runtimes

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

        try:
            data = yt_dl.extract_info(url, download=False)
        except Exception as e:
            if (
                    is_legacy_ssl_handshake_error(e)
                    and urlparse(url).scheme in ("http", "https")
            ):
                is_video = False
                width = None
                height = None
                update_client_status(client_state, client_id, "Direct Stream", title=url)
                return build_direct_audio_response(url)

            err_msg = str(e)
            if "DRM protected" in err_msg or "DRM" in err_msg:
                clean_err = "This track is DRM protected (SoundCloud Go+ / Copyright)"
                update_client_status(client_state, client_id, "DRM Error", title=url)
            else:
                clean_err = err_msg.split('\n')[0] if '\n' in err_msg else err_msg
                update_client_status(client_state, client_id, "Media Error", title=url)

            logger.warning("Media extraction failed for client %s: %s", client_id or "unknown", clean_err)
            return (
                {"action": "error", "message": clean_err},
                [],
                None,
            )

        if data.get("extractor") == "generic":
            data["id"] = "g" + data.get("webpage_url_domain") + data.get("id")

        """
        If the data is a playlist, we need to get the first video and return it,
        also, we need to grep all video in the playlist to provide support.
        """
        if data.get("_type") == "playlist":
            entries = data.get("entries") or []
            for video in entries:
                playlist_videos.append(video.get("id"))

            if not entries:
                return (
                    {"action": "error", "message": "No results found."},
                    [],
                    None,
                )

            playlist_videos.pop(0)
            data = entries[0]

        """
        Search/playlist results can be flat entries without format URLs.
        Re-extract YouTube items by ID when key metadata is missing so
        video availability and download decisions are based on full info.
        """
        if data.get("extractor") == "youtube" and (
                data.get("view_count") is None
                or data.get("like_count") is None
                or (not data.get("formats") and not data.get("url"))
        ):
            try:
                data = yt_dl.extract_info(data.get("id"), download=False)
            except DownloadError as e:
                return (
                    {"action": "error", "message": str(e)},
                    [],
                    None,
                )
        
        # Update metadata as soon as we have it
        update_client_status(
            client_state, 
            client_id, 
            "Processing...", 
            title=data.get("title") or url,
            media_id=data.get("id")
        )

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
                {"audio_url": audio_url, "media_id": media_id},
            )

        media_id = data.get("id")

        if data.get("is_live") or data.get("live_status") == "is_live":
            if is_video:
                audio_url = pick_audio_url(data) or data.get("url") or url
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
                    {"audio_url": audio_url, "media_id": media_id},
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
                {"audio_url": audio_url, "media_id": media_id},
            )

        create_data_folder_if_not_present()
        clean_expired_raw_cache()

        with LockFile(join(DATA_FOLDER, media_id)):
            audio_downloaded = is_audio_already_downloaded(media_id)
            video_downloaded = (
                is_video_already_downloaded(media_id, width, height) if is_video else True
            )

            cached_raw = get_cached_raw_file(media_id)

            if not audio_downloaded or (not video_downloaded and is_video):
                if cached_raw:
                    logger.info("Found cached raw download for media %s (skipping yt-dlp): %s", media_id, cached_raw)
                    update_client_status(client_state, client_id, "Using cached video...")
                    run_coroutine_threadsafe(
                        resp.send(
                            dumps({"action": "status", "message": "Using cached raw download ..."})
                        ),
                        loop,
                    )
                else:
                    run_coroutine_threadsafe(
                        resp.send(
                            dumps({"action": "status", "message": "Downloading resource ..."})
                        ),
                        loop,
                    )

                    try:
                        yt_dl.process_ie_result(data, download=True)
                    except DownloadError as e:
                        if is_video and is_format_unavailable_error(e):
                            # Decide fallback based on actual download failure instead of
                            # incomplete pre-extraction metadata.
                            is_video = False
                            width = None
                            height = None
                            yt_dl.params["format"] = "bestaudio/best"
                            run_coroutine_threadsafe(
                                resp.send(
                                    dumps(
                                        {
                                            "action": "status",
                                            "message": "Video not available, falling back to audio.",
                                        }
                                    )
                                ),
                                loop,
                            )
                            audio_downloaded = is_audio_already_downloaded(media_id)
                            video_downloaded = True
                            if not audio_downloaded:
                                try:
                                    yt_dl.process_ie_result(data, download=True)
                                except DownloadError as retry_error:
                                    return (
                                        {"action": "error", "message": str(retry_error)},
                                        [],
                                        None,
                                    )
                        else:
                            err_msg = str(e)
                            clean_err = err_msg.split('\n')[0] if '\n' in err_msg else err_msg
                            update_client_status(client_state, client_id, "Download Error", title=data.get("title") or url)
                            logger.warning("Download failed for client %s: %s", client_id or "unknown", clean_err)
                            return (
                                {"action": "error", "message": clean_err},
                                [],
                                None,
                            )

            # TODO: Thread audio & video download

            if not audio_downloaded:
                download_audio(temp_dir, media_id, resp, loop, client_id, client_state)

            if not video_downloaded and is_video:
                # Extract actual video FPS and duration from metadata
                fps = data.get("fps")
                duration = data.get("duration")
                total_frames = int(duration * fps) if (duration and fps) else 0
                download_video(temp_dir, media_id, resp, loop, width, height, client_id, client_state, fps=fps, total_frames=total_frames)

    out = {
        "action": "media",
        "id": media_id,
        "title": data.get("title"),
        "like_count": data.get("like_count"),
        "view_count": data.get("view_count"),
        "channel": data.get("channel") or data.get("uploader") or data.get("artist"),
        "duration": data.get("duration"),
        "is_video": is_video,
        "has_video": is_video,
    }

    # Only return playlist_videos if there are videos in playlist_videos
    if len(playlist_videos) > 0:
        out["playlist_videos"] = playlist_videos

    files = []
    files.append(get_audio_name(media_id))
    if is_video:
        files.append(get_video_name(media_id, width, height))

    return out, files, None
