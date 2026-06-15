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
musetalk_server.py - MuseTalk lip sync Flask server
Port: 7863

Flow:
  liveportrait_server.py output video + audio
    -> POST /lipsync
  musetalk_server.py (this file, Port 7863)
    -> MuseTalk inference
    -> return lip-synced video filename
"""

import os
import sys
import uuid
import copy
import glob
import pickle
import re
import logging
import shutil
import subprocess
from pathlib import Path
from argparse import Namespace

import cv2
import numpy as np
import torch
import imageio
from flask import Flask, request, jsonify
from transformers import WhisperModel
from dotenv import load_dotenv

load_dotenv()

# Add MuseTalk to path
PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# =========================
# Path settings
# =========================
MODELS_DIR  = PROJECT_DIR / "models"
OUTPUT_DIR  = PROJECT_DIR / "results" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# Load models (once at startup)
# =========================
logger.info("Loading MuseTalk models...")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
logger.info(f"Device: {device}")

from musetalk.utils.utils import load_all_model
from musetalk.utils.audio_processor import AudioProcessor
from musetalk.utils.blending import get_image
from musetalk.utils.face_parsing import FaceParsing
from musetalk.utils.preprocessing import get_landmark_and_bbox, read_imgs, coord_placeholder, get_bbox_range
from musetalk.utils.utils import get_file_type, get_video_fps, datagen

vae, unet, pe = load_all_model(
    unet_model_path=str(MODELS_DIR / "musetalkV15" / "unet.pth"),
    vae_type="sd-vae-ft-mse",
    unet_config=str(MODELS_DIR / "musetalkV15" / "musetalk.json"),
    device=device
)

# Use float16 for RTX 5070 Ti performance
pe        = pe.half().to(device)
vae.vae   = vae.vae.half().to(device)
unet.model = unet.model.half().to(device)
weight_dtype = torch.float16

timesteps = torch.tensor([0], device=device)

audio_processor = AudioProcessor(
    feature_extractor_path=str(MODELS_DIR / "whisper")
)
whisper = WhisperModel.from_pretrained(str(MODELS_DIR / "whisper"))
whisper = whisper.to(device=device, dtype=weight_dtype).eval()
whisper.requires_grad_(False)

logger.info("All models loaded successfully")


# =========================
# Core inference function
# =========================
@torch.no_grad()
def run_lipsync(video_path: str, audio_path: str, output_dir: Path) -> str:
    args = Namespace(
        result_dir   = str(output_dir),
        fps          = 25,
        batch_size   = 4,
        output_vid_name = "",
        use_saved_coord = False,
        audio_padding_length_left  = 2,
        audio_padding_length_right = 2,
        version      = "v15",
        extra_margin = 10,
        parsing_mode = "jaw",
        left_cheek_width  = 90,
        right_cheek_width = 90,
    )

    input_basename  = Path(video_path).stem
    audio_basename  = Path(audio_path).stem
    output_basename = f"{input_basename}_{audio_basename}"

    temp_dir = output_dir / "v15"
    temp_dir.mkdir(parents=True, exist_ok=True)

    result_img_save_path = temp_dir / output_basename
    result_img_save_path.mkdir(parents=True, exist_ok=True)

    crop_coord_save_path = output_dir / f"{input_basename}.pkl"

    output_vid_name = str(temp_dir / f"{output_basename}.mp4")

    # ── Extract frames ──────────────────────────────────────────
    logger.info("Extracting frames from video...")
    save_dir_full = temp_dir / input_basename
    save_dir_full.mkdir(parents=True, exist_ok=True)

    reader = imageio.get_reader(video_path)
    for i, im in enumerate(reader):
        imageio.imwrite(str(save_dir_full / f"{i:08d}.png"), im)
    reader.close()

    input_img_list = sorted(glob.glob(str(save_dir_full / "*.[jpJP][pnPN]*[gG]")))
    fps = get_video_fps(video_path)

    # ── Resample audio to 16kHz for whisper (via FFmpeg) ────────
    logger.info("Checking audio sample rate...")
    _resampled_path = str(Path(audio_path).with_suffix("")) + "_16k.wav"
    _ffmpeg_bin = os.environ.get("FFMPEG_PATH", "ffmpeg")
    _r = subprocess.run(
        [_ffmpeg_bin, "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", _resampled_path],
        capture_output=True, text=True
    )
    if _r.returncode == 0:
        audio_path_16k = _resampled_path
        logger.info("Resampled audio to 16000Hz")
    else:
        audio_path_16k = audio_path
        logger.warning(f"FFmpeg resample failed: {_r.stderr[-100:]}")

    # ── Extract audio features ───────────────────────────────────
    logger.info("Extracting audio features...")
    whisper_input_features, librosa_length = audio_processor.get_audio_feature(audio_path_16k)
    whisper_chunks = audio_processor.get_whisper_chunk(
        whisper_input_features,
        device,
        weight_dtype,
        whisper,
        librosa_length,
        fps=fps,
        audio_padding_length_left=args.audio_padding_length_left,
        audio_padding_length_right=args.audio_padding_length_right,
    )

    # ── Get face landmarks ───────────────────────────────────────
    logger.info("Getting face landmarks...")
    if crop_coord_save_path.exists() and args.use_saved_coord:
        with open(str(crop_coord_save_path), "rb") as f:
            coord_list = pickle.load(f)
        frame_list = read_imgs(input_img_list)
    else:
        coord_list, frame_list = get_landmark_and_bbox(input_img_list, 0)
        with open(str(crop_coord_save_path), "wb") as f:
            pickle.dump(coord_list, f)

    fp = FaceParsing(
        left_cheek_width=args.left_cheek_width,
        right_cheek_width=args.right_cheek_width
    )

    # ── Encode latents ───────────────────────────────────────────
    logger.info("Encoding latents...")
    input_latent_list = []
    for bbox, frame in zip(coord_list, frame_list):
        if bbox == coord_placeholder:
            continue
        x1, y1, x2, y2 = bbox
        y2 = min(y2 + args.extra_margin, frame.shape[0])
        crop_frame = cv2.resize(frame[y1:y2, x1:x2], (256, 256),
                                interpolation=cv2.INTER_LANCZOS4)
        input_latent_list.append(vae.get_latents_for_unet(crop_frame))

    frame_list_cycle   = frame_list + frame_list[::-1]
    coord_list_cycle   = coord_list + coord_list[::-1]
    latent_list_cycle  = input_latent_list + input_latent_list[::-1]

    # ── Inference ────────────────────────────────────────────────
    logger.info("Running inference...")
    video_num  = len(whisper_chunks)
    batch_size = args.batch_size
    gen = datagen(
        whisper_chunks=whisper_chunks,
        vae_encode_latents=latent_list_cycle,
        batch_size=batch_size,
        delay_frame=0,
        device=device,
    )
    res_frame_list = []
    from tqdm import tqdm
    for whisper_batch, latent_batch in tqdm(gen, total=int(np.ceil(video_num / batch_size))):
        audio_feature_batch = pe(whisper_batch)
        latent_batch = latent_batch.to(dtype=weight_dtype)
        pred_latents = unet.model(latent_batch, timesteps,
                                  encoder_hidden_states=audio_feature_batch).sample
        recon = vae.decode_latents(pred_latents)
        res_frame_list.extend(recon)

    # ── Paste back ───────────────────────────────────────────────
    logger.info("Pasting results back...")
    for i, res_frame in enumerate(res_frame_list):
        bbox     = coord_list_cycle[i % len(coord_list_cycle)]
        ori_frame = copy.deepcopy(frame_list_cycle[i % len(frame_list_cycle)])
        if bbox == coord_placeholder:
            continue
        x1, y1, x2, y2 = bbox
        y2 = min(y2 + args.extra_margin, ori_frame.shape[0])
        try:
            res_frame = cv2.resize(res_frame.astype(np.uint8), (x2 - x1, y2 - y1))
        except Exception:
            continue
        combine_frame = get_image(ori_frame, res_frame, [x1, y1, x2, y2],
                                  mode=args.parsing_mode, fp=fp)
        cv2.imwrite(str(result_img_save_path / f"{i:08d}.png"), combine_frame)

    # ── Compose video ────────────────────────────────────────────
    logger.info("Composing final video...")
    pattern = re.compile(r"\d{8}\.png")
    files   = sorted(
        [f for f in os.listdir(str(result_img_save_path)) if pattern.match(f)],
        key=lambda x: int(x.split(".")[0])
    )
    images = [imageio.imread(str(result_img_save_path / f)) for f in files]

    temp_vid = str(output_dir / "temp_muse.mp4")
    imageio.mimwrite(temp_vid, images, "FFMPEG", fps=25,
                     codec="libx264", pixelformat="yuv420p")

    # ── Merge audio ──────────────────────────────────────────────
    from moviepy import VideoFileClip, AudioFileClip
    video_clip = VideoFileClip(temp_vid)
    audio_clip = AudioFileClip(audio_path)
    video_clip = video_clip.with_audio(audio_clip)
    video_clip.write_videofile(output_vid_name, codec="libx264",
                               audio_codec="aac", fps=25, logger=None)
    video_clip.close()
    audio_clip.close()

    if os.path.exists(temp_vid):
        os.remove(temp_vid)

    # ── Copy to final output ─────────────────────────────────────
    final_name = f"lipsync_{uuid.uuid4().hex[:8]}.mp4"
    final_path = str(output_dir / final_name)
    shutil.copy2(output_vid_name, final_path)

    # Cleanup temp frames
    shutil.rmtree(str(save_dir_full), ignore_errors=True)
    shutil.rmtree(str(result_img_save_path), ignore_errors=True)

    logger.info(f"Lip sync complete: {final_name}")
    return final_name


# =========================
# Route: lip sync
# POST /lipsync
# Body: { "video_path": "...", "audio_path": "..." }
# =========================
@app.route("/lipsync", methods=["POST"])
def lipsync():
    try:
        data       = request.get_json() or {}
        video_path = data.get("video_path", "")
        audio_path = data.get("audio_path", "")

        if not video_path or not audio_path:
            return jsonify({"error": "Missing video_path or audio_path"}), 400
        if not Path(video_path).exists():
            return jsonify({"error": f"Video not found: {video_path}"}), 400
        if not Path(audio_path).exists():
            return jsonify({"error": f"Audio not found: {audio_path}"}), 400

        filename = run_lipsync(video_path, audio_path, OUTPUT_DIR)
        return jsonify({"filename": filename, "path": f"/results/output/{filename}"})

    except Exception as e:
        logger.error(f"/lipsync error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# =========================
# Route: health check
# =========================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":       "ok",
        "device":       str(device),
        "models_dir":   str(MODELS_DIR),
        "output_dir":   str(OUTPUT_DIR),
        "cuda_available": torch.cuda.is_available(),
        "gpu":          torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A",
    })


if __name__ == "__main__":
    logger.info("MuseTalk Server starting on port 7863...")
    app.run(host="0.0.0.0", port=7863, debug=False, threaded=False)