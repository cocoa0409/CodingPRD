"""Funding-pool ledger conservation and the withdrawal cascade (PRD §2.6/§3.1),
plus material-order rounding and funding gates (PRD §3.8)."""

from test_helpers import (
    ApiErrorId,
    api_client,
    cancel_project,
    create_candidate,
    create_commitment,
    create_cycle,
    create_eligible_volunteer,
    create_material_order,
    create_material_order_payload,
    create_published_event,
    create_sponsor,
    deliver_material_order,
    enroll_volunteer,
    get_application,
    get_commitment,
    get_cycle,
    get_enrollment,
    get_event,
    get_project,
    get_project_for_application,
    material_line_payload,
    open_selection,
    reset_clock,
    run_selection,
    scope_item_payload,
    setup_selected_project,
    trade_scope_item_payload,
    validate_error,
    validate_ok,
    validate_paginated,
    STAFF,
)


def _setup_three_project_pool():
    """Cycle 1200000 + one RECEIVED commitment 500000 (pool 1700000); three
    candidates scored 81/50/38 each estimating 450000 (envelope 517500), all
    selected (reserved 1552500, available 147500). The lowest-priority project
    hosts a PUBLISHED event with one enrolled eligible volunteer."""
    reset_clock()
    cycle = create_cycle(total_budget_cents=1_200_000)
    sponsor = create_sponsor(name="Acme Corp")
    commitment = create_commitment(sponsor["id"], cycle["id"], 500_000, receive=True)
    specs = [
        trade_scope_item_payload(
            est_low_cents=100_000, est_high_cents=200_000, description="panel"
        ),
        scope_item_payload(
            est_low_cents=200_000, est_high_cents=400_000, description="ramp"
        ),
    ]
    ctx1 = create_candidate(
        cycle["id"],
        scope_items=specs,
        homeowner_name="A1 Older Vet",
        date_of_birth="1960-05-05",
        household_size=2,
        household_income_cents=3_000_000,
        is_veteran=True,
    )
    ctx2 = create_candidate(
        cycle["id"],
        scope_items=specs,
        homeowner_name="A2 Older",
        date_of_birth="1960-05-05",
        household_size=2,
        household_income_cents=3_000_000,
    )
    ctx3 = create_candidate(
        cycle["id"],
        scope_items=specs,
        homeowner_name="A3 Disabled",
        date_of_birth="1980-01-01",
        household_size=2,
        household_income_cents=3_000_000,
        has_disability=True,
    )
    open_selection(cycle["id"])
    sel = run_selection(cycle["id"])
    assert sel["apply"]["applied_count"] == 3, (
        "all three envelopes 517500 fit the 1700000 pool"
    )
    p3 = get_project_for_application(ctx3["application"]["id"])
    event = create_published_event(
        p3["id"], name="NRD Site 3", event_date="2026-10-10", max_volunteers=5
    )
    volunteer = create_eligible_volunteer(full_name="Vol One")
    enrollment = enroll_volunteer(event["id"], volunteer["id"])
    return {
        "cycle": cycle,
        "commitment": commitment,
        "apps": [ctx1["application"], ctx2["application"], ctx3["application"]],
        "p3": p3,
        "event": event,
        "enrollment": enrollment,
    }


def test_commitment_withdrawal_cascades_to_project_event_enrollment():
    """PRD §3.1: "2. While `reserved_cents` exceeds `pool_cents` minus
    `spent_cents`, the lowest-priority cancellable project — one in `PLANNING`
    or `READY`, chosen by `priority_score_snapshot` ascending with ties broken
    by the project's `created_at` descending, so that among equals the most
    recently created is sacrificed first — is cancelled with
    `cancellation_reason` `FUNDING_WITHDRAWN`, repeating until the invariant
    holds again."
    PRD §3.1: "3. Each cancelled project releases its `reserved_balance_cents`
    back to the cycle, its application falls to `DEFERRED` with
    `decision_reason` `FUNDING_WITHDRAWN`, and every non-terminal rebuild event
    of the project is cancelled."
    PRD §3.1: "4. Every enrollment of such a cascade-cancelled event that sits
    in `ENROLLED`, `CONFIRMED`, or `CHECKED_IN` is withdrawn to `WITHDRAWN`."
    PRD §3.1: "Withdrawing a `RECEIVED` or `ALLOCATED` commitment stamps
    `withdrawn_at`, drops `pool_cents` and `available_cents` by `amount_cents`,
    and — for an allocated commitment — returns its `allocated_amount_cents` to
    zero."

    Withdrawing the RECEIVED commitment shrinks the pool to 1200000; the
    lowest-priority project (score snapshot 38) is auto-cancelled, its
    application deferred, its event cancelled, and the event's enrollment
    withdrawn — a four-link compensating cascade.

    Design: Difficulty/transitive_cascade/commitment_withdrawal_cascades_four_links
    """
    ctx = _setup_three_project_pool()
    validate_ok(
        api_client.patch_commitment(
            ctx["commitment"]["id"], {"status": "WITHDRAWN"}, STAFF
        )
    )
    com_after = get_commitment(ctx["commitment"]["id"])
    assert com_after["status"] == "WITHDRAWN"
    assert com_after["allocated_amount_cents"] == 0, (
        "the 352500 waterfall allocation is clawed back"
    )
    p3 = get_project(ctx["p3"]["id"])
    assert p3["status"] == "CANCELLED"
    assert p3["cancellation_reason"] == "FUNDING_WITHDRAWN"
    app3 = get_application(ctx["apps"][2]["id"])
    assert app3["status"] == "DEFERRED"
    assert app3["decision_reason"] == "FUNDING_WITHDRAWN"
    assert get_event(ctx["event"]["id"])["status"] == "CANCELLED"
    assert get_enrollment(ctx["enrollment"]["id"])["status"] == "WITHDRAWN"


def test_commitment_withdrawal_restores_ledger_invariant():
    """PRD §2.6: "One compensating invariant governs the ledger:
    `available_cents` equals `pool_cents` minus `reserved_cents` minus
    `spent_cents` before and after every mutation, with no exceptions."

    After the withdrawal cascade, pool is 1200000, the two surviving projects
    hold reserved 1035000, and available is exactly 165000 — one cancellation
    restored the invariant and the other projects are untouched.

    Design: Difficulty/transitive_cascade/commitment_withdrawal_cascades_four_links
    """
    ctx = _setup_three_project_pool()
    validate_ok(
        api_client.patch_commitment(
            ctx["commitment"]["id"], {"status": "WITHDRAWN"}, STAFF
        )
    )
    cycle = get_cycle(ctx["cycle"]["id"])
    assert cycle["pool_cents"] == 1_200_000, (
        "the commitment leaves the pool entirely"
    )
    assert cycle["reserved_cents"] == 1_035_000
    assert cycle["available_cents"] == 165_000
    assert cycle["spent_cents"] == 0
    for app in ctx["apps"][:2]:
        project = get_project_for_application(app["id"])
        assert project["status"] == "PLANNING", (
            "the surviving projects are not cascade-cancelled"
        )
        assert get_application(app["id"])["status"] == "SELECTED"


def test_funding_pool_conserved_across_delivery_and_return():
    """PRD §2.6: "One compensating invariant governs the ledger:
    `available_cents` equals `pool_cents` minus `reserved_cents` minus
    `spent_cents` before and after every mutation, with no exceptions."
    PRD §3.8: "Staff then stage the order (`ORDERED` → `STAGED`) and record
    delivery (`STAGED` → `DELIVERED`); delivery raises the cycle's `spent_cents`
    by `total_cents` and recomputes posture, which may fire the automatic
    `PLANNING` → `READY` promotion."
    PRD §3.8: "Returning a `DELIVERED` order refunds `total_cents` out of the
    cycle's `spent_cents` and recomputes posture, possibly demoting `READY`
    back to `PLANNING`."

    Selection reserves the envelope (available 885000); delivery moves 1787 to
    spent (available 883213) without touching the reserve; the return refunds
    it exactly (available 885000 again).

    Design: Difficulty/compensating_invariant/funding_pool_conserved_across_selection_delivery_return_and_cancel
    """
    reset_clock()
    cycle = create_cycle(total_budget_cents=1_000_000)
    cycle0 = get_cycle(cycle["id"])
    assert cycle0["available_cents"] == 1_000_000
    assert cycle0["reserved_cents"] == 0
    assert cycle0["spent_cents"] == 0
    ctx = create_candidate(cycle["id"])
    open_selection(cycle["id"])
    run_selection(cycle["id"])
    cycle1 = get_cycle(cycle["id"])
    assert cycle1["reserved_cents"] == 115_000
    assert cycle1["available_cents"] == 885_000
    assert cycle1["spent_cents"] == 0
    project = get_project_for_application(ctx["application"]["id"])
    order = create_material_order(
        project["id"],
        lines=[
            material_line_payload(
                item_name="brackets", quantity=1, unit_price_dollars=10.005
            ),
            material_line_payload(
                item_name="sealant", quantity=1, unit_price_dollars=7.255
            ),
        ],
    )
    assert order["total_cents"] == 1_787
    deliver_material_order(order["id"])
    cycle2 = get_cycle(cycle["id"])
    assert cycle2["spent_cents"] == 1_787
    assert cycle2["reserved_cents"] == 115_000
    assert cycle2["available_cents"] == 883_213
    validate_ok(
        api_client.patch_material_order(order["id"], {"status": "RETURNED"}, STAFF)
    )
    cycle3 = get_cycle(cycle["id"])
    assert cycle3["spent_cents"] == 0, "the return refunds the delivery exactly"
    assert cycle3["available_cents"] == 885_000


def test_funding_pool_conserved_across_selection_and_cancel():
    """PRD §2.6: "A selection that reserves an envelope, paired with a later
    cancellation that releases it, leaves `available_cents` unchanged; a
    material delivery that adds to `spent_cents`, paired with a return that
    subtracts the same amount, leaves it unchanged; and an invoice payment that
    shifts funds from reserved to spent, followed by a project completion that
    releases the remainder, leaves it unchanged as well."

    The select/cancel pair alone closes the round trip with zero drift:
    available 1000000 -> 885000 -> 1000000.

    Design: Difficulty/compensating_invariant/funding_pool_conserved_across_selection_delivery_return_and_cancel
    """
    reset_clock()
    cycle = create_cycle(total_budget_cents=1_000_000)
    ctx = create_candidate(cycle["id"])
    open_selection(cycle["id"])
    run_selection(cycle["id"])
    project = get_project_for_application(ctx["application"]["id"])
    cycle1 = get_cycle(cycle["id"])
    assert cycle1["reserved_cents"] == 115_000
    assert cycle1["available_cents"] == 885_000
    cancelled = cancel_project(project["id"], "STAFF_DECISION")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["reserved_balance_cents"] == 0
    cycle2 = get_cycle(cycle["id"])
    assert cycle2["reserved_cents"] == 0
    assert cycle2["spent_cents"] == 0
    assert cycle2["available_cents"] == 1_000_000, (
        "cancellation releases the reserve; the cycle closes the round trip "
        "with zero drift"
    )


def test_pledged_commitment_withdrawal_leaves_pool_untouched():
    """PRD §3.1: "Withdrawing a `PLEDGED` commitment merely stamps
    `withdrawn_at`; the pool is unchanged because the money never entered it."

    The PLEDGED-withdrawal contrast case: pool and available are identical
    before and after, and no deferral cascade fires.

    Design: Corner/cross_cutting_complexity_layers/pledged_commitment_withdrawal_leaves_pool_untouched
    """
    reset_clock()
    cycle = create_cycle(total_budget_cents=1_000_000)
    sponsor = create_sponsor(name="Maybe Corp")
    commitment = create_commitment(sponsor["id"], cycle["id"], 500_000)
    ctx = create_candidate(cycle["id"])
    open_selection(cycle["id"])
    run_selection(cycle["id"])
    project = get_project_for_application(ctx["application"]["id"])
    pre = get_cycle(cycle["id"])
    assert pre["pool_cents"] == 1_000_000
    assert pre["available_cents"] == 885_000
    proj_pre = get_project(project["id"])
    validate_ok(
        api_client.patch_commitment(
            commitment["id"], {"status": "WITHDRAWN"}, STAFF
        )
    )
    post = get_cycle(cycle["id"])
    assert post["pool_cents"] == 1_000_000, "PLEDGED funds never entered the pool"
    assert post["available_cents"] == 885_000
    proj_post = get_project(project["id"])
    assert proj_post["status"] == proj_pre["status"], (
        "no deferral cascade fires for a PLEDGED withdrawal"
    )


def test_material_order_above_available_returns_insufficient_funding():
    """PRD §3.8: "At creation the order's `total_cents` must fit within the
    cycle's `available_cents`, otherwise `ERR_INSUFFICIENT_FUNDING` (HTTP 402)."

    The computed total (subtotal 100000 + fee 3500 = 103500), not the raw line
    sum, is checked against the 85000 left available after selection.

    Design: Corner/validations/material_order_above_available_returns_insufficient_funding
    """
    ctx = setup_selected_project(budget_cents=200_000)
    project = ctx["project"]
    resp = api_client.create_material_order(
        create_material_order_payload(
            project["id"],
            lines=[
                material_line_payload(
                    item_name="lumber bundle", quantity=1, unit_price_dollars=1000.00
                )
            ],
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDING)
    rows, _ = validate_paginated(
        api_client.list_material_orders(STAFF, params={"project_id": project["id"]})
    )
    assert rows == [], "no MaterialOrder row persists for the failed create"


def test_material_total_per_line_rounding_beats_sum_then_round():
    """PRD §3.8: "Each line is first converted to cents on its own — `quantity`
    times `unit_price_dollars` times one hundred, rounded half up — and the
    order's `subtotal_cents` is the sum of those individually rounded line
    amounts."

    Lines 1x10.005 and 1x7.255 dollars: round_half_up(1000.5) = 1001 and
    round_half_up(725.5) = 726 give subtotal 1727; a sum-then-round
    implementation would produce 1726 and is non-conforming.

    Design: Difficulty/combinatorial_formula/material_total_per_line_rounding_then_fee
    """
    ctx = setup_selected_project(budget_cents=2_000_000)
    order = create_material_order(
        ctx["project"]["id"],
        lines=[
            material_line_payload(
                item_name="brackets", quantity=1, unit_price_dollars=10.005
            ),
            material_line_payload(
                item_name="sealant", quantity=1, unit_price_dollars=7.255
            ),
        ],
    )
    assert order["subtotal_cents"] == 1_727, (
        f"per-line rounding must yield 1001 + 726; got {order['subtotal_cents']}"
    )


def test_material_delivery_fee_on_rounded_subtotal():
    """PRD §3.8: "The `delivery_fee_cents` is then the subtotal times three and
    a half percent, rounded half up, computed on the already-rounded subtotal.
    The `total_cents` is the subtotal plus the fee."

    On the rounded subtotal 1727 the fee is round_half_up(60.445) = 60 and the
    total is 1787.

    Design: Difficulty/combinatorial_formula/material_total_per_line_rounding_then_fee
    """
    ctx = setup_selected_project(budget_cents=2_000_000)
    order = create_material_order(
        ctx["project"]["id"],
        lines=[
            material_line_payload(
                item_name="brackets", quantity=1, unit_price_dollars=10.005
            ),
            material_line_payload(
                item_name="sealant", quantity=1, unit_price_dollars=7.255
            ),
        ],
    )
    assert order["subtotal_cents"] == 1_727
    assert order["delivery_fee_cents"] == 60, (
        f"round_half_up(1727 * 0.035) = 60; got {order['delivery_fee_cents']}"
    )
    assert order["total_cents"] == 1_787
