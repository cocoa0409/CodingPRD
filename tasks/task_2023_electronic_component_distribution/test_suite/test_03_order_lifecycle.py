"""Order booking, acknowledgement snapshots, and lifecycle reads (PRD §3.3)."""
from test_helpers import (
    ADMIN,
    SALES,
    WAREHOUSE,
    ApiErrorId,
    acknowledge_order,
    assert_customer_order,
    assert_order_line,
    create_customer,
    create_order,
    get_order_lines,
    get_success_data,
    order_line_spec,
    setup_acknowledged_order,
    setup_allocated_order,
    setup_catalog,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInlineLineCreation:
    def test_order_lines_created_inline_start_open(self, api):
        """PRD §3.3: "Lines are created inline with the order and begin `OPEN`;
        the order itself begins `SUBMITTED`."
        PRD §2.3: "Order lines carry an additional tie-break: lines created
        together in a single order-creation request are ordered by their array
        index in that request."

        Design: Corner/entities/order_lines_created_inline_start_open
        """
        line, part = setup_catalog(line_code="LIN-OL")
        customer = create_customer(name="Cust OL")
        resp = api.create_order(
            {"customer_id": customer["id"],
             "lines": [order_line_spec(part["id"], 5, "2026-10-01"),
                       order_line_spec(part["id"], 7, "2026-11-01")]},
            SALES,
        )
        order = validate_success(resp, 201)
        assert_customer_order(order)
        assert order["status"] == "SUBMITTED"

        lines, meta = validate_paginated(
            api.list_order_lines(ADMIN, params={"order_id": order["id"]}))
        assert meta["total_count"] == 2
        for order_line, expected_qty in zip(lines, (5, 7)):
            assert_order_line(order_line)
            assert order_line["status"] == "OPEN"
            assert order_line["order_id"] == order["id"]
            assert order_line["quantity"] == expected_qty
            assert order_line["shipped_qty"] == 0
            assert order_line["allocated_qty"] == 0


class TestAcknowledge:
    def test_acknowledge_twice_rejected(self, api):
        """PRD §3.3: "It is permitted only from `SUBMITTED` — otherwise
        `ERR_ORDER_NOT_SUBMITTED` — and only while the customer remains
        `GOOD_STANDING`."

        Design: Corner/state_machines/acknowledge_twice_rejected
        """
        sc = setup_acknowledged_order(quantity=5, line_code="LIN-AK")
        order_after_ack = get_success_data(api.get_order(sc["order"]["id"], ADMIN))

        resp = api.acknowledge_order(sc["order"]["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SUBMITTED)

        order_final = get_success_data(api.get_order(sc["order"]["id"], ADMIN))
        assert order_final["status"] == "ACKNOWLEDGED"
        assert order_final["version"] == order_after_ack["version"], (
            "The rejected second acknowledge must not mutate the order"
        )

    def test_acknowledge_snapshots_line_terms(self, api):
        """PRD §3.3: "On acknowledgement the system snapshots onto every line
        the part's current `book_price_cents` as `unit_price_cents`, the line's
        `ncnr_snapshot` from the manufacturer line, and both window lengths as
        `cancel_window_days_snapshot` and `reschedule_window_days_snapshot`."
        PRD §3.3: "From those snapshots each line's `cancel_by_date` is computed
        as its `ship_date` minus `cancel_window_days_snapshot`."

        Design: Corner/state_machines/acknowledge_snapshots_line_terms
        """
        sc = setup_acknowledged_order(
            quantity=5, ship_date="2026-10-01", line_code="LIN-SN",
            line_kw={"cancel_window_days": 45, "reschedule_window_days": 15},
            part_kw={"book_price_cents": 1500})
        order_line = sc["order_line"]
        assert order_line["unit_price_cents"] == 1500
        assert order_line["ncnr_snapshot"] is False
        assert order_line["cancel_window_days_snapshot"] == 45
        assert order_line["reschedule_window_days_snapshot"] == 15
        assert order_line["cancel_by_date"] == "2026-08-17", (
            "cancel_by_date = ship_date 2026-10-01 minus 45 days"
        )
        order = get_success_data(api.get_order(sc["order"]["id"], ADMIN))
        assert order["open_exposure_cents"] == 7500, "5 units * 1500 cents"

    def test_immediate_consistency_read_after_write(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §2.8: "Mutations that cascade — a quarantine releasing reservations
        across many orders, an allocation publish touching many lines — refresh
        `updated_at` and increment `version` on each touched parent resource
        individually, so clients always observe a consistent read-after-write
        snapshot."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        line, part = setup_catalog(line_code="LIN-IC")
        customer = create_customer(name="Cust IC")
        order = create_order(customer["id"],
                             [order_line_spec(part["id"], 5, "2026-10-01")])
        created_version = order["version"]

        ack_resp = api.acknowledge_order(order["id"], SALES)
        ack_data = validate_success(ack_resp, 200)
        assert ack_data["status"] == "ACKNOWLEDGED"
        assert ack_data["version"] == created_version + 1, (
            "Acknowledge increments the order version by one (PRD §3.3)"
        )
        assert ack_data["open_exposure_cents"] == 7500

        fetched = get_success_data(api.get_order(order["id"], ADMIN))
        assert fetched["status"] == ack_data["status"]
        assert fetched["version"] == ack_data["version"]
        assert fetched["open_exposure_cents"] == ack_data["open_exposure_cents"]


class TestLineCancelRecompute:
    def test_order_exposure_recompute_on_line_cancel(self, api):
        """PRD §3.3: "A whole-order cancel zeroes the order's
        `open_exposure_cents` and `allocated_value_cents`; a single-line cancel
        recomputes them. Either way the order's `version` increments."

        Design: Corner/calculations/order_exposure_recompute_on_line_cancel
        """
        line, part = setup_catalog(line_code="LIN-EX")
        customer = create_customer(name="Cust EX")
        order = create_order(
            customer["id"],
            [order_line_spec(part["id"], 5, "2026-10-01"),
             order_line_spec(part["id"], 10, "2026-11-01")])
        order = acknowledge_order(order["id"])
        assert order["open_exposure_cents"] == 22500, "(5 + 10) * 1500"
        line1 = get_order_lines(order["id"])[0]

        cancelled = validate_success(
            api.cancel_order_line(order["id"], line1["id"], SALES), 200)
        assert cancelled["status"] == "CANCELLED"

        order_after = get_success_data(api.get_order(order["id"], ADMIN))
        assert order_after["open_exposure_cents"] == 15000, (
            "Only the surviving 10-unit line remains open"
        )
        assert order_after["status"] == "ACKNOWLEDGED", (
            "A single-line cancel does not cancel the order while another "
            "line remains open"
        )
        assert order_after["version"] > order["version"]


class TestHoldAndRelease:
    def test_release_hold_roundtrip(self, api):
        """PRD §3.6: "Equality is allowed; exceeding it rejects the ship with
        `ERR_CREDIT_LIMIT_EXCEEDED` and simultaneously moves the order from
        `ACKNOWLEDGED` or `PARTIALLY_SHIPPED` to `ON_HOLD`."
        PRD §3.6: "An order on hold can be released back to `ACKNOWLEDGED` by a
        `SalesRep` or `DistributorAdmin`; release from any state other than
        `ON_HOLD` is `ERR_ORDER_NOT_ACKNOWLEDGED`, and a successful release
        increments the order's `version`."

        Design: Corner/state_machines/release_hold_roundtrip
        """
        sc = setup_allocated_order(quantity=10, lot_qty=100, line_code="LIN-RH",
                                   customer_kw={"credit_limit_cents": 1000})
        ship_resp = api.ship_order_line(sc["order"]["id"], sc["order_line"]["id"],
                                        {"qty": 10}, WAREHOUSE)
        validate_error(ship_resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        held = get_success_data(api.get_order(sc["order"]["id"], ADMIN))
        assert held["status"] == "ON_HOLD"

        released = validate_success(
            api.release_hold_order(sc["order"]["id"], SALES), 200)
        assert released["status"] == "ACKNOWLEDGED"
        assert released["version"] == held["version"] + 1

        resp2 = api.release_hold_order(sc["order"]["id"], SALES)
        validate_error(resp2, ApiErrorId.ERR_ORDER_NOT_ACKNOWLEDGED)
        still = get_success_data(api.get_order(sc["order"]["id"], ADMIN))
        assert still["status"] == "ACKNOWLEDGED"
