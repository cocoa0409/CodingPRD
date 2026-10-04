"""Transitions gated by a sibling entity's state."""
from test_helpers import (
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
    add_accepted_demand,
    pay_order,
    fulfill_order,
    reset_clock,
    OPS,

)


class TestDispatchRequiresAnActiveLicence:

    def test_dispatch_is_refused_while_the_licence_is_pending(self, api):
        """PRD §3.7: "a missing, expired, revoked or superseded licence — or a
        pharmacy whose shipping_enabled flag is false — refuses the dispatch
        with ERR_NOT_LICENSED_IN_STATE and HTTP 422."

        Design: Difficulty/cross_entity_state_dependency/order_shipping_requires_pharmacy_license_active_for_ship_state
        """
        reset_clock()
        ctx = pending_licence_stack(api)
        response = api.ship_order(ctx["order"]["id"], OPS)
        validate_error(response, "ERR_NOT_LICENSED_IN_STATE")
        licence = get_success_data(
            api.get_license(ctx["pharmacy"]["id"], ctx["license"]["id"], OPS))
        assert licence["status"] == "PENDING"

    def test_verifying_the_licence_unblocks_the_same_dispatch(self, api):
        """PRD §3.5: "Moving a licence from PENDING to ACTIVE requires that the
        licence is PENDING and that its expiry_at is strictly after the logical
        clock; on success verified_at is stamped with the logical clock."
        PRD §3.5: "The practical consequence for the rest of the system is that
        coverage is a live property"

        Design: Difficulty/cross_entity_state_dependency/order_shipping_requires_pharmacy_license_active_for_ship_state
        """
        reset_clock()
        ctx = pending_licence_stack(api)
        verified = verify_license(ctx["pharmacy"]["id"], ctx["license"]["id"])
        assert verified["status"] == "ACTIVE"
        assert verified["verified_at"] is not None

        shipped = get_success_data(api.ship_order(ctx["order"]["id"], OPS))
        assert shipped["status"] == "SHIPPED"


class TestFormularyAdmissionRequiresAnActiveManufacturer:

    def test_suspended_manufacturer_empties_the_pool_and_refuses_admission(self, api):
        """PRD §3.1: "Suspension is not cosmetic — it removes the
        manufacturer's entire price offering from the sourcing pool"
        PRD §3.3: "a failure of the gate as a whole is reported as
        ERR_FORMULARY_GATE_FAILED with HTTP 422."

        Design: Difficulty/cross_entity_state_dependency/formulary_expansion_of_drug_requires_manufacturer_active_and_price_sourced
        """
        reset_clock()
        ctx = suspended_manufacturer_stack(api)
        scored = get_success_data(api.get_drug(ctx["drug"]["id"], OPS))
        assert scored["supply_units"] == 0, (
            "a suspended manufacturer's rows leave the pool entirely"
        )
        assert scored["sourcing_status"] != "SOURCED"

        response = api.expand_formulary(ctx["drug"]["id"], OPS)
        validate_error(response, "ERR_FORMULARY_GATE_FAILED")
        still = get_success_data(api.get_drug(ctx["drug"]["id"], OPS))
        assert still["state"] == "NON_FORMULARY"

    def test_reactivating_the_manufacturer_admits_the_drug(self, api):
        """PRD §3.3: "On success the drug's packaging is set from the selected
        primary price row, and effective_unit_cost_cents, ship_interval_days and
        expansion_score are recomputed."

        Design: Difficulty/cross_entity_state_dependency/formulary_expansion_of_drug_requires_manufacturer_active_and_price_sourced
        """
        reset_clock()
        ctx = suspended_manufacturer_stack(api)
        reactivated = get_success_data(
            api.set_manufacturer_state(ctx["manufacturer"]["id"], "ACTIVE", OPS))
        assert reactivated["status"] == "ACTIVE"

        # Suspension moved the row to SUPPRESSED, which is terminal (PRD §3.2),
        # so reactivation restores the manufacturer's eligibility but does not
        # revive the row: the drug is still refused while the only row it has
        # sits outside the pool.
        drug = get_success_data(api.get_drug(ctx["drug"]["id"], OPS))
        assert drug["sourcing_status"] == "UNDER_REVIEW", (
            "the widened sourcing-status pool regains the ACTIVE-price row, but "
            "with no SOURCED row and positive units the drug sits UNDER_REVIEW"
        )
        assert drug["effective_unit_cost_cents"] is None, (
            "the sourcing pool counts only ACTIVE+SOURCED rows of an ACTIVE "
            "manufacturer, and the suppressed row is not one of them"
        )
        response = api.expand_formulary(ctx["drug"]["id"], OPS)
        validate_error(response, "ERR_FORMULARY_GATE_FAILED")

        # With the manufacturer ACTIVE again a fresh offering can be registered
        # and sourced, which refills the pool.
        fresh = create_sourced_price(ctx["drug"]["id"], ctx["manufacturer"]["id"],
                                     unit_cost_cents=12, available_units=500,
                                     reliability_tier="C",
                                     packaging="500-count bottle")
        drug = get_success_data(api.get_drug(ctx["drug"]["id"], OPS))
        assert drug["sourcing_status"] == "SOURCED"
        assert drug["supply_units"] == 500
        assert drug["effective_unit_cost_cents"] == 12, (
            "the freshly sourced row of the reactivated manufacturer re-derives "
            "the sourcing-effective cost"
        )

        admitted = get_success_data(api.expand_formulary(ctx["drug"]["id"], OPS))
        assert admitted["state"] == "FORMULARY"


# ─── local helpers ────────────────────────────────────

def pending_licence_stack(api):
    """A FULFILLING order whose destination state carries only a PENDING
    licence. The drug's pool is A-tier with 600 units, so ship_interval_days is
    0 and the interval gate is already satisfied."""
    manufacturer = create_manufacturer()
    drug = create_drug()
    create_sourced_price(drug["id"], manufacturer["id"], unit_cost_cents=12,
                         available_units=600, reliability_tier="A",
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
    licence = create_license_pending(pharmacy["id"], state_code="CA")
    prices = list_payload(api.list_drug_prices_of_drug(drug["id"], OPS))
    order = get_success_data(api.create_order(create_order_payload(
        rx["id"], rq["id"], pharmacy["id"], prices[0]["id"], quantity=30), OPS))
    order = pay_order(order["id"])
    order = fulfill_order(order["id"])
    return {"order": order, "drug": drug, "pharmacy": pharmacy, "license": licence}


def suspended_manufacturer_stack(api):
    """A drug whose sole 500-unit sourced row is offered by a manufacturer that
    is then suspended, with 250 units of trailing demand already in place."""
    manufacturer = create_manufacturer("Bexley Generics")
    drug = create_drug()
    price_row = create_sourced_price(drug["id"], manufacturer["id"],
                                     unit_cost_cents=12, available_units=500,
                                     reliability_tier="C",
                                     packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    add_accepted_demand(drug["id"], patient["id"], prescriber["id"], 250)
    get_success_data(api.set_manufacturer_state(manufacturer["id"], "SUSPENDED", OPS))
    return {"drug": drug, "manufacturer": manufacturer, "price_row": price_row}