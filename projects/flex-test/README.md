# Pika H3 Flex vs Turbo LoRA：Spark A/B 實測

測試日期：2026-11-01
結論：畫質 Flex 較好（使用者看片判斷），**Spark 上的 FL2VA、Ref2VA 自 2026-11-01 起預設改用 Flex**；`H3_FLEX=0` 可切回 Turbo。

## Flex 是什麼、從哪來

- Pika 以 MiniMax H3 為底做後訓練（post-trained）的開放權重版本，2026-10 底發布，主打 6 步生成（原版 H3 50 步）。授權沿用 MiniMax H3 Community License。
- 來源：Hugging Face [`Pika-Labs/Pika-H3-Flex`](https://huggingface.co/Pika-Labs/Pika-H3-Flex)，鎖定 revision `3ff166447d5edb1406107ab8370c42000ce173e4`
- 官方介紹：[Pika Blog](https://pika.art/blog/pika-h3-flex)、[技術說明](https://pika.art/blog/pika-h3-flex-research)、[ComfyUI 教學](https://docs.comfy.org/tutorials/video/pika/pika-h3-flex)
- 我們只用 `comfy/loras/` 下的兩個 ComfyUI 版 LoRA（各 1.96 GB，`sha256sum -c SHA256SUMS` 通過），疊在既有的 H3 INT8 主模型上，**不需要**下載 repo 裡約 200 GB 的 diffusers 完整權重：
  - `pika_h3_flex_fl2va_comfy_bf16.safetensors` → 配 `minimax_h3_fl2va_pruned_int8_convrot`
  - `pika_h3_flex_ref2va_comfy_bf16.safetensors` → 配 `minimax_h3_ref2va_pruned_int8_convrot`
- Spark 位置：`~/h3-bench/models/loras/`（原始下載與授權檔在 `~/h3-bench/flex/`）

## 取樣設定（不能只把步數改成 6）

照官方 workflow 模板（`video_pika_h3_flex_fl2va.json`／`_ref2va.json`）：

| 項目 | Turbo（舊） | Flex（新） |
|---|---|---|
| LoRA | FL2VA：`minimax_h3_turbo_v4_step600_ema_pruned_comfyui`；Ref2VA：`minimax_h3_ref2v_turbo_4step_v0.1` | 上面兩個 Flex LoRA，強度 1.0 |
| sampler | `euler` | `lcm` |
| sigmas | `BasicScheduler`（beta），FL2VA 8 步／Ref2VA 4 步 | `ManualSigmas`：`1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0`（6 步） |

改動見 [`bench_flex.patch`](bench_flex.patch)（Spark 上 `comic-video/bench.py`、`studio/bench.py` 都套用，原檔備份為 `*.bak_preflex`）。Pika 的 README 註明 ComfyUI 版尚未做端對端驗證，本實驗就是我們自己的驗證。

## 實驗條件

- 機器：DGX Spark（GB10），只留 llama.cpp 8002，TTS 與 Qwen-Image 關閉
- 素材：Qwen-Image 2.1 生成的寫實真人首幀 [`first_frame.png`](first_frame.png)（咖啡館女性，seed 2）；FL2VA 當首幀、Ref2VA 當參考圖
- 提示詞：[`prompt_fl2va.txt`](prompt_fl2va.txt)、[`prompt_ref2va.txt`](prompt_ref2va.txt)（官方結構化格式，一句中文台詞＋啜飲、撥頭髮動作）
- 672×384、8 秒、Heretic 編碼器、INT8；seed 164723 與 42 各跑一次；工作間冷卻 30 秒
- 執行腳本：[`run_ab.sh`](run_ab.sh)

## 結果

| 模式 | A：Turbo | B：Flex | 差別 |
|---|---|---|---|
| FL2VA | 8 步，總 180 秒（推論 170 秒） | 6 步，總 149 秒（推論 140 秒） | Flex 快約 17% |
| Ref2VA | 4 步，總 109 秒 | 6 步，總 138 秒 | Flex 慢約 27% |

- 兩個 seed 的秒數幾乎一樣，數字穩定。
- 官方宣稱的「快 1.8 倍」是對 50 步原版；我們本來就用 Turbo，所以速度幾乎沒賺到，換 Flex 是為了畫質。
- 抽幀看動作與人臉一致性兩邊相同（同首幀同 seed，構圖走向一致）；畫質差異需看動態，使用者判斷 Flex 較好。
- 冒煙測試：改完後用正式 `comic-video/run_jobs.sh`（FL2VA）與 `studio/bench.py`（Ref2VA）各跑一支，推論 140 秒／130 秒，與 Flex 實驗一致。

對照影片（每支前 8 秒 A、後 8 秒 B）在本機本資料夾 `ab_*.mp4`，不進 git；Spark 上在 `~/h3-bench/flex/test/out/`。

## 影響範圍

- **會變成 Flex**：Spark 上的漫畫轉影片流程（`comic-video/run_jobs.sh`、`run_series.sh` 用的 `comic-video/bench.py`）與 Studio 的 Spark 後端（`scripts/runner_spark.py` 用的 `studio/bench.py`）。
- **不受影響**：Colab notebook（`assets/MiniMax_H3_Turbo_Colab.ipynb`）仍是 Turbo；Spark 上舊的 `butterfly/`、`run_bench*.sh` 各用自己那份 bench.py。
- 換人模式也走 Ref2VA，所以同樣預設 Flex（實測見下節）。

## 換人模式疊 Flex（2026-11-02）

### 換人：Turbo vs Flex

- 原片：上面 FL2VA Turbo seed 164723 的咖啡館女性（`fl_A1.mp4`，8 秒）當 `<Video 1>`
- 新角色：Qwen-Image 生成的寫實男性（眼鏡、短鬍、深藍襯衫，純白背景）[`swap_char.png`](swap_char.png) 當 `<Picture 1>`
- 提示詞 [`prompt_swap.txt`](prompt_swap.txt)，腳本 [`run_swap.sh`](run_swap.sh)（用正式 `studio/bench.py`，`H3_CHARACTER_SWAP=1`）

| | Turbo 4 步 | Flex 6 步 |
|---|---|---|
| 總時間（seed 164723／42） | 259／249 秒 | 338／349 秒 |

兩組都成功換成新角色，眼鏡、鬍子、襯衫、背景、動作時間點都保留；Flex 慢約 35%。換人維持預設 Flex。

### 換人＋換聲

- 問題：換人後樣貌換了，聲音仍是原片女聲。即使加了 `<Audio 1>`（《影子》林博士參考音，`comic-video/shadow/audio/ref_林博士.wav`）並在提示詞要求用它的音色，結果仍與原片相同。
- 原因：`bench.py` 把原片音軌接到 `ref_video_audios.ref_video_audio_N`，模型照它重生成原聲，`<Audio>` 音色被蓋掉。
- 實驗：同提示詞（[`prompt_swapvoice.txt`](prompt_swapvoice.txt)），只差有沒有送原片音軌：

| | 中位音高 |
|---|---|
| 原片（女） | 250 Hz |
| 換人＋`<Audio 1>`，送原片音軌（2 個 seed） | 250 Hz，與原片完全相同 |
| 換人＋`<Audio 1>`，不送原片音軌（2 個 seed） | 112 Hz |
| 林博士參考音 | 108 Hz |

  每支約 330 秒。對照影片 `ab_voice_*.mp4`（前 8 秒送、後 8 秒不送，不進 git）。
- 定案：Spark 的 `studio/bench.py`、`comic-video/bench.py` 改成「換人模式且有 `<Audio>`」時自動不送原片音軌，`H3_VIDEO_AUDIO=1／0` 可強制開關；改動見 [`bench_voice.patch`](bench_voice.patch)，原檔備份 `*.bak_prevoice`。只換人不給 `<Audio>` 時行為不變（保留原聲）。
- Colab：notebook 原本接法相同，所以同樣換不了聲。在 Spark 用 Turbo＋強制送原片音軌（`H3_FLEX=0 H3_VIDEO_AUDIO=1`，等同 Colab 圖）重現，音高 242 Hz 仍是原片女聲。`assets/MiniMax_H3_Turbo_Colab.ipynb` 已套用同樣邏輯，2026-11-02 在 Colab A100 實跑（同素材、seed 164723、8 秒、1376×768）：日誌顯示不送原片音軌，音高 118 Hz（林博士 108 Hz），換聲成功；推論 270 秒、全程 8 分鐘、約 1 CU。
- 前端：`app.py` 的 LLM 擴寫在換人＋有 `<Audio>` 時加上換聲規則（`EXPAND_SWAP_VOICE_RULES`）；`index.html` 的導演分鏡、固定換人指示、換人勾選框說明同步改成換聲寫法；長片分段換人改成每段都帶 `<Audio>`（尚未實跑）。

### 換聲後第一句沒聲音（2026-11-02，教訓）

- 現象：從 Studio 用 LLM 擴寫的提示詞換人＋換聲，開頭原片嘴型在動卻沒聲音，新聲音到 5.2–7.5 秒才出現（原片說話在 0.2–2.8 秒）。之前 Spark／Colab 測試沒踩到，因為手寫提示詞剛好有 `At 00:00.000 … speaks`。
- 根因：一般換人時，原片音軌送進模型，聲音與嘴型的時間由它對齊。換聲為了讓 `<Audio>` 生效拿掉原片音軌，也一併拿掉了「何時說話」的唯一來源。擴寫 LLM 只看得到原片幾張畫面、聽不到聲音，規則又禁止自編時間點，台詞就被寫在描述最後；H3 照文字順序把台詞排到動作之後。
- 修正（PR #17）：擴寫時後端以音量偵測原片人聲時段（`app.py` 的 `_speech_spans`），告訴 LLM，換聲規則要求台詞以 `At mm:ss.mmm` 寫在同一時段。修正後人聲 0.3–2.5 秒。
- 限制：只看音量，原片有大聲配樂或噪音時可能誤判成說話；目前只用咖啡館原片測過。

教訓：
1. **拿掉一個條件輸入前，先列出它原本提供了哪些資訊。** 原片音軌同時提供「音色」和「時間」，只想到要換音色。
2. **測試要走使用者實際的路徑。** 手寫提示詞把時間寫好了，掩蓋了擴寫路徑的缺口；改完要用前端＋LLM 擴寫實跑一次。
3. **驗收不只看「有沒有換成功」，要看時間軸。** 只量音高（110 Hz）會判定成功；逐 0.5 秒量音量、對照原片說話時段，才看得出聲音位置錯了。
4. **H3 沒有時間點時依文字順序安排。** 台詞要對齊畫面，提示詞就要寫明時間點。

## Colab 改用 Flex（2026-11-02）

同素材（真人首幀、`prompt_fl2va.txt`／`prompt_ref2va.txt`）、seed 164723、8 秒，在同一個 Colab A100 session 依序跑 4 支（1376×768）。只比推論時間（第一支另含安裝與下載）：

| 模式 | Turbo | Flex | 差別 |
|---|---|---|---|
| FL2VA | 8 步，321 秒 | 6 步，240 秒 | Flex 快 25% |
| Ref2VA | 4 步，171 秒 | 6 步，240 秒 | Flex 慢 41% |

- Flex LoRA 在 Colab 下載約 4 秒，幾乎不增加成本。4 支共用約 3 CU。
- 定案：Colab 的 FL2VA 預設 Flex，Ref2VA 為省 CU 留在 Turbo 4 步（使用者決定）。notebook 的 `H3_FLEX` 預設依模式而定，runner manifest 可用 `flex: true／false` 強制；不填就交給各後端預設（Spark 兩種都用 Flex）。
- 修改：notebook 下載清單加入鎖定版本的 Flex LoRA（repo 內在 `comfy/loras/`，下載後搬到 `models/loras`）、取樣改 `lcm`＋`ManualSigmas`；`scripts/backup_models.py` 的 Drive 備份清單加入兩個 Flex LoRA。
- 對照影片 `colab/ab_colab_cfl.mp4`、`colab/ab_colab_cref.mp4`（不進 git）。
