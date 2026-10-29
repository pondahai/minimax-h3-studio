#!/bin/bash
# 在 Spark 上依序跑指定的 H3 工作（672×384）。每個工作：名稱 prompt檔 seed 秒數 首幀(- = t2va)
# 用法：bash run_jobs.sh "S10v2 prompts/S10.txt 164723 12 frames/S10_first.png" "music1 prompts/music.txt 1 12 -" ...
set -u
BASE=/home/funsteam/h3-bench/butterfly
cd "$BASE"
for job in "$@"; do
  set -- $job
  name=$1 prompt=$2 seed=$3 dur=$4 img=$5
  mkdir -p "run/$name" out
  cp "$prompt" "run/$name/prompt.txt"
  if [ "$img" = "-" ]; then
    MODE="-e H3_T2VA=1"
  else
    cp "$img" "run/$name/first_frame.png"
    MODE="-e H3_INPUT_IMAGE=/content/run/first_frame.png"
  fi
  echo "$(date -Is) $name 開始（${dur}s，seed $seed，首幀 $img）"
  docker run --rm --name h3-butterfly --gpus all --ipc host \
    -e PYTORCH_NO_CUDA_MEMORY_CACHING=1 -e PYTHONUNBUFFERED=1 \
    -e H3_INFERENCE_MODE=first_frame $MODE \
    -e 'H3_REFERENCE_AUDIOS=[]' -e 'H3_REFERENCE_VIDEOS=[]' -e 'H3_GUIDES=[]' \
    -e H3_PROMPT_FILE=/content/run/prompt.txt -e H3_DURATION_SECONDS=$dur -e H3_SEED=$seed \
    -e H3_OUTPUT_PREFIX=butterfly_$name -e H3_OUTPUT_PATH=/content/run/output.mp4 -e H3_JOB_TIMEOUT_SECONDS=3600 \
    -e H3_CHARACTER_SWAP=0 -e H3_ASPECT=landscape -e H3_TEXT_ENCODER=heretic -e H3_FIRST_FRAME_FIT=crop \
    -v /home/funsteam/h3-bench/ComfyUI:/content/ComfyUI \
    -v /home/funsteam/h3-bench/models:/content/ComfyUI/models \
    -v "$BASE/run/$name":/content/run -v "$BASE/bench.py":/content/bench.py:ro \
    --entrypoint sh h3-bench:latest -c 'touch /content/.h3_comfyui_setup_v1 && cd /content && python3 /content/bench.py' > "run/$name/bench.log" 2>&1
  rc=$?
  if [ $rc = 0 ] && [ -f "run/$name/output.mp4" ]; then
    cp "run/$name/output.mp4" "out/$name.mp4"; echo "$(date -Is) $name 完成"
  else
    echo "$(date -Is) $name 失敗 rc=$rc"
  fi
  sleep 60  # 冷卻
done
echo "$(date -Is) 工作結束"
