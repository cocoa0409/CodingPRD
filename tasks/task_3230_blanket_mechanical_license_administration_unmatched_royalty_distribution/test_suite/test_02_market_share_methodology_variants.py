"""Dual-variant market-share waterfall: USAGE vs PRIOR methodology."""
from test_helpers import (
    TEST_USERS, make_dsp_headers, make_member_headers, validate_success,
    validate_paginated, get_success_data,
    set_clock, create_schedule_pending, activate_dsp, create_dsp, create_member,
    create_payee, setup_work_with_share, create_report_with_lines,
    submit_report, accept_report, pad_report_for_match_floor,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _run_two_cycles():
    """Build the two-cycle fixture.

    June report (NEW schedule window): 'Merlin' line (10 plays, unmatched at
    accept because the work does not exist yet) + 'Petrel' line (400 plays,
    stays unmatched -> HELD accrual, 52400 cents).
    May report (SUPERSEDED 120-cent window): 'Gadwall' (1000 plays -> 120000
    cents, HELD accrual).
    Both reports are padded with matched lines on shareless works so the
    acceptance circuit breaker passes.
    Then work 'Merlin' is registered with a 100% share for signatory member A
    and a match run selects it (match_run_count -> 1).

    Hold expiries: the May accrual expires 2029-06-01, the June accrual
    2029-07-01 (PRD §3.5). Because a cycle's close forfeits every expired
    accrual outside its pool window (PRD §3.8), the May cycle must close while
    the June accrual is still unexpired: C_may (cycle_month 2029-06, window
    [2026-05,2026-05], MARKET_SHARE_USAGE) closes at 2029-06-15 with pool
    120000; C_jun (cycle_month 2029-08, window [2026-06,2026-06],
    MARKET_SHARE_PRIOR) closes at 2029-08-10 with pool 52400.
    """
    set_clock("2026-09-01T00:00:00Z")
    rs_old = create_schedule_pending(
        under=120, over=240,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z")
    rs_new = create_schedule_pending(
        under=131, over=252, effective_from="2026-06-01T00:00:00Z")
    api_client.activate_rate_schedule(rs_old["id"], ADMIN)
    api_client.activate_rate_schedule(rs_new["id"], ADMIN)
    dsp, dsp_headers, ack = activate_dsp(create_dsp())
    m_a = create_member(legal_name="Alder Publishing", ipi_number="00000000101",
                        is_signatory=True)
    m_b = create_member(legal_name="Birch Songs", ipi_number="00000000202",
                        member_type="SELF_PUBLISHED_SONGWRITER", is_signatory=False)
    # June report (131-cent window); padded with matched lines so the
    # acceptance circuit breaker (unmatched <= 60% of total, PRD §3.3) passes
    # with Merlin + Petrel unmatched (53700 cents).
    r_jun, _ = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Merlin", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900011"},
        {"track_title": "Petrel", "plays_count": 400, "duration_seconds": 100,
         "isrc": "USAA19900003"},
    ])
    pad_report_for_match_floor(dsp, dsp_headers, r_jun, 53700)
    submit_report(dsp, dsp_headers, ack, r_jun)
    accept_report(dsp, ack, r_jun)
    # May report (SUPERSEDED 120-cent window), accepted after June to keep order
    r_may, _ = create_report_with_lines(dsp, dsp_headers, "2026-05", [
        {"track_title": "Gadwall", "plays_count": 1000, "duration_seconds": 100,
         "isrc": "USAA19900004"},
    ])
    pad_report_for_match_floor(dsp, dsp_headers, r_may, 120000, rate=120)
    submit_report(dsp, dsp_headers, ack, r_may)
    accept_report(dsp, ack, r_may)
    # Data-quality improvement: register 'Merlin' and re-match
    setup_work_with_share("Merlin", m_a, share_percent=100)
    api_client.create_match_run(ADMIN)
    # Member A payee + finalized statement so the cycle can DISTRIBUTE the line
    create_payee(m_a["id"])
    st = get_success_data(api_client.create_statement(m_a["id"], "2026-06", ADMIN))
    get_success_data(api_client.finalize_statement(m_a["id"], st["id"], ADMIN))
    # May's accrual expires 2029-06-01, June's 2029-07-01: the May cycle must
    # close between the two expiries so the June accrual survives for its own
    # cycle (a close forfeits every expired accrual outside its pool window,
    # PRD §3.8). The fixture leaves the clock at 2029-06-15; the PRIOR test
    # advances it past 2029-07-01 before closing the June cycle.
    set_clock("2029-06-15T00:00:00Z")
    c_may = get_success_data(api_client.create_cycle_run({
        "cycle_month": "2029-06", "pool_from_month": "2026-05",
        "pool_to_month": "2026-05", "methodology": "MARKET_SHARE_USAGE"}, ADMIN))
    c_jun = get_success_data(api_client.create_cycle_run({
        "cycle_month": "2029-08", "pool_from_month": "2026-06",
        "pool_to_month": "2026-06", "methodology": "MARKET_SHARE_PRIOR"}, ADMIN))
    return m_a, m_b, c_may, c_jun


def _member_line(cycle_id, member_id):
    lines, _meta = validate_paginated(
        api_client.list_cycle_distribution_lines(cycle_id, ADMIN))
    by_member = {l["member_id"]: l for l in lines}
    return by_member[member_id]


def test_usage_methodology_weights_from_fresh_match_evidence(api):
    """PRD §3.8: "Under `MARKET_SHARE_USAGE`, a signatory member's weight is the
    number of distinct works with `match_run_count` greater than zero whose
    `ACTIVE`-or-`DISPUTED` shares name the member as claimant, while a
    non-signatory member's weight is a flat one."

    Design: Difficulty/dual_variant_calc/historical_market_share_methodology_variants
    """
    m_a, m_b, c_may, _c_jun = _run_two_cycles()
    closed = validate_success(api_client.close_cycle_run(c_may["id"], ADMIN))
    assert closed["pool_cents"] == 120000, (
        f"May pool must be the 1000*120 Gadwall accrual; got {closed['pool_cents']}")
    line_a = _member_line(c_may["id"], m_a["id"])
    line_b = _member_line(c_may["id"], m_b["id"])
    assert line_a["weight_numerator"] == 1, (
        f"signatory A weight = distinct matched works = 1; got {line_a['weight_numerator']}")
    assert line_b["weight_numerator"] == 1, (
        f"non-signatory B weight = flat 1; got {line_b['weight_numerator']}")
    assert line_a["allocated_cents"] == 60000, (
        f"weights 1:1 over 120000 -> 60000 each; got {line_a['allocated_cents']}")
    assert line_b["allocated_cents"] == 60000


def test_prior_methodology_weights_from_frozen_snapshot(api):
    """PRD §3.8: "Under `MARKET_SHARE_PRIOR`, a member whose
    `prior_market_share_denominator` is greater than zero is weighted by their
    `prior_market_share_numerator`, and any other member receives the new-member
    floor of one."

    Design: Difficulty/dual_variant_calc/historical_market_share_methodology_variants
    """
    m_a, m_b, c_may, c_jun = _run_two_cycles()
    validate_success(api_client.close_cycle_run(c_may["id"], ADMIN))
    # C_may's close freezes the prior-epoch snapshot onto every member
    m_a_after = validate_success(api_client.get_member(m_a["id"], ADMIN))
    assert m_a_after["prior_market_share_numerator"] == 1
    assert m_a_after["prior_market_share_denominator"] > 0
    set_clock("2029-08-10T00:00:00Z")  # June accrual (expiry 2029-07-01) now expired
    closed2 = validate_success(api_client.close_cycle_run(c_jun["id"], ADMIN))
    assert closed2["pool_cents"] == 52400, (
        f"June pool must be the 400*131 Petrel accrual; got {closed2['pool_cents']}")
    line_a = _member_line(c_jun["id"], m_a["id"])
    line_b = _member_line(c_jun["id"], m_b["id"])
    # PRIOR reads the frozen numerator (A=1) and B's frozen numerator (1)
    assert line_a["weight_numerator"] == 1, (
        f"PRIOR variant must read the frozen prior_market_share_numerator (==1); "
        f"got {line_a['weight_numerator']}")
    assert line_a["allocated_cents"] == 26200, (
        f"weights 1:1 over 52400 -> 26200 each; got {line_a['allocated_cents']}")
    assert line_b["allocated_cents"] == 26200
