"""Serving the built website from the server, as production does."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.site import ALWAYS_ASK, A_WEEK, FOREVER, find, serve_site


@pytest.fixture
def site(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "pyodide").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>CodeSeat</title>", "utf-8")
    (tmp_path / "sw.js").write_text("// worker", "utf-8")
    (tmp_path / "manifest.webmanifest").write_text("{}", "utf-8")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)", "utf-8")
    (tmp_path / "pyodide" / "pyodide.mjs").write_text("export {}", "utf-8")
    (tmp_path / "pyodide" / "pyodide.asm.wasm").write_bytes(b"\0asm")
    (tmp_path.parent / "secret.txt").write_text("not part of the site", "utf-8")
    return tmp_path


def test_files_are_found_with_the_right_caching(site):
    assert find(site, "assets/index-abc123.js") == (site / "assets" / "index-abc123.js", FOREVER)
    assert find(site, "pyodide/pyodide.mjs") == (site / "pyodide" / "pyodide.mjs", A_WEEK)
    assert find(site, "sw.js") == (site / "sw.js", ALWAYS_ASK)


def test_the_apps_own_addresses_get_the_page(site):
    for path in ("", "teach", "teach/ABC234", "class/ABC234", "join/ABC234", "signup", "no/such/page"):
        assert find(site, path) == (site / "index.html", ALWAYS_ASK), path


def test_missing_files_and_api_addresses_are_not_pages(site):
    assert find(site, "assets/old-build.js") is None
    assert find(site, "favicon.ico") is None
    assert find(site, "api/nothing") is None
    assert find(site, "ws/ABC234") is None


def test_nothing_outside_the_site_is_served(site):
    assert find(site, "../secret.txt") is None
    assert find(site, "assets/../../secret.txt") is None


def test_the_server_sends_the_site_with_isolation_headers(site):
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"ok": True}

    assert serve_site(app, site) is True
    client = TestClient(app)

    for path, kind in [
        ("/", "text/html"),
        ("/teach/ABC234", "text/html"),
        ("/assets/index-abc123.js", "javascript"),
        ("/pyodide/pyodide.mjs", "text/javascript"),
        ("/pyodide/pyodide.asm.wasm", "application/wasm"),
        ("/manifest.webmanifest", "application/manifest+json"),
        ("/api/health", "application/json"),
    ]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert kind in response.headers["content-type"], path
        assert response.headers["cross-origin-opener-policy"] == "same-origin", path
        assert response.headers["cross-origin-embedder-policy"] == "require-corp", path

    assert client.get("/assets/index-abc123.js").headers["cache-control"] == FOREVER
    assert client.get("/").headers["cache-control"] == ALWAYS_ASK
    assert client.get("/assets/gone.js").status_code == 404
    assert client.get("/api/nothing").status_code == 404


def test_without_a_built_site_the_server_is_the_api_only(tmp_path):
    assert serve_site(FastAPI(), tmp_path) is False
