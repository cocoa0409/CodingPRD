"""Difficulty claims where one resource's state gates another's."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    fixtures,
    get_attestation_data,
    get_client_data,
    get_engagement_data,
    get_threat_data,
    validate_error,
)


class TestActivationDependsOnAcceptance:
    """The engagement leaves ACCEPTANCE_PENDING only when the evaluation is
    decided."""

    def test_engagement_waits_in_acceptance_pending_before_the_decision(self, api):
        """PRD §3.2: "moves the evaluation from `DRAFT` to `SUBMITTED` while
        simultaneously advancing the governing engagement to
        `ACCEPTANCE_PENDING`."
        PRD §3.1: "the risk axis starts at `LOW` with a `combined_risk_score` of
        0 until an acceptance decision supplies a real value."

        Design: Difficulty/cross_entity_state_dependency/engagement_activation_depends_on_acceptance_approval
        """
        world = fixtures.scenario_activation_dependency(api)
        engagement = get_engagement_data(api, world["engagement"]["id"])

        assert world["acceptance"]["status"] == "SUBMITTED"
        assert engagement["status"] == "ACCEPTANCE_PENDING"
        assert engagement["combined_risk_score"] == 0
        assert engagement["risk_tier"] == "LOW"

    def test_approval_copies_the_score_onto_the_engagement_and_activates_the_client(self, api):
        """PRD §3.2: "on success `decided_at` is stamped from the logical clock,
        the governing engagement becomes `ACTIVE` with the evaluation's
        `combined_risk_score` and `risk_tier` copied onto it, and the client
        becomes `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/engagement_activation_depends_on_acceptance_approval
        """
        world = fixtures.scenario_activation_dependency(api)
        fixtures.decide_acceptance_ok(
            api, world["acceptance"]["id"], "APPROVE", "acceptable"
        )

        engagement = get_engagement_data(api, world["engagement"]["id"])
        acceptance = fixtures.get_acceptance_data(api, world["acceptance"]["id"])
        client = get_client_data(api, world["client"]["id"])
        # RETAIL 15 + US 0 + the twenty-point row at full weight.
        assert acceptance["combined_risk_score"] == pytest.approx(35.0)
        assert engagement["status"] == "ACTIVE"
        assert engagement["combined_risk_score"] == pytest.approx(35.0)
        assert client["status"] == "ACTIVE"


class TestMultinationalActivationGate:
    """A pending attestation holds the activation back."""

    def test_pending_attestation_blocks_the_activation(self, api):
        """PRD §3.2: "when the engagement is multinational, no affiliate
        attestation for it may still be `PENDING`, a condition whose violation
        surfaces as `ERR_ATTESTATION_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/multinational_activation_blocked_by_pending_attestation
        """
        world = fixtures.scenario_multinational_attestation(api)

        response = fixtures.decide_acceptance(
            api, world["acceptance"]["id"], "APPROVE", "attempt one"
        )
        validate_error(response, ApiErrorId.ERR_ATTESTATION_INCOMPLETE)

        engagement = get_engagement_data(api, world["engagement"]["id"])
        assert engagement["status"] == "ACCEPTANCE_PENDING"

    def test_attesting_releases_the_gate(self, api):
        """PRD §3.7: "Attesting — the `ATTEST` action — moves a `PENDING`
        attestation to `ATTESTED`, stamps `attested_on` from the logical clock,
        and recomputes the engagement's independence posture."

        Design: Difficulty/cross_entity_state_dependency/multinational_activation_blocked_by_pending_attestation
        """
        world = fixtures.scenario_multinational_attestation(api)
        fixtures.decide_acceptance(api, world["acceptance"]["id"], "APPROVE", "attempt one")

        fixtures.attestation_transition_ok(api, world["attestation"]["id"], "ATTEST")
        attested = get_attestation_data(api, world["attestation"]["id"])
        assert attested["attestation_status"] == "ATTESTED"
        assert attested["attested_on"] is not None

        fixtures.decide_acceptance_ok(api, world["acceptance"]["id"], "APPROVE", "attempt two")
        engagement = get_engagement_data(api, world["engagement"]["id"])
        assert engagement["status"] == "ACTIVE"


class TestCoolingOffStaffingBar:
    """The cooling-off interval is closed at both ends."""

    def test_assignment_starting_exactly_on_the_window_end_is_rejected(self, api):
        """PRD §3.4: "an assignment starting exactly on `effective_on` or
        exactly on `cooling_off_end_on` is inside it. A staffing attempt that
        violates the bar is rejected with `ERR_COOLING_OFF_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/assignment_blocked_by_cooling_off_threat_window
        """
        world = fixtures.scenario_cooling_off(api)
        threat = get_threat_data(api, world["threat"]["id"])
        assert_same_instant(threat["cooling_off_end_on"], "2027-01-01T00:00:00Z")
        assert threat["status"] == "IN_COOLING_OFF"

        # The clock still sits on 2026-12-31, so the window has not closed yet.
        response = fixtures.staff(
            api, world["engagement"]["id"], world["professional"]["id"], "LEAD_PARTNER",
            "2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
            ep_headers=world["ep_headers"],
        )
        validate_error(response, ApiErrorId.ERR_COOLING_OFF_ACTIVE)
        assert fixtures.list_assignments_for(api, world["engagement"]["id"]) == []

    def test_assignment_after_the_window_is_admitted(self, api):
        """PRD §3.4: "The bar lifts on its own: once the logical clock reaches
        `cooling_off_end_on`, the threat recomputes from `IN_COOLING_OFF` to
        `CLEARED` on the next read or mutation".

        Design: Difficulty/cross_entity_state_dependency/assignment_blocked_by_cooling_off_threat_window
        """
        world = fixtures.scenario_cooling_off(api)
        fixtures.set_clock(api, "2027-01-02T00:00:00Z")

        assignment = fixtures.staff_ok(
            api, world["engagement"]["id"], world["professional"]["id"], "LEAD_PARTNER",
            "2027-01-02T00:00:00Z", "2028-01-02T00:00:00Z",
            ep_headers=world["ep_headers"],
        )
        assert assignment["status"] == "ACTIVE"
        assert assignment["role"] == "LEAD_PARTNER"
