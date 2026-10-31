"""把每句 TTS 用 DTW 對齊 H3 自己唸的那句（sfx/SXX_vocals.wav），算出時間對照錨點，寫 sfx/align.json。

用法（Spark，demucs-sfx 容器，要 librosa；pipeline.sh 會自動跑）：python align_dtw.py <篇目> [段落...]
H3 的嘴是照它自己唸的聲音動的，TTS 頭尾對上了，句子中間的節奏仍會錯開；
這裡兩邊抽 MFCC（各自做 CMVN，抵消不同聲線）跑 DTW，每 ANCHOR 秒取一個錨點 [TTS 秒, 影片秒]，
mux.py 再依錨點逐段用 atempo 變速，讓 TTS 的每個音節落在 H3 開口的位置。
需要 sfx/lipsync.json（H3 每句開口、閉口）。
"""
import json

import librosa
import numpy as np

import comic

SR, HOP = 16000, 160
PAD = 0.3  # H3 那句前後多取一點，避免開口量測切掉字頭字尾
ANCHOR = 0.25
RATIO = (0.6, 1.8)  # 每段 TTS 時長／影片時長的上下限，超過就壓回來，避免怪聲


def feats(y):
    m = librosa.feature.mfcc(y=y, sr=SR, n_mfcc=20, hop_length=HOP)[1:]
    return (m - m.mean(1, keepdims=True)) / (m.std(1, keepdims=True) + 1e-6)


def anchors(tts, h3, h3_t0):
    """錨點的 TTS 秒是原 wav 的時間（含開頭靜音），mux 會切掉第一個錨點之前和最後一個之後。"""
    tts, (ta, _) = librosa.effects.trim(tts, top_db=35)
    h3, (a, b) = librosa.effects.trim(h3, top_db=30)
    t0, off = h3_t0 + a / SR, ta / SR
    _, wp = librosa.sequence.dtw(feats(tts), feats(h3), metric="cosine")
    wp = wp[::-1]
    n = feats(tts).shape[1]
    map_ = np.zeros(n)
    for i in range(n):
        map_[i] = np.median(wp[wp[:, 0] == i, 1])
    tts_len, h3_len = len(tts) / SR, (b - a) / SR
    pts = [(0.0, t0)]
    for s in np.arange(ANCHOR, tts_len - ANCHOR / 2, ANCHOR):
        pts.append((s, t0 + map_[min(int(s * SR / HOP), n - 1)] * HOP / SR))
    pts.append((tts_len, t0 + h3_len))
    out = [pts[0]]  # 單調＋限制每段變速比
    for s, v in pts[1:]:
        ps, pv = out[-1]
        ds = s - ps
        v = min(max(v, pv + ds / RATIO[1]), pv + ds / RATIO[0])
        out.append((s, v))
    return [(round(s + off, 3), round(v, 3)) for s, v in out]


if __name__ == "__main__":
    cfg, d, only = comic.load()
    lips = json.loads((d / "sfx" / "lipsync.json").read_text(encoding="utf-8"))
    lines = json.loads((d / "audio" / "lines.json").read_text(encoding="utf-8"))
    path = d / "sfx" / "align.json"
    result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    vocals = {}
    for ln in lines:
        if (only and ln["sid"] not in only) or ln["file"] not in lips:
            continue
        sid = ln["sid"]
        if sid not in vocals:
            vocals[sid] = librosa.load(d / "sfx" / f"{sid}_vocals.wav", sr=SR)[0]
        s, e = lips[ln["file"]]
        s0, e0 = max(s - PAD, 0), e + PAD
        h3 = vocals[sid][int(s0 * SR):int(e0 * SR)]
        tts = librosa.load(d / "audio" / ln["file"], sr=SR)[0]
        result[ln["file"]] = anchors(tts, h3, s0)
        a = result[ln["file"]]
        print(f"{ln['file']}: TTS {a[-1][0]:.2f}s → 影片 {a[0][1]:.2f}–{a[-1][1]:.2f}s，{len(a)} 個錨點", flush=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
