"""Derived counters, sweeps, auth/RBAC, and listing filters."""
import pytest

from test_helpers import (
    make_auditor_headers,
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    create_appeal_payload,
    create_milestone_payload,
    create_mitigation_plan_payload,
    create_penalty_payload,
    create_registration_payload,
    create_violation,
    create_violation_payload,
    get_success_data,
    make_officer_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

AUD = TEST_USERS["auditor_headers"]
RC = TEST_USERS["registration_coordinator_headers"]
RER = TEST_USERS["regional_reviewer_headers"]
FED = TEST_USERS["federal_reviewer_headers"]


def _register(name):
    return get_success_data(api_client.create_registration(
        create_registration_payload(legal_name=name, registration_functions=["GO"]), RC))


def _open_violation(entity_id, **overrides):
    # Route through the PRD-legal fixture so AUDIT/SPOT_CHECK sources carry a
    # valid source reference (PRD §3.4 source integrity).
    return create_violation(entity_id, **overrides)


class TestOpenViolationCountConservation:
    def _setup_two(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("GenCo Inv")
        v1 = _open_violation(e1["id"], violation_risk_factor="MODERATE",
                             severity_level="SEVERE")
        v2 = _open_violation(e1["id"], standard_id="STD-GO-002",
                             violation_start="2026-01-05T00:00:00Z",
                             violation_end="2026-01-06T00:00:00Z")
        return e1, v1, v2

    def test_count_two_after_two_creates(self):
        """PRD §3.1: "open_violation_count counts the entity's violations whose
        status is OPEN, MITIGATION_SUBMITTED, MITIGATION_IN_PROGRESS, or
        APPEALED, and is recomputed on every violation creation and status
        change." PRD §3.4: "creating the violation increments the owning
        entity's open_violation_count by one."

        Design: Difficulty/compensating_invariant/open_violation_count_conservation
        """
        e1, v1, v2 = self._setup_two()
        ent = validate_success(api_client.get_registration(e1["id"], AUD))
        assert ent["open_violation_count"] == 2

    def test_count_zero_after_mitigation_close_and_appeal_grant(self):
        """PRD §3.5: "Verification moves the plan to VERIFIED and cascades the
        violation from MITIGATION_COMPLETE to CLOSED, which ... decrements the
        entity's open_violation_count by one." PRD §3.9: "A grant at either
        review level — regional or federal — closes the case: ... the entity's
        open_violation_count drops by one."

        Design: Difficulty/compensating_invariant/open_violation_count_conservation
        """
        e1, v1, v2 = self._setup_two()
        officer = make_officer_headers(e1["id"])
        # Close V1 via mitigation.
        plan = get_success_data(api_client.create_mitigation_plan(
            v1["id"], create_mitigation_plan_payload(v1["version"]), officer))
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        m = get_success_data(api_client.create_milestone(
            plan["id"], create_milestone_payload(title="m",
                                                 due_date="2026-10-01T00:00:00Z"), officer))
        get_success_data(api_client.complete_milestone(m["id"], officer))
        get_success_data(api_client.complete_mitigation(v1["id"], officer))
        get_success_data(api_client.verify_plan(plan["id"], AUD))
        # Close V2 via granted appeal.
        v2_now = validate_success(api_client.get_violation(v2["id"], AUD))
        ap = get_success_data(api_client.create_appeal(
            v2["id"], create_appeal_payload(v2_now["version"]), officer))
        get_success_data(api_client.grant_appeal(ap["id"], RER))
        ent = validate_success(api_client.get_registration(e1["id"], AUD))
        assert ent["open_violation_count"] == 0


class TestDerivedFieldReconciliationOnViolationClose:
    def test_count_create_appeal_close_sequence(self):
        """PRD §3.1: "open_violation_count counts the entity's violations whose
        status is OPEN, MITIGATION_SUBMITTED, MITIGATION_IN_PROGRESS, or
        APPEALED, and is recomputed on every violation creation and status
        change."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_on_violation_close
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Recon Co")
        v = _open_violation(e1["id"])
        c1 = validate_success(api_client.get_registration(e1["id"], AUD))
        assert c1["open_violation_count"] == 1
        ap = get_success_data(api_client.create_appeal(
            v["id"], create_appeal_payload(v["version"]), make_officer_headers(e1["id"])))
        c2 = validate_success(api_client.get_registration(e1["id"], AUD))
        assert c2["open_violation_count"] == 1  # APPEALED still counts
        get_success_data(api_client.grant_appeal(ap["id"], RER))
        c3 = validate_success(api_client.get_registration(e1["id"], AUD))
        assert c3["open_violation_count"] == 0

    def test_count_increments_per_violation(self):
        """PRD §3.4: "creating the violation increments the owning entity's
        open_violation_count by one."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_on_violation_close
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Recon2 Co")
        _open_violation(e1["id"])
        _open_violation(e1["id"], standard_id="STD-GO-002",
                        violation_start="2026-02-01T00:00:00Z",
                        violation_end="2026-02-02T00:00:00Z")
        ent = validate_success(api_client.get_registration(e1["id"], AUD))
        assert ent["open_violation_count"] == 2


class TestOpsRunCheckpointSweepsMilestonesAndRestrictions:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Sweep Co")
        officer = make_officer_headers(e1["id"])
        v1 = _open_violation(e1["id"])
        plan = get_success_data(api_client.create_mitigation_plan(
            v1["id"], create_mitigation_plan_payload(v1["version"]), officer))
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        m = get_success_data(api_client.create_milestone(
            plan["id"], create_milestone_payload(title="m",
                                                 due_date="2026-09-05T00:00:00Z"), officer))
        v2 = _open_violation(e1["id"], standard_id="STD-GO-002",
                             violation_start="2026-02-01T00:00:00Z",
                             violation_end="2026-02-02T00:00:00Z")
        pen = get_success_data(api_client.create_penalty(create_penalty_payload(v2["id"]), AUD))
        get_success_data(api_client.confirm_penalty(pen["id"], make_auditor_headers("test-auditor-2")))
        return e1, m

    def test_single_advance_fires_both_sweeps(self):
        """PRD §3.10: "Advancing the clock runs two sweeps in one motion. The
        milestone sweep moves every PENDING milestone whose due_date has fallen
        behind the new clock to MISSED (§3.5). The restriction sweep walks all
        penalties: every penalty in CONFIRMED whose due_date lies before the
        current clock forces its owning entity's compliance_status to
        RESTRICTED."

        Design: Corner/cross_cutting_layers/ops_run_checkpoint_sweeps_milestones_and_restrictions
        """
        e1, m = self._setup()
        advance_clock(2678400)  # 31 days: past milestone due (09-05) and past penalty due (10-01)
        m_data = validate_success(api_client.get_milestone(m["id"], AUD))
        assert m_data["status"] == "MISSED"
        ent = validate_success(api_client.get_registration(e1["id"], AUD))
        assert ent["compliance_status"] == "RESTRICTED"

    def test_no_sweep_effects_before_deadlines(self):
        """PRD §3.10: "Advancing the clock runs two sweeps in one motion." PRD
        §2.8: "An entity becomes RESTRICTED when a confirmed penalty against it
        remains unsettled past its due date" — before the deadlines pass, no
        sweep effect applies.

        Design: Corner/cross_cutting_layers/ops_run_checkpoint_sweeps_milestones_and_restrictions
        """
        e1, m = self._setup()
        advance_clock(86400)  # one day only
        m_data = validate_success(api_client.get_milestone(m["id"], AUD))
        assert m_data["status"] == "PENDING"
        ent = validate_success(api_client.get_registration(e1["id"], AUD))
        assert ent["compliance_status"] == "ACTIVE"


class TestUnauthenticatedMissingHeaders:
    def test_missing_user_id_header(self):
        """PRD §2.1: "Every request must carry two HTTP headers: X-User-ID,
        identifying the acting user, and X-User-Role, naming the capacity in
        which they act. A request missing either header, or carrying a malformed
        one, is rejected with ERR_UNAUTHENTICATED."

        Design: Corner/errors/unauthenticated_missing_headers
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api_client.list_registrations(
            headers={"X-User-Role": "ComplianceAuditor",
                     "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_missing_role_header(self):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        one, is rejected with ERR_UNAUTHENTICATED."

        Design: Corner/errors/unauthenticated_missing_headers
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api_client.list_registrations(
            headers={"X-User-ID": "someone", "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestEntityOfficerCannotCreateEngagement:
    def test_officer_create_engagement_denied(self):
        """PRD §2.1: "A request whose role is not authorized for the endpoint is
        rejected with ERR_UNAUTHORIZED." PRD §4: "POST /compliance/engagements
        ... ComplianceAuditor."

        Design: Corner/rbac/entity_officer_cannot_create_engagement
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Rbac Co")
        resp = api_client.create_engagement(
            {"entity_id": e1["id"], "engagement_type": "AUDIT",
             "standard_ids": ["STD-GO-001"],
             "period_start": "2026-01-01T00:00:00Z",
             "period_end": "2026-01-31T00:00:00Z"},
            make_officer_headers(e1["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_auditor_create_engagement_allowed(self):
        """PRD §4: "POST /compliance/engagements — Schedule an audit, spot
        check, or self-certification — ComplianceAuditor."

        Design: Corner/rbac/entity_officer_cannot_create_engagement
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Rbac2 Co")
        resp = api_client.create_engagement(
            {"entity_id": e1["id"], "engagement_type": "AUDIT",
             "standard_ids": ["STD-GO-001"],
             "period_start": "2026-01-01T00:00:00Z",
             "period_end": "2026-01-31T00:00:00Z"}, AUD)
        validate_success(resp, expected_status=201)


class TestRegionalReviewerCannotGrantFederalLevelAppeal:
    def _setup_federal_pending(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("FedRbac Co")
        v = _open_violation(e1["id"])
        ap = get_success_data(api_client.create_appeal(
            v["id"], create_appeal_payload(v["version"]), make_officer_headers(e1["id"])))
        get_success_data(api_client.deny_appeal(ap["id"], RER))
        get_success_data(api_client.request_federal_review(ap["id"], make_officer_headers(e1["id"])))
        return e1, v, ap

    def test_regional_grant_at_federal_level_denied(self):
        """PRD §2.1: "RegionalEntityReviewer may grant or deny only appeals
        currently in APPEAL_PENDING_REVIEW, while FederalReviewer may grant or
        deny only appeals in FEDERAL_REVIEW_REQUESTED; the wrong level for the
        appeal's current status is an authorization failure, not merely an
        invalid state."

        Design: Corner/rbac/regional_reviewer_cannot_grant_federal_level_appeal
        """
        e1, v, ap = self._setup_federal_pending()
        resp = api_client.grant_appeal(ap["id"], RER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_federal_grant_at_federal_level_allowed(self):
        """PRD §2.1: "FederalReviewer may grant or deny only appeals in
        FEDERAL_REVIEW_REQUESTED."

        Design: Corner/rbac/regional_reviewer_cannot_grant_federal_level_appeal
        """
        e1, v, ap = self._setup_federal_pending()
        data = validate_success(api_client.grant_appeal(ap["id"], FED))
        assert data["status"] == "APPEAL_GRANTED"


class TestSegregationOfDutiesPlanSubmitterCannotApprove:
    def test_officer_cannot_approve_plan(self):
        """PRD §2.1: "A request whose role is not authorized for the endpoint is
        rejected with ERR_UNAUTHORIZED." PRD §4: "POST
        /compliance/mitigation-plans/{planId}/approve ... ComplianceAuditor."

        Design: Corner/rbac/segregation_of_duties_plan_submitter_cannot_approve
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Sod Co")
        v = _open_violation(e1["id"])
        plan = get_success_data(api_client.create_mitigation_plan(
            v["id"], create_mitigation_plan_payload(v["version"]),
            make_officer_headers(e1["id"])))
        resp = api_client.approve_plan(plan["id"], make_officer_headers(e1["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_auditor_who_did_not_submit_may_approve(self):
        """PRD §2.1: "The same X-User-ID that submitted a MitigationPlan may not
        later approve or verify that plan" — a different auditor identity (the
        submitter was the entity's officer) is permitted.

        Design: Corner/rbac/segregation_of_duties_plan_submitter_cannot_approve
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Sod2 Co")
        v = _open_violation(e1["id"])
        plan = get_success_data(api_client.create_mitigation_plan(
            v["id"], create_mitigation_plan_payload(v["version"]),
            make_officer_headers(e1["id"])))
        resp = api_client.approve_plan(plan["id"], AUD)
        data = validate_success(resp)
        assert data["status"] == "APPROVED"


class TestFilteredListReverseReachability:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Parent Co")
        e2 = _register("Other Co")
        v1 = _open_violation(e1["id"])
        plan = get_success_data(api_client.create_mitigation_plan(
            v1["id"], create_mitigation_plan_payload(v1["version"]),
            make_officer_headers(e1["id"])))
        get_success_data(api_client.approve_plan(plan["id"], AUD))
        m = get_success_data(api_client.create_milestone(
            plan["id"], create_milestone_payload(title="m",
                                                 due_date="2026-10-01T00:00:00Z"),
            make_officer_headers(e1["id"])))
        return e1, e2, v1, plan, m

    def test_violations_filtered_by_entity(self):
        """PRD §3.4: "Violations are listable filtered by entity_id, status,
        source_engagement_id, and source_self_report_id."

        Design: Corner/endpoints/filtered_list_reverse_reachability
        """
        e1, e2, v1, plan, m = self._setup()
        rows_e2, meta_e2 = validate_paginated(
            api_client.list_violations(AUD, params={"entity_id": e2["id"]}))
        assert meta_e2["total_count"] == 0
        rows_e1, meta_e1 = validate_paginated(
            api_client.list_violations(AUD, params={"entity_id": e1["id"]}))
        assert meta_e1["total_count"] == 1
        assert rows_e1[0]["id"] == v1["id"]

    def test_milestones_listed_under_plan(self):
        """PRD §3.5: "a plan's milestones are listed under the plan itself."

        Design: Corner/endpoints/filtered_list_reverse_reachability
        """
        e1, e2, v1, plan, m = self._setup()
        rows, meta = validate_paginated(
            api_client.list_milestones(plan["id"], AUD))
        assert meta["total_count"] == 1
        assert rows[0]["title"] == "m"
