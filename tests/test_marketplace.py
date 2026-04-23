import json
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from capacium.models import Capability, Kind
from capacium.registry import Registry
from capacium.registry_server import create_server


MARKETPLACE_DIR = Path(__file__).parent.parent / "src" / "capacium" / "marketplace"


class TestMarketplaceFiles:
    def test_marketplace_dir_exists(self):
        assert MARKETPLACE_DIR.is_dir()

    def test_init_py_exists(self):
        assert (MARKETPLACE_DIR / "__init__.py").is_file()

    def test_index_html_exists(self):
        index = MARKETPLACE_DIR / "index.html"
        assert index.is_file()
        content = index.read_text()
        assert "<!DOCTYPE html>" in content

    def test_style_css_exists(self):
        css = MARKETPLACE_DIR / "style.css"
        assert css.is_file()
        content = css.read_text()
        assert ":root" in content

    def test_app_js_exists(self):
        js = MARKETPLACE_DIR / "app.js"
        assert js.is_file()
        content = js.read_text()
        assert "API_BASE" in content or "fetch" in content

    def test_index_html_references_assets(self):
        index = (MARKETPLACE_DIR / "index.html").read_text()
        assert "style.css" in index
        assert "app.js" in index

    def test_html_valid_structure(self):
        index = (MARKETPLACE_DIR / "index.html").read_text()
        assert "<html" in index
        assert "<head>" in index
        assert "<body>" in index
        assert "</html>" in index

    def test_css_valid_rules(self):
        css = (MARKETPLACE_DIR / "style.css").read_text()
        assert "{" in css
        assert "}" in css

    def test_js_valid_syntax(self):
        js = (MARKETPLACE_DIR / "app.js").read_text()
        assert "function" in js or "=>" in js
        assert "fetch" in js


class TestRegistryServerAPI:
    @pytest.fixture
    def reg(self, tmp_home):
        r = Registry()
        caps = [
            Capability(
                owner="test", name="web-fetcher", version="1.2.0",
                kind=Kind.SKILL, fingerprint="abc123",
                install_path=Path("/tmp/test"), installed_at=datetime.now(),
                dependencies=["requests@^2.28.0"],
                framework="opencode",
            ),
            Capability(
                owner="test", name="db-tool", version="2.0.0",
                kind=Kind.TOOL, fingerprint="def456",
                install_path=Path("/tmp/test"), installed_at=datetime.now(),
                dependencies=None, framework="claude-code",
            ),
            Capability(
                owner="demo", name="prompt-pack", version="0.5.0",
                kind=Kind.PROMPT, fingerprint="ghi789",
                install_path=Path("/tmp/test"), installed_at=datetime.now(),
                dependencies=[], framework=None,
            ),
        ]
        for c in caps:
            r.add_capability(c)
        return r

    @pytest.fixture
    def server(self, reg):
        s = create_server(host="127.0.0.1", port=0, registry=reg)
        th = threading.Thread(target=s.serve_forever, daemon=True)
        th.start()
        time.sleep(0.05)
        yield s
        s.shutdown()

    @property
    def base_url(self, server):
        return f"http://127.0.0.1:{server.server_port}"

    def test_health(self, server):
        url = f"http://127.0.0.1:{server.server_port}/v1/health"
        resp = urlopen(url)
        data = json.loads(resp.read())
        assert data["status"] == "ok"
        assert data["version"] == "1.0.0"

    def test_list_capabilities(self, server):
        url = f"http://127.0.0.1:{server.server_port}/v1/capabilities"
        resp = urlopen(url)
        data = json.loads(resp.read())
        assert data["count"] == 3
        names = {r["name"] for r in data["results"]}
        assert names == {"web-fetcher", "db-tool", "prompt-pack"}

    def test_search_by_query(self, server):
        url = f"http://127.0.0.1:{server.server_port}/v1/capabilities?query=web"
        resp = urlopen(url)
        data = json.loads(resp.read())
        assert data["count"] == 1
        assert data["results"][0]["name"] == "web-fetcher"

    def test_filter_by_kind(self, server):
        url = f"http://127.0.0.1:{server.server_port}/v1/capabilities?kind=tool"
        resp = urlopen(url)
        data = json.loads(resp.read())
        assert data["count"] == 1
        assert data["results"][0]["kind"] == "tool"

    def test_filter_by_invalid_kind(self, server):
        url = f"http://127.0.0.1:{server.server_port}/v1/capabilities?kind=invalid"
        with pytest.raises(HTTPError) as exc:
            urlopen(url)
        assert exc.value.code == 400

    def test_get_capability_by_id(self, server):
        url = f"http://127.0.0.1:{server.server_port}/v1/capabilities/test/web-fetcher"
        resp = urlopen(url)
        data = json.loads(resp.read())
        assert data["name"] == "web-fetcher"
        assert data["owner"] == "test"
        assert data["version"] == "1.2.0"
        assert data["kind"] == "skill"
        assert data["fingerprint"] == "abc123"
        assert "frameworks" in data
        assert "opencode" in data["frameworks"]

    def test_get_nonexistent_capability(self, server):
        url = f"http://127.0.0.1:{server.server_port}/v1/capabilities/nonexistent"
        with pytest.raises(HTTPError) as exc:
            urlopen(url)
        assert exc.value.code == 404

    def test_list_versions(self, server):
        url = f"http://127.0.0.1:{server.server_port}/v1/capabilities/test/web-fetcher/versions"
        resp = urlopen(url)
        data = json.loads(resp.read())
        assert data["name"] == "test/web-fetcher"
        assert len(data["versions"]) >= 1
        assert data["versions"][0]["version"] == "1.2.0"

    def test_limit_and_offset(self, server):
        url = f"http://127.0.0.1:{server.server_port}/v1/capabilities?limit=2&offset=0"
        resp = urlopen(url)
        data = json.loads(resp.read())
        assert len(data["results"]) == 2

    def test_serve_index_html(self, server):
        url = f"http://127.0.0.1:{server.server_port}/"
        resp = urlopen(url)
        body = resp.read().decode("utf-8")
        assert "<!DOCTYPE html>" in body
        assert "Capacium" in body

    def test_serve_style_css(self, server):
        url = f"http://127.0.0.1:{server.server_port}/style.css"
        resp = urlopen(url)
        body = resp.read().decode("utf-8")
        assert ":root" in body

    def test_serve_app_js(self, server):
        url = f"http://127.0.0.1:{server.server_port}/app.js"
        resp = urlopen(url)
        body = resp.read().decode("utf-8")
        assert "fetch" in body

    def test_cors_headers(self, server):
        url = f"http://127.0.0.1:{server.server_port}/v1/capabilities"
        req = Request(url)
        resp = urlopen(req)
        assert resp.getheader("Access-Control-Allow-Origin") == "*"

    def test_marketplace_cli_command_exists(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "capacium.cli", "marketplace", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "marketplace" in result.stdout
