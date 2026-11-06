"""Shared test helpers: a fake Publora server, image fixtures and a CLI runner.

Nothing here touches the network beyond 127.0.0.1, and all scratch state lives
in tempfile.mkdtemp() directories outside the repository.
"""

import hashlib
import http.server
import json
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIPOST = os.path.join(REPO, "bin", "lipost")
API_KEY = "pk_test_SECRET_9f8e7d6c5b4a"
PLATFORM = "linkedin-Tz9W5i6ZYG"


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def magick(*args):
    subprocess.run(["magick", *args], check=True, capture_output=True)


def make_image(path, size="40x20", color="red"):
    magick("-size", size, f"xc:{color}", path)
    return path


def _exif_segment(gps=True, orientation=None):
    """Build a JPEG APP1 Exif segment with optional GPS IFD and Orientation.

    ImageMagick cannot write GPS tags (`-set exif:GPSLatitude` is ignored), so
    the TIFF structure is assembled by hand: IFD0 -> GPSInfo pointer -> GPS IFD.
    """
    entries = []
    if orientation is not None:
        entries.append(("orient", orientation))
    if gps:
        entries.append(("gps", None))
    ifd0_off = 8
    ifd0_size = 2 + 12 * len(entries) + 4
    gps_off = ifd0_off + ifd0_size
    rat_off = gps_off + 2 + 2 * 12 + 4
    tiff = b"II*\x00" + struct.pack("<I", ifd0_off)
    tiff += struct.pack("<H", len(entries))
    for kind, value in entries:
        if kind == "orient":
            tiff += struct.pack("<HHIHH", 0x0112, 3, 1, value, 0)
        else:
            tiff += struct.pack("<HHII", 0x8825, 4, 1, gps_off)
    tiff += struct.pack("<I", 0)
    if gps:
        tiff += struct.pack("<H", 2)
        tiff += struct.pack("<HHI", 1, 2, 2) + b"N\x00\x00\x00"
        tiff += struct.pack("<HHII", 2, 5, 3, rat_off) + struct.pack("<I", 0)
        tiff += struct.pack("<6I", 12, 1, 30, 1, 0, 1)
    payload = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def make_jpeg_with_exif(path, size="40x20", gps=True, orientation=None):
    make_image(path, size=size)
    with open(path, "rb") as fh:
        data = fh.read()
    with open(path, "wb") as fh:
        fh.write(data[:2] + _exif_segment(gps, orientation) + data[2:])
    return path


def gps_of(path):
    out = subprocess.run(
        ["magick", "identify", "-format", "%[EXIF:GPSLatitude]", path],
        capture_output=True, text=True,
    )
    return out.stdout.strip()


class FakePublora:
    """In-process HTTP server mimicking the Publora endpoints lipost uses."""

    def __init__(self):
        self.requests = []
        self.connections = [
            {"platformId": PLATFORM, "displayName": "Ada Lovelace", "username": "ada"},
            {"platformId": "twitter-123", "displayName": "Ada on X", "username": "ada_x"},
        ]
        self.posts = {}
        self.next_id = 0
        self.overrides = {}  # path -> (status, body dict, extra headers)
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                fake.requests.append({
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": raw,
                })
                status, body, headers = fake.route(self.command, self.path, raw)
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = _handle

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}/api/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def route(self, method, path, raw):
        if path in self.overrides:
            return self.overrides[path]
        body = json.loads(raw) if raw and not path.startswith("/upload/") else {}
        if method == "GET" and path == "/api/v1/platform-connections":
            return 200, {"success": True, "connections": self.connections}, {}
        if method == "POST" and path == "/api/v1/create-post":
            self.next_id += 1
            pid = f"507f1f77bcf86cd79943{self.next_id:04d}"
            self.posts[pid] = {"content": body["content"], "platforms": body["platforms"],
                               "status": "draft", "media": []}
            return 200, {"success": True, "postGroupId": pid, "scheduledTime": None}, {}
        if method == "POST" and path == "/api/v1/get-upload-url":
            post = self.posts[body["postGroupId"]]
            n = len(post["media"])
            post["media"].append({"mediaId": f"m{n}", "type": "image", "status": "ready",
                                  "mimeType": body["contentType"]})
            return 200, {"success": True,
                         "uploadUrl": f"http://127.0.0.1:{self.port}/upload/{body['postGroupId']}/{n}",
                         "fileUrl": f"https://cdn.example/{n}", "mediaId": f"m{n}"}, {}
        if method == "PUT" and path.startswith("/upload/"):
            return 200, None, {}
        parts = path.split("/")
        pid = parts[-1]
        post = self.posts.get(pid)
        if post is None:
            return 404, {"error": "Post group not found"}, {}
        if method == "GET" and path.startswith("/api/v1/get-post/"):
            plat, _, raw_id = post["platforms"][0].partition("-")
            return 200, {
                "success": True, "postGroupId": pid, "status": post["status"],
                "scheduledTime": None, "platforms": post["platforms"],
                "posts": [{"_id": "p1", "platform": plat, "platformId": raw_id,
                           "content": post["content"], "status": post["status"]}],
                "media": post["media"],
            }, {}
        if method == "PUT" and path.startswith("/api/v1/update-post/"):
            if body.get("publishNow") is True:
                post["status"] = "scheduled"
            return 200, {"success": True, "message": "Post updated successfully",
                         "scheduledTime": "2026-11-05T12:00:00.000Z",
                         "postGroup": {"_id": pid, "status": post["status"],
                                       "content": post["content"]}}, {}
        if method == "DELETE" and path.startswith("/api/v1/delete-post/"):
            del self.posts[pid]
            return 200, {"success": True}, {}
        return 404, {"error": "Not found"}, {}

    def calls(self, method=None, prefix=""):
        return [r for r in self.requests
                if (method is None or r["method"] == method) and r["path"].startswith(prefix)]


class CliTestCase(unittest.TestCase):
    """Base class: isolated HOME/XDG dirs and a fake Publora per test."""

    use_server = True

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lipost-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.home,
            "XDG_STATE_HOME": os.path.join(self.tmp, "state"),
            "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
            "PUBLORA_API_KEY": API_KEY,
            "LIPOST_PLATFORM_ID": PLATFORM,
        }
        if self.use_server:
            self.fake = FakePublora()
            self.addCleanup(self.fake.close)
            self.env["LIPOST_PUBLORA_BASE_URL"] = self.fake.base

    def run_cli(self, *args, env=None):
        proc = subprocess.run([LIPOST, *args], capture_output=True, text=True,
                              env=env if env is not None else self.env, timeout=60)
        return proc

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def write_text(self, content, name="post.txt"):
        p = self.path(name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        return p

    def manifest_path(self, draft_id):
        return os.path.join(self.env["XDG_STATE_HOME"], "lipost", "drafts", f"{draft_id}.json")
