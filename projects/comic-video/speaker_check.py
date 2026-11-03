"""8002 看每句台詞時段的畫面，判斷是誰在開口，跟分鏡指定的說話者比對（H3 常讓同框的別人開口）。
用法：python speaker_check.py <篇目> <lipsync.json> [段...]
lipsync.json 沒有的句子（H3 沒生成人聲）一律標出來。lipsync.json 是 Spark 上 <篇目>/sfx/lipsync.json（每句台詞在影片裡的開口時段）；影片讀 <篇目>/mixed/SXX.mp4。
每句抽 4 格原尺寸拼成 2×2，8002 回答開口的是誰；不一致或看不出來的列出來給人聽。"""
import base64, json, re, subprocess, sys, tempfile, urllib.request
from pathlib import Path
import imageio_ffmpeg
import comic

URL = "http://100.89.149.50:8002/v1/chat/completions"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
SYS = """You see 4 frames in a 2x2 grid (read left to right, top to bottom) from one moment of an anime video where exactly one character is saying a line.
Characters who may appear:
{cast}
For each character visible, look closely at the mouth in every frame: a speaking character's mouth changes between open and
closed shapes across the frames; a listening character's mouth stays closed or fixed in one smile.
Only list characters actually visible. Reply with JSON only, no code fence: {{"mouths": {{"<name>": "<under 10 words: mouth across the 4 frames>"}}, "speaker": "<name of the one character talking, or unclear>"}}"""


def frames(video, start, end):
    """開口時段內平均抽 4 格，拼成 2×2 一張 PNG。"""
    with tempfile.TemporaryDirectory() as tmp:
        ts = [start + (end - start) * (i + 0.5) / 4 for i in range(4)]
        for i, t in enumerate(ts):
            subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                            f"{tmp}/{i}.png"], check=True)
        out = f"{tmp}/tile.png"
        subprocess.run([FFMPEG, "-v", "error", "-y"] + sum([["-i", f"{tmp}/{i}.png"] for i in range(4)], []) +
                       ["-filter_complex", "[0][1]hstack[a];[2][3]hstack[b];[a][b]vstack", out], check=True)
        return Path(out).read_bytes()


def ask(cfg, png):
    cast = "\n".join(f"- {n}: {look}" for n, look in cfg["looks_en"].items())
    body = {"messages": [{"role": "system", "content": SYS.format(cast=cast)},
                         {"role": "user", "content": [{"type": "image_url", "image_url": {
                             "url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}],
            "temperature": 0.1, "max_tokens": 1200, "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        text = json.load(r)["choices"][0]["message"]["content"]
    try:
        return json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip()).strip())
    except ValueError:
        return {"speaker": "unclear", "mouths": {"raw": text[:300]}}


if __name__ == "__main__":
    cfg, d, rest = comic.load()
    spans = json.loads(Path(rest[0]).read_text(encoding="utf-8"))
    only = rest[1:]
    lines = json.loads((d / "audio" / "lines.json").read_text(encoding="utf-8"))
    bad = []
    for ln in lines:
        if (only and ln["sid"] not in only) or ln["who"] == "旁白":
            continue
        want = cfg["names_en"].get(ln["who"], ln["who"])
        # lipsync.json 沒有的句子是 H3 在那個時段沒生成人聲，mux 只能貼在分鏡時段開頭，多半對不上嘴（第二集 S08 八戒）
        silent = ln["file"] not in spans
        start, end = (ln["start"], ln["end"]) if silent else spans[ln["file"]]
        ans = ask(cfg, frames(d / "mixed" / f"{ln['sid']}.mp4", start, end))
        got = ans.get("speaker", "unclear")
        ok = got.lower() == want.lower() and not silent
        note = "（H3 沒生成人聲，用分鏡時段）" if silent else ""
        print(f"{'OK ' if ok else '?? '} {ln['file']} {start:.1f}–{end:.1f}s 應為 {want}，8002 看到 {got}{note}", flush=True)
        if not ok:
            print(f"     {json.dumps(ans.get('mouths', {}), ensure_ascii=False)}", flush=True)
            bad.append(ln["file"])
    print(f"\n要人聽：{len(bad)} 句" + ("".join(f"\n  {b}" for b in bad)))
