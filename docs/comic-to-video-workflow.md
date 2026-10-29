# 漫畫轉影片工作流程（復盤筆記）

首次實作：2026-10-29，社子文教基金會「科學天地／自然小探險隊」《蝴蝶生命循環》（7 格）→ 約 119 秒草稿影片
程式與素材：[`projects/butterfly/`](../projects/butterfly/)

## 成品

| 檔案 | 內容 |
|---|---|
| `butterfly_draft.mp4` | 原版（無字幕）：672×384、10 段、TTS 配音＋配樂 |
| `butterfly_sub.mp4` | 壓字幕版（另外輸出，原版不動） |
| `butterfly.srt` | 繁體中文字幕檔 |

### 不進 git 的檔案（`projects/butterfly/.gitignore`）

| 檔案 | 內容 | 存放位置 |
|---|---|---|
| `butterfly_draft.mp4`、`butterfly_sub.mp4`、`butterfly_share.mp4` | 成片（原版、壓字幕版、分享用瘦身版：壓字幕版以 CRF 27、AAC 96k、faststart 重新編碼，8.3 MB） | 本機 `projects/butterfly/`、Spark `~/h3-bench/butterfly/` |
| `*.wav`（`audio/`、`audio/candidates/`） | 台詞配音、角色參考音、候選音 | 本機；配音另有一份在 Spark `~/h3-bench/butterfly/audio/` |
| `music/` | H3 配樂候選與選定的 `bgm.wav` | 本機、Spark |
| `frames/` | Qwen-Image 首幀候選 | 本機；選定的在 Spark `~/h3-bench/butterfly/frames/` |
| `contact_sheet.png` | 每 6 秒一格的總覽圖 | 本機 |
| `video/`、`mixed/` | 各段原始影片、配好音的各段 | Spark：`out/`（各段，含 `out/archive/` 舊版）、`mixed/` |
| 漫畫原圖 | 來源分格圖（版權屬原作者） | 本機暫存資料夾，`expand.py` 的 `PANEL_DIR` |

進 git 的是可重現成品的部分：分鏡、prompt、`audio/lines.json`（台詞與排定時間）、字幕檔、腳本。Spark 上的完整工作目錄是 `~/h3-bench/butterfly/`（含各段的 `run/<段>/bench.log`）。

## 機器與服務

| 服務 | 位置 | 用途 |
|---|---|---|
| llama.cpp（多模態） | Spark `100.89.149.50:8002` | 分鏡擴寫成影片 prompt，可附圖 |
| VoxCPM2 TTS | Spark `:8792`（`~/dgx-voxcpm-eval/chinese_tts_server.py`，平常不跑） | 角色配音 |
| Qwen-Image 2.1 ComfyUI | Spark `:8188`（container `qwen-image-comfyui`） | 生成首幀 |
| MiniMax H3 | Spark `~/h3-bench`（docker image `h3-bench`） | 生成影片／配樂 |
| Breeze ASR（常駐） | Jetson `100.108.74.45:8013`，SSH 帳號 `nvidia` | 核對 TTS 有沒有唸對 |

**記憶體互斥**：TTS、Qwen-Image、H3 三者一次只開一個；跑 H3 時 Spark 上只留 8002（停掉 `qwen3.8-nvfp4`、`qwen-image-comfyui`、`qwen-gradio-ui`）。實測 H3 跑時系統用量約 71 GB／121 GB，沒有用到 swap。

## 流程（定案版）

### 1. 取材
- 從來源頁抓分格原圖（本例 `https://shezi.org.tw/assets/images/panels/butterfly-2026/panel-0X.png`），先完整讀一遍劇情、角色、台詞
- 漫畫版權屬原作者，原圖不放進 repo

### 2. 分鏡（人工）→ `storyboard.md`
- 單段 ≤ 12 秒；一個連續動作超過 12 秒就拆段，用「前段末幀 → 後段首幀」續接（標 ⟶續）
- 每段寫成秒級時間軸表：秒數區間｜畫面動作｜鏡頭｜聲音（台詞）
- 續接段的前一段最後一秒要寫明末幀構圖
- 台詞以中文約 4 字／秒估算，排進對應時段；童聲語速較慢，要多留空間
- 先定角色外觀表，全片一致
- **畫面不要出現任何文字**（招牌、圖示標籤、標語）：H3 會畫成亂碼。標語改用字幕呈現

### 3. 擴寫（8002）→ `expand.py` → `prompts/SXX.txt`
- 每段送「分鏡表＋對應漫畫分格圖」；system prompt 規定：
  - 逐條保留時間區段，不得合併、刪改、重排
  - 圖片只參考外觀、配色、畫風；忽略圖中文字；不准加分鏡表沒有的角色或情節
  - 角色不寫說話、驚呼等發聲動作；結尾加「音訊：無對白、無人聲，只有自然環境音與輕快的兒童配樂」
- **擴寫後必查**（8002 會自由發揮）：
  1. 程式比對每段時間軸和分鏡一致
  2. 檢查有沒有多出來的角色（看圖版特別容易照圖把角色塞進特寫）
  3. 檢查「」引號裡的畫面文字
  4. 前後段外觀是否連續（例如毛毛蟲顏色、蛹的顏色）
- 有問題直接人工改 prompt 檔

### 4. 配音（TTS）→ `tts.py`
1. 啟動 TTS：`cd ~/dgx-voxcpm-eval && source .venv/bin/activate && nohup python chinese_tts_server.py &`
2. **角色聲音人工挑選**：每個角色用不同的音色描述生成 3–4 個候選，給使用者挑完才繼續（不能自動選定）
3. 選定的音檔存成 `audio/ref_<角色>.wav`
4. 每句台詞用參考音克隆。**用 prompt 模式**（`clone_mode=prompt`＋`prompt_text`＝參考音的逐字稿）；reference 模式在短句、並列詞上容易唸出非中文
5. **ASR 核對**：`python asr_check.py` 逐句轉寫，和原文比對。壞句每句重配 3 個版本，ASR 篩過後給使用者挑
6. 判讀 ASR：
   - **漏字也算壞句**：S05「長大後，牠找到…」ASR 只轉出「他找到…」，前三個字其實唸成了日文，第一次核對時被當成 ASR 誤差放過
   - ASR 會認錯同音字（卵→段落、蛹→勇），這種代表發音正確；轉成不同音的字（蛹→有）才是可疑
   - 最後一律以人工試聽為準
7. **多音字唸錯**（例：「變乾」的乾唸成乾坤的 qián）：VoxCPM2 不支援拼音標註，只能在送給 TTS 的文字裡換成同音、沒有歧義的字（乾→甘），字幕和 `lines.json` 保留正確的字；或改說法（變乾→乾燥）
8. 台詞錯字（例：「一隻小小的卵」→「一顆」）要同步改 `storyboard.md`、`lines.json`，再重配那句
9. 關閉 TTS 再進下一步

### 5. 首幀（需要時，Qwen-Image）→ `qwen_frame.py`
- 用於：畫面需要重做、或要指定構圖的段落（本例 S10）
- 參考圖：原漫畫分格＋影片中已生成的角色畫面（讓畫風和角色對齊影片）
- 直接輸出 16:9（1344×768），negative prompt 排除文字；生成 3 個 seed 給使用者挑
- 開 `qwen-image-comfyui` → 生成 → 關閉

### 6. 影片生成（H3）→ `run_series.sh`／`run_jobs.sh`
- 草稿等級：672×384、Turbo 8 步、INT8；每段 12 秒約 5.5 分鐘（含載入），段間冷卻 60 秒
- 獨立段用 t2va（`H3_T2VA=1`）；續接段用 ffmpeg 取前段末幀當 `H3_INPUT_IMAGE`
- `run_series.sh`：整批依序跑，已有的段會跳過；失敗就停
- `run_jobs.sh`：單獨重跑指定段或其他工作，格式 `名稱 prompt檔 seed 秒數 首幀|-`
- 每段完成後抽幾格檢查（接縫、文字、角色外觀）

### 7. 配樂（H3）
- Spark 沒有音樂模型，用 H3 生成「無人物的靜態花園畫面＋純配樂」（`prompts/music.txt`），只取音軌
- 跑 3 個 seed，用 ASR 檢查有沒有混進人聲，再給使用者挑；選定的存成 `music/bgm.wav`

### 8. 合成 → `mux.py`
- H3 原生音軌**全部靜音**（它會自己編出非中文的說話聲）
- 台詞放在分鏡起秒；前句沒講完就順延，講不完用 atempo 加速（一般上限 1.35，段尾最後一句上限 1.5）
- 時段太緊的句子，優先在 `lines.json` 把起秒提前到沒有人說話的空檔，而不是硬加速
- 配樂以 1.5 秒交叉淡化循環到片長，音量 0.22，頭淡入 1 秒、尾淡出 3 秒

### 9. 字幕 → `subs.py`
- 依合成時實際排定的時間產生繁體中文 SRT；角色台詞標名字，旁白不標
- 片尾標語放畫面上方（`{\an8}`）
- 字型 Noto Sans CJK TC；壓字幕版另存 `butterfly_sub.mp4`，原版保留

## 這次踩到的坑

| 問題 | 原因 | 解法 |
|---|---|---|
| 影片裡有聽不懂的說話聲 | H3 依 prompt 中「角色說話」自己生成人聲 | 合成時靜音原生音軌；prompt 加「無對白、無人聲」 |
| 結尾畫面出現亂碼字 | prompt 要求畫循環圖示，H3 自己加字 | 拿掉圖示，Qwen-Image 重做無文字首幀後重跑 |
| 小男孩聲音不像小孩 | 自動選的音色描述不準 | 改成候選人工挑選 |
| 4 句旁白混進日文／怪音（S04_09、S05_00、S09_00、S09_08） | reference 克隆在短句、並列詞上不穩 | 改 prompt 模式克隆＋ASR 篩選；把「長大後」改成「長大以後」也較穩 |
| ASR 核對漏掉一句壞句 | 只看錯字，沒注意漏字 | 漏字一律當壞句 |
| 「變乾」唸成 qián | 多音字判斷錯誤，TTS 無拼音標註 | 送 TTS 時以同音字「甘」替換 |
| 看圖擴寫加入多餘角色 | 8002 照圖把角色塞進特寫 | 擴寫後程式檢查角色名稱，人工刪除 |
| 獨立段畫風不一致（部分偏 3D） | t2va 段落沒有共用參考 | 尚未解決：可改為每段都用 Qwen-Image 首幀 |

## 時間參考（本例）

| 步驟 | 耗時 |
|---|---|
| 8002 擴寫 10 段 | 約 3 分鐘 |
| TTS 25 句＋5 個參考音 | 約 3 分鐘 |
| ASR 25 句 | 約 6 分鐘 |
| H3 10 段（672×384） | 約 55 分鐘 |
| Qwen-Image 首幀 3 張（turbo int8） | 約 1 分鐘 |
| 合成＋壓字幕 | 約 2 分鐘 |
