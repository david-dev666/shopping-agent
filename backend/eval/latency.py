"""Summarize live HTTP measurements without treating empty results as collection success."""

import math
import re
from collections import Counter
from statistics import median

PLATFORMS = ("jd", "taobao", "pdd")
BLOCKED = re.compile(
    r"NEED_MANUAL_VERIFY|captcha|验证码|滑块|访问频繁|操作频繁|请求频繁|安全验证|"
    r"too many requests|rate.?limit|\b429\b", re.I
)


def stop_signal(row):
    if row.get("aborted"):
        return "user_interrupted"
    if row.get("http_status") in (403, 429):
        return "http_access_blocked"
    errors = " ".join(str(e) for e in row.get("platform_errors", {}).values())
    if BLOCKED.search(errors + " " + row.get("error", "")):
        return "platform_access_blocked"
    if not row.get("live_response"):
        return "request_failed_or_not_live"
    if any(not row.get("counts", {}).get(p, 0) for p in PLATFORMS):
        return "empty_platform_result"
    return None


def timings(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return {"n": 0, "p50_ms": None, "p95_ms": None, "min_ms": None, "max_ms": None}
    return {
        "n": len(values),
        "p50_ms": round(median(values), 2),
        "p95_ms": round(values[math.ceil(0.95 * len(values)) - 1], 2),
        "min_ms": round(values[0], 2),
        "max_ms": round(values[-1], 2),
    }


def summarize(rows):
    n = len(rows)
    valid = [r for r in rows if r.get("live_response")]
    nonempty = [r for r in valid if sum(r["counts"].values())]
    complete = [r for r in valid if all(r["counts"].get(p, 0) for p in PLATFORMS)]
    platforms = {}
    for platform in PLATFORMS:
        returned = sum(r["counts"].get(platform, 0) > 0 for r in valid)
        errored = sum(platform in r.get("platform_errors", {}) for r in valid)
        platforms[platform] = {
            "attempts": n,
            "nonempty": returned,
            "nonempty_rate": returned / n if n else None,
            "empty_without_error": sum(
                not r["counts"].get(platform, 0) and platform not in r.get("platform_errors", {})
                for r in valid
            ),
            "errors": errored,
            "request_failed_or_invalid": n - len(valid),
        }
    return {
        "attempts": n,
        "queries": len({r["query"] for r in rows}),
        "live_responses": len(valid),
        "interrupted_requests": sum(bool(r.get("aborted")) for r in rows),
        "nonempty_responses": len(nonempty),
        "all_three_nonempty": len(complete),
        "all_three_nonempty_rate": len(complete) / n if n else None,
        "wall_all_attempts": timings([r["wall_ms"] for r in rows]),
        "wall_nonempty_responses": timings([r["wall_ms"] for r in nonempty]),
        "wall_three_platform_responses": timings([r["wall_ms"] for r in complete]),
        "research": timings([
            r["node_ms"]["research"] for r in valid if "research" in r.get("node_ms", {})
        ]),
        "decide": timings([
            r["node_ms"]["decide"] for r in valid if "decide" in r.get("node_ms", {})
        ]),
        "engines": dict(Counter(r.get("engine", "unknown") for r in valid)),
        "platforms": platforms,
        "percentile_method": "P50 median; P95 nearest rank; descriptive for this small sample",
    }
