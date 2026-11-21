"""Generate a 16:9 singer first frame on DGX Spark via Qwen-Image 2.1 (:8188)."""
import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

COMFY = "http://100.89.149.50:8188"
W, H = 1344, 768
SIGMAS = "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0.0"
NEGATIVE = "文字, 字母, 標題, 字幕, 浮水印, logo, text, letters, watermark, microphone blocking mouth"

PROMPT = (
    "電影感寫實攝影，中近景（胸上至頭頂），一位二十多歲的台灣年輕女性民謠歌手坐在溫暖的木質小咖啡館舞台高腳椅上，"
    "懷中抱著一把原木色民謠木吉他，雙手自然放在吉他琴頸與琴身上準備彈唱。"
    "她留著自然的深棕色中長髮，身穿米白色針織毛衣，神情溫柔專注，微微面向鏡頭左前方。"
    "一支復古金屬電容式麥克風架在畫面左下側，位於她的嘴唇下方略微偏側，完全不遮擋她的嘴部與臉部。"
    "背景是柔和失焦的暖黃色鎢絲燈串與木質牆面，淺景深，自然膚質與溫暖逆光輪廓光，畫面裡剛好只有這 1 個人，沒有任何文字、標誌或看板。"
)


def stop_tts():
    r = subprocess.run(
        ["ssh", "-n", "-o", "ConnectTimeout=10", "funsteam@100.89.149.50",
         "pkill -f '[c]hinese_tts_server.py' && echo stopped || true"],
        capture_output=True, text=True, timeout=30,
    )
    if "stopped" in r.stdout:
        print("[*] 已關閉 TTS（:8792）", flush=True)


def ensure_comfy():
    try:
        urllib.request.urlopen(f"{COMFY}/system_stats", timeout=5).close()
        print("[*] ComfyUI (:8188) 已就緒", flush=True)
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


def build_workflow(seed: int):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_turbo_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image"}},
        "9": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}},
        "4": {"class_type": "TextEncodeQwenImage21API", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": PROMPT, "negative_prompt": NEGATIVE, "resolution": 1024}},
        "20": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS}},
        "21": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "6": {"class_type": "SamplerCustom", "inputs": {
            "model": ["9", 0], "add_noise": True, "noise_seed": seed, "cfg": 1.0,
            "positive": ["4", 0], "negative": ["4", 1], "sampler": ["21", 0],
            "sigmas": ["20", 0], "latent_image": ["5", 0],
        }},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": "singing_test_frame", "images": ["7", 0]}},
    }


def main():
    out_dir = Path(__file__).resolve().parent / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    stop_tts()
    ensure_comfy()
    dest = out_dir / "singer_frame_seed1.png"
    t0 = time.time()
    req = urllib.request.Request(
        f"{COMFY}/prompt",
        json.dumps({"prompt": build_workflow(seed=101)}).encode("utf-8"),
        {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        pid = json.load(r)["prompt_id"]
    print(f"[*] Submitted Qwen-Image job: {pid}", flush=True)
    while True:
        with urllib.request.urlopen(f"{COMFY}/history/{pid}") as r:
            h = json.load(r).get(pid)
        if h and (h.get("status", {}).get("completed") is not None or h.get("outputs")):
            break
        time.sleep(3)
    img = h["outputs"]["8"]["images"][0]
    url = f"{COMFY}/view?filename={urllib.parse.quote(img['filename'])}&subfolder={img['subfolder']}&type=output"
    with urllib.request.urlopen(url) as r:
        dest.write_bytes(r.read())
    print(f"[*] Saved {dest} ({time.time() - t0:.1f}s)", flush=True)


if __name__ == "__main__":
    main()
