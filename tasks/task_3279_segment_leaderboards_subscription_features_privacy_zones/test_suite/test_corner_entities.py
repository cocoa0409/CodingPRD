"""Entity corner claims: creation defaults, uniqueness, ranges, 404s."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    build_user_headers,
    ApiErrorId,
    assert_athlete,
    assert_club,
    assert_privacy_zone,
    assert_segment,
    create_athlete,
    create_club,
    create_privacy_zone,
    create_segment,
    make_athlete_headers,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_athlete_payload,
    create_privacy_zone_payload,
    create_segment_payload,
)


class TestAthleteCreateDefaults:
    def test_athlete_create_defaults_and_system_fields(self, api):
        """PRD 3.1: "Registration optionally accepts a `tier` of `FREE` or `SUMMIT` (defaulting to `FREE`) and a `heatmap_opt_out` flag (defaulting to false). A new athlete begins with `status` `ACTIVE` and a `safety_score` of 100."
        PRD 2.4: "`version` (integer): a system-managed integer that increments by one on every mutation of the resource, used for optimistic concurrency control."

        Design: Corner/entities/athlete_create_defaults_and_system_fields
        """
        resp = api.create_athlete(
            create_athlete_payload(email="d_ef@x.com", display_name="D EF", home_lat=37.0, home_lng=-122.0),
            build_user_headers("platform-admin-1", "PlatformAdmin"),
        )
        data = validate_success(resp, 201)
        assert_athlete(data)
        assert data["tier"] == "FREE"
        assert data["heatmap_opt_out"] is False
        assert data["safety_score"] == 100
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1

    def test_athlete_create_ignores_client_supplied_system_fields(self, api):
        """PRD 2.4: "Every resource in the system carries a standard set of system-managed fields"; system-managed means the server, not the client, owns them.
        PRD 3.1: "A new athlete begins with `status` `ACTIVE` and a `safety_score` of 100."

        Design: Corner/entities/athlete_create_defaults_and_system_fields
        """
        payload = create_athlete_payload(email="d_ef2@x.com", display_name="D EF2")
        payload["status"] = "DELETED"
        payload["safety_score"] = 7
        resp = api.create_athlete(payload, build_user_headers("platform-admin-1", "PlatformAdmin"))
        data = validate_success(resp, 201)
        assert data["status"] == "ACTIVE"
        assert data["safety_score"] == 100


class TestAthleteEmailUniqueness:
    def test_second_registration_with_taken_email_rejected(self, api):
        """PRD 3.1: "Anyone registering provides a unique `email` (stored lowercased; uniqueness is enforced globally and a taken address is rejected with `ERR_UNIQUE_VIOLATION`)".

        Design: Corner/entities/athlete_email_uniqueness_rejected
        """
        create_athlete(api, email="dup@x.com", display_name="First")
        resp = api.create_athlete(
            create_athlete_payload(email="dup@x.com", display_name="Second", home_lat=38.0, home_lng=-123.0),
            build_user_headers("platform-admin-1", "PlatformAdmin"),
        )
        validate_error(resp, ApiErrorId.ERR_UNIQUE_VIOLATION)

    def test_same_email_under_different_display_name_still_rejected(self, api):
        """PRD 3.1: "uniqueness is enforced globally and a taken address is rejected with `ERR_UNIQUE_VIOLATION`".

        Design: Corner/entities/athlete_email_uniqueness_rejected
        """
        first = create_athlete(api, email="dup2@x.com", display_name="Alpha")
        resp = api.create_athlete(
            create_athlete_payload(email="dup2@x.com", display_name="Beta"),
            build_user_headers("platform-admin-1", "PlatformAdmin"),
        )
        validate_error(resp, ApiErrorId.ERR_UNIQUE_VIOLATION)
        # The original athlete is untouched and readable.
        got = validate_success(api.get_athlete(first["id"], make_athlete_headers(first["id"])), 200)
        assert got["display_name"] == "Alpha"


class TestAthleteNotFound:
    def test_get_nonexistent_athlete_returns_404(self, api):
        """PRD 2.5: "A request to a child resource under a nonexistent parent is rejected with `ERR_NOT_FOUND` (HTTP 404) for the first identifier that fails to resolve, without inspecting later path segments."

        Design: Corner/entities/athlete_not_found_returns_404
        """
        resp = api.get_athlete(NON_EXISTENT_UUID, build_user_headers("platform-admin-1", "PlatformAdmin"))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPrivacyZoneCardinality:
    def test_second_zone_for_same_athlete_rejected(self, api):
        """PRD 3.3: "Each athlete may define exactly one privacy zone — a second attempt is rejected with `ERR_UNIQUE_VIOLATION`."

        Design: Corner/entities/privacy_zone_one_per_athlete
        """
        athlete = create_athlete(api, email="zo_z@x.com", display_name="ZO Z")
        create_privacy_zone(api, athlete["id"], center_lat=37.0, center_lng=-122.0, radius_m=500)
        resp = api.create_privacy_zone(
            athlete["id"],
            create_privacy_zone_payload(center_lat=38.0, center_lng=-123.0, radius_m=300),
            make_athlete_headers(athlete["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNIQUE_VIOLATION)


class TestPrivacyZoneRadiusRange:
    def test_radius_below_200_rejected(self, api):
        """PRD 3.3: "A zone is created with a `center_lat`, `center_lng`, and an integer `radius_m` between 200 and 2000 meters inclusive".

        Design: Corner/entities/privacy_zone_radius_range_enforced
        """
        athlete = create_athlete(api, email="zr_z@x.com", display_name="ZR Z")
        resp = api.create_privacy_zone(
            athlete["id"],
            create_privacy_zone_payload(center_lat=37.0, center_lng=-122.0, radius_m=100),
            make_athlete_headers(athlete["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestSegmentNameSportUniqueness:
    def test_duplicate_name_same_sport_rejected_other_sport_accepted(self, api):
        """PRD 3.5: "The `(name, sport_type)` pair must be unique among all segments not in `RETIRED` status — and because a retired segment keeps its name reserved, a `DRAFT` segment that recreates the name and sport of an `ACTIVE` *or* `RETIRED` segment is rejected with `ERR_UNIQUE_VIOLATION`."

        Design: Corner/entities/segment_name_sport_uniqueness_among_living
        """
        athlete = create_athlete(api, email="sn_s@x.com", display_name="SN S")
        create_segment(
            api, athlete["id"], name="Twin Peak", sport_type="RIDE",
            start_lat=47.00, start_lng=-132.00, end_lat=47.01, end_lng=-132.00,
            distance_m=1000, city="Twinville",
        )
        headers = make_athlete_headers(athlete["id"])
        dup = api.create_segment(
            create_segment_payload(
                athlete["id"], name="Twin Peak", sport_type="RIDE",
                start_lat=48.00, start_lng=-133.00, end_lat=48.01, end_lng=-133.00,
                distance_m=1000, city="Twinville",
            ),
            headers,
        )
        validate_error(dup, ApiErrorId.ERR_UNIQUE_VIOLATION)
        other_sport = api.create_segment(
            create_segment_payload(
                athlete["id"], name="Twin Peak", sport_type="RUN",
                start_lat=48.00, start_lng=-133.00, end_lat=48.01, end_lng=-133.00,
                distance_m=1000, city="Twinville",
            ),
            headers,
        )
        created = validate_success(other_sport, 201)
        assert_segment(created)
        assert created["sport_type"] == "RUN"

    def test_name_of_retired_segment_still_reserved(self, api):
        """PRD 3.5: "because a retired segment keeps its name reserved, a `DRAFT` segment that recreates the name and sport of an `ACTIVE` *or* `RETIRED` segment is rejected with `ERR_UNIQUE_VIOLATION`."

        Design: Corner/entities/segment_name_sport_uniqueness_among_living
        """
        athlete = create_athlete(api, email="sn_r@x.com", display_name="SN R")
        headers = make_athlete_headers(athlete["id"])
        seg = create_segment(api, athlete["id"], name="Reserved Rise", sport_type="RIDE")
        retire = api.retire_segment(seg["id"], headers)
        validate_success(retire, 200)
        resp = api.create_segment(
            create_segment_payload(athlete["id"], name="Reserved Rise", sport_type="RIDE"),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNIQUE_VIOLATION)


class TestClubNameUniqueness:
    def test_live_club_name_rejected_archived_name_allowed(self, api):
        """PRD 3.7: "An athlete founds a club by supplying an `owner_id`, a `name` of 3 to 60 characters that is globally unique among non-`ARCHIVED` clubs".

        Design: Corner/entities/club_name_uniqueness_ignores_archived
        """
        owner = create_athlete(api, email="cu_c@x.com", display_name="CU C")
        headers = make_athlete_headers(owner["id"])
        club = create_club(api, owner["id"], name="Riders United", sport_type="RIDE", join_policy="OPEN")
        dup = api.create_club(
            {"owner_id": owner["id"], "name": "Riders United", "sport_type": "RUN", "join_policy": "OPEN"},
            headers,
        )
        validate_error(dup, ApiErrorId.ERR_UNIQUE_VIOLATION)
        validate_success(api.archive_club(club["id"], headers), 200)
        recreated = api.create_club(
            {"owner_id": owner["id"], "name": "Riders United", "sport_type": "RUN", "join_policy": "OPEN"},
            headers,
        )
        data = validate_success(recreated, 201)
        assert_club(data)
        assert data["name"] == "Riders United"
