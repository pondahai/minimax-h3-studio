"""用常駐的 Breeze ASR（100.108.74.45:8013）轉寫 wav，核對 TTS 有沒有講對。

用法：python asr_check.py <篇目> [wav...]   （不帶 wav = 核對 <篇目>/audio/lines.json 全部台詞）
"""
import json, time, urllib.request, uuid
from pathlib import Path

import comic

BASE = "http://100.108.74.45:8013"


def transcribe(wav):
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nzh\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="format"\r\n\r\ntxt\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="clip.wav"\r\n'
            f'Content-Type: audio/wav\r\n\r\n').encode() + wav.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{BASE}/api/transcribe", body,
                                 {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        job = json.load(r)["job_id"]
    while True:
        with urllib.request.urlopen(f"{BASE}/api/jobs/{job}", timeout=30) as r:
            j = json.load(r)
        if j["status"] not in ("queued", "running"):
            return j["text"] if j["status"] == "done" else f"<{j['status']}>"
        time.sleep(1)


if __name__ == "__main__":
    cfg, d, wavs = comic.load()
    if wavs:
        for p in wavs:
            print(f"{Path(p).name}: {transcribe(Path(p))}", flush=True)
    else:
        for ln in json.loads((d / "audio" / "lines.json").read_text(encoding="utf-8")):
            print(f"{ln['file']}\n  原文：{ln['text']}\n  ASR ：{transcribe(d / 'audio' / ln['file'])}", flush=True)
