"""Breadth claims about terminal states, side effects and preconditions."""

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    fixtures,
    get_attestation_data,
    get_client_data,
    get_engagement_data,
    get_finding_data,
    get_professional_data,
    get_review_data,
    validate_error,
)


class TestClosedFindingLockdown:
    """A finding that has reached CLOSED admits no further action."""

    def test_every_action_on_a_closed_finding_is_rejected(self, api):
        """PRD §2.10: "The target resource must be in a state from which the
        requested action has a declared transition, and a resource that is
        already terminal admits none."

        Design: Corner/state_machines/finding_closed_is_terminal_for_every_action
        """
        world = fixtures.scenario_closed_finding(api)
        finding_id = world["finding"]["id"]
        assert world["finding"]["status"] == "CLOSED"
        closed_on = world["finding"]["closed_on"]

        for action in ("START_REMEDIATION", "PASS_RETEST"):
            response = fixtures.finding_transition(api, finding_id, action)
            validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

        stored = get_finding_data(api, finding_id)
        assert stored["status"] == "CLOSED"
        assert_same_instant(stored["closed_on"], closed_on)

    def test_a_closed_finding_leaves_the_engagement_clear(self, api):
        """PRD §3.5: "Findings in `OPEN`, `REMEDIATION`, `RE_TEST` and
        `REOPENED` are the "live" statuses used throughout this document: they
        keep the engagement's posture elevated"."

        Design: Corner/state_machines/finding_closed_is_terminal_for_every_action
        """
        world = fixtures.scenario_closed_finding(api)

        fixtures.finding_transition(api, world["finding"]["id"], "START_REMEDIATION")

        engagement = get_engagement_data(api, world["engagement"]["id"])
        assert engagement["independence_status"] == "CLEAR"


class TestQualityReviewTerminalState:
    """START and FAIL are legal only from the states that declare them."""

    def test_start_on_a_passed_review_is_rejected(self, api):
        """PRD §3.8: "The review lifecycle begins with the `START` action, which
        moves a `SCHEDULED` review to `IN_PROGRESS`."
        PRD §3.8: "moves the review to its terminal `PASSED` state".

        Design: Corner/state_machines/quality_review_invalid_state_on_terminal_row
        """
        world = fixtures.scenario_passed_review(api)
        assert world["review"]["status"] == "PASSED"

        response = fixtures.review_transition(
            api, world["review"]["id"], "START", world["reviewer"]["id"]
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        stored = get_review_data(api, world["review"]["id"])
        assert stored["status"] == "PASSED"

    def test_fail_on_a_passed_review_is_rejected(self, api):
        """PRD §3.8: "The `FAIL` action requires `deficiency_count` to be
        greater than 0 and moves the review to `DEFICIENT`".

        Design: Corner/state_machines/quality_review_invalid_state_on_terminal_row
        """
        world = fixtures.scenario_passed_review(api)

        response = fixtures.review_transition(
            api, world["review"]["id"], "FAIL", world["reviewer"]["id"]
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        stored = get_review_data(api, world["review"]["id"])
        engagement = get_engagement_data(api, world["engagement"]["id"])
        assert stored["status"] == "PASSED"
        assert engagement["quality_review_required"] is False


class TestEngagementCloseCascade:
    """Closing an engagement really ends the people sitting on it."""

    def test_close_ends_every_active_assignment(self, api):
        """PRD §3.9: "In both cases, every `ACTIVE` assignment on the
        engagement is ended in the same operation, each with its `ended_on`
        stamped from the logical clock".

        Design: Corner/state_machines/engagement_close_ends_every_active_assignment
        """
        world = fixtures.scenario_active_staffed_engagement(api)
        engagement_id = world["engagement"]["id"]

        fixtures.engagement_transition_ok(api, engagement_id, "CLOSE", world["ep_headers"])

        engagement = get_engagement_data(api, engagement_id)
        assert engagement["status"] == "CLOSED"
        assert engagement["assigned_workload_points"] == 0
        assert engagement["lead_partner_id"] is None
        for key in ("lead_assignment", "manager_assignment"):
            stored = fixtures.get_assignment_data(api, world[key]["id"])
            assert stored["status"] == "ENDED"
            assert_same_instant(stored["ended_on"], "2026-09-01T00:00:00Z")

    def test_close_recomputes_the_professional_and_terminates_the_client(self, api):
        """PRD §3.9: "each affected professional's `active_workload_points` and
        availability are recomputed."
        PRD §3.9: "When the closed engagement was the client's last engagement
        that is not itself `CLOSED`, the client moves to its terminal
        `TERMINATED` state".

        Design: Corner/state_machines/engagement_close_ends_every_active_assignment
        """
        world = fixtures.scenario_active_staffed_engagement(api)

        fixtures.engagement_transition_ok(
            api, world["engagement"]["id"], "CLOSE", world["ep_headers"]
        )

        lead = get_professional_data(api, world["lead"]["id"])
        client = get_client_data(api, world["client"]["id"])
        assert lead["active_workload_points"] == 0
        assert client["status"] == "TERMINATED"


class TestAttestationWaivePrecondition:
    """Waiving is available only to an alliance firm or a domestic engagement."""

    def test_member_firm_cannot_waive_on_a_multinational_engagement(self, api):
        """PRD §3.7: "Waiving — the `WAIVE` action — moves a `PENDING`
        attestation to `WAIVED` and is available only in two situations: the
        attesting firm is an `ALLIANCE`-tier member, or the engagement is not
        multinational at all".

        Design: Corner/state_machines/attestation_waive_cannot_apply_to_member_firm_on_multinational
        """
        world = fixtures.scenario_attestation_waive(api)

        response = fixtures.attestation_transition(
            api, world["member_attestation"]["id"], "WAIVE"
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        stored = get_attestation_data(api, world["member_attestation"]["id"])
        assert stored["attestation_status"] == "PENDING"
        assert stored["attested_on"] is None

    def test_alliance_firm_may_waive_on_the_same_engagement(self, api):
        """PRD §3.7: "an attestation is never waivable for a correspondent or
        member firm on a genuinely multinational engagement."
        PRD §3.7: "Waiving also stamps `attested_on` and recomputes the
        engagement's posture."

        Design: Corner/state_machines/attestation_waive_cannot_apply_to_member_firm_on_multinational
        """
        world = fixtures.scenario_attestation_waive(api)

        fixtures.attestation_transition_ok(api, world["alliance_attestation"]["id"], "WAIVE")

        stored = get_attestation_data(api, world["alliance_attestation"]["id"])
        assert stored["attestation_status"] == "WAIVED"
        assert stored["attested_on"] is not None
