"""Who may call which endpoint, whose rows they may touch, and what a stranger is told."""
from test_helpers import (
    ApiErrorId,
    HRBP_USER_ID,
    MANAGER_USER_ID,
    TEST_USERS,
    UNKNOWN_ATTENDANCE_WEEK_ID,
    UNKNOWN_CLASSIFICATION_ID,
    UNKNOWN_DESK_ASSIGNMENT_ID,
    UNKNOWN_EMPLOYEE_ID,
    UNKNOWN_ESCALATION_CASE_ID,
    UNKNOWN_EXCEPTION_REQUEST_ID,
    UNKNOWN_NEIGHBORHOOD_ID,
    UNKNOWN_POLICY_CYCLE_ID,
    UNKNOWN_RECALIBRATION_REVIEW_ID,
    UNKNOWN_RELOCATION_REQUEST_ID,
    UNKNOWN_SEAT_ALLOCATION_ID,
    UNKNOWN_SIGNAL_ID,
    UNKNOWN_TEAM_ID,
    add_signal,
    amend_payload,
    api_client,
    approve_classification_for,
    classification_decision_payload,
    create_cycle,
    create_team,
    draft_classification,
    employee_payload,
    employee_status_payload,
    exception_request_payload,
    file_exception,
    finalize,
    first_case_for,
    get_success_data,
    hold_payload,
    list_all,
    make_employee_headers,
    neighborhood_payload,
    open_week,
    pin_clock,
    policy_cycle_payload,
    posture_payload,
    read_case,
    read_cycle,
    read_employee,
    read_relocation,
    read_week,
    recalibration_review_payload,
    register_employee,
    relocation_decision_payload,
    relocation_request_payload,
    security_review_payload,
    team_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ACCOMMODATION, AUDITOR, HRBP, MANAGER, SYSTEM, WPO

STANDARD_DIALS = {
    "effective_from": "2026-09-01",
    "effective_to": "2026-12-31",
    "days_in_office_floor": 2,
    "badge_weight": 0.60,
    "network_weight": 0.40,
    "collaboration_target_score": 70.00,
    "equity_variance_threshold_pct": 20.00,
}

THREE_DAY_TEAM = {
    "expected_days_in_office_per_week": 3,
    "core_collaboration_days": ["TUE", "WED", "THU"],
    "headcount_planned": 12,
    "signal_corroboration_required": False,
}

NO_IDENTITY_EMPLOYEE = {**TEST_USERS["employee_headers"], "X-User-ID": ""}


def _refused(response, expected_status, expected_error_id):
    """Assert the refusal and that its body names no entity field at all."""
    error_data = validate_error(response, expected_error_id, expected_status)
    assert set(error_data) == {"error_id", "message"}, (
        "a refusal may not leak the row it declined to act on"
    )
    return error_data


def _a_cycle_a_team_and_one_employee(cycle_label):
    """One OPEN cycle carrying one team and one ACTIVE employee."""
    pin_clock()
    cycle = create_cycle(cycle_label=cycle_label, **STANDARD_DIALS)
    team = create_team(cycle["id"], team_code="T-A", **THREE_DAY_TEAM)
    employee = register_employee(
        team["id"], employee_number="E-1001", work_email="e1001@corp.example"
    )
    return {"cycle": cycle, "team": team, "employee": employee}


def _a_remote_worker_and_a_breaching_peer():
    """Every exclusive operation has a real, correctly-stated target in this world."""
    world = _a_cycle_a_team_and_one_employee("FY27-CRN59")
    team_id = world["team"]["id"]
    remote_worker = world["employee"]
    approve_classification_for(
        remote_worker, "FULLY_REMOTE", justification_code="TALENT_RETENTION"
    )
    relocation = get_success_data(
        api_client.create_relocation_request(
            relocation_request_payload(remote_worker["id"]), HRBP
        ),
        201,
    )
    peer = register_employee(
        team_id, employee_number="E-1002", work_email="e1002@corp.example",
        demographic_band="BAND_B",
    )
    pending = draft_classification(peer)
    get_success_data(api_client.submit_classification(pending["id"], HRBP))
    week = open_week(peer["id"], "2026-W37")
    settled = finalize(week["id"])
    case = first_case_for(peer["id"])
    return {
        "cycle": world["cycle"],
        "team": world["team"],
        "remote_worker": remote_worker,
        "relocation": relocation,
        "peer": peer,
        "pending": pending,
        "week": settled,
        "case": case,
    }


def _three_employees_on_one_team():
    """Three ACTIVE employees with no classifications, one per shared-operation writer."""
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-CRN61", **STANDARD_DIALS)
    team = create_team(cycle["id"], team_code="T-A", **THREE_DAY_TEAM)
    roster = {}
    for number, email, band in (
        ("E-A", "ea@corp.example", "BAND_A"),
        ("E-B", "eb@corp.example", "BAND_B"),
        ("E-C", "ec@corp.example", "BAND_C"),
    ):
        roster[number] = register_employee(
            team["id"], employee_number=number, work_email=email,
            demographic_band=band,
        )
    return {"cycle": cycle, "team": team, "roster": roster}


def _two_peers_each_with_a_week_and_one_request_between_them():
    """Employees E-A and E-B, a 2026-W37 week each, and one request owned by E-B."""
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-CRN62", **STANDARD_DIALS)
    team = create_team(cycle["id"], team_code="T-A", **THREE_DAY_TEAM)
    first = register_employee(
        team["id"], employee_number="E-A", work_email="ea@corp.example"
    )
    second = register_employee(
        team["id"], employee_number="E-B", work_email="eb@corp.example",
        demographic_band="BAND_B",
    )
    return {
        "cycle": cycle,
        "team": team,
        "first": first,
        "second": second,
        "first_week": open_week(first["id"], "2026-W37"),
        "second_week": open_week(second["id"], "2026-W37"),
        "second_request": file_exception(
            second["id"], requested_relief_days=1,
            start_date="2026-09-21", end_date="2026-09-21",
            rationale="filed by HR for E-B",
        ),
    }


def test_01_the_wrong_role_hears_the_same_refusal_whether_the_cycle_exists_or_not():
    """403 for the wrong role on a missing id, 404 only once the role is right.

    PRD 2.1: "Each endpoint in §4 lists the roles authorized to call it; a caller whose
    `X-User-Role` is not on that list is refused with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.1: "This role check runs **before** any resource is looked up, so an unauthorized
    caller who names a resource id that does not exist receives `ERR_UNAUTHORIZED` (403) and
    never a 404 — the API does not leak existence to callers who could not have acted
    anyway."
    PRD 2.10: "2. **Role authorization** — `ERR_UNAUTHORIZED`, ahead of every existence
    check."
    PRD 2.10: "3. **Existence** — the thirteen not-found codes of §2.5."
    PRD 2.5: "Because the role check of §2.1 runs first, none of these 404s is ever reachable
    by a caller who was not authorized in the first place."
    PRD 4: "| POST | `/policy-cycles/{cycle_id}/posture` | Moves the cycle between `OPEN`,
    `RECALIBRATING` and `LOCKED`. | WorkplaceProgramOffice |"
    PRD 3.1: "A new cycle starts in `OPEN` posture with `enrolled_team_count` at 0,
    `aggregate_compliance_rate` at 0.00 and `formal_action_total` at 0."

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_outranks_not_found
    """
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-PP4", **STANDARD_DIALS)
    assert cycle["posture"] == "OPEN"

    hidden = _refused(
        api_client.set_cycle_posture(
            UNKNOWN_POLICY_CYCLE_ID, posture_payload("LOCKED"), HRBP
        ),
        403,
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    assert hidden["error_id"] != "ERR_POLICY_CYCLE_NOT_FOUND", (
        "the wrong role learns nothing about whether that id resolves"
    )

    _refused(
        api_client.set_cycle_posture(
            UNKNOWN_POLICY_CYCLE_ID, posture_payload("LOCKED"), WPO
        ),
        404,
        ApiErrorId.ERR_POLICY_CYCLE_NOT_FOUND.value,
    )

    _refused(
        api_client.set_cycle_posture(cycle["id"], posture_payload("LOCKED"), HRBP),
        403,
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    unchanged = read_cycle(cycle["id"])
    assert unchanged["posture"] == "OPEN", "the refused posture move did nothing"
    assert unchanged["version"] == cycle["version"]


def test_02_three_more_exclusive_surfaces_answer_403_before_they_answer_404():
    """Employee status, week amendment and allocation commit all hide existence the same way.

    PRD 2.1: "This role check runs **before** any resource is looked up, so an unauthorized
    caller who names a resource id that does not exist receives `ERR_UNAUTHORIZED` (403) and
    never a 404 — the API does not leak existence to callers who could not have acted
    anyway."
    PRD 2.5: "Each entity has its own not-found code, all at HTTP 404:
    `ERR_POLICY_CYCLE_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
    `ERR_CLASSIFICATION_NOT_FOUND`, `ERR_ATTENDANCE_WEEK_NOT_FOUND`,
    `ERR_COMPLIANCE_SIGNAL_NOT_FOUND`, `ERR_EXCEPTION_REQUEST_NOT_FOUND`,
    `ERR_RELOCATION_REQUEST_NOT_FOUND`, `ERR_NEIGHBORHOOD_NOT_FOUND`,
    `ERR_SEAT_ALLOCATION_NOT_FOUND`, `ERR_DESK_ASSIGNMENT_NOT_FOUND`,
    `ERR_ESCALATION_CASE_NOT_FOUND` and `ERR_RECALIBRATION_REVIEW_NOT_FOUND`."
    PRD 4: "| POST | `/employees/{employee_id}/status` | Moves an employee between `ACTIVE`,
    `ON_LEAVE` and `SEPARATED`. | HRBusinessPartner |"
    PRD 4: "| POST | `/attendance-weeks/{week_id}/amend` | Reopens a finalized week for
    correction and withdraws its contribution to pressure. | HRBusinessPartner |"
    PRD 4: "| POST | `/seat-allocations/{allocation_id}/commit` | Commits a reserved
    allocation, charging it back and admitting it to the zone's per-week load. |
    WorkplaceProgramOffice |"
    PRD 3.2: "A freshly registered employee starts with `status` `ACTIVE`,
    `current_eligibility_class` at the `ONSITE_REQUIRED` policy default, `compliance_state`
    `COMPLIANT`, `escalation_stage` `NONE`, and `cumulative_shortfall_days`,
    `consecutive_breach_weeks`, `approved_relief_days_total` and `non_compliance_pressure`
    all at zero."

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_outranks_not_found
    """
    world = _a_cycle_a_team_and_one_employee("FY27-PP5")
    employee = world["employee"]

    _refused(
        api_client.set_employee_status(
            UNKNOWN_EMPLOYEE_ID, employee_status_payload("ON_LEAVE"), MANAGER
        ),
        403,
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    _refused(
        api_client.set_employee_status(
            UNKNOWN_EMPLOYEE_ID, employee_status_payload("ON_LEAVE"), HRBP
        ),
        404,
        ApiErrorId.ERR_EMPLOYEE_NOT_FOUND.value,
    )

    _refused(
        api_client.amend_week(
            UNKNOWN_ATTENDANCE_WEEK_ID, amend_payload("wrong role, missing week"), SYSTEM
        ),
        403,
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    _refused(
        api_client.amend_week(
            UNKNOWN_ATTENDANCE_WEEK_ID, amend_payload("right role, missing week"), HRBP
        ),
        404,
        ApiErrorId.ERR_ATTENDANCE_WEEK_NOT_FOUND.value,
    )

    _refused(
        api_client.commit_seat_allocation(UNKNOWN_SEAT_ALLOCATION_ID, AUDITOR),
        403,
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    _refused(
        api_client.commit_seat_allocation(UNKNOWN_SEAT_ALLOCATION_ID, WPO),
        404,
        ApiErrorId.ERR_SEAT_ALLOCATION_NOT_FOUND.value,
    )

    _refused(
        api_client.set_employee_status(
            employee["id"], employee_status_payload("ON_LEAVE"), MANAGER
        ),
        403,
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    untouched = read_employee(employee["id"])
    assert untouched["status"] == "ACTIVE", "the wrong role moved nobody"
    assert untouched["version"] == employee["version"]


def test_03_one_request_with_four_defects_answers_the_topmost_band_then_walks_down():
    """401 first, then 404 while the payload is still malformed, then 422, then 201.

    PRD 2.10: "Checks are grouped into precedence bands and evaluated from the top of this
    list downwards; the first band that produces a violation supplies the response, and
    later bands are never reached."
    PRD 2.10: "3. **Existence** — the thirteen not-found codes of §2.5."
    PRD 2.10: "6. **Request shape** — missing required fields, undeclared enum members and
    out-of-range numbers, all `ERR_INVALID_REQUEST`."
    PRD 2.1: "On every other endpoint, a missing or empty `X-User-ID` is refused with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.5: "Path parameters and payload foreign keys are resolved left to right, path
    segments before body fields, and the first identifier that fails to resolve determines
    the error."
    PRD 3.1: "The team declares `expected_days_in_office_per_week`, an integer from 0 through
    5 which must be at least the cycle's `days_in_office_floor`; a lower value is refused
    with `ERR_INVALID_REQUEST`."
    PRD 3.1: "Enrolling a team increments the cycle's `enrolled_team_count` by one."

    Design: Corner/validations/authentication_outranks_every_later_check_and_existence_outranks_shape
    """
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-CRN52", **STANDARD_DIALS)
    cycle_id = cycle["id"]

    def _ladder_payload(policy_cycle_id, expected_days):
        return team_payload(
            policy_cycle_id, team_code="T-LADDER",
            expected_days_in_office_per_week=expected_days,
            core_collaboration_days=["TUE"], headcount_planned=4,
            signal_corroboration_required=False,
        )

    _refused(
        api_client.create_team(
            _ladder_payload(UNKNOWN_POLICY_CYCLE_ID, 9), NO_IDENTITY_EMPLOYEE
        ),
        401,
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )
    _refused(
        api_client.create_team(_ladder_payload(UNKNOWN_POLICY_CYCLE_ID, 9), WPO),
        404,
        ApiErrorId.ERR_POLICY_CYCLE_NOT_FOUND.value,
    )
    _refused(
        api_client.create_team(_ladder_payload(cycle_id, 9), WPO),
        422,
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    enrolled = get_success_data(
        api_client.create_team(_ladder_payload(cycle_id, 3), WPO), 201
    )
    assert enrolled["team_code"] == "T-LADDER"
    assert enrolled["expected_days_in_office_per_week"] == 3

    rows, meta = list_all(api_client.list_teams, WPO, {"policy_cycle_id": cycle_id})
    assert meta["total_count"] == 1, "the three refusals enrolled nobody"
    assert [row["team_code"] for row in rows] == ["T-LADDER"]
    assert read_cycle(cycle_id)["enrolled_team_count"] == 1


def test_04_twelve_exclusive_operations_each_refuse_every_role_but_their_own():
    """A peer-structured matrix: no role's breadth anywhere buys it a write elsewhere.

    PRD 2.1: "Each endpoint in §4 lists the roles authorized to call it; a caller whose
    `X-User-Role` is not on that list is refused with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 4: "Path parameters resolve as described in §2.5, and the authorization column lists
    the only roles permitted to call each endpoint — any other role is refused with
    `ERR_UNAUTHORIZED` before the resource is looked up."
    PRD 4: "| POST | `/policy-cycles` | Opens a new hybrid-work policy cycle. |
    WorkplaceProgramOffice |"
    PRD 4: "| POST | `/policy-cycles/{cycle_id}/posture` | Moves the cycle between `OPEN`,
    `RECALIBRATING` and `LOCKED`. | WorkplaceProgramOffice |"
    PRD 4: "| POST | `/teams` | Enrolls a team in the cycle with its days-in-office
    expectation and signal-corroboration policy. | WorkplaceProgramOffice |"
    PRD 4: "| POST | `/neighborhoods` | Creates a seating neighborhood anchored to a team,
    with a desk index band whose width equals its seat count. | WorkplaceProgramOffice |"
    PRD 4: "| POST | `/recalibration-reviews` | Drafts a periodic recalibration of the
    cycle's days-in-office expectation. | WorkplaceProgramOffice |"
    PRD 4: "| POST | `/employees` | Registers an employee on a team, starting `ACTIVE` at the
    `ONSITE_REQUIRED` policy default. | HRBusinessPartner |"
    PRD 4: "| POST | `/employees/{employee_id}/status` | Moves an employee between `ACTIVE`,
    `ON_LEAVE` and `SEPARATED`. | HRBusinessPartner |"
    PRD 4: "| POST | `/attendance-weeks/{week_id}/amend` | Reopens a finalized week for
    correction and withdraws its contribution to pressure. | HRBusinessPartner |"
    PRD 4: "| POST | `/escalation-cases/{case_id}/hold` | Sets or clears the discretionary
    hold that suppresses automatic stage changes. | HRBusinessPartner |"
    PRD 4: "| POST | `/eligibility-classifications/{classification_id}/decision` | Records
    the manager decision to approve or send back for revision. | PeopleManager |"
    PRD 4: "| POST | `/remote-location-requests/{request_id}/decide` | Joins the two parallel
    review dimensions, scores the final risk and decides. | WorkplaceProgramOffice |"
    PRD 4: "| POST | `/remote-location-requests/{request_id}/security-review` | Records the
    data-security review dimension, independently of the tax dimension. | ComplianceAuditor,
    WorkplaceProgramOffice |"

    Design: Corner/rbac/every_exclusive_operation_refuses_every_other_role
    """
    world = _a_remote_worker_and_a_breaching_peer()
    cycle_id = world["cycle"]["id"]
    team_id = world["team"]["id"]
    peer_id = world["peer"]["id"]
    case = world["case"]
    relocation_id = world["relocation"]["id"]
    before = read_cycle(cycle_id)
    assert before["posture"] == "OPEN"
    assert case["stage"] == "PERFORMANCE_PLAN"
    assert case["discretionary_hold"] is False
    assert world["pending"]["state"] == "DRAFT"
    assert world["relocation"]["status"] == "SUBMITTED"
    unauthorized = ApiErrorId.ERR_UNAUTHORIZED.value

    _refused(
        api_client.create_policy_cycle(
            policy_cycle_payload(cycle_label="FY27-CRN60", **STANDARD_DIALS), HRBP
        ),
        403,
        unauthorized,
    )
    _refused(
        api_client.set_cycle_posture(
            cycle_id,
            posture_payload("RECALIBRATING", "attempted by the wrong role"),
            HRBP,
        ),
        403,
        unauthorized,
    )
    _refused(
        api_client.create_team(
            team_payload(
                cycle_id, team_code="T-X", expected_days_in_office_per_week=3,
                core_collaboration_days=["TUE"], headcount_planned=4,
                signal_corroboration_required=False,
            ),
            MANAGER,
        ),
        403,
        unauthorized,
    )
    _refused(
        api_client.create_neighborhood(
            neighborhood_payload(
                cycle_id, team_id, neighborhood_code="N-X", site_code="NYC-01",
                seat_count=4, buffer_seats=1, desk_index_from=1, desk_index_to=4,
            ),
            AUDITOR,
        ),
        403,
        unauthorized,
    )
    _refused(
        api_client.create_employee(
            employee_payload(
                team_id, MANAGER_USER_ID, HRBP_USER_ID,
                employee_number="E-9001", work_email="e9001@corp.example",
                demographic_band="BAND_C",
            ),
            WPO,
        ),
        403,
        unauthorized,
    )
    _refused(
        api_client.set_employee_status(
            peer_id,
            employee_status_payload("ON_LEAVE", "attempted by the wrong role"),
            MANAGER,
        ),
        403,
        unauthorized,
    )
    _refused(
        api_client.amend_week(
            world["week"]["id"], amend_payload("attempted by the wrong role"), SYSTEM
        ),
        403,
        unauthorized,
    )
    _refused(
        api_client.hold_case(
            case["id"], hold_payload(True, "attempted by the wrong role"), MANAGER
        ),
        403,
        unauthorized,
    )
    _refused(
        api_client.decide_classification(
            world["pending"]["id"], classification_decision_payload("APPROVE"), HRBP
        ),
        403,
        unauthorized,
    )
    _refused(
        api_client.decide_relocation(
            relocation_id, relocation_decision_payload("APPROVE"), AUDITOR
        ),
        403,
        unauthorized,
    )
    _refused(
        api_client.record_security_review(
            relocation_id, security_review_payload("CLEARED", 0), HRBP
        ),
        403,
        unauthorized,
    )
    _refused(
        api_client.create_recalibration_review(
            recalibration_review_payload(
                cycle_id, review_label="R-X", proposed_days_in_office_delta=0
            ),
            AUDITOR,
        ),
        403,
        unauthorized,
    )

    after = read_cycle(cycle_id)
    assert after["posture"] == "OPEN"
    assert after["version"] == before["version"], "not one refusal touched the cycle"
    _, team_meta = list_all(api_client.list_teams, WPO, {"policy_cycle_id": cycle_id})
    assert team_meta["total_count"] == 1
    _, zone_meta = list_all(
        api_client.list_neighborhoods, WPO, {"policy_cycle_id": cycle_id}
    )
    assert zone_meta["total_count"] == 0
    _, staff_meta = list_all(api_client.list_employees, HRBP, {"team_id": team_id})
    assert staff_meta["total_count"] == 2
    assert read_employee(peer_id)["status"] == "ACTIVE"
    assert read_week(world["week"]["id"])["status"] == "FINALIZED"
    still_held = read_case(case["id"])
    assert still_held["discretionary_hold"] is False
    assert still_held["stage"] == "PERFORMANCE_PLAN"
    assert get_success_data(
        api_client.get_classification(world["pending"]["id"], HRBP)
    )["state"] == "PENDING_MANAGER"
    assert read_relocation(relocation_id)["status"] == "SUBMITTED"


def test_05_every_role_named_on_a_shared_endpoint_really_can_call_it():
    """Three openers, two appenders, three settlers and three filers all succeed.

    PRD 4: "| POST | `/attendance-weeks` | Opens an attendance week for an employee, whose
    start date must be the Monday of the named ISO week. | SystemIntegration,
    HRBusinessPartner, PeopleManager |"
    PRD 4: "| POST | `/attendance-weeks/{week_id}/signals` | Appends one immutable compliance
    signal to an editable week. | SystemIntegration, PeopleManager |"
    PRD 4: "| POST | `/attendance-weeks/{week_id}/finalize` | Settles the week and drives the
    full non-compliance cascade. | SystemIntegration, HRBusinessPartner, PeopleManager |"
    PRD 4: "| POST | `/exception-requests` | Files an attendance exception request over a
    closed date interval. | Employee (own record only), PeopleManager, HRBusinessPartner |"
    PRD 4: "| GET | `/policy-cycles/{cycle_id}` | Reads one policy cycle including its derived
    roll-ups. | WorkplaceProgramOffice, HRBusinessPartner, PeopleManager,
    AccommodationSpecialist, ComplianceAuditor, SystemIntegration |"
    PRD 4: "| GET | `/attendance-weeks` | Lists attendance weeks, ordered by
    `week_start_date` ascending. | WorkplaceProgramOffice, HRBusinessPartner, PeopleManager,
    AccommodationSpecialist, ComplianceAuditor, SystemIntegration |"
    PRD 3.3: "The week opens in `status` `OPEN` with `required_days`, `credited_days`,
    `relief_days_credited` and `shortfall_days` all at 0, `variant_applied`,
    `amendment_reason` and `finalized_at` all null."
    PRD 3.3: "An `ONSITE_REQUIRED` employee is required for all five working days."
    PRD 3.4: "For a given date, badge evidence is satisfied when at least one signal on that
    date has source `BADGE` and at least 240 minutes present; network evidence is satisfied
    the same way with source `NETWORK`; and attestation evidence is satisfied when at least
    one signal on that date has source `MANUAL_ATTEST`, whatever its minutes."
    PRD 3.6: "At creation the server computes `interactive_process_required`, which is true
    when the `category` is `MEDICAL` or `DISABILITY_ACCOMMODATION`, and also true — whatever
    the category, `CAREGIVING` included — when the employee's
    `disability_accommodation_on_file` flag is set."

    Design: Corner/rbac/shared_operations_succeed_for_every_role_that_declares_them
    """
    world = _three_employees_on_one_team()
    roster = world["roster"]
    employee_a = roster["E-A"]
    employee_b = roster["E-B"]
    employee_c = roster["E-C"]

    week_a = open_week(employee_a["id"], "2026-W37", headers=SYSTEM)
    week_b = open_week(employee_b["id"], "2026-W37", headers=HRBP)
    week_c = open_week(employee_c["id"], "2026-W37", headers=MANAGER)
    for week in (week_a, week_b, week_c):
        assert week["status"] == "OPEN"
        assert week["credited_days"] == 0
        assert week["required_days"] == 0
        assert week["finalized_at"] is None

    by_feed = add_signal(
        week_a["id"], "2026-09-08", "BADGE", minutes_present=480, headers=SYSTEM
    )
    assert by_feed["signal_source"] == "BADGE"
    by_manager = add_signal(
        week_b["id"], "2026-09-08", "MANUAL_ATTEST", minutes_present=0, headers=MANAGER
    )
    assert by_manager["signal_source"] == "MANUAL_ATTEST"
    assert by_manager["minutes_present"] == 0

    settled_a = finalize(week_a["id"], headers=SYSTEM)
    settled_b = finalize(week_b["id"], headers=HRBP)
    settled_c = finalize(week_c["id"], headers=MANAGER)
    for settled in (settled_a, settled_b, settled_c):
        assert settled["status"] == "FINALIZED"
        assert settled["required_days"] == 5, "nobody here holds an approved classification"
        assert settled["variant_applied"] == "SIGNAL_UNION"
    assert settled_a["credited_days"] == 1, "a badge day of 480 minutes counts on its own"
    assert settled_b["credited_days"] == 1, "an attestation counts whatever its minutes"
    assert settled_c["credited_days"] == 0

    filed_by_self = file_exception(
        employee_a["id"], headers=make_employee_headers(employee_a["id"]),
        requested_relief_days=1, start_date="2026-09-21", end_date="2026-09-21",
        rationale="Filed by the employee for their own record.",
    )
    filed_by_manager = file_exception(
        employee_b["id"], headers=MANAGER,
        requested_relief_days=1, start_date="2026-09-21", end_date="2026-09-21",
        rationale="Filed by the people manager on the employee's behalf.",
    )
    filed_by_hr = file_exception(
        employee_c["id"], headers=HRBP,
        requested_relief_days=1, start_date="2026-09-21", end_date="2026-09-21",
        rationale="Filed by the HR business partner on the employee's behalf.",
    )
    for request in (filed_by_self, filed_by_manager, filed_by_hr):
        assert request["status"] == "SUBMITTED"
        assert request["category"] == "CAREGIVING"
        assert request["interactive_process_required"] is False

    readable = validate_success(
        api_client.get_policy_cycle(world["cycle"]["id"], ACCOMMODATION)
    )
    assert readable["id"] == world["cycle"]["id"]
    assert readable["posture"] == "OPEN"

    rows, meta = list_all(
        api_client.list_attendance_weeks,
        AUDITOR,
        {"employee_id": employee_a["id"], "status": "FINALIZED"},
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == week_a["id"]
    assert rows[0]["credited_days"] == 1


def test_06_an_employee_reaches_their_own_rows_and_nothing_that_belongs_to_a_peer():
    """Own row, own week and own filing all pass; three peer reads and one peer filing do not.

    PRD 2.1: "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting
    `Employee`; ownership checks on any resource that references an `Employee` compare that
    resource's `employee_id` to `X-User-ID`, and a mismatch is refused with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD 2.1: "That ownership gate guards exactly five operations: reading one employee (`GET
    /employees/{employee_id}`), filing an exception request (`POST /exception-requests`),
    filing a remote-location request (`POST /remote-location-requests`), reading one
    attendance week (`GET /attendance-weeks/{week_id}`) and reading one exception request
    (`GET /exception-requests/{request_id}`)."
    PRD 2.1: "Each endpoint in §4 lists the roles authorized to call it; a caller whose
    `X-User-Role` is not on that list is refused with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.10: "4. **Ownership** — `ERR_NOT_RESOURCE_OWNER` for an `Employee` caller reaching
    outside their own row."
    PRD 3.6: "An `Employee` may file a request for themselves — and only for themselves —
    while a `PeopleManager` or an `HRBusinessPartner` may file on anyone's behalf."
    PRD 3.6: "An employee may not hold two live requests of the same `category` whose closed
    date windows overlap: a live request being one in `SUBMITTED`, `INFO_REQUESTED` or
    `APPROVED` status, and an overlap being any pair of closed intervals sharing at least one
    date."
    PRD 3.6: "At creation the server computes `interactive_process_required`, which is true
    when the `category` is `MEDICAL` or `DISABILITY_ACCOMMODATION`, and also true — whatever
    the category, `CAREGIVING` included — when the employee's
    `disability_accommodation_on_file` flag is set."
    PRD 4: "| GET | `/employees` | Lists employees, optionally filtered, ordered by
    `employee_number` ascending. | WorkplaceProgramOffice, HRBusinessPartner, PeopleManager,
    AccommodationSpecialist, ComplianceAuditor, SystemIntegration |"

    Design: Corner/rbac/the_employee_role_is_confined_to_its_own_rows
    """
    world = _two_peers_each_with_a_week_and_one_request_between_them()
    first_id = world["first"]["id"]
    second_id = world["second"]["id"]
    acting = make_employee_headers(first_id)
    not_owner = ApiErrorId.ERR_NOT_RESOURCE_OWNER.value

    own_row = validate_success(api_client.get_employee(first_id, acting))
    assert own_row["id"] == first_id
    assert own_row["employee_number"] == "E-A"

    _refused(api_client.get_employee(second_id, acting), 403, not_owner)
    _refused(
        api_client.get_attendance_week(world["second_week"]["id"], acting),
        403,
        not_owner,
    )
    _refused(
        api_client.get_exception_request(world["second_request"]["id"], acting),
        403,
        not_owner,
    )
    _refused(
        api_client.create_exception_request(
            exception_request_payload(
                second_id, requested_relief_days=1,
                start_date="2026-09-21", end_date="2026-09-21",
                rationale="Filed by a peer, which ownership forbids.",
            ),
            acting,
        ),
        403,
        not_owner,
    )
    _refused(
        api_client.list_employees(acting, {"team_id": world["team"]["id"]}),
        403,
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    own_filing = get_success_data(
        api_client.create_exception_request(
            exception_request_payload(
                first_id, category="MEDICAL", requested_relief_days=2,
                start_date="2026-09-07", end_date="2026-09-08",
                rationale="Filed by the employee for their own record.",
            ),
            acting,
        ),
        201,
    )
    assert own_filing["employee_id"] == first_id
    assert own_filing["status"] == "SUBMITTED"
    assert own_filing["interactive_process_required"] is True
    assert validate_success(
        api_client.get_exception_request(own_filing["id"], acting)
    )["id"] == own_filing["id"]

    own_week = validate_success(
        api_client.get_attendance_week(world["first_week"]["id"], acting)
    )
    assert own_week["employee_id"] == first_id
    assert own_week["status"] == "OPEN"

    rows, meta = list_all(
        api_client.list_exception_requests, HRBP, {"employee_id": first_id}
    )
    assert meta["total_count"] == 1, "the peer filing was refused, not stored"
    assert rows[0]["id"] == own_filing["id"]


def test_07_all_thirteen_lookups_answer_with_their_own_not_found_code():
    """One authorized reader, thirteen unknown uuids, thirteen distinct 404s.

    PRD 2.5: "Each entity has its own not-found code, all at HTTP 404:
    `ERR_POLICY_CYCLE_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
    `ERR_CLASSIFICATION_NOT_FOUND`, `ERR_ATTENDANCE_WEEK_NOT_FOUND`,
    `ERR_COMPLIANCE_SIGNAL_NOT_FOUND`, `ERR_EXCEPTION_REQUEST_NOT_FOUND`,
    `ERR_RELOCATION_REQUEST_NOT_FOUND`, `ERR_NEIGHBORHOOD_NOT_FOUND`,
    `ERR_SEAT_ALLOCATION_NOT_FOUND`, `ERR_DESK_ASSIGNMENT_NOT_FOUND`,
    `ERR_ESCALATION_CASE_NOT_FOUND` and `ERR_RECALIBRATION_REVIEW_NOT_FOUND`."
    PRD 2.5: "Note that `request_id` is shared by two unrelated collections: an unresolvable
    exception-request id yields `ERR_EXCEPTION_REQUEST_NOT_FOUND` while an unresolvable
    remote-location-request id yields `ERR_RELOCATION_REQUEST_NOT_FOUND`."
    PRD 2.5: "Every entity is exposed as a peer collection at the API root, and relationships
    travel in payloads and query filters rather than in URL segments — a seat allocation
    names its `neighborhood_id` and `team_id` in its creation payload rather than hanging off
    a neighborhood's URL."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific
    error."

    Design: Corner/entities/every_entity_lookup_with_an_unknown_uuid_returns_not_found
    """
    pin_clock()
    lookups = (
        (api_client.get_policy_cycle, UNKNOWN_POLICY_CYCLE_ID,
         ApiErrorId.ERR_POLICY_CYCLE_NOT_FOUND.value),
        (api_client.get_team, UNKNOWN_TEAM_ID,
         ApiErrorId.ERR_TEAM_NOT_FOUND.value),
        (api_client.get_employee, UNKNOWN_EMPLOYEE_ID,
         ApiErrorId.ERR_EMPLOYEE_NOT_FOUND.value),
        (api_client.get_classification, UNKNOWN_CLASSIFICATION_ID,
         ApiErrorId.ERR_CLASSIFICATION_NOT_FOUND.value),
        (api_client.get_attendance_week, UNKNOWN_ATTENDANCE_WEEK_ID,
         ApiErrorId.ERR_ATTENDANCE_WEEK_NOT_FOUND.value),
        (api_client.get_compliance_signal, UNKNOWN_SIGNAL_ID,
         ApiErrorId.ERR_COMPLIANCE_SIGNAL_NOT_FOUND.value),
        (api_client.get_exception_request, UNKNOWN_EXCEPTION_REQUEST_ID,
         ApiErrorId.ERR_EXCEPTION_REQUEST_NOT_FOUND.value),
        (api_client.get_relocation_request, UNKNOWN_RELOCATION_REQUEST_ID,
         ApiErrorId.ERR_RELOCATION_REQUEST_NOT_FOUND.value),
        (api_client.get_neighborhood, UNKNOWN_NEIGHBORHOOD_ID,
         ApiErrorId.ERR_NEIGHBORHOOD_NOT_FOUND.value),
        (api_client.get_seat_allocation, UNKNOWN_SEAT_ALLOCATION_ID,
         ApiErrorId.ERR_SEAT_ALLOCATION_NOT_FOUND.value),
        (api_client.get_desk_assignment, UNKNOWN_DESK_ASSIGNMENT_ID,
         ApiErrorId.ERR_DESK_ASSIGNMENT_NOT_FOUND.value),
        (api_client.get_escalation_case, UNKNOWN_ESCALATION_CASE_ID,
         ApiErrorId.ERR_ESCALATION_CASE_NOT_FOUND.value),
        (api_client.get_recalibration_review, UNKNOWN_RECALIBRATION_REVIEW_ID,
         ApiErrorId.ERR_RECALIBRATION_REVIEW_NOT_FOUND.value),
    )
    assert len({error_id for _, _, error_id in lookups}) == 13
    assert len({unknown_id for _, unknown_id, _ in lookups}) == 13

    for lookup, unknown_id, expected_error_id in lookups:
        _refused(lookup(unknown_id, AUDITOR), 404, expected_error_id)
