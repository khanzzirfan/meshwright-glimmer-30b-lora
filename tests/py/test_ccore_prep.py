import hashlib
import json
from pathlib import Path

import pytest

import ccore_prep
import mesh_lora_hf

ROOT = Path(__file__).resolve().parents[2]


def html_answer(tag, pad=0):
    return "```html\n<html>" + tag + "</html>\n```\n<button>Export GLB</button>" + "x" * pad


def record(row_id, title, domain, answer, user="Make it.", reasoning="long reasoning trace"):
    return {
        "id": row_id,
        "title": title,
        "domain": domain,
        "messages": [
            {"role": "system", "content": "CCORE SYSTEM"},
            {"role": "user", "content": user},
            {"role": "assistant", "content": answer, "reasoning_content": reasoning},
        ],
    }


def write_parquet(path, records):
    import pyarrow as pa
    import pyarrow.parquet as pq

    messages = pa.list_(pa.struct([("role", pa.string()), ("content", pa.string()), ("reasoning_content", pa.string())]))
    table = pa.table({
        "id": pa.array([r["id"] for r in records], pa.string()),
        "title": pa.array([r["title"] for r in records], pa.string()),
        "domain": pa.array([r["domain"] for r in records], pa.string()),
        "messages": pa.array([r["messages"] for r in records], messages),
    })
    pq.write_table(table, path)


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


@pytest.fixture
def system_file(tmp_path):
    path = tmp_path / "system.txt"
    path.write_text("TRAIN SYSTEM PROMPT")
    return path


@pytest.fixture
def dataset(tmp_path, system_file):
    parquet = tmp_path / "parquet"
    parquet.mkdir()
    write_parquet(parquet / "train-00000.parquet", [
        record("t1", "Crater Lamp", "props_and_tools", html_answer("keep")),
        record("t2", "Big Thing", "furniture", html_answer("long", pad=300)),
        record("t3", "No Block", "food", "no code block and no button here"),
        record("t4", "Wooden Crate", "props_and_tools", html_answer("eval")),
        record("t5", "Crater Lamp Copy", "props_and_tools", html_answer("keep")),
        record("t6", "Copper Kettle", "props_and_tools", html_answer("keep2")),
    ])
    write_parquet(parquet / "validation-00000.parquet", [
        record("v1", "Silver Goblet", "nature", html_answer("val")),
    ])
    return parquet


def run_main(out, parquet, system, *extra, max_chars="100"):
    ccore_prep.main(["--parquet-dir", str(parquet), "--out", str(out),
                     "--max-chars", max_chars, "--system", str(system), *extra])


def test_rows_pass_check_data_and_use_the_system_prompt(tmp_path, system_file, dataset):
    out = tmp_path / "phase2"
    run_main(out, dataset, system_file)

    train = read_rows(out / "train.jsonl")
    val = read_rows(out / "val.jsonl")
    assert len(train) == 2 and len(val) == 1

    mesh_lora_hf.check_data(str(out))  # the phase 2 format mesh_lora_hf.py reads

    row = train[0]
    assert set(row) == {"id", "domain", "title", "prompt", "completion"}
    assert [m["role"] for m in row["prompt"]] == ["system", "user"]
    assert row["prompt"][0]["content"] == "TRAIN SYSTEM PROMPT"
    assert [m["role"] for m in row["completion"]] == ["assistant"]
    assert "reasoning" not in json.dumps(row)  # reasoning_content is dropped


def test_drop_counts_and_kept_rows_match_the_fixture(tmp_path, system_file, dataset):
    out = tmp_path / "phase2"
    run_main(out, dataset, system_file)

    stats = json.loads((out / "stats.json").read_text())
    assert stats["splits"]["train"]["kept"] == 2
    assert stats["splits"]["train"]["dropped"] == {
        "no_html": 1, "too_long": 1, "eval_subject": 1, "duplicate": 1,
    }
    assert stats["splits"]["val"]["kept"] == 1
    assert stats["splits"]["val"]["dropped"] == {
        "no_html": 0, "too_long": 0, "eval_subject": 0, "duplicate": 0,
    }
    assert stats["kept_by_domain"]["train"] == {"props_and_tools": 2}
    assert stats["kept_by_domain"]["val"] == {"nature": 1}

    titles = [r["title"] for r in read_rows(out / "train.jsonl")]
    assert "Crater Lamp" in titles      # 'Crater' is not 'crate' as a whole word
    assert "Wooden Crate" not in titles  # 'crate' is an eval subject


def test_stats_hashes_and_lengths(tmp_path, system_file, dataset):
    out = tmp_path / "phase2"
    run_main(out, dataset, system_file)

    stats = json.loads((out / "stats.json").read_text())
    assert stats["max_chars"] == 100
    assert stats["system_file"] == str(system_file)
    assert stats["system_sha256"] == hashlib.sha256(system_file.read_bytes()).hexdigest()
    assert stats["leak_file"] == "bench/glb/eval_subjects.json"
    assert stats["leak_file_sha256"] == hashlib.sha256(
        (ROOT / "bench" / "glb" / "eval_subjects.json").read_bytes()
    ).hexdigest()
    assert {(i["file"], i["split"]) for i in stats["inputs"]} == {
        ("train-00000.parquet", "train"), ("validation-00000.parquet", "val"),
    }
    for item in stats["inputs"]:
        assert item["sha256"] == hashlib.sha256((dataset / item["file"]).read_bytes()).hexdigest()

    lengths = sorted(len(r["completion"][0]["content"]) for r in read_rows(out / "train.jsonl"))
    assert stats["completion_chars"]["train"] == {"count": 2, "median": lengths[1], "max": lengths[-1]}


def test_system_ccore_is_the_pinned_prompt(tmp_path, dataset):
    out = tmp_path / "phase2"
    ccore_prep.main(["--parquet-dir", str(dataset), "--out", str(out), "--max-chars", "100"])

    stats = json.loads((out / "stats.json").read_text())
    assert stats["system_file"] == "prompts/ccore_glb_system.txt"
    assert stats["system_sha256"] == hashlib.sha256(
        (ROOT / "prompts" / "ccore_glb_system.txt").read_bytes()
    ).hexdigest()
    assert read_rows(out / "train.jsonl")[0]["prompt"][0]["content"] == (
        (ROOT / "prompts" / "ccore_glb_system.txt").read_text()
    )


def write_extra_run(base, records):
    run = base / "run"
    (run / "raw").mkdir(parents=True)
    (run / "validation.jsonl").write_text("".join(json.dumps({"id": i, "ok": ok}) + "\n" for i, ok in records))
    (run / "assembly.jsonl").write_text("".join(
        json.dumps({"id": i, "kind": "static", "assembly": {"assembled": ok}}) + "\n" for i, ok in records))
    for i, _ in records:
        (run / "raw" / f"{i}.json").write_text(json.dumps({
            "id": i, "brief": {"id": i, "domain": "props_and_tools", "title": f"Widget {i}", "brief": "A widget."},
            "content": html_answer(i),
        }))
    return run


def test_extra_run_adds_valid_assembled_rows(tmp_path, system_file, dataset):
    out = tmp_path / "phase2"
    run = write_extra_run(tmp_path, [("x1", True), ("x2", False)])
    extra_system = tmp_path / "extra_system.txt"
    extra_system.write_text("EXTRA SYSTEM")

    run_main(out, dataset, system_file, "--extra-run", str(run), "--extra-system", str(extra_system))

    train = read_rows(out / "train.jsonl")
    extra = next((r for r in train if r["id"] == "x1"), None)
    assert extra is not None and extra["prompt"][0]["content"] == "EXTRA SYSTEM"
    assert all(r["id"] != "x2" for r in train)  # not ok -> not added
    assert json.loads((out / "stats.json").read_text())["extra"]["kept"] == 1


def test_extra_run_refuses_an_eval_brief_id(tmp_path, system_file, dataset):
    out = tmp_path / "phase2"
    run = write_extra_run(tmp_path, [("g001", True)])
    extra_system = tmp_path / "extra_system.txt"
    extra_system.write_text("EXTRA SYSTEM")

    with pytest.raises(SystemExit) as exc:
        run_main(out, dataset, system_file, "--extra-run", str(run), "--extra-system", str(extra_system))

    assert exc.value.code != 0
    assert not (out / "train.jsonl").exists()  # nothing is written when a run is refused


def test_extra_run_requires_extra_system(tmp_path, system_file, dataset):
    out = tmp_path / "phase2"
    run = write_extra_run(tmp_path, [("x1", True)])

    with pytest.raises(SystemExit) as exc:
        run_main(out, dataset, system_file, "--extra-run", str(run))

    assert exc.value.code != 0


@pytest.mark.parametrize("sub", ["data/phase2", "out/phase2", "eval/phase2", "data", "out", "eval"])
def test_out_inside_protected_roots_is_refused(tmp_path, system_file, dataset, sub):
    with pytest.raises(SystemExit) as exc:
        ccore_prep.main(["--parquet-dir", str(dataset), "--out", str(ROOT / sub)])

    assert exc.value.code != 0


def test_title_match_is_whole_word_and_case_insensitive():
    assert ccore_prep.title_is_eval_subject("Wooden Crate", ["crate"])
    assert ccore_prep.title_is_eval_subject("WOODEN CRATE", ["crate"])
    assert not ccore_prep.title_is_eval_subject("Crater Lamp", ["crate"])
    assert ccore_prep.title_is_eval_subject("Big Treasure Chest", ["treasure chest", "toolbox"])
    assert not ccore_prep.title_is_eval_subject("Treasure Hunter", ["treasure chest"])


def test_parse_conversation_takes_the_answer_only():
    user, answer = ccore_prep.parse_conversation(record("a", "T", "d", "ANSWER")["messages"])
    assert user == "Make it."
    assert answer == "ANSWER"


def test_split_of_routes_the_parquet_names():
    assert ccore_prep.split_of("train-00000.parquet") == "train"
    assert ccore_prep.split_of("validation-00000.parquet") == "val"
    assert ccore_prep.split_of("something-else.parquet") is None
