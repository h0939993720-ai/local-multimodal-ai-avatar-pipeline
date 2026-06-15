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
extract_source_frame.py — 從驅動影片截取來源照片

【關鍵原則】
來源照片（master.jpg）必須與驅動影片（master_drive.mp4）
使用完全相同的裁切參數，確保：
  1. 臉部座標天然對齊 → LivePortrait 不需要額外校正
  2. 肩膀都在 ROI 內 → stitching 能帶動肩膀
  3. 比例一致 → 不會有臉部變形

放置位置：桌面/project/extract_source_frame.py
執行方式：extract_frame.bat 或 python extract_source_frame.py
"""

import subprocess
import shutil
import sys
from pathlib import Path

import requests

FFMPEG_SERVER = "http://localhost:7862"

# =========================
# 設定
# =========================
BASE_DIR      = Path(__file__).parent
DRIVING_VIDEO = BASE_DIR / "static" / "avatar" / "master_drive.mp4"
OUTPUT_PATH   = BASE_DIR / "static" / "avatar" / "master.jpg"
BACKUP_PATH   = BASE_DIR / "static" / "avatar" / "master_original.jpg"
PREVIEW_DIR   = BASE_DIR / "static" / "avatar" / "preview_frames"

# ── 截取時間（預設第 20 秒，嘴巴微閉、表情自然）────────────────────
EXTRACT_TIME  = "00:00:20"

# ── 裁切參數（與 prepare_driving_video.py 完全相同）─────────────────
# 原圖 2340x1080，寬版上半身裁切
CROP_FILTER   = "crop=iw*0.55:ih*0.72:iw*0.22:ih*0.05"
OUTPUT_W      = 512
OUTPUT_H      = 308

# 注意：這裡直接對驅動影片截幀，驅動影片已經裁切過了
# 所以只需要 scale，不需要再 crop
FRAME_VF      = f"scale={OUTPUT_W}:{OUTPUT_H}"


def backup_original():
    if OUTPUT_PATH.exists() and not BACKUP_PATH.exists():
        shutil.copy2(OUTPUT_PATH, BACKUP_PATH)
        print(f"✅ 已備份原始照片：{BACKUP_PATH.name}")


def extract_frame(time_str: str = EXTRACT_TIME):
    """從驅動影片截取單幀作為來源照片"""
    if not DRIVING_VIDEO.exists():
        raise FileNotFoundError(f"找不到驅動影片：{DRIVING_VIDEO}")

    try:
        response = requests.post(
            f"{FFMPEG_SERVER}/extract_frame",
            json={
                "video_path":  str(DRIVING_VIDEO),
                "output_path": str(OUTPUT_PATH),
                "time":        time_str,
                "width":       OUTPUT_W,
                "height":      OUTPUT_H,
            },
            timeout=30
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError("❌ FFmpeg Server 未啟動！請先執行 start_ffmpeg.bat")
    if response.status_code != 200:
        raise RuntimeError(f"FFmpeg Server 錯誤：{response.text}")
    print(f"✅ 來源照片截取完成：{OUTPUT_PATH}")
    print(f"   尺寸：{OUTPUT_W}x{OUTPUT_H}（與驅動影片比例一致）")


def preview_frames():
    """截取多個時間點供選擇，選嘴巴微閉、表情自然的幀"""
    PREVIEW_DIR.mkdir(exist_ok=True)

    times = [
        "00:00:05", "00:00:08", "00:00:10", "00:00:13",
        "00:00:15", "00:00:18", "00:00:20", "00:00:25",
    ]
    print("截取預覽幀中...")
    for t in times:
        t_safe = t.replace(":", "-")
        out = PREVIEW_DIR / f"frame_{t_safe}.jpg"
        try:
            requests.post(
                f"{FFMPEG_SERVER}/extract_frame",
                json={
                    "video_path":  str(DRIVING_VIDEO),
                    "output_path": str(out),
                    "time":        t,
                    "width":       OUTPUT_W,
                    "height":      OUTPUT_H,
                },
                timeout=30
            )
        except Exception:
            pass
        print(f"  → {out.name}")

    print(f"\n✅ 預覽幀已存至：{PREVIEW_DIR}")
    print("選一張嘴巴微閉、正面、表情自然的幀")
    print("記下時間（如 00:00:20），修改 EXTRACT_TIME 後重新執行")


if __name__ == "__main__":
    print("=" * 50)
    print("  來源照片截取工具")
    print("=" * 50)

    if "--preview" in sys.argv:
        preview_frames()
    else:
        try:
            backup_original()
            extract_frame(EXTRACT_TIME)
            print()
            print("=" * 50)
            print(f"✅ master.jpg 已更新（第 {EXTRACT_TIME} 秒）")
            print(f"   原始備份：master_original.jpg")
            print()
            print("若效果不理想，先預覽多個時間點：")
            print("   python extract_source_frame.py --preview")
            print("=" * 50)
        except Exception as e:
            print(f"\n❌ 錯誤：{e}")
            import traceback
            traceback.print_exc()