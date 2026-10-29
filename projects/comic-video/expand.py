"""把 <篇目>/storyboard.md 每段連同對應漫畫分格送 8002 擴寫成影片 prompt，輸出 <篇目>/prompts/SXX.txt。

用法：python expand.py <篇目> [段落...]   （不帶段落 = 全部）
config 的 prompt_format：
  official（預設）＝H3 官方英文結構化格式（integrated_multimodal_description／overall_soundscape／non_diegetic_music）。
    LLM 只寫英文畫面描述（JSON），時間戳、<d>[Chinese] 台詞</d>、旁白 off-screen voiceover＋角色閉嘴由程式組，
    讓 H3 照台詞對嘴；config 的 last_frames 列出有尾幀（frames/SXX_end.png）的段，會加官方尾幀句；H3 原生音軌合成時仍整條靜音、換成 TTS
  legacy＝《蝴蝶》當時的中文自由格式（H3 會自己編非中文人聲，不要再用）
"""
import base64, json, re, sys, urllib.request
from pathlib import Path

import comic

URL = "http://100.89.149.50:8002/v1/chat/completions"

SYSTEM = """你是影片生成提示詞擴寫器。輸入是一段 12 秒以內的分鏡表（秒數區間、畫面、鏡頭、聲音）。
請輸出一段給文生影片模型用的中文提示詞，規則：
1. 必須逐條保留每個時間區段，格式「X–Y秒：…」，秒數不得合併、刪改或重排。
2. 每個區段補充細節：主體外觀、動作過程、表情、光線、色彩、質感、鏡頭運動。
3. 開頭用一句話寫整體風格：{style}。
4. 角色外觀固定：{characters}。
5. 不要寫台詞內容與字幕，{no_text_rule}。
6. 若有「末幀」描述，最後一個區段要明確寫出最後畫面的構圖。
7. 附圖是原漫畫對應分格，只用來參考角色外觀、配色、場景與畫風；忽略圖中所有文字、對話框、編號與標題，
   動作與時間軸一律以分鏡表為準，不要加入分鏡表沒有的角色或情節。
8. 這部片的人聲另外用 TTS 配，影片音軌不能有任何人聲：結尾加一句「音訊：無對白、無人聲，只有自然環境音與輕快的兒童配樂」，
   角色描述不要寫說話、驚呼、喊叫等發聲動作，改寫成表情與肢體動作。
只輸出提示詞本身。"""

SYSTEM_OFFICIAL = """You write the visual part of a prompt for MiniMax H3, a video model. The input is a storyboard for one shot of at most 12 seconds,
as a table (time range | visuals and action | camera | sound), plus the original comic panel as an image.
Reply with JSON only, no markdown:
{{"intro": "...", "ranges": ["...", "..."], "final_frame": "...", "soundscape": "..."}}

- intro: 1-2 English sentences that set the style ({style}) and establish the scene, the characters present and the composition.
- ranges: exactly one English description per storyboard row, in the same order ({n} rows, so {n} items). Do not write timestamps.
  Describe concrete appearance, motion, expression, light, color and camera movement. Every item needs at least one visible change
  (character action, prop change or camera movement); never leave the picture static.
  If the row's sound is a character line, describe that character speaking: mouth moving, expression and gestures. Do not write the words.
  If the row's sound is narration (旁白) or silent, the characters do not speak.
- final_frame: if the storyboard describes a final frame (末幀), one sentence describing it; otherwise "".
- soundscape: 1-3 English sentences of ambient and physical action sounds only (breeze, birds, water, objects). Never speech or music.
- Characters and their looks (always refer to them by these English names exactly): {characters}
- {no_text_rule}
- Use the image only for character looks, colors, setting and art style; ignore all text, speech bubbles, numbers and titles in it.
  Follow the storyboard for actions and timing; do not add characters or events that are not in the storyboard."""

INSTRUCTION_FIRST_FRAME = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."


def official(cfg):
    return cfg.get("prompt_format", "official") != "legacy"


def system_prompt(cfg, n=0):
    if not official(cfg):
        return SYSTEM.format(style=cfg["style"], characters=cfg["characters"], no_text_rule=cfg["no_text_rule"])
    return SYSTEM_OFFICIAL.format(style=cfg["style_en"], characters=cfg["characters_en"], no_text_rule=cfg["no_text_rule_en"], n=n)


def stamp(sec):
    return f"00:{int(sec):02d}.000"


def rows(block):
    """分鏡表每列的 (起秒, 迄秒, 聲音欄)。"""
    return re.findall(r"^\| (\d+)–(\d+) \|.*\| ([^|]*?) \|$", block, re.M)


def assemble(cfg, sid, block, parts):
    """組成官方格式 prompt：每列一句「At 00:0X.000, 描述」，台詞放 <d>，旁白寫 voiceover 並讓角色閉嘴。"""
    speakers = {}
    sentences = [parts["intro"].strip()]
    for (start, _, sound), text in zip(rows(block), parts["ranges"]):
        line = f"At {stamp(start)}, {text.strip()}"
        if m := re.match(r"(\S+?)：「(.+?)」", sound):
            who, said = m[1], m[2]
            if who == "旁白":
                line += f" A narrator says in an off-screen voiceover, <d>[Chinese] {said}</d> The on-screen characters' lips remain closed."
            else:
                speakers.setdefault(who, f"S{len(speakers) + 1}")
                name = cfg.get("names_en", {}).get(who, who)
                line += f" {name} ({speakers[who]}) says, <d>[Chinese] {said}</d>"
        sentences.append(line)
    if sid in cfg.get("last_frames", []):  # 官方尾幀句：Picture 2 錨定在片長秒數
        sentences.append(f"<Picture 2> (from [Shot 1]) aligns with the {comic.durations(cfg)[sid]:.2f}-second mark of the target video.")
    if parts.get("final_frame"):
        sentences.append(parts["final_frame"].strip())
    body = (f"integrated_multimodal_description: [Shot 1] {' '.join(sentences)}\n\n"
            f"overall_soundscape: {parts['soundscape'].strip()}\n\n"
            "non_diegetic_music: N/A")
    has_frame = dict((s, f) for s, _, f in cfg["shots"]).get(sid, "-") != "-"
    return f"{INSTRUCTION_FIRST_FRAME}\n\n{body}" if has_frame else body  # 有首幀（Qwen-Image 圖或前段末幀）才加官方開頭句


def shots(d):
    text = (d / "storyboard.md").read_text(encoding="utf-8")
    for block in re.split(r"\n(?=### S\d+)", text)[1:]:
        block = block.split("\n**總長")[0].strip()
        yield re.match(r"### (S\d+)", block).group(1), block


def expand(cfg, sid, block, tries=3):
    img = base64.b64encode((Path(cfg["panel_dir"]) / f"{cfg['panels'][sid]}.png").read_bytes()).decode()
    user = [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}},
            {"type": "text", "text": block}]
    req_body = {
        "messages": [{"role": "system", "content": system_prompt(cfg, len(rows(block)))}, {"role": "user", "content": user}],
        "temperature": 0.6, "max_tokens": 1500,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if official(cfg):
        # 8002 偶爾回不合法的 JSON（《彩虹》S05、S06）：用 llama.cpp 的 JSON 文法限制輸出，段數不符再重試
        req_body["response_format"] = {"type": "json_object"}
    body = json.dumps(req_body).encode()
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            result = json.load(r)["choices"][0]["message"]["content"].strip()
        if not official(cfg):
            return result
        try:
            parts = json.loads(re.sub(r"^```(?:json)?|```$", "", result).strip())
            assert len(parts["ranges"]) == len(rows(block)), f"LLM 回了 {len(parts['ranges'])} 段，分鏡有 {len(rows(block))} 段"
            return assemble(cfg, sid, block, parts)
        except (ValueError, KeyError, AssertionError) as e:
            print(f"{sid} 第 {attempt} 次失敗：{e}", file=sys.stderr, flush=True)
    sys.exit(f"{sid}：重試 {tries} 次仍失敗")


if __name__ == "__main__":
    cfg, d, only = comic.load()
    out = d / "prompts"
    out.mkdir(exist_ok=True)
    for sid, block in shots(d):
        if only and sid not in only:
            continue
        result = expand(cfg, sid, block)
        (out / f"{sid}.txt").write_text(result, encoding="utf-8")
        print(f"== {sid}\n{result}\n", flush=True)
