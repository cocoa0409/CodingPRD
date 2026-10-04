"""Servicing transfers and subservicer oversight (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    set_clock,
    setup_counterparty_chain,
    create_approved_servicer,
    create_purchased_loan,
    create_demand_for_loan,
    appeal_demand,
    resolve_appeal,
    create_servicing_transfer_payload,
    create_subservicer_oversight_payload,
    make_servicer_officer_headers,
    get_loan,
    get_servicer,
    get_demand,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["gse_admin_headers"]
ADMIN_2 = TEST_USERS["gse_admin_2_headers"]


def _loan_version(api, loan_id):
    return api.get_loan(loan_id, ADMIN).json()["data"]["version"]


class TestTransferRequest:
    def test_servicing_transfer_strictly_future_effective_date(self, api):
        """PRD §3.8: "the `effective_date` must be strictly after the current
        logical time, else `ERR_TRANSFER_DATE_PAST`."
        PRD §3.8: "When the logical clock reaches an approved transfer's
        `effective_date`, the transfer moves `APPROVED → COMPLETED` and the
        loan's `servicer_id` is rewritten to `to_servicer_id`."

        Design: Difficulty/resource_temporal_overlap/servicing_transfer_strictly_future_effective_date
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        v2 = create_approved_servicer(legal_name="Second Servicing", servicer_number="V-2002")
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-TO2")
        officer = make_servicer_officer_headers(servicer["id"])
        # Effective date equal to now is rejected.
        resp = api.create_servicing_transfer(
            create_servicing_transfer_payload(
                loan["id"], v2["id"], effective_date="2026-09-01T00:00:00Z"
            ),
            officer,
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_DATE_PAST)
        # One second later is accepted and completes when the clock reaches it.
        transfer = validate_success(
            api.create_servicing_transfer(
                create_servicing_transfer_payload(
                    loan["id"], v2["id"], effective_date="2026-09-01T00:00:01Z"
                ),
                officer,
            ),
            expected_status=201,
        )
        assert transfer["status"] == "REQUESTED"
        approve = api.approve_servicing_transfer(
            transfer["id"], {"expected_loan_version": _loan_version(api, loan["id"])}, ADMIN_2
        )
        assert validate_success(approve)["status"] == "APPROVED"
        set_clock("2026-09-01T00:00:01Z")
        assert get_loan(loan["id"])["servicer_id"] == v2["id"]

    def test_transfer_at_future_date_completes_to_new_servicer(self, api):
        """PRD §3.8: "When the logical clock reaches an approved transfer's
        `effective_date`, the transfer moves `APPROVED → COMPLETED` and the
        loan's `servicer_id` is rewritten to `to_servicer_id` — unless the loan
        is in `REPURCHASED` status at that moment, in which case the transfer
        instead auto-transitions to `CANCELLED`."

        Design: Difficulty/resource_temporal_overlap/servicing_transfer_strictly_future_effective_date
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        v2 = create_approved_servicer(legal_name="Second Servicing", servicer_number="V-2002")
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-TO3")
        officer = make_servicer_officer_headers(servicer["id"])
        transfer = validate_success(
            api.create_servicing_transfer(
                create_servicing_transfer_payload(
                    loan["id"], v2["id"], effective_date="2026-10-01T00:00:00Z"
                ),
                officer,
            ),
            expected_status=201,
        )
        validate_success(
            api.approve_servicing_transfer(
                transfer["id"], {"expected_loan_version": _loan_version(api, loan["id"])}, ADMIN_2
            )
        )
        set_clock("2026-10-01T00:00:00Z")
        assert api.get_servicing_transfer(transfer["id"], ADMIN).json()["data"]["status"] == "COMPLETED"


class TestSegregationOfDuties:
    def test_error_segregation_of_duties_same_actor_approve(self, api):
        """PRD §3.8: "Segregation of duties requires that the acting
        administrator's `X-User-ID` differ from the `requester_id` recorded on
        the transfer; an administrator who is the same principal as the
        requesting officer is rejected with `ERR_SEGREGATION_OF_DUTIES` on both
        approval and rejection."

        Design: Corner/errors/error_segregation_of_duties_same_actor_approve
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        v2 = create_approved_servicer(legal_name="Second Servicing", servicer_number="V-2002")
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-SOD")
        officer = make_servicer_officer_headers(servicer["id"])
        transfer = validate_success(
            api.create_servicing_transfer(
                create_servicing_transfer_payload(
                    loan["id"], v2["id"], effective_date="2026-10-01T00:00:00Z"
                ),
                officer,
            ),
            expected_status=201,
        )
        lv = _loan_version(api, loan["id"])
        # Same principal (X-User-ID equals the requesting officer's id) is rejected.
        same_actor = build_user_headers(servicer["id"], "GseAdmin")
        resp = api.approve_servicing_transfer(
            transfer["id"], {"expected_loan_version": lv}, same_actor
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        # A different administrator approves.
        data = validate_success(
            api.approve_servicing_transfer(
                transfer["id"], {"expected_loan_version": lv}, ADMIN_2
            )
        )
        assert data["status"] == "APPROVED"


class TestTransferCancelOwnership:
    def test_transfer_cancel_restricted_to_requesting_officer(self, api):
        """PRD §3.8: "A pending transfer may also be withdrawn: the requesting
        officer — and only that officer, matched by comparing the caller's
        `X-User-ID` to the transfer's `requester_id`, failing with
        `ERR_FORBIDDEN_FOR_ROLE` otherwise — may cancel a `REQUESTED` transfer,
        moving it to `CANCELLED`."

        Design: Corner/roles/transfer_cancel_restricted_to_requesting_officer
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        v2 = create_approved_servicer(legal_name="Second Servicing", servicer_number="V-2002")
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-CAN")
        transfer = validate_success(
            api.create_servicing_transfer(
                create_servicing_transfer_payload(
                    loan["id"], v2["id"], effective_date="2026-10-01T00:00:00Z"
                ),
                make_servicer_officer_headers(servicer["id"]),
            ),
            expected_status=201,
        )
        resp = api.cancel_servicing_transfer(
            transfer["id"], make_servicer_officer_headers(v2["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        data = validate_success(
            api.cancel_servicing_transfer(
                transfer["id"], make_servicer_officer_headers(servicer["id"])
            )
        )
        assert data["status"] == "CANCELLED"


class TestOversightScore:
    def test_oversight_close_before_period_end_rejected(self, api):
        """PRD §3.8: "A record may close only once its `oversight_period_end`
        has been reached by the logical clock — earlier closure fails with
        `ERR_OVERSIGHT_PERIOD_NOT_ENDED` — moving it to `CLOSED` and again
        recomputing the master servicer's score."
        PRD §3.8: "The `oversight_score` itself starts at 100 and loses 5
        points for every pending issue and 2 points for every oversight
        finding."

        Design: Corner/validations/oversight_close_before_period_end_rejected
        """
        set_clock()
        v1 = create_approved_servicer()
        v2 = create_approved_servicer(legal_name="Sub Servicing", servicer_number="V-2002")
        record = validate_success(
            api.create_subservicer_oversight(
                create_subservicer_oversight_payload(
                    v1["id"], v2["id"],
                    oversight_period_start="2026-06-01T00:00:00Z",
                    oversight_period_end="2026-12-31T00:00:00Z",
                    findings_count=4,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        resp = api.close_subservicer_oversight(record["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_OVERSIGHT_PERIOD_NOT_ENDED)
        # While OPEN, 4 findings cost 2 points each: 100 - 8 = 92.
        assert get_servicer(v1["id"])["oversight_score"] == 92
        set_clock("2027-01-01T00:00:00Z")
        data = validate_success(api.close_subservicer_oversight(record["id"], ADMIN))
        assert data["status"] == "CLOSED"
        assert get_servicer(v1["id"])["oversight_score"] == 100

    def test_derived_field_reconciliation_servicer_score(self, api):
        """PRD §3.8: "The `oversight_score` itself starts at 100 and loses 5
        points for every pending issue and 2 points for every oversight
        finding. Pending issues are repurchase demands in `ISSUED` or
        `APPEALED` status on loans whose servicer of record is this servicer."
        PRD §3.9: "An `outcome` of `OVERTURNED` moves the demand to `WITHDRAWN`
        (terminal) and the finding to `OVERTURNED` (terminal), and the servicer
        oversight score is recomputed because a pending issue has left the
        books."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_servicer_score
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        assert get_servicer(servicer["id"])["oversight_score"] == 100
        loan, _ = create_purchased_loan(seller, servicer, agreement, loan_number="LN-REC")
        _, _, demand = create_demand_for_loan(loan, seller, "COLLATERAL")
        assert get_servicer(servicer["id"])["oversight_score"] == 95
        appeal_demand(demand, seller, "wrong collateral read")
        resolve_appeal(demand, "OVERTURNED")
        assert get_demand(demand["id"])["status"] == "WITHDRAWN"
        assert get_servicer(servicer["id"])["oversight_score"] == 100

    def test_oversight_score_threshold_ordering(self, api):
        """PRD §3.8: "Its `oversight_score` must be at least 60 — exactly 60
        passes — else `ERR_SUBSERVICER_OVERSIGHT_DEFICIENT`."
        PRD §3.8: "The `oversight_score` itself starts at 100 and loses 5
        points for every pending issue and 2 points for every oversight
        finding. Pending issues are repurchase demands in `ISSUED` or
        `APPEALED` status on loans whose servicer of record is this servicer."
        PRD §2.9: "This ordering matters operationally: for example, on
        transfer approval the oversight-deficiency rejection is evaluated
        before the stale-version rejection, so a caller receives
        `ERR_SUBSERVICER_OVERSIGHT_DEFICIENT` rather than `ERR_STALE_VERSION`
        when both would apply."

        Design: Difficulty/combinatorial_formula/oversight_score_threshold_ordering
        """
        from test_helpers import (
            create_pool_for,
            create_underwritten_loan,
            deliver_loan,
            issue_pool,
            open_audit,
            add_finding,
        )

        seller, servicer_v1, agreement, _ = setup_counterparty_chain(
            seller_overrides={"net_worth_cents": 900000000}
        )
        v2 = create_approved_servicer(legal_name="Servicer Two", servicer_number="V-2")
        # Nine purchased loans serviced by v2 in one pool.
        pool = create_pool_for(seller, agreement, target_balance_cents=400000000)
        loans = []
        for i in range(1, 10):
            loan = create_underwritten_loan(
                seller, v2, agreement,
                loan_number=f"B{i}",
                unpaid_principal_balance_cents=40000000,
                appraised_value_cents=50000000,
            )
            deliver_loan(loan, pool, seller)
            loans.append(loan)
        issue_pool(pool, seller)
        # A 10th purchased loan serviced by v1 (the transfer's subject).
        b10, _ = create_purchased_loan(seller, servicer_v1, agreement, loan_number="B10",
                                       unpaid_principal_balance_cents=40000000,
                                       appraised_value_cents=50000000)
        # Audit + 9 findings (one per v2 loan) + 8 demands issued.
        audit = open_audit(seller)
        findings = [add_finding(audit, loan, "COLLATERAL", "SIGNIFICANT") for loan in loans]
        validate_success(api.issue_findings(audit["id"], TEST_USERS["qc_auditor_headers"]))
        for finding in findings[:8]:
            validate_success(api.issue_repurchase_demand(finding["id"], ADMIN), expected_status=201)
        # 8 pending demands on v2 loans: score = 100 - 5*8 = 60 -> approval succeeds.
        assert get_servicer(v2["id"])["oversight_score"] == 60
        officer = make_servicer_officer_headers(servicer_v1["id"])
        t9 = validate_success(
            api.create_servicing_transfer(
                create_servicing_transfer_payload(
                    b10["id"], v2["id"], effective_date="2026-10-01T00:00:00Z"
                ),
                officer,
            ),
            expected_status=201,
        )
        approved = validate_success(
            api.approve_servicing_transfer(
                t9["id"], {"expected_loan_version": _loan_version(api, b10["id"])},
                TEST_USERS["gse_admin_2_headers"],
            )
        )
        assert approved["status"] == "APPROVED"
        # The 9th demand drops the score to 55.
        validate_success(api.issue_repurchase_demand(findings[8]["id"], ADMIN), expected_status=201)
        assert get_servicer(v2["id"])["oversight_score"] == 55
        t10 = validate_success(
            api.create_servicing_transfer(
                create_servicing_transfer_payload(
                    b10["id"], v2["id"], effective_date="2026-11-01T00:00:00Z"
                ),
                officer,
            ),
            expected_status=201,
        )
        resp = api.approve_servicing_transfer(
            t10["id"], {"expected_loan_version": _loan_version(api, b10["id"])},
            TEST_USERS["gse_admin_3_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SUBSERVICER_OVERSIGHT_DEFICIENT)
        assert api.get_servicing_transfer(t10["id"], ADMIN).json()["data"]["status"] == "REQUESTED"

    def test_oversight_deficiency_precedes_stale_version_rejection(self, api):
        """PRD §2.9: "This ordering matters operationally: for example, on
        transfer approval the oversight-deficiency rejection is evaluated
        before the stale-version rejection, so a caller receives
        `ERR_SUBSERVICER_OVERSIGHT_DEFICIENT` rather than `ERR_STALE_VERSION`
        when both would apply."
        PRD §3.8: "Its `oversight_score` must be at least 60 — exactly 60
        passes — else `ERR_SUBSERVICER_OVERSIGHT_DEFICIENT`."

        Design: Difficulty/combinatorial_formula/oversight_score_threshold_ordering
        """
        from test_helpers import (
            create_pool_for,
            create_underwritten_loan,
            deliver_loan,
            issue_pool,
            open_audit,
            add_finding,
        )

        seller, servicer_v1, agreement, _ = setup_counterparty_chain()
        v2 = create_approved_servicer(legal_name="Servicer Two", servicer_number="V-2")
        # Eight pending demands against v2 loans: score exactly 60.
        pool = create_pool_for(seller, agreement, target_balance_cents=400000000)
        loans = []
        for i in range(1, 9):
            loan = create_underwritten_loan(
                seller, v2, agreement,
                loan_number=f"C{i}",
                unpaid_principal_balance_cents=40000000,
                appraised_value_cents=50000000,
            )
            deliver_loan(loan, pool, seller)
            loans.append(loan)
        issue_pool(pool, seller)
        b10, _ = create_purchased_loan(seller, servicer_v1, agreement, loan_number="C9",
                                       unpaid_principal_balance_cents=40000000,
                                       appraised_value_cents=50000000)
        audit = open_audit(seller)
        findings = [add_finding(audit, loan, "COLLATERAL", "SIGNIFICANT") for loan in loans]
        validate_success(api.issue_findings(audit["id"], TEST_USERS["qc_auditor_headers"]))
        for finding in findings:
            validate_success(api.issue_repurchase_demand(finding["id"], ADMIN), expected_status=201)
        assert get_servicer(v2["id"])["oversight_score"] == 60
        # With a deliberately stale loan version AND a deficient score (after a
        # 9th demand), the compliance gate must fire first.
        ninth = create_underwritten_loan(
            seller, v2, agreement, loan_number="C10",
            unpaid_principal_balance_cents=40000000,
            appraised_value_cents=50000000,
        )
        pool2 = create_pool_for(seller, agreement, target_balance_cents=100000000)
        deliver_loan(ninth, pool2, seller)
        issue_pool(pool2, seller)
        f9 = add_finding(open_audit(seller), ninth, "COLLATERAL", "SIGNIFICANT")
        audit2 = api.get_qc_audit(f9["audit_id"], ADMIN).json()["data"]
        validate_success(api.issue_findings(audit2["id"], TEST_USERS["qc_auditor_headers"]))
        validate_success(api.issue_repurchase_demand(f9["id"], ADMIN), expected_status=201)
        assert get_servicer(v2["id"])["oversight_score"] == 55
        officer = make_servicer_officer_headers(servicer_v1["id"])
        t = validate_success(
            api.create_servicing_transfer(
                create_servicing_transfer_payload(
                    b10["id"], v2["id"], effective_date="2026-10-01T00:00:00Z"
                ),
                officer,
            ),
            expected_status=201,
        )
        stale_version = _loan_version(api, b10["id"]) - 1
        resp = api.approve_servicing_transfer(
            t["id"], {"expected_loan_version": stale_version},
            TEST_USERS["gse_admin_2_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SUBSERVICER_OVERSIGHT_DEFICIENT)
