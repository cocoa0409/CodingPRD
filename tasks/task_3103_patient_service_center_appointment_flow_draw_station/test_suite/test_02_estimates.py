"""Responsibility estimates: variants, rounding order, and the comparison reference."""
import pytest

from test_helpers import (
    validate_success, assert_estimate_invariants, api_client, INTAKE,
    TEST_USERS, create_estimate_payload,
)
from test_helpers.fixtures import (
    setup_eligible_order, setup_center_and_plan, new_patient, new_order,
    resolve_insurance, get_order, get_appointment, book, check_in, call_patient,
    set_clock,
)
from test_helpers import make_phlebotomist_headers, make_patient_headers


def test_attended_collected_estimate_grosses_and_discounts_the_eligible_order(api):
    """PRD §3.5: "The copay component is the plan's `copay_cents`; against the
    reference plan, whose copay is 2500 cents, it is 2500."
    PRD §3.5: "The discount is then the sum of twenty percent of that gross plus
    the expiry fee, rounded half up, where the twenty percent is
    `attended_collected` (0.20)."
    PRD §3.5: "Against the reference fixture — copay 2500, coinsurance 0.25,
    allowed 10000 — the ratio of the self-pay figure to the attended figure is
    exactly 1.25, being 5000 against 4000, a discount of 1000."

    Design: Difficulty/dual_variant_calc/estimate_dual_variant_on_test_order
    """
    data = setup_eligible_order()
    order = data["order"]
    estimate = validate_success(api.create_estimate(
        order["id"],
        create_estimate_payload("ATTENDED_COLLECTED", order["version"]),
        INTAKE), 201)

    assert estimate["variant"] == "ATTENDED_COLLECTED"
    assert estimate["gross_cents"] == 5000
    assert estimate["discount_cents"] == 1000
    assert estimate["net_patient_cents"] == 4000
    assert estimate["copay_component_cents"] == 2500
    assert estimate["coinsurance_component_cents"] == 2500
    assert estimate["deductible_component_cents"] == 0
    assert_estimate_invariants(estimate)

    # The self-pay figure for the same order stays the full list price.
    assert estimate["gross_cents"] != 4000
    read_back = validate_success(
        api_client.get_estimate(estimate["id"], INTAKE), 200)
    assert read_back["net_patient_cents"] == 4000


def test_provisional_variant_files_zero_patient_responsibility(api):
    """PRD §3.5: "`PROVISIONAL_ELIGIBLE` is the variant filed to the payer
    rather than the patient. All three figures are zero."
    PRD §3.5: "The variant is selected before any amount is computed, and the
    amounts are computed before the discount is applied; no other evaluation
    order is valid."

    Design: Corner/calculations/provisional_variant_selects_zero_patient_responsibility_for_a_collected_eligible_order
    """
    data = setup_eligible_order()
    order = data["order"]
    estimate = validate_success(api.create_estimate(
        order["id"],
        create_estimate_payload("PROVISIONAL_ELIGIBLE", order["version"]),
        INTAKE), 201)

    assert estimate["variant"] == "PROVISIONAL_ELIGIBLE"
    assert estimate["gross_cents"] == 0
    assert estimate["discount_cents"] == 0
    assert estimate["net_patient_cents"] == 0

    order_after = get_order(order["id"])
    assert order_after["patient_responsibility_cents"] == 0
    # The rate is stored independently of the variant, so it is still published.
    assert order_after["self_pay_rate_cents"] == 5000


def test_per_component_rounding_order_pins_the_estimate_one_cent_higher(api):
    """PRD §2.12: "Rounding is applied to each component of a sum before the
    components are added, not once after."
    PRD §3.5: "with an allowed amount of 10000, a coinsurance fraction of 0.25,
    a `prior_paid_pct` of 0.125, and a non-binding deductible, the coinsurance
    term is 2187.5 and the deductible term is 6562.5, so rounding each first
    yields 11251 while rounding the unrounded sum once would yield 11250 — and
    11251 is the contract."

    Design: Difficulty/combinatorial_formula/estimate_nested_rounding_order_pins_one_cent
    """
    set_clock("2026-09-01T13:00:00Z")
    center = api_client.create_service_center({
        "name": "Aurora Draw Station", "state_code": "TX",
        "timezone_offset_minutes": -300, "station_count": 2,
        "open_local_minutes": 480, "close_local_minutes": 1020,
    }, TEST_USERS["supervisor_headers"]).json()["data"]
    plan = validate_success(api_client.create_insurance_plan({
        "payer_name": "HALF CENT HMO", "plan_type": "HMO", "copay_cents": 2500,
        "coinsurance_pct": 0.25, "deductible_remaining_cents": 20000,
        "allowed_amount_cents": 10000, "prior_paid_pct": 0.125,
    }, INTAKE), 201)

    patient = new_patient()
    order = new_order(center["id"], patient["id"], plan["id"])
    order = resolve_insurance(order["id"])

    estimate = validate_success(api.create_estimate(
        order["id"],
        create_estimate_payload("ATTENDED_COLLECTED", order["version"]),
        INTAKE), 201)

    assert estimate["copay_component_cents"] == 2500
    assert estimate["coinsurance_component_cents"] == 2188
    assert estimate["deductible_component_cents"] == 6563
    assert estimate["gross_cents"] == 11251, (
        "per-component rounding must produce 11251, not the sum-then-round 11250"
    )
    assert estimate["gross_cents"] != 11250
    assert estimate["net_patient_cents"] == 9001


def test_weighted_blend_reference_sums_exactly_without_a_final_round_call(api):
    """PRD §3.5: "It is the exact sum of four parts: the plan's `copay_cents`;
    the allowed amount multiplied by `coinsurance_pct` and by one minus
    `prior_paid_pct`; the smaller of `deductible_remaining_cents` and the product
    of the allowed amount minus the copay and one minus `prior_paid_pct`; and the
    order's `list_price_cents`."
    PRD §3.5: "Against the reference plan, with a copay of 2500, an allowed
    amount of 10000, a coinsurance fraction of 0.25 against a non-binding
    deductible, and a panel list price of 5000, the exact sum is 10000."

    Design: Corner/calculations/weighted_blend_sums_exactly_without_a_final_rounding_call
    """
    set_clock("2026-09-01T13:00:00Z")
    center = api_client.create_service_center({
        "name": "Aurora Draw Station", "state_code": "TX",
        "timezone_offset_minutes": -300, "station_count": 2,
        "open_local_minutes": 480, "close_local_minutes": 1020,
    }, TEST_USERS["supervisor_headers"]).json()["data"]
    plan = validate_success(api_client.create_insurance_plan({
        "payer_name": "HORIZON HMO", "plan_type": "HMO", "copay_cents": 2500,
        "coinsurance_pct": 0.25, "deductible_remaining_cents": 0,
        "allowed_amount_cents": 10000, "prior_paid_pct": 0.0,
    }, INTAKE), 201)

    patient = new_patient()
    order = new_order(center["id"], patient["id"], plan["id"])
    order = resolve_insurance(order["id"])
    assert order["est_copay_cents"] == 2500
    assert order["est_coinsurance_cents"] == 2500

    estimate = validate_success(api.create_estimate(
        order["id"],
        create_estimate_payload("ATTENDED_COLLECTED", order["version"]),
        INTAKE), 201)

    # 2500 + 2500 + 0 + 5000 = 10000 exactly, with no residue and no final round.
    blend = (plan["copay_cents"]
             + plan["allowed_amount_cents"] * plan["coinsurance_pct"] * (1 - plan["prior_paid_pct"])
             + min(plan["deductible_remaining_cents"],
                   max(0, plan["allowed_amount_cents"] - plan["copay_cents"]) * (1 - plan["prior_paid_pct"]))
             + order["list_price_cents"])
    assert blend == 10000
    assert estimate["gross_cents"] == 5000
    assert estimate["net_patient_cents"] == 4000
    assert estimate["deductible_component_cents"] == 0


def test_estimate_supersession_chain_is_discoverable_from_the_predecessor(api):
    """PRD §3.5: "Estimates form a revision chain: a new estimate may point at
    the estimate it displaces through `supersedes_estimate_id`, which is null on
    the first estimate for an order."
    PRD §3.5: "An order may hold at most one estimate per variant — a repeat of a
    variant already collected is a state rejection, not a stale-version
    rejection."

    Design: Corner/consistency_model/estimate_revision_supersession_chain_is_queryable
    """
    data = setup_eligible_order()
    order = data["order"]

    first = validate_success(api.create_estimate(
        order["id"], create_estimate_payload("SELF_PAY_LIST", order["version"]),
        INTAKE), 201)
    order_after_first = get_order(order["id"])

    second = validate_success(api.create_estimate(
        order["id"],
        create_estimate_payload("ATTENDED_COLLECTED", order_after_first["version"],
                                supersedes_estimate_id=first["id"]),
        INTAKE), 201)

    assert second["id"] != first["id"]
    assert second["variant"] == "ATTENDED_COLLECTED"
    assert second["supersedes_estimate_id"] == first["id"]

    successors = api_client.list_estimates(
        INTAKE, params={"supersedes_estimate_id": first["id"]})
    body = successors.json()
    assert body["response_type"] == "array"
    assert body["data"][0]["id"] == second["id"]

    listed = api_client.list_order_estimates(order["id"], INTAKE).json()["data"]
    assert len(listed) == 2
    variants = {row["id"]: row["variant"] for row in listed}
    assert variants[first["id"]] == "SELF_PAY_LIST"