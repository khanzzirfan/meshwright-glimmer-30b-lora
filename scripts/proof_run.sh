#!/usr/bin/env bash
# One command from dataset to verdict for the proof ladder.
#   bash scripts/proof_run.sh one  --workdir /tmp/proof-one
#   bash scripts/proof_run.sh seen --workdir /tmp/proof-seen
# Adds the learning-rate guard: 2e-4 diverged on 3 Nov 2026 (loss 0.78 to 11).
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-.venv/bin/python}
[ -x "$PY" ] || PY=python3
MODEL=Qwen/Qwen2.5-0.5B-Instruct
ITERS=
LR=3e-5
MAX_SEQ=9728
MAX_TOKENS=8000
WORKDIR=
RUNG=
DRY_RUN=0
FORCE_LR=0

usage() {
  cat >&2 <<'EOF'
usage: bash scripts/proof_run.sh one|seen [options]

  one                    memorise one median mesh (default 200 iterations)
  seen                   reproduce 15 spread meshes (default 600 iterations)

  --model NAME           MLX model or Hugging Face repo (default Qwen/Qwen2.5-0.5B-Instruct)
  --iters N              training iterations (default 200 for one, 600 for seen)
  --lr RATE              learning rate (default 3e-5; above 1e-4 needs --force-lr)
  --max-seq N            training sequence length (default 9728)
  --workdir DIR          output folder (default a new folder under /tmp)
  --force-lr             allow a learning rate above 1e-4
  --dry-run              echo the commands and run none of them
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    one|seen) RUNG="$1"; shift ;;
    --model) MODEL="$2"; shift 2 ;;
    --iters) ITERS="$2"; shift 2 ;;
    --lr) LR="$2"; shift 2 ;;
    --max-seq) MAX_SEQ="$2"; shift 2 ;;
    --workdir) WORKDIR="$2"; shift 2 ;;
    --force-lr) FORCE_LR=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

if [ -z "$RUNG" ]; then
  echo "a rung is required: one or seen" >&2
  usage
  exit 2
fi

if [ -z "$ITERS" ]; then
  case "$RUNG" in
    one) ITERS=200 ;;
    seen) ITERS=600 ;;
  esac
fi
[ -n "$WORKDIR" ] || WORKDIR="/tmp/proof-$RUNG-$$"

if [ "$FORCE_LR" -eq 0 ] && awk -v lr="$LR" 'BEGIN { exit !(lr > 1e-4) }'; then
  echo "refusing --lr $LR: learning rate 2e-4 diverged on 3 Nov 2026 (loss 0.78 to 11)." >&2
  echo "Use --lr 3e-5 or lower, or pass --force-lr to run at $LR anyway." >&2
  exit 2
fi

case "$RUNG" in
  one) PICK=(--pick median --n 1) ;;
  seen) PICK=(--pick spread --n 15) ;;
esac

# Echo every command before running it; --dry-run only echoes. The first command
# prepares the work folder, the next four are the dataset -> train -> score -> verdict pipeline.
run() {
  printf '+ %s\n' "$*"
  [ "$DRY_RUN" -eq 1 ] && return 0
  "$@"
}

run mkdir -p "$WORKDIR"

run "$PY" scripts/proof_data.py --sft data/mesh/sft/train.jsonl "${PICK[@]}" \
  --repeat 1 --out-dir "$WORKDIR"

if [ "$RUNG" = "one" ]; then
  echo "estimate: rung one training ($ITERS iterations) should take roughly 10 minutes on this Mac"
else
  echo "estimate: rung seen training ($ITERS iterations) time is not measured"
fi

run "$PY" -m mlx_lm lora --model "$MODEL" --train --data "$WORKDIR" \
  -c scripts/mesh_lora_mlx.yaml --fine-tune-type lora --mask-prompt --num-layers 24 \
  --batch-size 1 --iters "$ITERS" --learning-rate "$LR" --max-seq-length "$MAX_SEQ" \
  --grad-checkpoint --steps-per-eval 20 --val-batches 6 --save-every 100 \
  --adapter-path "$WORKDIR/adapter"

run "$PY" scripts/proof_score.py --targets "$WORKDIR/targets.json" \
  --sft-system-from "$WORKDIR/train.jsonl" --model "$MODEL" --adapter "$WORKDIR/adapter" \
  --max-tokens "$MAX_TOKENS" --temperature 0.0 --out "$WORKDIR/report.json"

run "$PY" scripts/proof_ladder.py --report "$RUNG=$WORKDIR/report.json"
