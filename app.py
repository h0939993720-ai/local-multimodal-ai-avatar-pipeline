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

from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import warnings
import os
import chardet
import numpy as np
from sentence_transformers import SentenceTransformer
import faiss
from openai import OpenAI
from dotenv import load_dotenv
from collections import deque
import logging
import io
import sys
import threading
import time
import json as _json

# 強制 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# =========================
# 基本設定
# =========================
warnings.filterwarnings("ignore")
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["FAISS_OMP_NUM_THREADS"] = "4"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# =========================
# API KEY（從 .env 讀取）
# =========================
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("❌ 找不到 OPENAI_API_KEY，請確認 .env 已設定。")

app = Flask(__name__)
CORS(app)
client = OpenAI(api_key=api_key)

# =========================
# 進度狀態（SSE）
# =========================
_progress_store = {}  # session_id -> {"pct": 0, "msg": ""}

def set_progress(sid, pct, msg):
    _progress_store[sid] = {"pct": pct, "msg": msg}

# =========================
# 路徑設定
# =========================
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_PATH  = os.path.join(BASE_DIR, "data.txt")
AUDIO_DIR  = os.path.join(BASE_DIR, "static", "audio")
VIDEO_DIR  = os.path.join(BASE_DIR, "static", "video")
AVATAR_DIR = os.path.join(BASE_DIR, "static", "avatar")

for d in [AUDIO_DIR, VIDEO_DIR, AVATAR_DIR]:
    os.makedirs(d, exist_ok=True)

# =========================
# System Prompt（知識邊界）
# =========================
SYSTEM_PROMPT = """
你是星雲大師的數位法語助手，專門依據星雲大師的著作與開示，以慈悲、沉穩的語氣回答信眾問題。

【核心規範——請嚴格遵守】
1. 只能依據下方「參考資料」中的內容作答，不可自行推測、創作或補充大師未說過的話。
2. 若參考資料中找不到相關開示，請明確回覆：
   「大師未有此方面的具體開示，建議您親洽寺院法師請益，或參閱星雲大師全集。」
3. 不得對信眾的個人問題（健康、財運、姻緣、事業吉凶）給予預測、保證或算命式的回答。
4. 回答語氣應沉穩、慈悲，符合人間佛教精神，避免過於口語或現代網路用語。
5. 若信眾問及大師是否在世，請溫和說明此為 AI 法語助手，非大師本人。
6. 引用開示時，可於末尾附上出處書名（若不確定出處則不要虛構）。
7. 【重要】回答長度嚴格控制在 60 字以內，以一到兩句話完整表達，不超過此限制。
   語句必須在句號處結束，不可用逗號結尾或留下未完成的句子。
   若信眾需要更多說明，引導他們參閱《星雲大師全集》相關章節。

【身份聲明】
此系統為 AI 模擬輔助，非星雲大師本人，僅供法語學習與參考之用。
"""

# =========================
# 語義切分
# =========================
def split_passages(text, chunk_size=300, overlap=50):
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    sentences = []
    for para in paragraphs:
        for sent in para.replace('？','？\n').replace('！','！\n').replace('。','。\n').split('\n'):
            s = sent.strip()
            if s:
                sentences.append(s)
    chunks, current = [], ""
    for sent in sentences:
        if len(current) + len(sent) <= chunk_size:
            current += sent
        else:
            if current:
                chunks.append(current.strip())
            current = (current[-overlap:] if len(current) >= overlap else "") + sent
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if len(c) > 10]

# =========================
# 讀取語料 & 建立索引
# =========================
with open(DATA_PATH, "rb") as f:
    raw = f.read()
    encoding = chardet.detect(raw)["encoding"]
logger.info(f"偵測到編碼: {encoding}")

with open(DATA_PATH, "r", encoding=encoding, errors="replace") as f:
    data = f.read()

passages = split_passages(data)
logger.info(f"共切分出 {len(passages)} 個語義段落")

logger.info("載入 BGE-M3 模型中...")
embed_model = SentenceTransformer("BAAI/bge-m3")

embeddings = embed_model.encode(passages, show_progress_bar=True).astype("float32")
faiss.normalize_L2(embeddings)
faiss_index = faiss.IndexFlatIP(embeddings.shape[1])
faiss_index.add(embeddings)
logger.info(f"FAISS 索引建立完成，共 {faiss_index.ntotal} 筆")

# =========================
# 對話歷史
# =========================
conversation_history = deque(maxlen=10)

def add_to_history(role: str, content: str):
    conversation_history.append({"role": role, "content": content})

def get_history() -> list:
    return list(conversation_history)

# =========================
# RAG 問答
# =========================
def answer_question(query: str, top_k: int = 5, similarity_threshold: float = 0.45) -> str:
    query_emb = embed_model.encode([query]).astype("float32")
    faiss.normalize_L2(query_emb)
    distances, indices = faiss_index.search(query_emb, top_k)

    relevant = []
    for score, idx in zip(distances[0], indices[0]):
        flag = "✅" if score >= similarity_threshold else "❌"
        logger.info(f"  {flag} 相似度 {score:.3f} | {passages[idx][:40]}...")
        if score >= similarity_threshold and idx < len(passages):
            relevant.append(passages[idx])

    context = "\n\n".join(relevant) if relevant else "（資料庫中未找到相關開示）"

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += get_history()
    messages.append({
        "role": "user",
        "content": f"【參考資料】\n{context}\n\n【信眾提問】\n{query}"
    })

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.4,
            max_tokens=300  # ✅ 修正：原本 800 過寬，與 80 字限制不符，300 token 約 150 中文字，安全邊界
        )
        reply = response.choices[0].message.content.strip()

        # ✅ 後處理截斷：強制確保不超過 60 字
        # 目標：單段 TTS 合成（不切段），約 15~25 秒語音，符合 30 秒輸出標準
        MAX_REPLY_LEN = 60
        if len(reply) > MAX_REPLY_LEN:
            # 優先在句號處斷開，保持語意完整
            cut = reply[:MAX_REPLY_LEN].rfind('。')
            if cut != -1:
                reply = reply[:cut + 1]
            else:
                # 沒有句號，找逗號斷開
                cut = reply[:MAX_REPLY_LEN].rfind('，')
                reply = reply[:cut] + '。' if cut != -1 else reply[:MAX_REPLY_LEN] + '。'
            logger.info(f"回答已截斷至 {len(reply)} 字（原始超過 {MAX_REPLY_LEN} 字）")

        add_to_history("user", query)
        add_to_history("assistant", reply)
        return reply
    except Exception as e:
        logger.error(f"OpenAI API Error: {e}")
        return "系統暫時無法回應，請稍後再試。"

# =========================
# 路由：主頁
# =========================
@app.route('/')
def index():
    return render_template('frontend.html')

# =========================
# 路由：文字問答（原有 /send，保持相容）
# =========================
@app.route('/send', methods=['POST'])
def send():
    try:
        req_data = request.get_json()
        if not req_data:
            return jsonify({"reply": "請求格式錯誤。"}), 400
        user_message = req_data.get('message', '').strip()
        if not user_message:
            return jsonify({"reply": "請輸入訊息。"})
        reply = answer_question(user_message)
        return jsonify({"reply": reply})
    except Exception as e:
        logger.error(f"Route /send error: {e}")
        return jsonify({"reply": "系統異常，請稍後再試。"}), 500

# =========================
# 路由：一鍵完整流程（文字→語音→影片）
# =========================
@app.route('/ask', methods=['POST'])
def ask():
    """
    整合路由，前端統一呼叫此路由：
    1. RAG 生成文字回答
    2. TTS 合成大師聲音（需 tts_service.py 就緒）
    3. LivePortrait + MuseTalk 生成影片（需 video_service.py 就緒）
    回傳：reply 文字、audio_url、video_url（未就緒時為 null）
    """
    try:
        req_data = request.get_json()
        user_message = req_data.get('message', '').strip()
        if not user_message:
            return jsonify({"error": "請輸入訊息"}), 400

        import uuid as _uuid
        sid = req_data.get('sid', _uuid.uuid4().hex[:8])
        set_progress(sid, 5, "正在檢索法語知識庫...")

        # Step 1: RAG 文字回答（一定執行）
        reply_text = answer_question(user_message)
        result = {"reply": reply_text, "audio_url": None, "video_url": None, "sid": sid}
        set_progress(sid, 20, "法語已生成，合成大師聲音...")

        # Step 2: TTS（tts_service.py 就緒後自動啟用）
        try:
            from tts_service import synthesize
            audio_filename = synthesize(reply_text, output_dir=AUDIO_DIR)
            result["audio_url"] = f"/static/audio/{audio_filename}"
            set_progress(sid, 45, "語音合成完成，生成臉部動畫...")

            # Step 3: 影片（video_service.py 就緒後自動啟用）
            try:
                from video_service import generate
                avatar_path = os.path.join(AVATAR_DIR, "master.jpg")
                if os.path.exists(avatar_path):
                    audio_path = os.path.join(AUDIO_DIR, audio_filename)
                    set_progress(sid, 50, "LivePortrait 生成頭部動畫...")
                    video_filename = generate(audio_path, avatar_path, output_dir=VIDEO_DIR)
                    result["video_url"] = f"/static/video/{video_filename}"
                    set_progress(sid, 95, "影片合成完成！")
                else:
                    logger.warning("找不到 static/avatar/master.jpg，略過影片生成。")
            except ImportError:
                logger.info("video_service 尚未安裝，略過影片生成。")

        except ImportError:
            logger.info("tts_service 尚未安裝，略過語音合成。")

        set_progress(sid, 100, "完成")
        return jsonify(result)

    except Exception as e:
        logger.error(f"Route /ask error: {e}")
        return jsonify({"error": str(e)}), 500

# =========================
# 路由：SSE 進度推送
# =========================
@app.route('/progress/<sid>', methods=['GET'])
def progress_stream(sid):
    from flask import Response
    def generate():
        last = -1
        timeout = 0
        while timeout < 300:
            current = _progress_store.get(sid, {"pct": 0, "msg": "準備中"})
            pct = current["pct"]
            msg = current["msg"]
            if pct != last:
                yield f"data: {_json.dumps({'pct': pct, 'msg': msg}, ensure_ascii=False)}\n\n"
                last = pct
            if pct >= 100:
                break
            time.sleep(0.5)
            timeout += 0.5
    return Response(generate(), mimetype='text/event-stream',
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# =========================
# 路由：favicon（避免 404）
# =========================
@app.route('/favicon.ico')
def favicon():
    return '', 204

# =========================
# 路由：重置對話
# =========================
@app.route('/reset', methods=['POST'])
def reset():
    conversation_history.clear()
    return jsonify({"status": "ok", "message": "對話歷史已清除。"})

# =========================
# 路由：診斷工具
# =========================
@app.route('/debug', methods=['GET'])
def debug():
    """
    使用方式：https://www.ccchen.site:8080/debug?q=人間佛教是什麼
    查看實際相似度分數，幫助調整 similarity_threshold。
    """
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"error": "請提供參數 ?q=你的問題"}), 400
    query_emb = embed_model.encode([query]).astype("float32")
    faiss.normalize_L2(query_emb)
    distances, indices = faiss_index.search(query_emb, 10)
    results = []
    for rank, (score, idx) in enumerate(zip(distances[0], indices[0]), 1):
        results.append({
            "rank":    rank,
            "score":   round(float(score), 4),
            "passage": passages[idx][:80] + ("..." if len(passages[idx]) > 80 else "")
        })
    return jsonify({"query": query, "current_threshold": 0.45, "top10": results})

# =========================
# 路由：健康檢查
# =========================
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status":          "ok",
        "passages_count":  len(passages),
        "index_total":     int(faiss_index.ntotal),
        "history_turns":   len(conversation_history) // 2,
        "embedding_model": "BAAI/bge-m3"
    })

# =========================
# HTTPS 啟動
# =========================
SSL_CERT = os.environ.get("SSL_CERT", "www.ccchen.site-crt.pem")
SSL_KEY  = os.environ.get("SSL_KEY",  "www.ccchen.site-key.pem")

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=8080,
        debug=False,
        # ssl_context=(SSL_CERT, SSL_KEY)
    )