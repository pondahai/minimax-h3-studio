"""從 storyboard.md 取出台詞，用 Spark VoxCPM2 TTS 配音，輸出 audio/SXX_<起秒>_<角色>.wav。

每個角色先以 voice design 生成一段參考音（audio/ref_<角色>.wav），之後每句以 prompt 模式克隆（reference 模式在短句上容易唸出非中文），保持音色一致。
"""
import json, re, sys, urllib.request, uuid
from pathlib import Path

HERE = Path(__file__).parent
BASE = "http://100.89.149.50:8792"
VOICES = {
    "小明": "七歲小男孩，稚嫩的童聲，音調很高，天真活潑",
    "小美": "開朗溫柔的十歲女孩，聲音甜美",
    "旁白": "溫柔親切的年輕女性旁白，語速平穩",
    "毛毛蟲": "可愛圓潤的卡通小動物聲音，有點貪吃",
    "蝴蝶": "輕快優雅的卡通小精靈聲音",
}
REF_TEXT = "大家好，今天天氣真好，我們一起去森林裡看看吧！"
# 參考音的逐字稿（prompt 模式克隆需要）；小明的參考音是使用者從候選挑的那句
REF_TRANSCRIPT = {"小明": "哇！一隻小小的卵，竟然可以變成這麼美麗的蝴蝶！"}


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
    only = set(sys.argv[1:])  # 可只重配指定角色，例如 python tts.py 小明
    lines_path = out / "lines.json"
    report = [ln for ln in json.loads(lines_path.read_text(encoding="utf-8")) if ln["who"] not in only] if only else []
    for who, desc in VOICES.items():
        ref = out / f"ref_{who}.wav"
        if not ref.exists():
            r = post_json({"text": REF_TEXT, "voice": desc, "stable_voice": True})
            fetch(r["url"], ref)
            print(f"ref {who}: {r['audio_sec']}s", flush=True)
    for sid, start, end, who, said in lines():
        if only and who not in only:
            continue
        dest = out / f"{sid}_{start:02d}_{who}.wav"
        r = post_multipart({"text": said, "prompt_text": REF_TRANSCRIPT.get(who, REF_TEXT), "clone_mode": "prompt",
                            "stable_voice": "false"}, out / f"ref_{who}.wav")
        fetch(r["url"], dest)
        slot = end - start
        flag = "" if r["audio_sec"] <= slot + 0.3 else "  <-- 超出時段"
        print(f"{dest.name}: {r['audio_sec']:.1f}s / 時段 {slot}s{flag}", flush=True)
        report.append({"file": dest.name, "sid": sid, "start": start, "end": end, "who": who,
                       "text": said, "audio_sec": r["audio_sec"]})
    report.sort(key=lambda ln: (ln["sid"], ln["start"]))
    lines_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
