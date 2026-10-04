"""Regular-decision admissions and their unguaranteed packages, the
application status filter, the regular-pool empty fallback and tie-break, and
match-side enrollment."""
from test_helpers import (
    TEST_USERS,
    advance_cycle_to_phase,
    assert_aid_package,
    assert_aid_package_balances,
    assert_outcome_record,
    create_application,
    create_college,
    create_cycle,
    create_student,
    make_college_officer_headers,
    reset_clock,
    review_application,
    set_clock,
    setup_admitted_regular,
    setup_enrolled_match,
    setup_submitted_application,
    submit_application,
    validate_paginated,
)

_ADMIN = TEST_USERS["program_admin_headers"]


def test_regular_decision_admit_creates_unguaranteed_package(api):
    """PRD §3.8: "`ADMIT` lands the application in `ADMITTED_REGULAR` and
    creates its aid package in the same motion: `PROVISIONAL` status,
    `guaranteed_full_need` false, `match_id` null, `college_id` set to the
    acting college, and amounts computed under the provisional variant."
    PRD §3.7: "The `PROVISIONAL` variant works from the application's
    self-reported figures: an allowance of $24,000 — 2,400,000 cents — plus
    $6,000 (600,000 cents) per household member is subtracted from
    `household_income_cents`, the excess is multiplied by 0.20, the product is
    rounded half-up to a whole cent, and the result is floored at zero so the
    contribution never goes negative."

    Design: Corner/endpoints/regular_decision_admit_creates_unguaranteed_package
    """
    ctx = setup_admitted_regular()
    assert ctx["application"]["status"] == "ADMITTED_REGULAR"
    package = ctx["aid_package"]
    assert_aid_package(package)
    assert package["college_id"] == ctx["college"]["id"]
    assert package["match_id"] is None
    assert package["guaranteed_full_need"] is False
    assert package["status"] == "PROVISIONAL"
    assert package["aid_variant"] == "PROVISIONAL"
    assert package["efc_cents"] == 340000, (
        "(6,500,000 - 4,800,000) * 0.20 == 340,000"
    )
    assert package["grant_cents"] == 7360000, (
        "need 7,660,000 - work-study 300,000 - loan 0"
    )
    assert_aid_package_balances(package)


def test_applications_list_filters_by_status(api):
    """PRD §3.3: "Applications can be listed filtered by `student_id`,
    `cycle_id`, `referral_id`, `matched_college_id`, or `status`."

    Design: Corner/endpoints/applications_list_filters_by_status
    """
    ctx = setup_submitted_application()
    student_b = create_student()
    app_b = create_application(student_b["id"], ctx["cycle"]["id"])
    submit_application(app_b["id"], student_b["id"])
    advance_cycle_to_phase(ctx["cycle"]["id"], "REVIEW")
    review_application(ctx["application"]["id"], "NOT_FINALIST")
    data, meta = validate_paginated(
        api.list_applications(
            _ADMIN,
            params={"cycle_id": ctx["cycle"]["id"], "status": "UNDER_REVIEW"},
        )
    )
    assert meta["total_count"] == 1, (
        "the NOT_FINALIST application is filtered out"
    )
    assert [row["id"] for row in data] == [app_b["id"]]


def test_regular_pool_empty_returns_empty_array(api):
    """PRD §3.8: "Ordering is by descending score with ties broken by the
    application's `created_at` ascending, and an empty pool returns an empty
    array with HTTP 200 — never an error."

    Design: Corner/cross_cutting_layers/regular_pool_empty_returns_empty_array
    """
    reset_clock()
    cycle = create_cycle()
    college = create_college()
    advance_cycle_to_phase(cycle["id"], "MATCH_RUN")
    data, meta = validate_paginated(
        api.get_regular_pool(
            college["id"],
            make_college_officer_headers(college["id"]),
            params={"cycle_id": cycle["id"]},
        )
    )
    assert data == []
    assert meta["total_count"] == 0


def test_regular_pool_tie_break_uses_created_at(api):
    """PRD §3.8: "Ordering is by descending score with ties broken by the
    application's `created_at` ascending, and an empty pool returns an empty
    array with HTTP 200 — never an error."

    Design: Corner/cross_cutting_layers/regular_pool_tie_break_uses_created_at
    """
    reset_clock()
    cycle = create_cycle()
    advance_cycle_to_phase(cycle["id"], "RECRUITMENT")
    college = create_college()
    advance_cycle_to_phase(cycle["id"], "APPLICATION_OPEN")
    student_a = create_student()
    app_a = create_application(
        student_a["id"], cycle["id"], gpa_scaled=370, test_score=1200
    )
    # Move the logical clock so the second application's created_at strictly
    # follows the first (every system-assigned timestamp reads this clock).
    set_clock("2026-09-02T00:00:00Z")
    student_b = create_student()
    app_b = create_application(
        student_b["id"], cycle["id"], gpa_scaled=370, test_score=1200
    )
    app_a = submit_application(app_a["id"], student_a["id"])
    app_b = submit_application(app_b["id"], student_b["id"])
    assert app_a["academic_index"] == 1040  # 370*2 + floor(1200/4)
    assert app_b["academic_index"] == 1040
    assert app_a["need_tier"] == "STANDARD" and app_b["need_tier"] == "STANDARD"
    advance_cycle_to_phase(cycle["id"], "REVIEW")
    review_application(app_a["id"], "FINALIST")
    review_application(app_b["id"], "FINALIST")
    advance_cycle_to_phase(cycle["id"], "MATCH_RUN")
    data, meta = validate_paginated(
        api.get_regular_pool(
            college["id"],
            make_college_officer_headers(college["id"]),
            params={"cycle_id": cycle["id"]},
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in data] == [app_a["id"], app_b["id"]], (
        "equal priority scores (1040, no bonuses) fall back to created_at "
        "ascending — the first-created application leads"
    )


def test_enroll_matched_student_creates_outcome_record(api):
    """PRD §3.8: "A matched student is enrolled from the match side instead: a
    `CollegeOfficer` of the match's college, or a `ProgramAdmin`, records
    enrollment against a `BINDING` match — any other match status is
    `ERR_INVALID_STATE` — which moves the match `BINDING` → `ENROLLED`,
    creates the outcome record in `ENROLLED_Y1` with `match_id` set and
    application, college, and cycle copied from the match, raises
    `enrolled_count` by 1, cascades the application `MATCHED` → `ENROLLED`,
    sets `student_stage` to `ENROLLED`, and increments the match's `version`."

    Design: Corner/endpoints/enroll_matched_student_creates_outcome_record
    """
    ctx = setup_enrolled_match()
    match = ctx["match"]
    assert match["status"] == "ENROLLED"
    record = ctx["outcome_record"]
    assert_outcome_record(record)
    assert record["status"] == "ENROLLED_Y1"
    assert record["match_id"] == match["id"]
    assert record["application_id"] == ctx["application"]["id"]
    assert record["college_id"] == ctx["college"]["id"]
    assert record["cycle_id"] == ctx["cycle"]["id"]
    assert ctx["college"]["enrolled_count"] == 1
    assert ctx["application"]["status"] == "ENROLLED"
