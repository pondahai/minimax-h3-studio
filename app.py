import os
import sys
import json
import time
import uuid
import shutil
import threading
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
STATIC_DIR = BASE_DIR / "static"
PROGRESS_FILE = BASE_DIR / "current_progress.json"

for d in (UPLOADS_DIR, OUTPUTS_DIR, STATIC_DIR):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="MiniMax H3 Colab Studio", version="1.0.0")

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

# State management
generation_lock = threading.Lock()
active_generation_thread: Optional[threading.Thread] = None
current_state = {
    "is_running": False,
    "task": None,
    "status": "idle",
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


@app.post("/api/upload")
async def upload_images(files: List[UploadFile] = File(...)):
    """Upload 1-9 reference images for inference."""
    uploaded = []
    for file in files:
        file_ext = Path(file.filename).suffix or ".png"
        saved_filename = f"ref_{uuid.uuid4().hex[:8]}_{Path(file.filename).stem[:24]}{file_ext}"
        saved_path = UPLOADS_DIR / saved_filename
        with open(saved_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        uploaded.append({
            "filename": saved_filename,
            "original_name": file.filename,
            "path": str(saved_path),
            "url": f"/uploads/{saved_filename}",
        })
    return {"ok": True, "files": uploaded}


class GenerateRequest(BaseModel):
    title: Optional[str] = "MiniMax Video"
    reference_images: List[str]
    prompt: str
    duration_seconds: int = 12
    gpu: str = "A100"
    high_mem: bool = True
    timeout: int = 3600
    seed: Optional[int] = None
    output_name: Optional[str] = None


def _background_worker(manifest_data: dict, gpu: str, high_mem: bool, timeout: int):
    global current_state
    manifest_path = BASE_DIR / f".manifest_{uuid.uuid4().hex[:8]}.json"
    manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8")

    current_state["is_running"] = True
    current_state["status"] = "starting"
    current_state["error"] = None
    current_state["log_tail"] = ["Initializing Colab runtime session..."]

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
        current_state["log_tail"].append("Batch execution finished successfully.")
        
        # Save metadata for history
        for job in result.get("jobs", []):
            meta_file = OUTPUTS_DIR / f"{Path(job['output']).stem}.json"
            meta_file.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    except Exception as exc:
        current_state["status"] = "failed"
        current_state["error"] = str(exc)
        current_state["is_running"] = False
        current_state["log_tail"].append(f"Error: {exc}")
    finally:
        manifest_path.unlink(missing_ok=True)


@app.post("/api/generate")
def start_generation(req: GenerateRequest):
    """Trigger MiniMax H3 reference-to-video generation."""
    global active_generation_thread
    with generation_lock:
        if current_state["is_running"]:
            raise HTTPException(status_code=400, detail="Another generation task is already running.")

        if not (1 <= len(req.reference_images) <= 9):
            raise HTTPException(status_code=400, detail="Requires 1 to 9 reference images.")

        if not (4 <= req.duration_seconds <= 15):
            raise HTTPException(status_code=400, detail="Duration must be between 4 and 15 seconds.")

        # Resolve image paths
        resolved_images = []
        for img in req.reference_images:
            p = Path(img)
            if not p.is_absolute():
                p = UPLOADS_DIR / p.name
            if not p.is_file():
                raise HTTPException(status_code=400, detail=f"Image not found: {img}")
            resolved_images.append(str(p))

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
        return {"ok": True, "job_id": job_id, "message": "Generation started on Google Colab"}


@app.get("/api/status")
def get_status():
    """Poll live progress and logs."""
    progress = {}
    if PROGRESS_FILE.is_file():
        try:
            progress = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "ok": True,
        "is_running": current_state["is_running"],
        "status": progress.get("status") or current_state["status"],
        "session": progress.get("session") or current_state["session"],
        "gpu": progress.get("gpu"),
        "jobs": progress.get("jobs", []),
        "log_tail": progress.get("log_tail", current_state["log_tail"]),
        "updated_at": progress.get("updated_at") or current_state["updated_at"],
        "error": current_state["error"],
    }


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
    print("[*] MiniMax H3 Colab Studio is launching at: http://localhost:7860")
    print("=" * 60 + "\n")
    uvicorn.run("app:app", host="0.0.0.0", port=7860, reload=False)
