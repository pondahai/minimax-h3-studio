# MiniMax H3 Colab Studio 🎬

基於 Google Colab CLI 與 MiniMax H3 (Ref2VA) 模型架構打造的本機視覺化 Web 控制中心，讓您能在本地透過優雅直觀的前端介面，一鍵調用 Google Colab 雲端 A100 GPU 進行短片生成，並即時監控算力餘額與推論進度。

---

## 目錄
- [1. 貢獻者致謝](#1-貢獻者致謝)
- [2. 專案目錄結構](#2-專案目錄結構)
- [3. 前端功能與特色](#3-前端功能與特色)
  - [3.1 提示詞生成工作流：搭配外部 LLM（如 Qwen 3.8 27B）](#31-提示詞生成工作流搭配外部-llm如-qwen-38-27b)
- [4. 技術挑戰與相容性修復過程](#4-技術挑戰與相容性修復過程)
  - [4.1 Colab CLI Windows 原生相容性修復（termios / tty）](#41-colab-cli-windows-原生相容性修復termios--tty)
  - [4.2 Windows 控制台 CP950 編碼問題](#42-windows-控制台-cp950-編碼問題)
  - [4.3 上游筆記本字元損壞與 Windows 管線亂碼修復](#43-上游筆記本字元損壞與-windows-管線亂碼修復)
  - [4.4 Notebook JSON 結構毀損修復（NotJSONError）](#44-notebook-json-結構毀損修復notjsonerror)
- [5. 實測成果與算力消耗報告](#5-實測成果與算力消耗報告)
- [6. 快速上手指南](#6-快速上手指南)

---

## 1. 貢獻者致謝

本專案的核心推論邏輯與 Skill 機制奠基於開源社群的卓越成果，特此致謝：

1. **[@killkli](https://github.com/killkli)**：
   感謝開發並開源了 [minimax-h3-colab-skill](https://github.com/killkli/minimax-h3-colab-skill) 專案。該專案提供了獨立且模組化的 Codex / AGY Skill 架構、優異的批次佇列設計，以及專門針對 Google Colab 部署的 ComfyUI MiniMax H3 Turbo 4-step 推論 Notebook。
2. **MiniMax 團隊**：
   感謝 MiniMax 團隊研發的 H3 (Ref2VA) 多模態影片生成模型，實現了透過參考圖片進行人物外觀、風格保持與高品質語音音景合成的前沿體驗。
3. **Google Colab 團隊**：
   感謝提供便利的 `google-colab-cli` 工具與強大彈性的雲端運算環境。

---

## 2. 專案目錄結構

完整專案封裝於 `minimax-h3-studio` 目錄下：

```text
minimax-h3-studio/
├── app.py                  # FastAPI 後端伺服器（API 接口、任務調度、進度監控）
├── start_studio.bat        # Windows 一鍵啟動腳本（自動開啟服務與命令視窗）
├── current_progress.json   # 即時推論任務狀態與終端機日誌快取
├── README.md               # 本專案完整技術與架構文檔
├── static/
│   └── index.html          # 前端 Single Page Application（Tailwind CSS + Lucide 圖標）
├── uploads/                # 本地暫存的使用者上傳參照圖片
└── outputs/                # 生成完畢並自動自 Colab 下載的 MP4 影片與元資料 (.json)
```

---

## 3. 前端功能與特色 (Studio 2.0)

前端介面採用現代暗色系玻璃擬態設計（Glassmorphism），升級至 Studio 2.0 帶來全方位的工作流支援：

1. **即時 Colab 算力儀表板**：
   - 頂部常駐顯示目前帳號的 Google Colab 算力餘額（Compute Units, CU）。
   - 即時監控每小時費率（`Rate/hr`）與活躍虛擬機配置數（`Active assignments`）。
   - 支援 30 秒自動輪詢與手動即時刷新按鈕。
2. **多模態資產塢（Multi-Modal Dock）**：
   - **視覺素材（`<Picture 1-9>`）**：支援拖曳、點擊或直接剪貼簿 **Ctrl+V** 貼上（支援螢幕截圖 / 圖片複製）1～9 張人物與場景參考圖片，自動依序映射。
   - **音訊素材（`<Audio 1-3>` 音色置換與語音克隆）**：支援上傳 MP3 / WAV 乾淨人聲音訊（建議 2～15 秒）。模型自動擷取目標音色、音調與口音，並在對話句 `<d>[Chinese] ...</d>` 中合成具有該音色的自然台詞語音與唇形同步。
3. **分鏡時間軸與一鍵接續延伸（Last-Frame Continuation）**：
   - 內建故事板時間軸（Storyboard Timeline），將各次生成結果組織為連續鏡頭（Shot 1, Shot 2...）。
   - 提供「延伸此鏡頭（接續生成下一鏡）」按鈕：透過後端 OpenCV 即時無失真擷取當前影片最後一幀，自動將其設為下一段的 `<Picture 1>`，使鏡頭銜接流暢無縫。
4. **AI 導演提示詞助手（AI Copilot Assistant）**：
   - 支援輸入簡短靈感（例如：「賽博龐克雨夜偵探追逐」），Copilot 會自動結合目前上傳的圖片與音訊標籤，智能擴寫為結構化 Ref2VA 提示詞規範，大幅降低提示詞編寫門檻。
5. **雲端運算參數控制**：
   - 影片長度（4～15 秒滑動條，預設 12 秒）。
   - GPU 規格選擇（A100 極速推薦、V100、T4 經濟型、L4）。
   - 高記憶體（High-Mem）切換開關、自訂隨機種子（Seed）。
6. **5 階段視覺化步進條與即時日誌**：
   - 即時步進器（雲端連線 ➔ 資產上傳 ➔ A100 模型推論 ➔ 成果下載 ➔ 完成）。
   - 支援瀏覽器桌面通知（完成時彈出提醒，無需長時間盯盤）。
   - 終端機日誌視窗，即時串流遠端執行進度。
7. **歷史鏡頭庫與分鏡下載**：
   - 生成完成後即時於網頁播放預覽，提供一鍵下載 MP4。
   - 歷史清單自動讀取 `outputs/` 目錄，顯示歷史影片大小、時間並支援隨時回播或載入延伸。

### 3.1 提示詞生成技巧：搭配外部 LLM（如 Qwen 3.8 27B）

本 Studio 前端定義的結構化欄位非常適合交由具備聯網能力的大語言模型（如 Qwen 3.8 27B 等）輔助撰寫：

1. **欄位規格提供**：將 Studio 前端定義的六大欄位結構（主體定義、留存特徵、劇情概要、分鏡時序與台詞、音景、配樂）提供給 LLM。
2. **規格檢索與生成**：讓 LLM 查詢網路上 MiniMax H3 (Ref2VA) 的規範標準，針對您上傳的圖片與音訊特徵自動生成符合格式的內容：
   ```text
   subject_definitions:
   The subject (S1) is the character from <Picture 1>, speaking with voice timbre from <Audio 1>.

   summary:
   Cinematic sequence of S1 walking through the neon alley.

   retention_analysis:
   Retain facial identity from <Picture 1> and vocal pitch from <Audio 1>.

   detailed_description:
   [Shot 1] The camera slowly dollies in on S1. S1 looks into the rain and speaks: <d>[Chinese] 夜深了，這座城市還沒睡。</d>

   overall_soundscape:
   Heavy rain dripping, distant police sirens, and neon hum.

   non_diegetic_music:
   Dark synthwave with low pulsing bass.
   ```
3. **快速匯入執行**：將生成的內容貼回前端對應欄位，即可在 Colab A100 上順暢驅動模型生成完整影片。

---

## 4. 技術挑戰與相容性修復過程

在自 GitHub 專案導入並封裝 Windows 執行環境時，解決了以下關鍵相容性挑戰：

### 4.1 Colab CLI Windows 原生相容性修復（termios / tty）
- **現象**：在 Windows 執行 `colab version` 或 `colab usage` 時崩潰，回報：
  `ModuleNotFoundError: No module named 'termios'`。
- **成因**：官方 `google-colab-cli`（0.7.4 版）底層的 `console.py` 在頂部無條件引用了 POSIX 專屬的 `termios`、`tty` 以及 Unix 訊號 `signal.SIGWINCH`。
- **修復**：對 `colab_cli/console.py` 進行動態保護，將 Unix 專用模組改為 `try-except` 安全匯入，並增加 `hasattr(signal, 'SIGWINCH')` 平台判定，使 CLI 可以在 Windows 下原生執行。

### 4.2 Windows 控制台 CP950 編碼問題
- **現象**：啟動後端控制台時回報 `UnicodeEncodeError: 'cp950' codec can't encode character '\U0001f680'`。
- **成因**：Windows 中文預設控制台編碼為 CP950（Big5），無法輸出高位 Emoji 字元。
- **修復**：將控制台輸出改為純 ASCII 文字符號（如 `[*]`），確保在任何 Windows 終端機環境皆能無痛啟動。

### 4.3 上游筆記本字元損壞與 Windows 管線亂碼修復
- **現象**：前端日誌出現 `ҦGreference...`、`bͦvK` 等亂碼符號。
- **成因剖析**：
  1. 上游儲存庫中的 `MiniMax_H3_Turbo_Colab.ipynb` 筆記本在提交時，中文 print 訊息已遭轉碼損壞，內嵌大量 `\ufffd` 替代字元。
  2. Windows 子行程管線在未聲明 `PYTHONIOENCODING` 時採用系統代碼頁傳輸，導致與 Python UTF-8 讀取端衝突。
- **修復**：
  1. 重寫修正 Notebook 中所有損壞的 print 字串（「正在生成影片...」、「節點檢查通過，ComfyUI 已啟動」等）。
  2. 在 `runner.py` 調用 CLI 子行程時，注入環境變數 `PYTHONIOENCODING=utf-8`、`PYTHONUTF8=1`，並實作跨編碼回退解碼機制（UTF-8 ➔ CP950 ➔ GB18030）。

### 4.4 Notebook JSON 結構毀損修復（NotJSONError）
- **現象**：修復文字時曾遭遇 `NotJSONError: Notebook does not appear to be JSON`。
- **成因**：文字層級的正則表達式替換破壞了 Jupyter Notebook 內部的 JSON 跳脫格式。
- **修復**：改由標準 `nbformat` 程式庫重新載入原始 AST，在記憶體中修改程式碼儲存格陣列後通過 `nbformat.validate()` 驗證寫回，保證 18 個儲存格語法結構完全符合 Jupyter 規範。

---

## 5. 實測成果與算力消耗報告

完成所有修復後，透過 Web 前端成功調用 Google Colab 雲端算力進行完整端到端實測：

- **運算節點**：Google Colab A100 GPU (High-RAM 執行階段)
- **生成模式**：MiniMax H3 Ref2VA (Turbo 4-step)
- **影片規格**：長度 12.0 秒、24 fps（共 294 幀）、包含對齊之視訊與立體聲音訊串流
- **輸出成果**：
  - 檔案：[`outputs/h3_job_1790498551_0a0a_mp4_job_1790498551_0a0a.mp4`](file:///C:/Users/USER/minimax-h3-studio/outputs/h3_job_1790498551_0a0a_mp4_job_1790498551_0a0a.mp4)
  - 大小：**5.77 MB (6,047,249 bytes)**
- **算力點數消耗（Compute Units）**：
  - 初始餘額：`200.00 Units`
  - 執行後餘額：`198.87 Units`
  - **總共僅消耗：1.13 Units**（推論耗時約 4~5 分鐘）
- **關機安全保護**：任務結束後遠端 Session 立即自動中止（`Active assignments: 0`，`Rate: 0.00/hr`），未造成任何閒置漏點。

---

## 6. 快速上手指南

### 啟動服務
直接雙擊執行目錄下的：
```cmd
start_studio.bat
```
或在終端機中執行：
```powershell
cd C:\Users\USER\minimax-h3-studio
python app.py
```

### 開啟介面
打開瀏覽器訪問：
👉 **http://localhost:7860**

上傳 1～9 張照片，調整影片長度與提示詞，即可享受流暢穩定的 MiniMax H3 影片生成體驗！
