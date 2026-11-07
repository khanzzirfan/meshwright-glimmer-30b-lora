# 05. Export, serve, evaluate

## Merge and convert

```bash
bash scripts/export_gguf.sh out/lora Qwen/Qwen3.5-4B out/gguf
```

Steps inside the script:
1. Merge the LoRA into the base (`peft` `merge_and_unload`) and save HF weights to `out/gguf/merged`. If the folder has no `adapter_config.json` (a `--mode full` run, e.g. `out/full`), it is converted as is.
2. Convert with llama.cpp `convert_hf_to_gguf.py` to FP16 GGUF.
3. Quantise with `llama-quantize` to `Q4_K_M` and `Q8_0`.

You need a llama.cpp checkout. Set `LLAMA_CPP_DIR` (default `~/llama.cpp`) and build it once (`cmake -B build && cmake --build build -j`). ccore tested their GGUF with llama.cpp b11889; a recent build should work, but Qwen3.5 support is new, so **VERIFY** the converter recognises the architecture. If it does not, update llama.cpp first.

## Serve with Ollama

```bash
cd out/gguf
ollama create muse-threejs-4b -f Modelfile
ollama run muse-threejs-4b "A voxel lighthouse on a rocky island at night"
```

The generated `Modelfile` sets the system prompt from `prompts/system.txt` and the sampling settings ccore recommends: temperature 0.6-0.8, top_p 0.90-0.95, top_k 20-40, repeat penalty 1.0. LM Studio users: ccore warns to turn multi-token prediction off.

For the scripts, Ollama exposes an OpenAI-compatible API at `http://localhost:11434/v1`.

## Evaluate

Use the held-out briefs (`data/briefs.eval.jsonl`, written by `gen_briefs.py`).

```bash
python scripts/teacher_generate.py --briefs data/briefs.eval.jsonl --out eval/student_raw \
  --base-url http://localhost:11434/v1 --model muse-threejs-4b --api-key ollama --concurrency 1
node scripts/validate_scenes.mjs --raw eval/student_raw --scenes eval/student_scenes \
  --shots eval/student_shots --report eval/student_validation.jsonl
```

Run the same two commands against the teacher and the untouched Qwen3.5-4B for baselines.

### Metrics to report
| Metric | How |
|---|---|
| First-attempt pass rate | share of eval briefs with `ok: true`, by level 1-10 |
| Failure breakdown | counts of `js_error`, `blank`, `static`, `bad_import`, `no_html`, `external_dep` |
| Teacher gap | student pass rate minus teacher pass rate |
| Pass@4 | generate 4 per brief, any pass counts |
| Optional quality | Spark scores screenshot against brief, 1-5, blind to the code |
| Speed | tokens/second and seconds per scene on your Mac |

The pass rate from rendering is the number to quote; it is measured, unlike a vibe check. Keep every screenshot grid in `eval/` so you can show before/after.
