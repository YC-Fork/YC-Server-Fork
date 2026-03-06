#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
YC-Fork Server
"""

# built-in modules
import warnings
from asyncio import get_event_loop, run_coroutine_threadsafe, sleep as async_sleep
from base64 import b64encode
from datetime import datetime
from multiprocessing import Manager
from os import getenv, remove, system
from os.path import exists, getsize, join, dirname, abspath
from shutil import which
from subprocess import DEVNULL, Popen
import sys
import logging
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Any, List, Optional, Tuple, Type, Union

# Suppress the specific deprecation warning from sanic
# We use .* to match the [DEPRECATION v...] prefix
warnings.filterwarnings(
    "ignore",
    message=r".*Passing the loop argument to listeners is deprecated",
    category=DeprecationWarning,
    module="sanic.logging.deprecation"
)

# optional pip module
try:
    from orjson import JSONDecodeError, dumps
    from orjson import loads as load_json
except ModuleNotFoundError:
    from json import dumps
    from json import loads as load_json
    from json.decoder import JSONDecodeError

try:
    from types import UnionType
except ImportError:
    UnionType = Union[int, str]


# pip modules
from sanic import Request, Sanic, Websocket
from sanic.compat import open_async
from sanic.exceptions import SanicException
from sanic.handlers import ErrorHandler
from sanic.response import raw, text
from sanic_ext import Extend
from spotipy import MemoryCacheHandler, SpotifyClientCredentials
from spotipy.client import Spotify

# local modules
from yc_admin import admin_bp
from yc_colours import RESET, Foreground
from yc_download import DATA_FOLDER, FFMPEG_PATH, SANJUUNI_PATH, download
from yc_logging import NO_COLOR, setup_logging
from yc_magic import run_function_in_thread_from_async_function
from yc_spotify import SpotifyURLProcessor
from yc_utils import (
    cap_width_and_height,
    create_data_folder_if_not_present,
    get_audio_name,
    get_video_name,
    is_save,
    load_config,
    VIDEO_FORMAT,
)

VERSION = "0.1.1"

# one dfpwm chunk is 16 bits
CHUNK_SIZE = 16

"""
CHUNKS_AT_ONCE should not be too big, [CHUNK_SIZE * 1024]
because then the CC Computer cant decode the string fast enough!
Also, it should not be too small because then the client
would need to send thousands of WS messages
and that would also slow everything down! [CHUNK_SIZE * 1]
"""
CHUNKS_AT_ONCE = CHUNK_SIZE * 256


FRAMES_AT_ONCE = 10

# pylint settings
# pylint: disable=pointless-string-statement
# pylint: disable=fixme
# pylint: disable=multiple-statements

"""
Ubuntu nvida support fix and maby alpine support ?
us async base64 ?
use HTTP (and Streaming)
Add uvloop support https://github.com/CC-YouCube/server/issues/6
"""

"""
1 dfpwm chunk = 16
MAX_DOWNLOAD = 16 * 1024 * 1024 = 16777216
WEBSOCKET_MESSAGE = 128 * 1024 = 131072
(MAX_DOWNLOAD = 128 * WEBSOCKET_MESSAGE)

the speaker can accept a maximum of 128 x 1024 samples 16KiB

playAudio
This accepts a list of audio samples as amplitudes between -128 and 127.
These are stored in an internal buffer and played back at 48kHz.
If this buffer is full, this function will return false.
"""

"""Related CC-Tweaked issues
Streaming HTTP response https://github.com/cc-tweaked/CC-Tweaked/issues/1181
Speaker Networks        https://github.com/cc-tweaked/CC-Tweaked/issues/1488
Pocket computers do not have many usecases without network access
https://github.com/cc-tweaked/CC-Tweaked/issues/1406
Speaker limit to 8      https://github.com/cc-tweaked/CC-Tweaked/issues/1313
Some way to notify player through pocket computer with modem
https://github.com/cc-tweaked/CC-Tweaked/issues/1148
Memory limits for computers https://github.com/cc-tweaked/CC-Tweaked/issues/1580
"""

"""TODO: Add those:
AudioDevices:
 - Speaker Note (Sound)  https://tweaked.cc/peripheral/speaker.html
 - Notblock              https://www.youtube.com/watch?v=XY5UvTxD9dA
 - Create Steam whistles https://www.youtube.com/watch?v=dgZ4F7U19do
                         https://github.com/danielathome19/MIDIToComputerCraft/tree/master

Video Formats:
 - 32vid binary https://github.com/MCJack123/sanjuuni
 - qtv          https://github.com/Axisok/qtccv

Audio Formats:
 - DFPWM ffmpeg fallback ? https://github.com/asiekierka/pixmess/blob/master/scraps/aucmp.py
 - PCM
 - NBS  https://github.com/Xella37/NBS-Tunes-CC
 - MIDI https://github.com/OpenPrograms/Sangar-Programs/blob/master/midi.lua
 - XM   https://github.com/MCJack123/tracc

Audio u. Video preview / thumbnail:
 - NFP  https://tweaked.cc/library/cc.image.nft.html
 - bimg https://github.com/SkyTheCodeMaster/bimg
 - as 1 qtv frame
 - as 1 32vid frame
"""

logger = setup_logging()
# TODO: change sanic logging format


async def get_vid(vid_file: str, tracker: int, max_bytes: int) -> List[str]:
    """Returns up to max_bytes of 32vid lines starting at tracker."""
    async with await open_async(file=vid_file, mode="r", encoding="utf-8") as file:
        await file.seek(tracker)
        lines = []
        total = 0
        for _unused in range(FRAMES_AT_ONCE):
            line = (await file.readline())[:-1]  # remove \n
            if line == "":
                lines.append("")
                break
            line_len = len(line)
            if total and total + line_len > max_bytes:
                break
            if total == 0 and line_len > max_bytes:
                lines.append(line)
                break
            lines.append(line)
            total += line_len

    return lines


async def getchunk(media_file: str, chunkindex: int) -> bytes:
    """Returns a chunk of the given media file"""
    async with await open_async(file=media_file, mode="rb") as file:
        await file.seek(chunkindex * CHUNKS_AT_ONCE)
        return await file.read(CHUNKS_AT_ONCE)


def _remove_live_files(entry: dict) -> None:
    file_paths = []
    if entry.get("file_path"):
        file_paths.append(entry.get("file_path"))
    if entry.get("audio_file_path"):
        file_paths.append(entry.get("audio_file_path"))
    if entry.get("video_file_path"):
        file_paths.append(entry.get("video_file_path"))
    for path in {p for p in file_paths if p}:
        if exists(path):
            try:
                remove(path)
            except PermissionError:
                logger.warning("Failed to remove live stream file: %s", path)


def start_live_audio_stream(
    source_url: str,
    media_id: str,
    resp: Websocket,
    loop,
    live_streams: dict,
    live_streams_lock: Lock,
    client_id: int,
) -> None:
    """Starts a live audio stream and writes dfpwm output to disk."""
    file_name = get_audio_name(media_id)
    file_path = join(DATA_FOLDER, file_name)
    with live_streams_lock:
        entry = live_streams.get(media_id)
        if not entry:
            entry = {
                "media_id": media_id,
                "clients": {client_id},
                "last_used": datetime.now(),
                "stop_event": Event(),
                "ended": False,
                "delete_on_end": False,
                "start_time": monotonic(),
            }
            live_streams[media_id] = entry
        else:
            entry.setdefault("clients", set()).add(client_id)
            entry["last_used"] = datetime.now()
            entry.setdefault("stop_event", Event())
            entry.setdefault("start_time", monotonic())

        entry["file_name"] = file_name
        entry["file_path"] = file_path
        entry["audio_file_path"] = file_path

    stop_event = entry["stop_event"]

    create_data_folder_if_not_present()

    if exists(file_path):
        try:
            remove(file_path)
        except PermissionError:
            logger.warning("Live stream file in use, reusing: %s", file_path)

    def run():
        run_coroutine_threadsafe(
            resp.send(dumps({"action": "status", "message": "Starting live stream ..."})),
            loop,
        )

        cmd = [
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
            "-f",
            "dfpwm",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-y",
            file_path,
        ]

        with Popen(cmd, stdout=DEVNULL, stderr=DEVNULL) as process:
            while process.poll() is None:
                if stop_event.is_set():
                    process.terminate()
                    break
                sleep(0.25)
            process.wait()

        with live_streams_lock:
            entry["ended"] = True
            delete_on_end = entry.get("delete_on_end") or not entry.get("clients")

        run_coroutine_threadsafe(
            resp.send(dumps({"action": "status", "message": "Live stream ended"})),
            loop,
        )

        if delete_on_end:
            _remove_live_files(entry)

        with live_streams_lock:
            if delete_on_end:
                live_streams.pop(media_id, None)

    thread = Thread(target=run, daemon=True)
    entry["audio_thread"] = thread

    thread.start()


async def get_live_chunk(
    media_file: str, chunkindex: int, entry: dict, live_streams_lock: Lock
) -> Optional[bytes]:
    """Waits for the next live chunk to be available."""
    target_size = (chunkindex + 1) * CHUNKS_AT_ONCE
    start_time = monotonic()

    while True:
        if exists(media_file):
            size = getsize(media_file)
            if size >= target_size:
                return await getchunk(media_file, chunkindex)

        with live_streams_lock:
            ended = entry.get("ended", False)

        if ended and exists(media_file):
            if getsize(media_file) > chunkindex * CHUNKS_AT_ONCE:
                return await getchunk(media_file, chunkindex)
            return None

        if ended:
            return None

        if not entry.get("buffering_done") and LIVE_STREAM_READ_TIMEOUT > 0:
            if monotonic() - start_time >= LIVE_STREAM_READ_TIMEOUT:
                return None

        await async_sleep(LIVE_STREAM_POLL_INTERVAL)


def live_stream_cleaner(live_streams: dict, live_streams_lock: Lock):
    """Stops live streams that have been idle for too long."""
    if LIVE_STREAM_CLEANUP_INTERVAL <= 0 or LIVE_STREAM_IDLE_TIMEOUT <= 0:
        return

    while True:
        sleep(LIVE_STREAM_CLEANUP_INTERVAL)
        now = datetime.now()

        with live_streams_lock:
            entries = list(live_streams.items())

        for media_id, entry in entries:
            last_used = entry.get("last_used")
            if not last_used:
                continue

            if (now - last_used).total_seconds() <= LIVE_STREAM_IDLE_TIMEOUT:
                continue

            entry.get("stop_event").set()
            _remove_live_files(entry)

            with live_streams_lock:
                live_streams.pop(media_id, None)

# pylint: enable=redefined-outer-name


def assert_resp(
    __obj_name: str,
    __obj: Any,
    __class_or_tuple: Union[
        Type, UnionType, Tuple[Union[Type, UnionType, Tuple[Any, ...]], ...]
    ],
) -> Union[dict, None]:
    """
    "assert" / isinstance that returns a dict that can be send as a ws response
    """
    if not isinstance(__obj, __class_or_tuple):
        return {
            "action": "error",
            "message": f"{__obj_name} must be a {__class_or_tuple.__name__}",
        }
    return None


def resolve_config_value(value, env_key: str) -> Optional[str]:
    if value is None:
        return getenv(env_key)
    if isinstance(value, str) and not value.strip():
        return getenv(env_key)
    return value


# pylint: disable=duplicate-code
config = load_config()
spotify_config = config.get("spotify") if isinstance(config.get("spotify"), dict) else {}
spotify_client_id = resolve_config_value(
    spotify_config.get("client_id"), "SPOTIPY_CLIENT_ID"
)
spotify_client_secret = resolve_config_value(
    spotify_config.get("client_secret"), "SPOTIPY_CLIENT_SECRET"
)
spotify_market = spotify_config.get("market") if spotify_config else None
if isinstance(spotify_market, str) and not spotify_market.strip():
    spotify_market = None
spotify_market = spotify_market or "NL"
# pylint: disable-next=invalid-name
spotipy = None

if spotify_client_id and spotify_client_secret:
    spotipy = Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=spotify_client_id,
            client_secret=spotify_client_secret,
            cache_handler=MemoryCacheHandler(),
        )
    )

# pylint: disable-next=invalid-name
spotify_url_processor = None
if spotipy:
    spotify_url_processor = SpotifyURLProcessor(spotipy, spotify_market=spotify_market)

# pylint: enable=duplicate-code


class Actions:
    """
    Default set of actions
    Every action needs to be called with a message and needs to return a dict response
    """

    # pylint: disable=missing-function-docstring

    @staticmethod
    async def request_media(message: dict, resp: Websocket, request: Request):
        loop = get_event_loop()
        # get "url"
        url = message.get("url")
        if error := assert_resp("url", url, str):
            return error
        url = url.strip()
        # TODO: assert_resp width and height
        out, files, live_info = await run_function_in_thread_from_async_function(
            download,
            url,
            resp,
            loop,
            message.get("width"),
            message.get("height"),
            spotify_url_processor,
        )
        if live_info:
            live_streams, live_streams_lock = ensure_live_stream_ctx(request.app)
            client_state = get_shared_client_state(request.app)
            base_media_id = live_info.get("media_id")
            media_id = f"{base_media_id}-{id(resp):x}"
            out["id"] = media_id
            live_info["media_id"] = media_id
            if client_state is not None:
                client_id = f"{id(resp):x}"
                state = client_state.get(client_id) or {}
                state.update(
                    {
                        "mode": "audio",
                        "media_id": media_id,
                        "title": out.get("title"),
                        "is_live": True,
                        "url": url,
                        "listening_since": monotonic(),
                    }
                )
                client_state[client_id] = state

            audio_url = live_info.get("audio_url") or live_info.get("source_url")
            if audio_url:
                start_live_audio_stream(
                    audio_url,
                    media_id,
                    resp,
                    loop,
                    live_streams,
                    live_streams_lock,
                    id(resp),
                )

            await resp.send(dumps({"action": "status", "message": "Buffering live stream ..."}))
            return out

        for file in files:
            request.app.shared_ctx.data[file] = datetime.now()
        client_state = get_shared_client_state(request.app)
        has_video_file = any(
            file.lower().endswith(f".{VIDEO_FORMAT}") for file in files
        )
        if client_state is not None:
            client_id = f"{id(resp):x}"
            state = client_state.get(client_id) or {}
            state.update(
                {
                    "mode": "audio+video" if has_video_file else "audio",
                    "media_id": out.get("id"),
                    "title": out.get("title"),
                    "is_live": False,
                    "url": url,
                    "listening_since": monotonic(),
                }
            )
            client_state[client_id] = state
        return out

    @staticmethod
    async def get_chunk(message: dict, ws: Websocket, request: Request):
        # get "chunkindex"
        chunkindex = message.get("chunkindex")
        if error := assert_resp("chunkindex", chunkindex, int):
            return error

        # get "id"
        media_id = message.get("id")
        if error := assert_resp("media_id", media_id, str):
            return error

        if is_save(media_id):
            file_name = get_audio_name(message.get("id"))
            file = join(DATA_FOLDER, file_name)

            live_entry = None
            if hasattr(request.app.ctx, "live_streams") and hasattr(
                request.app.ctx, "live_streams_lock"
            ):
                live_streams, live_streams_lock = ensure_live_stream_ctx(request.app)
                with live_streams_lock:
                    live_entry = live_streams.get(media_id)
                    if live_entry:
                        live_entry.setdefault("clients", set()).add(id(ws))
                        live_entry["last_used"] = datetime.now()

            if live_entry and live_entry.get("audio_file_path"):
                if chunkindex == 0 and not live_entry.get("buffering_notified"):
                    live_entry["buffering_notified"] = True
                    await ws.send(
                        dumps(
                            {"action": "status", "message": "Buffering live stream ..."}
                        )
                    )
                chunk = await get_live_chunk(file, chunkindex, live_entry, live_streams_lock)
                if not chunk:
                    return {"action": "error", "message": "Live stream ended"}
                if chunkindex == 0 and not live_entry.get("buffering_done"):
                    live_entry["buffering_done"] = True
                    start_time = live_entry.get("start_time", monotonic())
                    elapsed = monotonic() - start_time
                    await ws.send(
                        dumps(
                            {
                                "action": "status",
                                "message": f"Buffered in {elapsed:.1f}s",
                            }
                        )
                    )
            else:
                request.app.shared_ctx.data[file_name] = datetime.now()
                chunk = await getchunk(file, chunkindex)

            return {"action": "chunk", "chunk": b64encode(chunk).decode("ascii")}
        logger.warning("User tried to use special Characters")
        return {"action": "error", "message": "You dare not use special Characters"}

    @staticmethod
    async def get_vid(message: dict, ws: Websocket, request: Request):
        # get "line"
        tracker = message.get("tracker")
        if error := assert_resp("tracker", tracker, int):
            return error

        # get "id"
        media_id = message.get("id")
        if error := assert_resp("id", media_id, str):
            return error

        # get "width"
        width = message.get("width")
        if error := assert_resp("width", width, int):
            return error

        # get "height"
        height = message.get("height")
        if error := assert_resp("height", height, int):
            return error

        # cap height and width
        width, height = cap_width_and_height(width, height)

        if is_save(media_id):
            file_name = get_video_name(message.get("id"), width, height)
            file = join(DATA_FOLDER, file_name)

            if not exists(file):
                if media_id.startswith("live-"):
                    return {
                        "action": "error",
                        "message": "Live video is not supported.",
                    }
                return {"action": "error", "message": "Video not found"}

            request.app.shared_ctx.data[file_name] = datetime.now()

            return {
                "action": "vid",
                "lines": await get_vid(file, tracker, MAX_WS_PAYLOAD_BYTES),
            }

        return {"action": "error", "message": "You dare not use special Characters"}

    @staticmethod
    async def handshake(message: dict, ws: Websocket, _request: Request):
        client_id = f"{id(ws):x}"
        client_version = message.get("client_version")
        if not client_version:
            return {
                "action": "error",
                "message": "Client version required",
            }
        if client_version != VERSION:
            return {
                "action": "error",
                "message": "Client version mismatch",
            }
        return {
            "action": "handshake",
            "server": {"version": VERSION},
            "api": {"version": VERSION},
            "client_id": client_id,
            "capabilities": {"video": ["32vid"], "audio": ["dfpwm"]},
        }

    # pylint: enable=missing-function-docstring


class CustomErrorHandler(ErrorHandler):
    """Error handler for sanic"""

    def default(self, request: Request, exception: Union[SanicException, Exception]):
        """handles errors that have no error handlers assigned"""

        if isinstance(exception, SanicException) and exception.status_code == 426:
            # TODO: Respond with nice html that tells the user how to install YC
            return text(
                "Your YC-Server-Fork is running correctly. Now all you need is the YC-Server-Client on your CC-Tweaked computer. "
                "See https://github.com/YC-Fork/YC-Client-Fork. "
            )

        return super().default(request, exception)


app = Sanic("YC-Fork-Server")
app.error_handler = CustomErrorHandler()
# FIXME: The Client is not Responsing to Websocket pings
app.config.WEBSOCKET_PING_INTERVAL = 0
# FIXME: Add UVLOOP support for alpine pypy
if getenv("SANIC_NO_UVLOOP"):
    app.config.USE_UVLOOP = False

app.config.TEMPLATING_PATH_TO_TEMPLATES = join(dirname(abspath(__file__)), 'web')

admin_config = config.get("admin_panel_web", {})
if admin_config.get("enabled", False):
    Extend(app, config={"templating": {"path_to_templates": join(dirname(abspath(__file__)), 'web')}})
    app.blueprint(admin_bp)


def ensure_live_stream_ctx(app: Sanic) -> Tuple[dict, Lock]:
    """Ensure live stream storage exists for the current process."""
    if not hasattr(app.ctx, "live_streams"):
        app.ctx.live_streams = {}
    if not hasattr(app.ctx, "live_streams_lock"):
        app.ctx.live_streams_lock = Lock()
    return app.ctx.live_streams, app.ctx.live_streams_lock


def ensure_ws_ctx(app: Sanic) -> Tuple[set, Lock]:
    """Ensure websocket tracking exists for the current process."""
    if not hasattr(app.ctx, "active_websockets"):
        app.ctx.active_websockets = set()
    if not hasattr(app.ctx, "active_websockets_lock"):
        app.ctx.active_websockets_lock = Lock()
    return app.ctx.active_websockets, app.ctx.active_websockets_lock


def ensure_ws_map_ctx(app: Sanic) -> Tuple[dict, Lock]:
    """Ensure websocket id map exists for the current process."""
    if not hasattr(app.ctx, "ws_by_id"):
        app.ctx.ws_by_id = {}
    if not hasattr(app.ctx, "ws_by_id_lock"):
        app.ctx.ws_by_id_lock = Lock()
    return app.ctx.ws_by_id, app.ctx.ws_by_id_lock


def get_shared_client_state(app: Sanic):
    """Returns shared client state map (main process creates it)."""
    if not hasattr(app.shared_ctx, "client_state"):
        return None
    return app.shared_ctx.client_state


def get_shared_kick_generation(app: Sanic):
    """Returns shared kick generation value (main process creates it)."""
    if not hasattr(app.shared_ctx, "kick_generation"):
        return None
    return app.shared_ctx.kick_generation


def get_shared_kick_targets(app: Sanic):
    """Returns shared kick targets map (main process creates it)."""
    if not hasattr(app.shared_ctx, "kick_targets"):
        return None
    return app.shared_ctx.kick_targets


def get_shared_debug_enabled(app: Sanic):
    """Returns shared debug enabled flag (main process creates it)."""
    if not hasattr(app.shared_ctx, "debug_enabled"):
        return None
    return app.shared_ctx.debug_enabled


def command_status(app: Sanic) -> None:
    client_state = get_shared_client_state(app)
    if client_state is None:
        logger.info("Status: unavailable (shared state not ready)")
        return
    items = list(client_state.values())
    ws_count = len(items)
    live_count = sum(1 for item in items if item.get("is_live"))
    logger.info("Status: %s active connections, %s live streams", ws_count, live_count)


def command_kick_all(app: Sanic) -> None:
    kick_generation = get_shared_kick_generation(app)
    if kick_generation is None:
        logger.warning("Kick-all failed: shared state not ready")
        return
    kick_generation.value += 1
    current = kick_generation.value
    logger.info("Kick-all issued (generation %s)", current)


def command_list_all(app: Sanic) -> None:
    client_state = get_shared_client_state(app)
    if client_state is None:
        logger.info("Clients: unavailable (shared state not ready)")
        return
    items = list(client_state.items())
    if not items:
        logger.info("Clients: none")
        return
    logger.info("Clients:")
    for client_id, state in items:
        media_id = state.get("media_id") or "-"
        mode = state.get("mode") or "unknown"
        title = state.get("title") or "-"
        ip = state.get("ip") or "-"
        url = state.get("url") or "-"
        listening_seconds = "-"
        started_at = state.get("listening_since")
        if isinstance(started_at, (int, float)):
            listening_seconds = f"{int(monotonic() - started_at)}s"
        logger.info(
            "  %s | %s | %s | %s | %s | %s | %s",
            client_id,
            ip,
            mode,
            media_id,
            title,
            url,
            listening_seconds,
        )


def kick_watcher(app: Sanic) -> None:
    kick_generation = get_shared_kick_generation(app)
    if kick_generation is None:
        return
    last_seen = kick_generation.value
    while True:
        sleep(0.5)
        current = kick_generation.value
        if current == last_seen:
            continue
        last_seen = current
        active_websockets, active_websockets_lock = ensure_ws_ctx(app)
        loop = getattr(app.ctx, "main_loop", None)
        if loop is None:
            continue
        with active_websockets_lock:
            sockets = list(active_websockets)
        for ws in sockets:
            try:
                run_coroutine_threadsafe(
                    ws.close(code=1000, reason="Server kick-all"), loop
                )
            except RuntimeError:
                logger.warning("Failed to kick websocket: loop not running")


def kick_target_watcher(app: Sanic) -> None:
    kick_targets = get_shared_kick_targets(app)
    if kick_targets is None:
        return
    while True:
        sleep(0.5)
        items = list(kick_targets.items())
        if not items:
            continue
        ws_by_id, ws_by_id_lock = ensure_ws_map_ctx(app)
        loop = getattr(app.ctx, "main_loop", None)
        if loop is None:
            continue
        now = monotonic()
        for client_id, stamp in items:
            with ws_by_id_lock:
                ws = ws_by_id.get(client_id)
            if ws is None:
                if isinstance(stamp, (int, float)) and now - stamp > 5:
                    kick_targets.pop(client_id, None)
                continue
            try:
                run_coroutine_threadsafe(
                    ws.close(code=1000, reason="Server kick"), loop
                )
            except RuntimeError:
                logger.warning("Failed to kick websocket: loop not running")
            kick_targets.pop(client_id, None)


def debug_watcher(app: Sanic) -> None:
    debug_enabled = get_shared_debug_enabled(app)
    if debug_enabled is None:
        return
    last_seen = debug_enabled.value
    while True:
        sleep(0.5)
        current = debug_enabled.value
        if current == last_seen:
            continue
        last_seen = current
        level = logging.DEBUG if current else logging.INFO
        logger.setLevel(level)
        for handler in logger.handlers:
            handler.setLevel(level)


def command_listener(app: Sanic) -> None:
    commands = {
        "status": command_status,
        "kick-all": command_kick_all,
        "kickall": command_kick_all,
        "list-all": command_list_all,
        "listall": command_list_all,
        "clear": None,
        "cls": None,
        "help": None,
    }
    # logger.info("Command listener ready: status, kick-all, kick, list-all, clear, debug, help")
    while True:
        try:
            line = sys.stdin.readline()
        except Exception:
            break
        if line == "":
            break
        cmd = line.strip().lower()
        if not cmd:
            continue
        if cmd == "help":
            logger.info(
                "Commands: status, kick-all, kick <id>, list-all, clear, debug, help"
            )
            continue
        if cmd in ("clear", "cls"):
            system("cls" if sys.platform.startswith("win") else "clear")
            continue
        if cmd.startswith("kick "):
            parts = cmd.split()
            if len(parts) != 2:
                logger.info("Usage: kick <client_id>")
                continue
            client_id = parts[1]
            kick_targets = get_shared_kick_targets(app)
            if kick_targets is None:
                logger.warning("Kick failed: shared state not ready")
                continue
            kick_targets[client_id] = monotonic()
            logger.info("Kick issued for %s", client_id)
            continue
        if cmd.startswith("debug"):
            parts = cmd.split()
            if len(parts) == 1:
                debug_enabled = get_shared_debug_enabled(app)
                if debug_enabled is None:
                    logger.info(
                        "Debug is %s", "on" if logger.level <= logging.DEBUG else "off"
                    )
                else:
                    logger.info(
                        "Debug is %s", "on" if debug_enabled.value else "off"
                    )
                continue
            if parts[1] in ("on", "true", "1"):
                debug_enabled = get_shared_debug_enabled(app)
                if debug_enabled is not None:
                    debug_enabled.value = 1
                logger.setLevel(logging.DEBUG)
                for handler in logger.handlers:
                    handler.setLevel(logging.DEBUG)
                logger.info("Debug logging enabled")
                continue
            if parts[1] in ("off", "false", "0"):
                debug_enabled = get_shared_debug_enabled(app)
                if debug_enabled is not None:
                    debug_enabled.value = 0
                logger.setLevel(logging.INFO)
                for handler in logger.handlers:
                    handler.setLevel(logging.INFO)
                logger.info("Debug logging disabled")
                continue
            logger.info("Usage: debug on|off")
            continue
        handler = commands.get(cmd)
        if handler is None:
            logger.info("Unknown command: %s", cmd)
            continue
        handler(app)


def stop_live_streams_for_client(app: Sanic, client_id: int) -> None:
    """Stops live streams that belong to a disconnected client."""
    live_streams, live_streams_lock = ensure_live_stream_ctx(app)
    with live_streams_lock:
        entries = list(live_streams.values())
    for entry in entries:
        clients = entry.get("clients") or set()
        if client_id not in clients:
            continue
        clients.discard(client_id)
        entry["clients"] = clients
        if not clients:
            entry["delete_on_end"] = True
            stop_event = entry.get("stop_event")
            if stop_event:
                stop_event.set()
            if entry.get("ended"):
                _remove_live_files(entry)
                with live_streams_lock:
                    live_streams.pop(entry.get("media_id"), None)

actions = {}

# add all actions from default action set
for method in dir(Actions):
    if not method.startswith("__"):
        actions[method] = getattr(Actions, method)


DATA_CACHE_CLEANUP_INTERVAL = int(getenv("DATA_CACHE_CLEANUP_INTERVAL", "300"))
DATA_CACHE_CLEANUP_AFTER = int(getenv("DATA_CACHE_CLEANUP_AFTER", "3600"))
LIVE_STREAM_CLEANUP_INTERVAL = int(getenv("LIVE_STREAM_CLEANUP_INTERVAL", "30"))
LIVE_STREAM_IDLE_TIMEOUT = int(getenv("LIVE_STREAM_IDLE_TIMEOUT", "300"))
LIVE_STREAM_POLL_INTERVAL = float(getenv("LIVE_STREAM_POLL_INTERVAL", "0.25"))
LIVE_STREAM_READ_TIMEOUT = float(getenv("LIVE_STREAM_READ_TIMEOUT", "60"))
MAX_WS_PAYLOAD_BYTES = int(getenv("MAX_WS_PAYLOAD_BYTES", "60000"))


def data_cache_cleaner(data: dict):
    """
    Checks for outdated cache entries every DATA_CACHE_CLEANUP_INTERVAL (default 300) Seconds and
    deletes them if they have not been used for DATA_CACHE_CLEANUP_AFTER (default 3600) Seconds.
    """
    try:
        while True:
            sleep(DATA_CACHE_CLEANUP_INTERVAL)
            for file_name, last_used in data.items():
                if (
                    datetime.now() - last_used
                ).total_seconds() > DATA_CACHE_CLEANUP_AFTER:
                    file_path = join(DATA_FOLDER, file_name)
                    if exists(file_path):
                        remove(file_path)
                        logger.debug('Deleted "%s"', file_name)
                    data.pop(file_name)

    except KeyboardInterrupt:
        pass

def print_startup_banner(admin_enabled: bool):
    """Prints a startup banner with component status."""
    if NO_COLOR:
        border = "=" * 40
        title = "YC-Fork Server"
    else:
        border = f"{Foreground.BRIGHT_BLUE}{'=' * 40}{RESET}"
        title = f"{Foreground.BRIGHT_CYAN}YC-Fork Server{RESET}"

    logger.info(border)
    logger.info(f" {title} v{VERSION}")
    logger.info(border)
    
    # Components
    components = []
    
    # Spotipy
    if spotipy:
        components.append(("Spotipy", "Enabled", Foreground.GREEN))
    else:
        components.append(("Spotipy", "Disabled", Foreground.RED))
        
    # Admin Panel
    if admin_enabled:
        components.append(("Admin Panel", "Enabled (/admin)", Foreground.GREEN))
    else:
        components.append(("Admin Panel", "Disabled", Foreground.RED))
        
    # Commands
    components.append(("Commands", "Enabled", Foreground.GREEN))

    for name, status, color in components:
        if NO_COLOR:
            logger.info(f" {name:<15} : {status}")
        else:
            logger.info(f" {name:<15} : {color}{status}{RESET}")
            
    logger.info(border)

# pylint: disable=redefined-outer-name
@app.main_process_ready
async def ready(app: Sanic):
    """See https://sanic.dev/en/guide/basics/listeners.html"""
    if DATA_CACHE_CLEANUP_INTERVAL > 0 and DATA_CACHE_CLEANUP_AFTER > 0:
        app.manager.manage(
            "Data-Cache-Cleaner", data_cache_cleaner, {"data": app.shared_ctx.data}
        )
    if LIVE_STREAM_CLEANUP_INTERVAL > 0 and LIVE_STREAM_IDLE_TIMEOUT > 0:
        Thread(
            target=live_stream_cleaner,
            args=(app.ctx.live_streams, app.ctx.live_streams_lock),
            daemon=True,
        ).start()


@app.main_process_start
async def main_start(app: Sanic):
    """See https://sanic.dev/en/guide/basics/listeners.html"""
    manager = Manager()
    app.shared_ctx.data = manager.dict()
    app.shared_ctx.client_state = manager.dict()
    app.shared_ctx.kick_generation = manager.Value("i", 0)
    app.shared_ctx.kick_targets = manager.dict()
    config = load_config()
    debug_default = bool(config.get("debug_logging_default", False))
    app.shared_ctx.debug_enabled = manager.Value("i", 1 if debug_default else 0)
    ensure_live_stream_ctx(app)

    if which(FFMPEG_PATH) is None:
        logger.warning("FFmpeg not found.")

    if which(SANJUUNI_PATH) is None:
        logger.warning("Sanjuuni not found.")

    admin_config = config.get("admin_panel_web", {})
    print_startup_banner(admin_config.get("enabled", False))

    if not sys.stdin.closed:
        Thread(target=command_listener, args=(app,), daemon=True).start()


@app.before_server_start
async def before_start(app: Sanic):
    warnings.filterwarnings(
        "ignore",
        message=r".*Passing the loop argument to listeners is deprecated",
        category=DeprecationWarning,
        module="sanic.logging.deprecation"
    )
    ensure_ws_ctx(app)
    ensure_ws_map_ctx(app)
    app.ctx.main_loop = get_event_loop()
    debug_enabled = get_shared_debug_enabled(app)
    if debug_enabled is not None:
        level = logging.DEBUG if debug_enabled.value else logging.INFO
        logger.setLevel(level)
        for handler in logger.handlers:
            handler.setLevel(level)
    Thread(target=kick_watcher, args=(app,), daemon=True).start()
    Thread(target=kick_target_watcher, args=(app,), daemon=True).start()
    Thread(target=debug_watcher, args=(app,), daemon=True).start()


@app.route("/dfpwm/<media_id:str>/<chunkindex:int>")
async def stream_dfpwm(_request: Request, media_id: str, chunkindex: int):
    """WIP HTTP mode"""
    return raw(await getchunk(join(DATA_FOLDER, get_audio_name(media_id)), chunkindex))


@app.route("/32vid/<media_id:str>/<width:int>/<height:int>/<tracker:int>")  # , stream=True
async def stream_32vid(
    _request: Request, media_id: str, width: int, height: int, tracker: int
):
    """WIP HTTP mode"""
    return raw(
        "\n".join(
            await get_vid(
                join(DATA_FOLDER, get_video_name(media_id, width, height)),
                tracker,
                MAX_WS_PAYLOAD_BYTES,
            )
        )
    )


""""
from sanic import response
@app.route("/dfpwm/<id:str>")
async def stream_dfpwm(request: Request, id: str):
    file_name = get_audio_name(id)
    file = join(DATA_FOLDER, get_audio_name(id))
    return await response.file_stream(
        file,
        chunk_size=CHUNKS_AT_ONCE,
        mime_type="application/metalink4+xml",
        headers={
            "Content-Disposition": f'Attachment; filename="{file_name}"',
            "Content-Type": "application/metalink4+xml",
        },
    )

@app.route("/32vid/<id:str>/<width:int>/<height:int>", stream=True)
async def stream_32vid(request: Request, id: str, width: int, height: int):
    file_name = get_video_name(id, width, height)
    file = join(
        DATA_FOLDER,
        file_name
    )
    return await response.file_stream(
        file,
        chunk_size=10,
        mime_type="application/metalink4+xml",
        headers={
            "Content-Disposition": f'Attachment; filename="{file_name}"',
            "Content-Type": "application/metalink4+xml",
        },
    )
"""
# pylint: enable=redefined-outer-name


@app.websocket("/")
# pylint: disable-next=invalid-name
async def wshandler(request: Request, ws: Websocket):
    """Handels web-socket requests"""
    client_id = f"{id(ws):x}"
    if NO_COLOR:
        prefix = f"[{request.client_ip}-{client_id}] "
    else:
        prefix = f"{Foreground.BLUE}[{request.client_ip}-{client_id}]{RESET} "

    logger.info("%sConnected!", prefix)

    logger.debug("%sMy headers are: %s", prefix, request.headers)

    active_websockets, active_websockets_lock = ensure_ws_ctx(request.app)
    client_state = get_shared_client_state(request.app)
    ws_by_id, ws_by_id_lock = ensure_ws_map_ctx(request.app)
    with active_websockets_lock:
        active_websockets.add(ws)
    with ws_by_id_lock:
        ws_by_id[client_id] = ws
    if client_state is not None:
        client_state[client_id] = {
            "mode": "idle",
            "media_id": None,
            "title": None,
            "is_live": False,
            "ip": request.client_ip,
            "listening_since": None,
        }

    try:
        while True:
            message = await ws.recv()
            if message is None:
                break
            logger.debug("%sMessage: %s", prefix, message)

            try:
                message: dict = load_json(message)
            except JSONDecodeError:
                logger.debug("%sFaild to parse Json", prefix)
                await ws.send(dumps({"action": "error", "message": "Faild to parse Json"}))
                continue

            if message.get("action") in actions:
                response = await actions[message.get("action")](message, ws, request)
                await ws.send(dumps(response))
                if (
                    message.get("action") == "handshake"
                    and response.get("action") == "error"
                ):
                    await ws.close()
    finally:
        with active_websockets_lock:
            active_websockets.discard(ws)
        with ws_by_id_lock:
            ws_by_id.pop(client_id, None)
        if client_state is not None:
            client_state.pop(client_id, None)
        stop_live_streams_for_client(request.app, id(ws))
        logger.info("%sDisconnected!", prefix)


def main() -> None:
    """
    Run all needed services
    """
    port = int(getenv("PORT", "5000"))
    host = getenv("HOST", "0.0.0.0")
    fast = not getenv("NO_FAST")

    app.run(host=host, port=port, fast=fast, access_log=True)


if __name__ == "__main__":
    main()
