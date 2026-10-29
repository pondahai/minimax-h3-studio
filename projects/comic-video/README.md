# 漫畫轉影片工作流

把一篇分格漫畫做成有配音、配樂、字幕的短片。**這是獨立的工作流，和本專案的 Studio 前端（`app.py`、`static/`）分開**：不經過 Colab，全部在本地 DGX Spark（＋Jetson ASR）上跑，用命令列腳本串起來。

- 本目錄放**共用腳本**；每一篇漫畫一個子目錄，只放該篇的分鏡、prompt、設定與成品
- 完整流程、注意事項與踩過的坑：[docs/comic-to-video-workflow.md](../../docs/comic-to-video-workflow.md)

## 篇目

| 子目錄 | 篇名 | 狀態 |
|---|---|---|
| [`butterfly/`](butterfly/) | 蝴蝶生命循環 | 完成（10 段約 119 秒） |
| [`density/`](density/) | 密度是什麼？一樣大，不一定一樣重！ | 製作中 |
| [`rainbow/`](rainbow/) | 彩虹為什麼會出現？ | 草稿待驗收（10 段 120 秒） |

## 流程

```
取材 → 分鏡（人工）→ 8002 擴寫＋檢查
     → TTS 配音（角色聲音人工挑選；送 TTS 前轉簡體）→ ASR 核對＋人工試聽
     → Qwen-Image 首幀（獨立段）→ 分鏡審查（review.html，使用者選定）
     → H3 分段生成（續接段接前段末幀）→ H3 配樂 → 合成 → 字幕
```

## 需要的服務

| 服務 | 位置 | 用途 |
|---|---|---|
| llama.cpp（多模態） | Spark `100.89.149.50:8002` | 擴寫 prompt |
| VoxCPM2 TTS | Spark `:8792`（用時才啟動） | 配音 |
| Qwen-Image ComfyUI | Spark `:8188`（用時才啟動） | 首幀 |
| MiniMax H3 | Spark `~/h3-bench`（docker） | 影片、配樂 |
| Breeze ASR | Jetson `100.108.74.45:8013` | 核對配音 |

TTS、Qwen-Image、H3 互斥（記憶體），一次只開一個。

## 共用腳本

每個腳本的第一個參數都是篇目子目錄名稱（例如 `density`）。

| 腳本 | 用途 | 在哪跑 |
|---|---|---|
| `comic.py` | 讀 `<篇目>/config.json`（其他腳本共用） | — |
| `draft_storyboard.py <篇目>` | 試驗：8002 逐格寫分鏡初稿，用檢查程式回饋重寫 → `storyboard_8002.md`（初稿，要人工修，見 docs） | 本機 |
| `check_storyboard.py <篇目> [分鏡檔]` | 檢查分鏡是否照規則寫（語速、續接、畫面不放字、角色對照 `panel_cast`） | 本機 |
| `expand.py <篇目> [段...]` | 分鏡＋漫畫分格圖送 8002 擴寫 → `prompts/SXX.txt` | 本機 |
| `tts.py <篇目> [角色...]` | 逐句配音 → `audio/`、`audio/lines.json`；帶角色只重配那些角色 | 本機 |
| `asr_check.py <篇目> [wav...]` | Breeze ASR 轉寫配音、和原文比對 | 本機 |
| `qwen_frame.py <篇目> <名稱> <seed數> <參考圖...>` | `frame_prompts/<名稱>.txt` → `frames/<名稱>_seedN.png` | 本機 |
| `review.py <篇目>` | 分鏡審查頁 `review.html`（首幀候選＋時間軸＋台詞） | 本機 |
| `run_series.sh <篇目> [起始段]` | 依 `shots` 依序生成全部分段；有 `frames/<段>_end.png` 就加尾幀（首尾幀） | Spark |
| `run_jobs.sh <篇目> "<工作>"...` | 單獨重跑指定段或配樂 | Spark |
| `mux.py <篇目>` | 配音依時間軸混入、配樂循環墊底 → `<篇目>_draft.mp4` | Spark（需 ffmpeg） |
| `subs.py <篇目>` | 繁中字幕 `<篇目>.srt`＋壓字幕版 `<篇目>_sub.mp4` | Spark |

`.sh` 由 `.gitattributes` 固定 LF 換行（CRLF 傳到 Spark 會跑不動）。

## 每篇的 `config.json`

| 欄位 | 內容 |
|---|---|
| `title`、`source` | 篇名、來源網址 |
| `style`、`characters`、`no_text_rule` | 擴寫 system prompt 的風格（只寫畫風，不寫場景道具）、角色外觀、畫面不放字的規則 |
| `panel_dir`、`panels` | 漫畫原圖所在的本機暫存資料夾（原圖不進 repo）、每段對應的分格；兩段共用一格時指向切好的 `panel-0Xa`／`b` |
| `voices`、`ref_text`、`ref_transcript` | 角色音色描述、參考音逐字稿（prompt 模式克隆用） |
| `t2s`、`pronounce` | 送 TTS 前轉簡體、仍唸錯時的同音字替換 |
| `shots` | `[段, 秒數, 首幀來源]`；首幀來源 `-`＝t2va、圖檔路徑＝用該圖、段名＝續接該段末幀 |
| `panel_cast` | 原圖每格出現的角色（`check_storyboard.py` 用） |
| `speakers`、`tagline` | 字幕標名字的角色（旁白不標）、片尾標語（可為 null） |

## 新增一篇

1. 建 `<篇目>/`，寫 `config.json`、`storyboard.md`（格式照現有篇目）；兩段共用一格的原圖先切塊
2. `python expand.py <篇目>` → 檢查並修 `prompts/`
3. 啟動 TTS → 新角色候選、**由人挑選**存成 `audio/ref_<角色>.wav`（同系列角色直接複製前一篇的）→ `python tts.py <篇目>` → `python asr_check.py <篇目>` → 壞句重配、人工試聽 → 關 TTS
4. 啟動 8188 → 每個獨立段 `python qwen_frame.py <篇目> <段> 3 <原漫畫分格> <角色參考圖>` → 關 8188
5. 寫 `review.json`（建議 seed 與理由）→ `python review.py <篇目>` → 使用者選定 → 存成 `shots` 指定的首幀檔名
6. 把本目錄腳本、`bench.py`（672×384）和 `<篇目>/` 放到 Spark `~/h3-bench/comic-video/`，停掉 8002 以外的服務 → `bash run_series.sh <篇目>`
7. 配樂：`bash run_jobs.sh <篇目> "music1 prompts/music.txt 1 12 -" ...` → 挑選 → `music/bgm.wav`
8. 各段影片放 `video/`、`audio/` 傳上 Spark → `python3 mux.py <篇目>` → `python3 subs.py <篇目>`

影片、wav、圖檔、`review.html` 不進 git，清單見 docs 筆記的「不進 git 的檔案」。
