"""Endpoint corner claims: athlete export, listing pagination, and the
non-owner obfuscated-route read."""

from test_helpers import (
    create_athlete,
    create_privacy_zone,
    create_safety_contact,
    create_segment,
    make_athlete_headers,
    upload_activity,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_activity_payload


class TestAthleteExport:
    def test_export_returns_all_ten_sections(self, api):
        """PRD 3.1: "The export bundles the profile, all activities with their raw track data, all efforts, all segments the athlete created, memberships, challenge participations, event RSVPs, privacy zones, safety contacts, and subscriptions — returned as an object with keys `profile`, `activities`, `efforts`, `segments`, `memberships`, `participations`, `rsvps`, `privacy_zones`, `safety_contacts`, and `subscriptions`."

        Design: Corner/endpoints/athlete_export_returns_full_payload
        """
        athlete = create_athlete(api, email="ex_e@x.com", display_name="EX E")
        create_safety_contact(api, athlete["id"], contact_email="sos_ex@x.com", label="SOS")
        activity = upload_activity(
            api, athlete["id"],
            device_source="mobile-app", sport_type="RUN", started_at="2026-09-01T06:00:00Z",
            duration_s=600, distance_m=2000,
            track_points=[{"lat": 58.00, "lng": -143.00, "t_offset_s": 0}, {"lat": 58.01, "lng": -143.00, "t_offset_s": 600}],
            start_lat=58.00, start_lng=-143.00, end_lat=58.01, end_lng=-143.00,
            idempotency_key="ex-1",
        )
        export = validate_success(api.export_athlete(athlete["id"], make_athlete_headers(athlete["id"])), 200)
        for key in (
            "profile", "activities", "efforts", "segments", "memberships",
            "participations", "rsvps", "privacy_zones", "safety_contacts", "subscriptions",
        ):
            assert key in export, f"export must include key {key!r}"
        assert export["profile"]["email"] == "ex_e@x.com"
        assert any(a["id"] == activity["id"] for a in export["activities"])
        assert len(export["safety_contacts"]) == 1

    def test_export_profile_carries_raw_track_data(self, api):
        """PRD 3.1: "The export bundles the profile, all activities with their raw track data".

        Design: Corner/endpoints/athlete_export_returns_full_payload
        """
        athlete = create_athlete(api, email="ex_raw@x.com", display_name="EX Raw")
        track = [{"lat": 58.10, "lng": -143.10, "t_offset_s": 0}, {"lat": 58.11, "lng": -143.10, "t_offset_s": 600}]
        upload_activity(
            api, athlete["id"],
            sport_type="RUN", started_at="2026-09-01T06:00:00Z", duration_s=600, distance_m=2000,
            track_points=track, start_lat=58.10, start_lng=-143.10, end_lat=58.11, end_lng=-143.10,
            idempotency_key="ex-raw-1",
        )
        export = validate_success(api.export_athlete(athlete["id"], make_athlete_headers(athlete["id"])), 200)
        assert export["activities"][0]["track_points"] == track


class TestSegmentsListFilterAndPagination:
    def test_sport_type_filter_and_limit(self, api):
        """PRD 2.3: "List responses carry pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
        PRD 2.3: "The `limit` parameter specifies the maximum number of items to return".

        Design: Corner/endpoints/segments_list_filter_and_pagination
        """
        owner = create_athlete(api, email="pg_p@x.com", display_name="PG P")
        create_segment(api, owner["id"], name="Page Ride A", sport_type="RIDE", start_lat=59.00, start_lng=-144.00, end_lat=59.01, end_lng=-144.00, distance_m=1000, city="Pageville")
        create_segment(api, owner["id"], name="Page Ride B", sport_type="RIDE", start_lat=59.10, start_lng=-144.10, end_lat=59.11, end_lng=-144.10, distance_m=1000, city="Pageville")
        create_segment(api, owner["id"], name="Page Run A", sport_type="RUN", start_lat=59.20, start_lng=-144.20, end_lat=59.21, end_lng=-144.20, distance_m=1000, city="Pageville")
        resp = api.list_segments(make_athlete_headers(owner["id"]), params={"sport_type": "RIDE", "limit": 1})
        rows, meta = validate_paginated(resp)
        assert len(rows) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert rows[0]["sport_type"] == "RIDE"

    def test_offset_walks_the_remaining_page(self, api):
        """PRD 2.3: "The `offset` parameter specifies how many items to skip and defaults to 0."
        PRD 2.3: "every list endpoint returns resources sorted by their creation timestamp in ascending order (`created_at` ascending)".

        Design: Corner/endpoints/segments_list_filter_and_pagination
        """
        owner = create_athlete(api, email="pg_q@x.com", display_name="PG Q")
        create_segment(api, owner["id"], name="Walk Ride A", sport_type="RIDE")
        create_segment(api, owner["id"], name="Walk Ride B", sport_type="RIDE")
        headers = make_athlete_headers(owner["id"])
        page1, meta1 = validate_paginated(api.list_segments(headers, params={"sport_type": "RIDE", "limit": 1}))
        page2, meta2 = validate_paginated(api.list_segments(headers, params={"sport_type": "RIDE", "limit": 1, "offset": 1}))
        assert page1[0]["id"] != page2[0]["id"]
        assert meta2["has_more"] is False
        assert meta1["total_count"] == meta2["total_count"] == 2


class TestNonOwnerReadsObfuscatedRouteOnly:
    def test_non_owner_sees_only_surviving_points(self, api):
        """PRD 3.3: "Public reads expose only the obfuscated route: a caller who is not the activity's owner (or a privileged role) receives the obfuscated coordinates and `obfuscated_track` in place of the raw fields."
        PRD 3.3: "the public route is derived from the raw `track_points` by walking the ordered points and dropping each one whose haversine distance to the center of *any* of the owner's `ACTIVE` zones is at most that zone's radius".

        Design: Corner/endpoints/non_owner_reads_obfuscated_route_only
        """
        owner = create_athlete(api, email="po_p@x.com", display_name="PO P", home_lat=60.0, home_lng=-145.0)
        reader = create_athlete(api, email="pu_p@x.com", display_name="PU P")
        create_privacy_zone(api, owner["id"], center_lat=60.000, center_lng=-145.000, radius_m=500)
        activity = upload_activity(
            api, owner["id"],
            device_source="mobile-app", sport_type="RUN", started_at="2026-09-01T06:00:00Z",
            duration_s=900, distance_m=3000,
            track_points=[
                {"lat": 60.001, "lng": -145.000, "t_offset_s": 0},
                {"lat": 60.002, "lng": -145.001, "t_offset_s": 300},
                {"lat": 60.100, "lng": -145.100, "t_offset_s": 600},
                {"lat": 60.001, "lng": -145.002, "t_offset_s": 900},
            ],
            start_lat=60.001, start_lng=-145.000, end_lat=60.001, end_lng=-145.002,
            idempotency_key="po-1",
        )
        view = validate_success(api.get_activity(activity["id"], make_athlete_headers(reader["id"])), 200)
        assert len(view["obfuscated_track"]) == 1
        assert view["obfuscated_start_lat"] == 60.100
        assert view["obfuscated_end_lat"] == 60.100
        # The public view must not surface the raw corners as the visible route.
        assert view["obfuscated_start_lat"] != 60.001

    def test_owner_still_sees_raw_track(self, api):
        """PRD 3.3: "Public reads expose only the obfuscated route: a caller who is not the activity's owner (or a privileged role) receives the obfuscated coordinates and `obfuscated_track` in place of the raw fields." — the owner is not a public reader.

        Design: Corner/endpoints/non_owner_reads_obfuscated_route_only
        """
        owner = create_athlete(api, email="po_q@x.com", display_name="PO Q", home_lat=60.0, home_lng=-145.0)
        create_privacy_zone(api, owner["id"], center_lat=60.000, center_lng=-145.000, radius_m=500)
        track = [
            {"lat": 60.001, "lng": -145.000, "t_offset_s": 0},
            {"lat": 60.100, "lng": -145.100, "t_offset_s": 600},
            {"lat": 60.001, "lng": -145.002, "t_offset_s": 900},
        ]
        activity = upload_activity(
            api, owner["id"],
            sport_type="RUN", started_at="2026-09-01T06:00:00Z", duration_s=900, distance_m=3000,
            track_points=track, start_lat=60.001, start_lng=-145.000, end_lat=60.001, end_lng=-145.002,
            idempotency_key="po-2",
        )
        view = validate_success(api.get_activity(activity["id"], make_athlete_headers(owner["id"])), 200)
        assert view["track_points"] == track
