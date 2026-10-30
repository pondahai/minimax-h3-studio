"""讓 8002 逐格看漫畫原圖寫分鏡稿草稿 → <篇目>/storyboard_8002.md（試驗：8002 能否接手人工分鏡）。

用法：python draft_storyboard.py <篇目>
一次只送一格（panel_dir 的 panel-01.png、panel-02.png…，網站原圖一格一張），附上該格角色（config 的 panel_cast）
和前面已寫好的段落摘要；config 有 panel_notes 時，把該格的人工備註（科學更正、安全句、段數）一起送，備註優先於通則。
每格寫完用 check_storyboard.py 的規則驗收，有問題把清單回饋給 8002 重寫，最多 REVISE 輪。
仍沒過的問題寫進檔尾「## 未解決」，交給人看。
第一版（7 格一次送）的結果見 docs/comic-to-video-workflow.md。
"""
import base64, json, re, urllib.request
from pathlib import Path

import comic
from check_storyboard import check_text

URL = "http://100.89.149.50:8002/v1/chat/completions"
REVISE = 2

SYSTEM = """你是兒童科普動畫的分鏡師。輸入是一篇分格漫畫的其中一格（圖片），請把這一格改寫成短片分鏡：預設一格一段（12 秒）；只有這一格的台詞與說明 12 秒唸不完時才拆成兩段，不准為了湊長度加戲，用繁體中文、Markdown 輸出。

格式（照抄這個結構，標題一定要有「（第 N 格）」和秒數）：
### S01 段名（第 1 格）— 12s
| 秒 | 畫面／動作 | 鏡頭 | 聲音 |
|---|---|---|---|
| 0–4 | … | … | 小明：「…」 |
同一格拆成兩段、而且景別相同、動作連續時，第二段標題寫「### S02 段名（第 1 格）— 12s（⟶續 S01 末幀）」，
並在第一段最後一列的畫面欄寫「（末幀：…構圖）」。不同格之間一律開新段，不准續接。

規則：
1. 每段最長 12 秒，每列 3–5 秒、一個主要事件。時間軸首尾相接：下一列的起秒等於上一列的迄秒，寫成 0–4、4–8、8–12，不要寫 0–4、5–8、9–12；最後一列結束在段長。
2. 每一列都要有看得見的動作（角色動作、道具變化或鏡頭運動），不能只寫站著、固定。
3. 聲音欄寫「角色：「台詞」」或「旁白：「…」」或「—」，一列最多一句。{children}是小孩，一列台詞不超過 3.5 字／秒（4 秒最多 14 字）；旁白、林博士不超過 4 字／秒。
4. 台詞以這一格的對話框與說明文字為準，可以精簡、拆到不同列；科學重點不能漏。標題、標籤、說明框改成旁白。
5. 畫面不能出現任何文字、標籤、圖表、箭頭、編號、對話框、照片、筆記；圖中的示意圖改成實景畫面或旁白說明。
6. 角色外觀：{characters}。阿柴不說話：圖中阿柴的台詞改給小明或小美。
7. 只能用這一格裡出現的角色：{cast}。不准加其他角色，不准編圖中沒有的情節。
8. 角色比這一格少時，在畫面欄寫明「（畫面只有某某）」或「（畫面沒有人物）」。
9. 場景寫在每一列裡（例如戶外木桌、山坡草地）。
10. 圖中若有科學錯誤或不安全的做法（例如直視太陽、玻璃杯給小孩拿），在台詞或畫面改正。
11. 若有「人工備註」，一定要照做，和上面規則衝突時以備註為準（包括段數）。
只輸出這一格的分鏡段落（### 開頭），不要其他說明。"""


def panels(cfg):
    return sorted(p for p in Path(cfg["panel_dir"]).glob("panel-*.png") if re.fullmatch(r"panel-\d+", p.stem))


def ask(messages):
    body = json.dumps({"messages": messages, "temperature": 0.4, "max_tokens": 3000,
                       "chat_template_kwargs": {"enable_thinking": False}}).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        text = json.load(r)["choices"][0]["message"]["content"].strip()
    return re.sub(r"^```(?:markdown)?|```$", "", text).strip()


def renumber(text, start):
    """8002 的段號不一定對：依序改成 S{start}、S{start+1}…，續接引用一起改。"""
    old = re.findall(r"^### (S\d+)", text, re.M)
    new = {o: f"S{start + i:02d}" for i, o in enumerate(old)}
    text = re.sub(r"^### (S\d+)", lambda m: "### " + new[m[1]], text, flags=re.M)
    return re.sub(r"⟶續 ?(S\d+)", lambda m: "⟶續 " + new.get(m[1], m[1]), text), len(old)


def summary(done):
    heads = re.findall(r"^### .*$", done, re.M)
    return "前面已寫好的段落：\n" + "\n".join(heads) if heads else "這是第一格。"


def draft(cfg):
    done, log = "", []
    global raw
    raw = []
    for n, p in enumerate(panels(cfg), 1):
        start = len(re.findall(r"^### S\d+", done, re.M)) + 1
        cast = cfg.get("panel_cast", {}).get(str(n))
        cast = "依圖" if cast is None else "、".join(cast) or "沒有角色（畫面沒有人物）"
        note = cfg.get("panel_notes", {}).get(str(n))
        note = f"\n人工備註（一定要照做）：\n{note}" if note else ""
        img = "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
        messages = [
            {"role": "system", "content": SYSTEM.format(characters=cfg["characters"], cast=cast, children="、".join(cfg.get("children", ["小明", "小美"])))},
            {"role": "user", "content": [
                {"type": "text", "text": f"篇名：《{cfg['title']}》。{summary(done)}\n請寫第 {n} 格，段號從 S{start:02d} 開始。{note}"},
                {"type": "image_url", "image_url": {"url": img}}]},
        ]
        for rnd in range(REVISE + 1):
            part, count = renumber(ask(messages), start)
            raw.append(f"<!-- 第 {n} 格 第 {rnd + 1} 次 -->\n{part}")
            # 連同前一段一起檢查，續接與跨格才查得到；只取這一格的段落結果
            results = check_text(cfg, done + "\n" + part)
            mine = [f"S{start + i:02d}" for i in range(count)]
            issues = {s: results.get(s, ["沒寫出這一段"]) for s in mine}
            bad = {s: v for s, v in issues.items() if v}
            print(f"第 {n} 格 第 {rnd + 1} 次：{'OK' if not bad else bad}", flush=True)
            if not bad or rnd == REVISE:
                break
            messages += [{"role": "assistant", "content": part},
                         {"role": "user", "content": "檢查沒過，請整格重寫，修正以下問題：\n" +
                          "\n".join(f"{s}：{i}" for s, v in bad.items() for i in v)}]
        done += ("\n\n" if done else "") + part
        log += [f"- {s}：{i}" for s, v in bad.items() for i in v]
    return done, log


if __name__ == "__main__":
    cfg, d, _ = comic.load()
    text, log = draft(cfg)
    total = sum(int(s) for s in re.findall(r"^### .*?— ?(\d+) ?s", text, re.M))
    out = f"# {cfg['title']} — 8002 分鏡草稿（逐格）\n\n## 分鏡\n\n{text}\n\n**總長**：{total} 秒\n"
    if log:
        out += "\n## 未解決（檢查程式重試後仍沒過）\n" + "\n".join(log) + "\n"
    (d / "storyboard_8002.md").write_text(out, encoding="utf-8")
    (d / "storyboard_8002_rounds.md").write_text("\n\n".join(raw) + "\n", encoding="utf-8")
