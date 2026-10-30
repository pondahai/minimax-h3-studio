#!/bin/bash
# Spark 按需 ASR：先檢查資源，通過才跑 whisper-cli（Breeze-ASR-26），跑完就結束，不常駐。
# 由 asr_check.py 經 ssh 呼叫：stdin 是 tar（000.wav、001.wav…），stdout 每行「檔名<TAB>轉寫」。
# 檢查不通過時 exit 3，第一行印 PREFLIGHT 原因，呼叫端改用 Xavier。
HUB=$HOME/breeze-asr-hub
CLI=$HUB/engine/whisper.cpp/build/bin/whisper-cli
MODEL=$HUB/models/ggml-breeze-asr-${ASR_MODEL:-26}.bin
MIN_FREE_GB=${ASR_MIN_FREE_GB:-8}  # 模型 3 GB＋推理暫存，留餘裕

fail() { echo "PREFLIGHT $*"; exit 3; }
[ -x "$CLI" ] && [ -f "$MODEL" ] || fail "找不到 whisper-cli 或模型 $MODEL"
docker ps --format '{{.Names}}' | grep -q '^h3-' && fail "H3 正在跑（容器 h3-*），不和它搶 GPU／記憶體"
pgrep -x whisper-cli > /dev/null && fail "已有另一個 whisper-cli 在跑"
free_gb=$(awk '/MemAvailable/ {print int($2 / 1048576)}' /proc/meminfo)
[ "$free_gb" -ge $MIN_FREE_GB ] || fail "可用記憶體 ${free_gb} GB < ${MIN_FREE_GB} GB"
busy=""
docker ps --format '{{.Names}}' | grep -q qwen-image-comfyui && busy="$busy Qwen-Image"
pgrep -f "[c]hinese_tts_server.py" > /dev/null && busy="$busy TTS"
echo "INFO 可用記憶體 ${free_gb} GB${busy:+，同時開著：$busy}" >&2

dir=$(mktemp -d) || exit 1
trap 'rm -rf "$dir"' EXIT
tar -x -C "$dir" || exit 1
files=("$dir"/*.wav)
"$CLI" -m "$MODEL" -l zh -nt -np -otxt $(printf -- '-f %s ' "${files[@]}") > /dev/null 2>&1 || { echo "whisper-cli 失敗" >&2; exit 1; }
for f in "${files[@]}"; do
  printf '%s\t%s\n' "$(basename "$f")" "$(tr -d '\n' < "$f.txt" | sed 's/^ *//')"
done
