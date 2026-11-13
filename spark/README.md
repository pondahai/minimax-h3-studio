# Spark 端 H3 推論腳本

`bench.py` 是 DGX Spark 上跑 MiniMax H3 的唯一一份推論腳本，Studio（`scripts/runner_spark.py`，story-film-studio 也透過它）與漫畫轉影片（`projects/comic-video/run_jobs.sh`、`run_series.sh`）共用。

## 規則

- **以 repo 為準**：只改 `spark/bench.py`，commit 後執行 `bash spark/deploy_bench.sh` 部署到 Spark `~/h3-bench/bench.py`。不要再 SSH 上去直接改。
- 部署腳本會檢查語法、拒絕未 commit 的改動（`FORCE=1` 可略過）、有 H3／Demucs 在跑時拒絕，舊檔備份為 `bench.py.bak-<時間>`，並把 commit 寫進 `~/h3-bench/bench.py.rev`。
- Spark 上 `studio/bench.py`、`comic-video/bench.py` 是指向 `../bench.py` 的 symlink，只為相容舊腳本（`intro/` 等），新腳本請直接用 `~/h3-bench/bench.py`。
- 實驗用的分支版本（例如 `flex/bench_steps.py`）可以放在 Spark 實驗目錄，但要正式使用就要併回這裡。
- Colab notebook（`assets/MiniMax_H3_Turbo_Colab.ipynb`）仍是另一份，改推論邏輯時兩邊都要改。

## 為什麼之前不在 repo（2026-11-13 查明）

1. 2026-10-28 比較 Spark 與 Colab 速度時，把 Colab notebook 的程式碼倒成 `bench.py`（檔頭仍有 `# ---- cell 3`），當作一次性測試輸入放在 Spark `~/h3-bench/run1/`。
2. 10-29 漫畫轉影片直接沿用這支測試檔正式生產；外圍腳本進了 repo，`bench.py` 沒有。
3. 11-01 Studio 接 Spark 時又複製一份成 `studio/bench.py`。
4. 之後每次功能都直接在 Spark 上改兩份，repo 只留部分 patch（`projects/*/bench_*.patch`），尾幀與 2 步的改動沒有 patch。

沒有人決定「不收」，是測試檔升格為正式程式時少了收進 repo 這一步。
