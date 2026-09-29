"""The admin console is the React app in admin-web/, built into
app/static/admin and served by the API at /admin.

No database is needed: these run the ASGI app without its lifespan, which is
exactly what serving a static file requires. They do not need a build either:
the `built` fixture points the mount at a stand-in build in a temp directory,
shaped like Vite's output.
"""

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.core.admin_ui import AdminConsoleFiles
from app.main import app

INDEX = (
    '<!doctype html><html><head><script type="module" crossorigin '
    'src="/admin/assets/index-abc123.js"></script></head>'
    '<body><div id="root"></div></body></html>'
)


def _client() -> TestClient:
    # No `with` block: skipping the lifespan keeps Postgres and Redis out of it.
    return TestClient(app)


def _mount() -> AdminConsoleFiles:
    route = next(r for r in app.routes if getattr(r, "path", None) == "/admin")
    return route.app  # type: ignore[attr-defined,return-value]


def _serve_from(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    files = _mount()
    monkeypatch.setattr(files, "directory", str(directory))
    monkeypatch.setattr(files, "all_directories", [str(directory)])


@pytest.fixture
def built(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX)
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log('admin')")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    _serve_from(monkeypatch, tmp_path)
    return tmp_path


def test_console_is_served_with_a_script_friendly_csp(built):
    r = _client().get("/admin/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'src="/admin/assets/index-abc123.js"' in r.text
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "connect-src 'self'" in csp  # the console calls /api/v1 on the same origin
    assert "media-src 'self' https:" in csp  # reel previews play from object storage
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp


def test_deep_links_load_the_app(built):
    """A reload on /admin/vendors/<id> must get index.html, not a 404: the
    router inside it resolves the path."""
    c = _client()
    for path in ("/admin/orders", "/admin/vendors/0f8b2c1e", "/admin/accept-invite"):
        r = c.get(path, params={"token": "x"} if "invite" in path else None)
        assert r.status_code == 200, path
        assert 'id="root"' in r.text, path


def test_missing_assets_stay_404(built):
    """HTML in place of a JavaScript module fails with a MIME error that is far
    harder to read than a 404."""
    c = _client()
    assert c.get("/admin/assets/index-gone.js").status_code == 404
    assert c.get("/admin/logo.png").status_code == 404


def test_hashed_assets_are_immutable_and_html_revalidates(built):
    c = _client()
    asset = c.get("/admin/assets/index-abc123.js")
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    for path in ("/admin/", "/admin/orders", "/admin/favicon.svg"):
        assert c.get(path).headers["cache-control"] == "no-cache", path


def test_unbuilt_console_says_how_to_build_it(tmp_path, monkeypatch):
    _serve_from(monkeypatch, tmp_path / "never-built")
    r = _client().get("/admin/orders")
    assert r.status_code == 503
    assert "make admin-build" in r.text


def test_writes_are_refused(built):
    assert _client().post("/admin/orders").status_code == 405


def test_csp_allows_the_storage_origins_uploads_use(built, monkeypatch):
    """Uploads are PUT straight to R2 and Lottie banners are read back from the
    public domain, so both must be in connect-src, and nothing else."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "acct123")
    monkeypatch.setattr(settings, "R2_ENDPOINT_URL", None)
    monkeypatch.setattr(settings, "R2_BUCKET", "media")
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", "key")
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.test/media")

    csp = _client().get("/admin/").headers["content-security-policy"]
    connect = re.search(r"connect-src ([^;]+)", csp).group(1).split()
    assert connect == [
        "'self'",
        "https://acct123.r2.cloudflarestorage.com",
        "https://cdn.example.test",
    ]


def test_source_index_has_no_inline_script():
    """The CSP has no 'unsafe-inline'; an inline <script> in the page Vite
    builds from would silently not run."""
    html = (Path(__file__).parents[1] / "admin-web" / "index.html").read_text()
    scripts = re.findall(r"<script\b[^>]*>", html)
    assert scripts and all("src=" in tag for tag in scripts)
    assert "onclick=" not in html and "<style" not in html


def test_api_keeps_the_strict_csp():
    r = _client().get("/health")
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_admin_subdomain_serves_the_console_at_root(built, monkeypatch):
    """With ADMIN_UI_HOST set, requests on that host land on the console at `/`
    while API and health paths pass through untouched."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_UI_HOST", "admin.example.test")
    c = _client()
    on_admin = {"host": "admin.example.test"}

    root = c.get("/", headers=on_admin)
    assert root.status_code == 200
    assert 'id="root"' in root.text
    assert "default-src 'self'" in root.headers["content-security-policy"]
    # A deep link on the subdomain, and the assets it references under /admin/.
    assert 'id="root"' in c.get("/orders", headers=on_admin).text
    assert c.get("/admin/assets/index-abc123.js", headers=on_admin).status_code == 200

    health = c.get("/health", headers=on_admin)
    assert health.status_code == 200 and health.json()["success"] is True
    assert health.headers["content-security-policy"].startswith("default-src 'none'")


def test_api_host_is_not_rewritten(built, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_UI_HOST", "admin.example.test")
    c = _client()
    assert c.get("/", headers={"host": "api.example.test"}).status_code == 404
    assert c.get("/admin/", headers={"host": "api.example.test"}).status_code == 200


def test_host_header_port_is_ignored(built, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_UI_HOST", "admin.example.test")
    r = _client().get("/", headers={"host": "Admin.Example.Test:8443"})
    assert r.status_code == 200 and 'id="root"' in r.text
