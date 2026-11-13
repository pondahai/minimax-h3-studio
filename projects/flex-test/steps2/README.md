# H3 2 步測試（Spark，2026-11-13）

同 11/01 Flex A/B 素材（咖啡館首幀、`prompt_fl2va.txt`／`prompt_ref2va.txt`）、seed 164723、8 秒 672×384。腳本 [`../run_steps2.sh`](../run_steps2.sh)，用 Spark 上 `flex/bench_steps.py`（`flex/bench.py` 複本，加 `H3_STEPS`、`H3_SIGMAS` 覆寫；正式 bench 未動）。

- Turbo 2 步：`BasicScheduler` steps=2
- Flex 2 步：`ManualSigmas` `1.0, 0.8, 0.0`（從官方 6 步 sigmas 取點，非官方設定）

| 模式 | 原步數（推論） | 2 步（推論／整支） |
|---|---|---|
| FL2VA Turbo | 8 步，170 秒 | 80 秒／90 秒 |
| FL2VA Flex | 6 步，140 秒 | 80 秒／90 秒 |
| Ref2VA Turbo | 4 步，約 100 秒 | 80 秒／90 秒 |
| Ref2VA Flex | 6 步，約 130 秒 | 70 秒／77 秒 |

推論時間是 10 秒輪詢粒度，2 步時固定開銷（編碼、VAE 解碼、音訊）佔大半。

抽幀觀察（每 2 秒一張，`cmp_*_grid.png`）：
- 4 組都沒崩：人臉、毛衣、杯子、背景構圖與原步數幾乎相同，動作時間點一致。
- 2 步整體偏亮、偏軟，細節（毛衣紋理、窗外樹）略糊。
- Flex 6 步背景有走動的人，Flex 2 步沒有：次要動態被省掉。
- Ref2VA Flex 2 步最後一段撥頭髮時手擋臉，比 6 步不自然。
- 動態流暢度與嘴型需看影片判斷。

## 已加入 Studio（2026-11-13）

- 前端解析度選單新增「草稿 672×384・2 步」（`resolution: "draft_fast"`，只在 Spark 有效）。
- `app.py` 轉成 manifest `fast_steps: 2`，`runner.py` 轉成 `H3_FAST_STEPS=2`。
- Spark `studio/bench.py`、`comic-video/bench.py` 讀 `H3_FAST_STEPS`：Turbo 改 `STEPS`，Flex 改 sigmas `1.0, 0.8, 0.0`；原檔備份 `*.bak_prefast`。
- 走 `runner.run_batch`＋Spark 實跑 FL2VA 一支：推論 80 秒（與上表一致），8002 自動還原。
- shotswap 頁面未加此選項。

對照影片 `cmp_*.mp4`（左原步數、右 2 步，音軌為 2 步版），不進 git。
