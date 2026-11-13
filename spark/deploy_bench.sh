#!/bin/bash
# 把 repo 的 spark/bench.py 部署到 Spark ~/h3-bench/bench.py（Studio 與漫畫流程共用的唯一一份）。
# 只能從 repo 部署，不要在 Spark 上直接改；改完先 commit 再跑本腳本。
# 有 H3／Demucs 在跑就拒絕，避免換掉正在用的檔案。舊檔備份為 bench.py.bak-<時間>。
set -euo pipefail
HOST=${H3_SPARK_HOST:-funsteam@100.89.149.50}
SRC="$(cd "$(dirname "$0")" && pwd)/bench.py"
python -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" "$SRC"
if ! git -C "$(dirname "$SRC")" diff --quiet HEAD -- bench.py; then
  echo "spark/bench.py 有未 commit 的改動，先 commit 再部署（FORCE=1 可略過）"; [ "${FORCE:-0}" = 1 ] || exit 1
fi
rev=$(git -C "$(dirname "$SRC")" log -1 --format=%h -- bench.py)
ssh -n "$HOST" 'docker ps --format "{{.Names}}" | grep -qE "^h3-|^demucs"' && { echo "Spark 上有 H3／Demucs 在跑，稍後再部署"; exit 3; }
scp -q "$SRC" "$HOST:h3-bench/bench.py.new"
ssh -n "$HOST" "cd ~/h3-bench && python3 -m py_compile bench.py.new \
  && { [ -f bench.py ] && cp bench.py bench.py.bak-\$(date +%Y%m%d-%H%M%S) || true; } \
  && mv bench.py.new bench.py && echo $rev > bench.py.rev && md5sum bench.py"
echo "已部署 spark/bench.py（commit $rev）"
