import json
import sys

import pytest

from scripts import bench_live


@pytest.mark.parametrize("stop", ["blocked", "limit", "interrupted"])
def test_runner_records_one_attempt_then_stops(tmp_path, monkeypatch, stop):
    queries = tmp_path / "queries.txt"
    queries.write_text("query-a\nquery-b\n")
    output = tmp_path / "result"
    monkeypatch.setattr(sys, "argv", [
        "bench_live", "--queries", str(queries), "--output", str(output),
        "--max-samples", "1" if stop == "limit" else "3", "--delay", "0",
    ])
    calls = []

    def measure(base_url, mode, query, timeout, response_path):
        calls.append(query)
        row = {"query": query, "live_response": True, "wall_ms": 10,
               "counts": dict.fromkeys(("jd", "taobao", "pdd"), 1)}
        if stop == "blocked":
            row["platform_errors"] = {"pdd": "NEED_MANUAL_VERIFY"}
        if stop == "interrupted":
            row.update(aborted=True, live_response=False)
        return row

    monkeypatch.setattr(bench_live, "measure", measure)
    bench_live.main()
    assert calls == ["query-a"]
    metadata = json.loads((output / "metadata.json").read_text())
    assert metadata["stopped_reason"] == {
        "blocked": "platform_access_blocked",
        "limit": "sample_limit",
        "interrupted": "user_interrupted",
    }[stop]
    assert len((output / "samples.jsonl").read_text().splitlines()) == 1
