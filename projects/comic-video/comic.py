"""漫畫轉影片工作流共用：讀篇目資料夾的 config.json。

每個腳本的第一個參數是篇目資料夾名稱（例如 density），其餘參數依各腳本而定。
"""
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).parent


def load():
    """回傳 (config, 篇目資料夾, 其餘參數)。"""
    names = sorted(p.parent.name for p in ROOT.glob("*/config.json"))
    if len(sys.argv) < 2 or sys.argv[1] not in names:
        sys.exit(f"用法：python {Path(sys.argv[0]).name} <篇目> ...   篇目：{'、'.join(names)}")
    d = ROOT / sys.argv[1]
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    cfg["id"] = sys.argv[1]
    # 同一篇做多個版本時（config 的 cuts：{"A": [段...], "B": [...]}），環境變數 CUT=A 只取那一版的段落，
    # 成品檔名加版本（airplane_A_draft.mp4、airplane_A.srt）；H3、sfx 等逐段處理的腳本不受影響
    if (cut := os.environ.get("CUT")) and cut in cfg.get("cuts", {}):
        keep = cfg["cuts"][cut]
        cfg["shots"] = sorted((s for s in cfg["shots"] if s[0] in keep), key=lambda s: keep.index(s[0]))
        cfg["id"] = f"{cfg['id']}_{cut}"
    return cfg, d, sys.argv[2:]


def durations(cfg):
    return {sid: dur for sid, dur, _ in cfg["shots"]}


ANCHOR_GAP = 0.15  # 前一句還沒講完，下一句順延到講完後再隔這麼久


def anchor_plan(lines, seg_dur):
    """TTS 音訊錨點的起秒（2026-11-17 起）：每句原速放在分鏡起秒，前句沒講完就順延。
    run_series.sh 照這個時間把 TTS 錨進 H3（H3 照我們的聲音生嘴型），mux.py／subs.py 用同一個時間放回 TTS，三者一致。
    回傳 [(行, 起秒)]；講到段尾之後的句子會印警告（要在 lines.json 改起秒或縮短台詞）。"""
    plan, prev_end = [], None
    for ln in lines:
        t = ln["start"] if prev_end is None else max(ln["start"], prev_end + ANCHOR_GAP)
        prev_end = t + ln["audio_sec"]
        if prev_end > seg_dur:
            print(f"警告：{ln['file']} 講到 {prev_end:.2f}s，超過段長 {seg_dur}s", file=sys.stderr)
        plan.append((ln, round(t, 3)))
    return plan


# 本地 LLM（分鏡、首幀 prompt、擴寫、外觀、對嘴檢查共用）。預設 8006＝Spark vLLM qwen3.8-nvfp4（2026-11-04 起取代 8002）；
# 環境變數 LLM_PORT=8002 改回 llama.cpp。8006 平常可能停著（pipeline.sh 跑 H3 前會停掉它），第一次呼叫時自動 docker start。
LLM_PORT = os.environ.get("LLM_PORT", os.environ.get("SB_PORT", "8006"))
LLM_URL = f"http://100.89.149.50:{LLM_PORT}/v1/chat/completions"
LLM_MODEL = {"8006": "qwen3.8"}.get(LLM_PORT)
_llm_ready = False


def ensure_llm():
    import subprocess, time, urllib.request
    global _llm_ready
    if _llm_ready:
        return
    models = LLM_URL.replace("/chat/completions", "/models")
    try:
        urllib.request.urlopen(models, timeout=5)
    except OSError:
        if LLM_PORT != "8006":
            raise
        print("8006 沒在跑，docker start qwen3.8-nvfp4（冷啟動數分鐘）", flush=True)
        subprocess.run(["ssh", "funsteam@100.89.149.50", "docker start qwen3.8-nvfp4"], check=True, capture_output=True)
        for _ in range(180):  # vLLM 冷啟動要讀 22 GB 權重＋編譯，實測 3 分鐘以上，給 15 分鐘
            time.sleep(5)
            try:
                urllib.request.urlopen(models, timeout=5)
                break
            except OSError:
                pass
        else:
            sys.exit("8006 啟動逾時")
    _llm_ready = True


def llm(body, timeout=600):
    """送 chat completion（body 不用帶 model），回傳 content 文字。"""
    import urllib.request
    ensure_llm()
    data = json.dumps({**({"model": LLM_MODEL} if LLM_MODEL else {}), **body}).encode()
    req = urllib.request.Request(LLM_URL, data, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["choices"][0]["message"]["content"]
