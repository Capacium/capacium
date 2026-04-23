def serve_marketplace(host: str = "0.0.0.0", port: int = 8000, open_browser: bool = False):
    from ..registry_server import run_server
    run_server(host=host, port=port, open_browser=open_browser)
