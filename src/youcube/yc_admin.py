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

def get_formatted_clients(client_state) -> list:
    """Helper to format the client state dictionary into a list."""
    clients = []
    if client_state:
        now = monotonic()
        for client_id, state in client_state.items():
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

            clients.append({
                "id": client_id,
                "ip": state.get("ip", "-"),
                "mode": state.get("mode", "unknown"),
                "status": state.get("status", "Idle"),
                "media_id": state.get("media_id", "-"),
                "title": state.get("title", "-"),
                "url": state.get("url", ""),
                "play_duration": play_duration,
                "conn_duration": conn_duration,
                "is_live": state.get("is_live", False)
            })
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
    clients = get_formatted_clients(client_state)
    
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
            clients = get_formatted_clients(client_state)
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
