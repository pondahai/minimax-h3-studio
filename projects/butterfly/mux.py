"""把 video/SXX.mp4 配上 TTS 台詞（H3 原生音軌壓低當環境音），再串成 butterfly_draft.mp4。

台詞放在分鏡標的起秒；若前一句還沒講完就順延，講不完則用 atempo 加速（一般上限 1.35，段尾最後一句上限 1.5）。
"""
import json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
AUDIO, VIDEO, MIXED = HERE / "audio", HERE / "video", HERE / "mixed"
DUR = {"S07": 10}
BED_VOLUME = 0.3
GAP = 0.15


def schedule(lines, seg_dur):
    plan, prev_end = [], 0.0
    for i, ln in enumerate(lines):
        t = max(ln["start"], prev_end + GAP if plan else ln["start"])
        last = i == len(lines) - 1
        limit = seg_dur if last else lines[i + 1]["start"]
        room = max(limit - t, 0.5)
        tempo = min(max(ln["audio_sec"] / room, 1.0), 1.5 if last else 1.35)
        prev_end = t + ln["audio_sec"] / tempo
        plan.append((ln, t, tempo))
    return plan


def mix(sid, lines):
    seg_dur = DUR.get(sid, 12)
    src = VIDEO / f"{sid}.mp4"
    dst = MIXED / f"{sid}.mp4"
    plan = schedule(lines, seg_dur)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
    filters = [f"[0:a]volume={BED_VOLUME},apad[bed]"]
    labels = ["[bed]"]
    for n, (ln, t, tempo) in enumerate(plan, start=1):
        cmd += ["-i", str(AUDIO / ln["file"])]
        filters.append(f"[{n}:a]aresample=48000,atempo={tempo:.3f},adelay={int(t * 1000)}:all=1[v{n}]")
        labels.append(f"[v{n}]")
        print(f"  {ln['file']} @ {t:.2f}s x{tempo:.2f} → 結束 {t + ln['audio_sec'] / tempo:.2f}s")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,atrim=0:{seg_dur}[a]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", str(seg_dur), str(dst)]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    MIXED.mkdir(exist_ok=True)
    report = json.loads((AUDIO / "lines.json").read_text(encoding="utf-8"))
    sids = sorted(p.stem for p in VIDEO.glob("S*.mp4"))
    for sid in sids:
        print(sid)
        mix(sid, [ln for ln in report if ln["sid"] == sid])
    (MIXED / "list.txt").write_text("".join(f"file '{s}.mp4'\n" for s in sids), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(MIXED / "list.txt"),
                    "-c", "copy", str(HERE / "butterfly_draft.mp4")], check=True)
    print("輸出：", HERE / "butterfly_draft.mp4")
