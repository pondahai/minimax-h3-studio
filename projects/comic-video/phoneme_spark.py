"""Spark 端音素辨識：stdin 是 tar（000.wav…），stdout 每行「檔名<TAB>IPA 音素（空白分隔）」。
由 phoneme_check.py 經 ssh 呼叫，用 TTS 的 venv 跑（已有 torch、transformers）。
模型 facebook/wav2vec2-xlsr-53-espeak-cv-ft 直接輸出聽到的音，不像 Whisper 會照文意修正（は 唸 ha 仍寫成「は」）。
tokenizer 需要 phonemizer，這裡只解碼，直接讀 vocab.json 免裝。
"""
import io, json, sys, tarfile

import librosa, torch
from huggingface_hub import hf_hub_download
from transformers import AutoModelForCTC, Wav2Vec2FeatureExtractor

MODEL = "facebook/wav2vec2-xlsr-53-espeak-cv-ft"

fe = Wav2Vec2FeatureExtractor.from_pretrained(MODEL)
model = AutoModelForCTC.from_pretrained(MODEL).eval()
vocab = {v: k for k, v in json.load(open(hf_hub_download(MODEL, "vocab.json"))).items()}

with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())) as tar:
    for m in sorted(tar.getmembers(), key=lambda m: m.name):
        wav, _ = librosa.load(tar.extractfile(m), sr=16000)
        with torch.no_grad():
            ids = model(fe(wav, sampling_rate=16000, return_tensors="pt").input_values).logits.argmax(-1)[0].tolist()
        phones, prev = [], None
        for i in ids:
            if i != prev and i != 0:
                phones.append(vocab[i])
            prev = i
        print(f"{m.name}\t{' '.join(phones)}", flush=True)
