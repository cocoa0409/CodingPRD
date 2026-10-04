"""Location fix ingestion, adaptive sample interval, retention, and geofence."""
from test_helpers import (
    TEST_USERS,
    create_circle,
    create_fix_payload,
    create_place_payload,
    get_member_state,
    invite_member,
    make_member_headers,
    make_owner_headers,
    post_fix,
    reset_clock,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client


class TestFixValidation:
    def test_fix_clock_skew_beyond_300s_rejected(self, api, system_headers):
        """PRD §3.4: "The server validates that the `recorded_at` is within 300
        seconds, in either direction, of its own logical clock; a skew beyond
        that, a non-positive `accuracy_m`, a negative `speed_mps`, a
        `battery_pct` outside the 0-to-100 range, or an unrecognized
        `motion_context` is rejected with `ERR_FIX_CLOCK_SKEW` (HTTP 422)."

        Design: Corner/validations/fix_clock_skew_beyond_300s_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="SkewFam")
        owner_id = circle["owner_member_id"]
        resp = api.post_fix(
            circle["id"], owner_id,
            create_fix_payload(recorded_at="2026-09-01T00:10:01Z"),
            owner_headers,
        )
        validate_error(resp, "ERR_FIX_CLOCK_SKEW")

    def test_fix_accuracy_zero_rejected(self, api, system_headers):
        """PRD §3.4: "a skew beyond that, a non-positive `accuracy_m`, a negative
        `speed_mps`, a `battery_pct` outside the 0-to-100 range, or an
        unrecognized `motion_context` is rejected with `ERR_FIX_CLOCK_SKEW`
        (HTTP 422)."

        Design: Corner/validations/fix_accuracy_zero_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="AccFam")
        owner_id = circle["owner_member_id"]
        resp = api.post_fix(
            circle["id"], owner_id,
            create_fix_payload(recorded_at="2026-09-01T00:00:30Z", accuracy_m=0),
            owner_headers,
        )
        validate_error(resp, "ERR_FIX_CLOCK_SKEW")

    def test_err_consent_not_granted_on_fix_post(self, api, system_headers):
        """PRD §3.4: "Ingestion requires the member's `consent_state` to be
        `GRANTED`; a fix submitted while consent is `REVOKED` or `EXPIRED` is
        recorded but with `fix_status` set to `REJECTED_CONSENT` rather than
        accepted."

        Design: Corner/errors/err_consent_not_granted_on_fix_post
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="ConsentFam")
        pending = invite_member(circle, owner_headers, display_name="P", email="p@example.com")
        resp = api.post_fix(
            circle["id"], pending["id"],
            create_fix_payload(recorded_at="2026-09-01T00:00:30Z"),
            make_member_headers(pending["id"]),
        )
        if resp.status_code in (400, 401, 403, 404, 409, 422):
            validate_error(resp, "ERR_CONSENT_NOT_GRANTED")
            return
        fix = validate_success(resp, 201)
        assert fix["fix_status"] == "REJECTED_CONSENT"

    def test_fix_post_after_revoke_recorded_as_rejected_consent(self, api, system_headers):
        """PRD §3.2: "every location fix the member's device subsequently submits
        is recorded as `REJECTED_CONSENT` rather than accepted"

        Design: Corner/errors/err_consent_not_granted_on_fix_post
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="RevokeFixFam")
        owner_id = circle["owner_member_id"]
        validate_success(api.revoke_consent(circle["id"], owner_id, owner_headers))
        resp = api.post_fix(
            circle["id"], owner_id,
            create_fix_payload(recorded_at="2026-09-01T00:00:30Z"),
            owner_headers,
        )
        if resp.status_code in (400, 401, 403, 404, 409, 422):
            validate_error(resp, "ERR_CONSENT_NOT_GRANTED")
            return
        fix = validate_success(resp, 201)
        assert fix["fix_status"] == "REJECTED_CONSENT"


class TestAdaptiveSampleInterval:
    def test_effective_sample_interval_mode_a_tier_floor_interaction(self, api, system_headers):
        """PRD §3.4: "First, the base seconds are chosen from the profile: 15
        seconds for `HIGH`, 60 for `BALANCED`, 300 for `SAVER`. Second, the base
        is multiplied by a motion modifier: a quarter when the fix reports
        `DRIVING`, half when `WALKING`, doubled when `STILL`, and unchanged when
        `UNKNOWN`. Third, that intermediate product is multiplied by a battery
        modifier: doubled when the battery is at or below 15 percent, multiplied
        by 1.5 when the battery is between 16 and 30 percent inclusive, and
        unchanged above 30 percent. Fourth, the result is floored at a per-tier
        minimum: 60 seconds on `FREE`, 30 seconds on `PLUS`, 15 seconds on
        `PROTECT` — meaning the interval is the larger of the raw product and
        the tier floor. Fifth and finally, the value is rounded half-up to an
        integer number of seconds and clamped to the inclusive range from 15 to
        900."

        Design: Difficulty/combinatorial_formula/effective_sample_interval_mode_a_tier_floor_interaction
        """
        reset_clock()
        free_circle, free_headers = create_circle(tier="FREE", name="FreeFam")
        plus_circle, plus_headers = create_circle(tier="PLUS", name="PlusFam")
        post_fix(free_circle, {"id": free_circle["owner_member_id"]}, free_headers,
                 recorded_at="2026-09-01T00:00:00Z", motion_context="DRIVING",
                 speed_mps=25.0, battery_pct=80)
        post_fix(plus_circle, {"id": plus_circle["owner_member_id"]}, plus_headers,
                 recorded_at="2026-09-01T00:00:00Z", motion_context="DRIVING",
                 speed_mps=25.0, battery_pct=80)
        free_member = get_member_state(free_circle["id"], free_circle["owner_member_id"], free_headers)
        plus_member = get_member_state(plus_circle["id"], plus_circle["owner_member_id"], plus_headers)
        # raw = 60 * 0.25 * 1.0 = 15; FREE floor 60 -> 60; PLUS floor 30 -> 30.
        assert free_member["effective_sample_interval_seconds"] == 60
        assert plus_member["effective_sample_interval_seconds"] == 30

    def test_effective_sample_interval_protect_tier_no_floor_binding(self, api, system_headers):
        """PRD §3.4: "Fourth, the result is floored at a per-tier minimum: 60
        seconds on `FREE`, 30 seconds on `PLUS`, 15 seconds on `PROTECT` —
        meaning the interval is the larger of the raw product and the tier
        floor."

        Design: Difficulty/combinatorial_formula/effective_sample_interval_mode_a_tier_floor_interaction
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="ProtectFam")
        post_fix(circle, {"id": circle["owner_member_id"]}, owner_headers,
                 recorded_at="2026-09-01T00:00:00Z", motion_context="DRIVING",
                 speed_mps=25.0, battery_pct=80)
        member = get_member_state(circle["id"], circle["owner_member_id"], owner_headers)
        # raw = 60 * 0.25 * 1.0 = 15; PROTECT floor 15 -> 15.
        assert member["effective_sample_interval_seconds"] == 15

    def test_cascading_fix_post_updates_member_battery_and_interval(self, api, system_headers):
        """PRD §3.4: "Each accepted fix updates three things on the member row:
        the `last_known_fix_id` points at the new fix, the `current_battery_pct`
        is overwritten with the fix's `battery_pct`, and the member's
        `effective_sample_interval_seconds` is recomputed."

        Design: Corner/cross_cutting_complexity_layers/cascading_fix_post_updates_member_battery_and_interval
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="CascadeFixFam")
        owner_id = circle["owner_member_id"]
        fix = post_fix(circle, {"id": owner_id}, owner_headers,
                       recorded_at="2026-09-01T00:00:30Z", battery_pct=12,
                       motion_context="STILL", speed_mps=0.0)
        member = get_member_state(circle["id"], owner_id, owner_headers)
        assert member["current_battery_pct"] == 12
        # raw = 60 (BALANCED) * 2.0 (STILL) * 2.0 (battery <= 15) = 240;
        # FREE floor 60 -> 240; clamp [15,900] -> 240.
        assert member["effective_sample_interval_seconds"] == 240
        assert member["last_known_fix_id"] == fix["id"]

    def test_cascading_fix_post_battery_mid_band_multiplier(self, api, system_headers):
        """PRD §3.4: "Third, that intermediate product is multiplied by a
        battery modifier: doubled when the battery is at or below 15 percent,
        multiplied by 1.5 when the battery is between 16 and 30 percent
        inclusive, and unchanged above 30 percent."
        PRD §3.4: "Each accepted fix updates three things on the member row:
        the `last_known_fix_id` points at the new fix, the `current_battery_pct`
        is overwritten with the fix's `battery_pct`, and the member's
        `effective_sample_interval_seconds` is recomputed."

        Design: Corner/cross_cutting_complexity_layers/cascading_fix_post_updates_member_battery_and_interval
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="MidBandFam")
        owner_id = circle["owner_member_id"]
        post_fix(circle, {"id": owner_id}, owner_headers,
                 recorded_at="2026-09-01T00:00:30Z", battery_pct=20,
                 motion_context="STILL", speed_mps=0.0)
        member = get_member_state(circle["id"], owner_id, owner_headers)
        assert member["current_battery_pct"] == 20
        # raw = 60 * 2.0 * 1.5 = 180; FREE floor 60 -> 180.
        assert member["effective_sample_interval_seconds"] == 180


class TestGeofenceMembership:
    def test_geofence_membership_accuracy_cap_outside_without_cap(self, api, system_headers):
        """PRD §3.5: "For a given place, the effective radius is the place's
        `radius_m` plus the smaller of the fix's `accuracy_m` and the place's
        `accuracy_floor_m` — the accuracy contribution is capped at the floor."

        Design: Corner/calculations/geofence_membership_accuracy_cap_applies
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="CapFam2")
        owner_id = circle["owner_member_id"]
        place = validate_success(api.create_place(
            circle["id"],
            create_place_payload(
                label="Cap2", center_lat=37.7000, center_lng=-122.4000,
                radius_m=200, accuracy_floor_m=50, dwell_bucket_seconds=60,
            ),
            owner_headers,
        ), 201)
        # ~260 m from centre with accuracy 40 (below the floor): 260 > 240.
        f = post_fix(circle, {"id": owner_id}, owner_headers,
                     recorded_at="2026-09-01T00:00:00Z", lat=37.70234,
                     lng=-122.4000, accuracy_m=40, motion_context="STILL")
        assert place["id"] not in f["place_ids_inside"]

    def test_geofence_boundary_inclusive_equality(self, api, system_headers):
        """PRD §3.5: "the fix is inside the place exactly when that distance is
        less than or equal to the effective radius (the comparison is inclusive
        — a fix exactly at the effective radius is inside)."

        Design: Corner/calculations/geofence_boundary_inclusive_equality
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="EqFam")
        owner_id = circle["owner_member_id"]
        place = validate_success(api.create_place(
            circle["id"],
            create_place_payload(
                label="Eq", center_lat=37.7000, center_lng=-122.4000,
                radius_m=500, accuracy_floor_m=100, dwell_bucket_seconds=60,
            ),
            owner_headers,
        ), 201)
        # Exactly 600 m north of the centre; effective radius = 500 + min(100,100) = 600.
        # (37.705395929635515 is the latitude whose haversine distance from the
        # centre is 600.0 m at 0.1 m precision with earth radius 6,371,000 m.)
        f = post_fix(circle, {"id": owner_id}, owner_headers,
                     recorded_at="2026-09-01T00:00:00Z", lat=37.705395929635515,
                     lng=-122.4000, accuracy_m=100, motion_context="STILL")
        assert place["id"] in f["place_ids_inside"]

    def test_geofence_fix_just_outside_effective_radius_is_excluded(self, api, system_headers):
        """PRD §3.5: "the fix is inside the place exactly when that distance is
        less than or equal to the effective radius (the comparison is inclusive
        — a fix exactly at the effective radius is inside)."

        Design: Corner/calculations/geofence_boundary_inclusive_equality
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="OutFam")
        owner_id = circle["owner_member_id"]
        place = validate_success(api.create_place(
            circle["id"],
            create_place_payload(
                label="Out", center_lat=37.7000, center_lng=-122.4000,
                radius_m=500, accuracy_floor_m=100, dwell_bucket_seconds=60,
            ),
            owner_headers,
        ), 201)
        # ~650 m north; 650 > 500 + min(100, 100) = 600 -> outside.
        f = post_fix(circle, {"id": owner_id}, owner_headers,
                     recorded_at="2026-09-01T00:00:00Z", lat=37.70585,
                     lng=-122.4000, accuracy_m=100, motion_context="STILL")
        assert place["id"] not in f["place_ids_inside"]


class TestRetentionWindow:
    def test_retention_cutoff_inclusive_boundary(self, api, system_headers):
        """PRD §3.9: "On every list of location fixes or trip reports, the
        server applies a projection: a row is visible exactly when its
        `recorded_at` is on or after the cutoff computed as the current logical
        time minus the circle's `history_retention_days` expressed in days
        (86,400 seconds each). The comparison is inclusive — a row exactly at
        the cutoff is included."

        Design: Difficulty/boundary_precision_check/retention_cutoff_inclusive_boundary
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="RetFam")
        owner_id = circle["owner_member_id"]
        set_clock("2026-09-01T11:59:59Z")
        fix_out = post_fix(circle, {"id": owner_id}, owner_headers,
                           recorded_at="2026-09-01T11:59:59Z")
        set_clock("2026-09-01T12:00:00Z")
        fix_in = post_fix(circle, {"id": owner_id}, owner_headers,
                          recorded_at="2026-09-01T12:00:00Z")
        set_clock("2026-09-08T12:00:00Z")
        data, meta = validate_paginated(api.list_fixes(circle["id"], owner_id, owner_headers))
        returned_ids = {f["id"] for f in data}
        assert fix_in["id"] in returned_ids, "fix exactly at the cutoff must be included"
        assert fix_out["id"] not in returned_ids, "fix one second before the cutoff must be excluded"
        assert meta["total_count"] == 1

    def test_retention_cutoff_protect_tier_sixty_day_window(self, api, system_headers):
        """PRD §3.9: "The window's depth is the circle's
        `history_retention_days` — 7 days on `FREE`, 30 on `PLUS`, 60 on
        `PROTECT`."
        PRD §3.9: "On every list of location fixes or trip reports, the server
        applies a projection: a row is visible exactly when its `recorded_at` is
        on or after the cutoff computed as the current logical time minus the
        circle's `history_retention_days` expressed in days (86,400 seconds
        each)."

        Design: Difficulty/boundary_precision_check/retention_cutoff_inclusive_boundary
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="RetProtFam")
        owner_id = circle["owner_member_id"]
        fix = post_fix(circle, {"id": owner_id}, owner_headers,
                       recorded_at="2026-09-01T00:00:00Z")
        # 30 days later the fix would be gone on FREE/PLUS but kept on PROTECT.
        set_clock("2026-10-01T00:00:00Z")
        data, meta = validate_paginated(api.list_fixes(circle["id"], owner_id, owner_headers))
        returned_ids = {f["id"] for f in data}
        assert fix["id"] in returned_ids
