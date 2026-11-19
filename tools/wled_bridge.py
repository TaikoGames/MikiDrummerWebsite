#!/usr/bin/env python3
"""Bridge between the 3D light show page and real LED strips running WLED.

Why this exists: the light show runs on https://www.mikidrummer.ca, and a
browser will not let an https page talk to plain-http/UDP devices on the local
network. It *does* allow talking to this computer (127.0.0.1), so this script
sits there: the page POSTs each frame of colours to it, and it forwards them to
the WLED controllers as realtime UDP ("DNRGB", port 21324), which WLED shows
immediately, at whatever frame rate the page sends (about 40 fps).

If the page stops (closed, crashed, laptop asleep) WLED goes back to its own
saved effect after 2 seconds, so the strips never freeze on one frame.

Run it on the show laptop before opening the light show page:

    python3 tools/wled_bridge.py          # macOS / Linux
    py tools\\wled_bridge.py               # Windows

No installs needed: standard library only, Python 3.8+.

Safety: it only listens on 127.0.0.1 (nothing else on the network can reach
it), only accepts frames from the Miki Drummer site or localhost, and only
sends to private LAN addresses (192.168.x.x, 10.x.x.x, ...).

Frame format (POST /frame, application/octet-stream), repeated per controller:
    4 bytes IPv4 address | 2 bytes UDP port (big-endian) | 2 bytes LED count
    | LED count * 3 bytes R,G,B
"""
import argparse
import ipaddress
import json
import socket
import struct
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 21325
SITE_ORIGINS = {"https://www.mikidrummer.ca", "https://mikidrummer.ca"}
MAX_PER_PACKET = 489          # DNRGB limit per UDP packet
MAX_LEDS = 4000
TIMEOUT_S = 2                 # WLED falls back to its own effect after this

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
stats = {"frames": 0, "packets": 0, "errors": 0}


def origin_ok(origin: str) -> bool:
    if not origin:            # not a browser (curl, tests): fine, we only listen locally
        return True
    if origin in SITE_ORIGINS or origin in EXTRA_ORIGINS:
        return True
    return origin.startswith(("http://localhost:", "http://127.0.0.1:")) or origin in (
        "http://localhost", "http://127.0.0.1")


def send_dnrgb(ip: str, port: int, rgb: bytes) -> None:
    n = len(rgb) // 3
    for start in range(0, n, MAX_PER_PACKET):
        chunk = rgb[start * 3:(start + MAX_PER_PACKET) * 3]
        sock.sendto(bytes([4, TIMEOUT_S, start >> 8, start & 0xFF]) + chunk, (ip, port))
        stats["packets"] += 1


def parse_frame(body: bytes):
    out, i = [], 0
    while i + 8 <= len(body):
        ip = socket.inet_ntoa(body[i:i + 4])
        port, count = struct.unpack(">HH", body[i + 4:i + 8])
        i += 8
        if count > MAX_LEDS or i + count * 3 > len(body):
            raise ValueError("bad LED count")
        out.append((ip, port, body[i:i + count * 3]))
        i += count * 3
    if i != len(body):
        raise ValueError("trailing bytes")
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"     # keep-alive: one connection for all frames

    def _cors(self):
        origin = self.headers.get("Origin", "")
        if origin and origin_ok(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            # Chrome asks a public site's page for this before it may reach localhost
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _reply(self, code, payload=None):
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(code)
        self._cors()
        if body:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._reply(204 if origin_ok(self.headers.get("Origin", "")) else 403)

    def do_GET(self):
        if self.path.split("?")[0] == "/ping":
            self._reply(200, {"ok": True, "bridge": "wled", "version": 1, **stats})
        else:
            self._reply(404, {"ok": False})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if self.path.split("?")[0] != "/frame":
            return self._reply(404, {"ok": False})
        if not origin_ok(self.headers.get("Origin", "")):
            return self._reply(403, {"ok": False, "error": "origin not allowed"})
        try:
            targets = parse_frame(body)
            for ip, port, rgb in targets:
                if not ipaddress.ip_address(ip).is_private:
                    raise ValueError(f"{ip} is not a local network address")
                send_dnrgb(ip, port, rgb)
            stats["frames"] += 1
            self._reply(204)
        except (ValueError, OSError) as e:
            stats["errors"] += 1
            self._reply(400, {"ok": False, "error": str(e)})

    def log_message(self, *args):     # one line per frame would flood the terminal
        pass


EXTRA_ORIGINS = set()


def self_test():
    rgb = bytes(range(9))
    frame = socket.inet_aton("192.168.1.50") + struct.pack(">HH", 21324, 3) + rgb
    assert parse_frame(frame) == [("192.168.1.50", 21324, rgb)]
    try:
        parse_frame(frame + b"x")
        raise AssertionError("trailing bytes accepted")
    except ValueError:
        pass
    assert origin_ok("https://www.mikidrummer.ca") and origin_ok("http://localhost:8000")
    assert not origin_ok("https://evil.example")
    assert not ipaddress.ip_address("8.8.8.8").is_private
    print("self-test ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--allow-origin", action="append", default=[],
                    help="extra page origin allowed to send frames (repeatable)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    EXTRA_ORIGINS.update(a.allow_origin)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"WLED bridge listening on http://127.0.0.1:{a.port}. Leave this window open.")
    print("Open the light show page and turn on 'Real LED strips'. Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    sys.exit(main())
