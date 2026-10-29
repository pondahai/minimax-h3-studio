# 漫畫轉影片工作流程（復盤筆記）

首次實作：2026-10-29，社子文教基金會「科學天地／自然小探險隊」《蝴蝶生命循環》（7 格）→ 約 119 秒草稿影片
程式與素材：[`projects/comic-video/`](../projects/comic-video/)（共用腳本）、[`butterfly/`](../projects/comic-video/butterfly/)（這篇的分鏡、prompt、設定）

第二篇：2026-10-29，《密度是什麼？一樣大，不一定一樣重！》（7 格）→ 11 段約 130 秒，[`density/`](../projects/comic-video/density/)（進行中）

## 成品

| 檔案 | 內容 |
|---|---|
| `butterfly_draft.mp4` | 原版（無字幕）：672×384、10 段、TTS 配音＋配樂 |
| `butterfly_sub.mp4` | 壓字幕版（另外輸出，原版不動） |
| `butterfly.srt` | 繁體中文字幕檔 |

### 不進 git 的檔案（各篇的 `.gitignore`，以《蝴蝶》為例）

| 檔案 | 內容 | 存放位置 |
|---|---|---|
| `butterfly_draft.mp4`、`butterfly_sub.mp4`、`butterfly_share.mp4` | 成片（原版、壓字幕版、分享用瘦身版：壓字幕版以 CRF 27、AAC 96k、faststart 重新編碼，8.3 MB） | 本機 `projects/comic-video/butterfly/`、Spark `~/h3-bench/butterfly/` |
| `*.wav`（`audio/`、`audio/candidates/`） | 台詞配音、角色參考音、候選音 | 本機；配音另有一份在 Spark `~/h3-bench/butterfly/audio/` |
| `music/` | H3 配樂候選與選定的 `bgm.wav` | 本機、Spark |
| `frames/` | Qwen-Image 首幀候選 | 本機；選定的在 Spark `~/h3-bench/butterfly/frames/` |
| `contact_sheet.png` | 每 6 秒一格的總覽圖 | 本機 |
| `video/`、`mixed/` | 各段原始影片、配好音的各段 | Spark：`out/`（各段，含 `out/archive/` 舊版）、`mixed/` |
| 漫畫原圖 | 來源分格圖（版權屬原作者） | 本機暫存資料夾，`config.json` 的 `panel_dir` |

進 git 的是可重現成品的部分：共用腳本，以及各篇的 `config.json`、分鏡、prompt、`audio/lines.json`（台詞與排定時間）、字幕檔。Spark 上的完整工作目錄是 `~/h3-bench/butterfly/`（含各段的 `run/<段>/bench.log`）。

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
- 先定角色外觀表，全片一致；同系列沿用前一篇的角色外觀與參考音（`ref_<角色>.wav`），只有新角色才做候選
- 原漫畫若有科學錯誤要在分鏡稿註明並改正（例：《密度》第 4 格石頭標「密度比水小」，應為比水大）
- **畫面不要出現任何文字**（招牌、圖示標籤、標語）：H3 會畫成亂碼。標語改用字幕呈現
- **續接只用在同一景別、動作連續的段落**：續接段的首幀就是前段末幀，H3 只會延續那格畫面，不會從 prompt 補出場景。前段末幀要交代得出下一段的場景，不要停在特寫上
- **景別大幅切換（特寫↔全景）就開新段**，用 Qwen-Image 做自己的首幀，剪接上是一個「切」。反例：《密度》S07 停在軟木塞入水特寫，S08 續接後大水槽變成小杯子
- **時段不能太滿也不能太空**：約每 3–5 秒一個主要事件
  - 太滿，H3 會跳過：《密度》S08 4 秒內三樣東西依序沉底，結果一樣都沒拍到 → 改成「同時放手、一起下沉」一個事件
  - 太空，H3 會自己加戲（亂移鏡頭、換場景）：《密度》S01 3–7 秒只寫掂量海綿，鏡頭自己往下帶到空桌、切掉人物的頭（推測）
- 每個時段都要有看得見的變化（角色動作、道具變化或鏡頭運動）；安靜時段寫具體小動作（陽光閃爍、阿柴搖尾、鏡頭慢推），不要只寫「固定」
- 時間軸寫成因果順序（放手→下沉→觸底→驚訝），讓每一秒都有東西可畫
- **說台詞的時段寫成口型＋肢體動作**：配音用 TTS（各段音色一致），畫面讓說話的角色嘴巴開合、配手勢表情，大致對上 TTS 台詞的時段；旁白時段角色不開口（2026-10-29 起，《密度》S08 開始套用）

### 3. 擴寫（8002）→ `python expand.py <篇目>` → `prompts/SXX.txt`
- 風格、角色外觀、不放字規則寫在 `config.json`（`style`、`characters`、`no_text_rule`），system prompt 其餘部分全篇共用
- 每段送「分鏡表＋對應漫畫分格圖」；system prompt 規定：
  - 逐條保留時間區段，不得合併、刪改、重排
  - 圖片只參考外觀、配色、畫風；忽略圖中文字；不准加分鏡表沒有的角色或情節
  - 有角色台詞的時段寫口型（嘴巴開合像在說話）＋表情手勢，旁白時段角色不開口；不寫台詞內容、驚呼、喊叫；結尾加「音訊：無對白、無人聲，只有自然環境音與輕快的兒童配樂」（原生音軌合成時整條靜音）。《蝴蝶》與《密度》S08 以外各段是舊規則（不寫任何發聲動作）擴寫的
  - 每個時段至少一個看得見的變化，不要讓畫面靜止
- **擴寫後必查**（8002 會自由發揮）：`python check_prompts.py <篇目> [段...]` 自動做 1–5，6 人工看
  1. 時間軸和分鏡一致
  2. 有沒有多出來的角色（看圖版特別容易照圖把角色塞進特寫；整行角色外觀清單也會被抓出來，要刪掉沒出場的）
  3. 「」引號裡的畫面文字
  4. 動作密度：時段描述太短（少於 15 字）、或寫了「固定／停留」卻沒有動作
  5. 有角色台詞的時段有沒有寫口型
  6. 前後段外觀是否連續（例如毛毛蟲顏色、蛹的顏色）
- 有問題直接人工改 prompt 檔

### 4. 配音（TTS）→ `python tts.py <篇目>`
1. 啟動 TTS：`cd ~/dgx-voxcpm-eval && source .venv/bin/activate && nohup python chinese_tts_server.py &`
2. **角色聲音人工挑選**：每個角色用不同的音色描述生成 3–4 個候選，給使用者挑完才繼續（不能自動選定）。使用者偏好台灣口音：描述裡寫「台灣華語口音」「台灣國語腔調」等（《密度》林博士選「六十多歲的台灣男教授，標準台灣華語口音，沉穩親切，語速慢」）
   - 台灣腔的參考音，ASR 容易聽錯（質量→資料），要人工試聽判斷，不能只看 ASR
3. 選定的音檔存成 `audio/ref_<角色>.wav`
4. 每句台詞用參考音克隆。**用 prompt 模式**（`clone_mode=prompt`＋`prompt_text`＝參考音的逐字稿）；reference 模式在短句、並列詞上容易唸出非中文
5. **ASR 核對**：`python asr_check.py <篇目>` 逐句轉寫，和原文比對。壞句每句重配 3 個版本，ASR 篩過後給使用者挑
6. 判讀 ASR：
   - **漏字也算壞句**：S05「長大後，牠找到…」ASR 只轉出「他找到…」，前三個字其實唸成了日文，第一次核對時被當成 ASR 誤差放過
   - ASR 會認錯同音字（卵→段落、蛹→勇），這種代表發音正確；轉成不同音的字（蛹→有）才是可疑
   - 最後一律以人工試聽為準
7. **送 TTS 前一律轉簡體**（`config.json` 的 `t2s: true`，`tts.py` 用 OpenCC t2s；《蝴蝶》為 false 以保留當時做法）：VoxCPM2 對繁體字常唸錯，例如《密度》S08「硬幣、湯匙」繁體送三次都唸成怪音，換同音字、改說法也沒用，轉簡體「汤匙」一次就對。原稿、字幕、`lines.json` 保留繁體
8. **多音字唸錯**（例：「變乾」的乾唸成乾坤的 qián）：VoxCPM2 不支援拼音標註，只能在送給 TTS 的文字裡換成同音、沒有歧義的字（乾→甘），字幕和 `lines.json` 保留正確的字；或改說法（變乾→乾燥）
9. 台詞錯字（例：「一隻小小的卵」→「一顆」）要同步改 `storyboard.md`、`lines.json`，再重配那句
10. 關閉 TTS 再進下一步

### 5. 首幀（Qwen-Image）→ `python qwen_frame.py <篇目> <名稱> 3 <參考圖...>`
- 《蝴蝶》只在需要重做的段落用（S10）；《密度》起改為**所有獨立段都先做首幀**：道具、圖解多的漫畫用 t2va 容易亂，也順便解決獨立段畫風不一致
- 續接段仍用前段末幀；首幀構圖要和該段 0 秒的分鏡一致（例：分鏡寫「走進畫面」，首幀卻已站好，就改分鏡與 prompt）
- 挑 seed 時特別看時間軸衝突：動作的結果不能已經在首幀出現（木塊已浮在水裡、油層已倒好）
- 每段一個 prompt：`frame_prompts/<名稱>.txt`，輸出 `frames/<名稱>_seedN.png`；參考圖＝原漫畫分格＋前一篇影片抽出的角色畫面
- 參考圖：原漫畫分格＋影片中已生成的角色畫面（讓畫風和角色對齊影片）
- 直接輸出 16:9（1344×768），negative prompt 排除文字；生成 3 個 seed 給使用者挑
- 開 `qwen-image-comfyui` → 生成 → 關閉

### 5.5 分鏡審查（使用者）→ `python review.py <篇目>` → `review.html`
- 建議 seed 與理由寫在 `review.json`；首幀完成後產出審查頁：每段首幀候選（標建議 seed 與理由）＋時間軸、鏡頭、台詞；續接段註明接前段末幀
- 使用者審查、選定首幀後才開始跑 H3

### 6. 影片生成（H3）→ `bash run_series.sh <篇目>`／`bash run_jobs.sh <篇目> ...`
- 草稿等級：672×384、Turbo 8 步、INT8；每段 12 秒約 5.5 分鐘（含載入），段間冷卻 60 秒
- 獨立段用 t2va（`H3_T2VA=1`）；續接段用 ffmpeg 取前段末幀當 `H3_INPUT_IMAGE`
- 段落表在 `config.json` 的 `shots`：`[段, 秒數, 首幀來源]`，首幀來源 `-`＝t2va、圖檔路徑（如 `frames/S01.png`，選定的 seed 複製改名）＝用該圖、段名＝續接該段末幀
- 從 Windows 傳到 Spark 的 `.sh` 要先轉成 LF 換行，否則 bash 會報 `$''` 指令找不到；`comic-video/.gitattributes` 已固定 `.sh` 為 LF，啟動前仍先 `bash -n` 檢查語法
- Spark 上的目錄比照 repo：`~/h3-bench/comic-video/`（共用腳本＋`bench.py`）、`~/h3-bench/comic-video/<篇目>/`。《密度》已搬到新位置（第一批 11 段是重整前用舊腳本跑的）；《蝴蝶》還在 `~/h3-bench/butterfly/`
- 重跑某段：把舊檔移到 `out/archive/<段>_v1.mp4`、`run/<段>_v1/`，更新 prompt／首幀／`config.json` 後 `bash run_series.sh <篇目> <段>`（其他已存在的段會跳過）
- `run_series.sh`：整批依序跑，已有的段會跳過；失敗就停
- `run_jobs.sh`：單獨重跑指定段或其他工作，格式 `名稱 prompt檔 seed 秒數 首幀|-`
- 每段完成後抽幾格檢查（接縫、文字、角色外觀）

### 7. 配樂（H3）
- Spark 沒有音樂模型，用 H3 生成「無人物的靜態畫面＋純配樂」，只取音軌
- **prompt 一定要用官方格式**（見下方「H3 prompt 格式」）：`[Shot 1]` 寫空景、`overall_soundscape` 只寫風聲鳥鳴、`non_diegetic_music` 寫樂器、節奏、力度。範例 `density/prompts/music_official.txt`
  - 《密度》先用中文自由格式（結尾「純音樂，無對白、無人聲」）跑 seed 1、2，兩首都混進說話聲；改官方格式後同一個 seed 1 就乾淨。《蝴蝶》當時 3 首也有 1 首混人聲，原因相同
- 跑 1 首、ASR 檢查（轉不出文字，只回 `<|7.55|>` 之類的時間戳＝乾淨）→ 給使用者聽；有人聲再換 seed。選定的存成 `music/bgm.wav`

### 8. 合成 → `python3 mux.py <篇目>`
- H3 原生音軌**全部靜音**（它會自己編出非中文的說話聲）
- 台詞放在分鏡起秒；前句沒講完就順延，講不完用 atempo 加速（一般上限 1.35，段尾最後一句上限 1.5）
- 時段太緊的句子，優先在 `lines.json` 把起秒提前到沒有人說話的空檔，而不是硬加速
- 配樂以 1.5 秒交叉淡化循環到片長，音量 0.22，頭淡入 1 秒、尾淡出 3 秒

### 9. 字幕 → `python3 subs.py <篇目>`
- 依合成時實際排定的時間產生繁體中文 SRT；角色台詞標名字，旁白不標
- 片尾標語放畫面上方（`{\an8}`）
- 字型 Noto Sans CJK TC；壓字幕版另存 `butterfly_sub.mp4`，原版保留

## H3 prompt 格式（官方，2026-10-29 查證）

來源：專案內的官方 Colab notebook（`assets/MiniMax_H3_Turbo_Colab.ipynb`）與 MiniMax 官方〈[Video Prompt Writing Guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md)〉。Studio 前端（`scripts/runner.py`）一直照這個格式寫，所以不會出現胡言亂語。

```
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.   ← 有首幀時才加（t2va 沒有）

integrated_multimodal_description: [Shot 1] …畫面、動作、說話者、台詞…
[Shot 2] At 00:04.000, the camera cuts to …

overall_soundscape: 1–4 句英文，環境音、動作聲、非語言人聲；不寫台詞

non_diegetic_music: 1–3 句英文，樂器、速度、節奏、力度；不寫抽象情緒；沒有配樂填 N/A
```

- 英文書寫；台詞保留原文放在 `<d>[Chinese] …</d>`，說話者編號 `(S1)` 寫在標籤外
- **只有 `<d>` 裡的內容會被唸出來**；不說話的角色不給說話者編號。官方沒有「無人聲」的寫法，寫了也沒用
- 旁白：`says in an off-screen voiceover`，並寫明畫面角色嘴巴閉著
- 台詞跨切鏡用 `<scenetrans>`，影片結束時話沒講完用 `<cutoff>`
- **漫畫流程到目前為止（《蝴蝶》全片、《密度》全片）都用中文自由格式**，是 H3 會編出非中文說話聲、配樂混人聲的主因。影片段落改用官方格式（`expand.py` 輸出英文結構化 prompt，台詞放 `<d>` 讓 H3 對嘴，合成時仍換成 TTS）待討論定案

## 這次踩到的坑

| 問題 | 原因 | 解法 |
|---|---|---|
| 影片裡有聽不懂的說話聲、配樂混人聲 | prompt 不是官方格式（中文自由段落），H3 自己猜音軌 | 合成時靜音原生音軌；配樂改官方格式後解決；影片段落待改 |
| 結尾畫面出現亂碼字 | prompt 要求畫循環圖示，H3 自己加字 | 拿掉圖示，Qwen-Image 重做無文字首幀後重跑 |
| 小男孩聲音不像小孩 | 自動選的音色描述不準 | 改成候選人工挑選 |
| 4 句旁白混進日文／怪音（S04_09、S05_00、S09_00、S09_08） | reference 克隆在短句、並列詞上不穩 | 改 prompt 模式克隆＋ASR 篩選；把「長大後」改成「長大以後」也較穩 |
| ASR 核對漏掉一句壞句 | 只看錯字，沒注意漏字 | 漏字一律當壞句 |
| 繁體「湯匙」唸成怪音（《密度》） | VoxCPM2 對繁體字不熟 | 送 TTS 前一律 OpenCC 轉簡體 |
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
| Qwen-Image 首幀 3 張（turbo int8） | 約 1 分鐘（《密度》7 段×3 張約 10 分鐘，首張含載入約 1 分鐘） |
| 合成＋壓字幕 | 約 2 分鐘 |
