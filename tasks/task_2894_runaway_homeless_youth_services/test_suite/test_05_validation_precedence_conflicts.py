"""Requests that violate two ladder rungs at once.

The ladder in §2.10 is total, so only the higher rung may ever be reported: youth
safety outranks bed inventory even though the two disagree on the HTTP status, and
case lifecycle state outranks the mediation cooldown even though both are 409s.
"""

from test_helpers import (
    ADMIN,
    CASE_MANAGER,
    SPECIALIST,
    USER_IDS,
    ApiErrorId,
    admission_payload,
    assert_instant_equals,
    clear_screening,
    escalate_screening,
    fetch_case,
    fetch_program,
    fetch_youth,
    get_success_data,
    home_assessment_payload,
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
)

# ─── Instance: escalated screening outranks bed capacity on the admission request ───

AVA = {
    "legal_first_name": "Ava", "legal_last_name": "Reyes",
    "date_of_birth": "2010-03-15", "unaccompanied": True,
}
BO = {
    "legal_first_name": "Bo", "legal_last_name": "Nakamura",
    "date_of_birth": "2012-06-10", "unaccompanied": True,
}


def _frozen_program_and_escalated_youth():
    """A one-bed program whose only bed is taken — so the posture is `FROZEN` — and
    a second in-band youth whose latest screening stands `ESCALATED`."""
    program = license_emergency_shelter(
        name="Riverside Emergency Shelter",
        licensed_bed_capacity=1,
        min_age_years=12,
        max_age_years=17,
        max_stay_nights=21,
    )
    occupant = intake_youth(**dict(AVA))
    clear_screening(occupant["id"])
    request_admission(occupant["id"], program["id"], instant("2026-08-20"))

    blocked = intake_youth(**dict(BO))
    screening = escalate_screening(
        blocked["id"], ["RECRUITER_PRESENT"], "ADVOCATE_ASSIGNED"
    )
    return program, blocked, screening


def test_escalated_screening_is_reported_before_bed_capacity(api):
    """PRD §2.10: "19. The youth's most recent screening is not `ESCALATED` —
    `ERR_SCREENING_ESCALATED_BLOCKS_ACTION`, 422 — on the admission request and on
    transitional-living placement."
    PRD §2.10: "43. Licensed capacity is respected — `ERR_BED_CAPACITY_EXCEEDED`,
    409 — on the admission request when waitlisting was opted out of against a
    `FROZEN` program, and on transitional-living placement when the program's beds
    are already full."
    PRD §2.10: "When several checks could fail on the same request, they are
    evaluated in a fixed order and the first failure is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/escalated_screening_outranks_bed_capacity_on_admission
    """
    program, blocked, _screening = _frozen_program_and_escalated_youth()
    assert fetch_program(program["id"])["posture"] == "FROZEN", (
        "the only bed is taken, so the program is frozen"
    )

    response = api.create_admission(
        admission_payload(blocked["id"], program["id"], instant("2026-08-25"),
                          waitlist_opt_out=True),
        CASE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_SCREENING_ESCALATED_BLOCKS_ACTION.value, 422)
    body = response.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_BED_CAPACITY_EXCEEDED.value, (
        "checking bed inventory before youth safety inverts the ladder, got "
        f"{body['data']['error_id']}"
    )
    assert response.status_code != 409, (
        "the capacity rung answers 409 and the screening rung answers 422, so a 409 "
        f"falsifies the ordering outright, got {response.status_code}"
    )


def test_refused_admission_request_changes_nothing(api):
    """PRD §3.2: "Screenings of a youth can be listed and narrowed by `status`, and
    the resulting rows expose the frozen `score`, the `tier`, the
    `specialized_response_code`, `screened_at`, `screener_user_id` and
    `disposition_user_id`."
    PRD §2.7: "The three clauses are evaluated top to bottom and the first match
    wins: the posture is `FROZEN` when the most recent screening exists and is in
    status `ESCALATED`; otherwise it is `RESTRICTED` when an open notification
    obligation exists or the youth's `trafficking_risk_tier` is `CRITICAL`;
    otherwise it is `OPEN`."
    PRD §3.3: "Admissions can be listed and narrowed by `youth_id`, by `program_id`
    and by `status`, and reading one admission exposes both billable-night figures,
    `extension_count`, `capacity_blocked`, `discharged_at`, `exit_destination` and
    `outcome_positive` alongside the fields above."

    Design: Difficulty/priority_pair_validation_conflict/escalated_screening_outranks_bed_capacity_on_admission
    """
    program, blocked, screening = _frozen_program_and_escalated_youth()

    api.create_admission(
        admission_payload(blocked["id"], program["id"], instant("2026-08-25"),
                          waitlist_opt_out=True),
        CASE_MANAGER,
    )

    assert screening["status"] == "ESCALATED", (
        f"the screening stands escalated, got {screening['status']}"
    )
    assert screening["specialized_response_code"] == "ADVOCATE_ASSIGNED", (
        f"the specialized response is recorded, got {screening['specialized_response_code']}"
    )
    youth = fetch_youth(blocked["id"])
    assert youth["risk_posture"] == "FROZEN", (
        f"an escalated screening freezes the youth, got {youth['risk_posture']}"
    )
    assert youth["status"] == "PROSPECT", (
        f"the refused request never moved the youth, got {youth['status']}"
    )

    current = fetch_program(program["id"])
    assert current["posture"] == "FROZEN", (
        f"the program is still frozen, got {current['posture']}"
    )
    assert current["occupied_beds"] == 1, (
        f"the single bed is still held by the occupant, got {current['occupied_beds']}"
    )
    assert current["waitlisted_count"] == 0, (
        f"a refused request never joins the waitlist, got {current['waitlisted_count']}"
    )
    rows, meta = validate_paginated(
        api.list_admissions(ADMIN, {"youth_id": blocked["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no admission row was persisted for the refused youth, got {meta['total_count']}"
    )
    assert rows == [], f"the listing is empty, got {len(rows)} rows"


# ─── Instance: case state outranks the mediation cooldown on session scheduling ───

MEDIATION_WINDOW = (instant("2026-08-03", "14:00:00"), instant("2026-08-03", "15:00:00"))
HELD_AT = instant("2026-08-03", "15:00:00")
COOLDOWN_VIOLATING_WINDOW = (instant("2026-08-04", "10:00:00"),
                             instant("2026-08-04", "11:00:00"))
RIO = {
    "legal_first_name": "Rio", "legal_last_name": "Delgado",
    "date_of_birth": "2010-03-15", "unaccompanied": True,
}


def _case_in_home_assessment_inside_the_cooldown(api):
    """A case that has held round one at 2026-08-03T15:00:00Z — so the cooldown floor
    is 2026-08-06T15:00:00Z — and has then moved on to `HOME_ASSESSMENT`, a status
    from which scheduling is not available at all."""
    youth = intake_youth(**dict(RIO))
    case = open_case(youth["id"], youth["version"],
                     household_label="Delgado household - father")
    session = schedule_session(case["id"], MEDIATION_WINDOW[0], MEDIATION_WINDOW[1])
    move_clock(HELD_AT)
    session = record_session_outcome(session["id"], "PROGRESS")
    case = get_success_data(
        api.record_home_assessment(
            case["id"], home_assessment_payload("CONDITIONAL"), SPECIALIST
        )
    )
    return youth, case, session


def test_case_state_is_reported_before_the_mediation_cooldown(api):
    """PRD §2.10: "14. The reunification case is in the state the requested step
    declares — `ERR_CASE_INVALID_STATE`, 409 — on scheduling a mediation session,
    recording a home assessment, deciding, and logging an aftercare contact."
    PRD §2.10: "29. The mediation cooldown has elapsed —
    `ERR_MEDIATION_COOLDOWN_ACTIVE`, 409 — on scheduling a mediation session."
    PRD §3.6: "Scheduling is available while the case stands `OPENED`, moving it
    `OPENED → MEDIATION_SCHEDULED`, and again while it stands `MEDIATION_HELD`,
    moving it `MEDIATION_HELD → MEDIATION_SCHEDULED` for the next round; from any
    other case status it is refused with `ERR_CASE_INVALID_STATE`."
    PRD §3.6: "Second, a **cooldown buffer** of seventy-two hours applies between
    rounds: `scheduled_start_at` must be at least seventy-two hours after the
    `held_at` of the case's most recent held session, and the buffer is measured from
    that `held_at` instant rather than from the previous window's end."

    Design: Difficulty/priority_pair_validation_conflict/case_state_outranks_mediation_cooldown_on_session_scheduling
    """
    _youth, case, _session = _case_in_home_assessment_inside_the_cooldown(api)

    response = api.create_mediation_session(
        case["id"],
        mediation_session_payload(COOLDOWN_VIOLATING_WINDOW[0],
                                  COOLDOWN_VIOLATING_WINDOW[1]),
        SPECIALIST,
    )

    validate_error(response, ApiErrorId.ERR_CASE_INVALID_STATE.value, 409)
    reported = response.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_MEDIATION_COOLDOWN_ACTIVE.value, (
        "both rungs answer 409, so only the error_id can show that the temporal "
        f"buffer was evaluated before the lifecycle state, got {reported}"
    )


def test_refused_scheduling_leaves_the_case_and_its_round_untouched(api):
    """PRD §3.6: "An accepted recording stores the outcome, stamps `held_at` with the
    clock instant, records the acting identifier as `recorded_by_user_id` — the value
    that later governs who may decide the case — and raises the case's
    `mediation_round` by one, moving the case `MEDIATION_SCHEDULED →
    MEDIATION_HELD`."
    PRD §3.6: "Sessions of a case can be listed in creation order."

    Design: Difficulty/priority_pair_validation_conflict/case_state_outranks_mediation_cooldown_on_session_scheduling
    """
    _youth, case, session = _case_in_home_assessment_inside_the_cooldown(api)

    api.create_mediation_session(
        case["id"],
        mediation_session_payload(COOLDOWN_VIOLATING_WINDOW[0],
                                  COOLDOWN_VIOLATING_WINDOW[1]),
        SPECIALIST,
    )

    current = fetch_case(case["id"])
    assert current["status"] == "HOME_ASSESSMENT", (
        f"the refused request never moved the case, got {current['status']}"
    )
    assert current["safety_assessment_result"] == "CONDITIONAL", (
        f"the recorded verdict stands, got {current['safety_assessment_result']}"
    )
    assert current["mediation_round"] == 1, (
        f"exactly one round has been held, got {current['mediation_round']}"
    )
    assert_instant_equals(session["held_at"], HELD_AT, "the held session's held_at")
    assert session["recorded_by_user_id"] == USER_IDS["REUNIFICATION_SPECIALIST_ALT"], (
        "the second specialist recorded the outcome, got "
        f"{session['recorded_by_user_id']}"
    )
    rows, meta = validate_paginated(api.list_mediation_sessions(case["id"], SPECIALIST))
    assert meta["total_count"] == 1, (
        f"the refused window was never persisted, got {meta['total_count']} sessions"
    )
    assert len(rows) == 1, f"one session is listed, got {len(rows)}"
