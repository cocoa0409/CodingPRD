"""Streaming partners, territory rights, and premium distribution windows."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_arena, create_event,
    create_streaming_partner, create_territory_right,
    create_territory_right_payload,
    setup_premium_event_with_spanning_right,
    create_distribution_window_payload,
)

DM = TEST_USERS["distribution_manager_headers"]
TP = TEST_USERS["tour_planner_headers"]
SE = TEST_USERS["storyline_editor_headers"]


class TestTerritoryRightOverlap:
    def test_adjacent_rights_legal_and_exclusive_overlap_conflicts(self, api):
        """PRD §3.7: "Overlap rules run at half-open date granularity, so adjacent rights where one window's end equals the other's start are legal. An **exclusive** right conflicts with any other right on the same `territory_code` whose window intersects it. Two **non-exclusive** rights for the same territory and the *same* partner may not overlap (the self-overlap ban), while non-exclusive rights across *different* partners may overlap freely. Any conflict is rejected with `ERR_TERRITORY_RIGHT_CONFLICT` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/territory_right_half_open_adjacency_and_exclusive_overlap
        """
        p1 = create_streaming_partner(name="PCo1", partner_code="P1")
        p2 = create_streaming_partner(name="PCo2", partner_code="P2")
        create_territory_right(p1["id"], window_start_date="2026-01-01",
                               window_end_date="2026-09-01")
        # Adjacent under half-open semantics: touching at 2026-09-01 is legal.
        adjacent = api.create_territory_right(
            create_territory_right_payload(p2["id"], window_start_date="2026-09-01",
                                           window_end_date="2027-01-01"),
            DM)
        assert validate_success(adjacent, expected_status=201)["id"]
        # A new exclusive right intersecting the existing windows conflicts.
        conflict = api.create_territory_right(
            create_territory_right_payload(p2["id"], window_start_date="2026-06-01",
                                           window_end_date="2026-12-01",
                                           exclusive=True),
            DM)
        validate_error(conflict, ApiErrorId.ERR_TERRITORY_RIGHT_CONFLICT)

    def test_non_exclusive_rights_across_partners_may_overlap(self, api):
        """PRD §3.7: "Two **non-exclusive** rights for the same territory and the *same* partner may not overlap (the self-overlap ban), while non-exclusive rights across *different* partners may overlap freely."

        Design: Difficulty/resource_temporal_overlap/territory_right_half_open_adjacency_and_exclusive_overlap
        """
        p1 = create_streaming_partner(name="FreeCo1", partner_code="F1")
        p2 = create_streaming_partner(name="FreeCo2", partner_code="F2")
        create_territory_right(p1["id"], window_start_date="2026-01-01",
                               window_end_date="2026-12-01")
        free = api.create_territory_right(
            create_territory_right_payload(p2["id"], window_start_date="2026-06-01",
                                           window_end_date="2027-01-01"),
            DM)
        assert validate_success(free, expected_status=201)["id"]

    def test_same_partner_same_territory_self_overlap_banned(self, api):
        """PRD §3.7: "Two **non-exclusive** rights for the same territory and the *same* partner may not overlap (the self-overlap ban), while non-exclusive rights across *different* partners may overlap freely. Any conflict is rejected with `ERR_TERRITORY_RIGHT_CONFLICT` (HTTP 422)."

        Design: Corner/validations/same_partner_same_territory_self_overlap_banned
        """
        partner = create_streaming_partner(name="SelfCo", partner_code="SF")
        create_territory_right(partner["id"], window_start_date="2026-01-01",
                               window_end_date="2026-09-01")
        resp = api.create_territory_right(
            create_territory_right_payload(partner["id"], window_start_date="2026-06-01",
                                           window_end_date="2027-01-01"),
            DM)
        validate_error(resp, ApiErrorId.ERR_TERRITORY_RIGHT_CONFLICT)


class TestDistributionWindowCreation:
    def test_window_on_non_premium_event_rejected(self, api):
        """PRD §3.7: "The target event must be `PREMIUM` — otherwise `ERR_EVENT_NOT_PREMIUM`."

        Design: Corner/validations/distribution_window_on_non_premium_event_rejected
        """
        arena = create_arena(name="NP Arena")
        house = create_event(arena["id"], name="HE", event_date="2026-09-05")
        partner = create_streaming_partner(name="NPCo", partner_code="NP")
        create_territory_right(partner["id"], window_start_date="2026-09-01",
                               window_end_date="2026-10-01")
        resp = api.create_distribution_window(
            create_distribution_window_payload(house["id"], partner["id"],
                                               opens_at="2026-09-05T22:30:00Z",
                                               closes_at="2026-09-06T02:00:00Z"),
            DM)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_PREMIUM)

    def test_uncovered_window_dates_rejected_then_spanning_right_accepted(self, api):
        """PRD §3.7: "The territory must be licensed: the same partner must hold a `TerritoryRight` on the `territory_code` whose window spans the distribution window's dates, and that partner's status must be `ACTIVE`; a gap in licensing is rejected with `ERR_TERRITORY_NOT_LICENSED`."

        Design: Difficulty/cross_entity_state_dependency/distribution_window_gated_by_territory_right_and_partner_status
        """
        arena = create_arena(name="Dist Arena")
        event = create_event(arena["id"], name="DPE", event_type="PREMIUM",
                             event_date="2026-09-20", start_time="20:00", end_time="23:00")
        partner = create_streaming_partner(name="LateCo", partner_code="LC")
        # The right starts after the window's dates: no coverage.
        create_territory_right(partner["id"], window_start_date="2026-10-01",
                               window_end_date="2027-01-01")
        # Event starts 2026-09-21T00:00:00Z in the arena's America/New_York
        # timezone, so the LIVE pre-open floor is 2026-09-20T23:30:00Z.
        payload = create_distribution_window_payload(
            event["id"], partner["id"], opens_at="2026-09-20T23:30:00Z",
            closes_at="2026-09-21T04:00:00Z")
        uncovered = api.create_distribution_window(payload, DM)
        validate_error(uncovered, ApiErrorId.ERR_TERRITORY_NOT_LICENSED)
        # A spanning right (adjacent to the first at 2026-10-01) licenses it.
        create_territory_right(partner["id"], window_start_date="2026-09-01",
                               window_end_date="2026-10-01")
        covered = api.create_distribution_window(payload, DM)
        assert validate_success(covered, expected_status=201)["status"] == "PROVISIONAL"
    def test_missing_right_entirely_rejected(self, api):
        """PRD §3.7: "The territory must be licensed: the same partner must hold a `TerritoryRight` on the `territory_code` whose window spans the distribution window's dates, and that partner's status must be `ACTIVE`; a gap in licensing is rejected with `ERR_TERRITORY_NOT_LICENSED`."

        Design: Difficulty/cross_entity_state_dependency/distribution_window_gated_by_territory_right_and_partner_status
        """
        arena = create_arena(name="NoRight Arena")
        event = create_event(arena["id"], name="NRE", event_type="PREMIUM",
                             event_date="2026-09-20", start_time="20:00", end_time="23:00")
        partner = create_streaming_partner(name="NoCo", partner_code="NC")
        # The partner is ACTIVE but holds no TerritoryRight at all.
        resp = api.create_distribution_window(
            create_distribution_window_payload(event["id"], partner["id"],
                                               opens_at="2026-09-20T19:30:00Z",
                                               closes_at="2026-09-20T23:30:00Z"),
            DM)
        validate_error(resp, ApiErrorId.ERR_TERRITORY_NOT_LICENSED)


class TestDistributionWindowTiming:
    def test_replay_requires_24h_delay_boundary(self, api):
        """PRD §3.7: "Timing depends on the window type: a `LIVE` window may open no earlier than 30 minutes before the event's start instant in UTC, and a `REPLAY` window may open no earlier than 24 hours after the event's end instant in UTC."
        PRD §3.7: "Timing or overlap violations are rejected with `ERR_WINDOW_OVERLAP`."

        Design: Corner/calculations/replay_window_requires_24h_delay
        """
        event, partner, _right = setup_premium_event_with_spanning_right(
            partner_name="RepCo", partner_code="RC")
        # Event ends 2026-09-20 23:00 America/New_York == 2026-09-21T03:00:00Z.
        early = api.create_distribution_window(
            create_distribution_window_payload(
                event["id"], partner["id"], window_type="REPLAY",
                opens_at="2026-09-22T02:00:00Z", closes_at="2026-09-22T06:00:00Z"),
            DM)
        validate_error(early, ApiErrorId.ERR_WINDOW_OVERLAP)
        exact = api.create_distribution_window(
            create_distribution_window_payload(
                event["id"], partner["id"], window_type="REPLAY",
                opens_at="2026-09-22T03:00:00Z", closes_at="2026-09-22T07:00:00Z"),
            DM)
        assert validate_success(exact, expected_status=201)["status"] == "PROVISIONAL"

    def test_live_exactly_30min_preopen_accepted(self, api):
        """PRD §3.7: "Timing depends on the window type: a `LIVE` window may open no earlier than 30 minutes before the event's start instant in UTC, and a `REPLAY` window may open no earlier than 24 hours after the event's end instant in UTC."
        PRD §3.7: "Timing or overlap violations are rejected with `ERR_WINDOW_OVERLAP`."

        Design: Corner/calculations/live_window_exactly_30min_preopen_accepted
        """
        event, partner, _right = setup_premium_event_with_spanning_right(
            partner_name="LiveCo", partner_code="LV")
        # Event starts 2026-09-20 20:00 America/New_York == 2026-09-21T00:00:00Z.
        early = api.create_distribution_window(
            create_distribution_window_payload(
                event["id"], partner["id"], window_type="LIVE",
                opens_at="2026-09-20T23:29:00Z", closes_at="2026-09-21T04:00:00Z"),
            DM)
        validate_error(early, ApiErrorId.ERR_WINDOW_OVERLAP)
        exact = api.create_distribution_window(
            create_distribution_window_payload(
                event["id"], partner["id"], window_type="LIVE",
                opens_at="2026-09-20T23:30:00Z", closes_at="2026-09-21T04:00:00Z"),
            DM)
        assert validate_success(exact, expected_status=201)["status"] == "PROVISIONAL"


class TestDistributionWindowLifecycle:
    def test_revoke_then_terminal_lockdown(self, api):
        """PRD §3.7: "Revocation flips a window to `REVOKED` from either `PROVISIONAL` or `PUBLISHED`, and the same destination is reached automatically for any `PROVISIONAL` or `PUBLISHED` window when its event is cancelled. `REVOKED` is terminal."
        PRD §3.7: "Publishing a `PROVISIONAL` window moves it to `PUBLISHED`; the owning event must be `SCHEDULED` or `LOCKED` at publish time"

        Design: Corner/endpoints/distribution_window_revoke_and_terminal_lockdown
        """
        event, partner, _right = setup_premium_event_with_spanning_right(
            partner_name="RevCo", partner_code="RV")
        window = validate_success(api.create_distribution_window(
            create_distribution_window_payload(event["id"], partner["id"]), DM),
            expected_status=201)
        revoked = validate_success(api.revoke_distribution_window(window["id"], DM))
        assert revoked["status"] == "REVOKED"
        publish = api.publish_distribution_window(window["id"], DM)
        validate_error(publish, ApiErrorId.ERR_INVALID_STATE)


class TestDistributionConsistency:
    def test_cancel_visibility_without_booked_talent(self, api):
        """PRD §3.5: "Cancelling a `SCHEDULED` event unwinds everything downstream. Every `BOOKED` booking flips to `SCRATCHED`; every `PLANNED` chapter flips to `MISSED` with the gap-count increments and shelving rule of §3.4; and every distribution window on the event still `PROVISIONAL` or `PUBLISHED` flips to `REVOKED`."
        PRD §3.1: "New talent enters the system at the `DEVELOPMENTAL` roster tier with `availability_status` set to `ACTIVE`, a `wellness_score` that starts at the floor of 0.00, and — because a score that low satisfies neither booking threshold — an initial `booking_mode` of `UNBOOKABLE` until wellness activity raises the score."

        Design: Difficulty/transitive_cascade/event_cancel_cascades_bookings_chapters_windows
        """
        # Under the PRD a fresh talent is UNBOOKABLE, so the BOOKED-booking hop
        # of the cancel cascade is unreachable; the chapter and window hops are
        # fully derivable and asserted here.
        from test_helpers import (
            create_storyline, create_chapter, activate_storyline, get_storyline,
        )
        event, partner, _right = setup_premium_event_with_spanning_right(
            partner_name="CancelCo", partner_code="CC")
        storyline = create_storyline(title="Cancel Feud")
        chapter = create_chapter(storyline["id"], event["id"])
        activate_storyline(storyline["id"])
        window = validate_success(api.create_distribution_window(
            create_distribution_window_payload(event["id"], partner["id"]), DM),
            expected_status=201)
        validate_success(api.publish_distribution_window(window["id"], DM))
        validate_success(api.cancel_event(event["id"], TP))
        chapters = api.list_event_chapters(event["id"], SE)
        data, _ = validate_paginated(chapters)
        assert data[0]["id"] == chapter["id"]
        assert data[0]["status"] == "MISSED"
        assert get_storyline(storyline["id"])["gap_count"] == 1
        win = validate_success(api.get_distribution_window(window["id"], DM))
        assert win["status"] == "REVOKED"


class TestEventCancelSweeps:
    def test_cancel_revokes_windows_and_increments_gap(self, api):
        """PRD §3.5: "Cancelling a `SCHEDULED` event unwinds everything downstream. Every `BOOKED` booking flips to `SCRATCHED`; every `PLANNED` chapter flips to `MISSED` with the gap-count increments and shelving rule of §3.4; and every distribution window on the event still `PROVISIONAL` or `PUBLISHED` flips to `REVOKED`."

        Design: Difficulty/transitive_cascade/event_cancel_cascades_bookings_chapters_windows
        """
        from test_helpers import (
            create_storyline, create_chapter, activate_storyline, get_storyline,
        )
        event, partner, _right = setup_premium_event_with_spanning_right(
            partner_name="SweepCo", partner_code="SW")
        storyline = create_storyline(title="Sweep Feud")
        chapter = create_chapter(storyline["id"], event["id"])
        activate_storyline(storyline["id"])
        # Two windows on the same event: one PROVISIONAL, one PUBLISHED. Both
        # must flip to REVOKED on cancellation.
        w_prov = validate_success(api.create_distribution_window(
            create_distribution_window_payload(
                event["id"], partner["id"],
                opens_at="2026-09-20T23:30:00Z", closes_at="2026-09-21T01:00:00Z"),
            DM), expected_status=201)
        w_pub = validate_success(api.create_distribution_window(
            create_distribution_window_payload(
                event["id"], partner["id"],
                opens_at="2026-09-21T01:00:00Z", closes_at="2026-09-21T04:00:00Z"),
            DM), expected_status=201)
        validate_success(api.publish_distribution_window(w_pub["id"], DM))
        cancelled = validate_success(api.cancel_event(event["id"], TP))
        assert cancelled["status"] == "CANCELLED"
        for w in (w_prov, w_pub):
            assert validate_success(api.get_distribution_window(w["id"], DM))["status"] == "REVOKED"
        chapters, _ = validate_paginated(api.list_event_chapters(event["id"], SE))
        assert chapters[0]["id"] == chapter["id"]
        assert chapters[0]["status"] == "MISSED"
        assert get_storyline(storyline["id"])["gap_count"] == 1
