"""The binding match run: the four-hop assignment cascade, the suspended
college skip, slot conservation, the once-per-cycle guard, the withdrawn
candidate filter, and immediate read consistency."""
from test_helpers import (
    ApiErrorId,
    CLOCK_IN_RANKING_WINDOW,
    TEST_USERS,
    advance_cycle_to_phase,
    assert_aid_package,
    assert_run_match_result,
    assert_slot_conservation,
    create_application,
    create_college,
    create_cycle,
    create_student,
    expect_error,
    expect_success,
    find_match_for_application,
    get_application,
    get_college,
    get_cycle,
    get_student,
    ranking_entry,
    release_match_payload,
    reset_clock,
    review_application,
    set_clock,
    setup_matched,
    setup_ranking_submitted,
    submit_application,
    submit_rankings,
    validate_paginated,
    withdraw_application,
)

_ADMIN = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/run_match_four_hop_cascade
# ---------------------------------------------------------------------------

def test_run_match_cascade_application_and_match_hops(api):
    """PRD §3.5: "A single assignment fans out into a four-link cascade.
    First, a Match record is created in `BINDING` status with
    `rank_position_awarded` set to the winning `rank_position`, `matched_at`
    stamped from the logical clock, and `application_id`, `college_id`, and
    `cycle_id` recorded."
    PRD §3.5: "Third, the application moves `RANKING_LOCKED` → `MATCHED` and
    its `matched_college_id` is set to the winning college."
    PRD §3.5: "In all cases the run's response reports `matched_count` and
    `unmatched_count`, the cycle's `match_run_completed` flips to true, and
    the cycle's `version` increments by 1."

    Design: Difficulty/transitive_cascade/run_match_four_hop_cascade
    """
    ctx = setup_matched()
    result = ctx["run_match_result"]
    assert_run_match_result(result)
    assert result == {"matched_count": 1, "unmatched_count": 0}
    application = ctx["application"]
    assert application["status"] == "MATCHED"
    assert application["matched_college_id"] == ctx["college"]["id"]
    match = ctx["match"]
    assert match["status"] == "BINDING"
    assert match["rank_position_awarded"] == 1
    assert match["application_id"] == application["id"]
    assert match["college_id"] == ctx["college"]["id"]
    assert match["cycle_id"] == ctx["cycle"]["id"]
    assert ctx["cycle"]["match_run_completed"] is True


def test_run_match_cascade_package_slots_and_stage_hops(api):
    """PRD §3.5: "Second, the match auto-creates its aid package:
    `PROVISIONAL` status, `guaranteed_full_need` true, `coa_cents` copied from
    the college's current figure, and all amounts computed under the
    provisional contribution variant and the composition waterfall of §3.7 —
    while the college's `slots_committed` rises by exactly 1."
    PRD §3.5: "Fourth, the student's `student_stage` advances `FINALIST` →
    `MATCHED`."

    Design: Difficulty/transitive_cascade/run_match_four_hop_cascade
    """
    ctx = setup_matched()
    package = ctx["aid_package"]
    assert_aid_package(package)
    assert package["status"] == "PROVISIONAL"
    assert package["guaranteed_full_need"] is True
    assert package["coa_cents"] == ctx["college"]["coa_cents"] == 8_000_000
    assert package["match_id"] == ctx["match"]["id"]
    assert package["aid_variant"] == "PROVISIONAL"
    college = ctx["college"]
    assert college["slots_committed"] == 1
    assert_slot_conservation(college)
    student = get_student(ctx["student"]["id"])
    assert student["student_stage"] == "MATCHED"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/suspended_college_skipped_in_match_run
# ---------------------------------------------------------------------------

def test_suspended_college_skipped_produces_unmatched(api):
    """PRD §3.5: "Each candidate's current list is walked in `rank_position`
    ascending, and a college qualifies at a position when three conditions
    hold at once: the college is `ACTIVE`, its `slots_committed` is still
    below its `match_slots`, and the application's `academic_index` is at
    least the college's `min_academic_index`."
    PRD §3.5: "A candidate whose list offers no qualifying position — every
    ranked college full or `SUSPENDED` — is never an error: the application
    falls through `RANKING_LOCKED` → `UNMATCHED` → `REGULAR_POOL` inside the
    same run and becomes visible on every partner college's regular-pool
    read."

    Design: Difficulty/cross_entity_state_dependency/suspended_college_skipped_in_match_run
    """
    ctx = setup_ranking_submitted()
    expect_success(api.suspend_college(ctx["college"]["id"], _ADMIN), 200)
    advance_cycle_to_phase(ctx["cycle"]["id"], "MATCH_RUN")
    result = expect_success(api.run_match(ctx["cycle"]["id"], _ADMIN), 200)
    assert result["matched_count"] == 0
    assert result["unmatched_count"] == 1, (
        "the suspended college is skipped, so the single-list candidate falls "
        "through as unmatched — never an error"
    )
    application = get_application(ctx["application"]["id"])
    assert application["status"] == "REGULAR_POOL"
    assert application["matched_college_id"] is None


def test_suspended_college_keeps_zero_committed_slots(api):
    """PRD §3.1: "a suspended college is excluded from future ranking
    submissions and from the next match run, while its existing matches and
    aid packages are entirely unaffected."
    PRD §2.9: "Its `slots_committed` counter tracks how many of those slots
    are spoken for, counting exactly the college's matches in `BINDING` or
    `ENROLLED` status."

    Design: Difficulty/cross_entity_state_dependency/suspended_college_skipped_in_match_run
    """
    ctx = setup_ranking_submitted()
    expect_success(api.suspend_college(ctx["college"]["id"], _ADMIN), 200)
    advance_cycle_to_phase(ctx["cycle"]["id"], "MATCH_RUN")
    expect_success(api.run_match(ctx["cycle"]["id"], _ADMIN), 200)
    college = get_college(ctx["college"]["id"])
    assert college["status"] == "SUSPENDED"
    assert college["slots_committed"] == 0, (
        "no match was created against the suspended college"
    )
    data, meta = validate_paginated(
        api.list_matches(_ADMIN, params={"cycle_id": ctx["cycle"]["id"]})
    )
    assert data == [] and meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/slot_conservation_across_match_and_release
# ---------------------------------------------------------------------------

def _setup_two_finalists_one_slot():
    """Two finalists each rank the same 1-slot college; the first applicant
    carries the higher academic_index (1142 vs 1060)."""
    reset_clock()
    cycle = create_cycle()
    advance_cycle_to_phase(cycle["id"], "RECRUITMENT")
    college = create_college(match_slots=1)
    advance_cycle_to_phase(cycle["id"], "APPLICATION_OPEN")
    student_hi = create_student()
    student_lo = create_student()
    app_hi = create_application(
        student_hi["id"], cycle["id"], gpa_scaled=390, test_score=1450
    )
    app_lo = create_application(
        student_lo["id"], cycle["id"], gpa_scaled=375, test_score=1240
    )
    app_hi = submit_application(app_hi["id"], student_hi["id"])
    app_lo = submit_application(app_lo["id"], student_lo["id"])
    assert app_hi["academic_index"] == 1142  # 390*2 + floor(1450/4)
    assert app_lo["academic_index"] == 1060  # 375*2 + floor(1240/4)
    advance_cycle_to_phase(cycle["id"], "REVIEW")
    app_hi = review_application(app_hi["id"], "FINALIST")
    app_lo = review_application(app_lo["id"], "FINALIST")
    advance_cycle_to_phase(cycle["id"], "RANKING")
    set_clock(CLOCK_IN_RANKING_WINDOW)
    submit_rankings(
        app_hi["id"], student_hi["id"],
        [ranking_entry(college["id"], 1)], app_hi["version"],
    )
    submit_rankings(
        app_lo["id"], student_lo["id"],
        [ranking_entry(college["id"], 1)], app_lo["version"],
    )
    advance_cycle_to_phase(cycle["id"], "MATCH_RUN")
    return cycle, college, app_hi, app_lo


def test_match_consumes_exactly_one_slot(api):
    """PRD §2.9: "The conserved invariant: for every college, `match_slots`
    always equals `slots_committed` plus the free slots still available — a
    match consumes exactly one slot when it is created, and an administrative
    release returns exactly one slot to the pool."
    PRD §3.5: "The candidate set is the cycle's applications in
    `RANKING_LOCKED`, processed in descending `academic_index` with ties
    broken by `created_at` ascending — never by id."

    Design: Difficulty/compensating_invariant/slot_conservation_across_match_and_release
    """
    cycle, college, app_hi, app_lo = _setup_two_finalists_one_slot()
    before = get_college(college["id"])
    assert before["slots_committed"] == 0, (
        "a newly registered college starts with slots_committed at zero (PRD §3.1)"
    )
    result = expect_success(api.run_match(cycle["id"], _ADMIN), 200)
    assert result["matched_count"] == 1 and result["unmatched_count"] == 1
    after = get_college(college["id"])
    assert after["slots_committed"] == 1, "1 == 1 committed + 0 free"
    assert_slot_conservation(after)
    assert get_application(app_hi["id"])["status"] == "MATCHED", (
        "the higher academic_index candidate takes the only slot"
    )
    assert get_application(app_lo["id"])["status"] == "REGULAR_POOL", (
        "exhausted quota is an ordinary outcome, never an error (PRD §2.9)"
    )


def test_release_returns_exactly_one_slot(api):
    """PRD §2.9: "The conserved invariant: for every college, `match_slots`
    always equals `slots_committed` plus the free slots still available — a
    match consumes exactly one slot when it is created, and an administrative
    release returns exactly one slot to the pool."
    PRD §3.8: "Its aid package, if still `PROVISIONAL`, `FINALIZED`, or
    `REVISED`, is voided, and the college's `slots_committed` drops by exactly
    1 — the freed slot returns to the pool per the conservation rule of §2.9."

    Design: Difficulty/compensating_invariant/slot_conservation_across_match_and_release
    """
    cycle, college, app_hi, app_lo = _setup_two_finalists_one_slot()
    expect_success(api.run_match(cycle["id"], _ADMIN), 200)
    match = find_match_for_application(app_hi["id"])
    payload = release_match_payload("compensation test")
    expect_success(api.release_match(match["id"], payload, _ADMIN), 200, payload)
    after = get_college(college["id"])
    assert after["slots_committed"] == 0, (
        "the compensating release restores 1 == 0 committed + 1 free"
    )
    assert_slot_conservation(after)


# ---------------------------------------------------------------------------
# Corner: once-per-cycle guard, withdrawn candidate filter, immediate reads
# ---------------------------------------------------------------------------

def test_second_run_match_returns_match_already_run(api):
    """PRD §3.5: "A run requested against a cycle whose `match_run_completed`
    is already true is rejected with `ERR_MATCH_ALREADY_RUN`."

    Design: Corner/validations/second_run_match_returns_match_already_run
    """
    ctx = setup_matched()
    resp = api.run_match(ctx["cycle"]["id"], _ADMIN)
    expect_error(resp, ApiErrorId.ERR_MATCH_ALREADY_RUN)
    data, meta = validate_paginated(
        api.list_matches(_ADMIN, params={"cycle_id": ctx["cycle"]["id"]})
    )
    assert meta["total_count"] == 1, (
        "the rejected second run creates no additional Match rows"
    )


def test_run_match_skips_withdrawn_application(api):
    """PRD §3.5: "The candidate set is the cycle's applications in
    `RANKING_LOCKED`, processed in descending `academic_index` with ties
    broken by `created_at` ascending — never by id."
    PRD §3.5: "An empty candidate set is likewise legal: the run succeeds and
    reports `matched_count` 0 and `unmatched_count` 0."
    PRD §3.3: "Withdrawal is the student's exit hatch at every point before a
    binding match: from `DRAFT`, `UNDER_REVIEW`, `FINALIST`,
    `RANKING_SUBMITTED`, or `REGULAR_POOL` the application lands in
    `WITHDRAWN`, ..."

    Design: Corner/calculations/run_match_skips_withdrawn_application
    """
    ctx = setup_ranking_submitted()
    withdrawn = withdraw_application(
        ctx["application"]["id"], ctx["student"]["id"]
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        "withdrawal from RANKING_SUBMITTED is legal, so the application is "
        "never locked and never a candidate"
    )
    advance_cycle_to_phase(ctx["cycle"]["id"], "MATCH_RUN")
    result = expect_success(api.run_match(ctx["cycle"]["id"], _ADMIN), 200)
    assert result == {"matched_count": 0, "unmatched_count": 0}
    data, meta = validate_paginated(
        api.list_matches(_ADMIN, params={"cycle_id": ctx["cycle"]["id"]})
    )
    assert data == [] and meta["total_count"] == 0


def test_match_run_response_immediately_consistent(api):
    """PRD §3.5: "In all cases the run's response reports `matched_count` and
    `unmatched_count`, the cycle's `match_run_completed` flips to true, and
    the cycle's `version` increments by 1."
    PRD §3.5: "Third, the application moves `RANKING_LOCKED` → `MATCHED` and
    its `matched_college_id` is set to the winning college. Fourth, the
    student's `student_stage` advances `FINALIST` → `MATCHED`."

    Design: Corner/consistency_model/match_run_response_immediately_consistent
    """
    ctx = setup_matched()
    result = ctx["run_match_result"]
    assert result["matched_count"] == 1 and result["unmatched_count"] == 0
    application = get_application(ctx["application"]["id"])
    college = get_college(ctx["college"]["id"])
    student = get_student(ctx["student"]["id"])
    assert application["status"] == "MATCHED"
    assert college["slots_committed"] == 1
    assert student["student_stage"] == "MATCHED"
    assert get_cycle(ctx["cycle"]["id"])["match_run_completed"] is True
