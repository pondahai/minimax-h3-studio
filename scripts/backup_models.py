#!/usr/bin/env python3
"""Back up the pinned MiniMax H3 model files to Google Drive, as a fallback if a Hugging Face source disappears.

Runs on a CPU-only Colab VM (no GPU charge): downloads each pinned file from Hugging Face straight into
<Drive>/minimax-h3-models/<repo>/<path>, skipping files already there with the right size. The first run
asks you to authorize Google Drive in the browser and press Enter, so run it from a terminal.

    python scripts/backup_models.py                # Ref2VA + character swap (~39 GiB)
    python scripts/backup_models.py --with-fl2va   # also the FL2VA first-frame models (~+45 GiB)
    python scripts/backup_models.py --with-heretic # also the Heretic (uncensored) text encoder (~+15 GiB)
    python scripts/backup_models.py --dry-run      # list the files only

Then start Studio with H3_DRIVE_FALLBACK=1 to let generation fall back to these copies.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402

# 與 assets/MiniMax_H3_Turbo_Colab.ipynb 的 HF_REVISIONS 保持一致
BASE = ("Comfy-Org/MiniMax-H3", "e5eb578a89295337b8ff433a035929ce0279e0b6")
FL2VA_LORA = ("drbaph/MiniMax-H3-Turbo-Lora-ComfyUI", "bb2bc497cbaca89dadd0bcf1856eed4f8275be20")
SWAP_LORA = ("akatz-ai/MiniMax-H3-Character-Swap-LoRA", "96ea3407b230b6f7df71c58c70e31df96bd7e533")
HERETIC = ("Momoking/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4", "0a9486d17cfb20c1a7abc97118c4d95910b9b1f4")

REF2VA_FILES = [
    (*BASE, "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors"),
    (*BASE, "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"),
    (*BASE, "vae/minimax_h3_video_vae_int8_convrot.safetensors"),
    (*BASE, "vae/minimax_h3_audio_vae_fp32.safetensors"),
    (*BASE, "loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"),
    (*SWAP_LORA, "h3_character_swap_v1.5.safetensors"),
]
FL2VA_FILES = [
    (*BASE, "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors"),
    (*BASE, "diffusion_models/minimax_h3_fl2va_pruned_fp8_scaled.safetensors"),
    (*BASE, "vae/minimax_h3_video_vae_fp16.safetensors"),
    (*FL2VA_LORA, "minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors"),
]
HERETIC_FILES = [(*HERETIC, "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors")]

REMOTE_SCRIPT = r'''
import json, os, shutil, subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub", "hf_xet"], check=True)
from huggingface_hub import HfApi, hf_hub_download
from pathlib import Path
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
ROOT = Path(__ROOT__)
files = json.loads(__FILES__)
api = HfApi()
for repo, revision, path in files:
    target = ROOT / repo / path
    info = api.get_paths_info(repo, [path], revision=revision)[0]
    if target.is_file() and target.stat().st_size == info.size:
        print(f"已存在，略過：{repo}/{path}", flush=True)
        continue
    print(f"下載中：{repo}/{path}（{info.size / 2**30:.2f} GiB）", flush=True)
    cached = hf_hub_download(repo, path, revision=revision, local_dir="/content/h3_backup_tmp")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached, target)
    os.remove(cached)
    print(f"已備份：{target}", flush=True)
print("BACKUP_DONE", flush=True)
'''


def colab(*args: str) -> None:
    # 直接接上終端機：drivemount 第一次需要你在瀏覽器授權後按 Enter
    subprocess.run([runner._colab_path(), f"--auth={runner.AUTH}", *args], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--with-fl2va", action="store_true", help="also back up the FL2VA first-frame models")
    parser.add_argument("--with-heretic", action="store_true", help="also back up the Heretic text encoder")
    parser.add_argument("--dry-run", action="store_true", help="only list the files")
    args = parser.parse_args()

    files = REF2VA_FILES + (FL2VA_FILES if args.with_fl2va else []) + (HERETIC_FILES if args.with_heretic else [])
    print(f"備份目的地：{runner.DRIVE_MODELS_DIR}")
    for repo, revision, path in files:
        print(f"  {repo}@{revision[:10]}  {path}")
    if args.dry_run:
        return 0

    session = f"h3-backup-{time.strftime('%Y%m%d-%H%M%S')}"
    script = (REMOTE_SCRIPT.replace("__ROOT__", repr(runner.DRIVE_MODELS_DIR))
              .replace("__FILES__", repr(json.dumps(files))))
    with tempfile.TemporaryDirectory() as tmp:
        script_path = Path(tmp) / "h3_backup.py"
        script_path.write_text(script, encoding="utf-8")
        colab("new", "--session", session)  # 不指定 GPU = CPU 執行階段
        try:
            colab("drivemount", "--session", session)
            colab("exec", "--session", session, "--timeout", "10800", "--file", str(script_path))
        finally:
            colab("stop", "--session", session)
    return 0


if __name__ == "__main__":
    sys.exit(main())
