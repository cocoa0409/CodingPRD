"""The five-part PUBLISH precondition battery and resource schedule conflicts
(PRD §2.8, §3.2)."""
from test_helpers import (
    ApiErrorId,
    assert_flight,
    create_balloon,
    create_draft_flight,
    create_granted_site,
    create_inspected_balloon,
    create_launch_site,
    create_pilot,
    get_flight,
    get_success_data,
    set_clock,
    setup_publish_ready,
    validate_error,
    validate_success,
)

def _publish(api, flight_id, headers):
    return api.flight_event(flight_id, {"event_type": "PUBLISH"}, headers)


class TestPublishHappyPath:
    def test_flight_publish_valid_transition(self, api, ops_headers):
        """PRD §3.2: "An `OperationsManager` publishes a flight, moving `status`
        from `DRAFT` to `SCHEDULED`, only when a five-part precondition battery
        passes". "A successful publish increments the flight's `version`."

        Design: Corner/state_machines/flight_publish_valid_transition
        """
        ctx = setup_publish_ready()
        flight = create_draft_flight(ctx)
        assert flight["status"] == "DRAFT"
        published = get_success_data(_publish(api, flight["id"], ops_headers))
        assert_flight(published)
        assert published["status"] == "SCHEDULED"
        assert published["version"] == flight["version"] + 1, (
            "publish increments the flight's version by one"
        )

    def test_immediate_visibility_after_mutation(self, api, ops_headers):
        """PRD §2.8: "These cascades are immediate: every effect is visible
        within the same request/response that triggered it."
        PRD §3.2: "A successful publish increments the flight's `version`."

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        ctx = setup_publish_ready()
        flight = create_draft_flight(ctx)
        data = validate_success(_publish(api, flight["id"], ops_headers))
        # The PUBLISH response itself carries the new state — no re-read needed.
        assert data["status"] == "SCHEDULED"
        assert data["version"] == flight["version"] + 1


class TestPublishPreconditionBattery:
    def test_publish_fails_with_pending_site_permission(self, api, ops_headers):
        """PRD §3.2: "The launch site's `permission_status` is `GRANTED` and its
        `permission_expires_on` falls on or after `scheduled_date`;
        otherwise the publish is rejected with
        `ERR_SITE_PERMISSION_NOT_GRANTED` (HTTP 409)."

        Design: Corner/validations/publish_fails_with_pending_site_permission
        """
        set_clock()
        site = create_launch_site()  # never granted -> stays PENDING
        balloon = create_inspected_balloon()
        pilot = create_pilot()
        flight = create_draft_flight({"site": site, "balloon": balloon, "pilot": pilot})
        validate_error(_publish(api, flight["id"], ops_headers),
                       ApiErrorId.ERR_SITE_PERMISSION_NOT_GRANTED)

    def test_publish_fails_with_expired_pilot(self, api, ops_headers):
        """PRD §3.2: "The pilot's `currency_status` is `CURRENT` per §2.10;
        otherwise `ERR_PILOT_NOT_CURRENT` (HTTP 409)."

        Design: Corner/validations/publish_fails_with_expired_pilot
        """
        ctx = setup_publish_ready(
            pilot_kw={"external_pic_hours_180d": 2.0, "external_takeoffs_landings_90d": 1}
        )
        flight = create_draft_flight(ctx)
        validate_error(_publish(api, flight["id"], ops_headers),
                       ApiErrorId.ERR_PILOT_NOT_CURRENT)
        assert get_flight(flight["id"])["status"] == "DRAFT"

    def test_publish_rejected_with_grounded_balloon(self, api, ops_headers):
        """PRD §3.2: "The balloon's `status` is `ACTIVE`, its
        `inspection_due_on` is not null, and `inspection_due_on` falls on
        or after `scheduled_date`; otherwise `ERR_BALLOON_GROUNDED`."

        Design: Difficulty/cross_entity_state_dependency/publish_requires_balloon_active
        """
        ctx = setup_publish_ready()
        flight = create_draft_flight(ctx)
        get_success_data(
            api.balloon_event(ctx["balloon"]["id"], {"event_type": "GROUND"}, ops_headers)
        )
        validate_error(_publish(api, flight["id"], ops_headers),
                       ApiErrorId.ERR_BALLOON_GROUNDED)
        assert get_flight(flight["id"])["status"] == "DRAFT", (
            "a rejected publish leaves the flight in DRAFT"
        )

    def test_publish_rejected_with_uninspected_balloon(self, api, ops_headers):
        """PRD §3.2: "The balloon's `status` is `ACTIVE`, its
        `inspection_due_on` is not null, and `inspection_due_on` falls on
        or after `scheduled_date`; otherwise `ERR_BALLOON_GROUNDED`."
        PRD §3.1: "Until a balloon's first inspection, both `last_inspection_on`
        and `inspection_due_on` are null."

        Design: Difficulty/cross_entity_state_dependency/publish_requires_balloon_active
        """
        set_clock()
        site = create_granted_site()
        balloon = create_balloon()  # ACTIVE but never inspected
        pilot = create_pilot()
        flight = create_draft_flight({"site": site, "balloon": balloon, "pilot": pilot})
        validate_error(_publish(api, flight["id"], ops_headers),
                       ApiErrorId.ERR_BALLOON_GROUNDED)


class TestBalloonScheduleConflicts:
    def test_balloon_overlap_rejected_but_adjacent_allowed(self, api, ops_headers):
        """PRD §3.2: "No other flight using the same `balloon_id` and sitting in
        `SCHEDULED`, `WEATHER_REVIEW`, `CLEARED_FOR_LAUNCH`, or `AIRBORNE` has a
        dawn window that overlaps this flight's window, where overlap is judged
        on the half-open interval from `dawn_window_start` (inclusive) to
        `dawn_window_end` (exclusive) — two windows that merely touch at an
        endpoint do not conflict. A violating overlap is rejected with
        `ERR_BALLOON_SCHEDULE_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/balloon_half_open_window_overlap
        """
        ctx = setup_publish_ready()
        pilot2 = create_pilot(external_pic_hours_180d=15.0, external_takeoffs_landings_90d=4)

        f1 = create_draft_flight(ctx)  # 2026-08-10 05:30-07:00Z
        get_success_data(_publish(api, f1["id"], ops_headers))

        # Overlapping window 06:30-08:00 on the same balloon -> conflict.
        f2 = create_draft_flight(
            ctx,
            pilot_id=pilot2["id"],
            dawn_window_start="2026-08-10T06:30:00Z",
            dawn_window_end="2026-08-10T08:00:00Z",
        )
        validate_error(_publish(api, f2["id"], ops_headers),
                       ApiErrorId.ERR_BALLOON_SCHEDULE_CONFLICT)

        # Adjacent window starting exactly at f1's dawn_window_end -> allowed.
        f3 = create_draft_flight(
            ctx,
            pilot_id=pilot2["id"],
            dawn_window_start="2026-08-10T07:00:00Z",
            dawn_window_end="2026-08-10T08:30:00Z",
        )
        published = get_success_data(_publish(api, f3["id"], ops_headers))
        assert published["status"] == "SCHEDULED", (
            "half-open adjacency at dawn_window_end must not conflict"
        )

    def test_balloon_freed_by_cancellation(self, api, ops_headers):
        """PRD §3.2: "No other flight using the same `balloon_id` and sitting in
        `SCHEDULED`, `WEATHER_REVIEW`, `CLEARED_FOR_LAUNCH`, or `AIRBORNE` has a
        dawn window that overlaps this flight's window, where overlap is judged
        on the half-open interval from `dawn_window_start` (inclusive) to
        `dawn_window_end` (exclusive) — two windows that merely touch at an
        endpoint do not conflict. A violating overlap is rejected with
        `ERR_BALLOON_SCHEDULE_CONFLICT` (HTTP 409)." — a `CANCELLED` flight is
        not one of the four blocking states.

        Design: Difficulty/resource_temporal_overlap/balloon_half_open_window_overlap
        """
        ctx = setup_publish_ready()
        pilot2 = create_pilot(external_pic_hours_180d=15.0, external_takeoffs_landings_90d=4)

        f1 = create_draft_flight(ctx)
        get_success_data(_publish(api, f1["id"], ops_headers))
        get_success_data(
            api.flight_event(f1["id"], {"event_type": "CANCEL"}, ops_headers)
        )
        assert get_flight(f1["id"])["status"] == "CANCELLED"

        f2 = create_draft_flight(ctx, pilot_id=pilot2["id"])
        published = get_success_data(_publish(api, f2["id"], ops_headers))
        assert published["status"] == "SCHEDULED", (
            "a cancelled flight no longer blocks its balloon's window"
        )


class TestPilotScheduleConflicts:
    def test_pilot_same_date_conflict_and_next_day_free(self, api, ops_headers):
        """PRD §3.2: "No other flight using the same `pilot_id` in those same
        four states shares this flight's `scheduled_date`; otherwise
        `ERR_PILOT_SCHEDULE_CONFLICT` (HTTP 409)." — the pilot rule is
        date-granular, so even a disjoint window on the same date conflicts.

        Design: Difficulty/resource_temporal_overlap/pilot_same_date_conflict
        """
        ctx = setup_publish_ready()
        balloon2 = create_inspected_balloon()
        pilot = ctx["pilot"]

        f1 = create_draft_flight(ctx)  # p1, 2026-08-10 05:30-07:00Z
        get_success_data(_publish(api, f1["id"], ops_headers))

        # Same pilot, same date, disjoint midday window -> conflict.
        f2 = create_draft_flight(
            ctx,
            balloon_id=balloon2["id"],
            dawn_window_start="2026-08-10T12:00:00Z",
            dawn_window_end="2026-08-10T13:30:00Z",
        )
        validate_error(_publish(api, f2["id"], ops_headers),
                       ApiErrorId.ERR_PILOT_SCHEDULE_CONFLICT)

        # Same pilot, next date -> allowed.
        f3 = create_draft_flight(
            ctx,
            balloon_id=balloon2["id"],
            scheduled_date="2026-08-11",
            dawn_window_start="2026-08-11T05:30:00Z",
            dawn_window_end="2026-08-11T07:00:00Z",
        )
        published = get_success_data(_publish(api, f3["id"], ops_headers))
        assert published["status"] == "SCHEDULED"

    def test_pilot_freed_by_cancellation_same_date(self, api, ops_headers):
        """PRD §3.2: "No other flight using the same `pilot_id` in those same
        four states shares this flight's `scheduled_date`; otherwise
        `ERR_PILOT_SCHEDULE_CONFLICT` (HTTP 409)." — a `CANCELLED` flight is not
        one of the four blocking states.

        Design: Difficulty/resource_temporal_overlap/pilot_same_date_conflict
        """
        ctx = setup_publish_ready()
        balloon2 = create_inspected_balloon()
        f1 = create_draft_flight(ctx)
        get_success_data(_publish(api, f1["id"], ops_headers))
        get_success_data(api.flight_event(f1["id"], {"event_type": "CANCEL"}, ops_headers))

        f2 = create_draft_flight(ctx, balloon_id=balloon2["id"])
        published = get_success_data(_publish(api, f2["id"], ops_headers))
        assert published["status"] == "SCHEDULED", (
            "a cancelled flight no longer blocks its pilot's date"
        )
