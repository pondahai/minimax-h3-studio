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
        for ln, t, tempo in mux.schedule([l for l in lines if l["sid"] == sid], dur[sid]):
            end = t + ln["audio_sec"] / tempo
            who = ln["file"].split("_")[2].split(".")[0]
            # 和 TTS 重疊最多的 H3 區段
            best = max(v, key=lambda s: min(s[1], end) - max(s[0], t), default=None)
            if who == "旁白":
                print(f"  {who:4} TTS {t:5.2f}–{end:5.2f}（旁白，畫面閉嘴）")
            elif best and min(best[1], end) > max(best[0], t) - 1.0:
                found[ln["file"]] = [round(best[0], 2), round(best[1], 2)]
                print(f"  {who:4} TTS {t:5.2f}–{end:5.2f}  H3 {best[0]:5.2f}–{best[1]:5.2f}  "
                      f"開口差 {t - best[0]:+.2f}s  長度 TTS {end - t:.2f} / H3 {best[1] - best[0]:.2f}")
            else:
                print(f"  {who:4} TTS {t:5.2f}–{end:5.2f}  H3 找不到對應區段")
    out.write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    print("寫入", out)
