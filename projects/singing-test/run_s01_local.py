"""Run S01 (10.65s) Singing Voice Lip-Sync Experiment on local DGX Spark using H3_GUIDES.

Uses:
  - First frame: projects/singing-test/frames/singer_frame_seed1.png (Qwen-Image 2.1)
  - Audio guide: Opencpop 2001.wav (0.50s - 11.15s = first 10.65s of opencpop_2001_60s.wav)
  - Mode: FL2VA + H3_GUIDES (audio anchored at frame 0), 672x384 draft on DGX Spark
"""
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import runner_spark

EXP_DIR = Path(__file__).resolve().parent
OUT_DIR = EXP_DIR / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
HOST = runner_spark.HOST
SSH_OPTS = runner_spark.SSH_OPTS


def ssh_run(cmd: str, timeout: int = 300) -> str:
    res = subprocess.run(
        ["ssh", *SSH_OPTS, HOST, cmd],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"SSH failed (exit {res.returncode}): {res.stderr or res.stdout}")
    return res.stdout.strip()


def main():
    full_res = "--full" in sys.argv
    tag = "S01_full" if full_res else "S01"
    frame_path = EXP_DIR / "frames" / "singer_frame_seed1.png"
    prompt_path = EXP_DIR / "prompt_s01.txt"
    if not frame_path.is_file():
        raise FileNotFoundError(f"Missing first frame: {frame_path}")
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Missing prompt: {prompt_path}")

    session = f"singing_{tag.lower()}_{int(time.time())}"
    transport = runner_spark.SPARK
    print(f"[*] Starting local DGX Spark session: {session} ({'1376x768 full + sol-attn' if full_res else '672x384 draft'})", flush=True)
    transport.start(session, gpu="Spark", high_mem=True)

    try:
        host_dir = transport._dir(session)
        # Slice S01 (0.00s - 10.65s) directly from Spark's opencpop_2001_60s.wav into session dir
        print("[*] Slicing S01 audio (0.00s - 10.65s) on Spark...", flush=True)
        host_seg01 = f"{host_dir}/seg_01.wav"
        ssh_run(
            f"ffmpeg -y -ss 0.0 -t 10.65 -i ~/h3-studio/singing_assets/opencpop_2001_60s.wav "
            f"-c:a pcm_s16le -ar 44100 -ac 1 {shlex.quote(host_seg01)} -loglevel error && "
            f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {shlex.quote(host_seg01)}"
        )

        remote_frame = f"{transport.remote_root}/singer_frame.png"
        remote_prompt = f"{transport.remote_root}/prompt_s01.txt"
        remote_audio = f"{transport.remote_root}/seg_01.wav"
        remote_mp4 = f"{transport.remote_root}/{tag}_h3_raw.mp4"

        transport.upload(session, frame_path, remote_frame, label="upload singer frame", timeout=120, on_line=print)
        transport.upload(session, prompt_path, remote_prompt, label="upload S01 prompt", timeout=120, on_line=print)

        guides = [{"audio": remote_audio, "frame": 0}]
        env_values = [
            "H3_INFERENCE_MODE=first_frame",
            f"H3_RESOLUTION={'full' if full_res else 'draft'}",
            f"H3_SPARSE={'1' if full_res else '0'}",
            "H3_DURATION_SECONDS=10.65",
            "H3_SEED=2026112101",
            f"H3_INPUT_IMAGE={remote_frame}",
            f"H3_PROMPT_FILE={remote_prompt}",
            f"H3_GUIDES={json.dumps(guides, separators=(',', ':'))}",
            f"H3_OUTPUT_PATH={remote_mp4}",
            f"H3_OUTPUT_PREFIX=singing_{tag.lower()}",
            "H3_JOB_TIMEOUT_SECONDS=3600",
        ]

        print(f"[*] Running MiniMax H3 FL2VA + H3_GUIDES ({tag}, 10.65s, {'1376x768 + sol-attn' if full_res else '672x384 draft'})...", flush=True)
        t0 = time.time()
        transport.execute(
            session, env_values, job_id=tag.lower(), work_dir=OUT_DIR,
            label=f"{tag} FL2VA H3_GUIDES singing", timeout=3600, on_line=print,
        )
        print(f"[*] {tag} H3 inference finished in {time.time() - t0:.1f}s", flush=True)

        # Mux original pristine singing audio onto the generated video + create 1fps contact sheet
        host_mp4_raw = f"{host_dir}/{tag}_h3_raw.mp4"
        host_mp4_orig = f"{host_dir}/{tag}_orig_audio.mp4"
        host_sheet = f"{host_dir}/{tag}_contact_sheet.png"
        print("[*] Muxing original audio version & generating contact sheet on Spark...", flush=True)
        info = ssh_run(
            f"ffmpeg -y -i {shlex.quote(host_mp4_raw)} -i {shlex.quote(host_seg01)} "
            f"-map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart {shlex.quote(host_mp4_orig)} -loglevel error && "
            f"ffmpeg -y -i {shlex.quote(host_mp4_raw)} -vf \"fps=1,scale=458:-1,tile=5x3\" -frames:v 1 {shlex.quote(host_sheet)} -loglevel error && "
            f"ffprobe -v error -show_entries format=duration -show_entries stream=codec_type,codec_name,width,height -of compact {shlex.quote(host_mp4_raw)}"
        )
        print(info, flush=True)

        # Download outputs
        local_raw = OUT_DIR / f"{tag}_h3_raw.mp4"
        local_orig = OUT_DIR / f"{tag}_orig_audio.mp4"
        local_sheet = OUT_DIR / f"{tag}_contact_sheet.png"
        transport.download(session, remote_mp4, local_raw, label=f"download {tag}_h3_raw.mp4", on_line=print)
        transport.download(session, f"{transport.remote_root}/{tag}_orig_audio.mp4", local_orig, label=f"download {tag}_orig_audio.mp4", on_line=print)
        transport.download(session, f"{transport.remote_root}/{tag}_contact_sheet.png", local_sheet, label=f"download {tag}_contact_sheet.png", on_line=print)

        print(f"\n=== {tag} COMPLETE ===", flush=True)
        print(f"H3 raw output:   {local_raw}", flush=True)
        print(f"Orig-audio mux:  {local_orig}", flush=True)
        print(f"Contact sheet:   {local_sheet}", flush=True)
    finally:
        print(f"[*] Stopping Spark session {session} and restoring services...", flush=True)
        transport.stop(session)


if __name__ == "__main__":
    main()
