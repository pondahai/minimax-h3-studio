"""Demucs（htdemucs）把 H3 原生音軌拆成人聲／非人聲 → <名稱>_novocals.wav（音效＋環境聲，mux.py 用）、<名稱>_vocals.wav。

在 Spark 的 nvcr.io/nvidia/pytorch 容器裡跑（容器沒有 torchaudio、ARM 裝不了 demucs 4.1 的 sphn，所以不用 demucs 的命令列）：
  docker run --rm --gpus all --ipc=host -v $PWD/sfx:/w -v ~/.cache/torch:/root/.cache/torch -e PYTHONPATH=/w/stub nvcr.io/nvidia/pytorch:25.11-py3 \n    sh -c "pip install -q --no-deps demucs==4.0.1 dora-search julius lameenc openunmix einops omegaconf antlr4-python3-runtime==4.9.3 treetable retrying submitit cloudpickle; cd /w && python sfx_sep.py S01_h3.wav ..."
/w/stub/torchaudio/__init__.py 是空檔：openunmix 會 import torchaudio，分離用不到。
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
