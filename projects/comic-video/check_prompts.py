"""擴寫後檢查 <篇目>/prompts/SXX.txt 和分鏡是否一致。

用法：python check_prompts.py <篇目> [段...]
檢查：時間軸、多出來的角色、「」引號（畫面文字）、動作密度（太短或只寫固定）、台詞。
official 格式另查三個欄位、首幀開頭句、每句台詞原封不動在 <d>[Chinese] …</d>、旁白有寫閉嘴。
前後段外觀是否連續仍要人工看。
"""
import re

import comic
from expand import INSTRUCTION_FIRST_FRAME, shots

MIN_CHARS = 15
STILL = re.compile(r"固定|停留|靜止")
MOTION = re.compile(r"推|拉|移|搖|晃|轉|伸|舉|放|倒|沉|浮|跳|走|跑|揮|指|拿|抬|點頭|眨|開合|閃|飄|流|落|升")
MOUTH = re.compile(r"嘴|口型|說話")
FIELDS = ("integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:")
STILL_EN = re.compile(r"\b(static|still|motionless|holds?)\b", re.I)


def check_official(cfg, sid, block, prompt):
    issues = []
    pos = [prompt.find(f) for f in FIELDS]
    if -1 in pos or pos != sorted(pos):
        issues.append("缺欄位或順序不對（integrated_multimodal_description → overall_soundscape → non_diegetic_music）")
    has_frame = dict((s, f) for s, _, f in cfg["shots"]).get(sid, "-") != "-"
    if has_frame != prompt.startswith(INSTRUCTION_FIRST_FRAME):
        issues.append("首幀開頭句" + ("缺少" if has_frame else "多出來（t2va 不該有）"))
    desc = prompt[pos[0]:pos[1]] if -1 not in pos else prompt
    rows = re.findall(r"^\| (\d+)–(\d+) \|(.*?)\| ([^|]*) \|$", block, re.M)
    stamps = [int(m) for m in re.findall(r"At 00:(\d\d)\.\d{3}", desc)]
    if stamps != [int(a) for a, *_ in rows]:
        issues.append(f"時間戳不符：分鏡 {[int(a) for a, *_ in rows]}，prompt {stamps}")
    spoken = re.findall(r"<d>\[Chinese\]\s*(.*?)\s*</d>", desc)
    want = [m[2] for *_, snd in rows if (m := re.match(r"(\S+?)：「(.+?)」", snd))]
    if spoken != want:
        issues.append(f"台詞不符：分鏡 {want}，<d> {spoken}")
    for _, _, _, snd in rows:
        if snd.startswith("旁白：") and not re.search(r"off-screen voiceover", desc):
            issues.append("旁白沒寫 off-screen voiceover")
            break
    if any(snd.startswith("旁白：") for *_, snd in rows) and not re.search(r"lips? (remain|stay|are kept) closed|closed lips", desc, re.I):
        issues.append("旁白時段沒寫角色閉嘴")
    names_en = cfg.get("names_en", {})
    extra = [zh for zh, en in names_en.items() if en in desc and zh not in block]
    if extra:
        issues.append(f"多出角色：{'、'.join(extra)}")
    for a, b in zip(stamps, stamps[1:] + [None]):
        seg = desc[desc.find(f"At 00:{a:02d}"):desc.find(f"At 00:{b:02d}") if b is not None else len(desc)]
        if len(seg) < 80 or (STILL_EN.search(seg) and not re.search(r"\b(mov|push|pan|tilt|drop|sink|float|rais|lift|turn|wave|point|nod|lean|bob|ripple|bubbl|sway|jiggl|vibrat|pour|settl)", seg, re.I)):
            issues.append(f"{a} 秒起 動作太少")
    return issues


def check(cfg, d, sid, block):
    if cfg.get("prompt_format", "official") != "legacy":
        prompt = (d / "prompts" / f"{sid}.txt").read_text(encoding="utf-8")
        if prompt.lstrip().startswith(("For the target", "integrated_multimodal_description")):
            return check_official(cfg, sid, block, prompt)
        return ["還是舊的中文格式，要用 official 格式重新擴寫"]
    names = re.findall(r"(?:^|；)([^＝；]+)＝", cfg["characters"])
    want = re.findall(r"^\| (\d+)–(\d+) \|.*?\| ([^|]*) \|$", block, re.M)
    prompt = (d / "prompts" / f"{sid}.txt").read_text(encoding="utf-8")
    slots = dict(((a, b), t) for a, b, t in re.findall(r"(\d+)[–-](\d+)\s*秒[：:](.*)", prompt))
    issues = []
    got = list(slots)
    if [(a, b) for a, b, _ in want] != got:
        issues.append(f"時間軸不符：分鏡 {[(a, b) for a, b, _ in want]}，prompt {got}")
    extra = [n for n in names if n in prompt and n not in block]
    if extra:
        issues.append(f"多出角色：{'、'.join(extra)}")
    quotes = re.findall(r"「[^」]*」", prompt)
    if quotes:
        issues.append(f"引號（可能畫成文字）：{' '.join(quotes)}")
    for a, b, sound in want:
        text = slots.get((a, b), "")
        if len(text) < MIN_CHARS or (STILL.search(text) and not MOTION.search(text)):
            issues.append(f"{a}–{b}秒 動作太少：{text[:40]}")
        speaker = re.match(r"(\S+?)：「", sound)
        if speaker and speaker[1] in names and not MOUTH.search(text):
            issues.append(f"{a}–{b}秒 {speaker[1]}有台詞但沒寫口型")
    return issues


if __name__ == "__main__":
    cfg, d, only = comic.load()
    for sid, block in shots(d):
        if only and sid not in only:
            continue
        issues = check(cfg, d, sid, block)
        print(sid, "OK" if not issues else "\n  " + "\n  ".join(issues))
