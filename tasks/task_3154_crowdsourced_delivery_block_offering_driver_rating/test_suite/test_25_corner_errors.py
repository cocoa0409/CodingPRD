"""Corner — errors: offer expiry, check-in window closed."""

from test_helpers import (
    TEST_USERS,
    api_client,
    set_clock,
    create_station,
    create_published_block,
    onboard_active_driver,
    create_offer,
    accept_block,
    get_assignment,
    run_surge_cycle,
    get_offer,
    make_driver_headers,
    validate_error,
)
from test_helpers.api_errors import ApiErrorId

STATION_OPS = TEST_USERS["station_ops_headers"]


class TestOfferExpired:
    def test_error_offer_expired_at_accept_rejected(self, api):
        """PRD §3.3: "Accepting or declining after the offer's `expires_at` fails with
        `ERR_OFFER_EXPIRED`, and any driver other than the addressee who touches the
        offer gets `ERR_OFFER_WRONG_DRIVER`."
        PRD §3.3: "Offers do not live forever. A surge cycle expires any `OFFERED` offer
        whose `expires_at` has been reached, moving it to `EXPIRED`."

        Design: Corner/errors/error_offer_expired_at_accept_rejected
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T10:00:00Z",
            ends_at="2026-09-01T12:00:00Z",
            base_pay_cents=4000,
        )
        offer = create_offer(
            block["id"],
            driver["id"],
            tier_floor="STANDARD",
            expires_at="2026-09-01T06:00:00Z",
        )

        # At exactly expires_at: the offer's time is up (boundary inclusive).
        set_clock("2026-09-01T06:00:00Z")
        resp = api_client.accept_offer(
            offer["id"],
            {"vehicle_id": vehicle["id"]},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)

        # The subsequent surge cycle persists the expiry.
        run_surge_cycle(station["id"], station["version"])
        assert get_offer(offer["id"])["status"] == "EXPIRED"


class TestCheckinWindowClosed:
    def test_error_checkin_window_closed_after_grace_rejected(self, api):
        """PRD §3.4: "Check-in moves the assignment from `ASSIGNED` to `CHECKED_IN` and
        is bounded on both sides: it may not happen earlier than 30 minutes before the
        block's `starts_at` (otherwise `ERR_CHECKIN_TOO_EARLY`), and may not happen
        later than 15 minutes after `starts_at` (otherwise `ERR_CHECKIN_WINDOW_CLOSED`);
        both bounds are inclusive."

        Design: Corner/errors/error_checkin_window_closed_after_grace_rejected
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        assignment = accept_block(block["id"], driver["id"], vehicle["id"])

        # One minute past the inclusive 15-minute grace bound.
        set_clock("2026-09-01T02:16:00Z")
        resp = api_client.check_in_assignment(
            assignment["id"], make_driver_headers(driver["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED)

        assert get_assignment(assignment["id"])["status"] == "ASSIGNED"
