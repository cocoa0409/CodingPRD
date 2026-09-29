"""Admission-request gates, the priority floor and clock monotonicity.

Each case violates exactly one rung of the ladder — or, in the priority-ordering
case, two rungs at once — and then shows that nothing was consumed on the way to
the refusal.
"""

from test_helpers import (
    ADMIN,
    CASE_MANAGER,
    ApiErrorId,
    admission_payload,
    assert_admission,
    assert_clock_response,
    assert_instant_equals,
    assert_program_counters,
    assert_safety_screening,
    clear_screening,
    clock_payload,
    escalate_screening,
    fetch_program,
    fetch_youth,
    instant,
    intake_youth,
    license_emergency_shelter,
    license_transitional_living,
    log_outreach_contact,
    move_clock,
    request_admission,
    run_census,
    validate_error,
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
}
PLANNED_DISCHARGE = instant("2026-08-15")
SECOND_PLANNED_DISCHARGE = instant("2026-08-20")
DOB_AGE_11 = "2015-03-15"
DOB_AGE_16 = "2010-03-15"
DOB_AGE_12 = "2014-03-15"


# ─── Instance: eleven is one year under an inclusive lower bound ───

ILAN = {
    "legal_first_name": "Ilan",
    "legal_last_name": "Rezaei",
    "date_of_birth": DOB_AGE_11,
    "unaccompanied": True,
}


def test_age_one_year_under_the_band_is_refused(api):
    """PRD §3.3: "The youth's `age_years` at the current clock must lie between the
    program's `min_age_years` and `max_age_years`, both bounds inclusive, or the
    request fails with `ERR_AGE_OUTSIDE_PROGRAM_BAND`."
    PRD §2.10: "25. The youth's age in whole years lies inside the program's licensed
    age band, both bounds inclusive — `ERR_AGE_OUTSIDE_PROGRAM_BAND`, 422 — on the
    admission request and on transitional-living placement."
    PRD §3.3: "The `PENDING_SCREENING` branch leaves `admitted_at` null, consumes no
    bed, creates no obligation and changes no youth field."

    Design: Corner/validations/age_below_the_program_band_is_rejected_on_admission
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    youth = intake_youth(**dict(ILAN))
    clear_screening(youth["id"])
    assert fetch_youth(youth["id"])["age_years"] == 11, "the youth is eleven at the clock"

    response = api.create_admission(
        admission_payload(youth["id"], program["id"], PLANNED_DISCHARGE), CASE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_AGE_OUTSIDE_PROGRAM_BAND.value, 422)
    still_prospect = fetch_youth(youth["id"])
    assert still_prospect["status"] == "PROSPECT", (
        f"a refused request never shelters the youth, got {still_prospect['status']}"
    )
    current = fetch_program(program["id"])
    assert_program_counters(current)
    assert current["occupied_beds"] == 0, (
        f"no bed was consumed, got {current['occupied_beds']}"
    )
    _rows, meta = validate_paginated(
        api.list_admissions(CASE_MANAGER, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no admission row was created at all, got {meta['total_count']}"
    )


# ─── Instance: an admission pointed at a transitional-living program ───

FEN = {
    "legal_first_name": "Fen",
    "legal_last_name": "Larsson",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}


def test_admission_at_a_transitional_living_program_is_a_type_mismatch(api):
    """PRD §3.3: "The program must be an `EMERGENCY_SHELTER` program, or the request
    fails with `ERR_PROGRAM_TYPE_MISMATCH`."
    PRD §2.10: "26. The program type matches the operation —
    `ERR_PROGRAM_TYPE_MISMATCH`, 422 — on the admission request and on
    transitional-living placement."
    PRD §3.3: "The licence declares a `name` of 1 to 120 characters and a
    `program_type` of either `EMERGENCY_SHELTER` or `TRANSITIONAL_LIVING`, which fixes
    for all time which kind of child record is allowed to occupy that program's
    beds."

    Design: Corner/validations/admission_at_a_transitional_living_program_is_a_type_mismatch
    """
    tlp_program = license_transitional_living(**dict(NORTHSIDE))
    youth = intake_youth(**dict(FEN))
    clear_screening(youth["id"])
    assert fetch_youth(youth["id"])["age_years"] == 16, (
        "sixteen sits inside the transitional-living band, so an age failure cannot "
        "explain the refusal"
    )

    response = api.create_admission(
        admission_payload(youth["id"], tlp_program["id"], PLANNED_DISCHARGE), CASE_MANAGER
    )

    error = validate_error(response, ApiErrorId.ERR_PROGRAM_TYPE_MISMATCH.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_AGE_OUTSIDE_PROGRAM_BAND.value, (
        f"the age band is satisfied, got {error['error_id']}"
    )
    current = fetch_program(tlp_program["id"])
    assert current["occupied_beds"] == 0, (
        f"the transitional-living program takes no admission, got {current['occupied_beds']}"
    )
    assert fetch_youth(youth["id"])["status"] == "PROSPECT", (
        "the youth is untouched by the refusal"
    )


# ─── Instance: the priority floor under a RESTRICTED posture ───

MIRA = {
    "legal_first_name": "Mira",
    "legal_last_name": "Abara",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
NILS = {
    "legal_first_name": "Nils",
    "legal_last_name": "Abara",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
ZOLA = {
    "legal_first_name": "Zola",
    "legal_last_name": "Antwi",
    "date_of_birth": DOB_AGE_12,
    "unaccompanied": True,
}
CRITICAL_FLAGS = ["COMMERCIAL_SEX", "THIRD_PARTY_CONTROL"]
OVERDUE_CLOCK = instant("2026-08-03")


def _restricted_program_with_one_free_bed(resident_overrides):
    """A two-bed program driven to `RESTRICTED` by exactly one overdue obligation,
    with its second bed still free."""
    program = license_emergency_shelter(**dict(RIVERSIDE))
    resident = intake_youth(**resident_overrides)
    clear_screening(resident["id"])
    request_admission(resident["id"], program["id"], PLANNED_DISCHARGE)
    move_clock(OVERDUE_CLOCK)
    run_census()
    return fetch_program(program["id"])


def test_a_candidate_below_the_priority_floor_is_refused_not_waitlisted(api):
    """PRD §3.3: "Where a program's posture is `RESTRICTED`, the resulting
    `priority_score` must be at least 60 or the request is refused with
    `ERR_PROGRAM_RESTRICTED_PRIORITY`."
    PRD §2.6: "A `RESTRICTED` posture admits only high-need youth: the admission's
    `priority_score` must be at least 60, and a lower score is refused with
    `ERR_PROGRAM_RESTRICTED_PRIORITY` (HTTP 422)."
    PRD §2.6: "A `FROZEN` posture diverts a new emergency-shelter admission request
    onto the waitlist rather than into a bed, unless the requester explicitly opted
    out of waitlisting, in which case the request is refused with
    `ERR_BED_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/restricted_posture_refuses_an_admission_below_the_priority_floor
    """
    program = _restricted_program_with_one_free_bed(dict(MIRA))
    assert program["posture"] == "RESTRICTED", (
        f"one overdue obligation restricts the program, got {program['posture']}"
    )
    candidate = intake_youth(**dict(NILS))
    clear_screening(candidate["id"])

    response = api.create_admission(
        admission_payload(candidate["id"], program["id"], SECOND_PLANNED_DISCHARGE),
        CASE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_PROGRAM_RESTRICTED_PRIORITY.value, 422)
    current = fetch_program(program["id"])
    assert_program_counters(current)
    assert current["overdue_notification_count"] == 1, (
        f"the overdue row is still the only one, got {current['overdue_notification_count']}"
    )
    assert current["occupied_beds"] == 1, (
        f"the free bed stays free, got {current['occupied_beds']}"
    )
    assert current["waitlisted_count"] == 0, (
        "waitlisting belongs to a FROZEN posture, not to a restricted one, got "
        f"{current['waitlisted_count']}"
    )
    _rows, meta = validate_paginated(
        api.list_admissions(CASE_MANAGER, {"youth_id": candidate["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused request created no admission row, got {meta['total_count']}"
    )
    assert fetch_youth(candidate["id"])["status"] == "PROSPECT", (
        "the refused candidate is untouched"
    )


def test_a_candidate_above_the_priority_floor_is_admitted(api):
    """PRD §3.3: "Those four are summed; then, if and only if the youth's
    `trafficking_risk_tier` is `CRITICAL`, a further 10 points are added; and the
    result is finally capped at 100."
    PRD §3.3: "The risk component is the youth's `trafficking_risk_score`, capped at
    40."
    PRD §3.3: "The age component is eighteen minus the youth's `age_years`, held at a
    floor of zero so that a youth aged eighteen or older contributes nothing,
    multiplied by four — so a fourteen-year-old contributes sixteen points."
    PRD §3.3: "The engagement component is the youth's `engagement_contact_count`
    multiplied by five, capped at 20, so a fourth and later encounter adds nothing
    further."
    PRD §2.6: "The posture is `FROZEN` when the occupied-bed count has reached or
    passed `licensed_bed_capacity`, or when the overdue-notification count has reached
    two."

    Design: Corner/validations/restricted_posture_admits_a_youth_above_the_priority_floor
    """
    program = _restricted_program_with_one_free_bed(dict(MIRA))
    candidate = intake_youth(**dict(ZOLA))
    log_outreach_contact(
        candidate["id"],
        engagement_stage="TRUST_ESTABLISHED",
        basic_needs_provided=["FOOD"],
        indicator_flags=list(CRITICAL_FLAGS),
    )
    clear_screening(candidate["id"])
    scored = fetch_youth(candidate["id"])
    assert scored["trafficking_risk_score"] == 70, (
        "a same-day contact flagged COMMERCIAL_SEX and THIRD_PARTY_CONTROL scores 70 "
        f"undecayed, got {scored['trafficking_risk_score']}"
    )
    assert scored["trafficking_risk_tier"] == "CRITICAL", (
        f"a score of 70 tiers as CRITICAL, got {scored['trafficking_risk_tier']}"
    )

    response = api.create_admission(
        admission_payload(candidate["id"], program["id"], SECOND_PLANNED_DISCHARGE),
        CASE_MANAGER,
    )
    admission = validate_success(response, 201)

    assert_admission(admission)
    assert admission["priority_score"] == 94, (
        "twenty-four age points plus forty capped risk points plus five engagement "
        "points plus fifteen exposure points plus the ten-point critical bump is 94, "
        f"got {admission['priority_score']}"
    )
    assert admission["status"] == "ACTIVE", (
        f"a score above the floor of 60 takes the free bed, got {admission['status']}"
    )
    assert_instant_equals(admission["admitted_at"], OVERDUE_CLOCK,
                          "the admission's admitted_at")

    current = fetch_program(program["id"])
    assert current["occupied_beds"] == 2, (
        f"both beds are now taken, got {current['occupied_beds']}"
    )
    assert current["utilization_bp"] == 10000, (
        f"two of two beds is 10000 basis points, got {current['utilization_bp']}"
    )
    assert current["posture"] == "FROZEN", (
        f"a full program is FROZEN, got {current['posture']}"
    )
    resident = fetch_youth(candidate["id"])
    assert resident["status"] == "SHELTERED", (
        f"the admitted youth is sheltered, got {resident['status']}"
    )
    assert resident["risk_posture"] == "RESTRICTED", (
        f"the new pending obligation restricts the youth, got {resident['risk_posture']}"
    )


# ─── Instance: the safety gate outranks the age band ───

BRAM = {
    "legal_first_name": "Bram",
    "legal_last_name": "Osei",
    "date_of_birth": DOB_AGE_11,
    "unaccompanied": True,
}


def test_an_escalated_screening_outranks_the_age_band(api):
    """PRD §2.10: "When several checks could fail on the same request, they are
    evaluated in a fixed order and the first failure is the one reported."
    PRD §2.10: "19. The youth's most recent screening is not `ESCALATED` —
    `ERR_SCREENING_ESCALATED_BLOCKS_ACTION`, 422 — on the admission request and on
    transitional-living placement."
    PRD §3.3: "The youth's most recent screening must not stand `ESCALATED`, or the
    request fails with `ERR_SCREENING_ESCALATED_BLOCKS_ACTION`."
    PRD §3.2: "`ESCALATED` recomputes the youth's `risk_posture` to `FROZEN`, which
    from that moment blocks opening a reunification case for that youth, blocks
    approving a reunification decision, and blocks resolving any of that youth's
    parental notifications as contacted — family contact is unsafe while a screening
    stands escalated."

    Design: Corner/validations/escalated_screening_outranks_the_age_band_on_admission
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    youth = intake_youth(**dict(BRAM))
    screening = escalate_screening(
        youth["id"], ["RECRUITER_PRESENT"], "LAW_ENFORCEMENT_LIAISON"
    )

    response = api.create_admission(
        admission_payload(youth["id"], program["id"], PLANNED_DISCHARGE), CASE_MANAGER
    )

    error = validate_error(
        response, ApiErrorId.ERR_SCREENING_ESCALATED_BLOCKS_ACTION.value, 422
    )
    assert error["error_id"] != ApiErrorId.ERR_AGE_OUTSIDE_PROGRAM_BAND.value, (
        "the lower-precedence age-band failure must not win, got "
        f"{error['error_id']}"
    )
    frozen_youth = fetch_youth(youth["id"])
    assert frozen_youth["age_years"] == 11, (
        "the youth is genuinely outside the 12 to 17 band as well, got "
        f"{frozen_youth['age_years']}"
    )
    assert frozen_youth["risk_posture"] == "FROZEN", (
        f"an escalated screening freezes the youth, got {frozen_youth['risk_posture']}"
    )
    assert_safety_screening(screening)
    assert screening["status"] == "ESCALATED", (
        f"the screening stands escalated, got {screening['status']}"
    )
    current = fetch_program(program["id"])
    assert current["occupied_beds"] == 0, (
        f"no bed was consumed, got {current['occupied_beds']}"
    )


# ─── Instance: the clock only moves forward ───

FIFTH_OF_AUGUST = instant("2026-08-05")
FOURTH_OF_AUGUST = instant("2026-08-04")
ONE_SECOND_LATER = instant("2026-08-05", "00:00:01")


def test_the_clock_refuses_to_move_backwards_or_stand_still(api):
    """PRD §2.5: "The clock is strictly monotonic: a `to_iso8601` value equal to or
    earlier than the present clock value is refused with
    `ERR_CLOCK_MONOTONIC_VIOLATION` (HTTP 422), and moving the clock mutates no entity
    and runs no census."
    PRD §2.5: "The administrative clock endpoint takes a single field, `to_iso8601`,
    and answers with the object `{ current_utc, previous_utc }`, reporting the new
    clock value and the value it replaced."
    PRD §2.10: "33. The logical clock only moves forward —
    `ERR_CLOCK_MONOTONIC_VIOLATION`, 422 — on the clock endpoint."

    Design: Corner/validations/logical_clock_refuses_to_move_backwards
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    move_clock(FIFTH_OF_AUGUST)

    backwards = api.set_clock(clock_payload(FOURTH_OF_AUGUST), ADMIN)

    validate_error(backwards, ApiErrorId.ERR_CLOCK_MONOTONIC_VIOLATION.value, 422)
    standing_still = api.set_clock(clock_payload(FIFTH_OF_AUGUST), ADMIN)
    validate_error(standing_still, ApiErrorId.ERR_CLOCK_MONOTONIC_VIOLATION.value, 422)

    accepted = validate_success(api.set_clock(clock_payload(ONE_SECOND_LATER), ADMIN))
    assert_clock_response(accepted, ONE_SECOND_LATER, FIFTH_OF_AUGUST)
    unchanged = fetch_program(program["id"])
    assert unchanged["version"] == 1, (
        f"moving the clock mutates no entity, got version {unchanged['version']}"
    )
    assert unchanged["posture"] == "OPEN", (
        f"the empty program is still OPEN, got {unchanged['posture']}"
    )
