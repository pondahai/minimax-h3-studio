# ---- cell 3
import os, shutil, subprocess, sys, torch
# 心跳與階段計時（CLI 用）：runner 以「8 分鐘沒有任何一行輸出」判定卡死，
# 但下載數十 GB 的權重時 huggingface 進度條只用 \r 重畫、不換行，會被誤判。
# 準備階段（安裝、下載、啟動 ComfyUI）每 30 秒印一行心跳；推論等待有自己的進度輸出，不加心跳，真的卡住仍會被抓到。
# 每階段結束印「[h3-stage] 名稱 秒數」，runner 會另外保存，用來量每鏡各階段耗時。
import threading as _h3_threading, time as _h3_time
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
if "H3_HB" not in globals():          # 同一個 session 連跑多鏡時 kernel 不重啟，只建一次
    H3_HB = {"stage": "install", "t": _h3_time.time()}

    def _h3_beat():
        from pathlib import Path as _P
        while True:
            _h3_time.sleep(30)
            if not H3_HB["stage"]:
                continue
            extra = ""
            try:
                gib = sum(f.stat().st_size for f in _P("/content/ComfyUI/models").rglob("*") if f.is_file()) / 2**30
                extra = f"，models {gib:.1f} GiB"
            except Exception:
                pass
            print(f"[h3-heartbeat] {H3_HB['stage']} {_h3_time.time() - H3_HB['t']:.0f}s{extra}", flush=True)

    _h3_threading.Thread(target=_h3_beat, daemon=True).start()


def h3_stage(done, nxt):
    now = _h3_time.time()
    print(f"[h3-stage] {done} {now - H3_HB['t']:.1f}s", flush=True)
    H3_HB.update(stage=nxt, t=now)


H3_HB.update(stage="install", t=_h3_time.time())

from pathlib import Path

assert torch.cuda.is_available(), "請在 Colab「執行階段 > 變更執行階段類型」選擇 GPU。"
print("GPU:", torch.cuda.get_device_name(0))
print("VRAM GiB:", round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1))
print("PyTorch CUDA:", torch.version.cuda)
print("Free disk GiB:", round(shutil.disk_usage("/content").free / 2**30, 1))
# 網頁 notebook 可改為 "reference"；CLI launcher 會自動設定。
INFERENCE_MODE = os.environ.get("H3_INFERENCE_MODE", "first_frame").strip().lower()
assert INFERENCE_MODE in {"first_frame", "reference"}, "H3_INFERENCE_MODE 請使用 first_frame 或 reference。"
GPU_CAPABILITY = torch.cuda.get_device_capability(0)
CUDA_MAJOR = int((torch.version.cuda or "0").split(".", 1)[0])
if INFERENCE_MODE == "reference":
    if CUDA_MAJOR >= 13 and GPU_CAPABILITY >= (8, 0):
        REF2VA_VARIANT = "int8_convrot"
    elif GPU_CAPABILITY >= (8, 9):
        REF2VA_VARIANT = "fp8_scaled"
    else:
        REF2VA_VARIANT = "bf16"
else:
    REF2VA_VARIANT = None
MINIMUM_FREE_DISK = 80 * 2**30 if REF2VA_VARIANT == "bf16" else 60 * 2**30
assert shutil.disk_usage("/content").free >= MINIMUM_FREE_DISK, (
    f"目前選用 {REF2VA_VARIANT or 'FL2VA'} 模型，至少需要 {MINIMUM_FREE_DISK / 2**30:.0f} GiB 可用磁碟。"
)
assert shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg 與 ffprobe 才能輸出並檢查 MP4 音訊。"
COMFY = Path("/content/ComfyUI")
VHS = COMFY / "custom_nodes" / "ComfyUI-VideoHelperSuite"
SETUP_MARKER = Path("/content/.h3_comfyui_setup_v1")
# 鎖定上游程式版本：每次都抓最新版，上游一改節點參數就可能壞掉。設 H3_PIN_UPSTREAM=0 改回抓最新版。
PIN_UPSTREAM = os.environ.get("H3_PIN_UPSTREAM", "1") == "1"
COMFYUI_COMMIT = "1a82e6d01f395b43275c77acd289af1eb7090bb9"  # 2026-10-22 實測可用
VHS_COMMIT = "4d907bee61e92c2e65af3bd6383a4e4d356126d1"      # 2026-09-02


def clone_repo(url, path, commit):
    if not PIN_UPSTREAM:
        subprocess.run(["git", "clone", "--depth", "1", url, str(path)], check=True)
        return
    path.mkdir(parents=True)
    for args in (["init", "-q"], ["remote", "add", "origin", url],
                 ["fetch", "-q", "--depth", "1", "origin", commit], ["checkout", "-q", "FETCH_HEAD"]):
        subprocess.run(["git", "-C", str(path), *args], check=True)
    print("鎖定版本:", url, commit[:10])


if SETUP_MARKER.exists():
    assert COMFY.is_dir() and VHS.is_dir(), "Colab setup marker exists, but ComfyUI files are missing; remove /content/.h3_comfyui_setup_v1 and retry."
    print("重用本次 Colab session 已安裝的 ComfyUI 環境")
else:
    if not COMFY.exists():
        clone_repo("https://github.com/Comfy-Org/ComfyUI.git", COMFY, COMFYUI_COMMIT)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(COMFY / "requirements.txt"), "huggingface_hub", "hf_xet", "pillow", "requests"], check=True)
    if not VHS.exists():
        clone_repo("https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git", VHS, VHS_COMMIT)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(VHS / "requirements.txt")], check=True)
    SETUP_MARKER.touch()
print("ComfyUI:", COMFY)

h3_stage("install", "download")


# ---- cell 5
from huggingface_hub import hf_hub_download

BASE_REPO = "Comfy-Org/MiniMax-H3"
# 文字編碼器（H3_TEXT_ENCODER）：heretic（預設）＝社群未審查版；official＝Comfy-Org 官方，同為 NVFP4 15.7 GB，可直接替換
TEXT_ENCODER_CHOICE = os.environ.get("H3_TEXT_ENCODER", "heretic").strip().lower()
assert TEXT_ENCODER_CHOICE in {"official", "heretic"}, "H3_TEXT_ENCODER 請使用 official 或 heretic。"
if TEXT_ENCODER_CHOICE == "heretic":
    TEXT_ENCODER_REPO = "Momoking/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4"
    TEXT_ENCODER_REMOTE = "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors"
else:
    TEXT_ENCODER_REPO = BASE_REPO
    TEXT_ENCODER_REMOTE = "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
TEXT_ENCODER = Path(TEXT_ENCODER_REMOTE).name
print("Text encoder:", TEXT_ENCODER_CHOICE, TEXT_ENCODER)
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"

if INFERENCE_MODE == "reference":
    DIFFUSION = f"minimax_h3_ref2va_pruned_{REF2VA_VARIANT}.safetensors"
    VIDEO_VAE = "minimax_h3_video_vae_int8_convrot.safetensors" if REF2VA_VARIANT == "int8_convrot" else "minimax_h3_video_vae_fp16.safetensors"
    LORA_REPO = BASE_REPO
    LORA_REMOTE = "loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
    print("Ref2VA variant:", REF2VA_VARIANT, "(CUDA", torch.version.cuda, "; GPU capability", GPU_CAPABILITY, ")")
else:
    LORA_REPO = "drbaph/MiniMax-H3-Turbo-Lora-ComfyUI"
    DIFFUSION_VARIANT = "auto"  # 可改為 "fp8_scaled" 或 "int8_convrot"。
    assert DIFFUSION_VARIANT in {"auto", "fp8_scaled", "int8_convrot"}
    if DIFFUSION_VARIANT == "int8_convrot" and not (torch.version.cuda or "").startswith("13."):
        raise ValueError("官方建議 int8 ConvRot 使用 CUDA 13.x PyTorch；請改用 auto 或 fp8_scaled。")
    use_int8 = DIFFUSION_VARIANT == "int8_convrot" or (
        DIFFUSION_VARIANT == "auto" and (torch.version.cuda or "").startswith("13."))
    DIFFUSION = ("minimax_h3_fl2va_pruned_int8_convrot.safetensors" if use_int8
                 else "minimax_h3_fl2va_pruned_fp8_scaled.safetensors")
    VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
    LORA_REMOTE = "minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors"

model_files = [
    (BASE_REPO, "diffusion_models/" + DIFFUSION, "diffusion_models"),
    (TEXT_ENCODER_REPO, TEXT_ENCODER_REMOTE, "text_encoders"),
    (BASE_REPO, "vae/" + VIDEO_VAE, "vae"),
    (BASE_REPO, "vae/" + AUDIO_VAE, "vae"),
    (LORA_REPO, LORA_REMOTE, "loras"),
]
LORA = Path(LORA_REMOTE).name
# Pika H3 Flex（2026-11-01 A/B 實測畫質較好）：FL2VA、Ref2VA 都預設用 Flex LoRA＋官方 6-NFE sigmas＋lcm；H3_FLEX=0 切回 Turbo（Ref2VA 用 Flex 6 步比 Turbo 4 步慢約 27%）
FLEX = os.environ.get("H3_FLEX", "1") == "1"
if FLEX:
    LORA = "pika_h3_flex_ref2va_comfy_bf16.safetensors" if INFERENCE_MODE == "reference" else "pika_h3_flex_fl2va_comfy_bf16.safetensors"  # 手動放進 models/loras（Pika-Labs/Pika-H3-Flex@3ff16644 comfy/loras）
    model_files = [f for f in model_files if Path(f[1]).name != Path(LORA_REMOTE).name]
# 換人模式（H3_CHARACTER_SWAP=1）：疊加社群 Character Swap LoRA，<Video 1> 原片＋<Picture 1> 新角色
CHARACTER_SWAP = os.environ.get("H3_CHARACTER_SWAP", "0") == "1"
SWAP_LORA = None
if CHARACTER_SWAP:
    assert INFERENCE_MODE == "reference", "換人模式需使用 Ref2VA（reference）。"
    SWAP_LORA_REPO = "akatz-ai/MiniMax-H3-Character-Swap-LoRA"
    SWAP_LORA = "h3_character_swap_v1.5.safetensors"
    model_files.append((SWAP_LORA_REPO, SWAP_LORA, "loras"))
# 鎖定模型版本（HF commit）：避免上游用同檔名覆蓋成不同權重。PIN_UPSTREAM=False 時抓最新版。
HF_REVISIONS = {
    "Comfy-Org/MiniMax-H3": "e5eb578a89295337b8ff433a035929ce0279e0b6",
    "drbaph/MiniMax-H3-Turbo-Lora-ComfyUI": "bb2bc497cbaca89dadd0bcf1856eed4f8275be20",
    "akatz-ai/MiniMax-H3-Character-Swap-LoRA": "96ea3407b230b6f7df71c58c70e31df96bd7e533",
    "Momoking/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4": "0a9486d17cfb20c1a7abc97118c4d95910b9b1f4",
}
# Google Drive 備援：runner 掛載 Drive 後設定 H3_DRIVE_MODELS，HF 下載失敗時改從 <備份目錄>/<repo>/<檔案路徑> 複製
DRIVE_MODELS = os.environ.get("H3_DRIVE_MODELS", "").strip()
for repo, remote_name, folder in model_files:
    target = COMFY / "models" / folder / Path(remote_name).name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or target.stat().st_size == 0:
        local_dir = COMFY / "models" if repo == BASE_REPO else COMFY / "models" / folder
        try:
            downloaded = Path(hf_hub_download(repo_id=repo, filename=remote_name, local_dir=local_dir,
                                             revision=HF_REVISIONS.get(repo) if PIN_UPSTREAM else None))
        except Exception as exc:
            backup = Path(DRIVE_MODELS) / repo / remote_name if DRIVE_MODELS else None
            if not (backup and backup.is_file()):
                raise
            print(f"HF 下載失敗（{type(exc).__name__}），改用 Google Drive 備份：{backup}", flush=True)
            shutil.copyfile(backup, target)
            downloaded = target
        assert downloaded == target, f"下載路徑不符：{downloaded} != {target}"
    print(folder, target.name, f"{target.stat().st_size / 2**30:.2f} GiB")

h3_stage("download", "prepare")


# ---- cell 7
import math

# 只改這個 cell 的設定，再從這裡往下執行。
# Studio 版：H3_RESOLUTION=draft（672×384 草稿，預設）或 full（1376×768）；H3_ASPECT=portrait 時寬高互換
WIDTH, HEIGHT = (1376, 768) if os.environ.get("H3_RESOLUTION", "draft") == "full" else (672, 384)
if os.environ.get("H3_ASPECT") == "portrait":
    WIDTH, HEIGHT = HEIGHT, WIDTH
DURATION_SECONDS = float(os.environ.get("H3_DURATION_SECONDS", "12.0"))
STEPS = 4 if INFERENCE_MODE == "reference" else 8
# 少步數草稿（2026-11-13 實測）：H3_FAST_STEPS=2 時 Turbo 改 2 步、Flex 改 sigmas 1.0→0.8→0.0
FAST_STEPS = int(os.environ.get("H3_FAST_STEPS", "0") or 0)
if FAST_STEPS:
    STEPS = FAST_STEPS
FLEX_SIGMAS = "1.0, 0.8, 0.0" if FAST_STEPS == 2 else "1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0"
SEED = int(os.environ.get("H3_SEED", "768914106098754"))
LORA_STRENGTH = 1.0
SAMPLER_NAME = "euler"
SCHEDULER_NAME = "beta"
DENOISE = 1.0
VIDEO_CRF = 20
OUTPUT_PREFIX = os.environ.get("H3_OUTPUT_PREFIX", "MiniMax_H3_Colab")
REFERENCE_IMAGE_SIZE = "match"  # "match" 較快；"max" 可保留較多身份細節但較慢。
FIRST_FRAME_MEGAPIXELS = 1.0
FIRST_FRAME_RESOLUTION_STEPS = 32
FIRST_FRAME_UPSCALE_METHOD = "nearest-exact"
LOW_VRAM_MODE = "auto"  # "auto"、"on" 或 "off"

# 一個清單項目 = 同一支影片內的一個 shot。起點以秒為單位，從影片開頭算起。
SHOTS = [
    {
        "start_seconds": 0.0,
        "description": (
            "Photorealistic wildlife documentary. The chameleon in <Picture 1> "
            "remains on the same wet moss-covered branch, preserving its shape, "
            "large turreted eye, textured scales and rainforest background. "
            "A medium macro shot follows it as it starts walking forward slowly, "
            "placing one foot at a time while water droplets tremble on its skin."
        ),
    },
    {
        "start_seconds": 4.0,
        "description": (
            "a close-up of the same chameleon's face. "
            "Its eye rotates independently while its skin gradually shifts from "
            "green to turquoise and yellow. The camera pushes in with small "
            "amplitude at slow speed; the wet scales remain sharply detailed."
        ),
    },
    {
        "start_seconds": 8.0,
        "description": (
            "a wider tracking view of the same branch. "
            "The chameleon continues forward without changing identity or "
            "location, with orange and red accents passing smoothly across its "
            "scales before returning to multicoloured green. It ends still "
            "walking through soft rainforest daylight."
        ),
    },
]
OVERALL_SOUNDSCAPE = (
    "Quiet rainforest ambience with faint birds, soft insects, dripping water "
    "and leaf rustling. Subtle wet contact sounds follow the chameleon's feet "
    "as they grip and release the mossy branch."
)
NON_DIEGETIC_MUSIC = "N/A"
PROMPT_OVERRIDE = ""  # 填入完整 prompt 才會覆蓋 shot 組裝；CLI 會改讀 --prompt 檔案。

assert WIDTH > 0 and HEIGHT > 0 and WIDTH % 32 == 0 and HEIGHT % 32 == 0, "寬高必須為正整數且是 32 的倍數。"
assert isinstance(DURATION_SECONDS, (int, float)) and math.isfinite(DURATION_SECONDS) and 4 <= DURATION_SECONDS <= 15, "請將影片長度設為 4–15 秒；5–15 秒較穩定。"
assert isinstance(STEPS, int) and STEPS > 0, "STEPS 必須是正整數。"
assert isinstance(SEED, int) and 0 <= SEED < 2**64, "SEED 必須是 0 到 2**64-1 的整數。"
assert math.isfinite(LORA_STRENGTH) and 0 <= LORA_STRENGTH <= 2, "LoRA 強度請設為 0–2。"
assert 0 < DENOISE <= 1, "DENOISE 請設為 0–1 之間（不含 0）。"
assert isinstance(VIDEO_CRF, int) and 0 <= VIDEO_CRF <= 51, "VIDEO_CRF 請設為 0–51 的整數。"
assert isinstance(OUTPUT_PREFIX, str) and OUTPUT_PREFIX.strip(), "請設定輸出檔名前綴。"
assert REFERENCE_IMAGE_SIZE in {"match", "max"}, "REFERENCE_IMAGE_SIZE 請使用 match 或 max。"
assert math.isfinite(FIRST_FRAME_MEGAPIXELS) and 0.01 <= FIRST_FRAME_MEGAPIXELS <= 16, "首幀縮放像素數請設為 0.01–16 MP。"
assert isinstance(FIRST_FRAME_RESOLUTION_STEPS, int) and FIRST_FRAME_RESOLUTION_STEPS > 0, "首幀尺寸倍數必須是正整數。"
assert LOW_VRAM_MODE in {"auto", "on", "off"}, "LOW_VRAM_MODE 請使用 auto、on 或 off。"

requested_frames = max(5, round(DURATION_SECONDS * 24))
FRAMES = requested_frames + (5 - requested_frames % 17) % 17
ACTUAL_SECONDS = FRAMES / 24
print(f"模式：{INFERENCE_MODE}；要求長度：{DURATION_SECONDS:.3f} 秒；排程：{FRAMES} 幀 / {ACTUAL_SECONDS:.3f} 秒（24 fps）")
if FRAMES < 124:
    print("提醒：此設定低於 ComfyUI H3 節點標示的約 124 幀已訓練下限，畫面/音訊可能不穩定。")
if ACTUAL_SECONDS > 15:
    print("提醒：對齊後稍長於 15 秒；若需嚴格不超過 15 秒，請設 14.375 秒或輸出後裁切。")


# ---- cell 9
def shot_timestamp(seconds):
    milliseconds = round(seconds * 1000)
    minutes, remainder = divmod(milliseconds, 60_000)
    secs, millis = divmod(remainder, 1_000)
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"

assert isinstance(PROMPT_OVERRIDE, str), "PROMPT_OVERRIDE 必須是字串。"
prompt_file_env = os.environ.get("H3_PROMPT_FILE")
if prompt_file_env:
    prompt_path = Path(prompt_file_env)
    assert prompt_path.is_file(), f"Colab CLI 上傳的 prompt 檔不存在：{prompt_path}"
    PROMPT = prompt_path.read_text(encoding="utf-8")
    assert PROMPT.strip(), f"prompt 檔是空的：{prompt_path}"
    print("使用 CLI 上傳的完整 prompt：", prompt_path)
elif PROMPT_OVERRIDE.strip():
    PROMPT = PROMPT_OVERRIDE.strip()
    print("使用完整自訂 prompt；SHOTS、環境聲與配樂設定不參與組裝。")
elif INFERENCE_MODE == "reference":
    raise ValueError("Ref2VA 需要完整參照格式 prompt；請設定 PROMPT_OVERRIDE 或使用 CLI --prompt 檔案。")
else:
    assert isinstance(SHOTS, list) and SHOTS, "SHOTS 至少需要一個鏡頭。"
    starts = []
    cut_milliseconds = []
    parts = []
    for number, shot in enumerate(SHOTS, start=1):
        assert isinstance(shot, dict), f"Shot {number} 必須是 dict。"
        start = shot.get("start_seconds")
        description = shot.get("description")
        assert isinstance(start, (int, float)) and math.isfinite(start), f"Shot {number} 的開始時間必須是數字。"
        assert isinstance(description, str) and description.strip(), f"Shot {number} 的 description 不能空白。"
        assert 0 <= start < DURATION_SECONDS, f"Shot {number} 的開始時間必須介於 0 與要求秒數之間。"
        assert not starts or start > starts[-1], "各 shot 的開始時間必須嚴格遞增。"
        stamp_ms = round(start * 1000)
        assert not cut_milliseconds or stamp_ms > cut_milliseconds[-1], "切鏡時間以毫秒顯示，請至少間隔 0.001 秒。"
        starts.append(start)
        cut_milliseconds.append(stamp_ms)
        description = description.strip()
        if number == 1:
            assert start == 0, "Shot 1 必須從 0 秒開始。"
            parts.append(f"[Shot 1] {description}")
        else:
            cut_words = ("the camera cuts to", "the shot cuts to", "the shot transitions to",
                         "the shot changes to", "the shot switches to")
            transition = description if description.lower().startswith(cut_words) else "the camera cuts to " + description
            parts.append(f"[Shot {number}] At {shot_timestamp(start)}, {transition}")

    assert isinstance(OVERALL_SOUNDSCAPE, str) and OVERALL_SOUNDSCAPE.strip(), "請填寫 OVERALL_SOUNDSCAPE。"
    assert isinstance(NON_DIEGETIC_MUSIC, str) and NON_DIEGETIC_MUSIC.strip(), "無配樂時請填 N/A。"
    PROMPT = (
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
        "integrated_multimodal_description: " + "\n".join(parts) + "\n\n"
        "overall_soundscape: " + OVERALL_SOUNDSCAPE.strip() + "\n\n"
        "non_diegetic_music: " + NON_DIEGETIC_MUSIC.strip()
    )
    print(f"已建立 {len(SHOTS)} 個 shot；要求的分鏡時間（切鏡由模型生成，非硬剪輯）：")
    for number, start in enumerate(starts, start=1):
        end = starts[number] if number < len(starts) else DURATION_SECONDS
        print(f"  Shot {number}: {start:.3f}–{end:.3f} 秒（約 {end - start:.3f} 秒）")

print("\n模型收到的完整 prompt：\n")
print(PROMPT)


# ---- cell 11
import json
from io import BytesIO
from PIL import Image

CLI_MODE = False
REFERENCE_IMAGE_NAMES = []
REFERENCE_IMAGE_PATHS = []

if INFERENCE_MODE == "reference":
    configured_references = os.environ.get("H3_REFERENCE_IMAGES")
    if configured_references:
        source_paths = json.loads(configured_references)
        assert isinstance(source_paths, list) and 1 <= len(source_paths) <= 9, "Ref2VA 請提供 1–9 張參照圖。"
        source_images = []
        for source_path in source_paths:
            path = Path(source_path)
            assert path.is_file(), f"參照圖片不存在：{path}"
            source_images.append((path.name, path))
        CLI_MODE = True
    else:
        from google.colab import files
        uploaded = files.upload()
        assert 1 <= len(uploaded) <= 9, "Ref2VA 請上傳 1–9 張參照圖片。"
        source_images = [(name, BytesIO(image_bytes)) for name, image_bytes in uploaded.items()]

    input_dir = COMFY / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    for number, (source_name, image_source) in enumerate(source_images, start=1):
        with Image.open(image_source) as opened:
            image = opened.convert("RGB")
        image_path = input_dir / f"h3_reference_{number:02d}.png"
        image.save(image_path)
        REFERENCE_IMAGE_NAMES.append(image_path.name)
        REFERENCE_IMAGE_PATHS.append(image_path)
        print(f"<Picture {number}>：{source_name} → {image_path} ({image.size[0]}×{image.size[1]})")
else:
    configured_image = os.environ.get("H3_INPUT_IMAGE")
    T2VA = os.environ.get("H3_T2VA") == "1"  # 不接首幀：純文字生影片
    source_path = Path(configured_image or "/content/h3_first_frame.png")
    CLI_MODE = T2VA or source_path.is_file()
    assert not configured_image or source_path.is_file(), f"Colab CLI 上傳的首幀不存在：{source_path}"
    if T2VA:
        print("t2va：不使用首幀")
    elif CLI_MODE:
        with Image.open(source_path) as opened:
            image = opened.convert("RGB")
        print("使用 CLI 上傳的首幀：", source_path)
    else:
        from google.colab import files
        uploaded = files.upload()
        assert len(uploaded) == 1, "FL2VA 請只上傳一張首幀圖片。"
        name, image_bytes = next(iter(uploaded.items()))
        with Image.open(BytesIO(image_bytes)) as opened:
            image = opened.convert("RGB")
        print("使用網頁上傳的首幀：", name)

    # 首幀比例與輸出不同時（H3_FIRST_FRAME_FIT）：crop＝置中裁切填滿（預設）；blur＝原圖置中、模糊放大版當背景；pad＝黑邊
    FIRST_FRAME_FIT = os.environ.get("H3_FIRST_FRAME_FIT", "crop").strip().lower()
    assert FIRST_FRAME_FIT in {"crop", "blur", "pad"}, "H3_FIRST_FRAME_FIT 請使用 crop、blur 或 pad。"
    if not T2VA and abs(image.width / image.height - WIDTH / HEIGHT) > 0.01:
        from PIL import ImageFilter, ImageOps
        if FIRST_FRAME_FIT == "crop":
            image = ImageOps.fit(image, (WIDTH, HEIGHT), Image.LANCZOS)
        else:
            if FIRST_FRAME_FIT == "blur":
                canvas = ImageOps.fit(image, (WIDTH, HEIGHT), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
            else:
                canvas = Image.new("RGB", (WIDTH, HEIGHT))
            inner = ImageOps.contain(image, (WIDTH, HEIGHT), Image.LANCZOS)
            canvas.paste(inner, ((WIDTH - inner.width) // 2, (HEIGHT - inner.height) // 2))
            image = canvas
        print(f"首幀比例與輸出不同，已用 {FIRST_FRAME_FIT} 調整為 {WIDTH}×{HEIGHT}")
    input_path = COMFY / "input" / "h3_colab_first_frame.png"
    if not T2VA:
        input_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(input_path)
        print("ComfyUI 首幀：", input_path, image.size)

# 音色參考 (Audio References for Voice Timbre Cloning)
REFERENCE_VIDEO_NAMES = []
for video_num, v_path_str in enumerate(json.loads(os.environ.get("H3_REFERENCE_VIDEOS") or "[]"), start=1):
    v_path = Path(v_path_str)
    assert v_path.is_file(), f"參照影片不存在：{v_path}"
    dest_video = COMFY / "input" / f"h3_video_{video_num:02d}{v_path.suffix}"
    dest_video.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(v_path, dest_video)
    REFERENCE_VIDEO_NAMES.append(dest_video.name)
    print(f"<Video {video_num}>：{v_path.name} -> {dest_video.name}")
assert len(REFERENCE_VIDEO_NAMES) <= 3, "Ref2VA 最多 3 支參照影片。"

REFERENCE_AUDIO_NAMES = []
configured_audios = os.environ.get("H3_REFERENCE_AUDIOS")
if configured_audios:
    try:
        source_audio_paths = json.loads(configured_audios)
        for audio_num, a_path_str in enumerate(source_audio_paths, start=1):
            a_path = Path(a_path_str)
            if a_path.is_file():
                dest_audio = input_dir / f"h3_audio_{audio_num:02d}{a_path.suffix}"
                shutil.copy2(a_path, dest_audio)
                REFERENCE_AUDIO_NAMES.append(dest_audio.name)
                print(f"<Audio {audio_num}>：{a_path.name} -> {dest_audio.name}")
    except Exception as exc:
        print(f"音訊載入通知：{exc}")


# ---- cell 13
h3_stage("prepare", "comfyui_start")
import json, time, requests

PORT = 8188
BASE_URL = f"http://127.0.0.1:{PORT}"
LOG_PATH = Path("/content/comfyui_h3.log")
try:
    response = requests.get(BASE_URL + "/system_stats", timeout=2)
    response.raise_for_status()
    print("使用已啟動的 ComfyUI")
except requests.RequestException:
    LOG_FILE = open(LOG_PATH, "a")
    launch = [sys.executable, str(COMFY / "main.py"), "--listen", "127.0.0.1", "--port", str(PORT), "--disable-auto-launch", "--disable-mmap", "--disable-pinned-memory"]
    if LOW_VRAM_MODE == "on" or (LOW_VRAM_MODE == "auto" and torch.cuda.get_device_properties(0).total_memory < 48 * 2**30):
        launch.append("--lowvram")
    COMFY_PROCESS = subprocess.Popen(launch, cwd=COMFY, stdout=LOG_FILE, stderr=subprocess.STDOUT)
    for _ in range(180):
        if COMFY_PROCESS.poll() is not None:
            raise RuntimeError(f"ComfyUI 啟動失敗；查看 {LOG_PATH}\n" + LOG_PATH.read_text()[-5000:])
        try:
            requests.get(BASE_URL + "/system_stats", timeout=2).raise_for_status()
            break
        except requests.RequestException:
            time.sleep(2)
    else:
        raise TimeoutError(f"ComfyUI 啟動逾時；查看 {LOG_PATH}")

object_info = requests.get(BASE_URL + "/object_info", timeout=30).json()
required_nodes = {"UNETLoader", "CLIPLoader", "VAELoader", "LoraLoaderModelOnly",
                  "LoadImage", "BasicGuider", "RandomNoise", "KSamplerSelect",
                  "BasicScheduler", "SamplerCustomAdvanced", "VAEDecode", "VAEDecodeAudio",
                  "VHS_VideoCombine"}
if INFERENCE_MODE == "reference":
    required_nodes.add("MiniMaxH3ReferenceToVideo")
    if REFERENCE_VIDEO_NAMES:
        required_nodes.add("VHS_LoadVideo")
else:
    required_nodes.update({"ImageScaleToTotalPixels", "MiniMaxH3ImageToVideo"})
missing = required_nodes - object_info.keys()
assert not missing, f"ComfyUI 缺少節點：{sorted(missing)}。請查看 {LOG_PATH}，並確認 ComfyUI / VideoHelperSuite 安裝成功。"
print("節點檢查通過，ComfyUI 已啟動")

h3_stage("comfyui_start", "submit")


# ---- cell 14
import re

graph = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": DIFFUSION, "weight_dtype": "default"}},
    "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": LORA, "strength_model": LORA_STRENGTH}},
    "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax", "device": "default"}},
    "4": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
    "5": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
}

if INFERENCE_MODE == "reference":
    picture_inputs = {
        "clip": ["3", 0], "vae": ["4", 0], "audio_vae": ["5", 0],
        "prompt": PROMPT, "width": WIDTH, "height": HEIGHT, "length": FRAMES,
        "ref_image_size": REFERENCE_IMAGE_SIZE,
    }
    for index, image_name in enumerate(REFERENCE_IMAGE_NAMES):
        node_id = str(100 + index)
        graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
        picture_inputs[f"ref_images.ref_image_{index}"] = [node_id, 0]

    # 連接音色參考節點 (Connect Voice Timbre Reference nodes)
    for a_idx, a_name in enumerate(REFERENCE_AUDIO_NAMES):
        a_node_id = str(200 + a_idx)
        graph[a_node_id] = {"class_type": "LoadAudio", "inputs": {"audio": a_name}}
        picture_inputs[f"ref_audios.ref_audio_{a_idx}"] = [a_node_id, 0]
    # 參照影片與原聲：<Video k> 對應 ref_video_{k-1}，原聲接同編號 ref_video_audio
    # 換人＋給了 <Audio>（換聲）時不送原片音軌：原片音軌一送進去，模型就照原聲重生成，<Audio> 音色完全無效（2026-11-02 實測）。
    # H3_VIDEO_AUDIO=1／0 可強制開／關
    USE_VIDEO_AUDIO = os.environ.get("H3_VIDEO_AUDIO", "0" if (CHARACTER_SWAP and REFERENCE_AUDIO_NAMES) else "1") == "1"
    if not USE_VIDEO_AUDIO and REFERENCE_VIDEO_NAMES:
        print("不送原片音軌（換聲：改用 <Audio> 音色）")
    for v_idx, v_name in enumerate(REFERENCE_VIDEO_NAMES):
        v_node_id = str(250 + v_idx)
        graph[v_node_id] = {"class_type": "VHS_LoadVideo", "inputs": {
            "video": v_name, "force_rate": 24, "custom_width": 0, "custom_height": 0,
            "frame_load_cap": min(FRAMES, 360), "skip_first_frames": 0, "select_every_nth": 1}}
        picture_inputs[f"ref_videos.ref_video_{v_idx}"] = [v_node_id, 0]
        if USE_VIDEO_AUDIO:
            picture_inputs[f"ref_video_audios.ref_video_audio_{v_idx}"] = [v_node_id, 2]
    video_count = len(REFERENCE_VIDEO_NAMES)
    invalid_videos = sorted({int(m.group(1)) for m in re.finditer(r"<Video\s+(\d+)>", PROMPT)
                             if not 1 <= int(m.group(1)) <= video_count})
    if invalid_videos:
        raise ValueError(f"prompt 使用了不存在的影片標籤：{invalid_videos}；目前有 {video_count} 支。")
    picture_count = len(REFERENCE_IMAGE_NAMES)
    referenced_pictures = [int(match.group(1)) for match in re.finditer(r"<Picture\s+(\d+)>", PROMPT)]
    invalid_pictures = sorted({number for number in referenced_pictures if number < 1 or number > picture_count})
    if invalid_pictures:
        raise ValueError(f"prompt 使用了不存在的圖片標籤：{invalid_pictures}；目前提供 {picture_count} 張，標籤為 <Picture 1>–<Picture {picture_count}>。")
    graph["7"] = {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": picture_inputs}
else:
    if T2VA:
        graph["7"] = {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["3", 0], "vae": ["4", 0],
            "prompt": PROMPT, "width": WIDTH, "height": HEIGHT, "length": FRAMES}}
    else:
        graph.update({
            "6": {"class_type": "LoadImage", "inputs": {"image": input_path.name}},
            "16": {"class_type": "ImageScaleToTotalPixels", "inputs": {
                "image": ["6", 0], "upscale_method": FIRST_FRAME_UPSCALE_METHOD,
                "megapixels": FIRST_FRAME_MEGAPIXELS, "resolution_steps": FIRST_FRAME_RESOLUTION_STEPS}},
            "7": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
                "clip": ["3", 0], "vae": ["4", 0], "first_frame": ["16", 0],
                "prompt": PROMPT, "width": WIDTH, "height": HEIGHT, "length": FRAMES}},
        })
        # 尾幀（官方 FL2VA）：H3_LAST_FRAME＝圖檔路徑，接到 MiniMaxH3ImageToVideo 的 last_frame
        if os.environ.get("H3_LAST_FRAME"):
            last_src = Path(os.environ["H3_LAST_FRAME"])
            assert last_src.is_file(), f"尾幀不存在：{last_src}"
            shutil.copy2(last_src, COMFY / "input" / "h3_last_frame.png")
            graph["6l"] = {"class_type": "LoadImage", "inputs": {"image": "h3_last_frame.png"}}
            graph["7"]["inputs"]["last_frame"] = ["6l", 0]
            print("ComfyUI 尾幀：", last_src)

# 時間軸錨點（Add Guide for MiniMax H3）：H3_GUIDES = [{"image": 路徑?, "audio": 路徑?, "frame": 幀}]
# 兩種模式都可用：例如 Ref2VA 以圖錨定第 0 幀當首幀，或把一段音訊固定在某幀開始。
CONDITIONING = ["7", 0]
MODEL = ["2", 0]
if SWAP_LORA:
    graph["6b"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": MODEL, "lora_name": SWAP_LORA, "strength_model": 1.0}}
    MODEL = ["6b", 0]
for guide_index, guide in enumerate(json.loads(os.environ.get("H3_GUIDES") or "[]")):
    base_id = 300 + guide_index * 3
    guide_inputs = {"positive": CONDITIONING, "latent": ["7", 1], "frame_idx": int(guide.get("frame", 0))}
    for kind, offset, loader, vae_key, vae_node in (("image", 0, "LoadImage", "vae", "4"),
                                                   ("audio", 1, "LoadAudio", "audio_vae", "5")):
        if guide.get(kind):
            source = Path(guide[kind])
            assert source.is_file(), f"錨點檔案不存在：{source}"
            target = COMFY / "input" / f"h3_guide_{guide_index:02d}_{kind}{source.suffix}"
            shutil.copy2(source, target)
            graph[str(base_id + offset)] = {"class_type": loader, "inputs": {kind: target.name}}
            guide_inputs[kind] = [str(base_id + offset), 0]
            guide_inputs[vae_key] = [vae_node, 0]
    graph[str(base_id + 2)] = {"class_type": "MiniMaxH3AddGuide", "inputs": guide_inputs}
    CONDITIONING = [str(base_id + 2), 0]
    print(f"錨點 {guide_index + 1}：第 {guide_inputs['frame_idx']} 幀", {k: guide[k] for k in ("image", "audio") if guide.get(k)})

# 稀疏注意力（2026-11-12 A/B：1376×768 首幀生影片快 37–40%、畫面無瑕疵；草稿解析度不會啟動）。H3_SPARSE=1 開啟，預設關
if os.environ.get("H3_SPARSE", "0") == "1":
    graph["sp1"] = {"class_type": "ModelAttentionBackend", "inputs": {"model": MODEL, "attention": "comfy kitchen attention"}}
    graph["sp2"] = {"class_type": "BlockSparseAttention", "inputs": {"model": ["sp1", 0], "selection": "sol-attn", "selection.tau": 1.3,
        "start_percent": 0.2, "end_percent": 1.0, "dense_blocks": "", "min_tokens": 12288, "extra_tokens": 256,
        "sink_conditioning": "exact_kv_and_rows", "verbose": False}}
    MODEL = ["sp2", 0]
    print("稀疏注意力：comfy kitchen attention＋sol-attn")
graph.update({
    "8": {"class_type": "BasicGuider", "inputs": {"model": MODEL, "conditioning": CONDITIONING}},
    "9": {"class_type": "RandomNoise", "inputs": {"noise_seed": SEED}},
    "10": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "lcm" if FLEX else SAMPLER_NAME}},
    "11": ({"class_type": "ManualSigmas", "inputs": {"sigmas": FLEX_SIGMAS}} if FLEX else
           {"class_type": "BasicScheduler", "inputs": {"model": MODEL, "scheduler": SCHEDULER_NAME, "steps": STEPS, "denoise": DENOISE}}),
    "12": {"class_type": "SamplerCustomAdvanced", "inputs": {
        "noise": ["9", 0], "guider": ["8", 0], "sampler": ["10", 0],
        "sigmas": ["11", 0], "latent_image": ["7", 1]}},
    "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["4", 0]}},
    "14": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["12", 0], "vae": ["5", 0]}},
    "15": {"class_type": "VHS_VideoCombine", "inputs": {
        "images": ["13", 0], "audio": ["14", 0], "frame_rate": 24,
        "loop_count": 0, "filename_prefix": OUTPUT_PREFIX,
        "format": "video/h264-mp4", "pix_fmt": "yuv420p", "crf": VIDEO_CRF,
        "save_metadata": True, "trim_to_audio": False,
        "pingpong": False, "save_output": True}},
})

for node in graph.values():
    spec = object_info[node["class_type"]]["input"]
    known = set(spec.get("required", {})) | set(spec.get("optional", {}))
    if node["class_type"] == "VHS_VideoCombine":
        format_info = spec["required"]["format"][1]["formats"]
        format_name = node["inputs"]["format"]
        if format_name not in format_info:
            raise ValueError(f"VideoHelperSuite 不支援輸出格式：{format_name}")
        known.update(widget[0] for widget in format_info[format_name])
    dynamic_reference_inputs = {
        key for key in node["inputs"]
        if node["class_type"] == "MiniMaxH3ReferenceToVideo"
        and (re.fullmatch(r"ref_images\.ref_image_\d+", key) or re.fullmatch(r"ref_audios\.ref_audio_\d+", key)
            or re.fullmatch(r"ref_videos\.ref_video_\d+", key)
            or re.fullmatch(r"ref_video_audios\.ref_video_audio_\d+", key))
    }
    unexpected = {k for k in set(node["inputs"]) - known - dynamic_reference_inputs if k.split(".")[0] not in known}
    if unexpected:
        raise ValueError(f"{node['class_type']} 的參數已變更：{sorted(unexpected)}；請更新 notebook。")
result = requests.post(BASE_URL + "/prompt", json={"prompt": graph, "client_id": "h3-colab"}, timeout=60)
if not result.ok:
    raise RuntimeError(f"提交失敗 HTTP {result.status_code}: {result.text}")
job = result.json()
if job.get("node_errors"):
    raise RuntimeError("節點驗證失敗：" + json.dumps(job["node_errors"], ensure_ascii=False, indent=2))
prompt_id = job["prompt_id"]
print("已提交推論：", prompt_id)

h3_stage("submit", None)      # 之後是推論等待：有自己的每 60 秒進度輸出，不加心跳


# ---- cell 16
job_timeout_seconds = float(os.environ.get("H3_JOB_TIMEOUT_SECONDS", "7200"))
assert math.isfinite(job_timeout_seconds) and job_timeout_seconds > 0, "H3_JOB_TIMEOUT_SECONDS 必須是正數。"
deadline = time.monotonic() + job_timeout_seconds
last_report = 0
while time.monotonic() < deadline:
    if 'COMFY_PROCESS' in globals() and COMFY_PROCESS.poll() is not None:
        raise RuntimeError(f"ComfyUI 已退出；查看 {LOG_PATH}\n" + LOG_PATH.read_text()[-5000:])
    history = requests.get(BASE_URL + f"/history/{prompt_id}", timeout=30).json()
    if prompt_id in history:
        run = history[prompt_id]
        if run.get("status", {}).get("status_str") == "error":
            raise RuntimeError("推論失敗：" + json.dumps(run.get("status", {}), ensure_ascii=False, indent=2) + f"\n日誌：{LOG_PATH}")
        outputs = run.get("outputs", {})
        if "15" in outputs:
            break
        if run.get("status", {}).get("status_str") == "success":
            raise RuntimeError("任務已完成但沒有 MP4 輸出：" + json.dumps(outputs, ensure_ascii=False))
    if time.monotonic() - last_report >= 60:
        print("仍在生成影片…")
        last_report = time.monotonic()
    time.sleep(10)
else:
    raise TimeoutError(f"等待推論超過兩小時；可查詢 /history/{prompt_id}，日誌：{LOG_PATH}")

h3_stage("inference", None)   # 含第一鏡載入模型到 GPU 的時間
filenames = outputs["15"].get("gifs", [])
if not filenames:
    raise RuntimeError("VideoHelperSuite 未回傳 MP4 輸出；請查看 " + str(LOG_PATH))
video_info = next((item for item in filenames if item["filename"].endswith(".mp4")), None)
if video_info is None:
    raise RuntimeError("找不到 MP4；輸出：" + str(filenames))
video_path = COMFY / "output" / video_info.get("subfolder", "") / video_info["filename"]
assert video_path.is_file() and video_path.stat().st_size > 0, f"輸出檔不存在：{video_path}"
probe = subprocess.run(
    ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
     "-of", "json", str(video_path)], capture_output=True, text=True, check=True)
streams = {item["codec_type"] for item in json.loads(probe.stdout).get("streams", [])}
assert {"video", "audio"} <= streams, f"MP4 缺少影片或音訊串流：{streams}"
print("完成：", video_path, f"({video_path.stat().st_size / 2**20:.1f} MiB，含影片與音訊)")

if CLI_MODE:
    CLI_OUTPUT_PATH = Path(os.environ.get("H3_OUTPUT_PATH", "/content/minimax_h3_output.mp4"))
    CLI_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video_path, CLI_OUTPUT_PATH)
    print("COLAB_CLI_OUTPUT_PATH:", CLI_OUTPUT_PATH)
else:
    from IPython.display import Video, display
    from google.colab import files

    display(Video(str(video_path), embed=True))
    files.download(str(video_path))

h3_stage("save", None)

