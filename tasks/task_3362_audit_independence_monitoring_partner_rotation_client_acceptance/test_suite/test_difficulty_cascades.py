"""Difficulty claims about chains where one hop causes the next."""

from test_helpers import (
    assert_same_instant,
    fixtures,
    get_assignment_data,
    get_client_data,
    get_engagement_data,
    get_professional_data,
)


class TestAcceptanceRejectionCascade:
    """A committee decision travels through the engagement to the client."""

    def test_rejection_moves_the_evaluation_and_its_engagement_back(self, api):
        """PRD §3.2: "A `REJECT` decision moves the evaluation to its terminal
        `REJECTED` state, stamps `decided_at`, returns the governing engagement
        to `DRAFT`".

        Design: Difficulty/transitive_cascade/acceptance_rejection_cascades_through_engagement_to_client
        """
        world = fixtures.scenario_rejection_cascade(api)
        acceptance_id = world["second_acceptance"]["id"]
        engagement_id = world["second_engagement"]["id"]

        fixtures.decide_acceptance_ok(api, acceptance_id, "REJECT", "continuance risk")

        acceptance = fixtures.get_acceptance_data(api, acceptance_id)
        engagement = get_engagement_data(api, engagement_id)
        assert acceptance["status"] == "REJECTED"
        assert acceptance["decided_at"] is not None
        assert engagement["status"] == "DRAFT"

    def test_client_keeps_its_status_while_a_sibling_engagement_is_active(self, api):
        """PRD §3.2: "returns the client to `PROSPECT` when that client has no
        other engagement outside `DRAFT`".
        PRD §3.2: "An `APPROVE` decision on a submitted evaluation requires the
        clamped combined risk score to be below 70".

        Design: Difficulty/transitive_cascade/acceptance_rejection_cascades_through_engagement_to_client
        """
        world = fixtures.scenario_rejection_cascade(api)
        client_id = world["client"]["id"]

        assert world["client"]["status"] == "ACTIVE"
        assert world["first_engagement"]["status"] == "ACTIVE"

        fixtures.decide_acceptance_ok(
            api, world["second_acceptance"]["id"], "REJECT", "continuance risk"
        )

        client = get_client_data(api, client_id)
        sibling = get_engagement_data(api, world["first_engagement"]["id"])
        # The demotion is conditioned on the sibling engagement, not on the decision.
        assert sibling["status"] == "ACTIVE"
        assert client["status"] == "ACTIVE"


class TestAssignmentEndCascade:
    """Ending an assignment starts a rotation clock and frees the seat."""

    def test_ending_an_assignment_starts_the_rotation_clock(self, api):
        """PRD §3.3: "Ending an assignment is an `EngagementPartner` action
        that stamps `ended_on` from the logical clock, recomputes the
        assignment's rotation tenure so that `time_off_months_required` and
        `eligible_return_on` are populated".
        PRD §3.3: "its `eligible_return_on` is set to `ended_on` plus that many
        months".

        Design: Difficulty/transitive_cascade/assignment_end_cascades_to_professional_time_off_availability
        """
        world = fixtures.scenario_assignment_end_cascade(api)
        fixtures.end_assignment_ok(api, world["assignment"]["id"], world["ep_headers"])

        assignment = get_assignment_data(api, world["assignment"]["id"])
        assert assignment["status"] == "ENDED"
        assert_same_instant(assignment["ended_on"], "2026-09-01T00:00:00Z")
        # A standard-regime lead partner owes twenty-four months off.
        assert assignment["time_off_months_required"] == 24
        assert_same_instant(assignment["eligible_return_on"], "2028-09-01T00:00:00Z")
        assert assignment["rotation_status"] == "IN_TIME_OFF"

    def test_ended_assignment_flips_the_professional_to_in_time_off(self, api):
        """PRD §3.3: "A professional with no `ACTIVE` assignment at all, but
        with at least one `ENDED` assignment whose `eligible_return_on` is still
        later than the logical clock, is `IN_TIME_OFF`."

        Design: Difficulty/transitive_cascade/assignment_end_cascades_to_professional_time_off_availability
        """
        world = fixtures.scenario_assignment_end_cascade(api)
        before = get_professional_data(api, world["professional"]["id"])
        assert before["availability"] == "AVAILABLE"

        fixtures.end_assignment_ok(api, world["assignment"]["id"], world["ep_headers"])

        after = get_professional_data(api, world["professional"]["id"])
        assert after["availability"] == "IN_TIME_OFF"

    def test_ending_an_assignment_clears_the_workload_totals(self, api):
        """PRD §3.3: "Because a `LEAD_PARTNER` or `CONCURRING_PARTNER`
        assignment ended by this action leaves `lead_partner_id` or
        `concurring_partner_id` null until a replacement is staffed".
        PRD §3.3: "`ENDED` assignments contribute nothing."

        Design: Difficulty/transitive_cascade/assignment_end_cascades_to_professional_time_off_availability
        """
        world = fixtures.scenario_assignment_end_cascade(api)
        fixtures.end_assignment_ok(api, world["assignment"]["id"], world["ep_headers"])

        engagement = get_engagement_data(api, world["engagement"]["id"])
        professional = get_professional_data(api, world["professional"]["id"])
        assert engagement["lead_partner_id"] is None
        assert engagement["assigned_workload_points"] == 0
        assert professional["active_workload_points"] == 0
