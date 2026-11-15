"""Serving the built frontend from the same server as the API.

In development Vite serves the pages and proxies the API. In production there
is one server: this module hands out the files of the built site and falls
back to its index.html for the app's own addresses (/teach, /class/ABC123, ...),
which exist only inside the page.

Every answer carries the two headers that make the page "cross-origin
isolated". The Python runner needs that for input(); see frontend/vite.config.ts.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

ISOLATION = {
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
}

# Not every system's list of file types knows these three.
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/manifest+json", ".webmanifest")

FOREVER = "public, max-age=31536000, immutable"  # file names under /assets/ change when their contents do
A_WEEK = "public, max-age=604800"
ALWAYS_ASK = "no-cache"  # the page and the service worker: a new deploy must show at the next load


def find(site: Path, path: str) -> tuple[Path, str] | None:
    """The file to send for a request path, with its caching rule, or None for a 404."""
    if path.startswith(("api/", "ws/")):
        return None  # a mistyped API address is an error, not a page
    root = site.resolve()
    wanted = (root / path).resolve()
    if path and wanted.is_file() and wanted.is_relative_to(root):
        if path.startswith("assets/"):
            return wanted, FOREVER
        if path.startswith("pyodide/"):
            return wanted, A_WEEK
        return wanted, ALWAYS_ASK
    if "." in path.rsplit("/", 1)[-1]:
        return None  # a file that is not there, such as an old script: say so rather than send a page
    return root / "index.html", ALWAYS_ASK


def serve_site(app: FastAPI, site: Path) -> bool:
    """Serves the built site from `site` if there is one. Returns whether it does."""
    if not (site / "index.html").is_file():
        return False

    @app.middleware("http")
    async def isolate(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(ISOLATION)
        return response

    @app.get("/{path:path}", include_in_schema=False)
    def page(path: str) -> FileResponse:
        found = find(site, path)
        if found is None:
            raise HTTPException(status_code=404, detail="There is nothing at this address.")
        file, caching = found
        return FileResponse(file, headers={"Cache-Control": caching})

    return True
