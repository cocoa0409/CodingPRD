"""The seasonal work plan's ledger: admission cap, posture bands and compensations."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_bridge_requisition,
    add_signage_requisition,
    assert_budget_invariant,
    assert_work_plan,
    create_material_order,
    plan_version,
    read_agreement,
    read_plan,
    setup_approved_plan,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _plan_with_budget(cents):
    return setup_approved_plan(
        plan_overrides={"requested_budget_cents": cents}, approved_budget_cents=cents
    )


def test_requisition_above_the_admission_cap_is_refused(api):
    """PRD 3.3: "The plan will admit a new order only while the plan's existing `committed_cents` plus its `spent_cents` plus the new order's `total_cents` remains at or below one hundred and twenty percent of `approved_budget_cents` — that is, `approved_budget_cents` multiplied by 1.20 and rounded half up to whole cents."
    PRD 3.3: "The cap is inclusive: a total that lands exactly on the cap is admitted. Anything above it is refused with `ERR_PLAN_BUDGET_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/plan_budget_cap_inclusive_at_one_hundred_twenty_percent
    """
    world = _plan_with_budget(200_000)

    response = api.create_material_order(
        {
            "work_plan_id": world["plan_id"],
            "category": "SIGNAGE",
            "lines": [{"sku": "SIGN_KIT", "unit_price_cents": 260000, "quantity": 1}],
            "expected_work_plan_version": plan_version(world["plan_id"]),
        },
        world["lead_headers"],
    )
    validate_error(response, ApiErrorId.ERR_PLAN_BUDGET_EXCEEDED.value, 422)

    plan = read_plan(world["plan_id"])
    assert plan["committed_cents"] == 0, "the refused order must commit nothing"
    assert_budget_invariant(plan)


def test_requisition_landing_exactly_on_the_admission_cap_is_admitted(api):
    """PRD 3.3: "The cap is inclusive: a total that lands exactly on the cap is admitted. Anything above it is refused with `ERR_PLAN_BUDGET_EXCEEDED`."
    PRD 3.3: "The plan's `available_cents` is `approved_budget_cents` less `committed_cents` less `spent_cents`, and it is allowed to go negative."
    PRD 3.8: "Step two selects a volume discount from that **pre-discount** figure, storing it as `discount_pct`: it is 0.00 while `line_subtotal_cents` is below 50,000 cents, 0.04 once `line_subtotal_cents` reaches 50,000 cents and while it remains below 250,000 cents, and 0.07 once `line_subtotal_cents` reaches 250,000 cents."

    Design: Difficulty/boundary_precision_check/plan_budget_cap_inclusive_at_one_hundred_twenty_percent
    """
    world = _plan_with_budget(200_000)

    order = validate_success(
        api.create_material_order(
            {
                "work_plan_id": world["plan_id"],
                "category": "SIGNAGE",
                "lines": [{"sku": "SIGN_KIT", "unit_price_cents": 249999, "quantity": 1}],
                "expected_work_plan_version": plan_version(world["plan_id"]),
            },
            world["lead_headers"],
        ),
        201,
    )
    assert order["discounted_subtotal_cents"] == 239999
    assert order["total_cents"] == 239999, "exactly the 240000-cent cap is not exceeded"

    plan = read_plan(world["plan_id"])
    assert_work_plan(plan)
    assert plan["committed_cents"] == 239999
    assert plan["available_cents"] == -39999
    assert plan["budget_posture"] == "OVER_COMMITTED"


def test_budget_posture_is_healthy_exactly_at_the_twenty_percent_floor(api):
    """PRD 3.3: "From `available_cents` the server derives `budget_posture` in four bands: it is `OVER_COMMITTED` when `available_cents` is below 0; `EXHAUSTED` when `available_cents` is exactly 0; `TIGHT` when `available_cents` is above 0 but strictly below a floor equal to one fifth of `approved_budget_cents` — that is, `approved_budget_cents` multiplied by 0.20 and rounded half up to whole cents; and `HEALTHY` in every remaining case."
    PRD 3.8: "Step four sets `freight_cents`. Freight is waived entirely — 0 cents — once `discounted_subtotal_cents` reaches 200,000 cents."

    Design: Corner/calculations/budget_posture_healthy_exactly_at_the_twenty_percent_floor
    """
    world = _plan_with_budget(250_000)

    first = create_material_order(
        world["plan_id"],
        world["lead_id"],
        category="SIGNAGE",
        lines=[{"sku": "SIGN_BUNDLE", "unit_price_cents": 208333, "quantity": 1}],
    )
    assert first["discounted_subtotal_cents"] == 200000
    assert first["total_cents"] == 200000

    plan = read_plan(world["plan_id"])
    assert plan["available_cents"] == 50000
    assert plan["budget_posture"] == "HEALTHY", "50000 is not strictly below the floor"

    second = create_material_order(
        world["plan_id"],
        world["lead_id"],
        category="TOOLS",
        lines=[{"sku": "PULASKI", "unit_price_cents": 1, "quantity": 1}],
    )
    assert second["total_cents"] == 4501

    plan = read_plan(world["plan_id"])
    assert plan["committed_cents"] == 204501
    assert plan["available_cents"] == 45499
    assert plan["budget_posture"] == "TIGHT"


def test_cancelling_a_requisition_restores_the_budget_identity_with_zero_drift(api):
    """PRD 2.9: "The **budget invariant** governs a work plan's ledger: `approved_budget_cents` always equals `committed_cents` plus `spent_cents` plus `available_cents`, after every material-order creation, cancellation and receipt."
    PRD 3.8: "The plan's `committed_cents` drops by `total_cents` and `available_cents` and `budget_posture` are recomputed so that the budget invariant is restored, with the plan's `version` advancing by 1."

    Design: Difficulty/compensating_invariant/material_order_cancel_restores_budget_identity_with_zero_drift
    """
    world = setup_approved_plan()
    add_signage_requisition(world)

    before = read_plan(world["plan_id"])
    assert before["committed_cents"] == 205236
    assert before["available_cents"] == 44764
    assert before["budget_posture"] == "TIGHT"
    assert_budget_invariant(before)

    bridge = add_bridge_requisition(world)
    assert bridge["total_cents"] == 47700

    middle = read_plan(world["plan_id"])
    assert middle["committed_cents"] == 252936
    assert middle["available_cents"] == -2936
    assert middle["budget_posture"] == "OVER_COMMITTED"
    assert_budget_invariant(middle)

    cancelled = validate_success(
        api.cancel_material_order(
            bridge["id"], {"reason": "Bridge deferred to next season."}, world["lead_headers"]
        )
    )
    assert cancelled["status"] == "CANCELLED"

    after = read_plan(world["plan_id"])
    assert after["committed_cents"] == 205236
    assert after["spent_cents"] == 0
    assert after["available_cents"] == 44764
    assert after["budget_posture"] == "TIGHT"
    assert after["committed_cents"] == before["committed_cents"]
    assert_budget_invariant(after)


def test_cancelling_the_over_committing_requisition_reactivates_the_adoption(api):
    """PRD 3.8: "If that recomputation carries `budget_posture` out of `OVER_COMMITTED`, the parent adoption carrying `suspension_reason` `BUDGET_OVER_COMMIT` returns from `SUSPENDED` to `ACTIVE`, and every work party under that agreement's plans sitting in `schedule_status` `SUSPENDED` with `block_reason` `AGREEMENT_SUSPENDED` returns to `CONFIRMED` with `readiness_status` set to `BRIEFED`."
    PRD 3.2: "When a work plan's `budget_posture` becomes `OVER_COMMITTED`, or when the segment's posture becomes `INCIDENT_CLOSED`, the agreement moves `ACTIVE → SUSPENDED` and `suspension_reason` is set to `BUDGET_OVER_COMMIT` or `SEGMENT_INCIDENT` accordingly."

    Design: Difficulty/compensating_invariant/material_order_cancel_restores_budget_identity_with_zero_drift
    """
    world = setup_approved_plan()
    add_signage_requisition(world)
    bridge = add_bridge_requisition(world)

    suspended = read_agreement(world["agreement_id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "BUDGET_OVER_COMMIT"

    validate_success(
        api.cancel_material_order(
            bridge["id"], {"reason": "Bridge deferred to next season."}, world["lead_headers"]
        )
    )

    recovered = read_agreement(world["agreement_id"])
    assert recovered["status"] == "ACTIVE"
    assert recovered["suspension_reason"] is None


def test_stale_work_plan_version_rejects_a_second_requisition(api):
    """PRD 2.8: "Creating a material order requires a non-optional `expected_work_plan_version` field carrying the client's last observed `version` of the target work plan."
    PRD 2.8: "If it does not equal the work plan's current `version`, the creation is rejected with `ERR_STALE_WORK_PLAN_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/stale_work_plan_version_rejects_material_order_creation
    """
    world = setup_approved_plan()
    observed_version = plan_version(world["plan_id"])

    first = create_material_order(
        world["plan_id"],
        world["lead_id"],
        expected_version=observed_version,
        category="TOOLS",
        lines=[{"sku": "PULASKI", "unit_price_cents": 1, "quantity": 1}],
    )
    assert first["total_cents"] == 4501

    stale = api.create_material_order(
        {
            "work_plan_id": world["plan_id"],
            "category": "TOOLS",
            "lines": [{"sku": "MCLEOD", "unit_price_cents": 2, "quantity": 1}],
            "expected_work_plan_version": observed_version,
        },
        world["lead_headers"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_WORK_PLAN_VERSION.value, 412)
    assert read_plan(world["plan_id"])["committed_cents"] == 4501

    retry = create_material_order(
        world["plan_id"],
        world["lead_id"],
        category="TOOLS",
        lines=[{"sku": "MCLEOD", "unit_price_cents": 2, "quantity": 1}],
    )
    assert retry["total_cents"] == 4502

    plan = read_plan(world["plan_id"])
    assert plan["committed_cents"] == 9003
    assert plan["available_cents"] == 240997
