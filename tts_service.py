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

import os
import uuid
import asyncio
import logging
import subprocess

logger = logging.getLogger(__name__)

# =========================
# 切換開關
# "fish"  = Fish Speech 聲線克隆
# "edge"  = edge-TTS 備用
# =========================
TTS_MODE = "fish"
FISH_SPEECH_URL = "http://localhost:7860/synthesize"

# 每段最大字數（控制單次合成時間在 20 秒以內）
MAX_SEGMENT_LEN = 200


# =========================
# 文字切段函式
# =========================
def split_text(text: str, max_len: int = MAX_SEGMENT_LEN) -> list:
    """
    依句號、問號、歎號切段，每段不超過 max_len 字。
    確保每段語意完整，不在句子中間截斷。
    """
    import re
    sentences = re.split(r'(?<=[。？！])', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    segments = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) <= max_len:
            current += sent
        else:
            if current:
                segments.append(current)
            # 單句超過 max_len，強制截斷
            while len(sent) > max_len:
                segments.append(sent[:max_len])
                sent = sent[max_len:]
            current = sent
    if current:
        segments.append(current)

    return segments if segments else [text[:max_len]]


# =========================
# edge-TTS 合成
# =========================
async def _edge_tts_async(text: str, output_path: str):
    import edge_tts
    communicate = edge_tts.Communicate(
        text,
        voice="zh-TW-YunJheNeural",
        rate="-25%",
        pitch="-8Hz"
    )
    await communicate.save(output_path)


def _synthesize_edge_segment(text: str, output_dir: str) -> str:
    filename = f"seg_{uuid.uuid4().hex[:8]}.mp3"
    output_path = os.path.join(output_dir, filename)
    asyncio.run(_edge_tts_async(text, output_path))
    return output_path


# =========================
# Fish Speech 單段合成
# ✅ 修正：fish_server 回傳的 filename 是純檔名，不含路徑
#    這裡直接用 output_dir 拼接即可，避免路徑重複問題
# =========================
def _synthesize_fish_segment(text: str, output_dir: str) -> str:
    import requests
    try:
        response = requests.post(
            FISH_SPEECH_URL,
            json={"text": text},
            timeout=120
        )
        if response.status_code != 200:
            raise RuntimeError(f"Fish Speech error {response.status_code}: {response.text}")

        data = response.json()

        # ✅ fish_server.py 回傳的是 {"filename": "reply_xxxx.wav", "path": "/static/audio/..."}
        # 這裡只取 filename，再搭配本地 output_dir 組成完整路徑
        filename = data.get("filename")
        if not filename:
            raise RuntimeError(f"Fish Speech 回傳缺少 filename 欄位：{data}")

        full_path = os.path.join(output_dir, filename)

        # ✅ 確認檔案確實存在（fish_server 已儲存到 OUTPUT_DIR）
        if not os.path.exists(full_path):
            raise RuntimeError(f"Fish Speech 音訊檔案不存在：{full_path}")

        return full_path

    except Exception as e:
        logger.warning(f"Fish Speech failed: {e}，切換到 edge-TTS 備用")
        return _synthesize_edge_segment(text, output_dir)


# =========================
# FFmpeg 串接多段音訊
# =========================
def _concat_audio(segment_paths: list, output_dir: str) -> str:
    """用 FFmpeg 把多段音訊串接成一個完整檔案"""
    if len(segment_paths) == 1:
        # 只有一段直接改名回傳
        final_name = f"reply_{uuid.uuid4().hex[:8]}.wav"
        final_path = os.path.join(output_dir, final_name)
        os.rename(segment_paths[0], final_path)
        return final_name

    # 建立 FFmpeg concat 清單
    list_path = os.path.join(output_dir, f"concat_{uuid.uuid4().hex[:6]}.txt")
    with open(list_path, 'w', encoding='utf-8') as f:
        for p in segment_paths:
            # ✅ 路徑使用正斜線，相容 Windows / Linux
            safe_p = p.replace("\\", "/")
            f.write(f"file '{safe_p}'\n")

    final_name = f"reply_{uuid.uuid4().hex[:8]}.wav"
    final_path = os.path.join(output_dir, final_name)

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        final_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    # 清理暫存
    try:
        os.remove(list_path)
        for p in segment_paths:
            if os.path.exists(p) and p != final_path:
                os.remove(p)
    except Exception:
        pass

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg concat error: {result.stderr}")

    logger.info(f"✅ 串接 {len(segment_paths)} 段完成 -> {final_name}")
    return final_name


# =========================
# 統一對外介面
# =========================
def synthesize(text: str, output_dir: str) -> str:
    """
    完整文字合成語音，回傳最終音訊檔名。
    自動切段、分別合成、FFmpeg 串接。
    """
    os.makedirs(output_dir, exist_ok=True)

    # ✅ 強制單段保護：60 字以內直接整段合成，不切段
    # 避免切段後 FFmpeg 串接產生接縫或復讀
    if len(text) <= 60:
        logger.info(f"文字 {len(text)} 字，強制單段合成（不切段）")
        segments = [text]
    else:
        segments = split_text(text)
    logger.info(f"切分為 {len(segments)} 段：{[s[:20]+'...' if len(s)>20 else s for s in segments]}")

    segment_paths = []
    for i, seg in enumerate(segments):
        logger.info(f"合成第 {i+1}/{len(segments)} 段：{seg[:30]}...")
        if TTS_MODE == "fish":
            path = _synthesize_fish_segment(seg, output_dir)
        else:
            path = _synthesize_edge_segment(seg, output_dir)
        segment_paths.append(path)
        logger.info(f"第 {i+1} 段完成：{os.path.basename(path)}")

    final_name = _concat_audio(segment_paths, output_dir)
    logger.info(f"✅ 完整語音合成完成：{final_name}")
    return final_name