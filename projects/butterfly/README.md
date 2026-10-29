# 漫畫轉影片工作流：《蝴蝶生命循環》

把一篇分格漫畫做成有配音、配樂、字幕的短片。**這是獨立的工作流，和本專案的 Studio 前端（`app.py`、`static/`）分開**：不經過 Colab，全部在 DGX Spark 上跑，用命令列腳本串起來。

- 來源：社子文教基金會「科學天地／自然小探險隊」[《蝴蝶生命循環》](https://shezi.org.tw/science/butterfly-life-cycle/)（7 格）
- 成品：約 119 秒、672×384 草稿等級，10 段（3 處首幀續接）
- 完整流程、注意事項與踩過的坑：[docs/comic-to-video-workflow.md](../../docs/comic-to-video-workflow.md)

## 流程圖

```text
 漫畫原圖（分格）
      │
      ▼
 ① 分鏡（人工）──────────── storyboard.md
      │  每段 ≤12 秒、秒級時間軸、台詞、末幀構圖
      ▼
 ② 擴寫（8002，附分格圖）── expand.py → prompts/
      │
      ├─▶ 檢查：時間軸一致？多出角色？畫面文字？前後外觀連續？
      │        └─ 有問題 → 人工修 prompt
      ▼
 ┌──────────── 以下三個服務互斥，一次只開一個 ────────────┐
 │                                                        │
 │ ③ 配音（TTS :8792）──────── tts.py → audio/            │
 │    │  每個角色做候選聲音 ──▶【人工挑選】               │
 │    │  逐句 prompt 模式克隆                             │
 │    ▼                                                   │
 │    ASR 核對（Jetson :8013）── asr_check.py             │
 │    │  錯字／漏字／多音字 → 重配 3 版 ──▶【人工挑選】   │
 │    ▼                                                   │
 │    關 TTS                                              │
 │                                                        │
 │ ④ 首幀（需要時，Qwen-Image :8188）── qwen_frame.py     │
 │    │  原漫畫＋影片角色當參考、無文字 ──▶【人工挑選】   │
 │    ▼                                                   │
 │    關 8188                                             │
 │                                                        │
 │ ⑤ 影片（H3，只留 8002）─── run_series.sh／run_jobs.sh  │
 │    │  672×384，獨立段 t2va，續接段取前段末幀當首幀     │
 │    │  每段抽幀檢查：接縫、文字、角色 → 有問題就重跑    │
 │    ▼                                                   │
 │ ⑥ 配樂（H3）── prompts/music.txt × 3 seed              │
 │    │  ASR 檢查無人聲 ──▶【人工挑選】→ music/bgm.wav    │
 └────┼───────────────────────────────────────────────────┘
      ▼
 ⑦ 合成 ── mux.py
      │  H3 原生音軌靜音、台詞依時間軸放入、配樂循環墊底
      ▼
 butterfly_draft.mp4（原版）
      │
      ▼
 ⑧ 字幕 ── subs.py
      │  繁中 SRT（依實際排定時間）
      ├──▶ butterfly.srt
      └──▶ butterfly_sub.mp4（壓字幕版）
                │
                ▼  CRF 27、AAC 96k、faststart
           butterfly_share.mp4（分享版）
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

## 檔案

| 檔案 | 用途 | 在哪跑 |
|---|---|---|
| `storyboard.md` | 分鏡：每段 ≤12 秒、秒級時間軸、台詞 | — |
| `expand.py` | 分鏡＋漫畫分格圖送 8002 擴寫 → `prompts/SXX.txt` | 本機 |
| `prompts/` | 影片 prompt 定稿（`music.txt` 是配樂）；`prompts_text/` 是純文字擴寫備份 | — |
| `tts.py` | 角色參考音＋逐句配音 → `audio/`；`python tts.py 小明` 只重配某角色 | 本機 |
| `asr_check.py` | 用 Breeze ASR 轉寫配音、和原文比對 | 本機 |
| `qwen_frame.py`、`frame_prompt.txt` | Qwen-Image 生成 16:9 首幀候選 → `frames/` | 本機 |
| `run_series.sh` | 依序生成全部分段，續接段自動取前段末幀 | Spark |
| `run_jobs.sh` | 單獨重跑指定段或配樂 | Spark |
| `mux.py` | 配音依時間軸混入、配樂循環墊底、串成 `butterfly_draft.mp4` | Spark（需 ffmpeg） |
| `subs.py` | 繁中字幕 `butterfly.srt`＋壓字幕版 `butterfly_sub.mp4`（原版不動） | Spark |
| `audio/lines.json` | 台詞、音檔、起秒、長度（合成與字幕的依據） | — |

影片、wav、圖檔不進 git，清單見 docs 筆記的「不進 git 的檔案」。

## 執行順序

1. 寫 `storyboard.md` → `python expand.py` → 檢查並修 `prompts/`
2. 啟動 TTS → 每個角色做候選聲音、**由人挑選** → `python tts.py` → `python asr_check.py` → 壞句重配 → 關 TTS
3. （需要時）啟動 8188 → `python qwen_frame.py ...` → 挑首幀 → 關 8188
4. 停掉 Spark 上 8002 以外的服務，把 `prompts/`、`bench.py`（672×384）、腳本放到 `~/h3-bench/butterfly/`，`bash run_series.sh`
5. 配樂：`bash run_jobs.sh "music1 prompts/music.txt 1 12 -" ...` → 挑選 → `music/bgm.wav`
6. 把 `audio/` 傳到 Spark → `python3 mux.py` → `python3 subs.py`
