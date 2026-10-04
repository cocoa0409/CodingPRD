"""Coaching sessions: assignment, window overlap, lockdown, overdue sweep."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_confirmed_event,
    get_event_auto_session,
    make_driver_headers,
    setup_base,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_manual_session_payload,
    reassign_session_payload,
)
from test_helpers.fixtures import set_clock

MANAGER = TEST_USERS["safety_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _confirmed_medium(base):
    return create_confirmed_event(
        base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
        event_type="HARSH_BRAKE", severity="MEDIUM",
        occurred_at="2026-08-30T00:00:00Z",
    )


class TestSessionWindowOverlap:
    def test_coaching_sessions_half_open_adjacency_admitted(self, api, safety_manager_headers):
        """PRD §3.6: "its window must not overlap the driver's other occupying
        sessions: session windows are half-open — inclusive at `starts_at`,
        exclusive at `ends_at` — so a session beginning exactly when another
        ends does not overlap, and any true overlap is rejected with
        `ERR_SESSION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/coaching_sessions_half_open_adjacency
        """
        base = setup_base()
        event = _confirmed_medium(base)
        first = validate_success(
            api.create_coaching_session(
                base["driver"]["id"],
                create_manual_session_payload(
                    event["id"],
                    starts_at="2026-09-02T10:00:00Z",
                    ends_at="2026-09-02T11:00:00Z",
                    due_at="2026-09-09T00:00:00Z",
                ),
                safety_manager_headers,
            ),
            201,
        )
        assert first["status"] == "ASSIGNED"
        second = validate_success(
            api.create_coaching_session(
                base["driver"]["id"],
                create_manual_session_payload(
                    event["id"],
                    starts_at="2026-09-02T11:00:00Z",
                    ends_at="2026-09-02T12:00:00Z",
                    due_at="2026-09-09T00:00:00Z",
                ),
                safety_manager_headers,
            ),
            201,
        )
        assert second["status"] == "ASSIGNED"

    def test_coaching_sessions_true_overlap_rejected(self, api, safety_manager_headers):
        """PRD §3.6: "its window must not overlap the driver's other occupying
        sessions: session windows are half-open — inclusive at `starts_at`,
        exclusive at `ends_at` — so a session beginning exactly when another
        ends does not overlap, and any true overlap is rejected with
        `ERR_SESSION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/coaching_sessions_half_open_adjacency
        """
        base = setup_base()
        event = _confirmed_medium(base)
        validate_success(
            api.create_coaching_session(
                base["driver"]["id"],
                create_manual_session_payload(
                    event["id"],
                    starts_at="2026-09-02T10:00:00Z",
                    ends_at="2026-09-02T11:00:00Z",
                    due_at="2026-09-09T00:00:00Z",
                ),
                safety_manager_headers,
            ),
            201,
        )
        resp = api.create_coaching_session(
            base["driver"]["id"],
            create_manual_session_payload(
                event["id"],
                starts_at="2026-09-02T10:30:00Z",
                ends_at="2026-09-02T11:30:00Z",
                due_at="2026-09-09T00:00:00Z",
            ),
            safety_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_WINDOW_OVERLAP)
        rows, _ = validate_paginated(
            api.list_driver_coaching_sessions(base["driver"]["id"], MANAGER)
        )
        assert len(rows) == 1


class TestSessionCompleteGating:
    def test_session_complete_blocked_when_fleet_locked(self, api, safety_manager_headers, platform_admin_headers):
        """PRD §2.9: "While a fleet is in `INCIDENT_LOCKDOWN`, three
        operations are blocked across the platform: confirming an event in
        review, completing a coaching session, and computing a score snapshot.
        Each is rejected with `ERR_FLEET_LOCKED`."
        PRD §3.6: "Completion is recorded by a `SafetyManager` against an
        `ACKNOWLEDGED` session with an `outcome` of `PASS` or `FAIL`
        (optionally with `notes`), stamping `completed_at`; completion is
        blocked while the fleet is in `INCIDENT_LOCKDOWN`
        (`ERR_FLEET_LOCKED`)."

        Design: Difficulty/cross_entity_state_dependency/session_complete_blocked_when_fleet_locked
        """
        base = setup_base()
        event = create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="HIGH",
            occurred_at="2026-08-30T00:00:00Z",
        )
        session = get_event_auto_session(event["id"])
        validate_success(
            api.acknowledge_coaching_session(
                session["id"], make_driver_headers(base["driver"]["id"])
            ),
            200,
        )
        validate_success(
            api.set_fleet_posture(
                base["fleet"]["id"],
                {"posture": "INCIDENT_LOCKDOWN", "note": "depot incident under investigation"},
                platform_admin_headers,
            ),
            200,
        )
        resp = api.complete_coaching_session(
            session["id"], {"outcome": "PASS", "notes": "done during lockdown?"},
            safety_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FLEET_LOCKED)
        during = validate_success(api.get_coaching_session(session["id"], MANAGER), 200)
        assert during["status"] == "ACKNOWLEDGED"
        assert during["completed_at"] is None
        validate_success(
            api.set_fleet_posture(
                base["fleet"]["id"], {"posture": "NORMAL", "note": "cleared"},
                platform_admin_headers,
            ),
            200,
        )
        completed = validate_success(
            api.complete_coaching_session(
                session["id"], {"outcome": "PASS", "notes": "done after lockdown"},
                safety_manager_headers,
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["outcome"] == "PASS"

    def test_session_complete_succeeds_while_normal_posture(self, api, safety_manager_headers):
        """PRD §3.6: "Completion is recorded by a `SafetyManager` against an
        `ACKNOWLEDGED` session with an `outcome` of `PASS` or `FAIL`
        (optionally with `notes`), stamping `completed_at`; completion is
        blocked while the fleet is in `INCIDENT_LOCKDOWN`
        (`ERR_FLEET_LOCKED`)."

        Design: Difficulty/cross_entity_state_dependency/session_complete_blocked_when_fleet_locked
        """
        base = setup_base()
        event = create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="HIGH",
            occurred_at="2026-08-30T00:00:00Z",
        )
        session = get_event_auto_session(event["id"])
        validate_success(
            api.acknowledge_coaching_session(
                session["id"], make_driver_headers(base["driver"]["id"])
            ),
            200,
        )
        completed = validate_success(
            api.complete_coaching_session(
                session["id"], {"outcome": "FAIL", "notes": "needs follow-up"},
                safety_manager_headers,
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["outcome"] == "FAIL"
        assert completed["completed_at"] is not None


class TestSessionStateMachine:
    def test_coaching_complete_from_assigned_rejected(self, api, safety_manager_headers):
        """PRD §3.6: "Completion is recorded by a `SafetyManager` against an
        `ACKNOWLEDGED` session with an `outcome` of `PASS` or `FAIL`."

        Design: Corner/state_machines/coaching_complete_from_assigned_rejected
        """
        base = setup_base()
        event = create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="HIGH",
            occurred_at="2026-08-30T00:00:00Z",
        )
        session = get_event_auto_session(event["id"])
        resp = api.complete_coaching_session(
            session["id"], {"outcome": "PASS"}, safety_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_coaching_session(session["id"], MANAGER), 200)
        assert after["status"] == "ASSIGNED"
        assert after["completed_at"] is None

    def test_coaching_completed_terminal_rejects_reassign(self, api, safety_manager_headers):
        """PRD §3.6: "An overdue session may be reassigned by a
        `SafetyManager` with a fresh `starts_at`, `ends_at`, and `due_at`
        (optionally annotated with a `reason`), returning it to `ASSIGNED` ...
        `COMPLETED` and `CANCELLED` are terminal."

        Design: Corner/state_machines/coaching_completed_terminal_rejects_reassign
        """
        base = setup_base()
        event = create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="HIGH",
            occurred_at="2026-08-30T00:00:00Z",
        )
        session = get_event_auto_session(event["id"])
        validate_success(
            api.acknowledge_coaching_session(
                session["id"], make_driver_headers(base["driver"]["id"])
            ),
            200,
        )
        validate_success(
            api.complete_coaching_session(
                session["id"], {"outcome": "PASS"}, safety_manager_headers
            ),
            200,
        )
        resp = api.reassign_coaching_session(
            session["id"], reassign_session_payload(), safety_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_coaching_session(session["id"], MANAGER), 200)
        assert after["status"] == "COMPLETED"
        assert after["reassign_count"] == 0


class TestMaintenanceSweep:
    def test_coaching_overdue_maintenance_sweep(self, api, safety_manager_headers, platform_admin_headers):
        """PRD §3.9: "The sweep examines the fleet's sessions in `ASSIGNED` or
        `ACKNOWLEDGED` whose `due_at` is strictly earlier than the logical
        clock — a session whose deadline equals the clock exactly is not yet
        overdue — and moves each to `OVERDUE`, processing them in `due_at`
        ascending order with ties broken by `created_at` ascending."
        PRD §3.6: "An overdue session may be reassigned by a `SafetyManager`
        with a fresh `starts_at`, `ends_at`, and `due_at` (optionally
        annotated with a `reason`), returning it to `ASSIGNED`; reassignment
        replaces the three timestamps, increments `reassign_count`, and
        enforces the same non-overlap rule as manual assignment."

        Design: Corner/state_machines/coaching_overdue_maintenance_sweep
        """
        base = setup_base()
        event = _confirmed_medium(base)
        session = validate_success(
            api.create_coaching_session(
                base["driver"]["id"],
                create_manual_session_payload(
                    event["id"],
                    starts_at="2026-09-02T10:00:00Z",
                    ends_at="2026-09-02T11:00:00Z",
                    due_at="2026-09-03T00:00:00Z",
                ),
                safety_manager_headers,
            ),
            201,
        )
        # Clock exactly at due_at: not yet overdue.
        set_clock("2026-09-03T00:00:00Z")
        validate_success(api.run_maintenance(base["fleet"]["id"], platform_admin_headers), 200)
        at_deadline = validate_success(
            api.get_coaching_session(session["id"], MANAGER), 200
        )
        assert at_deadline["status"] == "ASSIGNED"
        # Clock strictly past due_at: swept to OVERDUE.
        set_clock("2026-09-04T00:00:00Z")
        validate_success(api.run_maintenance(base["fleet"]["id"], platform_admin_headers), 200)
        overdue = validate_success(api.get_coaching_session(session["id"], MANAGER), 200)
        assert overdue["status"] == "OVERDUE"
        fleet = validate_success(api.get_fleet(base["fleet"]["id"], platform_admin_headers), 200)
        assert fleet["ops_run_index"] == 2
        reassigned = validate_success(
            api.reassign_coaching_session(
                session["id"],
                reassign_session_payload(reason="rescheduled"),
                safety_manager_headers,
            ),
            200,
        )
        assert reassigned["status"] == "ASSIGNED"
        assert reassigned["reassign_count"] == 1
        assert reassigned["starts_at"] == "2026-09-05T10:00:00.000Z"
        assert reassigned["due_at"] == "2026-09-12T00:00:00.000Z"


class TestRunMaintenance:
    def test_run_maintenance_advances_ops_index(self, api, platform_admin_headers):
        """PRD §3.9: "The platform recomputes derived state through an ops-run
        checkpoint: a `PlatformAdmin` invokes run-maintenance on a fleet,
        which increments the fleet's `ops_run_index` by one, sweeps coaching
        sessions, and refreshes derived score fields for all drivers of the
        fleet."

        Design: Corner/endpoints/run_maintenance_advances_ops_index
        """
        base = setup_base()
        validate_success(api.run_maintenance(base["fleet"]["id"], platform_admin_headers), 200)
        validate_success(api.run_maintenance(base["fleet"]["id"], platform_admin_headers), 200)
        fleet = validate_success(api.get_fleet(base["fleet"]["id"], platform_admin_headers), 200)
        assert fleet["ops_run_index"] == 2
        assert fleet["version"] == 3
