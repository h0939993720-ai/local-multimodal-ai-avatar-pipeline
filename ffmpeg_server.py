# -*- coding: utf-8 -*-
# Copyright 2026 黃俊淏
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
ffmpeg_server.py — FFmpeg 獨立處理伺服器

架構：
  prepare_driving_video.py / liveportrait_server.py
    ↓ POST /process_video 或 /merge_audio
  ffmpeg_server.py（此檔，Port 7862）
    ↓
  C:\ffmpeg\ffmpeg-8.1-essentials_build\bin\ffmpeg.exe（系統版本）
    ↓
  回傳處理結果

放置位置：桌面/project/ffmpeg_server.py
啟動方式：start_ffmpeg.bat（用系統 Python，不需要 venv）

【設計原因】
venv312 裡的 FFmpeg 是 4.2.2 舊版，會觸發 encoder EOF 錯誤。
系統安裝的 FFmpeg 8.1 正常，但在 venv 環境內呼叫有路徑衝突。
獨立 Server 完全繞開 venv，直接用系統 Python + 系統 FFmpeg。
"""

import os
import uuid
import subprocess
import json
import logging
from pathlib import Path
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# =========================
# FFmpeg 路徑（從 .env 讀取，預設用 PATH 中的 ffmpeg/ffprobe）
# =========================
FFMPEG  = os.environ.get("FFMPEG_PATH", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_PATH", "ffprobe")

# 確認存在（若指定絕對路徑但找不到，改用 PATH）
if FFMPEG not in ("ffmpeg", "ffprobe") and not Path(FFMPEG).exists():
    logger.warning(f"找不到指定 FFmpeg：{FFMPEG}，改用 PATH")
    FFMPEG  = "ffmpeg"
    FFPROBE = "ffprobe"
else:
    logger.info(f"FFmpeg: {FFMPEG}")


# =========================
# 工具：取得音訊時長
# =========================
def get_audio_duration(audio_path: str) -> float:
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "quiet", "-print_format", "json",
             "-show_streams", audio_path],
            capture_output=True, text=True, encoding="utf-8"
        )
        for s in json.loads(r.stdout).get("streams", []):
            if "duration" in s:
                return float(s["duration"])
    except Exception as e:
        logger.warning(f"FFprobe 失敗：{e}")
    return 15.0


# =========================
# 路由：處理驅動影片
# POST /process_video
# Body: {
#   "input_path": "...",
#   "output_path": "...",
#   "ss": "00:00:15",
#   "duration": "45",
#   "crop": "crop=iw*0.55:ih*0.72:iw*0.22:ih*0.05",
#   "width": 512,
#   "height": 309
# }
# =========================
@app.route('/process_video', methods=['POST'])
def process_video():
    try:
        data        = request.get_json() or {}
        input_path  = data.get("input_path", "")
        output_path = data.get("output_path", "")
        ss          = data.get("ss", "00:00:15")
        duration    = data.get("duration", "45")
        crop        = data.get("crop", "crop=iw*0.55:ih*0.72:iw*0.22:ih*0.05")
        width       = data.get("width", 512)
        height      = data.get("height", 308)

        if not input_path or not output_path:
            return jsonify({"error": "缺少 input_path 或 output_path"}), 400
        if not Path(input_path).exists():
            return jsonify({"error": f"輸入檔不存在：{input_path}"}), 400

        logger.info(f"處理驅動影片：{Path(input_path).name} → {Path(output_path).name}")

        vf = f"{crop},scale={width}:{height},fps=25"

        cmd = [
            FFMPEG, "-y",
            "-ss", ss,
            "-i", input_path,
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            output_path
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8"
        )

        if result.returncode != 0:
            logger.error(f"FFmpeg 失敗：{result.stderr[-500:]}")
            return jsonify({"error": result.stderr[-500:]}), 500

        size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        logger.info(f"✅ 驅動影片完成：{Path(output_path).name}（{size//1024} KB）")
        return jsonify({"status": "ok", "output": output_path, "size": size})

    except Exception as e:
        logger.error(f"❌ /process_video error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# =========================
# 路由：合併音訊到影片
# POST /merge_audio
# Body: {
#   "video_path": "...",
#   "audio_path": "...",
#   "output_path": "...",
#   "duration": 15.5      (可選，自動偵測)
# }
# =========================
@app.route('/merge_audio', methods=['POST'])
def merge_audio():
    try:
        data         = request.get_json() or {}
        video_path   = data.get("video_path", "")
        audio_path   = data.get("audio_path", "")
        output_path  = data.get("output_path", "")
        duration     = data.get("duration", None)

        if not video_path or not audio_path or not output_path:
            return jsonify({"error": "缺少 video_path、audio_path 或 output_path"}), 400

        # 自動偵測音訊時長
        if duration is None:
            duration = get_audio_duration(audio_path)
        logger.info(f"合併音訊，時長 {duration:.2f} 秒")

        color_vf = "hue=s=1.03,eq=contrast=1.02:brightness=0.01"

        cmd = [
            FFMPEG, "-y",
            "-stream_loop", "-1",
            "-i", video_path,
            "-i", audio_path,
            "-t", str(duration + 1.0),  
            "-vf", color_vf,
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            output_path
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8"
        )

        if result.returncode != 0:
            # 降級：不用色彩濾鏡
            logger.warning(f"色彩濾鏡失敗，改用純合併：{result.stderr[-200:]}")
            cmd_basic = [
                FFMPEG, "-y",
                "-stream_loop", "-1",
                "-i", video_path,
                "-i", audio_path,
                "-t", str(duration),
                "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-map", "0:v:0", "-map", "1:a:0",
                output_path
            ]
            r2 = subprocess.run(cmd_basic, capture_output=True, text=True, encoding="utf-8")
            if r2.returncode != 0:
                return jsonify({"error": r2.stderr[-500:]}), 500

        size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        logger.info(f"✅ 合併完成：{Path(output_path).name}（{size//1024} KB）")
        return jsonify({
            "status":   "ok",
            "output":   output_path,
            "duration": duration,
            "size":     size
        })

    except Exception as e:
        logger.error(f"❌ /merge_audio error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# =========================
# 路由：截取影片單幀
# POST /extract_frame
# Body: {
#   "video_path": "...",
#   "output_path": "...",
#   "time": "00:00:20",
#   "width": 512,
#   "height": 309
# }
# =========================
@app.route('/extract_frame', methods=['POST'])
def extract_frame():
    try:
        data        = request.get_json() or {}
        video_path  = data.get("video_path", "")
        output_path = data.get("output_path", "")
        time_str    = data.get("time", "00:00:20")
        width       = data.get("width", 512)
        height      = data.get("height", 308)

        if not video_path or not output_path:
            return jsonify({"error": "缺少 video_path 或 output_path"}), 400
        if not Path(video_path).exists():
            return jsonify({"error": f"影片不存在：{video_path}"}), 400

        cmd = [
            FFMPEG, "-y",
            "-ss", time_str,
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "1",
            "-vf", f"scale={width}:{height}",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

        if result.returncode != 0:
            return jsonify({"error": result.stderr[-500:]}), 500

        logger.info(f"✅ 截幀完成：{Path(output_path).name}")
        return jsonify({"status": "ok", "output": output_path})

    except Exception as e:
        logger.error(f"❌ /extract_frame error: {e}")
        return jsonify({"error": str(e)}), 500


# =========================
# 路由：健康檢查
# =========================
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status":          "ok",
        "ffmpeg":          FFMPEG,
        "ffmpeg_exists":   Path(FFMPEG).exists() if FFMPEG != "ffmpeg" else True,
        "ffprobe":         FFPROBE,
    })


if __name__ == '__main__':
    print("FFmpeg Server starting on port 7862...")
    print(f"FFmpeg: {FFMPEG}")
    app.run(host='0.0.0.0', port=7862, debug=False, threaded=True)