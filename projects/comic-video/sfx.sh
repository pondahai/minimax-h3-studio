#!/bin/bash
# 在 Spark 上把各段 H3 原生音軌去掉人聲，留下和畫面同步的音效 → <篇目>/sfx/SXX_novocals.wav（mux.py 會自動墊上）。
# 用法：bash sfx.sh <篇目> [段...]（不給段就照 config 的 shots 全做；已有 _novocals.wav 的段跳過，要重做先刪掉）
# 需要映像檔 demucs-sfx（Dockerfile.sfx）；H3 在跑時不要啟動（記憶體互斥）。
# 最後列出每段音效響度：太小聲（< -45 LUFS）的段落 H3 可能沒生成音效，要人聽過決定要不要另外補。
set -u
ROOT=$(cd "$(dirname "$0")" && pwd)
NAME=$1; shift
cd "$ROOT/$NAME" || exit 1
SIDS=${*:-$(python3 -c 'import json; print(" ".join(s for s, _, _ in json.load(open("config.json"))["shots"]))')}
if docker ps --format '{{.Names}}' | grep -q "^h3-"; then echo "H3 正在跑，等它結束再做"; exit 1; fi
mkdir -p sfx
todo=()
for sid in $SIDS; do
  [ -f "sfx/${sid}_novocals.wav" ] && { echo "$sid 已存在，跳過"; continue; }
  [ -f "out/$sid.mp4" ] || { echo "$sid 沒有 out/$sid.mp4，跳過"; continue; }
  ffmpeg -loglevel error -y -i "out/$sid.mp4" -vn -ar 44100 "sfx/${sid}_h3.wav" && todo+=("${sid}_h3.wav")
done
if [ ${#todo[@]} -gt 0 ]; then
  docker run --rm --name demucs-sfx --gpus all --ipc=host -v "$PWD/sfx:/w" demucs-sfx "${todo[@]}" || exit 1
fi
echo "== 音效響度"
for sid in $SIDS; do
  f="sfx/${sid}_novocals.wav"; [ -f "$f" ] || continue
  lufs=$(ffmpeg -hide_banner -i "$f" -af loudnorm=print_format=summary -f null - 2>&1 | awk '/Input Integrated/{print $3}')
  flag=$(awk -v l="$lufs" 'BEGIN{print (l < -45) ? "  ← 很小聲，H3 可能沒生成音效" : ""}')
  echo "$sid $lufs LUFS$flag"
done
