# AI 協作 Debug 指南 / AI Collaboration Debug Guide

> 本文件有兩個目的：
> 1. 提供給 AI 協作者（Claude、ChatGPT、Gemini 等）的專案上下文摘要，讓 AI 快速理解架構決策、已知雷區與歷史修復記錄。
> 2. 教導使用者**如何正確地與 AI 協作 debug**，而不是單純地複製錯誤訊息等待答案。
>
> This document serves two purposes:
> 1. A project context summary for AI collaborators to quickly understand architectural decisions, known pitfalls, and fix history.
> 2. A guide teaching users **how to collaborate effectively with AI for debugging**, rather than just pasting error messages and waiting for answers.

---

## 🧠 Debug 協作方法論 / Debug Collaboration Methodology

### 核心觀念：複製錯誤訊息不等於 debug

大多數使用者遇到問題的第一反應是把錯誤訊息複製給 AI，好一點的會加上截圖。這種做法的問題是：**AI 只能根據你給的資訊猜測，而你給的資訊往往只是症狀，不是根因。**

最常見的結果是 AI 給出「治標」的修法（改一個參數、加一個 try/except），問題表面上消失了，但根因還在，下次換個條件又會爆。

**正確的協作流程是：你負責收集現象與排查範圍，AI 負責提出下一層的假設。**

Most users paste error messages to AI as the first step — better ones add screenshots. The problem: **AI can only guess based on what you provide, and what you provide is usually the symptom, not the root cause.**

The typical result is a "symptomatic fix" (tweak a parameter, add a try/except) — the surface problem disappears, but the root cause remains and will resurface under different conditions.

**The correct collaboration flow: you collect observations and elimination results; AI proposes hypotheses for the next unexplored layer.**

---

### Step 1：先定位問題層級，再找 AI / Locate the layer before asking AI

遇到問題時，先自己回答這三個問題：

Before asking AI, answer these three questions yourself:

**Q1：是哪個服務出問題？**
- 看哪個終端機視窗有紅字
- 或依序呼叫各服務的 `/health` 端點確認（見下方「健康檢查 SOP」）

**Q2：是什麼時候出問題？**
- 啟動時就炸 → 通常是環境問題（套件缺失、路徑錯誤、venv 搞混）
- 執行中才炸 → 通常是輸入資料問題或推論邏輯問題

**Q3：這一層正常嗎？**
- 把問題從「輸出端」往「輸入端」逐層往上找
- **當你排查了某一層、確認沒問題，這個資訊本身就是給 AI 最有價值的線索**

---

### Step 2：給 AI 的標準資訊格式 / Standard information format for AI

提問時請提供以下資訊，**缺少任何一項都會讓 AI 只能猜測**：

```
【問題描述】
一句話描述現象（不是錯誤訊息，是你觀察到的行為）

【觸發條件】
什麼操作之後出現？第一次出現還是一直出現？

【已排查的範圍】
我檢查了 A → 正常
我檢查了 B → 正常
我檢查了 C → 沒有明顯異常
（這是最重要的部分）

【錯誤訊息 / Traceback】
完整文字（不是截圖）

【相關檔案與 venv】
哪個 .py 檔案 / 哪個 venv / 哪個 Port
```

> **【架構限制宣告（複製給 AI 時必帶）】**
> ※ 警告 AI：本專案為 5 Ports 獨立微服務架構，任何涉及跨 Port 的資料流必須透過 HTTP 傳輸。請勿建議直接 import 其他服務的 Python 模組；任何 FFmpeg 操作必須調用 Port 7862。
>
> 這段宣告的用途：防止 AI 陷入「用 AIGC 語法搬運、給出單機縫合怪建議」的盲目慣性。每次開新對話時，將本段與 Traceback 一起貼給 AI。

---

### Step 3：健康檢查 SOP / Health Check SOP

遇到任何問題，先跑一遍這個清單再找 AI：

```
□ fish_server      http://localhost:7860/health
□ liveportrait    http://localhost:7861/health
□ ffmpeg_server   http://localhost:7862/health
□ musetalk        http://localhost:7863/health
□ app (主程式)    http://localhost:8080/health

□ RAG 是否正常    http://localhost:8080/debug?q=測試問題
□ .env 是否完整   OPENAI_API_KEY、FFMPEG_PATH、MUSETALK_RESULTS_DIR 都有填？
□ 啟動順序是否正確 fish → ffmpeg → musetalk → liveportrait → app
```

如果某個 `/health` 沒有回應 → 那個服務沒啟動，或該 venv 啟動時報錯了。**先解決沒啟動的服務，再繼續排查其他問題。**

---

### Step 4：常見誤判模式 / Common Misdiagnosis Patterns

| 看到的現象 | 直覺誤判 | 實際根因 |
|---|---|---|
| CPU 使用率 90%+ | 「程式寫爛了、效能有問題」 | 多行程 OS 調度的正常邊界，不影響輸出品質（見 Known Issues） |
| 輸出是靜態影片（沒有動畫） | 「LivePortrait 壞了」 | 某個子服務沒啟動，系統自動降級到 `_fallback_static_video` |
| 影片有聲音但嘴沒動 | 「MuseTalk 失敗了」 | MuseTalk Server（Port 7863）沒啟動，liveportrait 降級跳過了 lip-sync |
| 語音被截斷 | 「TTS 合成有 bug」 | 回覆文字超過 60 字，被 `MAX_REPLY_LEN` 截斷後再合成，是設計行為 |
| 看到 `ConnectionError` | 「程式有 bug」 | 依賴的子服務還沒啟動，啟動順序不對 |
| 看到 `Warning` 就去修 | 「有警告代表有問題」 | 很多 Warning 是正常現象（mediapipe 棄用警告、torch nightly 警告等），貿然修掉反而引入新問題。只處理 `Error`，`Warning` 先觀察 |
| 子服務回傳 fallback 結果 | 「這個功能壞了」 | `_fallback_static_video` 是設計行為，代表某個上游服務未啟動，先跑健康檢查 SOP |
| 第一次推論跑很慢、畫面沒動靜 | 「程式卡死了」 | Fish Speech、MuseTalk 首次載入模型有 warmup 期，屬正常現象，等待即可 |
| CUDA out of memory | 「batch_size 太大，去改推論參數」 | 有時根因是上一次推論沒有釋放 VRAM，先重啟對應服務，再觀察是否復現 |

---

### 真實案例：音訊復讀問題的線性排查過程 / Real Case: Linear Debugging of Audio Repetition

這是本專案開發過程中最具代表性的 debug 案例，完整記錄「線性思維」如何找到根因。

**症狀 / Symptom**：合成語音出現尾音復讀、內容重複

**第一輪排查（輸出層）**：
- 檢查 `tts_service.py` 的切段邏輯 → 正常
- 檢查 FFmpeg 串接的 concat 清單 → 正常
- 檢查輸出音訊波形截圖 → 看起來正常，但播放有復讀

**關鍵轉折**：表層排查全部正常 → 往**輸入端的上一層**找

此時正確的提問方式不是「我的語音有復讀，幫我修」，而是：
> 「我已確認切段邏輯和 FFmpeg 串接都正常，但語音仍然有復讀。根因可能在推論的哪一層？」

**Gemini 提出假設**：問題可能出在底層音訊輸入（參考音訊），而不是推論邏輯本身。

**第二輪排查（輸入層）**：
- 檢查參考音訊 `master_voice_5s.wav` 的實際時長 → **發現實際長度約 267 秒（並非 5 秒）**
- 267 秒的參考音訊遠超出 Fish Speech 模型的負荷上限
- 模型爆出 **21 個 chunks**，大量 chunks 為低能量雜訊或重複片段
- 這些 chunks 被合併後造成聽覺上的復讀現象

**解法 / Fix**：
- `fish_server.py` 的 `load_reference_audio()` 加入 `max_sec=8` 強制裁切參考音訊至 8 秒
- `merge_audio_chunks()` 加入 RMS 能量過濾（`SILENCE_THRESHOLD=0.001`），過濾低能量雜訊 chunks

**這個案例說明的線性思維 / The linear thinking this case demonstrates**：

```
症狀（輸出端復讀）
    ↓ 排查輸出層 → 正常
    ↓ 排查推論邏輯 → 正常
    ↓ 往輸入端找
    ↓ 發現輸入資料本身超出模型能力上限
    ↓ 根因確認 → 修正輸入 → 問題解決
```

> **教訓**：症狀在輸出端，根因在輸入端。當你排查了所有「看得見的邏輯」都正常，下一步要問的是：**「傳進去的資料，本身就對嗎？」**

> **為什麼第一輪 AI 無法診斷出根因？** 因為 AI 預設使用者提供的是「合規的 5 秒標準音訊」，它在推論代碼時不具備對物理資產（Asset Profile）的自動觀測能力——它只看到程式邏輯是完整的，看不到你餵進去的那個檔案實際上是 267 秒。
>
> **核心思維轉變**：當代碼邏輯在 AI 眼中是「完美的」，物理世界卻是「崩潰的」，問題 100% 出在輸入資產的物理屬性超出了模型的邊界。這時候不是繼續讓 AI 看代碼，而是讓你自己去量測輸入資產的實際規格。

---

---

## 專案基本上下文 / Project Context

| 項目 | 說明 |
|---|---|
| 作業系統 | Windows（所有路徑、.bat、subprocess 均為 Windows 慣例） |
| GPU | NVIDIA RTX 5070 Ti（Blackwell 架構，16GB VRAM） |
| CPU | Intel Core Ultra 5 225（CPU 算力有限，非瓶頸討論的主角） |
| Python 環境 | 四個獨立 venv（詳見下方）；**不存在單一的大 venv** |
| PyTorch 版本 | 主程式與 LivePortrait venv：nightly build（`+cu128`）；Fish Speech venv：`2.8.0+cu128`；MuseTalk venv：nightly build |
| FFmpeg | 系統安裝版 8.1，路徑由 `FFMPEG_PATH` 環境變數控制；**venv312 內的舊版 FFmpeg 4.2.2 絕對不能用**，會觸發 encoder EOF 錯誤 |
| 對外服務 | OpenAI GPT-4o-mini（僅 RAG 回覆生成用，其餘推論全本地） |

---

## 四個 venv 的職責邊界 / venv Responsibility Map

**這是本專案最核心的架構決策，AI 協作者必須牢記：任何建議都不能打破這個邊界。**

| venv | 位置 | 負責的程式碼 | Port |
|---|---|---|---|
| `venv312` | `project/venv312/` | `app.py`、`ffmpeg_server.py`、`liveportrait_server.py`、`tts_service.py`、`video_service.py` | 8080、7861、7862 |
| `venv_fish` | `fish-speech/venv_fish/` | `fish_server.py` | 7860 |
| `LivePortrait/venv` | `LivePortrait-main/venv/` | `inference.py`（由 `liveportrait_server.py` 透過 subprocess 呼叫） | — |
| `MuseTalk/venv` | `MuseTalk/venv/` | `musetalk_server.py` | 7863 |

**為什麼不合併？**  
Fish Speech 依賴 PyTorch Nightly/CUDA 12.8+，MuseTalk 依賴舊版 diffusers/CUDA 12.1，底層物理排他，無法共存於同一環境。LivePortrait 的 `inference.py` 只能在其自己的 venv 內執行，因此以 `subprocess.run` 方式從 `venv312` 呼叫。

---

## 服務呼叫圖 / Service Call Graph

```
用戶 HTTP Request
    │
    ▼
app.py :8080
    │
    ├─► tts_service.py（同 venv312，直接 import）
    │       │
    │       └─► fish_server.py :7860（HTTP POST /synthesize）
    │
    └─► video_service.py（同 venv312，直接 import）
            │
            └─► liveportrait_server.py :7861（HTTP POST /generate）
                    │
                    ├─► subprocess → LivePortrait/venv/inference.py
                    │
                    ├─► ffmpeg_server.py :7862（HTTP POST /merge_audio）
                    │
                    └─► musetalk_server.py :7863（HTTP POST /lipsync）
                                │
                                └─► MuseTalk/venv（直接 import，同行程）
```

**重要**：`ffmpeg_server.py` 是用**系統 Python**（不在任何 venv 內）啟動的獨立行程，設計初衷是完全繞開 venv 內的舊版 FFmpeg。

---

## 已知雷區與歷史修復記錄 / Known Pitfalls & Fix History

### 🔴 雷區一：FFmpeg 版本衝突

- **現象**：影片合併時出現 encoder EOF 錯誤、輸出檔案損毀或大小為 0
- **根因**：`venv312` 環境內的 FFmpeg 是 4.2.2 舊版，與 `libx264`+`yuv420p` 現代參數不相容
- **解法**：`ffmpeg_server.py` 以系統 Python 獨立啟動，透過 `FFMPEG_PATH` 環境變數指向系統安裝的 FFmpeg 8.1
- **AI 協作注意**：若建議在 venv312 內直接呼叫 ffmpeg，一定會觸發此問題。任何 FFmpeg 操作必須透過 Port 7862 的 HTTP 介面，或確認使用系統 FFmpeg 路徑

### 🔴 雷區二：影片寬高必須為偶數

- **現象**：FFmpeg 使用 `libx264`+`yuv420p` 編碼時，若影片寬或高為奇數，直接報錯失敗
- **解法**：所有裁切尺寸統一使用 `scale=trunc(iw/2)*2:trunc(ih/2)*2` 強制轉為偶數；`_fallback_static_video` 與 `process_video` 已內建此保護
- **AI 協作注意**：若建議修改裁切參數（crop、scale、width/height 數值），必須確認輸出為偶數

### 🔴 雷區三：Fish Speech 多 chunk 音訊遺失

- **現象**：合成出的語音被截斷，只有前幾個字，後段內容消失
- **根因**：原本只取推論結果的第一個 chunk（`result[0]`），若推論分多個 chunk 輸出，後段音訊全部遺失
- **解法**：`fish_server.py` 的 `merge_audio_chunks()` 函式收集所有 chunks 並過濾無聲段（RMS 低於 `SILENCE_THRESHOLD=0.001`），合併為完整音訊
- **AI 協作注意**：修改 `fish_server.py` 的推論邏輯時，不能改回只取 `result[0]` 的寫法

### 🔴 雷區四：MuseTalk 的 mediapipe 遷移

- **現象**：啟動時 `ImportError` 或臉部偵測失敗
- **根因**：mediapipe API 在新版本有 breaking change，MuseTalk 原始程式碼使用舊版 API
- **解法**：已手動遷移至新版 mediapipe API，修改後的版本在 `musetalk_server.py` 內
- **AI 協作注意**：若建議降版 mediapipe，需確認不引入其他衝突

### 🔴 雷區五：MuseTalk Python 版本限制

- **現象**：MuseTalk venv 在 Python 3.12 下建置失敗，部分相依套件（如 `mmcv`）不支援
- **根因**：MuseTalk 生態系對 Python 3.12 支援不完整
- **解法**：MuseTalk venv 使用 **Python 3.10** 建立
- **AI 協作注意**：若建議升級 MuseTalk venv 的 Python 版本至 3.11+，需先驗證 mmcv、mmpose、mmdet 的相容性

### 🟡 雷區六：CPU 滿載（已知邊界，非 bug）

- **現象**：執行完整流程時 CPU 使用率達 93%，耗時 3~5 分鐘
- **根因**：多個異質 Python 行程並行競爭 CPU；Windows Kernel Scheduler 即便設定了 `OMP_NUM_THREADS=4`/`MKL_NUM_THREADS=4` 仍會有短暫搶佔
- **已套用緩解**：`app.py` 啟動時與 `liveportrait_server.py` 的 subprocess 呼叫中均已加入執行緒限制
- **結論**：這是單卡多模態管線的 OS 調度邊界現象，不影響輸出品質，暫不繼續深究
- **AI 協作注意**：不需要建議「改用非同步框架」或「重構為 async/await」，這會破壞現有的微服務架構；若要深究，方向是 Linux Cgroups 硬體隔離

### 🟡 雷區七：moviepy API 版本差異

- **現象**：`musetalk_server.py` 使用 moviepy 合併音訊時出現 `AttributeError`
- **根因**：moviepy 2.x 的 API 與 1.x 不相容（`set_audio` → `with_audio` 等）
- **解法**：已更新至 moviepy 2.x API（`video_clip.with_audio(audio_clip)`）
- **AI 協作注意**：若看到 moviepy 相關程式碼，確認使用的是 2.x API，不要建議回滾至 1.x 寫法

### 🟡 雷區八：音訊採樣率對齊

- **現象**：MuseTalk 嘴型與語音輕微不同步
- **根因**：Fish Speech 輸出的 WAV 採樣率不一定是 Whisper 期望的 16kHz
- **解法**：`musetalk_server.py` 在送入 Whisper 前，透過 FFmpeg 強制重採樣至 16kHz（`-ar 16000 -ac 1`）
- **AI 協作注意**：此重採樣步驟是必要的，不可移除

---

## 關鍵設計決策 / Key Design Decisions

這些決策是**刻意為之**，AI 協作者在提出修改建議前應先確認不會推翻它們：

1. **LivePortrait 移除 `--flag-do-crop`**：來源照片與驅動影片已用相同參數預裁切，座標天然對齊。啟用 `do-crop` 反而會讓 LivePortrait 重新裁切，破壞對齊，造成肩膀鎖死問題。
2. **全程使用 `--flag-pasteback`**：確保背景完全靜止，只修改人物區域，防止背景漂移。
3. **RAG 相似度門檻 `0.45`**：防止 LLM 在無相關語料時幻覺生成。這是調校後的經驗值，修改前請先用 `/debug?q=` 觀察分數分佈。
4. **TTS 60 字單段保護**：回覆強制截斷在 60 字，確保 Fish Speech 在單段模式（不切段）下完成推論，避免多段接縫產生復讀與卡頓。
5. **`_fallback_static_video` 降級機制**：這不是暫時的佔位碼，是刻意設計的系統容錯層。任何重構不應移除此機制。
6. **SSE 進度推送與至簡資料流**：前端透過 SSE 接收即時進度，`_progress_store` 為 Python 內置記憶體字典（In-memory dict）。**拒絕引入 Redis、Celery 或資料庫等外部重型組件**。本系統定位為「單機高吞吐 Pipeline 引擎」，資料流在進程間以 Binary 快照形式瞬時傳遞，引入外部緩存只會增加 Windows 裸機環境下的硬體依賴性，對單人推論毫無效能回報。

---

## 環境變數一覽 / Environment Variables

| 變數 | 使用位置 | 說明 |
|---|---|---|
| `OPENAI_API_KEY` | `app.py` | GPT-4o-mini API 金鑰，必填 |
| `FFMPEG_PATH` | `ffmpeg_server.py`、`musetalk_server.py` | 系統 FFmpeg 8.1 的完整路徑，預設 `"ffmpeg"` |
| `FFPROBE_PATH` | `ffmpeg_server.py` | 系統 FFprobe 的完整路徑，預設 `"ffprobe"` |
| `MUSETALK_RESULTS_DIR` | `liveportrait_server.py` | MuseTalk 輸出結果的資料夾路徑 |
| `SSL_CERT` / `SSL_KEY` | `app.py` | HTTPS 憑證（預設不啟用） |
| `OMP_NUM_THREADS` | `app.py`（啟動時設定） | CPU 執行緒限制，預設 `"4"` |
| `MKL_NUM_THREADS` | `app.py`（啟動時設定） | MKL 執行緒限制，預設 `"4"` |

---

## 給 AI 協作者的通用原則 / General Principles for AI Collaborators

1. **確認目標 venv 再提建議**：每個修改涉及的程式碼屬於哪個 venv，在該 venv 的套件限制下是否可行。
2. **不要建議合併 venv**：這是物理不可能的事，會浪費調試時間。
3. **路徑相關修改一律用環境變數**：不接受新增硬編碼的 `C:\Users\...` 路徑。
4. **修改推論參數前先說明影響**：Fish Speech 的 `repetition_penalty`、`temperature`、LivePortrait 的 `driving-multiplier` 等參數已調校，修改前需說明預期效果與風險。
5. **Windows 環境優先**：除非明確要求跨平台支援，否則所有建議應以 Windows 為準（路徑分隔符、subprocess 呼叫方式等）。
6. **不要建議 Docker 化**：研究原型階段，四個 venv 的隔離即為本專案設計的「容器」概念，Docker 化會大幅增加維護複雜度且不在研究範圍內。
7. **拒絕 AI 的退化妥協（Anti-Gaslighting）**：當連續 3 次除錯失敗時，AI 常會給出「那不如我們把這個功能拿掉」或「回滾到最簡單的單線程」這種閹割版建議。**駕駛員必須堅守架構底線**。當 AI 開始退化時，立刻開新對話（New Chat），並將本 Guide 與最新的 Traceback 重新餵給它，重置 AI 的推論狀態。不要在同一個上下文中繼續拉鋸——疲勞的對話只會讓 AI 越來越傾向妥協。
8. **拒絕黑盒子重構**：使用者遇到 bug 解不掉，容易被 AI 說「我幫你重寫這段」，然後拿到一個自己看不懂的版本。下次出問題時完全無法定位，等於把自己的維護能力拱手讓出。原則：**每一行修改你都要能說出為什麼**。看不懂的重構一律拒絕，要求 AI 逐行解釋後再決定是否採用。
9. **拒絕被 AI 說服後重構系統架構**：這比 Anti-Gaslighting 層級更高。防止 AI 在「順風局」時用一套聽起來有道理的技術論述，說服你把微服務改成單體、把 HTTP 改成 shared memory、把 venv 隔離改成 conda。**任何涉及跨服務邊界或 venv 邊界的重構建議，一律需要你能獨立驗證其必要性，而不是因為 AI 說得有道理就動手。** 判斷標準：這個重構能解決什麼現有的具體問題？如果答案是「讓架構更優雅」，直接拒絕。
10. **修改後必須執行檔案對齊檢查**：AI 每次只修改一個檔案，但本專案各服務之間存在介面依賴（回傳 JSON 格式、路徑約定、環境變數名稱）。**AI 修改任何一個檔案後，你必須主動問：「這個修改影響了哪些其他檔案的介面或假設？」** 特別危險的是沉默的介面變更——回傳格式改了、路徑約定改了，不會立刻報錯，而是在幾個步驟之後以莫名其妙的方式爆炸。同樣地，程式碼修改後，README 與 DEBUGGING.md 中對應的參數說明、架構描述也需要同步更新，避免文件與實際行為脫節後誤導下一次的 debug。
