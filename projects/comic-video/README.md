# 漫畫轉影片工作流

把一篇分格漫畫做成有配音、配樂、字幕的短片。**這是獨立的工作流，和本專案的 Studio 前端（`app.py`、`static/`）分開**：不經過 Colab，全部在本地 DGX Spark（＋Jetson ASR）上跑，用命令列腳本串起來。

- 本目錄放**共用腳本**；每一篇漫畫一個子目錄，只放該篇的分鏡、prompt、設定與成品
- 完整流程、注意事項與踩過的坑：[docs/comic-to-video-workflow.md](../../docs/comic-to-video-workflow.md)

## 篇目

| 子目錄 | 篇名 | 狀態 |
|---|---|---|
| [`butterfly/`](butterfly/) | 蝴蝶生命循環 | 完成（10 段約 119 秒） |
| [`density/`](density/) | 密度是什麼？一樣大，不一定一樣重！ | 製作中 |
| [`rainbow/`](rainbow/) | 彩虹為什麼會出現？ | 完成（10 段 120 秒） |
| [`sound/`](sound/) | 聲音是怎麼傳播的？ | 完成（12 段 144 秒，含 H3 音效、對嘴） |
| [`seasons/`](seasons/) | 為什麼會有四季？ | 完成（12 段 144 秒，8002 初稿附人工備註） |

## 流程

```
取材 → 分鏡（人工）→ 8002 擴寫＋檢查
     → TTS 配音（角色聲音人工挑選；送 TTS 前轉簡體）→ ASR 核對＋人工試聽
     → Qwen-Image 首幀（獨立段）→ 分鏡審查（review.html，使用者選定）
     → H3 分段生成（續接段接前段末幀）→ H3 配樂 → 合成 → 字幕
```

## 文字版工作流（彙整自四篇筆記）

以下把 [docs 復盤筆記](../../docs/comic-to-video-workflow.md) 與各篇 README 的定案做法整理成一條可照做的流程；每步的原因與踩坑細節仍以 docs 為準。

### 0. 原則
- **人決定、機器做**：角色聲音、首幀 seed、配樂、最終試聽都由使用者挑，不自動選定
- **記憶體互斥**：TTS、Qwen-Image、H3 一次只開一個；跑 H3 時 Spark 只留 8002
- **畫面不放任何文字**（招牌、標籤、標語、箭頭、示意圖），H3 會畫成亂碼；標語改用字幕
- 草稿等級 672×384；本機 Windows 沒有 ffmpeg，影音處理一律在 Spark 做

### 1. 取材
- 抓來源頁分格原圖（一格一張 `panel-0X.png`），放本機暫存資料夾（`panel_dir`），**不進 repo**
- 完整讀過劇情、角色、台詞；**先判斷原作比喻與科學是否正確**（8002 不會質疑原圖），需要的安全提醒（不要直視太陽、打孔請大人幫忙）先記下
- 在 `config.json` 填 `panel_cast`（每格出現的角色）

### 2. 分鏡 → `storyboard.md`
1. `python draft_storyboard.py <篇目>`：8002 逐格寫初稿 → `storyboard_8002.md`（每格檢查、回饋重寫最多 2 輪）
2. **人工修初稿**：科學、安全句、加戲、續接判斷、畫面不放字、說話者（這些 8002 和檢查程式都做不好）
3. `python check_storyboard.py <篇目>` 跑到沒有錯誤（警告確認是刻意的才保留）

分鏡規則：
- 單段 ≤ 12 秒，秒級時間軸「秒數｜畫面動作｜鏡頭｜聲音」；預設一格一段，唸不完才拆
- 台詞約 4 字／秒（童聲 3.5），約每 3–5 秒一個主要事件：太滿 H3 會跳過，太空 H3 會自己加戲
- 每一列（含第一列）都要有看得見的變化；時間軸寫成因果順序
- 寫明畫面裡有誰（「畫面只有小明」）；路人要寫外觀；道具名稱寫準
- 角色說話的時段寫口型＋手勢表情，旁白時段角色閉嘴
- **續接（⟶續）只用在同景別、動作連續**的段落，前段最後一秒寫明末幀構圖；景別大切換就開新段
- 續接後要拉遠到角色、或角色中途才入鏡 → 加 Qwen 尾幀（首尾幀）；物理結果（浮／沉）也用尾幀鎖住
- 光學題材寫明光源位置，動作也不能暗示光源方向
- 阿柴不說話（原作台詞改給其他角色或旁白）

### 3. 擴寫 → `python expand.py <篇目>` → `prompts/SXX.txt`
- `config.json` 的 `style`／`style_en` **只寫畫風、色調、光線**，場景道具寫在各段分鏡
- 一格拆成多段時先把原圖切成 `panel-0Xa`／`b`，切完確認沒帶到相鄰角色
- 輸出 H3 官方格式（`prompt_format: official`），8002 只回 JSON、時間戳與 `<d>[Chinese] 台詞</d>` 由程式組；角色一律用 `names_en`
- `python check_prompts.py <篇目>` → 再人工看：前後段外觀連續、道具有沒有被換（塑膠杯變 glass）；確認每段 `prompts/` 都有更新；有問題直接改 prompt 檔

### 4. 配音 → `python tts.py <篇目>`
1. 啟動 VoxCPM2 TTS（Spark `:8792`）
2. 新角色：用不同音色描述各生 3–4 個候選（偏好台灣華語口音）→ **使用者挑** → `audio/ref_<角色>.wav`；同系列角色直接沿用前一篇
3. 用 prompt 模式克隆；`t2s: true` 送 TTS 前轉簡體；多音字唸錯用 `pronounce` 換同音字（字幕保留正確字）
4. `python asr_check.py <篇目>`：**漏字也算壞句**、同音錯字代表發音對；壞句重配 3 版給使用者挑，最後以人工試聽為準
5. 台詞改字要同步改 `storyboard.md`、`lines.json`；完成後關 TTS

### 5. 首幀 → `python qwen_frame.py <篇目> <段> 3 <參考圖...>`
1. 啟動 `qwen-image-comfyui`（`:8188`）
2. 先做角色立繪 `frame_prompts/chars.txt` → `frames/chars.png`（純色背景、全員全身、手上無道具），之後當角色參考
3. **所有獨立段都做首幀**（1344×768，3 個 seed）；續接段用前段末幀；需要的段做尾幀 `frames/SXX_end.png`（config `last_frames`）
4. prompt 用中文、描述具體（「一半露出水面」而不是「浮在水面」）；只有路人的段不給立繪
5. 挑 seed 時排除：照抄參考圖（道具、整排立繪角色）、動作結果已出現在首幀、和 0 秒分鏡構圖不符
6. 關 8188

### 6. 分鏡審查 → `python review.py <篇目>`
- 建議 seed 與理由寫進 `review.json` → 產生 `review.html`（首幀候選＋時間軸＋台詞）
- **使用者選定**後，把選定 seed 複製成 `shots` 指定的首幀檔名，才開始跑 H3

### 7. 影片 → Spark `bash run_series.sh <篇目>`
- 腳本、`bench.py`、`<篇目>/` 放到 Spark `~/h3-bench/comic-video/`；先 `bash -n` 檢查語法；停掉 8002 以外的服務
- 長時間工作用 `setsid nohup … &`；`pgrep`／`pkill` 關鍵字寫成 `"[r]un_series.sh <篇目>"`
- 每段跑完抽幀檢查接縫、文字、角色外觀；重跑某段：舊檔移到 `out/archive/`、`run/<段>_v1/`，修 prompt／首幀後 `bash run_series.sh <篇目> <段>`

### 8. 配樂 → `bash run_jobs.sh <篇目> "music1 prompts/music.txt 1 12 -"`
- 官方格式：`[Shot 1]` 空景、`overall_soundscape` 只寫環境音、`non_diegetic_music` 寫樂器節奏（範例 `density/prompts/music_official.txt`）
- ASR 確認沒有人聲（只回時間戳＝乾淨）→ 使用者聽 → `music/bgm.wav`

### 9. 音效與對嘴（Spark）
1. `bash sfx.sh <篇目>`：去掉 H3 原生音軌的人聲 → `sfx/SXX_novocals.wav`，列出響度（< −45 LUFS 的對白段沒有音效是正常的）
2. `lipsync_measure.py <篇目>`（在 `demucs-sfx` 容器裡跑）→ `sfx/lipsync.json`：角色台詞對齊 H3 開口
3. 先挑幾段給使用者試聽再全片套用

### 10. 合成與字幕（Spark）
1. `python3 mux.py <篇目>`：原生音軌只取去人聲後的音效；台詞統一 −20 LUFS、依時間軸（或 lipsync）放入，太緊優先在 `lines.json` 提前起秒；配樂循環墊底 → `<篇目>_draft.mp4`
2. `python3 subs.py <篇目>` → `<篇目>.srt`＋`<篇目>_sub.mp4`（角色標名、旁白不標、片尾標語置頂）
3. scp 拉回本機、使用者驗收；分享版另以 CRF 27／AAC 96k 重編碼成 `<篇目>_share.mp4`

### 11. 收尾
- 在該篇 README 記下：聲音來源、原作處理、選定 seed、重跑原因、配樂；需要時寫 YouTube 標題與說明（註明原作與 AI 生成）
- 新的坑與解法補進 docs 筆記；新增工具更新 docs 的工具清單
- 影片、wav、圖檔、`review.html` 不進 git

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
| `review.py <篇目>` | 分鏡審查頁 `review.html`（首幀候選＋時間軸＋台詞；圖片內嵌，單檔可傳） | 本機 |
| `run_series.sh <篇目> [起始段]` | 依 `shots` 依序生成全部分段；有 `frames/<段>_end.png` 就加尾幀（首尾幀） | Spark |
| `run_jobs.sh <篇目> "<工作>"...` | 單獨重跑指定段或配樂 | Spark |
| `sfx.sh <篇目> [段...]` | H3 跑完後去掉原生音軌的人聲、留下同步音效 → `sfx/SXX_novocals.wav`，列出各段音效響度（映像檔 `Dockerfile.sfx`，裡面跑 `sfx_sep.py`） | Spark |
| `mux.py <篇目>` | 配音依時間軸混入、有 `sfx/SXX_novocals.wav` 就墊音效、配樂循環墊底 → `<篇目>_draft.mp4` | Spark（需 ffmpeg） |
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
| `panel_cast` | 原圖每格出現的角色（`check_storyboard.py` 用；空陣列＝沒有角色） |
| `panel_notes` | 每格人工備註（段數、場景、原作更正、科學補充、安全句），`draft_storyboard.py` 連同原圖送 8002 |
| `speakers`、`tagline` | 字幕標名字的角色（旁白不標）、片尾標語（可為 null） |

## 新增一篇

1. 建 `<篇目>/`，寫 `config.json`、`storyboard.md`（格式照現有篇目）；兩段共用一格的原圖先切塊
2. `python expand.py <篇目>` → 檢查並修 `prompts/`
3. 啟動 TTS → 新角色候選、**由人挑選**存成 `audio/ref_<角色>.wav`（同系列角色直接複製前一篇的）→ `python tts.py <篇目>` → `python asr_check.py <篇目>` → 壞句重配、人工試聽 → 關 TTS
4. 啟動 8188 → 每個獨立段 `python qwen_frame.py <篇目> <段> 3 <原漫畫分格> <角色參考圖>` → 關 8188
5. 寫 `review.json`（建議 seed 與理由）→ `python review.py <篇目>` → 使用者選定 → 存成 `shots` 指定的首幀檔名
6. 把本目錄腳本、`bench.py`（672×384）和 `<篇目>/` 放到 Spark `~/h3-bench/comic-video/`，停掉 8002 以外的服務 → `bash run_series.sh <篇目>`
7. 配樂：`bash run_jobs.sh <篇目> "music1 prompts/music.txt 1 12 -" ...` → 挑選 → `music/bgm.wav`
8. Spark 上 `bash sfx.sh <篇目>`（實驗音效）→ 各段影片放 `video/`、`audio/` 傳上 Spark → `python3 mux.py <篇目>` → `python3 subs.py <篇目>`

影片、wav、圖檔、`review.html` 不進 git，清單見 docs 筆記的「不進 git 的檔案」。
