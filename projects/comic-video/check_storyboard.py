"""檢查分鏡稿是否照 docs/comic-to-video-workflow.md 第 2 節的規則寫（人寫的或 8002 寫的都適用）。

用法：python check_storyboard.py <篇目> [分鏡檔]   （預設 storyboard.md）
檢查：段長 ≤12 秒、時間軸連續、每列 2–6 秒、台詞語速、每列有動作、阿柴不說話、說話者是已知角色、
畫面不放字、續接段（同一格、前段有寫末幀）、原圖沒有的角色、角色比原圖少時有沒有寫「畫面只有／沒有人物」。
原圖每格有誰寫在 config 的 panel_cast（{"1": ["小明", ...]}）；沒有這欄就跳過角色相關檢查。
"""
import re

import comic

MAX_SHOT = 12
CPS = 4.0          # 一般語速（字／秒）
CPS_CHILD = 3.5    # 童聲
CHILDREN = ("小明", "小美")
MUTE = ("阿柴",)
MOTION = re.compile(r"推|拉|移|搖|晃|轉|伸|舉|放|倒|沉|浮|跳|走|跑|揮|指|拿|抬|點頭|眨|閃|飄|流|落|升|噴|蹲|湊|拍|吹|浮現|出現|散|射|滴|動|攤|比|握|遮|追|靠|看|望|遞|叼|舔|拿")
STILL = re.compile(r"固定|停留|靜止|站著$")
TEXT_IN_PICTURE = re.compile(r"文字|標籤|標示|字幕|圖表|箭頭|虛線|示意圖|編號|對話框|照片|清單|筆記|「")
ONLY = re.compile(r"畫面只有|畫面沒有人物")
ROW = re.compile(r"^\| *(\d+)[–-](\d+) *\|(.*?)\|(.*?)\|(.*?)\|\s*$", re.M)


def parse(text):
    """回傳 [(段, 格, 秒數, 續接段或 None, 區塊文字, [(起, 迄, 畫面, 鏡頭, 聲音)])]。"""
    out = []
    for block in re.split(r"\n(?=### S\d+)", text)[1:]:
        block = block.split("\n**總長")[0].strip()
        head = block.splitlines()[0]
        sid = re.match(r"### (S\d+)", head)[1]
        panel = (m := re.search(r"第 ?(\d+) ?格", head)) and int(m[1])
        dur = (m := re.search(r"(\d+) ?s\b", head)) and int(m[1])
        cont = (m := re.search(r"⟶續 ?(S\d+)", head)) and m[1]
        # 「12–12 | （末幀：…）」這種只寫末幀的列不算時段
        rows = [(int(a), int(b), v.strip(), c.strip(), s.strip()) for a, b, v, c, s in ROW.findall(block)
                if not (a == b and "末幀" in v)]
        out.append((sid, panel, dur, cont, block, rows))
    return out


def lines(sound):
    return re.findall(r"(\S+?)：「(.+?)」", sound)


def check_shot(cfg, shot, prev):
    sid, panel, dur, cont, block, rows = shot
    known = set(cfg.get("names_en", {})) | {"旁白"}
    cast = cfg.get("panel_cast", {}).get(str(panel)) if panel else None
    issues = []
    if not rows:
        return ["沒有分鏡表"]
    if not panel:
        issues.append("標題沒寫（第 N 格），無法對照原圖")
    if dur and dur > MAX_SHOT:
        issues.append(f"段長 {dur} 秒，超過 {MAX_SHOT}")
    if rows[0][0] != 0 or any(b != a2 for (_, b, *_), (a2, *_) in zip(rows, rows[1:])):
        issues.append(f"時間軸不連續：{[(a, b) for a, b, *_ in rows]}")
    if dur and rows[-1][1] != dur:
        issues.append(f"最後一列到 {rows[-1][1]} 秒，段長寫 {dur} 秒")
    seen = set()
    for a, b, vis, cam, snd in rows:
        span = b - a
        if not 2 <= span <= 6:
            issues.append(f"{a}–{b} 秒 一列 {span} 秒（建議 3–5 秒一個事件）")
        if STILL.search(vis) or not MOTION.search(vis + cam):
            issues.append(f"{a}–{b} 秒 動作太少：{vis[:30]}")
        if TEXT_IN_PICTURE.search(vis):
            issues.append(f"{a}–{b} 秒 畫面可能有字：{TEXT_IN_PICTURE.search(vis)[0]}")
        said = lines(snd)
        n = sum(len(re.findall(r"[一-鿿]", t)) for _, t in said)
        cps = CPS_CHILD if any(w in CHILDREN for w, _ in said) else CPS
        if said and span > 0 and n / span > cps:
            issues.append(f"{a}–{b} 秒 台詞 {n} 字／{span} 秒，超過 {cps} 字／秒")
        for who, _ in said:
            if who in MUTE:
                issues.append(f"{a}–{b} 秒 {who}不說話，台詞要改給別人")
            elif who not in known:
                issues.append(f"{a}–{b} 秒 未知說話者：{who}")
        seen |= {n for n in known if n in vis or any(w == n for w, _ in said)}
    seen.discard("旁白")
    if prev and [r[2] for r in rows] == [r[2] for r in prev[5]]:
        issues.append(f"和 {prev[0]} 內容完全相同（重複段落）")
    elif prev and sum(r[4] == q[4] and r[4] != "—" for r, q in zip(rows, prev[5])) >= 2:
        issues.append(f"和 {prev[0]} 有兩句以上台詞重複")
    if cont:
        if not prev or prev[0] != cont:
            issues.append(f"續接 {cont}，但前一段不是 {cont}")
        elif not panel or prev[1] != panel:
            issues.append(f"續接段跨格（{cont} 第 {prev[1]} 格 → 第 {panel} 格），換場景要開新段")
        elif "末幀" not in prev[4]:
            issues.append(f"續接 {cont}，但 {cont} 沒寫末幀")
    if cast is not None:
        extra = seen - set(cast)
        if extra:
            issues.append(f"原圖第 {panel} 格沒有：{'、'.join(sorted(extra))}（確定要加再保留）")
        if seen < set(cast) and not ONLY.search(block):
            issues.append(f"角色比原圖少（{'、'.join(sorted(set(cast) - seen))}沒出場），沒寫「畫面只有…」")
    return issues


def check_text(cfg, text):
    shots = parse(text)
    return {s[0]: check_shot(cfg, s, p) for s, p in zip(shots, [None] + shots[:-1])}


if __name__ == "__main__":
    cfg, d, rest = comic.load()
    path = d / (rest[0] if rest else "storyboard.md")
    for sid, issues in check_text(cfg, path.read_text(encoding="utf-8")).items():
        print(sid, "OK" if not issues else "\n  " + "\n  ".join(issues))
