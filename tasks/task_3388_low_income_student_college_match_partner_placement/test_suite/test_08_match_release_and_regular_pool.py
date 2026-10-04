"""The binding-match exit paths (release cascade, binding withdraw refusal)
and the regular-pool ordering read with its need-aware branch."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_cycle_to_phase,
    create_college,
    create_counselor,
    create_cycle,
    create_referral,
    create_student,
    complete_prep_program,
    create_application,
    expect_error,
    expect_success,
    find_match_for_application,
    get_application,
    get_college,
    get_current_rankings,
    make_college_officer_headers,
    make_counselor_headers,
    make_student_headers,
    ranking_entry,
    regular_decision_payload,
    release_match_payload,
    reset_clock,
    review_application,
    setup_matched,
    setup_ranking_submitted,
    setup_released_match,
    submit_application,
    submit_rankings,
    submit_rankings_payload,
    validate_paginated,
)

_ADMIN = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/match_release_compensation_cascade
# ---------------------------------------------------------------------------

def test_release_voids_package_and_returns_slot(api):
    """PRD §3.8: "The release cascade has four links. The match itself moves
    `BINDING` → `RELEASED` and its `version` increments. Its aid package, if
    still `PROVISIONAL`, `FINALIZED`, or `REVISED`, is voided, and the
    college's `slots_committed` drops by exactly 1 — the freed slot returns to
    the pool per the conservation rule of §2.9."

    Design: Difficulty/transitive_cascade/match_release_compensation_cascade
    """
    ctx = setup_released_match()
    assert ctx["match"]["status"] == "RELEASED"
    package = ctx["aid_package"]
    assert package["status"] == "VOID", (
        f"the released match's package is voided, got {package['status']!r}"
    )
    assert ctx["college"]["slots_committed"] == 0, (
        "the freed slot returns to the pool"
    )


def test_release_reenters_regular_pool_and_demotes_stage(api):
    """PRD §3.8: "The application cascades `MATCHED` → `REGULAR_POOL` with
    `matched_college_id` cleared to null, rejoining the regular-decision pool.
    And the student's `student_stage` falls back to `FINALIST`."

    Design: Difficulty/transitive_cascade/match_release_compensation_cascade
    """
    ctx = setup_released_match()
    application = ctx["application"]
    assert application["status"] == "REGULAR_POOL"
    assert application["matched_college_id"] is None
    assert ctx["student"]["student_stage"] == "FINALIST"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/application_revision_loop_and_release_reentry
# ---------------------------------------------------------------------------

def _setup_finalist_with_two_colleges():
    """One finalist whose first accepted list names only college one; a second
    ACTIVE college exists for the resubmission."""
    ctx = setup_ranking_submitted(college_count=1)
    second = create_college()
    return ctx, ctx["college"], second


def test_ranking_resubmission_is_an_atomic_replace_self_loop(api):
    """PRD §3.4: "An accepted submission replaces the application's ranking
    rows atomically — the previous list is discarded wholesale, never edited
    row by row — and the new rows carry a `list_seq` one higher than the
    previous list's, starting at 1 on the first accepted submission. The first
    submission transitions the application `FINALIST` → `RANKING_SUBMITTED`; a
    resubmission is a self-loop that leaves it in `RANKING_SUBMITTED`. Every
    accepted submission increments the application's `version` by 1, which is
    precisely what invalidates any stale `expected_application_version` a
    client may still be holding."

    Design: Difficulty/non_linear_state_machine/application_revision_loop_and_release_reentry
    """
    ctx, first_college, second_college = _setup_finalist_with_two_colleges()
    pre = ctx["application_version"]
    payload = submit_rankings_payload(
        [ranking_entry(second_college["id"], 1),
         ranking_entry(first_college["id"], 2)],
        pre,
    )
    resp = api.submit_rankings(
        ctx["application"]["id"], payload,
        make_student_headers(ctx["student"]["id"]),
    )
    application = expect_success(resp, 200, payload)
    assert application["status"] == "RANKING_SUBMITTED", (
        "resubmission is a self-loop back into RANKING_SUBMITTED"
    )
    assert application["version"] == pre + 1
    rows = get_current_rankings(ctx["application"]["id"])
    assert len(rows) == 2
    assert all(row["list_seq"] == 2 for row in rows), (
        "the replacement list carries list_seq one higher"
    )
    top = {row["rank_position"]: row["college_id"] for row in rows}
    assert top[1] == second_college["id"] and top[2] == first_college["id"]


def test_release_reentry_into_regular_pool_then_admit(api):
    """PRD §3.8: "The application cascades `MATCHED` → `REGULAR_POOL` with
    `matched_college_id` cleared to null, rejoining the regular-decision
    pool."
    PRD §3.8: "`ADMIT` lands the application in `ADMITTED_REGULAR` and creates
    its aid package in the same motion: `PROVISIONAL` status,
    `guaranteed_full_need` false, `match_id` null, `college_id` set to the
    acting college, and amounts computed under the provisional variant."

    Design: Difficulty/non_linear_state_machine/application_revision_loop_and_release_reentry
    """
    ctx, first_college, second_college = _setup_finalist_with_two_colleges()
    submit_rankings(
        ctx["application"]["id"], ctx["student"]["id"],
        [ranking_entry(second_college["id"], 1),
         ranking_entry(first_college["id"], 2)],
        ctx["application_version"],
    )
    advance_cycle_to_phase(ctx["cycle"]["id"], "MATCH_RUN")
    expect_success(api.run_match(ctx["cycle"]["id"], _ADMIN), 200)
    application = get_application(ctx["application"]["id"])
    assert application["status"] == "MATCHED"
    assert application["matched_college_id"] == second_college["id"]
    match = find_match_for_application(application["id"])
    assert match["rank_position_awarded"] == 1

    release = release_match_payload("extenuating circumstances")
    expect_success(api.release_match(match["id"], release, _ADMIN), 200, release)
    application = get_application(application["id"])
    assert application["status"] == "REGULAR_POOL", (
        "release-driven re-entry returns the application to the branching pool"
    )
    assert application["matched_college_id"] is None

    advance_cycle_to_phase(ctx["cycle"]["id"], "REGULAR_DECISION")
    decision = regular_decision_payload("ADMIT")
    resp = api.regular_decision(
        application["id"], decision,
        make_college_officer_headers(first_college["id"]),
    )
    admitted = expect_success(resp, 200, decision)
    assert admitted["status"] == "ADMITTED_REGULAR"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/priority_score_need_aware_branch_flips_regular_pool_order
# ---------------------------------------------------------------------------

def _setup_two_applicants_in_regular_pool():
    """Applicant A: prep alum + converted counselor referral, HIGH need,
    academic_index 985. Applicant B: no bonuses, STANDARD need,
    academic_index 1060. Both slide FINALIST -> REGULAR_POOL (no lists)."""
    reset_clock()
    cycle = create_cycle()
    advance_cycle_to_phase(cycle["id"], "RECRUITMENT")
    college_no_loan = create_college(name="NoLoan College", aid_policy="NO_LOAN")
    college_min_loan = create_college(
        name="MinLoan College", aid_policy="MINIMAL_LOAN"
    )
    counselor = create_counselor()
    student_a = create_student(source="COUNSELOR")
    student_b = create_student()
    referral = create_referral(
        student_a["id"], cycle["id"], make_counselor_headers(counselor["id"])
    )
    complete_prep_program(student_a["id"])
    advance_cycle_to_phase(cycle["id"], "APPLICATION_OPEN")
    app_a = create_application(
        student_a["id"], cycle["id"], referral_id=referral["id"],
        household_income_cents=3_000_000, household_size=4,
        gpa_scaled=355, test_score=1100,
    )
    app_b = create_application(
        student_b["id"], cycle["id"],
        household_income_cents=6_500_000, household_size=4,
        gpa_scaled=375, test_score=1240,
    )
    app_a = submit_application(app_a["id"], student_a["id"])
    app_b = submit_application(app_b["id"], student_b["id"])
    assert app_a["academic_index"] == 985   # 355*2 + floor(1100/4)
    assert app_a["prep_alum"] is True
    assert app_a["need_tier"] == "HIGH"     # 3,000,000 <= 3,250,000 half-cap
    assert app_b["academic_index"] == 1060  # 375*2 + floor(1240/4)
    assert app_b["need_tier"] == "STANDARD"
    advance_cycle_to_phase(cycle["id"], "REVIEW")
    review_application(app_a["id"], "FINALIST")
    review_application(app_b["id"], "FINALIST")
    advance_cycle_to_phase(cycle["id"], "MATCH_RUN")
    return cycle, college_no_loan, college_min_loan, app_a, app_b


def test_need_aware_bonus_leads_at_no_loan_college(api):
    """PRD §3.8: "The pool read takes a `cycle_id` and returns that cycle's
    `REGULAR_POOL` applications ordered for the viewing college by a priority
    score: the application's `academic_index`, plus a 40-point bonus when
    `prep_alum` is set, plus a 25-point bonus when the application cites a
    referral that reached `CONVERTED`, plus a 15-point need-aware bonus that
    applies only when the viewing college's `aid_policy` is `NO_LOAN` and the
    application's `need_tier` is `HIGH`."

    Design: Difficulty/combinatorial_formula/priority_score_need_aware_branch_flips_regular_pool_order
    """
    cycle, college_no_loan, _college_min_loan, app_a, app_b = (
        _setup_two_applicants_in_regular_pool()
    )
    data, meta = validate_paginated(
        api.get_regular_pool(
            college_no_loan["id"],
            make_college_officer_headers(college_no_loan["id"]),
            params={"cycle_id": cycle["id"]},
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in data] == [app_a["id"], app_b["id"]], (
        "at the NO_LOAN college A scores 985+40+25+15 == 1065 against B's 1060"
    )


def test_need_aware_bonus_absent_at_minimal_loan_college(api):
    """PRD §3.8: "Because the need-aware bonus depends on the viewing college,
    the same application can outrank a higher-index competitor at a `NO_LOAN`
    college while losing to it at a `MINIMAL_LOAN` one."
    PRD §3.8: "Ordering is by descending score with ties broken by the
    application's `created_at` ascending, and an empty pool returns an empty
    array with HTTP 200 — never an error."

    Design: Difficulty/combinatorial_formula/priority_score_need_aware_branch_flips_regular_pool_order
    """
    cycle, _college_no_loan, college_min_loan, app_a, app_b = (
        _setup_two_applicants_in_regular_pool()
    )
    data, meta = validate_paginated(
        api.get_regular_pool(
            college_min_loan["id"],
            make_college_officer_headers(college_min_loan["id"]),
            params={"cycle_id": cycle["id"]},
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in data] == [app_b["id"], app_a["id"]], (
        "at the MINIMAL_LOAN college A stays 985+40+25 == 1050 and B leads "
        "on 1060"
    )


# ---------------------------------------------------------------------------
# Corner: binding withdraw refusal and terminal-state release guard
# ---------------------------------------------------------------------------

def test_withdraw_matched_application_returns_match_binding(api):
    """PRD §3.3: "Once the application is `MATCHED` the commitment is binding
    and withdrawal is rejected with `ERR_MATCH_BINDING`."

    Design: Corner/state_machines/withdraw_matched_application_returns_match_binding
    """
    ctx = setup_matched()
    resp = api.withdraw_application(
        ctx["application"]["id"], make_student_headers(ctx["student"]["id"])
    )
    expect_error(resp, ApiErrorId.ERR_MATCH_BINDING)
    refreshed = get_application(ctx["application"]["id"])
    assert refreshed["status"] == "MATCHED", (
        "the binding match survives the rejected withdrawal"
    )


def test_release_released_match_returns_invalid_state(api):
    """PRD §3.8: "A binding match ends only by administrative release: a
    `ProgramAdmin` releases a `BINDING` match, optionally recording a
    `reason`, and releasing a match in any other status is
    `ERR_INVALID_STATE`."
    PRD §2.9: "a match consumes exactly one slot when it is created, and an
    administrative release returns exactly one slot to the pool."

    Design: Corner/state_machines/release_released_match_returns_invalid_state
    """
    ctx = setup_released_match()
    payload = release_match_payload("second release")
    resp = api.release_match(ctx["match"]["id"], payload, _ADMIN)
    expect_error(resp, ApiErrorId.ERR_INVALID_STATE, payload)
    college = get_college(ctx["college"]["id"])
    assert college["slots_committed"] == 0, (
        "the compensation cascade must not fire twice"
    )
