"""Disposition: pinned markdown rounding, the cannibalization approve guard,
state/quantity/pct bounds, segregation of duties, the destroy-by window, the
CLOSED gate, and the safety-before-constraint priority pair.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_AT_PULL,
    CLOCK_PAST_DESTROY_BY,
    CM_ALICE_USER_ID,
    CM_BOB_USER_ID,
    DispositionOrderStatus,
    InventoryLotStatus,
    ProgramAdvanceTarget,
    SeasonalProgramStatus,
    WarehousePosture,
    TEST_USERS,
    advance_program_to,
    api_client,
    compute_markdown_recovered_value,
    create_approved_disposition,
    create_disposition_order_payload,
    decide_disposition,
    dispose_all_quarantined,
    execute_disposition,
    file_sell_through_report,
    get_lot_for_run,
    get_program,
    get_warehouse,
    make_category_manager_headers,
    propose_disposition,
    set_clock,
    setup_disposition_program,
    setup_on_shelf_program,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM_ALICE = TEST_USERS["category_manager_headers"]
CM_BOB = TEST_USERS["category_manager_b_headers"]


# ---------------------------------------------------------------------------
# Pinned per-unit-first markdown rounding
# ---------------------------------------------------------------------------

def test_markdown_recovery_rounds_per_unit_before_multiplication(api):
    """PRD §3.9: "For `MARKDOWN`, the per-unit price after markdown is
    computed first — the program's `retail_price_cents` scaled by one minus
    the `markdown_pct`, rounded half-up to whole cents — and only then
    multiplied by the disposed `units`; this per-unit-first order is pinned,
    and the alternative of multiplying first and rounding once is forbidden
    because it yields different cents (at a 499-cent price, a 0.15 markdown,
    and 10 units, the pinned result is 424 cents times 10, i.e. 4240 cents —
    not the 4242 cents the alternative would produce)."

    Design: Difficulty/combinatorial_formula/markdown_recovery_rounds_per_unit_before_summation
    """
    world = setup_disposition_program(produced_units=10)
    order = propose_disposition(
        world["program"], world["product"], world["warehouse"], 10,
        channel="MARKDOWN", markdown_pct=0.15,
    )
    decide_disposition(order["id"], "APPROVE")  # no reports exist: guard N/A
    executed = execute_disposition(order["id"])
    assert executed["status"] == DispositionOrderStatus.EXECUTED.value
    # round_half_up(499 x 0.85) = 424 per unit; 424 x 10 = 4240 (not 4242).
    assert executed["recovered_value_cents"] == 4240
    assert executed["recovered_value_cents"] != 4242
    assert executed["recovered_value_cents"] == compute_markdown_recovered_value(
        499, 0.15, 10,
    )


def test_markdown_execute_side_effects_dispose_lot_and_recompute_totals(api):
    """PRD §3.9: "Execution consumes the warehouse's `QUARANTINED` lots of the
    product in `created_at` ascending, `lot_code` ascending order, and a lot
    whose `units_on_hand` reaches zero becomes `DISPOSITIONED`." and
    "Execution then recomputes the warehouse's load figures and posture,
    refreshes the program's `disposed_units_total`".

    Design: Difficulty/combinatorial_formula/markdown_recovery_rounds_per_unit_before_summation
    """
    world = setup_disposition_program(produced_units=10)
    order = propose_disposition(
        world["program"], world["product"], world["warehouse"], 10,
        channel="MARKDOWN", markdown_pct=0.15,
    )
    decide_disposition(order["id"], "APPROVE")
    execute_disposition(order["id"])

    lot = get_lot_for_run(world["run"]["id"])
    assert lot["status"] == InventoryLotStatus.DISPOSITIONED.value
    assert lot["units_on_hand"] == 0
    program = get_program(world["program"]["id"])
    assert program["disposed_units_total"] == 10
    warehouse = get_warehouse(world["warehouse"]["id"])
    assert warehouse["in_use_units"] == 0
    assert warehouse["quarantined_units"] == 0
    assert warehouse["posture"] == WarehousePosture.OPEN.value


# ---------------------------------------------------------------------------
# Cannibalization guard on MARKDOWN approve
# ---------------------------------------------------------------------------

def test_cannibalization_guard_blocks_markdown_approve_below_floor(api):
    """PRD §3.9: "if at least one sell-through report exists for the program,
    the average of `cannibalization_raw` over those reports must be at least
    0.85 — the cannibalization floor — or the approval is rejected with
    `ERR_CANNIBALIZATION_GUARD` (HTTP 422)"."

    Design: Corner/calculations/cannibalization_guard_blocks_markdown_approve_below_floor
    """
    world = setup_on_shelf_program(produced_units=10)
    report = file_sell_through_report(
        world["program"], world["retailer"],
        seasonal_units_sold=40, seasonal_units_on_hand=200,
        everyday_units_sold=800,
    )
    assert report["cannibalization_raw"] == pytest.approx(0.8, abs=1e-9)  # < 0.85

    set_clock(CLOCK_AT_PULL)
    advance_program_to(world["program"]["id"], ProgramAdvanceTarget.DISPOSITION.value)

    md = propose_disposition(
        world["program"], world["product"], world["warehouse"], 10,
        channel="MARKDOWN", markdown_pct=0.30,
    )
    blocked = api_client.approve_disposition_order(md["id"], {"decision": "APPROVE"}, CM_BOB)
    validate_error(blocked, ApiErrorId.ERR_CANNIBALIZATION_GUARD)
    after = validate_success(api_client.get_disposition_order(md["id"], ADMIN), 200)
    assert after["status"] == DispositionOrderStatus.PROPOSED.value

    # The guard is channel-specific: DESTRUCTION on the same stock approves.
    dest = propose_disposition(
        world["program"], world["product"], world["warehouse"], 10,
        channel="DESTRUCTION",
    )
    approved = decide_disposition(dest["id"], "APPROVE")
    assert approved["status"] == DispositionOrderStatus.APPROVED.value


# ---------------------------------------------------------------------------
# Proposal gates: program state, markdown bounds, quarantined-stock bound
# ---------------------------------------------------------------------------

def test_disposition_propose_before_disposition_state_returns_invalid_state(api):
    """PRD §3.9: "A `CategoryManager` proposes a `DispositionOrder` naming the
    `program_id` — the program must be in `DISPOSITION` status, or the
    proposal is rejected with `ERR_INVALID_STATE`".

    Design: Corner/validations/disposition_propose_before_disposition_state_returns_invalid_request
    """
    world = setup_on_shelf_program(produced_units=10)
    resp = api_client.create_disposition_order(
        create_disposition_order_payload(
            program_id=world["program"]["id"], product_id=world["product"]["id"],
            warehouse_id=world["warehouse"]["id"], units=10, channel="DESTRUCTION",
        ),
        CM_ALICE,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    rows, _meta = validate_paginated(api_client.list_disposition_orders(
        ADMIN, params={"program_id": world["program"]["id"]},
    ))
    assert rows == []
    lot = get_lot_for_run(world["run"]["id"])
    assert lot["status"] == InventoryLotStatus.AVAILABLE.value, (
        "no pull quarantine has run yet"
    )


def test_markdown_pct_below_floor_and_above_cap_rejected_bounds_inclusive(api):
    """PRD §3.9: "A `MARKDOWN` order must carry a `markdown_pct` — a fraction
    no lower than 0.10 and no higher than 0.70 — and a missing or out-of-band
    value is rejected with `ERR_MARKDOWN_OUT_OF_RANGE` (HTTP 422)."

    Design: Corner/validations/markdown_pct_below_floor_and_above_cap_rejected_bounds_inclusive
    """
    world = setup_disposition_program(produced_units=10)

    def propose_with_pct(pct):
        return api_client.create_disposition_order(
            create_disposition_order_payload(
                program_id=world["program"]["id"], product_id=world["product"]["id"],
                warehouse_id=world["warehouse"]["id"], units=1,
                channel="MARKDOWN", markdown_pct=pct,
            ),
            CM_ALICE,
        )

    validate_error(propose_with_pct(0.05), ApiErrorId.ERR_MARKDOWN_OUT_OF_RANGE)
    validate_error(propose_with_pct(0.75), ApiErrorId.ERR_MARKDOWN_OUT_OF_RANGE)

    ok = validate_success(propose_with_pct(0.10), 201)  # exactly the floor
    assert ok["status"] == DispositionOrderStatus.PROPOSED.value
    assert ok["markdown_pct"] == pytest.approx(0.10)


def test_disposition_units_above_quarantined_stock_rejected(api):
    """PRD §3.9: "The `units` must be at least 1 and no more than the
    quarantined `units_on_hand` of that product at that warehouse, or the
    proposal is rejected with `ERR_DISPOSITION_EXCEEDS_QUARANTINE`
    (HTTP 422)."

    Design: Corner/validations/disposition_units_above_quarantined_stock_rejected
    """
    world = setup_disposition_program(produced_units=10)

    over = api_client.create_disposition_order(
        create_disposition_order_payload(
            program_id=world["program"]["id"], product_id=world["product"]["id"],
            warehouse_id=world["warehouse"]["id"], units=11, channel="DESTRUCTION",
        ),
        CM_ALICE,
    )
    validate_error(over, ApiErrorId.ERR_DISPOSITION_EXCEEDS_QUARANTINE)

    exact = validate_success(api_client.create_disposition_order(
        create_disposition_order_payload(
            program_id=world["program"]["id"], product_id=world["product"]["id"],
            warehouse_id=world["warehouse"]["id"], units=10, channel="DESTRUCTION",
        ),
        CM_ALICE,
    ), 201)
    assert exact["units"] == 10
    assert exact["status"] == DispositionOrderStatus.PROPOSED.value


# ---------------------------------------------------------------------------
# Segregation of duties on approval
# ---------------------------------------------------------------------------

def test_disposition_approve_by_proposing_manager_returns_segregation_of_duties(api):
    """PRD §3.9: "Approval belongs to a **different** `CategoryManager`: the
    approver's `X-User-ID` must differ from `proposed_by_user_id`, and a
    self-approval — whether the decision is `APPROVE` or `REJECT` — is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/disposition_approve_by_proposing_manager_returns_segregation_of_duties
    """
    world = setup_disposition_program(produced_units=10)
    order = propose_disposition(
        world["program"], world["product"], world["warehouse"], 10,
        channel="DESTRUCTION", proposer_headers=make_category_manager_headers(CM_ALICE_USER_ID),
    )
    assert order["proposed_by_user_id"] == CM_ALICE_USER_ID

    self_approve = api_client.approve_disposition_order(
        order["id"], {"decision": "APPROVE"},
        make_category_manager_headers(CM_ALICE_USER_ID),
    )
    validate_error(self_approve, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    approved = validate_success(api_client.approve_disposition_order(
        order["id"], {"decision": "APPROVE"},
        make_category_manager_headers(CM_BOB_USER_ID),
    ), 200)
    assert approved["status"] == DispositionOrderStatus.APPROVED.value
    assert approved["approved_by_user_id"] == CM_BOB_USER_ID


# ---------------------------------------------------------------------------
# destroy_by_on partitions the channels at execute time
# ---------------------------------------------------------------------------

def test_markdown_execute_after_destroy_by_closed_but_destruction_still_allowed(api):
    """PRD §3.9: "a `MARKDOWN` or `SECONDARY` order may execute only while the
    logical clock has not passed the program's `destroy_by_on`; after that
    instant only `DESTRUCTION` may execute, and an out-of-window attempt is
    rejected with `ERR_DISPOSITION_WINDOW_CLOSED` (HTTP 422)." and "For
    `DESTRUCTION`, the recovered value is 0."

    Design: Corner/errors/markdown_execute_after_destroy_by_closed_but_destruction_still_allowed
    """
    world = setup_disposition_program(produced_units=10)
    md = create_approved_disposition(
        world["program"], world["product"], world["warehouse"], 5,
        channel="MARKDOWN", markdown_pct=0.30,
    )
    dest = create_approved_disposition(
        world["program"], world["product"], world["warehouse"], 5,
        channel="DESTRUCTION",
    )

    set_clock(CLOCK_PAST_DESTROY_BY)  # 2028-01-01, past destroy_by 2027-12-31
    late_md = api_client.execute_disposition_order(
        md["id"], TEST_USERS["logistics_coordinator_headers"],
    )
    validate_error(late_md, ApiErrorId.ERR_DISPOSITION_WINDOW_CLOSED)
    after_md = validate_success(api_client.get_disposition_order(md["id"], ADMIN), 200)
    assert after_md["status"] == DispositionOrderStatus.APPROVED.value

    executed = execute_disposition(dest["id"])
    assert executed["status"] == DispositionOrderStatus.EXECUTED.value
    assert executed["recovered_value_cents"] == 0
    warehouse = get_warehouse(world["warehouse"]["id"])
    assert warehouse["quarantined_units"] == 5  # the markdown-blocked 5 remain


# ---------------------------------------------------------------------------
# The CLOSED gate: no undisposed quarantined stock
# ---------------------------------------------------------------------------

def test_close_blocked_until_all_quarantined_stock_disposed(api):
    """PRD §3.9: "advancing the program from `DISPOSITION` to `CLOSED`
    requires that no `QUARANTINED` lot with `units_on_hand` greater than zero
    remain for any product of the program, and an attempt with undisposed
    stock outstanding is rejected with `ERR_UNDISPOSED_STOCK_REMAINS`
    (HTTP 422)."

    Design: Corner/errors/close_blocked_until_all_quarantined_stock_disposed
    """
    world = setup_disposition_program(produced_units=10)
    program = world["program"]

    blocked = api_client.advance_program(
        program["id"],
        {
            "to_state": ProgramAdvanceTarget.CLOSED.value,
            "expected_program_version": program["version"],
        },
        ADMIN,
    )
    validate_error(blocked, ApiErrorId.ERR_UNDISPOSED_STOCK_REMAINS)

    dispose_all_quarantined(world)
    drained = get_program(program["id"])
    assert drained["disposed_units_total"] == 10
    lot = get_lot_for_run(world["run"]["id"])
    assert lot["status"] == InventoryLotStatus.DISPOSITIONED.value
    assert lot["units_on_hand"] == 0
    assert get_warehouse(world["warehouse"]["id"])["quarantined_units"] == 0

    closed = advance_program_to(program["id"], ProgramAdvanceTarget.CLOSED.value)
    assert closed["status"] == SeasonalProgramStatus.CLOSED.value


# ---------------------------------------------------------------------------
# Priority pair: business safety (8) beats structural constraint (10)
# ---------------------------------------------------------------------------

def _propose_secondary_overshoot():
    """DISPOSITION world with 10 quarantined units of a brand-protected
    product; propose SECONDARY for 9999 units (both brand protection and the
    quarantine bound are violated)."""
    world = setup_disposition_program(produced_units=10)
    return api_client.create_disposition_order(
        create_disposition_order_payload(
            program_id=world["program"]["id"], product_id=world["product"]["id"],
            warehouse_id=world["warehouse"]["id"], units=9999, channel="SECONDARY",
        ),
        CM_ALICE,
    ), world


def test_brand_protection_blocks_secondary_for_protected_product(api):
    """PRD §3.9: "Brand protection is absolute: a `SECONDARY`-channel order
    for a `brand_protected` product is rejected with `ERR_BRAND_PROTECTION`
    (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/brand_protection_safety_beats_quarantine_quantity_constraint
    """
    resp, world = _propose_secondary_overshoot()
    validate_error(resp, ApiErrorId.ERR_BRAND_PROTECTION)
    rows, _meta = validate_paginated(api_client.list_disposition_orders(
        ADMIN, params={"program_id": world["program"]["id"]},
    ))
    assert rows == []


def test_brand_protection_beats_quarantine_quantity_constraint(api):
    """PRD §2.8: "A request that violates several rules at once receives
    exactly one error, and the winner is determined by a fixed priority
    order" — "8. **Business safety** — brand protection ..." ranks ahead of
    "10. **Structural constraints** — uniqueness, ... and quarantined-stock
    bounds (`ERR_DUPLICATE_RESOURCE`, ..., `ERR_DISPOSITION_EXCEEDS_QUARANTINE`)."

    Design: Difficulty/priority_pair_validation_conflict/brand_protection_safety_beats_quarantine_quantity_constraint
    """
    resp, _world = _propose_secondary_overshoot()
    # units 9999 > 10 quarantined too, but safety priority 8 wins.
    error = validate_error(resp, ApiErrorId.ERR_BRAND_PROTECTION)
    assert error["error_id"] != ApiErrorId.ERR_DISPOSITION_EXCEEDS_QUARANTINE.value
