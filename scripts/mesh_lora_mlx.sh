#!/usr/bin/env bash
# End to end LoRA proof on this Mac with mlx-lm: (convert once) -> train -> generate the 30 held-out captions -> score.
#   bash scripts/mesh_lora_mlx.sh convert   # one time: downloads about 58 GB of BF16 weights and writes a 4-bit copy. ASKS FIRST.
#   bash scripts/mesh_lora_mlx.sh smoke     # 20 iterations, 2 captions: does it load, train, generate?
#   bash scripts/mesh_lora_mlx.sh full      # 600 iterations (about 2 epochs of 288 rows), then all 30 captions
# Nothing here is verified end to end yet; every stage prints what it is about to do.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
MODEL=${MODEL:-models/glimmer-4bit}            # local MLX copy of meta-models/Muse-Glimmer-30B
ADAPTER=${ADAPTER:-out/mesh-lora-mlx}
STAGE=${1:-smoke}

if [ "$STAGE" = "convert" ]; then
  echo "This downloads meta-models/Muse-Glimmer-30B (BF16, about 58 GB) and writes $MODEL (about 18 GB)."
  [ "${CONFIRM_DOWNLOAD:-}" = "yes" ] || { echo "Re-run with CONFIRM_DOWNLOAD=yes to proceed."; exit 1; }
  $PY -m mlx_lm convert --hf-path meta-models/Muse-Glimmer-30B --mlx-path "$MODEL" -q --q-bits 4
  exit 0
fi

[ -d "$MODEL" ] || { echo "No $MODEL. Run: CONFIRM_DOWNLOAD=yes bash scripts/mesh_lora_mlx.sh convert"; exit 1; }
$PY -m pip show mlx-lm >/dev/null 2>&1 || { echo "pip install mlx-lm first (tested with 0.32.2)"; exit 1; }
[ -f data/mesh/sft/mlx/train.jsonl ] || $PY scripts/mesh_sft_data.py

case "$STAGE" in
  smoke) ITERS=20; LIMIT="--limit 2"; OUT=eval/mesh_lora_mlx_smoke ;;
  full)  ITERS=600; LIMIT=""; OUT=eval/mesh_lora_mlx ;;
  *) echo "usage: $0 convert|smoke|full"; exit 2 ;;
esac

echo "== train: $ITERS iterations, adapter -> $ADAPTER"
$PY -m mlx_lm lora --model "$MODEL" --train --data data/mesh/sft/mlx -c scripts/mesh_lora_mlx.yaml \
  --fine-tune-type lora --mask-prompt --num-layers 24 --batch-size 1 --iters "$ITERS" --learning-rate 1e-4 \
  --max-seq-length 9728 --grad-checkpoint --steps-per-eval 20 --val-batches 6 --save-every 100 --adapter-path "$ADAPTER" \
  2>&1 | tee "${ADAPTER##*/}.train.log"

echo "== generate held-out captions with the adapter -> $OUT"
$PY scripts/mesh_generate.py --backend mlx --mlx-model "$MODEL" --adapter "$ADAPTER" --out "$OUT" $LIMIT

echo "== score against the real meshes"
$PY scripts/mesh_quality.py --run "$OUT" --pairs "$OUT/pairs.jsonl"
echo "before: eval/mesh_baseline/summary.json   after: $OUT/summary.json and $OUT/quality.json"
