# -*- coding: utf-8 -*-
"""
HTTP-обработчик для раздачи автономной панели CRUD (Svelte 5 + Tailwind v4).
Раздает статические файлы из папки static/ по маршрутам /crud (или /admin)
и обеспечивает строгую изоляцию через страницу входа /crud/login.
"""

import mimetypes
from pathlib import Path
from urllib.parse import parse_qs

from rsgi_wsrpc.core.router import http_route
from rsgi_wsrpc.core.http import extract_header
from .auth import (
    get_crud_session,
    authenticate_admin,
    create_crud_session,
    revoke_crud_session,
    render_login_html,
)

STATIC_DIR = Path(__file__).parent / "static"


def _extract_crud_token(scope) -> str:
    raw_cookie = extract_header(scope, "cookie", "")
    if not raw_cookie:
        return ""
    for part in raw_cookie.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            if k in ("rsgi_crud_session", "rsgi_session"):
                return v
    return ""


@http_route("/crud", methods=["GET", "POST"])
@http_route("/crud/*", methods=["GET", "POST"])
@http_route("/admin", methods=["GET", "POST"])
@http_route("/admin/*", methods=["GET", "POST"])
async def serve_crud_static(scope, proto) -> None:
    """
    Раздает автономную сборку админки из папки static/.
    Авторизует администратора через /crud/login и защищает /crud/ от гостей.
    """
    path = getattr(scope, "path", "/crud")
    method = getattr(scope, "method", "GET").upper()

    if path in ("/crud", "/admin"):
        target_redirect = f"{path}/"
        proto.response_str(
            status=307,
            headers=[
                ("location", target_redirect),
                ("content-length", "0"),
            ],
            body=""
        )
        return

    prefix = "/crud/" if path.startswith("/crud/") else "/admin/"
    subpath = path[len(prefix):] if path.startswith(prefix) else ""
    token = _extract_crud_token(scope)
    session_data = get_crud_session(token) if token else None
    is_admin = bool(session_data and session_data.get("role") in ("admin", "ADMIN"))

    # --- 1. МАРШРУТ /crud/login ---
    if subpath == "login":
        if method == "GET":
            if is_admin:
                proto.response_str(
                    status=307,
                    headers=[("location", prefix), ("content-length", "0")],
                    body=""
                )
                return
            html = render_login_html(base_path=prefix)
            proto.response_str(
                status=200,
                headers=[("content-type", "text/html; charset=utf-8"), ("cache-control", "no-cache")],
                body=html
            )
            return

        elif method == "POST":
            # Чтение тела запроса RSGI
            body_bytes = b""
            if hasattr(proto, "read"):
                b = await proto.read()
                body_bytes = b if isinstance(b, bytes) else str(b).encode("utf-8")
            else:
                chunks = []
                while True:
                    if hasattr(proto, "receive_bytes"):
                        c = await proto.receive_bytes()
                    elif hasattr(proto, "receive"):
                        m = await proto.receive()
                        c = m if isinstance(m, bytes) else (m.get("body", b"") if isinstance(m, dict) else b"")
                    else:
                        c = b""
                    if not c:
                        break
                    chunks.append(c)
                body_bytes = b"".join(chunks)

            parsed = parse_qs(body_bytes.decode("utf-8", errors="replace"))
            uname = parsed.get("username", [""])[0]
            passwd = parsed.get("password", [""])[0]

            user_info = await authenticate_admin(uname, passwd)
            if user_info and user_info.get("role") in ("admin", "ADMIN"):
                new_token = create_crud_session(user_info)
                proto.response_str(
                    status=303,
                    headers=[
                        ("location", prefix),
                        ("set-cookie", f"rsgi_crud_session={new_token}; Path=/; HttpOnly; SameSite=Lax"),
                        ("content-length", "0"),
                    ],
                    body=""
                )
                return
            else:
                html = render_login_html(
                    error_message="Неверный логин или пароль администратора.",
                    base_path=prefix
                )
                proto.response_str(
                    status=200,
                    headers=[("content-type", "text/html; charset=utf-8"), ("cache-control", "no-cache")],
                    body=html
                )
                return

    # --- 2. МАРШРУТ /crud/logout ---
    if subpath == "logout":
        if token:
            revoke_crud_session(token)
        proto.response_str(
            status=303,
            headers=[
                ("location", f"{prefix}login"),
                ("set-cookie", "rsgi_crud_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT"),
                ("content-length", "0"),
            ],
            body=""
        )
        return

    # --- 3. СТАТИЧЕСКИЕ РЕСУРСЫ И КОРНЕВОЙ ИНТЕРФЕЙС ---
    is_root_app = not subpath or subpath == "index.html"

    # Если не авторизован как админ и запрашивает корень админки -> редирект на /crud/login
    if is_root_app and not is_admin:
        proto.response_str(
            status=307,
            headers=[
                ("location", f"{prefix}login"),
                ("content-length", "0"),
            ],
            body=""
        )
        return

    target_file = STATIC_DIR / "index.html" if is_root_app else (STATIC_DIR / subpath).resolve()

    # Path traversal защита
    try:
        resolved_static = STATIC_DIR.resolve()
        target_resolved = target_file.resolve()
        if not str(target_resolved).startswith(str(resolved_static)):
            proto.response_str(
                status=403,
                headers=[("content-type", "text/plain; charset=utf-8")],
                body="403 Forbidden"
            )
            return
    except Exception:
        proto.response_str(
            status=400,
            headers=[("content-type", "text/plain; charset=utf-8")],
            body="400 Bad Request"
        )
        return

    if not target_resolved.is_file():
        proto.response_str(
            status=404,
            headers=[("content-type", "text/plain; charset=utf-8")],
            body="404 Not Found"
        )
        return

    content_type, _ = mimetypes.guess_type(str(target_resolved))
    if not content_type:
        content_type = "application/octet-stream"
    if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
        content_type += "; charset=utf-8"

    cache_control = "no-cache" if target_resolved.name == "index.html" else "public, max-age=31536000, immutable"

    proto.response_file(
        status=200,
        headers=[
            ("content-type", content_type),
            ("cache-control", cache_control),
        ],
        file=str(target_resolved)
    )
