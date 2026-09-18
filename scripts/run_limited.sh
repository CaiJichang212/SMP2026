#!/usr/bin/env bash
set -euo pipefail

if (( $# == 0 )); then
  printf '用法：%s 命令 [参数...]\n' "$0" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$root/logs"
exec 9>"$root/logs/.experiment.lock"
if ! flock -n 9; then
  printf '已有受限实验正在运行。\n' >&2
  exit 1
fi

first_cpu="$(awk '/^Cpus_allowed_list:/ { split($2, parts, /[-,]/); print parts[1] }' /proc/self/status)"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/smp20260918-uv-cache}"

# 虚拟地址空间上限采取保守值；每次运行仍需记录峰值常驻内存。
exec taskset -c "$first_cpu" nice -n 10 timeout --signal=TERM --kill-after=10s 600s \
  prlimit --as=$(( 2500 * 1024 * 1024 )) -- "$@"
