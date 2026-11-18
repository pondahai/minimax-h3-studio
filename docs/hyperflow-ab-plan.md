# HyperFlow H3 Flash（14B）vs 現行 31B：A/B 測試大綱

狀態：大綱草稿，等使用者確認後才下載模型、改 `spark/bench.py`。

## 授權（2026-11-18 讀過 LICENSE／NOTICE）
- HyperFlow 是 MiniMax H3 的 Model Derivative（衍生模型），沿用同一份 **MiniMax H3 Community License**，和我們現在用的 31B 是同一份授權，沒有多出新條款。
- 地區限制：歐盟、英國、韓國、美國不在授權範圍內。我們在台灣跑，不受影響。
- 生成的影片（Output）不算衍生模型，所以上傳 YouTube 和現在一樣。
- 我們只在本地使用，不重新散布權重，所以不需要附授權副本、也不需要標註修改。
- 不是 MiniMax 官方產品，是 Video Rebirth 做的。

## 環境（唯讀檢查結果）
| 項目 | 現況 | 測試需要 |
|---|---|---|
| 磁碟 | 剩 63 GB（使用率 93%） | FL2VA int8 16.0 GB；之後加 Ref2VA 16.4 GB，剩約 30 GB |
| custom_nodes | 只有 VideoHelperSuite、SelfLift | 要加裝 **ComfyUI-HyperFlow-Flash**（int8 版不需要 GGUF 節點包） |
| 文字編碼器 | `qwen3vl_32b_heretic_minimax_h3_nvfp4` | 先沿用；官方建議的是 `nvfp4_awq`，要換的話另外抓 15.7 GB |
| VAE | 影像 fp16／int8、聲音 fp32 | 共用 ✅ |
| int8 執行環境 | 31B 已經用 int8_convrot 跑通 | 照理可直接用；README 要求 CUDA 13 的 PyTorch 或 triton，到時再確認 |
| 服務 | 目前有 `h3-owl01ab` 在跑 H3；8006 有開；8002 沒開 | 測試要等它跑完；照規則確認 8002 已停 |

## 兩組設定
| | A（現行） | B（HyperFlow） |
|---|---|---|
| 主模型 | `minimax_h3_fl2va_pruned_int8_convrot`（31B） | `minimax_h3_fl2va_hyperflow_flash_14b-int8_convrot`（13.7B） |
| 加速 | Pika Flex LoRA，6 步，sampler 為 lcm | 不加 LoRA（模型本身就是 few-step），官方預設 6 步，CFG=1 |
| 模式 | FL2VA（首幀生影片） | 同左 |

只換主模型和它自己的取樣設定，其他都一樣：首幀、prompt、TTS 錨點、seed、解析度。

## 測試素材
挑 journey07 的 3 個鏡頭，分別測：
1. 對話鏡頭：檢查對嘴，以及 TTS 錨點能不能用。
2. 動作或接續鏡頭：檢查動作是否連貫，首幀角色會不會變形。
3. 多角色鏡頭：檢查會不會多出人、畫面上會不會出現字。

## 跑法
1. 草稿 672×384，每個鏡頭 A、B 各跑 2 個 seed，共 12 支。
2. 草稿看起來有希望的話，再跑 `RES=full`（會自動開稀疏注意力），每個鏡頭 A、B 各 1 支。
3. 所有測試都停 8002，用 trap 還原。

## 記錄項目
- 耗時：載入時間和取樣時間分開記錄。
- 記憶體峰值。
- 輸出檔，並把 A、B 拼成左右並排的對照影片。

## 判定
- 打亂 A／B 順序做盲選，由使用者判斷畫質、對嘴、角色一致性。
- B 的畫質不輸 A，而且速度快 30% 以上，才考慮改預設。
- 如果採用，Ref2VA 版另外再測一輪。
- **換人功能**：2026-11-18 查過 HuggingFace，所有換人 LoRA 都是針對 31B 訓練的，沒有一個標明支援 HyperFlow 14B。搜尋過的包括 akatz-ai（我們現在用的）、RunningHub、Kobe202455、arthur-y 等約 8 個。14B 改過模型結構，這些 LoRA 預計套不上去。採用 14B 的話，需要換人的鏡頭要切回 31B。
- 另一個可以考慮的選項：`VideoRebirthAI/hyperflow` 是給 31B 原版用的 8 步加速 LoRA，可以和換人 LoRA 一起用，能當 C 組和 Flex 比。

## 需要使用者同意的步驟
1. 下載 FL2VA int8 模型（16.0 GB）到 Spark。
2. 在 h3-bench 容器裝 ComfyUI-HyperFlow-Flash 節點包：直接裝進共用的 `~/h3-bench/ComfyUI/custom_nodes`（使用者決定不另外隔離），**等使用者的生成工作做完、Spark 空檔時才裝**。
3. 改 `spark/bench.py`：新增 `H3_DIFFUSION=hyperflow`（預設不變），commit 後用 `deploy_bench.sh` 部署。
