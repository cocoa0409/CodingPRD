"""DateAvail windows: adjacency, release semantics, force-release cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_date_avail,
    create_labor_call,
    create_truck_move,
    setup_confirmed_engagement,
    setup_held_engagement,
    setup_rigging_plan,
    setup_tour_and_venue,
    validate_error,
    validate_success,
)

TM = TEST_USERS["tour_manager_headers"]
VB = TEST_USERS["venue_booker_headers"]
PA = TEST_USERS["platform_admin_headers"]


class TestAvailAdjacencyAndOverlap:
    def test_date_avail_adjacency_allowed_overlap_rejected(self):
        """PRD §3.2: "The new window must also not collide with any existing
        non-`RELEASED` avail on the same venue under half-open interval
        semantics; pure adjacency, where the new window's `opens_at` equals an
        existing window's `closes_at`, is allowed, but true overlap is rejected
        with `ERR_AVAIL_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/date_avail_half_open_overlap_adjacency_allowed
        """
        _, venue = setup_tour_and_venue()
        create_date_avail(
            venue["id"], opens_at="2026-09-10T00:00:00Z",
            closes_at="2026-09-15T00:00:00Z",
        )
        # Adjacent: opens exactly at the first window's closes_at — allowed.
        resp = api_client.create_date_avail(
            venue["id"],
            {"opens_at": "2026-09-15T00:00:00Z", "closes_at": "2026-09-20T00:00:00Z",
             "priority_rank": 10},
            VB,
        )
        adjacent = validate_success(resp, expected_status=201)
        assert adjacent["status"] == "OPEN"

        # True overlap: [Sep 14, Sep 16) intersects [Sep 10, Sep 15).
        resp = api_client.create_date_avail(
            venue["id"],
            {"opens_at": "2026-09-14T00:00:00Z", "closes_at": "2026-09-16T00:00:00Z",
             "priority_rank": 10},
            VB,
        )
        validate_error(resp, ApiErrorId.ERR_AVAIL_OVERLAP)

    def test_date_avail_containing_window_overlap_rejected(self):
        """PRD §3.2: "The new window must also not collide with any existing
        non-`RELEASED` avail on the same venue under half-open interval
        semantics; pure adjacency, where the new window's `opens_at` equals an
        existing window's `closes_at`, is allowed, but true overlap is rejected
        with `ERR_AVAIL_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/date_avail_half_open_overlap_adjacency_allowed
        """
        _, venue = setup_tour_and_venue()
        create_date_avail(
            venue["id"], opens_at="2026-09-10T00:00:00Z",
            closes_at="2026-09-15T00:00:00Z",
        )
        # A window fully containing the existing one overlaps.
        resp = api_client.create_date_avail(
            venue["id"],
            {"opens_at": "2026-09-09T00:00:00Z", "closes_at": "2026-09-16T00:00:00Z",
             "priority_rank": 10},
            VB,
        )
        validate_error(resp, ApiErrorId.ERR_AVAIL_OVERLAP)


class TestAvailRelease:
    def test_avail_release_already_released_returns_avail_not_open(self):
        """PRD §3.2: "A `VenueBooker` may release an avail explicitly: releasing
        an `OPEN` avail moves it to `RELEASED` (releasing one in any other
        non-held state is rejected with `ERR_AVAIL_NOT_OPEN`, HTTP 409)"

        Design: Corner/errors/avail_release_already_released_returns_avail_not_open
        """
        _, venue = setup_tour_and_venue()
        avail = create_date_avail(venue["id"])
        resp = api_client.release_date_avail(venue["id"], avail["id"], VB)
        released = validate_success(resp)
        assert released["status"] == "RELEASED"

        resp = api_client.release_date_avail(venue["id"], avail["id"], VB)
        validate_error(resp, ApiErrorId.ERR_AVAIL_NOT_OPEN)

        resp = api_client.get_date_avail(venue["id"], avail["id"], VB)
        assert validate_success(resp)["status"] == "RELEASED"


class TestForceReleaseCascade:
    def test_force_release_cascades_engagement_plans_calls_moves(self):
        """PRD §3.2: "force-releasing a `HELD` avail is permitted only while the
        holding engagement is still in `HOLD` — never after confirmation — and
        cascades: the held engagement transitions to `CANCELLED` with reason
        `AVAIL_FORCE_RELEASED`, and `held_for_engagement_id` is cleared."
        PRD §3.3: "While the engagement is in `HOLD`, a `TourManager` may cancel
        it outright (or the system does so at hold expiry): the avail returns
        `HELD → OPEN`, every rigging plan on the engagement in `DRAFT` or
        `SUBMITTED` moves to `SUPERSEDED`, every labor call in `DRAFT` or
        `POSTED` moves to `CANCELLED`, and every truck move in `SCHEDULED` or
        `DISPATCHED` moves to `CANCELLED`."

        Design: Difficulty/transitive_cascade/venue_deactivate_releases_avail_cascades_engagement_cancel_supersedes_plans
        """
        ctx = setup_held_engagement()
        tour_id = ctx["tour"]["id"]
        eng_id = ctx["engagement"]["id"]
        venue_id = ctx["venue"]["id"]

        point, plan = setup_rigging_plan(
            ctx, allocations=[{"static_load_kg": 1000, "dynamic_load_kg": 100}],
        )
        call = create_labor_call(ctx)
        move = create_truck_move(ctx)

        resp = api_client.release_date_avail(venue_id, ctx["avail"]["id"], VB)
        released = validate_success(resp)
        assert released["status"] == "RELEASED"

        eng = validate_success(api_client.get_engagement(tour_id, eng_id, TM))
        assert eng["status"] == "CANCELLED"

        plan_now = validate_success(api_client.get_rigging_plan(tour_id, eng_id, plan["id"], TM))
        assert plan_now["status"] == "SUPERSEDED"

        call_now = validate_success(api_client.get_labor_call(tour_id, eng_id, call["id"], TM))
        assert call_now["status"] == "CANCELLED"

        move_now = validate_success(api_client.get_truck_move(tour_id, eng_id, move["id"], TM))
        assert move_now["status"] == "CANCELLED"

    def test_force_release_clears_held_for_engagement_id(self):
        """PRD §3.2: "force-releasing a `HELD` avail is permitted only while the
        holding engagement is still in `HOLD` — never after confirmation — and
        cascades: the held engagement transitions to `CANCELLED` with reason
        `AVAIL_FORCE_RELEASED`, and `held_for_engagement_id` is cleared."

        Design: Difficulty/transitive_cascade/venue_deactivate_releases_avail_cascades_engagement_cancel_supersedes_plans
        """
        ctx = setup_held_engagement()
        venue_id = ctx["venue"]["id"]

        held = validate_success(
            api_client.get_date_avail(venue_id, ctx["avail"]["id"], VB)
        )
        assert held["status"] == "HELD"
        assert held["held_for_engagement_id"] == ctx["engagement"]["id"]

        released = validate_success(
            api_client.release_date_avail(venue_id, ctx["avail"]["id"], VB)
        )
        assert released["status"] == "RELEASED"
        assert released["held_for_engagement_id"] is None


class TestConfirmOrdering:
    def test_confirm_after_force_release_and_deactivate_returns_not_in_hold(self):
        """PRD §3.3: "Confirm enforces four checks, evaluated in this order —
        the state gate first (the engagement must be in `HOLD`, otherwise
        `ERR_ENGAGEMENT_NOT_IN_HOLD`, HTTP 409), then hold freshness (the
        logical clock must be strictly earlier than `hold_expires_at`, otherwise
        `ERR_HOLD_EXPIRED`, HTTP 409), then market rotation, then venue liveness
        (the venue must be `ACTIVE`, otherwise `ERR_VENUE_INACTIVE`, HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/engagement_confirm_gated_on_venue_active
        """
        ctx = setup_held_engagement()
        tour_id = ctx["tour"]["id"]
        eng_id = ctx["engagement"]["id"]
        venue_id = ctx["venue"]["id"]

        # Force-release cancels the held engagement; then deactivation is
        # unblocked because no open engagements remain.
        validate_success(api_client.release_date_avail(venue_id, ctx["avail"]["id"], VB))
        venue = validate_success(api_client.deactivate_venue(venue_id, PA))
        assert venue["status"] == "INACTIVE"

        eng = validate_success(api_client.get_engagement(tour_id, eng_id, TM))
        assert eng["status"] == "CANCELLED"

        resp = api_client.confirm_engagement(tour_id, eng_id, TM)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_IN_HOLD)

    def test_confirm_on_active_venue_succeeds_and_books_avail(self):
        """PRD §3.3: "then venue liveness (the venue must be `ACTIVE`, otherwise
        `ERR_VENUE_INACTIVE`, HTTP 409)."
        PRD §3.3: "On success, the held avail flips `HELD → BOOKED`; the tour's
        `open_engagement_count` is unchanged, because `HOLD` already counted."

        Design: Difficulty/cross_entity_state_dependency/engagement_confirm_gated_on_venue_active
        """
        ctx = setup_held_engagement()
        eng = validate_success(
            api_client.confirm_engagement(ctx["tour"]["id"], ctx["engagement"]["id"], TM)
        )
        assert eng["status"] == "CONFIRMED"
        avail = validate_success(
            api_client.get_date_avail(ctx["venue"]["id"], ctx["avail"]["id"], VB)
        )
        assert avail["status"] == "BOOKED"

    def test_confirm_after_hold_expiry_reports_not_in_hold_not_hold_expired(self):
        """PRD §3.3: "Confirm enforces four checks, evaluated in this order —
        the state gate first (the engagement must be in `HOLD`, otherwise
        `ERR_ENGAGEMENT_NOT_IN_HOLD`, HTTP 409), then hold freshness (the
        logical clock must be strictly earlier than `hold_expires_at`, otherwise
        `ERR_HOLD_EXPIRED`, HTTP 409), then market rotation, then venue liveness
        (the venue must be `ACTIVE`, otherwise `ERR_VENUE_INACTIVE`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_expired_hold_confirm
        """
        from test_helpers import set_clock

        ctx = setup_held_engagement()
        tour_id = ctx["tour"]["id"]
        eng_id = ctx["engagement"]["id"]

        set_clock("2026-09-05T00:00:00Z")
        eng = validate_success(api_client.get_engagement(tour_id, eng_id, TM))
        assert eng["status"] == "CANCELLED"

        resp = api_client.confirm_engagement(tour_id, eng_id, TM)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_IN_HOLD)

    def test_confirm_within_hold_ttl_succeeds(self):
        """PRD §3.3: "Confirm enforces four checks, evaluated in this order —
        the state gate first (the engagement must be in `HOLD`, otherwise
        `ERR_ENGAGEMENT_NOT_IN_HOLD`, HTTP 409), then hold freshness (the
        logical clock must be strictly earlier than `hold_expires_at`, otherwise
        `ERR_HOLD_EXPIRED`, HTTP 409), then market rotation, then venue liveness
        (the venue must be `ACTIVE`, otherwise `ERR_VENUE_INACTIVE`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_expired_hold_confirm
        """
        from test_helpers import set_clock

        ctx = setup_held_engagement()
        # One second before expiry: hold is still fresh, so confirm succeeds.
        set_clock("2026-09-03T23:59:59Z")
        eng = validate_success(
            api_client.confirm_engagement(ctx["tour"]["id"], ctx["engagement"]["id"], TM)
        )
        assert eng["status"] == "CONFIRMED"
