"""Boundary precision on the expansion gate and the refill budget."""
from test_helpers import (
    create_order_payload,
    list_payload,
    get_success_data,
    validate_success,
    create_manufacturer,
    create_drug,
    create_sourced_price,
    create_patient,
    create_prescriber,
    create_prescription,
    create_pharmacy,
    create_license_pending,
    verify_license,
    submit_intake,
    review_intake,
    accept_intake,
    add_accepted_demand,
    pay_order,
    fulfill_order,
    ship_order,
    deliver_order,
    reset_clock,
    OPS,
    PHARMACIST,

)


class TestExpansionGateBoundary:

    def test_supply_one_unit_below_twice_demand_admits_at_score_two(self, api):
        """PRD §3.3: "Otherwise, when supply_units is less than twice
        demand_units_30d, the score is 2 — supply covers demand but with less
        than double the headroom, and since the gate requires a score of at
        least 2, this admitted band means a drug with tight supply still
        passes."

        Design: Difficulty/boundary_precision_check/formulary_gate_band_upper_edge_supply_exactly_twice_demand_admits
        """
        reset_clock()
        drug, _price_row, _rx, _rq = setup_gate_drug(demand=250, supply=499)
        scored = validate_success(api.expansion_score(drug["id"], OPS))
        assert scored["demand_units_30d"] == 250
        assert scored["supply_units"] == 499
        assert scored["expansion_score"] == 2, (
            "499 is less than twice the demand of 250, so the tight-supply "
            "band scores 2"
        )
        admitted = validate_success(api.expand_formulary(drug["id"], OPS))
        assert admitted["state"] == "FORMULARY"


class TestRefillBudgetZero:

    def test_first_delivery_exhausts_a_zero_refill_budget(self, api):
        """PRD §3.8: "when refills_consumed now reaches
        total_refills_authorized, the prescription's own exhausted-budget
        transition fires in the same operation, moving the prescription from
        ACTIVE to DEPLETED"

        Design: Difficulty/boundary_precision_check/refill_budget_zero_exhausted_on_first_delivery_then_authorization_denied
        """
        reset_clock()
        ctx = zero_budget_stack(api)
        order = drive_to_shipped(api, ctx)
        deliver_order(order["id"])

        rx_after = get_success_data(api.get_prescription(ctx["prescription"]["id"], OPS))
        assert rx_after["refills_consumed"] == 1
        assert rx_after["total_refills_authorized"] == 0
        assert rx_after["status"] == "DEPLETED", (
            "a single delivery already reaches the zero refill budget, so the "
            "exhausted-budget transition fires"
        )

    def test_authorisation_on_a_zero_budget_is_denied_refills_exhausted(self, api):
        """PRD §3.4: "Authorising a refill requires the claim to be PENDING, the
        prescription to be ACTIVE, the prescription's refills_consumed to be
        strictly below total_refills_authorized"
        PRD §3.4: "Refusal because the refill budget is exhausted is the fourth
        blocking condition and carries the denial_reason_code
        REFILLS_EXHAUSTED. Each denial stamps denied_at with the logical clock,
        sets the matching denial_reason_code, and resets reserved_quantity to
        zero."

        Design: Difficulty/boundary_precision_check/refill_budget_zero_exhausted_on_first_delivery_then_authorization_denied
        """
        reset_clock()
        ctx = zero_budget_stack(api)
        # No delivery yet: the claim is PENDING and the prescription is ACTIVE,
        # but refills_consumed (0) is already at total_refills_authorized (0).
        claim = ctx["claim"]
        assert claim["status"] == "PENDING"
        response = api.authorize_refill(claim["id"], 30, PHARMACIST)
        body = validate_success(response, 200)

        assert body["status"] == "DENIED", (
            "the authorisation is refused as a denial outcome, not as an error"
        )
        assert body["denial_reason_code"] == "REFILLS_EXHAUSTED"
        assert body["reserved_quantity"] == 0
        assert body["denied_at"] is not None


# ─── local helpers ────────────────────────────────────

def setup_gate_drug(demand, supply):
    """A drug with exactly `demand` units of trailing demand and one sourced row
    of exactly `supply` available units."""
    manufacturer = create_manufacturer()
    drug = create_drug()
    price_row = create_sourced_price(drug["id"], manufacturer["id"],
                                     unit_cost_cents=12, available_units=supply,
                                     reliability_tier="C",
                                     packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    prescriptions, requests = add_accepted_demand(
        drug["id"], patient["id"], prescriber["id"], demand
    )
    return drug, price_row, prescriptions, requests


def zero_budget_stack(api):
    """Formulary drug, prescription with total_refills_authorized 0, its first
    PENDING claim, and a CREATED order."""
    manufacturer = create_manufacturer()
    drug = create_drug()
    create_sourced_price(drug["id"], manufacturer["id"], unit_cost_cents=12,
                         available_units=600, reliability_tier="A",
                         packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             total_refills_authorized=0)
    rq = submit_intake(rx["id"], packaged_quantity=100)
    review_intake(rq["id"])
    _rq, claim = accept_intake(rq["id"])
    drug = get_success_data(api.expand_formulary(drug["id"], OPS))
    pharmacy = create_pharmacy()
    licence = create_license_pending(pharmacy["id"], state_code="CA")
    verify_license(pharmacy["id"], licence["id"])
    prices = list_payload(api.list_drug_prices_of_drug(drug["id"], OPS))
    order = get_success_data(api.create_order(create_order_payload(
        rx["id"], rq["id"], pharmacy["id"], prices[0]["id"], quantity=30), OPS))
    return {
        "drug": drug,
        "pharmacy": pharmacy,
        "order": order,
        "claim": claim,
        "prescription": get_success_data(api.get_prescription(rx["id"], OPS)),
        "request": rq,
    }


def drive_to_shipped(api, ctx):
    order = pay_order(ctx["order"]["id"])
    order = fulfill_order(order["id"])
    return ship_order(order["id"])