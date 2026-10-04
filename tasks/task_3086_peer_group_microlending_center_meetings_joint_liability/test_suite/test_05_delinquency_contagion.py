"""Delinquency sweeps, cure cycles, and joint-liability contagion.

Covers difficulty instances under boundary_precision_check,
non_linear_state_machine (loan cure cycle), transitive_cascade (delinquency
contagion), and the corner sweep-ordering instance.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_application,
    close_meeting,
    disburse_member,
    draft_application,
    get_success_data,
    make_center_manager_headers,
    make_member_headers,
    mark_attendance,
    open_meeting,
    post_collection,
    schedule_meeting,
    set_clock,
    setup_active_group,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]


class TestDelinquencyBoundary:
    def test_delinquency_day_7_vs_day_8_boundary(self, api):
        """PRD §3.6: "For each loan, while its `next_due_date` is at least 8 days
        past due, the sweep consumes that due — `installments_missed` increments
        and `next_due_date` advances by 7 days — and the first consumed due on
        an `ACTIVE` loan flips it to `DELINQUENT`. The boundary is exact: a due
        date 7 days past leaves the loan `ACTIVE`; at 8 days it flips."

        Design: Difficulty/boundary_precision_check/delinquency_day_7_vs_day_8_boundary
        """
        ctx = setup_active_group(prefix="day78")
        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])

        set_clock("2026-09-15T00:00:00Z")  # first due (Sep 8) is 7 days past
        day7 = get_success_data(api.get_loan(loan["id"], PA))
        assert day7["status"] == "ACTIVE", "7 days past due stays ACTIVE"
        assert day7["installments_missed"] == 0

        set_clock("2026-09-16T00:00:00Z")  # exactly 8 days past
        day8 = get_success_data(api.get_loan(loan["id"], PA))
        assert day8["status"] == "DELINQUENT", "8 days past due flips to DELINQUENT"
        assert day8["installments_missed"] == 1
        assert day8["next_due_date"] == "2026-09-15T00:00:00Z", (
            "the consumed due advances next_due_date by 7 days"
        )

    def test_delinquency_day_7_vs_day_8_boundary_default_29_vs_30(self, api):
        """PRD §3.6: "After the consumption loop, a `DELINQUENT` loan whose
        oldest consumed-but-unpaid due has reached at least 30 days past due
        hardens into `DEFAULTED`; at 29 days it remains `DELINQUENT`."

        Design: Difficulty/boundary_precision_check/delinquency_day_7_vs_day_8_boundary
        """
        ctx = setup_active_group(prefix="day2930")
        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])

        set_clock("2026-10-07T00:00:00Z")  # oldest due (Sep 8) is 29 days past
        day29 = get_success_data(api.get_loan(loan["id"], PA))
        assert day29["status"] == "DELINQUENT", "29 days remains DELINQUENT"

        set_clock("2026-10-08T00:00:00Z")  # exactly 30 days past
        day30 = get_success_data(api.get_loan(loan["id"], PA))
        assert day30["status"] == "DEFAULTED", "30 days hardens into DEFAULTED"


class TestSweepMultipleDuesAndDefault:
    def test_sweep_consumes_multiple_dues_in_chronological_order(self, api):
        """PRD §3.6: "After the consumption loop, a `DELINQUENT` loan whose
        oldest consumed-but-unpaid due has reached at least 30 days past due
        hardens into `DEFAULTED`; at 29 days it remains `DELINQUENT`."
        PRD §3.6: "When a loan reaches `DEFAULTED`, the member becomes
        `BLACKLISTED` — whether they were `ACTIVE_BORROWER` or `DELINQUENT` —
        their savings account is frozen `OPEN → FROZEN`, a `FINAL` bureau report
        is filed".

        Design: Corner/calculations/sweep_consumes_multiple_dues_in_chronological_order
        """
        ctx = setup_active_group(prefix="sweep-multi")
        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])

        set_clock("2026-10-08T00:00:00Z")  # oldest due (Sep 8) is 30 days past
        loan_now = get_success_data(api.get_loan(loan["id"], PA))
        assert loan_now["status"] == "DEFAULTED"
        assert loan_now["installments_missed"] == 4, (
            "dues of Sep 8, 15, 22 and 29 are consumed (each at least 8 days "
            "past); the Oct 6 due is only 2 days past"
        )
        assert loan_now["next_due_date"] == "2026-10-06T00:00:00Z"

        member_now = get_success_data(api.get_member(ctx["applicant"]["id"], PA))
        assert member_now["status"] == "BLACKLISTED"

        accounts, _ = validate_paginated(
            api.get_member_savings_account(ctx["applicant"]["id"], PA)
        )
        assert accounts[0]["status"] == "FROZEN"

        reports, _ = validate_paginated(api.list_loan_bureau_reports(loan["id"], PA))
        assert any(r["report_type"] == "FINAL" for r in reports), (
            "a FINAL bureau report is filed at default"
        )


class TestCureCycle:
    def test_loan_delinquency_cure_cycle_restores_active(self, api):
        """PRD §3.6: "Cure runs the chain in reverse. When a collection's
        arrears bucket retires every consumed unpaid installment, the loan moves
        `DELINQUENT → ACTIVE`; once the member holds no remaining `DELINQUENT`
        loan, the member moves `DELINQUENT → ACTIVE_BORROWER` with
        `cured_delinquency_count` incremented — the counter that later selects
        the rehabilitated ladder variant and the penalty rate; and the group's
        `delinquent_loan_count` decrements, returning the group `RESTRICTED →
        ACTIVE` and lifting the ladder freeze the moment the count reaches
        zero."
        PRD §3.5: "**Arrears.** What remains applies to consumed-but-unpaid
        installments, oldest due date first."

        Design: Difficulty/non_linear_state_machine/loan_delinquency_cure_cycle_restores_active
        """
        ctx = setup_active_group(prefix="cure")
        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])
        set_clock("2026-09-17T00:00:00Z")  # first due is 9 days past

        loan_before = get_success_data(api.get_loan(loan["id"], PA))
        assert loan_before["status"] == "DELINQUENT"
        member_before = get_success_data(api.get_member(ctx["applicant"]["id"], PA))
        assert member_before["status"] == "DELINQUENT"

        meeting = schedule_meeting(
            ctx["center"]["id"], ctx["manager"],
            start="2026-09-22T10:00:00Z", end="2026-09-22T11:00:00Z",
        )
        open_meeting(meeting["id"], ctx["manager"])
        # 200 savings + 4567 arrears + 4567 current installment
        txn = post_collection(
            meeting["id"], ctx["manager"], ctx["applicant"]["id"], loan["id"], 9_334
        )
        assert txn["savings_applied_cents"] == 200
        assert txn["installment_applied_cents"] == 9_134, (
            f"arrears 4567 + current 4567: {txn['installment_applied_cents']}"
        )

        loan_after = get_success_data(api.get_loan(loan["id"], PA))
        assert loan_after["status"] == "ACTIVE", "covering all arrears cures the loan"
        member_after = get_success_data(api.get_member(ctx["applicant"]["id"], PA))
        assert member_after["status"] == "ACTIVE_BORROWER"
        assert member_after["cured_delinquency_count"] == 1
        group_after = get_success_data(api.get_peer_group(ctx["group"]["id"], PA))
        assert group_after["delinquent_loan_count"] == 0
        assert group_after["status"] == "ACTIVE"

    def test_loan_delinquency_cure_cycle_restores_active_group_recovers(self, api):
        """PRD §3.6: "Hop two: the member's group's `delinquent_loan_count` —
        the count of group members' loans in `DELINQUENT` or `DEFAULTED` —
        increments, and since a group is restricted whenever that count is at
        least 1 (exactly one delinquent loan is enough), an `ACTIVE` group moves
        to `RESTRICTED`."
        PRD §3.6: "Cure runs the chain in reverse. When a collection's arrears
        bucket retires every consumed unpaid installment, the loan moves
        `DELINQUENT → ACTIVE`".

        Design: Difficulty/non_linear_state_machine/loan_delinquency_cure_cycle_restores_active
        """
        ctx = setup_active_group(prefix="cure-cycle")
        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])
        group_before = get_success_data(api.get_peer_group(ctx["group"]["id"], PA))
        assert group_before["status"] == "ACTIVE"

        set_clock("2026-09-17T00:00:00Z")
        group_mid = get_success_data(api.get_peer_group(ctx["group"]["id"], PA))
        assert group_mid["status"] == "RESTRICTED", (
            "the first consumed due flips the group RESTRICTED"
        )
        assert group_mid["delinquent_loan_count"] == 1

        meeting = schedule_meeting(
            ctx["center"]["id"], ctx["manager"],
            start="2026-09-22T10:00:00Z", end="2026-09-22T11:00:00Z",
        )
        open_meeting(meeting["id"], ctx["manager"])
        post_collection(
            meeting["id"], ctx["manager"], ctx["applicant"]["id"], loan["id"], 9_334
        )
        group_after = get_success_data(api.get_peer_group(ctx["group"]["id"], PA))
        assert group_after["status"] == "ACTIVE", "cure returns the group to ACTIVE"
        assert group_after["delinquent_loan_count"] == 0
        loan_after = get_success_data(api.get_loan(loan["id"], PA))
        assert loan_after["status"] == "ACTIVE"


class TestDelinquencyContagion:
    def test_delinquency_contagion_loan_group_sibling_applications(self, api):
        """PRD §3.6: "Hop two: the member's group's `delinquent_loan_count` —
        the count of group members' loans in `DELINQUENT` or `DEFAULTED` —
        increments, and since a group is restricted whenever that count is at
        least 1 (exactly one delinquent loan is enough), an `ACTIVE` group moves
        to `RESTRICTED`. Hop three: every *other* group member's `ACTIVE` loan
        has its ladder advancement frozen — no `cycle_level` increment at payoff
        while the group is `RESTRICTED` — and every `VOTING` application
        belonging to any member of the group is moved to `EXPIRED`, because
        joint liability forbids new lending while any member is delinquent."
        PRD §3.3: "the sweep expires an undecided application only when the
        logical clock is **strictly later** than `voting_deadline`".

        Design: Difficulty/transitive_cascade/delinquency_contagion_loan_group_sibling_applications
        """
        ctx = setup_active_group(prefix="contagion")
        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])

        set_clock("2026-09-12T00:00:00Z")  # 4 days past the first due; no flip yet
        peer_application = draft_application(ctx["group"]["id"], ctx["peers"][0]["id"], 50_000)
        submit_application(peer_application["id"])  # deadline 2026-09-19
        casters = [ctx["applicant"]["id"], ctx["peers"][1]["id"]]
        for voter_id in casters:
            get_success_data(
                api.cast_vote(
                    peer_application["id"],
                    {"decision": "APPROVE"},
                    make_member_headers(voter_id),
                )
            )

        set_clock("2026-09-16T00:00:00Z")  # first due is exactly 8 days past

        loan_now = get_success_data(api.get_loan(loan["id"], PA))
        assert loan_now["status"] == "DELINQUENT"
        assert loan_now["installments_missed"] == 1

        group_now = get_success_data(api.get_peer_group(ctx["group"]["id"], PA))
        assert group_now["status"] == "RESTRICTED"
        assert group_now["delinquent_loan_count"] == 1

        app_now = get_success_data(api.get_loan_application(peer_application["id"], PA))
        assert app_now["status"] == "EXPIRED", (
            "the group-RESTRICTED cascade expires the VOTING application even "
            "though its deadline 2026-09-19 is after the sweep date"
        )

        member_now = get_success_data(api.get_member(ctx["applicant"]["id"], PA))
        assert member_now["status"] == "DELINQUENT"
        peer_now = get_success_data(api.get_member(ctx["peers"][0]["id"], PA))
        assert peer_now["status"] == "ELIGIBLE", (
            "delinquency does not blacklist or demote the peer by itself"
        )

    def test_delinquency_contagion_loan_group_sibling_applications_sweep_isolation(self, api):
        """PRD §3.3: "the sweep expires an undecided application only when the
        logical clock is **strictly later** than `voting_deadline`, while a vote
        is already invalid **at** the deadline".
        PRD §3.6: "every `VOTING` application belonging to any member of the
        group is moved to `EXPIRED`, because joint liability forbids new lending
        while any member is delinquent."

        Design: Difficulty/transitive_cascade/delinquency_contagion_loan_group_sibling_applications
        """
        ctx = setup_active_group(prefix="contagion-iso")
        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])

        set_clock("2026-09-12T00:00:00Z")
        peer_application = draft_application(ctx["group"]["id"], ctx["peers"][0]["id"], 50_000)
        submit_application(peer_application["id"])  # deadline 2026-09-19T00:00:00Z

        # Clock move that flips the loan (8 days past) but stays strictly
        # before the application's deadline.
        set_clock("2026-09-16T00:00:00Z")
        app_now = get_success_data(api.get_loan_application(peer_application["id"], PA))
        assert app_now["status"] == "EXPIRED"
        assert app_now["voting_deadline"] == "2026-09-19T00:00:00Z", (
            "the expiry predates the deadline: only group contagion can have fired"
        )
        group_now = get_success_data(api.get_peer_group(ctx["group"]["id"], PA))
        assert group_now["status"] == "RESTRICTED"


class TestDisburseBlockedUnderRestriction:
    def test_disbursement_blocked_when_group_restricted(self, api):
        """PRD §3.4: "the applicant's group must be `ACTIVE` — a group under
        joint-liability restriction blocks disbursement with
        `ERR_GROUP_RESTRICTED`".

        Design: Difficulty/cross_entity_state_dependency/disbursement_blocked_when_group_restricted
        """
        ctx = setup_active_group(prefix="restricted")
        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])

        peer = ctx["peers"][0]
        application = draft_application(ctx["group"]["id"], peer["id"], 50_000)
        submit_application(application["id"])
        for voter in [ctx["applicant"]] + ctx["peers"][1:]:
            get_success_data(
                api.cast_vote(
                    application["id"],
                    {"decision": "APPROVE"},
                    make_member_headers(voter["id"]),
                )
            )
        approved = get_success_data(api.get_loan_application(application["id"], PA))
        assert approved["status"] == "APPROVED"

        set_clock("2026-09-16T00:00:00Z")  # applicant's loan flips DELINQUENT
        group_now = get_success_data(api.get_peer_group(ctx["group"]["id"], PA))
        assert group_now["status"] == "RESTRICTED"

        response = api.disburse_loan_application(application["id"], TEST_USERS["branch_manager_headers"])
        validate_error(response, ApiErrorId.ERR_GROUP_RESTRICTED, expected_status=409)
        app_now = get_success_data(api.get_loan_application(application["id"], PA))
        assert app_now["status"] == "APPROVED", (
            "a blocked disbursement neither expires nor rejects the application"
        )

    def test_disbursement_blocked_when_group_restricted_cure_restores(self, api):
        """PRD §3.4: "the applicant's group must be `ACTIVE` — a group under
        joint-liability restriction blocks disbursement with
        `ERR_GROUP_RESTRICTED`".
        PRD §3.6: "the group's `delinquent_loan_count` decrements, returning the
        group `RESTRICTED → ACTIVE` and lifting the ladder freeze the moment the
        count reaches zero."

        Design: Difficulty/cross_entity_state_dependency/disbursement_blocked_when_group_restricted
        """
        ctx = setup_active_group(prefix="restricted-cure")
        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])

        peer = ctx["peers"][0]
        application = draft_application(ctx["group"]["id"], peer["id"], 50_000)
        submit_application(application["id"])
        for voter in [ctx["applicant"]] + ctx["peers"][1:]:
            get_success_data(
                api.cast_vote(
                    application["id"], {"decision": "APPROVE"},
                    make_member_headers(voter["id"]),
                )
            )

        set_clock("2026-09-16T00:00:00Z")
        blocked = api.disburse_loan_application(application["id"], TEST_USERS["branch_manager_headers"])
        validate_error(blocked, ApiErrorId.ERR_GROUP_RESTRICTED, expected_status=409)

        # Cure the delinquent loan: the group returns to ACTIVE and disbursement
        # succeeds.
        meeting = schedule_meeting(
            ctx["center"]["id"], ctx["manager"],
            start="2026-09-22T10:00:00Z", end="2026-09-22T11:00:00Z",
        )
        open_meeting(meeting["id"], ctx["manager"])
        post_collection(
            meeting["id"], ctx["manager"], ctx["applicant"]["id"], loan["id"], 9_334
        )
        group_now = get_success_data(api.get_peer_group(ctx["group"]["id"], PA))
        assert group_now["status"] == "ACTIVE"

        disbursed = api.disburse_loan_application(application["id"], TEST_USERS["branch_manager_headers"])
        loan2 = validate_success(disbursed, expected_status=200)
        assert loan2["status"] == "ACTIVE"
        app_now = get_success_data(api.get_loan_application(application["id"], PA))
        assert app_now["status"] == "DISBURSED"
