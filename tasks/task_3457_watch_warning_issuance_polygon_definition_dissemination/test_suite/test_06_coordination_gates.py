"""Coordination gates and validation-tier precedence.

Unsatisfiable cross-CWA geometry is a referential error (tier 11), a needless
submit is a state error, a skipped submit is ERR_COORDINATION_NOT_ACKED, and
issuance criteria (tier 8) outrank both temporal (tier 9) and referential
(tier 11) failures (PRD §2.8, §3.5).
"""

from test_helpers import (
    ApiErrorId,
    Bundle,
    create_forecaster,
    create_office,
    create_storm,
    create_warning_draft,
    create_watch_draft,
    create_zone,
    get_product,
    list_coordination_requests,
    make_forecaster_headers,
    set_clock,
    setup_coordinated_offices,
    setup_office_with_storm,
    setup_office_with_zone,
    validate_error,
)


def _offices_without_agreement(api) -> Bundle:
    """Offices A and C with NO neighbor agreement; C owns a zone at
    lon 0.2..0.3; A has a forecaster and a SEVERE storm at 50 mph."""
    office_a = create_office(api)
    office_c = create_office(api)
    zone_c = create_zone(api, office_c["id"], lon_min=0.2, lon_max=0.3)
    fc_a = create_forecaster(api, office_a["id"])
    headers_a = make_forecaster_headers(fc_a["id"])
    storm = create_storm(
        api, office_a["id"], headers_a, "SEVERE_THUNDERSTORM", max_wind_mph=50
    )
    return Bundle(office_a=office_a, office_c=office_c, zone_c=zone_c, headers_a=headers_a, storm=storm)


def _cross_cwa_low_wind_draft(api, env):
    """A warning draft from office A whose polygon spans lon 0.05..0.25,
    overlapping office C's zone by a quarter of its area with no covering
    agreement; the storm's 50 mph is below the 58 mph warning criterion."""
    return create_warning_draft(
        api,
        env.office_a,
        env.headers_a,
        env.storm,
        polygon={
            "vertices": [
                {"lat": 0.0, "lon": 0.05},
                {"lat": 0.0, "lon": 0.25},
                {"lat": 0.1, "lon": 0.25},
                {"lat": 0.1, "lon": 0.05},
            ]
        },
        expires_at="2026-09-01T01:00:00Z",
    )


class TestSubmitCoordinationGates:
    def test_submit_coordination_without_agreement_returns_zone_outside_cwa(self, api):
        """PRD §3.5: "When a required office is unsatisfiable, the submit is
        rejected with `ERR_ZONE_OUTSIDE_CWA` for an office reached through the
        zone list or `ERR_POLYGON_OUTSIDE_CWA` for one reached through polygon
        overlap."

        Design: Corner/validations/submit_coordination_without_agreement_returns_zone_outside_cwa
        """
        office_a = create_office(api)
        office_x = create_office(api)
        zone_a = create_zone(api, office_a["id"])
        zone_x = create_zone(api, office_x["id"], lon_min=0.2, lon_max=0.3)
        fc_a = create_forecaster(api, office_a["id"])
        headers_a = make_forecaster_headers(fc_a["id"])
        draft = create_watch_draft(
            api,
            office_a,
            headers_a,
            [zone_a["id"], zone_x["id"]],
            hazard_type="SEVERE_THUNDERSTORM",
            effective_from="2026-09-01T06:00:00Z",
            expires_at="2026-09-01T18:00:00Z",
        )
        assert draft["coordination_required"] is True
        resp = api.submit_coordination(draft["id"], headers_a)
        validate_error(resp, ApiErrorId.ERR_ZONE_OUTSIDE_CWA)
        assert get_product(api, draft["id"], headers_a)["status"] == "DRAFT"
        assert list_coordination_requests(api, draft["id"], headers_a) == [], (
            "the rejected submit created zero requests"
        )

    def test_submit_coordination_when_not_required_returns_invalid_state(self, api):
        """PRD §3.5: "The submission is only meaningful when
        `coordination_required` is true; submitting a product that needs no
        coordination is rejected with `ERR_INVALID_PRODUCT_STATE`."

        Design: Corner/validations/submit_coordination_when_not_required_returns_invalid_state
        """
        bundle = setup_office_with_zone(api)
        draft = create_watch_draft(
            api,
            bundle.office,
            bundle.headers,
            [bundle.zone["id"]],
            hazard_type="SEVERE_THUNDERSTORM",
            effective_from="2026-09-01T06:00:00Z",
            expires_at="2026-09-01T18:00:00Z",
        )
        assert draft["coordination_required"] is False, (
            "own-CWA zone, non-HURRICANE hazard: nothing requires coordination"
        )
        resp = api.submit_coordination(draft["id"], bundle.headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_PRODUCT_STATE)
        assert get_product(api, draft["id"], bundle.headers)["status"] == "DRAFT"

    def test_issue_draft_with_satisfiable_coordination_returns_not_acked(self, api):
        """PRD §3.5: "When coordination is required and every required office
        is satisfiable but coordination was never submitted, issuance is
        rejected with `ERR_COORDINATION_NOT_ACKED`"

        Design: Corner/state_machines/issue_draft_with_satisfiable_coordination_returns_not_acked
        """
        bundle = setup_coordinated_offices(api)
        draft = create_watch_draft(
            api,
            bundle.office_a,
            bundle.headers_a,
            [bundle.zone_a["id"], bundle.zone_b["id"]],
            hazard_type="SEVERE_THUNDERSTORM",
            effective_from="2026-09-01T06:00:00Z",
            expires_at="2026-09-01T18:00:00Z",
        )
        resp = api.issue_product(
            draft["id"], {"expected_product_version": draft["version"]}, bundle.headers_a
        )
        validate_error(resp, ApiErrorId.ERR_COORDINATION_NOT_ACKED)
        assert get_product(api, draft["id"], bundle.headers_a)["status"] == "DRAFT"
        assert list_coordination_requests(api, draft["id"], bundle.headers_a) == [], (
            "no requests were created by the failed issue"
        )


class TestCriteriaPrecedesReferentialTier:
    def test_low_wind_reports_criteria_error_despite_cross_cwa_polygon(self, api):
        """PRD §2.8: "a request that would fail at several tiers is always
        rejected with the error from the earliest applicable tier"
        PRD §3.5: "Failure of the requested level's criteria is rejected with
        `ERR_ISSUANCE_CRITERIA_NOT_MET`."

        Design: Difficulty/priority_pair_validation_conflict/low_wind_and_polygon_outside_cwa_reports_criteria_error
        """
        env = _offices_without_agreement(api)
        draft = _cross_cwa_low_wind_draft(api, env)
        resp = api.issue_product(
            draft["id"], {"expected_product_version": draft["version"]}, env.headers_a
        )
        err = validate_error(resp, ApiErrorId.ERR_ISSUANCE_CRITERIA_NOT_MET)
        assert err["error_id"] == "ERR_ISSUANCE_CRITERIA_NOT_MET", (
            "wind 50 < 58 fails the safety tier before any referential check"
        )

    def test_criteria_error_precedes_referential_tier(self, api):
        """PRD §2.8: "a product whose required coordination offices include an
        office with no covering agreement is rejected from the final
        referential tier with `ERR_ZONE_OUTSIDE_CWA` or
        `ERR_POLYGON_OUTSIDE_CWA` — never with `ERR_COORDINATION_NOT_ACKED`,
        which is reserved for satisfiable-but-incomplete coordination."
        PRD §2.8: "Eighth, issuance criteria and polygon geometry
        (`ERR_ISSUANCE_CRITERIA_NOT_MET`, `ERR_POLYGON_INVALID`)."

        Design: Difficulty/priority_pair_validation_conflict/low_wind_and_polygon_outside_cwa_reports_criteria_error
        """
        env = _offices_without_agreement(api)
        draft = _cross_cwa_low_wind_draft(api, env)
        assert draft["coordination_required"] is True, (
            "the polygon reaches into office C's CWA"
        )
        resp = api.issue_product(
            draft["id"], {"expected_product_version": draft["version"]}, env.headers_a
        )
        err = validate_error(resp, ApiErrorId.ERR_ISSUANCE_CRITERIA_NOT_MET)
        assert err["error_id"] != "ERR_POLYGON_OUTSIDE_CWA"
        assert err["error_id"] != "ERR_COORDINATION_NOT_ACKED"
        assert get_product(api, draft["id"], env.headers_a)["status"] == "DRAFT"


class TestCriteriaPrecedesTemporalTier:
    def test_safety_criteria_beats_temporal_duration_violation(self, api):
        """PRD §2.8: "a request that would fail at several tiers is always
        rejected with the error from the earliest applicable tier"
        PRD §2.8: "Eighth, issuance criteria and polygon geometry
        (`ERR_ISSUANCE_CRITERIA_NOT_MET`, `ERR_POLYGON_INVALID`). Ninth,
        temporal window checks (`ERR_WINDOW_INVALID`,
        `ERR_DURATION_OUT_OF_RANGE`, `ERR_EFFECTIVE_IN_PAST`)."

        Design: Corner/validations/safety_criteria_beats_temporal_duration_violation
        """
        bundle = setup_office_with_storm(
            api, hazard_type="SEVERE_THUNDERSTORM", readings={"max_wind_mph": 57}
        )
        set_clock(api, "2026-09-01T10:00:00Z")
        draft = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm, expires_at="2026-09-01T12:01:00Z"
        )
        resp = api.issue_product(
            draft["id"], {"expected_product_version": draft["version"]}, bundle.headers
        )
        err = validate_error(resp, ApiErrorId.ERR_ISSUANCE_CRITERIA_NOT_MET)
        assert err["error_id"] != "ERR_DURATION_OUT_OF_RANGE", (
            "the 121-minute window also violates the ceiling, but safety reports first"
        )
        assert get_product(api, draft["id"], bundle.headers)["status"] == "DRAFT"
