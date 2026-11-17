#!/bin/bash
# S01 對嘴三版比較（2026-11-17）。C＝現行成品 mixed/S01.mp4，不重跑；這裡只跑兩版：
#   A：首幀＋TTS 當時間軸錨點（三句 TTS 分別錨在第 0／120／216 幀＝0／5／9 秒），prompt 與現行完全相同
#   B：Ref2VA（參考圖生影片）＋角色參考音 <Audio 1–3>，S01.png 同時當 <Picture 1> 與第 0 幀圖錨點（試著保住首幀）
# 用法（Spark）：cd ~/h3-bench/comic-video/journey07 && bash voice_test/run.sh [A|B]（不給就兩版都跑）
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

run() {  # run <版本> <額外 docker 參數...>
  v=$1; shift
  d=$T/$v; mkdir -p $d
  echo "$(date -Is) $v 開始" >> $T/status
  docker run --rm --name h3-voicetest --gpus all --ipc host \
    -e PYTORCH_NO_CUDA_MEMORY_CACHING=1 -e PYTHONUNBUFFERED=1 \
    -e 'H3_REFERENCE_VIDEOS=[]' \
    -e H3_PROMPT_FILE=/content/t/prompt_$v.txt -e H3_DURATION_SECONDS=12 -e H3_SEED=164723 \
    -e H3_OUTPUT_PREFIX=voicetest_$v -e H3_OUTPUT_PATH=/content/t/$v/output.mp4 -e H3_JOB_TIMEOUT_SECONDS=3600 \
    -e H3_RESOLUTION=draft -e H3_CHARACTER_SWAP=0 -e H3_ASPECT=landscape -e H3_TEXT_ENCODER=heretic -e H3_FIRST_FRAME_FIT=crop \
    "$@" \
    -v /home/funsteam/h3-bench/ComfyUI:/content/ComfyUI \
    -v /home/funsteam/h3-bench/models:/content/ComfyUI/models \
    -v "$BASE/$T":/content/t -v "$BASE/frames":/content/frames:ro -v "$BASE/audio":/content/audio:ro \
    -v "$ROOT/bench.py":/content/bench.py:ro \
    --entrypoint sh h3-bench:latest -c 'touch /content/.h3_comfyui_setup_v1 && cd /content && python3 /content/bench.py' > $d/bench.log 2>&1
  echo "$(date -Is) $v 結束 rc=$? $(ls $d/output.mp4 2>/dev/null)" >> $T/status
}

if [ "${1:-A}" = A ] || [ -z "${1:-}" ]; then
  run A -e H3_INFERENCE_MODE=first_frame -e H3_INPUT_IMAGE=/content/frames/S01.png -e 'H3_REFERENCE_AUDIOS=[]' \
    -e 'H3_GUIDES=[{"audio":"/content/audio/S01_00_悟空.wav","frame":0},{"audio":"/content/audio/S01_05_悟淨.wav","frame":120},{"audio":"/content/audio/S01_09_鸚鵡.wav","frame":216}]'
fi
if [ "${1:-B}" = B ] || [ -z "${1:-}" ]; then
  run B -e H3_INFERENCE_MODE=reference -e 'H3_REFERENCE_IMAGES=["/content/frames/S01.png"]' \
    -e 'H3_REFERENCE_AUDIOS=["/content/t/ref_悟空.wav","/content/t/ref_悟淨.wav","/content/t/ref_鸚鵡.wav"]' \
    -e 'H3_GUIDES=[{"image":"/content/frames/S01.png","frame":0}]'
fi
echo "$(date -Is) DONE" >> $T/status
