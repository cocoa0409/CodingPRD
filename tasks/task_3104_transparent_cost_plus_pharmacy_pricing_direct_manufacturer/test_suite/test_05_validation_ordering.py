"""Which check surfaces when two apply to the same request."""
from test_helpers import (
    PHARMACIST,
    create_order_payload,
    list_payload,
    get_success_data,
    validate_error,
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
    pay_order,
    fulfill_order,
    reset_clock,
    OPS,
)


class TestStateBeforeBusinessSafety:

    def test_backward_intake_on_an_active_controlled_drug_prescription(self, api):
        """PRD §2.12: "State validation — whether the resource is in a state
        that admits the requested transition, with every transition attempted
        from a terminal state rejected — comes next. The business gates then
        follow"
        PRD §5: "ERR_INVALID_STATE | 409"

        Design: Difficulty/priority_pair_validation_conflict/state_before_business_safety_controlled_drug_intake
        """
        reset_clock()
        rx = active_controlled_prescription(api)

        current = get_success_data(api.get_prescription(rx["id"], OPS))
        assert current["status"] == "ACTIVE"

        second = api.create_intake_request(rx["id"], 30, OPS)
        validate_error(second, "ERR_INVALID_STATE")

    def test_rejected_call_leaves_the_prescription_and_requests_untouched(self, api):
        """PRD §2.12: "a request that fails more than one check must surface the
        check that comes first."
        PRD §2.1: "A request whose role is declared but not permitted for the
        operation being attempted is refused with ERR_ROLE_NOT_PERMITTED and
        HTTP 403."

        Design: Difficulty/priority_pair_validation_conflict/state_before_business_safety_controlled_drug_intake
        """
        reset_clock()
        rx = active_controlled_prescription(api)
        before = get_success_data(api.get_prescription(rx["id"], OPS))

        api.create_intake_request(rx["id"], 30, OPS)

        after = get_success_data(api.get_prescription(rx["id"], OPS))
        assert after["status"] == "ACTIVE", "the refused call changed nothing"
        requests = list_payload(
            api.list_intake_requests_of_prescription(rx["id"], OPS))
        assert len(requests) == 1, "no additional intake request was created"
        assert after["version"] == before["version"]


class TestDispatchRequiresLicenceCoverage:

    def test_dispatch_is_refused_when_the_destination_state_is_uncovered(self, api):
        """PRD §3.7: "The order's ship_state_code must be covered by a
        PharmacyLicense held by that pharmacy with status ACTIVE and matching
        state_code; a missing, expired, revoked or superseded licence — or a
        pharmacy whose shipping_enabled flag is false — refuses the dispatch
        with ERR_NOT_LICENSED_IN_STATE and HTTP 422."
        PRD §5: "ERR_NOT_LICENSED_IN_STATE | 422"

        Design: Difficulty/priority_pair_validation_conflict/business_safety_before_business_temporal_no_licence_then_interval
        """
        reset_clock()
        ctx = prepare_fulfilling_order(api, interval_tier="B", licence_state="TX")
        response = api.ship_order(ctx["order"]["id"], OPS)
        validate_error(response, "ERR_NOT_LICENSED_IN_STATE")

# ─── local helpers ────────────────────────────────────

def active_controlled_prescription(api):
    """An ACTIVE prescription whose drug is a controlled substance.

    A controlled drug cannot enter intake at all (PRD §3.4), so the intake is
    routed and accepted against a non-controlled sibling and the prescription is
    then substituted onto the controlled drug — substitution carries no
    controlled-substance gate. The prescription ends ACTIVE on the controlled
    drug, which is exactly the state the "state precedes the business gate"
    precedence needs.
    """
    manufacturer = create_manufacturer("Bexley Generics")
    clean_drug = create_drug()
    controlled = create_drug(drug_name="Zolpidem", strength="10MG",
                             is_controlled=True, retail_reference_price_cents=5000,
                             insured_reference_price_cents=4500)
    create_sourced_price(clean_drug["id"], manufacturer["id"],
                         unit_cost_cents=30, available_units=400,
                         reliability_tier="A", packaging="100-count bottle")
    create_sourced_price(controlled["id"], manufacturer["id"],
                         unit_cost_cents=30, available_units=400,
                         reliability_tier="A", packaging="100-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    rx = create_prescription(patient["id"], prescriber["id"], clean_drug["id"],
                             total_refills_authorized=1)
    rq = submit_intake(rx["id"], packaged_quantity=30)
    review_intake(rq["id"])
    accept_intake(rq["id"])
    get_success_data(api.substitute_prescription(
        rx["id"],
        {"new_drug_id": controlled["id"], "reason_code": "SHORTAGE_SUBSTITUTION"},
        PHARMACIST,
    ))
    return rx

def prepare_fulfilling_order(api, interval_tier="B", licence_state="TX"):
    """An order on a licensed pharmacy driven to FULFILLING (shipment PENDING)
    while the destination state is not covered."""
    manufacturer = create_manufacturer("Bexley Generics")
    drug = create_drug()
    create_sourced_price(drug["id"], manufacturer["id"], unit_cost_cents=12,
                         available_units=600, reliability_tier=interval_tier,
                         packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             total_refills_authorized=1, ship_state_code="CA")
    rq = submit_intake(rx["id"], packaged_quantity=100)
    review_intake(rq["id"])
    accept_intake(rq["id"])
    drug = get_success_data(api.expand_formulary(drug["id"], OPS))
    pharmacy = create_pharmacy()
    licence = create_license_pending(pharmacy["id"], state_code=licence_state,
                                     license_number=f"{licence_state}-MP-2201")
    verify_license(pharmacy["id"], licence["id"])
    price_rows = list_payload(api.list_drug_prices_of_drug(drug["id"], OPS))
    order = get_success_data(api.create_order(create_order_payload(
        rx["id"], rq["id"], pharmacy["id"], price_rows[0]["id"], quantity=30), OPS))
    order = pay_order(order["id"])
    # The shipment interval is measured from paid_at, so the clock must move past
    # the tier-B boundary before fulfilment is admissible.
    reset_clock("2026-09-30T00:00:00Z")
    order = fulfill_order(order["id"])
    return {"order": order, "drug": drug, "pharmacy": pharmacy}