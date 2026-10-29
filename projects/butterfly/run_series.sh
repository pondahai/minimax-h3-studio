#!/bin/bash
# 在 Spark 上依序生成蝴蝶分鏡 S01–S10（672×384），續接段取前段末幀當首幀。
# 用法：bash run_series.sh [起始段，例如 S05]
set -u
BASE=/home/funsteam/h3-bench/butterfly
cd "$BASE"
# 段落：代號 秒數 續接來源（- 表示 t2va）
SHOTS="S01 12 - S02 12 - S03 12 S02 S04 12 - S05 12 S04 S06 12 - S07 10 S06 S08 12 - S09 12 - S10 12 -"
START=${1:-S01}
started=0
( while true; do echo "$(date +%s) $(free -m | awk '/Mem:/{print $3}') $(free -m | awk '/置換|Swap/{print $3}')"; sleep 5; done ) >> mem.log &
MEMPID=$!
set -- $SHOTS
while [ $# -gt 0 ]; do
  sid=$1 dur=$2 src=$3; shift 3
  [ "$sid" = "$START" ] && started=1
  [ $started = 1 ] || continue
  [ -f "out/$sid.mp4" ] && { echo "$sid 已存在，跳過"; continue; }
  mkdir -p "run/$sid" out
  cp "prompts/$sid.txt" "run/$sid/prompt.txt"
  if [ "$src" = "-" ]; then
    MODE="-e H3_T2VA=1"
  else
    ffmpeg -y -loglevel error -sseof -0.1 -i "out/$src.mp4" -frames:v 1 -update 1 "run/$sid/first_frame.png" || { echo "$sid 取末幀失敗"; break; }
    MODE="-e H3_INPUT_IMAGE=/content/run/first_frame.png"
  fi
  echo "$(date -Is) $sid 開始（${dur}s，續接 $src）"
  docker run --rm --name h3-butterfly --gpus all --ipc host \
    -e PYTORCH_NO_CUDA_MEMORY_CACHING=1 -e PYTHONUNBUFFERED=1 \
    -e H3_INFERENCE_MODE=first_frame $MODE \
    -e 'H3_REFERENCE_AUDIOS=[]' -e 'H3_REFERENCE_VIDEOS=[]' -e 'H3_GUIDES=[]' \
    -e H3_PROMPT_FILE=/content/run/prompt.txt -e H3_DURATION_SECONDS=$dur -e H3_SEED=164723 \
    -e H3_OUTPUT_PREFIX=butterfly_$sid -e H3_OUTPUT_PATH=/content/run/output.mp4 -e H3_JOB_TIMEOUT_SECONDS=3600 \
    -e H3_CHARACTER_SWAP=0 -e H3_ASPECT=landscape -e H3_TEXT_ENCODER=heretic -e H3_FIRST_FRAME_FIT=crop \
    -v /home/funsteam/h3-bench/ComfyUI:/content/ComfyUI \
    -v /home/funsteam/h3-bench/models:/content/ComfyUI/models \
    -v "$BASE/run/$sid":/content/run -v "$BASE/bench.py":/content/bench.py:ro \
    --entrypoint sh h3-bench:latest -c 'touch /content/.h3_comfyui_setup_v1 && cd /content && python3 /content/bench.py' > "run/$sid/bench.log" 2>&1
  rc=$?
  if [ $rc = 0 ] && [ -f "run/$sid/output.mp4" ]; then
    cp "run/$sid/output.mp4" "out/$sid.mp4"; echo "$(date -Is) $sid 完成"
  else
    echo "$(date -Is) $sid 失敗 rc=$rc"; break
  fi
  sleep 60  # 冷卻
done
kill $MEMPID
echo "$(date -Is) 系列結束"
