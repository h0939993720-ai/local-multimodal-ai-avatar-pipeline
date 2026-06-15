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
audio_preprocess.py — 錄音雜音清洗工具（一次性執行）

用途：將有背景雜音的大師錄音清洗為乾淨的參考音訊，
      供 CosyVoice 2 進行聲線克隆。

使用方式：
    python audio_preprocess.py --input 原始錄音.mp3 --output static/avatar/master_voice.wav

安裝：
    pip install demucs pydub
    （Demucs 會自動下載模型，約 1~2 GB，首次執行需要網路）
"""

import os
import argparse
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def remove_noise(input_path: str, output_path: str):
    """
    使用 Demucs htdemucs_ft 模型分離人聲與背景雜音。
    Demucs 會輸出四個音軌：vocals（人聲）、drums、bass、other
    我們只取 vocals（純人聲）作為克隆參考音訊。
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"找不到輸入檔案：{input_path}")

    output_dir = os.path.dirname(output_path) or "."
    os.makedirs(output_dir, exist_ok=True)
    temp_dir = os.path.join(output_dir, "demucs_temp")

    logger.info(f"開始雜音清洗：{input_path}")
    logger.info("首次執行會下載 Demucs 模型（約 300MB），請耐心等候...")

    # 呼叫 Demucs 分離人聲
    cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals",    # 只分離人聲 vs 其他，速度更快
        "-n", "htdemucs_ft",# 使用 fine-tuned 版本，人聲品質最好
        "--mp3",
        "--out", temp_dir,
        input_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Demucs 錯誤：{result.stderr}")

    # 找到輸出的人聲檔案
    input_stem = os.path.splitext(os.path.basename(input_path))[0]
    vocals_path = os.path.join(temp_dir, "htdemucs_ft", input_stem, "vocals.mp3")

    if not os.path.exists(vocals_path):
        raise FileNotFoundError(f"Demucs 輸出找不到：{vocals_path}")

    # 轉換為 CosyVoice 需要的格式（16kHz, mono, 16-bit WAV）
    logger.info("轉換為 CosyVoice 相容格式（16kHz, mono）...")
    convert_cmd = [
        "ffmpeg", "-y",
        "-i", vocals_path,
        "-ar", "16000",         # 取樣率 16kHz
        "-ac", "1",             # 單聲道
        "-sample_fmt", "s16",   # 16-bit
        output_path
    ]
    result = subprocess.run(convert_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg 轉換錯誤：{result.stderr}")

    logger.info(f"✅ 清洗完成！輸出：{output_path}")
    logger.info("此檔案可直接用於 CosyVoice 2 聲線克隆。")

    # 清理暫存
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="大師錄音雜音清洗工具")
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="原始錄音檔路徑（支援 .mp3, .wav, .m4a 等格式）"
    )
    parser.add_argument(
        "--output", "-o",
        default="static/avatar/master_voice.wav",
        help="輸出路徑（預設：static/avatar/master_voice.wav）"
    )
    args = parser.parse_args()
    remove_noise(args.input, args.output)


if __name__ == "__main__":
    main()