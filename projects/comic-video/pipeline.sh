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
# 跑完（DONE、ABORT、被 pkill 暫停都算）把開跑前停掉的服務開回來。
# 2026-11-06 起 8006（qwen3.8-nvfp4）常駐、跑 H3 時改停 8002：跑完拉回 8002，8006 若不在也順手拉起。
# ComfyUI 是 comfy-ondemand 按需啟動，不還原。
RESTORE_TTS=""
restore_services() {
  docker ps --format '{{.Names}}' | grep -qx qwen3.8-nvfp4 || { docker start qwen3.8-nvfp4 > /dev/null 2>&1 && echo "$(date '+%F %T') 8006 沒在跑，已啟動" >> "$ST"; }
  if [ -n "$RESTORE_TTS" ]; then
    (cd ~/dgx-voxcpm-eval && . .venv/bin/activate && setsid -f python chinese_tts_server.py > tts.log 2>&1 < /dev/null)
    echo "$(date '+%F %T') 還原 TTS（:8792）" >> "$ST"
  fi
  if ! pgrep -f "[l]lama-server.*--port 8002" > /dev/null && [ -x ~/models/qwen3.6-abliterated/start.sh ]; then
    setsid -f ~/models/qwen3.6-abliterated/start.sh >> ~/models/qwen3.6-abliterated/llama-server.log 2>&1 < /dev/null
    echo "$(date '+%F %T') 還原 8002（llama.cpp）" >> "$ST"
  fi
}
trap 'set_busy_status false; restore_services' EXIT
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

# 0. 互斥檢查：TTS／Qwen-Image／Demucs／其他 H3／8002 都不能開；8006 常駐（2026-11-06 起，H3＋8006 約 90 GB／121 GB）
# qwen-gradio-ui 豁免不停：前端很輕（透過 ComfyUI 才佔記憶體），停掉 qwen-image-comfyui 後
# 它只是連不到後端、頁面顯示讀取中，不會額外佔用 H3 需要的記憶體；保留它讓使用者至少能看到
# 頁面還在、知道「現在不能生圖」，而不是整個 8443 直接斷線。
if docker ps --format '{{.Names}}' | grep -qx qwen-image-comfyui; then
  say "等待 Qwen-Image 目前的工作做完才交班"
  wait_qwen_idle
  say "停掉 qwen-image-comfyui"
  docker stop qwen-image-comfyui > /dev/null
fi
pgrep -f "[l]lama-server.*--port 8002" > /dev/null && { say "停掉 8002（跑完會還原）"; pkill -f "[l]lama-server.*--port 8002"; }
pgrep -f "[c]hinese_tts_server.py" > /dev/null && { say "停掉 TTS（跑完會還原）"; pkill -f "[c]hinese_tts_server.py"; RESTORE_TTS=1; }
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

# 1. 配樂：H3 配樂是抽卡，常混吟唱／誦經／說話聲（第六集 seed 1、2 都中）。
#   prompt 補禁止人聲句（降低機率）；每個 seed 生成後用 Demucs 拆人聲軌「只做偵測」，
#   人聲軌 RMS／伴奏 RMS > 0.1 或人聲軌 ASR（去掉括號幻聽）有中文 → 換下一個 seed，最多 MUSIC_TRIES 個。
#   bgm.wav 一律用原始配樂（Demucs 去人聲後伴奏受損嚴重，第六集使用者試聽否決）。
#   實測：有人聲 8.4、5.6；乾淨 0.002、0.011。
mkdir -p music
NOVOX="Strictly instrumental with no human voice at all: no vocals, no singing, no humming, no chanting, no choir, no speech."
sed "/^non_diegetic_music:/ { /no vocals/! s/\$/ $NOVOX/ }" prompts/music_official.txt > prompts/music_run.txt
music_ok=""
for seed in $(seq 1 ${MUSIC_TRIES:-4}); do
  m=music$seed
  [ -f out/$m.mp4 ] || RES=draft bash "$ROOT/run_jobs.sh" "$NAME" "$m prompts/music_run.txt $seed 12 -"
  [ -f out/$m.mp4 ] || { say "$m 生成失敗"; continue; }
  ffmpeg -y -loglevel error -i out/$m.mp4 -vn -ar 44100 music/$m.wav
  cp music/$m.wav music/${m}_h3.wav
  docker run --rm --name demucs-music --gpus all --ipc=host -v "$BASE/music:/w" demucs-sfx ${m}_h3.wav >> post.log 2>&1
  rm -f music/${m}_h3.wav
  if [ ! -f music/${m}_vocals.wav ]; then say "$m Demucs 失敗，無法偵測人聲，暫用（看 post.log）"; music_ok=$m; break; fi
  ratio=$(python3 -c "
import wave, array, math
def rms(f):
    w = wave.open(f); a = array.array('h', w.readframes(w.getnframes())); return math.sqrt(sum(x*x for x in a) / max(len(a), 1))
print(round(rms('music/${m}_vocals.wav') / max(rms('music/${m}_novocals.wav'), 1e-6), 3))")
  tmp=$(mktemp -d); cp music/${m}_vocals.wav "$tmp/000.wav"
  asr=$(tar -C "$tmp" -cf - 000.wav | bash "$ROOT/asr_spark.sh" 2>/dev/null | cut -f2-); rm -rf "$tmp"
  # whisper 對純音樂常幻聽成括號短語（「(日語)」「(我愛你)」），去掉括號內容再判斷
  if python3 -c "import sys; sys.exit(0 if float('$ratio') > 0.1 else 1)" || echo "$asr" | sed 's/([^)]*)//g' | grep -qP '[\x{4e00}-\x{9fff}]'; then
    say "$m 有人聲（人聲／伴奏 $ratio，人聲軌 ASR：${asr:-空白}），換下一個 seed"
  else
    say "$m 乾淨（人聲／伴奏 $ratio），設成 bgm.wav"; music_ok=$m; break
  fi
done
if [ -n "$music_ok" ]; then cp music/$music_ok.wav music/bgm.wav
else say "配樂 ${MUSIC_TRIES:-4} 個 seed 都有人聲，試聽版沒有配樂，要人處理"; rm -f music/bgm.wav; fi

# 2. 各段 H3：失敗重試 1 次，仍失敗就跳過
failed=""
for sid in $SIDS; do
  [ -f "out/$sid.mp4" ] && continue
  for try in 1 2; do
    ONLY=$sid bash "$ROOT/run_series.sh" "$NAME" >> series.log 2>&1
    # 結束碼 3＝Spark 被別的 H3／Demucs 佔用（例如 Studio 中途開跑）：不要逐段重試燒過去，整條停下
    [ $? -eq 3 ] && { say "ABORT $sid 開跑前發現已有 H3／Demucs 在跑，pipeline 停止"; exit 1; }
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
