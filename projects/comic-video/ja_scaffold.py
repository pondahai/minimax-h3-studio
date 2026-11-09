"""從中文篇目建立日文版資料夾 <篇目>_ja/：storyboard.md、config.json、校稿檔、參考音。

用法：python ja_scaffold.py <篇目>
譯稿放在 <篇目>_ja/lines_ja.json：
{"title": "日文片名", "cut": "B（中文版有 A／B 版時才寫）", "names": {"小明": "ミン", ...}, "note": "給校稿者的補充（可省略）",
 "lines": [["S01", "0–3", "ミン", "台詞", "全假名讀音（は當助詞寫わ）"], ...]}
秒數要和中文版的時段一模一樣；全假名讀音送 TTS，台詞原文用在字幕。
"""
import json, re, shutil, sys

import comic

MORA_PER_SEC = 7.5  # 超過就提示偏長
CAST_JA = {"ミン": "7歳男の子", "メイ": "10歳女の子", "リン博士": "やさしい博士", "ナレーター": "ナレーション"}


def zh_lines(path):
    out, sid = {}, None
    for row in path.read_text(encoding="utf-8").splitlines():
        if m := re.match(r"### (S\d+[A-Z]?)", row):
            sid = m.group(1)
        if sid and (m := re.match(r"^\| ([\d–]+) \|.*\| (\S+?)：「(.+?)」 \|$", row)):
            out[(sid, m[1])] = (m[2], m[3])
    return out


if __name__ == "__main__":
    src_cfg, src, _ = comic.load()
    dst = src.parent / f"{src.name}_ja"
    ja = json.loads((dst / "lines_ja.json").read_text(encoding="utf-8"))
    names, lines = ja["names"], ja["lines"]
    zh = zh_lines(src / "storyboard.md")
    if cut := ja.get("cut"):  # 中文版有 A／B 版時，只做上傳的那一版
        keep = src_cfg["cuts"][cut]
        zh = {k: v for k, v in zh.items() if k[0] in keep}
        src_cfg["shots"] = sorted((s for s in src_cfg["shots"] if s[0] in keep), key=lambda s: keep.index(s[0]))
        src_cfg.pop("cuts")

    missing = [k for k in zh if k not in {(s, t) for s, t, *_ in lines}]
    extra = [(s, t) for s, t, *_ in lines if (s, t) not in zh]
    if missing or extra:
        sys.exit(f"時段對不上中文版：缺 {missing}，多 {extra}")
    for s, t, who, said, kana in lines:
        a, b = map(int, t.split("–"))
        mora = len(re.sub(r"[、。！？…「」　 ]", "", kana))
        if mora / (b - a) > MORA_PER_SEC:
            print(f"偏長 {s} {t} {who}：{mora} 拍 / {b - a} 秒 = {mora / (b - a):.1f}")

    md = [f"# {src_cfg['title']} — 日本語版台詞", "",
          f"畫面、時段與 `../{src.name}/storyboard.md` 相同（影片、配樂沿用），這裡只放日文台詞，格式供 `tts.py` 讀取。",
          "日語約 7–8 拍/秒，台詞已縮短以落在時段內。"]
    sid = None
    for s, t, who, said, _ in lines:
        if s != sid:
            md += ["", f"### {s}", "| 秒 | 畫面 | 聲音 |", "|---|---|---|"]
            sid = s
        md.append(f"| {t} | — | {who}：「{said}」 |")
    (dst / "storyboard.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    voices = {names[k]: v for k, v in src_cfg["voices"].items() if k in names}
    cfg = {"title": f"{ja['title']}（日本語版）", "source": src_cfg["source"],
           **{k: src_cfg[k] for k in ("style", "characters", "no_text_rule", "panel_dir", "shots", "panels", "cuts") if k in src_cfg},
           "voices": voices, "ref_text": src_cfg["ref_text"],
           "ref_transcript": {names[k]: v for k, v in src_cfg.get("ref_transcript", {}).items() if k in names},
           "lang": "ja", "t2s": False,
           "pronounce": {said: kana for *_, said, kana in lines if said != kana},
           "speakers": [names[k] for k in src_cfg["speakers"] if k in names],
           "tagline": "", "sub_font": "Noto Sans CJK JP",
           "note": f"《{src_cfg['title']}》日文配音＋日文字幕版：影片、配樂沿用 {src.name}/，參考音沿用中文版選定的參考音（跨語言克隆）"}
    (dst / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")

    (dst / "audio").mkdir(exist_ok=True)
    for zh_name, ja_name in names.items():
        ref = src / "audio" / f"ref_{zh_name}.wav"
        if ref.exists():
            shutil.copy(ref, dst / "audio" / f"ref_{ja_name}.wav")
        elif ja_name in voices:
            print(f"注意：沒有 {ref.name}，配音時會用 voice design 生成，要先讓使用者挑")
    gi = src.parent / "condensation_ja" / ".gitignore"
    if not (dst / ".gitignore").exists():
        shutil.copy(gi, dst / ".gitignore")

    cast = "、".join(f"{n}（{CAST_JA.get(n, zh_name)}）" for zh_name, n in names.items() if n in voices)
    txt = [f"《{src_cfg['title']}》日本語版 台詞校正用", f"日本語タイトル（暫定）：{ja['title']}", "",
           "・秒數為該句可用的時間，日文需在時間內說完（約 7–8 拍/秒）", f"・登場人物：{cast}"]
    if ja.get("note"):
        txt.append(f"・{ja['note']}")
    txt += ["・修改請直接寫在「修正：」後面", ""]
    sid = None
    for s, t, who, said, _ in lines:
        if s != sid:
            txt += ["", f"■ {s}"]
            sid = s
        zw, zt = zh[(s, t)]
        txt += [f"[{t}秒] {who}", f"  中文：{zw}：{zt}", f"  日本語：{said}", "  修正：", ""]
    (dst / f"{src.name}_ja_校稿.txt").write_text("\n".join(txt), encoding="utf-8-sig")
    print(f"{dst.name}：{len(lines)} 句")
