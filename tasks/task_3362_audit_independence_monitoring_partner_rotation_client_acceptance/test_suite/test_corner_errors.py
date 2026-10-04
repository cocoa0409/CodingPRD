"""Breadth claims about the two clock-facing date validations."""

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK,
    assert_same_instant,
    fixtures,
    get_acceptance_data,
    get_assignment_data,
    validate_error,
)


class TestAssignmentDating:
    """An assignment may not start before the logical clock."""

    def test_backdated_assignment_start_is_rejected(self, api):
        """PRD §3.3: "A `started_on` earlier than the logical clock is rejected
        as a backdated assignment with `ERR_BACKDATED_ASSIGNMENT`."

        Design: Corner/errors/error_backdated_assignment_start_is_rejected
        """
        world = fixtures.scenario_assignment_gates(api)

        response = fixtures.staff(
            api, world["engagement"]["id"], world["professional"]["id"], "LEAD_PARTNER",
            "2026-09-30T00:00:00Z", "2027-09-30T00:00:00Z",
            ep_headers=world["ep_headers"],
        )
        validate_error(response, ApiErrorId.ERR_BACKDATED_ASSIGNMENT, 422)

    def test_assignment_starting_at_the_clock_is_admitted(self, api):
        """PRD §2.10: "`EngagementRoleAssignment.started_on` must not be earlier
        than the logical clock. Otherwise `ERR_BACKDATED_ASSIGNMENT` with HTTP
        422."

        Design: Corner/errors/error_backdated_assignment_start_is_rejected
        """
        world = fixtures.scenario_assignment_gates(api)

        assignment = fixtures.staff_ok(
            api, world["engagement"]["id"], world["professional"]["id"], "LEAD_PARTNER",
            "2026-10-01T00:00:00Z", "2027-10-01T00:00:00Z",
            ep_headers=world["ep_headers"],
        )
        stored = get_assignment_data(api, assignment["id"])
        assert_same_instant(stored["started_on"], "2026-10-01T00:00:00Z")
        assert stored["status"] == "ACTIVE"


class TestAssessmentDating:
    """An assessment may not be dated after the logical clock."""

    def test_future_dated_assessment_is_rejected_without_recomputing(self, api):
        """PRD §3.2: "an assessment dated later than the logical clock is
        rejected outright with `ERR_ASSESSMENT_DATE_IN_FUTURE`."
        PRD §3.5: "`IntegrityAssessment.assessed_on` must not be later than the
        logical clock."

        Design: Corner/errors/error_future_dated_integrity_assessment_is_rejected
        """
        fixtures.set_clock(api)
        world = fixtures.seed_reference_data(api, legal_name="Ashford Analytics")
        acceptance = fixtures.open_acceptance(
            api, world["client"]["id"], world["engagement"]["id"],
            industry_expertise_required="TECH",
        )

        response = api.create_integrity_assessment(
            acceptance["id"],
            {
                "source_type": "MEDIA_ADVERSE", "severity": "MEDIUM", "score_impact": 12,
                "assessed_on": "2026-11-01T00:00:00Z", "resolved": True,
            },
            fixtures.COMMITTEE_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_ASSESSMENT_DATE_IN_FUTURE, 422)

        after = get_acceptance_data(api, acceptance["id"])
        assert after["integrity_score"] == pytest.approx(100.0)

    def test_same_day_assessment_is_admitted(self, api):
        """PRD §3.2: "The `assessed_on` date is a temporal anchor in its own
        right: an assessment dated later than the logical clock is rejected
        outright".

        Design: Corner/errors/error_future_dated_integrity_assessment_is_rejected
        """
        fixtures.set_clock(api)
        world = fixtures.seed_reference_data(api, legal_name="Ashford Analytics")
        acceptance = fixtures.open_acceptance(
            api, world["client"]["id"], world["engagement"]["id"],
            industry_expertise_required="TECH",
        )

        fixtures.record_integrity(
            api, acceptance["id"], source_type="MEDIA_ADVERSE", severity="MEDIUM",
            score_impact=12, assessed_on=DEFAULT_CLOCK, resolved=True,
        )

        after = get_acceptance_data(api, acceptance["id"])
        assert after["integrity_score"] == pytest.approx(88.0)
