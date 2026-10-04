"""Footage clips: parallel state dimensions, retention, purge, upload caps."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_footage_clip,
    create_litigation_hold_payload,
    get_event,
    ingest_event,
    place_hold,
    register_clip,
    setup_base,
    upload_clip,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import set_clock
from test_helpers.test_users import make_safety_manager_headers

MANAGER = TEST_USERS["safety_manager_headers"]
INGEST = TEST_USERS["telematics_ingest_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _get_clip(api, clip_id):
    return validate_success(api.get_footage_clip(clip_id, MANAGER), 200)


class TestParallelDimensions:
    def test_footage_parallel_dimensions_independent(self, api, safety_manager_headers):
        """PRD §3.5: "Every clip carries two independent state dimensions that
        evolve in parallel and never influence one another: `upload_status`
        (`QUEUED`, `UPLOADING`, `UPLOADED`, `PURGED`) and `retention_class`
        (`STANDARD`, `COLLISION`, `LITIGATION_HOLD`). At registration the clip
        starts `QUEUED`, and its retention class initializes to `COLLISION`
        when the parent event's type is `COLLISION`, otherwise `STANDARD`."
        PRD §3.5: "Placement immediately reclassifies every covered clip that
        has not been purged: its `retention_class` becomes `LITIGATION_HOLD`
        while `upload_status` is left untouched. Releasing a hold stamps
        `released_at`, moves the hold to `RELEASED`, and reverts each covered
        clip still carrying the `LITIGATION_HOLD` class — provided no other
        `ACTIVE` hold still covers it — deterministically by the parent
        event's type: clips of `COLLISION` events return to `COLLISION`, all
        others return to `STANDARD`."

        Design: Difficulty/non_linear_state_machine/footage_parallel_dimensions_independent
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="COLLISION", severity="HIGH",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        assert clip["retention_class"] == "COLLISION"
        assert clip["upload_status"] == "QUEUED"
        hold = place_hold(
            base["fleet"]["id"], scope="EVENT", event_id=event["id"],
            reason="claim CLM-881 by third party",
        )
        held = validate_success(api.get_footage_clip(clip["id"], MANAGER), 200)
        assert held["retention_class"] == "LITIGATION_HOLD"
        assert held["upload_status"] == "QUEUED"
        validate_success(api.upload_begin_clip(clip["id"], INGEST), 200)
        uploading = validate_success(api.get_footage_clip(clip["id"], MANAGER), 200)
        assert uploading["upload_status"] == "UPLOADING"
        assert uploading["retention_class"] == "LITIGATION_HOLD"
        validate_success(api.upload_complete_clip(clip["id"], INGEST), 200)
        uploaded = validate_success(api.get_footage_clip(clip["id"], MANAGER), 200)
        assert uploaded["upload_status"] == "UPLOADED"
        assert uploaded["retention_class"] == "LITIGATION_HOLD"
        validate_success(
            api.release_litigation_hold(hold["id"], make_safety_manager_headers("sm-1")), 200
        )
        released_clip = validate_success(api.get_footage_clip(clip["id"], MANAGER), 200)
        assert released_clip["retention_class"] == "COLLISION"
        assert released_clip["upload_status"] == "UPLOADED"
        assert get_event(event["id"])["status"] == "IN_REVIEW"

    def test_hold_does_not_block_upload_begin_or_complete(self, api):
        """PRD §3.5: "Placement immediately reclassifies every covered clip
        that has not been purged: its `retention_class` becomes
        `LITIGATION_HOLD` while `upload_status` is left untouched."

        Design: Difficulty/non_linear_state_machine/footage_parallel_dimensions_independent
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="COLLISION", severity="HIGH",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        place_hold(
            base["fleet"]["id"], scope="EVENT", event_id=event["id"],
            reason="claim CLM-881",
        )
        validate_success(api.upload_begin_clip(clip["id"], INGEST), 200)
        done = validate_success(api.upload_complete_clip(clip["id"], INGEST), 200)
        assert done["upload_status"] == "UPLOADED"
        assert done["retention_class"] == "LITIGATION_HOLD"


class TestHoldPurgeBlock:
    def test_hold_place_cascade_clip_retention_and_purge_block(self, api, safety_manager_headers, platform_admin_headers):
        """PRD §3.5: "Purging moves an `UPLOADED` clip to `PURGED`, stamps
        `purged_at`, and subtracts `size_mb` from the fleet's
        `retention_used_mb`. Two preconditions guard the purge. First, no
        `ACTIVE` litigation hold may cover the clip's event or its driver — a
        covered purge is rejected with `ERR_LITIGATION_HOLD_ACTIVE`, and a
        clip sitting in retention class `LITIGATION_HOLD` is never purgeable
        while it remains in that class."
        PRD §3.5: "The fleet's `retention_used_mb` is defined at all times as
        the sum of `size_mb` over the fleet's clips whose `upload_status` is
        not `PURGED`; placing or releasing a hold never changes it."

        Design: Difficulty/transitive_cascade/hold_place_cascade_clip_retention_and_purge_block
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="LOW",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        place_hold(
            base["fleet"]["id"], scope="EVENT", event_id=event["id"],
            reason="subpoena expected",
        )
        held = validate_success(api.get_footage_clip(clip["id"], MANAGER), 200)
        assert held["retention_class"] == "LITIGATION_HOLD"
        assert held["upload_status"] == "UPLOADED"
        resp = api.purge_clip(clip["id"], safety_manager_headers)
        validate_error(resp, ApiErrorId.ERR_LITIGATION_HOLD_ACTIVE)
        fleet = validate_success(api.get_fleet(base["fleet"]["id"], platform_admin_headers), 200)
        assert fleet["retention_used_mb"] == 5

    def test_driver_scope_hold_blocks_purge_of_drivers_clip(self, api, safety_manager_headers):
        """PRD §3.5: "First, no `ACTIVE` litigation hold may cover the clip's
        event or its driver — a covered purge is rejected with
        `ERR_LITIGATION_HOLD_ACTIVE`, and a clip sitting in retention class
        `LITIGATION_HOLD` is never purgeable while it remains in that class."

        Design: Difficulty/transitive_cascade/hold_place_cascade_clip_retention_and_purge_block
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="LOW",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        place_hold(
            base["fleet"]["id"], scope="DRIVER", driver_id=base["driver"]["id"],
            reason="driver matter",
        )
        resp = api.purge_clip(clip["id"], safety_manager_headers)
        validate_error(resp, ApiErrorId.ERR_LITIGATION_HOLD_ACTIVE)


class TestRetentionBytesConservation:
    def test_hold_place_release_restores_retention_bytes(self, api, platform_admin_headers):
        """PRD §3.5: "The fleet's `retention_used_mb` is defined at all times
        as the sum of `size_mb` over the fleet's clips whose `upload_status`
        is not `PURGED`; placing or releasing a hold never changes it."
        PRD §3.5: "Releasing a hold stamps `released_at`, moves the hold to
        `RELEASED`, and reverts each covered clip still carrying the
        `LITIGATION_HOLD` class — provided no other `ACTIVE` hold still covers
        it — deterministically by the parent event's type: clips of
        `COLLISION` events return to `COLLISION`, all others return to
        `STANDARD`."

        Design: Difficulty/compensating_invariant/hold_place_release_restores_retention_bytes
        """
        base = setup_base()
        clips = []
        for occurred in ("2026-08-30T00:00:00Z", "2026-08-30T01:00:00Z"):
            event = ingest_event(
                base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
                event_type="COLLISION", severity="HIGH", occurred_at=occurred,
            )
            clip = register_clip(event["id"], size_mb=50, captured_at=occurred)
            upload_clip(clip["id"])
            clips.append(clip)
        fleet = validate_success(api.get_fleet(base["fleet"]["id"], platform_admin_headers), 200)
        assert fleet["retention_used_mb"] == 100
        hold = place_hold(
            base["fleet"]["id"], scope="DRIVER", driver_id=base["driver"]["id"],
            reason="multi-claim litigation",
        )
        fleet = validate_success(api.get_fleet(base["fleet"]["id"], platform_admin_headers), 200)
        assert fleet["retention_used_mb"] == 100
        for clip in clips:
            held = validate_success(api.get_footage_clip(clip["id"], MANAGER), 200)
            assert held["retention_class"] == "LITIGATION_HOLD"
        released = validate_success(
            api.release_litigation_hold(hold["id"], make_safety_manager_headers("sm-1")), 200
        )
        assert released["status"] == "RELEASED"
        assert released["released_at"] == "2026-09-01T00:00:00.000Z"
        fleet = validate_success(api.get_fleet(base["fleet"]["id"], platform_admin_headers), 200)
        assert fleet["retention_used_mb"] == 100
        for clip in clips:
            reverted = validate_success(api.get_footage_clip(clip["id"], MANAGER), 200)
            assert reverted["retention_class"] == "COLLISION"

    def test_purge_returns_bytes_after_retention_expiry(self, api, safety_manager_headers, platform_admin_headers):
        """PRD §3.5: "Purging moves an `UPLOADED` clip to `PURGED`, stamps
        `purged_at`, and subtracts `size_mb` from the fleet's
        `retention_used_mb`."
        PRD §3.5: "The fleet's `retention_used_mb` is defined at all times as
        the sum of `size_mb` over the fleet's clips whose `upload_status` is
        not `PURGED`; placing or releasing a hold never changes it."

        Design: Difficulty/compensating_invariant/hold_place_release_restores_retention_bytes
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="LOW",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        fleet = validate_success(api.get_fleet(base["fleet"]["id"], platform_admin_headers), 200)
        assert fleet["retention_used_mb"] == 5
        # Retention deadline for STANDARD under the 30-day policy:
        # 2026-08-30 + 30 days = 2026-09-29, inclusive; 2026-09-30 is past it.
        set_clock("2026-09-30T00:00:00Z")
        purged = validate_success(api.purge_clip(clip["id"], safety_manager_headers), 200)
        assert purged["upload_status"] == "PURGED"
        fleet = validate_success(api.get_fleet(base["fleet"]["id"], platform_admin_headers), 200)
        assert fleet["retention_used_mb"] == 0


class TestPurgeRetentionBoundary:
    def test_clip_purge_before_retention_expiry_rejected(self, api, safety_manager_headers):
        """PRD §3.5: "Second, retention must have expired: a `STANDARD` clip
        is purgeable once the logical clock has reached `captured_at` plus the
        active policy's `retention_days_standard`, and a `COLLISION` clip once
        the clock has reached `captured_at` plus `retention_days_collision`;
        the boundary is inclusive, so a clip exactly at its retention deadline
        may be purged, and an earlier attempt is rejected with
        `ERR_RETENTION_NOT_EXPIRED`."

        Design: Corner/state_machines/clip_purge_before_retention_expiry_rejected
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="LOW",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        # Well short of the 30-day standard retention (deadline: 2026-09-29).
        resp = api.purge_clip(clip["id"], safety_manager_headers)
        validate_error(resp, ApiErrorId.ERR_RETENTION_NOT_EXPIRED)
        # 1 day short.
        set_clock("2026-09-28T00:00:00Z")
        resp = api.purge_clip(clip["id"], safety_manager_headers)
        validate_error(resp, ApiErrorId.ERR_RETENTION_NOT_EXPIRED)
        # Exactly at the boundary: inclusive, admitted.
        set_clock("2026-09-29T00:00:00Z")
        purged = validate_success(api.purge_clip(clip["id"], safety_manager_headers), 200)
        assert purged["upload_status"] == "PURGED"


class TestDailyUploadCap:
    def test_daily_upload_cap_exact_fit_then_one_byte_over(self, api, telematics_ingest_headers, platform_admin_headers):
        """PRD §3.5: "Completing it moves `UPLOADING` → `UPLOADED`, stamps
        `uploaded_at` with the logical clock, and enforces the fleet's daily
        upload budget: completing is rejected with `ERR_ACTIVE_POLICY_REQUIRED`
        when the fleet has no `ACTIVE` camera policy, and with
        `ERR_DAILY_UPLOAD_CAP_EXCEEDED` when the sum of `size_mb` over the
        fleet's clips already uploaded on the same UTC calendar day as the
        logical clock, plus this clip's `size_mb`, would exceed the policy's
        `daily_upload_cap_mb` — a total exactly equal to the cap is admitted."

        Design: Difficulty/boundary_precision_check/daily_upload_cap_exact_fit_then_one_byte_over
        """
        base = setup_base()
        clip_ids = []
        for size, occurred in (
            (60, "2026-08-31T22:00:00Z"),
            (40, "2026-08-31T22:05:00Z"),
            (1, "2026-08-31T22:10:00Z"),
        ):
            event = ingest_event(
                base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
                event_type="HARSH_BRAKE", severity="LOW", occurred_at=occurred,
            )
            clip = register_clip(event["id"], size_mb=size, captured_at=occurred)
            validate_success(api.upload_begin_clip(clip["id"], telematics_ingest_headers), 200)
            clip_ids.append((clip["id"], event["id"]))
        c1 = validate_success(api.upload_complete_clip(clip_ids[0][0], telematics_ingest_headers), 200)
        assert c1["upload_status"] == "UPLOADED"
        c2 = validate_success(api.upload_complete_clip(clip_ids[1][0], telematics_ingest_headers), 200)
        assert c2["upload_status"] == "UPLOADED"
        resp = api.upload_complete_clip(clip_ids[2][0], telematics_ingest_headers)
        validate_error(resp, ApiErrorId.ERR_DAILY_UPLOAD_CAP_EXCEEDED)
        stuck = validate_success(api.get_footage_clip(clip_ids[2][0], MANAGER), 200)
        assert stuck["upload_status"] == "UPLOADING"
        assert get_event(clip_ids[0][1])["status"] == "IN_REVIEW"
        assert get_event(clip_ids[1][1])["status"] == "IN_REVIEW"
        assert get_event(clip_ids[2][1])["status"] == "DETECTED"

    def test_daily_upload_cap_exact_boundary_admitted(self, api, telematics_ingest_headers):
        """PRD §3.5: "completing is rejected with `ERR_ACTIVE_POLICY_REQUIRED`
        when the fleet has no `ACTIVE` camera policy, and with
        `ERR_DAILY_UPLOAD_CAP_EXCEEDED` when the sum of `size_mb` over the
        fleet's clips already uploaded on the same UTC calendar day as the
        logical clock, plus this clip's `size_mb`, would exceed the policy's
        `daily_upload_cap_mb` — a total exactly equal to the cap is admitted."

        Design: Difficulty/boundary_precision_check/daily_upload_cap_exact_fit_then_one_byte_over
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="LOW",
            occurred_at="2026-08-31T22:00:00Z",
        )
        clip = register_clip(
            event["id"], size_mb=100, captured_at="2026-08-31T22:00:00Z"
        )
        validate_success(api.upload_begin_clip(clip["id"], telematics_ingest_headers), 200)
        done = validate_success(api.upload_complete_clip(clip["id"], telematics_ingest_headers), 200)
        assert done["upload_status"] == "UPLOADED"


class TestHoldStateMachine:
    def test_hold_release_twice_rejected(self, api, safety_manager_headers):
        """PRD §3.5: "Releasing a hold stamps `released_at`, moves the hold to
        `RELEASED`."
        PRD §3.5: "Litigation holds are placed by a `SafetyManager` with a
        `fleet_id`, a `scope` of `DRIVER` or `EVENT`, and a `reason` matter
        reference."

        Design: Corner/state_machines/hold_release_twice_rejected
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="LOW",
            occurred_at="2026-08-30T00:00:00Z",
        )
        hold = validate_success(
            api.create_litigation_hold(
                create_litigation_hold_payload(
                    base["fleet"]["id"], scope="EVENT", event_id=event["id"],
                    reason="matter M-1",
                ),
                safety_manager_headers,
            ),
            201,
        )
        released = validate_success(
            api.release_litigation_hold(hold["id"], safety_manager_headers), 200
        )
        assert released["status"] == "RELEASED"
        resp = api.release_litigation_hold(hold["id"], safety_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_litigation_hold(hold["id"], MANAGER), 200)
        assert after["status"] == "RELEASED"
        assert after["released_at"] == released["released_at"]
