# CaptionCraft

AI 影片字幕產生與編輯工具。上傳影片、自動語音辨識產生字幕，接著在瀏覽器裡直接校對文字、調整時間軸與樣式，最後匯出 SRT / VTT，或直接把字幕燒錄進影片匯出完整 MP4。

前端 **Vue 3 + Vite**，後端 **Python FastAPI**，語音辨識使用 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)（本機執行，無需外部 API）。

## 功能

**影片庫**
- 拖曳 / 點擊上傳影片（MP4 / MOV / MKV / WEBM / AVI）
- 縮圖、時長、字幕產生狀態即時顯示（自動輪詢進度）

**編輯器**
- 自訂播放器：倒退／快轉 5 秒、播放速度、音量、全螢幕（字幕一起顯示），即時顯示字幕疊加效果
- 鍵盤快捷鍵：空白鍵／K 播放暫停、← → 倒退快轉 5 秒（加 Shift 為 1 秒）、`,` `.` 逐幀、↑ ↓ 音量、M 靜音、F 全螢幕、C 比較原始／增強畫面（在輸入框打字時不會觸發）
- 可視化時間軸：拖動字幕區塊移動、拖動邊緣調整起訖時間、點擊尺標跳轉播放位置，播放時自動捲動跟隨
- 字幕清單：直接編輯文字與時間碼、新增 / 刪除 / 拆分字幕，點選時間軸與清單雙向同步
- 字幕樣式面板：位置（上／中／下）、字型大小、文字顏色、背景透明度，即時預覽
- 一鍵重新執行 AI 語音辨識（會覆蓋目前字幕）
- 匯出 SRT / VTT 字幕檔
- 匯出「含字幕的完整影片」：將目前的文字與樣式直接燒錄進畫面，帶進度顯示，完成後自動下載；任何字幕或樣式修改都會讓舊的匯出失效，避免下載到過期內容

**音畫同步**
- 自動偵測聲音與畫面的時間差：用 [MediaPipe](https://ai.google.dev/edge/mediapipe) 追蹤說話者嘴型（唇距 + jawOpen），和音軌的人聲頻段（300–3000 Hz）振幅包絡做互相關比對（同時比對開合程度與起始點），標示信心度（需要畫面中有人正面說話）
- 從整部影片平均取多段分析並合併結果，各段結果可展開查看；各段差異過大時提示「可能漂移」
- 手動微調音軌位移（滑桿、輸入秒數、±1 幀 / ±10ms 按鈕），可在播放器即時預覽同步效果
- 字幕預設跟著聲音一起位移（可關閉）；另有「字幕整體位移」直接修改所有字幕時間
- 位移會套用到匯出影片；沒有字幕與畫質調整時只重新編碼音軌（畫面不重新壓縮）
- 第一次偵測會自動下載 MediaPipe 臉部模型（約 3.6 MB）到 `backend/storage/models/`

| 變數 | 說明 | 預設 |
| --- | --- | --- |
| `AVSYNC_MAX_SECONDS` | 總共分析的秒數（平均分散在整部影片） | `180` |
| `AVSYNC_WINDOW_SECONDS` | 每段分析長度（秒） | `30` |
| `AVSYNC_MAX_OFFSET` | 搜尋的最大位移（秒） | `2.0` |

**畫質增強**
- 輸出解析度：原始 / 720P / 1080P / 2K / 4K（只放大不縮小，接近 16:9 的來源會對齊標準寬度，例如 854×480 → 1920×1080）
- 放大方式：標準放大（Lanczos，快）或 AI 超解析（Real-ESRGAN `realesr-general-x4v3`，在另一台有 GPU 的伺服器上跑，見下方「AI 超解析伺服器」；伺服器連不到時自動改用本機的輕量 ESPCN 模型並在畫面上提示）
- 亮度、對比、飽和度、銳利度、降噪，附預設組合；前四項可在播放器即時預覽，也可產生「目前畫面」的實際匯出效果預覽圖（含放大與降噪）
- 第一次使用 AI 超解析會自動下載 ESPCN 模型（約 85 KB）到 `backend/storage/models/`

## AI 超解析伺服器（`upscaler/`）

Real-ESRGAN 需要 GPU，所以獨立成一個小服務跑在有顯示卡的機器上，CaptionCraft 匯出時把影片送過去放大、拿回來再加濾鏡 / 字幕 / 音軌。

**伺服器端**（需要 NVIDIA 驅動，`nvidia-smi` 要能用）：

```bash
# 第一次會建立 venv、安裝 PyTorch (CUDA) 與相依套件，之後只是重啟服務
~/projects/captioncraft-upscaler/start.sh
# 開機自動啟動
(crontab -l; echo "@reboot ~/projects/captioncraft-upscaler/start.sh") | crontab -
```

服務只綁 `127.0.0.1:12130`，不對外開放；模型（約 5 MB）第一次使用時自動下載。

**開發機端**：開一條 SSH 通道，把本機 `12130` 接到伺服器的 `127.0.0.1:12130`：

```bash
ssh -N -L 12130:127.0.0.1:12130 bospoel@192.168.137.11
```

後端預設打 `http://127.0.0.1:12130`（環境變數 `UPSCALER_URL` 可改，設成空字串則停用）。編輯器「畫質增強」面板會顯示伺服器是否已連線。

## 專案結構

```
backend/    FastAPI 服務、SQLite 資料庫、faster-whisper 語音辨識、影片燒錄匯出
frontend/   Vue 3 + Vite 前端
```

## 一鍵啟動（Docker，推薦）

需要先安裝 [Docker](https://docs.docker.com/get-docker/) 與 Docker Compose（新版 Docker Desktop 已內建）。

```bash
docker compose up --build
```

啟動後開啟 **http://localhost:3000** 即可使用。前端由 nginx 提供靜態檔並將 `/api` 反向代理到後端，後端則跑在容器內的 `8000` port（同時也對外開放方便直接除錯）。

- 影片、縮圖、資料庫會存在 Docker volume `backend_storage`，重開容器不會遺失
- Whisper 模型會快取在 volume `whisper_cache`，只有第一次執行辨識才需要下載
- 可用環境變數調整辨識設定（`docker-compose.yml` 裡的 `backend.environment`），意義同下方「啟動後端」章節的表格
- 關閉：`docker compose down`（加 `-v` 會連同影片資料一起刪除）

若不想用 Docker，也可以照下面步驟分別手動啟動前後端（開發模式，支援熱重載）。

## 啟動後端（本機開發模式）

```bash
cd backend
python -m venv .venv
./.venv/Scripts/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

第一次執行「AI 重新辨識」時，會自動從 Hugging Face 下載 Whisper 模型（預設 `small`，約數百 MB），需要網路連線，請耐心等候。可用環境變數調整：

| 變數 | 說明 | 預設 |
| --- | --- | --- |
| `WHISPER_MODEL_SIZE` | `tiny` / `base` / `small` / `medium` / `large-v3` | `small` |
| `WHISPER_DEVICE` | `cpu` 或 `cuda` | `cpu` |
| `WHISPER_COMPUTE_TYPE` | `int8`（CPU 較快）或 `float16` 等 | `int8` |

## 啟動前端（本機開發模式）

```bash
cd frontend
npm install
npm run dev
```

開發伺服器預設在 `http://localhost:5173`（若被佔用會自動換埠），已設定 proxy 將 `/api` 轉發到後端 `http://127.0.0.1:8000`。

## 技術重點

- 影片／音訊解碼與縮圖擷取、字幕燒錄皆使用 [PyAV](https://github.com/PyAV-Org/PyAV)（bundle ffmpeg），不需另外安裝系統 ffmpeg
- 影片串流與匯出下載皆支援 HTTP Range（區間請求），瀏覽器可正常拖動進度、大檔案穩定播放
- 字幕燒錄逐幀進度回報，前端即時顯示百分比進度條

## 資料儲存

- 影片檔與縮圖存放於 `backend/storage/media/`
- 資料庫為 SQLite，存放於 `backend/storage/app.db`

上述路徑純屬本機儲存，已加入 `.gitignore`。

## 授權

本專案採用 [MIT License](LICENSE)。
