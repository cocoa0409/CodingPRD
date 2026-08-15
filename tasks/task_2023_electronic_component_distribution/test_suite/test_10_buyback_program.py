"""Excess returns and shortage buy-backs: tiered credits, the 15% cap, and
window/qty/state gates (PRD §3.9)."""
from test_helpers import (
    ADMIN,
    SALES,
    WAREHOUSE,
    ApiErrorId,
    advance_clock,
    approve_buyback,
    create_buyback,
    get_success_data,
    setup_buyback_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def _receive(api, buyback_id, received_qty, lot_date_code="202601"):
    return api.receive_buyback(buyback_id,
                               {"received_qty": received_qty,
                                "lot_date_code": lot_date_code},
                               WAREHOUSE)


class TestTierCrossing:
    def test_buyback_provisional_credit_tier_one(self, api):
        """PRD §3.9: "For an excess return, `price_basis_cents` is the lesser of
        the order line's snapshotted `unit_price_cents` and the part's current
        `book_price_cents`".
        PRD §3.9: "The restocking fee is tiered by whole days elapsed between
        the line's `last_shipped_at` and the evaluation instant, and the
        selected fraction is recorded as `fee_pct`: within ninety days the fee
        fraction is 0.10; from ninety-one through one hundred eighty days it is
        0.25".
        PRD §3.9: "The provisional credit, computed at request time, is
        `provisional_credit_cents` — the offered `qty` multiplied by the price
        basis and by one minus the request-date `fee_pct`, the full product
        rounded half-up to integer cents."

        Design: Difficulty/combinatorial_formula/buyback_credit_tier_crossing
        """
        sc = setup_buyback_scenario(quantity=10, lot_qty=100,
                                    trailing_purchases_cents=1_000_000)
        advance_clock("2026-09-20T00:00:00Z")  # 50 days after the 2026-08-01 ship

        bb = create_buyback(sc["customer"]["id"], sc["order_line"]["id"],
                            kind="EXCESS_RETURN", qty=10)
        assert bb["price_basis_cents"] == 1500, "min(unit_price 1500, book 1500)"
        assert bb["fee_pct"] == 0.10, "Day 50 falls in the first tier"
        assert bb["provisional_credit_cents"] == 13500, (
            "round_half_up(10 * 1500 * (1 - 0.10))"
        )
        assert bb["status"] == "REQUESTED"

    def test_buyback_final_credit_tier_crossing(self, api):
        """PRD §3.9: "Receipt re-prices the credit at the receipt date: the fee
        tier is re-selected from the whole days between `last_shipped_at` and
        the receive instant, so a receipt landing in a later tier yields a
        smaller credit than the provisional; `final_credit_cents` is the
        received quantity times the price basis times one minus that
        receipt-date fee fraction, rounded half-up to integer cents."
        PRD §3.9: "The order line's `returned_qty` rises by the received
        amount, and the returned units re-enter the building as a brand-new
        inventory lot: `OPEN_MARKET` sourcing, `authenticity`
        `PENDING_INSPECTION`, status `IN_INSPECTION`, `qty_received` equal to
        the received quantity, `date_code` taken from the receipt's
        `lot_date_code`."

        Design: Difficulty/combinatorial_formula/buyback_credit_tier_crossing
        """
        sc = setup_buyback_scenario(quantity=10, lot_qty=100,
                                    trailing_purchases_cents=1_000_000)
        advance_clock("2026-09-20T00:00:00Z")  # day 50: provisional tier 1
        bb = create_buyback(sc["customer"]["id"], sc["order_line"]["id"],
                            kind="EXCESS_RETURN", qty=10)
        assert bb["provisional_credit_cents"] == 13500
        approve_buyback(bb["id"])

        advance_clock("2026-11-09T00:00:00Z")  # day 100: receipt lands in tier 2
        received = validate_success(_receive(api, bb["id"], 10), 200)
        assert received["status"] == "RECEIVED"
        assert received["received_qty"] == 10
        assert received["final_credit_cents"] == 11250, (
            "round_half_up(10 * 1500 * (1 - 0.25)) — tier re-selected at receipt"
        )
        assert received["final_credit_cents"] != received["provisional_credit_cents"]

        line_after = get_success_data(api.get_order_line(sc["order_line"]["id"], ADMIN))
        assert line_after["returned_qty"] == 10

        lots, meta = validate_paginated(
            api.list_lots(ADMIN, params={"part_id": sc["part"]["id"]}))
        assert meta["total_count"] == 2, "The original lot plus the return lot"
        return_lot = [l for l in lots if l["id"] != sc["lot"]["id"]][0]
        assert return_lot["source_type"] == "OPEN_MARKET"
        assert return_lot["authenticity"] == "PENDING_INSPECTION"
        assert return_lot["status"] == "IN_INSPECTION"
        assert return_lot["qty_received"] == 10
        assert return_lot["date_code"] == "202601"


class TestCapBoundary:
    def _setup_cap_scenario(self, api):
        """One line of 200 shipped at the default clock (day 0, tier 1 fee);
        customer trailing purchases 990000 -> cap floor(0.15 * 990000) ==
        148500; bb1 for 109 units APPROVED (147150 used)."""
        sc = setup_buyback_scenario(quantity=200, lot_qty=250,
                                    trailing_purchases_cents=990_000)
        bb1 = create_buyback(sc["customer"]["id"], sc["order_line"]["id"],
                             kind="EXCESS_RETURN", qty=109)
        assert bb1["provisional_credit_cents"] == 147150, (
            "109 * 1500 * (1 - 0.10)"
        )
        approve_buyback(bb1["id"])
        return sc, bb1

    def test_buyback_cap_inclusive_boundary_allowed(self, api):
        """PRD §3.9: "the cap is the floor of fifteen percent of
        `trailing_12mo_purchases_cents`, and the customer's usage toward the cap
        is the sum over their `EXCESS_RETURN` buy-backs created within the
        trailing three hundred sixty-five days and still in `REQUESTED`,
        `APPROVED`, or `RECEIVED` — counting each request's final credit when
        received, else its provisional credit. The new request is allowed only
        while used-plus-new-provisional stays at or under the cap; equality is
        allowed".

        Design: Difficulty/boundary_precision_check/buyback_cap_inclusive_boundary
        """
        sc, bb1 = self._setup_cap_scenario(api)
        bb2 = create_buyback(sc["customer"]["id"], sc["order_line"]["id"],
                             kind="EXCESS_RETURN", qty=1)
        assert bb2["provisional_credit_cents"] == 1350
        # 147150 + 1350 == 148500 == cap exactly -> allowed (inclusive).
        assert bb2["status"] == "REQUESTED"

    def test_buyback_cap_exceeded_one_unit_over(self, api):
        """PRD §3.9: "The new request is allowed only while used-plus-new-provisional
        stays at or under the cap; equality is allowed, and a breach is
        `ERR_BUYBACK_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/buyback_cap_inclusive_boundary
        """
        sc, bb1 = self._setup_cap_scenario(api)
        create_buyback(sc["customer"]["id"], sc["order_line"]["id"],
                       kind="EXCESS_RETURN", qty=1)  # lands exactly on the cap

        resp = api.create_buyback(
            {"customer_id": sc["customer"]["id"],
             "order_line_id": sc["order_line"]["id"],
             "kind": "EXCESS_RETURN", "qty": 1},
            SALES)
        validate_error(resp, ApiErrorId.ERR_BUYBACK_CAP_EXCEEDED)


class TestWindowAndQtyGates:
    def test_buyback_window_closed_day181_rejected(self, api):
        """PRD §3.9: "An excess return is only lawful within one hundred eighty
        days of the line's `last_shipped_at`, inclusive — at exactly one
        hundred eighty days the request is still allowed; later, it is
        `ERR_BUYBACK_WINDOW_CLOSED`."

        Design: Corner/errors/buyback_window_closed_day181_rejected
        """
        sc = setup_buyback_scenario(quantity=10, lot_qty=100,
                                    trailing_purchases_cents=1_000_000)
        advance_clock("2027-01-29T00:00:00Z")  # 181 days after the ship
        resp = api.create_buyback(
            {"customer_id": sc["customer"]["id"],
             "order_line_id": sc["order_line"]["id"],
             "kind": "EXCESS_RETURN", "qty": 1},
            SALES)
        validate_error(resp, ApiErrorId.ERR_BUYBACK_WINDOW_CLOSED)
        buybacks, meta = validate_paginated(
            api.list_buybacks(ADMIN, params={"customer_id": sc["customer"]["id"]}))
        assert meta["total_count"] == 0

    def test_buyback_qty_over_shipped_rejected(self, api):
        """PRD §3.9: "the offered `qty`, which must be positive and no more
        than the line's `shipped_qty` minus quantities already covered by other
        `REQUESTED`, `APPROVED`, or `RECEIVED` buy-backs on that line —
        overshooting is `ERR_BUYBACK_QTY_EXCEEDED`."

        Design: Corner/errors/buyback_qty_over_shipped_rejected
        """
        sc = setup_buyback_scenario(quantity=10, lot_qty=100,
                                    trailing_purchases_cents=1_000_000)
        resp = api.create_buyback(
            {"customer_id": sc["customer"]["id"],
             "order_line_id": sc["order_line"]["id"],
             "kind": "EXCESS_RETURN", "qty": 11},
            SALES)
        validate_error(resp, ApiErrorId.ERR_BUYBACK_QTY_EXCEEDED)

    def test_shortage_buyback_without_shortage_rejected(self, api):
        """PRD §3.9: "A shortage buy-back instead requires that shortage
        conditions actually be in effect for the part: a `PUBLISHED` allocation
        run must exist for it whose `total_demand_qty` exceeds its
        `total_supply_qty`, otherwise `ERR_SHORTAGE_NOT_IN_EFFECT`."

        Design: Corner/errors/shortage_buyback_without_shortage_rejected
        """
        sc = setup_buyback_scenario(quantity=10, lot_qty=100,
                                    trailing_purchases_cents=1_000_000)
        # The part's only PUBLISHED run had supply 100 >= demand 10.
        assert sc["run"]["status"] == "PUBLISHED"
        assert sc["run"]["total_supply_qty"] == 100
        assert sc["run"]["total_demand_qty"] == 10

        resp = api.create_buyback(
            {"customer_id": sc["customer"]["id"],
             "order_line_id": sc["order_line"]["id"],
             "kind": "SHORTAGE_BUYBACK", "qty": 5},
            SALES)
        validate_error(resp, ApiErrorId.ERR_SHORTAGE_NOT_IN_EFFECT)
        buybacks, meta = validate_paginated(
            api.list_buybacks(ADMIN, params={"customer_id": sc["customer"]["id"]}))
        assert meta["total_count"] == 0


class TestReceiveStateGate:
    def test_buyback_receive_before_approval_rejected(self, api):
        """PRD §3.9: "Physical receipt is the warehouse's final act: a
        `WarehouseOps` operator receives against an `APPROVED` request,
        reporting the `received_qty` — at least one and no more than the
        requested `qty`, else `ERR_BUYBACK_QTY_EXCEEDED` — and the returned
        stock's `lot_date_code`."

        Design: Corner/errors/buyback_receive_before_approval_rejected
        """
        sc = setup_buyback_scenario(quantity=10, lot_qty=100,
                                    trailing_purchases_cents=1_000_000)
        bb = create_buyback(sc["customer"]["id"], sc["order_line"]["id"],
                            kind="EXCESS_RETURN", qty=2)
        assert bb["status"] == "REQUESTED"

        resp = _receive(api, bb["id"], 2)
        validate_error(resp, ApiErrorId.ERR_BUYBACK_INVALID_STATE)
        after = get_success_data(api.get_buyback(bb["id"], ADMIN))
        assert after["status"] == "REQUESTED"
        assert after.get("final_credit_cents") is None, (
            "The final credit is computed only at receipt"
        )
