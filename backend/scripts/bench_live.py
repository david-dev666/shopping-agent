"""Repeat uncached live requests and retain every response, error and platform outcome."""

import argparse
import hashlib
import json
import platform
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from eval.latency import stop_signal, summarize


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def measure(base_url, mode, query, timeout, response_path):
    payload = {"query": query, "data_mode": "live"}
    if mode == "query":
        payload["refresh"] = True
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/{mode}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    row = {"query": query, "started_at": datetime.now(UTC).isoformat(), "mode": mode}
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            row["http_status"] = response.status
            body = json.load(response)
        write_json(response_path, body)
        row.update(
            live_response=(
                body.get("origin") == "live"
                and not body.get("demo") and not body.get("cached")
                and isinstance(body.get("offers"), list)
            ),
            counts=dict(Counter(o["platform"] for o in body.get("offers", []))),
            platform_errors=body.get("errors", {}),
            engine=body.get("decision", {}).get("engine", "not_applicable"),
            node_ms={
                step["node"]: step["elapsed_ms"]
                for step in body.get("trace", [])
                if step["node"] != "intent"
            },
            response_file=response_path.name,
        )
    except urllib.error.HTTPError as exc:
        row.update(live_response=False, http_status=exc.code, error=f"HTTPError: {exc.code}")
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        row.update(live_response=False, error=f"{type(exc).__name__}: {exc}")
    except KeyboardInterrupt:
        row.update(live_response=False, aborted=True, error="measurement interrupted by user")
    row["wall_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-samples", type=int, default=3)
    parser.add_argument("--delay", type=float, default=3)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--mode", choices=("chat", "query"), default="chat")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    queries = [line.strip() for line in args.queries.read_text().splitlines() if line.strip()]
    if not queries or len(queries) != len(set(queries)) or args.repeats < 1 or args.max_samples < 1:
        parser.error("queries must be nonempty and unique; repeats must be positive")
    if args.delay < 0 or args.timeout <= 0:
        parser.error("delay must be nonnegative; timeout must be positive")
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
    ).stdout.strip()
    source_hash = hashlib.sha256()
    for source in sorted((root / "backend/app").rglob("*.py")):
        source_hash.update(str(source.relative_to(root)).encode())
        source_hash.update(source.read_bytes())
    metadata = {
        "started_at": datetime.now(UTC).isoformat(),
        "revision": revision,
        "app_source_sha256": source_hash.hexdigest(),
        "system": platform.platform(),
        "python": platform.python_version(),
        "endpoint": f"/api/{args.mode}",
        "queries": queries,
        "repeats": args.repeats,
        "max_samples": args.max_samples,
        "delay_seconds": args.delay,
        "request_timeout_seconds": args.timeout,
        "sequential": True,
        "sample_mode": False,
        "cache_bypassed": True,
    }
    write_json(args.output / "metadata.json", metadata)
    rows = []
    reason = None
    try:
        with (args.output / "samples.jsonl").open("w", encoding="utf-8") as log:
            for repeat in range(args.repeats):
                for query in queries:
                    index = len(rows) + 1
                    row = measure(
                        args.base_url, args.mode, query, args.timeout,
                        args.output / f"response-{index:03d}.json",
                    )
                    row.update(index=index, repeat=repeat + 1)
                    rows.append(row)
                    log.write(json.dumps(row, ensure_ascii=False) + "\n")
                    log.flush()
                    write_json(args.output / "summary.json", summarize(rows))
                    print(json.dumps(row, ensure_ascii=False), flush=True)
                    reason = stop_signal(row)
                    if reason or index >= args.max_samples:
                        reason = reason or "sample_limit"
                        break
                    if index < len(queries) * args.repeats:
                        time.sleep(args.delay)
                if reason:
                    break
    except KeyboardInterrupt:
        reason = "user_interrupted_between_requests"
    finally:
        metadata.update(
            finished_at=datetime.now(UTC).isoformat(),
            stopped_reason=reason or "completed",
            recorded_attempts=len(rows),
        )
        write_json(args.output / "metadata.json", metadata)


if __name__ == "__main__":
    main()
