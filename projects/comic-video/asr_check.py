"""轉寫 wav，核對 TTS 有沒有講對。

預設在 Spark 按需跑 Breeze ASR（asr_spark.sh：先檢查資源，whisper-cli 一次載入模型轉完整批就結束）；
資源檢查不通過（H3 在跑、記憶體不足…）就改用 Xavier 常駐的 Breeze ASR（100.108.74.45:8013）。
環境變數 ASR_HOST=xavier 可強制用 Xavier。config.json 的 lang（預設 zh）決定轉寫語言，日文版填 ja，並改用 Spark 上的 ggml-large-v3-turbo（Xavier 備援仍是 Breeze，非中文不可靠）。

用法：python asr_check.py <篇目> [wav...]   （不帶 wav = 核對 <篇目>/audio/lines.json 全部台詞）
"""
import io, json, os, subprocess, sys, tarfile, time, urllib.request, uuid
from pathlib import Path

import comic

SPARK = "funsteam@100.89.149.50"
SPARK_SCRIPT = "~/h3-bench/comic-video/asr_spark.sh"
LANG = "zh"
MODEL_ENV = ""  # 非中文改用通用 Whisper：Breeze 只會把日文翻成中文
XAVIER = "http://100.108.74.45:8013"


def transcribe_spark(wavs):
    """整批送 Spark；回傳轉寫清單，資源檢查不通過回傳 None。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for i, w in enumerate(wavs):
            tar.add(w, f"{i:03d}.wav")
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=10", SPARK, f"ASR_LANG={LANG} {MODEL_ENV}bash {SPARK_SCRIPT}"],
                       input=buf.getvalue(), capture_output=True, timeout=600)
    out = r.stdout.decode("utf-8", "replace")
    sys.stderr.write(r.stderr.decode("utf-8", "replace"))
    if r.returncode == 3:
        print(f"Spark ASR 不啟動：{out.strip().removeprefix('PREFLIGHT ')}，改用 Xavier", file=sys.stderr)
        return None
    if r.returncode != 0:
        raise RuntimeError(f"Spark ASR 失敗（exit {r.returncode}）")
    texts = dict(line.split("\t", 1) for line in out.splitlines() if "\t" in line)
    return [texts.get(f"{i:03d}.wav", "<missing>") for i in range(len(wavs))]


def transcribe_xavier(wav):
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nzh\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="format"\r\n\r\ntxt\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="clip.wav"\r\n'
            f'Content-Type: audio/wav\r\n\r\n').encode() + wav.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{XAVIER}/api/transcribe", body,
                                 {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        job = json.load(r)["job_id"]
    while True:
        with urllib.request.urlopen(f"{XAVIER}/api/jobs/{job}", timeout=30) as r:
            j = json.load(r)
        if j["status"] not in ("queued", "running"):
            return j["text"] if j["status"] == "done" else f"<{j['status']}>"
        time.sleep(1)


def transcribe_all(wavs):
    texts = None if os.environ.get("ASR_HOST") == "xavier" else transcribe_spark(wavs)
    if texts is None and LANG != "zh":
        sys.exit("Spark ASR 不能跑，Xavier 只有 Breeze（非中文會翻成中文），稍後再試")
    if texts is None:
        texts = [transcribe_xavier(w) for w in wavs]
    return texts


if __name__ == "__main__":
    cfg, d, wavs = comic.load()
    LANG = cfg.get("lang", "zh")
    MODEL_ENV = "" if LANG == "zh" else "ASR_MODEL_FILE=ggml-large-v3-turbo.bin "
    if wavs:
        paths = [Path(p) for p in wavs]
        for p, t in zip(paths, transcribe_all(paths)):
            print(f"{p.name}: {t}", flush=True)
    else:
        lines = json.loads((d / "audio" / "lines.json").read_text(encoding="utf-8"))
        for ln, t in zip(lines, transcribe_all([d / "audio" / ln["file"] for ln in lines])):
            print(f"{ln['file']}\n  原文：{ln['text']}\n  ASR ：{t}", flush=True)
    if LANG == "ja":
        # Whisper 會照文意修正讀音（は 唸 ha、常温 唸 ちょうおん 都照樣寫對），再用音素模型聽一次
        import re, phoneme_check
        by_file = {ln["file"]: ln["text"] for ln in json.loads((d / "audio" / "lines.json").read_text(encoding="utf-8"))}
        items = ([(p, by_file[re.sub(r"_v\d+(?=\.wav$)", "", p.name)]) for p in paths] if wavs
                 else [(d / "audio" / f, t) for f, t in by_file.items()])
        print("\n── 音素比對 ──", flush=True)
        bad = phoneme_check.check(cfg, items)
        print(f"\n發音可疑 {len(bad)} 句：{'、'.join(bad) or '無'}")
