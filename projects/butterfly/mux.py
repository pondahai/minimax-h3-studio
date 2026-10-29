"""把 video/SXX.mp4 配上 TTS 台詞（H3 原生音軌靜音），再串成 butterfly_draft.mp4。

台詞放在分鏡標的起秒；若前一句還沒講完就順延，講不完則用 atempo 加速（一般上限 1.35，段尾最後一句上限 1.5）。
"""
import json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
AUDIO, VIDEO, MIXED = HERE / "audio", HERE / "video", HERE / "mixed"
DUR = {"S07": 10}
BED_VOLUME = 0.0  # H3 原生音軌會自己編出非中文的說話聲，與 TTS 疊在一起，故不使用
GAP = 0.15
MUSIC = HERE / "music" / "bgm.wav"  # 使用者選定的配樂（H3 生成的 12 秒片段）
MUSIC_CLIP, MUSIC_XFADE, MUSIC_VOLUME = 12.25, 1.5, 0.22


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


def add_music(src, dst, total):
    """把 12 秒配樂以交叉淡化循環到片長，壓低音量墊在台詞下，頭尾淡入淡出。"""
    copies = int(total // (MUSIC_CLIP - MUSIC_XFADE)) + 2
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)] + ["-i", str(MUSIC)] * copies
    chain, prev = [], "[1:a]"
    for n in range(2, copies + 1):
        chain.append(f"{prev}[{n}:a]acrossfade=d={MUSIC_XFADE}[m{n}]")
        prev = f"[m{n}]"
    chain.append(f"{prev}atrim=0:{total},volume={MUSIC_VOLUME},afade=t=in:d=1,afade=t=out:st={total - 3}:d=3[bgm]")
    chain.append("[0:a][bgm]amix=inputs=2:normalize=0:duration=first[a]")
    cmd += ["-filter_complex", ";".join(chain), "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", str(dst)]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    MIXED.mkdir(exist_ok=True)
    report = json.loads((AUDIO / "lines.json").read_text(encoding="utf-8"))
    sids = sorted(p.stem for p in VIDEO.glob("S*.mp4"))
    for sid in sids:
        print(sid)
        mix(sid, [ln for ln in report if ln["sid"] == sid])
    (MIXED / "list.txt").write_text("".join(f"file '{s}.mp4'\n" for s in sids), encoding="utf-8")
    dialog = MIXED / "dialog.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(MIXED / "list.txt"),
                    "-c", "copy", str(dialog)], check=True)
    total = sum(DUR.get(s, 12) for s in sids)
    if MUSIC.exists():
        add_music(dialog, HERE / "butterfly_draft.mp4", total)
    else:
        dialog.replace(HERE / "butterfly_draft.mp4")
    print("輸出：", HERE / "butterfly_draft.mp4")
