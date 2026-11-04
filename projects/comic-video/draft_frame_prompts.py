"""讓本地模型（預設 8006）依定稿分鏡寫每段首幀 prompt → <篇目>/frame_prompts/SXX.txt，並產生 frame_refs.json。

用法：python draft_frame_prompts.py <篇目> [段...]
續接段（標題有「⟶續」）用前段末幀，不寫首幀。送給模型：該段分鏡、原圖該格、角色外觀（不寫名字）、第三集手寫範例。
參考圖由程式依該段 0 秒那列出場的角色決定（config 的 char_refs，可用 frame_cast 指定）；config 的 frame_notes 是給各段的審稿意見。寫完做簡單檢查（出現角色名字、豬、猴子、缺「沒有任何文字」），有問題回饋重寫。
"""
import base64, json, re
from pathlib import Path

import comic
from check_storyboard import parse

REVISE = 2
BANNED = ["悟空", "八戒", "悟淨", "阿嬤", "豬", "猴"]  # 「鸚鵡」是外觀稱呼的一部分，不禁

EXAMPLE = (Path(__file__).parent / "journey03/frame_prompts/S07.txt").read_text(encoding="utf-8")

SYSTEM = """你替 AI 繪圖模型（Qwen-Image）寫動畫短片某一段「第 0 秒首幀」的中文 prompt。輸入是這一段的分鏡、漫畫原圖這一格，以及角色外觀。
規則：
1. 第一句固定寫「參考圖是動畫裡的角色立繪。畫一張 16:9 的{style}畫面，畫風和角色外觀照參考圖，不要照抄立繪的白色背景：」
2. 只畫分鏡第 0 秒那一刻的畫面：還沒發生的動作不能已經完成。
3. 角色不准寫名字，也不准出現「豬」「猴子」等字，只用下面的外觀稱呼：{looks}
4. 場景、時間（午後、黃昏、夕陽、入夜）、光線、地面材質寫具體，背景不能是白色。
5. 寫一句景別（全景、中景、近景）。
6. 寫「畫面裡剛好只有……，沒有其他人物」，列出第 0 秒在畫面裡的角色（路人遊客可以寫成「遠處有模糊的遊客」）。
7. 最後一行固定寫「畫面中完全沒有任何文字、字母、數字、標籤、招牌字、匾額字、狀聲詞或對話框。」招牌、地圖、手機螢幕要寫明是空白或只有圖案。
8. 只輸出 prompt 本文，不要標題或說明。
範例（第三集，別的場景）：
{example}"""

LOOKS = {
    "悟空": "棕髮男孩（棕色刺蝟頭、額頭戴金色頭圈、黑外套配黃色上衣、黑色背包）",
    "八戒": "胖男孩（戴黑色鴨舌帽、穿深藍色拉鍊運動外套的圓臉胖胖男孩）",
    "悟淨": "眼鏡男孩（黑短髮、黑框眼鏡、淺藍色上衣、灰色背包）",
    "鸚鵡": "卡通金剛鸚鵡（紅頭、黃胸、綠藍翅膀）",
    "阿嬤": "親切的老奶奶（灰白短髮包灰藍色頭巾、圓臉瞇眼笑、酒紅色上衣外罩米白色圍裙）",
}


def ask(messages):
    return comic.llm({"messages": messages, "temperature": 0.4, "max_tokens": 1500,
                      "chat_template_kwargs": {"enable_thinking": False}}).strip()


def problems(text):
    out = [f"出現「{w}」" for w in BANNED if w in text]
    if "沒有任何文字" not in text:
        out.append("最後缺「畫面中完全沒有任何文字…」那一行")
    if "剛好只有" not in text and "沒有人物" not in text:
        out.append("缺「畫面裡剛好只有……」")
    return out


if __name__ == "__main__":
    cfg, d, only = comic.load()
    text = (d / "storyboard.md").read_text(encoding="utf-8")
    refs_path = d / "frame_refs.json"
    refs = json.loads(refs_path.read_text(encoding="utf-8")) if refs_path.exists() else {}
    looks = "；".join(LOOKS.values())
    system = SYSTEM.format(style=cfg["style"], looks=looks, example=EXAMPLE)
    (d / "frame_prompts").mkdir(exist_ok=True)
    for sid, panel, dur, cont, block, rows in parse(text):
        if cont or (only and sid not in only):
            continue
        first = rows[0][2] + rows[0][4]
        # 第 0 秒那列常寫「三人背影」不寫名字：寫到三人時補上三個男孩；config 的 frame_cast 可直接指定
        cast = cfg.get("frame_cast", {}).get(sid) or [w for w in LOOKS if w in first or (w in ("悟空", "八戒", "悟淨") and "三人" in first)] or [w for w in LOOKS if w in block]
        refs[sid] = [cfg["char_refs"][w] for w in cast]
        img = base64.b64encode((Path(cfg["panel_dir"]) / f"panel-{panel:02d}.png").read_bytes()).decode()
        note = cfg.get("frame_notes", {}).get(sid)
        ask_text = f"這一段的分鏡（第 0 秒是第一列）：\n{block}\n第 0 秒畫面裡的角色：{'、'.join(LOOKS[w] for w in cast)}"
        if note:
            ask_text += f"\n審稿意見（一定要照做）：{note}"
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": ask_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}]}]
        for attempt in range(REVISE + 1):
            out = ask(msgs)
            bad = problems(out)
            print(f"{sid} 第 {attempt + 1} 次：{bad or 'OK'}", flush=True)
            if not bad:
                break
            msgs += [{"role": "assistant", "content": out},
                     {"role": "user", "content": "請修正以下問題後重寫整段 prompt：" + "；".join(bad)}]
        (d / "frame_prompts" / f"{sid}.txt").write_text(out + "\n", encoding="utf-8")
    refs_path.write_text(json.dumps(refs, ensure_ascii=False, indent=1), encoding="utf-8")
