"""Difficulty queue A: compensating-action invariants — adjudication reversal
conserves money buckets; pick-then-reverse conserves lot unit count."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_order,
    create_enrollment,
    create_order,
    pick_order,
    setup_supply_pipeline,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_agent_headers"]


def _adjudicated_with_savings_card(api):
    """Adjudicated PHARMACY order for a patient with an ENROLLED savings card
    (cap 5000c). 1 unit x 8900c, copay 0.20, deductible 0."""
    ctx = setup_supply_pipeline(quantity_per_fill=1)
    create_enrollment(ctx["patient"], ctx["payer"], card_max_per_fill_cents=5000)
    order = create_order(ctx["patient"], ctx["prescription"], ctx["verification"], ctx["lot"])
    adjudicated = adjudicate_order(order)
    ctx["order"] = adjudicated
    return ctx


def test_adjudication_money_buckets_decompose_allowed_amount(api):
    """PRD §3.6: "The plan's allowed amount is the order `quantity` multiplied
    by the product's `list_price_cents`."
    PRD §3.6: "When eligible, `savings_card_paid_cents` is the smallest of
    three values: the patient's remaining responsibility after adjudication,
    the enrollment's `card_max_per_fill_cents`, and the enrollment's
    `card_remaining_cents`. The patient's `patient_paid_cents` is reduced by
    the savings-card contribution."

    1 x 8900c, copay 0.20, deductible 0: patient owes 1780; card (cap 5000,
    balance 60000) covers all 1780; patient pays 0; plan pays 7120.

    Design: Difficulty/compensating_invariant/adjudication_reversal_conserves_money_buckets
    """
    ctx = _adjudicated_with_savings_card(api)
    order = ctx["order"]
    assert order["allowed_amount_cents"] == 8900
    assert order["plan_paid_cents"] == 7120
    assert order["savings_card_paid_cents"] == 1780
    assert order["patient_paid_cents"] == 0
    assert (
        order["allowed_amount_cents"]
        == order["plan_paid_cents"]
        + order["patient_paid_cents"]
        + order["savings_card_paid_cents"]
    )


def test_reversal_zeroes_all_paid_buckets(api):
    """PRD §3.6: "On reversal, the order's `billing_status` transitions from
    `ADJUDICATED` to `REVERSED` and its `plan_paid_cents`,
    `patient_paid_cents`, and `savings_card_paid_cents` are zeroed out."

    Design: Difficulty/compensating_invariant/adjudication_reversal_conserves_money_buckets
    """
    ctx = _adjudicated_with_savings_card(api)
    reversed_order = validate_success(api.reverse_sensor_order(ctx["order"]["id"], BILLING))
    assert reversed_order["billing_status"] == "REVERSED"
    assert reversed_order["plan_paid_cents"] == 0
    assert reversed_order["patient_paid_cents"] == 0
    assert reversed_order["savings_card_paid_cents"] == 0


def test_pick_allocates_units_while_conserving_lot_count(api):
    """PRD §3.5: "On a successful pick, the platform allocates exactly
    `quantity` units from the lot, selecting by earliest `manufacture_date`
    ascending and breaking ties by `serial_number` ascending; each allocated
    unit transitions `IN_STOCK → ALLOCATED` and has its `patient_id` set to the
    order's patient."

    Lot of 3 units: before pick all 3 IN_STOCK; after picking 1, one ALLOCATED
    with patient set and two IN_STOCK — the lot still holds 3 units.

    Design: Difficulty/compensating_invariant/lot_unit_lifecycle_conserves_unit_count
    """
    ctx = setup_supply_pipeline(num_units=3, lot_quantity=3, quantity_per_fill=1)
    order = create_order(ctx["patient"], ctx["prescription"], ctx["verification"], ctx["lot"])
    adjudicate_order(order)
    pick_order(order)
    units, _meta = validate_paginated(api.list_lot_sensor_units(ctx["lot"]["id"], ADMIN))
    assert len(units) == 3
    by_status = {}
    for unit in units:
        by_status.setdefault(unit["status"], []).append(unit)
    assert len(by_status.get("ALLOCATED", [])) == 1
    assert len(by_status.get("IN_STOCK", [])) == 2
    assert by_status["ALLOCATED"][0]["patient_id"] == ctx["patient"]["id"]


def test_reverse_after_pick_restores_units_and_clears_patient(api):
    """PRD §3.6: "If the order was already `PICKED`, the allocated units revert
    from `ALLOCATED` back to `IN_STOCK` and their `patient_id` is cleared."

    Design: Difficulty/compensating_invariant/lot_unit_lifecycle_conserves_unit_count
    """
    ctx = setup_supply_pipeline(num_units=3, lot_quantity=3, quantity_per_fill=1)
    order = create_order(ctx["patient"], ctx["prescription"], ctx["verification"], ctx["lot"])
    adjudicate_order(order)
    pick_order(order)
    validate_success(api.reverse_sensor_order(order["id"], BILLING))
    units, _meta = validate_paginated(api.list_lot_sensor_units(ctx["lot"]["id"], ADMIN))
    assert len(units) == 3
    assert all(unit["status"] == "IN_STOCK" for unit in units)
    assert all(unit.get("patient_id") in (None, "") for unit in units)
