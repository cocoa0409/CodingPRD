"""Savings account lifecycle, OCC restructuring, expansion feasibility,
caseload conservation, blacklist priority, and list filtering.

Covers difficulty instances under priority_pair_validation_conflict,
combinatorial_formula (expansion), compensating_invariant (caseload), and the
remaining corner instances.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_application,
    close_meeting,
    create_center,
    create_center,
    create_center_manager,
    create_expansion_plan_payload,
    create_restructure_payload,
    disburse_member,
    draft_application,
    get_success_data,
    make_member_headers,
    mark_attendance,
    open_meeting,
    post_collection,
    schedule_meeting,
    set_clock,
    setup_active_group,
    setup_open_meeting_with_loan,
    setup_org,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
BM = TEST_USERS["branch_manager_headers"]
FO = TEST_USERS["field_officer_headers"]


class TestSavingsCloseGuards:
    def test_savings_close_blocked_by_nonzero_balance(self, api):
        """PRD §3.8: "Closure likewise belongs to the member and requires the
        account `OPEN` (`ERR_ACCOUNT_NOT_OPEN`), no loan in `ACTIVE` or
        `DELINQUENT` (`ERR_MEMBER_HAS_ACTIVE_LOAN`), and a `balance_cents` of
        exactly zero (`ERR_ACCOUNT_NOT_EMPTY`)".

        Design: Corner/state_machines/savings_close_blocked_by_nonzero_balance
        """
        ctx = setup_open_meeting_with_loan(prefix="close-nonzero")
        # Full payoff: savings 200 + outstanding 109608; then close the meeting.
        post_collection(
            ctx["meeting"]["id"], ctx["manager"],
            ctx["applicant"]["id"], ctx["loan"]["id"], 109_808,
        )
        close_meeting(ctx["meeting"]["id"], ctx["manager"])
        response = api.close_savings(
            ctx["applicant"]["id"], make_member_headers(ctx["applicant"]["id"])
        )
        validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_EMPTY, expected_status=409)
        accounts, _ = validate_paginated(
            api.get_member_savings_account(ctx["applicant"]["id"], PA)
        )
        assert accounts[0]["status"] == "OPEN"
        assert accounts[0]["balance_cents"] == 200

    def test_withdrawal_blocked_when_account_frozen(self, api):
        """PRD §3.8: "a `Member` withdraws by supplying `amount_cents`; the
        account must be `OPEN` (`ERR_ACCOUNT_NOT_OPEN`) and the amount may not
        exceed `withdrawable_cents`".
        PRD §3.6: "their savings account is frozen `OPEN → FROZEN`".

        Design: Corner/validations/withdrawal_blocked_when_account_frozen
        """
        ctx = setup_open_meeting_with_loan(prefix="frozen-withdraw")
        post_collection(
            ctx["meeting"]["id"], ctx["manager"],
            ctx["applicant"]["id"], ctx["loan"]["id"], 4_768,
        )
        close_meeting(ctx["meeting"]["id"], ctx["manager"])
        set_clock("2026-10-08T00:00:00Z")  # loan defaults; member blacklisted
        response = api.withdraw_savings(
            ctx["applicant"]["id"],
            {"amount_cents": 100},
            make_member_headers(ctx["applicant"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_OPEN, expected_status=409)
        accounts, _ = validate_paginated(
            api.get_member_savings_account(ctx["applicant"]["id"], PA)
        )
        assert accounts[0]["status"] == "FROZEN"
        assert accounts[0]["balance_cents"] == 200

    def test_unfreeze_requires_frozen_state(self, api):
        """PRD §3.8: "a `FROZEN` account can be restored to `OPEN` by a
        `ProgramAdmin` override, which requires the account to actually be
        `FROZEN` (`ERR_ACCOUNT_NOT_FROZEN`)."

        Design: Corner/errors/unfreeze_requires_frozen_state
        """
        ctx = setup_active_group(prefix="unfreeze-open")
        disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])
        response = api.unfreeze_savings(ctx["applicant"]["id"], PA)
        validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_FROZEN, expected_status=409)


class TestOccRestructure:
    def test_occ_restructure_succeeds_with_current_version(self, api):
        """PRD §3.9: "Restructures follow create-with-supersede semantics: the
        new record is born `ACTIVE` ... The loan's `term_weeks` becomes
        `new_term_weeks` ... The loan's `version` increments, which is exactly
        what makes a concurrent stale restructure detectable."
        PRD §2.7: "The request must carry `expected_loan_version`, a
        non-optional field holding the `version` of the target loan as the
        client last observed it."

        Design: Corner/cross_cutting_layers/occ_restructure_succeeds_with_current_version
        """
        ctx = setup_active_group(prefix="occ-happy")
        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])
        before = get_success_data(api.get_loan(loan["id"], PA))
        response = api.create_restructure(
            loan["id"],
            create_restructure_payload(36, before["version"]),
            BM,
        )
        restructure = validate_success(response, expected_status=201)
        assert restructure["status"] == "ACTIVE"
        after = get_success_data(api.get_loan(loan["id"], PA))
        assert after["version"] == before["version"] + 1
        assert after["term_weeks"] == 36


class TestExpansionFeasibility:
    def test_expansion_feasibility_pinned_evaluation_order(self, api):
        """PRD §3.10: "Feasibility is computed at submission in a pinned
        evaluation order that deliberately uses only *current* membership for
        tiering, breaking what would otherwise be a circular dependency between
        tier, caps, and capacity".
        PRD §3.10: "The plan is feasible only when the required member capacity
        is at most the available member capacity **and** the required center
        slots are at most the available center slots — equality on either axis
        still counts as feasible."
        PRD §3.10: "A plan that fails the evaluation is refused outright with
        `ERR_EXPANSION_INFEASIBLE`; a feasible plan is created directly in
        `SUBMITTED`".

        Design: Difficulty/combinatorial_formula/expansion_feasibility_pinned_evaluation_order
        """
        # Branch with exactly 5 active members (one fully trained group).
        ctx = setup_active_group(prefix="expansion-order")
        branch = ctx["branch"]

        branch_now = get_success_data(api.get_branch(branch["id"], PA))
        assert branch_now["tier"] == "SMALL"
        assert branch_now["active_member_count"] == 5

        exact = api.submit_expansion_plan(
            branch["id"],
            create_expansion_plan_payload(
                new_centers=2, new_managers_hired=2, target_new_members=175
            ),
            BM,
        )
        plan = validate_success(exact, expected_status=201)
        assert plan["status"] == "SUBMITTED"
        assert plan["feasibility"]["available_member_capacity"] == 180, (
            "3 managers x 60 (SMALL member_cap)"
        )
        assert plan["feasibility"]["feasible"] is True

        over = api.submit_expansion_plan(
            branch["id"],
            create_expansion_plan_payload(
                new_centers=2, new_managers_hired=2, target_new_members=176
            ),
            BM,
        )
        validate_error(over, ApiErrorId.ERR_EXPANSION_INFEASIBLE, expected_status=409)

    def test_expansion_feasibility_pinned_evaluation_order_center_slots(self, api):
        """PRD §3.10: "Read the caps for that tier: `member_cap` 60 / 80 / 100
        and `center_cap` 3 / 4 / 5."
        PRD §3.10: "Available capacity is `mgrs` times `member_cap` members, and
        `mgrs` times `center_cap` minus the branch's current center count in
        center slots."
        PRD §3.10: "A plan that fails the evaluation is refused outright with
        `ERR_EXPANSION_INFEASIBLE`".

        Design: Difficulty/combinatorial_formula/expansion_feasibility_pinned_evaluation_order
        """
        # Empty SMALL branch: 1 manager, 1 center. Available center slots with
        # no new hires: 1 * 3 - 1 = 2.
        branch, manager, center = setup_org()
        fits = api.submit_expansion_plan(
            branch["id"],
            create_expansion_plan_payload(
                new_centers=2, new_managers_hired=0, target_new_members=0
            ),
            BM,
        )
        plan = validate_success(fits, expected_status=201)
        assert plan["feasibility"]["available_center_slots"] == 2
        assert plan["feasibility"]["required_center_slots"] == 2
        assert plan["feasibility"]["feasible"] is True

        too_many = api.submit_expansion_plan(
            branch["id"],
            create_expansion_plan_payload(
                new_centers=3, new_managers_hired=0, target_new_members=0
            ),
            BM,
        )
        validate_error(too_many, ApiErrorId.ERR_EXPANSION_INFEASIBLE, expected_status=409)

    def test_expansion_capacity_exactly_equal_is_feasible(self, api):
        """PRD §3.10: "The plan is feasible only when the required member
        capacity is at most the available member capacity **and** the required
        center slots are at most the available center slots — equality on either
        axis still counts as feasible."

        Design: Corner/calculations/expansion_capacity_exactly_equal_is_feasible
        """
        branch, manager, center = setup_org()
        exact = api.submit_expansion_plan(
            branch["id"],
            create_expansion_plan_payload(
                new_centers=2, new_managers_hired=2, target_new_members=180
            ),
            BM,
        )
        plan = validate_success(exact, expected_status=201)
        assert plan["status"] == "SUBMITTED"
        assert plan["feasibility"]["feasible"] is True
        assert plan["feasibility"]["available_member_capacity"] == 180

        over = api.submit_expansion_plan(
            branch["id"],
            create_expansion_plan_payload(
                new_centers=2, new_managers_hired=2, target_new_members=181
            ),
            BM,
        )
        validate_error(over, ApiErrorId.ERR_EXPANSION_INFEASIBLE, expected_status=409)


class TestCaseloadConservation:
    def test_center_reassignment_conserves_branch_total_caseload(self, api):
        """PRD §3.1: "Centers may later be reassigned to another manager of the
        *same* branch; reassignment recomputes both managers'
        `current_caseload`, enforces the target manager's caps
        (`ERR_CASELOAD_CAP_EXCEEDED`), and conserves the branch's
        `total_manager_caseload` — moving a center between two managers of one
        branch never changes the branch total."

        Design: Difficulty/compensating_invariant/center_reassignment_conserves_branch_total_caseload
        """
        ctx = setup_active_group(prefix="caseload")
        branch = ctx["branch"]
        manager_a = ctx["manager"]
        manager_b = create_center_manager(branch["id"], full_name="Second Manager")

        a_before = get_success_data(api.get_center_manager(manager_a["id"], PA))
        branch_before = get_success_data(api.get_branch(branch["id"], PA))
        assert a_before["current_caseload"] == 5
        assert branch_before["total_manager_caseload"] == 5

        get_success_data(
            api.reassign_center(ctx["center"]["id"], {"center_manager_id": manager_b["id"]}, PA)
        )

        a_after = get_success_data(api.get_center_manager(manager_a["id"], PA))
        b_after = get_success_data(api.get_center_manager(manager_b["id"], PA))
        branch_after = get_success_data(api.get_branch(branch["id"], PA))
        assert a_after["current_caseload"] == 0
        assert b_after["current_caseload"] == 5
        assert branch_after["total_manager_caseload"] == 5, "the branch total is conserved"

    def test_center_reassignment_conserves_branch_total_caseload_two_centers(self, api):
        """PRD §3.1: "Centers may later be reassigned to another manager of the
        *same* branch; reassignment recomputes both managers'
        `current_caseload`, enforces the target manager's caps
        (`ERR_CASELOAD_CAP_EXCEEDED`), and conserves the branch's
        `total_manager_caseload` — moving a center between two managers of one
        branch never changes the branch total."

        Design: Difficulty/compensating_invariant/center_reassignment_conserves_branch_total_caseload
        """
        ctx = setup_active_group(prefix="caseload2")
        branch = ctx["branch"]
        manager_a = ctx["manager"]
        manager_b = create_center_manager(branch["id"], full_name="Second Manager")
        # Manager B already carries one (empty) center.
        center_b = create_center(branch["id"], manager_b["id"], name="Center B")

        get_success_data(
            api.reassign_center(ctx["center"]["id"], {"center_manager_id": manager_b["id"]}, PA)
        )
        a_after = get_success_data(api.get_center_manager(manager_a["id"], PA))
        b_after = get_success_data(api.get_center_manager(manager_b["id"], PA))
        branch_after = get_success_data(api.get_branch(branch["id"], PA))
        assert a_after["current_caseload"] == 0
        assert b_after["current_caseload"] == 5, "B's own empty center adds no members"
        assert branch_after["total_manager_caseload"] == 5


class TestBlacklistPriority:
    def test_priority_safety_blacklist_beats_referential_membership(self, api):
        """PRD §2.8: "Within a group-membership add, the blacklist screen is
        evaluated before the already-in-a-group check, so a blacklisted
        ex-member surfaces as `ERR_MEMBER_BLACKLISTED` rather than
        `ERR_MEMBER_ALREADY_IN_GROUP`."
        PRD §3.6: "When a loan reaches `DEFAULTED`, the member becomes
        `BLACKLISTED`".

        Design: Difficulty/priority_pair_validation_conflict/priority_safety_blacklist_beats_referential_membership
        """
        ctx = setup_active_group(prefix="blacklist-prio")
        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])

        # A second group at the same center in FORMING with 4 members.
        g2 = get_success_data(
            api.create_peer_group({"center_id": ctx["center"]["id"], "name": "G2"}, FO)
        )
        for i in range(4):
            member = get_success_data(
                api.create_member(
                    {"branch_id": ctx["branch"]["id"],
                     "full_name": f"G2 Member {i}", "national_id": f"NID-G2-{i}"},
                    FO,
                )
            )
            get_success_data(api.add_group_member(g2["id"], {"member_id": member["id"]}, FO))

        set_clock("2026-10-08T00:00:00Z")  # applicant's loan defaults
        member_now = get_success_data(api.get_member(ctx["applicant"]["id"], PA))
        assert member_now["status"] == "BLACKLISTED"

        response = api.add_group_member(g2["id"], {"member_id": ctx["applicant"]["id"]}, FO)
        validate_error(response, ApiErrorId.ERR_MEMBER_BLACKLISTED, expected_status=403)
        g2_now = get_success_data(api.get_peer_group(g2["id"], PA))
        assert g2_now["member_count"] == 4, "the blacklisted member is not added"

    def test_priority_safety_blacklist_beats_referential_membership_low_final_score(self, api):
        """PRD §3.2: "The blacklist screen comes first: a member whose status
        is `BLACKLISTED`, or who carries a `FINAL` bureau report with a
        `score_reported` below 300, is refused with `ERR_MEMBER_BLACKLISTED` —
        this fires before any membership check."

        Design: Difficulty/priority_pair_validation_conflict/priority_safety_blacklist_beats_referential_membership

        Setup note: the FINAL score is clamped to the 300 floor (PRD §3.4:
        "the same 300–850 clamp"), so no FINAL report can ever read below 300
        and the report-based branch of the screen is unreachable through the
        scoring formula. This test therefore exercises the screen through its
        BLACKLISTED-status branch — the applicant accumulates 20 attendance
        strikes (PRD §3.7: a strike when the absence streak reaches 2; a
        PRESENT week resets it), then lets a loan default, which blacklists
        her (PRD §3.6). The FINAL report lands at the clamped floor of 300,
        and the re-add attempt surfaces ERR_MEMBER_BLACKLISTED before any
        membership check.
        """
        ctx = setup_active_group(prefix="blacklist-low-score")
        member_id = ctx["applicant"]["id"]
        others = [p["id"] for p in ctx["peers"]]

        from datetime import date, timedelta

        # PRD §3.7 awards a strike exactly when the absence streak *reaches* 2,
        # and a PRESENT resets the streak — so each strike costs one
        # ABSENT-ABSENT-PRESENT triple. Twenty triples give 20 strikes while
        # leaving the member submittable (streak 0 at the end).
        last_tuesday = None
        for i in range(20):
            base = date(2026, 9, 8) + timedelta(weeks=3 * i)
            plan = (
                (base, others),                      # streak 1
                (base + timedelta(weeks=1), others), # streak 2 -> strike
                (base + timedelta(weeks=2), others + [member_id]),  # reset
            )
            for tuesday, attendee_ids in plan:
                meeting = schedule_meeting(
                    ctx["center"]["id"], ctx["manager"],
                    start=f"{tuesday.isoformat()}T10:00:00Z",
                    end=f"{tuesday.isoformat()}T11:00:00Z",
                )
                open_meeting(meeting["id"], ctx["manager"])
                mark_attendance(meeting["id"], ctx["manager"], attendee_ids)
                close_meeting(meeting["id"], ctx["manager"])
                last_tuesday = tuesday
        set_clock(f"{(last_tuesday + timedelta(days=1)).isoformat()}T00:00:00Z")

        member_mid = get_success_data(api.get_member(member_id, PA))
        assert member_mid["attendance_strikes"] == 20
        assert member_mid["consecutive_absence_streak"] == 0, (
            "the presence weeks keep the member submittable"
        )

        _, loan = disburse_member(ctx["group"]["id"], ctx["applicant"], ctx["peers"])
        # Disbursed at the logical clock (2027-05-12): dues run weekly from
        # 2027-05-19, and the loan's lifetime window closes at the default
        # sweep below.

        # Attend four meetings whose CLOSED transitions land inside the loan's
        # lifetime (they close at the current logical clock, before the sweep
        # moves it), keeping the strike count at 20, then let every due age out
        # unpaid. The loan disburses at the logical clock (2027-10-27 after the
        # 20 triples), so dues run weekly from 2027-11-03.
        for tuesday in [date(2027, 11, 2) + timedelta(weeks=i) for i in range(4)]:
            meeting = schedule_meeting(
                ctx["center"]["id"], ctx["manager"],
                start=f"{tuesday.isoformat()}T10:00:00Z",
                end=f"{tuesday.isoformat()}T11:00:00Z",
            )
            open_meeting(meeting["id"], ctx["manager"])
            mark_attendance(meeting["id"], ctx["manager"], others + [member_id])
            close_meeting(meeting["id"], ctx["manager"])

        # Default the loan: at 2027-12-10 the first due (2027-11-03) is 37
        # days past and every due through 2027-12-01 has been consumed unpaid
        # (5 misses).
        set_clock("2027-12-10T00:00:00Z")
        loan_now = get_success_data(api.get_loan(loan["id"], PA))
        assert loan_now["status"] == "DEFAULTED"
        reports, _ = validate_paginated(api.list_loan_bureau_reports(loan["id"], PA))
        final = [r for r in reports if r["report_type"] == "FINAL"][0]
        # Raw: 600 - 30*5 missed + 2*4 attended - 15*20 strikes = 158, clamped
        # up to the 300 floor (PRD §3.4 "the same 300–850 clamp") — the clamp
        # is exactly why the <300 report branch is unreachable.
        assert final["score_reported"] == 300, (
            f"the clamped FINAL report sits at the 300 floor: {final}"
        )

        # The defaulted member is BLACKLISTED; she also still carries her old
        # peer_group_id, so both the blacklist screen and the membership check
        # could fire on a re-add — and the screen must win.
        g2 = get_success_data(
            api.create_peer_group({"center_id": ctx["center"]["id"], "name": "G2b"}, FO)
        )
        for i in range(4):
            member = get_success_data(
                api.create_member(
                    {"branch_id": ctx["branch"]["id"],
                     "full_name": f"G2b Member {i}", "national_id": f"NID-G2b-{i}"},
                    FO,
                )
            )
            get_success_data(api.add_group_member(g2["id"], {"member_id": member["id"]}, FO))
        response = api.add_group_member(g2["id"], {"member_id": member_id}, FO)
        validate_error(response, ApiErrorId.ERR_MEMBER_BLACKLISTED, expected_status=403)


class TestDisbursePriorityStateOverFiscal:
    def test_priority_state_beats_fiscal_at_disbursement(self, api):
        """PRD §2.8: "One consequence worth stating explicitly: at disbursement,
        the state check (`ERR_APPLICATION_NOT_APPROVED`) outranks the fiscal
        ladder check, so a non-approved application can never surface
        `ERR_LADDER_CEILING_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_at_disbursement
        """
        ctx = setup_active_group(prefix="state-fiscal")
        application = draft_application(ctx["group"]["id"], ctx["applicant"]["id"], 250_000)
        submit_application(application["id"])
        # Only 3 of the 4 required APPROVE votes.
        for peer in ctx["peers"][:3]:
            get_success_data(
                api.cast_vote(
                    application["id"], {"decision": "APPROVE"},
                    make_member_headers(peer["id"]),
                )
            )
        current = get_success_data(api.get_loan_application(application["id"], PA))
        assert current["status"] == "VOTING"

        response = api.disburse_loan_application(application["id"], BM)
        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_APPROVED, expected_status=409)
        assert response.status_code != 422, "the fiscal check never surfaces here"
        still = get_success_data(api.get_loan_application(application["id"], PA))
        assert still["status"] == "VOTING"

    def test_priority_state_beats_fiscal_at_disbursement_from_draft(self, api):
        """PRD §2.8: "One consequence worth stating explicitly: at disbursement,
        the state check (`ERR_APPLICATION_NOT_APPROVED`) outranks the fiscal
        ladder check, so a non-approved application can never surface
        `ERR_LADDER_CEILING_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_at_disbursement
        """
        ctx = setup_active_group(prefix="state-fiscal-draft")
        # DRAFT application over the cycle-1 ceiling, never submitted.
        application = draft_application(ctx["group"]["id"], ctx["applicant"]["id"], 250_000)
        response = api.disburse_loan_application(application["id"], BM)
        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_APPROVED, expected_status=409)
        still = get_success_data(api.get_loan_application(application["id"], PA))
        assert still["status"] == "DRAFT"


class TestMemberScopedFilters:
    def test_member_scoped_list_filters_compose(self, api):
        """PRD §2.9: "loan applications accept `peer_group_id`, `member_id`, and
        `status`; loans accept `member_id`, `loan_application_id`, and
        `status`".

        Design: Corner/cross_cutting_layers/member_scoped_list_filters_compose
        """
        ctx = setup_active_group(prefix="filters")
        application, loan = disburse_member(
            ctx["group"]["id"], ctx["applicant"], ctx["peers"]
        )
        rows, meta = validate_paginated(
            api.list_loans(PA, params={"member_id": ctx["applicant"]["id"], "status": "ACTIVE"})
        )
        assert len(rows) == 1 and meta["total_count"] == 1
        assert rows[0]["id"] == loan["id"]

        empty, meta_empty = validate_paginated(
            api.list_loans(PA, params={"member_id": ctx["peers"][0]["id"], "status": "ACTIVE"})
        )
        assert empty == [] and meta_empty["total_count"] == 0

        apps, meta_apps = validate_paginated(
            api.list_loan_applications(PA, params={"member_id": ctx["applicant"]["id"]})
        )
        assert len(apps) == 1 and meta_apps["total_count"] == 1
        assert apps[0]["status"] == "DISBURSED"
