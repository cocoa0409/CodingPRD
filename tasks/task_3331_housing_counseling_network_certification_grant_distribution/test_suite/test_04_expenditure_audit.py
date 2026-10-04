"""Expenditure reports, compliance audits, clawback, and terminal lockdown."""
import pytest
from test_helpers import (
    TEST_USERS, ApiErrorId, validate_success, validate_error, get_success_data,
    validate_error_is_one_of,
    create_member, create_counselor, create_course, set_clock,
    setup_chartered_member_with_counselor, create_grant_cycle,
    create_grant_application, submit_application, advance_cycle_to_awarded,
    award_application, setup_cycle_with_award,
    setup_active_award_with_disbursement, submit_expenditure_report,
    flag_report_and_get_audit, issue_audit_findings,
    setup_member_in_probation,
    make_member_admin_headers, make_grant_officer_headers,
)
from test_helpers.assertions import assert_compliance_audit, assert_expenditure_report

DIRECTOR = TEST_USERS["network_director_headers"]
OFFICER = TEST_USERS["grant_officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestExpenditureCascade:
    def test_expenditure_flag_to_member_freeze(self, api):
        """PRD §3.6: "the officer flags the report, moving it to `FLAGGED` and
        spawning a compliance audit in `OPEN` for the award"
        PRD §3.6: "issuance moves the linked flagged report from `FLAGGED` to
        `AUDITED`"
        PRD §3.6: "Escalating moves the audit to `ESCALATED` and fires the
        third cascade link: the award transitions to `SUSPENDED`; the award's
        `disbursed_cents` is reduced by `disallowance_cents` through a clawback
        adjusting entry; and the disallowed amount is credited back to the
        cycle's pools in waterfall order — the competitive pool's committed
        total first, then the formula pool's"
        PRD §3.6: "Escalation also forces the member's `compliance_posture` to
        `FROZEN` on recompute."

        Design: Difficulty/transitive_cascade/expenditure_flag_to_member_freeze
        """
        member, cycle, award = setup_active_award_with_disbursement(
            fiscal_year=2030, requested_formula_cents=60000,
            requested_competitive_cents=50000, review_score=80,
            verify_match_cents=25000, disburse_amount=80000,
            member_overrides={"legal_name": "Cascade Housing", "ein": "777777771",
                              "state_code": "GA", "service_regions": ["13001"]},
            course_code="HO-401")
        assert award["formula_component_cents"] == 60000
        assert award["competitive_component_cents"] == 40000

        report = submit_expenditure_report(
            award, member, period_start="2026-10-01T00:00:00Z",
            period_end="2026-12-31T00:00:00Z", reported_spent_cents=70000)
        report, audit = flag_report_and_get_audit(report)
        issue_audit_findings(audit, 15000)
        resp = api.escalate_audit(audit["id"], AUDITOR)
        validate_success(resp)

        report_after = validate_success(api.get_expenditure_report(report["id"], OFFICER))
        assert report_after["report_status"] == "AUDITED"
        award_after = validate_success(api.get_grant_award(award["id"], OFFICER))
        assert award_after["award_status"] == "SUSPENDED"
        assert award_after["disbursed_cents"] == 65000
        cycle_after = validate_success(api.get_grant_cycle(cycle["id"], OFFICER))
        assert cycle_after["competitive_committed_cents"] == 25000
        member_after = validate_success(api.get_member(member["id"], DIRECTOR))
        assert member_after["compliance_posture"] == "FROZEN"

    def test_flag_creates_open_audit(self, api):
        """PRD §3.6: "Alternatively, the officer flags the report, moving it to
        `FLAGGED` and spawning a compliance audit in `OPEN` for the award — the
        first link of a transitive cascade."

        Design: Difficulty/transitive_cascade/expenditure_flag_to_member_freeze
        """
        member, cycle, award = setup_active_award_with_disbursement(
            fiscal_year=2056, requested_formula_cents=60000,
            requested_competitive_cents=0, review_score=None,
            verify_match_cents=6000, disburse_amount=30000,
            member_overrides={"legal_name": "Flag Housing", "ein": "777777773",
                              "state_code": "GA", "service_regions": ["13003"]},
            course_code="HO-403")
        report = submit_expenditure_report(
            award, member, period_start="2026-10-01T00:00:00Z",
            period_end="2026-12-31T00:00:00Z", reported_spent_cents=10000)
        report, audit = flag_report_and_get_audit(report)
        assert report["report_status"] == "FLAGGED"
        assert_compliance_audit(audit)
        assert audit["audit_status"] == "OPEN"
        assert audit["award_id"] == award["id"]


class TestClawbackInvariant:
    def test_clawback_conserves_cycle_pool(self, api):
        """PRD §3.6: "the disallowed amount is credited back to the cycle's
        pools in waterfall order — the competitive pool's committed total
        first, then the formula pool's — so that the cycle's pools are
        conserved."
        PRD §3.6: "the award's `disbursed_cents` is reduced by
        `disallowance_cents` through a clawback adjusting entry"

        Design: Difficulty/compensating_invariant/clawback_conserves_cycle_pool
        """
        member, cycle, award = setup_active_award_with_disbursement(
            fiscal_year=2037, formula_pool_cents=500000,
            competitive_pool_cents=500000, requested_formula_cents=60000,
            requested_competitive_cents=50000, review_score=80,
            verify_match_cents=25000, disburse_amount=80000,
            member_overrides={"legal_name": "Invariant Housing", "ein": "123450005",
                              "state_code": "OR", "service_regions": ["41005"]},
            course_code="HO-901")
        assert award["formula_component_cents"] == 60000
        assert award["competitive_component_cents"] == 40000

        report = submit_expenditure_report(
            award, member, period_start="2026-10-01T00:00:00Z",
            period_end="2026-10-31T00:00:00Z", reported_spent_cents=70000)
        report, audit = flag_report_and_get_audit(report)
        issue_audit_findings(audit, 15000)
        resp = api.escalate_audit(audit["id"], AUDITOR)
        validate_success(resp)

        award_after = validate_success(api.get_grant_award(award["id"], OFFICER))
        assert award_after["disbursed_cents"] == 65000
        cycle_after = validate_success(api.get_grant_cycle(cycle["id"], OFFICER))
        assert cycle_after["competitive_committed_cents"] == 25000
        assert cycle_after["formula_committed_cents"] == 60000
        # Conservation: committed totals + clawed-back == original commitment.
        assert (cycle_after["formula_committed_cents"]
                + cycle_after["competitive_committed_cents"] + 15000) == 100000

    def test_clawback_waterfall_spills_to_formula(self, api):
        """PRD §3.6: "the disallowed amount is credited back to the cycle's
        pools in waterfall order — the competitive pool's committed total
        first, then the formula pool's"

        Design: Difficulty/compensating_invariant/clawback_conserves_cycle_pool
        """
        # Competitive commitment 40000; disallowance 50000 spills 10000 into formula.
        member, cycle, award = setup_active_award_with_disbursement(
            fiscal_year=2057, formula_pool_cents=500000,
            competitive_pool_cents=500000, requested_formula_cents=60000,
            requested_competitive_cents=50000, review_score=80,
            verify_match_cents=25000, disburse_amount=90000,
            member_overrides={"legal_name": "Waterfall Housing", "ein": "123450007",
                              "state_code": "OR", "service_regions": ["41007"]},
            course_code="HO-904")
        assert award["competitive_component_cents"] == 40000

        report = submit_expenditure_report(
            award, member, period_start="2026-10-01T00:00:00Z",
            period_end="2026-10-31T00:00:00Z", reported_spent_cents=85000)
        report, audit = flag_report_and_get_audit(report)
        issue_audit_findings(audit, 50000)
        resp = api.escalate_audit(audit["id"], AUDITOR)
        validate_success(resp)

        cycle_after = validate_success(api.get_grant_cycle(cycle["id"], OFFICER))
        assert cycle_after["competitive_committed_cents"] == 0
        assert cycle_after["formula_committed_cents"] == 50000
        award_after = validate_success(api.get_grant_award(award["id"], OFFICER))
        assert award_after["disbursed_cents"] == 40000


class TestExpenditureAggregateCapacity:
    def test_expenditure_report_period_capacity_overlap(self, api):
        """PRD §3.6: "A `GrantOfficer` accepts it only while its cumulative
        spend stays within the award's `disbursed_cents`; a report whose
        cumulative claim exceeds what has been disbursed is rejected with
        `ERR_POOL_EXHAUSTED`."
        PRD §3.6: "Each report derives a `cumulative_spent_cents`: the sum of
        reported spending over that award's reports in `ACCEPTED` or `AUDITED`
        status whose period starts on or before this report's period start."

        Design: Difficulty/resource_temporal_overlap/expenditure_report_period_capacity_overlap
        """
        member, cycle, award = setup_active_award_with_disbursement(
            fiscal_year=2036, formula_pool_cents=500000,
            competitive_pool_cents=0, requested_formula_cents=100000,
            requested_competitive_cents=0, review_score=None,
            verify_match_cents=10000, disburse_amount=60000,
            member_overrides={"legal_name": "Cap Housing", "ein": "123450004",
                              "state_code": "OR", "service_regions": ["41004"]},
            course_code="HO-802")

        r1 = submit_expenditure_report(
            award, member, period_start="2026-10-01T00:00:00Z",
            period_end="2026-10-31T00:00:00Z", reported_spent_cents=50000)
        resp = api.accept_expenditure_report(r1["id"], OFFICER)
        r1 = validate_success(resp)
        assert r1["report_status"] == "ACCEPTED"

        r2 = submit_expenditure_report(
            award, member, period_start="2026-11-01T00:00:00Z",
            period_end="2026-11-30T00:00:00Z", reported_spent_cents=15000)
        assert_expenditure_report(r2)
        resp = api.accept_expenditure_report(r2["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_POOL_EXHAUSTED)

    def test_expenditure_report_accept_within_disbursed(self, api):
        """PRD §3.6: "A `GrantOfficer` accepts it only while its cumulative
        spend stays within the award's `disbursed_cents`" — an in-budget
        cumulative total accepts and moves the report to `ACCEPTED`;
        §3.6: "Acceptance moves the report to `ACCEPTED` and reconciles the
        award-level spending totals."

        Design: Difficulty/resource_temporal_overlap/expenditure_report_period_capacity_overlap
        """
        member, cycle, award = setup_active_award_with_disbursement(
            fiscal_year=2058, formula_pool_cents=500000,
            competitive_pool_cents=0, requested_formula_cents=100000,
            requested_competitive_cents=0, review_score=None,
            verify_match_cents=10000, disburse_amount=60000,
            member_overrides={"legal_name": "Cap Two Housing", "ein": "123450014",
                              "state_code": "OR", "service_regions": ["41014"]},
            course_code="HO-804")

        r1 = submit_expenditure_report(
            award, member, period_start="2026-10-01T00:00:00Z",
            period_end="2026-10-31T00:00:00Z", reported_spent_cents=50000)
        resp = api.accept_expenditure_report(r1["id"], OFFICER)
        validate_success(resp)
        r2 = submit_expenditure_report(
            award, member, period_start="2026-11-01T00:00:00Z",
            period_end="2026-11-30T00:00:00Z", reported_spent_cents=10000)
        resp = api.accept_expenditure_report(r2["id"], OFFICER)
        r2 = validate_success(resp)
        assert r2["report_status"] == "ACCEPTED"
        assert r2["cumulative_spent_cents"] == 60000


class TestPosturePriorityOnAward:
    def test_posture_vs_fiscal_on_application_award(self, api):
        """PRD §2.9: "then the member compliance-posture gate (`ERR_MEMBER_POSTURE_BLOCKED`)"
        PRD §2.9: "then fiscal sufficiency of pools, award totals, and disbursed amounts (`ERR_POOL_EXHAUSTED`)"
        PRD §3.4: "Awarding is refused when the applicant member's posture is
        `FROZEN` (`ERR_MEMBER_POSTURE_BLOCKED`)"

        Design: Difficulty/priority_pair_validation_conflict/posture_vs_fiscal_on_application_award
        """
        member, cycle6, award6 = setup_active_award_with_disbursement(
            fiscal_year=2032, formula_pool_cents=200000,
            competitive_pool_cents=0, requested_formula_cents=100000,
            requested_competitive_cents=0, review_score=None,
            verify_match_cents=10000, disburse_amount=1000,
            member_overrides={"legal_name": "Frozen Fiscal Housing", "ein": "888888882",
                              "state_code": "AZ", "service_regions": ["04002"]},
            course_code="HO-501")

        report = submit_expenditure_report(
            award6, member, period_start="2026-10-01T00:00:00Z",
            period_end="2026-12-31T00:00:00Z", reported_spent_cents=1000)
        report, audit = flag_report_and_get_audit(report)
        issue_audit_findings(audit, 1000)

        # Second cycle: posture still WATCH at submit time (findings issued).
        cycle7 = create_grant_cycle(fiscal_year=2033, formula_pool_cents=0,
                                    competitive_pool_cents=30000)
        app7 = create_grant_application(
            cycle7, member, requested_formula_cents=0,
            requested_competitive_cents=100000, pledged_match_cents=25000)
        submit_application(app7, member)
        api.lock_formula(cycle7["id"], OFFICER)
        api.open_competitive_review(cycle7["id"], OFFICER)
        api.score_application(app7["id"], {"review_score": 95},
                              make_grant_officer_headers("go-reviewer-7"))

        # Freeze the member via escalation.
        resp = api.escalate_audit(audit["id"], AUDITOR)
        validate_success(resp)
        member_after = validate_success(api.get_member(member["id"], DIRECTOR))
        assert member_after["compliance_posture"] == "FROZEN"

        api.finalize_cycle(cycle7["id"], OFFICER)
        resp = api.award_application(app7["id"], make_grant_officer_headers("go-approver-7"))
        validate_error(resp, ApiErrorId.ERR_MEMBER_POSTURE_BLOCKED)
        cycle7_after = validate_success(api.get_grant_cycle(cycle7["id"], OFFICER))
        assert cycle7_after["competitive_committed_cents"] == 0

    def test_frozen_member_blocks_new_disbursement(self, api):
        """PRD §3.5: "Creating a new disbursement against an award whose member
        is `FROZEN` is blocked by the posture gate"
        PRD §2.10: "`FROZEN` members cannot begin counseling on client files,
        submit grant applications, receive awards, or receive new
        disbursements"

        Design: Difficulty/priority_pair_validation_conflict/posture_vs_fiscal_on_application_award
        """
        member, cycle, award = setup_active_award_with_disbursement(
            fiscal_year=2059, formula_pool_cents=500000,
            competitive_pool_cents=0, requested_formula_cents=100000,
            requested_competitive_cents=0, review_score=None,
            verify_match_cents=10000, disburse_amount=1000,
            member_overrides={"legal_name": "Frozen Disb Housing", "ein": "888888884",
                              "state_code": "AZ", "service_regions": ["04004"]},
            course_code="HO-503")
        report = submit_expenditure_report(
            award, member, period_start="2026-10-01T00:00:00Z",
            period_end="2026-12-31T00:00:00Z", reported_spent_cents=1000)
        report, audit = flag_report_and_get_audit(report)
        issue_audit_findings(audit, 1000)
        api.escalate_audit(audit["id"], AUDITOR)
        member_after = validate_success(api.get_member(member["id"], DIRECTOR))
        assert member_after["compliance_posture"] == "FROZEN"

        resp = api.create_disbursement({"award_id": award["id"], "amount_cents": 100}, OFFICER)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_MEMBER_POSTURE_BLOCKED, ApiErrorId.ERR_INVALID_STATE])


class TestTerminalAwardLockdown:
    def test_terminal_award_lockdown(self, api):
        """PRD §3.5: "Awards in `DISBURSING`, `ACTIVE`, or `SUSPENDED` whose
        member's charter is revoked terminate automatically."
        PRD §2.9: "then whether the target resource is in a state from which
        the requested transition exists (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/terminal_award_lockdown
        """
        member, counselor, certification = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Term Housing", "ein": "200000002",
                              "state_code": "CA", "service_regions": ["06039"]},
            program_area="FORECLOSURE_PREVENTION", course_code="HO-112")
        cycle, app, award = setup_cycle_with_award(
            member, fiscal_year=2040, formula_pool_cents=100000,
            requested_formula_cents=50000, activate=False)

        # Drive the member to PROBATION (PRD §3.8) so it can be revoked (PRD §3.1);
        # submission had to happen while still CHARTERED (PRD §3.4).
        review = validate_success(api.create_performance_review(
            {"member_id": member["id"], "review_period": "FY2040-H1"}, DIRECTOR),
            expected_status=201)
        api.score_performance_review(review["id"], {"review_score": 30}, DIRECTOR)
        validate_success(api.resolve_performance_review(
            review["id"], {"verdict": "CORRECTIVE_ACTION"}, DIRECTOR))
        set_clock("2027-06-01T00:00:00Z")
        validate_success(api.escalate_performance_review(review["id"], DIRECTOR))

        resp = api.revoke_member(member["id"], {"revocation_reason": "non-compliance"}, DIRECTOR)
        validate_success(resp)
        award_after = validate_success(api.get_grant_award(award["id"], OFFICER))
        assert award_after["award_status"] == "TERMINATED"

        resp = api.create_disbursement({"award_id": award["id"], "amount_cents": 100}, OFFICER)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_MEMBER_POSTURE_BLOCKED])

    def test_period_end_before_start_rejected(self, api):
        """PRD §3.6: "the member's `MemberAdmin` submits expenditure reports
        covering a period from `period_start` (inclusive) to `period_end`
        (exclusive, strictly after the start)"
        PRD §2.9: "then payload shape, enum validity, and range checks
        (`ERR_INVALID_REQUEST`)"

        Design: Corner/validations/period_end_before_start_rejected
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Period Org", "ein": "400000005",
                              "state_code": "CA", "service_regions": ["06047"]},
            course_code="HO-313")
        cycle, _app, award = setup_cycle_with_award(
            member, fiscal_year=2041, formula_pool_cents=100000,
            requested_formula_cents=50000, activate=False)

        resp = api.create_expenditure_report(
            {"award_id": award["id"], "period_start": "2026-12-31T00:00:00Z",
             "period_end": "2026-10-01T00:00:00Z", "reported_spent_cents": 100},
            make_member_admin_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestReconcileGate:
    def test_err_award_not_reconcilable_when_undisbursed(self, api):
        """PRD §3.5: "an `ACTIVE` award reconciles only when its
        `disbursed_cents` equals the sum of its two components exactly and
        every expenditure report against it has reached `ACCEPTED` or
        `AUDITED`; a premature reconcile is rejected with
        `ERR_AWARD_NOT_RECONCILABLE`."

        Design: Corner/errors/err_award_not_reconcilable_when_undisbursed
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Recon Org", "ein": "600000002",
                              "state_code": "CA", "service_regions": ["06051"]},
            course_code="HO-512")
        cycle, _app, award = setup_cycle_with_award(
            member, fiscal_year=2044, formula_pool_cents=100000,
            requested_formula_cents=40000, verify_match_cents=4000)
        assert award["disbursed_cents"] == 0

        resp = api.reconcile_award(award["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_AWARD_NOT_RECONCILABLE)
