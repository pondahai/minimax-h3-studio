"""Chain S02-S06 from S01_full_h3_raw.mp4 into a full 60-second 1376x768 singing video on local DGX Spark.

Features:
  - Reuses existing outputs/S01_full_h3_raw.mp4 (skips any already-completed segment)
  - Runs S02-S06 in ONE warm h3-bench container (ComfyUI + model loaded once)
  - Full resolution 1376x768 + H3_SPARSE=1 (sol-attn)
  - Exact frame-accurate last-frame continuation (extracts frame at exact slice end before H3 tail)
  - Exact slice trimming during final concat so 60.00s audio stays 100% lip-synced with zero drift
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

SEGMENTS = [
    {
        "id": "S01",
        "start": 0.00,
        "duration": 10.65,
        "seed": 2026112101,
        "lyrics": "感受停在我髮端的指尖，如何瞬間凍結時間。",
        "prompt": None,  # Already rendered as S01_full_h3_raw.mp4
    },
    {
        "id": "S02",
        "start": 10.65,
        "duration": 10.35,
        "seed": 2026112102,
        "lyrics": "記住望著我堅定的雙眼，也許已經沒有明天。",
        "prompt": (
            "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
            "integrated_multimodal_description: [Shot 1] Photorealistic live acoustic studio performance film, continuing seamlessly from <Picture 1>. "
            "The young Taiwanese female indie folk singer remains in the exact same warm cozy café, preserving her face, dark brown medium-length hair, "
            "cream knit sweater, vintage condenser microphone positioned below and slightly aside from her mouth, and warm tungsten bokeh lights behind her. "
            "From 00:00.000 to 00:00.400, she takes a gentle breath and looks steadily forward with sincere emotion. "
            "From 00:00.400 to 00:04.500, she sings melodically with clear, expressive lip and jaw articulation synchronized to every sung syllable, "
            "subtle shoulder sway and warm eye contact as she sings: <d>[Chinese] 記住望著我堅定的雙眼，</d>. "
            "From 00:04.500 to 00:10.100, her expression deepens with quiet yearning, softening her gaze slightly on the sustained ending note as she sings: "
            "<d>[Chinese] 也許已經沒有明天。</d>. "
            "The camera stays steady at the exact same medium close-up framing with only subtle natural handheld breathing, keeping her mouth sharp and unobstructed throughout.\n\n"
            "overall_soundscape: Clean, intimate studio close-mic female Mandarin solo singing vocal synchronized precisely to her lip movements. No crowd chatter, no spoken dialogue.\n\n"
            "non_diegetic_music: N/A"
        ),
    },
    {
        "id": "S03",
        "start": 21.00,
        "duration": 10.45,
        "seed": 2026112103,
        "lyrics": "面對浩瀚的星海，我們微小得像塵埃，漂浮在一片無奈。",
        "prompt": (
            "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
            "integrated_multimodal_description: [Shot 1] Photorealistic live acoustic studio performance film, continuing seamlessly from <Picture 1>. "
            "The young Taiwanese female indie folk singer remains in the exact same warm cozy café, preserving her face, dark brown medium-length hair, "
            "cream knit sweater, vintage condenser microphone positioned below and slightly aside from her mouth, and warm tungsten bokeh lights behind her. "
            "From 00:00.000 to 00:05.300, she lifts her gaze slightly with gentle wonder and sings melodically with clear, natural lip and jaw movement synchronized to every syllable: "
            "<d>[Chinese] 面對浩瀚的星海，我們微小得像塵埃，</d>. "
            "From 00:05.300 to 00:10.200, she gently tilts her head and briefly closes her eyes on the emotional sustained vowel, then opens them softly as she sings: "
            "<d>[Chinese] 漂浮在一片無奈。</d>. "
            "The camera holds a steady medium close-up framing with very gentle natural micro-movement, keeping her face and lips crisp and completely unobstructed.\n\n"
            "overall_soundscape: Clean, intimate studio close-mic female Mandarin solo singing vocal synchronized precisely to her lip movements. No crowd chatter, no spoken dialogue.\n\n"
            "non_diegetic_music: N/A"
        ),
    },
    {
        "id": "S04",
        "start": 31.45,
        "duration": 11.20,
        "seed": 2026112104,
        "lyrics": "緣分讓我們相遇亂世以外，命運卻要我們危難中相愛。",
        "prompt": (
            "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
            "integrated_multimodal_description: [Shot 1] Photorealistic live acoustic studio performance film, continuing seamlessly from <Picture 1>. "
            "The young Taiwanese female indie folk singer remains in the exact same warm cozy café, preserving her face, dark brown medium-length hair, "
            "cream knit sweater, vintage condenser microphone positioned below and slightly aside from her mouth, and warm tungsten bokeh lights behind her. "
            "From 00:00.000 to 00:05.800, her singing rises in emotional intensity; she leans slightly toward the condenser microphone with expressive eyebrows and clear lip-sync as she sings: "
            "<d>[Chinese] 緣分讓我們相遇亂世以外，</d>. "
            "From 00:05.800 to 00:10.900, she sways gently with heartfelt passion, articulating every sung syllable crisply while singing: "
            "<d>[Chinese] 命運卻要我們危難中相愛。</d>. "
            "The camera stays steady at the exact same medium close-up framing, keeping her face, mouth, and microphone sharp and stable throughout.\n\n"
            "overall_soundscape: Clean, intimate studio close-mic female Mandarin solo singing vocal synchronized precisely to her lip movements. No crowd chatter, no spoken dialogue.\n\n"
            "non_diegetic_music: N/A"
        ),
    },
    {
        "id": "S05",
        "start": 42.65,
        "duration": 5.50,
        "seed": 2026112105,
        "lyrics": "也許未來遙遠在光年之外，",
        "prompt": (
            "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
            "integrated_multimodal_description: [Shot 1] Photorealistic live acoustic studio performance film, continuing seamlessly from <Picture 1>. "
            "The young Taiwanese female indie folk singer remains in the exact same warm cozy café, preserving her face, dark brown medium-length hair, "
            "cream knit sweater, vintage condenser microphone positioned below and slightly aside from her mouth, and warm tungsten bokeh lights behind her. "
            "From 00:00.000 to 00:05.400, she builds emotional momentum with bright, open vocal projection and precise lip-sync, gently nodding with the melody as she sings: "
            "<d>[Chinese] 也許未來遙遠在光年之外，</d>. "
            "The camera holds steady at the same medium close-up framing with crisp focus on her face and lips.\n\n"
            "overall_soundscape: Clean, intimate studio close-mic female Mandarin solo singing vocal synchronized precisely to her lip movements. No crowd chatter, no spoken dialogue.\n\n"
            "non_diegetic_music: N/A"
        ),
    },
    {
        "id": "S06",
        "start": 48.15,
        "duration": 11.85,
        "seed": 2026112106,
        "lyrics": "我願守候未知裡為你等待。我沒想到為了你我能瘋狂到，山崩海嘯沒有你根本不想逃。",
        "prompt": (
            "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
            "integrated_multimodal_description: [Shot 1] Photorealistic live acoustic studio performance film, continuing seamlessly from <Picture 1>. "
            "The young Taiwanese female indie folk singer remains in the exact same warm cozy café, preserving her face, dark brown medium-length hair, "
            "cream knit sweater, vintage condenser microphone positioned below and slightly aside from her mouth, and warm tungsten bokeh lights behind her. "
            "From 00:00.000 to 00:04.100, she sings with deep devotion and clear lip articulation: <d>[Chinese] 我願守候未知裡為你等待。</d>. "
            "From 00:04.100 to 00:11.600, she reaches the emotional chorus climax with strong, passionate singing, expressive eyebrows, subtle head movement, and crisp open-vowel lip-sync as she sings: "
            "<d>[Chinese] 我沒想到為了你我能瘋狂到，山崩海嘯沒有你根本不想逃。</d>. "
            "The camera holds a steady medium close-up with very gentle natural breathing, keeping her face and mouth sharp and unobstructed through the final frame.\n\n"
            "overall_soundscape: Clean, intimate studio close-mic female Mandarin solo singing vocal synchronized precisely to her lip movements. No crowd chatter, no spoken dialogue.\n\n"
            "non_diegetic_music: N/A"
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
    s01_local = OUT_DIR / "S01_full_h3_raw.mp4"
    if not s01_local.is_file():
        raise FileNotFoundError(f"Missing S01 full output: {s01_local}")

    session = f"singing_60s_full_{int(time.time())}"
    transport = runner_spark.SPARK
    print(f"[*] Starting local DGX Spark warm session: {session} (1376x768 full + sol-attn)", flush=True)
    transport.start(session, gpu="Spark", high_mem=True)

    try:
        host_dir = transport._dir(session)
        # Upload S01_full_h3_raw.mp4 into session dir so we can extract its exact cut-point frame and concat later
        remote_s01 = f"{transport.remote_root}/S01_full_h3_raw.mp4"
        transport.upload(session, s01_local, remote_s01, label="upload S01_full_h3_raw.mp4", timeout=300, on_line=print)

        prev_mp4_host = f"{host_dir}/S01_full_h3_raw.mp4"
        prev_cut_time = SEGMENTS[0]["duration"] - 0.042  # 1 frame before exact slice end

        for seg in SEGMENTS[1:]:
            sid = seg["id"]
            local_raw = OUT_DIR / f"{sid}_full_h3_raw.mp4"
            remote_raw = f"{transport.remote_root}/{sid}_full_h3_raw.mp4"
            host_raw = f"{host_dir}/{sid}_full_h3_raw.mp4"

            if local_raw.is_file() and local_raw.stat().st_size > 100_000:
                print(f"[*] {sid} already exists locally ({local_raw.name}), uploading to Spark for continuation...", flush=True)
                transport.upload(session, local_raw, remote_raw, label=f"upload existing {sid}", timeout=300, on_line=print)
                prev_mp4_host = host_raw
                prev_cut_time = seg["duration"] - 0.042
                continue

            print(f"\n=== {sid} ({seg['start']:.2f}s - {seg['start'] + seg['duration']:.2f}s, {seg['duration']:.2f}s) ===", flush=True)
            # 1. Extract continuation first frame from previous segment at exact cut point
            host_frame = f"{host_dir}/{sid}_first_frame.png"
            remote_frame = f"{transport.remote_root}/{sid}_first_frame.png"
            host_wav = f"{host_dir}/{sid}.wav"
            remote_wav = f"{transport.remote_root}/{sid}.wav"
            ssh_run(
                f"ffmpeg -y -ss {prev_cut_time:.3f} -i {shlex.quote(prev_mp4_host)} -frames:v 1 -q:v 1 {shlex.quote(host_frame)} -loglevel error && "
                f"ffmpeg -y -ss {seg['start']:.3f} -t {seg['duration']:.3f} -i ~/h3-studio/singing_assets/opencpop_2001_60s.wav "
                f"-c:a pcm_s16le -ar 44100 -ac 1 {shlex.quote(host_wav)} -loglevel error"
            )

            # 2. Upload prompt
            local_prompt = OUT_DIR / f"prompt_{sid.lower()}.txt"
            local_prompt.write_text(seg["prompt"], encoding="utf-8")
            remote_prompt = f"{transport.remote_root}/prompt_{sid.lower()}.txt"
            transport.upload(session, local_prompt, remote_prompt, label=f"upload {sid} prompt", timeout=120, on_line=print)

            # 3. Run H3 FL2VA + H3_GUIDES in warm container
            guides = [{"audio": remote_wav, "frame": 0}]
            env_values = [
                "H3_INFERENCE_MODE=first_frame",
                "H3_RESOLUTION=full",
                "H3_SPARSE=1",
                f"H3_DURATION_SECONDS={seg['duration']:.3f}",
                f"H3_SEED={seg['seed']}",
                f"H3_INPUT_IMAGE={remote_frame}",
                f"H3_PROMPT_FILE={remote_prompt}",
                f"H3_GUIDES={json.dumps(guides, separators=(',', ':'))}",
                f"H3_OUTPUT_PATH={remote_raw}",
                f"H3_OUTPUT_PREFIX=singing_{sid.lower()}_full",
                "H3_JOB_TIMEOUT_SECONDS=3600",
            ]
            t0 = time.time()
            transport.execute(
                session, env_values, job_id=f"{sid.lower()}_full", work_dir=OUT_DIR,
                label=f"{sid} full 1376x768 H3_GUIDES", timeout=3600, on_line=print,
            )
            print(f"[*] {sid} finished in {time.time() - t0:.1f}s", flush=True)

            # 4. Download completed segment immediately (preserves progress)
            transport.download(session, remote_raw, local_raw, label=f"download {sid}_full_h3_raw.mp4", on_line=print)
            prev_mp4_host = host_raw
            prev_cut_time = seg["duration"] - 0.042

        # --- Final Assembly on Spark (exact duration trims -> zero cumulative lip-sync drift) ---
        print("\n=== Assembling full 60.00s video (frame-accurate trim + concat) ===", flush=True)
        trim_cmds = []
        concat_lines = []
        for seg in SEGMENTS:
            sid = seg["id"]
            src = f"{host_dir}/{sid}_full_h3_raw.mp4"
            trimmed = f"{host_dir}/{sid}_trimmed.mp4"
            trim_cmds.append(
                f"ffmpeg -y -i {shlex.quote(src)} -t {seg['duration']:.3f} "
                f"-r 24 -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p "
                f"-c:a aac -b:a 192k -ar 44100 -ac 1 {shlex.quote(trimmed)} -loglevel error"
            )
            concat_lines.append(f"file '{trimmed}'")

        concat_list_host = f"{host_dir}/concat_list.txt"
        concat_content = "\\n".join(concat_lines)
        full_h3_raw = f"{host_dir}/singing_60s_full_h3_raw.mp4"
        full_orig = f"{host_dir}/singing_60s_full_orig_audio.mp4"
        full_share = f"{host_dir}/singing_60s_full_share.mp4"
        full_sheet = f"{host_dir}/singing_60s_contact_sheet.png"

        assemble_script = (
            " && ".join(trim_cmds) +
            f" && printf '{concat_content}\\n' > {shlex.quote(concat_list_host)}"
            f" && ffmpeg -y -f concat -safe 0 -i {shlex.quote(concat_list_host)} -c copy -movflags +faststart {shlex.quote(full_h3_raw)} -loglevel error"
            f" && ffmpeg -y -i {shlex.quote(full_h3_raw)} -i ~/h3-studio/singing_assets/opencpop_2001_60s.wav "
            f"-map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart {shlex.quote(full_orig)} -loglevel error"
            f" && ffmpeg -y -i {shlex.quote(full_orig)} -c:v libx264 -crf 27 -preset medium -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart {shlex.quote(full_share)} -loglevel error"
            f" && ffmpeg -y -i {shlex.quote(full_orig)} -vf \"fps=0.25,scale=458:-1,tile=5x3\" -frames:v 1 {shlex.quote(full_sheet)} -loglevel error"
            f" && ffprobe -v error -show_entries format=duration,size -show_entries stream=codec_type,codec_name,width,height -of compact {shlex.quote(full_orig)}"
        )
        info = ssh_run(assemble_script, timeout=600)
        print(info, flush=True)

        # Download final 60s deliverables
        for name in (
            "singing_60s_full_orig_audio.mp4",
            "singing_60s_full_h3_raw.mp4",
            "singing_60s_full_share.mp4",
            "singing_60s_contact_sheet.png",
        ):
            transport.download(session, f"{transport.remote_root}/{name}", OUT_DIR / name, label=f"download {name}", on_line=print)

        print("\n=== ALL 60s FULL-RES DELIVERABLES COMPLETE ===", flush=True)
    finally:
        print(f"[*] Stopping Spark session {session} and restoring services...", flush=True)
        transport.stop(session)


if __name__ == "__main__":
    main()
