"""Escalation: repeat offenses, the coaching hold, and cross-entity gating."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_event,
    ingest_event,
    register_clip,
    review_event,
    setup_base,
    upload_clip,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["safety_manager_headers"]
INGEST = TEST_USERS["telematics_ingest_headers"]


def _confirmed_low_events(base, count):
    """Ingest + upload + confirm `count` LOW SEAT_BELT events for the driver."""
    events = []
    for i in range(count):
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="SEAT_BELT", severity="LOW",
            occurred_at=f"2026-08-{28 + i:02d}T00:00:00Z",
        )
        clip = register_clip(
            event["id"], size_mb=2, captured_at=f"2026-08-{28 + i:02d}T00:00:00Z"
        )
        upload_clip(clip["id"])
        events.append(event)
    return events


class TestEscalationThreshold:
    def test_two_confirmations_leave_driver_active(self, api):
        """PRD §3.7: "When a confirmation moves this count from exactly 2 to 3
        or more, the platform opens an `EscalationCase` in `OPEN` status,
        recording the confirming event in `trigger_event_id`, the new count in
        `offense_count`, and the window length in `window_days` (always 90),
        and simultaneously moves the driver `ACTIVE` → `COACHING_HOLD`. The
        second confirmed event triggers nothing; the third does."

        Design: Difficulty/boundary_precision_check/third_confirmed_event_exactly_triggers_escalation
        """
        base = setup_base()
        events = _confirmed_low_events(base, 3)
        for event in events[:2]:
            review_event(event["id"], "CONFIRM", rationale="belt")
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert driver["confirmed_events_90d"] == 2
        assert driver["status"] == "ACTIVE"
        rows, meta = validate_paginated(
            api.list_driver_escalation_cases(base["driver"]["id"], MANAGER)
        )
        assert len(rows) == 0

    def test_third_confirmation_opens_case_and_holds_driver(self, api):
        """PRD §3.7: "When a confirmation moves this count from exactly 2 to 3
        or more, the platform opens an `EscalationCase` in `OPEN` status,
        recording the confirming event in `trigger_event_id`, the new count in
        `offense_count`, and the window length in `window_days` (always 90),
        and simultaneously moves the driver `ACTIVE` → `COACHING_HOLD`. The
        second confirmed event triggers nothing; the third does."
        PRD §3.4: "First, if the event's severity is `HIGH` or `CRITICAL`, a
        coaching session is auto-created in `ASSIGNED` status."

        Design: Difficulty/boundary_precision_check/third_confirmed_event_exactly_triggers_escalation
        """
        base = setup_base()
        events = _confirmed_low_events(base, 3)
        for event in events:
            review_event(event["id"], "CONFIRM", rationale="belt")
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert driver["confirmed_events_90d"] == 3
        assert driver["status"] == "COACHING_HOLD"
        rows, meta = validate_paginated(
            api.list_driver_escalation_cases(base["driver"]["id"], MANAGER)
        )
        assert len(rows) == 1
        case = rows[0]
        assert case["status"] == "OPEN"
        assert case["offense_count"] == 3
        assert case["trigger_event_id"] == events[2]["id"]
        # LOW-severity confirmations auto-create no coaching sessions.
        sessions, _ = validate_paginated(
            api.list_driver_coaching_sessions(base["driver"]["id"], MANAGER)
        )
        assert len(sessions) == 0


class TestConfirmCascade:
    def test_confirm_to_session_to_escalation_to_driver_hold(self, api):
        """PRD §3.4: "On confirmation the server stamps `confirmed_at` with
        the logical clock and executes a four-link cascade in order. First, if
        the event's severity is `HIGH` or `CRITICAL`, a coaching session is
        auto-created in `ASSIGNED` status with `assigned_by` recorded as
        `SYSTEM`, its window starting at the current logical clock and ending
        seven days later, and `due_at` equal to that same end; auto-created
        sessions are exempt from the session-window overlap rule that
        constrains manual assignment. Second, the driver's
        `confirmed_events_90d` count and both safety score variants are
        recomputed. Third, if this confirmation moved the driver's rolling
        90-day confirmed count from exactly 2 to 3 or more, an escalation case
        opens automatically in `OPEN` status with `trigger_event_id` pointing
        at this event and `offense_count` recording the new count. Fourth,
        that case opening transitions the driver from `ACTIVE` to
        `COACHING_HOLD`."

        Design: Difficulty/transitive_cascade/confirm_to_session_to_escalation_to_driver_hold
        """
        base = setup_base()
        ev_ids = []
        for i, (etype, occurred) in enumerate([
            ("HARSH_BRAKE", "2026-08-28T00:00:00Z"),
            ("DISTRACTION", "2026-08-29T00:00:00Z"),
            ("FOLLOWING_DISTANCE", "2026-08-30T00:00:00Z"),
        ]):
            event = ingest_event(
                base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
                event_type=etype, severity="HIGH", occurred_at=occurred,
            )
            clip = register_clip(event["id"], captured_at=occurred)
            upload_clip(clip["id"])
            ev_ids.append(event["id"])
        for ev in ev_ids[:2]:
            review_event(ev, "CONFIRM", rationale="confirmed")
        # Third confirmation: the cascade fires.
        review_event(ev_ids[2], "CONFIRM", rationale="third strike confirmed")
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert driver["confirmed_events_90d"] == 3
        assert driver["status"] == "COACHING_HOLD"
        assert float(driver["safety_score_final"]) == 55.00
        cases, _ = validate_paginated(
            api.list_driver_escalation_cases(base["driver"]["id"], MANAGER)
        )
        assert len(cases) == 1
        assert cases[0]["status"] == "OPEN"
        assert cases[0]["offense_count"] == 3
        assert cases[0]["trigger_event_id"] == ev_ids[2]
        sessions, _ = validate_paginated(
            api.list_event_coaching_sessions(ev_ids[2], MANAGER)
        )
        assert len(sessions) == 1
        assert sessions[0]["status"] == "ASSIGNED"
        assert sessions[0]["assigned_by"] == "SYSTEM"
        assert sessions[0]["due_at"] == "2026-09-08T00:00:00.000Z"

    def test_high_confirm_auto_creates_assigned_session(self, api):
        """PRD §3.4: "First, if the event's severity is `HIGH` or `CRITICAL`,
        a coaching session is auto-created in `ASSIGNED` status with
        `assigned_by` recorded as `SYSTEM`, its window starting at the current
        logical clock and ending seven days later, and `due_at` equal to that
        same end."

        Design: Difficulty/transitive_cascade/confirm_to_session_to_escalation_to_driver_hold
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="HIGH",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        review_event(event["id"], "CONFIRM", rationale="coach this")
        sessions, _ = validate_paginated(
            api.list_event_coaching_sessions(event["id"], MANAGER)
        )
        assert len(sessions) == 1
        session = sessions[0]
        assert session["status"] == "ASSIGNED"
        assert session["assigned_by"] == "SYSTEM"
        assert session["due_at"] == "2026-09-08T00:00:00.000Z"


class TestCrossEntityDependencies:
    def test_review_confirm_requires_driver_active(self, api, safety_manager_headers):
        """PRD §3.4: "Confirming an event from `IN_REVIEW` to `CONFIRMED` is
        the most consequential action in the system and is guarded by three
        preconditions: the fleet must be in `NORMAL` posture (otherwise
        `ERR_FLEET_LOCKED`), the driver must be in `ACTIVE` or `COACHING_HOLD`
        status (otherwise `ERR_DRIVER_NOT_ACTIVE`), and if the event carries
        an inward-facing clip the privacy gate of Section 2.8 must pass
        (otherwise `ERR_INWARD_FOOTAGE_RESTRICTED`)."

        Design: Difficulty/cross_entity_state_dependency/review_confirm_requires_driver_active
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        validate_success(
            api.set_driver_status(
                base["driver"]["id"],
                {"to_status": "SUSPENDED", "reason": "pending investigation"},
                safety_manager_headers,
            ),
            200,
        )
        current = get_event(event["id"])
        resp = api.review_safety_event(
            event["id"],
            {
                "action": "CONFIRM",
                "rationale": "attempt on suspended driver",
                "expected_event_version": current["version"],
            },
            safety_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_ACTIVE)
        after = get_event(event["id"])
        assert after["status"] == "IN_REVIEW"
        assert after["review_count"] == 0
        rows, _ = validate_paginated(
            api.list_event_review_decisions(event["id"], MANAGER)
        )
        assert len(rows) == 0

    def test_review_confirm_rejected_for_inactive_driver_too(self, api, safety_manager_headers):
        """PRD §3.4: "the driver must be in `ACTIVE` or `COACHING_HOLD`
        status (otherwise `ERR_DRIVER_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/review_confirm_requires_driver_active
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        validate_success(
            api.set_driver_status(
                base["driver"]["id"],
                {"to_status": "INACTIVE", "reason": "left the fleet"},
                safety_manager_headers,
            ),
            200,
        )
        current = get_event(event["id"])
        resp = api.review_safety_event(
            event["id"],
            {
                "action": "CONFIRM",
                "rationale": "attempt on inactive driver",
                "expected_event_version": current["version"],
            },
            safety_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_ACTIVE)
        after = get_event(event["id"])
        assert after["status"] == "IN_REVIEW"
