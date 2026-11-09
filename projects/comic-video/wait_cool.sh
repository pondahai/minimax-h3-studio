# 段與段之間的冷卻：GPU 降到 COOL_TEMP 以下就繼續，取代固定 sleep 60。由 run_jobs.sh / run_series.sh source。
# COOL_TEMP（預設 58，Spark 閒置約 45°C）、COOL_MIN 最短等待（預設 10s，讓上一段收尾）、COOL_MAX 上限（預設 90s）
# 讀不到溫度（N/A）就退回等滿 COOL_MAX。
wait_cool() {
  local target=${COOL_TEMP:-58} min=${COOL_MIN:-10} max=${COOL_MAX:-90} t temp
  sleep "$min"; t=$min
  while [ "$t" -lt "$max" ]; do
    temp=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
    if [[ "$temp" =~ ^[0-9]+$ ]] && [ "$temp" -le "$target" ]; then
      echo "$(date -Is) 冷卻 ${t}s，GPU ${temp}°C"; return
    fi
    sleep 5; t=$((t + 5))
  done
  echo "$(date -Is) 冷卻達上限 ${max}s，GPU ${temp:-?}°C"
}
