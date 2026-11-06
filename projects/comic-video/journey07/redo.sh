#!/bin/bash
# 第七集重跑 S16（鸚鵡說話時悟空動嘴）與續接的 S17，再補後處理
cd "$(dirname "$0")"; ROOT=$(cd .. && pwd); NAME=journey07; ST=redo.status; : > $ST
docker ps --format '{{.Names}}' | grep -qx qwen-image-comfyui && docker stop qwen-image-comfyui > /dev/null
pkill -f "[l]lama-server.*--port 8002"; pkill -f "[c]hinese_tts_server.py"
mkdir -p out/archive; for s in S16 S17; do mv out/$s.mp4 out/archive/${s}_v1.mp4; mv run/$s run/${s}_v1; done
for s in S16 S17; do ONLY=$s bash $ROOT/run_series.sh $NAME >> series.log 2>&1; echo "$(date +%T) $s 結束 $?" >> $ST; done
cp out/S16.mp4 out/S17.mp4 video/
bash $ROOT/sfx.sh $NAME S16 S17 >> post.log 2>&1; echo "$(date +%T) sfx $?" >> $ST
docker run --rm -u $(id -u):$(id -g) -v "$ROOT":/c -w /c --entrypoint python demucs-sfx lipsync_measure.py $NAME >> post.log 2>&1; echo "lipsync $?" >> $ST
docker run --rm -u $(id -u):$(id -g) -v "$ROOT":/c -w /c --entrypoint python demucs-sfx align_dtw.py $NAME S16 S17 >> post.log 2>&1; echo "align $?" >> $ST
python3 $ROOT/mux.py $NAME >> post.log 2>&1; echo "mux $?" >> $ST
pgrep -f "[l]lama-server.*--port 8002" > /dev/null || setsid -f ~/models/qwen3.6-abliterated/start.sh >> ~/models/qwen3.6-abliterated/llama-server.log 2>&1 < /dev/null
echo DONE >> $ST
