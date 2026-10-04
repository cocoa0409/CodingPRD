"""Queue B — errors section (5 non-stub instances)."""
from test_helpers import (
    setup_active_prescription,
    list_payload,
    NON_EXISTENT_UUID,
    build_user_headers,
    create_drug,
    create_manufacturer,
    create_patient,
    create_pharmacy,
    create_prescriber,
    create_prescription,
    create_price_row,
    create_sourced_price,
    get_success_data,
    list_claims_of,
    validate_error,
    validate_success,
    reset_clock,
    OPS,
    PHARMACIST,

)


class TestOrderQuantityBound:

    def test_order_quantity_below_one_is_refused(self, api):
        """PRD §3.6: "quantity must be at least 1, reported as ERR_INVALID_AMOUNT
        when violated."

        Design: Corner/errors/order_create_with_quantity_below_one_is_rejected
        """
        reset_clock()
        ctx = ready_to_order(api)
        response = api.create_order({
            "prescription_id": ctx["prescription"]["id"],
            "request_id": ctx["request"]["id"],
            "pharmacy_id": ctx["pharmacy"]["id"],
            "quantity": 0,
            "source_price_id": ctx["price_row"]["id"],
        }, OPS)
        validate_error(response, "ERR_INVALID_AMOUNT")

    def test_no_order_row_is_created_by_the_refused_request(self, api):
        """PRD §2.12: "Lower-bound numeric validation on request payloads sits
        after the state and business rules at the lower end of the ordering"

        Design: Corner/errors/order_create_with_quantity_below_one_is_rejected
        """
        reset_clock()
        ctx = ready_to_order(api)
        api.create_order({
            "prescription_id": ctx["prescription"]["id"],
            "request_id": ctx["request"]["id"],
            "pharmacy_id": ctx["pharmacy"]["id"],
            "quantity": 0,
            "source_price_id": ctx["price_row"]["id"],
        }, OPS)
        orders = list_payload(
            api.list_orders(OPS, {"prescription_id": ctx["prescription"]["id"]}))
        assert orders == []


class TestRequestCapacityExceeded:

    def test_quantity_above_the_remaining_capacity_is_refused(self, api):
        """PRD §3.6: "an order whose quantity exceeds the request's remaining
        capacity — computed as packaged_quantity minus consumed_quantity — is
        refused with ERR_REQUEST_CAPACITY_EXCEEDED."

        Design: Corner/errors/request_capacity_exceeded_error_is_reachable
        """
        reset_clock()
        ctx = ready_to_order(api, packaged_quantity=20)
        response = api.create_order({
            "prescription_id": ctx["prescription"]["id"],
            "request_id": ctx["request"]["id"],
            "pharmacy_id": ctx["pharmacy"]["id"],
            "quantity": 21,
            "source_price_id": ctx["price_row"]["id"],
        }, OPS)
        validate_error(response, "ERR_REQUEST_CAPACITY_EXCEEDED")

    def test_quantity_at_the_exact_capacity_boundary_succeeds(self, api):
        """PRD §3.6: "it must still carry enough packaged_quantity headroom for
        the order's quantity"

        Design: Corner/errors/request_capacity_exceeded_error_is_reachable
        """
        reset_clock()
        ctx = ready_to_order(api, packaged_quantity=20)
        order = validate_success(api.create_order({
            "prescription_id": ctx["prescription"]["id"],
            "request_id": ctx["request"]["id"],
            "pharmacy_id": ctx["pharmacy"]["id"],
            "quantity": 20,
            "source_price_id": ctx["price_row"]["id"],
        }, OPS), 201)
        assert order["quantity"] == 20


class TestSourcePriceDrugMismatch:

    def test_a_price_row_for_another_drug_is_refused(self, api):
        """PRD §3.6: "The order's source_price_id must reference a manufacturer
        price row whose drug_id equals the prescription's drug_id; a cross-drug
        source is refused with ERR_SOURCE_PRICE_DRUG_MISMATCH and HTTP 422."

        Design: Corner/errors/source_price_from_a_different_drug_is_refused
        """
        reset_clock()
        ctx = ready_to_order(api)
        other_drug = create_drug(drug_name="Lisinopril", strength="10MG")
        other_row = create_sourced_price(
            other_drug["id"], ctx["manufacturer"]["id"], unit_cost_cents=9,
            available_units=600, reliability_tier="A", packaging="500-count bottle")

        response = api.create_order({
            "prescription_id": ctx["prescription"]["id"],
            "request_id": ctx["request"]["id"],
            "pharmacy_id": ctx["pharmacy"]["id"],
            "quantity": 30,
            "source_price_id": other_row["id"],
        }, OPS)
        validate_error(response, "ERR_SOURCE_PRICE_DRUG_MISMATCH")

    def test_matching_source_price_is_accepted(self, api):
        """PRD §3.6: "the source_price_id naming the primary manufacturer price
        row selected as the sourcing source"

        Design: Corner/errors/source_price_from_a_different_drug_is_refused
        """
        reset_clock()
        ctx = ready_to_order(api)
        order = validate_success(api.create_order({
            "prescription_id": ctx["prescription"]["id"],
            "request_id": ctx["request"]["id"],
            "pharmacy_id": ctx["pharmacy"]["id"],
            "quantity": 30,
            "source_price_id": ctx["price_row"]["id"],
        }, OPS), 201)
        assert order["source_price_id"] == ctx["price_row"]["id"]


class TestSourcingErrorsAreReachable:

    def test_formulary_gate_failure_is_reachable_through_expansion_alone(self, api):
        """PRD §3.3: "a failure of the gate as a whole is reported as
        ERR_FORMULARY_GATE_FAILED with HTTP 422"
        PRD §3.1: "A new row starts with its two dimensions at their initial
        values: price_status at PROPOSED"

        Design: Corner/errors/formulary_gate_failure_error_is_reachable_on_an_unsourced_drug
        """
        reset_clock()
        manufacturer = create_manufacturer()
        drug = create_drug()
        row = create_price_row(drug["id"], manufacturer["id"], unit_cost_cents=12,
                               available_units=600, reliability_tier="A",
                               packaging="500-count bottle")
        assert row["price_status"] == "PROPOSED"

        response = api.expand_formulary(drug["id"], OPS)
        validate_error(response, "ERR_FORMULARY_GATE_FAILED")

    def test_sourcing_unavailable_is_reachable_through_the_refill_alone(self, api):
        """PRD §3.4: "Refusal because the drug's sourcing status is not SOURCED
        is reported as ERR_SOURCING_UNAVAILABLE."

        Design: Corner/errors/formulary_gate_failure_error_is_reachable_on_an_unsourced_drug
        """
        reset_clock()
        ctx = unsourced_drug_stack(api)
        claim = ctx["claim"]
        response = api.authorize_refill(claim["id"], 30, PHARMACIST)
        validate_error(response, "ERR_SOURCING_UNAVAILABLE")
        after = get_success_data(api.get_claim(claim["id"], OPS))
        assert after["status"] != "AUTHORIZED", (
            "the refused authorisation left the claim un-authorised"
        )
        assert after["reserved_quantity"] == 0


class TestAuthorizationBeforeExistence:

    def test_permitted_role_with_unknown_id_reaches_not_found(self, api):
        """PRD §2.7: "the server resolves them strictly left to right. The first
        identifier in the path that does not correspond to a persisted resource
        terminates the request immediately with ERR_RESOURCE_NOT_FOUND"

        Design: Corner/errors/role_not_permitted_and_resource_not_found_are_distinguishable_on_the_same_path
        """
        reset_clock()
        create_patient()
        response = api.get_manufacturer(NON_EXISTENT_UUID, OPS)
        validate_error(response, "ERR_RESOURCE_NOT_FOUND")

    def test_unpermitted_role_reaches_role_not_permitted_first(self, api):
        """PRD §2.12: "Authentication and authorization are evaluated before
        anything else"
        PRD §2.1: "A request whose role is declared but not permitted for the
        operation being attempted is refused with ERR_ROLE_NOT_PERMITTED and
        HTTP 403."

        Design: Corner/errors/role_not_permitted_and_resource_not_found_are_distinguishable_on_the_same_path
        """
        reset_clock()
        patient = create_patient()
        response = api.get_manufacturer(
            NON_EXISTENT_UUID, build_user_headers(patient["id"], "Patient"))
        validate_error(response, "ERR_ROLE_NOT_PERMITTED")


# ─── local helpers ────────────────────────────────────

def ready_to_order(api, packaged_quantity=100):
    """A formulary drug, licensed pharmacy, and an ACTIVE prescription with an
    ACCEPTED request, ready for an order."""
    manufacturer = create_manufacturer()
    drug = create_drug()
    price_row = create_sourced_price(drug["id"], manufacturer["id"],
                                     unit_cost_cents=12, available_units=600,
                                     reliability_tier="A",
                                     packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             total_refills_authorized=1, ship_state_code="CA")
    rq = get_success_data(api.create_intake_request(rx["id"], packaged_quantity, OPS))
    get_success_data(api.review_intake_request(rq["id"], PHARMACIST))
    get_success_data(api.accept_intake_request(rq["id"], PHARMACIST))
    # The expansion gate needs trailing demand of at least 1 and supply at most
    # ten times demand; a second accepted request supplies that headroom.
    extra = setup_active_prescription(
        patient["id"], prescriber["id"], drug["id"],
        packaged_quantity=200, total_refills_authorized=1, ship_state_code="CA")
    drug = get_success_data(api.expand_formulary(drug["id"], OPS))
    pharmacy = create_pharmacy()
    return {
        "manufacturer": manufacturer,
        "drug": drug,
        "price_row": price_row,
        "pharmacy": pharmacy,
        "prescription": get_success_data(api.get_prescription(rx["id"], OPS)),
        "request": get_success_data(api.get_intake_request(rq["id"], OPS)),
    }


def unsourced_drug_stack(api):
    """A drug listed `is_controlled`, so no intake of its own can ever be
    routed (PRD §3.4: "A controlled-substance drug cannot enter intake at
    all"), but whose claims are created through a sibling generic of the same
    name — not applicable here: the intake exclusion is keyed on the drug, so
    the claim is built against a clean generic and the sourcing status is then
    taken away by revocation of its only row."""
    manufacturer = create_manufacturer()
    drug = create_drug()
    row = create_sourced_price(drug["id"], manufacturer["id"],
                               unit_cost_cents=12, available_units=600,
                               reliability_tier="A",
                               packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             total_refills_authorized=2, ship_state_code="CA")
    rq = get_success_data(api.create_intake_request(rx["id"], 100, OPS))
    get_success_data(api.review_intake_request(rq["id"], PHARMACIST))
    get_success_data(api.accept_intake_request(rq["id"], PHARMACIST))
    # Revoking the sole row drops the drug to UNSOURCED without cancelling any
    # order, because the order still sits at CREATED with no shipment at all
    # (PRD §3.5 revocation is a price-dimension move, so the reverse-sourcing
    # cascade of §3.2 does not run).
    get_success_data(api.revoke_price(row["id"], OPS))
    claims = list_claims_of(rx["id"])
    return {"drug": drug, "claim": claims[0], "request": rq}