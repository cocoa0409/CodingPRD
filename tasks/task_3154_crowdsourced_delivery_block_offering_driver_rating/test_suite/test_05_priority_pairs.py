"""Priority-pair validation conflicts: state beats temporal; safety beats temporal."""

from test_helpers import (
    TEST_USERS,
    api_client,
    set_clock,
    create_station,
    create_published_block,
    onboard_active_driver,
    deactivate_driver,
    accept_block,
    get_assignment,
    make_driver_headers,
    validate_error,
    setup_premier_driver,
)
from test_helpers.api_errors import ApiErrorId


class TestDeactivatedDriverStateBeatsVisibilityTemporal:
    def test_deactivated_driver_accept_rejected_with_state_error(self, api):
        """PRD §2.5: "The order is: first, authentication of the headers
        (`ERR_UNAUTHENTICATED`); second, role permission and ownership (`ERR_FORBIDDEN`,
        or `ERR_OFFER_WRONG_DRIVER` for wrong-driver offer actions); third, existence of
        path and body references (`ERR_NOT_FOUND`); fourth, state-machine legality,
        including the domain state errors `ERR_DRIVER_NOT_ACTIVE` and
        `ERR_BLOCK_NOT_PUBLISHED`, all rejected with `ERR_INVALID_STATE` or the named
        domain error (HTTP 409); fifth, business safety gates — screening, vehicle, and
        insurance checks such as `ERR_SCREENING_NOT_CLEARED`, `ERR_NO_ELIGIBLE_VEHICLE`,
        `ERR_INSURANCE_NOT_ATTESTED`, `ERR_VEHICLE_CLASS_MISMATCH`, and
        `ERR_INSURANCE_WINDOW_LAPSE`; sixth, temporal business gates such as
        `ERR_BLOCK_NOT_VISIBLE_YET`, `ERR_BLOCK_WINDOW_OVERLAP`,
        `ERR_OFFER_BUFFER_CONFLICT`, `ERR_OFFER_EXPIRED`, `ERR_CHECKIN_TOO_EARLY`, and
        `ERR_CHECKIN_WINDOW_CLOSED`."
        PRD §2.5: "The practical consequence is that safety beats temporal — a check-in
        violating both insurance containment and the check-in window returns
        `ERR_INSURANCE_WINDOW_LAPSE` — and that state errors beat every business check."

        Design: Difficulty/priority_pair_validation_conflict/deactivated_driver_state_beats_block_visibility_temporal
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        # Block starts 7 hours out — beyond any tier's visibility lead — so the
        # temporal gate would also fail; the state error must win.
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T07:00:00Z",
            ends_at="2026-09-01T09:00:00Z",
            base_pay_cents=4000,
        )
        deactivate_driver(driver["id"], reason="policy violation")

        resp = api_client.accept_block(
            block["id"],
            {"vehicle_id": vehicle["id"]},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_ACTIVE)

    def test_deactivated_driver_accept_rejected_even_for_visible_block(self, api):
        """PRD §3.3: "A first-come claim by a driver requires a payload containing the
        `vehicle_id` the driver will use. The block must be `PUBLISHED` (otherwise
        `ERR_BLOCK_NOT_PUBLISHED`), the driver must be `ACTIVE` (otherwise
        `ERR_DRIVER_NOT_ACTIVE`) …"

        Design: Difficulty/priority_pair_validation_conflict/deactivated_driver_state_beats_block_visibility_temporal
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        # Block starts within the hour — no temporal violation; state error stands alone.
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T00:30:00Z",
            ends_at="2026-09-01T02:00:00Z",
            base_pay_cents=4000,
        )
        deactivate_driver(driver["id"], reason="policy violation")

        resp = api_client.accept_block(
            block["id"],
            {"vehicle_id": vehicle["id"]},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_ACTIVE)


class TestInsuranceLapseSafetyBeatsCheckinTemporal:
    def test_insurance_lapse_wins_over_checkin_window_closed(self, api):
        """PRD §2.5: "The practical consequence is that safety beats temporal — a
        check-in violating both insurance containment and the check-in window returns
        `ERR_INSURANCE_WINDOW_LAPSE` — and that state errors beat every business check."
        PRD §3.4: "Safety is checked before the clock: the assignment's vehicle
        insurance must cover the entire block window under closed-interval containment,
        meaning `insurance_expires_on` must be on or after the calendar date of the
        block's `ends_at`; a policy that lapses mid-block is rejected with
        `ERR_INSURANCE_WINDOW_LAPSE`, and this safety rejection takes precedence over
        the temporal check-in errors when both apply."

        Design: Difficulty/priority_pair_validation_conflict/insurance_lapse_safety_beats_checkin_window_temporal
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver(
            insurance_expires_on="2026-09-04"
        )
        # Reserved offer bypasses the visibility lead so the far-future block can
        # be accepted by a STANDARD-tier driver.
        block = create_published_block(
            station["id"],
            starts_at="2026-09-05T10:00:00Z",
            ends_at="2026-09-05T12:00:00Z",
            base_pay_cents=5000,
        )
        from test_helpers import create_offer, accept_offer

        offer = create_offer(
            block["id"],
            driver["id"],
            tier_floor="STANDARD",
            expires_at="2026-09-05T08:00:00Z",
        )
        assignment = accept_offer(offer["id"], driver["id"], vehicle["id"])

        # Clock: 12:00 on block day — check-in window (ends 10:15) is closed AND
        # insurance (expires 2026-09-04) fails containment of the 2026-09-05 end date.
        set_clock("2026-09-05T12:00:00Z")
        resp = api_client.check_in_assignment(
            assignment["id"], make_driver_headers(driver["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INSURANCE_WINDOW_LAPSE)

        assert get_assignment(assignment["id"])["status"] == "ASSIGNED"

    def test_insurance_lapse_alone_rejected_at_checkin(self, api):
        """PRD §3.4: "Safety is checked before the clock: the assignment's vehicle
        insurance must cover the entire block window under closed-interval containment,
        meaning `insurance_expires_on` must be on or after the calendar date of the
        block's `ends_at`; a policy that lapses mid-block is rejected with
        `ERR_INSURANCE_WINDOW_LAPSE` …"

        Design: Difficulty/priority_pair_validation_conflict/insurance_lapse_safety_beats_checkin_window_temporal
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver(
            insurance_expires_on="2026-09-04"
        )
        from test_helpers import create_offer, accept_offer

        block = create_published_block(
            station["id"],
            starts_at="2026-09-05T10:00:00Z",
            ends_at="2026-09-05T12:00:00Z",
            base_pay_cents=5000,
        )
        offer = create_offer(
            block["id"],
            driver["id"],
            tier_floor="STANDARD",
            expires_at="2026-09-05T08:00:00Z",
        )
        assignment = accept_offer(offer["id"], driver["id"], vehicle["id"])

        # Inside the check-in window (09:45) but insurance lapses before block end.
        set_clock("2026-09-05T09:45:00Z")
        resp = api_client.check_in_assignment(
            assignment["id"], make_driver_headers(driver["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INSURANCE_WINDOW_LAPSE)
        assert get_assignment(assignment["id"])["status"] == "ASSIGNED"
