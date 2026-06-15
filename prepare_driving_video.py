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
prepare_driving_video.py — 下載並處理 LivePortrait 驅動影片

步驟：
  1. yt-dlp 下載 YouTube 影片
  2. FFmpeg 裁切出最佳片段（大師正面開示段落）
  3. 調整解析度與格式，存成 master_drive.mp4

放置位置：桌面/project/prepare_driving_video.py
執行方式：venv312\Scripts\activate → python prepare_driving_video.py
"""

import subprocess
import shutil
import sys
import requests
from pathlib import Path

FFMPEG_SERVER = "http://localhost:7862"

# =========================
# 設定
# =========================
YOUTUBE_URL   = "https://youtu.be/M2wM_mUzQf4"
OUTPUT_NAME   = "master_drive.mp4"
BASE_DIR      = Path(__file__).parent
TEMP_DIR      = BASE_DIR / "static" / "avatar" / "temp_download"
AVATAR_DIR    = BASE_DIR / "static" / "avatar"
FINAL_PATH    = AVATAR_DIR / OUTPUT_NAME

TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ── 時間設定 ──────────────────────────────────────────────────────────
CLIP_START    = "00:00:15"   # 跳過片頭黑畫面
CLIP_DURATION = "45"         # 取 45 秒開示段落

# ── 裁切參數（實測校正，上半身寬版）─────────────────────────────────
# 原圖 2340x1080：
#   x = iw*0.22 = 514  → 從大師左側開始
#   y = ih*0.05 = 54   → 去掉頂部台標
#   w = iw*0.55 = 1287 → 包含完整雙肩
#   h = ih*0.72 = 778  → 去掉底部字幕
# 效果：臉佔畫面約 60%，雙肩完整入鏡
# LivePortrait ROI 能覆蓋到肩膀 → 有效解決鎖肩
CROP_FILTER   = "crop=iw*0.55:ih*0.72:iw*0.22:ih*0.05"

# ── 輸出尺寸 ──────────────────────────────────────────────────────────
# 保持寬版比例 512x309（不強制正方形）
# LivePortrait 支援非正方形輸入，強制正方形反而壓縮肩膀
OUTPUT_W      = 512
OUTPUT_H      = 308   # 512 * (0.72/0.55) ≈ 669，但實際比例 777/1287 ≈ 0.604 → 309


def ensure_ytdlp():
    try:
        import yt_dlp
        print("✅ yt-dlp 已安裝")
    except ImportError:
        print("📦 安裝 yt-dlp...")
        subprocess.run([sys.executable, "-m", "pip", "install", "yt-dlp"], check=True)
        print("✅ yt-dlp 安裝完成")


def download_video() -> Path:
    raw_path = TEMP_DIR / "raw.mp4"
    if raw_path.exists():
        print(f"⏭️  已有下載檔案，跳過下載：{raw_path}")
        return raw_path

    print(f"⬇️  下載影片：{YOUTUBE_URL}")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]",
        "--merge-output-format", "mp4",
        "-o", str(raw_path),
        YOUTUBE_URL
    ]
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        raise RuntimeError("yt-dlp 下載失敗")
    print(f"✅ 下載完成：{raw_path}")
    return raw_path


def process_video(raw_path: Path) -> Path:
    print(f"✂️  裁切片段：{CLIP_START} 起，{CLIP_DURATION} 秒")
    print(f"   裁切參數：{CROP_FILTER}")
    print(f"   輸出尺寸：{OUTPUT_W}x{OUTPUT_H}（寬版，含雙肩）")
    print(f"   呼叫 FFmpeg Server：{FFMPEG_SERVER}")

    try:
        response = requests.post(
            f"{FFMPEG_SERVER}/process_video",
            json={
                "input_path":  str(raw_path),
                "output_path": str(FINAL_PATH),
                "ss":          CLIP_START,
                "duration":    CLIP_DURATION,
                "crop":        CROP_FILTER,
                "width":       OUTPUT_W,
                "height":      OUTPUT_H,
            },
            timeout=300
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError("❌ FFmpeg Server 未啟動！請先執行 start_ffmpeg.bat")

    if response.status_code != 200:
        raise RuntimeError(f"FFmpeg Server 錯誤：{response.text}")

    data = response.json()
    size = data.get("size", 0)
    print(f"✅ 驅動影片完成：{FINAL_PATH}（{size//1024} KB）")
    return FINAL_PATH


def cleanup():
    try:
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
        print("🧹 暫存清理完成")
    except Exception:
        pass


if __name__ == "__main__":
    print("=" * 50)
    print("  驅動影片準備工具（寬版上半身版本）")
    print("=" * 50)
    try:
        ensure_ytdlp()
        raw = download_video()
        process_video(raw)
        cleanup()
        print()
        print("=" * 50)
        print(f"✅ 完成！驅動影片已存至：{FINAL_PATH}")
        print(f"   尺寸：{OUTPUT_W}x{OUTPUT_H}，含完整雙肩")
        print("   接下來執行 extract_frame.bat 重新截取來源照片")
        print("=" * 50)
    except Exception as e:
        print(f"\n❌ 錯誤：{e}")
        import traceback
        traceback.print_exc()