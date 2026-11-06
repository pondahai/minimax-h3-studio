#!/bin/bash
# 第七集：新擴寫格式（每列 [Shot N]）先只跑 S01 驗證。停 ComfyUI／8002／TTS，跑完還原 8002。
cd "$(dirname "$0")"; ROOT=..
docker ps --format '{{.Names}}' | grep -qx qwen-image-comfyui && docker stop qwen-image-comfyui > /dev/null
pkill -f "[l]lama-server.*--port 8002"; pkill -f "[c]hinese_tts_server.py"
ONLY=S01 bash $ROOT/run_series.sh journey07 >> series.log 2>&1
echo "S01 結束 $?" >> one.status
pgrep -f "[l]lama-server.*--port 8002" > /dev/null || setsid -f ~/models/qwen3.6-abliterated/start.sh >> ~/models/qwen3.6-abliterated/llama-server.log 2>&1 < /dev/null
echo DONE >> one.status
