#!/usr/bin/env bash
# Operator commands for the v2 benchmark run (docs/13 section 12). ralph/glb-ops.prd.json calls these so an agent
# only starts, waits for and checks jobs. Jobs run detached and are resumable; one job runs at a time.
#   scripts/glb_ops.sh preflight            check Ollama, no job running, no RunPod pod; record the prompt hash
#   scripts/glb_ops.sh start dev1|glimmer|glimmer-think
#   scripts/glb_ops.sh wait JOB [SECONDS]   wait up to 540 s; exit 0 finished, 2 still running, 1 failed or never started
#   scripts/glb_ops.sh status [JOB]
#   scripts/glb_ops.sh freeze               after a PASS verdict on dev1: lock the prompt hash for the real runs
#   scripts/glb_ops.sh report               copy the v1 baselines in, then report and contact sheets for runs/glb_v2
# Overrides for tests: GLB_OPS_RUNS, GLB_OPS_BENCH, GLB_OPS_PROMPT, GLB_OPS_POLL, GLB_OPS_SKIP_CHECKS.
set -uo pipefail
cd "$(dirname "$0")/.."
RUNS="${GLB_OPS_RUNS:-runs/glb_v2}"
BENCH="${GLB_OPS_BENCH:-.venv/bin/python scripts/glb_bench.py}"
PROMPT="${GLB_OPS_PROMPT:-prompts/system_glb.txt}"
POLL="${GLB_OPS_POLL:-10}"
JOBS="$RUNS/jobs"
mkdir -p "$JOBS"

sha() { shasum -a 256 "$PROMPT" | cut -d' ' -f1; }
job_args() {
  case "$1" in
    dev1) echo "--out-root $RUNS/dev1 --only glimmer --briefs bench/glb/dev_briefs.jsonl" ;;
    glimmer) echo "--out-root $RUNS --only glimmer" ;;
    glimmer-think) echo "--out-root $RUNS --only glimmer-think" ;;
    *) return 1 ;;
  esac
}
job_total() { case "$1" in dev1) echo 12 ;; *) echo 48 ;; esac; }
job_raw() { case "$1" in dev1) echo "$RUNS/dev1/glimmer/raw" ;; *) echo "$RUNS/$1/raw" ;; esac; }
job_alive() { [ -f "$JOBS/$1.pid" ] && kill -0 "$(cat "$JOBS/$1.pid")" 2>/dev/null; }
any_alive() { for p in "$JOBS"/*.pid; do [ -f "$p" ] && job_alive "$(basename "$p" .pid)" && { echo "$(basename "$p" .pid)"; return 0; }; done; return 1; }
raw_count() { ls "$(job_raw "$1")" 2>/dev/null | wc -l | tr -d ' '; }

require_freeze() {
  [ -f "$RUNS/PROMPT_FROZEN.json" ] || { echo "REFUSED: the prompt is not frozen yet (run: scripts/glb_ops.sh freeze after dev1 passes)"; exit 1; }
  grep -q "\"sha256\": \"$(sha)\"" "$RUNS/PROMPT_FROZEN.json" || { echo "REFUSED: $PROMPT changed after it was frozen"; exit 1; }
}

cmd_preflight() {
  if [ -z "${GLB_OPS_SKIP_CHECKS:-}" ]; then
    curl -s localhost:11434/api/tags | grep -q "muse-glimmer:30b-mlx" || { echo "PREFLIGHT FAILED: Ollama is not serving muse-glimmer:30b-mlx"; exit 1; }
    if command -v runpodctl > /dev/null; then
      n=$(runpodctl pod list 2>/dev/null | python3 -c "import json,sys;print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
      [ "$n" = 0 ] || { echo "PREFLIGHT FAILED: $n RunPod pod(s) are running"; exit 1; }
    fi
  fi
  if j=$(any_alive); then echo "PREFLIGHT FAILED: job $j is still running"; exit 1; fi
  { echo "# v2 run state"; echo; echo "- preflight: $(date -u +%FT%TZ)"; echo "- prompt: $PROMPT sha256 $(sha)"; } > "$RUNS/STATE.md"
  echo "prompt sha256 $(sha)"
  echo "PREFLIGHT OK"
}

cmd_start() {
  job="${1:-}"; args=$(job_args "$job") || { echo "unknown job '$job' (dev1, glimmer, glimmer-think)"; exit 1; }
  if [ -f "$JOBS/$job.exit" ]; then
    if [ "$(cat "$JOBS/$job.exit")" = 0 ]; then echo "job $job already finished OK; not starting it again"; exit 0; fi
    rm -f "$JOBS/$job.exit"   # a failed job is resumable: finished briefs are skipped
  fi
  if j=$(any_alive); then
    echo "job $j is already running; one job at a time"
    [ "$j" = "$job" ] && exit 0 || exit 1
  fi
  case "$job" in glimmer|glimmer-think) require_freeze ;; esac
  sha > "$JOBS/$job.prompt_sha"
  ( nohup bash -c "$BENCH $args; echo \$? > '$JOBS/$job.exit'" > "$JOBS/$job.log" 2>&1 < /dev/null & echo $! > "$JOBS/$job.pid" )
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
  [ -f "$RUNS/PROMPT_FROZEN.json" ] && echo "prompt frozen: $(grep -o '"sha256": "[0-9a-f]*"' "$RUNS/PROMPT_FROZEN.json")"
  return 0
}

cmd_freeze() {
  verdict="$RUNS/dev1/judge.json"
  grep -q '"verdict": "PASS"' "$verdict" 2>/dev/null || { echo "REFUSED: no PASS verdict at $verdict (run: python3 scripts/glb_ops_judge.py dev $RUNS/dev1)"; exit 1; }
  [ "$(cat "$JOBS/dev1.prompt_sha" 2>/dev/null)" = "$(sha)" ] || { echo "REFUSED: the prompt changed since dev1 ran"; exit 1; }
  printf '{\n  "sha256": "%s",\n  "frozen_at": "%s",\n  "file": "%s"\n}\n' "$(sha)" "$(date -u +%FT%TZ)" "$PROMPT" > "$RUNS/PROMPT_FROZEN.json"
  cp "$PROMPT" "$RUNS/system_glb.frozen.txt"
  echo "FROZEN $(sha)"
}

cmd_report() {
  for m in glimmer glimmer-think; do [ -f "$RUNS/$m/validation.jsonl" ] || { echo "REFUSED: $RUNS/$m has no validation.jsonl yet"; exit 1; }; done
  # v1 baselines are copied in (read only from eval/) so the report compares v1 and v2 side by side
  [ -d "$RUNS/ccore-q8" ] || cp -R eval/glb_bench/ccore-q8 "$RUNS/ccore-q8"
  [ -d "$RUNS/glimmer-v1" ] || cp -R eval/glb_bench/glimmer "$RUNS/glimmer-v1"
  .venv/bin/python scripts/glb_report.py --root "$RUNS" --briefs bench/glb/briefs.jsonl || exit 1
  node scripts/glb_sheet.mjs --root "$RUNS" --out "$RUNS/sheet" --briefs bench/glb/briefs.jsonl || exit 1
  { echo "# v2 results (numbers copied from report.md)"; echo; cat "$RUNS/report.md"; } > "$RUNS/RESULTS.md"
  echo "REPORT OK: $RUNS/report.md $RUNS/sheet/rating.csv"
}

case "${1:-}" in
  preflight) cmd_preflight ;;
  start) shift; cmd_start "$@" ;;
  wait) shift; cmd_wait "$@" ;;
  status) shift; cmd_status "$@" ;;
  freeze) cmd_freeze ;;
  report) cmd_report ;;
  *) sed -n 2,10p "$0"; exit 2 ;;
esac
