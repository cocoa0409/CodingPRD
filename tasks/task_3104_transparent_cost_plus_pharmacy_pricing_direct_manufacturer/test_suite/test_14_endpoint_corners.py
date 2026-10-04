"""Queue B — endpoints section (5 non-stub instances)."""
from test_helpers import (
    create_order_payload,
    list_payload,
    create_drug,
    create_manufacturer,
    create_patient,
    create_pharmacy,
    create_prescriber,
    create_prescription,
    create_sourced_price,
    create_license_pending,
    verify_license,
    get_success_data,
    list_claims_of,
    list_shipments_of,
    pay_order,
    fulfill_order,
    ship_order,
    validate_error,
    validate_paginated,
    validate_success,
    reset_clock,
    OPS,
    PHARMACIST,

)


class TestClaimSummaryProjection:

    def test_claim_summary_reports_the_authorised_reservation(self, api):
        """PRD §4: "| GET | `/claim-summaries/{id}` | Get a refill authorisation
        summary | PharmacyOps, Pharmacist, Patient |"
        PRD §3.4: "On success the claim's reserved_quantity is set to the
        quantity drawn from the drug's supply"

        Design: Corner/endpoints/claim_summary_is_a_computed_read_that_matches_the_claim_row
        """
        reset_clock()
        ctx = refill_ready_stack(api)
        claim = ctx["claim"]
        get_success_data(api.authorize_refill(claim["id"], 40, PHARMACIST))

        summary = validate_success(api.get_claim_summary(claim["id"], OPS))
        row = get_success_data(api.get_claim(claim["id"], OPS))
        assert summary["claim_seq"] == 1
        assert summary["status"] == "AUTHORIZED"
        assert summary["reserved_quantity"] == 40
        assert summary["reserved_quantity"] == row["reserved_quantity"]
        assert summary["claim_id"] == row["id"]

    def test_claim_summary_carries_no_denial_evidence_when_authorised(self, api):
        """PRD §3.4: "Each denial stamps denied_at with the logical clock, sets
        the matching denial_reason_code, and resets reserved_quantity to zero."

        Design: Corner/endpoints/claim_summary_is_a_computed_read_that_matches_the_claim_row
        """
        reset_clock()
        ctx = refill_ready_stack(api)
        claim = ctx["claim"]
        get_success_data(api.authorize_refill(claim["id"], 40, PHARMACIST))
        summary = validate_success(api.get_claim_summary(claim["id"], OPS))
        assert summary["denial_reason_code"] is None
        assert summary["denied_at"] is None


class TestShipmentSummaryProjection:

    def test_summary_tracks_the_shipment_lifecycle_instants(self, api):
        """PRD §3.7: "A successful dispatch consumes one unit of the drug's
        carrier slot on the dispatch day and one on the preceding buffer day,
        sets the shipment to DISPATCHED with dispatch_at stamped at the logical
        clock"
        PRD §3.4: "On success a Shipment is created for the order with shipment_seq equal to the next sequence number for that order and status PENDING"

        Design: Corner/endpoints/shipment_summary_reports_dispatch_and_delivery_instants
        """
        reset_clock()
        ctx = dispatch_ready_order(api)
        shipment = list_shipments_of(ctx["order"]["id"])[0]
        before = validate_success(api.get_shipment_summary(shipment["id"], OPS))
        assert before["status"] == "PENDING"
        assert before["dispatch_at"] is None

        ship_order(ctx["order"]["id"])
        after = validate_success(api.get_shipment_summary(shipment["id"], OPS))
        assert after["status"] == "DISPATCHED"
        assert after["dispatch_at"] == "2026-09-01T00:00:00.000Z", (
            "PRD §2.4: every timestamp is an ISO 8601 UTC instant with three "
            "fractional digits"
        )

    def test_delivery_at_stays_null_until_delivery(self, api):
        """PRD §3.8: "Delivery sets the shipment to DELIVERED with delivery_at
        stamped at the logical clock."

        Design: Corner/endpoints/shipment_summary_reports_dispatch_and_delivery_instants
        """
        reset_clock()
        ctx = dispatch_ready_order(api)
        shipment = list_shipments_of(ctx["order"]["id"])[0]
        ship_order(ctx["order"]["id"])
        after_dispatch = validate_success(api.get_shipment_summary(shipment["id"], OPS))
        assert after_dispatch["delivery_at"] is None, (
            "delivery has not happened yet, so its instant is still empty"
        )


class TestCancellationReasonRequirement:

    def test_cancellation_without_a_reason_code_is_refused(self, api):
        """PRD §3.8: "The operator supplies a reason_code; a cancellation
        request without a stated reason code is refused with
        ERR_CANCELLATION_REASON_REQUIRED and HTTP 422."

        Design: Corner/endpoints/order_cancellation_without_reason_code_is_rejected
        """
        reset_clock()
        ctx = created_order_stack(api)
        response = api.cancel_order_no_reason(ctx["order"]["id"], OPS)
        validate_error(response, "ERR_CANCELLATION_REASON_REQUIRED")
        still = get_success_data(api.get_order(ctx["order"]["id"], OPS))
        assert still["status"] == "CREATED"

    def test_cancellation_with_a_reason_code_succeeds(self, api):
        """PRD §3.8: "Cancelling a CREATED order is unconditional — the only
        requirement is that the order is CREATED"

        Design: Corner/endpoints/order_cancellation_without_reason_code_is_rejected
        """
        reset_clock()
        ctx = created_order_stack(api)
        cancelled = get_success_data(
            api.cancel_order(ctx["order"]["id"], "PATIENT_REQUEST", OPS))
        assert cancelled["status"] == "CANCELED"


class TestReverseLookups:

    def test_filtered_and_sub_resource_claim_reads_agree(self, api):
        """PRD §4: "| GET | `/claims` | List refill authorisations | PharmacyOps, Pharmacist |" and
        "| GET | `/prescriptions/{id}/claims` | List a prescription's refill authorisations, ordered by `claim_seq` ascending | PharmacyOps, Pharmacist, Patient |"

        Design: Corner/endpoints/claims_and_shipments_reverse_lookups_return_the_children_of_their_parents
        """
        reset_clock()
        ctx = dispatch_ready_order(api)
        prescription_id = ctx["prescription"]["id"]

        filtered = validate_paginated(api.list_claims(OPS, {"prescription_id": prescription_id}))
        nested = validate_paginated(api.list_claims_of_prescription(prescription_id, OPS))
        assert filtered[1]["total_count"] == 1
        assert filtered[0] == nested[0]
        assert filtered[0][0]["claim_seq"] == 1

    def test_filtered_and_sub_resource_shipment_reads_agree(self, api):
        """PRD §4: "| GET | `/shipments` | List shipments | PharmacyOps, Pharmacist |" and "| GET | `/prescription-requests/{id}/shipments` | List the shipments consuming a request's capacity | PharmacyOps, Pharmacist |"

        Design: Corner/endpoints/claims_and_shipments_reverse_lookups_return_the_children_of_their_parents
        """
        reset_clock()
        ctx = dispatch_ready_order(api)
        order_id = ctx["order"]["id"]
        request_id = ctx["request"]["id"]

        filtered = validate_paginated(api.list_shipments(OPS, {"order_id": order_id}))
        nested = validate_paginated(
            api.list_shipments_of_intake_request(request_id, OPS))
        assert filtered[1]["total_count"] == 1
        assert filtered[0] == nested[0]
        assert filtered[0][0]["shipment_seq"] == 1


# ─── local helpers ────────────────────────────────────

def _base_stack(api, total_refills_authorized=2):
    manufacturer = create_manufacturer()
    drug = create_drug()
    price_row = create_sourced_price(drug["id"], manufacturer["id"],
                                     unit_cost_cents=12, available_units=600,
                                     reliability_tier="A",
                                     packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             total_refills_authorized=total_refills_authorized,
                             ship_state_code="CA")
    rq = get_success_data(api.create_intake_request(rx["id"], 100, OPS))
    get_success_data(api.review_intake_request(rq["id"], PHARMACIST))
    get_success_data(api.accept_intake_request(rq["id"], PHARMACIST))
    drug = get_success_data(api.expand_formulary(drug["id"], OPS))
    pharmacy = create_pharmacy()
    prices = list_payload(api.list_drug_prices_of_drug(drug["id"], OPS))
    return {"drug": drug, "pharmacy": pharmacy, "price_row": prices[0],
            "prescription": get_success_data(api.get_prescription(rx["id"], OPS)),
            "request": get_success_data(api.get_intake_request(rq["id"], OPS))}


def refill_ready_stack(api):
    """A PENDING claim whose drug is SOURCED and whose refill budget is unused."""
    ctx = _base_stack(api, total_refills_authorized=2)
    claims = list_claims_of(ctx["prescription"]["id"])
    ctx["claim"] = claims[0]
    return ctx


def dispatch_ready_order(api):
    """An order driven to FULFILLING with a PENDING shipment and a licensed
    pharmacy for the destination state."""
    ctx = _base_stack(api, total_refills_authorized=2)
    licence = create_license_pending(ctx["pharmacy"]["id"], state_code="CA")
    verify_license(ctx["pharmacy"]["id"], licence["id"])
    order = get_success_data(api.create_order(create_order_payload(
        ctx["prescription"]["id"], ctx["request"]["id"],
        ctx["pharmacy"]["id"], ctx["price_row"]["id"], quantity=30), OPS))
    order = pay_order(order["id"])
    ctx["order"] = fulfill_order(order["id"])
    return ctx


def created_order_stack(api):
    """A CREATED order on a formulary drug with a licensed pharmacy."""
    ctx = _base_stack(api, total_refills_authorized=1)
    licence = create_license_pending(ctx["pharmacy"]["id"], state_code="CA")
    verify_license(ctx["pharmacy"]["id"], licence["id"])
    ctx["order"] = get_success_data(api.create_order(create_order_payload(
        ctx["prescription"]["id"], ctx["request"]["id"],
        ctx["pharmacy"]["id"], ctx["price_row"]["id"], quantity=30), OPS))
    return ctx