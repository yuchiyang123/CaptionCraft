# CaptionCraft

AI 影片字幕產生與編輯工具。上傳影片、自動語音辨識產生字幕，接著在瀏覽器裡直接校對文字、調整時間軸與樣式，最後匯出 SRT / VTT，或直接把字幕燒錄進影片匯出完整 MP4。

前端 **Vue 3 + Vite**，後端 **Python FastAPI**，語音辨識使用 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)（本機執行，無需外部 API）。

## 功能

**影片庫**
- 拖曳 / 點擊上傳影片（MP4 / MOV / MKV / WEBM / AVI）
- 縮圖、時長、字幕產生狀態即時顯示（自動輪詢進度）

**編輯器**
- 內建播放器，即時顯示字幕疊加效果
- 可視化時間軸：拖動字幕區塊移動、拖動邊緣調整起訖時間、點擊尺標跳轉播放位置，播放時自動捲動跟隨
- 字幕清單：直接編輯文字與時間碼、新增 / 刪除 / 拆分字幕，點選時間軸與清單雙向同步
- 字幕樣式面板：位置（上／中／下）、字型大小、文字顏色、背景透明度，即時預覽
- 一鍵重新執行 AI 語音辨識（會覆蓋目前字幕）
- 匯出 SRT / VTT 字幕檔
- 匯出「含字幕的完整影片」：將目前的文字與樣式直接燒錄進畫面，帶進度顯示，完成後自動下載；任何字幕或樣式修改都會讓舊的匯出失效，避免下載到過期內容

## 專案結構

```
backend/    FastAPI 服務、SQLite 資料庫、faster-whisper 語音辨識、影片燒錄匯出
frontend/   Vue 3 + Vite 前端
```

## 啟動後端

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

## 啟動前端

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
