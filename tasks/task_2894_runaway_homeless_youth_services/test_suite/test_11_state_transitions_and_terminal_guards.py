"""Declared transitions, legitimate self-loops and terminal-state lockdown.

Each case drives one documented edge of a state machine and then replays it, so
the second attempt shows both the refusal code and that no counter moved twice.
"""

from test_helpers import (
    ADMIN,
    ADMIN_ALT,
    CASE_MANAGER,
    COORDINATOR,
    SPECIALIST,
    USER_IDS,
    ApiErrorId,
    assert_admission,
    assert_guardian_notification,
    assert_governance_proposal,
    assert_instant_equals,
    assert_mediation_session,
    assert_program_counters,
    assert_reunification_case,
    assert_safety_screening,
    assert_tlp_placement,
    cast_vote,
    close_vote,
    disposition_screening,
    exit_placement,
    fetch_admission,
    fetch_case,
    fetch_placement,
    fetch_program,
    fetch_proposal,
    fetch_youth,
    instant,
    intake_youth,
    license_emergency_shelter,
    move_clock,
    notification_of_admission,
    open_case,
    open_proposal,
    record_attempt,
    record_session_outcome,
    schedule_session,
    setup_active_admission,
    setup_pending_screening_admission,
    setup_sheltered_youth_open_posture,
    setup_tlp_placement,
    setup_vote_eligible_youth,
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
NORTHSIDE = {
    "name": "Northside Transitional Living",
    "licensed_bed_capacity": 3,
    "min_age_years": 16,
    "max_age_years": 20,
    "max_placement_days": 540,
    "savings_match_rate_bp": 2500,
    "required_savings_rate_bp": 2000,
}
DOB_16 = "2010-03-15"
PLANNED_DISCHARGE = instant("2026-08-15")


def _pending_screening_admission(first_name="Iris", last_name="Vance"):
    return setup_pending_screening_admission(
        program_overrides=dict(RIVERSIDE),
        youth_overrides={"legal_first_name": first_name, "legal_last_name": last_name,
                         "date_of_birth": DOB_16, "unaccompanied": True},
        planned_discharge_at=PLANNED_DISCHARGE,
    )


def test_admission_without_a_screening_rests_in_pending_screening(api):
    """PRD §3.3: "Otherwise the admission rests in its initial `PENDING_SCREENING`
    status and nothing further changes until a screening is dispositioned as
    cleared."
    PRD §3.3: "The `PENDING_SCREENING` branch leaves `admitted_at` null, consumes no
    bed, creates no obligation and changes no youth field."
    PRD §3.3: "On acceptance the server stamps `requested_at` with the clock instant,
    records the acting case manager as `admitting_user_id` — the value that later
    governs who may waive the parental notification — and freezes `priority_score`
    onto the row."

    Design: Corner/state_machines/admission_initial_state_is_pending_screening
    """
    setup = _pending_screening_admission()
    admission = setup["admission"]

    assert_admission(admission)
    assert admission["status"] == "PENDING_SCREENING", (
        f"a youth with no screening on file waits for one, got {admission['status']}"
    )
    assert admission["admitted_at"] is None, (
        f"no stay has begun, got {admission['admitted_at']}"
    )
    assert admission["capacity_blocked"] is False, (
        f"the request was not diverted by a full program, got {admission['capacity_blocked']}"
    )
    assert admission["extension_count"] == 0, (
        f"a fresh request has never been extended, got {admission['extension_count']}"
    )
    assert_instant_equals(admission["requested_at"], instant("2026-08-01"),
                          "the admission's requested_at")
    assert admission["admitting_user_id"] == USER_IDS["SHELTER_CASE_MANAGER"], (
        f"the acting case manager is stamped onto the row, got {admission['admitting_user_id']}"
    )

    program = fetch_program(setup["program"]["id"])
    assert_program_counters(program)
    assert program["occupied_beds"] == 0, (
        f"the request consumes no bed, got {program['occupied_beds']}"
    )
    assert program["posture"] == "OPEN", (
        f"an unconsumed program stays OPEN, got {program['posture']}"
    )
    youth = fetch_youth(setup["youth"]["id"])
    assert youth["status"] == "PROSPECT", (
        f"no youth field changes on this branch, got {youth['status']}"
    )
    _rows, meta = validate_paginated(
        api.list_guardian_notifications(admission["id"], CASE_MANAGER)
    )
    assert meta["total_count"] == 0, (
        f"the branch creates no obligation, got {meta['total_count']}"
    )


def test_clearing_the_screening_activates_the_waiting_admission(api):
    """PRD §3.2: "`CLEARED` recomputes the youth's `risk_posture`, which leaves
    `FROZEN`, and then fires a further cascade: the youth's oldest admission still
    waiting on screening — the one with the earliest `created_at` among that youth's
    admissions in `PENDING_SCREENING` — advances to its active stay, which stamps
    that admission's `admitted_at`, computes its projected billable nights,
    increments the program's `occupied_beds` and recomputes that program's
    `utilization_bp` and `posture`, and creates that admission's parental-notification
    obligation in `PENDING`."
    PRD §3.3: "The age component is eighteen minus the youth's `age_years`, held at a
    floor of zero so that a youth aged eighteen or older contributes nothing,
    multiplied by four — so a fourteen-year-old contributes sixteen points."
    PRD §3.3: "The exposure component is 15 for a youth whose
    `cumulative_shelter_nights` is exactly zero — a first-time entrant to the system
    — and otherwise 15 minus the youth's `cumulative_shelter_nights`, held at a floor
    of zero."
    PRD §3.4: "The obligation references its admission through `admission_id`, opens
    in `status` `PENDING` with `attempt_count` at 0, `last_attempt_at` null and
    `resolved_at` null, and carries a `due_at` computed as the admission's
    `admitted_at` plus twenty-four hours."

    Design: Corner/state_machines/screening_cleared_disposition_activates_the_pending_admission
    """
    setup = _pending_screening_admission()
    screening = submit_screening(setup["youth"]["id"])

    response = api.disposition_safety_screening(
        screening["id"], {"disposition": "CLEARED"}, ADMIN
    )
    dispositioned = validate_success(response)

    assert_safety_screening(dispositioned)
    assert dispositioned["status"] == "CLEARED", (
        f"the disposition is recorded on the row, got {dispositioned['status']}"
    )
    assert dispositioned["screener_user_id"] == USER_IDS["OUTREACH_WORKER"], (
        f"the submitter is preserved, got {dispositioned['screener_user_id']}"
    )
    assert dispositioned["disposition_user_id"] == USER_IDS["PROGRAM_ADMIN"], (
        f"the deciding administrator is stamped, got {dispositioned['disposition_user_id']}"
    )

    admission = fetch_admission(setup["admission"]["id"])
    assert admission["status"] == "ACTIVE", (
        f"the waiting admission advances to its stay, got {admission['status']}"
    )
    assert_instant_equals(admission["admitted_at"], instant("2026-08-01"),
                          "the activated admission's admitted_at")
    assert admission["priority_score"] == 23, (
        "eight age points for a sixteen-year-old plus fifteen exposure points is 23, "
        f"got {admission['priority_score']}"
    )

    program = fetch_program(setup["program"]["id"])
    assert program["occupied_beds"] == 1, (
        f"the activation consumes one bed, got {program['occupied_beds']}"
    )
    assert program["utilization_bp"] == 5000, (
        f"one of two beds is 5000 basis points, got {program['utilization_bp']}"
    )
    assert program["posture"] == "OPEN", (
        f"half-filled and with nothing overdue is OPEN, got {program['posture']}"
    )

    notification = notification_of_admission(admission["id"])
    assert_guardian_notification(notification)
    assert notification["status"] == "PENDING", (
        f"the obligation opens in PENDING, got {notification['status']}"
    )
    assert notification["attempt_count"] == 0, (
        f"nothing has been attempted yet, got {notification['attempt_count']}"
    )
    assert_instant_equals(notification["due_at"], instant("2026-08-02"),
                          "the obligation's due_at")

    youth = fetch_youth(setup["youth"]["id"])
    assert youth["status"] == "SHELTERED", (
        f"the youth now occupies a bed, got {youth['status']}"
    )
    assert youth["risk_posture"] == "RESTRICTED", (
        f"the pending obligation restricts the youth, got {youth['risk_posture']}"
    )


def test_a_second_attempt_is_a_self_loop_that_overwrites_the_channel(api):
    """PRD §3.4: "Each recorded attempt supplies `attempt_channel`, one of `PHONE`,
    `IN_PERSON`, `CERTIFIED_MAIL` or `EMAIL`, raises `attempt_count` by one, stamps
    `last_attempt_at` with the clock instant and stores the channel, overwriting
    whatever channel a previous attempt had recorded."
    PRD §3.4: "The first attempt moves the obligation `PENDING → ATTEMPTED`; further
    attempts are a legitimate self-loop `ATTEMPTED → ATTEMPTED`, because chasing a
    guardian usually takes several tries."

    Design: Corner/state_machines/guardian_notification_attempt_self_loop_overwrites_the_channel
    """
    setup = setup_active_admission(
        program_overrides=dict(RIVERSIDE),
        youth_overrides={"legal_first_name": "Sasha", "legal_last_name": "Byrne",
                         "date_of_birth": DOB_16, "unaccompanied": True},
        planned_discharge_at=PLANNED_DISCHARGE,
    )
    record_attempt(setup["notification"]["id"], "PHONE")
    move_clock(instant("2026-08-01", "06:00:00"))

    response = api.record_notification_attempt(
        setup["notification"]["id"], {"attempt_channel": "CERTIFIED_MAIL"}, CASE_MANAGER
    )
    notification = validate_success(response)

    assert_guardian_notification(notification)
    assert notification["status"] == "ATTEMPTED", (
        f"the self-loop leaves the obligation ATTEMPTED, got {notification['status']}"
    )
    assert notification["attempt_count"] == 2, (
        f"each attempt raises the count by one, got {notification['attempt_count']}"
    )
    assert notification["attempt_channel"] == "CERTIFIED_MAIL", (
        "the newest channel overwrites the previous one rather than being appended, "
        f"got {notification['attempt_channel']}"
    )
    assert_instant_equals(notification["last_attempt_at"],
                          instant("2026-08-01", "06:00:00"),
                          "the obligation's last_attempt_at")
    assert notification["resolved_at"] is None, (
        f"chasing a guardian resolves nothing, got {notification['resolved_at']}"
    )

    youth = fetch_youth(setup["youth"]["id"])
    assert youth["risk_posture"] == "RESTRICTED", (
        f"the obligation is still open, got {youth['risk_posture']}"
    )
    program = fetch_program(setup["program"]["id"])
    assert program["overdue_notification_count"] == 0, (
        f"the obligation is not yet past due, got {program['overdue_notification_count']}"
    )


def test_contacted_resolution_with_no_attempt_on_file_is_refused(api):
    """PRD §3.4: "`CONTACTED` records that the guardian was actually reached; it is
    available from `ATTEMPTED` and from `OVERDUE`, requires that at least one attempt
    has already been recorded, and requires that the youth's `risk_posture` is not
    `FROZEN` — an escalated safety screening forbids guardian contact outright."
    PRD §3.4: "Resolving as contacted with zero recorded attempts, or while the youth
    is frozen, is refused with `ERR_NOTIFICATION_UNSAFE_CONTACT`."

    Design: Corner/state_machines/notification_resolve_contacted_with_zero_attempts_is_rejected
    """
    setup = setup_active_admission(
        program_overrides=dict(RIVERSIDE),
        youth_overrides={"legal_first_name": "Tovah", "legal_last_name": "Lund",
                         "date_of_birth": DOB_16, "unaccompanied": True},
        planned_discharge_at=PLANNED_DISCHARGE,
    )

    response = api.resolve_notification(
        setup["notification"]["id"], {"outcome": "CONTACTED"}, CASE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_NOTIFICATION_UNSAFE_CONTACT.value, 422)
    notification = notification_of_admission(setup["admission"]["id"])
    assert notification["status"] == "PENDING", (
        f"the refused resolution leaves the obligation open, got {notification['status']}"
    )
    assert notification["attempt_count"] == 0, (
        f"no attempt was recorded, got {notification['attempt_count']}"
    )
    assert notification["resolved_at"] is None, (
        f"nothing was resolved, got {notification['resolved_at']}"
    )
    youth = fetch_youth(setup["youth"]["id"])
    assert youth["risk_posture"] == "RESTRICTED", (
        "the open obligation still restricts the youth, got "
        f"{youth['risk_posture']}"
    )


def test_a_discharged_admission_refuses_a_second_discharge(api):
    """PRD §3.5: "An admission in `PENDING_SCREENING` or `WAITLISTED` cannot be
    discharged or extended and is refused with `ERR_ADMISSION_NOT_ACTIVE`; an
    admission already in `DISCHARGED` or `DENIED` is refused with
    `ERR_ADMISSION_ALREADY_TERMINAL`."
    PRD §3.5: "At discharge it is the number of whole calendar days from the calendar
    date of `admitted_at` to the calendar date of `discharged_at`, plus one further
    night when the hour of the discharge instant is at or after twelve — a youth
    still in the bed at or after 12:00:00Z on the discharge date has occupied that
    night's bed for federal reporting purposes."

    Design: Corner/state_machines/discharged_admission_rejects_a_second_discharge
    """
    setup = setup_active_admission(
        program_overrides=dict(RIVERSIDE),
        youth_overrides={"legal_first_name": "Odell", "legal_last_name": "Prasad",
                         "date_of_birth": DOB_16, "unaccompanied": True},
        planned_discharge_at=PLANNED_DISCHARGE,
    )
    first = validate_success(
        api.discharge_admission(
            setup["admission"]["id"], {"exit_destination": "OTHER_SHELTER"}, CASE_MANAGER
        )
    )
    assert first["status"] == "DISCHARGED", (
        f"the first discharge terminates the stay, got {first['status']}"
    )

    response = api.discharge_admission(
        setup["admission"]["id"], {"exit_destination": "UNKNOWN"}, CASE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_ADMISSION_ALREADY_TERMINAL.value, 409)
    admission = fetch_admission(setup["admission"]["id"])
    assert admission["status"] == "DISCHARGED", (
        f"the terminal status is unchanged, got {admission['status']}"
    )
    assert admission["exit_destination"] == "OTHER_SHELTER", (
        "the destination of the accepted discharge stands, got "
        f"{admission['exit_destination']}"
    )
    assert admission["final_billable_nights"] == 0, (
        "the discharge date equals the admission date and the hour is before twelve, "
        f"so no night is billable, got {admission['final_billable_nights']}"
    )

    program = fetch_program(setup["program"]["id"])
    assert_program_counters(program)
    assert program["occupied_beds"] == 0, (
        f"the bed is released exactly once, got {program['occupied_beds']}"
    )
    assert program["utilization_bp"] == 0, (
        f"an empty program is at zero basis points, got {program['utilization_bp']}"
    )
    youth = fetch_youth(setup["youth"]["id"])
    assert youth["status"] == "EXITED", (
        f"an OTHER_SHELTER destination exits the youth, got {youth['status']}"
    )
    assert youth["cumulative_shelter_nights"] == 0, (
        f"no billable night accrued, got {youth['cumulative_shelter_nights']}"
    )


def test_a_resolved_notification_refuses_a_second_resolution(api):
    """PRD §2.10: "The guardian notification is not already `CONTACTED`, `WAIVED` or
    `LAW_ENFORCEMENT_REPORTED` — `ERR_NOTIFICATION_ALREADY_RESOLVED`, 409 — on
    recording an attempt and on resolving."
    PRD §3.4: "Every accepted resolution stamps `resolved_at` with the clock instant
    and stores the acting identifier as `resolving_user_id`; a law-enforcement
    resolution additionally stamps `runaway_report_filed_at` with the same instant."

    Design: Corner/state_machines/resolved_notification_rejects_a_second_resolve
    """
    setup = setup_sheltered_youth_open_posture(
        program_overrides=dict(RIVERSIDE),
        youth_overrides={"legal_first_name": "Wren", "legal_last_name": "Adeyemi",
                         "date_of_birth": DOB_16, "unaccompanied": True},
        planned_discharge_at=PLANNED_DISCHARGE,
    )
    move_clock(instant("2026-08-01", "09:00:00"))

    response = api.resolve_notification(
        setup["notification"]["id"], {"outcome": "CONTACTED"}, CASE_MANAGER
    )

    error = validate_error(response, ApiErrorId.ERR_NOTIFICATION_ALREADY_RESOLVED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_NOTIFICATION_UNSAFE_CONTACT.value, (
        "the already-resolved guard outranks the safety gate, got "
        f"{error['error_id']}"
    )
    notification = notification_of_admission(setup["admission"]["id"])
    assert notification["status"] == "CONTACTED", (
        f"the terminal resolution stands, got {notification['status']}"
    )
    assert_instant_equals(notification["resolved_at"], instant("2026-08-01"),
                          "the notification's resolved_at")
    assert notification["attempt_count"] == 1, (
        f"the single recorded attempt is preserved, got {notification['attempt_count']}"
    )
    youth = fetch_youth(setup["youth"]["id"])
    assert youth["risk_posture"] == "OPEN", (
        f"the resolved obligation leaves the youth open, got {youth['risk_posture']}"
    )


def test_re_clearing_an_already_cleared_screening_is_not_a_declared_transition(api):
    """PRD §2.10: "The requested screening disposition is a declared transition —
    `ERR_SCREENING_INVALID_TRANSITION`, 409 — on screening disposition. `SUBMITTED`
    may go to `CLEARED` or `ESCALATED`, `ESCALATED` may go to `CLEARED`, and `CLEARED`
    may go to `ESCALATED`; re-clearing an already-`CLEARED` screening and
    re-escalating an already-`ESCALATED` screening are not declared transitions."

    Design: Corner/state_machines/cleared_screening_rejects_a_second_cleared_disposition
    """
    youth = intake_youth(legal_first_name="Kai", legal_last_name="Ferreira",
                         date_of_birth=DOB_16, unaccompanied=True)
    screening = submit_screening(youth["id"])
    disposition_screening(screening["id"], "CLEARED")

    response = api.disposition_safety_screening(
        screening["id"], {"disposition": "CLEARED"}, ADMIN
    )

    validate_error(response, ApiErrorId.ERR_SCREENING_INVALID_TRANSITION.value, 409)
    rows, meta = validate_paginated(api.list_safety_screenings(youth["id"], ADMIN))
    assert meta["total_count"] == 1, (
        f"the refused disposition wrote no new screening, got {meta['total_count']}"
    )
    stored = next(row for row in rows if row["id"] == screening["id"])
    assert stored["status"] == "CLEARED", (
        f"the screening keeps its cleared disposition, got {stored['status']}"
    )
    current = fetch_youth(youth["id"])
    assert current["risk_posture"] == "OPEN", (
        f"a cleared screening leaves the youth open, got {current['risk_posture']}"
    )


def test_a_screening_travels_cleared_to_escalated_and_back(api):
    """PRD §3.2: "A `CLEARED` screening may later be re-escalated `CLEARED →
    ESCALATED`, and an `ESCALATED` screening may be re-cleared `ESCALATED → CLEARED`
    once the specialized response has run."
    PRD §3.2: "`ESCALATED` recomputes the youth's `risk_posture` to `FROZEN`, which
    from that moment blocks opening a reunification case for that youth, blocks
    approving a reunification decision, and blocks resolving any of that youth's
    parental notifications as contacted — family contact is unsafe while a screening
    stands escalated."
    PRD §3.2: "That figure is frozen onto the row and is never re-decayed afterwards."

    Design: Corner/state_machines/screening_cleared_to_escalated_and_back_is_a_real_cycle
    """
    youth = intake_youth(legal_first_name="Lior", legal_last_name="Mbeki",
                         date_of_birth=DOB_16, unaccompanied=True)
    screening = submit_screening(youth["id"], ["CURFEW_ENFORCED"])
    disposition_screening(screening["id"], "CLEARED")

    escalated = validate_success(
        api.disposition_safety_screening(
            screening["id"],
            {"disposition": "ESCALATED", "specialized_response_code": "ADVOCATE_ASSIGNED"},
            ADMIN,
        )
    )
    assert escalated["status"] == "ESCALATED", (
        f"a cleared screening may be re-escalated, got {escalated['status']}"
    )
    assert escalated["specialized_response_code"] == "ADVOCATE_ASSIGNED", (
        "the specialized response is recorded at disposition time, got "
        f"{escalated['specialized_response_code']}"
    )
    frozen = fetch_youth(youth["id"])
    assert frozen["risk_posture"] == "FROZEN", (
        f"an escalated screening freezes the youth, got {frozen['risk_posture']}"
    )

    recleared = validate_success(
        api.disposition_safety_screening(
            screening["id"], {"disposition": "CLEARED"}, ADMIN_ALT
        )
    )
    assert recleared["status"] == "CLEARED", (
        f"an escalated screening may be re-cleared, got {recleared['status']}"
    )
    assert recleared["score"] == 10, (
        f"the frozen score is never recomputed, got {recleared['score']}"
    )
    assert recleared["tier"] == "LOW", (
        f"a score of ten reads as LOW, got {recleared['tier']}"
    )
    thawed = fetch_youth(youth["id"])
    assert thawed["risk_posture"] == "OPEN", (
        "the posture is derived from the latest disposition rather than latched, got "
        f"{thawed['risk_posture']}"
    )


def test_a_mediation_outcome_cannot_be_recorded_twice(api):
    """PRD §2.10: "The mediation session has no recorded outcome yet and its case is
    neither `SUPERSEDED` nor `CLOSED` — `ERR_SESSION_ALREADY_RECORDED`, 409 — on
    recording a mediation outcome."

    Design: Corner/state_machines/mediation_session_outcome_cannot_be_recorded_twice
    """
    youth = intake_youth(legal_first_name="Bex", legal_last_name="Alvarez",
                         date_of_birth=DOB_16, unaccompanied=True)
    case = open_case(youth["id"], household_label="Alvarez household")
    session = schedule_session(
        case["id"], instant("2026-08-03", "14:00:00"), instant("2026-08-03", "16:00:00")
    )
    move_clock(instant("2026-08-03", "14:30:00"))
    record_session_outcome(session["id"], "PROGRESS", headers=SPECIALIST)

    response = api.record_mediation_outcome(
        session["id"], {"outcome": "IMPASSE"}, SPECIALIST
    )

    validate_error(response, ApiErrorId.ERR_SESSION_ALREADY_RECORDED.value, 409)
    rows, meta = validate_paginated(api.list_mediation_sessions(case["id"], SPECIALIST))
    assert meta["total_count"] == 1, (
        f"the replay created no second session, got {meta['total_count']}"
    )
    stored = rows[0]
    assert_mediation_session(stored)
    assert stored["outcome"] == "PROGRESS", (
        f"the recorded outcome is not overwritten, got {stored['outcome']}"
    )
    assert_instant_equals(stored["held_at"], instant("2026-08-03", "14:30:00"),
                          "the session's held_at")
    assert stored["round_number"] == 1, (
        f"the session keeps its round number, got {stored['round_number']}"
    )

    current = fetch_case(case["id"])
    assert_reunification_case(current)
    assert current["status"] == "MEDIATION_HELD", (
        f"the case rests where the accepted recording left it, got {current['status']}"
    )
    assert current["mediation_round"] == 1, (
        f"the refused replay advances no round, got {current['mediation_round']}"
    )


def test_an_exited_placement_refuses_a_second_exit(api):
    """PRD §3.7: "This is available from `PLACED` and from `NOTICE_GIVEN`, and both
    routes behave identically: `tenancy_status` becomes `EXITED`, `exited_at` is
    stamped with the clock instant, the reason is stored, the program's
    `occupied_beds` falls by one — which forces `utilization_bp` and `posture` to be
    recomputed — the youth moves `TLP_ENROLLED → EXITED` with the youth's `version`
    incremented by one and `governance_vote_eligible` recomputed to false, and
    `compliance_status` is frozen at whatever value it held and is no longer
    reviewable."
    PRD §3.7: "Any savings entry, life-skills completion, compliance review or second
    exit attempted against an already-exited placement is refused with
    `ERR_PLACEMENT_ALREADY_EXITED`."

    Design: Corner/state_machines/exited_placement_rejects_a_second_exit
    """
    setup = setup_tlp_placement(
        documented_monthly_income_cents=90000,
        shelter_program_overrides=dict(RIVERSIDE),
        tlp_program_overrides=dict(NORTHSIDE),
        youth_overrides={"legal_first_name": "Petra", "legal_last_name": "Osei",
                         "date_of_birth": DOB_16, "unaccompanied": True},
    )
    exited = exit_placement(setup["placement"]["id"], "INDEPENDENT_HOUSING")
    assert exited["tenancy_status"] == "EXITED", (
        f"the first exit ends the tenancy, got {exited['tenancy_status']}"
    )

    response = api.exit_tlp_placement(
        setup["placement"]["id"], {"exit_reason": "YOUTH_INITIATED"}, COORDINATOR
    )

    validate_error(response, ApiErrorId.ERR_PLACEMENT_ALREADY_EXITED.value, 409)
    placement = fetch_placement(setup["placement"]["id"])
    assert_tlp_placement(placement)
    assert placement["tenancy_status"] == "EXITED", (
        f"the terminal tenancy stands, got {placement['tenancy_status']}"
    )
    assert placement["exit_reason"] == "INDEPENDENT_HOUSING", (
        f"the reason of the accepted exit is kept, got {placement['exit_reason']}"
    )
    assert_instant_equals(placement["exited_at"], instant("2026-08-01"),
                          "the placement's exited_at")

    program = fetch_program(setup["tlp_program"]["id"])
    assert_program_counters(program)
    assert program["occupied_beds"] == 0, (
        f"the transitional-living bed is released exactly once, got {program['occupied_beds']}"
    )
    assert program["utilization_bp"] == 0, (
        f"an empty program is at zero basis points, got {program['utilization_bp']}"
    )
    youth = fetch_youth(setup["youth"]["id"])
    assert youth["status"] == "EXITED", (
        f"the exit moves the youth out of TLP_ENROLLED, got {youth['status']}"
    )


def test_a_decided_proposal_refuses_a_second_close(api):
    """PRD §3.9: "Otherwise the proposal becomes `ADOPTED` when `support_ratio_bp` has
    reached or passed 5000 basis points — a simple majority of the electorate — **and**
    `support_vote_count` is at least 2, so a single supporter can never adopt a
    proposal however small the electorate."
    PRD §3.9: "Otherwise, when either the ratio falls short of 5000 basis points or
    the support count falls short of 2, the proposal becomes `REJECTED`."
    PRD §3.9: "Both decided outcomes freeze `eligible_electorate_size` and
    `support_ratio_bp` onto the row and record the acting administrator as
    `decided_by_user_id`; adoption additionally stamps `adopted_at` with the clock
    instant, while rejection leaves `adopted_at` null."
    PRD §3.9: "A second close attempt on an already-decided proposal is refused with
    `ERR_PROPOSAL_ALREADY_DECIDED`."

    Design: Corner/state_machines/decided_proposal_rejects_a_second_close_vote
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    resident = setup_vote_eligible_youth(
        program["id"], PLANNED_DISCHARGE,
        {"legal_first_name": "Suri", "legal_last_name": "Baptiste",
         "date_of_birth": DOB_16, "unaccompanied": True},
    )
    proposal = open_proposal(
        program["id"], instant("2026-08-20"),
        title="Quiet hours after 22:00", category="HOUSE_RULES",
    )
    vote = cast_vote(proposal["id"], resident["youth"]["id"], "SUPPORT")
    decided = close_vote(proposal["id"])
    assert decided["status"] == "REJECTED", (
        "one supporter in an electorate of one falls short of the two-vote floor, "
        f"got {decided['status']}"
    )

    response = api.close_governance_vote(proposal["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_PROPOSAL_ALREADY_DECIDED.value, 409)
    stored = fetch_proposal(proposal["id"])
    assert_governance_proposal(stored)
    assert stored["status"] == "REJECTED", (
        f"the decided outcome is terminal, got {stored['status']}"
    )
    assert stored["eligible_electorate_size"] == 1, (
        f"exactly one resident youth is eligible, got {stored['eligible_electorate_size']}"
    )
    assert stored["support_ratio_bp"] == 10000, (
        "one support vote over an electorate of one is the whole, got "
        f"{stored['support_ratio_bp']}"
    )
    assert stored["support_vote_count"] == 1, (
        f"the frozen tally counts one supporter, got {stored['support_vote_count']}"
    )
    assert stored["adopted_at"] is None, (
        f"a rejection leaves adopted_at null, got {stored['adopted_at']}"
    )
    rows, _meta = validate_paginated(api.list_proposal_votes(proposal["id"], ADMIN))
    counted = next(row for row in rows if row["id"] == vote["id"])
    assert counted["status"] == "COUNTED", (
        f"the cast vote is still counted, got {counted['status']}"
    )
