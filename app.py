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


# LLM 提示詞擴寫：OpenAI 相容的 /v1/chat/completions（llama.cpp、Ollama、LM Studio、雲端皆可）
LLM_BASE_URL = os.environ.get("H3_LLM_BASE_URL", "http://localhost:8080/v1").rstrip("/")
LLM_MODEL = os.environ.get("H3_LLM_MODEL", "")  # 空白 = 用伺服器第一個模型
LLM_API_KEY = os.environ.get("H3_LLM_API_KEY", "")
LLM_TIMEOUT = float(os.environ.get("H3_LLM_TIMEOUT", "180"))
LLM_THINKING = os.environ.get("H3_LLM_THINKING", "1") == "1"  # Qwen3 等推理模型先推理再作答

EXPAND_SYSTEM_PROMPT = """You write prompts for MiniMax H3, a reference-to-video model that generates video with synchronized audio.
Output ONLY the final prompt in English: one paragraph, no title, no markdown, no explanation.

Rules:
- Refer to reference images exactly as <Picture 1> ... <Picture N>, reference videos as <Video 1> ... <Video N>, reference audio as <Audio 1> ... <Audio N>. Only use tags for assets that exist.
- Describe who the subject is (tie them to their <Picture N>), what they do moment by moment, camera framing and movement, setting, lighting, and the soundscape.
- Spoken lines go inside <d>[Chinese] ...</d> (or <d>[English] ...</d>), preceded by who speaks, e.g. The woman says, <d>[Chinese] 你好。</d>
- Keep actions physically plausible and paced to fit the requested duration.
- Write the user's idea faithfully; add concrete visual detail, never change its intent.
- When frames of a reference video are attached, describe its setting, subjects, camera and action exactly as the frames show them; never relocate or reinvent what <Video N> contains.
- When no frames of a reference video are attached, you cannot see it: do not invent its setting, subjects or action; describe it only as the user's idea does."""

EXPAND_SWAP_RULES = """Character swap mode: <Video 1> is the source performance, <Picture 1> is the new character.
- Start with: Replace the [describe the person in <Video 1>] in <Video 1> with the character from <Picture 1>.
- State to keep the reference character's face, hair, body and clothing from <Picture 1> (unless the user says otherwise); describe that look briefly if the image is attached.
- Follow the source performance's pose, gaze, expression, movement and timing; describe the actions concretely, in the order the frames show them.
- Preserve the scene, camera, other people and the original audio of <Video 1>.
- This is a replacement from the first frame, not a transformation: never describe dissolving, morphing or one figure turning into another.
- Do not invent dialogue; the original audio is kept.
- Do not invent exact timestamps, prop types or outcomes that neither the frames nor the user's idea show."""

LLM_VISION = os.environ.get("H3_LLM_VISION", "1") == "1"  # 把參考圖與影片畫面一起送給支援看圖的 LLM
LLM_VIDEO_FRAMES = 6


class ExpandPromptRequest(BaseModel):
    idea: str
    current_prompt: Optional[str] = ""
    image_count: int = 0
    video_count: int = 0
    audio_count: int = 0
    character_swap: bool = False
    duration_seconds: float = 12
    image_paths: Optional[List[str]] = []
    video_path: Optional[str] = None


def _upload_file(path: Optional[str]) -> Optional[Path]:
    """Only read files the user uploaded (or generated) through Studio."""
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = UPLOADS_DIR / p.name
    p = p.resolve()
    if p.is_file() and any(p.is_relative_to(d.resolve()) for d in (UPLOADS_DIR, OUTPUTS_DIR)):
        return p
    return None


def _jpeg_data_url(frame, max_side: int = 768) -> str:
    import base64
    h, w = frame.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def _vision_parts(req: "ExpandPromptRequest") -> tuple:
    """Reference images and evenly spaced video frames as chat image parts, plus the video length."""
    parts: List[dict] = []
    video_seconds = None
    if cv2 is None:
        return parts, video_seconds
    for index, path in enumerate((req.image_paths or [])[:4], start=1):
        p = _upload_file(path)
        image = cv2.imread(str(p)) if p else None
        if image is not None:
            parts += [{"type": "text", "text": f"<Picture {index}>:"},
                      {"type": "image_url", "image_url": {"url": _jpeg_data_url(image)}}]
    video = _upload_file(req.video_path)
    if video:
        cap = cv2.VideoCapture(str(video))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 24
        if total > 0:
            video_seconds = total / fps
            parts.append({"type": "text", "text": f"Frames of <Video 1> in order ({video_seconds:.1f} s long):"})
            for i in range(LLM_VIDEO_FRAMES):
                index = int(i * (total - 1) / (LLM_VIDEO_FRAMES - 1))
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = cap.read()
                if ok:
                    parts += [{"type": "text", "text": f"t={index / fps:.1f}s"},
                              {"type": "image_url", "image_url": {"url": _jpeg_data_url(frame)}}]
        cap.release()
    return parts, video_seconds


def _llm_chat(messages: List[Dict[str, Any]]) -> str:
    import urllib.request
    import re

    def call(path: str, payload: Optional[dict] = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if LLM_API_KEY:
            headers["Authorization"] = f"Bearer {LLM_API_KEY}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(LLM_BASE_URL + path, data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=LLM_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    model = LLM_MODEL or call("/models")["data"][0]["id"]
    result = call("/chat/completions", {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        # 推理內容另計 token，開 thinking 時要留足空間，否則正文會被截掉
        "max_tokens": 8000 if LLM_THINKING else 1500,
        "chat_template_kwargs": {"enable_thinking": LLM_THINKING},
    })
    text = (result["choices"][0]["message"].get("content") or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if not text:
        raise RuntimeError("LLM 沒有回傳內容。")
    return text


@app.post("/api/expand_prompt")
def expand_prompt(req: ExpandPromptRequest):
    """Expand a short idea (or refine the current prompt) into a full H3 prompt via an LLM."""
    if not req.idea.strip() and not (req.current_prompt or "").strip():
        raise HTTPException(status_code=400, detail="請先輸入構想或現有提示詞。")
    parts, video_seconds = _vision_parts(req) if LLM_VISION else ([], None)
    assets = (f"Available assets: {req.image_count} image(s), {req.video_count} video(s), "
              f"{req.audio_count} audio clip(s). Requested duration: {req.duration_seconds:g} seconds.")
    if video_seconds:
        assets += f" <Video 1> is {video_seconds:.1f} seconds long."
    system = EXPAND_SYSTEM_PROMPT + ("\n\n" + EXPAND_SWAP_RULES if req.character_swap else "")
    user = assets + "\n\nUser idea (may be in Chinese):\n" + (req.idea.strip() or "(none)")
    if (req.current_prompt or "").strip():
        user += "\n\nCurrent prompt to improve (keep what still fits the idea):\n" + req.current_prompt.strip()
    text_only = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    used_vision = bool(parts)
    try:
        if parts:
            try:
                prompt = _llm_chat([text_only[0], {"role": "user", "content": [{"type": "text", "text": user}, *parts]}])
            except Exception:
                # LLM 不支援看圖時退回純文字
                used_vision = False
                prompt = _llm_chat(text_only)
        else:
            prompt = _llm_chat(text_only)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM 擴寫失敗（{LLM_BASE_URL}）：{exc}")
    return {"ok": True, "prompt": prompt, "used_vision": used_vision}


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
    reference_videos: Optional[List[str]] = []
    character_swap: bool = False
    aspect: Optional[str] = "landscape"
    text_encoder: Optional[str] = "heretic"
    prompt: str
    duration_seconds: int = 12
    gpu: str = "A100"
    high_mem: bool = True
    timeout: int = 1500
    seed: Optional[int] = None
    output_name: Optional[str] = None


def _job_settings(job: dict) -> dict:
    """Inputs worth keeping next to an output: the prompt and what it was generated from."""
    names = lambda paths: [Path(p).name for p in paths or []]
    return {
        "prompt": job.get("prompt"),
        "mode": job.get("mode"),
        "character_swap": job.get("character_swap", False),
        "aspect": job.get("aspect"),
        "text_encoder": job.get("text_encoder", "official"),
        "requested_seconds": job.get("duration_seconds"),
        "reference_images": names(job.get("reference_images")),
        "reference_audios": names(job.get("reference_audios")),
        "reference_videos": names(job.get("reference_videos")),
    }


def _background_worker(manifest_data: dict, gpu: str, high_mem: bool, timeout: int):
    global current_state
    manifest_path = BASE_DIR / f".manifest_{uuid.uuid4().hex[:8]}.json"
    manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8")

    current_state["is_running"] = True
    current_state["task"] = "single"
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

        # Save metadata for history（連同提示詞與輸入設定，方便事後檢討與重現）
        settings = {j["id"]: _job_settings(j) for j in manifest_data["jobs"]}
        for job in result.get("jobs", []):
            meta_file = OUTPUTS_DIR / f"{Path(job['output']).stem}.json"
            meta = {**job, **settings.get(job.get("id"), {})}
            meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

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

        # Resolve video paths (<Video 1>–<Video 3>)
        resolved_videos = []
        for vid in (req.reference_videos or []):
            vp = Path(vid)
            if not vp.is_absolute():
                vp = UPLOADS_DIR / vp.name
            if not vp.is_file():
                raise HTTPException(status_code=400, detail=f"找不到參照影片：{vid}")
            resolved_videos.append(str(vp))
        if len(resolved_videos) > 3:
            raise HTTPException(status_code=400, detail="最多 3 支參照影片。")
        if req.character_swap and not resolved_videos:
            raise HTTPException(status_code=400, detail="換人模式需要上傳一支原片。")

        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        output_name = req.output_name or f"h3_{job_id}"
        if not output_name.endswith(".mp4"):
            output_name += ".mp4"

        mode_val = "first_frame" if str(req.mode or "").lower() in ("fl2va", "first_frame") else "reference"
        manifest_data = {
            "jobs": [
                {
                    "id": job_id,
                    "title": req.title or "MiniMax H3 Video",
                    "mode": mode_val,
                    "reference_images": resolved_images,
                    "reference_audios": resolved_audios,
                    "reference_videos": resolved_videos,
                    "character_swap": req.character_swap,
                    "aspect": "portrait" if req.aspect == "portrait" else "landscape",
                    "text_encoder": req.text_encoder or "heretic",
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


# 長片分段換人：原片切成 ≤ 8 秒的段落，依序換人（上一段結尾畫面當下一段的接續參考），最後接成一支
LONG_SWAP_MAX_SEGMENT = 8.0
LONG_SWAP_CONTINUITY = (
    " The video starts exactly like <Picture {n}>: same person, same pose, same framing and lighting;"
    " <Picture {n}> is only a continuity frame, the character identity still comes from <Picture 1>."
)


class LongSwapRequest(BaseModel):
    title: Optional[str] = "Long Character Swap"
    reference_images: List[str]
    source_video: str
    aspect: Optional[str] = "landscape"
    text_encoder: Optional[str] = "heretic"
    prompt: str
    gpu: str = "A100"
    high_mem: bool = True
    timeout: int = 1500
    seed: Optional[int] = None


def _ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("找不到 ffmpeg，長片分段換人需要 ffmpeg 切段與合併（請安裝並加入 PATH）。")
    return path


def _run_ffmpeg(args: List[str]) -> None:
    import subprocess
    proc = subprocess.run([_ffmpeg_path(), "-v", "error", "-y", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失敗：{proc.stderr.strip()[-400:]}")


def _video_duration(path: Path) -> float:
    cap = cv2.VideoCapture(str(path))
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    cap.release()
    if frames <= 0 or fps <= 0:
        raise RuntimeError(f"無法讀取影片長度：{path.name}")
    return frames / fps


def _frame_at(video: Path, seconds: float, out_path: Path) -> None:
    """Save the frame shown at `seconds` (the segment's cut point, not the generated tail)."""
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(total - 1, round(seconds * fps) - 1)))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"無法擷取接續畫面：{video.name}")
    cv2.imwrite(str(out_path), frame)


def plan_segments(duration: float) -> List[tuple]:
    count = max(1, int(-(-duration // LONG_SWAP_MAX_SEGMENT)))
    length = duration / count
    return [(i * length, length) for i in range(count)]


def _long_swap_worker(req: LongSwapRequest, images: List[str], source: Path, segments: List[tuple]):
    global current_state
    run_id = f"long_{int(time.time())}_{uuid.uuid4().hex[:4]}"
    work = UPLOADS_DIR / run_id
    work.mkdir(parents=True, exist_ok=True)
    session = f"h3-{run_id}".replace("_", "-")
    seed = req.seed if req.seed is not None else int(time.time()) % 1000000
    outputs: List[Path] = []

    current_state.update({
        "is_running": True, "task": "long_swap", "status": "starting", "stage": 1, "error": None,
        "session": session, "segment": 0, "segment_count": len(segments), "jobs": [],
        "stage_label": "建立 Colab GPU 執行階段",
        "log_tail": [f"[*] 長片分段換人：{len(segments)} 段，每段約 {segments[0][1]:.1f} 秒"],
    })
    try:
        runner.start_session(session, req.gpu, req.high_mem)
        continuity: Optional[Path] = None
        for index, (start, length) in enumerate(segments):
            if not current_state["is_running"]:
                raise RuntimeError("任務已取消。")
            current_state["segment"] = index + 1
            current_state["status"] = "running"
            clip = work / f"source_{index + 1:02d}.mp4"
            _run_ffmpeg(["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(source),
                         "-c:v", "libx264", "-crf", "18", "-c:a", "aac", str(clip)])

            refs = list(images)
            prompt = req.prompt
            if continuity is not None:
                refs.append(str(continuity))
                prompt += LONG_SWAP_CONTINUITY.format(n=len(refs))
            job_id = f"{run_id}_seg{index + 1:02d}"
            manifest = {"jobs": [{
                "id": job_id,
                "title": f"{req.title} {index + 1}/{len(segments)}",
                "mode": "reference",
                "reference_images": refs,
                "reference_audios": [],
                "reference_videos": [str(clip)],
                "character_swap": True,
                "aspect": "portrait" if req.aspect == "portrait" else "landscape",
                "text_encoder": req.text_encoder or "heretic",
                "prompt": prompt,
                # 生成長度會向上對齊；要求整數秒向上取整，合併時再裁回原片段長度以保持時間軸同步
                "duration_seconds": max(4, int(-(-length // 1))),
                "seed": seed,
                "output_name": f"{job_id}.mp4",
            }]}
            manifest_path = BASE_DIR / f".manifest_{job_id}.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                result = runner.run_batch(
                    manifest_path, session=session, gpu=req.gpu, high_mem=req.high_mem,
                    stop_on_complete=False, progress_path=PROGRESS_FILE, output_dir=OUTPUTS_DIR,
                    exec_timeout=req.timeout,
                )
            finally:
                manifest_path.unlink(missing_ok=True)
            job = next((j for j in result.get("jobs", []) if j.get("status") == "completed"), None)
            if not job:
                raise RuntimeError(result.get("error") or f"第 {index + 1} 段生成失敗。")
            output = Path(job["output"])
            meta = {**job, **_job_settings(manifest["jobs"][0])}
            (OUTPUTS_DIR / f"{output.stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            outputs.append(output)
            current_state["log_tail"].append(f"[*] 第 {index + 1}/{len(segments)} 段完成")
            if index + 1 < len(segments):
                continuity = work / f"continuity_{index + 1:02d}.png"
                _frame_at(output, length, continuity)

        current_state["status"] = "merging"
        final = OUTPUTS_DIR / f"{run_id}_full.mp4"
        inputs: List[str] = []
        chains = []
        for i, (path, (_, length)) in enumerate(zip(outputs, segments)):
            inputs += ["-i", str(path)]
            chains.append(f"[{i}:v]trim=0:{length:.3f},setpts=PTS-STARTPTS[v{i}];"
                          f"[{i}:a]atrim=0:{length:.3f},asetpts=PTS-STARTPTS[a{i}]")
        joined = "".join(f"[v{i}][a{i}]" for i in range(len(outputs)))
        graph = ";".join(chains) + f";{joined}concat=n={len(outputs)}:v=1:a=1[v][a]"
        _run_ffmpeg([*inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
                     "-c:v", "libx264", "-crf", "18", "-c:a", "aac", str(final)])
        meta = {"id": run_id, "title": req.title, "status": "completed", "output": str(final),
                "segments": [str(p) for p in outputs], "seed": seed, "finished_at": runner.now_iso(),
                "prompt": req.prompt, "character_swap": True, "aspect": req.aspect,
                "text_encoder": req.text_encoder or "heretic",
                "reference_images": [Path(p).name for p in images], "source_video": source.name}
        (OUTPUTS_DIR / f"{final.stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        current_state["jobs"] = [meta]
        current_state["status"] = "completed"
        current_state["log_tail"].append(f"[*] 已合併 {len(outputs)} 段：{final.name}")
    except Exception as exc:
        if current_state["status"] != "cancelled":
            current_state["status"] = "failed"
            current_state["error"] = str(exc)
        current_state["log_tail"].append(f"錯誤：{exc}")
    finally:
        try:
            runner.stop_session(session)
        except Exception:
            runner.emergency_stop_session(session)
        current_state["is_running"] = False
        shutil.rmtree(work, ignore_errors=True)


@app.post("/api/generate_long_swap")
def start_long_swap(req: LongSwapRequest):
    """Character-swap a source video longer than one H3 clip by chaining short segments."""
    global active_generation_thread
    with generation_lock:
        if current_state["is_running"]:
            raise HTTPException(status_code=400, detail="另一個影片生成任務正在進行中。")
        if cv2 is None:
            raise HTTPException(status_code=500, detail="OpenCV (cv2) is not installed.")
        try:
            _ffmpeg_path()
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        if not (1 <= len(req.reference_images) <= 8):
            raise HTTPException(status_code=400, detail="需要 1 到 8 張參照圖片（保留一格給接續畫面）。")

        images = []
        for img in req.reference_images:
            p = Path(img)
            if not p.is_absolute():
                p = UPLOADS_DIR / p.name
            if not p.is_file():
                raise HTTPException(status_code=400, detail=f"找不到參照圖片：{img}")
            images.append(str(p))
        source = Path(req.source_video)
        if not source.is_absolute():
            source = UPLOADS_DIR / source.name
        if not source.is_file():
            raise HTTPException(status_code=400, detail=f"找不到原片：{req.source_video}")

        duration = _video_duration(source)
        if duration < 4:
            raise HTTPException(status_code=400, detail="原片至少要 4 秒。")
        segments = plan_segments(duration)

        current_state["is_running"] = True
        active_generation_thread = threading.Thread(
            target=_long_swap_worker, args=(req, images, source, segments), daemon=True,
        )
        active_generation_thread.start()
        return {"ok": True, "segments": len(segments), "segment_seconds": round(segments[0][1], 2),
                "message": f"已排入 {len(segments)} 段換人任務"}


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
    long_swap = current_state.get("task") == "long_swap"
    if long_swap:
        # 每段 run_batch 都會把進度檔寫成 completed；整體結果以長片 worker 的狀態為準
        if not current_state["is_running"] or current_state["status"] in ("starting", "merging"):
            status_str = current_state["status"]
        elif status_str in ("completed", "failed", "partial"):
            status_str = "running"

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
    elif status_str == "merging":
        stage = 4
        stage_label = "4/5 合併各段影片"
        progress_percent = 95
    elif status_str == "cancelled":
        stage = 0
        stage_label = current_state["stage_label"]

    jobs = progress.get("jobs", [])
    log_tail = progress.get("log_tail", current_state["log_tail"])
    if long_swap:
        if current_state["is_running"] and current_state.get("segment"):
            stage_label = f"第 {current_state['segment']}/{current_state['segment_count']} 段 · {stage_label}"
        jobs = current_state["jobs"]
        log_tail = (current_state["log_tail"] + progress.get("log_tail", [])[-15:])[-30:]

    return {
        "ok": True,
        "is_running": current_state["is_running"],
        "status": status_str,
        "stage": stage,
        "stage_label": stage_label,
        "progress_percent": progress_percent,
        "session": progress.get("session") or current_state["session"],
        "gpu": progress.get("gpu"),
        "jobs": jobs,
        "log_tail": log_tail,
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
