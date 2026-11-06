"""量 H3 角色實際開口時間（sfx/SXX_vocals.wav 的有聲區段），和 mux.py 排的 TTS 時間對照；
結果寫進 <篇目>/sfx/lipsync.json（{台詞檔名: [H3 開口, H3 閉口]}，旁白不列），mux.py 用來對齊台詞起點。

用法（Spark，demucs-sfx 映像檔裡有 numpy/scipy；mux.py 在主機跑、沒有 numpy，所以分開）：
  docker run --rm -v $PWD:/c -w /c --entrypoint python demucs-sfx lipsync_measure.py <篇目> [段...]
對照用的是不對齊時的排法（LIPSYNC=0），才不會被上一次的對齊結果影響。
"""
import json, sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).parent))
import mux

FRAME, THRESH_DB, MERGE, MIN_LEN = 0.02, -30, 0.35, 0.25
MAX_SPEEDUP = 1.25  # TTS 塞進 H3 區段最多加速這麼多，超過就不對齊、照分鏡時間播
MAX_SHIFT = 1.5  # H3 開口離分鏡起秒超過這麼多秒就不採用


def voiced(wav):
    """回傳 [(起, 迄)]：RMS 高於該軌峰值 THRESH_DB 的區段，間隔 < MERGE 合併、短於 MIN_LEN 丟掉。"""
    sr, x = wavfile.read(wav)
    x = x.astype(np.float32)
    if x.ndim > 1:
        x = x.mean(1)
    n = int(sr * FRAME)
    rms = np.sqrt(np.mean(x[: len(x) // n * n].reshape(-1, n) ** 2, 1)) + 1e-9
    db = 20 * np.log10(rms / rms.max())
    on = db > THRESH_DB
    segs, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        if not v and start is not None:
            segs.append([start * FRAME, i * FRAME]); start = None
    if start is not None:
        segs.append([start * FRAME, len(on) * FRAME])
    merged = []
    for s in segs:
        if merged and s[0] - merged[-1][1] < MERGE:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [s for s in merged if s[1] - s[0] >= MIN_LEN]


if __name__ == "__main__":
    name, sids = sys.argv[1], sys.argv[2:]
    d = Path(name)
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    lines = json.loads((d / "audio" / "lines.json").read_text(encoding="utf-8"))
    dur = {s: t for s, t, _ in cfg["shots"]}
    mux.LIPSYNC = {}
    out = d / "sfx" / "lipsync.json"
    found = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    for sid in sids or list(dur):
        v = voiced(d / "sfx" / f"{sid}_vocals.wav")
        print(f"== {sid}  H3 有聲區段：" + "、".join(f"{a:.2f}–{b:.2f}" for a, b in v))
        plan = mux.schedule([l for l in lines if l["sid"] == sid], dur[sid])
        # H3 常把一句拆成幾口氣、或把連續幾句講成一口氣：每個有聲區段分給和它重疊超過 0.3 秒的句子，
        # 只重疊一句就整段給它，重疊多句就按 TTS 長度比例切開；每句的 H3 區間 = 分到的片段頭到尾
        picks = []
        for ln, t, tempo in plan:
            picks.append((ln, t, t + ln["audio_sec"] / tempo, ln["file"].split("_")[2].split(".")[0]))
        talk = [p for p in picks if p[3] != "旁白"]
        win = {}
        for a, b in v:
            hit = [p for p in talk if min(b, p[2]) - max(a, p[1]) > 0.3]
            if not hit:  # 沒重疊夠的，給最近且在 1 秒內的那句
                near = min(talk, key=lambda p: max(p[1] - b, a - p[2]), default=None)
                hit = [near] if near and max(near[1] - b, a - near[2]) < 1.0 else []
            tot = sum(p[0]["audio_sec"] for p in hit)
            for p in hit:
                w = (b - a) * p[0]["audio_sec"] / tot
                s0, e0 = win.get(p[0]["file"], (a, a + w))
                win[p[0]["file"]] = (min(s0, a), a + w)
                a += w
        picks = [(ln, t, end, who, None) for ln, t, end, who in picks]
        prev = 0.0
        for ln, t, end, who, best in picks:
            found.pop(ln["file"], None)
            if who == "旁白":
                print(f"  {who:4} TTS {t:5.2f}–{end:5.2f}（旁白，畫面閉嘴）")
                prev = end
                continue
            w = win.get(ln["file"])
            why = ("H3 找不到對應區段" if w is None else
                   f"H3 {w[0]:.2f}–{w[1]:.2f} 早於上一句結束 {prev:.2f}" if w[0] < prev - 0.05 else
                   f"H3 {w[0]:.2f}–{w[1]:.2f} 太短，要加速 {ln['audio_sec'] / (w[1] - w[0]):.2f} 倍" if ln["audio_sec"] / (w[1] - w[0]) > MAX_SPEEDUP else
                   f"H3 {w[0]:.2f} 離分鏡 {ln['start']} 秒太遠" if abs(w[0] - ln["start"]) > MAX_SHIFT else None)
            if why:
                print(f"  {who:4} TTS {t:5.2f}–{end:5.2f}  不對齊（{why}），照分鏡時間")
                prev = end
                continue
            found[ln["file"]] = [round(w[0], 2), round(w[1], 2)]
            prev = max(w[1], w[0] + ln["audio_sec"] / MAX_SPEEDUP)
            print(f"  {who:4} TTS {t:5.2f}–{end:5.2f}  H3 {w[0]:5.2f}–{w[1]:5.2f}  "
                  f"開口差 {t - w[0]:+.2f}s  長度 TTS {ln['audio_sec']:.2f} / H3 {w[1] - w[0]:.2f}")
    out.write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    print("寫入", out)
