"""本地 LLM（comic.LLM_URL，預設 8006）看 <篇目>/frames/char_*.png 定裝圖，寫出每個角色的英文外觀短語（給 config looks_en 用，讓 H3 分得出誰在講話）。
用法：python looks.py journey02 out.json"""
import base64, json, sys
from pathlib import Path

import comic
d = Path(sys.argv[1]) / "frames"
SYS = ("You see a character reference sheet for an anime video. First silently check, from head to toe: hair color and style, "
       "anything on the head or face (headband, cap, GLASSES, earrings), top and its exact color, bottoms, shoes, bag and its exact color, "
       "anything held. Then write ONE English noun phrase of 15-25 words that lets a video model pick this character out of a group shot: "
       "start with 'the', give body type, hair, every face/head accessory, and the 2-3 most distinctive clothing items with exact colors. "
       "Skip props that are not part of the outfit. Visual facts only, no name, no personality. Reply with the phrase only.")
out = {}
for who, f in [("Wukong","wukong"),("Bajie","bajie"),("Wujing","wujing"),("the parrot","parrot"),("the Venerable","monk")]:
    img = base64.b64encode((d / f"char_{f}.png").read_bytes()).decode()
    body = {"messages":[{"role":"system","content":SYS},{"role":"user","content":[{"type":"image_url","image_url":{"url":f"data:image/png;base64,{img}"}}]}],"temperature":0.2,"max_tokens":200,"chat_template_kwargs":{"enable_thinking":False}}
    out[who] = comic.llm(body, timeout=300).strip().strip('"')
    print(who, "=>", out[who], flush=True)
json.dump(out, open(sys.argv[2], "w", encoding="utf8"), ensure_ascii=False, indent=1)
