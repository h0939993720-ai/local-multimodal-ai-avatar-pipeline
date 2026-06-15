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

import os
import uuid
import io
import torch
import torchaudio
import numpy as np
from pathlib import Path
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================
# 路徑設定
# 結構說明：
#   桌面/fish-speech/   ← fish_server.py 所在位置（BASE_DIR）
#   桌面/project/       ← 專題主程式、音訊、頭像
# =========================
BASE_DIR       = Path(__file__).parent                          # 桌面/fish-speech/
PROJECT_DIR    = BASE_DIR.parent / "project"                    # 桌面/project/

CHECKPOINT_DIR = BASE_DIR / "checkpoints" / "fish-speech-1.5"
DECODER_PTH    = CHECKPOINT_DIR / "firefly-gan-vq-fsq-8x1024-21hz-generator.pth"

# ✅ 修正：REFERENCE_WAV 和 OUTPUT_DIR 指向 project 資料夾
REFERENCE_WAV  = PROJECT_DIR / "static" / "avatar" / "master_voice_5s.wav"
OUTPUT_DIR     = PROJECT_DIR / "static" / "audio"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 啟動時印出路徑，方便確認
print(f"BASE_DIR     : {BASE_DIR}")
print(f"PROJECT_DIR  : {PROJECT_DIR}")
print(f"REFERENCE_WAV: {REFERENCE_WAV}  exists={REFERENCE_WAV.exists()}")
print(f"OUTPUT_DIR   : {OUTPUT_DIR}")

device    = "cuda" if torch.cuda.is_available() else "cpu"
precision = torch.half if device == "cuda" else torch.bfloat16
print(f"Device: {device}")

import pyrootutils
pyrootutils.setup_root(__file__, indicator=".project-root", pythonpath=True)

from fish_speech.models.vqgan.inference import load_model as load_vqgan
from fish_speech.models.text2semantic.inference import launch_thread_safe_queue
from fish_speech.inference_engine import TTSInferenceEngine
from fish_speech.utils.schema import ServeTTSRequest

# =========================
# 統一推論參數（Warmup 與實際合成保持一致）
# ✅ 修正：原本 warmup=600、合成=500，不一致。統一為 600
# =========================
INFER_PARAMS = dict(
    max_new_tokens=300,      # ✅ 給足空間避免截斷
    chunk_length=150,        # ✅ 降低chunk長度：減少重複問題
    top_p=0.7,
    repetition_penalty=1.8,
    temperature=0.5,
    format="wav"
)

print("Loading VQGAN decoder...")
decoder_model = load_vqgan(
    config_name="firefly_gan_vq",
    checkpoint_path=str(DECODER_PTH),
    device=device
)

print("Loading LLM...")
llama_queue = launch_thread_safe_queue(
    checkpoint_path=str(CHECKPOINT_DIR),
    device=device,
    precision=precision,
    compile=False
)

print("Creating inference engine...")
engine = TTSInferenceEngine(
    llama_queue=llama_queue,
    decoder_model=decoder_model,
    precision=precision,
    compile=False
)

print("Warming up...")
list(engine.inference(ServeTTSRequest(
    text="Hello.",
    references=[],
    reference_id=None,
    **INFER_PARAMS
)))
print("Fish Speech v1.5 ready!")


# =========================
# 工具函式：讀取並預處理參考音訊
# =========================
def load_reference_audio(ref_path: Path, max_sec: int = 8) -> bytes:
    """
    載入參考音訊，強制裁切至 max_sec 秒、重採樣至 16kHz，回傳 bytes。
    """
    ref_audio, ref_sr = torchaudio.load(str(ref_path))

    # 裁切至最大秒數，防止 Token 爆掉
    max_samples = ref_sr * max_sec
    if ref_audio.shape[1] > max_samples:
        ref_audio = ref_audio[:, :max_samples]
        print(f"Trimmed reference audio to {max_sec} seconds")

    # 統一重採樣至 16kHz
    if ref_sr != 16000:
        ref_audio = torchaudio.functional.resample(ref_audio, ref_sr, 16000)
        ref_sr = 16000

    buf = io.BytesIO()
    torchaudio.save(buf, ref_audio, ref_sr, format="wav")
    return buf.getvalue()


# =========================
# 工具函式：合併所有推論 chunks 的音訊
# ✅ 修正：原本只取 result[0]，若推論分多個 chunk 會遺失後段音訊
# =========================
def merge_audio_chunks(result_list: list) -> tuple:
    """
    將 engine.inference 回傳的所有 chunk 合併為完整音訊。
    ✅ 新增：過濾無聲尾巴 chunk（能量低於閾值的靜音段）
    回傳 (sample_rate, audio_tensor)。
    """
    audio_chunks = []
    sr = None
    SILENCE_THRESHOLD = 0.001  # 能量低於此值視為無聲 chunk，直接跳過

    for i, item in enumerate(result_list):
        # 處理推論錯誤
        if hasattr(item, 'error') and item.error:
            raise RuntimeError(str(item.error))

        if hasattr(item, 'audio') and item.audio is not None:
            audio = item.audio

            if isinstance(audio, tuple):
                sr = audio[0]
                audio = audio[1]

            if isinstance(audio, np.ndarray):
                audio = torch.from_numpy(audio)

            if audio.ndim == 1:
                audio = audio.unsqueeze(0)

            # ✅ 過濾無聲 chunk：計算 RMS 能量，低於閾值跳過
            rms = audio.float().pow(2).mean().sqrt().item()
            if rms < SILENCE_THRESHOLD:
                print(f"  跳過無聲 chunk #{i}（RMS={rms:.6f}）")
                continue

            audio_chunks.append(audio)

    if not audio_chunks:
        raise RuntimeError("推論結果為空，未產生任何有效音訊")

    print(f"  有效 chunks: {len(audio_chunks)}/{len(result_list)}")
    merged = torch.cat(audio_chunks, dim=1) if len(audio_chunks) > 1 else audio_chunks[0]
    return sr, merged


# =========================
# 路由：語音合成
# =========================
@app.route('/synthesize', methods=['POST'])
def synthesize():
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        if not text:
            return jsonify({"error": "No text provided"}), 400

        if not REFERENCE_WAV.exists():
            return jsonify({"error": f"Reference audio not found: {REFERENCE_WAV}"}), 400

        # 預處理參考音訊
        ref_bytes = load_reference_audio(REFERENCE_WAV)

        # 執行推論（收集所有 chunks）
        result_list = list(engine.inference(ServeTTSRequest(
            text=text,
            references=[{
                "audio": ref_bytes,
                "text":  "所請人間佛教，也就是佛陀的教法。",
                "text":  "各位觀眾，大家平安吉祥。"
            }],
            reference_id=None,
            **INFER_PARAMS
        )))

        # ✅ 合併所有 chunks，不再只取第一個
        sr, merged_audio = merge_audio_chunks(result_list)

        # 儲存音訊
        filename    = f"reply_{uuid.uuid4().hex[:8]}.wav"
        output_path = OUTPUT_DIR / filename
        torchaudio.save(str(output_path), merged_audio, sr)

        print(f"✅ Synthesized: {filename}  (chunks: {len(result_list)}, sr: {sr})")
        return jsonify({
            "filename": filename,
            "path": f"/static/audio/{filename}"
        })

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# =========================
# 路由：健康檢查
# =========================
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "device": device,
        "reference_wav_exists": REFERENCE_WAV.exists(),
        "output_dir": str(OUTPUT_DIR)
    })


if __name__ == '__main__':
    print("Fish Speech Server starting on port 7860...")
    app.run(host='0.0.0.0', port=7860, debug=False)