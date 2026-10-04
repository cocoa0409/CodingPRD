"""Order ship/cancel: invalid transitions, terminal lockdown, compensating invariants."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_customer,
    get_inventory_position,
    get_order_lines,
    make_customer,
    make_customer_headers,
    make_order,
    make_stocked_priced_part,
    submit_order,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["supply_planner_headers"]


def _submitted_order(api, part_number="CD40XX", on_hand=100, price=100, qty=10,
                     credit=1_000_000, tier="STANDARD", channel="DIRECT_FIELD",
                     demand=None, buffer_multiple=None):
    part, _ = make_stocked_priced_part(
        part_number, on_hand=on_hand, unit_price_cents=price,
        demand_rate=demand, buffer_multiple=buffer_multiple,
    )
    cust = make_customer(tier=tier, channel=channel, credit_limit_cents=credit)
    order = make_order(cust["id"], [{"part_id": part["id"], "quantity": qty}])
    submitted = submit_order(order["id"], cust["id"])
    return part, cust, order, submitted


class TestOrderFulfillment:
    def test_ship_backordered_order_rejected(self, api):
        """PRD §3.4: "Shipping is performed by a `SupplyPlanner` and only from
        `ALLOCATED` — shipping from any other state is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/ship_backordered_order_rejected
        """
        part, cust, order, submitted = _submitted_order(
            api, part_number="TLV2462IDR", on_hand=50, qty=10,
            demand=40, buffer_multiple=1.5,
        )
        assert submitted["status"] == "BACKORDERED"

        res = api.ship_order(order["id"], PLANNER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_order(order["id"], PLANNER), 200)
        assert after["status"] == "BACKORDERED"
        assert get_inventory_position(part["id"])["on_hand_units"] == 50

    def test_cancel_shipped_order_terminal_lockdown(self, api):
        """PRD §3.4: "Cancelling a `SHIPPED` or already `CANCELLED` order is
        `ERR_INVALID_STATE`."
        PRD §3.4: "Shipping decrements each line's part `on_hand_units` by the line's
        `awarded_units` and releases the reservation (`reserved_units` decreases by
        the same amount), decreases the customer's `open_exposure_cents` by the
        order's `total_cents`, recomputes `posture` for every shipped part, increments
        the order's `version`, and moves the order to the terminal state `SHIPPED`."

        Design: Corner/state_machines/cancel_shipped_order_terminal_lockdown
        """
        part, cust, order, submitted = _submitted_order(
            api, part_number="CD4011BE", on_hand=100, qty=10
        )
        assert submitted["status"] == "ALLOCATED"
        shipped = validate_success(api.ship_order(order["id"], PLANNER), 200)
        assert shipped["status"] == "SHIPPED"

        res = api.cancel_order(order["id"], make_customer_headers(cust["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_order(order["id"], PLANNER), 200)
        assert after["status"] == "SHIPPED"
        pos = get_inventory_position(part["id"])
        assert pos["on_hand_units"] == 90
        assert pos["reserved_units"] == 0
        assert get_customer(cust["id"])["open_exposure_cents"] == 0

    def test_allocate_then_cancel_conserves_physical_units(self, api):
        """PRD §3.4: "Cancelling an `ALLOCATED` or `BACKORDERED` order releases every
        line's reservation: each part's `reserved_units` decreases by the line's
        `awarded_units`, each line's `awarded_units` resets to 0, the customer's
        `open_exposure_cents` decreases by the order's `total_cents`, `posture` is
        recomputed for every ordered part, and the order's `version` increments."

        Design: Difficulty/compensating_invariant/allocate_then_cancel_conserves_physical_units
        """
        part, cust, order, submitted = _submitted_order(
            api, part_number="CD4050BE", on_hand=500, qty=200, credit=10_000_000
        )
        assert submitted["status"] == "ALLOCATED"
        mid = get_inventory_position(part["id"])
        assert mid["on_hand_units"] == 500 and mid["reserved_units"] == 200

        cancelled = validate_success(
            api.cancel_order(order["id"], make_customer_headers(cust["id"])), 200
        )
        assert cancelled["status"] == "CANCELLED"

        pos = get_inventory_position(part["id"])
        assert pos["on_hand_units"] == 500, "physical stock bit-identical to baseline"
        assert pos["reserved_units"] == 0
        for line in get_order_lines(order["id"]):
            assert line["awarded_units"] == 0

    def test_cancel_backordered_order_releases_reservations(self, api):
        """PRD §3.4: "Cancelling an `ALLOCATED` or `BACKORDERED` order releases every
        line's reservation: each part's `reserved_units` decreases by the line's
        `awarded_units`, each line's `awarded_units` resets to 0, the customer's
        `open_exposure_cents` decreases by the order's `total_cents`, `posture` is
        recomputed for every ordered part, and the order's `version` increments."

        Design: Difficulty/compensating_invariant/allocate_then_cancel_conserves_physical_units
        """
        normal_part, _ = make_stocked_priced_part(
            "SN74HC08N", on_hand=100, unit_price_cents=100,
            site_name="DFAB", process_technology="CMOS_180NM",
        )
        shortage_part, _ = make_stocked_priced_part(
            "TPS5432DDAR", on_hand=50, unit_price_cents=100,
            demand_rate=40, buffer_multiple=1.5,
            site_name="DFAB", process_technology="ANALOG_BIPOLAR",
        )
        cust = make_customer(name="Mixed Cancel", credit_limit_cents=10_000_000)
        order = make_order(
            cust["id"],
            [
                {"part_id": normal_part["id"], "quantity": 5},
                {"part_id": shortage_part["id"], "quantity": 5},
            ],
        )
        submitted = submit_order(order["id"], cust["id"])
        assert submitted["status"] == "BACKORDERED"
        assert get_inventory_position(normal_part["id"])["reserved_units"] == 5
        assert get_customer(cust["id"])["open_exposure_cents"] == 1000

        cancelled = validate_success(
            api.cancel_order(order["id"], make_customer_headers(cust["id"])), 200
        )
        assert cancelled["status"] == "CANCELLED"
        assert get_inventory_position(normal_part["id"])["reserved_units"] == 0
        assert get_inventory_position(shortage_part["id"])["reserved_units"] == 0
        assert get_customer(cust["id"])["open_exposure_cents"] == 0
        for line in get_order_lines(order["id"]):
            assert line["awarded_units"] == 0

    def test_submit_then_cancel_conserves_customer_exposure(self, api):
        """PRD §3.2: "`open_exposure_cents` is the sum of `total_cents` over the
        customer's orders in `ALLOCATED` or `BACKORDERED` status, plus the sum of
        `ltb_value_cents` over the customer's `APPROVED` lifetime buys."
        PRD §3.4: "Cancelling an `ALLOCATED` or `BACKORDERED` order releases every
        line's reservation: each part's `reserved_units` decreases by the line's
        `awarded_units`, each line's `awarded_units` resets to 0, the customer's
        `open_exposure_cents` decreases by the order's `total_cents`, `posture` is
        recomputed for every ordered part, and the order's `version` increments."

        Design: Difficulty/compensating_invariant/submit_then_cancel_conserves_customer_exposure
        """
        part, cust, order, submitted = _submitted_order(
            api, part_number="MCP6002-I/P", on_hand=100, price=210, qty=40,
            credit=10_000_000, tier="SMALL", channel="DIRECT_ONLINE",
        )
        assert submitted["subtotal_cents"] == 8400
        assert submitted["service_fee_cents"] == 500
        assert submitted["total_cents"] == 8900
        assert get_customer(cust["id"])["open_exposure_cents"] == 8900

        cancelled = validate_success(
            api.cancel_order(order["id"], make_customer_headers(cust["id"])), 200
        )
        assert cancelled["status"] == "CANCELLED"
        assert get_customer(cust["id"])["open_exposure_cents"] == 0

    def test_ship_releases_customer_exposure(self, api):
        """PRD §3.4: "Shipping decrements each line's part `on_hand_units` by the
        line's `awarded_units` and releases the reservation (`reserved_units`
        decreases by the same amount), decreases the customer's `open_exposure_cents`
        by the order's `total_cents`, recomputes `posture` for every shipped part,
        increments the order's `version`, and moves the order to the terminal state
        `SHIPPED`."

        Design: Difficulty/compensating_invariant/submit_then_cancel_conserves_customer_exposure
        """
        part, cust, order, submitted = _submitted_order(
            api, part_number="MCP6003-I/P", on_hand=100, price=210, qty=40,
            credit=10_000_000, tier="SMALL", channel="DIRECT_ONLINE",
        )
        assert submitted["status"] == "ALLOCATED"
        assert get_customer(cust["id"])["open_exposure_cents"] == 8900

        shipped = validate_success(api.ship_order(order["id"], PLANNER), 200)
        assert shipped["status"] == "SHIPPED"
        assert get_customer(cust["id"])["open_exposure_cents"] == 0
        pos = get_inventory_position(part["id"])
        assert pos["on_hand_units"] == 60
        assert pos["reserved_units"] == 0
