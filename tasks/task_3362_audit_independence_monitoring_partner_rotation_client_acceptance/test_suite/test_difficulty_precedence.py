"""Difficulty claims about which check wins when two could both fail."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    get_threat_data,
    validate_error,
)

#: A well-formed identifier that names no engagement in the deployment.
UNKNOWN_ENGAGEMENT_ID = "3f1c9d47-6b2a-4c8e-9f10-5a7d2e4b8c61"


class TestStateBeatsMaterialInterest:
    """A closed engagement and a material holding on the same request."""

    def test_staffing_a_closed_engagement_reports_the_state_violation(self, api):
        """PRD §2.10: "The first check that fails determines the error the
        caller sees."
        PRD §2.10: "creating a role assignment and raising an independence
        finding each require the target engagement's status to be one of
        `DRAFT`, `ACCEPTANCE_PENDING`, `ACTIVE` or `SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/closed_engagement_state_beats_material_interest_safety
        """
        world = fixtures.scenario_closed_engagement_material_interest(api)
        assert world["engagement"]["status"] == "CLOSED"

        # The lower-priority bar really is live: a direct holding in a public
        # interest entity is material whatever its size.
        threat = get_threat_data(api, world["threat"]["id"])
        assert threat["is_material"] is True
        assert threat["status"] == "DECLARED"

        response = fixtures.staff(
            api,
            world["engagement"]["id"],
            world["professional"]["id"],
            "LEAD_PARTNER",
            "2026-10-01T00:00:00Z",
            "2027-10-01T00:00:00Z",
            expected_version=world["stale_version"],
            ep_headers=world["ep_headers"],
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    def test_material_interest_conflict_fires_on_a_staffable_engagement(self, api):
        """PRD §3.4: "a professional holding a threat of type
        `FINANCIAL_INTEREST` that is material and still in `DECLARED` or
        `IN_COOLING_OFF` status for the engagement's client cannot be assigned
        to that engagement, and the attempt is rejected with
        `ERR_MATERIAL_INTEREST_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/closed_engagement_state_beats_material_interest_safety
        """
        world = fixtures.scenario_material_interest_gate(api)

        response = fixtures.staff(
            api,
            world["engagement"]["id"],
            world["professional"]["id"],
            "LEAD_PARTNER",
            "2026-10-01T00:00:00Z",
            "2027-10-01T00:00:00Z",
            ep_headers=world["ep_headers"],
        )
        validate_error(response, ApiErrorId.ERR_MATERIAL_INTEREST_CONFLICT)


class TestExistenceBeatsConcurrency:
    """A dangling foreign key alongside a stale snapshot."""

    def test_dangling_engagement_id_reports_the_existence_failure(self, api):
        """PRD §2.10: "Every foreign key supplied in the body — `client_id`,
        `engagement_id`, `professional_id`, `affiliate_id`, `acceptance_id` or
        `reviewer_id` — must resolve to an existing row."

        Design: Difficulty/priority_pair_validation_conflict/unknown_engagement_existence_beats_overlap_temporal
        """
        world = fixtures.scenario_dangling_engagement(api)
        assert world["current_version"] != world["stale_version"]

        response = fixtures.staff(
            api,
            UNKNOWN_ENGAGEMENT_ID,
            world["second_professional"]["id"],
            "EQ_REVIEWER",
            "2026-06-15T00:00:00Z",
            "2026-12-15T00:00:00Z",
            expected_version=world["stale_version"],
            ep_headers=world["ep_headers"],
        )
        validate_error(response, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND)

    def test_dangling_engagement_leaves_no_assignment_behind(self, api):
        """PRD §2.11: "foreign keys supplied in a payload — `client_id`,
        `engagement_id`, `professional_id`, `affiliate_id`, `acceptance_id` or
        `reviewer_id` — are resolved during the cascade of §2.10 and, when
        dangling, produce `ERR_REFERENCED_ENTITY_NOT_FOUND` with HTTP 404."

        Design: Difficulty/priority_pair_validation_conflict/unknown_engagement_existence_beats_overlap_temporal
        """
        world = fixtures.scenario_dangling_engagement(api)

        fixtures.staff(
            api,
            UNKNOWN_ENGAGEMENT_ID,
            world["second_professional"]["id"],
            "EQ_REVIEWER",
            "2026-06-15T00:00:00Z",
            "2026-12-15T00:00:00Z",
            expected_version=world["stale_version"],
            ep_headers=world["ep_headers"],
        )

        remaining = fixtures.list_assignments_for(api, world["engagement"]["id"])
        assert [row for row in remaining if row["professional_id"] == world["second_professional"]["id"]] == []
