#!/usr/bin/env bash
# Run the four PRDs one after another with ralph-tui, stopping at the first PRD that does not finish.
#   ralph/run-all.sh              # all PRDs in order, headless, resumes where it stopped
#   ralph/run-all.sh --from 2     # start at PRD 2
#   ralph/run-all.sh --only 3     # just PRD 3
#   ralph/run-all.sh --tui        # show the Ralph TUI instead of headless logs (single PRD recommended)
# A PRD counts as finished only when every story has "passes": true. Nothing is committed.
set -euo pipefail
cd "$(dirname "$0")/.."

FROM=1; ONLY=""; MODE="--headless"
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --only) ONLY="$2"; shift 2 ;;
    --tui) MODE=""; shift ;;
    *) echo "unknown flag $1"; exit 2 ;;
  esac
done

python3 ralph/build_prds.py --check >/dev/null || { echo "PRDs invalid; run: python3 ralph/build_prds.py"; exit 1; }

all_pass() {
  python3 - "$1" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if all(s["passes"] for s in d["userStories"]) else 1)
PY
}

i=0
for prd in ralph/prd-0*.json; do
  i=$((i+1))
  [ "$i" -lt "$FROM" ] && continue
  [ -n "$ONLY" ] && [ "$i" -ne "$ONLY" ] && continue
  if all_pass "$prd"; then echo "== $prd already complete"; continue; fi
  echo "== running $prd"
  resume=""
  [ -f .ralph-tui/session.json ] && grep -q "\"prdPath\": \"./$prd\"" .ralph-tui/session.json && resume="--resume"
  ralph-tui run --prd "./$prd" --iterations 0 $MODE --no-setup $resume || true
  if ! all_pass "$prd"; then
    echo "== $prd is not finished. Read the notes, fix or edit the story, then re-run this script."
    python3 ralph/build_prds.py --status
    exit 1
  fi
  echo "== $prd complete. Review the changes before the next PRD if you want (nothing is committed)."
done
echo "== all requested PRDs complete"
