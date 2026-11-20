"""
Tiny web server that hands Twilio the call script (TwiML) when it asks for it.
Needed on Twilio TRIAL accounts, which don't allow sending the script inside the call request.

    python3 twiml_server.py            # serves on port 8000

Then expose it to the internet with a tunnel (see README steps) and put the tunnel's
https address in .env as PUBLIC_BASE_URL. voicebot.py writes each call's script into
./twiml_pending/ and this server serves those files back to Twilio. No dependencies.
"""
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PENDING = Path(__file__).resolve().parent.parent / "orchestrator" / "agents" / "real" / "twiml_pending"
PENDING.mkdir(exist_ok=True)
NAME_RE = re.compile(r"^/twiml/([A-Za-z0-9_]+\.xml)$")


class Handler(BaseHTTPRequestHandler):
    def _serve(self, head_only=False):
        m = NAME_RE.match(self.path.split("?")[0])
        f = PENDING / m.group(1) if m else None
        if not f or not f.is_file():
            self.send_response(404)
            self.end_headers()
            print(f"[404] {self.path}")
            return
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)
        print(f"[200] served {f.name} to {self.client_address[0]}")

    def do_GET(self):
        self._serve()

    def do_POST(self):  # Twilio POSTs to the Url by default
        # Read (and ignore) the request body first. Closing the connection with unread
        # data makes the OS reset it, and the client can then miss our reply entirely.
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n:
            self.rfile.read(n)
        self._serve()

    def do_HEAD(self):
        self._serve(head_only=True)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"Serving TwiML from {PENDING} on http://localhost:{port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
