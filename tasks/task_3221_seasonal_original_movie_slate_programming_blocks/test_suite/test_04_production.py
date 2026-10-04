"""Production: shoot-day quota, location overlap/blackout, wrap/cancel conservation."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    set_clock, make_studio, make_locked_season, make_title, approve_title,
    make_location, book_slot, create_production_slot_payload,
    setup_locked_season_with_approved_title,
)
from test_helpers.fixtures import ADMIN, PLANNER, PROD, EXEC


class TestShootDayQuotaEqualityBoundary:
    def test_booking_landing_exactly_on_max_succeeds(self, api):
        """PRD §3.3: "landing exactly on `max_shoot_days` succeeds, because only a
        strict excess rejects".

        Design: Difficulty/boundary_precision_check/shoot_day_quota_equality_boundary
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2, max_shoot_days=30)
        t1 = make_title(season["id"], name="T1")
        approve_title(t1["id"], sv)
        season = get_success_data(api_client.get_season(season["id"], ADMIN))
        t2 = make_title(season["id"], name="T2", genre="FAMILY", tone_rating="GENTLE")
        approve_title(t2["id"], season["version"])
        loc_a = make_location(studio["id"], name="Stage A")
        loc_b = make_location(studio["id"], name="Stage B")
        book_slot(t1["id"], loc_a["id"], "2027-03-01T00:00:00Z", "2027-03-21T00:00:00Z", 20)
        slot = book_slot(t2["id"], loc_b["id"], "2027-04-01T00:00:00Z", "2027-04-11T00:00:00Z", 10)
        assert slot["status"] == "BOOKED"
        season_after = get_success_data(api_client.get_season(season["id"], ADMIN))
        assert season_after["booked_shoot_days"] == 30

    def test_one_day_over_max_rejected_quota_exceeded(self, api):
        """PRD §3.3: "The **day quota** sums `shoot_days` over the season's slots
        currently in `BOOKED` and rejects with `ERR_PRODUCTION_QUOTA_EXCEEDED`
        when the existing sum plus the new slot's `shoot_days` would exceed
        `max_shoot_days`".

        Design: Difficulty/boundary_precision_check/shoot_day_quota_equality_boundary
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2, max_shoot_days=30)
        t1 = make_title(season["id"], name="T1")
        approve_title(t1["id"], sv)
        season = get_success_data(api_client.get_season(season["id"], ADMIN))
        t2 = make_title(season["id"], name="T2", genre="FAMILY", tone_rating="GENTLE")
        approve_title(t2["id"], season["version"])
        loc_a = make_location(studio["id"], name="Stage A")
        loc_b = make_location(studio["id"], name="Stage B")
        book_slot(t1["id"], loc_a["id"], "2027-03-01T00:00:00Z", "2027-03-21T00:00:00Z", 20)
        book_slot(t2["id"], loc_b["id"], "2027-04-01T00:00:00Z", "2027-04-11T00:00:00Z", 10)
        resp = api_client.create_production_slot(
            create_production_slot_payload(title_id=t2["id"], location_id=loc_b["id"],
                                           shoot_start="2027-05-01T00:00:00Z",
                                           shoot_end="2027-05-02T00:00:00Z", shoot_days=1),
            PROD)
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_QUOTA_EXCEEDED)


class TestShootDayQuotaConservation:
    def test_book_then_cancel_restores_quota(self, api):
        """PRD §3.3: "A `BOOKED` slot may instead be cancelled, moving it to the
        terminal `CANCELLED` state with the same quota release."

        Design: Difficulty/compensating_invariant/shoot_day_quota_book_cancel_conserves
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        season_id = ctx["season"]["id"]
        loc = make_location(ctx["studio"]["id"])
        slot = book_slot(ctx["title"]["id"], loc["id"],
                         "2027-03-01T00:00:00Z", "2027-03-11T00:00:00Z", 10)
        validate_success(api_client.cancel_production_slot(slot["id"], PROD))
        season_after = get_success_data(api_client.get_season(season_id, ADMIN))
        assert season_after["booked_shoot_days"] == 0
        slot_after = get_success_data(api_client.get_production_slot(slot["id"], PROD))
        assert slot_after["status"] == "CANCELLED"

    def test_book_then_wrap_restores_quota(self, api):
        """PRD §3.3: "a `ProductionManager` wraps a `BOOKED` slot, moving it to the
        terminal `WRAPPED` state and subtracting its `shoot_days` from the
        season's `booked_shoot_days` — quota is released at wrap".

        Design: Difficulty/compensating_invariant/shoot_day_quota_book_cancel_conserves
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        season_id = ctx["season"]["id"]
        loc = make_location(ctx["studio"]["id"])
        slot = book_slot(ctx["title"]["id"], loc["id"],
                         "2027-04-01T00:00:00Z", "2027-04-11T00:00:00Z", 10)
        validate_success(api_client.wrap_production_slot(slot["id"], PROD))
        season_after = get_success_data(api_client.get_season(season_id, ADMIN))
        assert season_after["booked_shoot_days"] == 0
        slot_after = get_success_data(api_client.get_production_slot(slot["id"], PROD))
        assert slot_after["status"] == "WRAPPED"


class TestLocationShootHalfOpenOverlap:
    def test_interior_overlap_rejected(self, api):
        """PRD §3.3: "a conflict exists precisely when the new slot starts before
        the existing slot ends *and* the existing slot starts before the new slot
        ends" and "A conflict is rejected with `ERR_LOCATION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/location_shoot_half_open_overlap
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        approve_title(t1["id"], sv)
        season = get_success_data(api_client.get_season(season["id"], ADMIN))
        t2 = make_title(season["id"], name="T2", genre="FAMILY", tone_rating="GENTLE")
        approve_title(t2["id"], season["version"])
        loc = make_location(studio["id"])
        book_slot(t1["id"], loc["id"], "2027-03-10T00:00:00Z", "2027-03-20T00:00:00Z", 10)
        resp = api_client.create_production_slot(
            create_production_slot_payload(title_id=t2["id"], location_id=loc["id"],
                                           shoot_start="2027-03-19T23:00:00Z",
                                           shoot_end="2027-03-25T00:00:00Z", shoot_days=6),
            PROD)
        validate_error(resp, ApiErrorId.ERR_LOCATION_OVERLAP)

    def test_touching_endpoints_do_not_conflict(self, api):
        """PRD §3.3: "two intervals that merely touch — one ends exactly when the
        other begins — do not conflict."

        Design: Difficulty/resource_temporal_overlap/location_shoot_half_open_overlap
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        approve_title(t1["id"], sv)
        season = get_success_data(api_client.get_season(season["id"], ADMIN))
        t2 = make_title(season["id"], name="T2", genre="FAMILY", tone_rating="GENTLE")
        approve_title(t2["id"], season["version"])
        loc = make_location(studio["id"])
        book_slot(t1["id"], loc["id"], "2027-03-10T00:00:00Z", "2027-03-20T00:00:00Z", 10)
        slot = book_slot(t2["id"], loc["id"], "2027-03-20T00:00:00Z", "2027-03-25T00:00:00Z", 5)
        assert slot["status"] == "BOOKED"
        season_after = get_success_data(api_client.get_season(season["id"], ADMIN))
        assert season_after["booked_shoot_days"] == 15


class TestLocationBlackout:
    def test_blackout_intersection_rejected(self, api):
        """PRD §3.3: "The **blackout** rule applies the same half-open intersection
        test against each of the location's `blackout_windows` and rejects an
        intersecting booking with `ERR_LOCATION_BLACKOUT`."

        Design: Corner/state_machines/location_blackout_window_blocks_shoot
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        approve_title(t1["id"], sv)
        loc = make_location(studio["id"], blackout_windows=[
            {"start": "2027-04-01T00:00:00Z", "end": "2027-04-15T00:00:00Z"}])
        resp = api_client.create_production_slot(
            create_production_slot_payload(title_id=t1["id"], location_id=loc["id"],
                                           shoot_start="2027-03-28T00:00:00Z",
                                           shoot_end="2027-04-05T00:00:00Z", shoot_days=8),
            PROD)
        validate_error(resp, ApiErrorId.ERR_LOCATION_BLACKOUT)

    def test_shoot_ending_at_blackout_start_passes(self, api):
        """PRD §3.3: "The **blackout** rule applies the same half-open intersection
        test" and "two intervals that merely touch — one ends exactly when the
        other begins — do not conflict."

        Design: Corner/state_machines/location_blackout_window_blocks_shoot
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t2 = make_title(season["id"], name="T2", genre="FAMILY", tone_rating="GENTLE")
        approve_title(t2["id"], sv)
        loc = make_location(studio["id"], blackout_windows=[
            {"start": "2027-04-01T00:00:00Z", "end": "2027-04-15T00:00:00Z"}])
        slot = book_slot(t2["id"], loc["id"], "2027-03-22T00:00:00Z", "2027-04-01T00:00:00Z", 10)
        assert slot["status"] == "BOOKED"


class TestShootDaysShape:
    def test_shoot_days_mismatching_ceil_rejected(self, api):
        """PRD §3.3: "`shoot_days` must equal the length of the interval in seconds
        divided by the number of seconds in a day, rounded up to a whole day; a
        mismatch is a shape violation rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/shoot_days_must_match_ceil_of_interval
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        loc = make_location(ctx["studio"]["id"])
        # 36-hour interval: ceil is 2, declared 1 -> 400
        resp = api_client.create_production_slot(
            create_production_slot_payload(title_id=ctx["title"]["id"], location_id=loc["id"],
                                           shoot_start="2027-03-10T00:00:00Z",
                                           shoot_end="2027-03-11T12:00:00Z", shoot_days=1),
            PROD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_shoot_days_matching_ceil_accepted(self, api):
        """PRD §3.3: "`shoot_days` must equal the length of the interval in seconds
        divided by the number of seconds in a day, rounded up to a whole day".

        Design: Corner/state_machines/shoot_days_must_match_ceil_of_interval
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        loc = make_location(ctx["studio"]["id"])
        slot = book_slot(ctx["title"]["id"], loc["id"],
                         "2027-03-10T00:00:00Z", "2027-03-11T12:00:00Z", 2)
        assert slot["status"] == "BOOKED"
        assert slot["shoot_days"] == 2


class TestProductionSlotTerminalLockdown:
    def test_wrap_from_wrapped_is_invalid_state(self, api):
        """PRD §3.3: "a `ProductionManager` wraps a `BOOKED` slot" — WRAPPED is
        terminal, so a second wrap has no such transition (PRD §2.7 item 6,
        `ERR_INVALID_STATE`).

        Design: Corner/state_machines/production_slot_wrap_from_wrapped_is_invalid_state
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        season_id = ctx["season"]["id"]
        loc = make_location(ctx["studio"]["id"])
        slot = book_slot(ctx["title"]["id"], loc["id"])
        validate_success(api_client.wrap_production_slot(slot["id"], PROD))
        resp = api_client.wrap_production_slot(slot["id"], PROD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        season_after = get_success_data(api_client.get_season(season_id, ADMIN))
        assert season_after["booked_shoot_days"] == 0, "quota must not be released twice"
        slot_after = get_success_data(api_client.get_production_slot(slot["id"], PROD))
        assert slot_after["status"] == "WRAPPED"
