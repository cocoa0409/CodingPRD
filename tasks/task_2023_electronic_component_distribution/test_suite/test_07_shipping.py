"""Shipping: FEFO picks, credit gate, date-code freshness, substitutes, and
claim genesis gating (PRD §3.6, §2.11)."""
from test_helpers import (
    ADMIN,
    SALES,
    WAREHOUSE,
    ApiErrorId,
    advance_clock,
    approve_registration,
    assert_lot_unit_conservation,
    create_allocation_run_for_part,
    create_customer,
    create_line,
    create_order,
    create_part,
    get_customer,
    get_lot,
    get_order,
    get_order_line,
    get_order_lines,
    get_part,
    get_single_line,
    get_success_data,
    order_line_spec,
    propose_alternate,
    publish_run,
    receive_lot,
    setup_acknowledged_order,
    setup_allocated_order,
    setup_catalog,
    ship_line,
    submit_registration,
    validate_error,
    validate_paginated,
)


class TestOrderAutoTransitions:
    def test_order_auto_transitions_partial_then_completed(self, api):
        """PRD §3.6: "The first successful ship on an order moves it from
        `ACKNOWLEDGED` to `PARTIALLY_SHIPPED`, and when every line is `SHIPPED`
        or `CANCELLED` with at least one line shipped, the order completes to
        `COMPLETED`."
        PRD §3.5: "A lot reaches its terminal `DEPLETED` state automatically
        when a ship leaves it with `qty_on_hand` at zero, `qty_reserved` at
        zero, and `qty_shipped` equal to `qty_received`".

        Design: Corner/state_machines/order_auto_transitions_partial_then_completed
        """
        line, part = setup_catalog(line_code="LIN-AT")
        lot = receive_lot(part["id"], qty_received=100)
        customer = create_customer(name="Cust AT")
        order = create_order(
            customer["id"],
            [order_line_spec(part["id"], 40, "2026-10-01"),
             order_line_spec(part["id"], 30, "2026-11-01")])
        get_success_data(api.acknowledge_order(order["id"], SALES))
        line1, line2 = get_order_lines(order["id"])
        publish_run(create_allocation_run_for_part(part["id"])["id"])

        ship_line(order["id"], line1["id"], 40)
        mid = get_success_data(api.get_order(order["id"], ADMIN))
        assert mid["status"] == "PARTIALLY_SHIPPED", (
            "First successful ship moves the order to PARTIALLY_SHIPPED"
        )

        ship_line(order["id"], line2["id"], 30)
        final = get_success_data(api.get_order(order["id"], ADMIN))
        assert final["status"] == "COMPLETED"
        assert get_order_line(line1["id"])["status"] == "SHIPPED"
        assert get_order_line(line2["id"])["status"] == "SHIPPED"

        part_after = get_part(part["id"])
        assert part_after["qty_on_hand"] == 30
        assert part_after["qty_reserved"] == 0
        lot_after = get_lot(lot["id"])
        assert lot_after["status"] == "AVAILABLE", (
            "30 units remain on hand, so the lot is not depleted"
        )
        assert_lot_unit_conservation(lot_after)


class TestShipPreconditions:
    def test_ship_open_line_rejected(self, api):
        """PRD §3.6: "A `WarehouseOps` operator ships against a line that is
        `ALLOCATED` — any other line state draws `ERR_LINE_NOT_ALLOCATED`".

        Design: Corner/errors/ship_open_line_rejected
        """
        sc = setup_acknowledged_order(quantity=5, line_code="LIN-SO")
        receive_lot(sc["part"]["id"], qty_received=100)
        resp = api.ship_order_line(sc["order"]["id"], sc["order_line"]["id"],
                                   {"qty": 5}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_ALLOCATED)
        after = get_order_line(sc["order_line"]["id"])
        assert after["shipped_qty"] == 0
        assert after["status"] == "OPEN"

    def test_ship_more_than_allocated_rejected(self, api):
        """PRD §3.6: "The shipped `qty` must be at least one and no more than
        the line's unshipped allocated remainder (`allocated_qty` minus
        `shipped_qty`); overshooting that remainder is
        `ERR_QUANTITY_EXCEEDS_AVAILABLE`."

        Design: Corner/errors/ship_more_than_allocated_rejected
        """
        sc = setup_allocated_order(quantity=10, lot_qty=5, line_code="LIN-OQ")
        order_line = get_order_line(sc["order_line"]["id"])
        assert order_line["allocated_qty"] == 5, (
            "Shortage: supply 5 against demand 10 allocates only 5"
        )
        resp = api.ship_order_line(sc["order"]["id"], order_line["id"],
                                   {"qty": 6}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_QUANTITY_EXCEEDS_AVAILABLE)
        after = get_order_line(order_line["id"])
        assert after["shipped_qty"] == 0
        assert after["allocated_qty"] == 5


class TestDateCodeFreshness:
    def test_date_code_at_limit_still_ships(self, api):
        """PRD §2.6: "A lot whose elapsed age in months is at most the part's
        limit is shippable — the boundary is inclusive, so a lot exactly at the
        limit is still fresh, while one month beyond it is stale and any ship
        pick touching it fails with `ERR_DATE_CODE_TOO_OLD`."
        PRD §3.6: "The customer's `open_balance_cents` rises by the shipment's
        value."

        Design: Corner/calculations/date_code_at_limit_still_ships
        """
        sc = setup_allocated_order(quantity=4, lot_qty=10, line_code="LIN-DC",
                                   part_kw={"date_code_limit_months": 24},
                                   lot_date_code="202408")
        advance_clock("2026-08-15T00:00:00Z")  # months_elapsed == 24 == limit
        shipped = ship_line(sc["order"]["id"], sc["order_line"]["id"], 4)
        assert shipped["status"] == "SHIPPED"
        assert shipped["shipped_qty"] == 4
        customer = get_customer(sc["customer"]["id"])
        assert customer["open_balance_cents"] == 6000, "4 units * 1500 cents"


class TestSafetyBeatsFiscal:
    def _setup_stale_lot_over_credit(self):
        """Allocated line whose only lot goes stale at 2026-09-01 and whose
        ship value exceeds the customer's credit limit."""
        return setup_allocated_order(
            quantity=5, lot_qty=10, ship_date="2026-09-10", line_code="LIN-S",
            part_kw={"date_code_limit_months": 24},
            customer_kw={"credit_limit_cents": 1000},
            lot_date_code="202408")

    def test_safety_beats_fiscal_at_ship(self, api):
        """PRD §2.11: "Likewise, safety beats fiscal: a ship that would fail
        both the date-code check and the credit check surfaces
        `ERR_DATE_CODE_TOO_OLD`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_at_ship
        """
        sc = self._setup_stale_lot_over_credit()
        advance_clock("2026-09-01T00:00:00Z")  # months_elapsed == 25 > 24

        resp = api.ship_order_line(sc["order"]["id"], sc["order_line"]["id"],
                                   {"qty": 3}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_DATE_CODE_TOO_OLD)
        order = get_order(sc["order"]["id"])
        assert order["status"] == "ACKNOWLEDGED", (
            "The credit check never ran, so the order never went ON_HOLD"
        )

    def test_safety_failure_leaves_no_side_effects(self, api):
        """PRD §2.11: "Likewise, safety beats fiscal: a ship that would fail
        both the date-code check and the credit check surfaces
        `ERR_DATE_CODE_TOO_OLD`."
        PRD §3.6: "Lots are picked FEFO: among the shipped part's lots with
        `qty_reserved` above zero, ordered by date code ascending and then
        creation time ascending, units move from `qty_reserved` to
        `qty_shipped`." (a rejected ship moves nothing)

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_at_ship
        """
        sc = self._setup_stale_lot_over_credit()
        advance_clock("2026-09-01T00:00:00Z")

        resp = api.ship_order_line(sc["order"]["id"], sc["order_line"]["id"],
                                   {"qty": 3}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_DATE_CODE_TOO_OLD)

        line_after = get_order_line(sc["order_line"]["id"])
        assert line_after["shipped_qty"] == 0
        lot_after = get_lot(sc["lot"]["id"])
        assert lot_after["qty_reserved"] == 5, "Reservation untouched"
        assert lot_after["qty_shipped"] == 0
        customer_after = get_customer(sc["customer"]["id"])
        assert customer_after["open_balance_cents"] == 0


class TestSubstituteShip:
    def test_ship_with_unapproved_substitute_rejected(self, api):
        """PRD §3.6: "When the shipment uses an approved substitute — the
        request carries a `substitute_part_id` — there must exist an
        alternate-part approval (§3.8) for this customer, this line's part as
        primary, and the substitute as alternate, in `APPROVED`; otherwise
        `ERR_ALTERNATE_NOT_APPROVED`."

        Design: Corner/errors/ship_with_unapproved_substitute_rejected
        """
        line = create_line(line_code="LIN-AL")
        primary = create_part(line["id"], part_number="PAL-1")
        alternate = create_part(line["id"], part_number="PAL-2",
                                standard_cost_cents=900, book_price_cents=1400)
        receive_lot(primary["id"], qty_received=50)
        receive_lot(alternate["id"], qty_received=50)
        customer = create_customer(name="Cust AL")
        approval = propose_alternate(customer["id"], primary["id"], alternate["id"])
        assert approval["status"] == "PROPOSED"

        order = create_order(customer["id"],
                             [order_line_spec(primary["id"], 5, "2026-10-01")])
        get_success_data(api.acknowledge_order(order["id"], SALES))
        order_line = get_single_line(order["id"])
        publish_run(create_allocation_run_for_part(primary["id"])["id"])

        resp = api.ship_order_line(order["id"], order_line["id"],
                                   {"qty": 2, "substitute_part_id": alternate["id"]},
                                   WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_ALTERNATE_NOT_APPROVED)
        assert get_order_line(order_line["id"])["shipped_qty"] == 0
        approval_after = get_success_data(
            api.get_alternate_approval(approval["id"], ADMIN))
        assert approval_after["status"] == "PROPOSED"


class TestClaimGenesisGate:
    def _setup_gate_scenario(self):
        """Allocated line qty 10 plus a registration that stays SUBMITTED until
        the test approves it."""
        sc = setup_allocated_order(quantity=10, lot_qty=100, line_code="LIN-G")
        registration = submit_registration(sc["customer"]["id"], sc["part"]["id"],
                                           registered_cost_cents=700,
                                           max_registered_qty=20)
        return sc, registration

    def test_ship_creates_no_claim_while_registration_submitted(self, api):
        """PRD §3.6: "The system selects the covering registration for the
        shipped part: the registration's `customer_id` must equal the order's
        customer, its `part_id` must equal the shipped part, its status must be
        `APPROVED`, the logical-clock date must fall within its closed validity
        window, and its `registered_qty_remaining` must exceed zero".

        Design: Difficulty/cross_entity_state_dependency/claim_creation_requires_registration_approved
        """
        sc, registration = self._setup_gate_scenario()
        assert registration["status"] == "SUBMITTED"

        shipped = ship_line(sc["order"]["id"], sc["order_line"]["id"], 5)
        assert shipped["shipped_qty"] == 5

        claims, meta = validate_paginated(
            api.list_claims(ADMIN, params={"order_line_id": sc["order_line"]["id"]}))
        assert meta["total_count"] == 0, (
            "A SUBMITTED registration covers nothing; no claim is auto-created"
        )

    def test_ship_creates_claim_once_registration_approved(self, api):
        """PRD §3.6: "When coverage is positive, a ship-and-debit claim is
        created in `SUBMITTED` with `qty` set to the covered amount,
        `registration_id` and `order_line_id` pointing at the covering
        registration and the shipped line, and both cost baselines snapshotted
        — `standard_cost_cents` from the part and `registered_cost_cents` from
        the registration. The registration's `registered_qty_remaining` falls
        by the covered amount".
        PRD §3.7: "`amount_provisional_cents` is the claim `qty` multiplied by
        the gap between its snapshotted `standard_cost_cents` and
        `registered_cost_cents` — exact integer-cents multiplication, no
        rounding."

        Design: Difficulty/cross_entity_state_dependency/claim_creation_requires_registration_approved
        """
        sc, registration = self._setup_gate_scenario()
        ship_line(sc["order"]["id"], sc["order_line"]["id"], 5)
        claims, meta = validate_paginated(
            api.list_claims(ADMIN, params={"order_line_id": sc["order_line"]["id"]}))
        assert meta["total_count"] == 0

        approve_registration(registration["id"])
        shipped = ship_line(sc["order"]["id"], sc["order_line"]["id"], 5)
        assert shipped["status"] == "SHIPPED", "10 of 10 shipped across both ships"

        claims, meta = validate_paginated(
            api.list_claims(ADMIN, params={"order_line_id": sc["order_line"]["id"]}))
        assert meta["total_count"] == 1
        claim = claims[0]
        assert claim["qty"] == 5
        assert claim["standard_cost_cents"] == 1000
        assert claim["registered_cost_cents"] == 700
        assert claim["amount_provisional_cents"] == 1500, "5 * (1000 - 700)"
        assert claim["status"] == "SUBMITTED"

        registration_after = get_success_data(
            api.get_design_registration(registration["id"], ADMIN))
        assert registration_after["registered_qty_remaining"] == 15
        assert registration_after["status"] == "APPROVED"
