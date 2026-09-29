"""Endpoint surfaces whose behaviour is more than a write: the ungated
enrollment right, the allowance recomputation, the review's third outcome and a
census epoch that finds nothing due.
"""

from test_helpers import (
    ADMIN,
    CASE_MANAGER,
    COORDINATOR,
    USER_IDS,
    assert_census_counts,
    assert_education_enrollment,
    assert_instant_equals,
    assert_life_skills_completion,
    assert_program_counters,
    assert_savings_ledger_entry,
    assert_tlp_placement,
    clear_screening,
    credit_life_skills,
    education_enrollment_payload,
    escalate_screening,
    fetch_admission,
    fetch_placement,
    fetch_program,
    fetch_youth,
    instant,
    intake_youth,
    license_emergency_shelter,
    life_skills_completion_payload,
    move_clock,
    notification_of_admission,
    request_admission,
    setup_placement_with_deposits,
    setup_tlp_placement,
    validate_paginated,
    validate_success,
)

RIVERSIDE = {
    "name": "Riverside Emergency Shelter",
    "licensed_bed_capacity": 2,
    "min_age_years": 12,
    "max_age_years": 17,
    "max_stay_nights": 21,
}
NORTHSIDE = {
    "name": "Northside Transitional Living",
    "licensed_bed_capacity": 3,
    "min_age_years": 16,
    "max_age_years": 20,
    "max_placement_days": 540,
    "savings_match_rate_bp": 2500,
    "required_savings_rate_bp": 2000,
}
DOB_AGE_16 = "2010-03-15"
CLOCK_START_INSTANT = instant("2026-08-01")
PLANNED_DISCHARGE = instant("2026-08-15")
MONTHLY_INCOME_CENTS = 90000


# ─── Instance: the enrollment right survives a frozen risk posture ───

AMAL = {
    "legal_first_name": "Amal",
    "legal_last_name": "Traore",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
SCHOOL_ENROLLMENT = {"school_name": "Riverside High", "enrollment_type": "PUBLIC_K12"}
VERIFICATION_CLOCK = instant("2026-08-04", "10:00:00")


def test_enrollment_is_immediate_for_a_frozen_youth_then_verified(api):
    """PRD §3.9: "The server stamps `enrolled_at` with the clock instant, records the
    acting staff member as `liaison_user_id`, opens the enrollment in `status`
    `IMMEDIATE_ENROLLMENT` with `verified_at` null, and sets `records_waived` to the
    youth's `unaccompanied` value as it stands at enrollment time — recording that
    guardian-held records were waived under the school-enrollment right."
    PRD §3.9: "This operation is deliberately exempt from every gate in the system:
    neither the program posture nor the youth's `risk_posture` ever blocks it, because
    the enrollment right of an unaccompanied youth is unconditional."
    PRD §3.9: "When the receiving school later confirms the youth's records, a staff
    member records the verification, which moves the enrollment `IMMEDIATE_ENROLLMENT
    → VERIFIED` and stamps `verified_at` with the clock instant."
    PRD §3.9: "Enrollments of a youth can be listed and narrowed by `status`."

    Design: Corner/endpoints/education_enrollment_is_immediate_then_verified_even_for_a_frozen_youth
    """
    youth = intake_youth(**dict(AMAL))
    escalate_screening(youth["id"], ["DOCUMENT_WITHHELD"], "EMERGENCY_RELOCATION")
    assert fetch_youth(youth["id"])["risk_posture"] == "FROZEN", (
        "the escalated screening freezes the youth"
    )

    response = api.create_education_enrollment(
        youth["id"], education_enrollment_payload(**dict(SCHOOL_ENROLLMENT)), CASE_MANAGER
    )
    enrollment = validate_success(response, 201)

    assert_education_enrollment(enrollment)
    assert enrollment["status"] == "IMMEDIATE_ENROLLMENT", (
        f"the enrollment opens immediately, got {enrollment['status']}"
    )
    assert enrollment["records_waived"] is True, (
        f"an unaccompanied youth has guardian records waived, got {enrollment['records_waived']}"
    )
    assert enrollment["verified_at"] is None, (
        f"verification has not happened yet, got {enrollment['verified_at']}"
    )
    assert_instant_equals(enrollment["enrolled_at"], CLOCK_START_INSTANT,
                          "the enrollment's enrolled_at")
    assert enrollment["liaison_user_id"] == USER_IDS["SHELTER_CASE_MANAGER"], (
        f"the acting case manager is the liaison, got {enrollment['liaison_user_id']}"
    )

    move_clock(VERIFICATION_CLOCK)
    verified = validate_success(
        api.verify_education_records(enrollment["id"], COORDINATOR)
    )

    assert verified["status"] == "VERIFIED", (
        f"the school confirmed the records, got {verified['status']}"
    )
    assert_instant_equals(verified["verified_at"], VERIFICATION_CLOCK,
                          "the enrollment's verified_at")
    rows, meta = validate_paginated(
        api.list_education_enrollments(youth["id"], CASE_MANAGER, {"status": "VERIFIED"})
    )
    assert meta["total_count"] == 1, (
        f"the verified enrollment is discoverable by status, got {meta['total_count']}"
    )
    assert rows[0]["id"] == enrollment["id"], (
        f"the listed row is the enrollment just verified, got {rows[0]['id']}"
    )
    assert fetch_youth(youth["id"])["risk_posture"] == "FROZEN", (
        "enrolling never lifts the safety freeze"
    )


# ─── Instance: two completions cross the forty-hour milestone ───

YUKI = {
    "legal_first_name": "Yuki",
    "legal_last_name": "Bello",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}


def test_a_second_completion_earns_the_full_sixty_day_bonus(api):
    """PRD §3.7: "The server records the owning placement as `placement_id`, stamps
    `completed_at` with the clock instant and records the acting identifier as
    `verified_by_user_id`."
    PRD §3.7: "Crediting a completion adds the credited hours to the placement's
    `life_skills_credit_hours`, then recomputes `earned_bonus_days` and
    `allowance_days` by the three-step rule, and increments the placement's `version`
    by one."
    PRD §3.7: "Step two computes the life-skills bonus from `life_skills_credit_hours`:
    the milestone bonus is 90 days at 60 or more credited hours, 60 days at 40 or more
    hours, 30 days at 20 or more hours, and 0 days below 20 hours; that milestone bonus
    is then subjected to a late-stage haircut, so `earned_bonus_days` is the milestone
    bonus halved and floored to whole days when step one's `consumed_ratio_bp` has
    reached or passed 7500 — three quarters of the base allowance consumed — and is the
    full milestone bonus otherwise."
    PRD §3.7: "Step three sets `allowance_days` to `base_allowance_days` plus
    `earned_bonus_days`."
    PRD §3.7: "Completions of a placement can be listed."

    Design: Corner/endpoints/life_skills_completions_accumulate_into_the_duration_allowance
    """
    setup = setup_tlp_placement(
        MONTHLY_INCOME_CENTS,
        shelter_program_overrides=dict(RIVERSIDE),
        tlp_program_overrides=dict(NORTHSIDE),
        youth_overrides=dict(YUKI),
    )
    placement = setup["placement"]
    credit_life_skills(placement["id"], 20, "BUDGETING")

    response = api.create_life_skills_completion(
        placement["id"], life_skills_completion_payload(20, "TENANCY"), COORDINATOR
    )
    completion = validate_success(response, 201)

    assert_life_skills_completion(completion)
    assert_instant_equals(completion["completed_at"], CLOCK_START_INSTANT,
                          "the completion's completed_at")
    assert completion["verified_by_user_id"] == USER_IDS["TLP_COORDINATOR"], (
        f"the acting coordinator verified the hours, got {completion['verified_by_user_id']}"
    )

    current = fetch_placement(placement["id"])
    assert_tlp_placement(current)
    assert current["life_skills_credit_hours"] == 40, (
        f"two twenty-hour completions total forty hours, got {current['life_skills_credit_hours']}"
    )
    assert current["days_elapsed"] == 0, (
        f"no time has passed since placement, got {current['days_elapsed']}"
    )
    assert current["consumed_ratio_bp"] == 0, (
        f"zero days elapsed is zero basis points consumed, got {current['consumed_ratio_bp']}"
    )
    assert current["earned_bonus_days"] == 60, (
        "forty credited hours earns the full sixty-day milestone with no haircut, got "
        f"{current['earned_bonus_days']}"
    )
    assert current["base_allowance_days"] == 540, (
        f"the base allowance is copied from the program, got {current['base_allowance_days']}"
    )
    assert current["allowance_days"] == 600, (
        f"540 base days plus 60 earned days is 600, got {current['allowance_days']}"
    )
    _rows, meta = validate_paginated(
        api.list_life_skills_completions(placement["id"], COORDINATOR)
    )
    assert meta["total_count"] == 2, (
        f"both completions are on file, got {meta['total_count']}"
    )


# ─── Instance: a balance below half the requirement lands on probation ───

RAFI = {
    "legal_first_name": "Rafi",
    "legal_last_name": "Delgado",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
REVIEW_CLOCK = instant("2026-09-01")


def test_a_balance_below_half_the_requirement_lands_on_probation(api):
    """PRD §3.8: "The monthly requirement in cents is the placement's
    `documented_monthly_income_cents` multiplied by the program's
    `required_savings_rate_bp`, divided by 10000 and floored to whole cents."
    PRD §3.8: "Otherwise a balance at or above half the required savings, that half
    being floored to whole cents, lands on `SAVINGS_DEFICIENT`."
    PRD §3.8: "Otherwise the review lands on `PROBATION`."
    PRD §3.8: "From `IN_COMPLIANCE` a review may move the placement to
    `SAVINGS_DEFICIENT`, which resets `consecutive_probation_reviews` to 0 and leaves
    the tenancy dimension untouched, or to `PROBATION`, which raises
    `consecutive_probation_reviews` by one and blocks withdrawals from that point on."
    PRD §3.7: "The two dimensions evolve independently: a compliance review never moves
    the tenancy dimension except in the single coupled case described below, and a
    tenancy change never alters `compliance_status` at all."

    Design: Corner/endpoints/compliance_review_drops_to_probation_below_half_the_requirement
    """
    setup = setup_placement_with_deposits(
        [1000],
        documented_monthly_income_cents=MONTHLY_INCOME_CENTS,
        shelter_program_overrides=dict(RIVERSIDE),
        tlp_program_overrides=dict(NORTHSIDE),
        youth_overrides=dict(RAFI),
    )
    entry = setup["entries"][0]
    assert_savings_ledger_entry(entry)
    assert entry["match_component_cents"] == 250, (
        "1000 cents at 2500 basis points is a 250-cent match, got "
        f"{entry['match_component_cents']}"
    )
    move_clock(REVIEW_CLOCK)

    reviewed = validate_success(
        api.run_compliance_review(setup["placement"]["id"], ADMIN)
    )

    assert_tlp_placement(reviewed)
    assert reviewed["days_elapsed"] == 31, (
        f"2026-08-01 to 2026-09-01 is 31 whole days, got {reviewed['days_elapsed']}"
    )
    assert reviewed["required_savings_cents"] == 18000, (
        "90000 cents of income at 2000 basis points is 18000 cents for one full "
        f"month, got {reviewed['required_savings_cents']}"
    )
    assert reviewed["savings_balance_cents"] == 1250, (
        "1000 deposited cents plus a 250-cent match is 1250, got "
        f"{reviewed['savings_balance_cents']}"
    )
    assert reviewed["compliance_status"] == "PROBATION", (
        "1250 cents is below the floored half-requirement of 9000 cents, got "
        f"{reviewed['compliance_status']}"
    )
    assert reviewed["consecutive_probation_reviews"] == 1, (
        "a first probation review raises the counter to one, got "
        f"{reviewed['consecutive_probation_reviews']}"
    )
    assert reviewed["tenancy_status"] == "PLACED", (
        "a single probation review never gives notice, got "
        f"{reviewed['tenancy_status']}"
    )


# ─── Instance: a census epoch with nothing due ───

CLEO = {
    "legal_first_name": "Cleo",
    "legal_last_name": "Winters",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
DOV = {
    "legal_first_name": "Dov",
    "legal_last_name": "Winters",
    "date_of_birth": "2010-04-15",
    "unaccompanied": True,
}
MIDDAY_CLOCK = instant("2026-08-01", "12:00:00")
SECOND_PLANNED_DISCHARGE = instant("2026-08-20")


def test_a_census_with_nothing_due_moves_nothing(api):
    """PRD §3.10: "A second administrator-only capability then runs one **census
    epoch** against the current clock and performs, in this order, every
    deadline-driven transition in the system: guardian notifications in `PENDING` or
    `ATTEMPTED` whose `due_at` has passed move to `OVERDUE`, after which each affected
    program's `overdue_notification_count` and `posture` are recomputed; admissions in
    `PENDING_SCREENING` whose `requested_at` is more than seventy-two hours behind the
    clock move to `DENIED`; the waitlist selector runs for every program whose posture
    is not `FROZEN`, promoting one admission per program per epoch, ranked by
    `priority_score` descending with earlier `created_at` breaking ties; placements in
    `PLACED` reach `NOTICE_GIVEN` once `days_elapsed` has reached the allowance less the
    thirty-day notice lead, and placements in `NOTICE_GIVEN` reach `EXITED` with
    `exit_reason` `DURATION_LIMIT` once `days_elapsed` has reached `allowance_days`;
    reunification cases in `DECLINED` reach `CLOSED` once a hundred and sixty-eight
    hours have passed since they were last updated; and every youth's
    `trafficking_risk_score` is re-decayed against the new clock by the history rule of
    §3.1, with every program posture and youth posture recomputed at the end."
    PRD §3.4: "The obligation references its admission through `admission_id`, opens in
    `status` `PENDING` with `attempt_count` at 0, `last_attempt_at` null and
    `resolved_at` null, and carries a `due_at` computed as the admission's
    `admitted_at` plus twenty-four hours."
    PRD §3.3: "Otherwise the admission rests in its initial `PENDING_SCREENING` status
    and nothing further changes until a screening is dispositioned as cleared."

    Design: Corner/endpoints/nightly_census_is_a_no_op_when_nothing_is_due
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    resident = intake_youth(**dict(CLEO))
    clear_screening(resident["id"])
    active_admission = request_admission(resident["id"], program["id"], PLANNED_DISCHARGE)
    waiting_youth = intake_youth(**dict(DOV))
    waiting_admission = request_admission(
        waiting_youth["id"], program["id"], SECOND_PLANNED_DISCHARGE
    )
    assert waiting_admission["status"] == "PENDING_SCREENING", (
        f"an unscreened youth rests on the screening branch, got {waiting_admission['status']}"
    )
    move_clock(MIDDAY_CLOCK)

    census = validate_success(api.run_nightly_census(ADMIN))

    assert_census_counts(
        census,
        overdue_marked=0,
        admissions_denied=0,
        admissions_promoted=0,
        placements_noticed=0,
        placements_exited=0,
        cases_closed=0,
    )
    notification = notification_of_admission(active_admission["id"])
    assert notification["status"] == "PENDING", (
        "the obligation is not due until 2026-08-02T00:00:00Z, got "
        f"{notification['status']}"
    )
    still_waiting = fetch_admission(waiting_admission["id"])
    assert still_waiting["status"] == "PENDING_SCREENING", (
        "twelve hours is well inside the seventy-two-hour window, got "
        f"{still_waiting['status']}"
    )
    current = fetch_program(program["id"])
    assert_program_counters(current)
    assert current["occupied_beds"] == 1, (
        f"only the active stay holds a bed, got {current['occupied_beds']}"
    )
    assert current["overdue_notification_count"] == 0, (
        f"nothing fell overdue, got {current['overdue_notification_count']}"
    )
    assert current["posture"] == "OPEN", (
        f"the program is unchanged by an empty epoch, got {current['posture']}"
    )
