#!/usr/bin/env bash
# Run one PRD with several models one after another: each model gets a bounded turn, and the next model
# continues the same session when the PRD is not finished. Nothing is committed.
#   ralph/run-models.sh ralph/proof-1.prd.json
#   ralph/run-models.sh ralph/proof-1.prd.json --models "nvidia/moonshotai/kimi-k2.6 ollama/qwen3.8:27b-64k"
#   ralph/run-models.sh ralph/proof-1.prd.json --iters 6 --minutes 25
# Keys (NVIDIA_NIM_API_KEY, CMDC_KEY) are read from .env if they are not already exported; they are never printed.
set -uo pipefail
cd "$(dirname "$0")/.."

PRD="${1:?usage: ralph/run-models.sh ralph/<name>.prd.json [--models \"m1 m2\"] [--iters N] [--minutes M]}"; shift
MODELS="nvidia/deepseek-ai/deepseek-v4.1-flash nvidia/moonshotai/kimi-k2.6 nvidia/z-ai/glm-5.3-flash nvidia/minimaxai/minimax-m3.1-flash nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b ollama/qwen3.8:27b-64k"
ITERS=8; MINUTES=30
while [ $# -gt 0 ]; do
  case "$1" in
    --models) MODELS="$2"; shift 2 ;;
    --iters) ITERS="$2"; shift 2 ;;
    --minutes) MINUTES="$2"; shift 2 ;;
    *) echo "unknown flag $1"; exit 2 ;;
  esac
done

[ -f .env ] && { set -a; . ./.env; set +a; }
python3 ralph/build_prds.py --check >/dev/null || { echo "PRDs invalid; run: python3 ralph/build_prds.py"; exit 1; }

done_count() {
  python3 - "$PRD" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); s = d["userStories"]
print(sum(1 for x in s if x["passes"]), len(s))
PY
}
all_pass() { read -r a b < <(done_count); [ "$a" -eq "$b" ]; }

mkdir -p .ralph-tui/models
# `ralph-tui run --model X` crashes in the opencode plugin (j.split is not a function, seen 3 Nov 2026), so the model is
# switched by rewriting the model line in .ralph-tui/config.toml; the original file is put back on exit.
cp .ralph-tui/config.toml .ralph-tui/config.toml.orig
trap 'mv -f .ralph-tui/config.toml.orig .ralph-tui/config.toml' EXIT
set_model() {
  python3 - "$1" <<'PY'
import re, sys
p = ".ralph-tui/config.toml"; s = open(p).read()
s = re.sub(r'(?m)^model = ".*"', f'model = "{sys.argv[1]}"', s, count=1)
open(p, "w").write(s)
PY
}
name="$(basename "$PRD" .json)"
n=0
for model in $MODELS; do
  n=$((n+1))
  if all_pass; then echo "== $PRD complete"; break; fi
  read -r before total < <(done_count)
  log=".ralph-tui/models/${name}.${n}.$(echo "$model" | tr '/:' '__').log"
  resume=""
  [ -f .ralph-tui/session.json ] && grep -q "\"prdPath\": \"./${PRD#./}\"" .ralph-tui/session.json && resume="--resume"
  echo "== [$n] model $model | stories passing $before/$total | log $log"
  set_model "$model"
  ralph-tui run --prd "./${PRD#./}" --iterations "$ITERS" --headless --no-setup $resume > "$log" 2>&1 &
  pid=$!
  waited=0
  while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt $((MINUTES*60)) ]; do sleep 10; waited=$((waited+10)); done
  if kill -0 "$pid" 2>/dev/null; then echo "   time limit ($MINUTES min) reached, stopping this model"; kill "$pid" 2>/dev/null; sleep 3; kill -9 "$pid" 2>/dev/null; fi
  wait "$pid" 2>/dev/null
  read -r after _ < <(done_count)
  echo "   result: $before -> $after of $total stories passing"
  echo "$(date -u +%FT%TZ) $name model=$model passing $before->$after/$total" >> .ralph-tui/models/summary.log
done
python3 ralph/build_prds.py --status | grep "$name" || true
all_pass && { echo "== done: every story passes (verify them yourself before trusting)"; exit 0; }
echo "== not finished after all models; read the story notes"; exit 1
