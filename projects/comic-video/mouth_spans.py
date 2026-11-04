"""H3 沒生成人聲的台詞（lipsync.json 量不到開口時段）：本地 LLM（comic.LLM_URL，預設 8006）在分鏡時段內每 0.25 秒看一格，判斷說話者嘴巴開不開，
找出開口時段，印出可貼進 config lipsync_manual 的 JSON（mux.py 會照這個時段放台詞）。
用法：python mouth_spans.py <篇目> <台詞檔名>...   例：python mouth_spans.py journey02 S08_08_八戒.wav"""
import base64, json, subprocess, sys, tempfile, urllib.request
from pathlib import Path
import imageio_ffmpeg
import comic

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
STEP = 0.25


def frame(video, t):
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", f"{tmp}/f.png"], check=True)
        return Path(f"{tmp}/f.png").read_bytes()


def is_open(name, look, png):
    body = {"messages": [{"role": "system", "content":
                          f"Look at {name} ({look}) in this anime frame. Is {name}'s mouth (or beak) open, as when talking? "
                          "Answer with one word: open, closed, or hidden (not visible)."},
                         {"role": "user", "content": [{"type": "image_url", "image_url": {
                             "url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}],
            "temperature": 0, "max_tokens": 5, "chat_template_kwargs": {"enable_thinking": False}}
    return comic.llm(body, timeout=120).strip().lower()


def span(ts, marks, need):
    """把開口格連成時段（中間閉一格不算斷）；取最長的一段，太短就以中心往兩邊補到台詞長度。"""
    runs = []
    for t, m in zip(ts, marks):
        if m.startswith("open"):
            if runs and t - runs[-1][1] <= STEP + 1e-6:
                runs[-1][1] = t + STEP
            else:
                runs.append([t, t + STEP])
    if not runs:
        return None
    s, e = max(runs, key=lambda r: r[1] - r[0])
    if e - s < need:
        mid = (s + e) / 2
        s, e = mid - need / 2, mid + need / 2
    return [round(s, 2), round(e, 2)]


if __name__ == "__main__":
    cfg, d, files = comic.load()
    lines = {l["file"]: l for l in json.loads((d / "audio" / "lines.json").read_text(encoding="utf-8"))}
    out = {}
    for f in files:
        ln = lines[f]
        name = cfg["names_en"].get(ln["who"], ln["who"])
        video = d / "mixed" / f"{ln['sid']}.mp4"
        ts = [ln["start"] + i * STEP for i in range(int((ln["end"] - ln["start"]) / STEP))]
        marks = [is_open(name, cfg["looks_en"][name], frame(video, t)) for t in ts]
        print(f"{f}：" + " ".join(f"{t:.2f}{'●' if m.startswith('open') else '·' if m.startswith('closed') else '?'}" for t, m in zip(ts, marks)), flush=True)
        if sp := span(ts, marks, ln["audio_sec"]):
            sp = [max(sp[0], ln["start"]), min(sp[1], ln["end"])]
            out[f] = sp
            print(f"  → {sp[0]}–{sp[1]}s（台詞 {ln['audio_sec']}s）", flush=True)
        else:
            print("  → 找不到開口，要人看", flush=True)
    print(json.dumps(out, ensure_ascii=False))
