"""Demucs（htdemucs）把 H3 原生音軌拆成人聲／非人聲 → <名稱>_novocals.wav（音效＋環境聲，mux.py 用）、<名稱>_vocals.wav。

由 sfx.sh 在 demucs-sfx 映像檔（Dockerfile.sfx）裡呼叫：python /opt/sfx_sep.py S01_h3.wav ...
"""
import sys, numpy as np, torch
from scipy.io import wavfile
from demucs.pretrained import get_model
from demucs.apply import apply_model
m = get_model("htdemucs").cuda().eval()
for f in sys.argv[1:]:
    sr, x = wavfile.read(f)
    x = x.astype(np.float32) / (32768 if x.dtype == np.int16 else 1)
    if x.ndim == 1: x = np.stack([x, x], 1)
    wav = torch.tensor(x.T)[None].cuda()
    with torch.no_grad(): out = apply_model(m, wav, split=True)[0]
    vi = m.sources.index("vocals")
    rest = (out.sum(0) - out[vi]).cpu().numpy().T
    for name, y in (("novocals", rest), ("vocals", out[vi].cpu().numpy().T)):
        wavfile.write(f.replace("_h3.wav", "_" + name + ".wav"), sr, (np.clip(y, -1, 1) * 32767).astype(np.int16))
    print("done", f, flush=True)
