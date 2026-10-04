"""CIP assets, access grants, penalties, restriction sweeps, and self-log
review periods."""
import pytest

from test_helpers import (
    make_auditor_headers,
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    create_access_grant_payload,
    create_cip_asset_payload,
    create_milestone_payload,
    create_mitigation_plan_payload,
    create_penalty_payload,
    create_registration_payload,
    create_self_log_entry_payload,
    create_self_report_payload,
    create_violation,
    create_violation_payload,
    get_success_data,
    make_cip_manager_headers,
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


def _register(name, enrollment=None):
    payload = create_registration_payload(legal_name=name, registration_functions=["GO"])
    if enrollment is not None:
        payload["enrollment_self_logging"] = enrollment
    return get_success_data(api_client.create_registration(payload, RC))


class TestCipDecommissionDependsOnAccessGrantState:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("GenCo CIP")
        cip = make_cip_manager_headers(e1["id"])
        ca = get_success_data(api_client.create_cip_asset(
            create_cip_asset_payload(e1["id"], asset_name="Substation Relay House",
                                     impact_rating="HIGH"), cip))
        g1 = get_success_data(api_client.create_access_grant(
            create_access_grant_payload(ca["id"], grantee_badge="B-100"), cip))
        return e1, cip, ca, g1

    def test_decommission_blocked_by_active_grant(self):
        """PRD §3.7: "Decommissioning is blocked while any access grant against
        the asset is still ACTIVE; the attempt is rejected with
        ERR_ACTIVE_ACCESS_GRANTS, so grants must be revoked first."

        Design: Difficulty/cross_entity_state_dependency/cip_decommission_depends_on_access_grant_state
        """
        e1, cip, ca, g1 = self._setup()
        resp = api_client.decommission_cip_asset(ca["id"], cip)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_ACCESS_GRANTS)

    def test_decommission_succeeds_after_revoke(self):
        """PRD §3.7: "An asset begins ACTIVE and can be decommissioned, moving
        it one-way to DECOMMISSIONED. Decommissioning is blocked while any
        access grant against the asset is still ACTIVE ... so grants must be
        revoked first."

        Design: Difficulty/cross_entity_state_dependency/cip_decommission_depends_on_access_grant_state
        """
        e1, cip, ca, g1 = self._setup()
        validate_error(api_client.decommission_cip_asset(ca["id"], cip),
                       ApiErrorId.ERR_ACTIVE_ACCESS_GRANTS)
        get_success_data(api_client.revoke_access_grant(g1["id"], cip))
        data = validate_success(api_client.decommission_cip_asset(ca["id"], cip))
        assert data["status"] == "DECOMMISSIONED"


class TestAccessGrantOnDecommissionedAssetRejected:
    def test_grant_on_decommissioned_asset(self):
        """PRD §3.7: "Granting access to an asset that is already DECOMMISSIONED
        fails with ERR_ASSET_DECOMMISSIONED."

        Design: Corner/state_machines/access_grant_on_decommissioned_asset_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Decom Co")
        cip = make_cip_manager_headers(e1["id"])
        ca = get_success_data(api_client.create_cip_asset(
            create_cip_asset_payload(e1["id"], asset_name="Old Yard",
                                     impact_rating="LOW"), cip))
        get_success_data(api_client.decommission_cip_asset(ca["id"], cip))
        resp = api_client.create_access_grant(
            create_access_grant_payload(ca["id"], grantee_badge="B-1"), cip)
        validate_error(resp, ApiErrorId.ERR_ASSET_DECOMMISSIONED)

    def test_grant_on_active_asset_accepted(self):
        """PRD §3.7: "The server stamps granted_at, leaves revoked_at null, and
        starts the grant ACTIVE."

        Design: Corner/state_machines/access_grant_on_decommissioned_asset_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Grant Co")
        cip = make_cip_manager_headers(e1["id"])
        ca = get_success_data(api_client.create_cip_asset(
            create_cip_asset_payload(e1["id"], asset_name="Yard",
                                     impact_rating="MEDIUM"), cip))
        resp = api_client.create_access_grant(
            create_access_grant_payload(ca["id"], grantee_badge="B-2"), cip)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert data.get("revoked_at") is None


class TestPenaltyDueDateAggregateRestriction:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("GenCo Due")
        v1 = create_violation(e1["id"], standard_id="STD-GO-001")
        v2 = create_violation(e1["id"], standard_id="STD-GO-002",
                              violation_start="2026-01-03T00:00:00Z",
                              violation_end="2026-01-04T00:00:00Z")
        p1 = get_success_data(api_client.create_penalty(create_penalty_payload(v1["id"]), AUD))
        p2 = get_success_data(api_client.create_penalty(create_penalty_payload(v2["id"]), AUD))
        get_success_data(api_client.confirm_penalty(p1["id"], make_auditor_headers("test-auditor-2")))
        get_success_data(api_client.confirm_penalty(p2["id"], make_auditor_headers("test-auditor-2")))
        return e1, v1, v2, p1, p2

    def test_active_at_due_date_restricted_after(self):
        """PRD §2.8: "An entity becomes RESTRICTED when a confirmed penalty
        against it remains unsettled past its due date — that is, when the
        current logical clock has advanced beyond the penalty's due_date while
        the penalty is still in CONFIRMED status."

        Design: Difficulty/resource_temporal_overlap/penalty_due_date_aggregate_restriction
        """
        e1, v1, v2, p1, p2 = self._setup()
        advance_clock(2592000)  # exactly 30 days: now == due_date
        at_due = validate_success(api_client.get_registration(e1["id"], AUD))
        assert at_due["compliance_status"] == "ACTIVE"
        advance_clock(86400)  # one day past due
        past_due = validate_success(api_client.get_registration(e1["id"], AUD))
        assert past_due["compliance_status"] == "RESTRICTED"

    def test_restriction_lifts_only_when_all_resolved(self):
        """PRD §2.8: "The entity returns to ACTIVE only when no confirmed
        past-due penalty remains against it; both settlement and waiver can lift
        the restriction, and the sweep applies the same rule."

        Design: Difficulty/resource_temporal_overlap/penalty_due_date_aggregate_restriction
        """
        e1, v1, v2, p1, p2 = self._setup()
        advance_clock(2592000 + 86400)
        officer = make_officer_headers(e1["id"])
        get_success_data(api_client.settle_penalty(p1["id"], officer))
        one_settled = validate_success(api_client.get_registration(e1["id"], AUD))
        assert one_settled["compliance_status"] == "RESTRICTED"
        get_success_data(api_client.settle_penalty(p2["id"], officer))
        both_settled = validate_success(api_client.get_registration(e1["id"], AUD))
        assert both_settled["compliance_status"] == "ACTIVE"


class TestPenaltyWaiveOnAssessedRejected:
    def test_waive_assessed_rejected(self):
        """PRD §3.8: "Either action attempted on a penalty not in CONFIRMED
        fails as ERR_PENALTY_NOT_CONFIRMED."

        Design: Corner/state_machines/penalty_waive_on_assessed_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Waive Co")
        v = create_violation(e1["id"])
        pen = get_success_data(api_client.create_penalty(create_penalty_payload(v["id"]), AUD))
        resp = api_client.waive_penalty(pen["id"], FED)
        validate_error(resp, ApiErrorId.ERR_PENALTY_NOT_CONFIRMED)

    def test_waive_confirmed_accepted(self):
        """PRD §3.8: "Alternatively, a FederalReviewer waives it, moving
        CONFIRMED to WAIVED — the federal override."

        Design: Corner/state_machines/penalty_waive_on_assessed_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Waive2 Co")
        v = create_violation(e1["id"])
        pen = get_success_data(api_client.create_penalty(create_penalty_payload(v["id"]), AUD))
        get_success_data(api_client.confirm_penalty(pen["id"], make_auditor_headers("test-auditor-2")))
        data = validate_success(api_client.waive_penalty(pen["id"], FED))
        assert data["status"] == "WAIVED"


class TestComputedReadPenaltySnapshot:
    def test_amount_snapshots_proposed_penalty(self):
        """PRD §3.8: "The row snapshots the violation's pricing at issuance:
        base_amount and adjustment_factor come from the penalty computation, and
        amount is the snapshot of the violation's proposed_penalty." The
        fixture's SPOT_CHECK source engagement carries no evidence, so its
        coverage_fraction is 0.0 < 0.8 and the §3.4 gap-aggravation step
        applies: MINIMAL/LOWER prices at 1000 * 1.25 = 1250.00.

        Design: Corner/endpoints/computed_read_penalty_snapshot
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Snap Co")
        v = create_violation(e1["id"])
        assert v["proposed_penalty"] == pytest.approx(1250.00, abs=0.005)
        pen = get_success_data(api_client.create_penalty(create_penalty_payload(v["id"]), AUD))
        assert pen["amount"] == pytest.approx(1250.00, abs=0.005)
        assert pen["status"] == "ASSESSED"

    def test_due_date_thirty_days_after_issuance(self):
        """PRD §3.8: "The server stamps issued_at and sets due_date exactly
        thirty days after issuance."

        Design: Corner/endpoints/computed_read_penalty_snapshot
        """
        from datetime import datetime, timedelta
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Snap2 Co")
        v = create_violation(e1["id"])
        pen = get_success_data(api_client.create_penalty(create_penalty_payload(v["id"]), AUD))
        issued = datetime.fromisoformat(pen["issued_at"].replace("Z", "+00:00"))
        due = datetime.fromisoformat(pen["due_date"].replace("Z", "+00:00"))
        assert due - issued == timedelta(days=30)


class TestReviewPeriods:
    def test_empty_period_start_review_rejected(self):
        """PRD §3.6: "Moving the period from OPEN to REVIEWING requires that at
        least one entry has accumulated — starting review of an empty period is
        rejected with ERR_EMPTY_REVIEW_PERIOD."

        Design: Difficulty/boundary_precision_check/empty_review_period_zero_count
        """
        set_clock("2026-09-01T00:00:00Z")
        rp = get_success_data(api_client.create_review_period(AUD))
        resp = api_client.start_review_period(rp["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_EMPTY_REVIEW_PERIOD)

    def test_empty_period_stays_open_after_rejection(self):
        """PRD §3.6: "A ComplianceAuditor opens a new ReviewPeriod at any time;
        the server stamps open_at, closed_at starts null, and the period is
        OPEN."

        Design: Difficulty/boundary_precision_check/empty_review_period_zero_count
        """
        set_clock("2026-09-01T00:00:00Z")
        rp = get_success_data(api_client.create_review_period(AUD))
        validate_error(api_client.start_review_period(rp["id"], AUD),
                       ApiErrorId.ERR_EMPTY_REVIEW_PERIOD)
        data = validate_success(api_client.get_review_period(rp["id"], AUD))
        assert data["status"] == "OPEN"

    def test_close_with_unreviewed_entries_rejected(self):
        """PRD §3.6: "Closing a period moves it from REVIEWING to CLOSED and
        stamps closed_at, but only when every entry of the period has been
        adjudicated — any entry still LOGGED blocks closure with
        ERR_ENTRIES_UNREVIEWED."

        Design: Corner/state_machines/review_period_close_with_unreviewed_entries_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Unrev Co", enrollment=True)
        rp = get_success_data(api_client.create_review_period(AUD))
        get_success_data(api_client.create_self_log_entry(
            create_self_log_entry_payload(e1["id"], period_id=rp["id"]),
            make_officer_headers(e1["id"])))
        get_success_data(api_client.start_review_period(rp["id"], AUD))
        resp = api_client.close_review_period(rp["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_ENTRIES_UNREVIEWED)

    def test_close_after_all_reviewed_succeeds(self):
        """PRD §3.6: "Closing a period moves it from REVIEWING to CLOSED and
        stamps closed_at, but only when every entry of the period has been
        adjudicated."

        Design: Corner/state_machines/review_period_close_with_unreviewed_entries_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Rev Co", enrollment=True)
        rp = get_success_data(api_client.create_review_period(AUD))
        entry = get_success_data(api_client.create_self_log_entry(
            create_self_log_entry_payload(e1["id"], period_id=rp["id"]),
            make_officer_headers(e1["id"])))
        get_success_data(api_client.start_review_period(rp["id"], AUD))
        get_success_data(api_client.review_self_log_entry(
            entry["id"], {"outcome": "REVIEWED_OK"}, AUD))
        data = validate_success(api_client.close_review_period(rp["id"], AUD))
        assert data["status"] == "CLOSED"
        assert data.get("closed_at")

    def test_happy_path_counters_and_qualified_auto_dismissal(self):
        """PRD §3.6: "when the escalation's risk factor is MINIMAL and its
        severity is LOWER, the violation is created with
        is_self_logging_qualified set to true and moves atomically from OPEN to
        DISMISSED in the same act — it never enters open_violation_count, the
        net effect on the count being zero."

        Design: Corner/state_machines/review_period_happy_path_with_escalation
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Review Co", enrollment=True)
        officer = make_officer_headers(e1["id"])
        rp = get_success_data(api_client.create_review_period(AUD))
        le1 = get_success_data(api_client.create_self_log_entry(
            create_self_log_entry_payload(e1["id"], exception_note="ok one",
                                          period_id=rp["id"]), officer))
        le2 = get_success_data(api_client.create_self_log_entry(
            create_self_log_entry_payload(e1["id"], standard_id="STD-GO-002",
                                          exception_note="esc one",
                                          period_id=rp["id"]), officer))
        get_success_data(api_client.start_review_period(rp["id"], AUD))
        get_success_data(api_client.review_self_log_entry(
            le1["id"], {"outcome": "REVIEWED_OK"}, AUD))
        get_success_data(api_client.review_self_log_entry(
            le2["id"], {"outcome": "ESCALATED", "violation_risk_factor": "MINIMAL",
                        "severity_level": "LOWER"}, AUD))
        data = validate_success(api_client.close_review_period(rp["id"], AUD))
        assert data["status"] == "CLOSED"
        assert data["reviewed_ok_count"] == 1
        assert data["escalated_count"] == 1
        ent = validate_success(api_client.get_registration(e1["id"], AUD))
        assert ent["open_violation_count"] == 0

    def test_nonqualified_escalation_creates_open_violation(self):
        """PRD §3.6: "Any other risk/severity combination creates the violation
        in OPEN and increments the entity's open_violation_count by one, which
        is how a self-log escalation becomes a formal case."

        Design: Corner/state_machines/review_period_happy_path_with_escalation
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Review2 Co", enrollment=True)
        rp = get_success_data(api_client.create_review_period(AUD))
        le = get_success_data(api_client.create_self_log_entry(
            create_self_log_entry_payload(e1["id"], period_id=rp["id"]),
            make_officer_headers(e1["id"])))
        get_success_data(api_client.start_review_period(rp["id"], AUD))
        get_success_data(api_client.review_self_log_entry(
            le["id"], {"outcome": "ESCALATED", "violation_risk_factor": "SERIOUS",
                       "severity_level": "SEVERE"}, AUD))
        ent = validate_success(api_client.get_registration(e1["id"], AUD))
        assert ent["open_violation_count"] == 1


class TestEnrollmentGateBeatsReferentialOnSelfLog:
    def test_not_enrolled_beats_not_applicable(self):
        """PRD §2.5: "Only after these six layers pass do the domain-specific
        business rules run, in the following relative order: self-logging
        enrollment and the CIP access-log evidence requirement first ... then
        standard applicability." PRD §3.6: "An entity not enrolled is rejected
        with ERR_SELF_LOG_NOT_ENROLLED."

        Design: Difficulty/priority_pair_validation_conflict/enrollment_gate_beats_referential_on_self_log
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("GenCo NotEnrolled")  # enrollment defaults to false
        resp = api_client.create_self_log_entry(
            {"entity_id": e1["id"], "standard_id": "STD-TO-001",
             "exception_note": "not our standard and not enrolled"},
            make_officer_headers(e1["id"]))
        validate_error(resp, ApiErrorId.ERR_SELF_LOG_NOT_ENROLLED)

    def test_enrolled_but_not_applicable_standard(self):
        """PRD §3.6: "a standard_id that must belong to the entity's applicable
        standards" — an enrolled entity logging against an out-of-applicability
        standard is rejected with ERR_STANDARD_NOT_APPLICABLE (PRD §3.1 /
        §2.5 standard applicability rule).

        Design: Difficulty/priority_pair_validation_conflict/enrollment_gate_beats_referential_on_self_log
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("GenCo Enrolled", enrollment=True)
        resp = api_client.create_self_log_entry(
            {"entity_id": e1["id"], "standard_id": "STD-TO-001",
             "exception_note": "not our standard"},
            make_officer_headers(e1["id"]))
        validate_error(resp, ApiErrorId.ERR_STANDARD_NOT_APPLICABLE)


class TestEntityRestrictedBlocksSelfReport:
    def test_restricted_entity_self_report_rejected(self):
        """PRD §2.5: "the registered-entity posture gate runs: entity-initiated
        mutation endpoints — filing a self-report, submitting a mitigation plan,
        filing an appeal, logging a self-log entry, or creating an access grant
        — are rejected with ERR_ENTITY_RESTRICTED when the acting entity's
        compliance_status is RESTRICTED."

        Design: Corner/validations/entity_restricted_blocks_self_report
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Restr Co")
        v = create_violation(e1["id"])
        pen = get_success_data(api_client.create_penalty(create_penalty_payload(v["id"]), AUD))
        get_success_data(api_client.confirm_penalty(pen["id"], make_auditor_headers("test-auditor-2")))
        advance_clock(2678400)  # 31 days past issuance -> past due
        ent = validate_success(api_client.get_registration(e1["id"], AUD))
        assert ent["compliance_status"] == "RESTRICTED"
        resp = api_client.create_self_report(
            create_self_report_payload(e1["id"]), make_officer_headers(e1["id"]))
        validate_error(resp, ApiErrorId.ERR_ENTITY_RESTRICTED)

    def test_active_entity_self_report_accepted(self):
        """PRD §3.3: "An entity's EntityComplianceOfficer may self-report a
        potential noncompliance ... A self-report enters RECEIVED."

        Design: Corner/validations/entity_restricted_blocks_self_report
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register("Actv Co")
        resp = api_client.create_self_report(
            create_self_report_payload(e1["id"]), make_officer_headers(e1["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "RECEIVED"
