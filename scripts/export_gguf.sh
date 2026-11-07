#!/usr/bin/env bash
# usage: export_gguf.sh <lora_or_full_dir> <base_model> <out_dir>
# Merges a LoRA into the base (a full fine-tune is used as is), converts to GGUF,
# quantises, writes an Ollama Modelfile.
set -euo pipefail
ADAPTER="${1:?lora or full model dir}"; BASE="${2:-Qwen/Qwen3.5-4B}"; OUT="${3:-out/gguf}"
LLAMA="${LLAMA_CPP_DIR:-$HOME/llama.cpp}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$OUT"

if [ ! -f "$ADAPTER/adapter_config.json" ]; then
  MERGED="$ADAPTER"
else
MERGED="$OUT/merged"
python3 - "$ADAPTER" "$BASE" "$MERGED" <<'PY'
import sys, torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
adapter, base, out = sys.argv[1:4]
m = AutoModelForCausalLM.from_pretrained(base, dtype=torch.bfloat16)
m = PeftModel.from_pretrained(m, adapter).merge_and_unload()
m.save_pretrained(out); AutoTokenizer.from_pretrained(base).save_pretrained(out)
PY
fi

python3 "$LLAMA/convert_hf_to_gguf.py" "$MERGED" --outfile "$OUT/model-f16.gguf" --outtype f16
"$LLAMA/build/bin/llama-quantize" "$OUT/model-f16.gguf" "$OUT/model-Q4_K_M.gguf" Q4_K_M
"$LLAMA/build/bin/llama-quantize" "$OUT/model-f16.gguf" "$OUT/model-Q8_0.gguf" Q8_0

cat > "$OUT/Modelfile" <<EOF
FROM ./model-Q4_K_M.gguf
PARAMETER temperature 0.7
PARAMETER top_p 0.95
PARAMETER top_k 30
PARAMETER repeat_penalty 1.0
PARAMETER num_ctx 16384
SYSTEM """$(cat "$HERE/prompts/system.txt")"""
EOF
echo "next: cd $OUT && ollama create muse-threejs-4b -f Modelfile"
