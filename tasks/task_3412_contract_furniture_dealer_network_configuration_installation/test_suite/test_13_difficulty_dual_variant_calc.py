"""Difficulty rule: dual_variant_calculation — the provisional and final
pricing variants of one order diverge on the tier basis, and the BUSINESS
variant of punch aging governs `escalated` where the CALENDAR variant
disagrees (PRD §3.5, §3.8)."""

from test_helpers import (
    acknowledge_order,
    create_and_lock_configuration,
    create_order,
    escalated_expected,
    file_punch,
    get_agreement,
    make_dealer_headers,
    make_end_user_headers,
    make_module_entry,
    set_logical_clock,
    setup_dealer_world,
    setup_phase_in_progress,
    submit_order,
    validate_paginated,
)


def _chair_order_200(api):
    """Dealer world + locked 200 x TASK_CHAIR_SET (A) config + DRAFT order.
    200 chairs x 125000c parts each gives a pre-discount total of exactly
    25000000 cents."""
    ctx = setup_dealer_world(api)
    spec = create_and_lock_configuration(
        api, ctx["dealer"]["id"],
        modules=[make_module_entry("TASK_CHAIR_SET", "A", 200)],
    )
    order = create_order(
        api, ctx["agreement"]["id"], spec["id"], ctx["dealer"]["id"]
    )
    return ctx, order


def test_provisional_pricing_excludes_current_order(api):
    """PRD §3.5: "the provisional tier basis is the agreement's
    `cumulative_volume_cents` as it stands before this order — excluding this
    order entirely — and the tier is 1 if the basis is less than 25000000".
    With cumulative volume 0, a 200-chair order (pre-discount exactly
    25000000) prices at tier 1: 25000000 x 0.90 = 22500000.

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_excludes_final_includes_current_order
    """
    ctx, order = _chair_order_200(api)
    submitted = submit_order(api, order, ctx["dealer"]["id"])
    assert submitted["pre_discount_total_cents"] == 25000000
    assert submitted["provisional_tier"] == 1
    assert submitted["provisional_total_cents"] == 22500000


def test_final_pricing_includes_current_order(api):
    """PRD §3.5: "the final tier basis is the agreement's
    `cumulative_volume_cents` plus this order's `pre_discount_total_cents`,
    so a single large order can tip itself into a higher tier." The same
    200-chair order acknowledges at final basis 0 + 25000000 = 25000000, tier
    2: 25000000 x 0.85 = 21250000 — 1250000 less than its own provisional
    total on identical inputs.

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_excludes_final_includes_current_order
    """
    ctx, order = _chair_order_200(api)
    submitted = submit_order(api, order, ctx["dealer"]["id"])
    acknowledged = acknowledge_order(api, order["id"])
    assert acknowledged["final_tier"] == 2
    assert acknowledged["final_total_cents"] == 21250000
    assert (
        acknowledged["provisional_total_cents"]
        - acknowledged["final_total_cents"]
        == 1250000
    )

    # §3.5: "Acknowledgment then debits the agreement ledger:
    # `cumulative_volume_cents` increases by the order's
    # `pre_discount_total_cents` and `current_tier` is recomputed."
    agreement = get_agreement(api, ctx["agreement"]["id"])
    assert agreement["cumulative_volume_cents"] == 25000000
    assert agreement["current_tier"] == 2


def _punch_filed_thursday(api):
    """Full chain to an IN_PROGRESS phase; a MAJOR punch filed by the end
    user at clock 2026-12-03 (a Thursday)."""
    ctx = setup_phase_in_progress(api, production_date="2026-11-02")
    set_logical_clock(api, "2026-12-03T00:00:00Z")
    ticket = file_punch(
        api, ctx["phase"]["id"],
        make_end_user_headers(ctx["end_user"]["id"]),
        severity="MAJOR",
        description="Scratched panel on workstation 12",
    )
    assert ticket["status"] == "OPEN"
    return ctx, ticket


def test_business_age_4_stays_unescalated_despite_calendar_age_6(api):
    """PRD §3.8: "The flag is true while the ticket is `OPEN` and at least 5
    business days have elapsed strictly after the ticket's creation calendar
    date" and "A separate calendar age — the clock date minus the creation
    date — exists for reporting and display only and never drives the flag".
    Created Thursday 2026-12-03, at clock Wednesday 2026-12-09 the calendar
    age is 6 but the business age is 4 (Fri, Mon, Tue, Wed), so `escalated`
    is false.

    Design: Difficulty/dual_variant_calc/punch_escalation_business_days_authoritative_over_calendar_days
    """
    ctx, ticket = _punch_filed_thursday(api)
    set_logical_clock(api, "2026-12-09T00:00:00Z")
    data, _meta = validate_paginated(
        api.list_punch_tickets(
            make_dealer_headers(ctx["dealer"]["id"]),
            params={"installation_phase_id": ctx["phase"]["id"]},
        )
    )
    assert len(data) == 1
    assert data[0]["id"] == ticket["id"]
    assert escalated_expected("OPEN", "2026-12-03", "2026-12-09") is False
    assert data[0]["escalated"] is False


def test_business_age_5_escalates_on_inclusive_boundary(api):
    """PRD §3.8: "Business age counts the dates strictly after the creation
    date up to and including the clock date that fall Monday through Friday,
    with no holiday calendar; the boundary is inclusive, so a business age of
    exactly 5 escalates." At clock Thursday 2026-12-10 the business age of
    the same ticket reaches 5 and `escalated` flips to true.

    Design: Difficulty/dual_variant_calc/punch_escalation_business_days_authoritative_over_calendar_days
    """
    ctx, ticket = _punch_filed_thursday(api)
    set_logical_clock(api, "2026-12-10T00:00:00Z")
    data, _meta = validate_paginated(
        api.list_punch_tickets(
            make_dealer_headers(ctx["dealer"]["id"]),
            params={"installation_phase_id": ctx["phase"]["id"]},
        )
    )
    assert len(data) == 1
    assert data[0]["id"] == ticket["id"]
    assert escalated_expected("OPEN", "2026-12-03", "2026-12-10") is True
    assert data[0]["escalated"] is True
