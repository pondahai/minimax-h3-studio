"""擴寫後檢查 <篇目>/prompts/SXX.txt 和分鏡是否一致。

用法：python check_prompts.py <篇目> [段...]
檢查：時間軸、多出來的角色、「」引號（畫面文字）、動作密度（太短或只寫固定）、台詞時段有沒有寫口型。
前後段外觀是否連續仍要人工看。
"""
import re

import comic
from expand import shots

MIN_CHARS = 15
STILL = re.compile(r"固定|停留|靜止")
MOTION = re.compile(r"推|拉|移|搖|晃|轉|伸|舉|放|倒|沉|浮|跳|走|跑|揮|指|拿|抬|點頭|眨|開合|閃|飄|流|落|升")
MOUTH = re.compile(r"嘴|口型|說話")


def check(cfg, d, sid, block):
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
