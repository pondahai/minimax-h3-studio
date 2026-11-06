"""日文台詞的發音核對：音素辨識結果和讀音表（config 的 pronounce 全假名）逐音比對。

Whisper 會照文意修正（は 唸成 ha 仍寫「は」、ちょうおん 也寫成「常温」），抓不到這類錯；
這裡改用 Spark 上的音素模型（phoneme_spark.py）聽實際發音，兩邊都轉成粗略羅馬字再比對。
音素模型本身有雜訊，所以只標兩種可疑句：
  - 清濁／は行わ行對調（j↔ch、z↔s、w↔h）：常温 じょうおん→ちょうおん、は 唸 ha 都屬這類
  - 整句相似度低於 MIN_RATIO
最後仍以人工試聽為準。

用法：python phoneme_check.py <篇目> [wav...]   （不帶 wav = 核對 <篇目>/audio/lines.json 全部台詞）
asr_check.py 在 config 的 lang 為 ja 時會自動接著跑這支。
"""
import difflib, io, json, re, subprocess, sys, tarfile
from pathlib import Path

import comic

SPARK = "funsteam@100.89.149.50"
SPARK_CMD = "~/dgx-voxcpm-eval/.venv/bin/python ~/h3-bench/comic-video/phoneme_spark.py"
MIN_RATIO = 0.6
# g↔k、d↔t、b↔p 不算：母音間的 k、t 本來就常被音素模型聽成 g、d（《凝結》27 句裡 8 句誤報）
SWAPS = {frozenset(p) for p in [("j", "ch"), ("z", "s"), ("w", "h")]}

KANA = dict(zip(
    "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"
    "がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ",
    "a i u e o ka ki ku ke ko sa shi su se so ta chi tsu te to na ni nu ne no ha hi fu he ho "
    "ma mi mu me mo ya yu yo ra ri ru re ro wa o n "
    "ga gi gu ge go za ji zu ze zo da ji zu de do ba bi bu be bo pa pi pu pe po".split()))
SMALL = {"ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o"}
IPA = {"ç": "h", "ɸ": "f", "ʃ": "sh", "ɕ": "sh", "tʃ": "ch", "tɕ": "ch", "dʒ": "j", "ʑ": "j", "dʑ": "j",
       "dz": "z", "ɾ": "r", "l": "r", "ɯ": "u", "ʊ": "u", "ɪ": "i", "ɔ": "o", "ɑ": "a", "æ": "a", "ɛ": "e",
       "ə": "", "v": "w", "ʋ": "w", "β": "w", "ɡ": "g", "ŋ": "n", "ɲ": "n", "x": "h", "j": "y"}


def kana_to_romaji(text):
    text = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)  # 片假名→平假名
    out = ""
    for c in text:
        if c in SMALL and out.endswith("i"):
            # きゃ→kya；しゃ、ちゃ、じゃ→sha、cha、ja
            out = out[:-1] + (SMALL[c][-1] if out.endswith(("shi", "chi", "ji")) else SMALL[c])
        elif c in SMALL:
            out += SMALL[c][-1]
        elif c in KANA:
            out += KANA[c]
        elif c == "ー" and out:
            out += out[-1]
        elif c == "っ":
            out += "Q"
    out = re.sub(r"Q(.)", r"\1\1", out).replace("Q", "")
    return out


def ipa_to_romaji(phones):
    return "".join(IPA.get(p.replace("ː", ""), p.replace("ː", "")) for p in phones.split())


def normalize(r):
    """長音、促音、拗音在音素模型上很不穩，比對前都壓掉。"""
    r = r.replace("ou", "o").replace("ei", "e")
    r = re.sub(r"(.)\1+", r"\1", r)
    return re.sub(r"[^a-z]", "", r)


def consonants(seg):
    return set(re.findall(r"ch|sh|ts|[bcdfghjkmnprstwyz]", seg))


def compare(expected, heard):
    """回傳 (相似度, 可疑的對調清單)。"""
    a, b = normalize(expected), normalize(heard)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    swaps = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "replace":
            continue
        ea, hb = consonants(a[max(0, i1 - 1):i2 + 1]), consonants(b[max(0, j1 - 1):j2 + 1])
        for x in ea - hb:
            for y in hb - ea:
                if frozenset((x, y)) in SWAPS:
                    swaps.append(f"{a[max(0, i1 - 2):i2 + 2]}→{b[max(0, j1 - 2):j2 + 2]}")
    return sm.ratio(), swaps


def phonemes(wavs):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for i, w in enumerate(wavs):
            tar.add(w, f"{i:03d}.wav")
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=10", SPARK, SPARK_CMD],
                       input=buf.getvalue(), capture_output=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"Spark 音素辨識失敗：{r.stderr.decode('utf-8', 'replace')[-500:]}")
    got = dict(line.split("\t", 1) for line in r.stdout.decode("utf-8").splitlines() if "\t" in line)
    return [got.get(f"{i:03d}.wav", "") for i in range(len(wavs))]


def check(cfg, items):
    """items：[(wav 路徑, 台詞原文)]；印出每句結果，回傳可疑句檔名。"""
    pron = cfg.get("pronounce", {})
    bad = []
    for (wav, text), heard in zip(items, phonemes([w for w, _ in items])):
        exp, got = kana_to_romaji(pron.get(text, text)), ipa_to_romaji(heard)
        ratio, swaps = compare(exp, got)
        flag = swaps or ratio < MIN_RATIO
        if flag:
            bad.append(wav.name)
        print(f"{'⚠' if flag else ' '} {wav.name}  相似度 {ratio:.2f}{'  對調：' + '、'.join(swaps) if swaps else ''}\n"
              f"    應為：{normalize(exp)}\n    聽到：{normalize(got)}", flush=True)
    return bad


if __name__ == "__main__":
    cfg, d, wavs = comic.load()
    lines = json.loads((d / "audio" / "lines.json").read_text(encoding="utf-8"))
    by_file = {ln["file"]: ln["text"] for ln in lines}
    if wavs:
        # 候選檔 SXX_YY_角色_vN.wav 用原句的台詞
        items = [(Path(w), by_file[re.sub(r"_v\d+(?=\.wav$)", "", Path(w).name)]) for w in wavs]
    else:
        items = [(d / "audio" / ln["file"], ln["text"]) for ln in lines]
    bad = check(cfg, items)
    print(f"\n可疑 {len(bad)} 句：{'、'.join(bad) or '無'}")
