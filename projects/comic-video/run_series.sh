#!/bin/bash
# 在 Spark 上依 <篇目>/config.json 的 shots 依序生成各段（672×384），已有的段會跳過；失敗就停。
# shots 第三欄是首幀來源：- ＝t2va；圖檔路徑（如 frames/S01.png）＝用該圖；段名＝續接該段末幀。
# 有 frames/<段>_end.png 就當尾幀（官方 FL2VA，首尾幀）。
# 用法：bash run_series.sh <篇目> [起始段，例如 S05]
# Spark 目錄：~/h3-bench/comic-video/（本目錄的腳本＋bench.py）、~/h3-bench/comic-video/<篇目>/
set -u
ROOT=$(cd "$(dirname "$0")" && pwd)
NAME=$1
BASE=$ROOT/$NAME
cd "$BASE" || exit 1
SHOTS=$(python3 -c 'import json; print(" ".join(f"{s} {d} {f}" for s, d, f in json.load(open("config.json"))["shots"]))')
START=${2:-S01}
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
  elif [ -f "$src" ]; then
    cp "$src" "run/$sid/first_frame.png"
    MODE="-e H3_INPUT_IMAGE=/content/run/first_frame.png"
  else
    ffmpeg -y -loglevel error -sseof -0.1 -i "out/$src.mp4" -frames:v 1 -update 1 "run/$sid/first_frame.png" || { echo "$sid 取末幀失敗"; break; }
    MODE="-e H3_INPUT_IMAGE=/content/run/first_frame.png"
  fi
  LAST=""
  [ -f "frames/${sid}_end.png" ] && { cp "frames/${sid}_end.png" "run/$sid/last_frame.png"; LAST="-e H3_LAST_FRAME=/content/run/last_frame.png"; }
  echo "$(date -Is) $sid 開始（${dur}s，首幀 $src）"
  docker run --rm --name h3-$NAME --gpus all --ipc host \
    -e PYTORCH_NO_CUDA_MEMORY_CACHING=1 -e PYTHONUNBUFFERED=1 \
    -e H3_INFERENCE_MODE=first_frame $MODE $LAST \
    -e 'H3_REFERENCE_AUDIOS=[]' -e 'H3_REFERENCE_VIDEOS=[]' -e 'H3_GUIDES=[]' \
    -e H3_PROMPT_FILE=/content/run/prompt.txt -e H3_DURATION_SECONDS=$dur -e H3_SEED=164723 \
    -e H3_OUTPUT_PREFIX=${NAME}_$sid -e H3_OUTPUT_PATH=/content/run/output.mp4 -e H3_JOB_TIMEOUT_SECONDS=3600 \
    -e H3_CHARACTER_SWAP=0 -e H3_ASPECT=landscape -e H3_TEXT_ENCODER=heretic -e H3_FIRST_FRAME_FIT=crop \
    -v /home/funsteam/h3-bench/ComfyUI:/content/ComfyUI \
    -v /home/funsteam/h3-bench/models:/content/ComfyUI/models \
    -v "$BASE/run/$sid":/content/run -v "$ROOT/bench.py":/content/bench.py:ro \
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
