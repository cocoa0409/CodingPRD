"""Breadth claims about the computed summary read and the manual lifecycle
actions."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    get_engagement_data,
    get_summary_data,
    validate_error,
)


class TestIndependenceSummaryRead:
    """The roll-up exposes each count that feeds the posture."""

    def test_summary_reports_each_count_separately(self, api):
        """PRD §4: "its `data` object carries `engagement_id`,
        `independence_status`, `critical_open_count`, `high_open_count`,
        `prohibited_service_count`, `breached_attestation_count`,
        `material_interest_count` and `network_risk_points`".

        Design: Corner/endpoints/independence_summary_breakdown_matches_the_stored_rows
        """
        world = fixtures.scenario_summary_breakdown(api)
        summary = get_summary_data(api, world["engagement"]["id"])

        assert summary["engagement_id"] == world["engagement"]["id"]
        # The inspection finding plus the finding the material interest raised.
        assert summary["critical_open_count"] == 2
        assert summary["high_open_count"] == 1
        assert summary["prohibited_service_count"] == 0
        assert summary["breached_attestation_count"] == 1
        assert summary["material_interest_count"] == 1
        # One cumulative breach on a member firm weighs three points.
        assert summary["network_risk_points"] == 3

    def test_summary_posture_matches_the_frozen_branch(self, api):
        """PRD §2.6: "The posture is `FROZEN` when any one of these holds: at
        least one live `CRITICAL` finding".

        Design: Corner/endpoints/independence_summary_breakdown_matches_the_stored_rows
        """
        world = fixtures.scenario_summary_breakdown(api)
        summary = get_summary_data(api, world["engagement"]["id"])
        engagement = get_engagement_data(api, world["engagement"]["id"])

        assert summary["independence_status"] == "FROZEN"
        assert engagement["independence_status"] == "FROZEN"


class TestManualResumeAction:
    """RESUME is conditional on the derived posture axis."""

    def test_resume_is_rejected_while_the_engagement_is_frozen(self, api):
        """PRD §3.9: "The `RESUME` action moves a `SUSPENDED` engagement back to
        `ACTIVE`, but only when its independence posture is not `FROZEN`; a
        frozen engagement is rejected with `ERR_ENGAGEMENT_FROZEN`."

        Design: Corner/endpoints/engagement_resume_is_rejected_while_frozen
        """
        world = fixtures.scenario_resume_while_frozen(api)
        assert world["engagement"]["status"] == "SUSPENDED"
        assert world["engagement"]["independence_status"] == "FROZEN"

        response = fixtures.engagement_transition(
            api, world["engagement"]["id"], "RESUME", world["ep_headers"]
        )
        validate_error(response, ApiErrorId.ERR_ENGAGEMENT_FROZEN)

        unchanged = get_engagement_data(api, world["engagement"]["id"])
        assert unchanged["status"] == "SUSPENDED"

    def test_clearing_the_critical_finding_returns_the_engagement_to_active(self, api):
        """PRD §2.6: "an engagement suspended by that rule returns to `ACTIVE`
        provided no live `CRITICAL` finding remains."

        Design: Corner/endpoints/engagement_resume_is_rejected_while_frozen
        """
        world = fixtures.scenario_resume_while_frozen(api)
        finding_id = world["finding"]["id"]

        fixtures.finding_transition_ok(api, finding_id, "START_REMEDIATION")
        fixtures.finding_transition_ok(api, finding_id, "SUBMIT_FOR_RETEST")
        fixtures.finding_transition_ok(api, finding_id, "PASS_RETEST")

        engagement = get_engagement_data(api, world["engagement"]["id"])
        assert engagement["independence_status"] == "CLEAR"
        assert engagement["status"] == "ACTIVE"
