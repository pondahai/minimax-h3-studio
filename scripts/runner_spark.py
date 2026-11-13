#!/usr/bin/env python3
"""Run MiniMax H3 jobs on the DGX Spark (h3-bench container) instead of Colab.

Same job contract as the Colab notebook: run_batch() builds the H3_* env values, this transport
copies files over scp, runs bench.py in `docker run h3-bench` over ssh, and copies the MP4 back.
Spark runs one of H3 / TTS / Qwen-Image at a time, so start() refuses when H3 or Demucs is
already running or Qwen-Image is mid-job, and otherwise stops the idle services the same way
projects/comic-video/pipeline.sh does.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Callable

import runner

HOST = os.environ.get("H3_SPARK_HOST", "funsteam@100.89.149.50")
WORK_ROOT = os.environ.get("H3_SPARK_WORK", "/home/funsteam/h3-studio")
BENCH_ROOT = "/home/funsteam/h3-bench"
# 唯一一份 H3 推論腳本：repo 的 spark/bench.py，用 spark/deploy_bench.sh 部署；漫畫流程也用同一支
BENCH_PY = f"{BENCH_ROOT}/bench.py"
IMAGE = "h3-bench:latest"
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30"]


class SparkBusyError(RuntimeError):
    # run_batch 看到 busy 就不呼叫 stop()：被拒絕的工作沒有停過任何服務，不能去還原別人停掉的 8002
    busy = True


def _ssh(script: str, *, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", *SSH_OPTS, HOST, "bash -s"], input=script.encode("utf-8"),
                          capture_output=True, timeout=timeout, check=False)


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").strip()


def _busy_flag(busy: bool) -> str:
    body = '{"busy": %s, "reason": "H3（Studio）正在運作"}' % ("true" if busy else "false")
    return (f"curl -s -m 3 -X POST http://127.0.0.1:7860/busy_status -H 'Content-Type: application/json' "
            f"-d {shlex.quote(body)} > /dev/null 2>&1 || true\n")


# 交班：H3／Demucs 在跑或 Qwen-Image 手上有工作就拒絕（回 exit 3），否則照 pipeline.sh 停掉佔記憶體的服務
TAKEOVER = r"""
set -u
if docker ps --format '{{.Names}}' | grep -qE '^h3-|^demucs'; then echo "Spark 忙碌：已有 H3／Demucs 在跑"; exit 3; fi
if docker ps --format '{{.Names}}' | grep -qx qwen-image-comfyui; then
  busy=$(curl -s -m 5 http://127.0.0.1:8188/queue 2>/dev/null | python3 -c '
import sys, json
try:
    q = json.load(sys.stdin)
    print(1 if (q.get("queue_running") or q.get("queue_pending")) else 0)
except Exception:
    print(0)
')
  if [ "$busy" = "1" ]; then echo "Spark 忙碌：Qwen-Image 正在生圖"; exit 3; fi
  docker stop qwen-image-comfyui > /dev/null && echo "[*] 已停掉 qwen-image-comfyui"
fi
# 8006（qwen3.8-nvfp4）常駐不停（2026-11-06 起），改停 8002 讓出記憶體；H3 跑完由 RESTORE 拉回來
pgrep -f "[l]lama-server.*--port 8002" > /dev/null && pkill -f "[l]lama-server.*--port 8002" && echo "[*] 已停掉 8002（llama.cpp）"
pgrep -f "[c]hinese_tts_server.py" > /dev/null && pkill -f "[c]hinese_tts_server.py" && echo "[*] 已停掉 TTS"
"""


# H3 跑完（正常或中止）：拉回 8002，8006 若不在也順手啟動（與 pipeline.sh 的 restore_services 一致）
# 還有別的 H3／Demucs 在跑（自己的容器除外）就什麼都不做：8002 和 busy 旗標留給最後一個跑完的人還原，
# 否則 8002（約 55 GB）會在別人推論中途被拉回來，H3＋8006＋8002 搶統一記憶體、塞爆 swap（2026-11-13 卡機）
def _restore(own_container: str) -> str:
    return (f"others=$(docker ps --format '{{{{.Names}}}}' | grep -E '^h3-|^demucs' | grep -vx {shlex.quote(own_container)})\n"
            "if [ -n \"$others\" ]; then echo \"[*] 還有 $others 在跑，不還原 8002／不清 busy 旗標\"; exit 0; fi\n"
            + _busy_flag(False) + RESTORE)


RESTORE = r"""
if ! pgrep -f "[l]lama-server.*--port 8002" > /dev/null && [ -x ~/models/qwen3.6-abliterated/start.sh ]; then
  setsid -f ~/models/qwen3.6-abliterated/start.sh >> ~/models/qwen3.6-abliterated/llama-server.log 2>&1 < /dev/null
fi
docker ps --format '{{.Names}}' | grep -qx qwen3.8-nvfp4 || docker start qwen3.8-nvfp4 > /dev/null 2>&1
true
"""


class SparkTransport:
    name = "spark"
    remote_root = "/content/run"
    max_exec_timeout = 3600.0  # Spark 比 A100 慢，首次載入模型也較久

    def _dir(self, session: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session):
            raise ValueError("Invalid session name.")
        return f"{WORK_ROOT}/{session}"

    def _host_path(self, session: str, remote: str) -> str:
        if not remote.startswith(self.remote_root + "/"):
            raise ValueError(f"Remote path must be under {self.remote_root}: {remote}")
        return f"{self._dir(session)}/{remote[len(self.remote_root) + 1:]}"

    def _container(self, session: str) -> str:
        return f"h3-studio-{session}"

    def check(self) -> None:
        pass

    def start(self, session: str, gpu: str, high_mem: bool) -> None:
        result = _ssh(TAKEOVER + _busy_flag(True) + f"mkdir -p {shlex.quote(self._dir(session))}\n", timeout=180)
        output = _text(result.stdout + result.stderr)
        if result.returncode == 3:
            raise SparkBusyError(output or "Spark 忙碌中")
        if result.returncode != 0:
            raise RuntimeError(f"無法連線或準備 Spark（exit {result.returncode}）：{output[-400:]}")
        if output:
            print(output, flush=True)

    def stop(self, session: str) -> None:
        _ssh(f"rm -rf {shlex.quote(self._dir(session))}\n" + _restore(self._container(session)), timeout=60)

    def emergency_stop(self, session: str) -> None:
        try:
            _ssh(f"docker kill {shlex.quote(self._container(session))} > /dev/null 2>&1\n"
                 f"rm -rf {shlex.quote(self._dir(session))}\n" + _restore(self._container(session)), timeout=60)
        except Exception as exc:
            print(f"[!] 中止 Spark 容器失敗：{exc}", flush=True)

    def upload(self, session: str, local: Path, remote: str, *, label: str, timeout: float,
               on_line: Callable[[str], None], stall_timeout: float | None = 120) -> None:
        runner.stream_command(["scp", "-q", *SSH_OPTS, str(local), f"{HOST}:{self._host_path(session, remote)}"],
                              label=label, timeout=timeout, on_line=on_line, stall_timeout=None)

    def execute(self, session: str, env_values: list[str], *, job_id: str, work_dir: Path, label: str,
                timeout: int, on_line: Callable[[str], None]) -> None:
        env_args = " ".join(f"-e {shlex.quote(value)}" for value in env_values)
        command = (
            f"docker run --rm --name {shlex.quote(self._container(session))} --gpus all --ipc host "
            f"-e PYTORCH_NO_CUDA_MEMORY_CACHING=1 -e PYTHONUNBUFFERED=1 {env_args} "
            f"-v {BENCH_ROOT}/ComfyUI:/content/ComfyUI -v {BENCH_ROOT}/models:/content/ComfyUI/models "
            f"-v {shlex.quote(self._dir(session))}:{self.remote_root} -v {BENCH_PY}:/content/bench.py:ro "
            f"--entrypoint sh {IMAGE} -c 'touch /content/.h3_comfyui_setup_v1 && cd /content && python3 /content/bench.py'"
        )
        try:
            runner.stream_command(["ssh", *SSH_OPTS, HOST, command], label=label, timeout=timeout + 60,
                                  on_line=on_line, on_abort=lambda: self.emergency_stop(session),
                                  stall_timeout=runner.DEFAULT_STALL_TIMEOUT_SECONDS)
        except runner.ColabCommandError:
            # ssh 斷線時容器仍在 Spark 上跑，要主動砍掉才會釋放 GPU
            self.emergency_stop(session)
            raise

    def download(self, session: str, remote: str, local: Path, *, label: str,
                 on_line: Callable[[str], None]) -> None:
        runner.stream_command(["scp", "-q", *SSH_OPTS, f"{HOST}:{self._host_path(session, remote)}", str(local)],
                              label=label, timeout=600, on_line=on_line, stall_timeout=None)


SPARK = SparkTransport()
