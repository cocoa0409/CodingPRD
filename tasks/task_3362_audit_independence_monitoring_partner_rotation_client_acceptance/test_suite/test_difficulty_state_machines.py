"""Difficulty claims about the three cyclic or dual-axis state machines."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    get_acceptance_data,
    get_client_data,
    get_engagement_data,
    get_finding_data,
    validate_error,
)


class TestAcceptanceReturnCycle:
    """A SUBMITTED evaluation can be sent back and resubmitted on the same row."""

    def test_return_decision_sends_both_rows_back_to_draft(self, api):
        """PRD §3.2: "A `RETURN` decision sends the evaluation back to `DRAFT`,
        overwrites `decision_notes` with the return rationale, and returns the
        governing engagement to `DRAFT` with its `risk_tier` reset to `LOW` and
        its `combined_risk_score` reset to 0."

        Design: Difficulty/non_linear_state_machine/acceptance_return_to_draft_then_resubmit_cycle
        """
        world = fixtures.scenario_acceptance_cycle(api)
        acceptance_id = world["acceptance"]["id"]
        engagement_id = world["engagement"]["id"]

        fixtures.submit_acceptance(api, acceptance_id)
        pending = get_engagement_data(api, engagement_id)
        assert pending["status"] == "ACCEPTANCE_PENDING"

        fixtures.decide_acceptance_ok(api, acceptance_id, "RETURN", "evidence incomplete")

        returned = get_acceptance_data(api, acceptance_id)
        engagement = get_engagement_data(api, engagement_id)
        assert returned["status"] == "DRAFT"
        assert engagement["status"] == "DRAFT"
        assert engagement["risk_tier"] == "LOW"
        assert engagement["combined_risk_score"] == 0

    def test_returned_acceptance_can_be_resubmitted_and_approved(self, api):
        """PRD §3.2: "A successful submission recomputes `integrity_score`,
        recomputes `risk_score` under the final variant, re-clamps
        `combined_risk_score`, and moves the evaluation from `DRAFT` to
        `SUBMITTED` while simultaneously advancing the governing engagement to
        `ACCEPTANCE_PENDING`."
        PRD §3.2: "the governing engagement becomes `ACTIVE` with the
        evaluation's `combined_risk_score` and `risk_tier` copied onto it, and
        the client becomes `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/acceptance_return_to_draft_then_resubmit_cycle
        """
        world = fixtures.scenario_acceptance_cycle(api)
        acceptance_id = world["acceptance"]["id"]
        engagement_id = world["engagement"]["id"]
        client_id = world["client"]["id"]

        fixtures.submit_acceptance(api, acceptance_id)
        fixtures.decide_acceptance_ok(api, acceptance_id, "RETURN", "evidence incomplete")

        # The same row is submitted a second time, so DRAFT is reached twice.
        fixtures.submit_acceptance(api, acceptance_id)
        resubmitted = get_acceptance_data(api, acceptance_id)
        pending = get_engagement_data(api, engagement_id)
        assert resubmitted["status"] == "SUBMITTED"
        assert pending["status"] == "ACCEPTANCE_PENDING"

        fixtures.decide_acceptance_ok(api, acceptance_id, "APPROVE", "evidence complete")

        approved = get_acceptance_data(api, acceptance_id)
        engagement = get_engagement_data(api, engagement_id)
        client = get_client_data(api, client_id)
        assert approved["status"] == "APPROVED"
        assert engagement["status"] == "ACTIVE"
        # RETAIL 15 + US 0 + the resolved five-point row at full weight.
        assert engagement["combined_risk_score"] == 20
        assert client["status"] == "ACTIVE"

    def test_decision_on_an_approved_acceptance_is_rejected(self, api):
        """PRD §2.10: "The target resource must be in a state from which the
        requested action has a declared transition, and a resource that is
        already terminal admits none."

        Design: Difficulty/non_linear_state_machine/acceptance_return_to_draft_then_resubmit_cycle
        """
        world = fixtures.scenario_acceptance_cycle(api)
        acceptance_id = world["acceptance"]["id"]

        fixtures.submit_acceptance(api, acceptance_id)
        fixtures.decide_acceptance_ok(api, acceptance_id, "APPROVE", "clean")

        response = fixtures.decide_acceptance(api, acceptance_id, "APPROVE", "again")
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)


class TestFindingRemediationCycle:
    """The remediation loop re-enters REMEDIATION without resetting the budget."""

    def test_finding_walks_remediation_retest_reopened_and_back(self, api):
        """PRD §3.5: "From `REMEDIATION`, the officer submits the finding for
        re-test with the `SUBMIT_FOR_RETEST` action, moving it to `RE_TEST`".
        PRD §3.5: "A `REOPENED` finding may restart remediation through the
        `RESTART_REMEDIATION` action, returning it to `REMEDIATION`".

        Design: Difficulty/non_linear_state_machine/finding_retest_reopen_remediation_cycle
        """
        world = fixtures.scenario_finding_cycle(api)
        finding_id = world["finding"]["id"]

        assert get_finding_data(api, finding_id)["status"] == "OPEN"
        fixtures.finding_transition_ok(api, finding_id, "START_REMEDIATION")
        assert get_finding_data(api, finding_id)["status"] == "REMEDIATION"
        fixtures.finding_transition_ok(api, finding_id, "SUBMIT_FOR_RETEST")
        assert get_finding_data(api, finding_id)["status"] == "RE_TEST"
        fixtures.finding_transition_ok(api, finding_id, "FAIL_RETEST")
        assert get_finding_data(api, finding_id)["status"] == "REOPENED"
        fixtures.finding_transition_ok(api, finding_id, "RESTART_REMEDIATION")
        assert get_finding_data(api, finding_id)["status"] == "REMEDIATION"

    def test_failed_retest_accumulates_attempts_without_reset(self, api):
        """PRD §3.5: "a failing re-test (`FAIL_RETEST`) moves it to `REOPENED`
        and increments `remediation_attempts` by 1."
        PRD §3.5: "A failure also recomputes `remediation_due_on` from the
        logical clock rather than from the original discovery date".

        Design: Difficulty/non_linear_state_machine/finding_retest_reopen_remediation_cycle
        """
        world = fixtures.scenario_finding_cycle(api)
        finding_id = world["finding"]["id"]

        fixtures.finding_transition_ok(api, finding_id, "START_REMEDIATION")
        original_due = get_finding_data(api, finding_id)["remediation_due_on"]
        fixtures.finding_transition_ok(api, finding_id, "SUBMIT_FOR_RETEST")
        fixtures.finding_transition_ok(api, finding_id, "FAIL_RETEST")

        after_failure = get_finding_data(api, finding_id)
        assert after_failure["remediation_attempts"] == 1
        assert after_failure["remediation_due_on"] != original_due

        fixtures.finding_transition_ok(api, finding_id, "RESTART_REMEDIATION")
        after_restart = get_finding_data(api, finding_id)
        assert after_restart["remediation_attempts"] == 1
        assert after_restart["remediation_due_on"] != original_due

    def test_high_finding_keeps_the_engagement_restricted(self, api):
        """PRD §2.6: "If the engagement is not `FROZEN`, its posture is
        `RESTRICTED` when exactly one live `HIGH` finding exists".

        Design: Difficulty/non_linear_state_machine/finding_retest_reopen_remediation_cycle
        """
        world = fixtures.scenario_finding_cycle(api)
        engagement = get_engagement_data(api, world["engagement"]["id"])
        assert engagement["independence_status"] == "RESTRICTED"

        # The posture follows the finding through the loop.
        fixtures.finding_transition_ok(api, world["finding"]["id"], "START_REMEDIATION")
        fixtures.finding_transition_ok(api, world["finding"]["id"], "SUBMIT_FOR_RETEST")
        still_live = get_engagement_data(api, world["engagement"]["id"])
        assert still_live["independence_status"] == "RESTRICTED"


class TestEngagementDualAxes:
    """One row, two independent state axes, one driving the other."""

    def test_critical_finding_freezes_and_suspends_an_active_engagement(self, api):
        """PRD §2.6: "When an engagement that is `ACTIVE` recomputes to
        `FROZEN`, its status is set to `SUSPENDED`".
        PRD §2.6: "The posture is `FROZEN` when any one of these holds: at
        least one live `CRITICAL` finding".

        Design: Difficulty/non_linear_state_machine/engagement_status_and_independence_status_axes_move_independently
        """
        world = fixtures.scenario_engagement_axes(api)
        engagement = get_engagement_data(api, world["engagement"]["id"])

        assert engagement["independence_status"] == "FROZEN"
        assert engagement["status"] == "SUSPENDED"

    def test_closing_the_critical_finding_restores_clear_and_active(self, api):
        """PRD §2.6: "When the recomputed posture leaves `FROZEN` for
        `RESTRICTED` or `CLEAR`, an engagement suspended by that rule returns to
        `ACTIVE` provided no live `CRITICAL` finding remains."

        Design: Difficulty/non_linear_state_machine/engagement_status_and_independence_status_axes_move_independently
        """
        world = fixtures.scenario_engagement_axes(api)
        finding_id = world["finding"]["id"]
        engagement_id = world["engagement"]["id"]

        fixtures.finding_transition_ok(api, finding_id, "START_REMEDIATION")
        fixtures.finding_transition_ok(api, finding_id, "SUBMIT_FOR_RETEST")
        fixtures.finding_transition_ok(api, finding_id, "PASS_RETEST")

        finding = get_finding_data(api, finding_id)
        engagement = get_engagement_data(api, engagement_id)
        assert finding["status"] == "CLOSED"
        assert finding["closed_on"] is not None
        # No lifecycle call was issued: the status followed the posture back.
        assert engagement["independence_status"] == "CLEAR"
        assert engagement["status"] == "ACTIVE"

    def test_the_two_axes_never_swap_their_vocabularies(self, api):
        """PRD §3.1: "Opening an engagement places it on two independent axes
        at once. The lifecycle axis starts at `DRAFT`, and the independence axis
        starts at `CLEAR`".

        Design: Difficulty/non_linear_state_machine/engagement_status_and_independence_status_axes_move_independently
        """
        world = fixtures.scenario_engagement_axes(api)
        engagement = get_engagement_data(api, world["engagement"]["id"])

        lifecycle = {"DRAFT", "ACCEPTANCE_PENDING", "ACTIVE", "SUSPENDED", "CLOSED"}
        posture = {"CLEAR", "RESTRICTED", "FROZEN"}
        assert engagement["status"] in lifecycle
        assert engagement["independence_status"] in posture
        assert engagement["status"] not in posture
        assert engagement["independence_status"] not in lifecycle
