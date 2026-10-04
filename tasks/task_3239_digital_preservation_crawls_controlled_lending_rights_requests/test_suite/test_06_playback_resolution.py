"""Playback resolution depth: variant selection and time-weighted formula."""
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_patron_headers,
    create_crawl_job_payload,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
CRAWLOP = TEST_USERS["crawl_operator_headers"]


def _running_job_with_captures(seed, scheduled_at, captures_spec):
    """captures_spec: list of (clock_iso, url, content_hash, has_dynamic_content)."""
    set_clock("2026-09-01T00:00:00Z")
    job = get_success_data(api_client.create_crawl_job(
        create_crawl_job_payload(
            seed_url=seed, scheduled_at=scheduled_at, requests_per_minute=60
        ),
        CRAWLOP,
    ))
    # start the job at its scheduled time
    set_clock(scheduled_at)
    get_success_data(api_client.start_crawl_job(job["id"], CRAWLOP))
    ids = []
    for clock_iso, url, content_hash, dynamic in captures_spec:
        set_clock(clock_iso)
        cap = get_success_data(api_client.create_capture(
            {"crawl_job_id": job["id"], "url": url, "content_hash": content_hash,
             "has_dynamic_content": dynamic},
            CRAWLOP,
        ))
        ids.append(cap["id"])
    return job, ids


def test_playback_variant_nearest_time_vs_latest_default_with_requested_at():
    """PRD 3.7: "With `requested_at` omitted, the pick is the candidate with the
    maximum `captured_at`. With `requested_at` supplied, the pick is the
    candidate whose `captured_at` is nearest in absolute time, and on an exact
    tie between an earlier and a later capture the earlier one wins — the rule
    is closed on the past side — with any further tie broken by `created_at`
    ascending."

    Design: Difficulty/dual_variant_calc/playback_variant_nearest_time_vs_latest_default
    """
    job, (cap1, cap2) = _running_job_with_captures(
        "https://example.site/",
        "2026-09-01T01:00:00Z",
        [
            ("2026-09-02T00:00:00Z", "https://example.site/a", "h1", False),
            ("2026-09-05T00:00:00Z", "https://example.site/a", "h2", False),
        ],
    )
    # requested_at 2026-09-04: |2d| vs |1d| -> cap2 wins (nearer)
    nearest = validate_success(
        api_client.get_playback(
            make_patron_headers("patron-any"),
            params={"url": "https://example.site/a",
                    "requested_at": "2026-09-04T00:00:00Z"},
        )
    )
    assert nearest["mode"] == "FULL"
    assert nearest["capture_id"] == cap2


def test_playback_variant_nearest_time_vs_latest_default_omitted_requested_at():
    """PRD 3.7: "With `requested_at` omitted, the pick is the candidate with the
    maximum `captured_at`. With `requested_at` supplied, the pick is the
    candidate whose `captured_at` is nearest in absolute time, and on an exact
    tie between an earlier and a later capture the earlier one wins — the rule
    is closed on the past side — with any further tie broken by `created_at`
    ascending."

    Design: Difficulty/dual_variant_calc/playback_variant_nearest_time_vs_latest_default
    """
    job, (cap1, cap2) = _running_job_with_captures(
        "https://example.site/",
        "2026-09-01T01:00:00Z",
        [
            ("2026-09-02T00:00:00Z", "https://example.site/a", "h1", False),
            ("2026-09-05T00:00:00Z", "https://example.site/a", "h2", False),
        ],
    )
    latest = validate_success(
        api_client.get_playback(
            make_patron_headers("patron-any"),
            params={"url": "https://example.site/a"},
        )
    )
    assert latest["mode"] == "FULL"
    assert latest["capture_id"] == cap2
    # requested_at exactly equidistant between the two (2026-09-03):
    # the earlier capture wins the tie
    tie = validate_success(
        api_client.get_playback(
            make_patron_headers("patron-any"),
            params={"url": "https://example.site/a",
                    "requested_at": "2026-09-03T00:00:00Z"},
        )
    )
    assert tie["mode"] == "FULL"
    assert tie["capture_id"] == cap1


def test_playback_time_weighted_mode_formula_tie_and_dynamic():
    """PRD 3.7: "With `requested_at` supplied, the pick is the candidate whose
    `captured_at` is nearest in absolute time, and on an exact tie between an
    earlier and a later capture the earlier one wins — the rule is closed on
    the past side — with any further tie broken by `created_at` ascending."
    PRD 3.7: "If the picked capture has `has_dynamic_content` true, the mode is
    `DEGRADED`; otherwise it is `FULL`."

    Design: Difficulty/combinatorial_formula/playback_time_weighted_mode_formula
    """
    set_clock("2026-09-01T00:00:00Z")
    job = get_success_data(api_client.create_crawl_job(
        create_crawl_job_payload(
            seed_url="https://tie.site/", scheduled_at="2026-09-01T00:30:00Z",
            requests_per_minute=30,
        ),
        CRAWLOP,
    ))
    set_clock("2026-09-01T00:30:00Z")
    get_success_data(api_client.start_crawl_job(job["id"], CRAWLOP))
    ids = {}
    for label, clock_iso, chash, dyn in (
        ("d1", "2026-09-02T00:00:00Z", "t1", False),
        ("d2", "2026-09-04T00:00:00Z", "t2", False),
        ("d3", "2026-09-06T00:00:00Z", "t3", True),
    ):
        set_clock(clock_iso)
        cap = get_success_data(api_client.create_capture(
            {"crawl_job_id": job["id"], "url": "https://tie.site/x",
             "content_hash": chash, "has_dynamic_content": dyn},
            CRAWLOP,
        ))
        ids[label] = cap["id"]

    # equidistant tie at 2026-09-03 between d1 (09-02) and d2 (09-04):
    # the EARLIER capture wins
    tie = validate_success(
        api_client.get_playback(
            ADMIN, params={"url": "https://tie.site/x",
                           "requested_at": "2026-09-03T00:00:00Z"}
        )
    )
    assert tie["capture_id"] == ids["d1"]
    assert tie["mode"] == "FULL"

    # omitted requested_at picks max captured_at (d3), which is dynamic
    dyn = validate_success(
        api_client.get_playback(ADMIN, params={"url": "https://tie.site/x"})
    )
    assert dyn["capture_id"] == ids["d3"]
    assert dyn["mode"] == "DEGRADED"


def test_playback_time_weighted_mode_formula_empty_candidate_set():
    """PRD 3.7: "If no candidate exists, the mode is `NOT_FOUND`."
    PRD 3.7: "The response carries the `mode`, the chosen `capture_id` (null
    unless a capture was selected), its `captured_at`, and its
    `has_dynamic_content` flag."

    Design: Difficulty/combinatorial_formula/playback_time_weighted_mode_formula
    """
    set_clock("2026-09-01T00:00:00Z")
    job = get_success_data(api_client.create_crawl_job(
        create_crawl_job_payload(
            seed_url="https://tie.site/", scheduled_at="2026-09-01T00:30:00Z",
            requests_per_minute=30,
        ),
        CRAWLOP,
    ))
    set_clock("2026-09-01T00:30:00Z")
    get_success_data(api_client.start_crawl_job(job["id"], CRAWLOP))
    get_success_data(api_client.create_capture(
        {"crawl_job_id": job["id"], "url": "https://tie.site/x",
         "content_hash": "t1", "has_dynamic_content": False},
        CRAWLOP,
    ))
    miss = validate_success(
        api_client.get_playback(ADMIN, params={"url": "https://tie.site/absent"})
    )
    assert miss["mode"] == "NOT_FOUND"
    assert miss["capture_id"] is None
