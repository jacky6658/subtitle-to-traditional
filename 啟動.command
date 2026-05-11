#!/bin/bash
cd "$(dirname "$0")"

# ── Check Python ──────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  osascript -e 'display alert "找不到 Python 3" message "請先安裝 Python 3（https://python.org）" as critical'
  exit 1
fi

# ── Install dependencies if missing ──────────────────────────────────────
echo "🔍 檢查依賴套件..."
pip3 install -q fastapi uvicorn python-multipart opencv-python-headless pillow numpy zhconv openai-whisper 2>&1 | tail -5

# ── Check ffmpeg ──────────────────────────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
  osascript -e 'display alert "找不到 ffmpeg" message "請執行：brew install ffmpeg" as critical'
  exit 1
fi

# ── Start server ──────────────────────────────────────────────────────────
echo "🚀 啟動伺服器..."
python3 server.py &
SERVER_PID=$!

# Wait for server to be ready
for i in {1..20}; do
  sleep 0.5
  if curl -s http://127.0.0.1:8765/docs &>/dev/null; then
    break
  fi
done

# ── Open browser ──────────────────────────────────────────────────────────
echo "🌐 開啟瀏覽器..."
open index.html

echo "✅ 工具已啟動！關閉此視窗即可停止伺服器。"
wait $SERVER_PID
