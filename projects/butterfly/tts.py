"""從 storyboard.md 取出台詞，用 Spark VoxCPM2 TTS 配音，輸出 audio/SXX_<起秒>_<角色>.wav。

每個角色先以 voice design 生成一段參考音（audio/ref_<角色>.wav），之後每句以 reference 克隆，保持音色一致。
"""
import json, re, sys, urllib.request, uuid
from pathlib import Path

HERE = Path(__file__).parent
BASE = "http://100.89.149.50:8792"
VOICES = {
    "小明": "活潑開朗的十歲男孩，聲音清亮",
    "小美": "開朗溫柔的十歲女孩，聲音甜美",
    "旁白": "溫柔親切的年輕女性旁白，語速平穩",
    "毛毛蟲": "可愛圓潤的卡通小動物聲音，有點貪吃",
    "蝴蝶": "輕快優雅的卡通小精靈聲音",
}
REF_TEXT = "大家好，今天天氣真好，我們一起去森林裡看看吧！"


def post_json(payload):
    req = urllib.request.Request(f"{BASE}/api/tts", json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def post_multipart(fields, wav):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="voice_sample"; filename="ref.wav"\r\n'
                 f'Content-Type: audio/wav\r\n\r\n'.encode() + wav.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"{BASE}/api/tts", b"".join(parts),
                                 {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def fetch(url, dest):
    with urllib.request.urlopen(BASE + urllib.parse.quote(url), timeout=120) as r:
        dest.write_bytes(r.read())


def lines():
    text = (HERE / "storyboard.md").read_text(encoding="utf-8")
    sid = None
    for row in text.splitlines():
        if m := re.match(r"### (S\d+)", row):
            sid = m.group(1)
        if sid and (m := re.match(r"^\| (\d+)–(\d+) \|.*\| (\S+?)：「(.+?)」 \|$", row)):
            start, end, who, said = int(m[1]), int(m[2]), m[3], m[4]
            if who in VOICES:
                yield sid, start, end, who, said


if __name__ == "__main__":
    import urllib.parse
    out = HERE / "audio"
    out.mkdir(exist_ok=True)
    report = []
    for who, desc in VOICES.items():
        ref = out / f"ref_{who}.wav"
        if not ref.exists():
            r = post_json({"text": REF_TEXT, "voice": desc, "stable_voice": True})
            fetch(r["url"], ref)
            print(f"ref {who}: {r['audio_sec']}s", flush=True)
    for sid, start, end, who, said in lines():
        dest = out / f"{sid}_{start:02d}_{who}.wav"
        r = post_multipart({"text": said, "clone_mode": "reference", "stable_voice": "true"}, out / f"ref_{who}.wav")
        fetch(r["url"], dest)
        slot = end - start
        flag = "" if r["audio_sec"] <= slot + 0.3 else "  <-- 超出時段"
        print(f"{dest.name}: {r['audio_sec']:.1f}s / 時段 {slot}s{flag}", flush=True)
        report.append({"file": dest.name, "sid": sid, "start": start, "end": end, "who": who,
                       "text": said, "audio_sec": r["audio_sec"]})
    (out / "lines.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
