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
