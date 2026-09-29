"""Filing exception requests, running information rounds and closing them out."""
from test_helpers import (
    ApiErrorId,
    adjudicate_payload,
    api_client,
    exception_request_payload,
    file_exception,
    get_success_data,
    list_all,
    read_employee,
    read_exception,
    register_employee,
    request_info_payload,
    respond_info_payload,
    setup_cycle_team_employee,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ACCOMMODATION, HRBP
from test_helpers.test_users import make_employee_headers


def _interactive_request_scenario():
    """A medical request filed by the employee for the whole of the first week."""
    base = setup_cycle_team_employee(
        cycle_overrides={"cycle_label": "FY27-IPL", "days_in_office_floor": 2},
        team_overrides={
            "team_code": "T1-CORE",
            "expected_days_in_office_per_week": 5,
            "core_collaboration_days": ["MON", "TUE", "WED", "THU", "FRI"],
            "headcount_planned": 25,
            "signal_corroboration_required": False,
        },
        employee_overrides={"employee_number": "E-1001",
                            "disability_accommodation_on_file": False},
    )
    base["headers"] = make_employee_headers(base["employee"]["id"])
    base["request"] = file_exception(
        base["employee"]["id"],
        headers=base["headers"],
        category="MEDICAL",
        requested_relief_days=2,
        start_date="2026-09-07",
        end_date="2026-09-11",
        rationale="post-operative recovery, two office days per week not feasible",
    )
    return base


def _caregiving_window_scenario():
    """One employee holding a live caregiving request over the first week."""
    base = setup_cycle_team_employee(
        cycle_overrides={"cycle_label": "FY27-RT3", "days_in_office_floor": 2},
        team_overrides={
            "team_code": "T1-CORE",
            "expected_days_in_office_per_week": 3,
            "core_collaboration_days": ["TUE", "WED", "THU"],
            "headcount_planned": 12,
            "signal_corroboration_required": False,
        },
        employee_overrides={"employee_number": "E-4001",
                            "disability_accommodation_on_file": False},
    )
    base["headers"] = make_employee_headers(base["employee"]["id"])
    base["first"] = file_exception(
        base["employee"]["id"],
        headers=base["headers"],
        category="CAREGIVING",
        requested_relief_days=2,
        start_date="2026-09-07",
        end_date="2026-09-11",
        rationale="elder-care coverage for the stated window",
    )
    return base


def test_01_an_interactive_request_refuses_approval_before_any_round_has_completed():
    """The gate is the counter, not the status: a SUBMITTED row is still not approvable.

    PRD 3.6: "At creation the server computes `interactive_process_required`, which
    is true when the `category` is `MEDICAL` or `DISABILITY_ACCOMMODATION`, and also
    true — whatever the category, `CAREGIVING` included — when the employee's
    `disability_accommodation_on_file` flag is set."
    PRD 3.6: "And where the interactive process is required, an approval may not be
    recorded until at least one information round has completed — an approval while
    `info_round_count` is still 0 is refused with `ERR_INTERACTIVE_PROCESS_PENDING`
    (409)."
    PRD 3.6: "An `AccommodationSpecialist` or an `HRBusinessPartner` opens a round by
    supplying `info_needed` — the text of what is being asked for — which moves the
    request to `INFO_REQUESTED`; the request must be `SUBMITTED` for this, and any
    other status, `INFO_REQUESTED` included, is refused with
    `ERR_REQUEST_NOT_SUBMITTED` (409)."

    Design: Difficulty/non_linear_state_machine/exception_request_info_round_loop_with_gate
    """
    scenario = _interactive_request_scenario()
    request = scenario["request"]
    assert request["interactive_process_required"] is True, (
        "MEDICAL is an inherently interactive category"
    )
    assert request["status"] == "SUBMITTED"
    assert request["info_round_count"] == 0

    validate_error(
        api_client.adjudicate_exception(
            request["id"],
            adjudicate_payload("APPROVE", granted_relief_days=2),
            ACCOMMODATION,
        ),
        ApiErrorId.ERR_INTERACTIVE_PROCESS_PENDING.value,
        409,
    )
    blocked = read_exception(request["id"])
    assert blocked["status"] == "SUBMITTED"
    assert blocked["info_round_count"] == 0
    assert blocked["adjudicated_by_user_id"] is None

    opened = validate_success(
        api_client.request_exception_info(
            request["id"],
            request_info_payload("clinician note covering the requested window"),
            ACCOMMODATION,
        )
    )
    assert opened["status"] == "INFO_REQUESTED"
    assert opened["info_needed"] == "clinician note covering the requested window"
    assert opened["info_round_count"] == 0, (
        "the counter advances on the reply, not on the request"
    )

    validate_error(
        api_client.request_exception_info(
            request["id"], request_info_payload("a second round in flight"),
            ACCOMMODATION,
        ),
        ApiErrorId.ERR_REQUEST_NOT_SUBMITTED.value,
        409,
    )
    assert read_exception(request["id"])["status"] == "INFO_REQUESTED"


def test_02_two_completed_laps_leave_the_counter_at_two_and_only_the_specialist_approves():
    """The loop is unbounded, and clearing the counter gate does not clear the role gate.

    PRD 3.6: "The employee (for their own request), their manager or an
    `HRBusinessPartner` then replies with a `response_note`, which returns the request
    to `SUBMITTED` and increments `info_round_count` by one; a reply against a request
    whose status is not `INFO_REQUESTED` is refused with
    `ERR_REQUEST_NOT_INFO_REQUESTED` (409)."
    PRD 3.6: "The loop is unbounded — an accommodation conversation may take as many
    rounds as it takes, and `info_round_count` records how many completed."
    PRD 3.6: "First, only an `AccommodationSpecialist` may adjudicate such a request;
    an `HRBusinessPartner` attempting it is refused with
    `ERR_ACCOMMODATION_SPECIALIST_REQUIRED` (409), and the same restriction applies to
    opening an information round on it."
    PRD 3.6: "**Second**, because the request is now approved, the employee's
    `approved_relief_days_total` — the sum of `granted_relief_days` across their
    `APPROVED` requests — is recomputed."

    Design: Difficulty/non_linear_state_machine/exception_request_info_round_loop_with_gate
    """
    scenario = _interactive_request_scenario()
    request_id = scenario["request"]["id"]
    employee_headers = scenario["headers"]

    validate_success(
        api_client.request_exception_info(
            request_id,
            request_info_payload("clinician note covering the requested window"),
            ACCOMMODATION,
        )
    )
    first_lap = validate_success(
        api_client.respond_exception_info(
            request_id, respond_info_payload("note attached"), employee_headers
        )
    )
    assert first_lap["status"] == "SUBMITTED", "the loop returns to the intake state"
    assert first_lap["info_round_count"] == 1

    validate_success(
        api_client.request_exception_info(
            request_id,
            request_info_payload("expected duration of the restriction"),
            ACCOMMODATION,
        )
    )
    second_lap = validate_success(
        api_client.respond_exception_info(
            request_id,
            respond_info_payload("restriction expected to last six weeks"),
            employee_headers,
        )
    )
    assert second_lap["status"] == "SUBMITTED"
    assert second_lap["info_round_count"] == 2, "the same edge traversed twice"
    assert second_lap["response_note"] == "restriction expected to last six weeks"

    validate_error(
        api_client.adjudicate_exception(
            request_id, adjudicate_payload("APPROVE", granted_relief_days=2), HRBP
        ),
        ApiErrorId.ERR_ACCOMMODATION_SPECIALIST_REQUIRED.value,
        409,
    )
    assert read_exception(request_id)["status"] == "SUBMITTED"

    approved = validate_success(
        api_client.adjudicate_exception(
            request_id,
            adjudicate_payload("APPROVE", granted_relief_days=2),
            ACCOMMODATION,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["granted_relief_days"] == 2
    assert approved["adjudicated_by_user_id"] == "acc-1"
    assert approved["info_round_count"] == 2, "closing the request does not reset it"
    assert read_employee(scenario["employee"]["id"])["approved_relief_days_total"] == 2

    validate_error(
        api_client.request_exception_info(
            request_id, request_info_payload("one more question"), ACCOMMODATION
        ),
        ApiErrorId.ERR_REQUEST_NOT_SUBMITTED.value,
        409,
    )


def test_03_a_single_shared_date_collides_only_within_the_same_category():
    """The overlap key is the pair of employee and category, and one date is enough.

    PRD 3.6: "An employee may not hold two live requests of the same `category`
    whose closed date windows overlap: a live request being one in `SUBMITTED`,
    `INFO_REQUESTED` or `APPROVED` status, and an overlap being any pair of closed
    intervals sharing at least one date. Such a collision is
    `ERR_EXCEPTION_WINDOW_OVERLAP` (409)."
    PRD 2.6: "**Date intervals are closed**: an exception request's relief window,
    a desk assignment's occupancy, and an attendance week's seven-date span all
    include both endpoints."
    PRD 3.6: "At creation the server computes `interactive_process_required`, which
    is true when the `category` is `MEDICAL` or `DISABILITY_ACCOMMODATION`, and also
    true — whatever the category, `CAREGIVING` included — when the employee's
    `disability_accommodation_on_file` flag is set."

    Design: Difficulty/resource_temporal_overlap/exception_window_overlap_is_per_category_and_ignores_dead_rows
    """
    scenario = _caregiving_window_scenario()
    employee_id = scenario["employee"]["id"]
    assert scenario["first"]["status"] == "SUBMITTED", "the incumbent row is live"
    assert scenario["first"]["interactive_process_required"] is False

    validate_error(
        api_client.create_exception_request(
            exception_request_payload(
                employee_id,
                category="CAREGIVING",
                requested_relief_days=2,
                start_date="2026-09-11",
                end_date="2026-09-15",
                rationale="second caregiving window starting on the incumbent's last day",
            ),
            scenario["headers"],
        ),
        ApiErrorId.ERR_EXCEPTION_WINDOW_OVERLAP.value,
        409,
    )

    twin = get_success_data(
        api_client.create_exception_request(
            exception_request_payload(
                employee_id,
                category="MEDICAL",
                requested_relief_days=2,
                start_date="2026-09-11",
                end_date="2026-09-15",
                rationale="medical window over exactly the refused caregiving dates",
            ),
            scenario["headers"],
        )
    )
    assert twin["status"] == "SUBMITTED", (
        "the identical window under another category is not a collision at all"
    )
    assert twin["interactive_process_required"] is True

    rows, meta = list_all(
        api_client.list_exception_requests, HRBP, {"employee_id": employee_id}
    )
    assert meta["total_count"] == 2, "the refused create left no row behind"
    assert {row["category"] for row in rows} == {"CAREGIVING", "MEDICAL"}
    assert read_employee(employee_id)["approved_relief_days_total"] == 0


def test_04_a_dead_row_frees_its_window_and_abutting_dates_never_conflict():
    """Denial retires the window, and a closed interval carries no changeover buffer.

    PRD 3.6: "Requests in `DENIED`, `REVOKED` or `WITHDRAWN` status are dead and
    never conflict, so a revoked window may be re-requested."
    PRD 3.6: "A denial sets `status` to `DENIED`, stores `closure_reason` and
    `adjudicated_by_user_id`, leaves `granted_relief_days` at 0, and moves nothing
    downstream."
    PRD 3.6: "An employee may not hold two live requests of the same `category`
    whose closed date windows overlap: a live request being one in `SUBMITTED`,
    `INFO_REQUESTED` or `APPROVED` status, and an overlap being any pair of closed
    intervals sharing at least one date."
    PRD 2.3: "Unless a collection states otherwise, rows are returned in `created_at`
    ascending order."

    Design: Difficulty/resource_temporal_overlap/exception_window_overlap_is_per_category_and_ignores_dead_rows
    """
    scenario = _caregiving_window_scenario()
    employee_id = scenario["employee"]["id"]

    denied = validate_success(
        api_client.adjudicate_exception(
            scenario["first"]["id"],
            adjudicate_payload("DENY", closure_reason="Coverage arranged internally."),
            HRBP,
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["granted_relief_days"] == 0
    assert denied["closure_reason"] == "Coverage arranged internally."
    assert denied["adjudicated_by_user_id"] == "hrbp-1"

    refiled = get_success_data(
        api_client.create_exception_request(
            exception_request_payload(
                employee_id,
                category="CAREGIVING",
                requested_relief_days=2,
                start_date="2026-09-11",
                end_date="2026-09-15",
                rationale="the same window the dead row used to occupy",
            ),
            scenario["headers"],
        )
    )
    assert refiled["status"] == "SUBMITTED", (
        "the denied row no longer defends its dates"
    )

    abutting = get_success_data(
        api_client.create_exception_request(
            exception_request_payload(
                employee_id,
                category="CAREGIVING",
                requested_relief_days=2,
                start_date="2026-09-16",
                end_date="2026-09-20",
                rationale="the day after the live window closes",
            ),
            scenario["headers"],
        )
    )
    assert abutting["status"] == "SUBMITTED", (
        "touching windows share no date, and relief windows carry no buffer"
    )

    validate_error(
        api_client.create_exception_request(
            exception_request_payload(
                employee_id,
                category="CAREGIVING",
                requested_relief_days=2,
                start_date="2026-09-20",
                end_date="2026-09-24",
                rationale="starting on the final date of the abutting window",
            ),
            scenario["headers"],
        ),
        ApiErrorId.ERR_EXCEPTION_WINDOW_OVERLAP.value,
        409,
    )

    rows, meta = list_all(
        api_client.list_exception_requests,
        HRBP,
        {"employee_id": employee_id, "category": "CAREGIVING"},
    )
    assert meta["total_count"] == 3, (
        "one dead row and two live ones, and nothing from either refusal"
    )
    assert [row["id"] for row in rows] == [
        scenario["first"]["id"], refiled["id"], abutting["id"]
    ], "the collection is ordered by creation"
    assert [row["status"] for row in rows] == ["DENIED", "SUBMITTED", "SUBMITTED"]
    assert read_employee(employee_id)["approved_relief_days_total"] == 0, (
        "nothing here was ever approved"
    )


def test_05_withdrawal_is_legal_from_both_live_states_while_a_reply_is_not():
    """One decision reaches the terminal row from two different live states.

    PRD 3.6: "A denial and an approval both require the request to be `SUBMITTED`,
    whereas a withdrawal is legal from `SUBMITTED` and from `INFO_REQUESTED` alike."
    PRD 3.6: "A withdrawal sets `status` to `WITHDRAWN` and stores `closure_reason`,
    and likewise moves nothing downstream."
    PRD 3.6: "The employee (for their own request), their manager or an
    `HRBusinessPartner` then replies with a `response_note`, which returns the request
    to `SUBMITTED` and increments `info_round_count` by one; a reply against a request
    whose status is not `INFO_REQUESTED` is refused with
    `ERR_REQUEST_NOT_INFO_REQUESTED` (409)."

    Design: Corner/state_machines/exception_withdraw_is_reachable_from_both_live_states
    """
    scenario = _caregiving_window_scenario()
    employee_id = scenario["employee"]["id"]
    request_a = scenario["first"]
    request_b = file_exception(
        employee_id,
        category="CAREGIVING",
        requested_relief_days=2,
        start_date="2026-09-14",
        end_date="2026-09-18",
        rationale="a second, non-overlapping caregiving window",
    )
    assert request_b["status"] == "SUBMITTED"
    assert request_b["info_round_count"] == 0

    from_submitted = validate_success(
        api_client.adjudicate_exception(
            request_a["id"],
            adjudicate_payload("WITHDRAW", closure_reason="Filed in error."),
            HRBP,
        )
    )
    assert from_submitted["status"] == "WITHDRAWN"
    assert from_submitted["granted_relief_days"] == 0
    assert from_submitted["closure_reason"] == "Filed in error."

    validate_error(
        api_client.respond_exception_info(
            request_a["id"], respond_info_payload("detail for a closed request"), HRBP
        ),
        ApiErrorId.ERR_REQUEST_NOT_INFO_REQUESTED.value,
        409,
    )
    validate_error(
        api_client.respond_exception_info(
            request_b["id"], respond_info_payload("detail nobody asked for"), HRBP
        ),
        ApiErrorId.ERR_REQUEST_NOT_INFO_REQUESTED.value,
        409,
    )
    assert read_exception(request_b["id"])["info_round_count"] == 0, (
        "an unsolicited reply advances no counter"
    )

    asked = validate_success(
        api_client.request_exception_info(
            request_b["id"],
            request_info_payload("dates of the dependent's appointments"),
            ACCOMMODATION,
        )
    )
    assert asked["status"] == "INFO_REQUESTED"
    assert asked["info_round_count"] == 0

    from_info_requested = validate_success(
        api_client.adjudicate_exception(
            request_b["id"],
            adjudicate_payload("WITHDRAW", closure_reason="Employee no longer needs it."),
            HRBP,
        )
    )
    assert from_info_requested["status"] == "WITHDRAWN", (
        "the withdrawal edge leaves the loop state as readily as the intake state"
    )
    assert from_info_requested["granted_relief_days"] == 0
    assert from_info_requested["info_round_count"] == 0, (
        "the open round was abandoned rather than completed"
    )

    employee = read_employee(employee_id)
    assert employee["approved_relief_days_total"] == 0
    assert employee["non_compliance_pressure"] == 0.00, (
        "two withdrawn requests moved nothing downstream"
    )


def test_06_the_employee_flag_makes_an_ordinary_caregiving_request_interactive():
    """Byte-identical payloads, two employees, and only one of them needs a specialist.

    PRD 3.6: "At creation the server computes `interactive_process_required`, which
    is true when the `category` is `MEDICAL` or `DISABILITY_ACCOMMODATION`, and also
    true — whatever the category, `CAREGIVING` included — when the employee's
    `disability_accommodation_on_file` flag is set."
    PRD 3.6: "First, only an `AccommodationSpecialist` may adjudicate such a request;
    an `HRBusinessPartner` attempting it is refused with
    `ERR_ACCOMMODATION_SPECIALIST_REQUIRED` (409), and the same restriction applies to
    opening an information round on it."
    PRD 3.6: "And where the interactive process is required, an approval may not be
    recorded until at least one information round has completed — an approval while
    `info_round_count` is still 0 is refused with `ERR_INTERACTIVE_PROCESS_PENDING`
    (409)."
    PRD 3.6: "**Second**, because the request is now approved, the employee's
    `approved_relief_days_total` — the sum of `granted_relief_days` across their
    `APPROVED` requests — is recomputed."

    Design: Corner/validations/the_disability_flag_makes_an_otherwise_routine_category_interactive
    """
    base = setup_cycle_team_employee(
        cycle_overrides={"cycle_label": "FY27-CRN51", "days_in_office_floor": 2},
        team_overrides={
            "team_code": "T-A",
            "expected_days_in_office_per_week": 3,
            "core_collaboration_days": ["TUE", "WED", "THU"],
            "headcount_planned": 12,
            "signal_corroboration_required": False,
        },
        employee_overrides={"employee_number": "E-FLAG",
                            "disability_accommodation_on_file": True},
    )
    flagged = base["employee"]
    plain = register_employee(base["team"]["id"], employee_number="E-PLAIN")
    assert flagged["disability_accommodation_on_file"] is True
    assert plain["disability_accommodation_on_file"] is False, (
        "the omitted input fell back to its declared default"
    )

    identical_window = {
        "category": "CAREGIVING",
        "requested_relief_days": 2,
        "start_date": "2026-09-07",
        "end_date": "2026-09-08",
        "rationale": "eldercare coverage Monday and Tuesday",
    }
    request_flag = file_exception(flagged["id"], **identical_window)
    request_plain = file_exception(plain["id"], **identical_window)
    assert request_flag["interactive_process_required"] is True
    assert request_plain["interactive_process_required"] is False, (
        "the disjunction is decided by the employee row, not by the payload"
    )

    routine = validate_success(
        api_client.adjudicate_exception(
            request_plain["id"],
            adjudicate_payload("APPROVE", granted_relief_days=2),
            HRBP,
        )
    )
    assert routine["status"] == "APPROVED"
    assert routine["adjudicated_by_user_id"] == "hrbp-1"
    assert routine["info_round_count"] == 0, (
        "a non-interactive request is approvable with no round at all"
    )

    validate_error(
        api_client.adjudicate_exception(
            request_flag["id"],
            adjudicate_payload("APPROVE", granted_relief_days=2),
            ACCOMMODATION,
        ),
        ApiErrorId.ERR_INTERACTIVE_PROCESS_PENDING.value,
        409,
    )
    validate_success(
        api_client.request_exception_info(
            request_flag["id"],
            request_info_payload("confirmation of the accommodation plan on file"),
            ACCOMMODATION,
        )
    )
    answered = validate_success(
        api_client.respond_exception_info(
            request_flag["id"],
            respond_info_payload("plan confirmed by occupational health"),
            HRBP,
        )
    )
    assert answered["status"] == "SUBMITTED"
    assert answered["info_round_count"] == 1, (
        "with the counter gate cleared the next refusal can only be the role gate"
    )

    validate_error(
        api_client.adjudicate_exception(
            request_flag["id"],
            adjudicate_payload("APPROVE", granted_relief_days=2),
            HRBP,
        ),
        ApiErrorId.ERR_ACCOMMODATION_SPECIALIST_REQUIRED.value,
        409,
    )
    approved = validate_success(
        api_client.adjudicate_exception(
            request_flag["id"],
            adjudicate_payload("APPROVE", granted_relief_days=2),
            ACCOMMODATION,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["adjudicated_by_user_id"] == "acc-1"
    assert read_employee(flagged["id"])["approved_relief_days_total"] == 2
    assert read_employee(plain["id"])["approved_relief_days_total"] == 2
