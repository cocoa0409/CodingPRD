"""Mitigation plans, milestones, and the verify cascade."""
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    create_milestone_payload,
    create_mitigation_plan_payload,
    create_registration_payload,
    create_violation,
    create_violation_payload,
    get_success_data,
    make_officer_headers,
    set_clock,
    validate_error,
    validate_success,
    ApiErrorId,
)

AUD = TEST_USERS["auditor_headers"]
RC = TEST_USERS["registration_coordinator_headers"]


def _register(name="GenCo Cyc"):
    return get_success_data(api_client.create_registration(
        create_registration_payload(legal_name=name, registration_functions=["GO"]), RC))


def _open_violation(entity_id, **overrides):
    # Route through the PRD-legal fixture so AUDIT/SPOT_CHECK sources carry a
    # valid source reference (PRD §3.4 source integrity).
    return create_violation(entity_id, **overrides)


def _submit_plan(entity_id, violation):
    return get_success_data(api_client.create_mitigation_plan(
        violation["id"], create_mitigation_plan_payload(violation["version"]),
        make_officer_headers(entity_id)))


class TestMitigationPlanResubmissionCycle:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register()
        v = _open_violation(e1["id"])
        plan = _submit_plan(e1["id"], v)
        return e1, v, plan

    def test_submit_reject_resubmit_approve_cycle(self):
        """PRD §3.5: "Rejection moves the plan to REJECTED and leaves the
        violation where it is. ... the plan itself returns to REJECTED, from
        which the entity may resubmit it back to SUBMITTED, optionally revising
        the description."

        Design: Difficulty/non_linear_state_machine/mitigation_plan_resubmission_cycle
        """
        e1, v, plan = self._setup()
        officer = make_officer_headers(e1["id"])
        get_success_data(api_client.reject_plan(plan["id"], AUD))
        get_success_data(api_client.resubmit_plan(plan["id"], officer, payload={"description": "v2"}))
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        get_success_data(api_client.reject_plan(plan["id"], AUD))
        get_success_data(api_client.resubmit_plan(plan["id"], officer, payload={"description": "v3"}))
        plan2 = validate_success(api_client.approve_plan(plan["id"], AUD))
        assert plan2["status"] == "APPROVED"

    def test_violation_tracks_plan_approval_state(self):
        """PRD §3.5: "Approval moves the plan to APPROVED and, as a cascade,
        moves the violation from MITIGATION_SUBMITTED to MITIGATION_IN_PROGRESS.
        ... a post-approval rejection keeps the violation in
        MITIGATION_IN_PROGRESS while the plan itself returns to REJECTED."

        Design: Difficulty/non_linear_state_machine/mitigation_plan_resubmission_cycle
        """
        e1, v, plan = self._setup()
        officer = make_officer_headers(e1["id"])
        get_success_data(api_client.reject_plan(plan["id"], AUD))
        get_success_data(api_client.resubmit_plan(plan["id"], officer))
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        get_success_data(api_client.reject_plan(plan["id"], AUD))
        v_mid = validate_success(api_client.get_violation(v["id"], AUD))
        assert v_mid["status"] == "MITIGATION_IN_PROGRESS"
        get_success_data(api_client.resubmit_plan(plan["id"], officer))
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        v_final = validate_success(api_client.get_violation(v["id"], AUD))
        assert v_final["status"] == "MITIGATION_IN_PROGRESS"


class TestVerifyCascadeFourHops:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("GenCo Cascade")
        # Completed audit engagement with zero coverage (gap aggravation applies).
        eng = get_success_data(api_client.create_engagement(
            {"entity_id": e1["id"], "engagement_type": "AUDIT",
             "standard_ids": ["STD-GO-001"],
             "period_start": "2026-01-01T00:00:00Z",
             "period_end": "2026-01-31T00:00:00Z"}, AUD))
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        get_success_data(api_client.complete_engagement(eng["id"], AUD))
        v = _open_violation(e1["id"], source_type="AUDIT",
                            violation_start="2025-01-01T00:00:00Z",
                            violation_end="2025-01-02T00:00:00Z",
                            violation_risk_factor="MODERATE", severity_level="SEVERE",
                            source_engagement_id=eng["id"])
        plan = _submit_plan(e1["id"], v)
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        officer = make_officer_headers(e1["id"])
        m = get_success_data(api_client.create_milestone(
            plan["id"], create_milestone_payload(title="m1",
                                                 due_date="2026-10-01T00:00:00Z"), officer))
        get_success_data(api_client.complete_milestone(m["id"], officer))
        get_success_data(api_client.complete_mitigation(v["id"], officer))
        return e1, v, plan

    def test_verify_closes_violation_and_computes_final_penalty(self):
        """PRD §3.5: "Verification moves the plan to VERIFIED and cascades the
        violation from MITIGATION_COMPLETE to CLOSED, which recomputes the
        violation's final_penalty per §3.4, decrements the entity's
        open_violation_count by one, and upserts the violation's Penalty row so
        its amount equals the recomputed final penalty."

        Design: Difficulty/transitive_cascade/verify_cascade_four_hops
        """
        e1, v, plan = self._setup()
        get_success_data(api_client.verify_plan(plan["id"], AUD))
        closed = validate_success(api_client.get_violation(v["id"], AUD))
        # Stale (violation ended 2026-01-02, closure 2026-09-01 > 365 days):
        # base 5000*0.9=4500, factor 2.0 * 1.25 (coverage 0.0 < 0.8) = 2.5 => 11250.00
        assert closed["status"] == "CLOSED"
        assert closed["final_penalty"] == pytest.approx(11250.00, abs=0.005)

    def test_verify_decrements_open_count_and_upserts_penalty(self):
        """PRD §3.5: "decrements the entity's open_violation_count by one, and
        upserts the violation's Penalty row so its amount equals the recomputed
        final penalty."

        Design: Difficulty/transitive_cascade/verify_cascade_four_hops
        """
        e1, v, plan = self._setup()
        before = validate_success(api_client.get_registration(e1["id"], AUD))
        assert before["open_violation_count"] == 1
        get_success_data(api_client.verify_plan(plan["id"], AUD))
        after = validate_success(api_client.get_registration(e1["id"], AUD))
        assert after["open_violation_count"] == 0
        from test_helpers import validate_paginated
        rows, meta = validate_paginated(api_client.list_penalties(
            AUD, params={"violation_id": v["id"]}))
        assert len(rows) == 1
        assert rows[0]["amount"] == pytest.approx(11250.00, abs=0.005)


class TestMilestoneMissedThenLateCompletion:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Late Co")
        v = _open_violation(e1["id"])
        plan = _submit_plan(e1["id"], v)
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        m = get_success_data(api_client.create_milestone(
            plan["id"], create_milestone_payload(title="m",
                                                 due_date="2026-09-10T00:00:00Z"),
            make_officer_headers(e1["id"])))
        return e1, v, plan, m

    def test_clock_sweep_marks_overdue_milestone_missed(self):
        """PRD §3.5: "The clock-advance sweep plays the other side of this
        lifecycle: any milestone still PENDING whose due_date has fallen behind
        the logical clock is swept to MISSED."

        Design: Corner/state_machines/milestone_missed_then_late_completion
        """
        e1, v, plan, m = self._setup()
        advance_clock(864000)  # 10 days -> past 2026-09-10
        data = validate_success(api_client.get_milestone(m["id"], AUD))
        assert data["status"] == "MISSED"

    def test_late_completion_from_missed_allowed(self):
        """PRD §3.5: "A missed milestone is not dead — marking it complete from
        MISSED still moves it to COMPLETED with completed_at stamped."

        Design: Corner/state_machines/milestone_missed_then_late_completion
        """
        e1, v, plan, m = self._setup()
        advance_clock(864000)
        resp = api_client.complete_milestone(m["id"], make_officer_headers(e1["id"]))
        data = validate_success(resp)
        assert data["status"] == "COMPLETED"
        assert data.get("completed_at")


class TestCompleteMitigationWithPendingMilestoneRejected:
    def test_complete_mitigation_pending_milestone(self):
        """PRD §3.5: "Once every milestone of the plan stands in COMPLETED —
        none PENDING, none MISSED — the entity's officer marks the mitigation
        complete ... Attempting this with milestones outstanding is rejected
        with ERR_MILESTONES_INCOMPLETE."

        Design: Corner/state_machines/complete_mitigation_with_pending_milestone_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Pend Co")
        v = _open_violation(e1["id"])
        plan = _submit_plan(e1["id"], v)
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        get_success_data(api_client.create_milestone(
            plan["id"], create_milestone_payload(title="m",
                                                 due_date="2026-10-01T00:00:00Z"),
            make_officer_headers(e1["id"])))
        resp = api_client.complete_mitigation(v["id"], make_officer_headers(e1["id"]))
        validate_error(resp, ApiErrorId.ERR_MILESTONES_INCOMPLETE)

    def test_complete_mitigation_all_done_succeeds(self):
        """PRD §3.5: "Once every milestone of the plan stands in COMPLETED —
        none PENDING, none MISSED — the entity's officer marks the mitigation
        complete, moving the violation from MITIGATION_IN_PROGRESS to
        MITIGATION_COMPLETE."

        Design: Corner/state_machines/complete_mitigation_with_pending_milestone_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Done Co")
        v = _open_violation(e1["id"])
        plan = _submit_plan(e1["id"], v)
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        officer = make_officer_headers(e1["id"])
        m = get_success_data(api_client.create_milestone(
            plan["id"], create_milestone_payload(title="m",
                                                 due_date="2026-10-01T00:00:00Z"), officer))
        get_success_data(api_client.complete_milestone(m["id"], officer))
        resp = api_client.complete_mitigation(v["id"], officer)
        data = validate_success(resp)
        assert data["status"] == "MITIGATION_COMPLETE"


class TestVerifyPlanBeforeCompleteMitigationRejected:
    def test_verify_while_in_progress_rejected(self):
        """PRD §3.5: "the auditor verifies an APPROVED plan — verification from
        any other plan state fails as ERR_PLAN_STATE — and only when the
        violation has reached MITIGATION_COMPLETE, else ERR_VIOLATION_STATE."

        Design: Corner/state_machines/verify_plan_before_complete_mitigation_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("EarlyVer Co")
        v = _open_violation(e1["id"])
        plan = _submit_plan(e1["id"], v)
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        resp = api_client.verify_plan(plan["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_VIOLATION_STATE)
        plan_after = validate_success(api_client.get_mitigation_plan(plan["id"], AUD))
        assert plan_after["status"] == "APPROVED"

    def test_verify_after_complete_mitigation_succeeds(self):
        """PRD §3.5: "Verification moves the plan to VERIFIED and cascades the
        violation from MITIGATION_COMPLETE to CLOSED."

        Design: Corner/state_machines/verify_plan_before_complete_mitigation_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("GoodVer Co")
        v = _open_violation(e1["id"])
        plan = _submit_plan(e1["id"], v)
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        officer = make_officer_headers(e1["id"])
        m = get_success_data(api_client.create_milestone(
            plan["id"], create_milestone_payload(title="m",
                                                 due_date="2026-10-01T00:00:00Z"), officer))
        get_success_data(api_client.complete_milestone(m["id"], officer))
        get_success_data(api_client.complete_mitigation(v["id"], officer))
        resp = api_client.verify_plan(plan["id"], AUD)
        data = validate_success(resp)
        assert data["status"] == "VERIFIED"


class TestMilestoneCreationInDraftPlanRejected:
    def test_milestone_on_submitted_plan_rejected(self):
        """PRD §3.5: "Milestones may be added only while the plan is APPROVED —
        adding to a plan in any other state fails as ERR_PLAN_STATE."

        Design: Corner/entities/milestone_creation_in_draft_plan_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("MileStone Co")
        v = _open_violation(e1["id"])
        plan = _submit_plan(e1["id"], v)  # plan is SUBMITTED (DRAFT flips immediately)
        resp = api_client.create_milestone(
            plan["id"], create_milestone_payload(title="too early",
                                                 due_date="2026-10-01T00:00:00Z"),
            make_officer_headers(e1["id"]))
        validate_error(resp, ApiErrorId.ERR_PLAN_STATE)

    def test_milestone_on_approved_plan_accepted(self):
        """PRD §3.5: "The entity adds a Milestone to a plan by supplying a title
        and a due_date that must lie strictly in the future of the logical clock
        at creation ... each new milestone starts PENDING."

        Design: Corner/entities/milestone_creation_in_draft_plan_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("MileStone OK Co")
        v = _open_violation(e1["id"])
        plan = _submit_plan(e1["id"], v)
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        resp = api_client.create_milestone(
            plan["id"], create_milestone_payload(title="on time",
                                                 due_date="2026-10-01T00:00:00Z"),
            make_officer_headers(e1["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PENDING"
