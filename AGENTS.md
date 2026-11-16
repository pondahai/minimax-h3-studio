# AGENTS.md：給接手這個 repo 的 AI agent

這個 repo 用 MiniMax H3 在自家 DGX Spark 上生成兒童動畫：把漫畫轉成有配音、配樂、字幕的影片。另外還有一個 Studio 前端（`app.py`、`scripts/runner.py`）。

## 先讀這三份
1. **[docs/comic-to-video-runbook.md](docs/comic-to-video-runbook.md)**：每一集照這份從上往下做（取材 → 交件共 11 步）。每一步分「前置／做／停／完成」，「停」的地方一定要等使用者決定。
2. [docs/comic-to-video-notes.md](docs/comic-to-video-notes.md)：每一步為什麼這樣做，以及踩過的坑。遇到問題先查這份。
3. 範例集：`projects/comic-video/journey07/`（config、storyboard、prompts、成品都有）。

腳本在 `projects/comic-video/`，用法 `python <腳本> <篇目> …`。進行中的計畫放在 `docs/*-plan.md`。

## 名詞對照（說明時學名一律附俗名）
| 學名 | 俗名 |
|---|---|
| Ref2VA | 參考圖生影片 |
| FL2VA | 首幀生影片（可加尾幀） |
| T2VA | 文生影片 |
| Flex／Turbo | 兩種加速 LoRA；Spark 預設 Flex，`H3_FLEX=0` 改用 Turbo |
| sol-attn（`H3_SPARSE=1`） | 稀疏注意力（少算一點） |
| 8006 | 本地 LLM（vLLM），負責分鏡、prompt 擴寫、對嘴檢查 |

## 硬性規則
**全部在本地跑**
- 生成都在 Spark 和 Jetson 上做，不用 Colab，也不用雲端影片服務。
- 這個 repo 是**公開的**：真人（尤其兒童）的照片、立繪原圖不要 commit。

**使用者要決定的事，不能自己定**
- 角色聲音：先生成候選讓使用者挑，挑好才能做影片。
- 首幀的 seed、分鏡、配音試聽、成品驗收。

**分工**
- 由 8006 起稿，agent 審稿，再交回 8006 修。不要自己把 8006 的輸出整個重寫。
- 審稿意見寫進 config 的 `panel_notes`【審稿意見】，再重跑腳本，然後回報 8006 照做了哪些。

**畫面**
- 角色立繪：純白素色背景、全身、一張只畫一個角色、沒有任何字。
- 首幀 prompt 不寫有名角色的名字（悟空、八戒…），只寫外觀，並加「畫面裡剛好只有這 N 個人」。
- 畫面上不能有字：海報、螢幕、印章都寫「沒有字」。

**鏡頭銜接**
- 接續的鏡頭：從上一段輸出中擷取最後一幀（凍結之前的那一幀）當下一段的首幀。不要另外生成一張「很像」的首幀。
- 一個鏡頭只換一級景別。
- 要從特寫拉遠，或物理結果要維持住（例如浮起、沉下）時，用首尾幀，尾幀用 Qwen 畫。

**H3 prompt**
- 用官方英文結構化格式（新集數用 `prompt_format: official_mixed`）。
- 台詞只放在 `<d>[Chinese] …</d>` 裡；其他地方寫明沒有對白、沒有人聲。
- 每句台詞都要有秒數（4 字／秒，童聲 3.5 字／秒）；一段最多 12 秒。

**配音**
- 用台灣華語口音；送進 TTS 前轉成簡體（`t2s: true`）。
- ASR 抓到的錯讓使用者用耳朵判斷。

**解析度**
- 預設出 672×384 草稿。正式版加 `RES=full`，會自動開稀疏注意力。

**交件**
- `pipeline.sh` 跑到 `DONE` 只是草稿。之後還要跑 `subs.py`、做分享版（CRF 27）、跑 `speaker_check.py`，所有版本一次交出。
- YouTube 文案照前一集 README 的長度與語氣寫。

**記錄**
- 學到的新東西當下就寫進 notes 的踩坑表；如果改變了某一步的做法，同步改 runbook。

## Spark（DGX，Tailscale 內網）
- 登入：`ssh funsteam@100.89.149.50`（金鑰登入）。不在內網就只能做文件和腳本的部分。
- ASR 備援機：Jetson Xavier，`nvidia@100.108.74.45`。
- **記憶體互斥**：TTS、ComfyUI（Qwen-Image）、H3 不能同時開。每一步要開關哪些服務，照 runbook 開頭那張表做。
  - 腳本大多會自動開關：`tts.py`、`qwen_frame.py`、`pipeline.sh` 都會。
  - 自己寫的 H3 測試要先停 8002，並用 trap 確保結束後還原。
- **呼叫服務前**：先花 5 秒檢查埠有沒有開，沒開就立刻啟動並告訴使用者。
  - 遠端啟動一律用 `ssh -n … "setsid -f cmd > log 2>&1 < /dev/null"`。
  - ssh 字串裡的 pkill／pgrep 關鍵字要寫成 `[c]hinese_tts` 這種形式，否則會砍到自己的 ssh。
- ComfyUI 8188 用 `curl -X POST http://127.0.0.1:8190/ensure` 叫醒，不要直接 `docker start`。
- **H3 推論程式**：只改 repo 裡的 `spark/bench.py`，用 `bash spark/deploy_bench.sh` 部署。不要 ssh 上去直接改。
- Windows 本機沒有 ffmpeg，影音處理都在 Spark 上做。

## 暫不採用（使用者沒提就不要提議）
- RefMod
- Sol-H3
- 2K 超解析放大
- H3 閉源的 Context-IR 和 Regenerate-2K
