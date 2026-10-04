"""Offer window geometry (half-open, midnight wrap) and app-only enforcement."""
from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    add_line,
    api_client,
    create_customer_payload,
    get_location,
    api_client,
    create_customer_payload,
    get_location,
    create_location,
    create_menu_item,
    create_offer_payload,
    create_service_target,
    create_stall,
    intercom_checkin,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["shift_manager_headers"]


def _setup_order_with_night_offer(code, window_start="22:00", window_end="02:00"):
    """Location + service target + 400c drink + 50%% night offer + DRAFT
    intercom order with one line. Offer applicability is pinned to the
    check-in instant."""
    location = create_location(code=code, stall_capacity=2)
    create_service_target(location["id"])
    item = create_menu_item(
        sku=f"DR-{code}", name="Night Drink", category="DRINK", base_price_cents=400
    )
    validate_success(
        api_create_offer(
            location["id"],
            create_offer_payload(
                code="NIGHT", kind="PROMO", discount_type="PERCENT_OFF_ORDER",
                discount_value=50, window_start_local=window_start,
                window_end_local=window_end, app_only=False,
            ),
        ),
        201,
    )
    stall = create_stall(location["id"], stall_number=1)
    order = intercom_checkin(location["id"], stall["id"])
    add_line(location["id"], order["id"], item["id"])
    return location, order


def api_create_offer(location_id, payload):
    from test_helpers import api_client

    return api_client.create_offer(location_id, payload, ADMIN)


class TestOfferWindowHalfOpenMidnightWrap:
    def test_offer_window_end_is_exclusive_at_midnight_wrap(self, api):
        """PRD: "The daily window runs from `window_start_local` inclusive to
        `window_end_local` exclusive, with equal endpoints meaning all-day"

        A 22:00-02:00 offer does not apply to an order whose check-in local
        time is exactly 02:00: placement leaves offer_discount_cents at 0 on
        the 400c drink.

        Design: Difficulty/resource_temporal_overlap/offer_window_half_open_midnight_wrap
        """
        set_clock(TEST_DEFAULTS["CLOCK_0200_LOCAL"])  # 02:00 local == exclusive end
        location, order = _setup_order_with_night_offer("DIFF-WIN1")

        placed = validate_success(
            api.place_order(location["id"], order["id"], {}, MANAGER), 200
        )
        assert placed["offer_discount_cents"] == 0
        assert placed["subtotal_cents"] == 400

    def test_offer_window_applies_inside_midnight_wrap(self, api):
        """PRD: "The daily window runs from `window_start_local` inclusive to
        `window_end_local` exclusive, with equal endpoints meaning all-day"

        The same 22:00-02:00 offer applies to an order checked in at 23:30
        local: the 50% percent-off discount takes 200c off the 400c drink.

        Design: Difficulty/resource_temporal_overlap/offer_window_half_open_midnight_wrap
        """
        # 23:30 local (America/Chicago) == 2026-09-01T04:30:00Z.
        set_clock("2026-09-01T04:30:00Z")
        location, order = _setup_order_with_night_offer("DIFF-WIN2")

        placed = validate_success(
            api.place_order(location["id"], order["id"], {}, MANAGER), 200
        )
        assert placed["offer_discount_cents"] == 200
        assert placed["subtotal_cents"] == 400


class TestAppOnlyOfferEnforcement:
    def test_app_only_offer_rejected_for_intercom_guest(self, api):
        """PRD: "A placer may also force a specific offer by naming an
        `offer_code`; if that offer is not `ACTIVE`, its window does not
        contain the check-in time, or its app-only restriction is not met,
        placement fails with `ERR_OFFER_NOT_APPLICABLE`."

        An app-restricted offer named on a guest intercom order cannot apply.

        Design: Corner/cross_cutting_layers/app_only_offer_rejected_for_intercom_guest
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        location = create_location(code="CRN-APP1", stall_capacity=2)
        create_service_target(location["id"])
        validate_success(
            api_create_offer(
                location["id"],
                create_offer_payload(
                    code="APPONLY", kind="APP_ONLY", discount_type="PERCENT_OFF_ORDER",
                    discount_value=25, window_start_local="00:00",
                    window_end_local="23:59", app_only=True,
                ),
            ),
            201,
        )
        item = create_menu_item(sku="AO-F", name="F", category="FOOD", base_price_cents=500)
        stall = create_stall(location["id"], stall_number=1)
        order = intercom_checkin(location["id"], stall["id"])
        add_line(location["id"], order["id"], item["id"])

        resp = api.place_order(location["id"], order["id"], {"offer_code": "APPONLY"}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_APPLICABLE)

    def test_app_only_offer_rejected_for_intercom_customer_order(self, api):
        """PRD: "A placer may also force a specific offer by naming an
        `offer_code`; if that offer is not `ACTIVE`, its window does not
        contain the check-in time, or its app-only restriction is not met,
        placement fails with `ERR_OFFER_NOT_APPLICABLE`."

        An app-restricted offer named on an intercom order placed for a
        registered customer still cannot apply, because the channel is not
        APP_CHECKIN.

        Design: Corner/cross_cutting_layers/app_only_offer_rejected_for_intercom_guest
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        location = create_location(code="CRN-APP2", stall_capacity=2)
        create_service_target(location["id"])
        validate_success(
            api_create_offer(
                location["id"],
                create_offer_payload(
                    code="APPONLY2", kind="APP_ONLY", discount_type="PERCENT_OFF_ORDER",
                    discount_value=25, window_start_local="00:00",
                    window_end_local="23:59", app_only=True,
                ),
            ),
            201,
        )
        customer = validate_success(
            api_client.create_customer(
                create_customer_payload(email="ao2@x.com", display_name="AO2"), ADMIN
            ),
            201,
        )
        item = create_menu_item(sku="AO-F2", name="F2", category="FOOD", base_price_cents=500)
        stall = create_stall(location["id"], stall_number=1)

        # Intercom check-in naming the customer keeps channel STALL_INTERCOM.
        version = get_location(location["id"])["version"]
        order = validate_success(
            api.checkin(
                location["id"], stall["id"],
                {"expected_location_version": version, "customer_id": customer["id"]},
                MANAGER,
            ),
            201,
        )
        add_line(location["id"], order["id"], item["id"])

        resp = api.place_order(location["id"], order["id"], {"offer_code": "APPONLY2"}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_APPLICABLE)
