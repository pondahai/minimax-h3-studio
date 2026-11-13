#!/bin/bash
# 2 步測試：同 run_ab.sh 素材，seed 164723、8 秒 672×384；對照組為 out/fl_A1、fl_B1、ref_A1、ref_B1
# 每個工作「名稱 模式 flex」。Turbo 用 H3_STEPS=2；Flex 用 H3_SIGMAS（從官方 6 步 sigmas 取 1.0→0.8→0.0）
set -u
T=/home/funsteam/h3-bench/flex/test
SIG2="1.0, 0.8, 0.0"
busy() { curl -s -m 3 -X POST http://127.0.0.1:7860/busy_status -H 'Content-Type: application/json' \
  -d "{\"busy\": $1, \"reason\": \"H3 2 步測試\"}" > /dev/null 2>&1 || true; }
restore() {
  busy false
  if ! pgrep -f "[l]lama-server.*--port 8002" > /dev/null && [ -x ~/models/qwen3.6-abliterated/start.sh ]; then
    setsid -f ~/models/qwen3.6-abliterated/start.sh >> ~/models/qwen3.6-abliterated/llama-server.log 2>&1 < /dev/null
  fi
  echo "$(date -Is) 已還原 8002"
}
if docker ps --format '{{.Names}}' | grep -qE '^h3-|^demucs'; then echo "Spark 忙碌，中止"; exit 3; fi
trap restore EXIT
busy true
docker ps --format '{{.Names}}' | grep -qx qwen-image-comfyui && docker stop qwen-image-comfyui > /dev/null
pkill -f "[l]lama-server.*--port 8002" && echo "已停 8002"
pkill -f "[c]hinese_tts_server.py"
sleep 10
cd $T
for job in "fl_T2 first_frame 0" "fl_F2 first_frame 1" "ref_T2 reference 0" "ref_F2 reference 1"; do
  set -- $job; name=$1 mode=$2 flex=$3 seed=164723
  R=$T/run/$name; mkdir -p $R out
  cp first_frame.png $R/first_frame.png
  if [ $mode = reference ]; then cp prompt_ref2va.txt $R/prompt.txt; else cp prompt_fl2va.txt $R/prompt.txt; fi
  s=$(date +%s); echo "$(date -Is) $name 開始"
  docker run --rm --name h3-steps --gpus all --ipc host \
    -e PYTORCH_NO_CUDA_MEMORY_CACHING=1 -e PYTHONUNBUFFERED=1 \
    -e H3_INFERENCE_MODE=$mode -e H3_FLEX=$flex -e H3_STEPS=2 -e "H3_SIGMAS=$SIG2" \
    -e H3_INPUT_IMAGE=/content/run/first_frame.png \
    -e "H3_REFERENCE_IMAGES=[\"/content/run/first_frame.png\"]" -e "H3_REFERENCE_AUDIOS=[]" -e "H3_REFERENCE_VIDEOS=[]" -e "H3_GUIDES=[]" \
    -e H3_PROMPT_FILE=/content/run/prompt.txt -e H3_DURATION_SECONDS=8 -e H3_SEED=$seed \
    -e H3_OUTPUT_PREFIX=steps_$name -e H3_OUTPUT_PATH=/content/run/output.mp4 -e H3_JOB_TIMEOUT_SECONDS=3600 \
    -e H3_CHARACTER_SWAP=0 -e H3_ASPECT=landscape -e H3_TEXT_ENCODER=heretic -e H3_FIRST_FRAME_FIT=crop \
    -v /home/funsteam/h3-bench/ComfyUI:/content/ComfyUI -v /home/funsteam/h3-bench/models:/content/ComfyUI/models \
    -v $R:/content/run -v /home/funsteam/h3-bench/flex/bench_steps.py:/content/bench.py:ro \
    --entrypoint sh h3-bench:latest -c "touch /content/.h3_comfyui_setup_v1 && cd /content && python3 /content/bench.py" > $R/bench.log 2>&1
  rc=$?; e=$(( $(date +%s) - s ))
  [ $rc = 0 ] && [ -f $R/output.mp4 ] && cp $R/output.mp4 out/$name.mp4
  echo "$(date -Is) $name rc=$rc ${e}s"
  sleep 30
done
echo 全部結束
