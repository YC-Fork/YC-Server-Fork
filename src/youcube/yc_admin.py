#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Admin Panel for YC-Server-Fork
"""

from asyncio import sleep, get_event_loop
from datetime import datetime
from functools import wraps
from os import getenv
from time import monotonic
from typing import Optional
import json
import urllib.request

from sanic import Blueprint, Request, response, Websocket
from sanic.exceptions import WebsocketClosed
from sanic_ext import render

from yc_utils import load_config, VERSION

admin_bp = Blueprint("admin", url_prefix="/admin")

AUTH_COOKIE_NAME = "ycf_admin_auth"
AUTH_COOKIE_VALUE = "authenticated"
VERSION_URL = "https://raw.githubusercontent.com/YC-Fork/YC-Server-Fork/main/versions.json"

def check_auth(request: Request) -> bool:
    """Checks if the user is authenticated via cookie."""
    return request.cookies.get(AUTH_COOKIE_NAME) == AUTH_COOKIE_VALUE

def login_required(wrapped):
    """Decorator to require login for admin routes."""
    def decorator(f):
        @wraps(f)
        async def decorated_function(request: Request, *args, **kwargs):
            if not check_auth(request):
                if request.path.endswith("/ws"): # For websockets, just close
                    return
                prefix = request.app.blueprints["admin"].url_prefix
                return response.redirect(f"{prefix}/login")
            return await f(request, *args, **kwargs)
        return decorated_function
    return decorator(wrapped)

def format_duration(seconds: float) -> str:
    """Formats seconds into a readable string (e.g., 1h 2m 3s)."""
    if not seconds:
        return "-"
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

def determine_media_type(state: dict) -> str:
    """Derives media type: Video, Audio, Stream, Radio, or -."""
    if not state or state.get("status") == "Idle" or state.get("mode") in ("idle", "unknown", None):
        return "-"
    is_live = state.get("is_live", False)
    mode = state.get("mode", "")
    title = (state.get("title") or "").lower()
    url = (state.get("url") or "").lower()

    if is_live:
        if mode == "audio" or "radio" in title or "radio" in url or url.endswith(".pls") or url.endswith(".m3u"):
            return "Radio"
        return "Stream"
    
    if mode == "audio+video" or mode == "video":
        return "Video"
    
    return "Audio"

def get_formatted_clients(client_state, app=None) -> list:
    """Helper to format the client state dictionary into a list and purge disconnected clients."""
    clients = []
    if client_state:
        ws_by_id = None
        if app:
            ws_by_id = getattr(app.ctx, "ws_by_id", None) or getattr(app.shared_ctx, "ws_by_id", None)

        now = monotonic()
        stale_keys = []
        for client_id, state in list(client_state.items()):
            if ws_by_id is not None and client_id not in ws_by_id:
                stale_keys.append(client_id)
                continue

            # Play Duration
            listening_since = state.get("listening_since")
            play_duration = "-"
            if isinstance(listening_since, (int, float)):
                play_duration = format_duration(now - listening_since)
            
            # Connection Duration
            connected_since = state.get("connected_since")
            conn_duration = "-"
            if isinstance(connected_since, (int, float)):
                conn_duration = format_duration(now - connected_since)

            elapsed = (now - listening_since) if isinstance(listening_since, (int, float)) else 0.0
            duration = state.get("duration", 0)

            clients.append({
                "id": client_id,
                "ip": state.get("ip", "-"),
                "mode": state.get("mode", "unknown"),
                "type": determine_media_type(state),
                "status": state.get("status", "Idle"),
                "media_id": state.get("media_id", "-"),
                "title": state.get("title", "-"),
                "url": state.get("url", ""),
                "play_duration": play_duration,
                "conn_duration": conn_duration,
                "nickname": state.get("nickname", ""),
                "is_live": state.get("is_live", False),
                "volume": state.get("volume", 3.0),
                "duration": duration,
                "elapsed": elapsed
            })

        for k in stale_keys:
            client_state.pop(k, None)

    return clients

def fetch_latest_version():
    """Fetches the latest version from GitHub."""
    try:
        with urllib.request.urlopen(VERSION_URL, timeout=5) as url:
            data = json.loads(url.read().decode())
            return data.get("latest")
    except Exception:
        return None

@admin_bp.route("/login", methods=["GET", "POST"])
async def login(request: Request):
    """Handles admin login."""
    if request.method == "POST":
        password = request.form.get("password")
        config = load_config()
        server_settings = config.get("server_settings", {}) if isinstance(config, dict) else {}
        admin_config = server_settings.get("admin_panel_web", {})
        admin_password = admin_config.get("password") or getenv("ADMIN_PASSWORD")
        
        if not admin_password:
             return await render(
                "login.html", 
                context={"error": "Admin password not configured on server."}, 
                status=500
            )

        if password == admin_password:
            prefix = request.app.blueprints["admin"].url_prefix
            resp = response.redirect(prefix)
            resp.add_cookie(
                AUTH_COOKIE_NAME,
                AUTH_COOKIE_VALUE,
                httponly=True,
                path=prefix,
            )
            return resp
        
        return await render(
            "login.html", 
            context={"error": "Invalid password"}
        )
        
    return await render("login.html", context={"error": None})

@admin_bp.route("/logout")
async def logout(request: Request):
    """Logs out the admin."""
    prefix = request.app.blueprints["admin"].url_prefix
    resp = response.redirect(f"{prefix}/login")
    resp.delete_cookie(AUTH_COOKIE_NAME, path=prefix)
    return resp

@admin_bp.route("/")
@login_required
async def dashboard(request: Request):
    """Renders the admin dashboard."""
    client_state = request.app.shared_ctx.client_state
    clients = get_formatted_clients(client_state, request.app)
    
    loop = get_event_loop()
    latest_version = await loop.run_in_executor(None, fetch_latest_version)
    
    return await render("dashboard.html", context={
        "clients": clients,
        "current_version": VERSION,
        "latest_version": latest_version,
        "admin_prefix": request.app.blueprints["admin"].url_prefix
    })

@admin_bp.websocket("/ws")
@login_required
async def admin_feed(request: Request, ws: Websocket):
    """Provides a live feed of client status to the admin dashboard."""
    try:
        while True:
            client_state = request.app.shared_ctx.client_state
            clients = get_formatted_clients(client_state, request.app)
            await ws.send(json.dumps(clients))
            await sleep(2)
    except WebsocketClosed:
        pass

@admin_bp.route("/kick/<client_id>")
@login_required
async def kick_client(request: Request, client_id: str):
    """Kicks a specific client."""
    kick_targets = request.app.shared_ctx.kick_targets
    if kick_targets is not None:
        kick_targets[client_id] = monotonic()
    prefix = request.app.blueprints["admin"].url_prefix
    return response.redirect(prefix)

@admin_bp.route("/kick-all")
@login_required
async def kick_all(request: Request):
    """Kicks all clients."""
    kick_generation = request.app.shared_ctx.kick_generation
    if kick_generation is not None:
        kick_generation.value += 1
    prefix = request.app.blueprints["admin"].url_prefix
    return response.redirect(prefix)

@admin_bp.route("/play/<client_id>", methods=["POST", "GET"])
@login_required
async def play_to_client(request: Request, client_id: str):
    """Queues a song for a specific client and notifies them if they are idle."""
    url = request.args.get("url") or request.form.get("url")
    no_video = (request.args.get("no_video") == "true") or (request.form.get("no_video") == "true")
    if url:
        queues = request.app.shared_ctx.client_queues
        if queues is not None:
            client_queue = list(queues.get(client_id, []))
            client_queue.append((url, no_video))
            queues[client_id] = client_queue
            
            from yc_logging import logger
            logger.info("Queued play command for client %s: %s (no_video=%s)", client_id, url, no_video)
            
            # If the client is idle, it will retrieve it via the 2-second polling loop
            pass

    prefix = request.app.blueprints["admin"].url_prefix
    return response.redirect(prefix)

@admin_bp.route("/stop/<client_id>")
@login_required
async def stop_client(request: Request, client_id: str):
    """Sends a stop command to a specific client by setting a shared stop signal and pushing directly via WS."""
    from yc_logging import logger

    # 1. Clear queue so client doesn't start next track
    client_queues = getattr(request.app.shared_ctx, "client_queues", None)
    if client_queues is not None and client_id in client_queues:
        client_queues[client_id] = []

    # 2. Update status immediately so dashboard reflects feedback
    client_state = getattr(request.app.shared_ctx, "client_state", None)
    if client_state and client_id in client_state:
        state = client_state[client_id]
        state["status"] = "Stopping..."
        state["mode"] = "idle"
        client_state[client_id] = state

    # 3. Set signal fallback
    stop_signals = getattr(request.app.shared_ctx, "stop_signals", None)
    if stop_signals is not None:
        stop_signals[client_id] = True
        logger.info("Set stop signal for client %s", client_id)

    # 4. Direct instantaneous WS push if client is connected (check app.ctx.ws_by_id first)
    ws_by_id = getattr(request.app.ctx, "ws_by_id", None) or getattr(request.app.shared_ctx, "ws_by_id", None)
    if ws_by_id and client_id in ws_by_id:
        try:
            ws = ws_by_id[client_id]
            await ws.send(json.dumps({"action": "stop"}))
            logger.info("Directly pushed stop action to client %s via WS", client_id)
        except Exception as e:
            logger.warning("Failed direct WS stop push to %s: %s", client_id, e)

    if request.headers.get("accept") == "application/json" or request.args.get("json") == "true":
        return response.json({"status": "success"})
    prefix = request.app.blueprints["admin"].url_prefix
    return response.redirect(prefix)

@admin_bp.route("/skip/<client_id>")
@login_required
async def skip_client(request: Request, client_id: str):
    """Sends a skip command to a specific client."""
    from yc_logging import logger

    # 1. Update status immediately so dashboard reflects feedback
    client_state = getattr(request.app.shared_ctx, "client_state", None)
    if client_state and client_id in client_state:
        state = client_state[client_id]
        state["status"] = "Skipping..."
        client_state[client_id] = state

    # 2. Set signal fallback
    skip_signals = getattr(request.app.shared_ctx, "skip_signals", None)
    if skip_signals is not None:
        skip_signals[client_id] = True
        logger.info("Set skip signal for client %s", client_id)

    # 3. Direct instantaneous WS push if client is connected (check app.ctx.ws_by_id first)
    ws_by_id = getattr(request.app.ctx, "ws_by_id", None) or getattr(request.app.shared_ctx, "ws_by_id", None)
    if ws_by_id and client_id in ws_by_id:
        try:
            ws = ws_by_id[client_id]
            await ws.send(json.dumps({"action": "skip"}))
            logger.info("Directly pushed skip action to client %s via WS", client_id)
        except Exception as e:
            logger.warning("Failed direct WS skip push to %s: %s", client_id, e)

    if request.headers.get("accept") == "application/json" or request.args.get("json") == "true":
        return response.json({"status": "success"})
    prefix = request.app.blueprints["admin"].url_prefix
    return response.redirect(prefix)

@admin_bp.route("/restart/<client_id>")
@login_required
async def restart_client(request: Request, client_id: str):
    """Sends a restart command to a specific client to restart current media from 0:00."""
    from yc_logging import logger

    client_state = getattr(request.app.shared_ctx, "client_state", None)
    if client_state and client_id in client_state:
        state = client_state[client_id]
        state["status"] = "Restarting..."
        state["listening_since"] = monotonic()
        client_state[client_id] = state

    restart_signals = getattr(request.app.shared_ctx, "restart_signals", None)
    if restart_signals is not None:
        restart_signals[client_id] = True

    ws_by_id = getattr(request.app.ctx, "ws_by_id", None) or getattr(request.app.shared_ctx, "ws_by_id", None)
    if ws_by_id and client_id in ws_by_id:
        try:
            ws = ws_by_id[client_id]
            await ws.send(json.dumps({"action": "restart"}))
            logger.info("Directly pushed restart action to client %s via WS", client_id)
        except Exception as e:
            logger.warning("Failed direct WS restart push to %s: %s", client_id, e)

    if request.headers.get("accept") == "application/json" or request.args.get("json") == "true":
        return response.json({"status": "success"})
    prefix = request.app.blueprints["admin"].url_prefix
    return response.redirect(prefix)

@admin_bp.route("/seek/<client_id>/<timestamp:float>")
@login_required
async def seek_client(request: Request, client_id: str, timestamp: float):
    """Sends a seek command to a specific client to jump to target timestamp (seconds)."""
    from yc_logging import logger

    client_state = getattr(request.app.shared_ctx, "client_state", None)
    if client_state and client_id in client_state:
        state = client_state[client_id]
        if state.get("is_live", False):
            return response.json({"status": "error", "message": "Live streams cannot be seeked"}, status=400)
        
        # Update listening_since to match new seek timestamp
        state["listening_since"] = monotonic() - max(0.0, timestamp)
        client_state[client_id] = state

    # Direct WS push to client
    ws_by_id = getattr(request.app.ctx, "ws_by_id", None) or getattr(request.app.shared_ctx, "ws_by_id", None)
    if ws_by_id and client_id in ws_by_id:
        try:
            ws = ws_by_id[client_id]
            await ws.send(json.dumps({"action": "seek", "timestamp": max(0.0, timestamp)}))
            logger.info("Directly pushed seek action (timestamp=%.1f) to client %s via WS", timestamp, client_id)
        except Exception as e:
            logger.warning("Failed direct WS seek push to %s: %s", client_id, e)

    return response.json({"status": "success", "timestamp": max(0.0, timestamp)})

@admin_bp.route("/queue/<client_id>")
@login_required
async def get_client_queue(request: Request, client_id: str):
    """Returns the current queue of media items for a specific client as JSON."""
    queues = request.app.shared_ctx.client_queues
    client_queue = []
    if queues is not None and client_id in queues:
        raw_queue = queues[client_id]
        for i, item in enumerate(raw_queue):
            if isinstance(item, (tuple, list)):
                url, no_video = item[0], item[1]
            else:
                url, no_video = item, False
            client_queue.append({"index": i, "url": url, "no_video": no_video})
    return response.json(client_queue)

@admin_bp.route("/queue/<client_id>/delete/<index:int>", methods=["POST", "GET"])
@login_required
async def delete_queue_item(request: Request, client_id: str, index: int):
    """Deletes an item from the client's queue by its index."""
    queues = request.app.shared_ctx.client_queues
    if queues is not None and client_id in queues:
        client_queue = list(queues[client_id])
        if 0 <= index < len(client_queue):
            client_queue.pop(index)
            queues[client_id] = client_queue
            
    if request.headers.get("accept") == "application/json" or request.args.get("json") == "true":
        return response.json({"status": "success"})
        
    prefix = request.app.blueprints["admin"].url_prefix
    return response.redirect(prefix)


@admin_bp.route("/volume/<client_id>", methods=["POST", "GET"])
@login_required
async def set_client_volume(request: Request, client_id: str):
    """Sets the volume for a specific client (0.0 – 3.0)."""
    volume = request.args.get("volume") or (request.json or {}).get("volume")
    if volume is None:
        return response.json({"status": "error", "message": "volume required"}, status=400)
    try:
        volume = float(volume)
        volume = max(0.0, min(3.0, volume))
    except (TypeError, ValueError):
        return response.json({"status": "error", "message": "volume must be a number"}, status=400)

    # Store in a shared volume_signals dict — picked up by get_chunk next request
    volume_signals = getattr(request.app.shared_ctx, "volume_signals", None)
    if volume_signals is not None:
        volume_signals[client_id] = volume
        from yc_logging import logger
        logger.info("Set volume signal for client %s to %.2f", client_id, volume)

    # Immediately update client_state so the dashboard stays in sync
    client_state = getattr(request.app.shared_ctx, "client_state", None)
    if client_state and client_id in client_state:
        state = client_state[client_id]
        state["volume"] = volume
        client_state[client_id] = state

    if request.headers.get("accept") == "application/json" or request.args.get("json") == "true":
        return response.json({"status": "success", "volume": volume})
    prefix = request.app.blueprints["admin"].url_prefix
    return response.redirect(prefix)

