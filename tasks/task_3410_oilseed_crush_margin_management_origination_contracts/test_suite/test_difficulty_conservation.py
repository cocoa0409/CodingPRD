"""Difficulty queue — compensating_invariant: physical bushel mass conserved
across book/deliver/cancel, and monetary cents conserved across accrue/settle
(PRD §3.5 and §3.4).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_origination_contract,
    book_shipment,
    cancel_shipment,
    create_crush_plant,
    create_truck_lane,
    deliver_shipment_now,
    elect_price,
    post_bean_quote,
    read_contract,
    set_clock,
    settle_contract,
    setup_deferred_contract_delivered_unpriced,
    setup_elevator_with_stored_bushels,
    validate_paginated,
    validate_success,
)

MERCH = TEST_USERS["origination_merchandiser_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]


class TestBushelMassConservedAcrossBookDeliverCancel:
    """Elevator holding one 5000-bu lot; TRUCK lane (transit 2) to a plant;
    shipment A moves 2000 bu to the plant; shipment B books 1000 and is then
    cancelled."""

    def _setup_through_delivery(self):
        base = setup_elevator_with_stored_bushels(5000)
        plant = create_crush_plant()
        lane = create_truck_lane(
            base["site"]["elevator"]["id"], plant["id"], transit_days=2
        )
        ship_a = book_shipment(
            lane["id"], 2000, departure_date="2026-09-10T00:00:00Z"
        )
        set_clock("2026-09-12T00:00:00Z")
        deliver_shipment_now(ship_a["id"])
        return base, plant, lane

    def test_delivery_moves_bushels_to_plant_without_loss(self, api):
        """PRD §3.5: "the coordinator marks the shipment delivered: it moves from `BOOKED` to `DELIVERED`, terminal, the destination plant's `bean_inventory_bushels` grows by the shipped bushels". Mass is
        conserved: 3000 stored + 2000 at the plant == the 5000 applied.

        Design: Difficulty/compensating_invariant/bushel_mass_conserved_across_book_deliver_cancel
        """
        base, plant, _ = self._setup_through_delivery()
        elevator = validate_success(
            api_client.get_elevator(base["site"]["elevator"]["id"], LOGISTICS)
        )
        plant_after = validate_success(
            api_client.get_crush_plant(plant["id"], LOGISTICS)
        )
        assert float(elevator["stored_bushels"]) == pytest.approx(3000)
        assert float(plant_after["bean_inventory_bushels"]) == pytest.approx(2000)
        assert (
            float(elevator["stored_bushels"])
            + float(plant_after["bean_inventory_bushels"])
        ) == pytest.approx(5000)

    def test_book_then_cancel_restores_lot_exactly(self, api):
        """PRD §3.5: "every entry in `draws` is restored in reverse draw order, each lot's `current_bushels` climbing back by exactly what was drawn — a `DEPLETED` lot that rises above zero returns to `OPEN` — the elevator's stored and certified counters recover".
        Booking 1000 drops stored to 2000; cancelling restores stored to
        exactly 3000 and the lot to 3000/OPEN, while the delivered 2000 at the
        plant is untouched.

        Design: Difficulty/compensating_invariant/bushel_mass_conserved_across_book_deliver_cancel
        """
        base, plant, lane = self._setup_through_delivery()
        ship_b = book_shipment(
            lane["id"], 1000, departure_date="2026-09-13T00:00:00Z"
        )
        mid = validate_success(
            api_client.get_elevator(base["site"]["elevator"]["id"], LOGISTICS)
        )
        assert float(mid["stored_bushels"]) == pytest.approx(2000)

        cancel_shipment(ship_b["id"])
        elevator = validate_success(
            api_client.get_elevator(base["site"]["elevator"]["id"], LOGISTICS)
        )
        assert float(elevator["stored_bushels"]) == pytest.approx(3000), (
            "the book/cancel pair conserves bushel mass with zero drift"
        )
        positions, meta = validate_paginated(
            api_client.list_storage_positions(
                LOGISTICS, params={"elevator_id": base["site"]["elevator"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert float(positions[0]["current_bushels"]) == pytest.approx(3000)
        assert positions[0]["status"] == "OPEN"
        plant_after = validate_success(
            api_client.get_crush_plant(plant["id"], LOGISTICS)
        )
        assert float(plant_after["bean_inventory_bushels"]) == pytest.approx(2000)


class TestSettlementMoneyConservedLinesMinusAccrual:
    """DEFERRED 1000 bu at 2 cents/bu/day, delivered 2026-09-10, priced
    2026-09-20 at 1250, then settled."""

    def _setup_settled(self):
        base = setup_deferred_contract_delivered_unpriced(
            quantity_bushels=1000,
            storage_rate_cents_per_bushel_day=2,
            pricing_deadline="2026-12-15T00:00:00Z",
            futures_month="2026-12",
            bean_price_cents=1200,
            bean_quote_date="2026-09-01T00:00:00Z",
            apply_clock="2026-09-10T00:00:00Z",
        )
        set_clock("2026-09-20T00:00:00Z")
        post_bean_quote("2026-12", 1250, "2026-09-20T00:00:00Z")
        elect_price(base["contract"]["id"], 1000)
        settled = settle_contract(base["contract"]["id"])
        return settled

    def test_accrual_is_moved_out_of_payable_exactly(self, api):
        """PRD §3.4: "settlement_accrual_deduction_cents` is the frozen `accrued_storage_cents`; and `settlement_net_payable_cents` is the line total minus the accrual deduction." Cents are conserved:
        1250000 - 20000 - 1230000 == 0 — the accrual is moved out of the
        payable, never created or destroyed.

        Design: Difficulty/compensating_invariant/settlement_money_conserved_lines_minus_accrual
        """
        settled = self._setup_settled()
        assert_origination_contract(settled)
        assert settled["settlement_line_total_cents"] == 1250000
        assert settled["settlement_accrual_deduction_cents"] == 20000
        assert settled["settlement_net_payable_cents"] == 1230000
        assert (
            settled["settlement_line_total_cents"]
            - settled["settlement_accrual_deduction_cents"]
            - settled["settlement_net_payable_cents"]
        ) == 0

    def test_accrual_frozen_after_final_pricing(self, api):
        """PRD §3.4: "Once a contract reaches `PRICED` the accrual stops: the final leg runs through the final pricing instant and the balance freezes." Advancing the clock to 2026-09-25 after settlement leaves
        accrued_storage_cents at exactly 20000 — the forward accrual and its
        cutoff compensation net to zero drift.

        Design: Difficulty/compensating_invariant/settlement_money_conserved_lines_minus_accrual
        """
        settled = self._setup_settled()
        set_clock("2026-09-25T00:00:00Z")
        after = read_contract(settled["id"])
        assert after["accrued_storage_cents"] == 20000
        assert after["fulfillment_status"] == "SETTLED"
