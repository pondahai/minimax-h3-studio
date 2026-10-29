"""讓 8002 看整篇漫畫原圖，直接寫分鏡稿草稿 → <篇目>/storyboard_8002.md（試驗：比較 8002 能否接手人工分鏡）。

用法：python draft_storyboard.py <篇目>
讀 config 的 panel_dir 裡的 panel-01.png、panel-02.png…（網站原圖，一格一張；不含切塊的 a／b），
連同篇名、角色表一次送給 8002。規則摘自 docs/comic-to-video-workflow.md 第 2 節。
"""
import base64, json, re, urllib.request
from pathlib import Path

import comic

URL = "http://100.89.149.50:8002/v1/chat/completions"

SYSTEM = """你是兒童科普動畫的分鏡師。輸入是一篇分格漫畫（依序 {n} 張圖，每張一格）。請把它改寫成短片分鏡稿，用繁體中文、Markdown 輸出，規則：

格式（照抄這個結構）：
### S01 段名（第 1 格）— 12s
| 秒 | 畫面／動作 | 鏡頭 | 聲音 |
|---|---|---|---|
| 0–4 | … | … | 小明：「…」 |
續接前一段末幀的段落，標題寫「（⟶續 S0X 末幀）」。

1. 每段最長 12 秒，每列 3–5 秒一個主要事件；不要太滿（同一列塞好幾個依序發生的事），也不要太空。
2. 每一列（包括第一列）都要有看得見的變化：角色動作、道具變化或鏡頭運動，不能只寫「站著」「固定」。
3. 聲音欄寫台詞「角色：「台詞」」或「旁白：「…」」或「—」。中文約 4 字／秒，童聲要更慢；一列的台詞不能超過那列秒數能唸完的量。
4. 台詞以漫畫對話框與說明文字為準，可以精簡；漫畫裡的標題、標籤、說明框改成旁白。
5. 畫面裡絕對不能出現任何文字、標籤、圖表、編號、對話框；漫畫中的圖示、示意圖要改成實景畫面或旁白說明。
6. 角色（全片外觀一致）：{characters}。阿柴不說話：漫畫裡阿柴的台詞改給其他角色或刪掉。
7. 角色比漫畫原圖少時，在該列寫明「（畫面只有某某）」或「（畫面沒有人物）」。
8. 場景要寫在每一段裡（例如戶外木桌、山坡草地），不要假設全片同一場景。
9. 續接只用在同一景別、動作連續的段落；景別大幅切換（特寫↔全景）就開新段。續接段的前一段，最後一列寫明「末幀：…」構圖。
10. 漫畫若有科學錯誤或不安全的做法，在最前面「## 原作處理」列出並改正。
11. 一格內容太多可以拆成兩段；最後寫「**總長**：X 秒」。
只輸出分鏡稿本身。"""


def panels(cfg):
    return sorted(p for p in Path(cfg["panel_dir"]).glob("panel-*.png") if re.fullmatch(r"panel-\d+", p.stem))


def draft(cfg):
    files = panels(cfg)
    user = [{"type": "text", "text": f"篇名：《{cfg['title']}》，共 {len(files)} 格。"}]
    for i, p in enumerate(files, 1):
        user += [{"type": "text", "text": f"第 {i} 格："},
                 {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()}}]
    body = json.dumps({
        "messages": [{"role": "system", "content": SYSTEM.format(n=len(files), characters=cfg["characters"])},
                     {"role": "user", "content": user}],
        "temperature": 0.4, "max_tokens": 8000,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)["choices"][0]["message"]["content"].strip()


if __name__ == "__main__":
    cfg, d, _ = comic.load()
    text = draft(cfg)
    (d / "storyboard_8002.md").write_text(f"# {cfg['title']} — 8002 分鏡草稿\n\n{text}\n", encoding="utf-8")
    print(text)
