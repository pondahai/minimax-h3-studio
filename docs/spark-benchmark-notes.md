# MiniMax H3：Colab vs DGX Spark 測試筆記

測試日期：2026-10-28
環境細節與復原程序：見 [spark-baseline-2026-10-28.md](spark-baseline-2026-10-28.md)

## 目的

本專案目前用 Colab 跑推論。這次要確認：用同樣的內容在 DGX Spark 上跑，速度和畫質差多少。網路上找不到同條件的比較，所以自己測。

## 測試條件

### 測試內容（兩邊相同）

| 項目 | 設定 |
|---|---|
| 對照任務 | Colab `job_1793164723_ebf8`（2026-10-28 05:18 UTC） |
| 模式 | FL2VA 首幀生成影片（first_frame），不換人 |
| 片長 / 比例 | 12 秒 / 橫式，輸出 1376×768、24 fps，含音訊 |
| 首幀圖 | `uploads/ref_img_e2ff971b_QwenImage21_20261027.png`，裁切方式 crop |
| 提示詞 / seed | 與該任務相同 / 164723 |
| 主模型 | `minimax_h3_fl2va_pruned_int8_convrot`（INT8） |
| 文字編碼器 | Heretic 未審查版 NVFP4（`qwen3vl_32b_heretic_minimax_h3_nvfp4`） |
| LoRA | `minimax_h3_turbo_v4_step600_ema_pruned_comfyui`（Turbo，8 步） |
| VAE | video fp16、audio fp32 |
| 程式碼 | 同一份 `assets/MiniMax_H3_Turbo_Colab.ipynb`（code cells 直接執行） |
| ComfyUI / VHS | commit 1a82e6d / 4d907be（與 Colab 鎖定版本相同） |
| 模型版本 | 與 Colab 鎖定的 HF revision 相同，9 個檔案都已比對大小 |

### 平台差異

| | Colab | DGX Spark |
|---|---|---|
| GPU | A100（介面預設，該次任務沒有記錄實際型號） | NVIDIA GB10，128 GB 統一記憶體 |
| PyTorch | Colab 預設環境 | 2.10.0 nv25.11，CUDA 13.0（NGC） |
| ComfyUI 參數 | 預設 | 額外加 `--disable-mmap --disable-pinned-memory`（Spark 統一記憶體需要） |
| 模型來源 | 每次都重新下載 | 預先存在硬碟上 |
| 其他負載 | 獨佔 | 測試期間暫停了四個常駐服務（vLLM、llama.cpp、ComfyUI、Gradio），只剩 litellm、splitframe 等輕量服務 |

## 結果

| 階段 | Colab | Spark |
|---|---|---|
| 安裝 | 22.9 s | 0.1 s |
| 下載模型 | 125.6 s | 0.0 s |
| 啟動 ComfyUI | 24.4 s | 4.2 s |
| **推論**（取樣加解碼） | **640.3 s** | **1770.5 s** |
| 總計 | 約 13.5 分 | 約 29.6 分 |

- Spark 的取樣每步約 204 秒，8 步共 1631 秒，約占推論時間的 92%；剩下的是 VAE 解碼
- **純推論 Spark 慢 2.77 倍；算上準備時間，整個任務慢約 2.2 倍**
- Spark 記憶體峰值 53 GB，128 GB 只用了不到一半。swap 2.2 GB 是測試前就已存在的
- GPU 溫度 74°C、功耗約 77 W，速度在整個過程中都很穩定

### 畫質

- 抽查第 0、144、287 幀：兩邊的構圖和動作幾乎完全相同，沒有雜訊（Blackwell 上某些 ComfyUI 版本會輸出全雜訊，這次沒有發生）
- 片長都是 12.25 秒，解析度、音軌也一致
- 同一個 seed 得到幾乎相同的畫面，間接證實 Colab 那次用的也是 INT8 主模型，兩邊的比較是公平的
- 輸出檔：`outputs/h3_job_1793164723_ebf8_mp4_job_1793164723_ebf8.mp4`（Colab）、`outputs/spark_bench_run1_job_1793164723_ebf8.mp4`（Spark）

## 結論

1. **推論速度：Colab A100 明顯較快。** GB10 的算力和記憶體頻寬（273 GB/s）都遠低於 A100，實測結果和之前從規格做的推估一致
2. **Spark 的優勢在準備時間和穩定性**：每次省下約 3 分鐘的安裝和下載，沒有 503 搶不到 GPU 的問題，沒有 session 時間限制，也不扣 Colab 點數
3. **記憶體不是瓶頸**：Spark 專用時只用了 53 GB，Colab 上會超時的長片在 Spark 上可能跑得完（還沒驗證）
4. 照現在的設定直接搬到 Spark，一支 12 秒影片的等待時間會從約 13.5 分鐘變成約 30 分鐘

## 尚未驗證

- Ref2VA／換人模式（這次只測了 FL2VA 首幀模式）
- 其他片長（推論時間隨片長的增加曲線），以及超過 15 秒的長片
- Spark 加速方案：Sol-Attn／Sol Engine、NVFP4 主模型、兩段式生成（網路上的資料聲稱可快 2～4 倍）
- 只跑了一次，沒有重複測量誤差；也沒有測熱啟動（模型已經載入）時的速度

## 重現方法

```bash
# 在 Spark 上（funsteam@100.89.149.50）
# 1. 依 spark-baseline 文件暫停四個服務
# 2. 執行測試（輸入放在 ~/h3-bench/<run>/：bench.py、first_frame.png、prompt.txt）
~/h3-bench/run_bench.sh run1
# 3. 結果：bench.log（各階段 [h3-stage] 計時）、output.mp4、mem.log（每 5 秒記錄的記憶體用量）
# 4. 依 spark-baseline 文件恢復四個服務
```
