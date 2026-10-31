"""Metric denominators include failures and distinguish empty and partial results."""

from eval.latency import stop_signal, summarize, timings


def test_percentiles_use_all_values_and_handle_empty_samples():
    assert timings([])["p95_ms"] is None
    result = timings([100, 200, 300, 400])
    assert result == {"n": 4, "p50_ms": 250, "p95_ms": 400, "min_ms": 100, "max_ms": 400}


def test_partial_empty_failed_and_complete_requests_have_separate_denominators():
    rows = [
        {"query": "q", "wall_ms": 100, "live_response": True, "counts": {"jd": 2}},
        {"query": "q", "wall_ms": 200, "live_response": True, "counts": {},
         "platform_errors": {"taobao": "timeout"}},
        {"query": "q", "wall_ms": 500, "live_response": False, "error": "request failed"},
        {"query": "other", "wall_ms": 300, "live_response": True,
         "counts": {"jd": 1, "taobao": 1, "pdd": 1}, "engine": "llm"},
    ]
    report = summarize(rows)
    assert report["attempts"] == 4
    assert report["live_responses"] == 3
    assert report["nonempty_responses"] == 2
    assert report["all_three_nonempty_rate"] == 0.25
    assert report["wall_all_attempts"]["max_ms"] == 500
    assert report["platforms"]["taobao"] == {
        "attempts": 4, "nonempty": 1, "nonempty_rate": 0.25,
        "empty_without_error": 1, "errors": 1, "request_failed_or_invalid": 1,
    }
    assert report["wall_three_platform_responses"]["n"] == 1


def test_no_samples_do_not_claim_perfect_success():
    report = summarize([])
    assert report["all_three_nonempty_rate"] is None
    assert report["wall_all_attempts"]["n"] == 0


def test_platform_rate_limit_and_verification_stop_before_the_next_request():
    for error in ("访问频繁，请稍后重试", "NEED_MANUAL_VERIFY", "HTTP 429", "captcha"):
        assert stop_signal({"platform_errors": {"pdd": error}}) == "platform_access_blocked"
    assert stop_signal({"http_status": 429}) == "http_access_blocked"
    assert stop_signal({"aborted": True}) == "user_interrupted"


def test_empty_platform_is_not_retried_and_success_allows_next_sample():
    assert stop_signal({"live_response": True, "counts": {"jd": 15}}) == "empty_platform_result"
    complete = {"live_response": True, "counts": dict.fromkeys(("jd", "taobao", "pdd"), 15)}
    assert stop_signal(complete) is None


def test_interrupted_attempt_is_counted_without_inventing_a_latency():
    report = summarize([{"query": "q", "wall_ms": None, "live_response": False, "aborted": True}])
    assert report["attempts"] == report["interrupted_requests"] == 1
    assert report["wall_all_attempts"]["n"] == 0
