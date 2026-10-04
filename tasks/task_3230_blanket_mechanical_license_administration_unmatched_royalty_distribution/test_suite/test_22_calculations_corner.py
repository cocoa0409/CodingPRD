"""Queue B (corner) — calculations: royalty pricing, match-rate input set,
deterministic tie-breaks, chronological audit adjustment."""
from test_helpers import (
    TEST_USERS, validate_success, validate_paginated, get_success_data,
    make_member_headers,
    set_clock, create_active_schedule, setup_active_dsp, create_member,
    create_work, create_share, setup_work_with_share,
    create_report_with_lines, submit_report, accept_report,
    pad_report_for_match_floor,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def test_royalty_short_and_long_form_known_results(api):
    """PRD §3.3: "When `duration_seconds` is at most 300, the unit price is that
    schedule's `rate_cents_under_5min`. When the duration exceeds 300 seconds,
    the unit price is the greater of the short rate and the per-minute rate
    multiplied by the duration in minutes rounded up to the next whole minute.
    The line's `royalties_cents` is the `plays_count` multiplied by that unit
    price, computed entirely in integer cents with no rounding."

    Design: Corner/calculations/usage_line_royalty_correct_result
    """
    set_clock("2026-09-10T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, _ack = setup_active_dsp()
    report, _ = create_report_with_lines(dsp, dsp_headers, "2026-08", [])
    line_a = validate_success(api_client.create_usage_line(
        dsp["id"], report["id"],
        {"isrc": "USAA19900051", "track_title": "Sora",
         "plays_count": 1000, "duration_seconds": 200},
        dsp_headers), expected_status=201)
    line_b = validate_success(api_client.create_usage_line(
        dsp["id"], report["id"],
        {"isrc": "USAA19900052", "track_title": "Ruff",
         "plays_count": 10, "duration_seconds": 601},
        dsp_headers), expected_status=201)
    assert line_a["royalties_cents"] == 131000
    assert line_b["royalties_cents"] == 27720, (
        f"601s -> ceil 11 minutes; 252 * 11 = 2772 > 131; "
        f"got {line_b['royalties_cents']}")


def _setup_match_rate_fixture():
    """Accepted report 2026-06: L1 'Merlin' and L2 'Gale' unmatched at accept,
    L3 'Kestrel' matched at accept (work pre-registered); work 'Merlin'
    registered afterwards. A shareless-work pad line (matched at accept, never
    re-evaluated) keeps unmatched at or under 60% of the report total."""
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    m_a = create_member()
    setup_work_with_share("Kestrel", m_a)
    report, _ = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Kestrel", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900001"},
        {"track_title": "Merlin", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900011"},
        {"track_title": "Gale", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900032"},
    ])
    pad_report_for_match_floor(dsp, dsp_headers, report, 2620)
    submit_report(dsp, dsp_headers, ack, report)
    accept_report(dsp, ack, report)
    setup_work_with_share("Merlin", m_a)


def test_match_run_input_set_excludes_already_matched(api):
    """PRD §3.4: "The run records `initiated_by` (the opaque id of the
    administrator who started it, kept for audit purposes and for the
    segregation-of-duties rule in §3.6), `total_lines_evaluated`,
    `lines_matched`, and `lines_promoted_unmatched` — the count of previously
    `PENDING_MATCH` lines that evaluated to no-match and became `UNMATCHED`,
    spawning accruals as usual. Its `match_rate_bps` is the integer division of
    `lines_matched` times 10000 by `total_lines_evaluated`, and is zero when
    nothing was evaluated."
    PRD §3.4: "an administrator may launch a matching pass that re-evaluates
    every line in `PENDING_MATCH` or `UNMATCHED` across the system"

    Design: Corner/calculations/match_rate_bps_input_set_filtering
    """
    _setup_match_rate_fixture()
    run = validate_success(api_client.create_match_run(ADMIN), expected_status=201)
    assert run["total_lines_evaluated"] == 2, (
        f"only the two UNMATCHED lines; got {run['total_lines_evaluated']}")
    assert run["lines_matched"] == 1
    assert run["match_rate_bps"] == 5000, (
        f"1 * 10000 // 2; got {run['match_rate_bps']}")


def test_matching_tie_break_prefers_iswc_then_created_at(api):
    """PRD §3.4: "Candidates are ranked with works carrying a non-null `iswc`
    ahead of works without one; among equal ranks, the work with the earlier
    `created_at` wins, and further ties cannot occur because creation
    timestamps are unique."

    Design: Corner/calculations/deterministic_matching_tie_break_by_created_at
    """
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    create_member()
    create_work(title="Kestrel")  # earlier, iswc null
    w2 = create_work(title="Kestrel", iswc="T0000000002")
    report, lines = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Kestrel", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900001"},
    ])
    submit_report(dsp, dsp_headers, ack, report)
    accept_report(dsp, ack, report)
    line = validate_success(api_client.get_usage_line(lines[0]["id"], ADMIN))
    assert line["matched_work_id"] == w2["id"], (
        f"the ISWC-present work outranks the earlier ISWC-less work; "
        f"got {line['matched_work_id']}")


def test_audit_adjustment_applied_chronologically(api):
    """PRD §3.8: "Closure applies the adjustment report by report in
    chronological `reporting_month` order: a negative delta is absorbed by
    `matched_usage_cents` first, up to what that figure holds, and any
    unabsorbed remainder flows to `unmatched_usage_cents`, never driving either
    figure below zero; `total_usage_cents` absorbs the full delta. A report
    whose covering engagement closes with a zero adjustment moves from
    `UNDER_AUDIT` to `AUDIT_CONFIRMED`; a non-zero adjustment moves it to
    `AMENDED`"
    PRD §3.8: "The consumed credit is refunded to the provider (`audit_credits`
    increases by one) exactly when the adjustment is zero; a non-zero
    adjustment consumes the credit permanently."

    Design: Corner/calculations/audit_adjustment_applied_chronologically
    """
    set_clock("2026-09-10T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    m_a = create_member()
    setup_work_with_share("Sora", m_a)
    setup_work_with_share("Ruff", m_a)
    r_jun, _ = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Sora", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900051"},
    ])
    submit_report(dsp, dsp_headers, ack, r_jun)
    accept_report(dsp, ack, r_jun)
    r_jul, _ = create_report_with_lines(dsp, dsp_headers, "2026-07", [
        {"track_title": "Ruff", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900052"},
    ])
    submit_report(dsp, dsp_headers, ack, r_jul)
    accept_report(dsp, ack, r_jul)
    audit = validate_success(api_client.create_audit(
        dsp["id"], m_a["id"], ["2026-06", "2026-07"],
        make_member_headers(m_a["id"])), expected_status=201)
    validate_success(api_client.issue_audit_findings(
        audit["id"], "Overreported plays", make_member_headers(m_a["id"])))
    validate_success(api_client.close_audit(audit["id"], -2000, ADMIN))
    jun = validate_success(api_client.get_usage_report(dsp["id"], r_jun["id"], ADMIN))
    jul = validate_success(api_client.get_usage_report(dsp["id"], r_jul["id"], ADMIN))
    assert jun["status"] == "AMENDED"
    assert jul["status"] == "AMENDED"
    # D = -2000 applied in reporting_month ASC order: June absorbs 1310 into
    # matched (to zero), then the remaining 690 hits July's matched.
    assert jun["matched_usage_cents"] == 0, (
        f"June's matched absorbs min(1310, 2000); got {jun['matched_usage_cents']}")
    assert jul["matched_usage_cents"] == 620, (
        f"July's matched absorbs the remaining 690; got {jul['matched_usage_cents']}")
    dsp_after = validate_success(api_client.get_service_provider(dsp["id"], ADMIN))
    assert dsp_after["audit_credits"] == 1, (
        f"2 granted by the accepts, 1 permanently consumed by the non-zero "
        f"adjustment; got {dsp_after['audit_credits']}")
