"""依 mux.py 實際排定的台詞時間產生繁體中文字幕 <篇目>.srt，並另存壓字幕版 <篇目>_sub.mp4（原片不動）。

用法（Spark）：python3 subs.py <篇目> [來源影片，預設 <篇目>_draft.mp4]
config 的 speakers 是字幕要標名字的角色（旁白不標）；tagline（漫畫頁尾標語）以字幕呈現，不畫進影片。
"""
import json, subprocess

import comic
from mux import schedule


def ts(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def cues(cfg, d):
    report = json.loads((d / "audio" / "lines.json").read_text(encoding="utf-8"))
    offset, out = 0.0, []
    for sid, seg in comic.durations(cfg).items():
        for ln, t, tempo in schedule([l for l in report if l["sid"] == sid], seg):
            end = min(t + ln["audio_sec"] / tempo, seg)
            who = ln["who"] if ln["who"] in cfg["speakers"] else None
            text = ln["text"].rstrip("，")
            out.append((offset + t, offset + end, f"{who}：{text}" if who else text))
        offset += seg
    # 標語放畫面上方（{\an8}），從倒數第二句講完顯示到片尾，與底部最後一句旁白並存
    if cfg.get("tagline"):
        out.append((out[-2][1] + 0.2, offset, "{\\an8}" + cfg["tagline"]))
    return sorted(out)


if __name__ == "__main__":
    cfg, d, args = comic.load()
    src = d / (args[0] if args else f"{cfg['id']}_draft.mp4")
    srt = d / f"{cfg['id']}.srt"
    sub = d / f"{cfg['id']}_sub.mp4"
    srt.write_text("".join(f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(cues(cfg, d), 1)), encoding="utf-8")
    style = "FontName=Noto Sans CJK TC,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=14"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", f"subtitles={srt.name}:force_style='{style}'",
                    "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "copy", str(sub)],
                   check=True, cwd=d)
    print("字幕：", srt, "\n壓字幕版：", sub)
