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
video_service.py — 影片生成模組

流程：
  大師照片 (master.jpg) + 合成語音
    ↓ HTTP POST /generate
  liveportrait_server.py（Port 7861）
    ↓
  LivePortrait 動畫 + FFmpeg 合併音訊
    ↓
  最終 .mp4
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

LIVEPORTRAIT_SERVER_URL = "http://localhost:7861/generate"
REQUEST_TIMEOUT         = 900  # LivePortrait + MuseTalk 需要更多時間


# =========================
# 統一對外介面（app.py 呼叫此函式）
# =========================
def generate(audio_path: str, avatar_path: str, output_dir: str) -> str:
    """
    呼叫 liveportrait_server 生成影片，回傳最終影片檔名。
    若 server 未啟動或失敗，自動降級為靜態影片。
    """
    os.makedirs(output_dir, exist_ok=True)

    try:
        logger.info("Step 1/2：呼叫 LivePortrait Server 生成臉部動畫...")
        response = requests.post(
            LIVEPORTRAIT_SERVER_URL,
            json={
                "audio_path":  audio_path,
                "avatar_path": avatar_path,
            },
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            raise RuntimeError(f"LivePortrait Server 回傳錯誤 {response.status_code}: {response.text}")

        data     = response.json()
        filename = data.get("filename")

        if not filename:
            raise RuntimeError(f"LivePortrait Server 回傳缺少 filename：{data}")

        logger.info(f"✅ 影片生成完成：{filename}")
        return filename

    except requests.exceptions.ConnectionError:
        logger.warning("LivePortrait Server 未啟動（ConnectionError），降級為靜態影片")
        return _fallback_static_video(audio_path, avatar_path, output_dir)

    except Exception as e:
        logger.warning(f"LivePortrait 失敗：{e}，降級為靜態影片")
        return _fallback_static_video(audio_path, avatar_path, output_dir)


# =========================
# 降級模式：靜態照片 + 語音
# =========================
def _fallback_static_video(audio_path: str, avatar_path: str, output_dir: str) -> str:
    import uuid
    import subprocess

    filename    = f"video_{uuid.uuid4().hex[:8]}.mp4"
    output_path = os.path.join(output_dir, filename)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", avatar_path,
        "-i", audio_path,
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg 靜態影片失敗：{result.stderr[-500:]}")

    logger.info(f"⚠️ 靜態影片（降級模式）完成：{filename}")
    return filename