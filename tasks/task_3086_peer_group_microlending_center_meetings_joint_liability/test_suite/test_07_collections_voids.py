"""Collections waterfall, savings floor, and void invariants.

Covers difficulty instances under compensating_invariant (ledger reversal) and
corner instances for the waterfall buckets, the savings floor, collections on a
closed meeting, attendance upsert, double-void, and the group dissolve guard.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_meeting,
    create_attendance_payload,
    disburse_member,
    get_success_data,
    make_center_manager_headers,
    open_meeting,
    post_collection,
    schedule_meeting,
    set_clock,
    setup_active_group,
    setup_open_meeting_with_loan,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
BM = TEST_USERS["branch_manager_headers"]
FO = TEST_USERS["field_officer_headers"]


class TestCollectionWaterfall:
    def test_savings_floor_200_beats_two_percent_of_installment(self, api):
        """PRD §3.4: "The mandatory savings per collection,
        `savings_required_cents`, is the larger of 200 cents and a percentage of
        the weekly installment rounded half up: 2% at rung 1"."
        PRD §3.5: "A collection whose `amount_cents` is less than
        `savings_required_cents` plus 1 is refused outright with
        `ERR_COLLECTION_BELOW_SAVINGS_MINIMUM` — every repayment must fund the
        savings deposit and retire at least one cent of debt."

        Design: Corner/calculations/savings_floor_200_beats_two_percent_of_installment
        """
        ctx = setup_open_meeting_with_loan(prefix="savings-floor")
        assert ctx["loan"]["weekly_installment_cents"] == 4567
        assert ctx["loan"]["savings_required_cents"] == 200

        under = api.post_collection(
            ctx["meeting"]["id"],
            {"member_id": ctx["applicant"]["id"], "loan_id": ctx["loan"]["id"],
             "amount_cents": 200},
            make_center_manager_headers(ctx["manager"]["id"]),
        )
        validate_error(
            under, ApiErrorId.ERR_COLLECTION_BELOW_SAVINGS_MINIMUM, expected_status=422
        )

        ok = api.post_collection(
            ctx["meeting"]["id"],
            {"member_id": ctx["applicant"]["id"], "loan_id": ctx["loan"]["id"],
             "amount_cents": 4_768},
            make_center_manager_headers(ctx["manager"]["id"]),
        )
        txn = validate_success(ok, expected_status=201)
        assert txn["savings_applied_cents"] == 200
        # bucket 3 is capped at one weekly installment; the extra cent is
        # bucket-4 prepayment (installment 4567 + prepayment 1)
        assert txn["installment_applied_cents"] == 4_567
        assert txn["principal_applied_cents"] == 4_568

    def test_collection_amount_at_savings_minimum_exactly_is_refused(self, api):
        """PRD §3.5: "A collection whose `amount_cents` is less than
        `savings_required_cents` plus 1 is refused outright with
        `ERR_COLLECTION_BELOW_SAVINGS_MINIMUM` — every repayment must fund the
        savings deposit and retire at least one cent of debt."

        Design: Corner/validations/collection_amount_exactly_at_floor_passes

        With savings_required_cents = 200 (the floor beats 2% of the 4567
        installment), the boundary amount 200 = savings + 0 retires no debt and
        is refused; 201 = savings + 1 is the smallest legal collection.
        """
        ctx = setup_open_meeting_with_loan(prefix="floor-exact")
        cm = make_center_manager_headers(ctx["manager"]["id"])
        at_floor = api.post_collection(
            ctx["meeting"]["id"],
            {"member_id": ctx["applicant"]["id"], "loan_id": ctx["loan"]["id"],
             "amount_cents": 200},
            make_center_manager_headers(ctx["manager"]["id"]),
        )
        validate_error(
            at_floor, ApiErrorId.ERR_COLLECTION_BELOW_SAVINGS_MINIMUM, expected_status=422
        )
        above_floor = api.post_collection(
            ctx["meeting"]["id"],
            {"member_id": ctx["applicant"]["id"], "loan_id": ctx["loan"]["id"],
             "amount_cents": 201},
            cm,
        )
        txn = validate_success(above_floor, expected_status=201)
        assert txn["savings_applied_cents"] == 200
        assert txn["principal_applied_cents"] == 1

    def test_waterfall_prepayment_bucket_and_on_time_counting(self, api):
        """PRD §3.5: "**Prepayment.** Any remainder retires outstanding
        principal directly, capped at the outstanding left after buckets 2 and
        3."
        PRD §3.5: "The recorded `installment_applied_cents` is the sum applied
        in buckets 2 and 3, and the recorded `principal_applied_cents` adds the
        bucket-4 prepayment to it. An installment counts toward
        `installments_on_time` only when the collection's logical posting time
        is at or before that installment's due date".

        Design: Corner/calculations/waterfall_prepayment_bucket_and_on_time_counting
        """
        ctx = setup_open_meeting_with_loan(prefix="waterfall")
        txn = post_collection(
            ctx["meeting"]["id"], ctx["manager"],
            ctx["applicant"]["id"], ctx["loan"]["id"], 6_000,
        )
        assert txn["savings_applied_cents"] == 200
        assert txn["installment_applied_cents"] == 4_567
        assert txn["principal_applied_cents"] == 5_800, (
            f"4567 installment + 1233 prepayment: {txn['principal_applied_cents']}"
        )
        loan_now = get_success_data(api.get_loan(ctx["loan"]["id"], PA))
        assert loan_now["principal_outstanding_cents"] == 103_808
        assert loan_now["installments_on_time"] == 1, (
            "prepayment does not consume future installments"
        )


class TestVoidInvariant:
    def test_post_and_void_leave_loan_outstanding_unchanged(self, api):
        """PRD §3.7: "A void is an exact ledger reversal, not an approximation:
        the loan's `principal_outstanding_cents` grows back by the transaction's
        `principal_applied_cents`, the installment counters are decremented by
        the amounts that transaction had applied, the savings account's
        `balance_cents` is debited by the transaction's `savings_applied_cents`,
        and the member's `credit_score` is recomputed."

        Design: Difficulty/compensating_invariant/post_and_void_leave_loan_outstanding_unchanged
        """
        ctx = setup_open_meeting_with_loan(prefix="void-invariant")
        txn = post_collection(
            ctx["meeting"]["id"], ctx["manager"],
            ctx["applicant"]["id"], ctx["loan"]["id"], 4_768,
        )
        loan_posted = get_success_data(api.get_loan(ctx["loan"]["id"], PA))
        assert loan_posted["principal_outstanding_cents"] == 105_040
        accounts, _ = validate_paginated(
            api.get_member_savings_account(ctx["applicant"]["id"], PA)
        )
        assert accounts[0]["balance_cents"] == 200

        voided = get_success_data(api.void_repayment_transaction(txn["id"], BM))
        assert voided["status"] == "VOIDED"
        loan_restored = get_success_data(api.get_loan(ctx["loan"]["id"], PA))
        assert loan_restored["principal_outstanding_cents"] == 109_608
        assert loan_restored["installments_on_time"] == 0, (
            "counter reversal, not just balance"
        )
        accounts_after, _ = validate_paginated(
            api.get_member_savings_account(ctx["applicant"]["id"], PA)
        )
        assert accounts_after[0]["balance_cents"] == 0

    def test_post_and_void_leave_loan_outstanding_unchanged_credit_and_counters(self, api):
        """PRD §3.7: "A void is an exact ledger reversal, not an approximation:
        the loan's `principal_outstanding_cents` grows back by the transaction's
        `principal_applied_cents`, the installment counters are decremented by
        the amounts that transaction had applied, the savings account's
        `balance_cents` is debited by the transaction's `savings_applied_cents`,
        and the member's `credit_score` is recomputed."
        PRD §3.4: "A member mid-cycle with no activity at all therefore reads
        720 provisionally."

        Design: Difficulty/compensating_invariant/post_and_void_leave_loan_outstanding_unchanged
        """
        ctx = setup_open_meeting_with_loan(prefix="void-score")
        txn = post_collection(
            ctx["meeting"]["id"], ctx["manager"],
            ctx["applicant"]["id"], ctx["loan"]["id"], 4_768,
        )
        loan_posted = get_success_data(api.get_loan(ctx["loan"]["id"], PA))
        assert loan_posted["installments_on_time"] == 1

        get_success_data(api.void_repayment_transaction(txn["id"], BM))
        loan_after = get_success_data(api.get_loan(ctx["loan"]["id"], PA))
        assert loan_after["principal_outstanding_cents"] == 109_608
        assert loan_after["installments_on_time"] == 0
        member_after = get_success_data(api.get_member(ctx["applicant"]["id"], PA))
        assert member_after["credit_score"] == 720, (
            "after the reversal the member again has no applied activity"
        )

    def test_void_on_already_voided_transaction_returns_not_posted(self, api):
        """PRD §3.7: "A `BranchManager` may void a transaction while it is
        `POSTED` (`ERR_TXN_NOT_POSTED`)".

        Design: Corner/errors/void_on_already_voided_transaction_returns_not_posted
        """
        ctx = setup_open_meeting_with_loan(prefix="double-void")
        txn = post_collection(
            ctx["meeting"]["id"], ctx["manager"],
            ctx["applicant"]["id"], ctx["loan"]["id"], 4_768,
        )
        get_success_data(api.void_repayment_transaction(txn["id"], BM))
        response = api.void_repayment_transaction(txn["id"], BM)
        validate_error(response, ApiErrorId.ERR_TXN_NOT_POSTED, expected_status=409)
        loan_now = get_success_data(api.get_loan(ctx["loan"]["id"], PA))
        assert loan_now["principal_outstanding_cents"] == 109_608, (
            "the ledger is not double-reversed"
        )


class TestCollectionStateGuards:
    def test_collections_rejected_on_closed_meeting(self, api):
        """PRD §3.5: "Collections are the in-person repayments, also taken only
        while the meeting is `OPEN`."
        PRD §2.8 item 5 names `ERR_MEETING_NOT_OPEN` as the meeting-open state
        error: "the target resource must be in the source state the operation
        requires (for example, an application in `DRAFT` to submit, a meeting in
        `OPEN` to collect ...)".

        Design: Corner/endpoints/collections_rejected_on_closed_meeting
        """
        ctx = setup_open_meeting_with_loan(prefix="closed-collect")
        close_meeting(ctx["meeting"]["id"], ctx["manager"])
        response = api.post_collection(
            ctx["meeting"]["id"],
            {"member_id": ctx["applicant"]["id"], "loan_id": ctx["loan"]["id"],
             "amount_cents": 4_768},
            make_center_manager_headers(ctx["manager"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_MEETING_NOT_OPEN, expected_status=409)


class TestAttendanceUpsert:
    def test_attendance_upsert_changes_row_not_duplicate(self, api):
        """PRD §3.5: "While `OPEN`, the manager records attendance rows
        upsert-style with `member_id` and a boolean `present` (true marking the
        member `PRESENT`, false `ABSENT`)".

        Design: Corner/endpoints/attendance_upsert_changes_row_not_duplicate
        """
        ctx = setup_active_group(prefix="att-upsert")
        meeting = schedule_meeting(ctx["center"]["id"], ctx["manager"])
        open_meeting(meeting["id"], ctx["manager"])
        cm = make_center_manager_headers(ctx["manager"]["id"])
        p1 = ctx["peers"][0]
        get_success_data(
            api.record_attendance(meeting["id"], create_attendance_payload(p1["id"], True), cm)
        )
        get_success_data(
            api.record_attendance(meeting["id"], create_attendance_payload(p1["id"], False), cm)
        )
        rows, _ = validate_paginated(api.list_meeting_attendance(meeting["id"], PA))
        p1_rows = [r for r in rows if r["member_id"] == p1["id"]]
        assert len(p1_rows) == 1, "attendance is upserted, not duplicated"
        assert p1_rows[0]["present"] is False


class TestDissolveGuard:
    def test_dissolve_group_with_active_loan_rejected(self, api):
        """PRD §3.6: "no member may hold a loan in `ACTIVE` or `DELINQUENT`
        (`ERR_GROUP_HAS_ACTIVE_LOANS`)."

        Design: Corner/state_machines/dissolve_group_with_active_loan_rejected
        """
        ctx = setup_active_group(prefix="dissolve-guard")
        disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])
        response = api.dissolve_peer_group(ctx["group"]["id"], FO)
        validate_error(response, ApiErrorId.ERR_GROUP_HAS_ACTIVE_LOANS, expected_status=409)
        group_now = get_success_data(api.get_peer_group(ctx["group"]["id"], PA))
        assert group_now["status"] == "ACTIVE"
