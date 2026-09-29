"""Two contended resources with deliberately opposite interval semantics.

A youth's occupancy is half-open, so a stay may begin at the instant the previous
stay ends; a case's mediation windows are closed, so touching endpoints collide.
"""

from test_helpers import (
    ADMIN,
    CASE_MANAGER,
    SPECIALIST,
    ApiErrorId,
    admission_payload,
    assert_admission,
    assert_instant_equals,
    assert_mediation_session,
    clear_screening,
    fetch_admission,
    fetch_case,
    fetch_program,
    fetch_youth,
    instant,
    intake_youth,
    license_emergency_shelter,
    mediation_session_payload,
    move_clock,
    open_case,
    record_session_outcome,
    request_admission,
    schedule_session,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Instance: half-open occupancy on the youth, adjacency is legal ───

FIRST_DISCHARGE = instant("2026-08-10")
SECOND_DISCHARGE = instant("2026-08-20")
DAY_BEFORE = instant("2026-08-09")
SAM = {
    "legal_first_name": "Sam", "legal_last_name": "Oyelaran",
    "date_of_birth": "2010-03-15", "unaccompanied": True,
}


def _standing_stay_at_the_first_program():
    """A youth holding an undischarged stay whose occupancy interval runs from
    2026-08-01 up to but not including 2026-08-10, plus a second program with free
    beds so that only the youth-level overlap rule can bite."""
    first = license_emergency_shelter(
        name="Riverside Emergency Shelter", licensed_bed_capacity=2,
        min_age_years=12, max_age_years=17, max_stay_nights=21,
    )
    second = license_emergency_shelter(
        name="Eastgate Emergency Shelter", licensed_bed_capacity=2,
        min_age_years=12, max_age_years=17, max_stay_nights=21,
    )
    youth = intake_youth(**dict(SAM))
    clear_screening(youth["id"])
    admission = request_admission(youth["id"], first["id"], FIRST_DISCHARGE)
    return first, second, youth, admission


def test_stay_intersecting_a_standing_stay_is_refused(api):
    """PRD §3.3: "Stays of one youth may not overlap, and the overlap rule is
    **half-open with a zero buffer and a capacity of one youth**."
    PRD §3.3: "It must not intersect the interval of any other admission of the same
    youth in status `PENDING_SCREENING`, `WAITLISTED`, `ACTIVE`, `EXTENDED` or
    `DISCHARGE_SCHEDULED`, where the existing admission's interval runs from its
    `admitted_at` — falling back to its `requested_at` when it has not yet been
    admitted — up to but not including its `discharged_at`, falling back to its
    `planned_discharge_at` when it has not yet been discharged."

    Design: Difficulty/resource_temporal_overlap/admission_half_open_occupancy_adjacency_on_the_youth_is_legal
    """
    _first, second, youth, _admission = _standing_stay_at_the_first_program()
    move_clock(DAY_BEFORE)

    response = api.create_admission(
        admission_payload(youth["id"], second["id"], SECOND_DISCHARGE), CASE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_ADMISSION_OVERLAP.value, 409)
    _rows, meta = validate_paginated(
        api.list_admissions(ADMIN, {"youth_id": youth["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the refused request persists no second row, got {meta['total_count']}"
    )


def test_stay_beginning_exactly_when_the_previous_one_ends_is_admitted(api):
    """PRD §3.3: "Because both intervals exclude their end instants, exact adjacency
    is legal: a new stay whose start instant equals a prior stay's end instant does
    not collide."
    PRD §3.3: "Any genuine intersection is refused with `ERR_ADMISSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/admission_half_open_occupancy_adjacency_on_the_youth_is_legal
    """
    first, second, youth, standing = _standing_stay_at_the_first_program()
    move_clock(DAY_BEFORE)
    api.create_admission(
        admission_payload(youth["id"], second["id"], SECOND_DISCHARGE), CASE_MANAGER
    )
    move_clock(FIRST_DISCHARGE)

    adjacent = validate_success(
        api.create_admission(
            admission_payload(youth["id"], second["id"], SECOND_DISCHARGE), CASE_MANAGER
        ),
        201,
    )

    assert_admission(adjacent)
    assert adjacent["status"] == "ACTIVE", (
        f"exact adjacency does not collide, got {adjacent['status']}"
    )
    assert_instant_equals(adjacent["admitted_at"], FIRST_DISCHARGE,
                          "the adjacent stay's admitted_at")
    assert adjacent["projected_billable_nights"] == 10, (
        "2026-08-10 to 2026-08-20 is ten whole calendar days, got "
        f"{adjacent['projected_billable_nights']}"
    )
    previous = fetch_admission(standing["id"])
    assert previous["status"] == "ACTIVE", (
        f"the earlier stay is untouched, got {previous['status']}"
    )
    assert previous["discharged_at"] is None, (
        f"the earlier stay was never discharged, got {previous['discharged_at']}"
    )
    assert fetch_program(first["id"])["occupied_beds"] == 1, (
        "the first program still holds its bed"
    )
    second_program = fetch_program(second["id"])
    assert second_program["occupied_beds"] == 1, (
        f"the adjacent stay consumes one bed, got {second_program['occupied_beds']}"
    )
    assert second_program["utilization_bp"] == 5000, (
        f"one of two beds is 5000 basis points, got {second_program['utilization_bp']}"
    )
    assert second_program["posture"] == "OPEN", (
        f"a half-full program with no overdue obligation is open, got {second_program['posture']}"
    )
    assert fetch_youth(youth["id"])["cumulative_shelter_nights"] == 0, (
        "nights only accrue at discharge"
    )
    _rows, meta = validate_paginated(
        api.list_admissions(ADMIN, {"youth_id": youth["id"]})
    )
    assert meta["total_count"] == 2, (
        f"the youth now holds two stays, got {meta['total_count']}"
    )


# ─── Instance: closed mediation windows on the case, touching endpoints collide ───

INTENSIVE_WINDOW = (instant("2026-08-03", "14:00:00"), instant("2026-08-08", "15:00:00"))
HELD_AT = instant("2026-08-03", "15:00:00")
TOUCHING_WINDOW = (instant("2026-08-08", "15:00:00"), instant("2026-08-08", "16:00:00"))
CLEAR_WINDOW = (instant("2026-08-08", "15:00:01"), instant("2026-08-08", "16:00:00"))
TAO = {
    "legal_first_name": "Tao", "legal_last_name": "Bergstrom",
    "date_of_birth": "2010-03-15", "unaccompanied": True,
}


def _case_after_a_five_day_intensive():
    """A case whose first round was a five-day intensive ending 2026-08-08T15:00:00Z,
    held at 2026-08-03T15:00:00Z — so the 72-hour cooldown floor of
    2026-08-06T15:00:00Z is already behind every candidate window."""
    youth = intake_youth(**dict(TAO))
    case = open_case(youth["id"], youth["version"],
                     household_label="Bergstrom household - grandmother")
    session = schedule_session(case["id"], INTENSIVE_WINDOW[0], INTENSIVE_WINDOW[1])
    move_clock(HELD_AT)
    session = record_session_outcome(session["id"], "PROGRESS", SPECIALIST)
    return youth, case, session


def test_window_starting_on_the_previous_windows_end_collides(api):
    """PRD §3.6: "First, session windows on one case are **closed intervals** and
    touching endpoints do collide: the new window running from `scheduled_start_at` to
    `scheduled_end_at` inclusive must not intersect the window of any other session of
    the same case, and a new window whose start instant equals a prior window's end
    instant is rejected — unlike the half-open admission rule, where exact adjacency
    is legal."
    PRD §3.6: "A collision is refused with `ERR_MEDIATION_SESSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/mediation_closed_interval_touching_endpoints_on_the_case_collide
    """
    _youth, case, _session = _case_after_a_five_day_intensive()

    response = api.create_mediation_session(
        case["id"],
        mediation_session_payload(TOUCHING_WINDOW[0], TOUCHING_WINDOW[1]),
        SPECIALIST,
    )

    validate_error(response, ApiErrorId.ERR_MEDIATION_SESSION_OVERLAP.value, 409)
    reported = response.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_MEDIATION_COOLDOWN_ACTIVE.value, (
        "the candidate starts long after the 72-hour cooldown floor, so the cooldown "
        f"is provably not what rejects it, got {reported}"
    )
    _rows, meta = validate_paginated(api.list_mediation_sessions(case["id"], SPECIALIST))
    assert meta["total_count"] == 1, (
        f"the refused window was not persisted, got {meta['total_count']}"
    )


def test_window_one_second_clear_of_the_endpoint_is_accepted(api):
    """PRD §3.6: "The server stores the session against its case through `case_id`,
    sets `round_number` to the case's current `mediation_round` plus one, records
    `scheduler_user_id`, and leaves `outcome` and `held_at` null."
    PRD §3.6: "Scheduling is available while the case stands `OPENED`, moving it
    `OPENED → MEDIATION_SCHEDULED`, and again while it stands `MEDIATION_HELD`, moving
    it `MEDIATION_HELD → MEDIATION_SCHEDULED` for the next round; from any other case
    status it is refused with `ERR_CASE_INVALID_STATE`."

    Design: Difficulty/resource_temporal_overlap/mediation_closed_interval_touching_endpoints_on_the_case_collide
    """
    _youth, case, held = _case_after_a_five_day_intensive()
    api.create_mediation_session(
        case["id"],
        mediation_session_payload(TOUCHING_WINDOW[0], TOUCHING_WINDOW[1]),
        SPECIALIST,
    )

    accepted = validate_success(
        api.create_mediation_session(
            case["id"],
            mediation_session_payload(CLEAR_WINDOW[0], CLEAR_WINDOW[1]),
            SPECIALIST,
        ),
        201,
    )

    assert_mediation_session(accepted)
    assert accepted["round_number"] == 2, (
        f"the next round is round two, got {accepted['round_number']}"
    )
    assert_instant_equals(accepted["scheduled_start_at"], CLEAR_WINDOW[0],
                          "the accepted window's scheduled_start_at")
    assert accepted["outcome"] is None, (
        f"a scheduled session has no outcome yet, got {accepted['outcome']}"
    )
    assert accepted["held_at"] is None, (
        f"a scheduled session has not been held, got {accepted['held_at']}"
    )
    assert_instant_equals(held["held_at"], HELD_AT, "the first session's held_at")

    current = fetch_case(case["id"])
    assert current["status"] == "MEDIATION_SCHEDULED", (
        f"the case loops back to scheduled for the next round, got {current['status']}"
    )
    assert current["mediation_round"] == 1, (
        "scheduling does not raise the held-round count, got "
        f"{current['mediation_round']}"
    )
    _rows, meta = validate_paginated(api.list_mediation_sessions(case["id"], SPECIALIST))
    assert meta["total_count"] == 2, (
        f"the case now carries two sessions, got {meta['total_count']}"
    )
