"""Compensating invariant: the cycle pool is conserved across the waterfall."""
from test_helpers import (
    TEST_USERS, validate_success, validate_paginated, get_success_data,
    set_clock, create_active_schedule, setup_active_dsp, create_member,
    create_payee, setup_work_with_share, create_report_with_lines,
    submit_report, accept_report, get_line_accrual, pad_report_for_match_floor,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _close_cycle_with_pool():
    """Matched 'Merlin' line (postings finalized) + unmatched 'Petrel' line
    (764 plays -> 100084 cents HELD accrual expiring 2029-07-01). Members A
    (signatory, weight 1 via the matched work) and B (non-signatory, flat 1).
    Cycle 2029-08 over [2026-06, 2026-06], MARKET_SHARE_USAGE, closed."""
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    m_a = create_member(legal_name="Alder Publishing", ipi_number="00000000101",
                        is_signatory=True)
    m_b = create_member(legal_name="Birch Songs", ipi_number="00000000202",
                        member_type="SELF_PUBLISHED_SONGWRITER", is_signatory=False)
    setup_work_with_share("Merlin", m_a)
    report, lines = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Merlin", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900011"},
        {"track_title": "Petrel", "plays_count": 764, "duration_seconds": 100,
         "isrc": "USAA19900003"},
    ])
    # Pad with a matched line on a shareless work so the acceptance circuit
    # breaker passes with the 100084-cent Petrel line unmatched; the pad line
    # spawns no accrual and names no member, so pool and weights are unchanged.
    pad_report_for_match_floor(dsp, dsp_headers, report, 100084)
    submit_report(dsp, dsp_headers, ack, report)
    accept_report(dsp, ack, report)
    create_payee(m_a["id"])
    st = get_success_data(api_client.create_statement(m_a["id"], "2026-06", ADMIN))
    get_success_data(api_client.finalize_statement(m_a["id"], st["id"], ADMIN))
    set_clock("2029-08-01T00:00:00Z")
    cycle = validate_success(api_client.create_cycle_run({
        "cycle_month": "2029-08", "pool_from_month": "2026-06",
        "pool_to_month": "2026-06", "methodology": "MARKET_SHARE_USAGE"}, ADMIN),
        expected_status=201)
    closed = validate_success(api_client.close_cycle_run(cycle["id"], ADMIN))
    dlines, _meta = validate_paginated(
        api_client.list_cycle_distribution_lines(cycle["id"], ADMIN))
    return closed, dlines, lines, m_a, m_b


def test_pool_equals_swept_unmatched_accrual(api):
    """PRD §3.8: "The sweep examines every accrual whose `hold_expires_at` is at
    or before the close time: those whose `reporting_month` falls inside the
    pool window move to `DISTRIBUTED` and their `amount_cents` is swept into
    `pool_cents` (their usage lines move to `DISTRIBUTED` as well); those
    outside the window move to `FORFEITED` and contribute nothing."

    Design: Difficulty/compensating_invariant/cycle_close_conserves_pool_cents
    """
    closed, dlines, lines, _m_a, _m_b = _close_cycle_with_pool()
    assert closed["pool_cents"] == 100084, (
        f"the pool is the 764*131 Petrel accrual; got {closed['pool_cents']}")
    petrel = validate_success(api_client.get_usage_line(lines[1]["id"], ADMIN))
    assert petrel["status"] == "DISTRIBUTED", (
        f"the swept line moves to DISTRIBUTED; got {petrel['status']}")


def test_waterfall_allocations_conserve_the_pool(api):
    """PRD §2.9: "Second, a distribution cycle's `pool_cents` counts only the
    accruals actually swept into the pool; accruals that expire outside the
    cycle's pool window are forfeited and contribute nothing. Funds are never
    created or destroyed by matching, claiming, or distribution — a released
    accrual returns its cents to the matched-royalty stream, and a forfeited
    accrual's cents simply remain outside distribution."

    Design: Difficulty/compensating_invariant/cycle_close_conserves_pool_cents
    """
    closed, dlines, _lines, m_a, m_b = _close_cycle_with_pool()
    distributed = sum(l["allocated_cents"] + l["residual_cents"] for l in dlines)
    assert distributed + closed["residual_cents"] == closed["pool_cents"], (
        f"pool conservation: {distributed} + {closed['residual_cents']} "
        f"!= {closed['pool_cents']}")
    by_member = {l["member_id"]: l for l in dlines}
    assert by_member[m_a["id"]]["allocated_cents"] == 50042
    assert by_member[m_b["id"]]["allocated_cents"] == 50042
    assert closed["residual_cents"] == 0
