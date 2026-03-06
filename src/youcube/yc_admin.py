#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Admin Panel for YC-Server-Fork
"""

from asyncio import sleep
from datetime import datetime
from functools import wraps
from os import getenv
from time import monotonic
from typing import Optional

from sanic import Blueprint, Request, response
from sanic.exceptions import Unauthorized
from sanic_ext import render

from yc_utils import load_config

admin_bp = Blueprint("admin", url_prefix="/admin")

AUTH_COOKIE_NAME = "ycf_admin_auth"
AUTH_COOKIE_VALUE = "authenticated"

def check_auth(request: Request) -> bool:
    """Checks if the user is authenticated via cookie."""
    return request.cookies.get(AUTH_COOKIE_NAME) == AUTH_COOKIE_VALUE

def login_required(wrapped):
    """Decorator to require login for admin routes."""
    def decorator(f):
        @wraps(f)
        async def decorated_function(request: Request, *args, **kwargs):
            if not check_auth(request):
                return response.redirect("/admin/login")
            return await f(request, *args, **kwargs)
        return decorated_function
    return decorator(wrapped)

@admin_bp.route("/login", methods=["GET", "POST"])
async def login(request: Request):
    """Handles admin login."""
    if request.method == "POST":
        password = request.form.get("password")
        config = load_config()
        admin_config = config.get("admin_panel_web", {})
        admin_password = admin_config.get("password") or getenv("ADMIN_PASSWORD")
        
        if not admin_password:
             return await render(
                "login.html", 
                context={"error": "Admin password not configured on server."}, 
                status=500
            )

        if password == admin_password:
            resp = response.redirect("/admin")
            resp.add_cookie(
                AUTH_COOKIE_NAME,
                AUTH_COOKIE_VALUE,
                httponly=True,
                path="/admin",
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
    resp = response.redirect("/admin/login")
    resp.delete_cookie(AUTH_COOKIE_NAME, path="/admin")
    return resp

@admin_bp.route("/")
@login_required
async def dashboard(request: Request):
    """Renders the admin dashboard."""
    client_state = request.app.shared_ctx.client_state
    clients = []
    
    if client_state:
        for client_id, state in client_state.items():
            listening_since = state.get("listening_since")
            duration = "-"
            if isinstance(listening_since, (int, float)):
                duration = f"{int(monotonic() - listening_since)}s"
                
            clients.append({
                "id": client_id,
                "ip": state.get("ip", "-"),
                "mode": state.get("mode", "unknown"),
                "media_id": state.get("media_id", "-"),
                "title": state.get("title", "-"),
                "url": state.get("url", "-"),
                "duration": duration,
                "is_live": state.get("is_live", False)
            })
            
    return await render("dashboard.html", context={"clients": clients})

@admin_bp.route("/kick/<client_id>")
@login_required
async def kick_client(request: Request, client_id: str):
    """Kicks a specific client."""
    kick_targets = request.app.shared_ctx.kick_targets
    if kick_targets is not None:
        kick_targets[client_id] = monotonic()
    return response.redirect("/admin")

@admin_bp.route("/kick-all")
@login_required
async def kick_all(request: Request):
    """Kicks all clients."""
    kick_generation = request.app.shared_ctx.kick_generation
    if kick_generation is not None:
        kick_generation.value += 1
    return response.redirect("/admin")
