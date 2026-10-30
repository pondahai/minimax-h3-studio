"""把 <篇目>/video/SXX.mp4 配上 TTS 台詞（H3 原生音軌靜音），再串成 <篇目>/<篇目>_draft.mp4。

用法（Spark）：python3 mux.py <篇目>

台詞放在分鏡標的起秒；若前一句還沒講完就順延，講不完則用 atempo 加速（一般上限 1.35，段尾最後一句上限 1.5）。
每句先統一響度到 LINE_LUFS，避免某個角色的聲線偏小聲。
"""
import json, re, subprocess

import comic

BED_VOLUME = 0.0  # H3 原生音軌會自己編出非中文的說話聲，與 TTS 疊在一起，故不使用
SFX_VOLUME = 0.6  # 有 sfx/SXX_novocals.wav（Demucs 去掉人聲的原生音軌）就改用它當底，保留和畫面同步的音效
GAP = 0.15
MUSIC_FILE = "music/bgm.wav"  # 使用者選定的配樂（H3 生成的 12 秒片段）
LINE_LUFS = -20.0  # 每句台詞先量響度再拉到同一音量（林博士原本 -28.6 LUFS，比其他角色小聲）
MUSIC_CLIP, MUSIC_XFADE, MUSIC_VOLUME = 12.25, 1.5, 0.22


LIPSYNC = {}  # sfx/lipsync.json：{台詞檔名: [H3 開口, 閉口]}（lipsync_measure.py 產生）；有就把角色台詞對齊 H3 的嘴型
LIPSYNC_MIN = 0.3  # 開口差小於這個就不動


def start_of(ln):
    h3 = LIPSYNC.get(ln["file"])
    return h3[0] if h3 and abs(h3[0] - ln["start"]) > LIPSYNC_MIN else ln["start"]


def schedule(lines, seg_dur):
    plan, prev_end = [], 0.0
    for i, ln in enumerate(lines):
        t = max(start_of(ln), prev_end + GAP if plan else start_of(ln))
        last = i == len(lines) - 1
        limit = seg_dur if last else max(start_of(lines[i + 1]), t + 0.5)
        room = max(limit - t, 0.5)
        h3 = LIPSYNC.get(ln["file"])
        if h3:  # 盡量貼近 H3 那句的長度；加速仍受上限，講不完的尾巴在閉嘴後講完
            room = min(room, max(h3[1] - h3[0], 0.5))
        tempo = min(max(ln["audio_sec"] / room, 1.0), 1.5 if last else 1.35)
        prev_end = t + ln["audio_sec"] / tempo
        plan.append((ln, t, tempo))
    return plan


def gain_db(wav):
    """量 wav 的整體響度（LUFS），回傳拉到 LINE_LUFS 要加的 dB。"""
    log = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(wav), "-af", "loudnorm=print_format=summary", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return LINE_LUFS - float(re.search(r"Input Integrated:\s*(-?[\d.]+)", log)[1])


def mix(d, sid, seg_dur, lines):
    src = d / "video" / f"{sid}.mp4"
    dst = d / "mixed" / f"{sid}.mp4"
    plan = schedule(lines, seg_dur)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
    sfx = d / "sfx" / f"{sid}_novocals.wav"
    if sfx.exists():
        cmd += ["-i", str(sfx)]
        filters = [f"[1:a]aresample=48000,volume={SFX_VOLUME},apad[bed]"]
    else:
        filters = [f"[0:a]volume={BED_VOLUME},apad[bed]"]
    labels = ["[bed]"]
    first = 2 if sfx.exists() else 1
    for n, (ln, t, tempo) in enumerate(plan, start=first):
        wav = d / "audio" / ln["file"]
        cmd += ["-i", str(wav)]
        filters.append(f"[{n}:a]aresample=48000,volume={gain_db(wav):.1f}dB,alimiter=limit=0.95,atempo={tempo:.3f},adelay={int(t * 1000)}:all=1[v{n}]")
        labels.append(f"[v{n}]")
        print(f"  {ln['file']} @ {t:.2f}s x{tempo:.2f} → 結束 {t + ln['audio_sec'] / tempo:.2f}s")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,atrim=0:{seg_dur}[a]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", str(seg_dur), str(dst)]
    subprocess.run(cmd, check=True)


def add_music(src, music, dst, total):
    """把 12 秒配樂以交叉淡化循環到片長，壓低音量墊在台詞下，頭尾淡入淡出。"""
    copies = int(total // (MUSIC_CLIP - MUSIC_XFADE)) + 2
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)] + ["-i", str(music)] * copies
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
    cfg, d, _ = comic.load()
    MIXED = d / "mixed"
    MIXED.mkdir(exist_ok=True)
    dur = comic.durations(cfg)
    if (d / "sfx" / "lipsync.json").exists():
        LIPSYNC.update(json.loads((d / "sfx" / "lipsync.json").read_text(encoding="utf-8")))
        print(f"對齊 H3 嘴型：{len(LIPSYNC)} 句")
    report = json.loads((d / "audio" / "lines.json").read_text(encoding="utf-8"))
    sids = list(dur)
    for sid in sids:
        print(sid)
        mix(d, sid, dur[sid], [ln for ln in report if ln["sid"] == sid])
    (MIXED / "list.txt").write_text("".join(f"file '{s}.mp4'\n" for s in sids), encoding="utf-8")
    dialog = MIXED / "dialog.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(MIXED / "list.txt"),
                    "-c", "copy", str(dialog)], check=True)
    total = sum(dur.values())
    out = d / f"{cfg['id']}_draft.mp4"
    if (d / MUSIC_FILE).exists():
        add_music(dialog, d / MUSIC_FILE, out, total)
    else:
        dialog.replace(out)
    print("輸出：", out)
