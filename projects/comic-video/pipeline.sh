#!/bin/bash
# 在 Spark 上離線跑完一篇的 H3 與後處理，本機可以關機：配樂 music1 → 各段 H3（失敗重試 1 次，仍失敗就跳過）
# → out/ 複製到 video/ → sfx.sh → lipsync_measure.py → align_dtw.py → mux.py（試聽版）。不做全片、字幕、分享版（等使用者試聽）。
# 用法（Spark 上）：setsid nohup bash pipeline.sh <篇目> > <篇目>/pipeline.log 2>&1 < /dev/null &
# 進度：<篇目>/pipeline.status 每階段一行；跑完最後一行是 DONE（或 ABORT 原因）。
set -u
ROOT=$(cd "$(dirname "$0")" && pwd)
NAME=$1
BASE=$ROOT/$NAME
cd "$BASE" || exit 1
ST=$BASE/pipeline.status
say() { echo "$(date '+%F %T') $*" | tee -a "$ST"; }
: > "$ST"

# 0. 互斥檢查：只留 8002，TTS／Qwen-Image／Demucs／其他 H3 都不能開
for c in qwen-image-comfyui qwen3.8-nvfp4 qwen-gradio-ui; do
  docker ps --format '{{.Names}}' | grep -qx "$c" && { say "停掉 $c"; docker stop "$c" > /dev/null; }
done
pgrep -f "[c]hinese_tts_server.py" > /dev/null && { say "停掉 TTS"; pkill -f "[c]hinese_tts_server.py"; }
if docker ps --format '{{.Names}}' | grep -qE '^h3-|^demucs'; then say "ABORT 已有 H3／Demucs 在跑"; exit 1; fi
for f in config.json prompts/music_official.txt audio/lines.json; do [ -f "$f" ] || { say "ABORT 缺 $f"; exit 1; }; done
SIDS=$(python3 -c 'import json; print(" ".join(s for s, _, _ in json.load(open("config.json"))["shots"]))')
for sid in $SIDS; do [ -f "prompts/$sid.txt" ] && [ -f "frames/$sid.png" ] || { say "ABORT 缺 $sid 的 prompt 或首幀"; exit 1; }; done
say "開始：$SIDS ＋ music1"

# 1. 配樂
mkdir -p music
if [ ! -f out/music1.mp4 ]; then
  bash "$ROOT/run_jobs.sh" "$NAME" "music1 prompts/music_official.txt 1 12 -"
fi
if [ -f out/music1.mp4 ]; then
  ffmpeg -y -loglevel error -i out/music1.mp4 -vn -ar 44100 music/music1.wav && cp music/music1.wav music/bgm.wav
  tmp=$(mktemp -d); cp music/music1.wav "$tmp/000.wav"
  asr=$(tar -C "$tmp" -cf - 000.wav | bash "$ROOT/asr_spark.sh" 2>/dev/null | cut -f2-); rm -rf "$tmp"
  if echo "$asr" | grep -qP '[\x{4e00}-\x{9fff}]'; then say "music1 完成，ASR 聽到人聲：$asr（仍暫用當 bgm，要人聽）"
  else say "music1 完成，ASR 沒聽到人聲（${asr:-空白}），已設成 bgm.wav"; fi
else
  say "music1 失敗，試聽版會沒有配樂"
fi

# 2. 各段 H3：失敗重試 1 次，仍失敗就跳過
failed=""
for sid in $SIDS; do
  [ -f "out/$sid.mp4" ] && continue
  for try in 1 2; do
    ONLY=$sid bash "$ROOT/run_series.sh" "$NAME" >> series.log 2>&1
    [ -f "out/$sid.mp4" ] && break
    [ -d "run/$sid" ] && mv "run/$sid" "run/${sid}_fail$try"
    say "$sid 第 $try 次失敗"
  done
  if [ -f "out/$sid.mp4" ]; then say "$sid 完成"; else failed="$failed $sid"; fi
done
[ -n "$failed" ] && say "H3 失敗段落：$failed"

# 3. 後處理（試聽版）
mkdir -p video && cp out/S*.mp4 video/
say "out/ 已複製到 video/"
bash "$ROOT/sfx.sh" "$NAME" >> post.log 2>&1 && say "sfx.sh 完成" || say "sfx.sh 失敗（看 post.log）"
docker run --rm -u $(id -u):$(id -g) -v "$ROOT":/c -w /c --entrypoint python demucs-sfx lipsync_measure.py "$NAME" >> post.log 2>&1 \
  && say "lipsync_measure 完成" || say "lipsync_measure 失敗（看 post.log）"
docker run --rm -u $(id -u):$(id -g) -v "$ROOT":/c -w /c --entrypoint python demucs-sfx align_dtw.py "$NAME" >> post.log 2>&1 \
  && say "align_dtw 完成" || say "align_dtw 失敗（看 post.log）"
python3 "$ROOT/mux.py" "$NAME" >> post.log 2>&1 && say "mux 完成（mixed/ 試聽版）" || say "mux 失敗（看 post.log）"
say "DONE${failed:+（失敗段落：$failed）}"
