"""Refusals whose identity is the point: which code, out of which rung.

Every case here has a plausible neighbouring code that must not win — a generic
404 instead of the segment's own, a terminal-admission code instead of the
not-operable one, an overlap instead of the same-program rule, a stale-version
412 instead of the safety gate.
"""

from test_helpers import (
    ADMIN,
    CASE_MANAGER,
    COORDINATOR,
    SPECIALIST,
    ApiErrorId,
    admission_payload,
    assert_admission,
    assert_guardian_notification,
    assert_instant_equals,
    assert_program_counters,
    assert_reunification_case,
    assert_safety_screening,
    clear_screening,
    decision_payload,
    discharge_payload,
    escalate_screening,
    extend_payload,
    fetch_admission,
    fetch_case,
    fetch_program,
    fetch_youth,
    instant,
    intake_youth,
    license_emergency_shelter,
    make_youth_member_headers,
    mediation_outcome_payload,
    move_clock,
    notification_attempt_payload,
    notification_of_admission,
    record_attempt,
    resolve_notification,
    reunification_case_payload,
    run_census,
    screening_disposition_payload,
    setup_active_admission,
    setup_case_in_home_assessment,
    setup_pending_screening_admission,
    submit_screening,
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
DOB_AGE_16 = "2010-03-15"
PLANNED_DISCHARGE = instant("2026-08-15")


# ─── Instance: eight path families, eight not-found codes ───

VERA = {
    "legal_first_name": "Vera",
    "legal_last_name": "Solano",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
UNKNOWN_NOTIFICATION = "44444444-4444-4444-4444-444444444444"
UNKNOWN_SCREENING = "44444444-4444-4444-4444-444444444445"
UNKNOWN_CASE = "44444444-4444-4444-4444-444444444446"
UNKNOWN_SESSION = "44444444-4444-4444-4444-444444444447"
UNKNOWN_PLACEMENT = "44444444-4444-4444-4444-444444444448"
UNKNOWN_ENROLLMENT = "44444444-4444-4444-4444-444444444449"
UNKNOWN_PROPOSAL = "44444444-4444-4444-4444-44444444444a"
UNKNOWN_VOTE = "44444444-4444-4444-4444-44444444444b"


def test_each_unknown_path_segment_answers_with_its_own_not_found_code(api):
    """PRD §2.10: "Identifiers embedded in a URL path are resolved strictly left to
    right, and the first identifier that fails to resolve determines the error."
    PRD §2.10: "Each resource kind has its own not-found code, so a request naming an
    unknown youth fails with `ERR_YOUTH_NOT_FOUND` before the server ever looks at the
    nested segment."
    PRD §2.10: "The eleven not-found codes are `ERR_YOUTH_NOT_FOUND`,
    `ERR_PROGRAM_NOT_FOUND`, `ERR_ADMISSION_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`,
    `ERR_NOTIFICATION_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
    `ERR_PLACEMENT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND` and
    `ERR_VOTE_NOT_FOUND`, each returning HTTP 404."
    PRD §2.10: "4. Every identifier in the path resolves, left to right — the matching
    not-found code, 404, on every path-templated endpoint."

    Design: Corner/errors/unknown_ids_across_the_action_surface_return_their_own_not_found_codes
    """
    license_emergency_shelter(**dict(RIVERSIDE))
    youth = intake_youth(**dict(VERA))

    validate_error(
        api.record_notification_attempt(
            UNKNOWN_NOTIFICATION, notification_attempt_payload("PHONE"), CASE_MANAGER
        ),
        ApiErrorId.ERR_NOTIFICATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.disposition_safety_screening(
            UNKNOWN_SCREENING, screening_disposition_payload("CLEARED"), ADMIN
        ),
        ApiErrorId.ERR_SCREENING_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_reunification_case(UNKNOWN_CASE, SPECIALIST),
        ApiErrorId.ERR_CASE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.record_mediation_outcome(
            UNKNOWN_SESSION, mediation_outcome_payload("PROGRESS"), SPECIALIST
        ),
        ApiErrorId.ERR_SESSION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_tlp_placement(UNKNOWN_PLACEMENT, COORDINATOR),
        ApiErrorId.ERR_PLACEMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.verify_education_records(UNKNOWN_ENROLLMENT, COORDINATOR),
        ApiErrorId.ERR_ENROLLMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_governance_proposal(UNKNOWN_PROPOSAL, ADMIN),
        ApiErrorId.ERR_PROPOSAL_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.retract_governance_vote(
            UNKNOWN_VOTE, make_youth_member_headers(youth["id"])
        ),
        ApiErrorId.ERR_VOTE_NOT_FOUND.value,
        404,
    )


# ─── Instance: extending a stay that never started ───

GUS = {
    "legal_first_name": "Gus",
    "legal_last_name": "Marchetti",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
LATER_DISCHARGE = instant("2026-08-18")


def test_extending_a_pending_screening_stay_is_not_operable_rather_than_terminal(api):
    """PRD §3.5: "An admission in `PENDING_SCREENING` or `WAITLISTED` cannot be
    discharged or extended and is refused with `ERR_ADMISSION_NOT_ACTIVE`; an admission
    already in `DISCHARGED` or `DENIED` is refused with
    `ERR_ADMISSION_ALREADY_TERMINAL`."
    PRD §2.10: "9. The admission is in an operable non-terminal state for the requested
    action — `ERR_ADMISSION_NOT_ACTIVE`, 409 — on extend and discharge. Extension
    requires status `ACTIVE` or `EXTENDED`; discharge requires status `ACTIVE`,
    `EXTENDED` or `DISCHARGE_SCHEDULED`. This rule is deliberately scoped to the five
    non-terminal statuses `PENDING_SCREENING`, `WAITLISTED`, `ACTIVE`, `EXTENDED` and
    `DISCHARGE_SCHEDULED` only; an already-terminal admission falls outside its scope
    and is caught by rule 10 instead, so the two codes never shadow one another."
    PRD §3.5: "An accepted extension replaces `planned_discharge_at` with the supplied
    instant, raises `extension_count` by one, and recomputes
    `projected_billable_nights`."

    Design: Corner/errors/extend_on_a_pending_screening_admission_returns_not_active
    """
    setup = setup_pending_screening_admission(
        program_overrides=dict(RIVERSIDE),
        youth_overrides=dict(GUS),
        planned_discharge_at=PLANNED_DISCHARGE,
    )
    admission = setup["admission"]
    assert admission["status"] == "PENDING_SCREENING", (
        f"an unscreened youth rests on the screening branch, got {admission['status']}"
    )

    response = api.extend_admission(
        admission["id"], extend_payload(LATER_DISCHARGE), CASE_MANAGER
    )

    error = validate_error(response, ApiErrorId.ERR_ADMISSION_NOT_ACTIVE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_ADMISSION_ALREADY_TERMINAL.value, (
        "PENDING_SCREENING is non-terminal, so the terminal code must not fire, got "
        f"{error['error_id']}"
    )
    unchanged = fetch_admission(admission["id"])
    assert_admission(unchanged)
    assert unchanged["status"] == "PENDING_SCREENING", (
        f"the refused extension moves nothing, got {unchanged['status']}"
    )
    assert unchanged["extension_count"] == 0, (
        f"no extension was consumed, got {unchanged['extension_count']}"
    )
    assert_instant_equals(unchanged["planned_discharge_at"], PLANNED_DISCHARGE,
                          "the admission's planned_discharge_at")


# ─── Instance: a second stay at the same program ───

IVO = {
    "legal_first_name": "Ivo",
    "legal_last_name": "Salgado",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
OVERLAPPING_DISCHARGE = instant("2026-08-10")


def test_a_second_stay_at_the_same_program_is_already_sheltered_not_an_overlap(api):
    """PRD §3.3: "The youth must not already hold another admission at the same program
    in status `ACTIVE`, `EXTENDED` or `DISCHARGE_SCHEDULED`, or the request fails with
    `ERR_YOUTH_ALREADY_SHELTERED`."
    PRD §2.10: "11. The youth holds no other admission at the same program in status
    `ACTIVE`, `EXTENDED` or `DISCHARGE_SCHEDULED` — `ERR_YOUTH_ALREADY_SHELTERED`, 409 —
    on the admission request."
    PRD §2.10: "27. The requested stay does not overlap another stay of the same youth —
    `ERR_ADMISSION_OVERLAP`, 409 — on the admission request."
    PRD §2.10: "When several checks could fail on the same request, they are evaluated
    in a fixed order and the first failure is the one reported."

    Design: Corner/errors/second_admission_at_the_same_program_returns_already_sheltered
    """
    setup = setup_active_admission(
        program_overrides=dict(RIVERSIDE),
        youth_overrides=dict(IVO),
        planned_discharge_at=PLANNED_DISCHARGE,
    )
    assert setup["admission"]["status"] == "ACTIVE", (
        f"the first stay holds a bed, got {setup['admission']['status']}"
    )

    response = api.create_admission(
        admission_payload(
            setup["youth"]["id"], setup["program"]["id"], OVERLAPPING_DISCHARGE
        ),
        CASE_MANAGER,
    )

    error = validate_error(response, ApiErrorId.ERR_YOUTH_ALREADY_SHELTERED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_ADMISSION_OVERLAP.value, (
        "the two windows do intersect, but the same-program rule is evaluated first, "
        f"got {error['error_id']}"
    )
    _rows, meta = validate_paginated(
        api.list_admissions(CASE_MANAGER, {"youth_id": setup["youth"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the refused request created no second row, got {meta['total_count']}"
    )
    program = fetch_program(setup["program"]["id"])
    assert_program_counters(program)
    assert program["occupied_beds"] == 1, (
        f"the second bed stays free, got {program['occupied_beds']}"
    )


# ─── Instance: a critical screening may be escalated but never cleared ───

JUNO = {
    "legal_first_name": "Juno",
    "legal_last_name": "Vasquez",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
CRITICAL_CODES = ["COMMERCIAL_SEX", "THIRD_PARTY_CONTROL"]


def test_a_critical_screening_refuses_clearance_yet_still_escalates(api):
    """PRD §3.2: "Clearing in either direction is additionally forbidden when the
    screening's `tier` is `CRITICAL`: such a screening is refused with
    `ERR_SCREENING_CRITICAL_TIER`, the specialized response must run, and a fresh
    screening must be submitted before the youth can be cleared."
    PRD §3.2: "The screening's `tier` is read off the same two thresholds as the youth's
    tier — `CRITICAL` at 60 or more, `ELEVATED` at 30 or more, `LOW` below 30 — but it is
    read off the screening's own `score` rather than off the youth's history figure."
    PRD §3.1: "Each indicator code carries a weight: `THIRD_PARTY_CONTROL` is worth 30
    points, `QUOTA_DEBT` 25, `COMMERCIAL_SEX` 40, `DOCUMENT_WITHHELD` 20,
    `RECRUITER_PRESENT` 15 and `CURFEW_ENFORCED` 10."
    PRD §3.2: "From `SUBMITTED` a screening may move to `CLEARED` or to `ESCALATED`."
    PRD §3.2: "`ESCALATED` recomputes the youth's `risk_posture` to `FROZEN`, which from
    that moment blocks opening a reunification case for that youth, blocks approving a
    reunification decision, and blocks resolving any of that youth's parental
    notifications as contacted — family contact is unsafe while a screening stands
    escalated."

    Design: Corner/errors/critical_tier_screening_cannot_be_dispositioned_cleared
    """
    youth = intake_youth(**dict(JUNO))
    screening = submit_screening(youth["id"], list(CRITICAL_CODES))

    assert_safety_screening(screening)
    assert screening["score"] == 70, (
        "COMMERCIAL_SEX at 40 points plus THIRD_PARTY_CONTROL at 30 is 70, got "
        f"{screening['score']}"
    )
    assert screening["tier"] == "CRITICAL", (
        f"a score of 70 sits at or above the critical threshold, got {screening['tier']}"
    )

    refused = api.disposition_safety_screening(
        screening["id"], screening_disposition_payload("CLEARED"), ADMIN
    )

    validate_error(refused, ApiErrorId.ERR_SCREENING_CRITICAL_TIER.value, 422)
    rows, _meta = validate_paginated(api.list_safety_screenings(youth["id"], ADMIN))
    assert rows[0]["status"] == "SUBMITTED", (
        f"the refused clearance leaves the row untouched, got {rows[0]['status']}"
    )

    escalated = validate_success(
        api.disposition_safety_screening(
            screening["id"],
            screening_disposition_payload("ESCALATED", "ADVOCATE_ASSIGNED"),
            ADMIN,
        )
    )
    assert escalated["status"] == "ESCALATED", (
        "the very same row accepts an escalation, got "
        f"{escalated['status']}"
    )
    assert fetch_youth(youth["id"])["risk_posture"] == "FROZEN", (
        "the escalation freezes the youth"
    )


# ─── Instance: a frozen youth cannot open a reunification case ───

RAVI = {
    "legal_first_name": "Ravi",
    "legal_last_name": "Achebe",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}


def test_a_frozen_youth_cannot_open_a_case_even_with_a_fresh_version(api):
    """PRD §3.6: "Opening a case is refused with `ERR_YOUTH_POSTURE_FROZEN` while the
    youth's `risk_posture` is `FROZEN`."
    PRD §2.10: "20. The youth's risk posture is not `FROZEN` —
    `ERR_YOUTH_POSTURE_FROZEN`, 422 — on opening a reunification case and on the
    reunification decision."
    PRD §2.10: "7. `expected_youth_version` equals the youth's current `version` —
    `ERR_STALE_YOUTH_VERSION`, 412, on opening a reunification case."
    PRD §3.6: "A new case opens in `status` `OPENED` with `opened_at` stamped from the
    clock, `mediation_round` at 0, `max_mediation_rounds` fixed by the server at 3,
    `safety_assessment_result` null, `aftercare_plan_due_at` null,
    `aftercare_contacts_completed` at 0 and `closed_at` null."

    Design: Corner/errors/frozen_youth_cannot_open_a_reunification_case
    """
    youth = intake_youth(**dict(RAVI))
    escalate_screening(youth["id"], ["QUOTA_DEBT"], "ADVOCATE_ASSIGNED")
    frozen = fetch_youth(youth["id"])
    assert frozen["risk_posture"] == "FROZEN", (
        f"the escalated screening freezes the youth, got {frozen['risk_posture']}"
    )

    response = api.create_reunification_case(
        reunification_case_payload(
            frozen["id"], frozen["version"], guardian_household_label="Achebe household"
        ),
        SPECIALIST,
    )

    error = validate_error(response, ApiErrorId.ERR_YOUTH_POSTURE_FROZEN.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_STALE_YOUTH_VERSION.value, (
        "the pinned version was read immediately beforehand, so the concurrency check "
        f"cannot explain the refusal, got {error['error_id']}"
    )
    _rows, meta = validate_paginated(
        api.list_youth_reunification_cases(frozen["id"], SPECIALIST)
    )
    assert meta["total_count"] == 0, (
        f"no case row was created, got {meta['total_count']}"
    )


# ─── Instance: the runaway report is the price of a discharge ───

TALIA = {
    "legal_first_name": "Talia",
    "legal_last_name": "Moreau",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
OVERDUE_CLOCK = instant("2026-08-03")


def test_an_overdue_obligation_blocks_the_discharge_until_the_report_is_filed(api):
    """PRD §3.4: "An admission whose obligation stands `OVERDUE` with
    `runaway_report_filed_at` still null cannot be discharged; the attempt is refused
    with `ERR_RUNAWAY_REPORT_REQUIRED`."
    PRD §3.4: "Once a runaway report has been filed, the discharge gate is satisfied
    from then on."
    PRD §3.4: "`LAW_ENFORCEMENT_REPORTED` records that a runaway report was filed with
    law enforcement; it is available only from `OVERDUE` and requires at least one
    recorded attempt."
    PRD §3.4: "Every accepted resolution stamps `resolved_at` with the clock instant and
    stores the acting identifier as `resolving_user_id`; a law-enforcement resolution
    additionally stamps `runaway_report_filed_at` with the same instant."
    PRD §3.4: "When the obligation being resolved was `OVERDUE`, the program's
    `overdue_notification_count` falls by one and the program's `posture` is recomputed,
    which can lift a program back out of `FROZEN` or `RESTRICTED`."

    Design: Corner/errors/overdue_notification_blocks_discharge_until_the_runaway_report_is_filed
    """
    setup = setup_active_admission(
        program_overrides=dict(RIVERSIDE),
        youth_overrides=dict(TALIA),
        planned_discharge_at=PLANNED_DISCHARGE,
    )
    record_attempt(setup["notification"]["id"], "PHONE")
    move_clock(OVERDUE_CLOCK)
    run_census()
    overdue = notification_of_admission(setup["admission"]["id"])
    assert overdue["status"] == "OVERDUE", (
        f"the census marked the obligation overdue, got {overdue['status']}"
    )

    refused = api.discharge_admission(
        setup["admission"]["id"], discharge_payload("UNKNOWN"), CASE_MANAGER
    )

    validate_error(refused, ApiErrorId.ERR_RUNAWAY_REPORT_REQUIRED.value, 422)
    assert fetch_admission(setup["admission"]["id"])["status"] == "ACTIVE", (
        "the refused discharge leaves the stay running"
    )

    reported = resolve_notification(overdue["id"], "LAW_ENFORCEMENT_REPORTED")
    assert_guardian_notification(reported)
    assert reported["status"] == "LAW_ENFORCEMENT_REPORTED", (
        f"the report is filed against the obligation, got {reported['status']}"
    )
    assert_instant_equals(reported["runaway_report_filed_at"], OVERDUE_CLOCK,
                          "the obligation's runaway_report_filed_at")
    cleared_program = fetch_program(setup["program"]["id"])
    assert cleared_program["overdue_notification_count"] == 0, (
        "resolving the overdue row drops the program's counter, got "
        f"{cleared_program['overdue_notification_count']}"
    )

    discharged = validate_success(
        api.discharge_admission(
            setup["admission"]["id"], discharge_payload("UNKNOWN"), CASE_MANAGER
        )
    )
    assert discharged["status"] == "DISCHARGED", (
        "the identical request now succeeds, got "
        f"{discharged['status']}"
    )
    assert discharged["final_billable_nights"] == 2, (
        "2026-08-01 to 2026-08-03 is two calendar days and a midnight discharge earns "
        f"no cutoff night, got {discharged['final_billable_nights']}"
    )
    exited = fetch_youth(setup["youth"]["id"])
    assert exited["cumulative_shelter_nights"] == 2, (
        f"two final nights accrue to the youth, got {exited['cumulative_shelter_nights']}"
    )
    assert exited["status"] == "EXITED", (
        f"an UNKNOWN destination exits the youth, got {exited['status']}"
    )
    assert fetch_program(setup["program"]["id"])["occupied_beds"] == 0, (
        "the discharge releases the bed"
    )


# ─── Instance: a pending obligation with no attempt blocks approval ───

NOUR = {
    "legal_first_name": "Nour",
    "legal_last_name": "Haddad",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
SESSION_WINDOW = (instant("2026-08-03", "14:00:00"), instant("2026-08-03", "16:00:00"))
HELD_AT = instant("2026-08-03", "14:30:00")


def test_an_untouched_obligation_blocks_the_reunification_approval(api):
    """PRD §3.6: "`APPROVE` additionally requires three things: the recorded
    `safety_assessment_result` must be `SAFE` or `CONDITIONAL`, so an unsafe home can
    never be approved; the youth's `risk_posture` must not be `FROZEN`, or the request is
    refused with `ERR_YOUTH_POSTURE_FROZEN`; and every guardian notification belonging to
    the youth's `ACTIVE` or `EXTENDED` admissions must already stand in `ATTEMPTED`,
    `CONTACTED`, `WAIVED` or `LAW_ENFORCEMENT_REPORTED` — a still-`PENDING` obligation
    with zero recorded attempts blocks approval and is refused with
    `ERR_NOTIFICATION_UNRESOLVED`."
    PRD §2.10: "23. Every notification of the youth's `ACTIVE` and `EXTENDED` admissions
    is at least `ATTEMPTED` — `ERR_NOTIFICATION_UNRESOLVED`, 422 — on the reunification
    decision."
    PRD §3.6: "Both branches require that the acting identifier differs from the
    `recorded_by_user_id` of the latest held session, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`; whoever ran the mediation may not also sign off on its
    result."
    PRD §3.6: "The case's `aftercare_plan_due_at` is set to the clock instant plus
    seventy-two hours and the case moves to `APPROVED`."

    Design: Corner/errors/pending_notification_with_no_attempt_blocks_case_approval
    """
    setup = setup_case_in_home_assessment(
        "SAFE",
        "PENDING",
        program_overrides=dict(RIVERSIDE),
        youth_overrides=dict(NOUR),
        planned_discharge_at=PLANNED_DISCHARGE,
        session_window=SESSION_WINDOW,
        held_at=HELD_AT,
        outcome="PROGRESS",
    )
    untouched = notification_of_admission(setup["admission"]["id"])
    assert untouched["attempt_count"] == 0, (
        f"no attempt has been recorded, got {untouched['attempt_count']}"
    )

    response = api.decide_reunification_case(
        setup["case"]["id"], decision_payload("APPROVE"), SPECIALIST
    )

    error = validate_error(response, ApiErrorId.ERR_NOTIFICATION_UNRESOLVED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, (
        "the deciding specialist differs from the one who recorded the outcome, got "
        f"{error['error_id']}"
    )
    case = fetch_case(setup["case"]["id"])
    assert_reunification_case(case)
    assert case["status"] == "HOME_ASSESSMENT", (
        f"the refused decision moves the case nowhere, got {case['status']}"
    )
    assert case["aftercare_plan_due_at"] is None, (
        f"no aftercare window was opened, got {case['aftercare_plan_due_at']}"
    )
    assert fetch_admission(setup["admission"]["id"])["status"] == "ACTIVE", (
        "the stay is not rescheduled for discharge"
    )
    assert notification_of_admission(setup["admission"]["id"])["status"] == "PENDING", (
        "the obligation is not waived by a refused approval"
    )
    assert fetch_youth(setup["youth"]["id"])["status"] == "SHELTERED", (
        "the youth stays sheltered"
    )


# ─── Instance: a planned discharge behind the clock ───

RUNE = {
    "legal_first_name": "Rune",
    "legal_last_name": "Bianchi",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
PAST_DISCHARGE = instant("2026-07-01")


def test_a_planned_discharge_behind_the_clock_is_an_invalid_interval(api):
    """PRD §3.3: "The `planned_discharge_at` instant must be strictly later than the
    current clock, or the request fails with `ERR_INVALID_INTERVAL`."
    PRD §2.10: "32. Caller-supplied instants lie in the future and are internally
    ordered — `ERR_INVALID_INTERVAL`, 422 — on the admission request, on extend, on
    scheduling a mediation session, and on opening a governance proposal."
    PRD §2.5: "The clock starts at `2026-08-01T00:00:00Z` and stays there until an
    administrator moves it; the server never falls back to real time for any purpose."

    Design: Corner/errors/planned_discharge_in_the_past_returns_invalid_interval
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    youth = intake_youth(**dict(RUNE))
    clear_screening(youth["id"])

    response = api.create_admission(
        admission_payload(youth["id"], program["id"], PAST_DISCHARGE), CASE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_INTERVAL.value, 422)
    current = fetch_program(program["id"])
    assert_program_counters(current)
    assert current["occupied_beds"] == 0, (
        "an instant a month behind the 2026-08-01 clock consumes no bed, got "
        f"{current['occupied_beds']}"
    )
    assert fetch_youth(youth["id"])["status"] == "PROSPECT", (
        "the cleared youth is left a prospect by the refusal"
    )
