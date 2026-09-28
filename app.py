import os
import sys
import json
import time
import uuid
import shutil
import threading
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    import cv2
except ImportError:
    cv2 = None

BASE_DIR = Path(__file__).resolve().parent
LOCAL_SCRIPTS = BASE_DIR / "scripts"
GLOBAL_SCRIPTS = Path.home() / ".agents" / "skills" / "minimax-h3-colab" / "scripts"

if LOCAL_SCRIPTS.is_dir():
    if str(LOCAL_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(LOCAL_SCRIPTS))
elif GLOBAL_SCRIPTS.is_dir():
    if str(GLOBAL_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(GLOBAL_SCRIPTS))

import runner

UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
STATIC_DIR = BASE_DIR / "static"
PROGRESS_FILE = BASE_DIR / "current_progress.json"

for d in (UPLOADS_DIR, OUTPUTS_DIR, STATIC_DIR):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="MiniMax H3 Colab Studio 2.0", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

generation_lock = threading.Lock()
active_generation_thread: Optional[threading.Thread] = None
current_state = {
    "is_running": False,
    "task": None,
    "status": "idle",
    "stage": 0,
    "stage_label": "系統就緒",
    "session": None,
    "current_job": None,
    "jobs": [],
    "log_tail": [],
    "updated_at": None,
    "error": None,
}

balance_cache = {
    "data": None,
    "last_fetched": 0,
}

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=404, detail="index.html not found")
    return index_file.read_text(encoding="utf-8")


@app.get("/api/balance")
def get_balance(force_refresh: bool = False):
    """Fetch current Colab compute-unit balance and status."""
    now = time.time()
    if not force_refresh and balance_cache["data"] and (now - balance_cache["last_fetched"] < 30):
        return balance_cache["data"]

    try:
        usage = runner.get_usage()
        result = {
            "ok": True,
            "balance": usage["balance"],
            "rate_per_hour": usage["rate_per_hour"],
            "active_assignments": usage["active_assignments"],
            "checked_at": usage["checked_at"],
        }
        balance_cache["data"] = result
        balance_cache["last_fetched"] = now
        return result
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "checked_at": runner.now_iso(),
        }


@app.post("/api/upload")
async def upload_assets(files: List[UploadFile] = File(...)):
    """Upload multi-modal reference assets: images, audio, or video."""
    uploaded = []
    image_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    audio_exts = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
    video_exts = {".mp4", ".mov", ".webm", ".mkv"}

    for file in files:
        ext = Path(file.filename).suffix.lower() or ".bin"
        if ext in image_exts:
            asset_type = "image"
            prefix = "ref_img"
        elif ext in audio_exts:
            asset_type = "audio"
            prefix = "ref_audio"
        elif ext in video_exts:
            asset_type = "video"
            prefix = "ref_video"
        else:
            asset_type = "other"
            prefix = "ref_file"

        saved_filename = f"{prefix}_{uuid.uuid4().hex[:8]}_{Path(file.filename).stem[:20]}{ext}"
        saved_path = UPLOADS_DIR / saved_filename
        with open(saved_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        uploaded.append({
            "filename": saved_filename,
            "original_name": file.filename,
            "path": str(saved_path),
            "url": f"/uploads/{saved_filename}",
            "type": asset_type,
            "size": saved_path.stat().st_size,
        })
    return {"ok": True, "files": uploaded}


class ExtractLastFrameRequest(BaseModel):
    video_filename: str


@app.post("/api/extract_last_frame")
def extract_last_frame(req: ExtractLastFrameRequest):
    """Extract the very last frame of a generated video for continuation."""
    video_path = OUTPUTS_DIR / Path(req.video_filename).name
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found.")

    if cv2 is None:
        raise HTTPException(status_code=500, detail="OpenCV (cv2) is not installed.")

    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        raise HTTPException(status_code=400, detail="Could not read video frames.")

    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total_frames - 1))
    ret, frame = cap.read()
    cap.release()

    if not ret:
        raise HTTPException(status_code=500, detail="Failed to capture last frame.")

    frame_filename = f"last_frame_{int(time.time())}_{uuid.uuid4().hex[:6]}.png"
    frame_path = UPLOADS_DIR / frame_filename
    cv2.imwrite(str(frame_path), frame)

    return {
        "ok": True,
        "filename": frame_filename,
        "url": f"/uploads/{frame_filename}",
        "path": str(frame_path),
        "total_frames": total_frames,
    }


class AICoPilotRequest(BaseModel):
    concept: str
    genre: Optional[str] = "cinematic"
    has_audio: bool = False
    has_image: bool = True
    image_count: int = 1


@app.post("/api/ai_copilot")
def ai_copilot(req: AICoPilotRequest):
    """Built-in creative AI copilot that generates complete Ref2VA structures."""
    concept = req.concept.strip() or "A cinematic moment with rich atmosphere."
    genre = req.genre or "cinematic"

    audio_clause = " S1 speaks with the exact vocal timbre, pitch, and accent of <Audio 1>." if req.has_audio else ""
    audio_shot = " S1 speaks with the voice of <Audio 1>, saying, <d>[Chinese] 很高興與你相遇，期待我們接下來的旅程。</d>" if req.has_audio else " S1 smiles gently, saying, <d>[Chinese] 很高興與你相遇，期待我們接下來的旅程。</d>"

    templates = {
        "cinematic": {
            "subject": f"The subject (S1) is the character from <Picture 1>.{audio_clause}",
            "summary": f"Cinematic narrative sequence: {concept}",
            "retention": "Retain key facial features, outfit texture, lighting mood, and overall character consistency from <Picture 1>.",
            "shot1": f"The camera slowly dollies in on S1 in warm cinematic lighting as S1 turns toward the lens.{audio_shot}",
            "shot2": "the camera cuts to a close-up tracking shot capturing S1's expressive eyes and subtle head motion under atmospheric bokeh.",
            "soundscape": "Gentle outdoor breeze, soft urban ambience, and subtle organic footsteps.",
            "music": "Warm cinematic strings with emotive acoustic piano chords.",
        },
        "scifi": {
            "subject": f"The subject (S1) is the futuristic operative from <Picture 1>.{audio_clause}",
            "summary": f"Cyberpunk sci-fi sequence: {concept}",
            "retention": "Retain cybernetic details, neon reflections, costume design, and facial features from <Picture 1>.",
            "shot1": f"The camera pans smoothly across the rainy neon-lit street as S1 steps forward into the glow.{audio_shot}",
            "shot2": "the camera cuts to a dynamic low-angle tracking shot as neon reflections gleam on S1's jacket.",
            "soundscape": "Continuous city rainfall, distant hovercraft hums, and neon sign electric buzzing.",
            "music": "Pulsing synthwave bassline with dark analog synthesizer textures.",
        },
        "commercial": {
            "subject": f"The subject (S1) is the charismatic presenter from <Picture 1>.{audio_clause}",
            "summary": f"High-end commercial showcase: {concept}",
            "retention": "Preserve immaculate lighting, professional wardrobe, and confident expression from <Picture 1>.",
            "shot1": f"The camera glides smoothly around S1 in clean modern studio lighting as S1 looks engagingly at the viewer.{audio_shot}",
            "shot2": "the camera cuts to an elegant medium shot emphasizing S1's poised demeanor with modern lifestyle backdrop.",
            "soundscape": "Clean studio acoustic ambience with subtle room resonance.",
            "music": "Uplifting, optimistic modern acoustic guitar with crisp percussion.",
        },
        "dialogue": {
            "subject": f"The subject (S1) is the character from <Picture 1>.{audio_clause}",
            "summary": f"Emotional character monologue: {concept}",
            "retention": "Retain subtle facial expressions, micro-emotions, and distinctive features from <Picture 1>.",
            "shot1": f"A stationary medium close-up frames S1 under soft window lighting as S1 begins speaking with poignant emotion.{audio_shot}",
            "shot2": "the camera cuts to a tight close-up emphasizing S1's lips and eyes conveying heartfelt sincerity.",
            "soundscape": "Quiet interior room tone with gentle rain tapping on the windowpane.",
            "music": "Subtle melancholic cello layered with soft felt piano notes.",
        },
    }

    selected = templates.get(genre, templates["cinematic"])
    shots = [
        {"start_seconds": 0.0, "description": selected["shot1"]},
        {"start_seconds": 6.0, "description": selected["shot2"]},
    ]

    return {
        "ok": True,
        "subject_definitions": selected["subject"],
        "summary": selected["summary"],
        "retention_analysis": selected["retention"],
        "shots": shots,
        "overall_soundscape": selected["soundscape"],
        "non_diegetic_music": selected["music"],
    }


class ShotItem(BaseModel):
    start_seconds: float
    description: str
    dialogue: Optional[str] = ""
    speaker: Optional[str] = "The subject (S1)"


class Ref2VAPromptRequest(BaseModel):
    subject_definitions: str
    summary: str
    retention_analysis: str
    shots: List[ShotItem]
    overall_soundscape: str
    non_diegetic_music: str
    image_count: int
    duration_seconds: float
    detailed_description: Optional[str] = ""


@app.post("/api/compose_prompt")
def compose_prompt(req: Ref2VAPromptRequest):
    """Compose and validate structured Ref2VA prompt using skill runner."""
    try:
        shots_data = [shot.model_dump() for shot in req.shots]
        prompt = runner.compose_ref2va_prompt(
            subject_definitions=req.subject_definitions,
            summary=req.summary,
            retention_analysis=req.retention_analysis,
            shots=shots_data,
            overall_soundscape=req.overall_soundscape,
            non_diegetic_music=req.non_diegetic_music,
            image_count=req.image_count,
            duration_seconds=req.duration_seconds,
            detailed_description=req.detailed_description or "",
        )
        return {"ok": True, "prompt": prompt}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


class GenerateRequest(BaseModel):
    title: Optional[str] = "MiniMax Video"
    mode: Optional[str] = "ref2va"
    reference_images: List[str]
    reference_audios: Optional[List[str]] = []
    prompt: str
    duration_seconds: int = 12
    gpu: str = "A100"
    high_mem: bool = True
    timeout: int = 1500
    seed: Optional[int] = None
    output_name: Optional[str] = None


def _background_worker(manifest_data: dict, gpu: str, high_mem: bool, timeout: int):
    global current_state
    manifest_path = BASE_DIR / f".manifest_{uuid.uuid4().hex[:8]}.json"
    manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8")

    current_state["is_running"] = True
    current_state["status"] = "starting"
    current_state["stage"] = 1
    current_state["stage_label"] = "申請分配 Google Colab A100 GPU"
    current_state["error"] = None
    current_state["log_tail"] = ["[*] 正在建立 Google Colab 雲端工作階段 (Session)..."]

    try:
        result = runner.run_batch(
            manifest_path,
            session=None,
            gpu=gpu,
            high_mem=high_mem,
            stop_on_complete=True,
            progress_path=PROGRESS_FILE,
            output_dir=OUTPUTS_DIR,
            exec_timeout=timeout,
        )
        current_state["status"] = result.get("status", "completed")
        current_state["is_running"] = False
        current_state["stage"] = 5
        current_state["stage_label"] = "影片已完成並下載至本地"
        current_state["log_tail"].append("[*] 批次生成完成，Colab Session 已安全關閉。")

        # Save metadata for history
        for job in result.get("jobs", []):
            meta_file = OUTPUTS_DIR / f"{Path(job['output']).stem}.json"
            meta_file.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    except Exception as exc:
        current_state["status"] = "failed"
        current_state["error"] = str(exc)
        current_state["is_running"] = False
        current_state["stage"] = 0
        current_state["stage_label"] = "生成中斷"
        current_state["log_tail"].append(f"錯誤：{exc}")
    finally:
        manifest_path.unlink(missing_ok=True)


@app.post("/api/generate")
def start_generation(req: GenerateRequest):
    """Trigger MiniMax H3 reference-to-video generation."""
    global active_generation_thread
    with generation_lock:
        if current_state["is_running"]:
            raise HTTPException(status_code=400, detail="另一個影片生成任務正在進行中。")

        if not (1 <= len(req.reference_images) <= 9):
            raise HTTPException(status_code=400, detail="需要提供 1 到 9 張參照圖片。")

        if not (4 <= req.duration_seconds <= 15):
            raise HTTPException(status_code=400, detail="影片秒數必須介於 4 到 15 秒之間。")

        # Resolve image paths
        resolved_images = []
        for img in req.reference_images:
            p = Path(img)
            if not p.is_absolute():
                p = UPLOADS_DIR / p.name
            if not p.is_file():
                raise HTTPException(status_code=400, detail=f"找不到參照圖片：{img}")
            resolved_images.append(str(p))

        # Resolve audio paths
        resolved_audios = []
        for aud in (req.reference_audios or []):
            ap = Path(aud)
            if not ap.is_absolute():
                ap = UPLOADS_DIR / ap.name
            if ap.is_file():
                resolved_audios.append(str(ap))

        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        output_name = req.output_name or f"h3_{job_id}"
        if not output_name.endswith(".mp4"):
            output_name += ".mp4"

        manifest_data = {
            "jobs": [
                {
                    "id": job_id,
                    "title": req.title or "MiniMax H3 Video",
                    "reference_images": resolved_images,
                    "reference_audios": resolved_audios,
                    "prompt": req.prompt,
                    "duration_seconds": req.duration_seconds,
                    "seed": req.seed if req.seed is not None else int(time.time()) % 1000000,
                    "output_name": output_name,
                }
            ]
        }

        active_generation_thread = threading.Thread(
            target=_background_worker,
            args=(manifest_data, req.gpu, req.high_mem, req.timeout),
            daemon=True,
        )
        active_generation_thread.start()
        return {"ok": True, "job_id": job_id, "message": "任務已排入 Google Colab 佇列"}


@app.post("/api/cancel")
def cancel_generation():
    """Immediately abort current task and terminate remote Colab VM."""
    global current_state
    session = current_state.get("session")
    if not session and PROGRESS_FILE.is_file():
        try:
            p = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            session = p.get("session")
        except Exception:
            pass

    current_state["is_running"] = False
    current_state["status"] = "cancelled"
    current_state["stage"] = 0
    current_state["stage_label"] = "任務已手動取消，Colab 虛擬機已安全釋放"
    current_state["log_tail"].append("[*] 🛑 手動取消任務，正在強制釋放遠端 Colab...")

    if session:
        runner.emergency_stop_session(session)

    return {"ok": True, "message": "任務已中止並釋放 Colab 運算資源。"}


@app.get("/api/status")
def get_status():
    """Poll live progress, stage, logs and outputs."""
    progress = {}
    if PROGRESS_FILE.is_file():
        try:
            progress = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    status_str = progress.get("status") or current_state["status"]

    # Compute stages 1-5
    stage = current_state["stage"]
    stage_label = current_state["stage_label"]
    progress_percent = 0

    if status_str == "starting":
        stage = 1
        stage_label = "1/5 建立 Colab GPU 執行階段"
        progress_percent = 20
    elif status_str == "uploading":
        stage = 2
        stage_label = "2/5 上傳多模態素材至雲端"
        progress_percent = 40
    elif status_str in ("running", "generating"):
        stage = 3
        stage_label = "3/5 MiniMax H3 A100 GPU 取樣推論中"
        progress_percent = 75
    elif status_str == "downloading":
        stage = 4
        stage_label = "4/5 下載高畫質 MP4 成果"
        progress_percent = 90
    elif status_str == "completed":
        stage = 5
        stage_label = "5/5 完成！Colab 虛擬機已安全釋放"
        progress_percent = 100
    elif status_str == "failed":
        stage = 0
        stage_label = "任務失敗"
        progress_percent = 100

    return {
        "ok": True,
        "is_running": current_state["is_running"],
        "status": status_str,
        "stage": stage,
        "stage_label": stage_label,
        "progress_percent": progress_percent,
        "session": progress.get("session") or current_state["session"],
        "gpu": progress.get("gpu"),
        "jobs": progress.get("jobs", []),
        "log_tail": progress.get("log_tail", current_state["log_tail"]),
        "updated_at": progress.get("updated_at") or current_state["updated_at"],
        "error": current_state["error"] or progress.get("error"),
    }


@app.post("/api/stop")
def stop_generation():
    """Stop active Colab session immediately to prevent extra billing."""
    global current_state
    session = current_state.get("session")
    if PROGRESS_FILE.is_file():
        try:
            data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            session = session or data.get("session")
        except Exception:
            pass

    if session:
        try:
            runner.stop_session(session)
        except Exception as e:
            runner.emergency_stop_session(session)

    current_state["is_running"] = False
    current_state["status"] = "stopped"
    current_state["stage_label"] = "已手動停止"
    current_state["log_tail"].append("[*] 已發送停止信號，Colab Session 已關閉。")
    return {"ok": True, "message": "Colab session stopped."}


@app.get("/api/history")
def get_history():
    """Retrieve all previously generated videos."""
    videos = []
    for mp4 in sorted(OUTPUTS_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        meta_file = mp4.with_suffix(".json")
        meta = {}
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        videos.append({
            "filename": mp4.name,
            "url": f"/outputs/{mp4.name}",
            "size_mb": round(mp4.stat().st_size / (1024 * 1024), 2),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mp4.stat().st_mtime)),
            "metadata": meta,
        })
    return {"ok": True, "videos": videos}


if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 60)
    print("[*] MiniMax H3 Colab Studio 2.0 launching at: http://localhost:7860")
    print("=" * 60 + "\n")
    uvicorn.run("app:app", host="0.0.0.0", port=7860, reload=False)
