"""Onboarding foundations, authentication, and RBAC denials."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_fleet,
    assert_safety_event,
    assert_terminal,
    assert_vehicle,
    create_terminal,
    create_union_agreement_payload,
    get_event,
    ingest_event,
    make_driver_headers,
    make_safety_manager_headers,
    reset_clock_default,
    set_clock,
    setup_base,
    upload_clip,
    register_clip,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_driver_payload,
    create_fleet_payload,
    create_litigation_hold_payload,
    create_safety_event_payload,
    create_vehicle_payload,
)
from test_helpers.fixtures import create_fleet, get_event_auto_session, review_event


class TestFleetOnboarding:
    def test_fleet_create_returns_defaults(self, api, platform_admin_headers):
        """PRD §3.1: "A new fleet starts with `posture` `NORMAL`, an
        `ops_run_index` of 0, and `retention_used_mb` of 0."

        Design: Corner/entities/fleet_create_returns_defaults
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.create_fleet(create_fleet_payload(), platform_admin_headers)
        fleet = validate_success(resp, 201)
        assert_fleet(fleet)
        assert fleet["posture"] == "NORMAL"
        assert fleet["ops_run_index"] == 0
        assert fleet["retention_used_mb"] == 0
        assert fleet["version"] == 1


class TestTerminalRetrieval:
    def test_terminal_get_roundtrips_stored_fields(self, api, platform_admin_headers, safety_manager_headers):
        """PRD §3.1: "Terminals are then registered against the fleet by
        `fleet_id`, each with a `name` and a two-letter `region_code`. Every
        terminal exposes a computed `safety_score_cached` holding the
        terminal-level aggregation defined in Section 3.9."
        PRD §3.9: "The fleet score is the mean of the terminal scores over
        terminals having at least one non-`INACTIVE` driver, rounded half-up
        to two decimal places, and a fleet with no such terminal scores
        100.00."

        Design: Corner/entities/terminal_get_roundtrips_stored_fields
        """
        set_clock("2026-09-01T00:00:00Z")
        fleet = create_fleet()
        terminal = create_terminal(fleet["id"], name="Knoxville Depot", region_code="TN")
        resp = api.get_terminal(terminal["id"], safety_manager_headers)
        got = validate_success(resp, 200)
        assert_terminal(got)
        assert got["name"] == "Knoxville Depot"
        assert got["region_code"] == "TN"
        assert got["fleet_id"] == fleet["id"]
        assert float(got["safety_score_cached"]) == 100.00


class TestVehicleDefaults:
    def test_vehicle_create_defaults_status_active(self, api, platform_admin_headers):
        """PRD §3.1: "A new vehicle starts `ACTIVE`; decommissioning moves it
        to `DECOMMISSIONED` and is only permitted while the vehicle has no
        events still sitting in `DETECTED` or `IN_REVIEW`."

        Design: Corner/entities/vehicle_create_defaults_status_active
        """
        set_clock("2026-09-01T00:00:00Z")
        fleet = create_fleet()
        terminal = create_terminal(fleet["id"])
        resp = api.create_vehicle(
            create_vehicle_payload(
                terminal["id"], vin="5YJSA1E26HF122334",
                camera_unit_id="CAM-12", bandwidth_tier="LOW",
            ),
            platform_admin_headers,
        )
        vehicle = validate_success(resp, 201)
        assert_vehicle(vehicle)
        assert vehicle["status"] == "ACTIVE"
        assert vehicle["version"] == 1


class TestDriverCreationRules:
    def test_driver_create_computed_fields_input_ignored(self, api, platform_admin_headers):
        """PRD §3.9: "Both variants are computed on read and recomputed after
        every review action, every exoneration decision, and every clock
        movement observed via maintenance. The driver's `incentive_tier`
        derives from `safety_score_final` per the pricing table below."

        Design: Corner/entities/driver_create_computed_fields_input_ignored
        """
        set_clock("2026-09-01T00:00:00Z")
        fleet = create_fleet()
        terminal = create_terminal(fleet["id"])
        payload = create_driver_payload(
            terminal["id"], employee_ref="E-2002", name="Pat Quinn",
            inward_camera_consent=False,
        )
        payload["safety_score_final"] = 1
        payload["confirmed_events_90d"] = 99
        resp = api.create_driver(payload, platform_admin_headers)
        driver = validate_success(resp, 201)
        assert float(driver["safety_score_final"]) == 100.00
        assert float(driver["safety_score_provisional"]) == 100.00
        assert driver["confirmed_events_90d"] == 0
        assert driver["incentive_tier"] == "GOLD"
        assert driver["status"] == "ACTIVE"

    def test_driver_create_missing_required_employee_ref_returns_400(self, api, platform_admin_headers):
        """PRD §3.1: "Drivers are registered against a terminal by
        `terminal_id`, carrying an external HR reference `employee_ref`
        (unique within the fleet — a duplicate is rejected with
        `ERR_DUPLICATE_RESOURCE`), a `name`, a `hire_date`, and the driver's
        signed `inward_camera_consent` flag."
        PRD §2.10: "Next the request body is validated as JSON with all
        required fields present, enum members declared, datetimes parseable,
        integer ranges respected, and the session-window shape constraints —
        `starts_at` strictly before `ends_at`, and `due_at` no earlier than
        `ends_at` — enforced (`ERR_VALIDATION`)."

        Design: Corner/entities/driver_create_missing_required_employee_ref_returns_400
        """
        set_clock("2026-09-01T00:00:00Z")
        fleet = create_fleet()
        terminal = create_terminal(fleet["id"])
        payload = create_driver_payload(terminal["id"], name="No Ref")
        del payload["employee_ref"]
        resp = api.create_driver(payload, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        rows, meta = validate_paginated(
            api.list_terminal_drivers(terminal["id"], TEST_USERS["safety_manager_headers"])
        )
        assert len(rows) == 0


class TestEventIngestionRules:
    def test_event_create_system_fields_input_ignored(self, api, telematics_ingest_headers):
        """PRD §3.3: "The server stamps `detected_at` with the logical clock
        at ingest, initializes the event to `DETECTED` with `review_count` 0
        and `confirmed_at` unset, and computes the event's
        `upload_priority_score` exactly once; the score is stored and never
        recomputed afterward."
        PRD §3.3: "The base score is the severity weight — 1 for `LOW`, 3
        for `MEDIUM`, 6 for `HIGH`, 10 for `CRITICAL` — multiplied by the age
        step, multiplied by the vehicle's bandwidth tier multiplier (1 for
        `LOW`, 2 for `STANDARD`, 3 for `HIGH`)."

        Design: Corner/entities/event_create_system_fields_input_ignored
        """
        base = setup_base()
        payload = create_safety_event_payload(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-31T22:00:00Z",
        )
        payload["status"] = "CONFIRMED"
        payload["upload_priority_score"] = 999999
        resp = api.create_safety_event(payload, telematics_ingest_headers)
        event = validate_success(resp, 201)
        assert_safety_event(event)
        assert event["status"] == "DETECTED"
        # MEDIUM 3 x age step 4 (2 hours old) x HIGH tier 3 == 36
        assert event["upload_priority_score"] == 36
        assert event["review_count"] == 0
        assert event["version"] == 1

    def test_event_create_invalid_enum_returns_400(self, api, telematics_ingest_headers, safety_manager_headers):
        """PRD §3.3: "The `TelematicsIngest` pipeline registers a detected
        safety event with the `fleet_id`, `driver_id`, and `vehicle_id` it
        concerns, an `event_type` of `HARSH_BRAKE`, `FOLLOWING_DISTANCE`,
        `DISTRACTION`, `SEAT_BELT`, or `COLLISION`, a `severity` of `LOW`,
        `MEDIUM`, `HIGH`, or `CRITICAL`, and the `occurred_at` instant."
        PRD §2.10: "Next the request body is validated as JSON with all
        required fields present, enum members declared, datetimes parseable,
        integer ranges respected, and the session-window shape constraints —
        `starts_at` strictly before `ends_at`, and `due_at` no earlier than
        `ends_at` — enforced (`ERR_VALIDATION`)."

        Design: Corner/entities/event_create_invalid_enum_returns_400
        """
        base = setup_base()
        payload = create_safety_event_payload(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="TAILGATING", severity="LOW",
            occurred_at="2026-08-31T00:00:00Z",
        )
        resp = api.create_safety_event(payload, telematics_ingest_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        rows, meta = validate_paginated(
            api.list_fleet_safety_events(base["fleet"]["id"], safety_manager_headers)
        )
        assert len(rows) == 0


class TestSessionCreationNotFound:
    def test_session_create_event_not_found_returns_404(self, api, safety_manager_headers):
        """PRD §2.11: "List endpoints that hang beneath a parent path resolve
        their path identifiers strictly left-to-right. Each segment that does
        not resolve to an existing resource fails with the resource-specific
        not-found error."
        PRD §3.6: "They arise in two ways: automatically on confirmation of a
        `HIGH` or `CRITICAL` event (Section 3.4), or manually when a
        `SafetyManager` assigns a session against a driver by supplying the
        `event_id` of a confirmed event plus a `starts_at`, `ends_at`, and
        `due_at`."

        Design: Corner/entities/session_create_event_not_found_returns_404
        """
        base = setup_base()
        resp = api.create_coaching_session(
            base["driver"]["id"],
            {
                "event_id": NON_EXISTENT_UUID,
                "starts_at": "2026-09-02T10:00:00Z",
                "ends_at": "2026-09-02T11:00:00Z",
                "due_at": "2026-09-09T00:00:00Z",
            },
            safety_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND)
        rows, meta = validate_paginated(
            api.list_driver_coaching_sessions(base["driver"]["id"], safety_manager_headers)
        )
        assert len(rows) == 0


class TestNotFoundErrors:
    def test_driver_get_not_found_returns_404(self, api, safety_manager_headers):
        """PRD §2.11: "Each segment that does not resolve to an existing
        resource fails with the resource-specific not-found error —
        `ERR_FLEET_NOT_FOUND`, `ERR_TERMINAL_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`,
        `ERR_VEHICLE_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
        `ERR_CLIP_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`,
        or `ERR_AWARD_NOT_FOUND` as appropriate — before any later segment is
        examined."

        Design: Corner/entities/driver_get_not_found_returns_404
        """
        resp = api.get_driver(NON_EXISTENT_UUID, safety_manager_headers)
        error_data = validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_FOUND)
        assert "message" in error_data

    def test_clip_get_not_found_returns_404(self, api, safety_manager_headers):
        """PRD §2.11: "Each segment that does not resolve to an existing
        resource fails with the resource-specific not-found error —
        `ERR_FLEET_NOT_FOUND`, `ERR_TERMINAL_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`,
        `ERR_VEHICLE_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
        `ERR_CLIP_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`,
        or `ERR_AWARD_NOT_FOUND` as appropriate — before any later segment is
        examined."

        Design: Corner/errors/clip_get_not_found_returns_404
        """
        resp = api.get_footage_clip(NON_EXISTENT_UUID, safety_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CLIP_NOT_FOUND)


class TestAuthentication:
    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID`,
        identifying the acting principal, and `X-User-Role`, naming the role
        under which that principal acts. A request missing either header, or
        carrying a role name the platform does not recognize, is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/missing_role_header_unauthenticated
        """
        # Send X-User-ID only — no X-User-Role header at all.
        headers = {"X-User-ID": "test-admin-1"}
        resp = api.create_fleet(
            {"name": "No Role Freight", "incentive_budget_cents": 1000}, headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbacDenials:
    def test_driver_role_cannot_review_events(self, api):
        """PRD §2.1: "`SafetyManager` — the safety reviewer. Owns the review
        queue, coaching sessions, escalation cases, manual driver status
        changes, footage purges, and litigation holds."
        PRD §2.1: "A request whose role is not authorized for the target
        endpoint — or which violates an ownership rule — is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/driver_role_cannot_review_events
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="LOW",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        current = get_event(event["id"])
        resp = api.review_safety_event(
            event["id"],
            {
                "action": "CONFIRM",
                "rationale": "self-review attempt",
                "expected_event_version": current["version"],
            },
            make_driver_headers(base["driver"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_event(event["id"])
        assert after["status"] == "IN_REVIEW"
        assert after["review_count"] == 0

    def test_claims_adjuster_cannot_place_holds(self, api, claims_adjuster_headers, safety_manager_headers):
        """PRD §2.1: "`SafetyManager` — the safety reviewer. Owns the review
        queue, coaching sessions, escalation cases, manual driver status
        changes, footage purges, and litigation holds."
        PRD §2.1: "A request whose role is not authorized for the target
        endpoint — or which violates an ownership rule — is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/claims_adjuster_cannot_place_holds
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="LOW",
            occurred_at="2026-08-30T00:00:00Z",
        )
        resp = api.create_litigation_hold(
            create_litigation_hold_payload(
                base["fleet"]["id"], scope="EVENT", event_id=event["id"],
                reason="adjuster overreach",
            ),
            claims_adjuster_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        rows, meta = validate_paginated(
            api.list_fleet_litigation_holds(base["fleet"]["id"], safety_manager_headers)
        )
        assert len(rows) == 0

    def test_acknowledge_by_other_driver_forbidden(self, api):
        """PRD §3.6: "The driver acknowledges their own session, moving it
        `ASSIGNED` → `ACKNOWLEDGED`; the acting `X-User-ID` must equal the
        session's `driver_id`, otherwise the attempt is rejected with
        `ERR_FORBIDDEN`."
        PRD §2.1: "When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of
        the acting `Driver`; ownership checks on any resource that references
        a `Driver` compare the resource's `driver_id` field to `X-User-ID`,
        and a mismatch is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/acknowledge_by_other_driver_forbidden
        """
        base = setup_base()
        other = api.create_driver(
            create_driver_payload(
                base["terminal"]["id"], employee_ref="E-3003",
                name="Sam Okafor",
            ),
            TEST_USERS["platform_admin_headers"],
        )
        other_driver = validate_success(other, 201)
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="HIGH",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        review_event(event["id"], "CONFIRM", rationale="coach")

        session = get_event_auto_session(event["id"])
        resp = api.acknowledge_coaching_session(
            session["id"], make_driver_headers(other_driver["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        resp = api.acknowledge_coaching_session(
            session["id"], make_driver_headers(base["driver"]["id"])
        )
        acknowledged = validate_success(resp, 200)
        assert acknowledged["status"] == "ACKNOWLEDGED"
