"""Places: config validation, defaults, overlap rule, dwell bucket, alerts."""
from test_helpers import (
    TEST_USERS,
    create_circle,
    create_place_payload,
    make_owner_headers,
    post_fix,
    reset_clock,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client


class TestPlaceConfig:
    def test_place_dwell_bucket_default_180_when_omitted(self, api, system_headers):
        """PRD §3.5: "The `dwell_bucket_seconds` — one of 60, 180, or 300,
        defaulting to 180 — is the minimum dwell a member must accumulate
        inside the geofence before an arrival is confirmed."

        Design: Corner/entities/place_dwell_bucket_default_180_when_omitted
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="DwellFam")
        payload = create_place_payload(
            label="Work", center_lat=37.8, center_lng=-122.5,
            radius_m=200, accuracy_floor_m=50, notify_on_arrive=True,
            notify_on_depart=False,
        )
        del payload["dwell_bucket_seconds"]
        place = validate_success(api.create_place(circle["id"], payload, owner_headers), 201)
        assert place["dwell_bucket_seconds"] == 180
        assert place["place_status"] == "ACTIVE"

    def test_place_config_radius_out_of_range(self, api, system_headers):
        """PRD §3.5: "The geofence is a `center_lat` between -90 and 90, a
        `center_lng` between -180 and 180, and a `radius_m` between 50 and
        5,000 metres inclusive. ... Any violation of these ranges on create or
        update is rejected with `ERR_PLACE_CONFIG_INVALID` (HTTP 422)."

        Design: Corner/validations/place_config_radius_out_of_range
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="RangeFam")
        resp_low = api.create_place(
            circle["id"],
            create_place_payload(label="Tiny", radius_m=10),
            owner_headers,
        )
        validate_error(resp_low, "ERR_PLACE_CONFIG_INVALID")
        resp_high = api.create_place(
            circle["id"],
            create_place_payload(label="Huge", radius_m=9999),
            owner_headers,
        )
        validate_error(resp_high, "ERR_PLACE_CONFIG_INVALID")

    def test_place_config_radius_boundaries_accepted(self, api, system_headers):
        """PRD §3.5: "The geofence is a `center_lat` between -90 and 90, a
        `center_lng` between -180 and 180, and a `radius_m` between 50 and
        5,000 metres inclusive."

        Design: Corner/validations/place_config_radius_out_of_range
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="RangeOkFam")
        small = validate_success(api.create_place(
            circle["id"],
            create_place_payload(label="MinR", center_lat=37.0, center_lng=-122.0, radius_m=50),
            owner_headers,
        ), 201)
        assert small["radius_m"] == 50
        big = validate_success(api.create_place(
            circle["id"],
            create_place_payload(label="MaxR", center_lat=38.5, center_lng=-122.0, radius_m=5000),
            owner_headers,
        ), 201)
        assert big["radius_m"] == 5000


class TestPlaceOverlap:
    def test_place_geofence_overlap_area_threshold(self, api, system_headers):
        """PRD §3.5: "When a new place is created or an existing place's
        `radius_m` or centre is updated, the server compares the candidate
        against every other `ACTIVE` place in the circle; if the candidate's
        geofence intersects an existing place's geofence by more than 50
        percent of the smaller of the two radii areas, the operation is
        rejected with `ERR_PLACE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/place_geofence_overlap_area_threshold
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="OvFam")
        validate_success(api.create_place(
            circle["id"],
            create_place_payload(label="Home", center_lat=37.7000, center_lng=-122.4000,
                                 radius_m=500, dwell_bucket_seconds=60),
            owner_headers,
        ), 201)
        # 250 m north (intersection ratio ~0.685 of the smaller circle) -> rejected.
        resp_close = api.create_place(
            circle["id"],
            create_place_payload(label="TooClose", center_lat=37.70225, center_lng=-122.4000,
                                 radius_m=500, dwell_bucket_seconds=60),
            owner_headers,
        )
        validate_error(resp_close, "ERR_PLACE_OVERLAP")
        # 500 m north (ratio ~0.391) -> accepted.
        far = validate_success(api.create_place(
            circle["id"],
            create_place_payload(label="FarEnough", center_lat=37.70450, center_lng=-122.4000,
                                 radius_m=500, dwell_bucket_seconds=60),
            owner_headers,
        ), 201)
        assert far["place_status"] == "ACTIVE"

    def test_place_geofence_tangent_places_accepted(self, api, system_headers):
        """PRD §3.5: "if the candidate's geofence intersects an existing place's
        geofence by more than 50 percent of the smaller of the two radii areas,
        the operation is rejected with `ERR_PLACE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/place_geofence_overlap_area_threshold
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="TangentFam")
        validate_success(api.create_place(
            circle["id"],
            create_place_payload(label="A", center_lat=37.7000, center_lng=-122.4000,
                                 radius_m=500, dwell_bucket_seconds=60),
            owner_headers,
        ), 201)
        # ~1110 m north: sum of radii (1000 m) exceeded — disjoint, accepted.
        ok = validate_success(api.create_place(
            circle["id"],
            create_place_payload(label="B", center_lat=37.70998, center_lng=-122.4000,
                                 radius_m=500, dwell_bucket_seconds=60),
            owner_headers,
        ), 201)
        assert ok["place_status"] == "ACTIVE"


class TestPlaceAlerts:
    def test_place_alert_terminal_states_lockdown(self, api, system_headers):
        """PRD §3.5: "Candidates that do not confirm resolve to `SUPPRESSED` or
        `CANCELLED`; those that do confirm land in `CONFIRMED`."
        PRD §3.5: "Confirmation stamps the `window_close_fix_id`, computes
        `visible_to_owner` from the member's `privacy_mode` at that moment
        (`true` under `PRECISE` or `BLURRED`, `false` under `HIDDEN`), and
        freezes both."

        Design: Corner/state_machines/place_alert_terminal_states_lockdown
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="AlertLockFam")
        owner_id = circle["owner_member_id"]
        place = validate_success(api.create_place(
            circle["id"],
            create_place_payload(label="Home", center_lat=37.7000, center_lng=-122.4000,
                                 radius_m=200, accuracy_floor_m=100, dwell_bucket_seconds=60),
            owner_headers,
        ), 201)
        post_fix(circle, {"id": owner_id}, owner_headers, recorded_at="2026-09-01T00:00:00Z")
        post_fix(circle, {"id": owner_id}, owner_headers, recorded_at="2026-09-01T00:02:00Z", battery_pct=89)
        post_fix(circle, {"id": owner_id}, owner_headers, recorded_at="2026-09-01T00:04:00Z", battery_pct=88)
        data, _meta = validate_paginated(
            api.list_place_alerts(circle["id"], place["id"], owner_headers)
        )
        confirmed = [a for a in data if a["alert_status"] == "CONFIRMED"]
        assert len(confirmed) >= 1, "expected at least one CONFIRMED arrival alert"
        snapshot = {
            a["id"]: (a["alert_status"], a.get("window_close_fix_id")) for a in confirmed
        }
        # A later inside fix must not mutate the already-CONFIRMED rows.
        post_fix(circle, {"id": owner_id}, owner_headers, recorded_at="2026-09-01T00:05:00Z", battery_pct=87)
        data2, _meta2 = validate_paginated(
            api.list_place_alerts(circle["id"], place["id"], owner_headers)
        )
        for a in data2:
            if a["id"] in snapshot:
                assert a["alert_status"] == "CONFIRMED"
                assert a.get("window_close_fix_id") == snapshot[a["id"]][1]

    def test_place_alert_confirmed_alert_is_immutable_after_departure_and_reentry(self, api, system_headers):
        """PRD §3.5: "Candidates that do not confirm resolve to `SUPPRESSED` or
        `CANCELLED`; those that do confirm land in `CONFIRMED`."
        PRD §3.5: "A candidate alert opens in `PENDING_DWELL` when a fix places
        a member inside a place they were not previously inside (an `ARRIVAL`
        candidate) or outside a place they were previously inside (a
        `DEPARTURE` candidate)."

        Design: Corner/state_machines/place_alert_terminal_states_lockdown
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="AlertLockFam2")
        owner_id = circle["owner_member_id"]
        place = validate_success(api.create_place(
            circle["id"],
            create_place_payload(label="Home2", center_lat=37.7000, center_lng=-122.4000,
                                 radius_m=200, accuracy_floor_m=100, dwell_bucket_seconds=60),
            owner_headers,
        ), 201)
        post_fix(circle, {"id": owner_id}, owner_headers, recorded_at="2026-09-01T00:00:00Z")
        post_fix(circle, {"id": owner_id}, owner_headers, recorded_at="2026-09-01T00:02:00Z", battery_pct=89)
        data, _m = validate_paginated(api.list_place_alerts(circle["id"], place["id"], owner_headers))
        confirmed_ids = {a["id"] for a in data if a["alert_status"] == "CONFIRMED"}
        assert confirmed_ids
        # Depart (far outside) then re-enter; the confirmed row must persist.
        # Advance the logical clock so each recorded_at stays within the 300 s
        # fix-ingestion skew window (PRD §3.4).
        set_clock("2026-09-01T00:04:00Z")
        post_fix(circle, {"id": owner_id}, owner_headers,
                 recorded_at="2026-09-01T00:04:00Z", lat=37.7500, battery_pct=88)
        set_clock("2026-09-01T00:06:00Z")
        post_fix(circle, {"id": owner_id}, owner_headers,
                 recorded_at="2026-09-01T00:06:00Z", lat=37.7000, battery_pct=87)
        set_clock("2026-09-01T00:08:00Z")
        post_fix(circle, {"id": owner_id}, owner_headers,
                 recorded_at="2026-09-01T00:08:00Z", lat=37.7000, battery_pct=86)
        data2, _m2 = validate_paginated(api.list_place_alerts(circle["id"], place["id"], owner_headers))
        for a in data2:
            if a["id"] in confirmed_ids:
                assert a["alert_status"] == "CONFIRMED"

    def test_dwell_bucket_enforces_min_interval_factor(self, api, system_headers):
        """PRD §3.5: "The dwell window's two fixes must be separated by at least
        half of the member's `effective_sample_interval_seconds` as computed at
        the window-open fix — a window whose two fixes are closer together than
        that could not have been produced by the device's actual sampling
        cadence. The evaluation order is pinned: first compute the effective
        interval at the window-open fix; then, if the inter-fix gap is less
        than half that interval, suppress the alert with `suppressed_reason`
        `DUPLICATE_EVENT`; otherwise, if the dwell is at least the bucket,
        confirm; otherwise suppress with `suppressed_reason` left null."

        Design: Corner/calculations/dwell_bucket_enforces_min_interval_factor
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="SaverFam")
        owner_id = circle["owner_member_id"]
        place = validate_success(api.create_place(
            circle["id"],
            create_place_payload(label="Saver", center_lat=37.7000, center_lng=-122.4000,
                                 radius_m=200, accuracy_floor_m=100, dwell_bucket_seconds=60),
            owner_headers,
        ), 201)
        # First fix: STILL with battery 12 -> effective interval 240 s (raw
        # 60 * 2.0 * 2.0), so a 30-second window cannot confirm (30 < 120).
        post_fix(circle, {"id": owner_id}, owner_headers,
                 recorded_at="2026-09-01T00:00:00Z", battery_pct=12)
        post_fix(circle, {"id": owner_id}, owner_headers,
                 recorded_at="2026-09-01T00:00:30Z", battery_pct=11)
        data, _meta = validate_paginated(
            api.list_place_alerts(circle["id"], place["id"], owner_headers)
        )
        for alert in data:
            assert alert["alert_status"] != "CONFIRMED", (
                "a 30 s window cannot confirm against a 240 s effective interval"
            )
            if alert["alert_status"] == "SUPPRESSED":
                assert alert["suppressed_reason"] == "DUPLICATE_EVENT"

    def test_dwell_bucket_confirms_when_dwell_and_interval_both_satisfied(self, api, system_headers):
        """PRD §3.5: "The candidate is confirmed when a subsequent fix from the
        same member lands inside the same geofence (under the membership rule
        above) and the elapsed dwell — the difference between the candidate's
        `window_close_fix_id` recorded time and the `window_open_fix_id`
        recorded time — is at least the place's `dwell_bucket_seconds`,
        provided the circle's posture is `OPEN` at confirmation time."

        Design: Corner/calculations/dwell_bucket_enforces_min_interval_factor
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="ConfirmFam")
        owner_id = circle["owner_member_id"]
        place = validate_success(api.create_place(
            circle["id"],
            create_place_payload(label="Ok", center_lat=37.7000, center_lng=-122.4000,
                                 radius_m=200, accuracy_floor_m=100, dwell_bucket_seconds=60),
            owner_headers,
        ), 201)
        # BALANCED/STILL/battery 90 -> interval 120; half = 60; dwell 120 >= 60.
        post_fix(circle, {"id": owner_id}, owner_headers, recorded_at="2026-09-01T00:00:00Z")
        post_fix(circle, {"id": owner_id}, owner_headers,
                 recorded_at="2026-09-01T00:02:00Z", battery_pct=89)
        data, _meta = validate_paginated(
            api.list_place_alerts(circle["id"], place["id"], owner_headers)
        )
        confirmed = [a for a in data if a["alert_status"] == "CONFIRMED"]
        assert confirmed, "expected the arrival alert to confirm at 120 s dwell"
        assert all(a["visible_to_owner"] is True for a in confirmed)
