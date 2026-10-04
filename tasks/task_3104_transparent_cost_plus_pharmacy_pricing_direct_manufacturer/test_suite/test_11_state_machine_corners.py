"""Queue B — state_machines section (4 non-stub instances)."""
from test_helpers import (
    create_order_payload,
    get_success_data,
    validate_error,
    create_manufacturer,
    create_drug,
    create_patient,
    create_sourced_price,
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
    ship_order,
    deliver_order,
    reset_clock,
    OPS,

)


class TestOrderCancellationBranches:

    def test_created_order_cancels_and_delivered_order_is_locked(self, api):
        """PRD §3.8: "Cancelling a CREATED order is unconditional — the only
        requirement is that the order is CREATED"
        PRD §3.8: "DELIVERED and CANCELED are the terminal states of the order
        machine."

        Design: Corner/state_machines/cancel_order_from_created_is_allowed_but_from_delivered_is_locked
        """
        reset_clock()
        ctx = order_stack(api)
        created = set_status(api, ctx, quantity=30, target="CREATED")
        delivered = set_status(api, ctx, quantity=30, target="DELIVERED")

        cancelled = get_success_data(
            api.cancel_order(created["id"], "PATIENT_REQUEST", OPS))
        assert cancelled["status"] == "CANCELED"

        response = api.cancel_order(delivered["id"], "PATIENT_REQUEST", OPS)
        validate_error(response, "ERR_INVALID_STATE")
        still = get_success_data(api.get_order(delivered["id"], OPS))
        assert still["status"] == "DELIVERED"

    def test_cancellation_without_a_reason_code_is_refused(self, api):
        """PRD §3.8: "The operator supplies a reason_code; a cancellation
        request without a stated reason code is refused with
        ERR_CANCELLATION_REASON_REQUIRED and HTTP 422."

        Design: Corner/state_machines/cancel_order_from_created_is_allowed_but_from_delivered_is_locked
        """
        reset_clock()
        ctx = order_stack(api)
        created = set_status(api, ctx, quantity=30, target="CREATED")
        response = api.cancel_order_no_reason(created["id"], OPS)
        validate_error(response, "ERR_CANCELLATION_REASON_REQUIRED")


class TestManufacturerSuspensionQuarantine:

    def test_suspension_suppresses_every_sourced_row_of_the_manufacturer(self, api):
        """PRD §3.1: "it forces every one of that manufacturer's rows that
        currently sits at SOURCED on the sourcing dimension to SUPPRESSED, each
        such move running the full sourcing-loss cascade"

        Design: Corner/state_machines/manufacturer_suspension_quarantines_every_sourced_price_row
        """
        reset_clock()
        manufacturer = create_manufacturer("Cardell Labs")
        drug = create_drug()
        row_a = create_sourced_price(drug["id"], manufacturer["id"],
                                     unit_cost_cents=12, available_units=500,
                                     reliability_tier="A", packaging="500-count bottle")
        row_b = create_sourced_price(drug["id"], manufacturer["id"],
                                     unit_cost_cents=18, available_units=300,
                                     reliability_tier="B", packaging="300-count bottle")

        suspended = get_success_data(
            api.set_manufacturer_state(manufacturer["id"], "SUSPENDED", OPS))
        assert suspended["status"] == "SUSPENDED"

        a_after = get_success_data(api.get_price(row_a["id"], OPS))
        b_after = get_success_data(api.get_price(row_b["id"], OPS))
        assert a_after["sourcing_status"] == "SUPPRESSED"
        assert b_after["sourcing_status"] == "SUPPRESSED"

    def test_drug_sourcing_picture_collapses_when_the_pool_empties(self, api):
        """PRD §3.2: "If that pool is empty, the drug's sourcing_status is
        UNSOURCED."
        PRD §3.2: "The supply total, written to the drug's supply_units, sums
        available_units across rows whose sourcing dimension is SOURCED or
        UNDER_REVIEW and whose manufacturer is ACTIVE"

        Design: Corner/state_machines/manufacturer_suspension_quarantines_every_sourced_price_row
        """
        reset_clock()
        manufacturer = create_manufacturer("Cardell Labs")
        drug = create_drug()
        create_sourced_price(drug["id"], manufacturer["id"], unit_cost_cents=12,
                             available_units=500, reliability_tier="A",
                             packaging="500-count bottle")
        get_success_data(api.set_manufacturer_state(manufacturer["id"], "SUSPENDED", OPS))

        after = get_success_data(api.get_drug(drug["id"], OPS))
        assert after["sourcing_status"] == "UNSOURCED"
        assert after["supply_units"] == 0


class TestPriceRowRevocation:

    def test_revocation_suppresses_the_row_and_empties_the_pool(self, api):
        """PRD §3.1: "Moving a row from ACTIVE to REVOKED requires only that the
        row's price_status is currently ACTIVE, and it simultaneously forces the
        row's sourcing_status to SUPPRESSED — a revoked row can never be a
        sourcing candidate."
        PRD §3.2: "When the pool is empty, effective_unit_cost_cents is null."

        Design: Corner/state_machines/price_row_revocation_suppresses_the_row_and_empties_the_eligible_pool
        """
        reset_clock()
        manufacturer = create_manufacturer()
        drug = create_drug()
        row = create_sourced_price(drug["id"], manufacturer["id"],
                                   unit_cost_cents=12, available_units=500,
                                   reliability_tier="A", packaging="500-count bottle")
        revoked = get_success_data(api.revoke_price(row["id"], OPS))
        assert revoked["price_status"] == "REVOKED"
        assert revoked["sourcing_status"] == "SUPPRESSED"

        data = get_success_data(api.stock_check(drug["id"], OPS))
        assert data["effective_unit_cost_cents"] is None
        assert data["sourcing_status"] == "UNSOURCED"
        assert data["eligible_price_ids"] == []

    def test_revoked_row_is_terminal_for_its_price_dimension(self, api):
        """PRD §3.1: "REVOKED and SUPPRESSED are the terminal values of their
        respective dimensions."

        Design: Corner/state_machines/price_row_revocation_suppresses_the_row_and_empties_the_eligible_pool
        """
        reset_clock()
        manufacturer = create_manufacturer()
        drug = create_drug()
        row = create_sourced_price(drug["id"], manufacturer["id"],
                                   unit_cost_cents=12, available_units=500,
                                   reliability_tier="A", packaging="500-count bottle")
        get_success_data(api.revoke_price(row["id"], OPS))
        response = api.activate_price(row["id"], OPS)
        validate_error(response, "ERR_INVALID_STATE")


# ─── local helpers ────────────────────────────────────

def order_stack(api):
    """A formulary drug, licensed pharmacy, patient, prescriber and one ACTIVE
    prescription with an ACCEPTED request ready to order against."""
    manufacturer = create_manufacturer("Bexley Generics")
    drug = create_drug()
    price_row = create_sourced_price(
        drug["id"], manufacturer["id"], unit_cost_cents=12, available_units=600,
        reliability_tier="A", packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             total_refills_authorized=2, ship_state_code="CA")
    rq = submit_intake(rx["id"], packaged_quantity=100)
    review_intake(rq["id"])
    accept_intake(rq["id"])
    drug = get_success_data(api.expand_formulary(drug["id"], OPS))
    pharmacy = create_pharmacy()
    licence = create_license_pending(pharmacy["id"], state_code="CA")
    verify_license(pharmacy["id"], licence["id"])
    return {"drug": drug, "pharmacy": pharmacy, "price_row": price_row,
            "patient": patient, "prescriber": prescriber, "prescription": rx,
            "request": rq}


def set_status(api, ctx, quantity, target):
    """Create a fresh order on its own prescription/request and drive it to
    `target`."""
    rx = create_prescription(ctx["patient"]["id"], ctx["prescriber"]["id"],
                             ctx["drug"]["id"], total_refills_authorized=2,
                             ship_state_code="CA")
    rq = submit_intake(rx["id"], packaged_quantity=quantity)
    review_intake(rq["id"])
    accept_intake(rq["id"])
    order = get_success_data(api.create_order(create_order_payload(
        rx["id"], rq["id"], ctx["pharmacy"]["id"],
        ctx["price_row"]["id"], quantity=quantity), OPS))
    if target == "CREATED":
        return order
    order = pay_order(order["id"])
    if target == "PAID":
        return order
    order = fulfill_order(order["id"])
    if target == "FULFILLING":
        return order
    order = ship_order(order["id"])
    if target == "SHIPPED":
        return order
    return deliver_order(order["id"])