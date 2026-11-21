"""Accompanied Singing A/B Experiment on local DGX Spark (H3_GUIDES).

Compares two strategies for accompanied singing (DiffRhythm open-source jazz ballad
'常溫咖啡', 00:05.50 - 00:18.50 = 13.00s, including a 1.3s pure jazz instrumental intro):
  - Group A (raw_mix):       Feed full mix (vocals + jazz accompaniment) into H3_GUIDES.
  - Group B (demucs_vocals): Feed Demucs-separated pure vocals into H3_GUIDES,
                             then mux the original full jazz mix back onto the video.

Runs both arms in ONE warm h3-bench container (672x384 draft, same first frame & seed),
and produces individual MP4s + a side-by-side comparison video (Left=A, Right=B).
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
OUT_DIR = EXP_DIR / "outputs_accomp_ab"
OUT_DIR.mkdir(parents=True, exist_ok=True)
HOST = runner_spark.HOST
SSH_OPTS = runner_spark.SSH_OPTS

PROMPT_BASE = (
    "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
    "integrated_multimodal_description: [Shot 1] Photorealistic live cozy café jazz ballad performance film. "
    "The young Taiwanese female singer in <Picture 1> remains seated on the wooden stool in the warm café, "
    "preserving her exact face, dark brown medium-length hair, cream knit sweater, natural acoustic guitar, "
    "vintage condenser microphone positioned below and slightly aside from her mouth, and the warm tungsten bokeh lights behind her. "
    "From 00:00.000 to 00:01.290, during the gentle instrumental jazz intro, her mouth remains softly closed with a relaxed, warm expression as she sways gently to the rhythm and strums softly. "
    "From 00:01.290 to 00:04.530, she begins singing smoothly and expressively with clear, natural lip and jaw articulation synchronized to every sung syllable: "
    "<d>[Chinese] 失聯了幾年，</d>. "
    "From 00:04.530 to 00:07.430, she tilts her head slightly with bittersweet emotion and sings clearly: "
    "<d>[Chinese] 意外的邀約，</d>. "
    "From 00:07.430 to 00:10.070, she softens her eyes and leans gently toward the microphone as she sings: "
    "<d>[Chinese] 你像擱置太久，</d>. "
    "From 00:10.070 to 00:12.800, she finishes the phrase with tender, lingering expression and crisp lip-sync: "
    "<d>[Chinese] 忘了洗的底片。</d>. "
    "The camera performs a very slow, steady push-in at medium close-up scale so her mouth and facial expressions remain sharp and unobstructed throughout.\n\n"
    "overall_soundscape: Intimate live jazz café recording with a warm close-mic female Mandarin singing voice synchronized precisely to her lip movements. No crowd chatter, no spoken dialogue.\n\n"
    "non_diegetic_music: {music_line}"
)


def ssh_run(cmd: str, timeout: int = 300) -> str:
    res = subprocess.run(
        ["ssh", *SSH_OPTS, HOST, cmd],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"SSH failed (exit {res.returncode}): {res.stderr or res.stdout}")
    return res.stdout.strip()


def main():
    frame_path = EXP_DIR / "frames" / "singer_frame_seed1.png"
    if not frame_path.is_file():
        raise FileNotFoundError(f"Missing first frame: {frame_path}")

    session = f"singing_ab_{int(time.time())}"
    transport = runner_spark.SPARK
    print(f"[*] Starting local DGX Spark warm session: {session} (Accompanied Singing A/B, 672x384 draft)", flush=True)
    transport.start(session, gpu="Spark", high_mem=True)

    try:
        host_dir = transport._dir(session)
        # Copy the prepared mix & demucs vocals into session dir
        ssh_run(
            f"cp ~/h3-studio/singing_accomp/accomp_h3.wav {shlex.quote(host_dir)}/accomp_mix.wav && "
            f"cp ~/h3-studio/singing_accomp/accomp_vocals.wav {shlex.quote(host_dir)}/accomp_vocals.wav && "
            f"cp ~/h3-studio/singing_accomp/accomp_novocals.wav {shlex.quote(host_dir)}/accomp_novocals.wav"
        )

        remote_frame = f"{transport.remote_root}/singer_frame.png"
        transport.upload(session, frame_path, remote_frame, label="upload singer frame", timeout=120, on_line=print)

        arms = [
            {
                "id": "A_raw_mix",
                "guide_audio": f"{transport.remote_root}/accomp_mix.wav",
                "music_line": "Soft warm café jazz ballad accompaniment with mellow electric piano, upright bass, and brushed drums.",
            },
            {
                "id": "B_demucs_vocals",
                "guide_audio": f"{transport.remote_root}/accomp_vocals.wav",
                "music_line": "N/A",
            },
        ]

        for arm in arms:
            aid = arm["id"]
            print(f"\n=== Running Arm {aid} (13.0s, 672x384 draft, seed=2026112199) ===", flush=True)
            prompt_text = PROMPT_BASE.format(music_line=arm["music_line"])
            local_p = OUT_DIR / f"prompt_{aid}.txt"
            local_p.write_text(prompt_text, encoding="utf-8")
            remote_p = f"{transport.remote_root}/prompt_{aid}.txt"
            transport.upload(session, local_p, remote_p, label=f"upload {aid} prompt", timeout=120, on_line=print)

            remote_mp4 = f"{transport.remote_root}/AB_{aid}_h3_audio.mp4"
            guides = [{"audio": arm["guide_audio"], "frame": 0}]
            env_values = [
                "H3_INFERENCE_MODE=first_frame",
                "H3_RESOLUTION=draft",
                "H3_DURATION_SECONDS=13.0",
                "H3_SEED=2026112199",
                f"H3_INPUT_IMAGE={remote_frame}",
                f"H3_PROMPT_FILE={remote_p}",
                f"H3_GUIDES={json.dumps(guides, separators=(',', ':'))}",
                f"H3_OUTPUT_PATH={remote_mp4}",
                f"H3_OUTPUT_PREFIX=ab_{aid}",
                "H3_JOB_TIMEOUT_SECONDS=1800",
            ]
            t0 = time.time()
            transport.execute(
                session, env_values, job_id=aid, work_dir=OUT_DIR,
                label=f"{aid} FL2VA H3_GUIDES", timeout=1800, on_line=print,
            )
            print(f"[*] Arm {aid} finished in {time.time() - t0:.1f}s", flush=True)

        # Post-process on Spark: mux original full jazz mix onto both A & B, build side-by-side video, contact sheets
        print("\n=== Post-processing A/B deliverables & side-by-side video on Spark ===", flush=True)
        post_cmd = (
            f"cd {shlex.quote(host_dir)} && "
            f"ffmpeg -y -i AB_A_raw_mix_h3_audio.mp4 -i accomp_mix.wav -map 0:v:0 -map 1:a:0 -t 13.0 -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart AB_A_raw_mix_orig_mix.mp4 -loglevel error && "
            f"ffmpeg -y -i AB_B_demucs_vocals_h3_audio.mp4 -i accomp_mix.wav -map 0:v:0 -map 1:a:0 -t 13.0 -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart AB_B_demucs_vocals_orig_mix.mp4 -loglevel error && "
            f"ffmpeg -y -i AB_A_raw_mix_orig_mix.mp4 -i AB_B_demucs_vocals_orig_mix.mp4 -filter_complex \"[0:v][1:v]hstack=inputs=2[v]\" -map \"[v]\" -map 0:a:0 -c:v libx264 -crf 20 -pix_fmt yuv420p -c:a copy -movflags +faststart AB_side_by_side_orig_mix.mp4 -loglevel error && "
            f"ffmpeg -y -i AB_A_raw_mix_orig_mix.mp4 -vf \"fps=1,scale=336:-1,tile=5x3\" -frames:v 1 AB_contact_sheet_A.png -loglevel error && "
            f"ffmpeg -y -i AB_B_demucs_vocals_orig_mix.mp4 -vf \"fps=1,scale=336:-1,tile=5x3\" -frames:v 1 AB_contact_sheet_B.png -loglevel error && "
            f"ls -lh AB_*"
        )
        print(ssh_run(post_cmd, timeout=300), flush=True)

        for name in (
            "AB_A_raw_mix_h3_audio.mp4",
            "AB_A_raw_mix_orig_mix.mp4",
            "AB_B_demucs_vocals_h3_audio.mp4",
            "AB_B_demucs_vocals_orig_mix.mp4",
            "AB_side_by_side_orig_mix.mp4",
            "AB_contact_sheet_A.png",
            "AB_contact_sheet_B.png",
            "accomp_mix.wav",
            "accomp_vocals.wav",
        ):
            transport.download(session, f"{transport.remote_root}/{name}", OUT_DIR / name, label=f"download {name}", on_line=print)

        print("\n=== ACCOMPANIED SINGING A/B COMPLETE ===", flush=True)
    finally:
        print(f"[*] Stopping Spark session {session} and restoring services...", flush=True)
        transport.stop(session)


if __name__ == "__main__":
    main()
