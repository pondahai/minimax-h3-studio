"""依 mux.py 實際排定的台詞時間產生繁體中文字幕 butterfly.srt，並另存壓字幕版 butterfly_sub.mp4（原片不動）。

用法：python3 subs.py [來源影片，預設 butterfly_draft.mp4]
片尾標語（漫畫頁尾）以字幕呈現，不畫進影片。
"""
import json, subprocess, sys
from pathlib import Path

from mux import AUDIO, DUR, HERE, VIDEO, schedule

SPEAKER = {"小明": "小明", "小美": "小美", "毛毛蟲": "毛毛蟲", "蝴蝶": "蝴蝶"}  # 旁白不標名字
TAGLINE = "觀察・尊重・守護"


def ts(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def cues():
    report = json.loads((AUDIO / "lines.json").read_text(encoding="utf-8"))
    offset, out = 0.0, []
    for sid in sorted(p.stem for p in VIDEO.glob("S*.mp4")):
        seg = DUR.get(sid, 12)
        for ln, t, tempo in schedule([l for l in report if l["sid"] == sid], seg):
            end = min(t + ln["audio_sec"] / tempo, seg)
            who = SPEAKER.get(ln["who"])
            text = ln["text"].rstrip("，")
            out.append((offset + t, offset + end, f"{who}：{text}" if who else text))
        offset += seg
    # 標語放畫面上方（{\an8}），從倒數第二句講完顯示到片尾，與底部最後一句旁白並存
    out.append((out[-2][1] + 0.2, offset, "{\\an8}" + TAGLINE))
    return sorted(out)


if __name__ == "__main__":
    src = HERE / (sys.argv[1] if len(sys.argv) > 1 else "butterfly_draft.mp4")
    srt = HERE / "butterfly.srt"
    srt.write_text("".join(f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(cues(), 1)), encoding="utf-8")
    style = "FontName=Noto Sans CJK TC,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=14"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", f"subtitles={srt.name}:force_style='{style}'",
                    "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "copy", str(HERE / "butterfly_sub.mp4")],
                   check=True, cwd=HERE)
    print("字幕：", srt, "\n壓字幕版：", HERE / "butterfly_sub.mp4")
