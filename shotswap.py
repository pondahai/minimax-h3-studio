"""鏡頭分段換人 v2：先依鏡頭切換點分段，每段各自寫提示詞、各自換人、逐段驗收，最後接回原片音軌。

和舊的長片分段換人（app.py 的 /api/generate_long_swap，快速模式）並存：
- 切點用 ffmpeg 的場景分數找鏡頭切換，不平均切；超過單段上限的鏡頭在動作最少的時刻切開（強制接縫）
- 不用接續圖：每段只送角色圖與該段原片，彼此獨立，可單獨重跑
- 生成走全域排隊器：同一時間只有一個 H3 任務（Spark 並行會 OOM 當機），並和單片生成共用 is_running

狀態存在 outputs/shotswap/<id>/state.json，Studio 重開後可以接著做（排隊中的段落會回到未送出）。
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import runner
import runner_spark

MIN_SHOT = 4.0          # H3 最短秒數
MAX_SHOT = 12.0         # 自動規劃的單段上限（2026-11-10 Spark 實測換人 12 秒可穩定跑完）
HARD_MAX_SHOT = 15.0    # H3 單次上限；手動調整可到這裡
SCENE_THRESHOLD = 0.2   # ffmpeg 場景分數高於此值視為鏡頭切換（0.3 在夜景漏掉 0.23、0.29 的明顯切點，2026-11-10）
SEAM_WINDOW = 1.0       # 強制接縫在理想切點前後幾秒內找動作最少的幀
MIN_CUT_GAP = 0.5       # 兩個切點至少相隔幾秒（閃光、快速晃動會連續觸發）
# 短於 MIN_SHOT 的鏡頭：放慢到剛好 MIN_SHOT 秒送 H3，生成後再加速回原長（2026-11-10 實測 1.3 秒×3.08、
# 2.6 秒×1.54 都成功，動作逐幀對得上；加速時每幾幀取一幀，放慢造成的重複幀頓挫也跟著消失）。
# 更短的鏡頭原始畫面太少，預設保留原片（介面上可改成換人）。
MIN_STRETCH_SOURCE = 1.0
BUSY_RETRY_SECONDS = 60

A: Any = None  # app 模組，register() 時注入
ROOT: Path = Path()
_lock = threading.RLock()
_queue: deque = deque()          # (project_id, shot_id)
_queue_cv = threading.Condition(_lock)
_worker_note = {"text": ""}      # 排隊器目前在做什麼（給介面顯示）


# ───────────────────────── 狀態檔 ─────────────────────────

def _pdir(pid: str) -> Path:
    if not re.fullmatch(r"ss_[0-9a-f]{8}", pid or ""):
        raise HTTPException(status_code=400, detail="無效的專案編號。")
    return ROOT / pid


def _load(pid: str) -> dict:
    path = _pdir(pid) / "state.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="找不到這個鏡頭換人專案。")
    return json.loads(path.read_text(encoding="utf-8"))


def _save(state: dict) -> None:
    state["updated_at"] = runner.now_iso()
    path = _pdir(state["id"]) / "state.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _shot(state: dict, sid: str) -> dict:
    for shot in state["shots"]:
        if shot["id"] == sid:
            return shot
    raise HTTPException(status_code=404, detail="找不到這個鏡頭（可能已被合併或拆分）。")


def _url(path: Path) -> str:
    return "/outputs/" + path.resolve().relative_to(A.OUTPUTS_DIR.resolve()).as_posix()


def _upload_url(path: str) -> Optional[str]:
    try:
        return "/uploads/" + Path(path).resolve().relative_to(A.UPLOADS_DIR.resolve()).as_posix()
    except Exception:
        return None


# ───────────────────────── 分鏡 ─────────────────────────

def _ffmpeg() -> str:
    return A._ffmpeg_path()


def scene_scores(video: Path) -> List[tuple]:
    """每一幀的 (時間, 場景分數)。縮小畫面算，幾十秒的片只要幾秒。"""
    proc = subprocess.run(
        [_ffmpeg(), "-v", "error", "-i", str(video), "-an",
         "-vf", "scale=320:-2,select='gte(scene\\,0)',metadata=print:file=-", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"場景偵測失敗：{proc.stderr.strip()[-300:]}")
    scores, t = [], None
    for line in proc.stdout.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"lavfi\.scene_score=([0-9.]+)", line)
        if m and t is not None:
            scores.append((t, float(m.group(1))))
            t = None
    return scores


def _quietest(scores: List[tuple], lo: float, hi: float, target: float) -> float:
    window = [(s, abs(t - target), t) for t, s in scores if lo <= t <= hi]
    return min(window)[2] if window else target


def plan_shots(duration: float, scores: List[tuple], threshold: float = SCENE_THRESHOLD) -> List[dict]:
    """鏡頭切換點 → 段落清單。每段 {start, end, action, seam_before, contains_cut}。"""
    cuts: List[float] = []
    # 片頭片尾附近的切點也要收：只有幾幀的上一鏡留在段落裡，LLM 會把它寫成切鏡（2026-11-10 實測）。
    # 間隔太近的連續切點（閃光）只取第一個。
    for t, s in scores:
        if s >= threshold and 0.01 < t < duration - 0.01 and (not cuts or t - cuts[-1] >= MIN_CUT_GAP):
            cuts.append(t)
    edges = [0.0, *cuts, duration]
    shots = [{"start": a, "end": b, "action": "swap", "seam_before": False, "contains_cut": False}
             for a, b in zip(edges, edges[1:])]

    # 超過上限：在動作最少的時刻切開
    out: List[dict] = []
    for shot in shots:
        s, end = shot["start"], shot["end"]
        first = True
        while end - s > MAX_SHOT:
            pieces = -(-(end - s) // MAX_SHOT)
            target = s + (end - s) / pieces
            lo = max(s + MIN_SHOT, target - SEAM_WINDOW, end - (pieces - 1) * MAX_SHOT)
            hi = min(s + MAX_SHOT, target + SEAM_WINDOW, end - (pieces - 1) * MIN_SHOT)
            cut = _quietest(scores, lo, hi, target) if lo <= hi else target
            out.append({**shot, "start": s, "end": cut, "seam_before": shot["seam_before"] if first else True})
            s, first = cut, False
        out.append({**shot, "start": s, "end": end, "seam_before": shot["seam_before"] if first else True})
    # 短鏡頭不再併入相鄰段（快速剪接的片會一路併成一段，又回到漏換的老問題）：
    # 1～4 秒放慢處理，短於 1 秒預設保留原片
    for x in out:
        if x["end"] - x["start"] < MIN_STRETCH_SOURCE:
            x["action"] = "keep"
    return out


def stretch_factor(shot: dict) -> float:
    """放慢倍數：短於 MIN_SHOT 才放慢到剛好 MIN_SHOT 秒，否則 1。"""
    length = shot["end"] - shot["start"]
    return MIN_SHOT / length if 0 < length < MIN_SHOT else 1.0


def _atempo(factor: float) -> str:
    """atempo 每級最低 0.5，放慢超過 2 倍要串接。"""
    parts = []
    while factor < 0.5:
        parts.append("atempo=0.5")
        factor /= 0.5
    parts.append(f"atempo={factor:.6f}")
    return ",".join(parts)


def _new_shot(start: float, end: float, action: str = "swap", seam_before: bool = False,
              contains_cut: bool = False, prompt: str = "") -> dict:
    return {"id": uuid.uuid4().hex[:8], "start": round(start, 3), "end": round(end, 3), "action": action,
            "seam_before": seam_before, "contains_cut": contains_cut, "prompt": prompt,
            "status": "idle", "error": None, "output": None, "seed": None, "review": None,
            "expanding": False, "elapsed": None}


def _clip(state: dict, shot: dict) -> Path:
    """該段原片（精準重編碼切割），以起訖時間命名，邊界沒變就沿用。"""
    pdir = _pdir(state["id"])
    path = pdir / "clips" / f"src3_{int(shot['start'] * 1000):07d}_{int(shot['end'] * 1000):07d}.mp4"
    if not path.is_file():
        path.parent.mkdir(exist_ok=True)
        # 用 trim 依幀時間切，邊界各往前讓半幀：切點就是下一鏡第一幀的時間，讓半幀才會包含本段第一幀、
        # 排除下一鏡第一幀。不用 -ss/-t：它會把輸出時間軸對齊到第一個解出的幀，多切進下一鏡一幀，
        # LLM 看到就把它寫成切鏡（2026-11-10 實測）。-fps_mode passthrough：否則 trim 後 ffmpeg 7 以 25 fps 輸出而掉幀。
        fps = state.get("fps") or _probe_size(Path(state["source"]))[2]
        half = 0.5 / fps
        a, b = max(0.0, shot["start"] - half), shot["end"] - half
        A._run_ffmpeg(["-i", state["source"],
                       "-vf", f"trim=start={a:.4f}:end={b:.4f},setpts=PTS-STARTPTS",
                       "-af", f"atrim=start={shot['start']:.4f}:end={shot['end']:.4f},asetpts=PTS-STARTPTS",
                       "-fps_mode", "passthrough",
                       "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
                       "-c:a", "aac", str(path)])
    return path


def _gen_clip(state: dict, shot: dict) -> Path:
    """送 H3（和 LLM 擴寫）用的原片：短鏡頭放慢到 MIN_SHOT 秒，音軌同步放慢（音高不變）。
    換人模式會把原片音軌送進模型，放慢片一定要有音軌，否則 ComfyUI 直接失敗（2026-11-10 實測）。"""
    k = stretch_factor(shot)
    if k == 1.0:
        return _clip(state, shot)
    src = _clip(state, shot)
    path = src.with_name(src.stem.replace("src3_", "slow_") + ".mp4")
    if not path.is_file():
        fps = state.get("fps") or _probe_size(Path(state["source"]))[2]
        A._run_ffmpeg(["-i", str(src), "-vf", f"setpts={k:.6f}*PTS,fps={fps:g}", "-af", _atempo(1 / k),
                       "-t", f"{MIN_SHOT:.3f}",
                       "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
                       "-c:a", "aac", str(path)])
    return path


def _thumb(state: dict, shot: dict) -> Path:
    pdir = _pdir(state["id"])
    path = pdir / "clips" / f"th_{int(shot['start'] * 1000):07d}_{int(shot['end'] * 1000):07d}.jpg"
    if not path.is_file():
        path.parent.mkdir(exist_ok=True)
        mid = (shot["start"] + shot["end"]) / 2
        A._run_ffmpeg(["-ss", f"{mid:.3f}", "-i", state["source"], "-frames:v", "1", "-vf", "scale=320:-2", str(path)])
    return path


def _validate(shot: dict) -> Optional[str]:
    length = shot["end"] - shot["start"]
    if shot["action"] != "swap":
        return None
    if length < MIN_STRETCH_SOURCE - 0.01:
        return f"短於 {MIN_STRETCH_SOURCE:g} 秒，放慢後畫面太少：請保留原片或與相鄰鏡頭合併"
    if length > HARD_MAX_SHOT + 0.05:
        return f"超過 {HARD_MAX_SHOT:g} 秒，請拆分"
    return None


def _view(state: dict) -> dict:
    """回給前端的狀態：補上網址、長度與警告。"""
    shots = []
    with _lock:
        queued = [sid for pid, sid in _queue if pid == state["id"]]
    for i, shot in enumerate(state["shots"], start=1):
        length = shot["end"] - shot["start"]
        item = {**shot, "index": i, "length": round(length, 2), "problem": _validate(shot),
                "stretch": round(stretch_factor(shot), 2),
                "long_warning": shot["action"] == "swap" and MAX_SHOT < length <= HARD_MAX_SHOT,
                "queue_position": queued.index(shot["id"]) + 1 if shot["id"] in queued else None}
        try:
            item["clip_url"] = _url(_clip(state, shot))
            item["thumb_url"] = _url(_thumb(state, shot))
        except Exception as exc:
            item["clip_url"] = item["thumb_url"] = None
            item["problem"] = item["problem"] or f"無法切出原片：{exc}"
        if shot.get("output") and Path(shot["output"]).is_file():
            item["output_url"] = _url(Path(shot["output"]))
        shots.append(item)
    final = state.get("final")
    return {**state, "shots": shots, "image_urls": [_upload_url(p) for p in state["images"]],
            "source_url": _upload_url(state["source"]), "final_url": _url(Path(final)) if final and Path(final).is_file() else None,
            "limits": {"min": MIN_SHOT, "max": MAX_SHOT, "hard_max": HARD_MAX_SHOT, "min_stretch": MIN_STRETCH_SOURCE},
            "worker": _worker_note["text"], "spark_busy": A.current_state["is_running"]}


def _editable(state: dict) -> None:
    if any(x["status"] in ("queued", "running") for x in state["shots"]):
        raise HTTPException(status_code=400, detail="有段落正在排隊或生成，請等它結束或先取消排隊再修改分鏡。")


# ───────────────────────── API 模型 ─────────────────────────

class CreateRequest(BaseModel):
    source_video: str
    reference_images: List[str]
    idea: Optional[str] = ""
    title: Optional[str] = ""
    backend: Optional[str] = "spark"
    resolution: Optional[str] = "draft"
    threshold: Optional[float] = None


class SettingsRequest(BaseModel):
    idea: Optional[str] = None
    title: Optional[str] = None
    backend: Optional[str] = None
    resolution: Optional[str] = None


class EditRequest(BaseModel):
    op: str                      # merge（與下一段合併）／split（在 at 秒切開）／action（swap／keep）／prompt
    shot_id: str
    at: Optional[float] = None   # split：絕對時間（秒）
    action: Optional[str] = None
    prompt: Optional[str] = None


class ShotIdsRequest(BaseModel):
    shot_ids: Optional[List[str]] = None  # 空白 = 所有適用的段落


class ReviewRequest(BaseModel):
    shot_id: str
    verdict: str  # pass／keep／reset


# ───────────────────────── 排隊器 ─────────────────────────

def _enqueue(pid: str, sids: List[str]) -> int:
    added = 0
    with _queue_cv:
        state = _load(pid)
        for sid in sids:
            shot = _shot(state, sid)
            if shot["status"] in ("queued", "running"):
                continue
            shot.update(status="queued", error=None, review=None)
            _queue.append((pid, sid))
            added += 1
            state["final"] = None
        _save(state)
        _queue_cv.notify_all()
    return added


def _set_shot(pid: str, sid: str, **fields) -> None:
    with _lock:
        state = _load(pid)
        try:
            _shot(state, sid).update(**fields)
        except HTTPException:
            return
        _save(state)


def _drop_queue(reason: str) -> None:
    """取消（緊急中斷）後，佇列裡還沒跑的段落退回未送出。"""
    with _lock:
        items = list(_queue)
        _queue.clear()
    for pid, sid in items:
        _set_shot(pid, sid, status="idle", error=reason)


def _run_one(pid: str, sid: str, session: str, transport) -> None:
    with _lock:
        state = _load(pid)
        shot = _shot(state, sid)
        shot.update(status="running", error=None)
        _save(state)
    clip = _gen_clip(state, shot)
    k = stretch_factor(shot)
    length = (shot["end"] - shot["start"]) * k  # 放慢段送進去的長度是 MIN_SHOT
    seed = random.randint(0, 999999)
    job_id = f"{pid}_{sid}_{int(time.time())}"
    pdir = _pdir(pid)
    job = {
        "id": job_id, "title": f"{state.get('title') or '鏡頭換人'} #{state['shots'].index(shot) + 1}",
        "mode": "reference", "reference_images": state["images"], "reference_audios": [],
        "reference_videos": [str(clip)], "character_swap": True, "aspect": state["aspect"],
        "text_encoder": "heretic",
        "resolution": "full" if transport.name == "colab" or state.get("resolution") == "full" else "draft",
        "prompt": shot["prompt"],
        # 生成長度向上取整秒，合併時再裁回原段長度（放慢段先加速回來再裁）
        "duration_seconds": max(int(MIN_SHOT), int(-(-round(length, 3) // 1))), "seed": seed,
        "output_name": f"shot_{sid}_{seed}.mp4",
    }
    manifest_path = pdir / f".manifest_{sid}.json"
    manifest_path.write_text(json.dumps({"jobs": [job]}, ensure_ascii=False, indent=2), encoding="utf-8")
    started = time.time()
    try:
        result = runner.run_batch(manifest_path, session=session, gpu="A100", high_mem=True, stop_on_complete=False,
                                  progress_path=A.PROGRESS_FILE, output_dir=pdir / "out",
                                  exec_timeout=transport.max_exec_timeout if hasattr(transport, "max_exec_timeout") else 1800,
                                  transport=transport)
    finally:
        manifest_path.unlink(missing_ok=True)
    done = next((j for j in result.get("jobs", []) if j.get("status") == "completed"), None)
    if not done:
        raise RuntimeError(result.get("error") or "生成失敗")
    meta = {**done, **A._job_settings(job), "shotswap": pid, "shot": sid, "start": shot["start"], "end": shot["end"]}
    Path(done["output"]).with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _set_shot(pid, sid, status="done", output=done["output"], seed=seed, review=None,
              elapsed=round(time.time() - started), output_stretch=k)


def _cancelled(run) -> bool:
    cs = A.current_state
    return cs.get("run") != run or not cs["is_running"] or cs["status"] in ("cancelled", "stopped")


def _worker() -> None:
    while True:
        with _queue_cv:
            while not _queue:
                _worker_note["text"] = ""
                _queue_cv.wait()
            pid, _ = _queue[0]
        try:
            backend = _load(pid).get("backend") or "spark"
        except Exception:
            with _lock:
                _queue.popleft()
            continue

        # 取得生成權：單片生成或快速模式在跑就等
        with A.generation_lock:
            if A.current_state["is_running"]:
                acquired = False
            else:
                A._begin_run("shotswap", backend)
                acquired = True
        if not acquired:
            _worker_note["text"] = "等待目前的生成任務結束"
            time.sleep(5)
            continue

        transport = A.BACKENDS[backend]
        run = A.current_state.get("run")
        session = f"h3-ss-{uuid.uuid4().hex[:8]}"
        cs = A.current_state
        cs.update(session=session, segment=0, segment_count=len(_queue), jobs=[],
                  log_tail=[f"[*] 鏡頭換人排隊器：{len(_queue)} 段待生成"])
        try:
            transport.start(session, "A100", True)
        except runner_spark.SparkBusyError as exc:
            _worker_note["text"] = f"等待 Spark 空閒（{exc}），{BUSY_RETRY_SECONDS} 秒後重試"
            if cs.get("run") == run:
                cs.update(is_running=False, status="idle", stage=0, stage_label=_worker_note["text"])
            time.sleep(BUSY_RETRY_SECONDS)
            continue
        except Exception as exc:
            _worker_note["text"] = f"無法啟動 {A.BACKEND_LABELS[backend]}：{exc}"
            if cs.get("run") == run:
                cs.update(is_running=False, status="failed", error=str(exc))
            _drop_queue(f"無法啟動 {A.BACKEND_LABELS[backend]}：{exc}")
            continue

        done = 0
        try:
            while True:
                with _lock:
                    if not _queue:
                        break
                    pid, sid = _queue[0]
                    try:
                        if (_load(pid).get("backend") or "spark") != backend:
                            break  # 換後端：先釋放這一個，下一輪再接手另一個
                    except Exception:
                        _queue.popleft()
                        continue
                    _queue.popleft()
                if _cancelled(run):
                    _set_shot(pid, sid, status="idle", error="已取消")
                    _drop_queue("已取消")
                    break
                done += 1
                cs.update(status="running", segment=done, segment_count=done + len(_queue))
                _worker_note["text"] = f"生成中：第 {done} 段（佇列還有 {len(_queue)} 段）"
                cs["log_tail"].append(f"[*] 開始 {pid} 鏡頭 {sid}")
                try:
                    _run_one(pid, sid, session, transport)
                    cs["log_tail"].append(f"[*] 鏡頭 {sid} 完成")
                except Exception as exc:
                    msg = "已取消" if _cancelled(run) else str(exc)
                    _set_shot(pid, sid, status="failed", error=msg)
                    cs["log_tail"].append(f"錯誤：鏡頭 {sid}：{msg}")
                    if _cancelled(run):
                        _drop_queue("已取消")
                        break
        finally:
            try:
                transport.stop(session)
            except Exception:
                transport.emergency_stop(session)
            if cs.get("run") == run:
                cs.update(is_running=False, status="completed", stage=5,
                          stage_label=f"鏡頭換人：完成 {done} 段，{A.BACKEND_LABELS[backend]} 已釋放")
            _worker_note["text"] = ""


# ───────────────────────── 合併 ─────────────────────────

def _probe_size(path: Path) -> tuple:
    proc = subprocess.run([_ffmpeg(), "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Video: .*?(\d{2,5})x(\d{2,5})", proc.stderr)
    f = re.search(r"([0-9.]+) fps", proc.stderr)
    if not m:
        raise RuntimeError(f"讀不到影片尺寸：{path.name}")
    return int(m.group(1)), int(m.group(2)), float(f.group(1)) if f else 24.0


def merge(state: dict) -> Path:
    shots = state["shots"]
    pending = [i + 1 for i, x in enumerate(shots) if not (x["action"] == "keep" or x.get("review") in ("pass", "keep"))]
    if pending:
        raise HTTPException(status_code=400, detail=f"第 {', '.join(map(str, pending))} 段還沒驗收（通過或保留原片）。")
    sources = []
    for x in shots:
        use_output = x["action"] == "swap" and x.get("review") == "pass" and x.get("output") and Path(x["output"]).is_file()
        if x["action"] == "swap" and x.get("review") == "pass" and not use_output:
            raise HTTPException(status_code=400, detail="有已通過的段落找不到生成檔，請重跑。")
        sources.append(Path(x["output"]) if use_output else _clip(state, x))
    generated = [p for p, x in zip(sources, shots) if x["action"] == "swap" and x.get("review") == "pass"]
    width, height, fps = _probe_size(generated[0] if generated else sources[0])
    width, height = width // 2 * 2, height // 2 * 2

    # 合併前檢查：各段尺寸／fps 不一致時一律縮放補邊到同一規格（保留原片的段落常常和生成檔解析度不同）
    notes = []
    for i, p in enumerate(sources, start=1):
        w, h, f = _probe_size(p)
        if (w, h) != (width, height) or abs(f - fps) > 0.01:
            notes.append(f"第 {i} 段 {w}×{h}@{f:g} → {width}×{height}@{fps:g}")

    inputs, chains = [], []
    for i, (p, x) in enumerate(zip(sources, shots)):
        length = x["end"] - x["start"]
        inputs += ["-i", str(p)]
        generated = x["action"] == "swap" and x.get("review") == "pass"
        k = (x.get("output_stretch") or 1.0) if generated else 1.0
        speed = f"setpts=PTS/{k:.6f}," if k != 1.0 else ""  # 放慢生成的段落加速回原長
        chains.append(f"[{i}:v]{speed}trim=0:{length:.3f},setpts=PTS-STARTPTS,fps={fps:g},"
                      f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                      f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{i}]")
    n = len(sources)
    graph = ";".join(chains) + ";" + "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    final = _pdir(state["id"]) / f"{state['id']}_full_{int(time.time())}.mp4"
    total = shots[-1]["end"]
    # 音軌直接用原片完整音軌，不分段處理，避免接縫處音畫不同步
    A._run_ffmpeg([*inputs, "-i", state["source"], "-filter_complex", graph, "-map", "[v]", "-map", f"{n}:a:0?",
                   "-t", f"{total:.3f}", "-c:v", "libx264", "-crf", "18", "-c:a", "aac", str(final)])
    state["merge_notes"] = notes
    return final


# ───────────────────────── 註冊路由 ─────────────────────────

def register(app, app_module) -> None:
    global A, ROOT
    A = app_module
    ROOT = A.OUTPUTS_DIR / "shotswap"
    ROOT.mkdir(parents=True, exist_ok=True)

    # 重開 Studio：排隊與生成中的段落不會自動恢復，退回未送出
    for path in ROOT.glob("ss_*/state.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            changed = False
            for x in state["shots"]:
                if x["status"] in ("queued", "running"):
                    x.update(status="idle", error="Studio 重新啟動，請重新送出")
                    changed = True
                if x.get("expanding"):
                    x["expanding"] = False
                    changed = True
            if changed:
                _save(state)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True, name="shotswap-queue").start()

    @app.get("/shotswap", response_class=HTMLResponse)
    def shotswap_page():
        return (A.STATIC_DIR / "shotswap.html").read_text(encoding="utf-8")

    @app.get("/api/shotswap")
    def list_projects():
        items = []
        for path in sorted(ROOT.glob("ss_*/state.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                s = json.loads(path.read_text(encoding="utf-8"))
                items.append({"id": s["id"], "title": s.get("title"), "source_name": s.get("source_name"),
                              "shots": len(s["shots"]), "updated_at": s.get("updated_at"),
                              "thumb_url": next((_url(t) for t in sorted(path.parent.glob("clips/th_*.jpg"))), None),
                              "image_url": _upload_url(s["images"][0]) if s.get("images") else None,
                              "done": sum(1 for x in s["shots"] if x.get("review") in ("pass", "keep") or x["action"] == "keep")})
            except Exception:
                pass
        return {"ok": True, "projects": items}

    @app.post("/api/shotswap")
    def create_project(req: CreateRequest):
        A._backend(req.backend)
        source = A._upload_file(req.source_video)
        if not source:
            raise HTTPException(status_code=400, detail=f"找不到原片：{req.source_video}")
        if not (1 <= len(req.reference_images) <= 9):
            raise HTTPException(status_code=400, detail="需要 1 到 9 張角色圖。")
        images = []
        for img in req.reference_images:
            p = A._upload_file(img)
            if not p:
                raise HTTPException(status_code=400, detail=f"找不到角色圖：{img}")
            images.append(str(p))
        try:
            duration = A._video_duration(source)
            scores = scene_scores(source)
            width, height, fps = _probe_size(source)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        if duration < MIN_SHOT:
            raise HTTPException(status_code=400, detail=f"原片至少要 {MIN_SHOT:g} 秒。")
        plan = plan_shots(duration, scores, req.threshold or SCENE_THRESHOLD)
        pid = f"ss_{uuid.uuid4().hex[:8]}"
        _pdir(pid).mkdir(parents=True)
        state = {
            "id": pid, "title": req.title or source.stem, "created_at": runner.now_iso(),
            "source": str(source), "source_name": source.name, "duration": round(duration, 3), "fps": fps,
            "aspect": "portrait" if height > width else "landscape", "images": images,
            "idea": req.idea or "", "backend": req.backend or "spark", "resolution": req.resolution or "draft",
            "threshold": req.threshold or SCENE_THRESHOLD, "final": None, "merge_notes": [],
            "shots": [_new_shot(x["start"], x["end"], x["action"], x["seam_before"], x["contains_cut"]) for x in plan],
        }
        with _lock:
            _save(state)
        return {"ok": True, "project": _view(state)}

    @app.get("/api/shotswap/{pid}")
    def get_project(pid: str):
        return {"ok": True, "project": _view(_load(pid))}

    @app.post("/api/shotswap/{pid}/settings")
    def update_settings(pid: str, req: SettingsRequest):
        with _lock:
            state = _load(pid)
            if req.backend is not None:
                A._backend(req.backend)
                state["backend"] = req.backend
            for key in ("idea", "title", "resolution"):
                if getattr(req, key) is not None:
                    state[key] = getattr(req, key)
            _save(state)
        return {"ok": True, "project": _view(state)}

    @app.post("/api/shotswap/{pid}/edit")
    def edit_shot(pid: str, req: EditRequest):
        with _lock:
            state = _load(pid)
            shots = state["shots"]
            shot = _shot(state, req.shot_id)
            i = shots.index(shot)
            if req.op == "prompt":
                if shot["status"] in ("queued", "running"):
                    raise HTTPException(status_code=400, detail="這段正在排隊或生成，不能改提示詞。")
                shot["prompt"] = req.prompt or ""
            elif req.op == "action":
                if req.action not in ("swap", "keep"):
                    raise HTTPException(status_code=400, detail="action 只能是 swap 或 keep。")
                if shot["status"] in ("queued", "running"):
                    raise HTTPException(status_code=400, detail="這段正在排隊或生成。")
                shot["action"] = req.action
            elif req.op == "merge":
                _editable(state)
                if i + 1 >= len(shots):
                    raise HTTPException(status_code=400, detail="最後一段沒有下一段可以合併。")
                nxt = shots[i + 1]
                prompt = shot["prompt"] if shot["prompt"] else nxt["prompt"]
                # 兩段之間原本是真的鏡頭切換（不是強制接縫）的話，合併後這段裡就含一次切鏡
                contains_cut = shot["contains_cut"] or nxt["contains_cut"] or not nxt["seam_before"]
                shots[i:i + 2] = [_new_shot(shot["start"], nxt["end"], "swap", shot["seam_before"], contains_cut, prompt)]
            elif req.op == "split":
                _editable(state)
                at = req.at if req.at is not None else -1
                if not (shot["start"] + 0.2 <= at <= shot["end"] - 0.2):
                    raise HTTPException(status_code=400, detail="切點要在這段之內。")
                shots[i:i + 1] = [_new_shot(shot["start"], at, shot["action"], shot["seam_before"], False, shot["prompt"]),
                                  _new_shot(at, shot["end"], shot["action"], False, False, shot["prompt"])]
            else:
                raise HTTPException(status_code=400, detail=f"未知的操作：{req.op}")
            state["final"] = None if req.op in ("merge", "split") else state.get("final")
            _save(state)
        return {"ok": True, "project": _view(state)}

    def _expand_shot(pid: str, sid: str) -> None:
        try:
            state = _load(pid)
            shot = _shot(state, sid)
            # LLM 看的是送進 H3 的那支（放慢段就看放慢片），提示詞裡的時間點才對得上
            clip = _gen_clip(state, shot)
            req = A.ExpandPromptRequest(
                idea=state.get("idea") or "", current_prompt="", image_count=len(state["images"]),
                video_count=1, audio_count=0, character_swap=True, mode="ref2va",
                duration_seconds=max(MIN_SHOT, round(shot["end"] - shot["start"], 2)),
                image_paths=state["images"], video_path=str(clip))
            prompt = A.expand_prompt(req)["prompt"]
            _set_shot(pid, sid, prompt=prompt, expanding=False, expand_error=None)
        except HTTPException as exc:
            _set_shot(pid, sid, expanding=False, expand_error=str(exc.detail))
        except Exception as exc:
            _set_shot(pid, sid, expanding=False, expand_error=str(exc))

    @app.post("/api/shotswap/{pid}/expand")
    def expand_shots(pid: str, req: ShotIdsRequest):
        """逐段擴寫提示詞（LLM 看角色圖與該段原片畫面）。在背景依序跑，前端輪詢狀態。"""
        with _lock:
            state = _load(pid)
            if not (state.get("idea") or "").strip():
                raise HTTPException(status_code=400, detail="請先寫一句全域構想（要把誰換成角色圖的人）。")
            wanted = req.shot_ids or [x["id"] for x in state["shots"] if x["action"] == "swap" and not x["prompt"].strip()]
            targets = []
            for sid in wanted:
                shot = _shot(state, sid)
                if shot["status"] in ("queued", "running") or shot.get("expanding"):
                    continue
                shot.update(expanding=True, expand_error=None)
                targets.append(sid)
            _save(state)

        def job():
            for sid in targets:
                _expand_shot(pid, sid)

        threading.Thread(target=job, daemon=True).start()
        return {"ok": True, "count": len(targets)}

    @app.post("/api/shotswap/{pid}/run")
    def run_shots(pid: str, req: ShotIdsRequest):
        with _lock:
            state = _load(pid)
            if req.shot_ids:
                chosen = [_shot(state, sid) for sid in req.shot_ids]
            else:  # 全部：還沒生成或失敗的換人段落
                chosen = [x for x in state["shots"] if x["action"] == "swap" and x["status"] in ("idle", "failed")]
            problems = []
            for x in chosen:
                n = state["shots"].index(x) + 1
                if x["action"] != "swap":
                    problems.append(f"第 {n} 段標為保留原片")
                elif _validate(x):
                    problems.append(f"第 {n} 段{_validate(x)}")
                elif not x["prompt"].strip():
                    problems.append(f"第 {n} 段還沒有提示詞")
            if problems:
                raise HTTPException(status_code=400, detail="；".join(problems))
            for x in chosen:
                _gen_clip(state, x)  # 先切好（含放慢片），避免在佔著 GPU 時才切
        added = _enqueue(pid, [x["id"] for x in chosen])
        return {"ok": True, "queued": added, "project": _view(_load(pid))}

    @app.post("/api/shotswap/{pid}/dequeue")
    def dequeue(pid: str, req: ShotIdsRequest):
        removed = 0
        with _lock:
            for sid in req.shot_ids or []:
                if (pid, sid) in _queue:
                    _queue.remove((pid, sid))
                    removed += 1
            state = _load(pid)
            for x in state["shots"]:
                if x["id"] in (req.shot_ids or []) and x["status"] == "queued":
                    x.update(status="idle", error=None)
            _save(state)
        return {"ok": True, "removed": removed, "project": _view(state)}

    @app.post("/api/shotswap/{pid}/review")
    def review(pid: str, req: ReviewRequest):
        with _lock:
            state = _load(pid)
            shot = _shot(state, req.shot_id)
            if req.verdict == "pass":
                if shot["status"] != "done":
                    raise HTTPException(status_code=400, detail="這段還沒有生成結果。")
                shot["review"] = "pass"
            elif req.verdict == "keep":
                shot["review"] = "keep"
            elif req.verdict == "reset":
                shot["review"] = None
            else:
                raise HTTPException(status_code=400, detail="verdict 只能是 pass、keep 或 reset。")
            state["final"] = None  # 驗收變了，舊的合併成品不再代表目前的選擇
            _save(state)
        return {"ok": True, "project": _view(state)}

    @app.post("/api/shotswap/{pid}/merge")
    def merge_project(pid: str):
        with _lock:
            state = _load(pid)
        try:
            final = merge(state)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        with _lock:
            fresh = _load(pid)
            fresh["final"] = str(final)
            fresh["merge_notes"] = state.get("merge_notes", [])
            _save(fresh)
        meta = {"id": pid, "title": fresh.get("title"), "status": "completed", "output": str(final),
                "character_swap": True, "shotswap": pid, "source_video": fresh["source_name"],
                "shots": [{k: x.get(k) for k in ("start", "end", "action", "review", "prompt", "seed", "output")}
                          for x in fresh["shots"]], "finished_at": runner.now_iso()}
        final.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "project": _view(fresh)}
