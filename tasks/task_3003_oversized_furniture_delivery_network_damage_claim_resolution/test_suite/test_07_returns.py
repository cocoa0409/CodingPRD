"""Return authorizations: approval window, disposition economics with the
tie-break to disposal, and the scheduled 30-day expiry."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    set_clock,
    setup_routed_network_order,
    setup_delivered_network_order,
    setup_drop_ship_supplier,
    place_drop_ship_order,
    deliver_drop_ship_shipment,
    create_item,
    api_client,
    TEST_USERS,
    make_customer_headers,
    SETUP_CLOCK,
)

ADMIN = TEST_USERS["network_admin_headers"]
HUB_OP = TEST_USERS["hub_operator_headers"]


class TestReturnApproveRequiresOrderDelivered:
    def test_approve_on_routed_order_fails_order_not_delivered(self, api):
        """PRD §3.8: "Approval requires the authorization to be `REQUESTED`
        (else `ERR_INVALID_STATE`), the order's `order_state` to be
        `DELIVERED` (else `ERR_ORDER_NOT_DELIVERED`), and the logical clock
        to be within 45 days of the order's delivery — an approval attempted
        later is rejected with `ERR_RETURN_WINDOW_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/return_approve_requires_order_delivered
        """
        refs = setup_routed_network_order()
        ra = validate_success(
            api.create_return_authorization(
                {"order_id": refs["order"]["id"], "reason": "BUYERS_REMORSE"},
                make_customer_headers(refs["customer"]["id"]),
            ),
            201,
        )
        resp = api.approve_return_authorization(ra["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DELIVERED)
        still = validate_success(api.get_return_authorization(ra["id"], ADMIN))
        assert still["status"] == "REQUESTED"

    def test_approve_on_delivered_order_succeeds(self, api):
        """PRD §3.8: "Approval requires the authorization to be `REQUESTED`
        (else `ERR_INVALID_STATE`), the order's `order_state` to be
        `DELIVERED` (else `ERR_ORDER_NOT_DELIVERED`), and the logical clock
        to be within 45 days of the order's delivery"

        Design: Difficulty/cross_entity_state_dependency/return_approve_requires_order_delivered
        """
        refs = setup_delivered_network_order()
        ra = validate_success(
            api.create_return_authorization(
                {"order_id": refs["order"]["id"], "reason": "BUYERS_REMORSE"},
                make_customer_headers(refs["customer"]["id"]),
            ),
            201,
        )
        approved = validate_success(
            api.approve_return_authorization(ra["id"], ADMIN), 200
        )
        assert approved["status"] == "APPROVED"


class TestReturnDispositionEconomicsAndTieBreak:
    def _delivered_drop_ship_order(self, api, refs, declared_value_cents, sku):
        item = create_item(
            refs["supplier"]["id"], sku=sku,
            dim_length_in=40, dim_width_in=40, dim_height_in=20,
            weight_lb=25, declared_value_cents=declared_value_cents,
            white_glove_eligible=False,
        )
        placed = place_drop_ship_order({**refs, "item": item})
        deliver_drop_ship_shipment(refs, placed["shipment"]["id"])
        return placed["order"]

    def _approve(self, api, order_id, customer, reason):
        ra = validate_success(
            api.create_return_authorization(
                {"order_id": order_id, "reason": reason},
                make_customer_headers(customer["id"]),
            ),
            201,
        )
        return validate_success(
            api.approve_return_authorization(ra["id"], ADMIN), 200
        )

    def test_return_disposition_economics_and_tie_break(self, api):
        """PRD §3.8: "The `reverse_haul_cost_cents` is the `ACTIVE` `LTL`
        lane's `base_rate_cents` to the customer's zone multiplied by a 1.20
        handling factor, rounded half-up to whole cents. The
        `refurb_value_cents` is a reason-driven fraction of the item's
        `declared_value_cents`, rounded half-up: 10% for `DAMAGE`, 40% for
        `BUYERS_REMORSE`, and 90% for `WRONG_ITEM`. The `disposition`
        compares the two: when the refurb value exceeds the reverse haul
        cost, the item comes back as `RETURN_TO_HUB`; otherwise — including
        an exact tie, where disposal wins at break-even — the disposition is
        `FIELD_DISPOSAL`."

        Design: Corner/calculations/return_disposition_economics_and_tie_break
        """
        from test_helpers import (
            create_supplier as _create_supplier,
            create_freight_lane as _create_lane,
            create_customer as _create_customer,
        )
        set_clock(SETUP_CLOCK)
        supplier = _create_supplier(
            "SUP-DS", legal_name="Return Source Co",
            drop_ship_enabled=True, lead_time_days=3,
        )
        _create_lane(
            leg_mode="LTL", dest_zone="ZONE_MA",
            base_rate_cents=40000, per_lb_rate_cents=20, transit_days=4,
        )
        customer = _create_customer(
            email="c3@example.com", full_name="Customer Three",
            destination_zone="ZONE_MA",
        )
        refs = {"supplier": supplier, "customer": customer}

        order_r1 = self._delivered_drop_ship_order(api, refs, 250000, "SKU-R1")
        order_r2 = self._delivered_drop_ship_order(api, refs, 300000, "SKU-R2")
        order_r3 = self._delivered_drop_ship_order(api, refs, 480000, "SKU-R3")

        ra1 = self._approve(api, order_r1["id"], customer, "DAMAGE")
        assert ra1["reverse_haul_cost_cents"] == 48000
        assert ra1["refurb_value_cents"] == 25000
        assert ra1["disposition"] == "FIELD_DISPOSAL"

        ra2 = self._approve(api, order_r2["id"], customer, "BUYERS_REMORSE")
        assert ra2["reverse_haul_cost_cents"] == 48000
        assert ra2["refurb_value_cents"] == 120000
        assert ra2["disposition"] == "RETURN_TO_HUB"

        ra3 = self._approve(api, order_r3["id"], customer, "DAMAGE")
        assert ra3["reverse_haul_cost_cents"] == 48000
        assert ra3["refurb_value_cents"] == 48000
        assert ra3["disposition"] == "FIELD_DISPOSAL", (
            "an exact tie resolves to FIELD_DISPOSAL — disposal wins at break-even"
        )


class TestReturnApproveAfter45Days:
    def _delivered_on_2026_09_12(self, api):
        """Network order completed with the logical clock at
        2026-09-12T11:00:00Z so delivered_at is pinned."""
        from test_helpers import setup_shipment_at_hub, book_appointment
        refs = setup_shipment_at_hub()
        appt = book_appointment(refs["shipment"])
        set_clock("2026-09-12T11:00:00Z")
        validate_success(api.complete_appointment(appt["id"], HUB_OP), 200)
        refs["order"] = validate_success(api.get_order(refs["order"]["id"], ADMIN))
        return refs

    def test_approve_at_day_45_succeeds(self, api):
        """PRD §3.8: "the logical clock to be within 45 days of the order's
        delivery — an approval attempted later is rejected with
        `ERR_RETURN_WINDOW_CLOSED`."

        Design: Corner/validations/return_approve_after_45_days_returns_window_closed
        """
        refs = self._delivered_on_2026_09_12(api)
        ra = validate_success(
            api.create_return_authorization(
                {"order_id": refs["order"]["id"], "reason": "BUYERS_REMORSE"},
                make_customer_headers(refs["customer"]["id"]),
            ),
            201,
        )
        set_clock("2026-10-27T11:00:00Z")  # exactly delivered_at + 45 days
        approved = validate_success(
            api.approve_return_authorization(ra["id"], ADMIN), 200
        )
        assert approved["status"] == "APPROVED"

    def test_approve_at_day_46_returns_window_closed(self, api):
        """PRD §3.8: "the logical clock to be within 45 days of the order's
        delivery — an approval attempted later is rejected with
        `ERR_RETURN_WINDOW_CLOSED`."

        Design: Corner/validations/return_approve_after_45_days_returns_window_closed
        """
        refs = self._delivered_on_2026_09_12(api)
        ra = validate_success(
            api.create_return_authorization(
                {"order_id": refs["order"]["id"], "reason": "BUYERS_REMORSE"},
                make_customer_headers(refs["customer"]["id"]),
            ),
            201,
        )
        set_clock("2026-10-28T11:00:01Z")  # one second past day 45
        resp = api.approve_return_authorization(ra["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_CLOSED)
        still = validate_success(api.get_return_authorization(ra["id"], ADMIN))
        assert still["status"] == "REQUESTED"


class TestReturnAuthorizationExpiry:
    def _approved_on_2026_09_12(self, api):
        refs = TestReturnApproveAfter45Days._delivered_on_2026_09_12(self, api)
        ra = validate_success(
            api.create_return_authorization(
                {"order_id": refs["order"]["id"], "reason": "DAMAGE"},
                make_customer_headers(refs["customer"]["id"]),
            ),
            201,
        )
        validate_success(api.approve_return_authorization(ra["id"], ADMIN), 200)
        refs["ra"] = ra
        return refs

    def test_approved_return_reads_approved_at_day_29(self, api):
        """PRD §3.8: "Alternatively, if the logical clock passes 30 days past
        `approved_at` without completion, the authorization expires
        automatically, moving to `EXPIRED`."

        Design: Corner/cross_cutting_complexity_layers/return_authorization_expires_30_days_after_approval
        """
        refs = self._approved_on_2026_09_12(api)
        set_clock("2026-10-11T11:00:00Z")  # approved_at + 29 days
        data = validate_success(api.get_return_authorization(refs["ra"]["id"], ADMIN))
        assert data["status"] == "APPROVED"

    def test_approved_return_expires_at_day_31_and_cannot_complete(self, api):
        """PRD §3.8: "Alternatively, if the logical clock passes 30 days past
        `approved_at` without completion, the authorization expires
        automatically, moving to `EXPIRED`."
        PRD §3.8: "From `APPROVED`, a `HubOperator` completes the return,
        moving the authorization to `COMPLETED` and the order's
        `fulfillment_state` from `FULFILLED` to `RETURNED`."

        Design: Corner/cross_cutting_complexity_layers/return_authorization_expires_30_days_after_approval
        """
        refs = self._approved_on_2026_09_12(api)
        set_clock("2026-10-13T11:00:01Z")  # approved_at + 31 days + 1s
        data = validate_success(api.get_return_authorization(refs["ra"]["id"], ADMIN))
        assert data["status"] == "EXPIRED"
        resp = api.complete_return_authorization(refs["ra"]["id"], HUB_OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
