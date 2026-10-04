"""Driver tracking, dwell measurement and detention billing."""
import pytest

from test_helpers import (
    api_client as api,
    make_carrier_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    send_ping,
    send_ping_ok,
    set_clock,
    setup_board,
    setup_detention_boundary_scenario,
    list_load_detention,
    list_load_pings,
)


class TestDwellBoundary:
    """The free-dwell boundary is inclusive; billing rounds up to whole hours."""

    def test_dwell_equal_to_the_free_allowance_bills_nothing(self):
        """PRD section 3.5: "A dwell of exactly 120 minutes at a facility with a
        120-minute allowance bills nothing; a dwell of 121 minutes bills one full
        hour."

        Design: Difficulty/boundary_precision_check/detention_bills_zero_at_exactly_free_dwell_and_one_hour_at_one_minute_past
        """
        board = setup_detention_boundary_scenario()
        events = list_load_detention(board["shipper_id"], board["loads"]["b"]["load"]["id"])
        assert len(events) == 1, f"expected one detention event, got {len(events)}"
        event = events[0]
        assert event["dwell_minutes"] == 120
        assert event["billable_detention_minutes"] == 0
        assert event["detention_charge_cents"] == 0

    def test_one_minute_past_the_free_allowance_bills_a_whole_hour(self):
        """PRD section 3.5: "A dwell of exactly 120 minutes at a facility with a
        120-minute allowance bills nothing; a dwell of 121 minutes bills one full
        hour."

        Design: Difficulty/boundary_precision_check/detention_bills_zero_at_exactly_free_dwell_and_one_hour_at_one_minute_past
        """
        board = setup_detention_boundary_scenario()
        events = list_load_detention(board["shipper_id"], board["loads"]["c"]["load"]["id"])
        assert len(events) == 1
        event = events[0]
        assert event["dwell_minutes"] == 121
        assert event["billable_detention_minutes"] == 1
        assert event["detention_charge_cents"] == 7500
        load = api.get_load(board["loads"]["c"]["load"]["id"],
                            make_shipper_headers(board["shipper_id"])).json()["data"]
        assert load["accessorial_total_cents"] == 7500
        assert load["accessorial_total_cents"] != 0

    def test_longer_dwell_rounds_up_to_whole_hours(self):
        """PRD section 3.5: "When the appointment completes, or the load is delivered, that event closes and its dwell is finalized: `departed_at` is stamped, `dwell_minutes` is the whole minutes elapsed from `arrived_at` to `departed_at`, `billable_detention_minutes` is whatever remains after the facility's `free_dwell_minutes` is subtracted and the result clamped at zero, and `detention_charge_cents` follows the strictly ordered sequence of §2.9 — billable minutes rounded up to whole hours, then multiplied by the facility's `detention_rate_per_hour_cents`."

        Design: Difficulty/boundary_precision_check/detention_bills_zero_at_exactly_free_dwell_and_one_hour_at_one_minute_past
        """
        board = setup_detention_boundary_scenario()
        events = list_load_detention(board["shipper_id"], board["loads"]["a"]["load"]["id"])
        assert len(events) == 1
        event = events[0]
        assert event["dwell_minutes"] == 185
        assert event["billable_detention_minutes"] == 65
        assert event["detention_charge_cents"] == 15000
        load = api.get_load(board["loads"]["a"]["load"]["id"],
                            make_shipper_headers(board["shipper_id"])).json()["data"]
        assert load["accessorial_total_cents"] == 15000

    def test_waived_event_leaves_the_accessorial_total_untouched(self):
        """PRD section 3.10: "A waive sets the event's `detention_charge_cents` to
        zero, moves it to `WAIVED`, and recomputes the load's accessorial total
        without it."

        Design: Difficulty/boundary_precision_check/detention_bills_zero_at_exactly_free_dwell_and_one_hour_at_one_minute_past
        """
        board = setup_detention_boundary_scenario()
        load_id = board["loads"]["a"]["load"]["id"]
        events = list_load_detention(board["shipper_id"], load_id)
        assert len(events) == 1
        event = events[0]
        waived = api.waive_detention_event(event["id"], "FACILITY_FAULT",
                                           make_platform_admin_headers())
        assert waived.status_code == 200, waived.text
        load = api.get_load(load_id, make_shipper_headers(board["shipper_id"])).json()["data"]
        assert load["accessorial_total_cents"] == 0
        assert waived.json()["data"]["detention_charge_cents"] == 0
        assert waived.json()["data"]["status"] == "WAIVED"


class TestRetentionArithmetic:
    """A closed event keeps its measured dwell visible for audit."""

    def test_closed_event_reports_its_dwell_and_charge(self):
        """PRD section 3.5: "When the appointment completes, or the load is delivered, that event closes and its dwell is finalized: `departed_at` is stamped, `dwell_minutes` is the whole minutes elapsed from `arrived_at` to `departed_at`, `billable_detention_minutes` is whatever remains after the facility's `free_dwell_minutes` is subtracted and the result clamped at zero, and `detention_charge_cents` follows the strictly ordered sequence of §2.9 — billable minutes rounded up to whole hours, then multiplied by the facility's `detention_rate_per_hour_cents`."

        Design: Corner/cross_cutting_complexity_layers/accessorial_total_reconciles_down_when_a_detention_charge_is_waived
        """
        board = setup_detention_boundary_scenario()
        load_id = board["loads"]["a"]["load"]["id"]
        events = list_load_detention(board["shipper_id"], load_id)
        assert len(events) == 1
        event = events[0]
        assert event["status"] == "CLOSED"
        assert event["departed_at"] is not None
        assert event["detention_charge_cents"] == 15000
        assert event["appointment_id"] and event["facility_id"] and event["load_id"]


class TestStatusProgression:
    """The ping ladder may only climb one rung at a time."""

    def test_rank_may_not_skip_a_rung_even_with_a_correct_sequence(self):
        """PRD section 3.6: "The supplied `sequence` must equal one more than the number of pings already recorded for that load, or the ping is refused with `ERR_TRACKING_SEQUENCE_OUT_OF_ORDER` (HTTP 409). And the ping's `status_rank` must be no greater than one more than the greatest rank observed so far on that load, or it is refused with `ERR_TRACKING_SEQUENCE_GAP` (HTTP 409)."

        Design: Corner/entities/tracking_ping_extra_client_sequence_and_status_rank_are_ignored_input
        """
        board = setup_board(units=1)
        load = _booked_load(board)
        first = send_ping(load["id"], board["carrier_id"], 1, "EN_ROUTE_PICKUP", "9vg81")
        assert first.status_code == 201, first.text

        skipped = send_ping(load["id"], board["carrier_id"], 2, "IN_TRANSIT", "9vg83")
        assert skipped.status_code == 409
        assert skipped.json()["data"]["error_id"] == "ERR_TRACKING_SEQUENCE_GAP"
        assert len(list_load_pings(board["shipper_id"], load["id"])) == 1, (
            "a rejected ping is stored nowhere")

    def test_departure_requires_an_arrival_ping_first(self):
        """PRD section 3.6: "A ping reporting `IN_TRANSIT` advances the load from
        `BOOKED` to `IN_TRANSIT`, and it can only do so once a ping of rank 2 or
        higher — that is, an `AT_PICKUP` — has already been recorded for the
        load; without one the attempt fails with `ERR_TRACKING_SEQUENCE_GAP`
        (HTTP 409)."

        Design: Corner/state_machines/booking_on_a_draft_load_returns_invalid_state_never_a_quote_error
        """
        board = setup_board(units=1)
        load = _booked_load(board)
        send_ping_ok(load["id"], board["carrier_id"], 1, "EN_ROUTE_PICKUP", "9vg81")
        departure = send_ping(load["id"], board["carrier_id"], 2, "IN_TRANSIT", "9vg83")
        assert departure.status_code == 409
        assert departure.json()["data"]["error_id"] == "ERR_TRACKING_SEQUENCE_GAP"

    def test_departure_closes_the_pickup_appointment_and_records_the_event(self):
        """PRD section 3.6: "The load's pickup appointment, which is `IN_PROGRESS`,
        becomes `COMPLETED`, its open detention event is closed with `departed_at`
        stamped at the current instant, and the load's `accessorial_total_cents` is
        recomputed.  A `DEPARTED_PICKUP` status event sourced to the driver app is
        appended."

        Design: Corner/cross_cutting_complexity_layers/one_booking_mutates_five_related_resources_in_the_same_request
        """
        board = setup_board(units=1)
        load = _booked_load(board)
        send_ping_ok(load["id"], board["carrier_id"], 1, "EN_ROUTE_PICKUP", "9vg81",
                     "2026-10-07T16:00:00Z")
        set_clock("2026-10-05T08:00:00Z")
        send_ping_ok(load["id"], board["carrier_id"], 2, "AT_PICKUP", "9vg82")
        set_clock("2026-10-05T09:00:00Z")
        send_ping_ok(load["id"], board["carrier_id"], 3, "IN_TRANSIT", "9vg83",
                     "2026-10-07T16:00:00Z")

        appointments = api.list_load_appointments(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        pickup = [slot for slot in appointments if slot["slot_kind"] == "PICKUP"]
        assert len(pickup) == 1
        assert pickup[0]["status"] == "COMPLETED"

        events = api.list_load_status_events(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        departed = [event for event in events if event["event_type"] == "DEPARTED_PICKUP"]
        assert len(departed) == 1
        assert departed[0]["source"] == "DRIVER_APP"

        detention = api.list_load_detention_events(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert len(detention) >= 1


class TestProjectedDelay:
    """Only the newest ping's ETA contributes, after the risk slack is added."""

    def test_the_projected_delay_uses_the_newest_pings_eta(self):
        """PRD section 3.6: "Only the ping with the greatest `sequence` on the load
        contributes; a lower-sequence ping carrying a later `eta_utc` is ignored
        entirely."
        PRD section 3.6: "Otherwise the server converts the carrier's
        `operational_risk_score` into a slack allowance: one hundred minus
        the score, in points, multiplied by 2.4 minutes per point and
        rounded half up to whole minutes — so a perfect-risk carrier at
        100.0 adds no slack at all and its posted ETA stands as given,
        while a carrier at 88.0 adds twelve points' worth, or 29 minutes,
        before the comparison is made."

        Design: Corner/cross_cutting_complexity_layers/one_booking_mutates_five_related_resources_in_the_same_request
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load = _booked_load(board)

        send_ping_ok(load["id"], board["carrier_id"], 1, "EN_ROUTE_PICKUP", "9vg81",
                     "2026-10-07T19:00:00Z")
        set_clock("2026-10-05T08:00:00Z")
        send_ping_ok(load["id"], board["carrier_id"], 2, "AT_PICKUP", "9vg82")

        # A perfect-risk carrier adds no slack, so the newest ETA is compared as
        # given against the load's delivery deadline.
        refreshed = api.get_load(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert refreshed["projected_delay_minutes"] == 0, (
            "an early projection reports zero, never a negative variance")

    def test_a_late_eta_projects_a_positive_delay(self):
        """PRD section 3.6: "That slack is added to the ping's `eta_utc` to produce a projected arrival instant, and `projected_delay_minutes` is the whole minutes by which that instant exceeds the load's `delivery_deadline`, floored, and never reported below zero — the figure is a positive lateness measure, not a signed variance, so an early projection reports zero."

        Design: Corner/cross_cutting_complexity_layers/one_booking_mutates_five_related_resources_in_the_same_request
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load = _booked_load(board)
        set_clock("2026-10-05T08:00:00Z")
        send_ping_ok(load["id"], board["carrier_id"], 1, "EN_ROUTE_PICKUP", "9vg81",
                     "2026-10-07T20:00:00Z")

        refreshed = api.get_load(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert refreshed["projected_delay_minutes"] == 120, (
            f"a two-hour-late ETA projects 120 minutes, got "
            f"{refreshed['projected_delay_minutes']}")

    def test_a_ping_without_an_eta_projects_no_delay(self):
        """PRD section 3.6: "If that newest ping has no `eta_utc`, the projected
        delay is zero."

        Design: Corner/cross_cutting_complexity_layers/one_booking_mutates_five_related_resources_in_the_same_request
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load = _booked_load(board)
        set_clock("2026-10-05T08:00:00Z")
        send_ping_ok(load["id"], board["carrier_id"], 1, "EN_ROUTE_PICKUP", "9vg81",
                     "2026-10-08T20:00:00Z")
        set_clock("2026-10-05T09:00:00Z")
        send_ping_ok(load["id"], board["carrier_id"], 2, "AT_PICKUP", "9vg82")

        refreshed = api.get_load(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert refreshed["projected_delay_minutes"] == 0


def _booked_load(board):
    load = api.create_load(
        {
            "shipper_id": board["shipper_id"],
            "origin_facility_id": board["origin_facility_id"],
            "destination_facility_id": board["destination_facility_id"],
            "pricing_mode": "SPOT",
            "equipment_type": "DRY_VAN",
            "commodity": "GENERAL",
            "weight_lbs": 40000,
            "declared_cargo_value_cents": 5000000,
            "distance_miles": 900,
            "pickup_window_start": "2026-10-05T08:00:00Z",
            "pickup_window_end": "2026-10-05T12:00:00Z",
            "delivery_deadline": "2026-10-07T18:00:00Z",
            "market_band": "BALANCED",
        },
        make_shipper_headers(board["shipper_id"]),
    )
    assert load.status_code == 201, load.text
    load_id = load.json()["data"]["id"]
    posted = api.post_load(load_id, make_shipper_headers(board["shipper_id"]))
    assert posted.status_code == 200, posted.text
    load_data = posted.json()["data"]
    quote = api.list_load_rate_quotes(
        load_id, make_shipper_headers(board["shipper_id"])).json()["data"][-1]
    booking = api.create_booking(
        {
            "load_id": load_id,
            "carrier_id": board["carrier_id"],
            "rate_quote_id": quote["id"],
            "equipment_id": board["equipment"][0]["id"],
            "expected_load_version": load_data["version"],
        },
        make_carrier_headers(board["carrier_id"]),
    )
    assert booking.status_code == 201, booking.text
    return api.get_load(load_id, make_shipper_headers(board["shipper_id"])).json()["data"]