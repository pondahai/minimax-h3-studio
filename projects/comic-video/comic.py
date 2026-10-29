"""漫畫轉影片工作流共用：讀篇目資料夾的 config.json。

每個腳本的第一個參數是篇目資料夾名稱（例如 density），其餘參數依各腳本而定。
"""
import json, sys
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
    return cfg, d, sys.argv[2:]


def durations(cfg):
    return {sid: dur for sid, dur, _ in cfg["shots"]}
