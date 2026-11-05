# 在另一台 DGX Spark 部署漫畫轉影片工作流

2026-11-04 依參考機（`funsteam@100.89.149.50`）現況整理：映像檔、compose、下載腳本、模型路徑都是實際盤點的結果。各步驟怎麼用、踩過哪些坑，見 [comic-to-video-workflow.md](comic-to-video-workflow.md)；本文只說「要裝什麼、裝在哪裡」。

## 0. 總覽

| 元件 | 參考機位置 | 用途 | 必要？ |
|---|---|---|---|
| MiniMax H3（ComfyUI＋INT8 權重＋Flex LoRA） | `~/h3-bench/`，映像 `h3-bench:latest` | 影片、配樂 | 必要 |
| Qwen-Image 2.1（ComfyUI :8188） | `~/qwen-image/`，映像 `qwen-image-studio:latest` | 首幀 | 必要（`h3-bench` 映像也以它為基底） |
| vLLM `qwen3.8-nvfp4`（:8006） | docker 容器，權重在 `~/.cache/huggingface` | 分鏡、擴寫、外觀、對嘴檢查 | 必要 |
| VoxCPM2 TTS（:8792） | `~/dgx-voxcpm-eval/.venv` | 配音；這個 venv 也跑音素比對 | 必要 |
| Breeze ASR（whisper.cpp CUDA） | `~/breeze-asr-hub/` | 核對 TTS、檢查配樂有沒有人聲 | 必要（沒有就要有 Xavier 備援） |
| `demucs-sfx` 映像 | 由 repo 的 `Dockerfile.sfx` build | 去人聲留音效、量開口 | 必要（`pipeline.sh` 會用） |
| llama.cpp（:8002） | `~/models/qwen3.6-abliterated/` | 2026-11-04 前的 LLM；`LLM_PORT=8002` 才會用到 | 選用 |
| `seed-vc` 映像 | `~/seed-vc-docker/` | 聲音轉換備案，尚未實測 | 選用 |

**參考機規格**：GB10、121 GB 統一記憶體、Ubuntu 24.04.4 aarch64、驅動 595.84、Docker 29.2。H3 跑的時候系統約用 71 GB。

**硬碟**：模型約 H3 70 GB（不含 `flex/` 原始下載 3.8 GB）、Qwen-Image 66 GB、vLLM 22 GB、VoxCPM2 4.7 GB、ASR 7.4 GB，合計約 170 GB。映像約 90 GB，其中 `h3-bench` 與 `qwen-image-studio`、`demucs-sfx`／`seed-vc` 與 pytorch 基底共用層。另外每篇作品的中間檔要預留數 GB。建議至少準備 **300 GB** 空間。

**統一記憶體三個共通設定**（ComfyUI 類服務都要加）：`PYTORCH_NO_CUDA_MEMORY_CACHING=1`、`--disable-mmap`、`--disable-pinned-memory`。沒加會讓權重佔兩份記憶體。

## 1. 主機基本環境

- NVIDIA 驅動、Docker＋NVIDIA Container Toolkit（`docker run --gpus all` 能跑）
- `ffmpeg`（apt）：主機上的 `mux.py`、`subs.py`、`sfx.sh` 會用到
- 系統 `python3` 不需要 numpy、torch，需要它們的腳本都在容器裡跑
- `hf` CLI（參考機是 `~/miniconda3/bin/hf`，`download_models.sh` 寫死這個路徑）
- 本機 → Spark 用 SSH 金鑰登入，腳本會用 `ssh`、`scp`、tar 管線傳檔

## 2. Qwen-Image（先裝，H3 映像要用它當基底）

照 Qwen-Image 部署筆記的「安裝步驟（從零重建用）」做：參考機 `~/qwen-image/DEPLOYMENT_NOTES.md`，副本在 Qwen-Image 部署 repo 的 `app/`。重點如下：

1. `~/qwen-image` 裡 `git clone` ComfyUI
2. `docker build -t qwen-image-studio:latest .`：基底 `nvcr.io/nvidia/pytorch:25.11-py3`，裝 ComfyUI requirements、gradio、pillow-heif，並**移除 torchaudio**
3. 從 `Comfy-Org/Qwen-Image-2.1` 下載模型到 `ComfyUI/models/`（diffusion_models、text_encoders、vae）
4. `docker compose up -d`。參考機的 `qwen-image-comfyui` 是 `restart: "no"`，按需啟動；Gradio 前端是 `restart: always`

`qwen_frame.py` 直接打 `:8188`，所以生首幀前要先 `docker start qwen-image-comfyui`。

## 3. MiniMax H3（`~/h3-bench`）

```bash
mkdir -p ~/h3-bench && cd ~/h3-bench
git clone https://github.com/Comfy-Org/ComfyUI.git
git -C ComfyUI checkout 1a82e6d01f395b43275c77acd289af1eb7090bb9
git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite
git -C ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite checkout 4d907be
```

**映像** `h3-bench:latest`：`FROM qwen-image-studio:latest`，加裝 ffmpeg，以及 ComfyUI 與 VideoHelperSuite 的 requirements（鎖住原本的 torch／torchvision／torchaudio／triton 版本）、`huggingface_hub`、`hf_xet`，再把 opencv 換成 headless。最後檢查 torch 是 CUDA 13。參考機的 Dockerfile 在 `~/h3-bench/Dockerfile`，請整份複製。

```bash
docker build -t h3-bench:latest ~/h3-bench
```

**權重**：參考機 `~/h3-bench/download_models.sh` 鎖定與 Colab 筆記本相同的 revision，下載到 `~/h3-bench/models/`：

| repo | revision | 檔案 |
|---|---|---|
| `Comfy-Org/MiniMax-H3` | `e5eb578a…` | `diffusion_models/minimax_h3_{ref2va,fl2va}_pruned_int8_convrot`、`vae/minimax_h3_video_vae_{int8_convrot,fp16}`、`vae/minimax_h3_audio_vae_fp32`、`loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16` |
| `Momoking/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4` | `0a9486d1…` | `text_encoders/qwen3vl_32b_heretic_minimax_h3_nvfp4` |
| `drbaph/MiniMax-H3-Turbo-Lora-ComfyUI` | `bb2bc497…` | `loras/minimax_h3_turbo_v4_step600_ema_pruned_comfyui` |
| `akatz-ai/MiniMax-H3-Character-Swap-LoRA` | `96ea3407…` | `loras/h3_character_swap_v1.5` |
| `Pika-Labs/Pika-H3-Flex` | `3ff16644…` | 只取 `comfy/loras/pika_h3_flex_{fl2va,ref2va}_comfy_bf16.safetensors`，放進 `models/loras/`。**不要**整個 repo 下載（約 200 GB） |

完整 revision hash 見 `download_models.sh` 和 [projects/flex-test/README.md](../projects/flex-test/README.md)。Flex 從 2026-11-01 起是預設；`-e H3_FLEX=0` 會切回 Turbo。

**執行方式**：工作流不常駐 ComfyUI。`run_series.sh`／`run_jobs.sh` 每段跑一次 `docker run --rm --name h3-<篇目> --gpus all --ipc host`，掛載 `~/h3-bench/ComfyUI`、`~/h3-bench/models` 和該段的 run 目錄，執行 `comic-video/bench.py`。`~/h3-bench/docker-compose.yml`（:8288）只在手動測試時用，平常不需要。

## 4. vLLM `qwen3.8-nvfp4`（:8006）

映像 `vllm/vllm-openai:nightly`。容器名稱必須是 `qwen3.8-nvfp4`，因為 `comic.py` 第一次呼叫 LLM 時會 `ssh … docker start qwen3.8-nvfp4`。

```bash
docker run -d --name qwen3.8-nvfp4 --gpus all --ipc host --network host \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:nightly \
  --model Jiunsong/SuperQwen3.8-27b-abliterated-NVFP4-DGX-Spark --trust-remote-code --served-model-name qwen3.8 \
  --reasoning-parser qwen3 --tool-call-parser qwen3_xml --enable-auto-tool-choice \
  --max-model-len 131072 --kv-cache-dtype fp8 --gpu-memory-utilization 0.35 \
  --kv-cache-memory-bytes 10737418240 \
  --speculative-config '{"method":"mtp","num_speculative_tokens":2}' \
  --max-num-seqs 4 --max-num-batched-tokens 8192 --no-enable-prefix-caching \
  --host 0.0.0.0 --port 8006
```

權重 2026-11-04 起從 `unsloth/Qwen3.8-27B-NVFP4` 換成無審查版 `Jiunsong/SuperQwen3.8-27b-abliterated-NVFP4-DGX-Spark`，其他參數不變。

上面的參數是從參考機 `docker inspect` 抄來的。網路模式與重啟策略請在新機用 `docker inspect qwen3.8-nvfp4` 對照。用不到時就停著，H3 跑的時候一定要停。

## 5. VoxCPM2 TTS（:8792）＋音素比對

```bash
mkdir -p ~/dgx-voxcpm-eval && cd ~/dgx-voxcpm-eval
# 從參考機複製：chinese_tts_server.py、scripts/setup_env.sh、RUNBOOK.zh.md
bash scripts/setup_env.sh        # 建 .venv：torch torchaudio torchcodec，voxcpm soundfile pandas
# 模型放 pretrained_models/VoxCPM2（約 4.7 GB；或用 VOXCPM_MODEL 環境變數指到別的位置）
```

- 這個資料夾在參考機上不是 git repo，`chinese_tts_server.py` 要從參考機複製
- 參考機 venv 的套件版本：torch 2.12、voxcpm 2.0.3
- 啟動：`source .venv/bin/activate && nohup python chinese_tts_server.py &`，port 用 `VOXCPM_PORT` 設定，預設 8792
- 日文版的音素比對（`phoneme_check.py` → Spark `phoneme_spark.py`）也用這個 venv。需要 librosa、transformers、huggingface_hub，第一次執行會下載 `facebook/wav2vec2-xlsr-53-espeak-cv-ft`

## 6. Breeze ASR（`~/breeze-asr-hub`）

```bash
git clone https://github.com/pondahai/breeze-asr-hub.git ~/breeze-asr-hub
cd ~/breeze-asr-hub && scripts/install.sh    # 會編譯 whisper.cpp（CUDA）
```

- 工作流只用 `engine/whisper.cpp/build/bin/whisper-cli`，**不需要**裝成開機服務（`service.sh`）
- 模型放 `models/`。安裝腳本**不會**下載 Breeze 模型：
  - `ggml-breeze-asr-26.bin`（2.9 GB，中文預設）：本地轉檔產生的，沒有公開下載點，直接從參考機 scp 過來
  - `ggml-large-v3-turbo.bin`（1.6 GB，日文用）：可用 whisper.cpp 的 `download-ggml-model.sh large-v3-turbo` 下載
  - `ggml-breeze-asr-25.bin`：舊版，可以不複製
- `asr_spark.sh` 啟動前會檢查 CLI 與模型；找不到就 exit 3，`asr_check.py` 改用 Xavier

## 7. `demucs-sfx` 映像

```bash
cd ~/h3-bench/comic-video        # repo 的 projects/comic-video 複製到這裡之後
docker build -t demucs-sfx -f Dockerfile.sfx .
```

build 時會把 htdemucs 權重抓進映像，之後離線也能跑。

## 8. 放上工作流腳本

- Spark 上的目錄比照 repo：把 `projects/comic-video/` 的共用腳本（`*.sh`、`*.py`、`bench.py`、`Dockerfile.sfx`）放到 `~/h3-bench/comic-video/`。各篇素材之後用 tar 經 ssh 傳到 `~/h3-bench/comic-video/<篇目>/`
- `.sh` 一定要是 LF 換行（`.gitattributes` 已設定）；從 Windows 傳過去之後先跑 `bash -n` 檢查
- 本機 Windows 需要 Python 3.12＋Pillow、OpenCC。本機沒有 ffmpeg，影音處理都在 Spark 做

### 寫死的主機位置（換機要改）

| 寫死的內容 | 檔案 |
|---|---|
| `100.89.149.50`／`funsteam@…` | `comic.py`（LLM URL、自動 `docker start`）、`asr_check.py`、`phoneme_check.py`、`qwen_frame.py`（:8188）、`tts.py`（:8792）、`draft_storyboard.py`、`draft_frame_prompts.py`、`expand.py`、`looks.py`、`mouth_spans.py`、`speaker_check.py` |
| `/home/funsteam/h3-bench/…` | `run_series.sh`、`run_jobs.sh`（docker `-v` 掛載）、`pipeline.sh` |
| `~/miniconda3/bin/hf` | 參考機 `~/h3-bench/download_models.sh` |

可以先用 `grep -rn "100\.89\|funsteam" projects/comic-video/*.py projects/comic-video/*.sh` 確認。比較好的做法是把這些值改成讀環境變數（例如 `SPARK_HOST`），預設值保留現在的設定。

## 9. 記憶體互斥（一定要照做）

TTS、Qwen-Image、H3 一次只能開一個。跑 H3 時要停掉 `qwen3.8-nvfp4` 和 `qwen-image-comfyui`。`pipeline.sh` 會自動做互斥檢查，並呼叫 Gradio 前端的 `/busy_status`。新機如果沒有 Gradio 前端，這個呼叫會失敗，要看腳本是否容忍，必要時加上判斷。

`restart: always` 的容器和 crontab `@reboot` 會在重開機後自己跑起來，跑 H3 前要確認它們都停了。服務的停止與復原方式見 [spark-baseline-2026-10-28.md](spark-baseline-2026-10-28.md)。

## 10. 驗收順序

1. `curl :8006/v1/models` 看到 `qwen3.8`；本機 `python draft_storyboard.py <小篇目>` 能出初稿
2. 啟動 TTS，`python tts.py <篇目>` 配一句；`python asr_check.py <篇目>` 輸出的第一行是 `INFO`（Spark），不是 `PREFLIGHT`（改用 Xavier）
3. `docker start qwen-image-comfyui`，`python qwen_frame.py <篇目> S01 1` 生出一張圖
4. 停 Qwen 與 vLLM，`ONLY=S01 bash run_series.sh <篇目>`。672×384、8 秒的 FL2VA 在參考機約 140 秒推論（含載入時間更長），檢查 `bench.log` 有出現 Flex LoRA
5. `bash sfx.sh <篇目>`、`python3 mux.py <篇目>`，產出 `mixed/` 試聽版
6. 全部通過後，再拿完整一篇跑 `pipeline.sh` 離線排隊

## 尚未驗證

- 本文是從參考機現況反推整理的，**還沒有在全新的 Spark 上從頭照做過**。第一次照做時，請把差異補回本文
- `seed-vc` 是選用的，本文沒有寫安裝細節，參考機的 Dockerfile 在 `~/seed-vc-docker/`
