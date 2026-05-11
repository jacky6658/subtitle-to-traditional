#!/usr/bin/env python3
"""
Windows setup wizard server — uses only Python stdlib.
Runs on port 8766, serves setup_windows.html and reports installation progress.
"""
import http.server, json, os, subprocess, threading, shutil, sys, time, glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER   = os.path.join(BASE_DIR, ".deps_installed")
LOG_FILE = os.path.join(BASE_DIR, "setup.log")
STATUS   = {"step": "idle", "message": "準備中...", "progress": 0, "done": False, "error": None}
STATUS_LOCK = threading.Lock()

def log(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

def set_status(step, message, progress, done=False, error=None):
    log(f"STATUS {step} | {message} | {progress}%")
    with STATUS_LOCK:
        STATUS.update(step=step, message=message, progress=progress, done=done, error=error)

def get_status():
    with STATUS_LOCK:
        return dict(STATUS)

def find_python():
    candidates = [
        sys.executable,
        shutil.which("python"),
        shutil.which("python3"),
        shutil.which("py"),
        os.path.join(os.environ.get("LOCALAPPDATA",""), "Programs", "Python", "Python312", "python.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA",""), "Programs", "Python", "Python311", "python.exe"),
        r"C:\Python312\python.exe",
        r"C:\Python311\python.exe",
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            log(f"found python: {p}")
            return p
    return None

def find_ffmpeg():
    # Check PATH first
    f = shutil.which("ffmpeg")
    if f:
        return f
    # Check winget install locations
    winget_dirs = glob.glob(os.path.join(
        os.environ.get("LOCALAPPDATA",""),
        "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "ffmpeg.exe"
    ), recursive=True)
    if winget_dirs:
        return winget_dirs[0]
    # Check common locations
    for p in [r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]:
        if os.path.isfile(p):
            return p
    return None

def add_to_path(directory):
    if directory and os.path.isdir(directory):
        os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
        log(f"added to PATH: {directory}")

def run_winget(pkg_id):
    log(f"winget install {pkg_id}")
    try:
        result = subprocess.run(
            ["winget", "install", "-e", "--id", pkg_id,
             "--silent", "--accept-package-agreements", "--accept-source-agreements"],
            capture_output=True, timeout=300
        )
        stdout = (result.stdout or b"").decode("utf-8", errors="replace")[-200:]
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")[-200:]
        log(f"winget exit={result.returncode} stdout={stdout} stderr={stderr}")
        # 0 = success, 0x8A150101 / -1978335999 = already installed
        return result.returncode in (0, -1978335999, 0x8A150101)
    except FileNotFoundError:
        log("winget not found")
        return False
    except Exception as e:
        log(f"winget error: {e}")
        return False

def run_setup():
    try:
        # ── Step 1: Python ──────────────────────────────────────────────
        set_status("python", "檢查 Python...", 5)
        python = find_python()
        if not python:
            set_status("python", "安裝 Python 3.12（約 1-2 分鐘）...", 8)
            run_winget("Python.Python.3.12")
            # Add possible install paths
            for d in [
                os.path.join(os.environ.get("LOCALAPPDATA",""), "Programs", "Python", "Python312"),
                os.path.join(os.environ.get("LOCALAPPDATA",""), "Programs", "Python", "Python312", "Scripts"),
            ]:
                add_to_path(d)
            python = find_python()
            if not python:
                raise RuntimeError("Python 安裝後仍找不到，請關閉此視窗重新執行 .bat")

        # ── Step 2: ffmpeg ──────────────────────────────────────────────
        set_status("ffmpeg", "檢查 ffmpeg...", 25)
        if not find_ffmpeg():
            set_status("ffmpeg", "安裝 ffmpeg（約 2-5 分鐘）...", 28)
            run_winget("Gyan.FFmpeg")
            # Add common ffmpeg bin paths
            for d in [
                r"C:\ffmpeg\bin",
                r"C:\Program Files\ffmpeg\bin",
                os.path.join(os.environ.get("LOCALAPPDATA",""),
                    "Microsoft", "WinGet", "Links"),
            ]:
                add_to_path(d)

        # ── Step 3: Python packages ─────────────────────────────────────
        set_status("packages", "安裝套件（約 3-5 分鐘）...", 55)
        pkgs = ["fastapi", "uvicorn", "python-multipart",
                "opencv-python-headless", "pillow", "numpy", "zhconv", "faster-whisper"]
        r = subprocess.run(
            [python, "-m", "pip", "install", "-q"] + pkgs,
            capture_output=True, text=True, timeout=1800
        )
        log(f"pip exit={r.returncode} err={r.stderr[-300:]}")

        # ── Step 4: Download Whisper model ──────────────────────────────
        set_status("whisper", "下載語音模型（約 600MB，請稍候）...", 75)
        r = subprocess.run(
            [python, "-c",
             "from faster_whisper import WhisperModel; WhisperModel('medium', device='cpu', compute_type='int8')"],
            capture_output=True, text=True, timeout=1800
        )
        log(f"whisper exit={r.returncode} err={r.stderr[-300:]}")

        # ── Done ────────────────────────────────────────────────────────
        open(MARKER, "w").close()
        set_status("done", "安裝完成！正在啟動工具...", 100, done=True)

        time.sleep(1)
        subprocess.Popen([python, os.path.join(BASE_DIR, "server.py")],
                         creationflags=0x00000008)  # DETACHED_PROCESS

    except Exception as e:
        log(f"ERROR: {e}")
        set_status("error", str(e), 0, error=str(e))


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path == "/api/status":
            body = json.dumps(get_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
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

        elif self.path == "/api/log":
            try:
                body = open(LOG_FILE, "rb").read()
            except Exception:
                body = b"no log yet"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
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
    log("=== setup_server started ===")
    server = http.server.HTTPServer(("127.0.0.1", 8766), Handler)
    server.serve_forever()
