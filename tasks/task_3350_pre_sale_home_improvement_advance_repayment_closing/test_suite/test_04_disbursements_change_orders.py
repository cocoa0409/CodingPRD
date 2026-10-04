"""Disbursement ledger administration, change orders, and advance-limit math."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    approve_disbursement,
    complete_engagement,
    create_change_order,
    create_disbursement,
    create_dispute,
    get_case,
    get_case_version,
    get_disbursement,
    setup_engagement_in_work,
    setup_engagement_scheduled,
    start_engagement,
    release_disbursement,
    reset_clock,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId as ERR

HOMEOWNER = TEST_USERS["homeowner_headers"]
UNDERWRITER = TEST_USERS["program_underwriter_headers"]


class TestDisbursementCreation:
    def test_disbursement_create_with_unknown_foreign_keys_returns_not_found(self, api):
        """PRD §2.8: "Resource existence comes third: any identifier that does
        not resolve yields `ERR_NOT_FOUND`."

        Design: Corner/entities/disbursement_create_body_foreign_keys_are_checked
        """
        reset_clock()
        resp = api_client.create_disbursement(
            {
                "concierge_case_id": "00000000-0000-4000-8000-000000000001",
                "improvement_project_id": "00000000-0000-4000-8000-000000000002",
                "vendor_engagement_id": "00000000-0000-4000-8000-000000000003",
                "amount_cents": 1_000_000,
                "kind": "DEPOSIT",
            },
            UNDERWRITER,
        )
        validate_error(resp, ERR.ERR_NOT_FOUND)


class TestDisbursementReleaseGuards:
    def test_release_without_approve_returns_invalid_state(self, api):
        """PRD §3.5: "Releasing a disbursement moves it from `APPROVED` to
        `RELEASED` and pays the vendor."
        PRD §2.8: "State appropriateness comes fourth: a resource in the wrong
        state for the requested operation yields `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/disbursement_release_without_approve_returns_invalid_state
        """
        ctx = setup_engagement_scheduled(plan_approved=True)
        disb = create_disbursement(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"]
        )
        resp = api_client.release_disbursement(disb["id"], UNDERWRITER)
        validate_error(resp, ERR.ERR_INVALID_STATE)

    def test_release_blocked_by_active_dispute_on_engagement(self, api):
        """PRD §3.5: "Release requires the engagement to be in `IN_WORK`,
        `COMPLETE_ON_TIME`, or `COMPLETE_LATE`, and requires that no dispute on
        that engagement is in `OPEN` or `IN_REVIEW` — an active dispute blocks
        the release with `ERR_DISPUTE_ACTIVE`."

        Design: Corner/validations/disbursement_release_blocked_by_active_dispute
        """
        ctx = setup_engagement_scheduled(plan_approved=True)
        disb = create_disbursement(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"]
        )
        approve_disbursement(disb["id"], ctx["case"]["id"])
        start_engagement(ctx["engagement"]["id"], ctx["vendor"])
        # Complete first: the engagement stays COMPLETE_ON_TIME when the dispute
        # is filed, so only the dispute gate can block the release.
        complete_engagement(ctx["engagement"]["id"], ctx["vendor"])
        create_dispute(ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"])
        resp = api_client.release_disbursement(disb["id"], UNDERWRITER)
        validate_error(resp, ERR.ERR_DISPUTE_ACTIVE)


class TestOccOnDisbursementApprove:
    def test_disbursement_approve_with_stale_version_returns_stale_version(self, api):
        """PRD §2.7: "Approving an improvement plan and approving a disbursement
        each require a non-optional request field, `expected_case_version`,
        carrying the client's last observed `version` of the target
        `ConciergeCase`."
        PRD §2.7: "the request is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_disbursement_approve
        """
        ctx = setup_engagement_scheduled(plan_approved=True)
        disb = create_disbursement(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"]
        )
        stale = get_case_version(ctx["case"]["id"]) - 1
        resp = api_client.approve_disbursement(
            disb["id"], {"expected_case_version": stale}, UNDERWRITER
        )
        validate_error(resp, ERR.ERR_STALE_VERSION)


class TestAdvanceLimitEnforcement:
    """advance_total_cents + amount_cents must not exceed advance_limit_cents."""

    def _setup_case_at_limit(self):
        """Project approved at exactly the limit: advance_total == limit."""
        ctx = setup_engagement_scheduled(
            project_overrides={
                "estimated_cost_cents": 15_000_000,
                "expected_sale_price_lift_cents": 5_000_000,
            },
            engagement_overrides={"agreed_price_cents": 15_000_000},
            plan_approved=True,
        )
        assert get_case(ctx["case"]["id"])["advance_total_cents"] == 15_000_000
        return ctx

    def test_approve_beyond_limit_returns_advance_limit_exceeded(self, api):
        """PRD §3.5: "The case's `advance_total_cents` plus the disbursement's
        `amount_cents` must not exceed the `advance_limit_cents`, failing with
        `ERR_ADVANCE_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_disbursement_approve
        """
        ctx = self._setup_case_at_limit()
        disb = create_disbursement(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"],
            amount_cents=1_000_000, kind="PROGRESS",
        )
        version = get_case_version(ctx["case"]["id"])
        resp = api_client.approve_disbursement(
            disb["id"], {"expected_case_version": version}, UNDERWRITER
        )
        validate_error(resp, ERR.ERR_ADVANCE_LIMIT_EXCEEDED)

    def test_approve_beyond_limit_leaves_ledger_and_disbursement_untouched(self, api):
        """PRD §3.5: "The case's `advance_total_cents` plus the disbursement's
        `amount_cents` must not exceed the `advance_limit_cents`, failing with
        `ERR_ADVANCE_LIMIT_EXCEEDED`."
        PRD §3.5: "On approval the `amount_cents` is added to the case's
        `advance_total_cents` and the case's `version` is incremented by 1."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_disbursement_approve
        """
        ctx = self._setup_case_at_limit()
        disb = create_disbursement(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"],
            amount_cents=1_000_000, kind="PROGRESS",
        )
        version = get_case_version(ctx["case"]["id"])
        resp = api_client.approve_disbursement(
            disb["id"], {"expected_case_version": version}, UNDERWRITER
        )
        validate_error(resp, ERR.ERR_ADVANCE_LIMIT_EXCEEDED)
        assert get_case(ctx["case"]["id"])["advance_total_cents"] == 15_000_000
        assert get_disbursement(disb["id"])["status"] == "REQUESTED"


class TestAdvanceLimitExactBoundary:
    """Boundary precision on the advance ledger cap of 15_000_000 cents."""

    def _setup_case_one_cent_below_limit(self):
        ctx = setup_engagement_scheduled(
            project_overrides={
                "estimated_cost_cents": 14_999_999,
                "expected_sale_price_lift_cents": 5_000_000,
            },
            engagement_overrides={"agreed_price_cents": 14_999_999},
            plan_approved=True,
        )
        assert get_case(ctx["case"]["id"])["advance_total_cents"] == 14_999_999
        return ctx

    def test_approve_to_exactly_the_limit_succeeds(self, api):
        """PRD §3.5: "The case's `advance_total_cents` plus the disbursement's
        `amount_cents` must not exceed the `advance_limit_cents`, failing with
        `ERR_ADVANCE_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/advance_limit_exact_boundary
        """
        ctx = self._setup_case_one_cent_below_limit()
        disb = create_disbursement(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"],
            amount_cents=1, kind="PROGRESS",
        )
        resp = api_client.approve_disbursement(
            disb["id"], {"expected_case_version": get_case_version(ctx["case"]["id"])},
            UNDERWRITER,
        )
        validate_success(resp)
        assert get_case(ctx["case"]["id"])["advance_total_cents"] == 15_000_000

    def test_approve_one_cent_over_the_limit_fails(self, api):
        """PRD §3.5: "The case's `advance_total_cents` plus the disbursement's
        `amount_cents` must not exceed the `advance_limit_cents`, failing with
        `ERR_ADVANCE_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/advance_limit_exact_boundary
        """
        ctx = self._setup_case_one_cent_below_limit()
        disb = create_disbursement(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"],
            amount_cents=2, kind="PROGRESS",
        )
        resp = api_client.approve_disbursement(
            disb["id"], {"expected_case_version": get_case_version(ctx["case"]["id"])},
            UNDERWRITER,
        )
        validate_error(resp, ERR.ERR_ADVANCE_LIMIT_EXCEEDED)


class TestAdvanceLedgerConservation:
    """approve adds exactly amount_cents; void subtracts exactly the same."""

    def _setup_with_requested_disbursement(self):
        ctx = setup_engagement_scheduled(plan_approved=True)
        disb = create_disbursement(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"]
        )
        return ctx, disb

    def test_approve_adds_amount_to_advance_total(self, api):
        """PRD §3.5: "On approval the `amount_cents` is added to the case's
        `advance_total_cents` and the case's `version` is incremented by 1."

        Design: Difficulty/compensating_invariant/advance_total_cents_conserved_on_void
        """
        ctx, disb = self._setup_with_requested_disbursement()
        before = get_case(ctx["case"]["id"])["advance_total_cents"]
        approve_disbursement(disb["id"], ctx["case"]["id"])
        after = get_case(ctx["case"]["id"])["advance_total_cents"]
        assert after - before == 5_000_000, (
            f"approve must add exactly amount_cents: {before} -> {after}"
        )

    def test_void_after_approve_restores_advance_total(self, api):
        """PRD §3.5: "Voiding from `APPROVED` moves it to `VOIDED` and reverses
        the ledger: the disbursement's `amount_cents` is subtracted from the
        case's `advance_total_cents`, so the advance ledger is conserved across
        the void path."

        Design: Difficulty/compensating_invariant/advance_total_cents_conserved_on_void
        """
        ctx, disb = self._setup_with_requested_disbursement()
        before = get_case(ctx["case"]["id"])["advance_total_cents"]
        approve_disbursement(disb["id"], ctx["case"]["id"])
        resp = api_client.void_disbursement(disb["id"], UNDERWRITER)
        validate_success(resp)
        after = get_case(ctx["case"]["id"])["advance_total_cents"]
        assert after == before, (
            f"void must restore the pre-approve ledger: {before} -> {after}"
        )
        assert get_disbursement(disb["id"])["status"] == "VOIDED"


class TestDerivedFieldReconciliation:
    def test_advance_total_correct_after_approve_and_after_void(self, api):
        """PRD §3.5: "On approval the `amount_cents` is added to the case's
        `advance_total_cents` and the case's `version` is incremented by 1."
        PRD §3.5: "Voiding from `APPROVED` moves it to `VOIDED` and reverses the
        ledger: the disbursement's `amount_cents` is subtracted from the case's
        `advance_total_cents`, so the advance ledger is conserved across the void
        path."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_advance_total_after_void
        """
        ctx = setup_engagement_scheduled(plan_approved=True)
        disb = create_disbursement(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"]
        )
        baseline = get_case(ctx["case"]["id"])["advance_total_cents"]
        approve_disbursement(disb["id"], ctx["case"]["id"])
        assert get_case(ctx["case"]["id"])["advance_total_cents"] == baseline + 5_000_000
        api_client.void_disbursement(disb["id"], UNDERWRITER)
        assert get_case(ctx["case"]["id"])["advance_total_cents"] == baseline


class TestChangeOrderHeadroom:
    def test_change_order_approve_beyond_limit_returns_advance_limit_exceeded(self, api):
        """PRD §3.5: "Approval from `PENDING` to `APPROVED` requires the project
        to be in `SCHEDULED` or `IN_WORK`, and requires headroom: the case's
        `advance_total_cents` plus the `delta_cents` must not exceed the
        `advance_limit_cents`, failing with `ERR_ADVANCE_LIMIT_EXCEEDED`."

        Design: Corner/validations/change_order_approve_blocked_by_advance_limit
        """
        ctx = setup_engagement_in_work(
            project_overrides={
                "estimated_cost_cents": 14_999_999,
                "expected_sale_price_lift_cents": 5_000_000,
            },
            engagement_overrides={"agreed_price_cents": 14_999_999},
        )
        # advance_total is now 14_999_999; +100_000 delta exceeds the 15_000_000 cap.
        change_order = create_change_order(
            ctx["project"]["id"], ctx["engagement"]["id"], ctx["vendor"],
            delta_cents=100_000, reason="SCOPE_CREEP",
        )
        resp = api_client.approve_change_order(change_order["id"], HOMEOWNER)
        validate_error(resp, ERR.ERR_ADVANCE_LIMIT_EXCEEDED)
