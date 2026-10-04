"""Issuance criteria: inclusive thresholds, duration gate, current readings.

Every issue here runs from DRAFT against an own-CWA polygon product so no
coordination precondition interferes (PRD §3.5).
"""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    create_storm,
    create_warning_draft,
    create_watch_draft,
    get_product,
    get_storm,
    issue_product,
    set_clock,
    setup_office_with_storm,
    setup_office_with_zone,
    update_storm,
    validate_error,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC instant regardless of fractional-digit rendering."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestWindThreshold:
    def test_wind_58_issues_at_inclusive_threshold(self, api):
        """PRD §3.5: "for `SEVERE_THUNDERSTORM`, wind of at least 58 mph or
        hail of at least 1.00 inch"
        PRD §2.5: "Threshold comparisons in issuance criteria and impact
        scoring are inclusive: "at least 58 mph" is satisfied by exactly 58."

        Design: Difficulty/boundary_precision_check/wind_58_issues_wind_57_rejected
        """
        bundle = setup_office_with_storm(
            api, hazard_type="SEVERE_THUNDERSTORM", readings={"max_wind_mph": 58}
        )
        set_clock(api, "2026-09-01T10:00:00Z")
        draft = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm, expires_at="2026-09-01T10:45:00Z"
        )
        product = issue_product(api, draft["id"], bundle.headers)
        assert product["status"] == "ISSUED", "58 >= 58 satisfies the inclusive threshold"

    def test_wind_57_rejected_below_threshold(self, api):
        """PRD §3.5: "for `SEVERE_THUNDERSTORM`, wind of at least 58 mph or
        hail of at least 1.00 inch"
        PRD §3.5: "Failure of the requested level's criteria is rejected with
        `ERR_ISSUANCE_CRITERIA_NOT_MET`."

        Design: Difficulty/boundary_precision_check/wind_58_issues_wind_57_rejected
        """
        bundle = setup_office_with_storm(
            api, hazard_type="SEVERE_THUNDERSTORM", readings={"max_wind_mph": 57}
        )
        set_clock(api, "2026-09-01T10:00:00Z")
        draft = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm, expires_at="2026-09-01T10:45:00Z"
        )
        resp = api.issue_product(
            draft["id"], {"expected_product_version": draft["version"]}, bundle.headers
        )
        validate_error(resp, ApiErrorId.ERR_ISSUANCE_CRITERIA_NOT_MET)
        assert get_product(api, draft["id"], bundle.headers)["status"] == "DRAFT"


class TestHailThreshold:
    def test_hail_threshold_100_included_099_rejected(self, api):
        """PRD §3.5: "for `SEVERE_THUNDERSTORM`, wind of at least 58 mph or
        hail of at least 1.00 inch"
        PRD §3.5: "Failure of the requested level's criteria is rejected with
        `ERR_ISSUANCE_CRITERIA_NOT_MET`."

        Design: Corner/calculations/hail_threshold_100_included_099_rejected
        """
        bundle = setup_office_with_zone(api)
        storm_ok = create_storm(
            api, bundle.office["id"], bundle.headers, "SEVERE_THUNDERSTORM",
            max_wind_mph=0, max_hail_inches=1.00,
        )
        storm_low = create_storm(
            api, bundle.office["id"], bundle.headers, "SEVERE_THUNDERSTORM",
            max_wind_mph=0, max_hail_inches=0.99,
        )
        set_clock(api, "2026-09-01T10:00:00Z")
        draft_ok = create_warning_draft(
            api, bundle.office, bundle.headers, storm_ok, expires_at="2026-09-01T10:45:00Z"
        )
        draft_low = create_warning_draft(
            api, bundle.office, bundle.headers, storm_low, expires_at="2026-09-01T10:45:00Z"
        )
        product = issue_product(api, draft_ok["id"], bundle.headers)
        assert product["status"] == "ISSUED", "hail exactly 1.00 inch meets the inclusive criterion"
        resp = api.issue_product(
            draft_low["id"], {"expected_product_version": draft_low["version"]}, bundle.headers
        )
        validate_error(resp, ApiErrorId.ERR_ISSUANCE_CRITERIA_NOT_MET)


class TestDurationGate:
    def test_duration_out_of_range_below_min_and_above_max(self, api):
        """PRD §3.5: "the whole minutes between `effective_from` and
        `expires_at` must fall inside the hazard's inclusive range — 15 to 120
        minutes for severe thunderstorm, 15 to 90 for tornado, 30 to 180 for
        flash flood, 60 to 720 for hurricane, and 60 to 720 for winter storm —
        or issuance fails with `ERR_DURATION_OUT_OF_RANGE`."
        PRD §3.5: "`WATCH` and `OUTLOOK` products carry no reading-based
        criterion at all."

        Design: Corner/calculations/duration_out_of_range_below_min_and_above_max
        """
        bundle = setup_office_with_storm(
            api, hazard_type="SEVERE_THUNDERSTORM", readings={"max_wind_mph": 60}
        )
        set_clock(api, "2026-09-01T10:00:00Z")
        draft_short = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm, expires_at="2026-09-01T10:10:00Z"
        )
        draft_long = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm, expires_at="2026-09-01T12:01:00Z"
        )
        watch = create_watch_draft(
            api,
            bundle.office,
            bundle.headers,
            [bundle.zone["id"]],
            hazard_type="WINTER_STORM",
            effective_from="2026-09-01T10:00:00Z",
            expires_at="2026-09-01T22:00:00Z",
        )
        resp = api.issue_product(
            draft_short["id"], {"expected_product_version": draft_short["version"]}, bundle.headers
        )
        validate_error(resp, ApiErrorId.ERR_DURATION_OUT_OF_RANGE)
        resp = api.issue_product(
            draft_long["id"], {"expected_product_version": draft_long["version"]}, bundle.headers
        )
        validate_error(resp, ApiErrorId.ERR_DURATION_OUT_OF_RANGE)
        product = issue_product(api, watch["id"], bundle.headers)
        assert product["status"] == "ISSUED", "duration bounds do not apply to WATCH"


class TestCriteriaReadFromCurrentReadings:
    def test_criteria_reevaluated_at_issue_from_current_storm_readings(self, api):
        """PRD §3.5: "Content checks at issuance run against the linked storm's
        current readings."
        PRD §3.3: "The first successful update also moves the event from
        `DETECTED` to `TRACKING`"
        PRD §2.6: "Issuing a product requires `expected_product_version`
        holding the client's last observed `version` of the product being
        issued."

        Design: Corner/calculations/criteria_reevaluated_at_issue_from_current_storm_readings
        """
        bundle = setup_office_with_storm(
            api, hazard_type="SEVERE_THUNDERSTORM", readings={"max_wind_mph": 50}
        )
        set_clock(api, "2026-09-01T10:00:00Z")
        draft = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm, expires_at="2026-09-01T10:45:00Z"
        )
        resp = api.issue_product(
            draft["id"], {"expected_product_version": draft["version"]}, bundle.headers
        )
        validate_error(resp, ApiErrorId.ERR_ISSUANCE_CRITERIA_NOT_MET)
        assert get_product(api, draft["id"], bundle.headers)["version"] == draft["version"], (
            "the failed issue attempt bumped nothing"
        )

        storm = update_storm(
            api, bundle.storm["id"], bundle.headers,
            expected_version=bundle.storm["version"], max_wind_mph=60,
        )
        assert storm["version"] == bundle.storm["version"] + 1
        assert storm["status"] == "TRACKING", "first update flips DETECTED -> TRACKING"

        resp = api.issue_product(
            draft["id"], {"expected_product_version": draft["version"]}, bundle.headers
        )
        product = validate_success(resp)
        assert product["status"] == "ISSUED", "the criteria now read the updated wind 60"
        assert _instant(product["issued_at"]) == _instant("2026-09-01T10:00:00Z")


class TestAdvisoryFloor:
    def test_advisory_floor_wind_40_issues_advisory_but_not_warning(self, api):
        """PRD §3.5: "An `ADVISORY` is issuable exactly when any advisory floor
        is met, and warning-strength readings always satisfy an advisory floor:
        for `SEVERE_THUNDERSTORM`, wind of at least 40 mph or hail of at least
        0.75 inches"
        PRD §3.4: "for warnings and advisories the server ignores the supplied
        onset and overwrites `effective_from` with the issuance instant."

        Design: Corner/calculations/advisory_floor_wind_40_issues_advisory_but_not_warning
        """
        bundle = setup_office_with_storm(
            api, hazard_type="SEVERE_THUNDERSTORM", readings={"max_wind_mph": 45}
        )
        set_clock(api, "2026-09-01T10:00:00Z")
        advisory = create_warning_draft(
            api,
            bundle.office,
            bundle.headers,
            bundle.storm,
            polygon={
                "vertices": [
                    {"lat": 0.0, "lon": 0.0},
                    {"lat": 0.0, "lon": 0.05},
                    {"lat": 0.1, "lon": 0.05},
                    {"lat": 0.1, "lon": 0.0},
                ]
            },
            expires_at="2026-09-01T10:45:00Z",
            product_level="ADVISORY",
        )
        warning = create_warning_draft(
            api,
            bundle.office,
            bundle.headers,
            bundle.storm,
            polygon={
                "vertices": [
                    {"lat": 0.0, "lon": 0.05},
                    {"lat": 0.0, "lon": 0.1},
                    {"lat": 0.1, "lon": 0.1},
                    {"lat": 0.1, "lon": 0.05},
                ]
            },
            expires_at="2026-09-01T10:45:00Z",
        )
        product = issue_product(api, advisory["id"], bundle.headers)
        assert product["status"] == "ISSUED", "45 >= 40 advisory floor"
        assert product["effective_from"] == product["issued_at"], (
            "polygon advisory onset is overwritten with the issuance instant"
        )
        assert _instant(product["issued_at"]) == _instant("2026-09-01T10:00:00Z")

        resp = api.issue_product(
            warning["id"], {"expected_product_version": warning["version"]}, bundle.headers
        )
        validate_error(resp, ApiErrorId.ERR_ISSUANCE_CRITERIA_NOT_MET)
        assert get_storm(api, bundle.storm["id"], bundle.headers)["max_wind_mph"] == 45
