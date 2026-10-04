"""Transitive cascades: delisting a drug and confirming a delivery."""
from test_helpers import (
    get_success_data,
    setup_full_stack,
    drive_order_to,
    pay_order,
    fulfill_order,
    ship_order,
    deliver_order,
    list_claims_of,
    list_shipments_of,
    reset_clock,
    OPS,
)


class TestDelistCascade:

    def test_delist_cancels_open_orders_and_returns_their_shipments(self, api):
        """PRD §3.2: "the drug is driven to DELISTED, every one of its price
        rows is suppressed, every order on the drug still at CREATED or PAID is
        cancelled, every shipment of those orders still at PENDING or DISPATCHED
        is returned, every claim of those prescriptions still at PENDING or
        AUTHORIZED is denied with denial_reason_code SOURCING_LOST"

        Design: Difficulty/transitive_cascade/delist_cascade_drug_to_order_to_shipment_to_claim_to_drug_supply
        """
        reset_clock()
        ctx = setup_full_stack(
            drug_rows=[{"unit_cost_cents": 12, "available_units": 600,
                        "reliability_tier": "A"}],
            formulary=True, quantity=30, packaged_quantity=100,
            total_refills_authorized=0,
        )
        order = drive_order_to(ctx["order"]["id"], "FULFILLING")
        shipment = list_shipments_of(order["id"])[0]
        claim = list_claims_of(ctx["prescription"]["id"])[0]
        assert order["status"] == "FULFILLING"
        assert shipment["status"] == "PENDING"
        assert claim["status"] == "PENDING"

        drug = get_success_data(api.delist_formulary(ctx["drug"]["id"], OPS))
        assert drug["state"] == "DELISTED"

        order_after = get_success_data(api.get_order(order["id"], OPS))
        assert order_after["status"] == "CANCELED", "hop one cancels the order"
        shipment_after = get_success_data(api.get_shipment_summary(shipment["id"], OPS))
        assert shipment_after["status"] == "RETURNED", "hop two returns the shipment"

    def test_delist_denies_outstanding_claims_and_recomputes_drug_supply(self, api):
        """PRD §3.2: "the drug's sourcing status is finally recomputed once more
        over the now-suppressed pool."
        PRD §3.2: "every claim of those prescriptions still at PENDING or
        AUTHORIZED is denied with denial_reason_code SOURCING_LOST and
        reserved_quantity reset to zero"

        Design: Difficulty/transitive_cascade/delist_cascade_drug_to_order_to_shipment_to_claim_to_drug_supply
        """
        reset_clock()
        ctx = setup_full_stack(
            drug_rows=[{"unit_cost_cents": 12, "available_units": 600,
                        "reliability_tier": "A"}],
            formulary=True, quantity=30, packaged_quantity=100,
            total_refills_authorized=0,
        )
        order = drive_order_to(ctx["order"]["id"], "FULFILLING")
        claim = list_claims_of(ctx["prescription"]["id"])[0]

        get_success_data(api.delist_formulary(ctx["drug"]["id"], OPS))

        claim_after = get_success_data(api.get_claim(claim["id"], OPS))
        assert claim_after["status"] == "DENIED", "hop three denies the claim"
        assert claim_after["denial_reason_code"] == "SOURCING_LOST"
        assert claim_after["reserved_quantity"] == 0
        assert claim_after["denied_at"] is not None

        drug_after = get_success_data(api.get_drug(ctx["drug"]["id"], OPS))
        assert drug_after["state"] == "DELISTED"
        # Hop four recomputes the sourcing picture over the now-suppressed pool
        # (PRD §3.2). The suppressed rows keep price_status ACTIVE, so the
        # widened sourcing-status pool is still non-empty with positive units
        # yet no sourced row, which reads UNDER_REVIEW rather than UNSOURCED.
        assert drug_after["sourcing_status"] == "UNDER_REVIEW", (
            "the widened sourcing-status pool survives delisting because the "
            "suppressed rows keep their ACTIVE price dimension"
        )
        assert drug_after["effective_unit_cost_cents"] is None, (
            "the sourcing pool itself is empty: every row was suppressed"
        )


class TestDeliveryCascade:

    def test_delivery_depletes_the_prescription_and_cancels_its_claims(self, api):
        """PRD §3.8: "when refills_consumed now reaches
        total_refills_authorized, the prescription's own exhausted-budget
        transition fires in the same operation, moving the prescription from
        ACTIVE to DEPLETED and cancelling every claim of the prescription still
        at PENDING, AUTHORIZED or SHIPPED."

        Design: Difficulty/transitive_cascade/shipment_delivery_cascade_to_prescription_then_claim_cancel_and_demand
        """
        reset_clock()
        ctx = setup_full_stack(
            drug_rows=[{"unit_cost_cents": 12, "available_units": 600,
                        "reliability_tier": "A"}],
            formulary=True, quantity=30, packaged_quantity=100,
            total_refills_authorized=0,
        )
        order = get_success_data(api.get_order(ctx["order"]["id"], OPS))
        paid = pay_order(order["id"])
        fulfill_order(paid["id"])
        ship_order(paid["id"])
        delivered = deliver_order(paid["id"])

        assert delivered["status"] == "DELIVERED", "hop one delivers the order"
        shipment = list_shipments_of(delivered["id"])[0]
        assert shipment["status"] == "DELIVERED"

        rx_after = get_success_data(api.get_prescription(ctx["prescription"]["id"], OPS))
        assert rx_after["refills_consumed"] == 1
        assert rx_after["status"] == "DEPLETED", "hop two exhausts the prescription"

        claims = list_claims_of(ctx["prescription"]["id"])
        assert claims[0]["status"] == "CANCELED", "hop three cancels the claim"
        assert claims[0]["reserved_quantity"] == 0

    def test_delivery_recomputes_the_drug_demand_window(self, api):
        """PRD §3.8: "It then increments the prescription's refills_consumed by
        1 and recomputes the drug's trailing demand"

        Design: Difficulty/transitive_cascade/shipment_delivery_cascade_to_prescription_then_claim_cancel_and_demand
        """
        reset_clock()
        ctx = setup_full_stack(
            drug_rows=[{"unit_cost_cents": 12, "available_units": 600,
                        "reliability_tier": "A"}],
            formulary=True, quantity=30, packaged_quantity=100,
            total_refills_authorized=0,
        )
        order = drive_order_to(ctx["order"]["id"], "SHIPPED")
        before = get_success_data(api.get_drug(ctx["drug"]["id"], OPS))
        deliver_order(order["id"])
        after = get_success_data(api.get_drug(ctx["drug"]["id"], OPS))
        assert after["demand_units_30d"] == before["demand_units_30d"], (
            "the accepted request of 100 units remains inside the trailing "
            "window, so the recompute leaves the demand figure at 100"
        )
        assert after["demand_units_30d"] == 100