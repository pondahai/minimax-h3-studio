"""2-Angle Soft-Diffused Matte-Skin Accompanied Singing MV Test (24.00s) on local DGX Spark.

Tests:
  1. Anti-oily matte skin lighting (soft diffused daylight + matte-skin prompt constraints)
  2. Multi-angle cut (Medium Guitar Shot -> CUT to Intimate Close-Up) to reset I2V contrast/highlight buildup
  3. Direct full-mix accompanied singing via H3_GUIDES (DiffRhythm jazz ballad '常溫咖啡', 00:05.50 - 00:29.50 = 24.00s)
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
OUT_DIR = EXP_DIR / "outputs_matte_2angle"
OUT_DIR.mkdir(parents=True, exist_ok=True)
HOST = runner_spark.HOST
SSH_OPTS = runner_spark.SSH_OPTS

SEGMENTS = [
    {
        "id": "M01",
        "start": 5.50,
        "duration": 13.00,
        "seed": 2026112151,
        "frame": EXP_DIR / "frames" / "matte_angle2_side.png",
        "prompt": (
            "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
            "integrated_multimodal_description: [Shot 1] Japanese 35mm film aesthetic live acoustic studio performance. "
            "The young Taiwanese female folk singer in <Picture 1> remains seated in the bright, sunlit minimalist studio, "
            "preserving her exact face, dark brown medium-length hair, oatmeal knit sweater, wooden acoustic guitar, "
            "matte silver condenser microphone positioned below and slightly aside from her mouth, and soft white sheer curtains behind her. "
            "Her face maintains natural matte skin texture under soft diffused window daylight with subtle 35mm film grain and no oily or glossy highlights on the face. "
            "From 00:00.000 to 00:01.290, during the gentle instrumental jazz intro, her mouth remains softly closed with a relaxed, warm expression as her fingers gently strum the acoustic guitar. "
            "From 00:01.290 to 00:04.530, she begins singing smoothly with clear, natural lip and jaw articulation synchronized to every sung syllable: "
            "<d>[Chinese] 失聯了幾年，</d>. "
            "From 00:04.530 to 00:07.430, she sways gently with bittersweet emotion while strumming and singing clearly: "
            "<d>[Chinese] 意外的邀約，</d>. "
            "From 00:07.430 to 00:10.070, she softens her gaze and sings tenderly: "
            "<d>[Chinese] 你像擱置太久，</d>. "
            "From 00:10.070 to 00:12.800, she finishes the phrase with crisp lip-sync: "
            "<d>[Chinese] 忘了洗的底片。</d>. "
            "The camera holds a steady medium shot showing her face, hands, and guitar cleanly throughout.\n\n"
            "overall_soundscape: Intimate sunlit studio jazz ballad recording with a warm close-mic female Mandarin singing voice synchronized precisely to her lip movements. No crowd chatter, no spoken dialogue.\n\n"
            "non_diegetic_music: Soft warm café jazz ballad accompaniment with mellow electric piano, upright bass, and brushed drums."
        ),
    },
    {
        "id": "M02",
        "start": 18.50,
        "duration": 11.00,
        "seed": 2026112152,
        "frame": EXP_DIR / "frames" / "matte_angle1_front.png",
        "prompt": (
            "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
            "integrated_multimodal_description: [Shot 1] Japanese 35mm film aesthetic live acoustic studio performance, intimate closer camera angle. "
            "The young Taiwanese female folk singer in <Picture 1> remains seated in the bright, sunlit minimalist studio, "
            "preserving her exact face, dark brown medium-length hair, oatmeal knit sweater, wooden acoustic guitar, "
            "matte silver condenser microphone positioned below and slightly aside from her mouth, and soft white sheer curtains behind her. "
            "Her face maintains natural matte skin texture under soft diffused window daylight with subtle 35mm film grain and no oily or glossy highlights on the face. "
            "From 00:00.000 to 00:00.900, she takes a soft musical breath with a gentle, reflective gaze. "
            "From 00:00.900 to 00:03.800, she sings with warm emotional depth and crisp lip-sync: "
            "<d>[Chinese] 深刻的從前，</d>. "
            "From 00:03.800 to 00:07.300, she tilts her head softly and sings clearly: "
            "<d>[Chinese] 禁不起陳列，</d>. "
            "From 00:07.300 to 00:10.800, she briefly closes her eyes on the tender note then opens them warmly as she sings: "
            "<d>[Chinese] 原封不動，才得以保全。</d>. "
            "The camera stays steady at medium close-up scale with very gentle natural breathing, keeping her matte skin, face, and lips crisp and unobstructed throughout.\n\n"
            "overall_soundscape: Intimate sunlit studio jazz ballad recording with a warm close-mic female Mandarin singing voice synchronized precisely to her lip movements. No crowd chatter, no spoken dialogue.\n\n"
            "non_diegetic_music: Soft warm café jazz ballad accompaniment with mellow electric piano, upright bass, and brushed drums."
        ),
    },
]


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
    tag = "full" if full_res else "draft"
    suffix = "_full" if full_res else ""
    for seg in SEGMENTS:
        if not seg["frame"].is_file():
            raise FileNotFoundError(f"Missing frame: {seg['frame']}")

    session = f"singing_matte_{tag}_{int(time.time())}"
    transport = runner_spark.SPARK
    print(f"[*] Starting local DGX Spark warm session: {session} (2-Angle Matte Skin MV, {'1376x768 full + sol-attn' if full_res else '672x384 draft'})", flush=True)
    transport.start(session, gpu="Spark", high_mem=True)

    try:
        host_dir = transport._dir(session)
        # Prepare continuous 24.00s audio + individual segment slices on Spark
        ssh_run(
            f"ffmpeg -y -ss 5.50 -t 24.00 -i ~/h3-studio/singing_accomp/chang_wen_ca_fei_jazz.mp3 "
            f"-c:a pcm_s16le -ar 44100 -ac 2 {shlex.quote(host_dir)}/full_24s_mix.wav -loglevel error"
        )

        for seg in SEGMENTS:
            sid = seg["id"]
            print(f"\n=== Running {sid} ({tag}, {seg['start']:.2f}s - {seg['start'] + seg['duration']:.2f}s, {seg['duration']:.2f}s) ===", flush=True)
            host_wav = f"{host_dir}/{sid}.wav"
            remote_wav = f"{transport.remote_root}/{sid}.wav"
            ssh_run(
                f"ffmpeg -y -ss {seg['start']:.3f} -t {seg['duration']:.3f} -i ~/h3-studio/singing_accomp/chang_wen_ca_fei_jazz.mp3 "
                f"-c:a pcm_s16le -ar 44100 -ac 2 {shlex.quote(host_wav)} -loglevel error"
            )

            remote_frame = f"{transport.remote_root}/{sid}_frame.png"
            remote_prompt = f"{transport.remote_root}/prompt_{sid}.txt"
            remote_mp4 = f"{transport.remote_root}/{sid}{suffix}_h3_raw.mp4"
            local_prompt = OUT_DIR / f"prompt_{sid}.txt"
            local_prompt.write_text(seg["prompt"], encoding="utf-8")

            transport.upload(session, seg["frame"], remote_frame, label=f"upload {sid} frame", timeout=120, on_line=print)
            transport.upload(session, local_prompt, remote_prompt, label=f"upload {sid} prompt", timeout=120, on_line=print)

            guides = [{"audio": remote_wav, "frame": 0}]
            env_values = [
                "H3_INFERENCE_MODE=first_frame",
                f"H3_RESOLUTION={'full' if full_res else 'draft'}",
                f"H3_SPARSE={'1' if full_res else '0'}",
                f"H3_DURATION_SECONDS={seg['duration']:.3f}",
                f"H3_SEED={seg['seed']}",
                f"H3_INPUT_IMAGE={remote_frame}",
                f"H3_PROMPT_FILE={remote_prompt}",
                f"H3_GUIDES={json.dumps(guides, separators=(',', ':'))}",
                f"H3_OUTPUT_PATH={remote_mp4}",
                f"H3_OUTPUT_PREFIX=matte_{sid}{suffix}",
                "H3_JOB_TIMEOUT_SECONDS=3600",
            ]
            t0 = time.time()
            transport.execute(
                session, env_values, job_id=f"{sid}_{tag}", work_dir=OUT_DIR,
                label=f"{sid} {tag} matte-skin FL2VA H3_GUIDES", timeout=3600, on_line=print,
            )
            print(f"[*] {sid} ({tag}) finished in {time.time() - t0:.1f}s", flush=True)
            transport.download(session, remote_mp4, OUT_DIR / f"{sid}{suffix}_h3_raw.mp4", label=f"download {sid}{suffix}_h3_raw.mp4", on_line=print)

        # Assemble exact 24.00s 2-angle MV on Spark
        print(f"\n=== Assembling 24.00s 2-Angle Matte-Skin MV ({tag}) on Spark ===", flush=True)
        out_raw = f"matte_mv_24s{suffix}_h3_raw.mp4"
        out_orig = f"matte_mv_24s{suffix}_orig_mix.mp4"
        out_share = f"matte_mv_24s{suffix}_share.mp4"
        out_sheet = f"matte_mv_24s{suffix}_contact_sheet.png"
        sheet_scale = 458 if full_res else 336
        assemble = (
            f"cd {shlex.quote(host_dir)} && "
            f"ffmpeg -y -i M01{suffix}_h3_raw.mp4 -t 13.000 -r 24 -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a aac -b:a 192k -ar 44100 -ac 2 M01_trim.mp4 -loglevel error && "
            f"ffmpeg -y -i M02{suffix}_h3_raw.mp4 -t 11.000 -r 24 -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a aac -b:a 192k -ar 44100 -ac 2 M02_trim.mp4 -loglevel error && "
            f"printf \"file 'M01_trim.mp4'\\nfile 'M02_trim.mp4'\\n\" > concat.txt && "
            f"ffmpeg -y -f concat -safe 0 -i concat.txt -c copy -movflags +faststart {out_raw} -loglevel error && "
            f"ffmpeg -y -i {out_raw} -i full_24s_mix.wav -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart {out_orig} -loglevel error && "
            f"ffmpeg -y -i {out_orig} -c:v libx264 -crf 27 -preset medium -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart {out_share} -loglevel error && "
            f"ffmpeg -y -i {out_orig} -vf \"fps=0.625,scale={sheet_scale}:-1,tile=5x3\" -frames:v 1 {out_sheet} -loglevel error && "
            f"ffprobe -v error -show_entries format=duration,size -show_entries stream=codec_type,width,height -of compact {out_orig}"
        )
        print(ssh_run(assemble, timeout=300), flush=True)

        for name in (out_orig, out_raw, out_share, out_sheet):
            transport.download(session, f"{transport.remote_root}/{name}", OUT_DIR / name, label=f"download {name}", on_line=print)

        print(f"\n=== 2-ANGLE MATTE-SKIN MV ({tag}) COMPLETE ===", flush=True)
    finally:
        print(f"[*] Stopping Spark session {session} and restoring services...", flush=True)
        transport.stop(session)


if __name__ == "__main__":
    main()
