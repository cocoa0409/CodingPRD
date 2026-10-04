"""QC audits, findings, repurchase demands, and the appeal cycle (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    set_clock,
    setup_counterparty_chain,
    create_purchased_loan,
    create_draft_loan,
    create_demand_for_loan,
    create_upheld_demand,
    open_audit,
    add_finding,
    appeal_demand,
    resolve_appeal,
    get_demand,
    get_finding,
    get_loan,
    make_seller_officer_headers,
    make_servicer_officer_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["gse_admin_headers"]
QC_AUDITOR = TEST_USERS["qc_auditor_headers"]


class TestFindings:
    def test_qc_finding_requires_purchased_loan(self, api):
        """PRD §3.9: "The cited loan must be `PURCHASED`, else
        `ERR_LOAN_NOT_PURCHASED`, and it must belong to the seller under audit
        — the loan's seller must equal the audit's seller — else the same
        referential failure surfaces. The first finding moves the audit
        `OPEN → IN_REVIEW`, the finding itself begins in `IDENTIFIED`."

        Design: Difficulty/cross_entity_state_dependency/qc_finding_requires_purchased_loan
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        purchased, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-CE2")
        draft = create_draft_loan(seller, servicer, agreement, loan_number="LN-DRAFT")
        audit = open_audit(seller)
        resp = api.create_qc_finding(
            audit["id"],
            {"loan_id": draft["id"], "defect_category": "OTHER", "severity": "MINOR"},
            QC_AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_LOAN_NOT_PURCHASED)
        finding = add_finding(audit, purchased, "OTHER", "MINOR")
        assert finding["status"] == "IDENTIFIED"
        assert api.get_qc_audit(audit["id"], ADMIN).json()["data"]["status"] == "IN_REVIEW"

    def test_error_audit_not_issued_blocks_demand(self, api):
        """PRD §3.9: "The audit must already be in `FINDINGS_ISSUED` status,
        else `ERR_AUDIT_NOT_ISSUED`."

        Design: Corner/errors/error_audit_not_issued_blocks_demand
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-ANI")
        audit = open_audit(seller)
        finding = add_finding(audit, loan, "COLLATERAL", "MINOR")
        resp = api.issue_repurchase_demand(finding["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_ISSUED)
        assert get_finding(finding["id"])["status"] == "IDENTIFIED"

    def test_repurchase_amount_equals_upb_at_issuance(self, api):
        """PRD §3.9: "A successful issuance moves the finding `IDENTIFIED →
        REPURCHASE_ISSUED` and creates a `RepurchaseDemand` in `ISSUED` status
        whose `amount_cents` equals the loan's `unpaid_principal_balance_cents`
        at the moment of issuance, whose `loan_id` is denormalized from the
        finding, whose `appeal_deadline` is set 30 days after issuance, and
        whose `appeal_rounds_used` starts at 0."

        Design: Corner/calculations/repurchase_amount_equals_upb_at_issuance
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-RAMT")
        audit, finding, demand = create_demand_for_loan(loan, seller, "ELIGIBILITY")
        assert demand["amount_cents"] == 400000000
        # Issued at the 2026-09-01T00:00:00Z logical clock; deadline is +30 days.
        assert demand["appeal_deadline"] == "2026-10-01T00:00:00.000Z"
        assert demand["status"] == "ISSUED"
        assert demand["appeal_rounds_used"] == 0
        assert get_finding(finding["id"])["status"] == "REPURCHASE_ISSUED"

    def test_qc_finding_moves_audit_open_to_in_review_on_first_finding(self, api):
        """PRD §3.9: "The cited loan must be `PURCHASED`, else
        `ERR_LOAN_NOT_PURCHASED`, and it must belong to the seller under audit
        — the loan's seller must equal the audit's seller — else the same
        referential failure surfaces. The first finding moves the audit
        `OPEN → IN_REVIEW`, the finding itself begins in `IDENTIFIED`."

        Design: Difficulty/cross_entity_state_dependency/qc_finding_requires_purchased_loan
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        purchased, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-QC2")
        audit = open_audit(seller)
        assert api.get_qc_audit(audit["id"], ADMIN).json()["data"]["status"] == "OPEN"
        finding = add_finding(audit, purchased, "ELIGIBILITY", "SIGNIFICANT")
        assert finding["status"] == "IDENTIFIED"
        assert api.get_qc_audit(audit["id"], ADMIN).json()["data"]["status"] == "IN_REVIEW"


class TestDemandSettlement:
    def test_repurchase_settle_from_issued_returns_demand_not_upheld(self, api):
        """PRD §3.9: "A `SellerOfficer` settles a demand only when it is
        `UPHELD`, else `ERR_DEMAND_NOT_UPHELD`."

        Design: Corner/state_machines/repurchase_settle_from_issued_returns_demand_not_upheld
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-SETT")
        _, _, demand = create_demand_for_loan(loan, seller, "ELIGIBILITY")
        resp = api.settle_repurchase_demand(
            demand["id"], make_seller_officer_headers(seller["id"])
        )
        validate_error(resp, ApiErrorId.ERR_DEMAND_NOT_UPHELD)
        assert get_demand(demand["id"])["status"] == "ISSUED"
        assert get_loan(loan["id"])["status"] == "PURCHASED"

    def test_settle_leaves_unrelated_loan_and_audit_untouched(self, api):
        """PRD §3.9: "A passing settlement moves the demand to `SETTLED`
        (terminal), the finding to `REMEDIATED` (terminal), and the loan
        `PURCHASED → REPURCHASED` (terminal for the loan)."

        Design: Difficulty/transitive_cascade/demand_settle_cascade_demand_finding_loan
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan_a, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-T2A")
        loan_b, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-T2B")
        _, finding_a, demand_a = create_upheld_demand(loan_a, seller, "ELIGIBILITY")
        data = validate_success(
            api.settle_repurchase_demand(
                demand_a["id"], make_seller_officer_headers(seller["id"])
            )
        )
        assert data["status"] == "SETTLED"
        assert get_loan(loan_a["id"])["status"] == "REPURCHASED"
        # The seller's other purchased loan is unaffected by the settle.
        assert get_loan(loan_b["id"])["status"] == "PURCHASED"

    def test_demand_settle_cascade_demand_finding_loan(self, api):
        """PRD §3.9: "A passing settlement moves the demand to `SETTLED`
        (terminal), the finding to `REMEDIATED` (terminal), and the loan
        `PURCHASED → REPURCHASED` (terminal for the loan)."
        PRD §3.9: "Before anything changes, the system runs the seller
        financial check: the sum of `amount_cents` across all of this seller's
        demands currently in `UPHELD` status — a sum that includes the demand
        being settled — must not exceed the seller's `net_worth_cents`."

        Design: Difficulty/transitive_cascade/demand_settle_cascade_demand_finding_loan
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-T2")
        _, finding, demand = create_upheld_demand(loan, seller, "ELIGIBILITY")
        data = validate_success(
            api.settle_repurchase_demand(
                demand["id"], make_seller_officer_headers(seller["id"])
            )
        )
        assert data["status"] == "SETTLED"
        assert get_finding(finding["id"])["status"] == "REMEDIATED"
        assert get_loan(loan["id"])["status"] == "REPURCHASED"

    def test_insufficient_seller_funds_blocks_settle(self, api):
        """PRD §3.9: "Before anything changes, the system runs the seller
        financial check: the sum of `amount_cents` across all of this seller's
        demands currently in `UPHELD` status — a sum that includes the demand
        being settled — must not exceed the seller's `net_worth_cents`.
        Equality is allowed; exceeding the net worth by even one cent rejects
        the settlement with `ERR_INSUFFICIENT_SELLER_FUNDS` and leaves all
        state untouched."

        Design: Corner/validations/insufficient_seller_funds_blocks_settle
        """
        # Seller net worth 250,000,000 < 400,000,000 demand amount.
        seller, servicer, agreement, _ = setup_counterparty_chain(
            seller_overrides={
                "legal_name": "Thin Seller",
                "seller_number": "S-THIN",
                "net_worth_cents": 250000000,
            }
        )
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-THIN")
        _, _, demand = create_upheld_demand(loan, seller, "ELIGIBILITY")
        resp = api.settle_repurchase_demand(
            demand["id"], make_seller_officer_headers(seller["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SELLER_FUNDS)
        assert get_demand(demand["id"])["status"] == "UPHELD"
        assert get_loan(loan["id"])["status"] == "PURCHASED"


class TestAppealCycle:
    def test_repurchase_appeal_cycle_exhausts_after_two_rounds(self, api):
        """PRD §3.9: "The seller may appeal a demand that is `ISSUED` or
        `UPHELD` — appealing from any other status fails with
        `ERR_INVALID_STATE`."
        PRD §3.9: "Each demand affords at most two appeals in total; a third
        attempt fails with `ERR_APPEAL_ROUNDS_EXHAUSTED`."
        PRD §3.9: "An `outcome` of `UPHELD` moves the demand to `UPHELD` and
        the finding to `UPHELD`."

        Design: Difficulty/non_linear_state_machine/repurchase_appeal_cycle_exhausts_after_two_rounds
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-RP")
        _, finding, demand = create_demand_for_loan(loan, seller, "COLLATERAL")

        # Appeal 1 from ISSUED, resolved UPHELD.
        appeal_demand(demand, seller, "appraisal review pending")
        resolve_appeal(demand, "UPHELD")
        # Appeal 2 from UPHELD, resolved UPHELD.
        appeal_demand(demand, seller, "second look with new comps")
        resolve_appeal(demand, "UPHELD")
        assert get_demand(demand["id"])["appeal_rounds_used"] == 2

        # Appeal 3 exhausts the budget.
        resp = api.appeal_repurchase_demand(
            demand["id"],
            {"appeal_reason": "third attempt"},
            make_seller_officer_headers(seller["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_ROUNDS_EXHAUSTED)
        assert get_demand(demand["id"])["status"] == "UPHELD"
        assert get_finding(finding["id"])["status"] == "UPHELD"

    def test_repurchase_appeal_from_upheld_stays_within_original_window(self, api):
        """PRD §3.9: "Note the window runs from issuance and is not extended by
        an early upheld ruling, so an appeal of an `UPHELD` demand is still
        measured against the original deadline."
        PRD §3.9: "An `UPHELD` finding may be appealed again, subject to the
        same window and the same two-appeal budget."

        Design: Difficulty/non_linear_state_machine/repurchase_appeal_cycle_exhausts_after_two_rounds
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-RP2")
        _, finding, demand = create_demand_for_loan(loan, seller, "COLLATERAL")
        appeal_demand(demand, seller, "first appeal")
        resolve_appeal(demand, "UPHELD")
        # The UPHELD demand can be appealed again within the original window.
        second = appeal_demand(demand, seller, "second appeal from upheld")
        assert second["status"] == "APPEALED"
        assert second["appeal_rounds_used"] == 2
        assert get_finding(finding["id"])["status"] == "APPEALED"

    def test_appeal_temporal_window_beats_rounds_constraint(self, api):
        """PRD §3.9: "The appeal must arrive on or before the
        `appeal_deadline`; later appeals fail with `ERR_APPEAL_WINDOW_CLOSED`."
        PRD §2.9: "Only then do the business gates run, in this order: temporal
        gates (appeal window, transfer date, oversight period end, agreement
        effectiveness, pool issue date), referential gates (pool-to-loan seller
        and agreement matching, finding-loan-to-audit-seller matching),
        compliance gates (relief-tier bars, segregation of duties,
        oversight-score floor), fiscal gates (pool capacity, seller funds), and
        finally constraint gates (appeal rounds, pool non-empty, approval
        thresholds, loan eligibility)."

        Design: Difficulty/priority_pair_validation_conflict/appeal_temporal_window_beats_rounds_constraint
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-P2")
        _, _, demand = create_demand_for_loan(loan, seller, "ELIGIBILITY")
        appeal_demand(demand, seller, "first appeal")
        resolve_appeal(demand, "UPHELD")
        appeal_demand(demand, seller, "second appeal")
        resolve_appeal(demand, "UPHELD")
        # Demand issued at 2026-09-01T00:00:00Z; deadline 2026-10-01T00:00:00Z.
        # Advance the clock past the deadline; the third appeal violates both
        # the window and the rounds cap — the temporal gate wins.
        set_clock("2026-10-02T00:00:00Z")
        resp = api.appeal_repurchase_demand(
            demand["id"],
            {"appeal_reason": "too late and out of rounds"},
            make_seller_officer_headers(seller["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)
        after = get_demand(demand["id"])
        assert after["status"] == "UPHELD"
        assert after["appeal_rounds_used"] == 2

    def test_appeal_on_or_before_deadline_is_accepted(self, api):
        """PRD §3.9: "The appeal must arrive on or before the
        `appeal_deadline`; later appeals fail with `ERR_APPEAL_WINDOW_CLOSED`."
        PRD §3.9: "Note the window runs from issuance and is not extended by an
        early upheld ruling, so an appeal of an `UPHELD` demand is still
        measured against the original deadline."

        Design: Difficulty/priority_pair_validation_conflict/appeal_temporal_window_beats_rounds_constraint
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-WIN")
        _, _, demand = create_demand_for_loan(loan, seller, "ELIGIBILITY")
        # Demand issued at 2026-09-01T00:00:00Z, deadline 2026-10-01T00:00:00Z.
        # An appeal lodged exactly at the deadline is accepted.
        set_clock("2026-10-01T00:00:00Z")
        data = validate_success(
            api.appeal_repurchase_demand(
                demand["id"],
                {"appeal_reason": "at the deadline"},
                make_seller_officer_headers(seller["id"]),
            )
        )
        assert data["status"] == "APPEALED"
        assert data["appeal_rounds_used"] == 1


class TestAuditClosure:
    def test_audit_close_blocked_until_findings_terminal(self, api):
        """PRD §3.9: "Moving `FINDINGS_ISSUED → CLOSED` requires every finding
        of the audit to be in a terminal finding state — `UPHELD` with its
        demand settled or withdrawn, `OVERTURNED`, or `REMEDIATED` — and any
        lingering non-terminal finding blocks closure with
        `ERR_AUDIT_HAS_OPEN_FINDINGS`."

        Design: Corner/state_machines/audit_close_blocked_until_findings_terminal
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-ACLS")
        audit, finding, demand = create_demand_for_loan(loan, seller, "COLLATERAL", "MODERATE")
        appeal_demand(demand, seller, "disputing severity")
        # Finding APPEALED is non-terminal: close is blocked.
        resp = api.close_qc_audit(audit["id"], QC_AUDITOR)
        validate_error(resp, ApiErrorId.ERR_AUDIT_HAS_OPEN_FINDINGS)
        # Resolve UPHELD then settle: finding REMEDIATED, close succeeds.
        resolve_appeal(demand, "UPHELD")
        validate_success(
            api.settle_repurchase_demand(
                demand["id"], make_seller_officer_headers(seller["id"])
            )
        )
        assert get_finding(finding["id"])["status"] == "REMEDIATED"
        data = validate_success(api.close_qc_audit(audit["id"], QC_AUDITOR))
        assert data["status"] == "CLOSED"


class TestQcRoleDenials:
    def test_qc_auditor_cannot_issue_demands_or_record_payments(self, api):
        """PRD §4: "POST /gse/qc-findings/{findingId}/issue-demand — GseAdmin";
        "POST /gse/payment-events — ServicerOfficer".
        PRD §2.1: "When a caller attempts an operation outside the permissions
        of their declared role, or fails an ownership check tied to their
        identity, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."

        Design: Corner/roles/qc_auditor_cannot_issue_demands_or_record_payments
        """
        from test_helpers import create_payment_event_payload

        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-RBC")
        audit = open_audit(seller)
        finding = add_finding(audit, loan, "COLLATERAL", "MINOR")
        validate_success(api.issue_findings(audit["id"], QC_AUDITOR))
        resp1 = api.issue_repurchase_demand(finding["id"], QC_AUDITOR)
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        resp2 = api.create_payment_event(
            create_payment_event_payload(loan["id"], due_date="2026-10-01T00:00:00Z"),
            QC_AUDITOR,
        )
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
