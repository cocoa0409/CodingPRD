"""Difficulty rule: boundary_precision_check — the volume-tier boundary is
inclusive on its lower edge, and the complete-gate counts blocking punch
tickets with a hard zero boundary (PRD §3.2, §3.5, §3.6)."""

from test_helpers import (
    ApiErrorId,
    acknowledge_chair_order,
    complete_phase,
    file_punch,
    make_dealer_headers,
    make_end_user_headers,
    resolve_punch,
    setup_dealer_world,
    setup_phase_in_progress,
    validate_error,
    verify_punch,
)


def test_final_basis_below_boundary_stays_tier1(api):
    """PRD §3.5: "the tier is 1 if the basis is less than 25000000, 2 if it
    is at least 25000000 and less than 75000000". With cumulative 12500000,
    a 99-chair order (pre-discount 12375000) lands the final basis at
    24875000 — one chair short — and stays tier 1: 12375000 x 0.90 =
    11137500.

    Design: Difficulty/boundary_precision_check/tier_boundary_exactly_25000000_cents_crosses
    """
    ctx = setup_dealer_world(api)
    acknowledge_chair_order(api, ctx, 100)
    order = acknowledge_chair_order(api, ctx, 99)
    assert order["pre_discount_total_cents"] == 12375000
    assert order["final_tier"] == 1
    assert order["final_total_cents"] == 11137500


def test_final_basis_exactly_at_boundary_crosses_tier2(api):
    """PRD §3.5: "2 if it is at least 25000000" — the boundary is inclusive
    on the lower edge. With cumulative 24875000 (100 + 99 chairs
    acknowledged), a 1-chair order lands the final basis on exactly
    25000000 and prices at tier 2: 125000 x 0.85 = 106250.

    Design: Difficulty/boundary_precision_check/tier_boundary_exactly_25000000_cents_crosses
    """
    ctx = setup_dealer_world(api)
    acknowledge_chair_order(api, ctx, 100)
    acknowledge_chair_order(api, ctx, 99)
    order = acknowledge_chair_order(api, ctx, 1)
    assert order["pre_discount_total_cents"] == 125000
    assert order["final_tier"] == 2
    assert order["final_total_cents"] == 106250


def _phase_with_critical_punch(api):
    """An IN_PROGRESS phase (clock at production date 2026-11-02) carrying
    one OPEN CRITICAL punch ticket filed by the end user."""
    ctx = setup_phase_in_progress(api, production_date="2026-11-02")
    ticket = file_punch(
        api, ctx["phase"]["id"],
        make_end_user_headers(ctx["end_user"]["id"]),
        severity="CRITICAL",
        description="Live wire exposed at station 7",
    )
    return ctx, ticket


def test_open_or_resolved_critical_punch_blocks_complete(api):
    """PRD §3.6: "the phase must have zero `CRITICAL` punch tickets in
    `OPEN` or `RESOLVED` status and zero `MAJOR` punch tickets in `OPEN`
    status, else `ERR_OPEN_CRITICAL_PUNCH`" — one CRITICAL punch blocks at
    count 1, and RESOLVED-but-unverified still counts.

    Design: Difficulty/boundary_precision_check/zero_open_critical_punches_gate_at_complete
    """
    ctx, ticket = _phase_with_critical_punch(api)
    dealer_h = make_dealer_headers(ctx["dealer"]["id"])

    resp = api.complete_phase(ctx["phase"]["id"], dealer_h)
    validate_error(resp, ApiErrorId.ERR_OPEN_CRITICAL_PUNCH)

    resolve_punch(api, ticket["id"], ctx["dealer"]["id"],
                  resolution_note="Rewired and taped")
    resp = api.complete_phase(ctx["phase"]["id"], dealer_h)
    validate_error(resp, ApiErrorId.ERR_OPEN_CRITICAL_PUNCH)


def test_verified_critical_punch_unblocks_complete(api):
    """PRD §3.6: the punch gate counts CRITICAL tickets "in `OPEN` or
    `RESOLVED` status" — after the end user's CONFIRMED verification moves
    the ticket to VERIFIED the count hits exactly zero and `IN_PROGRESS →
    COMPLETE` succeeds.

    Design: Difficulty/boundary_precision_check/zero_open_critical_punches_gate_at_complete
    """
    ctx, ticket = _phase_with_critical_punch(api)
    resolve_punch(api, ticket["id"], ctx["dealer"]["id"],
                  resolution_note="Rewired and taped")
    verify_punch(api, ticket["id"], ctx["end_user"]["id"],
                 outcome="CONFIRMED")

    done = complete_phase(api, ctx["phase"]["id"], ctx["dealer"]["id"])
    assert done["install_status"] == "COMPLETE"
