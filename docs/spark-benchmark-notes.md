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

### 解析度測試（2026-10-29）

條件與測試 1 相同（同提示詞、首幀圖、seed、INT8、Turbo 8 步、12 秒），只把 notebook 裡的 `WIDTH, HEIGHT` 改成較低解析度。四個服務都暫停，兩支片連續跑，中間冷卻 2 分鐘。這次另外每 5 秒記錄一次 GPU 溫度、功耗、時脈、使用率（`gpu.log`）。

| 解析度 | 推論時間 | 整個任務 | 相對 1376×768 | 記憶體峰值 | GPU 最高溫 / 功耗 |
|---|---|---|---|---|---|
| 1376×768（測試 1，10/28） | 1770.5 s | 約 29.6 分 | 1× | 53 GB | 74°C / 約 77 W（抽樣） |
| 960×544 | **660.2 s** | 約 11.1 分 | 快 2.7 倍 | 50.8 GB | 85°C / 89 W |
| 672×384 | **260.1 s** | 約 4.5 分 | 快 6.8 倍 | 50.3 GB | 84°C / 81 W |

- 960×544 在 Spark 上的推論時間，已經和 Colab 跑 1376×768 的 640 秒差不多
- 加速比例比像素減少的比例還大：960×544 的像素是 1376×768 的 49%，時間卻只剩 37%
- 記憶體峰值三種解析度都在 50 GB 左右，主要被模型權重佔掉，和解析度關係不大
- 畫質還沒有逐格比對
- 輸出檔：`outputs/spark_bench_run2_960x544.mp4`、`outputs/spark_bench_run3_672x384.mp4`

### 純文字生影片 + 保留 llama.cpp（2026-10-29，run4_t2va）

照部署方針只保留 llama.cpp（8002），停掉 8006、8188、7860，跑一支沒有首幀的 t2va。`MiniMaxH3ImageToVideo` 的 `first_frame` 本來就是選填（節點說明寫 "t2va and fl2va"），只是 notebook 程式碼一定要讀首幀；`run4_t2va/bench.py` 加了 `H3_T2VA=1` 開關，開啟時不讀圖、節點不接 `first_frame`。

| 項目 | 設定 |
|---|---|
| 模式 | t2va（FL2VA 主模型，不接首幀），Turbo 8 步，INT8，Heretic 編碼器 |
| 解析度 / 片長 | 960×544 / 12 秒 |
| 提示詞 | 中式天庭構想，經 8002 擴寫（約 30 秒）；seed 164723 |
| 其他負載 | llama.cpp 8002 開著但閒置，生成期間沒有送擴寫請求 |

| | run2（四個服務全停，有首幀） | run4（只留 8002，t2va） |
|---|---|---|
| 推論時間 | 660.2 s | **620.2 s** |
| 整個任務 | 約 11.1 分 | 約 10.5 分 |
| 記憶體峰值（系統總用量） | 50.8 GB | **75.1 GB** |
| swap | — | 0.65 → 0.87 GB |
| GPU 最高溫 / 功耗 | 85°C / 89 W | 85°C / 87 W |

- **記憶體夠用**：開跑前 29 GB（系統加 llama.cpp），峰值 75.1 GB，和部署方針估算的約 78 GB 接近，121 GB 裡還剩約 46 GB
- **8002 全程可用**：每 5 秒檢查一次 `/health`，126 筆都是 200
- **速度沒有變慢**，但 run4 是 t2va、提示詞也不同，不能把快 40 秒歸因於任何一方。只能說 llama.cpp 閒置時看不出影響
- llama.cpp 的權重在統一記憶體的 GPU 配置裡，不算進程序 RSS（`llama.log` 只記到約 2.2 GB），要看記憶體壓力請看 `mem.log` 的總用量
- 沒有斷電；最高溫和斷電那次一樣是 85°C
- 執行腳本：`~/h3-bench/run_bench_t2va.sh run4_t2va`（另外記錄 `llama.log`：時間、llama-server RSS MB、8002 health 狀態碼）
- 輸出檔：`outputs/spark_run4_t2va_960x544_heaven.mp4`（960×544、12.25 秒、含音訊）

### 斷電事件（2026-10-28 20:22）

第一次跑 960×544 時，Spark 在推論約 8 分鐘時失去回應。隔天早上發現機器是**關機**狀態，開機後才恢復（10/29 08:32）。

- **不是 OOM**：記憶體穩定在約 48 GB（共 121 GB），最後一筆紀錄 20:22:17 也正常
- **日誌沒有留下任何錯誤**：上一次開機的 journal 在 20:22:05 結束，最後一筆只是普通的 SSH 登出。20:14 之後沒有任何 warning 以上的訊息，也沒有 NVRM、Xid、OOM、MCE、soft lockup
- 沒有開 kdump（`crashkernel=...:0M`），pstore 要 sudo 才能讀，目前沒有查
- 判斷：機器在沒有任何紀錄的情況下直接斷電，比較像**硬體保護機制直接切電**（過熱或電源過載），不像軟體當機
- 同一個負載，測試 1 完整跑了 29 分鐘，隔天重跑也正常，所以是偶發，不是每次都會發生
- 當時的紀錄保存在 Spark 的 `~/h3-bench/crash_20261028/`

預防方向（尚未實施）：
1. 散熱環境：出風口不要被擋、不要放在櫃子裡、注意晚上的室溫、清灰塵
2. 電源供應器：不要被壓住或包住，延長線的額定功率要夠
3. 溫度看門狗：GPU 超過門檻（例如 88°C）就中止推論。但只看得到 GPU 溫度，電源過熱擋不住
4. 用 `nvidia-smi` 限制時脈或功耗（GB10 是否支援還沒確認，代價是速度變慢）
5. 更新 DGX OS 和韌體

之後每次測試都有 `gpu.log`，每筆寫入後馬上 sync。如果再斷電，就能看到斷電前最後的 GPU 溫度和功耗，用來分辨是 GPU 過熱還是電源問題。

## 結論

1. **推論速度：Colab A100 明顯較快。** GB10 的算力和記憶體頻寬（273 GB/s）都遠低於 A100，實測結果和之前從規格做的推估一致
2. **Spark 的優勢在準備時間和穩定性**：每次省下約 3 分鐘的安裝和下載，沒有 503 搶不到 GPU 的問題，沒有 session 時間限制，也不扣 Colab 點數
3. **記憶體不是瓶頸**：Spark 專用時只用了 53 GB，Colab 上會超時的長片在 Spark 上可能跑得完（還沒驗證）
4. 照現在的設定直接搬到 Spark，一支 12 秒影片的等待時間會從約 13.5 分鐘變成約 30 分鐘
5. **降解析度是 Spark 上最直接的加速方法**：960×544 約 11 分鐘、672×384 約 4.5 分鐘。畫質能不能接受還要看過影片才能決定
6. **穩定性有風險**：發生過一次長時間滿載時斷電，原因還沒確定，正式部署前要先處理散熱和電源，並長時間連續跑測試

## 部署方針（2026-10-28 決定，尚未實施）

日後如果要把 H3 部署到 Spark，**只保留 llama.cpp（8002），停掉另外三個服務**：vLLM（8006）、Qwen-Image ComfyUI（8188）、Gradio（7860）。

理由：
- llama.cpp 是本專案「LLM 擴寫提示詞」功能的後端，保留它，寫提示詞和生影片可以一起用
- 估算記憶體：系統約 4 GB + llama.cpp 約 24 GB + H3 峰值約 50 GB ≈ 78 GB，121 GB 裡還留有約 40 GB 的餘裕
- vLLM 和 llama.cpp 同時保留會到約 117 GB，太緊；Qwen-Image 生圖時的用量會再往上加

| 服務 | 埠 | 可用記憶體 / 實測占用 | 處理 |
|---|---|---|---|
| llama.cpp（Qwen3.6-35B abliterated） | 8002 | 約 24 GB | **保留** |
| vLLM（Qwen3.8-27B） | 8006 | 34～39 GB | 停止 |
| Qwen-Image ComfyUI | 8188 | 閒置約 17 GB | 停止 |
| Gradio | 7860 | 幾乎不占 | 停止（依賴 8188） |

部署前要確認或處理的事：
- [x] **實測**：只保留 llama.cpp 時重跑，確認記憶體峰值和 H3 速度。2026-10-29 以 960×544 t2va 實測（run4_t2va）：峰值 75.1 GB、推論 620 s，見上方「純文字生影片 + 保留 llama.cpp」。1376×768 和 llama.cpp 同時擴寫的情況還沒測
- [ ] 停掉的三個服務設有 `restart: always` / `unless-stopped`，重開機或 docker daemon 重啟後會自動跑回來，要改重啟策略或另做處理
- [ ] H3 的 ComfyUI 如果要常駐，要確認跑完一支片後會釋放模型（約 40 GB 以上），不然會擠壓 llama.cpp
- [ ] 長片（超過 15 秒）的記憶體峰值還沒測過
- [ ] H3 和 llama.cpp 共用記憶體頻寬，同時使用時兩邊都會變慢

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
# 低解析度：run2（960×544）、run3（672×384）的 bench.py 第 185 行改寫了 WIDTH, HEIGHT
# 多支連續跑（每支之間冷卻 120 秒）：~/h3-bench/run_series.sh run2 run3
# 純文字 t2va（不需 first_frame.png）：~/h3-bench/run_bench_t2va.sh run4_t2va
# 3. 結果：bench.log（各階段 [h3-stage] 計時）、output.mp4、mem.log（每 5 秒記錄的記憶體用量）、
#    gpu.log（每 5 秒：時間 溫度°C, 功耗W, SM 時脈MHz, 使用率%）
# 4. 依 spark-baseline 文件恢復四個服務
```
