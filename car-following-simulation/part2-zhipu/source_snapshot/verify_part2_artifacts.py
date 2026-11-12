"""Verify stored evidence against per-run traces, inputs and source snapshots."""
import csv
import hashlib
import json
from pathlib import Path

root = Path(__file__).parent
total = 0
for name in ["part2-results", "part2-interval2", "part2-failure"]:
    directory = root / name
    metadata = json.loads((directory / "run-metadata.json").read_text())
    assert metadata["evidence"] == "offline-NOT-LLM"
    for filename, digest in metadata["sources_sha256"].items():
        # These are the files present at execution time, before this verifier.
        executed = directory / "source_snapshot" / filename
        raw = (executed if executed.exists() else root / filename).read_bytes()
        lf = raw.replace(b"\r\n", b"\n")
        candidates = [raw, lf, lf.replace(b"\n", b"\r\n")]
        assert digest in {hashlib.sha256(value).hexdigest() for value in candidates}, filename
    summaries = json.loads((directory / "summary.json").read_text())
    for result in summaries:
        total += 1
        seed = result["seed"]
        label = result["label"]
        mode = "idm" if label == "IDM baseline" else label.split(" | ")[-1]
        run = directory / f"seed-{seed}" / mode
        assert result == json.loads((run / "metrics.json").read_text())
        peers = [r for r in summaries if r["seed"] == seed]
        assert len({r["scenario_sha256"] for r in peers}) == 1
        assert result["actual_api_requests"] == 0
        assert result["overlapping_pairs"] == 0
        with (run / "target.csv").open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        minimum = min(float(r["gap"]) for r in rows if r["gap"])
        assert abs(minimum - result["target_min_gap_m"]) < 1e-10
        decisions = [json.loads(line) for line in (run / "decisions.jsonl").read_text().splitlines()]
        assert len(decisions) == result["policy_stats"].get("decisions", 0)
        if name == "part2-failure" and mode != "idm":
            assert result["policy_stats"]["failures"] == len(decisions)
            assert result["policy_stats"]["fallback_steps"] == len(rows) - 1
            assert (run / "target.csv").read_bytes() == (directory / f"seed-{seed}" / "idm" / "target.csv").read_bytes()
    print(f"PASS {name}: {len(summaries)} runs; source hashes, matched inputs, traces and logs verified")
assert total == 21
print("PASS 21 offline runs; 0 actual API requests; fault target traces exactly match IDM")
