"""Multi-hop cascades: graduation with outcome checkpoints, and phase advancement."""
from test_helpers import (
    LND_STATEMENT_SEQUENCE,
    ApiErrorId,
    assert_instant_eq,
    completion_payload,
    create_active_agreement,
    create_and_pay_lnd_statement,
    create_cohort,
    create_enrolled_student,
    create_partner,
    placement_payload,
    read_cohort,
    read_student,
    setup_graduation_ready_placement,
    setup_student_at_phase,
    staff_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

GRADUATION_INSTANT = "2027-01-15T00:00:00Z"


def test_placement_completion_cascades_into_three_outcome_checkpoints(api):
    """PRD §3.6: "the student graduates: `current_phase` advances `INTERNSHIP →
    COMPLETED`, `graduation_at` is stamped with the logical clock, and three outcome
    checkpoints are created as described in §3.8"
    PRD §3.8: "the system creates three outcome checkpoints for the student, one at
    each `interval_months` value of 3, 6 and 12, and writes each one's `due_date` as
    `graduation_at` advanced by that many calendar months"

    Design: Difficulty/transitive_cascade/graduation_cascade_reaches_outcome_checkpoints
    """
    scenario = setup_graduation_ready_placement()

    data = validate_success(
        api.complete_placement(
            scenario.placement["id"], completion_payload(outcome="CONVERTED"), staff_headers()
        ),
        200,
    )
    assert data["state"] == "COMPLETED", data["state"]

    student = read_student(scenario.student["id"])
    assert student["current_phase"] == "COMPLETED", student["current_phase"]
    assert_instant_eq(student["graduation_at"], GRADUATION_INSTANT, "Student.graduation_at")

    checkpoints, meta = validate_paginated(
        api.list_student_checkpoints(scenario.student["id"], staff_headers())
    )
    assert meta["total_count"] == 3, meta
    assert [item["interval_months"] for item in checkpoints] == [3, 6, 12], checkpoints
    by_interval = {item["interval_months"]: item for item in checkpoints}
    assert_instant_eq(by_interval[3]["due_date"], "2027-04-15T00:00:00Z", "3-month due_date")
    assert_instant_eq(by_interval[12]["due_date"], "2028-01-15T00:00:00Z", "12-month due_date")


def test_completion_records_the_conversion_and_stamps_the_graduate(api):
    """PRD §3.6: "The completion moves the placement `ACTIVE → COMPLETED`."
    PRD §3.6: "The student's `conversion_streak` increments by 1 when the outcome is
    `CONVERTED` and resets to 0 when it is `NOT_CONVERTED`."
    PRD §3.8: "Each checkpoint starts with `employment_status` at `UNKNOWN` and no
    wage recorded."

    Design: Difficulty/transitive_cascade/graduation_cascade_reaches_outcome_checkpoints
    """
    scenario = setup_graduation_ready_placement()
    assert scenario.placement["state"] == "ACTIVE", scenario.placement["state"]

    validate_success(
        api.complete_placement(
            scenario.placement["id"], completion_payload(outcome="CONVERTED"), staff_headers()
        ),
        200,
    )

    placement = validate_success(
        api.get_placement(scenario.placement["id"], staff_headers()), 200
    )
    assert placement["state"] == "COMPLETED", placement["state"]
    assert placement["outcome"] == "CONVERTED", placement["outcome"]

    student = read_student(scenario.student["id"])
    assert student["conversion_streak"] == 1, student["conversion_streak"]
    assert student["current_phase"] == "COMPLETED", student["current_phase"]

    checkpoints, _ = validate_paginated(
        api.list_student_checkpoints(scenario.student["id"], staff_headers())
    )
    for checkpoint in checkpoints:
        assert checkpoint["employment_status"] == "UNKNOWN", checkpoint
        assert checkpoint.get("hourly_wage_cents") is None, checkpoint


def test_stipend_payment_advances_the_phase_and_recomputes_the_cohort_award(api):
    """PRD §3.2: "Reaching 12 points while the student has at least one statement at
    status `PAID` for phase `L_AND_D` and a `roster_status` other than `DISMISSED`
    advances `current_phase` from `L_AND_D` to `INTERNSHIP`"
    PRD §3.5: "Every payment also recomputes the `awarded_points` of the cohort the
    student is enrolled in, using the cohort award calculation in §3.2."

    Design: Difficulty/transitive_cascade/stipend_payment_cascade_reopens_matching
    """
    partner = create_partner()
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])
    create_active_agreement(partner)
    setup_student_at_phase(student, cohort["id"], statements=2)

    third = LND_STATEMENT_SEQUENCE[2]
    create_and_pay_lnd_statement(
        student["id"],
        period_start=third[0], period_end=third[1],
        hours_attended=third[2], hours_expected=third[3],
        behavior_incidents=third[4],
    )

    student_now = read_student(student["id"])
    assert student_now["lifetime_contract_points"] == 13, student_now["lifetime_contract_points"]
    assert student_now["current_phase"] == "INTERNSHIP", student_now["current_phase"]
    assert read_cohort(cohort["id"])["awarded_points"] == 204, read_cohort(cohort["id"])


def test_phase_advancement_reopens_placement_matching(api):
    """PRD §3.4: "the server checks that the student is eligible for matching —
    `application_state` at `ENROLLED` with `current_phase` at `INTERNSHIP`, or
    `current_phase` at `COMPLETED`; anything else is `ERR_NOT_ELIGIBLE_FOR_MATCH`
    (409)"

    The same request is refused before the payment that crosses twelve points and
    succeeds afterwards, when it creates the placement at MATCHED.

    Design: Difficulty/transitive_cascade/stipend_payment_cascade_reopens_matching
    """
    partner = create_partner()
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])
    agreement = create_active_agreement(partner)
    setup_student_at_phase(student, cohort["id"], statements=2)

    refused = api.create_placement(
        placement_payload(agreement["id"], student["id"]), staff_headers()
    )
    validate_error(refused, ApiErrorId.ERR_NOT_ELIGIBLE_FOR_MATCH)

    third = LND_STATEMENT_SEQUENCE[2]
    create_and_pay_lnd_statement(
        student["id"],
        period_start=third[0], period_end=third[1],
        hours_attended=third[2], hours_expected=third[3],
        behavior_incidents=third[4],
    )

    placement = validate_success(
        api.create_placement(
            placement_payload(agreement["id"], student["id"]), staff_headers()
        ),
        201,
    )
    assert placement["state"] == "MATCHED", placement["state"]
    assert read_student(student["id"])["total_stipend_paid_cents"] == 98775, (
        read_student(student["id"])["total_stipend_paid_cents"]
    )
