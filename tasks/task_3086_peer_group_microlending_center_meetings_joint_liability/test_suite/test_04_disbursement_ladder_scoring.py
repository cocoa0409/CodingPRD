"""Disbursement fan-out, loan-ladder variants, and credit scoring.

Covers difficulty instances under dual_variant_calc and combinatorial_formula
(loan side), plus corner instances for disbursement effects and immediate
consistency.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_application,
    close_meeting,
    disburse_application,
    disburse_member,
    draft_application,
    get_success_data,
    make_center_manager_headers,
    mark_attendance,
    open_meeting,
    post_collection,
    schedule_meeting,
    set_clock,
    setup_active_group,
    setup_two_active_groups,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
BM = TEST_USERS["branch_manager_headers"]
FO = TEST_USERS["field_officer_headers"]


def _pay_off_clean(ctx):
    """Single full-payoff collection (savings 200 + outstanding 109608) at the
    2026-09-08 meeting with everyone marked PRESENT, then close. The logical
    clock is moved to the meeting day first so the collection posts within the
    first installment's due window (PRD §2.4: every time-dependent rule reads
    the logical clock)."""
    set_clock("2026-09-08T00:00:00Z")
    meeting = schedule_meeting(ctx["center"]["id"], ctx["manager"])
    open_meeting(meeting["id"], ctx["manager"])
    mark_attendance(
        meeting["id"],
        ctx["manager"],
        [ctx["applicant"]["id"]] + [p["id"] for p in ctx["peers"]],
    )
    txn = post_collection(
        meeting["id"], ctx["manager"], ctx["applicant"]["id"], ctx["loan"]["id"], 109_808
    )
    close_meeting(meeting["id"], ctx["manager"])
    return meeting, txn


def _pay_off_after_one_cure(ctx):
    """Advance the clock so the first due goes delinquent, then a single
    collection at a later meeting cures and pays off in full. The clock is
    moved back to 9-days-past for the payoff so exactly one due has been
    consumed at that instant (at 15 days past, the sweep would consume two)."""
    set_clock("2026-09-17T00:00:00Z")  # first due (Sep 8) is 9 days past
    meeting = schedule_meeting(
        ctx["center"]["id"], ctx["manager"],
        start="2026-09-22T10:00:00Z", end="2026-09-22T11:00:00Z",
    )
    open_meeting(meeting["id"], ctx["manager"])
    mark_attendance(meeting["id"], ctx["manager"], [ctx["applicant"]["id"]])
    txn = post_collection(
        meeting["id"], ctx["manager"], ctx["applicant"]["id"], ctx["loan"]["id"], 109_808
    )
    close_meeting(meeting["id"], ctx["manager"])
    return meeting, txn


class TestLadderStandardVsRehabilitated:
    def test_ladder_ceiling_standard_vs_rehabilitated_same_member_profile(self, api):
        """PRD §3.4: "**Standard** applies while `cured_delinquency_count` is 0:
        the ceiling is a pure lookup on `cycle_level` — 100,000 cents at rung 1,
        200,000 at rung 2, 300,000 at rung 3, 400,000 at rung 4, and 500,000 at
        rung 5. **Rehabilitated** applies once `cured_delinquency_count` is at
        least 1: the ceiling is the *smaller* of the rung lookup and
        one-and-a-half times the `principal_cents` of the member's most recent
        `PAID_OFF` loan, with the multiplier product rounded down (floored) to
        whole cents."
        PRD §3.4: "the `requested_amount_cents` must not exceed the applicant's
        current ladder ceiling (`ERR_LADDER_CEILING_EXCEEDED`)."
        PRD §3.6: "The ladder then advances — `cycle_level` increments by one,
        capped at rung 5 — but only if `installments_missed` is zero *and* the
        member's group is not `RESTRICTED` at that moment; a payoff with any
        missed installment, or under a restricted group, leaves the rung
        unchanged."

        Design: Difficulty/dual_variant_calc/ladder_ceiling_standard_vs_rehabilitated_same_member_profile
        """
        ctx = setup_two_active_groups(prefix="ladder")

        # Both loans disburse before any clock move so both first dues fall on
        # 2026-09-08 — the clean payoff and the delinquency flip then share the
        # same calendar.
        g1_ctx = {
            "center": ctx["center"], "manager": ctx["manager"],
            "group": ctx["g1"], "applicant": ctx["m1"], "peers": ctx["peers1"],
        }
        _, loan1 = disburse_member(ctx["g1"]["id"], ctx["m1"], ctx["peers1"])
        g1_ctx["loan"] = loan1

        g2_ctx = {
            "center": ctx["center"], "manager": ctx["manager"],
            "group": ctx["g2"], "applicant": ctx["m2"], "peers": ctx["peers2"],
        }
        _, loan2 = disburse_member(ctx["g2"]["id"], ctx["m2"], ctx["peers2"])
        g2_ctx["loan"] = loan2

        # M1 (clean payer): cycle-1 100000c loan, paid off with zero misses.
        _pay_off_clean(g1_ctx)

        # M2 (rehabilitated): cycle-1 loan cured once before payoff.
        _pay_off_after_one_cure(g2_ctx)

        m1_now = get_success_data(api.get_member(ctx["m1"]["id"], PA))
        m2_now = get_success_data(api.get_member(ctx["m2"]["id"], PA))
        assert m1_now["cycle_level"] == 2, "clean payoff advances the ladder"
        assert m1_now["cured_delinquency_count"] == 0
        assert m2_now["cycle_level"] == 1, "missed installments block advancement"
        assert m2_now["cured_delinquency_count"] == 1

        # Identical 175000c applications approved for both.
        app3 = draft_application(ctx["g1"]["id"], ctx["m1"]["id"], 175_000)
        submit_application(app3["id"])
        approve_application(app3["id"], ctx["m1"]["id"], [p["id"] for p in ctx["peers1"]])
        app4 = draft_application(ctx["g2"]["id"], ctx["m2"]["id"], 175_000)
        submit_application(app4["id"])
        approve_application(app4["id"], ctx["m2"]["id"], [p["id"] for p in ctx["peers2"]])

        clean_disburse = api.disburse_loan_application(app3["id"], BM)
        assert clean_disburse.status_code == 200, (
            f"clean payer at cycle 2 must disburse under the 200000c ceiling: "
            f"{clean_disburse.text}"
        )
        app3_now = get_success_data(api.get_loan_application(app3["id"], PA))
        assert app3_now["status"] == "DISBURSED"
        assert app3_now["applied_ceiling_cents"] == 200_000

        rehab_disburse = api.disburse_loan_application(app4["id"], BM)
        validate_error(
            rehab_disburse, ApiErrorId.ERR_LADDER_CEILING_EXCEEDED, expected_status=422
        )
        app4_now = get_success_data(api.get_loan_application(app4["id"], PA))
        assert app4_now["status"] == "APPROVED", (
            "a failed disbursement must not revert the approval"
        )

    def test_ladder_ceiling_standard_vs_rehabilitated_same_member_profile_second_cycle_fields(self, api):
        """PRD §3.4: "**Standard** applies while `cured_delinquency_count` is 0:
        the ceiling is a pure lookup on `cycle_level` — 100,000 cents at rung 1,
        200,000 at rung 2, 300,000 at rung 3, 400,000 at rung 4, and 500,000 at
        rung 5."
        PRD §3.4: "The mandatory savings per collection,
        `savings_required_cents`, is the larger of 200 cents and a percentage of
        the weekly installment rounded half up: 2% at rung 1, 3% at rung 2, 4%
        at rung 3, and 5% at rungs 4 and 5."
        PRD §3.6: "The ladder then advances — `cycle_level` increments by one,
        capped at rung 5 — but only if `installments_missed` is zero *and* the
        member's group is not `RESTRICTED` at that moment".

        Design: Difficulty/dual_variant_calc/ladder_ceiling_standard_vs_rehabilitated_same_member_profile
        """
        ctx = setup_active_group(prefix="ladder-tier")
        _, loan1 = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])
        ctx["loan"] = loan1
        _pay_off_clean(ctx)

        member_now = get_success_data(api.get_member(ctx["applicant"]["id"], PA))
        assert member_now["cycle_level"] == 2

        # Rung-2 loan: STANDARD ceiling 200000c; the 3% tier applies.
        application = draft_application(ctx["group"]["id"], ctx["applicant"]["id"], 200_000)
        submit_application(application["id"])
        approve_application(
            application["id"], ctx["applicant"]["id"], [p["id"] for p in ctx["peers"]]
        )
        loan2 = disburse_application(application["id"])
        assert loan2["cycle_level"] == 2
        assert loan2["principal_cents"] == 200_000
        # clean rate 0.004: round_half_up(200000 * 1.096 / 24) = 9133
        # (9133.333... rounds down; not a half-tie)
        assert loan2["weekly_installment_cents"] == 9_133
        # max(200, round_half_up(0.03 * 9133)) = max(200, 274) = 274
        assert loan2["savings_required_cents"] == 274


class TestRehabPenaltyInstallmentSplit:
    def test_installment_split_rehab_penalty_tier_selection(self, api):
        """PRD §3.4: "The rehabilitation branch adjusts the rate, not the
        principal: with a `cured_delinquency_count` of at least 1 the rate
        becomes the flat rate plus 0.001 per week". So 100000c at rate 0.005
        over 24 weeks gives weekly_installment_cents =
        round_half_up(112000/24) = 4667.
        PRD §3.4: "The mandatory savings per collection, `savings_required_cents`,
        is the larger of 200 cents and a percentage of the weekly installment
        rounded half up: 2% at rung 1"."

        Design: Difficulty/combinatorial_formula/installment_split_rehab_penalty_tier_selection
        """
        ctx = setup_two_active_groups(prefix="rehab-split")
        _, loan2 = disburse_member(ctx["g2"]["id"], ctx["m2"], ctx["peers2"])
        g2_ctx = {
            "center": ctx["center"], "manager": ctx["manager"],
            "group": ctx["g2"], "applicant": ctx["m2"], "peers": ctx["peers2"],
            "loan": loan2,
        }
        _pay_off_after_one_cure(g2_ctx)

        app5 = draft_application(ctx["g2"]["id"], ctx["m2"]["id"], 100_000)
        submit_application(app5["id"])
        approve_application(app5["id"], ctx["m2"]["id"], [p["id"] for p in ctx["peers2"]])
        loan3 = disburse_application(app5["id"])

        assert loan3["weekly_installment_cents"] == 4667, (
            f"rehabilitated rate 0.005 must apply: {loan3['weekly_installment_cents']}"
        )
        assert loan3["savings_required_cents"] == 200, "the 200c floor binds at 2% of 4667"
        assert loan3["principal_outstanding_cents"] == 4667 * 24
        assert loan3["cycle_level"] == 1

    def test_installment_split_rehab_penalty_tier_selection_clean_borrower_contrast(self, api):
        """PRD §3.4: "The base cost of credit is a flat rate of 0.004 of
        principal per week."
        PRD §3.4: "The `weekly_installment_cents` is then the principal grown by
        that weekly rate over the full term — principal times
        one-plus-rate-times-`term_weeks` — divided by `term_weeks`, rounded half
        up to whole cents."

        Design: Difficulty/combinatorial_formula/installment_split_rehab_penalty_tier_selection
        """
        ctx = setup_active_group(prefix="clean-split")
        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])
        # Clean borrower (cured_delinquency_count 0): rate 0.004.
        # 100000 * 1.096 / 24 = 4566.666..., which rounds half up to 4567.
        assert loan["weekly_installment_cents"] == 4_567, (
            "round_half_up(100000 * 1.096 / 24) = 4567"
        )
        assert loan["savings_required_cents"] == 200, (
            "max(200, round_half_up(0.02 * 4567)) = 200"
        )
        assert loan["principal_outstanding_cents"] == 109_608
        member_now = get_success_data(api.get_member(ctx["applicant"]["id"], PA))
        assert member_now["cured_delinquency_count"] == 0


class TestCreditScoreDualReadings:
    def test_credit_score_provisional_vs_final_same_loan(self, api):
        """PRD §3.4: "A member mid-cycle with no activity at all therefore reads
        720 provisionally."
        PRD §3.4: "The **final** score, filed when a loan reaches `PAID_OFF` or
        `DEFAULTED` as a `FINAL` report, counts only actuals: 600 plus 10 per
        on-time installment, minus 30 per missed installment, plus 2 per meeting
        attended during the loan's lifetime ... minus 15 per
        `attendance_strikes`, with no projected credit and the same 300–850
        clamp."
        PRD §3.5: "An installment counts toward `installments_on_time` only
        when the collection's logical posting time is at or before that
        installment's due date".

        Design: Difficulty/dual_variant_calc/credit_score_provisional_vs_final_same_loan
        """
        ctx = setup_active_group(prefix="score-dual")
        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])
        ctx["loan"] = loan
        applicant_id = ctx["applicant"]["id"]

        provisional_read = get_success_data(api.get_member(applicant_id, PA))
        assert provisional_read["credit_score"] == 720, (
            f"mid-cycle with no activity reads 720 provisionally, got "
            f"{provisional_read['credit_score']}"
        )

        # Payoff meeting where the applicant is PRESENT, then close.
        _pay_off_clean(ctx)

        # Two later meetings where the applicant is auto-marked ABSENT.
        for day in ("2026-09-22", "2026-09-29"):
            set_clock(f"{day}T00:00:00Z")
            meeting = schedule_meeting(
                ctx["center"]["id"], ctx["manager"],
                start=f"{day}T10:00:00Z", end=f"{day}T11:00:00Z",
            )
            open_meeting(meeting["id"], ctx["manager"])
            mark_attendance(meeting["id"], ctx["manager"], [p["id"] for p in ctx["peers"]])
            close_meeting(meeting["id"], ctx["manager"])

        member_now = get_success_data(api.get_member(applicant_id, PA))
        assert member_now["attendance_strikes"] == 1
        # Payoff posts before the first due date, so all 24 installments count
        # on-time (PRD §3.5: a collection at or before an installment's due
        # date). The FINAL report is filed at the payoff instant — before the
        # payoff meeting's CLOSED transition — so it counts zero attended
        # meetings: 600 + 10*24 - 15*0 = 840. The member's readable
        # credit_score re-evaluates the same formula at read time (PRD §3.4:
        # "with no open loan it is the final score of their most recently
        # terminated loan"), after the payoff meeting closed inside the loan's
        # lifetime window and one strike landed: 600 + 240 + 2 - 15 = 827.
        assert member_now["credit_score"] == 827, (
            f"final reading re-evaluated at one strike: {member_now['credit_score']}"
        )

        reports, _ = validate_paginated(api.list_member_bureau_reports(applicant_id, PA))
        assert len(reports) == 2, (
            f"exactly one PROVISIONAL and one FINAL report exist, got {len(reports)}"
        )
        by_type = {r["report_type"]: r for r in reports}
        assert by_type["PROVISIONAL"]["score_reported"] == 720
        assert by_type["FINAL"]["score_reported"] == 840

    def test_credit_score_provisional_vs_final_same_loan_reading_transition(self, api):
        """PRD §3.4: "The member's readable `credit_score` is the provisional
        score while any of their loans is `ACTIVE` or `DELINQUENT`; with no open
        loan it is the final score of their most recently terminated loan; and a
        member who has never held a loan reads 600."
        PRD §3.4: "A member mid-cycle with no activity at all therefore reads
        720 provisionally."
        PRD §3.4: "The **final** score ... counts only actuals: 600 plus 10 per
        on-time installment, minus 30 per missed installment, plus 2 per meeting
        attended during the loan's lifetime".

        Design: Difficulty/dual_variant_calc/credit_score_provisional_vs_final_same_loan
        """
        ctx = setup_active_group(prefix="score-read")
        applicant_id = ctx["applicant"]["id"]

        before = get_success_data(api.get_member(applicant_id, PA))
        assert before["credit_score"] == 600, "a member who has never held a loan reads 600"

        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])
        ctx["loan"] = loan
        mid = get_success_data(api.get_member(applicant_id, PA))
        assert mid["credit_score"] == 720, "provisional reading while the loan is ACTIVE"

        _pay_off_clean(ctx)  # applicant PRESENT at the payoff meeting, then close
        after = get_success_data(api.get_member(applicant_id, PA))
        # Payoff posts before the first due date, so all 24 installments count
        # on-time (PRD §3.5), and the payoff meeting's CLOSED transition lands
        # inside the loan's lifetime window (inclusive at both ends, PRD §3.4):
        # 600 + 10*24 + 2*1 - 15*0 = 842.
        assert after["credit_score"] == 842, (
            f"final reading after payoff: {after['credit_score']}"
        )
        reports, _ = validate_paginated(api.list_member_bureau_reports(applicant_id, PA))
        by_type = {r["report_type"]: r for r in reports}
        # The FINAL report is filed at the payoff instant — before the payoff
        # meeting's CLOSED transition — so it counts zero attended meetings:
        # 600 + 10*24 - 15*0 = 840.
        assert by_type["FINAL"]["score_reported"] == 840


class TestDisburseSideEffects:
    def test_disburse_side_effects_create_loan_account_and_provisional_report(self, api):
        """PRD §3.4: "A successful disbursement creates the loan in one atomic
        bundle: `principal_cents` equal to the application's
        `requested_amount_cents`; a `cycle_level` snapshot of the member's rung;
        `term_weeks` fixed at 24 weekly installments; status `ACTIVE`;
        `next_due_date` set to the disbursement instant plus 7 days;
        `installments_on_time` and `installments_missed` at 0; and
        `principal_outstanding_cents` initialized to `term_weeks` times
        `weekly_installment_cents`."
        PRD §3.4: "Disbursement also opens the member's `SavingsAccount` if none
        exists yet (`OPEN`, balance zero — one account per member), moves a
        first-time borrower `ELIGIBLE → ACTIVE_BORROWER`, and files a
        `PROVISIONAL` credit bureau report whose `score_reported` is the
        provisional score."
        PRD §3.8: "`locked_cents` collateralizes open debt: ten percent of the
        total `principal_outstanding_cents` across the member's loans in
        `ACTIVE` or `DELINQUENT`, rounded half up to whole cents."

        Design: Corner/endpoints/disburse_side_effects_create_loan_account_and_provisional_report
        """
        ctx = setup_active_group(prefix="disburse-fx")
        application = draft_application(ctx["group"]["id"], ctx["applicant"]["id"])
        submit_application(application["id"])
        approve_application(
            application["id"], ctx["applicant"]["id"], [p["id"] for p in ctx["peers"]]
        )
        loan = disburse_application(application["id"])

        app_now = get_success_data(api.get_loan_application(application["id"], PA))
        assert app_now["status"] == "DISBURSED"
        assert app_now["applied_ceiling_cents"] == 100_000

        assert loan["status"] == "ACTIVE"
        assert loan["principal_cents"] == 100_000
        assert loan["weekly_installment_cents"] == 4567
        assert loan["savings_required_cents"] == 200
        assert loan["principal_outstanding_cents"] == 109_608
        assert loan["term_weeks"] == 24
        assert loan["cycle_level"] == 1
        assert loan["next_due_date"] == "2026-09-08T00:00:00Z"

        member_now = get_success_data(api.get_member(ctx["applicant"]["id"], PA))
        assert member_now["status"] == "ACTIVE_BORROWER"
        assert member_now["credit_score"] == 720

        accounts, _ = validate_paginated(
            api.get_member_savings_account(ctx["applicant"]["id"], PA)
        )
        assert len(accounts) == 1
        account = accounts[0]
        assert account["status"] == "OPEN"
        assert account["balance_cents"] == 0
        assert account["locked_cents"] == 10_961
        assert account["withdrawable_cents"] == 0

        reports, _ = validate_paginated(
            api.list_member_bureau_reports(ctx["applicant"]["id"], PA)
        )
        assert len(reports) == 1
        assert reports[0]["report_type"] == "PROVISIONAL"
        assert reports[0]["score_reported"] == 720

    def test_disburse_effects_visible_in_same_response_and_followup_reads(self, api):
        """PRD §2.4: "Every cascade those sweeps trigger — member status flips,
        group restriction, application expiry, blacklist freezes — completes
        inside the triggering request. The same immediate-consistency rule
        applies to cascades triggered by ordinary write operations: no side
        effect is ever deferred to a later request."
        PRD §3.4: "The member's readable `credit_score` is the provisional score
        while any of their loans is `ACTIVE` or `DELINQUENT`".

        Design: Corner/consistency_model/disburse_effects_visible_in_same_response_and_followup_reads
        """
        ctx = setup_active_group(prefix="immediate")
        application = draft_application(ctx["group"]["id"], ctx["applicant"]["id"])
        submit_application(application["id"])
        approve_application(
            application["id"], ctx["applicant"]["id"], [p["id"] for p in ctx["peers"]]
        )
        loan = disburse_application(application["id"])
        assert loan["weekly_installment_cents"] == 4567
        assert loan["principal_outstanding_cents"] == 109_608

        member_now = get_success_data(api.get_member(ctx["applicant"]["id"], PA))
        assert member_now["status"] == "ACTIVE_BORROWER"
        assert member_now["credit_score"] == 720
