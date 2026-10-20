"""test_census.py -- the one assertion that matters about a probe: it must refuse.

Run it directly (no pytest needed):  python test_census.py
"""
import http.server
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import census  # noqa: E402


class _Html(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><html><body>a web UI, not an API</body></html>"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class _Json(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"models": [{"name": "tiny"}]}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _serve(handler):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    srv = _serve(_Html)
    try:
        r = census._probe_port(srv.server_address[1])
    finally:
        srv.shutdown()
    assert r is not None, "an answering port must produce a row, not None"
    assert r["contract"] is False, "HTTP 200 with HTML was scored as a contract: %r" % (r,)

    srv = _serve(_Json)
    try:
        r2 = census._probe_port(srv.server_address[1])
    finally:
        srv.shutdown()
    assert r2 is not None and r2["contract"] is True, "a real JSON contract was refused: %r" % (r2,)
    print("ok: HTML refused, JSON accepted")


if __name__ == "__main__":
    main()
