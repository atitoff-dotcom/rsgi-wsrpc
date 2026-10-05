# -*- coding: utf-8 -*-
"""
HTTP-обработчик для раздачи автономной панели CRUD (Svelte 5 + Tailwind v4).
Раздает статические файлы из папки static/ по маршрутам /crud (или /admin).
"""

import mimetypes
from pathlib import Path
from rsgi_wsrpc.core.router import http_route

STATIC_DIR = Path(__file__).parent / "static"


@http_route("/crud", methods=["GET"])
@http_route("/crud/*", methods=["GET"])
@http_route("/admin", methods=["GET"])
@http_route("/admin/*", methods=["GET"])
async def serve_crud_static(scope, proto) -> None:
    """
    Раздает автономную сборку админки из папки static/.
    При обращении к /crud или /admin делает редирект на /crud/ или /admin/.
    """
    path = scope.path

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
    if not subpath or subpath == "index.html":
        target_file = STATIC_DIR / "index.html"
    else:
        target_file = (STATIC_DIR / subpath).resolve()

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
