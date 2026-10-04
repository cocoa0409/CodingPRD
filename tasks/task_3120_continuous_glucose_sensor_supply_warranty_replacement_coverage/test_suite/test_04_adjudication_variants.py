"""Difficulty queue A: dual-variant benefit adjudication (PHARMACY vs DME)
and the refill-cadence threshold formula."""
import math

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_order,
    create_approved_verification,
    create_lot,
    create_order,
    create_patient,
    create_payer,
    create_prescriber,
    create_prescription,
    create_product,
    create_units,
    set_clock,
    setup_supply_pipeline,
    validate_error,
    validate_success,
)

BILLING = TEST_USERS["billing_agent_headers"]
FULFILL = TEST_USERS["fulfillment_agent_headers"]


def _dual_route_setup():
    """Two identical patients/prescriptions/orders against a PHARMACY payer and
    a DME payer, sharing one product and lot."""
    set_clock()
    product = create_product(generation=3, wear_days=14, list_price_cents=8900)
    lot = create_lot(product, quantity_manufactured=20)
    create_units(lot, 4)
    prescriber = create_prescriber()
    payer_pharm = create_payer(
        benefit_route="PHARMACY", pharmacy_copay_pct=0.20,
        dme_coinsurance_pct=0.0, deductible_cap_cents=50000,
    )
    payer_dme = create_payer(
        benefit_route="DME", pharmacy_copay_pct=0.0,
        dme_coinsurance_pct=0.10, deductible_cap_cents=50000,
    )
    orders = {}
    for key, payer in (("pharm", payer_pharm), ("dme", payer_dme)):
        patient = create_patient()
        rx = create_prescription(
            patient, prescriber, product, quantity_per_fill=2, fills_authorized=12
        )
        cv = create_approved_verification(rx, payer)
        order = create_order(patient, rx, cv, lot)
        orders[key] = order
    return orders


def test_adjudication_pharmacy_route_deductible_absorbs_allowed_amount(api):
    """PRD §3.6: "The plan's allowed amount is the order `quantity` multiplied
    by the product's `list_price_cents`."
    PRD §3.6: "Under the `PHARMACY` variant, the patient's plan-year deductible
    accumulator starts at zero for this benchmark (single-order scope assumed).
    The remaining deductible is the payer's `deductible_cap_cents` less what the
    patient has already used this plan year, floored at zero. The deductible
    actually applied is the lesser of the allowed amount and that remaining
    deductible. The coinsurance base is the allowed amount less the deductible
    applied."
    PRD §3.6: "The `patient_paid_cents` is the deductible applied plus that
    summed coinsurance, and the `plan_paid_cents` is the allowed amount less
    the patient portion."

    Design: Difficulty/dual_variant_calc/adjudication_pharmacy_vs_dme_route_diverges
    """
    orders = _dual_route_setup()
    pharm = orders["pharm"]
    adjudicated = validate_success(
        api.adjudicate_sensor_order(
            pharm["id"], {"expected_order_version": pharm["version"]}, BILLING
        )
    )
    assert adjudicated["allowed_amount_cents"] == 17800
    # deductible cap 50000 fully absorbs 17800 -> coinsurance base is 0
    assert adjudicated["patient_paid_cents"] == 17800
    assert adjudicated["plan_paid_cents"] == 0


def test_adjudication_dme_route_bypasses_deductible_and_diverges(api):
    """PRD §3.6: "Under the `DME` variant, the deductible is bypassed entirely:
    no deductible is applied, and each unit contributes the floor of
    (`list_price_cents` multiplied by the payer's `dme_coinsurance_pct`) toward
    patient responsibility, summed across the order. The `patient_paid_cents`
    equals that summed coinsurance and `plan_paid_cents` is the remainder of
    the allowed amount."
    PRD §2.8: "the percentage is a real fraction between 0 and 1 and the
    resulting cents value is **floored per line** before summing across lines"

    Design: Difficulty/dual_variant_calc/adjudication_pharmacy_vs_dme_route_diverges
    """
    orders = _dual_route_setup()
    pharm = validate_success(
        api.adjudicate_sensor_order(
            orders["pharm"]["id"],
            {"expected_order_version": orders["pharm"]["version"]},
            BILLING,
        )
    )
    dme = validate_success(
        api.adjudicate_sensor_order(
            orders["dme"]["id"],
            {"expected_order_version": orders["dme"]["version"]},
            BILLING,
        )
    )
    assert dme["allowed_amount_cents"] == 17800
    # per-line floor: 2 * floor(8900 * 0.10) = 2 * 890
    assert dme["patient_paid_cents"] == 1780
    assert dme["plan_paid_cents"] == 16020
    assert pharm["patient_paid_cents"] != dme["patient_paid_cents"]


def test_refill_cadence_rejects_order_one_day_before_earliest_refill(api):
    """PRD §3.5: "When a prior order exists, the server computes the supply
    duration in days by multiplying the prescription's `quantity_per_fill` by
    the product's `wear_days`, then takes three quarters of that supply
    duration — that is, the supply duration multiplied by (1 − 0.25) — and
    rounds the result up to the next whole day. The `earliest_refill_date` on
    the new order is the prior order's `fill_date` plus that many days. The
    refill is permitted when the logical date is on or after
    `earliest_refill_date`; the rejection boundary is exactly one day before
    it. Attempting to create the order earlier yields `ERR_REFILL_TOO_EARLY`."

    supply = 3 * 14 = 42; ceil(42 * 0.75) = 32; first fill 2026-09-01, so the
    earliest refill date is 2026-10-03 and 2026-10-02 must be rejected.

    Design: Difficulty/combinatorial_formula/refill_cadence_mode_a_threshold_formula
    """
    ctx = setup_supply_pipeline(quantity_per_fill=3, lot_quantity=30)
    first = create_order(ctx["patient"], ctx["prescription"], ctx["verification"], ctx["lot"])
    adjudicate_order(first)
    assert first["fill_date"] == "2026-09-01"
    set_clock("2026-10-02T00:00:00Z")
    resp = api.create_sensor_order(
        ctx["patient"]["id"],
        {
            "prescription_id": ctx["prescription"]["id"],
            "coverage_verification_id": ctx["verification"]["id"],
            "lot_id": ctx["lot"]["id"],
            "quantity": 3,
        },
        FULFILL,
    )
    validate_error(resp, ApiErrorId.ERR_REFILL_TOO_EARLY, expected_status=409)


def test_refill_cadence_earliest_refill_date_stamped_from_prior_fill(api):
    """PRD §3.5: "When a prior order exists, the server computes the supply
    duration in days by multiplying the prescription's `quantity_per_fill` by
    the product's `wear_days`, then takes three quarters of that supply
    duration — that is, the supply duration multiplied by (1 − 0.25) — and
    rounds the result up to the next whole day. The `earliest_refill_date` on
    the new order is the prior order's `fill_date` plus that many days."
    PRD §3.5: "The new order is created with `fill_date` set to the current
    logical date, `fulfillment_status` of `PENDING_PICK`, `billing_status` of
    `UNBILLED`, the computed `earliest_refill_date` stamped on the order itself
    for downstream reference, and zeroed `plan_paid_cents`,
    `patient_paid_cents`, and `savings_card_paid_cents` pending adjudication."

    supply = 3 * 14 = 42; ceil(42 * 0.75) = 32; prior fill 2026-09-01 stamps
    earliest_refill_date == 2026-10-03 on the new order.

    Design: Difficulty/combinatorial_formula/refill_cadence_mode_a_threshold_formula
    """
    ctx = setup_supply_pipeline(quantity_per_fill=3, lot_quantity=30)
    first = create_order(ctx["patient"], ctx["prescription"], ctx["verification"], ctx["lot"])
    adjudicate_order(first)
    set_clock("2026-10-03T00:00:00Z")
    order = validate_success(
        api.create_sensor_order(
            ctx["patient"]["id"],
            {
                "prescription_id": ctx["prescription"]["id"],
                "coverage_verification_id": ctx["verification"]["id"],
                "lot_id": ctx["lot"]["id"],
                "quantity": 3,
            },
            FULFILL,
        ),
        expected_status=201,
    )
    assert order["fill_date"] == "2026-10-03"
    assert order["earliest_refill_date"] == "2026-10-03"
    assert order["fulfillment_status"] == "PENDING_PICK"
    assert order["billing_status"] == "UNBILLED"
    assert order["plan_paid_cents"] == 0
    assert order["patient_paid_cents"] == 0
    assert order["savings_card_paid_cents"] == 0


def test_per_line_rounding_patient_paid_uses_floor_per_line(api):
    """PRD §2.8: "the percentage is a real fraction between 0 and 1 and the
    resulting cents value is **floored per line** before summing across lines:
    each sensor unit in the order contributes its own floored line amount, and
    those per-line amounts are then summed to the order total. Summing first
    and then rounding is not equivalent and is not permitted."

    list_price 8999c, qty 3, copay 0.33, deductible 0:
    per-line = 3 * floor(8999 * 0.33) = 3 * 2969 = 8907;
    sum-then-floor would be floor(26997 * 0.33) = 8909 — not permitted.

    Design: Difficulty/combinatorial_formula/per_line_rounding_vs_sum_then_round_mode_b
    """
    ctx = setup_supply_pipeline(
        quantity_per_fill=3,
        product_overrides={"list_price_cents": 8999},
        payer_overrides={"pharmacy_copay_pct": 0.33, "deductible_cap_cents": 0},
    )
    order = create_order(ctx["patient"], ctx["prescription"], ctx["verification"], ctx["lot"])
    adjudicated = validate_success(
        api.adjudicate_sensor_order(
            order["id"], {"expected_order_version": order["version"]}, BILLING
        )
    )
    assert adjudicated["allowed_amount_cents"] == 26997
    assert adjudicated["patient_paid_cents"] == 3 * math.floor(8999 * 0.33) == 8907
    assert adjudicated["patient_paid_cents"] != math.floor(26997 * 0.33)


def test_per_line_rounding_plan_paid_is_remainder(api):
    """PRD §3.6: "The `patient_paid_cents` is the deductible applied plus that
    summed coinsurance, and the `plan_paid_cents` is the allowed amount less
    the patient portion."

    list_price 8999c, qty 3, copay 0.33, deductible 0:
    plan_paid = 26997 - 8907 = 18090.

    Design: Difficulty/combinatorial_formula/per_line_rounding_vs_sum_then_round_mode_b
    """
    ctx = setup_supply_pipeline(
        quantity_per_fill=3,
        product_overrides={"list_price_cents": 8999},
        payer_overrides={"pharmacy_copay_pct": 0.33, "deductible_cap_cents": 0},
    )
    order = create_order(ctx["patient"], ctx["prescription"], ctx["verification"], ctx["lot"])
    adjudicated = validate_success(
        api.adjudicate_sensor_order(
            order["id"], {"expected_order_version": order["version"]}, BILLING
        )
    )
    assert adjudicated["plan_paid_cents"] == 18090
    assert (
        adjudicated["allowed_amount_cents"]
        == adjudicated["plan_paid_cents"]
        + adjudicated["patient_paid_cents"]
        + adjudicated["savings_card_paid_cents"]
    )
