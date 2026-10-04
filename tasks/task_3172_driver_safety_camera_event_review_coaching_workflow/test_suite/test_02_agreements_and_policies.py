"""Union agreements and camera policies: state machines, OCC, overlap rules."""
from test_helpers import (
    ApiErrorId,
    assert_union_agreement,
    create_terminal,
    create_union_agreement_payload,
    set_clock,
    setup_base,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_camera_policy_payload,
    create_safety_event_payload,
)
from test_helpers.fixtures import (
    create_active_policy,
    create_driver,
    create_fleet,
    create_vehicle,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]


class TestUnionAgreementWindowOverlap:
    def test_union_agreement_closed_interval_touching_overlaps(self, api):
        """PRD §3.2: "Ratification moves it to `RATIFIED` and enforces window
        exclusivity: no other `RATIFIED` agreement of the same terminal may
        have a closed window sharing any instant with the ratifying window —
        and because both windows are closed, one window ending exactly when
        another begins still counts as overlap, rejected with
        `ERR_AGREEMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/union_agreement_closed_interval_touching_overlaps
        """
        set_clock("2026-09-01T00:00:00Z")
        fleet = create_fleet()
        terminal = create_terminal(fleet["id"])
        ag_a = validate_success(
            api.create_union_agreement(
                create_union_agreement_payload(
                    terminal["id"], agreement_code="CBA-2026-H1",
                    effective_from="2026-01-01T00:00:00Z",
                    effective_until="2026-06-30T00:00:00Z",
                ),
                ADMIN,
            ),
            201,
        )
        validate_success(api.ratify_union_agreement(ag_a["id"], ADMIN), 200)
        ag_b = validate_success(
            api.create_union_agreement(
                create_union_agreement_payload(
                    terminal["id"], agreement_code="CBA-2026-H2-TOUCH",
                    effective_from="2026-06-30T00:00:00Z",
                    effective_until="2026-12-31T00:00:00Z",
                ),
                ADMIN,
            ),
            201,
        )
        resp = api.ratify_union_agreement(ag_b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)
        after = validate_success(api.get_union_agreement(ag_b["id"], ADMIN), 200)
        assert after["status"] == "DRAFT"

    def test_union_agreement_window_with_gap_ratifies(self, api):
        """PRD §3.2: "no other `RATIFIED` agreement of the same terminal may
        have a closed window sharing any instant with the ratifying window —
        and because both windows are closed, one window ending exactly when
        another begins still counts as overlap, rejected with
        `ERR_AGREEMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/union_agreement_closed_interval_touching_overlaps
        """
        set_clock("2026-09-01T00:00:00Z")
        fleet = create_fleet()
        terminal = create_terminal(fleet["id"])
        ag_a = validate_success(
            api.create_union_agreement(
                create_union_agreement_payload(
                    terminal["id"], agreement_code="CBA-2026-H1",
                    effective_from="2026-01-01T00:00:00Z",
                    effective_until="2026-06-30T00:00:00Z",
                ),
                ADMIN,
            ),
            201,
        )
        validate_success(api.ratify_union_agreement(ag_a["id"], ADMIN), 200)
        # Starts a full day after the incumbent ends: no shared instant.
        ag_c = validate_success(
            api.create_union_agreement(
                create_union_agreement_payload(
                    terminal["id"], agreement_code="CBA-2026-H2-GAP",
                    effective_from="2026-07-01T00:00:00Z",
                    effective_until="2026-12-31T00:00:00Z",
                ),
                ADMIN,
            ),
            201,
        )
        ratified = validate_success(api.ratify_union_agreement(ag_c["id"], ADMIN), 200)
        assert ratified["status"] == "RATIFIED"
        rows, meta = validate_paginated(
            api.list_terminal_union_agreements(terminal["id"], ADMIN)
        )
        assert len(rows) == 2


class TestAgreementStateMachine:
    def test_agreement_expire_from_draft_rejected(self, api):
        """PRD §3.2: "A new agreement is `DRAFT`. Ratification moves it to
        `RATIFIED` ... A `RATIFIED` agreement may later be moved to `EXPIRED`,
        which is terminal."

        Design: Corner/state_machines/agreement_expire_from_draft_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        fleet = create_fleet()
        terminal = create_terminal(fleet["id"])
        agreement = validate_success(
            api.create_union_agreement(
                create_union_agreement_payload(terminal["id"], agreement_code="CBA-DRAFT-1"),
                ADMIN,
            ),
            201,
        )
        assert_union_agreement(agreement)
        resp = api.expire_union_agreement(agreement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_union_agreement(agreement["id"], ADMIN), 200)
        assert after["status"] == "DRAFT"


class TestCameraPolicyPatch:
    def test_policy_patch_partial_update(self, api):
        """PRD §3.2: "While `DRAFT`, its fields may be patched under
        optimistic concurrency (Section 2.6)."
        PRD §2.4: "an integer `version` that starts at its initial value on
        creation and increments by exactly one on every mutation of that
        resource, including system-driven mutations such as automatic status
        transitions."

        Design: Corner/endpoints/policy_patch_partial_update
        """
        set_clock("2026-09-01T00:00:00Z")
        fleet = create_fleet()
        policy = validate_success(
            api.create_camera_policy(
                create_camera_policy_payload(fleet["id"], name="Draft Policy"),
                ADMIN,
            ),
            201,
        )
        resp = api.patch_camera_policy(
            policy["id"],
            {
                "expected_policy_version": policy["version"],
                "name": "Draft Policy v2",
                "daily_upload_cap_mb": 200,
            },
            ADMIN,
        )
        updated = validate_success(resp, 200)
        assert updated["name"] == "Draft Policy v2"
        assert updated["daily_upload_cap_mb"] == 200
        assert updated["retention_days_standard"] == 30
        assert updated["retention_days_collision"] == 180
        assert updated["inward_capture_enabled"] is True
        assert updated["version"] == policy["version"] + 1
        assert updated["status"] == "DRAFT"

    def test_policy_patch_stale_version_returns_412(self, api):
        """PRD §2.6: "A camera policy patch must carry
        `expected_policy_version` equal to the policy's current `version`. If a
        prior patch or a status transition has advanced the policy since the
        client last observed it, the patch is rejected with
        `ERR_STALE_POLICY_VERSION` (HTTP 412)."

        Design: Corner/cross-cutting complexity layers/policy_patch_stale_version_returns_412
        """
        set_clock("2026-09-01T00:00:00Z")
        fleet = create_fleet()
        policy = validate_success(
            api.create_camera_policy(
                create_camera_policy_payload(fleet["id"], name="Draft Policy"),
                ADMIN,
            ),
            201,
        )
        first = validate_success(
            api.patch_camera_policy(
                policy["id"],
                {"expected_policy_version": policy["version"], "daily_upload_cap_mb": 150},
                ADMIN,
            ),
            200,
        )
        assert first["version"] == policy["version"] + 1
        resp = api.patch_camera_policy(
            policy["id"],
            {"expected_policy_version": policy["version"], "daily_upload_cap_mb": 999},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_POLICY_VERSION)
        current = validate_success(api.get_camera_policy(policy["id"], ADMIN), 200)
        assert current["daily_upload_cap_mb"] == 150


class TestEventTypeGating:
    def test_event_type_disabled_by_active_policy(self, api, telematics_ingest_headers):
        """PRD §3.2: "When the active policy disables a detection switch,
        ingesting an event of the disabled type is rejected with
        `ERR_EVENT_TYPE_DISABLED` — this applies to `DISTRACTION` and
        `SEAT_BELT` events."

        Design: Corner/validations/event_type_disabled_by_active_policy
        """
        set_clock("2026-09-01T00:00:00Z")
        fleet = create_fleet()
        terminal = create_terminal(fleet["id"])
        driver = create_driver(terminal["id"])
        vehicle = create_vehicle(terminal["id"])
        create_active_policy(fleet["id"], name="No-Distraction Policy",
                             distraction_detection_enabled=False)
        resp = api.create_safety_event(
            create_safety_event_payload(
                fleet["id"], driver["id"], vehicle["id"],
                event_type="DISTRACTION", severity="LOW",
                occurred_at="2026-08-31T00:00:00Z",
            ),
            telematics_ingest_headers,
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_TYPE_DISABLED)
        ok = validate_success(
            api.create_safety_event(
                create_safety_event_payload(
                    fleet["id"], driver["id"], vehicle["id"],
                    event_type="HARSH_BRAKE", severity="LOW",
                    occurred_at="2026-08-31T00:00:00Z",
                ),
                telematics_ingest_headers,
            ),
            201,
        )
        assert ok["status"] == "DETECTED"
        rows, meta = validate_paginated(
            api.list_fleet_safety_events(fleet["id"], TEST_USERS["safety_manager_headers"])
        )
        assert len(rows) == 1
