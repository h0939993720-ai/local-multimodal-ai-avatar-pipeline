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
liveportrait_server.py — LivePortrait 獨立 Flask 伺服器

架構：
  project/app.py → POST /generate → liveportrait_server.py（Port 7861）
                                   → inference.py（LivePortrait venv）
                                   → 回傳影片檔名

放置位置：桌面/project/liveportrait_server.py

【鎖肩問題根本解法】
1. prepare_driving_video.py：寬版裁切（含雙肩），512x309
2. extract_source_frame.py：完全相同裁切 → 座標天然對齊
3. 本程式：移除 --flag-do-crop（信任我們的裁切），啟用 stitching
   → LivePortrait ROI 覆蓋到肩膀 → stitching 帶動肩膀運動
"""

import os
import uuid
import subprocess
import logging
import json
import shutil
import requests
from pathlib import Path
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# =========================
# 路徑設定
# =========================
BASE_DIR         = Path(__file__).parent
LIVEPORTRAIT_DIR = BASE_DIR.parent / "LivePortrait-main"
PYTHON_EXE       = LIVEPORTRAIT_DIR / "venv" / "Scripts" / "python.exe"
INFERENCE_PY     = LIVEPORTRAIT_DIR / "inference.py"
OUTPUT_DIR       = BASE_DIR / "static" / "video"
DRIVING_VIDEO    = BASE_DIR / "static" / "avatar" / "master_drive.mp4"

MUSETALK_SERVER  = 'http://localhost:7863'

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"LIVEPORTRAIT_DIR : {LIVEPORTRAIT_DIR}  exists={LIVEPORTRAIT_DIR.exists()}")
print(f"PYTHON_EXE       : {PYTHON_EXE}  exists={PYTHON_EXE.exists()}")
print(f"INFERENCE_PY     : {INFERENCE_PY}  exists={INFERENCE_PY.exists()}")
print(f"DRIVING_VIDEO    : {DRIVING_VIDEO}  exists={DRIVING_VIDEO.exists()}")
print(f"OUTPUT_DIR       : {OUTPUT_DIR}")


# =========================
# 工具：找 LivePortrait 輸出影片
# =========================
def find_liveportrait_output(output_dir: Path, source_stem: str) -> Path | None:
    candidates = [
        f for f in output_dir.glob("*.mp4")
        if "_concat" not in f.name and f.stem.startswith(source_stem)
    ]
    if not candidates:
        all_mp4 = [f for f in output_dir.glob("*.mp4") if "_concat" not in f.name]
        if all_mp4:
            candidates = [max(all_mp4, key=lambda f: f.stat().st_mtime)]
    return candidates[0] if candidates else None


# =========================
# 工具：FFprobe 偵測音訊時長
# =========================
def get_audio_duration(audio_path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", str(audio_path)],
            capture_output=True, text=True, encoding="utf-8"
        )
        for s in json.loads(r.stdout).get("streams", []):
            if "duration" in s:
                return float(s["duration"])
    except Exception as e:
        logger.warning(f"FFprobe 失敗：{e}")
    return 15.0


# =========================
# 核心推論
# =========================
def _run_liveportrait(avatar_path: Path, audio_path: Path, output_dir: Path) -> str:

    # ── 環境檢查 ──────────────────────────────────────────────────
    for label, p in [
        ("PYTHON_EXE",    PYTHON_EXE),
        ("INFERENCE_PY",  INFERENCE_PY),
        ("DRIVING_VIDEO", DRIVING_VIDEO),
        ("avatar",        avatar_path),
        ("audio",         audio_path),
    ]:
        if not p.exists():
            raise FileNotFoundError(f"找不到 {label}：{p}")

    # ── Step 1：LivePortrait 推論 ──────────────────────────────────
    logger.info("Step 1/3：LivePortrait 生成臉部動畫...")
    lp_temp_dir = output_dir / f"lp_temp_{uuid.uuid4().hex[:6]}"
    lp_temp_dir.mkdir(parents=True, exist_ok=True)

    lp_cmd = [
        str(PYTHON_EXE), str(INFERENCE_PY),
        "--source",     str(avatar_path),
        "--driving",    str(DRIVING_VIDEO),
        "--output-dir", str(lp_temp_dir),

        # ── 效能 ────────────────────────────────────────────────
        "--flag-use-half-precision",

        # ── pasteback：背景鎖死，只修改人物區域 ─────────────────
        # 防止背景漂移，來源照片的背景保持靜態
        "--flag-pasteback",

        # ── relative-motion：相對姿態傳播 ───────────────────────
        # 驅動影片的動作以「相對位移」套用到來源照片
        # 讓肩膀動作正確傳遞而非絕對座標映射
        "--flag-relative-motion",

        # ── stitching：身體縫合，解決鎖肩關鍵參數 ───────────────
        # 讓頭頸運動平滑延伸縫合到肩膀區域
        # 配合寬版裁切（肩膀在 ROI 內），stitching 才能真正帶動肩膀
        "--flag-stitching",

        # ── 不使用 do-crop：信任我們精確的裁切 ──────────────────
        # 來源照片和驅動影片已用相同參數裁切，座標天然對齊
        # 啟用 do-crop 反而會讓 LivePortrait 重新裁切，破壞對齊
        # "--flag-do-crop",  ← 刻意移除

        # ── 動作幅度：1.0 完整複製驅動影片幅度 ──────────────────
        "--driving-multiplier", "1.0",

        # ── 細部重定向 ──────────────────────────────────────────
        "--flag-eye-retargeting",
        "--flag-lip-retargeting",

        # ── 平滑化：讓動作有慣性感 ──────────────────────────────
        "--driving-smooth-observation-variance", "3e-7",
    ]

    result = subprocess.run(
        lp_cmd,
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        cwd=str(LIVEPORTRAIT_DIR),
        env={
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "OMP_NUM_THREADS": "4",
            "MKL_NUM_THREADS": "4"
            }
    )

    if result.returncode != 0:
        logger.error(f"LivePortrait stderr:\n{result.stderr[-2000:]}")
        raise RuntimeError(f"LivePortrait 推論失敗（returncode={result.returncode}）")

    lp_output = find_liveportrait_output(lp_temp_dir, avatar_path.stem)
    if not lp_output:
        raise RuntimeError(f"找不到 LivePortrait 輸出影片：{lp_temp_dir}")
    logger.info(f"LivePortrait 輸出：{lp_output.name}")

    # ── Step 2：偵測音訊時長 ──────────────────────────────────────
    audio_duration = get_audio_duration(audio_path)
    logger.info(f"Step 2/3：音訊時長 {audio_duration:.2f} 秒")

    # ── Step 3：FFmpeg 合併音訊 ───────────────────────────────────
    # 不使用任何全畫面位移濾鏡（rotate/crop/zoompan）
    # 全畫面濾鏡會讓背景跟著動，造成「鏡頭晃動」穿幫感
    # 身體動作完全由 LivePortrait stitching 負責
    # FFmpeg 只做：循環補長 + 合併音訊 + 輕微色彩提升
    logger.info("Step 3/4: FFmpeg merging audio...")

    lp_with_audio_name = f"lp_audio_{uuid.uuid4().hex[:8]}.mp4"
    lp_with_audio_path = output_dir / lp_with_audio_name

    color_vf = "hue=s=1.03,eq=contrast=1.02:brightness=0.01"

    cmd_final = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(lp_output),
        "-i", str(audio_path),
        "-t", str(audio_duration + 1.0),
        "-vf", color_vf,
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0", "-map", "1:a:0",
        str(lp_with_audio_path)
    ]
    result = subprocess.run(cmd_final, capture_output=True, text=True, encoding="utf-8")

    if result.returncode != 0:
        logger.warning(f"Color filter failed: {result.stderr[-300:]}")
        cmd_basic = [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", str(lp_output),
            "-i", str(audio_path),
            "-t", str(audio_duration + 1.0),
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            str(lp_with_audio_path)
        ]
        r2 = subprocess.run(cmd_basic, capture_output=True, text=True, encoding="utf-8")
        if r2.returncode != 0:
            raise RuntimeError(f"FFmpeg merge failed: {r2.stderr[-500:]}")

    # Step 4: MuseTalk lip sync
    logger.info("Step 4/4: MuseTalk lip sync...")
    final_name = _run_musetalk(lp_with_audio_path, audio_path, output_dir)

    # Cleanup
    try:
        shutil.rmtree(lp_temp_dir, ignore_errors=True)
        lp_with_audio_path.unlink(missing_ok=True)
    except Exception:
        pass

    logger.info(f"Pipeline complete: {final_name}")
    return final_name


def _run_musetalk(video_path: Path, audio_path: Path, output_dir: Path) -> str:
    try:
        response = requests.post(
            f"{MUSETALK_SERVER}/lipsync",
            json={
                "video_path": str(video_path),
                "audio_path": str(audio_path),
            },
            timeout=600
        )
        if response.status_code != 200:
            raise RuntimeError(f"MuseTalk error {response.status_code}: {response.text}")

        data = response.json()
        filename = data.get("filename")
        if not filename:
            raise RuntimeError(f"MuseTalk missing filename: {data}")

        musetalk_result = Path(os.environ.get(
            "MUSETALK_RESULTS_DIR",
            str(BASE_DIR.parent / "MuseTalk" / "results" / "output")
        )) / filename
        final_name = f"video_{uuid.uuid4().hex[:8]}.mp4"
        final_path = output_dir / final_name

        if musetalk_result.exists():
            shutil.copy2(str(musetalk_result), str(final_path))
        else:
            final_name = filename
            final_path = output_dir / final_name

        logger.info(f"MuseTalk complete: {final_name}")
        return final_name

    except requests.exceptions.ConnectionError:
        logger.warning("MuseTalk server not running (7863), skipping lip sync")
        final_name = f"video_{uuid.uuid4().hex[:8]}.mp4"
        shutil.copy2(str(video_path), str(output_dir / final_name))
        return final_name

    except Exception as e:
        logger.warning(f"MuseTalk failed: {e}, using LivePortrait output")
        final_name = f"video_{uuid.uuid4().hex[:8]}.mp4"
        shutil.copy2(str(video_path), str(output_dir / final_name))
        return final_name


# =========================
# 降級模式
# =========================
def _fallback_static_video(avatar_path: Path, audio_path: Path, output_dir: Path) -> str:
    logger.warning("⚠️ 降級靜態影片模式...")
    filename    = f"video_{uuid.uuid4().hex[:8]}.mp4"
    output_path = output_dir / filename
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(avatar_path),
        "-i", str(audio_path),
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p", "-shortest",
        str(output_path)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"靜態影片失敗：{r.stderr[-500:]}")
    logger.info(f"⚠️ 靜態影片完成：{filename}")
    return filename


# =========================
# 路由：生成影片
# =========================
@app.route('/generate', methods=['POST'])
def generate_video():
    try:
        data       = request.get_json() or {}
        req_avatar = data.get("avatar_path", "")
        req_audio  = data.get("audio_path", "")

        if not req_avatar or not req_audio:
            return jsonify({"error": "缺少 avatar_path 或 audio_path"}), 400

        avatar_path = (BASE_DIR / req_avatar
                       if not req_avatar.startswith("/") else Path(req_avatar))
        audio_path  = (BASE_DIR / req_audio
                       if not req_audio.startswith("/")  else Path(req_audio))

        if not audio_path.exists():
            return jsonify({"error": f"音訊檔不存在：{audio_path}"}), 400
        if not avatar_path.exists():
            return jsonify({"error": f"照片不存在：{avatar_path}"}), 400

        try:
            filename = _run_liveportrait(avatar_path, audio_path, OUTPUT_DIR)
        except Exception as e:
            logger.warning(f"LivePortrait 失敗，降級：{e}")
            filename = _fallback_static_video(avatar_path, audio_path, OUTPUT_DIR)

        return jsonify({"filename": filename, "path": f"/static/video/{filename}"})

    except Exception as e:
        logger.error(f"❌ /generate error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# =========================
# 路由：健康檢查
# =========================
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status":               "ok",
        "liveportrait_dir":     str(LIVEPORTRAIT_DIR),
        "liveportrait_exists":  LIVEPORTRAIT_DIR.exists(),
        "python_exe_exists":    PYTHON_EXE.exists(),
        "inference_py_exists":  INFERENCE_PY.exists(),
        "driving_video_exists": DRIVING_VIDEO.exists(),
        "output_dir":           str(OUTPUT_DIR),
    })


if __name__ == '__main__':
    print("LivePortrait Server starting on port 7861...")
    app.run(host='0.0.0.0', port=7861, debug=False, threaded=True)