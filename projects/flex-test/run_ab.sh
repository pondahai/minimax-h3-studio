#!/bin/bash
# Flex A/B：每個工作「名稱 模式(first_frame|reference) flex(0|1) seed」，8 秒 672×384
set -u
T=/home/funsteam/h3-bench/flex/test
cd $T
for job in "$@"; do
  set -- $job; name=$1 mode=$2 flex=$3 seed=$4
  R=$T/run/$name; mkdir -p $R out
  cp first_frame.png $R/first_frame.png
  if [ $mode = reference ]; then cp prompt_ref2va.txt $R/prompt.txt; else cp prompt_fl2va.txt $R/prompt.txt; fi
  s=$(date +%s); echo "$(date -Is) $name 開始"
  docker run --rm --name h3-flex --gpus all --ipc host \
    -e PYTORCH_NO_CUDA_MEMORY_CACHING=1 -e PYTHONUNBUFFERED=1 \
    -e H3_INFERENCE_MODE=$mode -e H3_FLEX=$flex -e H3_INPUT_IMAGE=/content/run/first_frame.png \
    -e "H3_REFERENCE_IMAGES=[\"/content/run/first_frame.png\"]" -e "H3_REFERENCE_AUDIOS=[]" -e "H3_REFERENCE_VIDEOS=[]" -e "H3_GUIDES=[]" \
    -e H3_PROMPT_FILE=/content/run/prompt.txt -e H3_DURATION_SECONDS=8 -e H3_SEED=$seed \
    -e H3_OUTPUT_PREFIX=flex_$name -e H3_OUTPUT_PATH=/content/run/output.mp4 -e H3_JOB_TIMEOUT_SECONDS=3600 \
    -e H3_CHARACTER_SWAP=0 -e H3_ASPECT=landscape -e H3_TEXT_ENCODER=heretic -e H3_FIRST_FRAME_FIT=crop \
    -v /home/funsteam/h3-bench/ComfyUI:/content/ComfyUI -v /home/funsteam/h3-bench/models:/content/ComfyUI/models \
    -v $R:/content/run -v /home/funsteam/h3-bench/flex/bench.py:/content/bench.py:ro \
    --entrypoint sh h3-bench:latest -c "touch /content/.h3_comfyui_setup_v1 && cd /content && python3 /content/bench.py" > $R/bench.log 2>&1
  rc=$?; e=$(( $(date +%s) - s ))
  [ $rc = 0 ] && [ -f $R/output.mp4 ] && cp $R/output.mp4 out/$name.mp4
  echo "$(date -Is) $name rc=$rc ${e}s"
  sleep 30
done
echo 全部結束
