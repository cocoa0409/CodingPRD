"""Registering employees, their declared defaults, and the employment status machine."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assign_desk,
    commit_allocation,
    create_cycle,
    create_neighborhood,
    create_team,
    employee_status_payload,
    file_exception,
    first_case_for,
    get_success_data,
    open_and_finalize_week,
    pin_clock,
    read_allocation,
    read_case,
    read_cycle,
    read_employee,
    read_neighborhood,
    read_team,
    read_week,
    register_employee,
    reserve_allocation,
    set_status,
    setup_deep_cascade_breach,
    setup_standard_breach,
    team_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import HRBP, WPO


def _separation_scenario():
    """The deep-cascade breach plus a committed neighborhood seat and one live desk.

    E-1001 carries a settled three-day shortfall, a written-warning case and desk
    7 inside a committed allocation of the team's own neighborhood; E-1002 is the
    untouched compliant half of the cycle population.
    """
    scenario = setup_deep_cascade_breach(cycle_label="FY27-SEP")
    neighborhood = create_neighborhood(
        scenario["cycle"]["id"],
        scenario["team"]["id"],
        neighborhood_code="N-A1",
        seat_count=30,
        buffer_seats=4,
    )
    allocation = reserve_allocation(
        neighborhood["id"],
        scenario["team"]["id"],
        allocated_seats=5,
        window_start_week="2026-W37",
        window_end_week="2026-W41",
    )
    allocation = commit_allocation(allocation["id"])
    scenario["neighborhood"] = read_neighborhood(neighborhood["id"])
    scenario["allocation"] = allocation
    scenario["assignment"] = assign_desk(
        allocation["id"],
        scenario["employee"]["id"],
        desk_index=7,
        start_date="2026-09-07",
        end_date="2026-09-11",
    )
    return scenario


def test_01_omitted_optional_inputs_fall_back_to_their_declared_defaults():
    """A team without the corroboration flag and an employee without the accommodation flag.

    PRD 3.1: "Finally, the optional boolean `signal_corroboration_required`
    selects the evidence standard applied to this team's employees and defaults to
    false."
    PRD 3.2: "The payload also names the two operator identifiers
    `manager_user_id` and `hr_partner_user_id`, and may carry the optional boolean
    `disability_accommodation_on_file`, which defaults to false and which — when
    true — forces the interactive process onto every exception request that
    employee ever files, whatever its category."
    PRD 3.6: "At creation the server computes `interactive_process_required`,
    which is true when the `category` is `MEDICAL` or `DISABILITY_ACCOMMODATION`,
    and also true — whatever the category, `CAREGIVING` included — when the
    employee's `disability_accommodation_on_file` flag is set."
    PRD 3.6: "The request opens in `SUBMITTED` status with `granted_relief_days`
    and `info_round_count` at 0 and `info_needed`, `response_note`,
    `closure_reason` and `adjudicated_by_user_id` all null."

    Design: Corner/entities/employee_optional_input_omitted_falls_back_to_declared_default
    """
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-DEFAULT", days_in_office_floor=2)
    bare_team = team_payload(
        cycle["id"],
        team_code="T-A",
        expected_days_in_office_per_week=3,
        headcount_planned=12,
    )
    bare_team.pop("signal_corroboration_required")
    team = validate_success(api_client.create_team(bare_team, WPO), 201)
    assert team["signal_corroboration_required"] is False, (
        "the omitted corroboration flag falls back to false"
    )

    first = register_employee(team["id"], employee_number="E-1001")
    assert first["disability_accommodation_on_file"] is False, (
        "the omitted accommodation flag falls back to false"
    )
    second = register_employee(
        team["id"], employee_number="E-1002", disability_accommodation_on_file=True
    )
    assert second["disability_accommodation_on_file"] is True

    routine = file_exception(first["id"], category="CAREGIVING")
    flagged = file_exception(second["id"], category="CAREGIVING")
    assert routine["interactive_process_required"] is False, (
        "CAREGIVING is not an inherently interactive category"
    )
    assert flagged["interactive_process_required"] is True, (
        "the same category becomes interactive for an employee with an "
        "accommodation on file"
    )
    for request in (routine, flagged):
        assert request["status"] == "SUBMITTED"
        assert request["granted_relief_days"] == 0
        assert request["info_round_count"] == 0
        assert request["closure_reason"] is None

    settled = open_and_finalize_week(
        first["id"], "2026-W37", ["2026-09-08", "2026-09-09", "2026-09-10"]
    )
    assert settled["variant_applied"] == "SIGNAL_UNION", (
        "a team that does not require corroboration settles under the union standard"
    )


def test_02_employee_system_fields_are_minted_by_the_server_and_client_input_is_ignored():
    """An employee payload that names its own id, version, status and class is overridden.

    PRD 2.4: "Ids never carry a type prefix, are never supplied by the client, and
    are never used as a ranking or tie-breaking input by any calculation in this
    specification — where a tie-break is needed, `created_at` is the tie-breaker."
    PRD 2.4: "`version` is an integer that starts at 1 when the row is created and
    increments by exactly 1 on every mutation of that row, including mutations a
    cascade performs rather than the caller."
    PRD 3.2: "A freshly registered employee starts with `status` `ACTIVE`,
    `current_eligibility_class` at the `ONSITE_REQUIRED` policy default,
    `compliance_state` `COMPLIANT`, `escalation_stage` `NONE`, and
    `cumulative_shortfall_days`, `consecutive_breach_weeks`,
    `approved_relief_days_total` and `non_compliance_pressure` all at zero."

    Design: Corner/entities/employee_system_fields_are_server_generated_and_client_input_ignored
    """
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-SYSFLD", days_in_office_floor=2)
    team = create_team(cycle["id"], team_code="T-A")
    claimed_id = "00000000-0000-4000-8000-0000000000aa"
    created = register_employee(
        team["id"],
        employee_number="E-1001",
        id=claimed_id,
        version=47,
        status="SEPARATED",
        current_eligibility_class="FULLY_REMOTE",
        non_compliance_pressure=9.99,
    )
    assert created["id"] != claimed_id, "the id is server-minted, never client-supplied"
    assert created["version"] == 1, "a freshly created row starts at version 1"
    assert created["status"] == "ACTIVE"
    assert created["current_eligibility_class"] == "ONSITE_REQUIRED"
    assert created["non_compliance_pressure"] == 0.00
    assert created["compliance_state"] == "COMPLIANT"
    assert created["escalation_stage"] == "NONE"
    assert created["cumulative_shortfall_days"] == 0
    assert created["consecutive_breach_weeks"] == 0
    assert created["approved_relief_days_total"] == 0

    stored = read_employee(created["id"])
    assert stored["id"] == created["id"]
    assert stored["version"] == 1
    assert stored["status"] == "ACTIVE"
    assert stored["current_eligibility_class"] == "ONSITE_REQUIRED"
    assert stored["non_compliance_pressure"] == 0.00


def test_03_leave_and_return_move_the_compliance_rate_while_separation_is_terminal():
    """ON_LEAVE resizes the ACTIVE denominator without closing the case; SEPARATED closes it.

    PRD 3.2: "Moving to `ON_LEAVE` or back to `ACTIVE` changes `status`, advances
    the employee's `version`, and recomputes the cycle's
    `aggregate_compliance_rate` because the `ACTIVE` denominator has changed
    size."
    PRD 3.2: "An employee on leave still has their attendance weeks settled — the
    finalize step accepts an employee whose `status` is either `ACTIVE` or
    `ON_LEAVE` — but they leave both the compliance-rate population and the equity
    population, which count `ACTIVE` employees only."
    PRD 3.2: "A target that is not reachable from the current status — including
    the current status itself and any target out of `SEPARATED` — is refused with
    `ERR_INVALID_EMPLOYEE_STATUS_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/employee_status_round_trip_recomputes_compliance_rate_and_separated_is_terminal
    """
    scenario = setup_standard_breach()
    breaching = scenario["employee"]
    register_employee(scenario["team"]["id"], employee_number="E-1002")

    assert read_cycle(scenario["cycle"]["id"])["aggregate_compliance_rate"] == 50.00, (
        "one of the two ACTIVE employees is COMPLIANT"
    )
    assert read_team(scenario["team"]["id"])["escalated_headcount"] == 1
    assert read_team(scenario["team"]["id"])["formal_action_count"] == 1

    on_leave = set_status(breaching["id"], "ON_LEAVE", "medical leave of absence")
    assert on_leave["status"] == "ON_LEAVE"
    assert read_cycle(scenario["cycle"]["id"])["aggregate_compliance_rate"] == 100.00, (
        "the only remaining ACTIVE employee is COMPLIANT"
    )
    assert read_case(scenario["case"]["id"])["stage"] == "WRITTEN_WARNING", (
        "going on leave is not a case-closing event"
    )
    assert read_team(scenario["team"]["id"])["formal_action_count"] == 1

    returned = set_status(breaching["id"], "ACTIVE")
    assert returned["status"] == "ACTIVE"
    assert read_cycle(scenario["cycle"]["id"])["aggregate_compliance_rate"] == 50.00
    assert returned["non_compliance_pressure"] == 4.00, (
        "leave does not erase an already settled week"
    )

    separated = set_status(breaching["id"], "SEPARATED", "resignation effective 2026-09-01")
    assert separated["status"] == "SEPARATED"
    assert separated["escalation_stage"] == "NONE"
    assert read_case(scenario["case"]["id"])["stage"] == "CLOSED_SEPARATION"
    team_after = read_team(scenario["team"]["id"])
    assert team_after["escalated_headcount"] == 0
    assert team_after["formal_action_count"] == 0
    cycle_after = read_cycle(scenario["cycle"]["id"])
    assert cycle_after["formal_action_total"] == 0
    assert cycle_after["aggregate_compliance_rate"] == 100.00

    for target in ("ON_LEAVE", "ACTIVE"):
        validate_error(
            api_client.set_employee_status(
                breaching["id"], employee_status_payload(target), HRBP
            ),
            ApiErrorId.ERR_INVALID_EMPLOYEE_STATUS_TRANSITION.value,
            409,
        )
    assert read_employee(breaching["id"])["version"] == separated["version"], (
        "a refused transition writes nothing, so the version does not move"
    )


def test_04_separation_fans_out_to_the_desk_and_to_the_escalation_case():
    """One status write vacates the occupied desk and closes the case for separation.

    PRD 3.2: "Beyond setting `status` to `SEPARATED` and advancing the employee's
    `version`, every desk assignment of that employee whose `status` is `ASSIGNED`
    transitions to `VACATED` with `vacated_at` stamped at the current logical
    instant; the employee's escalation case, if one exists whose `stage` is
    neither `CURED` nor `CLOSED_SEPARATION`, transitions to `CLOSED_SEPARATION`,
    which sets the employee's `escalation_stage` to `NONE` and decrements the
    team's `escalated_headcount` by one, and — when the case was sitting in
    `WRITTEN_WARNING`, `PERFORMANCE_PLAN` or `REFERRED` — also decrements the
    team's `formal_action_count` by one and therefore the cycle's
    `formal_action_total`; and the cycle's `aggregate_compliance_rate` is
    recomputed with the employee dropped from the `ACTIVE` population."

    Design: Difficulty/transitive_cascade/employee_separation_fan_out_cascade
    """
    scenario = _separation_scenario()
    assert scenario["case"]["stage"] == "WRITTEN_WARNING"
    assert scenario["assignment"]["status"] == "ASSIGNED"
    assert scenario["cycle"]["aggregate_compliance_rate"] == 50.00
    assert scenario["team"]["escalated_headcount"] == 1
    assert scenario["team"]["formal_action_count"] == 1
    assert scenario["cycle"]["formal_action_total"] == 1

    separated = set_status(
        scenario["employee"]["id"],
        "SEPARATED",
        "voluntary resignation effective 2026-09-01",
    )
    assert separated["status"] == "SEPARATED"
    assert separated["escalation_stage"] == "NONE"

    assignment = get_success_data(
        api_client.get_desk_assignment(scenario["assignment"]["id"], WPO)
    )
    assert assignment["status"] == "VACATED", (
        "the space branch of the cascade vacates the live desk assignment"
    )
    assert assignment["vacated_at"] is not None
    assert assignment["vacated_at"].startswith("2026-09-01T09:00:00"), (
        "vacated_at is stamped at the current logical instant"
    )

    case = first_case_for(scenario["employee"]["id"])
    assert case["stage"] == "CLOSED_SEPARATION", (
        "separation closes the case for separation rather than curing it"
    )
    team_after = read_team(scenario["team"]["id"])
    assert team_after["escalated_headcount"] == 0
    assert team_after["formal_action_count"] == 0
    cycle_after = read_cycle(scenario["cycle"]["id"])
    assert cycle_after["formal_action_total"] == 0
    assert cycle_after["aggregate_compliance_rate"] == 100.00, (
        "the rate rose because the separated employee left the ACTIVE population, "
        "not because any pressure changed"
    )


def test_05_separation_leaves_settled_attendance_and_committed_seats_untouched():
    """The fan-out closes the case without rewriting history or releasing seats.

    PRD 3.2: "Separation runs a wider cascade, identically from `ACTIVE` and from
    `ON_LEAVE`."
    PRD 3.8: "The same `ASSIGNED → VACATED` move happens without any caller when
    the parent allocation is released or the occupant separates."
    PRD 3.8: "It sets `status` to `VACATED`, stamps `vacated_at` at the current
    logical instant, and immediately makes that `desk_index` available again to the
    automatic selector for overlapping date ranges, subject to the changeover
    buffer."

    Design: Difficulty/transitive_cascade/employee_separation_fan_out_cascade
    """
    scenario = _separation_scenario()
    employee_before = scenario["employee"]
    assert employee_before["non_compliance_pressure"] == 5.50
    assert employee_before["cumulative_shortfall_days"] == 3

    set_status(
        employee_before["id"],
        "SEPARATED",
        "voluntary resignation effective 2026-09-01",
    )

    employee_after = read_employee(employee_before["id"])
    assert employee_after["non_compliance_pressure"] == 5.50, (
        "separation closes the case without rewriting the attendance history"
    )
    assert employee_after["cumulative_shortfall_days"] == 3

    assert read_week(scenario["week"]["id"])["status"] == "FINALIZED"

    allocation_after = read_allocation(scenario["allocation"]["id"])
    assert allocation_after["status"] == "COMMITTED"
    assert allocation_after["line_chargeback_cents"] == (
        scenario["allocation"]["line_chargeback_cents"]
    )
    neighborhood_after = read_neighborhood(scenario["neighborhood"]["id"])
    assert neighborhood_after["peak_committed_seats"] == 5, (
        "vacating an occupant does not release the seats the allocation holds"
    )

    second = read_employee(scenario["second_employee"]["id"])
    assert second["status"] == "ACTIVE"
    assert second["compliance_state"] == "COMPLIANT"
    assert second["non_compliance_pressure"] == 0.00
