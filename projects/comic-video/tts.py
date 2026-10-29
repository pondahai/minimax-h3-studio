"""從 <篇目>/storyboard.md 取出台詞，用 Spark VoxCPM2 TTS 配音，輸出 <篇目>/audio/SXX_<起秒>_<角色>.wav。

用法：python tts.py <篇目> [角色...]   （帶角色 = 只重配那些角色）
每個角色要有參考音 audio/ref_<角色>.wav（使用者從候選挑的；沒有才用 config 的 voice design 生成），
每句以 prompt 模式克隆（reference 模式在短句上容易唸出非中文），保持音色一致。
"""
import json, re, urllib.parse, urllib.request, uuid

import comic

BASE = "http://100.89.149.50:8792"


def make_speakable(cfg):
    """原稿、字幕與 lines.json 保留繁體；只有送 TTS 的文字要處理。
    t2s：轉簡體（VoxCPM2 對繁體字常唸錯，例：繁體「湯匙」唸不出來，簡體「汤匙」正常）。
    pronounce：轉簡體後仍唸錯的多音字，換成同音字（VoxCPM2 不支援拼音標註）。"""
    convert = lambda t: t
    if cfg.get("t2s"):
        import opencc
        convert = opencc.OpenCC("t2s").convert

    def speakable(text):
        text = convert(text)
        for a, b in cfg.get("pronounce", {}).items():
            text = text.replace(a, b)
        return text
    return speakable


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


def clone(cfg, who, text, ref):
    """用參考音克隆一句台詞（prompt 模式，prompt_text 是參考音的逐字稿）。"""
    return post_multipart({"text": make_speakable(cfg)(text),
                           "prompt_text": cfg["ref_transcript"].get(who, cfg["ref_text"]),
                           "clone_mode": "prompt", "stable_voice": "false"}, ref)


def lines(cfg, d):
    text = (d / "storyboard.md").read_text(encoding="utf-8")
    sid = None
    for row in text.splitlines():
        if m := re.match(r"### (S\d+)", row):
            sid = m.group(1)
        if sid and (m := re.match(r"^\| (\d+)–(\d+) \|.*\| (\S+?)：「(.+?)」 \|$", row)):
            start, end, who, said = int(m[1]), int(m[2]), m[3], m[4]
            if who in cfg["voices"]:
                yield sid, start, end, who, said


if __name__ == "__main__":
    cfg, d, only = comic.load()
    only = set(only)
    out = d / "audio"
    out.mkdir(exist_ok=True)
    lines_path = out / "lines.json"
    report = [ln for ln in json.loads(lines_path.read_text(encoding="utf-8")) if ln["who"] not in only] if only else []
    for who, desc in cfg["voices"].items():
        ref = out / f"ref_{who}.wav"
        if not ref.exists():
            r = post_json({"text": cfg["ref_text"], "voice": desc, "stable_voice": True})
            fetch(r["url"], ref)
            print(f"ref {who}: {r['audio_sec']}s", flush=True)
    for sid, start, end, who, said in lines(cfg, d):
        if only and who not in only:
            continue
        dest = out / f"{sid}_{start:02d}_{who}.wav"
        r = clone(cfg, who, said, out / f"ref_{who}.wav")
        fetch(r["url"], dest)
        slot = end - start
        flag = "" if r["audio_sec"] <= slot + 0.3 else "  <-- 超出時段"
        print(f"{dest.name}: {r['audio_sec']:.1f}s / 時段 {slot}s{flag}", flush=True)
        report.append({"file": dest.name, "sid": sid, "start": start, "end": end, "who": who,
                       "text": said, "audio_sec": r["audio_sec"]})
    report.sort(key=lambda ln: (ln["sid"], ln["start"]))
    lines_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
