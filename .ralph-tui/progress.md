# Ralph Progress Log

This file tracks progress across iterations. Agents update this file
after each iteration and it's included in prompts for context.

## Codebase Patterns (Study These First)

*Add reusable patterns discovered during development here.*

---


## 2026-11-07 - US-002
- Ran `bash scripts/glb_ops.sh start dev1`; output: "started dev1 (pid 82340), raw 0/12"
- `bash scripts/glb_ops.sh status` output: "dev1: running, raw 0/12, started 2026-11-07T12:35:07Z"
- No 'one job at a time' message; no other job running.
- Files changed: none (only this progress entry)
- **Learnings:**
  - start is idempotent-ish: reports started / already running / already finished OK.
  - Job runs detached; later stories should poll `status` rather than wait.
---

## 2026-11-07 - US-003
- `bash scripts/glb_ops.sh wait dev1` output: "job dev1 finished with exit 0, raw 12/12"; wait exit code 0.
- Ran `python3 scripts/glb_ops_judge.py dev runs/glb_v2/dev1` (exit 0), which wrote runs/glb_v2/dev1/judge.json. Judge JSON, unchanged:
```
{
  "n": 12,
  "valid": 11,
  "animated": 3,
  "animated_with_animation": 3,
  "reasons": {
    "ok": 11,
    "js_error": 1,
    "no_download": 1
  },
  "dev_animated_with_animation": 3,
  "verdict": "PASS",
  "rule": "n == 12, valid >= 10, animated dev briefs with an animation >= 2 of 3"
}
```
- Files changed: none in the repo besides this entry (runs/glb_v2/dev1/judge.json was created by the judge).
- **Learnings:**
  - `wait` returns 0 when finished, 2 when still running; it finished within one call here.
  - The judge is not run by `wait`; run `glb_ops_judge.py dev runs/glb_v2/dev1` yourself. `freeze` refuses without a PASS in judge.json.
  - The reasons counts sum to 13 (11+1+1) while n is 12. I did not investigate; the verdict is still PASS under the stated rule.
---

## 2026-11-07 - US-004
- Ran `bash scripts/glb_ops.sh freeze`; output: "FROZEN e4a89010c8b4297c3705d16cce4c08fa96929b7f5e1848d93b799a98817e5601" (exit 0).
- Created runs/glb_v2/PROMPT_FROZEN.json (frozen_at 2026-11-07T12:50:03Z) and runs/glb_v2/system_glb.frozen.txt (2664 bytes).
- The sha256 equals the one in runs/glb_v2/STATE.md (preflight) and jobs/dev1.prompt_sha, so the prompt was not changed after dev1.
- Files changed: none in the repo besides this entry (the two runs/glb_v2 files were created by freeze).
- **Learnings:**
  - freeze checks judge.json for PASS and that dev1.prompt_sha matches the current prompt hash; it refuses otherwise.
  - The story 1 notes were not in progress.md (it starts at US-002), so I compared against STATE.md and dev1.prompt_sha instead.
---

## 2026-11-07 - US-005
- Ran `bash scripts/glb_ops.sh start glimmer`; output: "started glimmer (pid 85323), raw 0/48" (exit 0).
- `bash scripts/glb_ops.sh status` output:
  - "dev1: finished exit 0, raw 12/12, started 2026-11-07T12:35:07Z"
  - "glimmer: running, raw 0/48, started 2026-11-07T12:54:25Z"
  - "prompt frozen: "sha256": "e4a89010c8b4297c3705d16cce4c08fa96929b7f5e1848d93b799a98817e5601""
- Only glimmer is running (dev1 finished). Files changed: none besides this entry.
- **Learnings:**
  - start prints the pid and raw progress; the job is detached, so later stories should poll `status`/`wait`.
---

## 2026-11-08 - US-006
- `bash scripts/glb_ops.sh wait glimmer` was called 5 times; the first four exited 2 ("still running, raw 17/48", "27/48", "37/48", "47/48"), the fifth exited 0: "job glimmer finished with exit 0, raw 48/48".
- `wc -l runs/glb_v2/glimmer/validation.jsonl` output: "48 runs/glb_v2/glimmer/validation.jsonl"
- Summary printed at the end of runs/glb_v2/jobs/glimmer.log (copied unchanged; it is a text line, not JSON, no JSON summary was printed): `pass rate 91.7% { ok: 44, js_error: 4, no_download: 4 }`
- Generation line from the log: "done, 0 failed (rerun to retry), 0 skipped by budget, 124918 tokens used"; generation took 40:40 per the progress bar.
- Files changed: none besides this entry.
- **Learnings:**
  - A full 48-brief run takes ~41 min, i.e. about 5 `wait` calls of 540 s; `wait` also runs validation before exiting 0.
  - reasons here sum to 52 (44+4+4) for 48 files, same double-counting as dev1 (js_error and no_download co-occur on the same brief); not investigated.
---

## 2026-11-08 - US-007
- Checked glimmer first: runs/glb_v2/jobs/glimmer.exit exists and status showed "glimmer: finished exit 0, raw 48/48, started 2026-11-07T12:54:25Z".
- Ran `bash scripts/glb_ops.sh start glimmer-think`; output: "started glimmer-think (pid 90305), raw 0/48" (exit 0, not REFUSED).
- `bash scripts/glb_ops.sh status` output:
  - "dev1: finished exit 0, raw 12/12, started 2026-11-07T12:35:07Z"
  - "glimmer-think: running, raw 0/48, started 2026-11-07T13:40:57Z"
  - "glimmer: finished exit 0, raw 48/48, started 2026-11-07T12:54:25Z"
- Files changed: none besides this entry.
- **Learnings:**
  - Next story should poll with `bash scripts/glb_ops.sh wait glimmer-think` (expect ~5 calls, as for glimmer).
---

## 2026-11-08 - US-008
- `bash scripts/glb_ops.sh wait glimmer-think` was called repeatedly; every call but the last exited 2 ("still running", raw count rose 3/48 ... 47/48), the last exited 0: "job glimmer-think finished with exit 0, raw 48/48".
- `wc -l runs/glb_v2/glimmer-think/validation.jsonl` output: "48 runs/glb_v2/glimmer-think/validation.jsonl"
- Summary printed at the end of runs/glb_v2/jobs/glimmer-think.log (copied unchanged; text line, not JSON): `pass rate 93.8% { ok: 45, js_error: 3, no_download: 3 }`
- `status` output: "glimmer-think: finished exit 0, raw 48/48, started 2026-11-07T13:40:57Z"
- Files changed: none besides this entry.
- **Learnings:**
  - Thinking run advances ~2-3 briefs per 540 s wait (roughly 17+ wait calls total).
  - reasons sum to 51 (45+3+3) for 48 files, same js_error/no_download double counting as before; not investigated.
---

## 2026-11-08 - US-009
- Ran `bash scripts/glb_ops.sh report`: printed `REPORT OK: runs/glb_v2/report.md runs/glb_v2/sheet/rating.csv`; "rendered 162, skipped 0, already done 0, rating rows 192".
- runs/glb_v2/report.md, RESULTS.md, sheet/rating.csv all exist.
- `grep -c '^| ' runs/glb_v2/report.md` -> 31
- `sed -n 1,12p runs/glb_v2/report.md` Models table (Briefs: 48):
  - ccore-q8: 62.5% (48.4%-74.8%), animated 7/11, median tris 2476, max 21030, median tokens 14942, median s 736.495
  - glimmer: 91.7% (80.4%-96.7%), animated 8/11, median tris 581, max 3312, median tokens 1950.5, median s 50.6923
  - glimmer-think: 93.8% (83.2%-97.9%), animated 7/11, median tris 304, max 6876, median tokens 5828.5, median s 191.6
  - glimmer-v1: 89.6% (77.8%-95.5%), animated 2/11, median tris 484, max 13932, median tokens 1797.5, median s 50.4875
- Files changed: none by me (outputs are generated under runs/glb_v2/).
- **Learnings:** report command is idempotent; recognisable column shows "not rated" until rating.csv is filled in.
---
