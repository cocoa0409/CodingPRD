"""Pinned rounding order for per-share allocation (floor then remainder)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_paginated,
    set_clock, create_active_schedule, setup_active_dsp, create_member,
    create_share, create_work, create_report_with_lines, submit_report,
    accept_report,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _build_three_share_match():
    """Work 'Kestrel' with shares 33.4 (A) / 33.3 (B) / 33.3 (C) in creation
    order; accepted 2026-06 report with one matched 131000-cent line; one
    DRAFT statement per member for 2026-06."""
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    m_a = create_member(legal_name="Alder Publishing", ipi_number="00000000101")
    m_b = create_member(legal_name="Birch Songs", ipi_number="00000000202")
    m_c = create_member(legal_name="Cedar Music", ipi_number="00000000303")
    work = create_work(title="Kestrel")
    create_share(work["id"], m_a["id"], share_percent=33.4)
    create_share(work["id"], m_b["id"], share_percent=33.3)
    create_share(work["id"], m_c["id"], share_percent=33.3)
    report, _ = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Kestrel", "plays_count": 1000, "duration_seconds": 200,
         "isrc": "USAA19900001"},
    ])
    submit_report(dsp, dsp_headers, ack, report)
    accept_report(dsp, ack, report)
    stmts = {}
    for m in (m_a, m_b, m_c):
        st = validate_success(api_client.create_statement(m["id"], "2026-06", ADMIN),
                              expected_status=201)
        stmts[m["id"]] = st
    return m_a, m_b, m_c, stmts


def _alloc_for(member_id, statement_id):
    lines, _meta = validate_paginated(
        api_client.list_statement_lines(member_id, statement_id, ADMIN))
    assert len(lines) == 1, f"expected exactly one earnings line, got {lines}"
    return lines[0]["allocated_cents"]


def test_first_share_in_pinned_order_takes_the_remainder_cent(api):
    """PRD §3.7: "Each share receives the floor of the line's cents multiplied
    by its `share_percent` and divided by 100; the remainder, which is always
    smaller than the number of shares, is then distributed one cent at a time
    to shares in that same pinned order, so each share receives at most one
    remainder cent."

    Design: Difficulty/combinatorial_formula/per_share_allocation_rounding_order
    """
    m_a, m_b, m_c, stmts = _build_three_share_match()
    alloc_a = _alloc_for(m_a["id"], stmts[m_a["id"]]["id"])
    assert alloc_a == 43754, (
        f"floor(131000 * 33.4 / 100) == 43754 plus the single remainder cent to "
        f"the earliest share in pinned order; got {alloc_a}")


def test_later_shares_receive_their_floor_and_total_is_conserved(api):
    """PRD §3.7: "Each share receives the floor of the line's cents multiplied
    by its `share_percent` and divided by 100; the remainder, which is always
    smaller than the number of shares, is then distributed one cent at a time
    to shares in that same pinned order, so each share receives at most one
    remainder cent."

    Design: Difficulty/combinatorial_formula/per_share_allocation_rounding_order
    """
    m_a, m_b, m_c, stmts = _build_three_share_match()
    alloc_a = _alloc_for(m_a["id"], stmts[m_a["id"]]["id"])
    alloc_b = _alloc_for(m_b["id"], stmts[m_b["id"]]["id"])
    alloc_c = _alloc_for(m_c["id"], stmts[m_c["id"]]["id"])
    assert alloc_b == 43623, f"floor(131000 * 33.3 / 100) == 43623; got {alloc_b}"
    assert alloc_c == 43623, f"floor(131000 * 33.3 / 100) == 43623; got {alloc_c}"
    assert alloc_a + alloc_b + alloc_c == 131000, (
        f"conservation across the rounding split; got {alloc_a + alloc_b + alloc_c}")
