"""Transitive cascades: post-market recall blocking and liquidation closure,
plus the disposition apply gates."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    apply_disposition,
    assign_aisle,
    complete_screening,
    create_disposition,
    create_disposition_payload,
    create_event,
    get_lot,
    get_lot_summary,
    get_success_data,
    open_screening,
    propose_allocation,
    set_clock,
    setup_disposition_review_lot,
    setup_on_sale_lot,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["admin_headers"]
ALLOCATOR = TEST_USERS["allocation_manager_headers"]
OFFICER_ALT = TEST_USERS["safety_officer_alt_headers"]


def _block_lot_with_recall(lot_id: str) -> dict:
    """Post-market recall re-screen on an ON_SALE lot: open + FAIL recall."""
    scr = open_screening(lot_id, OFFICER_ALT)
    return complete_screening(
        lot_id, scr["id"], OFFICER_ALT,
        recall_check="FAIL", expiration_check="PASS", condition_verified=True,
        qty_grade_a=100, qty_grade_b=0, qty_grade_c=0)


def _create_disposition(lot_id: str, **overrides) -> dict:
    """Disposition factory that drops null optional fields (a MARKDOWN-only
    field like markdown_pct must not be sent as null on a LIQUIDATE)."""
    payload = create_disposition_payload(**overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    from test_helpers import api_client, get_lot as _get_lot
    if "expected_lot_version" not in payload:
        payload["expected_lot_version"] = _get_lot(lot_id)["version"]
    return get_success_data(api_client.create_disposition(
        lot_id, payload, TEST_USERS["sourcing_buyer_headers"]))


def test_recall_block_cancels_allocations_and_restores_pool(api):
    """PRD §3.3: "First, every allocation of the lot in `PROPOSED` or
    `CONFIRMED` status is cancelled, and each cancelled `CONFIRMED` allocation
    returns its `qty_granted` to the lot's `qty_pool`."
    PRD §3.3: "A `FAILED_RECALL` or `FAILED_EXPIRATION` result sets
    `safety_status` to `BLOCKED` and drives the lot to `BLOCKED` — whether it
    was in `SCREENING`, `ON_SALE`, or `DISPOSITION_REVIEW`".

    Design: Difficulty/transitive_cascade/recall_block_cascades_allocations_and_assignments
    """
    ctx = setup_on_sale_lot(receive=False)
    lot = ctx["lot"]
    store2 = get_success_data(api.create_store(
        {"name": "Store Two", "store_code": "S2",
         "jurisdiction_id": ctx["jurisdiction_id"], "performance_tier": "TIER_2"},
        ADMIN))
    al2 = propose_allocation(lot["id"], store2["id"], 20)  # stays PROPOSED

    done = _block_lot_with_recall(lot["id"])
    assert done["result"] == "FAILED_RECALL"

    al1_after = get_success_data(
        api.get_allocation(lot["id"], ctx["allocation"]["id"], ADMIN))
    al2_after = get_success_data(api.get_allocation(lot["id"], al2["id"], ADMIN))
    assert al1_after["status"] == "CANCELLED"
    assert al2_after["status"] == "CANCELLED"
    summary = get_lot_summary(lot["id"])
    assert summary["commercial_status"] == "BLOCKED"
    assert summary["qty_pool"] == 100
    assert summary["qty_allocated_outstanding"] == 0


def test_recall_block_supersedes_store_assignments(api):
    """PRD §3.3: "Second, for every store whose allocation was cancelled in
    the first link, that store's `ACTIVE` aisle assignments referencing the
    lot are superseded with `valid_to` set to the block timestamp."

    Design: Difficulty/transitive_cascade/recall_block_cascades_allocations_and_assignments
    """
    ctx = setup_on_sale_lot(receive=False)
    lot = ctx["lot"]
    assignment = assign_aisle(ctx["store"]["id"], lot["id"], daily_unit_limit=4)
    assert assignment["status"] == "ACTIVE"

    _block_lot_with_recall(lot["id"])

    data, _ = validate_paginated(
        api.list_store_aisle_assignments(ctx["store"]["id"], ADMIN))
    assert data[0]["status"] == "SUPERSEDED"
    assert data[0]["valid_to"] is not None


def test_liquidation_cascade_closes_assignments_and_events(api):
    """PRD §3.7: "Applying a `LIQUIDATE` requires that no allocation of the
    lot remain in `PROPOSED`, `CONFIRMED`, `SHIPPED`, or `RECEIVED` — the
    outstanding bucket must be empty — then moves all units in `qty_pool`
    into `qty_liquidated`, empties the pool, marks the disposition `APPLIED`,
    and closes the lot as `CLOSED_LIQUIDATED`; the closure cascades,
    superseding every `ACTIVE` aisle assignment referencing the lot with
    `valid_to` set to the close timestamp and cancelling every `SCHEDULED` or
    `ACTIVE` early-access event of the lot."
    PRD §3.9: "A `PricingLead` sweetens a deal by scheduling an
    `EarlyAccessEvent` on a lot that is `PRICED` or `ON_SALE`."

    Design: Difficulty/transitive_cascade/liquidation_cascade_closes_assignments_and_events
    """
    # Schedule the event while the lot is still ON_SALE (PRD §3.9 gates
    # event creation on PRICED/ON_SALE); the pacing review that follows
    # leaves the SCHEDULED event in place for the liquidation cascade to
    # cancel.
    ctx = setup_on_sale_lot(
        qty=100, alloc_qty=60,
        lot_overrides={"pace_target_units_per_week": 10}, receive=False)
    lot = ctx["lot"]
    store = ctx["store"]
    create_event(lot["id"], starts_at="2026-09-10T10:00:00Z",
                 ends_at="2026-09-10T12:00:00Z", min_tier="SILVER",
                 extra_discount_pct=10)
    set_clock("2026-09-04T00:00:00Z")
    lot = get_lot(lot["id"])
    assert lot["commercial_status"] == "DISPOSITION_REVIEW", (
        f"Setup failed: lot did not enter DISPOSITION_REVIEW, got "
        f"{lot['commercial_status']}")
    # Empty the outstanding bucket so liquidation is permitted.
    get_success_data(api.release_allocation(lot["id"], ctx["allocation"]["id"],
                                            ALLOCATOR))
    assign_aisle(store["id"], lot["id"], daily_unit_limit=4)

    dispo = _create_disposition(lot["id"], action="LIQUIDATE",
                                liquidator_ref="LIQ-9", recovery_cents=15000,
                                markdown_pct=None)
    applied = apply_disposition(lot["id"], dispo["id"])
    assert applied["status"] == "APPLIED"

    summary = get_lot_summary(lot["id"])
    assert summary["commercial_status"] == "CLOSED_LIQUIDATED"
    assert summary["qty_liquidated"] == 100
    assert summary["qty_pool"] == 0
    asg, _ = validate_paginated(
        api.list_store_aisle_assignments(store["id"], ADMIN))
    assert asg[0]["status"] == "SUPERSEDED"
    evs, _ = validate_paginated(api.list_early_access_events(lot["id"], ADMIN))
    assert evs[0]["status"] == "CANCELLED"


def test_liquidation_moves_pool_into_liquidated(api):
    """PRD §3.7: "Applying a `LIQUIDATE` ... then moves all units in
    `qty_pool` into `qty_liquidated`, empties the pool, marks the disposition
    `APPLIED`, and closes the lot as `CLOSED_LIQUIDATED`".
    PRD §3.7: "The three closed states are terminal."

    Design: Difficulty/transitive_cascade/liquidation_cascade_closes_assignments_and_events
    """
    ctx = setup_disposition_review_lot()
    lot = ctx["lot"]
    get_success_data(api.release_allocation(lot["id"], ctx["allocation"]["id"],
                                            ALLOCATOR))
    dispo = _create_disposition(lot["id"], action="LIQUIDATE",
                                liquidator_ref="LIQ-1", recovery_cents=5000,
                                markdown_pct=None)
    applied = apply_disposition(lot["id"], dispo["id"])
    assert applied["status"] == "APPLIED"
    assert applied["applied_at"] is not None
    summary = get_lot_summary(lot["id"])
    assert summary["commercial_status"] == "CLOSED_LIQUIDATED"
    assert summary["qty_liquidated"] == 100
    assert summary["qty_pool"] == 0
    assert summary["qty_sold"] == 0
    assert summary["qty_scrapped"] == 0


def test_markdown_apply_requires_disposition_review_state(api, buyer_headers):
    """PRD §3.7: "Applying a `MARKDOWN` reduces the lot's `retail_price_cents`
    by the stated percent ... and loops the lot back from
    `DISPOSITION_REVIEW` to `ON_SALE`, where pacing resumes against the same
    `on_sale_since`."
    PRD §2.6: "Lifecycle-state checks (`ERR_INVALID_STATE`) follow".

    Design: Corner/endpoints/conditional_action_markdown_requires_review_state
    """
    # ON_SALE lot, but the pacing review has not fired (clock at start).
    ctx = setup_on_sale_lot(receive=False)
    lot = ctx["lot"]
    dispo = create_disposition(lot["id"], action="MARKDOWN", markdown_pct=25)
    resp = api.apply_disposition(lot["id"], dispo["id"], buyer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    lot_after = get_lot(lot["id"])
    assert lot_after["retail_price_cents"] == 4000
    assert lot_after["markdown_rounds"] == 0
