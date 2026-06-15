# 本地化多模態 AI 數位人 Pipeline / Local-First Multimodal AI Digital Human Pipeline

> 本專案以「佛法數位大師」為示範主題，但核心 Pipeline 與主題無關，可依用途替換為客服、教學、虛擬主播等任何數位人角色。
>
> This project uses a "Buddhist Digital Master" persona as a demonstration, but the core pipeline is topic-agnostic — it can be repurposed for customer service, education, virtual streamers, or any digital human use case simply by swapping the avatar, voice, and knowledge base.

## 簡介 / Overview

本專案是一套多模態生成式 AI 流程，將文字問答（RAG）轉換為帶有語音與臉部動畫的數位人像影片。系統以多個獨立 Flask 微服務組成，方便個別開發、除錯與替換模型。

This project is a multimodal generative AI pipeline that turns a text Q&A response into a talking-head avatar video with synthesized speech and lip-synced facial animation. The system is composed of independent Flask microservices, allowing each stage to be developed, debugged, and swapped out individually.

## 為什麼選擇本地化部署？/ Why Local-First?

目前市面上多數 AI 數位人 MVP 本質上是依賴雲端 API（例如 OpenAI + ElevenLabs + HeyGen）的「體驗型展示」，這帶來三個現實代價：

Most AI digital-human MVPs on the market today are essentially cloud-API "demo experiences" (e.g. chaining OpenAI + ElevenLabs + HeyGen). This brings three real-world costs:

1. **失血型 Token 帳單 / Runaway token billing**：用戶量上升時，多模態（文字、語音、影像）的雲端計費呈指數級暴增，企業極易在獲利前被帳單抽乾。
   As usage scales, multimodal (text + audio + video) cloud billing grows exponentially — businesses can be drained by costs before turning a profit.

2. **資安與隱私蕩然無存 / No data privacy**：企業核心的 RAG 知識庫與內部資料必須上傳至第三方雲端，在軍工、醫療、機密金融等場景完全不適用。
   Core RAG knowledge bases and internal data must be sent to third-party clouds — unacceptable for defense, healthcare, or confidential financial use cases.

3. **過度依賴大廠母體 / Vendor lock-in risk**：一旦斷網、大廠改版或調整 API 售價，產品線將面臨降維打擊。
   A network outage, API deprecation, or pricing change from any upstream provider can break the entire product.

本專案以**本地端 / Local-first**的方式串接 RAG、TTS、臉部動畫與嘴型同步，所有推論皆在自有硬體上執行，主題與角色可依場景自由替換。

This project runs RAG, TTS, facial animation, and lip-sync entirely on local hardware. All inference happens on-premise, and the persona/topic can be freely swapped for any use case.

## ⚠️ 效能與延遲基準聲明 / Latency & Benchmark Statement

本系統定位為**「高精度多模態非同步渲染引擎（Asynchronous Heavy Inference Pipeline）」**，而非「即時語音對講機」。

This system is designed as a **high-fidelity multimodal asynchronous heavy-inference pipeline**, not a real-time voice intercom.

在 NVIDIA RTX 5070 Ti（16GB VRAM）本地端完全自行生成（無預錄動作庫）的環境下，輸入 60 字以內文本，總生成耗時約 **3~5 分鐘**。

On an NVIDIA RTX 5070 Ti (16GB VRAM), generating fully from scratch (no pre-recorded motion library) for input text under 60 characters takes approximately **3–5 minutes** end-to-end.

這是現階段開源多模態模型棒素推論的物理極限，本專案旨在提供最真實的端到端級聯延遲基準（Cascading Latency Benchmark）。若追求零延遲，請改用商業閉源 API。

This reflects the current physical limits of open-source multimodal inference at the pixel/sample level. This project aims to provide a realistic end-to-end cascading-latency benchmark. For zero-latency needs, use a commercial closed-source API instead.

## 系統架構 / Architecture

```
使用者提問 / User Question
   │
   ▼
app.py (Port 8080)
   │  RAG：BGE-M3 + FAISS 檢索 → GPT-4o-mini 生成回答
   │  RAG: BGE-M3 + FAISS retrieval → GPT-4o-mini answer generation
   ▼
tts_service.py ──► fish_server.py (Port 7860)
   │  Fish Speech v1.5 語音克隆合成
   │  Fish Speech v1.5 voice cloning synthesis
   ▼
video_service.py ──► liveportrait_server.py (Port 7861)
   │  LivePortrait 臉部/肩部動畫生成
   │  LivePortrait facial & shoulder animation
   │
   ├──► ffmpeg_server.py (Port 7862)
   │     影片裁切、合併音訊、截圖
   │     Video cropping, audio merging, frame extraction
   │
   └──► musetalk_server.py (Port 7863)
         MuseTalk 嘴型同步
         MuseTalk lip-sync
   │
   ▼
最終影片 / Final video (.mp4)
```

即時進度透過 SSE（Server-Sent Events）由 `/progress/<sid>` 推送至前端。
Real-time progress is streamed to the frontend via SSE at `/progress/<sid>`.

## 環境需求 / Requirements

### 🛡️ 部署高牆與架構防禦說明 / Deployment Barrier & Architecture Design

本系統**不提供單一的 `requirements.txt`**。因為 Fish Speech v1.5（依賴 PyTorch Nightly/CUDA 12.8+）與 MuseTalk（依賴舊版 diffusers/CUDA 12.1）在底層依賴庫上存在**物理排他性（Dependency Conflicts）**。

This system **does not provide a single `requirements.txt`**. Fish Speech v1.5 (PyTorch Nightly/CUDA 12.8+) and MuseTalk (older diffusers/CUDA 12.1) have **physically incompatible dependency chains** at the library level.

本專案刻意採用**「微服務群隔離部署（Microservices Environment Isolation）」**。使用者必須手動建立 4 個完全獨立的 Python 虛擬環境（venv），並透過指定 Port 進行非同步通訊。本專案不適合 AI 部署初學者，旨在為系統架構師提供 Windows 裸機下的極限解耦範例。

This project deliberately adopts **microservices environment isolation**: users must manually create 4 fully independent Python virtual environments (venvs) and communicate over dedicated ports asynchronously. This project is not aimed at AI-deployment beginners — it is intended as a reference for systems architects on extreme decoupling under bare-metal Windows.

本專案使用 **四個獨立的 Python 虛擬環境**，以避免套件版本衝突（特別是 PyTorch / FFmpeg 版本）：

This project uses **four separate Python virtual environments** to avoid dependency conflicts (especially PyTorch / FFmpeg versions):

| 服務 / Service | venv | Requirements 檔案 |
|---|---|---|
| `app.py`, `ffmpeg_server.py`, `liveportrait_server.py`, `tts_service.py`, `video_service.py` | venv312 | `requirements/requirements_main.txt` |
| `fish_server.py` | venv_fish | `requirements/requirements_fish.txt` |
| LivePortrait `inference.py`（由 `liveportrait_server.py` 呼叫 / called by `liveportrait_server.py`） | LivePortrait/venv | `requirements/requirements_liveportrait.txt` |
| `musetalk_server.py` | MuseTalk/venv | `requirements/requirements_musetalk.txt` |

> **PyTorch / FFmpeg 注意事項 / Note**：
> 主程式環境的 PyTorch 版本請依你的 GPU 自行安裝（RTX 50 系列 / Blackwell 架構需使用 nightly build）。詳見 `requirements_main.txt` 內的安裝說明。
>
> Install PyTorch separately according to your GPU (RTX 50-series / Blackwell requires a nightly build). See the install notes inside `requirements_main.txt`.

## 環境變數設定 / Environment Variables

複製 `.env.example` 為 `.env`，並填入你本機的實際路徑與金鑰：

Copy `.env.example` to `.env` and fill in your local paths and API key:

```
OPENAI_API_KEY=...
FFMPEG_PATH=...
FFPROBE_PATH=...
MUSETALK_RESULTS_DIR=...
```

## 角色替換 / Replacing the Avatar Character

1. 將 `static/avatar/master.jpg` 換成新角色的正面照片
2. 將 `static/avatar/master_voice_5s.wav` 換成新角色的 5 秒語音樣本
3. 將 `static/avatar/master_drive.mp4` 換成新的驅動影片
4. 重新執行 `prepare_driving_video.py` 與 `extract_source_frame.py`

1. Replace `static/avatar/master.jpg` with a front-facing photo of the new character
2. Replace `static/avatar/master_voice_5s.wav` with a 5-second voice sample of the new character
3. Replace `static/avatar/master_drive.mp4` with a new driving video
4. Re-run `prepare_driving_video.py` and `extract_source_frame.py`

## 原創工程調校與容錯機制 / Original Engineering Optimizations

1. **動態記憶體容錯（Graceful Degradation Fallback）**：系統內置硬體感知與超時保護。當宿主設備顯存（VRAM）溢出或子伺服器中斷時，系統會自動觸發 `_fallback_static_video` 機制，中斷全生成管線，無縫降級為「靜態頭像 + 音訊對齊」模式，確保系統工程級別的 100% 不崩潰率。

   The system has built-in hardware-awareness and timeout protection. If VRAM is exhausted or a sub-server connection fails, it automatically triggers the `_fallback_static_video` mechanism, short-circuiting the full generation pipeline and gracefully degrading to a "static avatar + aligned audio" mode — ensuring 100% pipeline availability at the engineering level.

2. **自迴歸 TTS 斷裂防禦（Anti-Repetition Segment Guard）**：針對開源 Fish Speech 長文本拼接易產生尾音復讀、接縫卡頓的工程傷害，本項目在 `tts_service.py` 中硬編碼字數閾值控制，強制在 60 字內進行完整單段推論，優化了 FFmpeg 後端音軌合成的穩定度。

   To address the well-known issue of open-source Fish Speech producing repeated trailing audio and stitching glitches when concatenating long-text segments, this project hardcodes a character-count threshold in `tts_service.py`, forcing single-pass inference for text under 60 characters — improving the stability of downstream FFmpeg audio composition.

## 已知問題 / Known Issues

### CPU 滿載問題 / CPU Saturation Issue

**現象 / Symptom**：執行 `/ask` 完整流程時（RAG → TTS → LivePortrait → FFmpeg → MuseTalk），CPU 使用率衝到 93%，記憶體佔用約 25/31.3 GB（80%），整個流程耗時數分鐘。

When running the full `/ask` pipeline (RAG → TTS → LivePortrait → FFmpeg → MuseTalk), CPU usage spikes to 93%, memory usage reaches ~25/31.3 GB (80%), and the entire pipeline takes several minutes.

**已知原因 / Known Causes**：

- LivePortrait 推論為主要負載來源，`liveportrait_server.py` 呼叫 `inference.py` 時未限制執行緒數。
  LivePortrait inference is the main load source; `liveportrait_server.py` calls `inference.py` without thread limits.
- MuseTalk 的 `batch_size=8` 也會增加負載。
  MuseTalk's `batch_size=8` also adds to the load.
- 硬體為 Intel Core Ultra 5 225（CPU 算力有限），主要瓶頸推測是 CPU 而非 GPU（RTX 5070 Ti 在當時負載僅 59%~68%）。
  Hardware is an Intel Core Ultra 5 225 (limited CPU performance); the bottleneck is suspected to be CPU rather than GPU (RTX 5070 Ti load was only 59%~68% during the same run).

**已嘗試的緩解措施 / Mitigations Already Applied**：

目前已對 `liveportrait_server.py` 的 `subprocess.run` 呼叫，以及 `app.py` 啟動時，加入環境變數 `OMP_NUM_THREADS=4`、`MKL_NUM_THREADS=4` 限制執行緒數，但 CPU 滿載問題**仍未完全解決**。

Thread-limiting environment variables (`OMP_NUM_THREADS=4`, `MKL_NUM_THREADS=4`) have already been added both to the `subprocess.run` call in `liveportrait_server.py` and at `app.py` startup, but the CPU saturation issue **has not been fully resolved**.

**尚未採用的優化方案（優先度低）/ Further Options Not Yet Adopted (Low Priority)**：

1. `musetalk_server.py` 的 `batch_size` 從 8 降為 4。
   Lower `batch_size` from 8 to 4 in `musetalk_server.py`.
2. 評估將部分推論步驟改為非同步/排隊執行，避免多個重負載步驟同時搶佔 CPU。
   Consider running heavy inference steps asynchronously/queued to avoid multiple CPU-heavy steps competing simultaneously.

### 📌 多行程 CPU 競爭與作業系統調度觀測 / Multi-Process CPU Saturation & OS Scheduling Observation

**技術現象描述 / Technical Observation**：當 `liveportrait_server.py` 調用核心推論時，即便已在程式碼端強制鎖定線程（`OMP_NUM_THREADS=4` / `MKL_NUM_THREADS=4`），Windows 核心調度器（Windows Kernel Scheduler）仍會出現短暫的 CPU 執行緒搶佔（CPU Saturation）現象。

When `liveportrait_server.py` invokes core inference, even though thread pinning is enforced at the code level (`OMP_NUM_THREADS=4` / `MKL_NUM_THREADS=4`), the Windows Kernel Scheduler still exhibits brief CPU thread contention (saturation).

**架構性結論 / Architectural Conclusion**：此現象屬於**作業系統層面的多重獨立 Python 行程（Heterogeneous Python Processes）高吞吐 I/O 競爭問題**。在單機單卡環境下，此為系統並行（Concurrency）的正常物理衍生代價，並不影響最終影片的像素渲染與音訊對齊。本團隊將此列為「**單卡多模態管線操作系統級調度**」的已知邊界現象，後續研究可朝向 Linux Cgroups 進行硬體進程強隔離。

This is a known OS-level resource-contention characteristic of running multiple heterogeneous, high-throughput Python processes on a single GPU/single machine. It is a normal, physical side effect of concurrency in this configuration and does **not** affect the pixel rendering or audio-alignment correctness of the final video. The team classifies this as a known boundary condition of "single-GPU multimodal pipeline OS-level scheduling." Future work could pursue hard process isolation via Linux Cgroups.

## 授權 / License

- 程式碼 / Code: Apache License 2.0
- 文件 / Documentation: CC BY 4.0

## 研究價值聲明 / Research Value Statement

詳見 `research_value_statement.docx`，涵蓋遊戲 NPC 引擎、VTuber 自動化、文化保存與企業應用等商業化潛力評估。

See `research_value_statement.docx` for an assessment of commercial application potential, including game NPC engines, VTuber automation, cultural preservation, and enterprise use cases.
