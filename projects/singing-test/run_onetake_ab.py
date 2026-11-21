"""3-Segment Continuous Single-Take (31.45s) A vs B Anti-Drift Experiment on local DGX Spark.

Stress-tests two single-take anti-oiliness / anti-drift strategies on our warm tungsten café
frame (singer_frame_seed1.png, where naive 6-hop FL2VA showed oily highlight accumulation):
  - Arm A (Ref2VA_anchor, 1 pass/seg):
      <Picture 1> ALWAYS locked to Gen-1 clean singer_frame_seed1.png, while H3_GUIDES at frame 0
      anchors BOTH image (previous segment cut-point frame) and audio (segment singing WAV).
  - Arm B (FL2VA_deglaze_lastframe, 2 passes/seg: 2-step draft + 6-step full):
      Pass 1: Fast 2-step FL2VA (H3_FAST_STEPS=2) generates motion & raw tail frame.
      Deglaze: Match tail frame's luminance/contrast/highlights back to Gen-1 clean frame.
      Pass 2: Standard 6-step FL2VA with H3_LAST_FRAME = deglazed tail + H3_GUIDES audio.

Both arms run in ONE warm h3-bench container at 672x384 draft (~22-25 min total) and output
individual 31.45s videos + a side-by-side comparison video (Left=A, Right=B).
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
OUT_DIR = EXP_DIR / "outputs_onetake_ab"
OUT_DIR.mkdir(parents=True, exist_ok=True)
HOST = runner_spark.HOST
SSH_OPTS = runner_spark.SSH_OPTS

SEGMENTS = [
    {
        "id": "S01",
        "start": 0.00,
        "duration": 10.65,
        "seed": 2026112161,
        "action": (
            "From 00:00.000 to 00:00.470, she gently strums the acoustic guitar and takes a soft breath. "
            "From 00:00.470 to 00:04.550, she sings expressively with clear lip-sync: <d>[Chinese] 感受停在我髮端的指尖，</d>. "
            "From 00:04.550 to 00:10.120, she sings tenderly with subtle shoulder sway: <d>[Chinese] 如何瞬間凍結時間。</d>."
        ),
    },
    {
        "id": "S02",
        "start": 10.65,
        "duration": 10.35,
        "seed": 2026112162,
        "action": (
            "From 00:00.000 to 00:00.400, she takes a gentle breath looking warmly forward. "
            "From 00:00.400 to 00:04.500, she sings melodically with crisp lip-sync: <d>[Chinese] 記住望著我堅定的雙眼，</d>. "
            "From 00:04.500 to 00:10.100, she softens her gaze slightly on the sustained note as she sings: <d>[Chinese] 也許已經沒有明天。</d>."
        ),
    },
    {
        "id": "S03",
        "start": 21.00,
        "duration": 10.45,
        "seed": 2026112163,
        "action": (
            "From 00:00.000 to 00:05.300, she lifts her gaze slightly with gentle wonder and sings clearly: "
            "<d>[Chinese] 面對浩瀚的星海，我們微小得像塵埃，</d>. "
            "From 00:05.300 to 00:10.200, she briefly closes her eyes on the emotional vowel then opens them softly as she sings: "
            "<d>[Chinese] 漂浮在一片無奈。</d>."
        ),
    },
]


def build_ref2va_prompt(action: str) -> str:
    return (
        "subject_definitions:\n"
        "<Subject 1>: The young Taiwanese female indie folk singer in <Picture 1>, with her exact face, "
        "natural matte skin texture, dark brown medium-length hair, cream knit sweater, natural acoustic guitar, "
        "and vintage condenser microphone positioned below and slightly aside from her mouth in the warm café.\n\n"
        "summary: A continuous single-take live acoustic studio vocal performance by <Subject 1> in the warm cozy café.\n\n"
        "retention_analysis: Strictly preserve <Subject 1>'s exact facial identity, natural matte non-oily skin tone, "
        "hair, cream knit sweater, acoustic guitar, microphone placement, and warm bokeh café background from <Picture 1> "
        "without increasing contrast or glossy skin highlights.\n\n"
        "detailed_description:\n"
        f"[Shot 1] Photorealistic live acoustic performance continuing seamlessly from frame 0. <Subject 1> remains seated "
        f"in the warm café with natural matte skin texture and subtle 35mm film grain (no oily or glossy highlights on the face). "
        f"{action} The camera stays steady at medium close-up framing with only subtle natural breathing, keeping her face and mouth sharp and unobstructed.\n\n"
        "overall_soundscape: Clean, intimate studio close-mic female Mandarin solo singing vocal synchronized precisely to her lip movements. No crowd chatter, no spoken dialogue.\n\n"
        "non_diegetic_music: N/A"
    )


def build_fl2va_prompt(action: str) -> str:
    return (
        "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
        "integrated_multimodal_description: [Shot 1] Photorealistic live acoustic performance continuing seamlessly from <Picture 1>. "
        "The young Taiwanese female indie folk singer remains seated in the warm cozy café, preserving her exact face, dark brown medium-length hair, "
        "cream knit sweater, acoustic guitar, vintage condenser microphone positioned below and slightly aside from her mouth, and warm tungsten bokeh lights behind her. "
        "Her face maintains natural matte skin texture with subtle 35mm film grain and no oily or glossy highlights. "
        f"{action} The camera stays steady at medium close-up framing with only subtle natural breathing, keeping her face and mouth sharp and unobstructed.\n\n"
        "overall_soundscape: Clean, intimate studio close-mic female Mandarin solo singing vocal synchronized precisely to her lip movements. No crowd chatter, no spoken dialogue.\n\n"
        "non_diegetic_music: N/A"
    )


# Python script executed inside h3-bench container (has PIL + numpy) to deglaze & color-match tail frame to Gen-1
DEGLAZE_PY = r"""
import sys, numpy as np
from PIL import Image

ref_path, tail_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
ref_im = Image.open(ref_path).convert("RGB")
tail_im = Image.open(tail_path).convert("RGB")
ref = np.asarray(ref_im.resize(tail_im.size, Image.LANCZOS), dtype=np.float32)
tail = np.asarray(tail_im, dtype=np.float32)

# Soft highlight roll-off (compress bright specular skin peaks) + channel mean/std match toward Gen-1 (blend 0.8)
out = tail.copy()
for c in range(3):
    r_mean, r_std = ref[:, :, c].mean(), ref[:, :, c].std() + 1e-5
    t_mean, t_std = tail[:, :, c].mean(), tail[:, :, c].std() + 1e-5
    matched = (tail[:, :, c] - t_mean) * (r_std / t_std) + r_mean
    # Blend 80% matched + 20% original to avoid any harsh jump while pulling contrast/oiliness back to Gen-1
    ch = 0.8 * matched + 0.2 * tail[:, :, c]
    # Soft-knee highlight compression above 215 to suppress oily specular shine
    over = np.maximum(0.0, ch - 215.0)
    ch = np.where(ch > 215.0, 215.0 + over * 0.55, ch)
    out[:, :, c] = np.clip(ch, 0.0, 255.0)

Image.fromarray(out.astype(np.uint8)).save(out_path)
print(f"Deglazed {tail_path} -> {out_path} (ref_std={ref.std():.1f}, tail_std={tail.std():.1f}, out_std={out.std():.1f})")
"""


def ssh_run(cmd: str, timeout: int = 300) -> str:
    res = subprocess.run(
        ["ssh", *SSH_OPTS, HOST, cmd],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"SSH failed (exit {res.returncode}): {res.stderr or res.stdout}")
    return res.stdout.strip()


def main():
    gen1_frame = EXP_DIR / "frames" / "singer_frame_seed1.png"
    if not gen1_frame.is_file():
        raise FileNotFoundError(f"Missing Gen-1 frame: {gen1_frame}")

    session = f"onetake_ab_{int(time.time())}"
    transport = runner_spark.SPARK
    container = transport._container(session)
    print(f"[*] Starting local DGX Spark warm session: {session} (3-seg 31.45s One-Take A vs B, 672x384 draft)", flush=True)
    transport.start(session, gpu="Spark", high_mem=True)

    try:
        host_dir = transport._dir(session)
        # Prepare 31.45s continuous audio + 3 segment slices + deglaze helper on Spark
        deglaze_local = OUT_DIR / "deglaze.py"
        deglaze_local.write_text(DEGLAZE_PY.strip() + "\n", encoding="utf-8")
        transport.upload(session, gen1_frame, f"{transport.remote_root}/gen1.png", label="upload Gen-1 frame", timeout=120, on_line=print)
        transport.upload(session, deglaze_local, f"{transport.remote_root}/deglaze.py", label="upload deglaze.py", timeout=60, on_line=print)

        slice_cmds = [
            f"ffmpeg -y -ss 0.00 -t 31.45 -i ~/h3-studio/singing_assets/opencpop_2001_60s.wav "
            f"-c:a pcm_s16le -ar 44100 -ac 1 {shlex.quote(host_dir)}/full_31s.wav -loglevel error"
        ]
        for seg in SEGMENTS:
            slice_cmds.append(
                f"ffmpeg -y -ss {seg['start']:.3f} -t {seg['duration']:.3f} -i ~/h3-studio/singing_assets/opencpop_2001_60s.wav "
                f"-c:a pcm_s16le -ar 44100 -ac 1 {shlex.quote(host_dir)}/{seg['id']}.wav -loglevel error"
            )
        ssh_run(" && ".join(slice_cmds))

        # =====================================================================
        # ARM A: Ref2VA (<Picture 1> = Gen-1) + H3_GUIDES (frame 0 = prev_last + audio), 1 pass/seg
        # =====================================================================
        print("\n================ ARM A: Ref2VA Gen-1 Lock + H3_GUIDES (1 pass/seg) ================", flush=True)
        prev_img_remote_A = f"{transport.remote_root}/gen1.png"
        t_armA_start = time.time()
        for seg in SEGMENTS:
            sid = seg["id"]
            print(f"\n--- Arm A {sid} ({seg['duration']:.2f}s, Ref2VA) ---", flush=True)
            local_p = OUT_DIR / f"prompt_A_{sid}.txt"
            local_p.write_text(build_ref2va_prompt(seg["action"]), encoding="utf-8")
            remote_p = f"{transport.remote_root}/prompt_A_{sid}.txt"
            transport.upload(session, local_p, remote_p, label=f"upload A {sid} prompt", timeout=120, on_line=print)

            remote_mp4 = f"{transport.remote_root}/A_{sid}.mp4"
            guides = [{"image": prev_img_remote_A, "audio": f"{transport.remote_root}/{sid}.wav", "frame": 0}]
            env_values = [
                "H3_INFERENCE_MODE=reference",
                "H3_RESOLUTION=draft",
                f"H3_DURATION_SECONDS={seg['duration']:.3f}",
                f"H3_SEED={seg['seed']}",
                f"H3_REFERENCE_IMAGES={json.dumps([f'{transport.remote_root}/gen1.png'])}",
                f"H3_PROMPT_FILE={remote_p}",
                f"H3_GUIDES={json.dumps(guides, separators=(',', ':'))}",
                f"H3_OUTPUT_PATH={remote_mp4}",
                f"H3_OUTPUT_PREFIX=onetake_A_{sid}",
                "H3_JOB_TIMEOUT_SECONDS=1800",
            ]
            t0 = time.time()
            transport.execute(session, env_values, job_id=f"A_{sid}", work_dir=OUT_DIR,
                              label=f"Arm A {sid} Ref2VA", timeout=1800, on_line=print)
            print(f"[*] Arm A {sid} finished in {time.time() - t0:.1f}s", flush=True)

            # Extract exact cut-point frame for next segment
            cut_t = seg["duration"] - 0.042
            host_last = f"{host_dir}/A_{sid}_last.png"
            ssh_run(f"ffmpeg -y -ss {cut_t:.3f} -i {shlex.quote(host_dir)}/A_{sid}.mp4 -frames:v 1 -q:v 1 {shlex.quote(host_last)} -loglevel error")
            prev_img_remote_A = f"{transport.remote_root}/A_{sid}_last.png"
        print(f"\n[*] ARM A TOTAL TIME: {time.time() - t_armA_start:.1f}s", flush=True)

        # =====================================================================
        # ARM B: FL2VA 2-step draft tail -> Deglaze/Color-Match -> 6-step FL2VA with H3_LAST_FRAME
        # =====================================================================
        print("\n================ ARM B: FL2VA 2-step Draft -> Deglaze -> 6-step H3_LAST_FRAME ================", flush=True)
        prev_img_remote_B = f"{transport.remote_root}/gen1.png"
        t_armB_start = time.time()
        for seg in SEGMENTS:
            sid = seg["id"]
            print(f"\n--- Arm B {sid} Pass 1 (2-step fast draft for tail frame) ---", flush=True)
            local_p = OUT_DIR / f"prompt_B_{sid}.txt"
            local_p.write_text(build_fl2va_prompt(seg["action"]), encoding="utf-8")
            remote_p = f"{transport.remote_root}/prompt_B_{sid}.txt"
            transport.upload(session, local_p, remote_p, label=f"upload B {sid} prompt", timeout=120, on_line=print)

            guides = [{"audio": f"{transport.remote_root}/{sid}.wav", "frame": 0}]
            remote_pass1_mp4 = f"{transport.remote_root}/B_{sid}_pass1.mp4"
            env_p1 = [
                "H3_INFERENCE_MODE=first_frame",
                "H3_RESOLUTION=draft",
                "H3_FAST_STEPS=2",
                f"H3_DURATION_SECONDS={seg['duration']:.3f}",
                f"H3_SEED={seg['seed']}",
                f"H3_INPUT_IMAGE={prev_img_remote_B}",
                f"H3_PROMPT_FILE={remote_p}",
                f"H3_GUIDES={json.dumps(guides, separators=(',', ':'))}",
                f"H3_OUTPUT_PATH={remote_pass1_mp4}",
                f"H3_OUTPUT_PREFIX=onetake_B_{sid}_p1",
                "H3_JOB_TIMEOUT_SECONDS=1800",
            ]
            t0 = time.time()
            transport.execute(session, env_p1, job_id=f"B_{sid}_p1", work_dir=OUT_DIR,
                              label=f"Arm B {sid} Pass 1 (2-step)", timeout=1800, on_line=print)
            print(f"[*] Arm B {sid} Pass 1 finished in {time.time() - t0:.1f}s", flush=True)

            # Extract final frame of Pass 1 (H3_LAST_FRAME anchors final frame of video) + deglaze to Gen-1
            host_raw_tail = f"{host_dir}/B_{sid}_raw_tail.png"
            remote_raw_tail = f"{transport.remote_root}/B_{sid}_raw_tail.png"
            remote_clean_tail = f"{transport.remote_root}/B_{sid}_clean_tail.png"
            ssh_run(
                f"ffmpeg -y -sseof -0.1 -i {shlex.quote(host_dir)}/B_{sid}_pass1.mp4 -update 1 -frames:v 1 -q:v 1 {shlex.quote(host_raw_tail)} -loglevel error && "
                f"docker exec {shlex.quote(container)} python3 {transport.remote_root}/deglaze.py "
                f"{transport.remote_root}/gen1.png {remote_raw_tail} {remote_clean_tail}"
            )

            print(f"--- Arm B {sid} Pass 2 (6-step FL2VA with deglazed H3_LAST_FRAME) ---", flush=True)
            remote_pass2_mp4 = f"{transport.remote_root}/B_{sid}.mp4"
            env_p2 = [
                "H3_INFERENCE_MODE=first_frame",
                "H3_RESOLUTION=draft",
                f"H3_DURATION_SECONDS={seg['duration']:.3f}",
                f"H3_SEED={seg['seed']}",
                f"H3_INPUT_IMAGE={prev_img_remote_B}",
                f"H3_LAST_FRAME={remote_clean_tail}",
                f"H3_PROMPT_FILE={remote_p}",
                f"H3_GUIDES={json.dumps(guides, separators=(',', ':'))}",
                f"H3_OUTPUT_PATH={remote_pass2_mp4}",
                f"H3_OUTPUT_PREFIX=onetake_B_{sid}_p2",
                "H3_JOB_TIMEOUT_SECONDS=1800",
            ]
            t1 = time.time()
            transport.execute(session, env_p2, job_id=f"B_{sid}_p2", work_dir=OUT_DIR,
                              label=f"Arm B {sid} Pass 2 (6-step FL2VA+LastFrame)", timeout=1800, on_line=print)
            print(f"[*] Arm B {sid} Pass 2 finished in {time.time() - t1:.1f}s", flush=True)

            # Extract exact cut-point frame from Pass 2 for next segment
            cut_t = seg["duration"] - 0.042
            host_last = f"{host_dir}/B_{sid}_last.png"
            ssh_run(f"ffmpeg -y -ss {cut_t:.3f} -i {shlex.quote(host_dir)}/B_{sid}.mp4 -frames:v 1 -q:v 1 {shlex.quote(host_last)} -loglevel error")
            prev_img_remote_B = f"{transport.remote_root}/B_{sid}_last.png"
        print(f"\n[*] ARM B TOTAL TIME: {time.time() - t_armB_start:.1f}s", flush=True)

        # =====================================================================
        # Assemble 31.45s Arm A, Arm B, and Side-by-Side Comparison on Spark
        # =====================================================================
        print("\n=== Assembling 31.45s One-Take A, B, and Side-by-Side Comparison ===", flush=True)
        assemble_parts = [f"cd {shlex.quote(host_dir)}"]
        for arm in ("A", "B"):
            lines = []
            for seg in SEGMENTS:
                sid = seg["id"]
                assemble_parts.append(
                    f"ffmpeg -y -i {arm}_{sid}.mp4 -t {seg['duration']:.3f} -r 24 -c:v libx264 -crf 18 -preset fast "
                    f"-pix_fmt yuv420p -an {arm}_{sid}_trim.mp4 -loglevel error"
                )
                lines.append(f"file '{arm}_{sid}_trim.mp4'")
            c_txt = "\\n".join(lines)
            out_name = "onetake_A_ref2va_31s.mp4" if arm == "A" else "onetake_B_fl2va_deglaze_31s.mp4"
            sheet_name = f"onetake_{arm}_contact_sheet.png"
            assemble_parts.append(f"printf '{c_txt}\\n' > concat_{arm}.txt")
            assemble_parts.append(
                f"ffmpeg -y -f concat -safe 0 -i concat_{arm}.txt -i full_31s.wav -map 0:v:0 -map 1:a:0 "
                f"-c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart {out_name} -loglevel error"
            )
            assemble_parts.append(
                f"ffmpeg -y -i {out_name} -vf \"fps=0.48,scale=336:-1,tile=5x3\" -frames:v 1 {sheet_name} -loglevel error"
            )
        assemble_parts.append(
            "ffmpeg -y -i onetake_A_ref2va_31s.mp4 -i onetake_B_fl2va_deglaze_31s.mp4 "
            "-filter_complex \"[0:v][1:v]hstack=inputs=2[v]\" -map \"[v]\" -map 0:a:0 "
            "-c:v libx264 -crf 20 -pix_fmt yuv420p -c:a copy -movflags +faststart onetake_AB_side_by_side_31s.mp4 -loglevel error"
        )
        assemble_parts.append("ls -lh onetake_*")
        print(ssh_run(" && ".join(assemble_parts), timeout=300), flush=True)

        for name in (
            "onetake_A_ref2va_31s.mp4",
            "onetake_B_fl2va_deglaze_31s.mp4",
            "onetake_AB_side_by_side_31s.mp4",
            "onetake_A_contact_sheet.png",
            "onetake_B_contact_sheet.png",
        ):
            transport.download(session, f"{transport.remote_root}/{name}", OUT_DIR / name, label=f"download {name}", on_line=print)

        print("\n=== ONE-TAKE A vs B COMPLETE ===", flush=True)
    finally:
        print(f"[*] Stopping Spark session {session} and restoring services...", flush=True)
        transport.stop(session)


if __name__ == "__main__":
    main()
