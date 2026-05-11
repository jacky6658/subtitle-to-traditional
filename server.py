import os, re, uuid, threading, tempfile, subprocess
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
import zhconv
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

import platform
_sys = platform.system()
if _sys == "Darwin":
    FONT_PATH = os.path.expanduser("~/Library/Fonts/NotoSansCJKtc-Bold.otf")
    FALLBACK_FONTS = [
        "/Library/Fonts/Arial Unicode MS.ttf",
        "/System/Library/Fonts/PingFang.ttc",
    ]
elif _sys == "Windows":
    FONT_PATH = r"C:\Windows\Fonts\msjh.ttc"   # Microsoft JhengHei
    FALLBACK_FONTS = [
        r"C:\Windows\Fonts\msjhbd.ttc",
        r"C:\Windows\Fonts\mingliu.ttc",
        r"C:\Windows\Fonts\kaiu.ttf",
    ]
else:
    FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
    FALLBACK_FONTS = [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

jobs: dict = {}  # job_id -> {status, progress, stage, output_path, error}


def find_font():
    for p in [FONT_PATH] + FALLBACK_FONTS:
        if os.path.exists(p):
            return p
    return None


def parse_srt(text):
    subs = []
    for block in re.split(r'\n\n+', text.strip()):
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        def ts(t):
            h, m, s = t.split(':')
            s, ms = s.split(',')
            return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000
        parts = lines[1].split(' --> ')
        subs.append({
            'start': ts(parts[0].strip()),
            'end':   ts(parts[1].strip()),
            'text':  ' '.join(lines[2:]).strip(),
        })
    return subs


def to_traditional(text):
    return zhconv.convert(text, 'zh-tw')


def process_job(job_id: str, input_path: str, output_path: str):
    job = jobs[job_id]
    try:
        # ── 1. Probe video ──────────────────────────────────────────────
        job.update(stage='分析影片...', progress=0.02)
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height,r_frame_rate',
             '-of', 'csv=p=0', input_path],
            capture_output=True, text=True, check=True
        )
        parts = probe.stdout.strip().split(',')
        W, H = int(parts[0]), int(parts[1])
        num, den = parts[2].split('/')
        fps = float(num) / float(den)

        # ── 2. Whisper transcription ────────────────────────────────────
        job.update(stage='Whisper 辨識字幕中...', progress=0.08)
        from faster_whisper import WhisperModel
        model = WhisperModel('medium', device='cpu', compute_type='int8')
        segments, _ = model.transcribe(input_path, language='zh')

        # Build SRT from segments
        def fmt_ts(s):
            h = int(s // 3600); m = int((s % 3600) // 60)
            sec = int(s % 60); ms = int((s % 1) * 1000)
            return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

        srt_lines = []
        for i, seg in enumerate(segments, 1):
            srt_lines.append(str(i))
            srt_lines.append(f"{fmt_ts(seg.start)} --> {fmt_ts(seg.end)}")
            srt_lines.append(seg.text.strip())
            srt_lines.append("")
        srt_raw = "\n".join(srt_lines)

        # ── 3. Convert to Traditional Chinese ──────────────────────────
        job.update(stage='轉換繁體中文...', progress=0.36)
        lines_out = []
        for line in srt_raw.split('\n'):
            if re.match(r'^\d+$', line.strip()) or re.match(r'^\d{2}:\d{2}', line.strip()) or not line.strip():
                lines_out.append(line)
            else:
                lines_out.append(to_traditional(line))
        srt_tw = '\n'.join(lines_out)
        subs = parse_srt(srt_tw)

        # save SRT alongside output
        srt_out = output_path.replace('.mp4', '.srt')
        open(srt_out, 'w', encoding='utf-8').write(srt_tw)

        # ── 4. Detect original subtitle region ─────────────────────────
        job.update(stage='偵測字幕位置...', progress=0.42)
        cap = cv2.VideoCapture(input_path)
        seek_sec = subs[0]['start'] + 1.0 if subs else 1.0
        cap.set(cv2.CAP_PROP_POS_MSEC, seek_sec * 1000)
        ok, sample_bgr = cap.read()
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()

        orig_y1, orig_y2 = int(H * 0.86), int(H * 0.95)
        if ok and sample_bgr is not None:
            bot_y = int(H * 0.75)
            region_gray = cv2.cvtColor(sample_bgr[bot_y:], cv2.COLOR_BGR2GRAY)
            row_whites = (region_gray > 200).sum(axis=1)
            text_rows = np.where(row_whites > 50)[0]
            if len(text_rows):
                orig_y1 = max(int(H * 0.75), bot_y + int(text_rows.min()) - 15)
                orig_y2 = min(H - 5, bot_y + int(text_rows.max()) + 15)

        # ── 5. Prepare drawing tools ────────────────────────────────────
        font_path = find_font()
        font_size = max(22, int(H * 0.034))
        pil_font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
        kernel = np.ones((5, 5), np.uint8)

        def process_frame(rgb: np.ndarray, t: float) -> np.ndarray:
            active = [s for s in subs if s['start'] <= t < s['end']]
            if not active:
                return rgb
            # inpaint original subtitle region
            region = rgb[orig_y1:orig_y2, :]
            gray = np.mean(region, axis=2).astype(np.uint8)
            mask = cv2.dilate(
                ((gray > 190) | (gray < 45)).astype(np.uint8) * 255,
                kernel, iterations=2
            )
            bgr = cv2.cvtColor(region, cv2.COLOR_RGB2BGR)
            inpainted = cv2.inpaint(bgr, mask, 7, cv2.INPAINT_TELEA)
            rgb[orig_y1:orig_y2, :] = cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB)
            # draw traditional Chinese text with outline
            img = Image.fromarray(rgb)
            draw = ImageDraw.Draw(img)
            text = active[0]['text']
            bbox = draw.textbbox((0, 0), text, font=pil_font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x = (W - tw) // 2
            y = orig_y1 + (orig_y2 - orig_y1 - th) // 2
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if dx or dy:
                        draw.text((x + dx, y + dy), text, font=pil_font, fill=(0, 0, 0))
            draw.text((x, y), text, font=pil_font, fill=(255, 255, 255))
            return np.array(img)

        # ── 6. FFmpeg pipe encode ───────────────────────────────────────
        job.update(stage='處理影片中...', progress=0.45)
        reader = subprocess.Popen(
            ['ffmpeg', '-i', input_path, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        writer = subprocess.Popen(
            ['ffmpeg', '-y',
             '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(fps), '-i', 'pipe:0',
             '-i', input_path,
             '-map', '0:v:0', '-map', '1:a:0',
             '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
             '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-level:v', '3.1',
             '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
             '-c:a', 'copy', output_path],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL
        )

        frame_size = W * H * 3
        idx = 0
        while True:
            raw = reader.stdout.read(frame_size)
            if len(raw) < frame_size:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((H, W, 3)).copy()
            frame = process_frame(frame, idx / fps)
            writer.stdin.write(frame.tobytes())
            idx += 1
            if total_frames > 0:
                pct = 0.45 + 0.53 * (idx / total_frames)
                job.update(stage=f'處理影片中... {idx}/{total_frames} 幀', progress=min(pct, 0.97))

        reader.stdout.close()
        reader.wait()
        writer.stdin.close()
        writer.wait()

        job.update(status='done', stage='完成！', progress=1.0)

    except Exception as e:
        job.update(status='error', error=str(e), progress=0)


# ── Routes ──────────────────────────────────────────────────────────────────

@app.post('/process')
async def start_process(video: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    tmp_dir = tempfile.mkdtemp()
    # use simple ascii filename to avoid subprocess encoding issues
    input_path = os.path.join(tmp_dir, 'input.mp4')
    output_path = os.path.join(tmp_dir, 'output.mp4')

    content = await video.read()
    with open(input_path, 'wb') as f:
        f.write(content)

    jobs[job_id] = {
        'status': 'running',
        'progress': 0.0,
        'stage': '準備中...',
        'output_path': output_path,
        'error': None,
    }
    t = threading.Thread(target=process_job, args=(job_id, input_path, output_path), daemon=True)
    t.start()
    return JSONResponse({'job_id': job_id})


@app.get('/status/{job_id}')
def get_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return JSONResponse({'status': 'error', 'error': '找不到工作'}, status_code=404)
    return JSONResponse({
        'status':   job['status'],
        'progress': job['progress'],
        'stage':    job['stage'],
        'error':    job['error'],
    })


@app.get('/download/{job_id}')
def download(job_id: str):
    job = jobs.get(job_id)
    if not job or job['status'] != 'done':
        return JSONResponse({'error': '尚未完成'}, status_code=400)
    return FileResponse(job['output_path'], media_type='video/mp4', filename='output_繁體字幕.mp4')


@app.get('/')
def home():
    return FileResponse(os.path.join(BASE_DIR, 'home.html'))

@app.get('/tool')
def index():
    return FileResponse(os.path.join(BASE_DIR, 'index.html'))

app.mount('/static', StaticFiles(directory=BASE_DIR), name='static')

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8765)
