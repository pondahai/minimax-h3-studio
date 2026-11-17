#!/bin/bash
# A 做法（首幀＋每句 TTS 當時間軸錨點）跑任意鏡頭，2026-11-17。prompt、首幀、seed 都和正式版相同，只多了音訊錨點。
# 錨點由 audio/lines.json 產生：該段每句一個 {"audio": 檔, "frame": 起秒×24}。首幀照 config shots（段名＝取該段 out/ 末幀）。
# 用法（Spark）：cd ~/h3-bench/comic-video/journey07 && bash voice_test/run_a.sh S07 S13 …
# 成品：voice_test/A_<段>.mp4；狀態寫 voice_test/status
set -u
cd "$(dirname "$0")/.."
BASE=$PWD; ROOT=$(dirname "$BASE"); T=voice_test
restore() {
  pgrep -f "[l]lama-server.*--port 8002" > /dev/null || setsid -f ~/models/qwen3.6-abliterated/start.sh >> ~/models/qwen3.6-abliterated/llama-server.log 2>&1 < /dev/null
  echo "$(date -Is) 已還原 8002" >> $T/status
}
trap restore EXIT
docker ps --format '{{.Names}}' | grep -qx qwen-image-comfyui && docker stop qwen-image-comfyui > /dev/null
pkill -f "[l]lama-server.*--port 8002"; pkill -f "[c]hinese_tts_server.py"
busy=$(docker ps --format '{{.Names}}' | grep -E '^h3-|^demucs' | tr '\n' ' ')
[ -n "$busy" ] && { echo "Spark 忙碌（$busy），停止" >> $T/status; exit 3; }

for sid in "$@"; do
  d=$T/A_$sid; mkdir -p $d
  read -r dur src guides < <(python3 - "$sid" <<'EOF'
import json, sys
sid = sys.argv[1]
dur, src = next((d, f) for s, d, f in json.load(open("config.json"))["shots"] if s == sid)
lines = json.load(open("audio/lines.json"))
lines = lines if isinstance(lines, list) else lines["lines"]
g = [{"audio": f"/content/audio/{x['file']}", "frame": int(round(x["start"] * 24))} for x in lines if x["sid"] == sid]
print(dur, src, json.dumps(g, ensure_ascii=False, separators=(",", ":")))
EOF
)
  if [ -f "$src" ]; then cp "$src" $d/first_frame.png
  else ffmpeg -y -loglevel error -sseof -0.1 -i "out/$src.mp4" -frames:v 1 -update 1 $d/first_frame.png || { echo "$sid 取末幀失敗" >> $T/status; continue; }
  fi
  cp prompts/$sid.txt $d/prompt.txt
  echo "$(date -Is) $sid 開始（${dur}s，首幀 $src，錨點 $guides）" >> $T/status
  docker run --rm --name h3-voicetest --gpus all --ipc host \
    -e PYTORCH_NO_CUDA_MEMORY_CACHING=1 -e PYTHONUNBUFFERED=1 \
    -e H3_INFERENCE_MODE=first_frame -e H3_INPUT_IMAGE=/content/d/first_frame.png \
    -e 'H3_REFERENCE_AUDIOS=[]' -e 'H3_REFERENCE_VIDEOS=[]' -e "H3_GUIDES=$guides" \
    -e H3_PROMPT_FILE=/content/d/prompt.txt -e H3_DURATION_SECONDS=$dur -e H3_SEED=164723 \
    -e H3_OUTPUT_PREFIX=voicetest_$sid -e H3_OUTPUT_PATH=/content/d/output.mp4 -e H3_JOB_TIMEOUT_SECONDS=3600 \
    -e H3_RESOLUTION=draft -e H3_CHARACTER_SWAP=0 -e H3_ASPECT=landscape -e H3_TEXT_ENCODER=heretic -e H3_FIRST_FRAME_FIT=crop \
    -v /home/funsteam/h3-bench/ComfyUI:/content/ComfyUI \
    -v /home/funsteam/h3-bench/models:/content/ComfyUI/models \
    -v "$BASE/$d":/content/d -v "$BASE/audio":/content/audio:ro \
    -v "$ROOT/bench.py":/content/bench.py:ro \
    --entrypoint sh h3-bench:latest -c 'touch /content/.h3_comfyui_setup_v1 && cd /content && python3 /content/bench.py' > $d/bench.log 2>&1
  rc=$?
  [ -f $d/output.mp4 ] && cp $d/output.mp4 $T/A_$sid.mp4
  echo "$(date -Is) $sid 結束 rc=$rc" >> $T/status
done
echo "$(date -Is) DONE" >> $T/status
