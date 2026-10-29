"""用 Spark 上的 Qwen-Image 2.1（ComfyUI :8188）依參考圖生成 16:9 首幀。

用法：python qwen_frame.py <篇目> <名稱> <seed數> <參考圖...>
  prompt 從 <篇目>/frame_prompts/<名稱>.txt 讀，輸出 <篇目>/frames/<名稱>_seedN.png；選定後另存成 shots 指定的首幀檔名
工作流比照 ~/qwen-image/gradio_app.py 的 turbo int8 路徑，但 latent 改用 EmptyLatentImage 固定 16:9。
"""
import json, time, urllib.request, uuid
from pathlib import Path

import comic

COMFY = "http://100.89.149.50:8188"
W, H = 1344, 768  # 16:9，672×384 的兩倍
SIGMAS = "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0.0"
NEGATIVE = "文字, 字母, 標題, 對話框, 招牌文字, 浮水印, logo, text, letters, watermark, speech bubble"


def upload(path):
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="cv_{uuid.uuid4().hex[:8]}.png"\r\n'
            f"Content-Type: image/png\r\n\r\n").encode() + Path(path).read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{COMFY}/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)["name"]


def workflow(prompt, refs, seed, prefix):
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_turbo_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image"}},
        "9": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}},
        "20": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS}},
        "21": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "6": {"class_type": "SamplerCustom", "inputs": {"model": ["9", 0], "add_noise": True, "noise_seed": seed, "cfg": 1.0,
                                                        "positive": ["4", 0], "negative": ["4", 1], "sampler": ["21", 0],
                                                        "sigmas": ["20", 0], "latent_image": ["5", 0]}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["7", 0]}},
    }
    images = {}
    for i, name in enumerate(refs, 1):
        wf[str(100 + i)] = {"class_type": "LoadImage", "inputs": {"image": name}}
        images[f"image{i}"] = [str(100 + i), 0]
    wf["4"] = {"class_type": "TextEncodeQwenImage21API", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": prompt,
                                                                    "negative_prompt": NEGATIVE, "resolution": 1024, **images}}
    return wf


def run(wf, dest):
    req = urllib.request.Request(f"{COMFY}/prompt", json.dumps({"prompt": wf}).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        pid = json.load(r)["prompt_id"]
    while True:
        with urllib.request.urlopen(f"{COMFY}/history/{pid}") as r:
            h = json.load(r).get(pid)
        if h and h.get("status", {}).get("completed") is not None or (h and h["outputs"]):
            break
        time.sleep(3)
    img = h["outputs"]["8"]["images"][0]
    url = f"{COMFY}/view?filename={urllib.parse.quote(img['filename'])}&subfolder={img['subfolder']}&type=output"
    with urllib.request.urlopen(url) as r:
        dest.write_bytes(r.read())


if __name__ == "__main__":
    import urllib.parse
    cfg, d, args = comic.load()
    name, n, refs = args[0], int(args[1]), args[2:]
    prompt = (d / "frame_prompts" / f"{name}.txt").read_text(encoding="utf-8").strip()
    names = [upload(p) for p in refs]
    for seed in range(1, n + 1):
        dest = d / "frames" / f"{name}_seed{seed}.png"
        dest.parent.mkdir(exist_ok=True)
        t = time.time()
        run(workflow(prompt, names, seed, f"{cfg['id']}_{name}"), dest)
        print(f"{dest.name} {time.time() - t:.0f}s", flush=True)
