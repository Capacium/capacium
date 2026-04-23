import json
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs

from .registry import Registry


class MarketplaceHandler(SimpleHTTPRequestHandler):

    registry: Optional[Registry] = None
    marketplace_dir: Optional[Path] = None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        if path.startswith("/v1"):
            self._handle_api(path[3:], params)
        else:
            self._serve_static()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith("/v1"):
            if path == "/v1/capabilities":
                self._handle_publish()
                return

        self.send_error(404, "Not found")

    def _serve_static(self):
        md = self.__class__.marketplace_dir
        if md is None:
            self.send_error(500, "Marketplace directory not configured")
            return

        requested = self.path.lstrip("/")
        if not requested or requested.endswith("/"):
            requested = "index.html"

        file_path = md / requested
        file_path = file_path.resolve()
        if not str(file_path).startswith(str(md.resolve())):
            self.send_error(403, "Forbidden")
            return

        if file_path.is_file():
            ext = file_path.suffix.lower()
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".json": "application/json",
                ".png": "image/png",
                ".svg": "image/svg+xml",
                ".ico": "image/x-icon",
            }.get(ext, "application/octet-stream")

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            with open(file_path, "rb") as f:
                self.wfile.write(f.read())
        else:
            index = md / "index.html"
            if index.is_file():
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                with open(index, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "Not found")

    def _handle_api(self, path: str, params: Dict[str, List[str]]):
        reg = self.__class__.registry
        if reg is None:
            self._json_response(500, {"error": "Registry not configured"})
            return

        if path == "/health":
            self._json_response(200, {
                "status": "ok",
                "version": "1.0.0"
            })

        elif path == "/capabilities":
            query = params.get("query", [None])[0]
            kind = params.get("kind", [None])[0]
            limit_str = params.get("limit", ["50"])[0]
            offset_str = params.get("offset", ["0"])[0]

            try:
                limit = max(0, int(limit_str))
                offset = max(0, int(offset_str))
            except ValueError:
                self._json_response(400, {"error": "Invalid limit or offset", "code": 400})
                return

            from .models import Kind
            kind_enum = None
            if kind:
                try:
                    kind_enum = Kind(kind.lower())
                except ValueError:
                    self._json_response(400, {
                        "error": f"Invalid kind: {kind}",
                        "code": 400,
                        "message": "Must be one of: skill, bundle, tool, prompt, template, workflow"
                    })
                    return

            try:
                if query or kind:
                    caps = reg.search_capabilities(query or "", kind=kind_enum)
                else:
                    caps = reg.list_capabilities()
            except Exception as e:
                self._json_response(500, {"error": str(e), "code": 500})
                return

            results = [self._cap_to_api(c) for c in caps]
            sliced = results[offset:offset + limit] if limit else results[offset:]

            self._json_response(200, {
                "count": len(results),
                "results": sliced
            })

        elif path.startswith("/capabilities/"):
            rest = path[len("/capabilities/"):]
            sub_actions = {"versions", "download"}
            rest_parts = rest.split("/")

            if len(rest_parts) >= 2 and rest_parts[-1] in sub_actions:
                name = "/".join(rest_parts[:-1])
                sub = rest_parts[-1]
            else:
                name = rest
                sub = None

            if name and sub == "versions":
                cap = reg.get_capability(name)
                if cap is None:
                    self._json_response(404, {
                        "error": "Not found",
                        "code": 404,
                        "message": f"Capability {name} not found"
                    })
                    return
                all_caps = reg.list_capabilities()
                versions = []
                for c in all_caps:
                    if c.id == cap.id or c.name == cap.name:
                        versions.append({
                            "version": c.version,
                            "published_at": c.installed_at.isoformat() if c.installed_at else "",
                            "fingerprint": c.fingerprint,
                        })
                self._json_response(200, {
                    "name": name,
                    "versions": versions
                })

            elif name and sub == "download":
                version = params.get("version", [None])[0]
                if not version:
                    self._json_response(400, {
                        "error": "Missing version parameter",
                        "code": 400
                    })
                    return
                self.send_error(501, "Download not implemented")

            elif name:
                cap = reg.get_capability(name)
                if cap is None:
                    self._json_response(404, {
                        "error": "Not found",
                        "code": 404,
                        "message": f"Capability {name} not found"
                    })
                    return
                self._json_response(200, self._cap_to_api(cap))

            else:
                self._json_response(400, {"error": "Invalid capability path", "code": 400})

        else:
            self._json_response(404, {"error": "Not found", "code": 404})

    def _handle_publish(self):
        self._json_response(501, {"error": "Publish not implemented via marketplace", "code": 501})

    def _cap_to_api(self, cap) -> Dict[str, Any]:
        frameworks = []
        if cap.framework:
            frameworks = [cap.framework]

        deps = {}
        if cap.dependencies:
            for dep in cap.dependencies:
                parts = dep.split("@", 1)
                name = parts[0].strip()
                ver = parts[1].strip() if len(parts) > 1 else "*"
                deps[name] = ver

        return {
            "name": cap.name,
            "owner": cap.owner,
            "version": cap.version,
            "kind": cap.kind.value if hasattr(cap.kind, 'value') else str(cap.kind),
            "description": "",
            "fingerprint": cap.fingerprint,
            "dependencies": deps,
            "frameworks": frameworks,
            "published_at": cap.installed_at.isoformat() if cap.installed_at else "",
        }

    def _json_response(self, status: int, data: Any):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[registry] {args[0]} {args[1]} {args[2]}")


def create_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    registry: Optional[Registry] = None,
    marketplace_dir: Optional[Path] = None,
) -> HTTPServer:
    if registry is None:
        registry = Registry()
    if marketplace_dir is None:
        marketplace_dir = Path(__file__).parent / "marketplace"

    MarketplaceHandler.registry = registry
    MarketplaceHandler.marketplace_dir = marketplace_dir

    server = HTTPServer((host, port), MarketplaceHandler)
    return server


def run_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    open_browser: bool = False,
):
    server = create_server(host=host, port=port)
    url = f"http://localhost:{port}"

    if open_browser:
        webbrowser.open(url)

    print(f"Capacium Marketplace \u2192 {url}")
    print(f"API \u2192 {url}/v1/")
    print("Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()
