"""Appeals: two-level review cycle, counter invariants, OCC, duplicate and
window rules."""
import pytest

from test_helpers import (
    make_auditor_headers,
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    create_appeal_payload,
    create_engagement_payload,
    create_evidence_payload,
    create_milestone_payload,
    create_mitigation_plan_payload,
    create_penalty_payload,
    create_registration_payload,
    create_violation_payload,
    create_violation,
    get_success_data,
    make_officer_headers,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

AUD = TEST_USERS["auditor_headers"]
RER = TEST_USERS["regional_reviewer_headers"]
FED = TEST_USERS["federal_reviewer_headers"]
RC = TEST_USERS["registration_coordinator_headers"]


def _register(name="GenCo App"):
    return get_success_data(api_client.create_registration(
        create_registration_payload(legal_name=name, registration_functions=["GO"]), RC))


def _open_violation(entity_id, **overrides):
    # Route through the PRD-legal fixture so AUDIT/SPOT_CHECK sources carry a
    # valid source reference (PRD §3.4 source integrity).
    return create_violation(entity_id, **overrides)


class TestAppealTwoLevelCycle:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register()
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"], standard_ids=["STD-GO-001"]), AUD))
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        a1 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"]), make_officer_headers(e1["id"])))
        get_success_data(api_client.accept_evidence(a1["id"], AUD))
        get_success_data(api_client.complete_engagement(eng["id"], AUD))
        v = get_success_data(api_client.create_violation(
            create_violation_payload(
                e1["id"], source_type="AUDIT",
                violation_start="2026-01-10T00:00:00Z",
                violation_end="2026-01-11T00:00:00Z",
                violation_risk_factor="MODERATE", severity_level="MODERATE",
                source_engagement_id=eng["id"]), AUD))
        appeal = get_success_data(api_client.create_appeal(
            v["id"], create_appeal_payload(v["version"]), make_officer_headers(e1["id"])))
        return e1, v, appeal

    def test_regional_deny_returns_violation_to_open(self):
        """PRD §3.9: "A denial restores the violation to wherever its mitigation
        posture dictates: back to OPEN when no mitigation plan exists for the
        violation."

        Design: Difficulty/non_linear_state_machine/appeal_two_level_cycle
        """
        e1, v, appeal = self._setup()
        get_success_data(api_client.deny_appeal(appeal["id"], RER))
        mid = validate_success(api_client.get_violation(v["id"], RER))
        assert mid["status"] == "OPEN"

    def test_federal_grant_closes_violation_with_final_penalty(self):
        """PRD §3.9: "A grant at either review level — regional or federal —
        closes the case: the violation moves from APPEALED to CLOSED, its
        final_penalty is recomputed per §3.4 ... the violation's penalty row is
        created or updated with amount equal to the recomputed final penalty."

        Design: Difficulty/non_linear_state_machine/appeal_two_level_cycle
        """
        e1, v, appeal = self._setup()
        get_success_data(api_client.deny_appeal(appeal["id"], RER))
        get_success_data(api_client.request_federal_review(appeal["id"], make_officer_headers(e1["id"])))
        granted = validate_success(api_client.grant_appeal(appeal["id"], FED))
        assert granted["status"] == "APPEAL_GRANTED"
        final = validate_success(api_client.get_violation(v["id"], FED))
        assert final["status"] == "CLOSED"
        assert final["final_penalty"] is not None


class TestAppealCounterRoundTripInvariant:
    def test_counter_round_trip(self):
        """PRD §3.9: "each denial path decrements the entity's
        unresolved_appeal_count by one — unless the denial is subsequently
        re-opened for federal review, in which case the federal-review request
        re-increments it, keeping the count aligned with appeals still alive."

        Design: Difficulty/compensating_invariant/appeal_counter_round_trip_invariant
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("GenCo AppCnt")
        v = _open_violation(e1["id"])
        appeal = get_success_data(api_client.create_appeal(
            v["id"], create_appeal_payload(v["version"]), make_officer_headers(e1["id"])))
        cnt1 = validate_success(api_client.get_registration(e1["id"], AUD))
        assert cnt1["unresolved_appeal_count"] == 1
        get_success_data(api_client.deny_appeal(appeal["id"], RER))
        cnt2 = validate_success(api_client.get_registration(e1["id"], AUD))
        assert cnt2["unresolved_appeal_count"] == 0
        get_success_data(api_client.request_federal_review(appeal["id"], make_officer_headers(e1["id"])))
        cnt3 = validate_success(api_client.get_registration(e1["id"], AUD))
        assert cnt3["unresolved_appeal_count"] == 1
        get_success_data(api_client.deny_appeal(appeal["id"], FED))
        cnt4 = validate_success(api_client.get_registration(e1["id"], AUD))
        assert cnt4["unresolved_appeal_count"] == 0
        v_final = validate_success(api_client.get_violation(v["id"], AUD))
        assert v_final["status"] == "OPEN"

    def test_counter_never_negative_after_full_round_trip(self):
        """PRD §3.1: "unresolved_appeal_count counts the entity's appeals
        sitting in APPEAL_PENDING_REVIEW" — after deny -> federal request ->
        federal deny, the count must be exactly 0, not negative.

        Design: Difficulty/compensating_invariant/appeal_counter_round_trip_invariant
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("GenCo AppCnt2")
        v = _open_violation(e1["id"])
        appeal = get_success_data(api_client.create_appeal(
            v["id"], create_appeal_payload(v["version"]), make_officer_headers(e1["id"])))
        get_success_data(api_client.deny_appeal(appeal["id"], RER))
        get_success_data(api_client.request_federal_review(appeal["id"], make_officer_headers(e1["id"])))
        get_success_data(api_client.deny_appeal(appeal["id"], FED))
        cnt = validate_success(api_client.get_registration(e1["id"], AUD))
        assert cnt["unresolved_appeal_count"] == 0


class TestAppealDeniedWithoutPlanReturnsViolationToOpen:
    def test_denied_appeal_restores_open_and_keeps_penalty(self):
        """PRD §3.9: "A denial restores the violation to wherever its mitigation
        posture dictates: back to OPEN when no mitigation plan exists for the
        violation." PRD §3.4: "A violation is priced as proposed_penalty while
        it sits in OPEN or APPEALED" — the fixture's SPOT_CHECK source
        engagement has no evidence, so its coverage_fraction is 0.0 < 0.8 and
        the gap-aggravation step of §3.4 applies: a MODERATE/HIGH spot-check
        violation is 5000 * 1.5 * 1.25 = 9375.00 both before and after the
        appeal round trip.

        Design: Corner/state_machines/appeal_denied_without_plan_returns_violation_to_open
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Deny Co")
        v = _open_violation(e1["id"], violation_risk_factor="MODERATE",
                            severity_level="HIGH")
        assert v["proposed_penalty"] == pytest.approx(9375.00, abs=0.005)
        appeal = get_success_data(api_client.create_appeal(
            v["id"], create_appeal_payload(v["version"]), make_officer_headers(e1["id"])))
        get_success_data(api_client.deny_appeal(appeal["id"], RER))
        after = validate_success(api_client.get_violation(v["id"], AUD))
        assert after["status"] == "OPEN"
        assert after["proposed_penalty"] == pytest.approx(9375.00, abs=0.005)
        ent = validate_success(api_client.get_registration(e1["id"], AUD))
        assert ent["open_violation_count"] == 1

    def test_denied_appeal_decrements_unresolved_appeal_count(self):
        """PRD §3.9: "each denial path decrements the entity's
        unresolved_appeal_count by one."

        Design: Corner/state_machines/appeal_denied_without_plan_returns_violation_to_open
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Deny2 Co")
        v = _open_violation(e1["id"], violation_risk_factor="MODERATE",
                            severity_level="HIGH")
        appeal = get_success_data(api_client.create_appeal(
            v["id"], create_appeal_payload(v["version"]), make_officer_headers(e1["id"])))
        before = validate_success(api_client.get_registration(e1["id"], AUD))
        assert before["unresolved_appeal_count"] == 1
        get_success_data(api_client.deny_appeal(appeal["id"], RER))
        after = validate_success(api_client.get_registration(e1["id"], AUD))
        assert after["unresolved_appeal_count"] == 0


class TestSecondAppealWhileActiveRejected:
    def test_second_appeal_rejected_while_pending(self):
        """PRD §3.9: "Only one appeal may be live at a time: if the violation
        already has an appeal in APPEAL_PENDING_REVIEW or
        FEDERAL_REVIEW_REQUESTED, a further filing is rejected with
        ERR_DUPLICATE_ACTIVE_APPEAL." A second filing while the first appeal is
        pending is rejected — PRD does not order this rule against §3.9's
        appealable-state rule ("from any other violation state the filing fails
        as ERR_VIOLATION_STATE"; filing moved the violation to APPEALED), so
        either error_id satisfies the PRD.

        Design: Corner/state_machines/second_appeal_while_active_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Dup Co")
        v = _open_violation(e1["id"])
        get_success_data(api_client.create_appeal(
            v["id"], create_appeal_payload(v["version"]), make_officer_headers(e1["id"])))
        v2 = validate_success(api_client.get_violation(v["id"], AUD))
        resp = api_client.create_appeal(
            v["id"], create_appeal_payload(v2["version"], grounds="g2"),
            make_officer_headers(e1["id"]))
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_DUPLICATE_ACTIVE_APPEAL,
            ApiErrorId.ERR_VIOLATION_STATE,
        ])

    def test_new_appeal_allowed_after_first_resolved(self):
        """PRD §3.9: "Only one appeal may be live at a time" — once the first
        appeal reaches a level-final state (APPEAL_DENIED), a subsequent filing
        is not a duplicate-active-appeal violation.

        Design: Corner/state_machines/second_appeal_while_active_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Dup2 Co")
        v = _open_violation(e1["id"])
        ap1 = get_success_data(api_client.create_appeal(
            v["id"], create_appeal_payload(v["version"]), make_officer_headers(e1["id"])))
        get_success_data(api_client.deny_appeal(ap1["id"], RER))
        v2 = validate_success(api_client.get_violation(v["id"], AUD))
        resp = api_client.create_appeal(
            v["id"], create_appeal_payload(v2["version"], grounds="second"),
            make_officer_headers(e1["id"]))
        validate_success(resp, expected_status=201)


class TestFederalReviewOutsideWindowRejected:
    # test_federal_review_request_too_late was deleted: it asserted a numeric
    # federal-review-window boundary (16 days past denial must be rejected),
    # but PRD §3.9 names FEDERAL_REVIEW_WINDOW_DAYS only symbolically — no
    # numeric length appears verbatim, so the boundary is not uniquely
    # derivable from the PRD.

    def test_federal_review_request_within_window(self):
        """PRD §3.9: "Within the federal review window ... the entity's officer
        requests federal review, moving the appeal from APPEAL_DENIED to
        FEDERAL_REVIEW_REQUESTED and adding one to unresolved_appeal_count."

        Design: Corner/state_machines/federal_review_outside_window_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("InTimeFed Co")
        v = _open_violation(e1["id"])
        appeal = get_success_data(api_client.create_appeal(
            v["id"], create_appeal_payload(v["version"]), make_officer_headers(e1["id"])))
        get_success_data(api_client.deny_appeal(appeal["id"], RER))
        resp = api_client.request_federal_review(appeal["id"], make_officer_headers(e1["id"]))
        data = validate_success(resp)
        assert data["status"] == "FEDERAL_REVIEW_REQUESTED"


class TestOccStaleVersion:
    def test_stale_version_on_second_plan_create(self):
        """PRD §2.7: "Two write endpoints require the caller to attest the
        version of the parent Violation they last observed, by including
        expected_violation_version as a non-optional field of the request body:
        submitting a mitigation plan for a violation, and filing an appeal
        against a violation. If the supplied value does not match the
        violation's current version, the request is rejected with
        ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/endpoints/occ_stale_version_on_mitigation_plan_create
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Occ Co")
        v = _open_violation(e1["id"])
        officer = make_officer_headers(e1["id"])
        get_success_data(api_client.create_mitigation_plan(
            v["id"], create_mitigation_plan_payload(v["version"], description="first"),
            officer))
        resp = api_client.create_mitigation_plan(
            v["id"], create_mitigation_plan_payload(v["version"], description="stale second"),
            officer)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_version_on_second_appeal_file(self):
        """PRD §2.7: "If the supplied value does not match the violation's
        current version, the request is rejected with ERR_STALE_VERSION (HTTP
        412)."

        Design: Corner/endpoints/occ_stale_version_on_appeal_file
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("OccApp Co")
        v = _open_violation(e1["id"])
        officer = make_officer_headers(e1["id"])
        ap1 = get_success_data(api_client.create_appeal(
            v["id"], create_appeal_payload(v["version"], grounds="first"), officer))
        get_success_data(api_client.deny_appeal(ap1["id"], RER))
        # Version has advanced since creation; reuse the stale observed version.
        resp = api_client.create_appeal(
            v["id"], create_appeal_payload(v["version"], grounds="stale second"), officer)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestAppealAfterWindowRejected:
    # test_appeal_after_thirty_days_rejected was deleted: it asserted a numeric
    # appeal-window boundary (filing 31 days after OPEN must be rejected), but
    # PRD §3.9 names the appeal-window length only symbolically — no numeric
    # length appears verbatim, so the boundary is not uniquely derivable from
    # the PRD (a faithful implementer choosing a 45-day window would see the
    # filing succeed). Same verdict as the federal-review-window deletion below.

    def test_appeal_immediately_after_open_accepted(self):
        """PRD §3.9: "A successful filing creates the Appeal in
        APPEAL_PENDING_REVIEW, stamps submitted_at, moves the violation to
        APPEALED, bumps the violation's version, and adds one to the entity's
        unresolved_appeal_count."

        Design: Corner/validations/appeal_after_window_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("OnTimeApp Co")
        v = _open_violation(e1["id"])
        resp = api_client.create_appeal(
            v["id"], create_appeal_payload(v["version"]), make_officer_headers(e1["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "APPEAL_PENDING_REVIEW"
        v2 = validate_success(api_client.get_violation(v["id"], AUD))
        assert v2["status"] == "APPEALED"


class TestEntityRestrictedBeatsStateOnAppeal:
    def test_restricted_entity_appeal_rejected_with_entity_restricted(self):
        """PRD §2.5: "Fourth, the registered-entity posture gate runs:
        entity-initiated mutation endpoints — filing a self-report, submitting a
        mitigation plan, filing an appeal, logging a self-log entry, or creating
        an access grant — are rejected with ERR_ENTITY_RESTRICTED when the
        acting entity's compliance_status is RESTRICTED." PRD §2.8: "While an
        entity is RESTRICTED, the entity-initiated mutations listed in §2.5 are
        blocked with ERR_ENTITY_RESTRICTED."

        Design: Difficulty/priority_pair_validation_conflict/entity_restricted_beats_state_on_appeal
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("GenCo Prio")
        officer = make_officer_headers(e1["id"])
        # V1 fully mitigated and closed.
        v1 = _open_violation(e1["id"], violation_start="2026-01-01T00:00:00Z",
                             violation_end="2026-01-02T00:00:00Z")
        plan = get_success_data(api_client.create_mitigation_plan(
            v1["id"], create_mitigation_plan_payload(v1["version"]), officer))
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        m = get_success_data(api_client.create_milestone(
            plan["id"], create_milestone_payload(title="m",
                                                 due_date="2026-10-01T00:00:00Z"), officer))
        get_success_data(api_client.complete_milestone(m["id"], officer))
        get_success_data(api_client.complete_mitigation(v1["id"], officer))
        get_success_data(api_client.verify_plan(plan["id"], AUD))
        # V2 with confirmed penalty; advance 31 days past issuance so the entity
        # becomes RESTRICTED.
        v2 = _open_violation(e1["id"], violation_start="2026-02-01T00:00:00Z",
                             violation_end="2026-02-02T00:00:00Z",
                             violation_risk_factor="MODERATE", severity_level="MODERATE")
        pen = get_success_data(api_client.create_penalty(create_penalty_payload(v2["id"]), AUD))
        get_success_data(api_client.confirm_penalty(pen["id"], make_auditor_headers("test-auditor-2")))
        advance_clock(2678400)
        ent = validate_success(api_client.get_registration(e1["id"], AUD))
        assert ent["compliance_status"] == "RESTRICTED"
        v1_now = validate_success(api_client.get_violation(v1["id"], AUD))
        assert v1_now["status"] == "CLOSED"
        resp = api_client.create_appeal(
            v1["id"], create_appeal_payload(v1_now["version"], grounds="too late anyway"),
            officer)
        validate_error(resp, ApiErrorId.ERR_ENTITY_RESTRICTED)

    def test_restricted_entity_mitigation_plan_rejected_too(self):
        """PRD §2.8: "While an entity is RESTRICTED, the entity-initiated
        mutations listed in §2.5 are blocked with ERR_ENTITY_RESTRICTED."

        Design: Difficulty/priority_pair_validation_conflict/entity_restricted_beats_state_on_appeal
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("GenCo Prio2")
        officer = make_officer_headers(e1["id"])
        v2 = _open_violation(e1["id"], violation_start="2026-02-01T00:00:00Z",
                             violation_end="2026-02-02T00:00:00Z",
                             violation_risk_factor="MODERATE", severity_level="MODERATE")
        pen = get_success_data(api_client.create_penalty(create_penalty_payload(v2["id"]), AUD))
        get_success_data(api_client.confirm_penalty(pen["id"], make_auditor_headers("test-auditor-2")))
        # A second open violation whose plan submission will be gated.
        v3 = _open_violation(e1["id"], violation_start="2026-03-01T00:00:00Z",
                             violation_end="2026-03-02T00:00:00Z")
        advance_clock(2678400)
        v3_now = validate_success(api_client.get_violation(v3["id"], AUD))
        resp = api_client.create_mitigation_plan(
            v3["id"], create_mitigation_plan_payload(v3_now["version"]), officer)
        validate_error(resp, ApiErrorId.ERR_ENTITY_RESTRICTED)


class TestSecondMitigationPlanRejected:
    def test_denied_appeal_with_rejected_plan_returns_mitigation_submitted(self):
        """PRD §3.9: "A denial restores the violation to wherever its mitigation
        posture dictates: ... back to MITIGATION_SUBMITTED when the plan is
        SUBMITTED or REJECTED."

        Design: Corner/validations/second_mitigation_plan_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Replan Co")
        officer = make_officer_headers(e1["id"])
        v = _open_violation(e1["id"])
        plan = get_success_data(api_client.create_mitigation_plan(
            v["id"], create_mitigation_plan_payload(v["version"]), officer))
        get_success_data(api_client.reject_plan(plan["id"], AUD))
        v2 = validate_success(api_client.get_violation(v["id"], AUD))
        ap = get_success_data(api_client.create_appeal(
            v["id"], create_appeal_payload(v2["version"]), officer))
        get_success_data(api_client.deny_appeal(ap["id"], RER))
        after = validate_success(api_client.get_violation(v["id"], AUD))
        assert after["status"] == "MITIGATION_SUBMITTED"

    def test_plan_submission_after_denial_back_in_submitted_state_rejected(self):
        """PRD §3.5: "the violation must actually be in OPEN (a plan submission
        against a violation in any other state fails as ERR_VIOLATION_STATE)" —
        a violation restored to MITIGATION_SUBMITTED by a denied appeal cannot
        accept a fresh plan submission.

        Design: Corner/validations/second_mitigation_plan_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Replan2 Co")
        officer = make_officer_headers(e1["id"])
        v = _open_violation(e1["id"])
        plan = get_success_data(api_client.create_mitigation_plan(
            v["id"], create_mitigation_plan_payload(v["version"]), officer))
        get_success_data(api_client.reject_plan(plan["id"], AUD))
        v2 = validate_success(api_client.get_violation(v["id"], AUD))
        ap = get_success_data(api_client.create_appeal(
            v["id"], create_appeal_payload(v2["version"]), officer))
        get_success_data(api_client.deny_appeal(ap["id"], RER))
        v3 = validate_success(api_client.get_violation(v["id"], AUD))
        resp = api_client.create_mitigation_plan(
            v["id"], create_mitigation_plan_payload(v3["version"]), officer)
        validate_error(resp, ApiErrorId.ERR_VIOLATION_STATE)
