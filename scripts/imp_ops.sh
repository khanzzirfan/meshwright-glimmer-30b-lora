#!/usr/bin/env bash
# Operator commands for the imp jobs (docs/14, ralph/imp-ops.prd.json) so an operator agent only starts, waits for and
# checks the long local jobs instead of running raw bench/repair commands. One job runs at a time, and the v3 prompt
# hash must match the frozen file before any job starts. Jobs run detached and are resumable.
#   scripts/imp_ops.sh preflight            Ollama up/down, the running job if any, the v3 hash check, imp-1 status
#   scripts/imp_ops.sh start v3s2|v3s3|repair-v3
#   scripts/imp_ops.sh wait JOB [SECONDS]   wait up to 540 s; exit 0 finished, 2 still running, 1 failed or never started
#   scripts/imp_ops.sh status [JOB]
# IMP_OPS_DRY=1 start JOB prints the real command instead of running it.
# Overrides for tests: IMP_OPS_RUNS, IMP_OPS_JOBS, IMP_OPS_BENCH, IMP_OPS_PROMPT, IMP_OPS_POLL, IMP_OPS_SKIP_CHECKS.
set -uo pipefail
cd "$(dirname "$0")/.."
RUNS="${IMP_OPS_RUNS:-runs/glb_v3}"
JOBS="${IMP_OPS_JOBS:-runs/imp/jobs}"
BENCH="${IMP_OPS_BENCH:-.venv/bin/python scripts/glb_bench.py}"
PROMPT="${IMP_OPS_PROMPT:-prompts/system_glb_v3.txt}"
POLL="${IMP_OPS_POLL:-10}"
FROZEN="$RUNS/PROMPT_FROZEN.json"
[ -n "${IMP_OPS_DRY:-}" ] || mkdir -p "$JOBS"

sha() { shasum -a 256 "$PROMPT" | cut -d' ' -f1; }
# the frozen file may be written with or without spaces around the colon, so pull the 64 hex value out
frozen_sha() { grep -o '"sha256"[[:space:]]*:[[:space:]]*"[0-9a-f]\{64\}"' "$FROZEN" 2>/dev/null | grep -o '[0-9a-f]\{64\}' | head -1; }
job_cmd() {
  case "$1" in
    v3s2) echo "$BENCH --out-root $RUNS --only glimmer-v3 --seed 2 --run-suffix -s2" ;;
    v3s3) echo "$BENCH --out-root $RUNS --only glimmer-v3 --seed 3 --run-suffix -s3" ;;
    repair-v3) echo ".venv/bin/python scripts/glb_repair.py --run $RUNS/glimmer-v3 --model-row glimmer-v3" ;;
    *) return 1 ;;
  esac
}
job_total() { echo 48; }
job_raw() {
  case "$1" in
    v3s2) echo "$RUNS/glimmer-v3-s2/raw" ;;
    v3s3) echo "$RUNS/glimmer-v3-s3/raw" ;;
    repair-v3) echo "$RUNS/glimmer-v3/repair/raw" ;;
  esac
}
job_alive() { [ -f "$JOBS/$1.pid" ] && kill -0 "$(cat "$JOBS/$1.pid")" 2>/dev/null; }
any_alive() { for p in "$JOBS"/*.pid; do [ -f "$p" ] && job_alive "$(basename "$p" .pid)" && { basename "$p" .pid; return 0; }; done; return 1; }
raw_count() { ls "$(job_raw "$1")" 2>/dev/null | wc -l | tr -d ' '; }
hash_ok() { [ -f "$FROZEN" ] && [ "$(frozen_sha)" = "$(sha)" ]; }

require_freeze() {
  [ -f "$FROZEN" ] || { echo "REFUSED: the v3 prompt is not frozen ($FROZEN is missing)"; exit 1; }
  [ "$(frozen_sha)" = "$(sha)" ] || { echo "REFUSED: $PROMPT changed after it was frozen"; exit 1; }
}

cmd_preflight() {
  if [ -z "${IMP_OPS_SKIP_CHECKS:-}" ]; then
    curl -s --max-time 5 localhost:11434/api/tags > /dev/null 2>&1 && echo "Ollama up" || echo "Ollama down"
  else
    echo "Ollama up/down: not checked"
  fi
  if j=$(any_alive); then echo "job running: $j"; else echo "no job running"; fi
  if hash_ok; then echo "v3 prompt hash: matches $(sha)"; else echo "v3 prompt hash: MISMATCH (frozen $(frozen_sha), current $(sha))"; fi
  python3 ralph/build_prds.py --status 2>/dev/null | grep imp-1 || echo "imp-1: status unavailable"
}

cmd_start() {
  job="${1:-}"; cmd=$(job_cmd "$job") || { echo "unknown job '$job' (v3s2, v3s3, repair-v3)"; exit 1; }
  [ -n "${IMP_OPS_DRY:-}" ] && { echo "$cmd"; exit 0; }
  if [ -f "$JOBS/$job.exit" ]; then
    if [ "$(cat "$JOBS/$job.exit")" = 0 ]; then echo "job $job already finished OK; not starting it again"; exit 0; fi
    rm -f "$JOBS/$job.exit"   # a failed job is resumable: finished briefs are skipped
  fi
  if j=$(any_alive); then
    echo "job $j is already running; one job at a time"
    [ "$j" = "$job" ] && exit 0 || exit 1
  fi
  require_freeze
  sha > "$JOBS/$job.prompt_sha"
  ( nohup bash -c "$cmd; echo \$? > '$JOBS/$job.exit'" > "$JOBS/$job.log" 2>&1 < /dev/null & echo $! > "$JOBS/$job.pid" )
  date -u +%FT%TZ > "$JOBS/$job.started"
  echo "started $job (pid $(cat "$JOBS/$job.pid")), raw $(raw_count "$job")/$(job_total "$job")"
}

cmd_wait() {
  job="${1:-}"; secs="${2:-540}"; [ "$secs" -gt 540 ] && secs=540
  [ -f "$JOBS/$job.started" ] || { echo "job $job was never started"; exit 1; }
  waited=0
  while [ ! -f "$JOBS/$job.exit" ] && job_alive "$job" && [ "$waited" -lt "$secs" ]; do sleep "$POLL"; waited=$((waited + POLL)); done
  n=$(raw_count "$job"); tot=$(job_total "$job")
  if [ -f "$JOBS/$job.exit" ]; then
    code=$(cat "$JOBS/$job.exit"); echo "job $job finished with exit $code, raw $n/$tot"
    [ "$code" = 0 ] && exit 0 || exit 1
  fi
  if job_alive "$job"; then echo "job $job still running, raw $n/$tot"; exit 2; fi
  echo "job $job stopped without an exit code, raw $n/$tot; start it again (it resumes)"; exit 1
}

cmd_status() {
  for p in "$JOBS"/*.started; do
    [ -f "$p" ] || continue; j=$(basename "$p" .started)
    if [ -f "$JOBS/$j.exit" ]; then st="finished exit $(cat "$JOBS/$j.exit")"; elif job_alive "$j"; then st="running"; else st="stopped"; fi
    echo "$j: $st, raw $(raw_count "$j")/$(job_total "$j"), started $(cat "$p")"
  done
  hash_ok && echo "v3 prompt hash matches $(sha)"
  return 0
}

case "${1:-}" in
  preflight) cmd_preflight ;;
  start) shift; cmd_start "$@" ;;
  wait) shift; cmd_wait "$@" ;;
  status) shift; cmd_status "$@" ;;
  *) sed -n 2,10p "$0"; exit 2 ;;
esac
