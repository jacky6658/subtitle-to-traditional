#!/usr/bin/env python3
"""
Windows setup wizard server — uses only Python stdlib.
Runs on port 8766, serves setup.html and reports installation progress.
"""
import http.server, json, os, subprocess, threading, shutil, sys, time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER = os.path.join(BASE_DIR, ".deps_installed")
STATUS = {"step": "idle", "message": "準備中...", "progress": 0, "done": False, "error": None}
STATUS_LOCK = threading.Lock()

def set_status(step, message, progress, done=False, error=None):
    with STATUS_LOCK:
        STATUS.update(step=step, message=message, progress=progress, done=done, error=error)

def find_python():
    for p in [sys.executable, shutil.which("python"), shutil.which("python3")]:
        if p and os.path.exists(p):
            return p
    return None

def find_ffmpeg():
    return shutil.which("ffmpeg")

def run_winget(pkg_id, name):
    """Install a package via winget silently."""
    result = subprocess.run(
        ["winget", "install", "-e", "--id", pkg_id,
         "--silent", "--accept-package-agreements", "--accept-source-agreements"],
        capture_output=True, text=True
    )
    return result.returncode == 0

def run_setup():
    try:
        # ── Step 1: Python ──────────────────────────────────────────────
        set_status("python", "檢查 Python...", 5)
        python = find_python()
        if not python:
            set_status("python", "安裝 Python 3.12（約 1-2 分鐘）...", 8)
            ok = run_winget("Python.Python.3.12", "Python")
            if not ok:
                raise RuntimeError("Python 安裝失敗，請至 https://python.org 手動安裝後重試")
            # Refresh PATH
            for candidate in [
                os.path.join(os.environ.get("LOCALAPPDATA",""), "Programs", "Python", "Python312"),
                os.path.join(os.environ.get("LOCALAPPDATA",""), "Programs", "Python", "Python312", "Scripts"),
            ]:
                if os.path.isdir(candidate):
                    os.environ["PATH"] = candidate + os.pathsep + os.environ.get("PATH","")
            python = find_python()
            if not python:
                raise RuntimeError("Python 安裝後仍找不到，請重新啟動後再試")

        # ── Step 2: ffmpeg ──────────────────────────────────────────────
        set_status("ffmpeg", "檢查 ffmpeg...", 25)
        if not find_ffmpeg():
            set_status("ffmpeg", "安裝 ffmpeg（約 2-5 分鐘）...", 28)
            ok = run_winget("Gyan.FFmpeg", "ffmpeg")
            if not ok:
                raise RuntimeError("ffmpeg 安裝失敗，請至 https://ffmpeg.org 手動安裝後重試")
            ffmpeg_bin = os.path.join(os.environ.get("ProgramFiles","C:\\Program Files"), "ffmpeg", "bin")
            if os.path.isdir(ffmpeg_bin):
                os.environ["PATH"] = ffmpeg_bin + os.pathsep + os.environ.get("PATH","")

        # ── Step 3: Python packages ─────────────────────────────────────
        set_status("packages", "安裝套件（約 1-3 分鐘）...", 55)
        pkgs = ["fastapi", "uvicorn", "python-multipart",
                "opencv-python-headless", "pillow", "numpy", "zhconv", "openai-whisper"]
        subprocess.run([python, "-m", "pip", "install", "-q"] + pkgs,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # ── Step 4: Download Whisper model ──────────────────────────────
        set_status("whisper", "下載語音模型（約 1.5GB，請稍候）...", 75)
        subprocess.run([python, "-c",
                        "import whisper; whisper.load_model('medium')"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # ── Done ────────────────────────────────────────────────────────
        open(MARKER, "w").close()
        set_status("done", "安裝完成！正在啟動工具...", 100, done=True)

        time.sleep(1)
        subprocess.Popen([python, os.path.join(BASE_DIR, "server.py")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    except Exception as e:
        set_status("error", str(e), 0, error=str(e))


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path == "/api/status":
            body = json.dumps(STATUS).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/api/start":
            threading.Thread(target=run_setup, daemon=True).start()
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        else:
            html_path = os.path.join(BASE_DIR, "setup_windows.html")
            with open(html_path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)


if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", 8766), Handler)
    server.serve_forever()
