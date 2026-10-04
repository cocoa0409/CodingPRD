"""Home-delivery booking guards: territory coverage, delivery-mode rules, DC
support, single-active-appointment, and the temporal window guards
(PRD §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    book_appointment,
    book_appointment_response,
    create_distribution_center,
    create_hd_order,
    create_licensee_order,
    create_order_payload,
    create_retail_account,
    create_territory,
    make_wholesale_buyer_headers,
    pick_order,
    run_cycle,
    setup_hd_context,
    setup_hd_picked_order,
    setup_open_cycle,
    submit_order,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

WS = "2026-09-10T09:00:00Z"
WE = "2026-09-10T12:00:00Z"


class TestTerritoryCoverage:
    def test_appointment_out_of_assigned_territory_rejected(self, api, platform_admin_headers):
        """PRD §3.6: "The delivery address region `region_code` must be covered by an
        `ASSIGNED` territory of the order's licensee, otherwise `ERR_OUT_OF_TERRITORY`."

        Design: Corner/errors/appointment_out_of_assigned_territory_rejected
        """
        ctx = setup_hd_picked_order(quantity=1)
        # T-PDX exists as a territory but is OPEN — assigned to nobody.
        create_territory(region_code="T-PDX", population_tier="SUBURBAN")
        resp = book_appointment_response(
            ctx["order"], ctx, WS, WE, zone="REGIONAL", region_code="T-PDX", crew_units=1
        )
        validate_error(resp, ApiErrorId.ERR_OUT_OF_TERRITORY.value)


class TestDeliveryModeRules:
    def test_retail_order_with_home_delivery_mode_rejected(self, api, platform_admin_headers):
        """PRD §3.5: "Home delivery is reserved for the licensed channel:
        `HOME_DELIVERY` on a retail-account order is `ERR_DELIVERY_MODE_NOT_ALLOWED`."

        Design: Corner/errors/retail_order_with_home_delivery_mode_rejected
        """
        ctx = setup_open_cycle()
        account = create_retail_account(credit_limit_cents=1_000_000)
        payload = create_order_payload(
            allocation_cycle_id=ctx["cycle"]["id"],
            product_line_id=ctx["line"]["id"],
            buyer_type="RETAIL_ACCOUNT",
            licensee_id=None,
            retail_account_id=account["id"],
            quantity=1,
            delivery_mode="HOME_DELIVERY",
        )
        resp = api.create_order(payload, make_wholesale_buyer_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_DELIVERY_MODE_NOT_ALLOWED.value)

    def test_appointment_on_freight_order_rejected(self, api, platform_admin_headers):
        """PRD §3.6: "booking against a `FREIGHT_TO_STORE` order is
        `ERR_DELIVERY_MODE_NOT_ALLOWED`."

        Design: Corner/errors/appointment_on_freight_order_rejected
        """
        ctx = setup_hd_context()
        freight = create_licensee_order(
            ctx["licensee"], ctx["cycle"], ctx["line"], quantity=1,
            delivery_mode="FREIGHT_TO_STORE",
        )
        submit_order(freight)
        run_cycle(ctx["cycle"]["id"])
        pick_order(freight["id"])  # PICKED, so the mode rule is what fires
        resp = book_appointment_response(
            get_order_fresh(freight["id"]), ctx, WS, WE, crew_units=1
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_MODE_NOT_ALLOWED.value)


def get_order_fresh(order_id):
    from test_helpers import get_order

    return get_order(order_id)


class TestDistributionCenterSupport:
    def test_appointment_on_dc_without_home_delivery_rejected(self, api, platform_admin_headers):
        """PRD §3.6: "The chosen `dc_id` must reference a distribution center whose
        `supports_home_delivery` is true, otherwise `ERR_HOME_DELIVERY_UNSUPPORTED`."

        Design: Corner/errors/appointment_on_dc_without_home_delivery_rejected
        """
        ctx = setup_hd_picked_order(quantity=1)
        dc2 = create_distribution_center(
            code="DC-TUK", supports_home_delivery=False, region_codes=["T-SEA"]
        )
        resp = book_appointment_response(
            ctx["order"], ctx, WS, WE, crew_units=1, dc_id=dc2["id"]
        )
        validate_error(resp, ApiErrorId.ERR_HOME_DELIVERY_UNSUPPORTED.value)


class TestSingleActiveAppointment:
    def test_second_active_appointment_on_same_order_rejected(self, api, platform_admin_headers):
        """PRD §3.6: "An order may carry at most one non-terminal appointment — one
        still `REQUESTED` or `CONFIRMED`; a second concurrent booking is
        `ERR_APPOINTMENT_ALREADY_ACTIVE`."

        Design: Corner/errors/second_active_appointment_on_same_order_rejected
        """
        ctx = setup_hd_picked_order(quantity=1)
        first = book_appointment(ctx["order"], ctx, WS, WE, crew_units=1)
        assert first["status"] == "REQUESTED"
        resp = book_appointment_response(
            ctx["order"],
            ctx,
            "2026-09-11T09:00:00Z",
            "2026-09-11T12:00:00Z",
            crew_units=1,
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_ALREADY_ACTIVE.value)


class TestTemporalWindowGuards:
    def test_window_in_past_rejected(self, api, platform_admin_headers):
        """PRD §3.6: "`window_start` strictly after the current time
        (`ERR_WINDOW_IN_PAST`); `window_start` at least `DELIVERY_MIN_LEAD_HOURS` — 48
        hours — ahead of the current time (`ERR_LEAD_TIME_TOO_SHORT`)"
        Both guards live in the same pipeline stage (PRD §2.8 stage 8, "all HTTP 422")
        and a past window necessarily violates both, so either error id satisfies the
        contract; the HTTP status is exact.

        Design: Corner/errors/window_in_past_rejected
        """
        ctx = setup_hd_picked_order(quantity=1)
        resp = book_appointment_response(
            ctx["order"],
            ctx,
            "2026-08-30T09:00:00Z",
            "2026-08-30T11:00:00Z",
            crew_units=1,
        )
        assert resp.status_code == 422, (
            f"expected 422, got {resp.status_code}: {resp.text}"
        )
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_WINDOW_IN_PAST.value,
                ApiErrorId.ERR_LEAD_TIME_TOO_SHORT.value,
            ],
        )

    def test_window_duration_sixty_minutes_rejected(self, api, platform_admin_headers):
        """PRD §3.6: "and a window duration between `WINDOW_MIN_MINUTES` (120 minutes)
        and `WINDOW_MAX_MINUTES` (360 minutes) inclusive
        (`ERR_WINDOW_DURATION_INVALID`)."

        Design: Corner/errors/window_duration_sixty_minutes_rejected
        """
        ctx = setup_hd_picked_order(quantity=1)
        # 60-minute window, lead time and territory valid: only the duration rule fires.
        resp = book_appointment_response(
            ctx["order"],
            ctx,
            "2026-09-10T09:00:00Z",
            "2026-09-10T10:00:00Z",
            crew_units=1,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_DURATION_INVALID.value)
