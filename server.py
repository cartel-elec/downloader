#!/usr/bin/env python3
"""
CARTE MULTI-DOWNLOADER
Self-hosted media downloader for TikTok, Instagram, Facebook, X and 1000+ sites.
Requires: yt-dlp + ffmpeg in PATH
"""

import json
import os
import subprocess
import tempfile
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT = 8080
TEMP_DIR = Path(tempfile.gettempdir()) / "carte_multi_dl"
TEMP_DIR.mkdir(exist_ok=True)

# Clean old files on start
for f in TEMP_DIR.glob("*"):
    try:
        f.unlink()
    except Exception:
        pass


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/download"):
            self.handle_download()
        else:
            if self.path in ("/", ""):
                self.path = "/index.html"
            return SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        if self.path == "/api/info":
            self.handle_info()
        else:
            self.send_error(404)

    def handle_info(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            return self.json_error("Invalid request body")

        url = (body.get("url") or "").strip()
        fmt = body.get("format", "best")

        if not url:
            return self.json_error("No URL provided")

        try:
            cmd = [
                "yt-dlp",
                "--dump-json",
                "--no-playlist",
                "--no-warnings",
                "--no-check-certificates",
                url,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=90
            )
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "yt-dlp failed").strip()
                # Make error message friendlier
                if "Unsupported URL" in err:
                    err = "This link is not supported or is private."
                elif "Private video" in err or "login" in err.lower():
                    err = "This content is private or requires login."
                return self.json_error(err[:300])

            info = json.loads(result.stdout)

            formats = []
            if fmt == "audio":
                formats.append(
                    {"format_id": "bestaudio/best", "ext": "mp3", "quality": "Best audio (MP3)"}
                )
            elif fmt == "photo":
                formats.append(
                    {"format_id": "best", "ext": "jpg", "quality": "Original image"}
                )
            else:
                formats.append(
                    {"format_id": "best", "ext": "mp4", "quality": "Best quality"}
                )
                formats.append(
                    {
                        "format_id": "bestvideo+bestaudio/best",
                        "ext": "mp4",
                        "quality": "Best video + audio",
                    }
                )

            data = {
                "title": info.get("title") or info.get("fulltitle") or "Untitled",
                "uploader": info.get("uploader")
                or info.get("channel")
                or info.get("creator")
                or "",
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail"),
                "formats": formats,
            }
            self.json_response(data)

        except subprocess.TimeoutExpired:
            self.json_error("Timed out while fetching media info")
        except json.JSONDecodeError:
            self.json_error("Could not parse media information")
        except Exception as e:
            self.json_error(str(e)[:200])

    def handle_download(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        url = qs.get("url", [""])[0]
        format_id = qs.get("format", ["best"])[0]
        ext = qs.get("ext", ["mp4"])[0]

        if not url:
            return self.send_error(400, "Missing URL")

        try:
            # Unique output template
            outtmpl = str(TEMP_DIR / "%(id)s.%(ext)s")
            cmd = [
                "yt-dlp",
                "-f",
                format_id,
                "--no-playlist",
                "-o",
                outtmpl,
                "--no-warnings",
                "--no-check-certificates",
                "--newline",
                url,
            ]

            if ext == "mp3":
                cmd.extend(["-x", "--audio-format", "mp3", "--audio-quality", "0"])

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=360
            )
            if result.returncode != 0:
                err = (result.stderr or "Download failed").strip()[:200]
                return self.send_error(500, err)

            # Find newest file in temp dir
            files = [p for p in TEMP_DIR.glob("*") if p.is_file()]
            if not files:
                return self.send_error(500, "File not found after download")

            filepath = max(files, key=lambda p: p.stat().st_mtime)
            filename = filepath.name

            # Safe content-type
            content_type = "application/octet-stream"
            if filename.lower().endswith(".mp4"):
                content_type = "video/mp4"
            elif filename.lower().endswith(".mp3"):
                content_type = "audio/mpeg"
            elif filename.lower().endswith((".jpg", ".jpeg")):
                content_type = "image/jpeg"
            elif filename.lower().endswith(".png"):
                content_type = "image/png"
            elif filename.lower().endswith(".webp"):
                content_type = "image/webp"

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header(
                "Content-Disposition", f'attachment; filename="{filename}"'
            )
            self.send_header("Content-Length", str(filepath.stat().st_size))
            self.end_headers()

            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

            # Cleanup
            try:
                filepath.unlink()
            except Exception:
                pass

        except subprocess.TimeoutExpired:
            self.send_error(500, "Download timed out")
        except Exception as e:
            self.send_error(500, str(e)[:200])

    def json_response(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def json_error(self, msg):
        self.json_response({"error": msg}, 400)

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {args[0]}")


if __name__ == "__main__":
    print("=" * 50)
    print("  CARTE MULTI-DOWNLOADER")
    print(f"  Running at http://localhost:{PORT}")
    print("  Press Ctrl+C to stop")
    print("=" * 50)
    HTTPServer(("", PORT), Handler).serve_forever()
