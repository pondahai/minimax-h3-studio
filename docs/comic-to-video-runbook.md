# 漫畫轉影片：每集步驟清單

每集開工照這份從上往下做。每一步：**前置**（先確認／先關什麼）→ **做**→ **停**（要等使用者決定的事，不能自己定）→ **完成**（交出什麼）。
某一步「為什麼這樣做」、過去的試驗與踩坑，查 [comic-to-video-notes.md](comic-to-video-notes.md)。進度寫在各集 `README.md` 的「進度」，一步一行、當下就寫。

腳本都在 `projects/comic-video/`，用法 `python <腳本> <篇目> …`。Spark＝`funsteam@100.89.149.50`。

## Spark 服務與記憶體（每一步開跑前看這張）

| 這一步 | 要開 | 要關 |
|---|---|---|
| 分鏡、首幀 prompt、擴寫、對嘴檢查（LLM） | 8006（`comic.llm()` 會自動 `docker start`） | — |
| 配音、聲音候選 | TTS :8792（`tts.py` 會自動開） | — |
| 首幀、立繪（Qwen-Image） | ComfyUI :8188（`qwen_frame.py` 自動叫醒） | **TTS**（`qwen_frame.py` 自動關） |
| H3 影片、配樂（`pipeline.sh`） | 8006（2026-11-06 起常駐） | 8002、TTS、ComfyUI（`pipeline.sh` 自動停，跑完還原 8002／TTS） |

- 呼叫服務前 5 秒檢查埠有沒有開；遠端啟動一律 `setsid -f … < /dev/null`
- ssh 字串裡的 `pkill -f`／`pgrep -f` 關鍵字寫成 `[c]hinese_tts` 這種形式，否則會砍到自己的 ssh
- Windows 本機沒有 ffmpeg，影音處理都在 Spark
- 跑長工作前看 GPU 溫度與 `free -g`；一張立繪超過 3 分鐘＝記憶體被搶，先查誰開著

## 1. 取材
- **做**：抓官網原圖 `https://shezi.org.tw/assets/images/panels/journey-NN/`（header、panel-01～12）→ `<篇目>/source/`；逐格讀圖
- **做**：寫 `README.md`：每格內容表（台詞原文、角色）＋「原作矛盾／待決定」（印章編號、說話者分配、畫面上的字、新角色、科學／安全問題），每點附建議
- **停**：使用者決定每一點
- **完成**：README 記下決定

## 2. 新角色聲音
- **前置**：同系列角色直接複製前一集 `audio/ref_<角色>.wav`
- **做**：新角色 3–4 個音色描述（寫「台灣華語口音」），生成候選 → `audio/candidates/candidates.html`，送給使用者
- **停**：使用者挑聲音（不能自己選）
- **完成**：`audio/ref_<角色>.wav`

## 3. config.json
- **做**：以前一集為底：`title`、`source`、`style`／`style_en`（只寫畫風與大場景，不寫道具）、新角色的 `voices`、`ref_transcript`、`names_en`、`looks_en`、`characters(_en)`、`char_refs`、`panel_cast`、`panel_dir`（指 `source/`）、`tagline`
- **做**：`panel_notes` 每格寫：場景、誰在畫面、逐句台詞＋說話者、【時間表】（4 字／秒，童聲 3.5；12 秒一段，超過就拆兩段）
- 台詞內層引號一律用『』；畫面上不能有字（海報、螢幕、印章都寫「沒有字」）；格序調換時連 `source/` 檔名一起對調

## 4. 新角色立繪
- **前置**：TTS 已關（`qwen_frame.py` 會自動關）
- **做**：從原圖裁該角色（避開對話框）當參考 → `frame_prompts/char_<角色>.txt`（純白背景、全身、只有一個角色、沒有任何字）→ `python qwen_frame.py <篇目> char_<角色> 3 <裁圖>`
- **停**：使用者挑 seed（先排除有字、帶背景的）
- **完成**：`frames/char_<角色>.png`，加進 `char_refs`

## 5. 分鏡
- **做**：`python draft_storyboard.py <篇目>`（8006 逐格）→ `storyboard_8006.md`
- **做（人工修）**：核對每格都有出現、台詞沒被縮短、說話者照決定、印章編號、`check_storyboard.py` 結果 → `storyboard.md`（檔尾寫修訂說明）
- **停**：使用者確認分鏡
- **完成**：`storyboard.md`

## 6. 配音
- **做**：`python tts.py <篇目>` → 列出超出時段的句子；`python asr_check.py <篇目>`（漏字也算壞句）
- **做**：超時的挪時段或縮句；壞句重配 3 版給使用者挑；`audio/lines.html` 試聽頁
- **停**：使用者試聽通過
- **完成**：`audio/*.wav`、`audio/lines.json`；**關 TTS**

## 7. 首幀
- **前置**：TTS 已關
- **做**：`python draft_frame_prompts.py <篇目>`（8006）→ 人工修：不寫角色名只寫外觀（悟空→棕髮男孩）、要說話的角色都在畫面、無人段不帶 style 也不給參考圖
- **做**：每段 3 seed（`frame_refs.json` 記每段參考圖）→ 總覽圖 `frames/contact_frames_*.png`，附建議 seed 與理由
- **停**：使用者選首幀
- **完成**：`frames/SXX.png`；`config.json` 加 `shots`（續接段寫前段段名）、`panels`、`last_frames`

## 8. H3 prompt
- **做**：`python expand.py <篇目>` → `python check_prompts.py <篇目>`；人工看多出的角色、畫面文字、無人段有沒有被寫進人物
- 格式（2026-11-06 起）：分鏡表每列一個 `[Shot N] At 00:0X.000, the shot cuts to the next moment of the same scene: …`（`[Shot 1]` 不寫時間戳）；有尾幀的段用官方首尾幀開頭句。舊寫法是 `prompt_format: official_inline`
- **新格式還沒在漫畫段落實跑過**：第一次用時先只跑一段 H3，看有沒有在每列真的硬切，再決定整集用哪個格式
- **做**：配樂 prompt `prompts/music_official.txt`（官方格式，空景＋樂器）

## 9. H3 影片（Spark 離線）
- **前置**：素材 tar 到 Spark `~/h3-bench/comic-video/<篇目>/`；`.sh` 是 LF
- **做**：`setsid nohup bash pipeline.sh <篇目> > <篇目>/pipeline.log 2>&1 < /dev/null &`（重導只寫一次）；看 `pipeline.status`
- 使用者要中途暫停就照 notes 的「中途暫停」做；續跑時已有的段會跳過
- **完成**：`pipeline.status` 最後一行 `DONE`

## 10. 驗收
- **做**：抽幀總覽 `contact_video/`、`all_*.jpg`；`python speaker_check.py <篇目> …`；配樂讓使用者試聽（有人聲就換 seed）
- **停**：使用者允收（或指定重跑哪幾段）

## 11. 交件
- **做**：`subs.py` → `_sub.mp4`、`.srt`；分享版 CRF 27／AAC 96k → `_share.mp4`；拉回本機
- **做**：README「成品」與「YouTube」段（照前一集的長度與語氣：約 110 字故事、3 點「會學到」、下集預告、原作出處、#標籤）
- **做**：本集新學到的事寫進 notes 的踩坑表；若改變了某一步的做法，同步改本檔
- **完成**：交出所有版本並 commit

## 日文版（中文版完成後另做，只重配聲音）
計畫與各篇進度：[japanese-version-plan.md](japanese-version-plan.md)；踩坑見 notes「日文版」段。
- **做**：寫 `<篇目>_ja/lines_ja.json`（片名、角色日文名、每句台詞＋全假名讀音，助詞は寫わ；秒數照中文版）→ `python ja_scaffold.py <篇目>`：產生 storyboard、config（`lang: ja`、`t2s: false`、日文字型）、校稿檔，複製參考音，提示偏長的句子
- **停**：校稿檔給日文同事校對，回來後改 `lines_ja.json` 重跑 `ja_scaffold.py`
- **做**：Windows 上設 `PYTHONIOENCODING=utf-8`；`tts.py <篇目>_ja` → `asr_check.py <篇目>_ja`（Whisper large-v3-turbo＋音素比對；Spark 有 H3 在跑就等它結束）
- **做**：ASR 錯字或音素比對標出的句子重配 3–5 版，`asr_check.py <篇目>_ja <候選 wav…>` 篩過，只把通過的給使用者挑
- **停**：使用者試聽（音素比對抓不到全部，最後以耳朵為準）
- **做**：Spark 建 `<篇目>_ja/`：`video`、`music` symlink 到中文版，`sfx/` 只連 `*_novocals.wav`（lipsync、align 是中文台詞量的，不能沿用）→ `mux.py` → `subs.py` → share 版；**關 TTS**
- **完成**：`_sub.mp4`、`_share.mp4` 交給使用者；計畫的進度表更新
