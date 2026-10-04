"""Transitive cascades: a seven-hop receipt and a four-hop posture hold."""

from test_helpers import (
    ADMIN,
    DCM,
    create_and_approve_return,
    list_lines,
    receive_return,
    setup_shipped_order,
    setup_supplier,
    validate_paginated,
    validate_success,
)


class TestReturnReceiptSevenHopCascade:
    """One receive call drives line, stock, claim, account, supplier and item."""

    def _received(self, api):
        scenario = setup_shipped_order(api, qty=5, price=10000, long_tail=True,
                                       on_hand=10, sku="SKU-4001")
        supplier = setup_supplier(api, home_dc=scenario["dc"])
        first = create_and_approve_return(api, scenario, requested_units=5)
        second = create_and_approve_return(api, scenario, requested_units=2)
        receive_return(api, ret=first, line=scenario["lines"][0],
                       part_number="SS-M6X30-4140")
        scenario["supplier"] = supplier
        scenario["returns"] = [first, second]
        return scenario

    def test_the_receipt_moves_line_stock_claim_account_and_catalogue(self, api):
        """PRD §3.9: "Each line's `returned_units` is increased by the authorized units
        for that line, and the line moves to `line_status` `RETURNED`."
        PRD §3.9: "The center's stock row for each line's item has its `on_hand_units`
        increased by the line's `restocked_units`, and its `available_units` is
        recomputed."
        PRD §3.9: "A `DamageClaim` is opened for the damaged share of each line's item, and
        the owning account's `open_claim_count` is incremented by 1."
        PRD §3.9: "When the item's damage ratio breach condition returns true —
        evaluated as described below — the item's `catalog_status` is set to `SUSPENDED`."
        PRD §3.9: "Exactly 10,000 cents suspends the item; 9,999 cents does not."

        Design: Difficulty/transitive_cascade/return_receipt_seven_hop_cascade
        """
        scenario = self._received(api)
        stock_id = scenario["stock_rows"][0]["id"]

        received = validate_success(api.get_return(scenario["returns"][0]["id"], DCM))
        assert received["return_status"] == "RECEIVED"

        lines = list_lines(api, scenario["acct"], scenario["order"])
        assert lines[0]["returned_units"] == 5
        assert lines[0]["restocked_units"] == 4
        assert lines[0]["damaged_units"] == 1

        stock = validate_success(api.get_stock(stock_id, DCM))
        assert stock["on_hand_units"] == 9, "5 left after the pick, 4 restored"
        assert stock["available_units"] == 9

        claims, _meta = validate_paginated(api.list_damage_claims(
            DCM, {"order_id": scenario["order"]["id"], "limit": 10, "offset": 0}))
        assert len(claims) == 1
        assert claims[0]["claim_units"] == 1
        assert claims[0]["damage_value_cents"] == 6000, "1 unit at 10000 cents, 0.60 factor"

        account = validate_success(api.get_account(scenario["acct"]["id"], DCM))
        assert account["open_claim_count"] == 1

        item = validate_success(api.get_item(scenario["items"][0]["id"], DCM))
        assert item["catalog_status"] == "SUSPENDED", (
            "1 damaged unit at 10000 cents reaches the inclusive trigger"
        )

    def test_the_stale_authorization_is_cancelled_and_the_order_is_returned(self, api):
        """PRD §3.9: "When the line's item has `long_tail` true, the supplier behind that
        item has its `commitment_breach_count` incremented by 1, and its
        `performance_rating_units` is recomputed as 100 minus ten times the new breach
        count".
        PRD §3.9: "Every return authorization on this order that is still in `return_status`
        `APPROVED` is set to `CANCELLED`, so stale authorizations that would otherwise be
        received twice are invalidated by the first receipt."
        PRD §3.9: "the order's `fulfillment_status` moves to `RETURNED`, its terminal
        value, with the order's `version` incremented by 1."

        Design: Difficulty/transitive_cascade/return_receipt_seven_hop_cascade
        """
        scenario = self._received(api)

        supplier = validate_success(api.get_supplier(scenario["supplier"]["id"], ADMIN))
        assert supplier["commitment_breach_count"] == 1
        assert supplier["performance_rating_units"] == 90

        second = validate_success(api.get_return(scenario["returns"][1]["id"], DCM))
        assert second["return_status"] == "CANCELLED", (
            "the stale restock authorization for the same order was invalidated"
        )

        order = validate_success(api.get_order(scenario["order"]["id"],
                                               scenario["acct_headers"]))
        assert order["fulfillment_status"] == "RETURNED"

        remaining, _meta = validate_paginated(api.list_returns(
            DCM, {"order_id": scenario["order"]["id"], "limit": 10, "offset": 0}))
        assert all(row["return_status"] != "APPROVED" for row in remaining), (
            "no return still holds an APPROVED restock authorization"
        )


class TestDcLockdownPostureFourHopCascade:
    """A posture change walks out four hops, and clearing it walks them back."""

    def _cut_off(self, api):
        return setup_shipped_order(api, qty=2, price=9000, on_hand=6, sku="SKU-4101")

    def test_raising_the_hold_holds_the_shipment_and_unwinds_the_pick_work(self, api):
        """PRD §3.8: "Opening an open quality or damage hold on a center drives the posture
        to `LOCKDOWN`, and the effect runs outward in four hops: first, every shipment at
        that center in `CUTOFF_CONFIRMED` becomes `HELD`; second, each of those shipments'
        orders has its `fulfillment_status` reverted from `PICKED` back to `ALLOCATED`".
        PRD §3.8: "third, each of those orders' lines has its `line_status` reverted from
        `PICKED` back to `ALLOCATED`; and fourth, each of those lines reopens its pick task
        by writing `shortage_disposition` `NONE` and returning `pick_status` to `PICKING`."

        Design: Difficulty/transitive_cascade/dc_lockdown_posture_four_hop_cascade
        """
        scenario = self._cut_off(api)
        dc = scenario["dc"]
        shipment = scenario["shipment"]
        task = scenario["tasks"][0]

        validate_success(api.reeducate(
            dc["id"], {"hold_action": "RAISE", "reason": "quality hold on the BOS lane"},
            DCM))

        held_dc = validate_success(api.get_distribution_center(dc["id"], DCM))
        assert held_dc["operations_posture"] == "LOCKDOWN"

        held_shipment = validate_success(api.get_shipment(shipment["id"], DCM))
        assert held_shipment["shipment_status"] == "HELD"

        order = validate_success(api.get_order(scenario["order"]["id"],
                                               scenario["acct_headers"]))
        assert order["fulfillment_status"] == "ALLOCATED"

        lines = list_lines(api, scenario["acct"], scenario["order"])
        assert lines[0]["line_status"] == "ALLOCATED"

        reopened = validate_success(api.get_pick_task(task["id"], DCM))
        assert reopened["pick_status"] == "PICKING"
        assert reopened["shortage_disposition"] == "NONE"

    def test_clearing_the_hold_restores_the_pair_without_touching_freight(self, api):
        """PRD §3.8: "Clearing the center's last open hold reverses the posture to `OPEN`,
        and the reversal runs in two hops: every `HELD` shipment at the center becomes
        `CUTOFF_CONFIRMED` again, and each of those shipments' orders has its
        `fulfillment_status` restored to `PICKED`."
        PRD §3.7: "This pair cycles for as long as the center's posture keeps changing."

        Design: Difficulty/transitive_cascade/dc_lockdown_posture_four_hop_cascade
        """
        scenario = self._cut_off(api)
        dc = scenario["dc"]
        shipment = scenario["shipment"]
        stamped_freight = shipment["freight_charge_cents"]

        validate_success(api.reeducate(
            dc["id"], {"hold_action": "RAISE", "reason": "quality hold on the BOS lane"},
            DCM))
        validate_success(api.reeducate(dc["id"], {"hold_action": "CLEAR"}, DCM))

        restored_dc = validate_success(api.get_distribution_center(dc["id"], DCM))
        assert restored_dc["operations_posture"] == "OPEN"

        restored_shipment = validate_success(api.get_shipment(shipment["id"], DCM))
        assert restored_shipment["shipment_status"] == "CUTOFF_CONFIRMED"
        assert restored_shipment["freight_charge_cents"] == stamped_freight, (
            "the posture cascade never re-prices the shipment's stored freight"
        )

        order = validate_success(api.get_order(scenario["order"]["id"],
                                               scenario["acct_headers"]))
        assert order["fulfillment_status"] == "PICKED"