"""產出分鏡審查頁 <篇目>/review.html：每段首幀候選（標建議 seed 與理由）＋時間軸、鏡頭、台詞。

用法：python review.py <篇目>
圖片內嵌成 base64 JPEG（672 寬），單獨傳 review.html 也看得到圖。
首幀段＝config shots 第三欄是圖檔的段，候選為 frames/<名稱>_seedN.png；建議與理由寫在 <篇目>/review.json（{"rec": {段: seed}, "notes": {段: 理由}}）。
"""
import base64, html, io, json, re
from pathlib import Path

import comic
from PIL import Image

CSS = """:root{--bg:#fafaf7;--fg:#222;--mut:#666;--line:#ddd;--acc:#2f7d4f;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#16181a;--fg:#e8e8e8;--mut:#9aa;--line:#333;--acc:#5fc28a;--card:#1e2124}}
body{background:var(--bg);color:var(--fg);font-family:"Noto Sans TC",system-ui,sans-serif;margin:0;padding:24px 16px;line-height:1.6}
main{max-width:1100px;margin:auto} h1{font-size:1.6rem;margin:0 0 4px} .sub{color:var(--mut);margin:0 0 24px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:20px}
h2{font-size:1.15rem;margin:0 0 12px} .frames{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
figure{margin:0;border:3px solid transparent;border-radius:6px;overflow:hidden} figure.rec{border-color:var(--acc)}
img{width:100%;display:block} figcaption{font-size:.8rem;text-align:center;color:var(--mut);padding:2px}
.rec figcaption{color:var(--acc);font-weight:700} .note{font-size:.9rem;color:var(--mut)} .cont{color:var(--acc);font-weight:600}
table{width:100%;border-collapse:collapse;font-size:.92rem;margin-top:8px} th,td{border-top:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}
.t{white-space:nowrap;font-variant-numeric:tabular-nums} .cam{color:var(--mut);white-space:nowrap}
@media (max-width:640px){.frames{grid-template-columns:1fr} .cam{white-space:normal}}"""


def embed(p):
    im = Image.open(p).convert("RGB")
    im.thumbnail((672, 672))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def section(d, block, src, rec, note):
    head = block.splitlines()[0][4:]
    sid = head.split()[0]
    rows = re.findall(r"^\| (\d+–\d+) \| (.+?) \| (.+?) \| (.+?) \|$", block, re.M)
    if src == "-":
        frame = '<p class="cont">無首幀：H3 直接生成（t2va）</p>'
    elif src.endswith(".png"):
        stem = Path(src).stem
        seeds = sorted(d.glob(f"frames/{stem}_seed*.png"))
        figs = "".join(f'<figure class="{"rec" if p.stem.endswith(f"seed{rec}") else ""}"><img src="{embed(p)}" loading="lazy">'
                       f'<figcaption>{p.stem.rsplit("_", 1)[1]}{" ★ 建議" if p.stem.endswith(f"seed{rec}") else ""}</figcaption></figure>'
                       for p in seeds)
        frame = f'<div class="frames">{figs}</div>' + (f'<p class="note">審查備註：{html.escape(note)}</p>' if note else "")
    else:
        frame = f'<p class="cont">⟶ 續接段：首幀＝{src} 影片的最後一格（H3 生成後才會有圖）</p>'
    trs = "".join(f'<tr><td class="t">{a}s</td><td>{html.escape(c)}</td><td class="cam">{html.escape(m)}</td><td>{html.escape(v)}</td></tr>'
                  for a, c, m, v in rows)
    return (f'<section><h2>{html.escape(head)}</h2>{frame}<table><thead><tr><th>秒</th><th>畫面／動作</th><th>鏡頭</th>'
            f'<th>聲音</th></tr></thead><tbody>{trs}</tbody></table></section>')


if __name__ == "__main__":
    cfg, d, _ = comic.load()
    rv = json.loads((d / "review.json").read_text(encoding="utf-8")) if (d / "review.json").exists() else {}
    src = {sid: s for sid, _, s in cfg["shots"]}
    blocks = [b.split("\n**總長")[0] for b in re.split(r"\n(?=### S\d+[A-Z]?)", (d / "storyboard.md").read_text(encoding="utf-8"))[1:]]
    body = "".join(section(d, b, src[b[4:7]], rv.get("rec", {}).get(b[4:7]), rv.get("notes", {}).get(b[4:7])) for b in blocks)
    n_frame = sum(s.endswith(".png") for s in src.values())
    n_cont = sum(s in src for s in src.values())
    total = sum(comic.durations(cfg).values())
    page = (f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(cfg["id"])} 分鏡審查</title><style>{CSS}</style></head><body><main><h1>{html.escape(cfg["title"])}</h1>'
            f'<p class="sub">分鏡審查稿｜{len(src)} 段約 {total} 秒｜672×384 草稿｜首幀段 {n_frame} 段（每段多個 seed，綠框為建議），'
            f'續接段 {n_cont} 段接前段末幀｜畫面不放字，標語與說明改成台詞／字幕</p>{body}</main></body></html>')
    (d / "review.html").write_text(page, encoding="utf-8")
    print("輸出：", d / "review.html")
