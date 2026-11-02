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

# 忙碌旗標：qwen-gradio-ui（:7860，前端豁免不停）跟 story-film-studio 都靠這個端點知道
# GPU 現在被誰佔用，顯示提示／排隊等待，而不是連線錯誤。通用端點，不只給 H3 用。
# trap 確保無論正常結束、ABORT 還是被殺掉，旗標都會被清掉，不會卡死在 busy=true。
set_busy_status() {
  curl -s -m 3 -X POST http://127.0.0.1:7860/busy_status \
    -H 'Content-Type: application/json' \
    -d "{\"busy\": $1, \"reason\": \"H3（$NAME）正在運作\"}" > /dev/null 2>&1 || true
}
trap 'set_busy_status false' EXIT
set_busy_status true

# 等 Qwen-Image 手上的工作做完才交班，不強制中斷進行中的生圖任務。
# 查不到隊列（ComfyUI 沒在跑／連線失敗）視為沒有任務，直接放行。
wait_qwen_idle() {
  local max_wait=60 waited=0 busy
  while [ $waited -lt $max_wait ]; do
    busy=$(curl -s -m 5 http://127.0.0.1:8188/queue 2>/dev/null | python3 -c '
import sys, json
try:
    q = json.load(sys.stdin)
    print(1 if (q.get("queue_running") or q.get("queue_pending")) else 0)
except Exception:
    print(0)
' 2>/dev/null)
    [ "$busy" = "1" ] || return 0
    sleep 3
    waited=$((waited + 3))
  done
  say "等待 Qwen-Image 隊列清空逾時（${max_wait}秒），改為直接停掉，可能打斷進行中的任務"
  return 1
}

# 0. 互斥檢查：只留 8002，TTS／Qwen-Image／Demucs／其他 H3 都不能開
# qwen-gradio-ui 豁免不停：前端很輕（透過 ComfyUI 才佔記憶體），停掉 qwen-image-comfyui 後
# 它只是連不到後端、頁面顯示讀取中，不會額外佔用 H3 需要的記憶體；保留它讓使用者至少能看到
# 頁面還在、知道「現在不能生圖」，而不是整個 8443 直接斷線。
if docker ps --format '{{.Names}}' | grep -qx qwen-image-comfyui; then
  say "等待 Qwen-Image 目前的工作做完才交班"
  wait_qwen_idle
  say "停掉 qwen-image-comfyui"
  docker stop qwen-image-comfyui > /dev/null
fi
docker ps --format '{{.Names}}' | grep -qx qwen3.8-nvfp4 && { say "停掉 qwen3.8-nvfp4"; docker stop qwen3.8-nvfp4 > /dev/null; }
pgrep -f "[c]hinese_tts_server.py" > /dev/null && { say "停掉 TTS"; pkill -f "[c]hinese_tts_server.py"; }
if docker ps --format '{{.Names}}' | grep -qE '^h3-|^demucs'; then say "ABORT 已有 H3／Demucs 在跑"; exit 1; fi
for f in config.json prompts/music_official.txt audio/lines.json; do [ -f "$f" ] || { say "ABORT 缺 $f"; exit 1; }; done
SIDS=$(python3 -c 'import json; print(" ".join(s for s, _, _ in json.load(open("config.json"))["shots"]))')
# 首幀來源是圖檔才檢查圖；續接段（來源＝前段名）只要 prompt，首幀由 run_series.sh 取前段末幀
python3 -c 'import json
for s, _, src in json.load(open("config.json"))["shots"]: print(s, src)' | while read -r sid src; do
  [ -f "prompts/$sid.txt" ] || { say "ABORT 缺 $sid 的 prompt"; exit 1; }
  case "$src" in *.png) [ -f "$src" ] || { say "ABORT 缺 $sid 的首幀 $src"; exit 1; } ;; esac
done || exit 1
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
