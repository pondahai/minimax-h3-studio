# DGX Spark 基準快照（2026-10-28 14:16 +08:00）

H3 測試前的原始狀態，測完復原時逐項比對。SSH：`funsteam@100.89.149.50`（金鑰登入）。主機已連續運行 27 天。

## 佔 GPU / 記憶體的服務（測試時要停）

| 服務 | 埠 | 啟動方式 | 重啟策略 | GPU 記憶體 | 停止 | 復原 |
|---|---|---|---|---|---|---|
| vLLM `qwen3.8-nvfp4`（unsloth/Qwen3.8-27B-NVFP4，`--gpu-memory-utilization 0.35`） | 8006 | 獨立 docker 容器 | unless-stopped | 約 39.4 GB | `docker stop qwen3.8-nvfp4` | `docker start qwen3.8-nvfp4` |
| llama.cpp（Qwen3.6-35B-A3B-abliterated Q4_K_M + mmproj） | 8002 | 主機程序，非 docker；crontab `@reboot` 執行 `~/models/qwen3.6-abliterated/start.sh` | 只在開機時啟動 | 約 24.1 GB | `kill <pid>`（盤點時 pid=629958，SIGTERM） | `nohup ~/models/qwen3.6-abliterated/start.sh >> ~/models/qwen3.6-abliterated/llama-server.log 2>&1 &` |
| ComfyUI `qwen-image-comfyui`（`--highvram --disable-mmap --disable-pinned-memory`） | 8188 | compose 專案 `qwen-image`（`~/qwen-image/docker-compose.yml`） | always | 約 17.0 GB | `docker compose stop`（在 `~/qwen-image` 執行） | `docker compose start` |
| Gradio `qwen-gradio-ui` | 7860 | 同上 compose | always | 透過 ComfyUI | 同上 | 同上 |

注意：
- `restart: always` 的容器手動停止後，**Spark 一旦重開機或 docker daemon 重啟就會自動跑回來**，crontab 也會把 llama.cpp 拉起來。測試期間要避免重開機，或者測試前先暫時調整。
- 本專案的「LLM 擴寫提示詞」功能連的是 8002，測試期間無法使用。

**復原範圍（使用者已確認）：只需要恢復上表四個服務**（vLLM 8006、llama.cpp 8002、ComfyUI 8188、Gradio 7860），其他項目都不在復原範圍內。

## H3 測試環境（2026-10-28 建立，與上述服務隔離）

- 目錄 `~/h3-bench`：`ComfyUI/`（commit 1a82e6d，與 Colab 相同）、`custom_nodes/ComfyUI-VideoHelperSuite`（4d907be）、`models/`（9 個檔案，已逐一比對 HF 大小）、`download_models.sh`、`Dockerfile`、`docker-compose.yml`
- 映像 `h3-bench:latest`：以 `qwen-image-studio:latest` 為基礎（torch 2.10 nv25.11、CUDA 13.0），補上 ComfyUI 的相依套件，並把 OpenCV 換成 headless 版。基礎映像本身沒有更動
- 容器 `h3-bench-comfyui`：8288 埠，`restart: "no"`（重開機不會自動啟動），沿用 Spark 的 `--disable-mmap --disable-pinned-memory`，但不加 `--highvram`
- 啟動：`cd ~/h3-bench && docker compose start`；停止：`docker compose stop`
- 驗證結果：ComfyUI 0.42.0，GB10 可正常使用，H3 和 VHS 的節點齊全，所有模型都看得到
- 目前狀態：已停止

## 測試 1 結果（2026-10-28 18:24–18:53）

對照組是 Colab 任務 `job_1793164723_ebf8`：FL2VA 首幀生影片、12 秒、橫式 1376×768、Heretic 編碼器、seed 164723、Turbo 8 步。Spark 端用同樣的輸入，執行同一份 notebook 程式碼（腳本為 `~/h3-bench/run_bench.sh run1`）。

| | Colab | Spark GB10 |
|---|---|---|
| 安裝 + 下載 + 啟動 ComfyUI | 172.9 s | 4.7 s |
| 推論（取樣 + 解碼） | **640.3 s** | **1770.5 s**（每步約 204 s，8 步共 1631 s） |
| 一次任務總計 | 約 13.5 分 | 約 29.6 分 |
| 記憶體峰值 | — | 53 GB（另有 swap 2.2 GB，是測試前就已存在的） |

- 推論本身 Spark 慢 **2.77 倍**。算上準備時間，單次任務總計約慢 2.2 倍
- 畫質：抽查第 0、144、287 幀，兩邊幾乎完全相同，沒有雜訊；影片長度和解析度也一致（12.25 s、1376×768、含音訊）
- 和 Colab 唯一的差異：ComfyUI 多加了 `--disable-mmap --disable-pinned-memory`
- 18:55 復原：四個服務（8006、8002、8188、7860）都有回應

## 輕量服務（不佔 GPU，可以照常運行）

- `litellm_gateway`：4000，docker，always（路由很可能指向 8006/8002，上游停止期間會回錯誤）
- `splitframe`：8005，docker（node），unless-stopped
- Hermes：user systemd 的 `hermes-gateway`、`hermes-dashboard`（9118/9119）
- 系統服務：dgx-dashboard、tailscaled、gnome-remote-desktop 等

已停止、不用處理：`qwen3.6-nvfp4`（Exited 0）、`diyllm-reader-demo`（Exited 137）。

## 記憶體 / GPU

- `free -h`：總計 121 Gi，已用 97 Gi，**可用 23 Gi**；swap 15 Gi 中已用 14 Gi
- GPU 程序：llama-server 24,055 MiB、vLLM 39,438 MiB、ComfyUI 16,959 MiB（合計約 80 GB）
- 驅動 595.84，GPU 使用率 0%（閒置）

## 硬碟

- `/`（nvme0n1p2，ext4）：916 G，已用 763 G，**可用 107 G（88%）**
- Docker：映像 55.95 GB（可回收 54.42 GB）、容器 3.5 GB
- 大目錄：`~/.cache/huggingface` 235G、`~/qwen-image` 101G、`~/models` 84G、`~/dgx-spark-playbooks` 51G、`~/breeze-asr-hub` 21G、`~/miniconda3` 16G、`~/下載` 15G

### H3 測試所需空間（依 Comfy-Org/MiniMax-H3 檔案大小）

| 檔案 | 大小 |
|---|---|
| ref2va_pruned_int8_convrot（DiT） | 20.97 GB |
| fl2va_pruned_int8_convrot（DiT，只有 FL2VA 測試才需要） | 20.97 GB |
| Heretic 文字編碼器 NVFP4 | 15.7 GB |
| video VAE int8 + fp16 | 2.81 + 5.21 GB |
| audio VAE | 0.61 GB |
| Turbo LoRA ×2、換人 LoRA | 約 4.1 GB |
| **小計** | **約 70 GB**（只測 Ref2VA 約 46 GB） |

再加上 ComfyUI 環境或容器映像（如果另外建，約 10～20 GB）和輸出影片，**全部裝完後剩餘空間大約只有 15～30 GB（使用率 97% 上下）**。可以做，但很緊，建議測試前先清出空間。

**更新：使用者已刪除 `openai/gpt-oss-120b`（122 GB），刪除後可用 229 G（74%）。**裝完 H3 後預計還剩 150 G 以上。

其他候選清理項目（尚未刪除）：未使用的 docker 映像（可回收約 54 GB）、`~/.cache/huggingface` 裡不再使用的模型、`~/下載`。
