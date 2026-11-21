"""Generate 2 consistent soft-diffused matte-skin camera angles via Qwen-Image 2.1 (:8188) on DGX Spark.

  - Angle 1 (matte_angle1_front.png): Soft natural window daylight, front-3/4 medium close-up, matte skin texture.
  - Angle 2 (matte_angle2_side.png):  Same singer/outfit/room using Angle 1 as image1 reference, 45-degree side medium shot.
"""
import json
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

COMFY = "http://100.89.149.50:8188"
W, H = 1344, 768
SIGMAS = "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0.0"
NEGATIVE = (
    "油光, 油膩皮膚, 滿臉油光, 反光皮膚, 塑膠感皮膚, 過曝, 高對比, 暗黑背景, "
    "文字, 字母, 標題, 字幕, 浮水印, logo, text, letters, watermark, "
    "oily skin, glossy skin, shiny face, sweaty, plastic skin, overly smooth skin, harsh specular highlights"
)

PROMPT_ANGLE1 = (
    "日系底片質感寫實攝影，35mm 膠片微顆粒，柔和的靠窗自然漫射日光（無刺眼高光、無暗黑背光）。"
    "中近景，一位二十多歲的台灣年輕女性民謠歌手坐在明亮簡約的淺木色錄音室高腳椅上，"
    "懷中抱著原木色民謠木吉他，身穿淺燕麥色亞麻針織上衣，自然深棕色中長髮。"
    "她的臉部是自然清爽的霧面底妝與真實細緻膚質，完全沒有油光或反光，神情溫柔放鬆。"
    "一支霧面消光銀色電容式麥克風架在畫面左下側，位於她的嘴唇下方略微偏側，完全不遮擋她的嘴部與臉部。"
    "背景是柔和失焦的淺米白牆面、木質書架與透入柔和日光的紗簾窗戶，低對比柔光色調，畫面裡剛好只有這 1 個人，沒有任何文字或標誌。"
)

PROMPT_ANGLE2 = (
    "以參考圖中的同一位台灣年輕女性民謠歌手、相同臉孔、相同深棕色中長髮、相同淺燕麥色針織上衣、"
    "相同原木色民謠木吉他、相同消光銀色電容麥克風與相同明亮淺木色錄音室背景為準，"
    "改為從右側 45 度角拍攝的中景側拍機位（看得到更多吉他琴身與雙手彈奏姿勢，麥克風在她的右前方下方且不遮擋嘴唇）。"
    "保持相同的柔和自然窗光漫射光線、自然清爽霧面膚質（無油光、無反光）與 35mm 底片微顆粒感，畫面裡剛好只有這 1 個人，沒有任何文字或標誌。"
)


def stop_tts():
    subprocess.run(
        ["ssh", "-n", "-o", "ConnectTimeout=10", "funsteam@100.89.149.50",
         "pkill -f '[c]hinese_tts_server.py' || true"],
        capture_output=True, text=True, timeout=30,
    )


def ensure_comfy():
    try:
        urllib.request.urlopen(f"{COMFY}/system_stats", timeout=5).close()
        return
    except OSError:
        pass
    print("[*] 叫醒 ComfyUI (:8188)...", flush=True)
    r = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", "funsteam@100.89.149.50",
         "curl -s -m 280 -X POST http://127.0.0.1:8190/ensure"],
        capture_output=True, text=True, timeout=300,
    )
    if '"ok": true' not in r.stdout:
        raise SystemExit(f"ComfyUI 叫不醒：{r.stdout or r.stderr}")
    print("[*] ComfyUI 已就緒", flush=True)


def upload(path: Path) -> str:
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="matte_{uuid.uuid4().hex[:8]}.png"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{COMFY}/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)["name"]


def run_qwen(prompt: str, seed: int, prefix: str, dest: Path, ref_names: list[str] | None = None):
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_turbo_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image"}},
        "9": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}},
        "20": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS}},
        "21": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "6": {"class_type": "SamplerCustom", "inputs": {
            "model": ["9", 0], "add_noise": True, "noise_seed": seed, "cfg": 1.0,
            "positive": ["4", 0], "negative": ["4", 1], "sampler": ["21", 0],
            "sigmas": ["20", 0], "latent_image": ["5", 0],
        }},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["7", 0]}},
    }
    images = {}
    for i, name in enumerate(ref_names or [], 1):
        wf[str(100 + i)] = {"class_type": "LoadImage", "inputs": {"image": name}}
        images[f"image{i}"] = [str(100 + i), 0]
    wf["4"] = {
        "class_type": "TextEncodeQwenImage21API",
        "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": prompt, "negative_prompt": NEGATIVE, "resolution": 1024, **images},
    }
    t0 = time.time()
    req = urllib.request.Request(f"{COMFY}/prompt", json.dumps({"prompt": wf}).encode("utf-8"), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        pid = json.load(r)["prompt_id"]
    while True:
        with urllib.request.urlopen(f"{COMFY}/history/{pid}") as r:
            h = json.load(r).get(pid)
        if h and (h.get("status", {}).get("completed") is not None or h.get("outputs")):
            break
        time.sleep(2)
    img = h["outputs"]["8"]["images"][0]
    url = f"{COMFY}/view?filename={urllib.parse.quote(img['filename'])}&subfolder={img['subfolder']}&type=output"
    with urllib.request.urlopen(url) as r:
        dest.write_bytes(r.read())
    print(f"[*] Saved {dest.name} ({time.time() - t0:.1f}s)", flush=True)


def main():
    out_dir = Path(__file__).resolve().parent / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    stop_tts()
    ensure_comfy()
    p1 = out_dir / "matte_angle1_front.png"
    p2 = out_dir / "matte_angle2_side.png"
    run_qwen(PROMPT_ANGLE1, seed=301, prefix="matte_angle1", dest=p1)
    ref1 = upload(p1)
    run_qwen(PROMPT_ANGLE2, seed=302, prefix="matte_angle2", dest=p2, ref_names=[ref1])


if __name__ == "__main__":
    main()
