"""Branching match paths from UNMATCHED: MatchRun re-match vs validated claim."""
from test_helpers import (
    TEST_USERS, make_member_headers, validate_success, validate_paginated,
    set_clock, create_active_schedule, setup_active_dsp, create_member,
    setup_work_with_share, create_report_with_lines, submit_report,
    accept_report, get_line_accrual, pad_report_for_match_floor,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_two_unmatched_lines_then_improve():
    """Accepted 2026-06 report with unmatched L1 'Merlin' (13100) and
    L2 'Harrier' (26200); afterwards works 'Merlin' and 'Harrier' registered,
    each with a 100% share for member A. L2's accrual additionally gets a
    validated claim from A.

    The report is padded with a matched line (shareless pad work) so the
    acceptance circuit breaker passes with 39300 unmatched cents."""
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    m_a = create_member(is_signatory=True)
    report, lines = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Merlin", "plays_count": 100, "duration_seconds": 100,
         "isrc": "USAA19900011"},
        {"track_title": "Harrier", "plays_count": 200, "duration_seconds": 100,
         "isrc": "USAA19900012"},
    ])
    pad_report_for_match_floor(dsp, dsp_headers, report, 39300)
    submit_report(dsp, dsp_headers, ack, report)
    accept_report(dsp, ack, report)
    l1, l2 = lines
    w1, _ = setup_work_with_share("Merlin", m_a)
    w2, _ = setup_work_with_share("Harrier", m_a)
    acc2 = get_line_accrual(l2["id"])
    claim = validate_success(api_client.create_claim({
        "accrual_id": acc2["id"], "claimant_member_id": m_a["id"],
        "claimed_work_id": w2["id"], "share_percent_claimed": 100,
    }, make_member_headers(m_a["id"])), expected_status=201)
    validate_success(api_client.validate_claim(claim["id"], ADMIN))
    return l1, l2, w1, w2, acc2


def test_match_run_releases_accrual_on_rematched_line(api):
    """PRD §3.4: "When a previously `UNMATCHED` line now resolves to exactly one
    work — the canonical data-quality improvement path — the line moves to
    `MATCHED`, its `matched_work_id` is set, matched-earnings postings are
    queued as at acceptance, and its `HELD` accrual moves to `RELEASED`,
    returning its cents to the matched-royalty stream."

    Design: Difficulty/non_linear_state_machine/usage_line_branching_match_paths
    """
    l1, _l2, w1, _w2, _acc2 = _setup_two_unmatched_lines_then_improve()
    validate_success(api_client.create_match_run(ADMIN), expected_status=201)
    line1 = validate_success(api_client.get_usage_line(l1["id"], ADMIN))
    assert line1["status"] == "MATCHED", (
        f"UNMATCHED -> MATCHED branch via MatchRun; got {line1['status']}")
    assert line1["matched_work_id"] == w1["id"]
    acc1 = get_line_accrual(l1["id"])
    assert acc1["status"] == "RELEASED", (
        f"the re-matched line's accrual moves to RELEASED; got {acc1['status']}")


def test_match_run_skips_claimed_matched_line(api):
    """PRD §3.6: "A clean validation moves the claim to `VALIDATED`, the accrual
    to `CLAIMED` with `matched_work_id` set to the `claimed_work_id`, and the
    usage line to `CLAIMED_MATCHED`; claim-earnings postings are then computed
    against the claimed work's shares per §3.7."

    Design: Difficulty/non_linear_state_machine/usage_line_branching_match_paths
    """
    _l1, l2, _w1, w2, acc2 = _setup_two_unmatched_lines_then_improve()
    validate_success(api_client.create_match_run(ADMIN), expected_status=201)
    line2 = validate_success(api_client.get_usage_line(l2["id"], ADMIN))
    assert line2["status"] == "CLAIMED_MATCHED", (
        f"the claimed line keeps its CLAIMED_MATCHED branch; got {line2['status']}")
    assert line2["matched_work_id"] == w2["id"]
    acc2_after = validate_success(api_client.get_accrual(acc2["id"], ADMIN))
    assert acc2_after["status"] == "CLAIMED", (
        f"the claimed accrual keeps its CLAIMED branch; got {acc2_after['status']}")
