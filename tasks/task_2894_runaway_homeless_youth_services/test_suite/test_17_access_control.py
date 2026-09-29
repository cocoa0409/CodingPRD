"""Who may act, in which capacity, and on whose rows.

The first three rungs of the ladder are distinguishable from one another only by
what they answer, so every case here also names the neighbouring code that must
not appear: a 401 that is not a 403, a role refusal that is not an ownership
refusal, an ownership refusal that is not a not-found.
"""

from test_helpers import (
    ADMIN,
    CASE_MANAGER,
    COORDINATOR,
    USER_IDS,
    WORKER,
    ApiErrorId,
    UserRole,
    admission_payload,
    assert_compliance_report,
    assert_governance_proposal,
    assert_governance_vote,
    assert_instant_equals,
    assert_outreach_contact,
    assert_tlp_placement,
    assert_youth,
    cast_vote,
    decision_payload,
    emergency_shelter_payload,
    fetch_case,
    fetch_placement,
    fetch_youth,
    governance_proposal_payload,
    governance_vote_payload,
    home_assessment_payload,
    instant,
    intake_youth,
    license_emergency_shelter,
    license_transitional_living,
    life_skills_completion_payload,
    make_headers,
    make_outreach_worker_headers,
    make_program_admin_headers,
    make_reunification_specialist_headers,
    make_shelter_case_manager_headers,
    make_youth_member_headers,
    move_clock,
    notification_attempt_payload,
    notification_of_admission,
    notification_resolve_payload,
    open_case,
    open_proposal,
    outreach_contact_payload,
    record_attempt,
    record_session_outcome,
    request_admission,
    safety_screening_payload,
    schedule_session,
    screening_disposition_payload,
    setup_vote_eligible_youth,
    submit_screening,
    tlp_placement_payload,
    validate_error,
    validate_paginated,
    validate_success,
    youth_payload,
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
VOTING_CLOSES_AT = instant("2026-08-10")


# ─── Instance: rung one answers before anything else is looked at ───

ODILE = {
    "legal_first_name": "Odile",
    "legal_last_name": "Marchand",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
UNRECOGNISED_ROLE = "Superintendent"


def test_empty_and_unrecognised_auth_headers_answer_with_one_code(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, declaring the capacity in which that user acts."
    PRD §2.1: "Both headers must be present and non-empty; a missing, empty or
    whitespace-only value, or a role string that is not one of the six recognised roles,
    is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before any other processing
    occurs."
    PRD §2.1: "Once the headers are accepted, the acting role must appear in the
    authorised-role list of the endpoint being called; if it does not, the request is
    refused with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §2.10: "1. Authentication headers present, non-empty, and the role recognised —
    `ERR_MISSING_AUTH_HEADERS`, 401, on every endpoint."
    PRD §2.10: "4. Every identifier in the path resolves, left to right — the matching
    not-found code, 404, on every path-templated endpoint."

    Design: Corner/rbac/blank_auth_headers_are_rejected
    """
    youth = intake_youth(**dict(ODILE))

    blank_role = api.get_youth(
        youth["id"], make_headers(USER_IDS["OUTREACH_WORKER"], "")
    )
    blank_user = api.get_youth(
        youth["id"], make_headers("", UserRole.OUTREACH_WORKER.value)
    )
    unrecognised = api.get_youth(
        youth["id"], make_headers(USER_IDS["OUTREACH_WORKER"], UNRECOGNISED_ROLE)
    )

    refusals = [
        validate_error(blank_role, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value, 401),
        validate_error(blank_user, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value, 401),
        validate_error(unrecognised, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value, 401),
    ]
    for error in refusals:
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, (
            "an unusable header pair never reaches the endpoint's role list, got "
            f"{error['error_id']}"
        )
        assert error["error_id"] != ApiErrorId.ERR_YOUTH_NOT_FOUND.value, (
            "the addressed youth genuinely exists, and rung one answers before the path "
            f"is resolved at all, got {error['error_id']}"
        )
    readable = validate_success(api.get_youth(youth["id"], WORKER))
    assert_youth(readable)
    assert readable["id"] == youth["id"], (
        "the same path with a usable header pair reads the row"
    )


# ─── Instance: peer roles are mutually exclusive on their own writes ───

LIOR = {
    "legal_first_name": "Lior",
    "legal_last_name": "Benali",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
MONA = {
    "legal_first_name": "Mona",
    "legal_last_name": "Benali",
    "date_of_birth": "2011-03-15",
    "unaccompanied": True,
}


def test_each_roles_exclusive_write_refuses_every_peer_role(api):
    """PRD §2.1: "An `OutreachWorker` is street outreach staff: this role alone intakes
    new youths and logs street-outreach encounters, and it shares the submission of
    safety screenings with a `ShelterCaseManager`."
    PRD §2.1: "A `ShelterCaseManager` is emergency-shelter staff: this role alone
    requests admissions, extends stays, discharges youths and records
    parental-notification attempts, and it shares notification resolution with a
    `ProgramAdmin` and shares education enrollment and records verification with a
    `TlpCoordinator`."
    PRD §2.1: "A `ProgramAdmin` licenses programs, dispositions safety screenings, closes
    governance votes, reads the federal compliance report, drives the logical clock and
    the nightly census, and may read every read endpoint in the system."
    PRD §2.1: "A `TlpCoordinator` owns transitional living exclusively: creating
    placements, posting savings entries, crediting life-skills completions and ending
    tenancies, and shares the savings-compliance review with a `ProgramAdmin`."
    PRD §2.10: "2. The acting role is authorised for the endpoint —
    `ERR_UNAUTHORIZED_ROLE`, 403, on every endpoint."

    Design: Corner/rbac/wrong_role_on_another_roles_exclusive_operation_is_rejected
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    youth = intake_youth(**dict(LIOR))
    screening = submit_screening(youth["id"], [])

    validate_error(
        api.create_admission(
            admission_payload(youth["id"], program["id"], PLANNED_DISCHARGE), WORKER
        ),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE.value,
        403,
    )
    validate_error(
        api.create_youth(youth_payload(**dict(MONA)), ADMIN),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE.value,
        403,
    )
    validate_error(
        api.create_shelter_program(
            emergency_shelter_payload(name="Unauthorized Annex", licensed_bed_capacity=4),
            COORDINATOR,
        ),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE.value,
        403,
    )
    validate_error(
        api.disposition_safety_screening(
            screening["id"], screening_disposition_payload("CLEARED"), CASE_MANAGER
        ),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE.value,
        403,
    )

    _admissions, admission_meta = validate_paginated(api.list_admissions(ADMIN))
    assert admission_meta["total_count"] == 0, (
        f"the refused admission request created nothing, got {admission_meta['total_count']}"
    )
    _youths, youth_meta = validate_paginated(api.list_youths(ADMIN))
    assert youth_meta["total_count"] == 1, (
        f"the refused intake created no second youth, got {youth_meta['total_count']}"
    )
    _programs, program_meta = validate_paginated(api.list_shelter_programs(ADMIN))
    assert program_meta["total_count"] == 1, (
        f"the refused licence created no second program, got {program_meta['total_count']}"
    )
    rows, _meta = validate_paginated(api.list_safety_screenings(youth["id"], ADMIN))
    assert rows[0]["status"] == "SUBMITTED", (
        f"the refused disposition moved the screening nowhere, got {rows[0]['status']}"
    )


# ─── Instance: rung three compares the header against the row's own youth ───

PERLA = {
    "legal_first_name": "Perla",
    "legal_last_name": "Osei",
    "date_of_birth": "2010-04-15",
    "unaccompanied": True,
}
QUINN = {
    "legal_first_name": "Quinn",
    "legal_last_name": "Osei",
    "date_of_birth": "2010-04-15",
    "unaccompanied": True,
}


def test_a_resident_reaches_its_own_row_and_vote_and_no_peers(api):
    """PRD §2.1: "When `X-User-Role` is `YouthMember`, by contrast, `X-User-ID` **is**
    the `id` of the acting `Youth`; ownership checks compare the youth-referencing
    foreign key on the addressed resource to `X-User-ID`."
    PRD §2.1: "Concretely, a `YouthMember` may read only the youth record whose `id`
    equals its own `X-User-ID`, may list only its own governance votes, may retract only
    a `GovernanceVote` whose `youth_id` equals its own `X-User-ID`, and casts votes that
    are stamped with its own `X-User-ID` as `youth_id`."
    PRD §2.1: "Any attempt by a `YouthMember` to reach another youth's data or another
    youth's vote is rejected with `ERR_NOT_VOTE_OWNER` (HTTP 403)."
    PRD §2.10: "3. A `YouthMember` is acting only on its own resources —
    `ERR_NOT_VOTE_OWNER`, 403 — on reading one youth, listing a youth's governance votes,
    casting a vote on a proposal, and retracting a vote."
    PRD §3.9: "Retraction is subject to the same proposal-decided and voting-deadline
    gates as casting, and to the ownership rule of §2.1: a vote may only be retracted by
    the youth who cast it, and any other youth is refused with `ERR_NOT_VOTE_OWNER`."

    Design: Corner/rbac/a_youth_member_cannot_touch_another_youths_row_or_vote
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    first = setup_vote_eligible_youth(program["id"], PLANNED_DISCHARGE, dict(PERLA))["youth"]
    second = setup_vote_eligible_youth(program["id"], PLANNED_DISCHARGE, dict(QUINN))["youth"]
    proposal = open_proposal(
        program["id"],
        VOTING_CLOSES_AT,
        title="Quiet hours after 22:00",
        category="HOUSE_RULES",
    )
    vote = cast_vote(proposal["id"], first["id"], "SUPPORT")
    peer = make_youth_member_headers(second["id"])

    peer_read = api.get_youth(first["id"], peer)
    peer_retraction = api.retract_governance_vote(vote["id"], peer)

    validate_error(peer_read, ApiErrorId.ERR_NOT_VOTE_OWNER.value, 403)
    validate_error(peer_retraction, ApiErrorId.ERR_NOT_VOTE_OWNER.value, 403)

    own_row = validate_success(api.get_youth(second["id"], peer))
    assert own_row["id"] == second["id"], (
        f"the resident reads exactly its own row, got {own_row['id']}"
    )
    own_retraction = validate_success(
        api.retract_governance_vote(vote["id"], make_youth_member_headers(first["id"]))
    )
    assert_governance_vote(own_retraction)
    assert own_retraction["status"] == "RETRACTED", (
        f"the caster withdraws its own vote, got {own_retraction['status']}"
    )
    assert own_retraction["youth_id"] == first["id"], (
        f"the retracted vote is the first resident's, got {own_retraction['youth_id']}"
    )


# ─── Instance: rung two closes the whole staff surface to a resident ───

SENA = {
    "legal_first_name": "Sena",
    "legal_last_name": "Okafor",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}


def test_a_resident_is_refused_on_staff_endpoints_including_its_own_admission(api):
    """PRD §2.1: "A `YouthMember` is a resident youth participating in program
    governance: this role alone casts and retracts governance votes, shares proposal
    creation with a `ProgramAdmin`, and has access to no other read or write endpoint
    whatsoever."
    PRD §2.1: "Once the headers are accepted, the acting role must appear in the
    authorised-role list of the endpoint being called; if it does not, the request is
    refused with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §2.10: "2. The acting role is authorised for the endpoint —
    `ERR_UNAUTHORIZED_ROLE`, 403, on every endpoint."
    PRD §2.10: "3. A `YouthMember` is acting only on its own resources —
    `ERR_NOT_VOTE_OWNER`, 403 — on reading one youth, listing a youth's governance votes,
    casting a vote on a proposal, and retracting a vote."

    Design: Corner/rbac/a_youth_member_cannot_reach_any_staff_endpoint
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    setup = setup_vote_eligible_youth(program["id"], PLANNED_DISCHARGE, dict(SENA))
    resident = make_youth_member_headers(setup["youth"]["id"])
    assert setup["admission"]["status"] == "ACTIVE", (
        f"the resident holds a live stay, got {setup['admission']['status']}"
    )

    own_admission = api.get_admission(setup["admission"]["id"], resident)
    placements = api.list_tlp_placements(resident)
    youths = api.list_youths(resident)

    refusals = [
        validate_error(own_admission, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403),
        validate_error(placements, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403),
        validate_error(youths, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403),
    ]
    for error in refusals:
        assert error["error_id"] != ApiErrorId.ERR_NOT_VOTE_OWNER.value, (
            "the role check answers before ownership is ever considered, so even the "
            f"resident's own admission is a role refusal, got {error['error_id']}"
        )
    own_row = validate_success(api.get_youth(setup["youth"]["id"], resident))
    assert own_row["governance_vote_eligible"] is True, (
        "the only surface open to the resident still works, got "
        f"{own_row['governance_vote_eligible']}"
    )


# ─── Instance: rung twenty-four compares identifiers, never roles ───

TOVA = {
    "legal_first_name": "Tova",
    "legal_last_name": "Lindqvist",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
URI = {
    "legal_first_name": "Uri",
    "legal_last_name": "Bergman",
    "date_of_birth": "2010-04-15",
    "unaccompanied": True,
}
SESSION_START = instant("2026-08-03", "14:00:00")
SESSION_END = instant("2026-08-03", "16:00:00")
RECORDING_CLOCK = instant("2026-08-03", "14:30:00")


def _the_three_paired_operations(api):
    """A screening submitted by `worker-7`, an admission requested by `cm-7` whose
    obligation stands `ATTEMPTED`, and a separate case whose only held session was
    recorded by `spec-7` — one half of each segregation pair, ready to be closed."""
    worker_seven = make_outreach_worker_headers(USER_IDS["OUTREACH_WORKER_ALT"])
    case_manager_seven = make_shelter_case_manager_headers(
        USER_IDS["SHELTER_CASE_MANAGER_ALT"]
    )
    specialist_seven = make_reunification_specialist_headers(
        USER_IDS["REUNIFICATION_SPECIALIST_THIRD"]
    )

    program = license_emergency_shelter(**dict(RIVERSIDE))
    screened = intake_youth(headers=worker_seven, **dict(TOVA))
    screening = submit_screening(screened["id"], [], worker_seven)

    mediated = intake_youth(**dict(URI))
    case = open_case(mediated["id"], household_label="Bergman household",
                     headers=specialist_seven)
    session = schedule_session(case["id"], SESSION_START, SESSION_END, specialist_seven)
    move_clock(RECORDING_CLOCK)
    record_session_outcome(session["id"], "AGREEMENT", specialist_seven)
    validate_success(
        api.record_home_assessment(
            case["id"], home_assessment_payload("SAFE"), specialist_seven
        )
    )
    return {
        "program": program,
        "screened": screened,
        "screening": screening,
        "case": case,
        "session": session,
        "worker_seven": worker_seven,
        "case_manager_seven": case_manager_seven,
        "specialist_seven": specialist_seven,
    }


def test_the_screener_cannot_disposition_even_wearing_the_admin_role(api):
    """PRD §2.1: "Two segregation-of-duties rules cut across the role model and are
    enforced with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §2.1: "The user who records a mediation outcome may not be the user who decides
    that reunification case; the `ProgramAdmin` who waives a parental notification may not
    be the case manager who admitted the youth; and the administrator who dispositions a
    safety screening may not be the person who submitted it."
    PRD §3.2: "Whoever dispositions the screening must not be the person who submitted it:
    a matching identifier is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.10: "24. Segregation of duties on the three paired operations —
    `ERR_SEGREGATION_OF_DUTIES`, 403 — on the reunification decision, on notification
    resolution, and on screening disposition."

    Design: Corner/rbac/the_same_user_cannot_screen_and_disposition_or_admit_and_waive_or_record_and_decide
    """
    setup = _the_three_paired_operations(api)
    screening = setup["screening"]
    admin_under_the_screeners_id = make_program_admin_headers(
        USER_IDS["OUTREACH_WORKER_ALT"]
    )

    refused = api.disposition_safety_screening(
        screening["id"], screening_disposition_payload("CLEARED"),
        admin_under_the_screeners_id,
    )

    error = validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, (
        "the acting role is the authorised one, so only the identifier can explain the "
        f"refusal, got {error['error_id']}"
    )
    rows, _meta = validate_paginated(
        api.list_safety_screenings(setup["screened"]["id"], ADMIN)
    )
    assert rows[0]["status"] == "SUBMITTED", (
        f"the refused disposition moved nothing, got {rows[0]['status']}"
    )

    accepted = validate_success(
        api.disposition_safety_screening(
            screening["id"], screening_disposition_payload("CLEARED"), ADMIN
        )
    )
    assert accepted["status"] == "CLEARED", (
        f"a second identifier closes the pair immediately, got {accepted['status']}"
    )
    assert accepted["screener_user_id"] == USER_IDS["OUTREACH_WORKER_ALT"], (
        f"the submitting identifier is the one compared against, got "
        f"{accepted['screener_user_id']}"
    )
    assert accepted["disposition_user_id"] == USER_IDS["PROGRAM_ADMIN"], (
        f"the dispositioning identifier is stored separately, got "
        f"{accepted['disposition_user_id']}"
    )


def test_the_admitting_case_manager_cannot_waive_that_admissions_obligation(api):
    """PRD §3.4: "`WAIVED` records that a statute suppresses guardian contact
    altogether; it is available from `PENDING`, from `ATTEMPTED` and from `OVERDUE`, it
    may only be performed by a `ProgramAdmin`, it requires a `waiver_reason` of
    `ABUSE_DISCLOSED`, `TRAFFICKING_RISK` or `COURT_ORDER`, and the acting identifier must
    differ from the `admitting_user_id` of the admission — the administrator who waives
    may not be the case manager who admitted, and a match is refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.4: "Every accepted resolution stamps `resolved_at` with the clock instant and
    stores the acting identifier as `resolving_user_id`; a law-enforcement resolution
    additionally stamps `runaway_report_filed_at` with the same instant."

    Design: Corner/rbac/the_same_user_cannot_screen_and_disposition_or_admit_and_waive_or_record_and_decide
    """
    setup = _the_three_paired_operations(api)
    case_manager_seven = setup["case_manager_seven"]
    validate_success(
        api.disposition_safety_screening(
            setup["screening"]["id"], screening_disposition_payload("CLEARED"), ADMIN
        )
    )
    admission = request_admission(
        setup["screened"]["id"], setup["program"]["id"], PLANNED_DISCHARGE,
        headers=case_manager_seven,
    )
    assert admission["admitting_user_id"] == USER_IDS["SHELTER_CASE_MANAGER_ALT"], (
        f"the requesting identifier is recorded on the stay, got "
        f"{admission['admitting_user_id']}"
    )
    notification = notification_of_admission(admission["id"], case_manager_seven)
    record_attempt(notification["id"], "PHONE", case_manager_seven)
    admin_under_the_admitting_id = make_program_admin_headers(
        USER_IDS["SHELTER_CASE_MANAGER_ALT"]
    )

    refused = api.resolve_notification(
        notification["id"],
        notification_resolve_payload("WAIVED", "ABUSE_DISCLOSED"),
        admin_under_the_admitting_id,
    )

    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    unresolved = notification_of_admission(admission["id"])
    assert unresolved["status"] == "ATTEMPTED", (
        f"the refused waiver left the obligation open, got {unresolved['status']}"
    )
    assert unresolved["resolved_at"] is None, (
        f"nothing was stamped by the refusal, got {unresolved['resolved_at']}"
    )

    waived = validate_success(
        api.resolve_notification(
            notification["id"],
            notification_resolve_payload("WAIVED", "ABUSE_DISCLOSED"),
            ADMIN,
        )
    )
    assert waived["status"] == "WAIVED", (
        f"a second administrator closes the pair, got {waived['status']}"
    )
    assert waived["resolving_user_id"] == USER_IDS["PROGRAM_ADMIN"], (
        f"the accepted identifier is stored, got {waived['resolving_user_id']}"
    )
    assert_instant_equals(waived["resolved_at"], RECORDING_CLOCK,
                          "the waived obligation's resolved_at")


def test_the_recording_specialist_cannot_decide_the_case(api):
    """PRD §3.6: "Both branches require that the acting identifier differs from the
    `recorded_by_user_id` of the latest held session, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`; whoever ran the mediation may not also sign off on its
    result."
    PRD §3.6: "Both branches store the acting identifier as `decision_user_id`."

    Design: Corner/rbac/the_same_user_cannot_screen_and_disposition_or_admit_and_waive_or_record_and_decide
    """
    setup = _the_three_paired_operations(api)
    case = setup["case"]

    refused = api.decide_reunification_case(
        case["id"], decision_payload("APPROVE"), setup["specialist_seven"]
    )

    error = validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_NOTIFICATION_UNRESOLVED.value, (
        "this youth holds no admission at all, so the notification gate is vacuous, got "
        f"{error['error_id']}"
    )
    blocked = fetch_case(case["id"])
    assert blocked["status"] == "HOME_ASSESSMENT", (
        f"the refused decision moved the case nowhere, got {blocked['status']}"
    )
    assert blocked["decision_user_id"] is None, (
        f"no identifier was stamped by the refusal, got {blocked['decision_user_id']}"
    )

    approved = validate_success(
        api.decide_reunification_case(
            case["id"], decision_payload("APPROVE"),
            make_reunification_specialist_headers(
                USER_IDS["REUNIFICATION_SPECIALIST_FOURTH"]
            ),
        )
    )
    assert approved["status"] == "APPROVED", (
        f"a second specialist signs off immediately, got {approved['status']}"
    )
    assert approved["decision_user_id"] == USER_IDS["REUNIFICATION_SPECIALIST_FOURTH"], (
        f"the deciding identifier is stored on the case, got {approved['decision_user_id']}"
    )
    sessions, _meta = validate_paginated(api.list_mediation_sessions(case["id"], ADMIN))
    assert sessions[0]["recorded_by_user_id"] == USER_IDS["REUNIFICATION_SPECIALIST_THIRD"], (
        "the recording identifier is the one compared against, got "
        f"{sessions[0]['recorded_by_user_id']}"
    )


# ─── Instance: the permissive half of the same matrix ───

NORTHSIDE = {
    "name": "Northside Transitional Living",
    "licensed_bed_capacity": 3,
    "min_age_years": 16,
    "max_age_years": 20,
    "max_placement_days": 540,
}
WREN = {
    "legal_first_name": "Wren",
    "legal_last_name": "Calderon",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
MONTHLY_INCOME_CENTS = 90000


def test_one_pass_exercises_every_roles_own_exclusive_writes(api):
    """PRD §2.1: "An `OutreachWorker` is street outreach staff: this role alone intakes
    new youths and logs street-outreach encounters, and it shares the submission of
    safety screenings with a `ShelterCaseManager`."
    PRD §2.1: "A `ShelterCaseManager` is emergency-shelter staff: this role alone
    requests admissions, extends stays, discharges youths and records
    parental-notification attempts, and it shares notification resolution with a
    `ProgramAdmin` and shares education enrollment and records verification with a
    `TlpCoordinator`."
    PRD §2.1: "A `TlpCoordinator` owns transitional living exclusively: creating
    placements, posting savings entries, crediting life-skills completions and ending
    tenancies, and shares the savings-compliance review with a `ProgramAdmin`."
    PRD §2.1: "A `ProgramAdmin` licenses programs, dispositions safety screenings, closes
    governance votes, reads the federal compliance report, drives the logical clock and
    the nightly census, and may read every read endpoint in the system."
    PRD §2.1: "A `YouthMember` is a resident youth participating in program governance:
    this role alone casts and retracts governance votes, shares proposal creation with a
    `ProgramAdmin`, and has access to no other read or write endpoint whatsoever."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    shelter = license_emergency_shelter(**dict(RIVERSIDE))
    tlp = license_transitional_living(**dict(NORTHSIDE))

    youth = validate_success(api.create_youth(youth_payload(**dict(WREN)), WORKER), 201)
    contact = validate_success(
        api.create_outreach_contact(
            youth["id"],
            outreach_contact_payload(
                engagement_stage="TRUST_ESTABLISHED",
                basic_needs_provided=["FOOD", "TRANSIT_PASS"],
                indicator_flags=[],
            ),
            WORKER,
        ),
        201,
    )
    assert_outreach_contact(contact)
    screening = validate_success(
        api.create_safety_screening(
            youth["id"], safety_screening_payload(indicator_codes=[]), CASE_MANAGER
        ),
        201,
    )
    cleared = validate_success(
        api.disposition_safety_screening(
            screening["id"], screening_disposition_payload("CLEARED"), ADMIN
        )
    )
    assert cleared["status"] == "CLEARED", (
        f"the administrator's disposition is accepted, got {cleared['status']}"
    )
    admission = validate_success(
        api.create_admission(
            admission_payload(youth["id"], shelter["id"], PLANNED_DISCHARGE), CASE_MANAGER
        ),
        201,
    )
    notification = notification_of_admission(admission["id"], CASE_MANAGER)
    attempted = validate_success(
        api.record_notification_attempt(
            notification["id"], notification_attempt_payload("PHONE"), CASE_MANAGER
        )
    )
    assert attempted["status"] == "ATTEMPTED", (
        f"the case manager's attempt is accepted, got {attempted['status']}"
    )
    contacted = validate_success(
        api.resolve_notification(
            notification["id"], notification_resolve_payload("CONTACTED"), ADMIN
        )
    )
    assert contacted["status"] == "CONTACTED", (
        f"the shared resolution is accepted from the administrator, got {contacted['status']}"
    )

    resident = make_youth_member_headers(youth["id"])
    proposal = validate_success(
        api.create_governance_proposal(
            shelter["id"],
            governance_proposal_payload(
                VOTING_CLOSES_AT, title="Add a study hour", category="PROGRAMMING"
            ),
            resident,
        ),
        201,
    )
    assert_governance_proposal(proposal)
    vote = validate_success(
        api.cast_governance_vote(proposal["id"], governance_vote_payload("SUPPORT"), resident),
        201,
    )
    assert_governance_vote(vote)
    assert vote["status"] == "COUNTED", (
        f"the resident's own vote counts, got {vote['status']}"
    )
    assert vote["youth_id"] == youth["id"], (
        f"the vote is stamped with the acting header's id, got {vote['youth_id']}"
    )

    placement = validate_success(
        api.create_tlp_placement(
            tlp_placement_payload(youth["id"], tlp["id"], MONTHLY_INCOME_CENTS), COORDINATOR
        ),
        201,
    )
    assert_tlp_placement(placement)
    completion = validate_success(
        api.create_life_skills_completion(
            placement["id"], life_skills_completion_payload(6, "BUDGETING"), COORDINATOR
        ),
        201,
    )
    assert completion["credit_hours"] == 6, (
        f"the coordinator's credit is accepted, got {completion['credit_hours']}"
    )
    report = validate_success(api.get_compliance_report(shelter["id"], ADMIN))
    assert_compliance_report(report)

    enrolled = fetch_youth(youth["id"])
    assert_youth(enrolled)
    assert enrolled["status"] == "TLP_ENROLLED", (
        f"the accepted placement enrolls the youth, got {enrolled['status']}"
    )
    assert enrolled["engagement_contact_count"] == 1, (
        f"the single outreach encounter is counted, got {enrolled['engagement_contact_count']}"
    )
    credited = fetch_placement(placement["id"])
    assert credited["life_skills_credit_hours"] == 6, (
        f"the credited hours land on the placement, got {credited['life_skills_credit_hours']}"
    )
