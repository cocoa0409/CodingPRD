"""Opening escalation cases, walking the ladder by hand and threading case history."""
from test_helpers import (
    ApiErrorId,
    add_signal,
    amend,
    api_client,
    canonical_instant,
    cases_for,
    escalation_action_payload,
    finalize,
    first_case_for,
    list_all,
    open_and_finalize_week,
    open_week,
    read_case,
    read_cycle,
    read_employee,
    read_team,
    read_week,
    register_employee,
    set_hold,
    setup_deep_cascade_breach,
    setup_employee_with_class,
    setup_standard_breach,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import HRBP, MANAGER


def _held_case_scenario():
    """A hybrid employee one credited day into a three-day week, with a coaching case."""
    base = setup_employee_with_class(
        "HYBRID",
        cycle_overrides={"cycle_label": "FY27-CRN55", "days_in_office_floor": 2},
        team_overrides={
            "team_code": "T-A",
            "expected_days_in_office_per_week": 3,
            "core_collaboration_days": ["TUE", "WED", "THU"],
            "headcount_planned": 12,
            "signal_corroboration_required": False,
        },
        employee_overrides={"employee_number": "E-1001"},
    )
    base["w37"] = open_week(base["employee"]["id"], "2026-W37")
    add_signal(base["w37"]["id"], "2026-09-08", "BADGE", minutes_present=480)
    base["w37"] = finalize(base["w37"]["id"])
    base["case"] = first_case_for(base["employee"]["id"])
    return base


def test_01_one_settlement_writes_the_week_and_then_the_employee_roll_ups():
    """The first two links of the chain: the week's own accounting and the counters.

    PRD 3.5: "**First**, the week's own accounting is written: `status` becomes
    `FINALIZED`, `finalized_at` is stamped at the current logical instant,
    `required_days` is snapshotted, `variant_applied` records `SIGNAL_CORROBORATED`
    when the team requires corroboration and `SIGNAL_UNION` otherwise,
    `credited_days` is counted under that standard, `relief_days_credited` is
    applied from approved exceptions, and `shortfall_days` becomes the required days
    minus the credited days minus the credited relief, floored at zero so it never
    goes negative."
    PRD 3.5: "**Second**, because this week has entered the settled set, the
    employee's `cumulative_shortfall_days`, `consecutive_breach_weeks`,
    `non_compliance_pressure` and `compliance_state` are all recomputed."
    PRD 3.5: "`cumulative_shortfall_days` is the sum of `shortfall_days` across that
    employee's weeks whose `status` is `FINALIZED` or `LOCKED`."

    Design: Difficulty/transitive_cascade/finalize_week_depth_six_to_cycle_totals
    """
    scenario = setup_deep_cascade_breach()
    week = scenario["week"]
    assert week["status"] == "FINALIZED"
    assert week["variant_applied"] == "SIGNAL_UNION", (
        "the team does not require corroboration, so the union standard applies"
    )
    assert week["required_days"] == 5
    assert week["credited_days"] == 2
    assert week["relief_days_credited"] == 0
    assert week["shortfall_days"] == 3
    assert canonical_instant(week["finalized_at"]) == "2026-09-01T09:00:00Z"

    employee = scenario["employee"]
    assert employee["cumulative_shortfall_days"] == 3
    assert employee["consecutive_breach_weeks"] == 1
    assert employee["non_compliance_pressure"] == 5.50, (
        "three days at the onsite multiplier of 1.5 plus a one-week streak"
    )
    assert employee["compliance_state"] == "BREACH"
    assert read_week(week["id"])["shortfall_days"] == 3


def test_02_the_same_settlement_opens_a_case_and_reaches_the_cycle_totals():
    """Links three through six, none of which the finalize request named.

    PRD 3.5: "**Third**, if that recomputation left the employee in `BREACH` and no
    escalation case for them is currently open, a case is opened."
    PRD 3.5: "**Fourth**, the open case's stage is driven from the recomputed
    pressure."
    PRD 3.5: "**Fifth**, a stage that has entered the formal-action band changes the
    team's `formal_action_count`."
    PRD 3.5: "**Sixth**, because the team counter changed, the cycle's
    `formal_action_total` and `aggregate_compliance_rate` are recomputed."
    PRD 3.5: "`escalated_headcount` is the number of that team's employees holding a
    case whose `stage` is `COACHING`, `WRITTEN_WARNING`, `PERFORMANCE_PLAN` or
    `REFERRED`; `formal_action_count` is the number holding a case in the narrower
    formal-action band of `WRITTEN_WARNING`, `PERFORMANCE_PLAN` or `REFERRED`."

    Design: Difficulty/transitive_cascade/finalize_week_depth_six_to_cycle_totals
    """
    scenario = setup_deep_cascade_breach()
    assert scenario["cycle_before"]["aggregate_compliance_rate"] == 100.00, (
        "both employees were compliant before the settlement"
    )
    assert scenario["cycle_before"]["formal_action_total"] == 0

    cases = cases_for(scenario["employee"]["id"])
    assert len(cases) == 1, "the cascade opened exactly one case"
    case = cases[0]
    assert case["opened_pressure"] == 5.50
    assert case["discretionary_hold"] is False
    assert case["prior_case_id"] is None
    assert case["stage"] == "WRITTEN_WARNING", (
        "the stage is assigned from 5.50 in the same cascade that opened the case, "
        "so it never rests at COACHING"
    )
    assert read_employee(scenario["employee"]["id"])["escalation_stage"] == (
        "WRITTEN_WARNING"
    )

    team = scenario["team"]
    assert team["escalated_headcount"] == 1
    assert team["formal_action_count"] == 1

    cycle = scenario["cycle"]
    assert cycle["formal_action_total"] == 1
    assert cycle["aggregate_compliance_rate"] == 50.00, (
        "one of the two ACTIVE employees is still COMPLIANT"
    )

    second = scenario["second_employee"]
    assert second["compliance_state"] == "COMPLIANT"
    assert second["non_compliance_pressure"] == 0.00
    assert second["escalation_stage"] == "NONE"
    assert cases_for(second["id"]) == [], (
        "the cascade reached only the employee whose week was settled"
    )


def test_03_a_manual_lap_up_and_back_down_leaves_both_counters_where_it_found_them():
    """One rung up, one rung down, a refused step below the floor, then the lap again.

    PRD 3.5: "A manual escalation sets `discretionary_hold` to true, records
    `last_action_by_user_id` and the supplied `action_note`, mirrors the new stage
    into `escalation_stage`, and maintains the two counters exactly as the automatic
    path does."
    PRD 3.5: "De-escalating one rung — `WRITTEN_WARNING → COACHING`,
    `PERFORMANCE_PLAN → WRITTEN_WARNING` or `REFERRED → PERFORMANCE_PLAN` — is
    reserved to the employee's own `PeopleManager`, comparing the acting `X-User-ID`
    against `manager_user_id`, and anyone else is refused with `ERR_UNAUTHORIZED`
    (403); it clears `discretionary_hold` back to false and records
    `last_action_by_user_id` and `action_note`."
    PRD 3.5: "Walking back down, `WRITTEN_WARNING → COACHING` decrements
    `formal_action_count` and refreshes `formal_action_total`, while
    `PERFORMANCE_PLAN → WRITTEN_WARNING` and `REFERRED → PERFORMANCE_PLAN` change
    neither."
    PRD 3.5: "De-escalating a case already at `COACHING` is refused with
    `ERR_ESCALATION_AT_FLOOR` (409) — the only exit from the bottom rung is a cure
    driven by the relief cascade — escalating a case already at `REFERRED` is refused
    with `ERR_ESCALATION_AT_CEILING` (409), and either lever applied to a case in
    `CURED` or `CLOSED_SEPARATION` is refused with `ERR_ESCALATION_TERMINAL` (409)."

    Design: Difficulty/compensating_invariant/manual_escalate_then_deescalate_conserves_formal_action_total
    """
    scenario = _held_case_scenario()
    case_id = scenario["case"]["id"]
    team_id = scenario["team"]["id"]
    cycle_id = scenario["cycle"]["id"]

    assert scenario["case"]["stage"] == "COACHING"
    assert scenario["case"]["opened_pressure"] == 3.00
    assert scenario["case"]["discretionary_hold"] is False
    assert read_team(team_id)["formal_action_count"] == 0
    assert read_cycle(cycle_id)["formal_action_total"] == 0

    escalated = validate_success(
        api_client.escalate_case(
            case_id,
            escalation_action_payload("second missed week discussed in the 1:1"),
            HRBP,
        )
    )
    assert escalated["stage"] == "WRITTEN_WARNING"
    assert escalated["discretionary_hold"] is True, (
        "the manual lever latches the hold"
    )
    assert escalated["last_action_by_user_id"] == "hrbp-1"
    assert read_employee(scenario["employee"]["id"])["escalation_stage"] == (
        "WRITTEN_WARNING"
    )
    assert read_team(team_id)["formal_action_count"] == 1, (
        "the case entered the formal-action band"
    )
    assert read_cycle(cycle_id)["formal_action_total"] == 1

    de_escalated = validate_success(
        api_client.de_escalate_case(
            case_id,
            escalation_action_payload("attendance plan agreed, stepping back down"),
            MANAGER,
        )
    )
    assert de_escalated["stage"] == "COACHING"
    assert de_escalated["discretionary_hold"] is False, (
        "stepping down clears the hold the escalation latched"
    )
    assert de_escalated["last_action_by_user_id"] == "mgr-1"
    assert read_team(team_id)["formal_action_count"] == 0, (
        "the band exit is the exact compensation of the band entry"
    )
    assert read_cycle(cycle_id)["formal_action_total"] == 0

    validate_error(
        api_client.de_escalate_case(
            case_id,
            escalation_action_payload("attempt to step below the bottom rung"),
            MANAGER,
        ),
        ApiErrorId.ERR_ESCALATION_AT_FLOOR.value,
        409,
    )
    refused = read_case(case_id)
    assert refused["stage"] == "COACHING"
    assert refused["version"] == de_escalated["version"], (
        "the refused step wrote nothing"
    )
    assert read_team(team_id)["formal_action_count"] == 0
    assert read_cycle(cycle_id)["formal_action_total"] == 0

    second_lap = validate_success(
        api_client.escalate_case(
            case_id,
            escalation_action_payload("plan not honoured, escalating again"),
            HRBP,
        )
    )
    assert second_lap["stage"] == "WRITTEN_WARNING", (
        "the second lap reproduces the first exactly"
    )
    assert second_lap["discretionary_hold"] is True
    assert read_team(team_id)["formal_action_count"] == 1
    assert read_cycle(cycle_id)["formal_action_total"] == 1
    assert read_team(team_id)["escalated_headcount"] == 1, (
        "no move in this lap reached a terminal stage"
    )


def test_04_a_latched_hold_lets_pressure_and_stage_diverge_without_breaking_the_counters():
    """An amendment drops the pressure to zero while the held case keeps its rung.

    PRD 3.5: "While the flag is true, the pressure-derived stage assignment is
    skipped entirely for that case and cascades leave `stage` untouched — but
    pressure itself keeps accumulating on the employee, so clearing the hold later
    exposes the case to whatever stage the accumulated pressure now implies."
    PRD 3.5: "Reopening zeroes the week's `credited_days`, `relief_days_credited` and
    `shortfall_days`, so the week stops contributing to the employee's totals while
    it sits amended."
    PRD 3.5: "The employee's `cumulative_shortfall_days`,
    `consecutive_breach_weeks`, `non_compliance_pressure` and `compliance_state` are
    then recomputed downward, and the employee's open case — provided
    `discretionary_hold` is false — has its `stage` reset from the new pressure; when
    that value is `CURED` the case becomes `CURED` and `escalated_headcount`,
    `formal_action_count` and `formal_action_total` all decrement accordingly."
    PRD 3.5: "So `COACHING → WRITTEN_WARNING` increments `formal_action_count` by one
    because the case entered the band, and the cycle's `formal_action_total` — the
    sum of `formal_action_count` across the cycle's teams — is recomputed."

    Design: Difficulty/compensating_invariant/manual_escalate_then_deescalate_conserves_formal_action_total
    """
    scenario = _held_case_scenario()
    case_id = scenario["case"]["id"]
    employee_id = scenario["employee"]["id"]
    team_id = scenario["team"]["id"]
    cycle_id = scenario["cycle"]["id"]

    validate_success(
        api_client.escalate_case(
            case_id, escalation_action_payload("first formal step"), HRBP
        )
    )
    validate_success(
        api_client.de_escalate_case(
            case_id, escalation_action_payload("plan agreed"), MANAGER
        )
    )
    validate_error(
        api_client.de_escalate_case(
            case_id, escalation_action_payload("one step too far"), MANAGER
        ),
        ApiErrorId.ERR_ESCALATION_AT_FLOOR.value,
        409,
    )
    held = validate_success(
        api_client.escalate_case(
            case_id, escalation_action_payload("plan not honoured"), HRBP
        )
    )
    assert held["stage"] == "WRITTEN_WARNING"
    assert held["discretionary_hold"] is True

    amended = amend(
        scenario["w37"]["id"], "badge export for the whole week arrived late"
    )
    assert amended["status"] == "AMENDED"
    assert amended["credited_days"] == 0
    assert amended["shortfall_days"] == 0

    employee = read_employee(employee_id)
    assert employee["cumulative_shortfall_days"] == 0
    assert employee["non_compliance_pressure"] == 0.00
    assert employee["compliance_state"] == "COMPLIANT"
    assert employee["escalation_stage"] == "WRITTEN_WARNING", (
        "the held case is not re-derived, so the mirrored stage stays put"
    )

    assert read_case(case_id)["stage"] == "WRITTEN_WARNING", (
        "a compliant employee may still carry a held formal-action case"
    )
    assert read_team(team_id)["formal_action_count"] == 1, (
        "the counter identity holds even while pressure and stage disagree"
    )
    assert read_cycle(cycle_id)["formal_action_total"] == 1
    assert read_team(team_id)["escalated_headcount"] == 1


def test_05_the_manual_lever_stops_at_the_ceiling_and_a_cured_case_refuses_both_levers():
    """REFERRED is a ceiling that still steps down; CURED answers the terminal error.

    PRD 3.5: "Escalating a case one rung — `COACHING → WRITTEN_WARNING`,
    `WRITTEN_WARNING → PERFORMANCE_PLAN` or `PERFORMANCE_PLAN → REFERRED` — is
    reserved to an `HRBusinessPartner` who is **not** the employee's
    `manager_user_id`; a manager attempting to sign their own report's formal action
    is refused with `ERR_SEGREGATION_OF_DUTIES` (409), and a `PeopleManager`
    attempting the step at all is refused with `ERR_UNAUTHORIZED` (403)."
    PRD 3.5: "Unlike the cascade, both manual levers always move exactly one rung."
    PRD 3.5: "De-escalating a case already at `COACHING` is refused with
    `ERR_ESCALATION_AT_FLOOR` (409) — the only exit from the bottom rung is a cure
    driven by the relief cascade — escalating a case already at `REFERRED` is refused
    with `ERR_ESCALATION_AT_CEILING` (409), and either lever applied to a case in
    `CURED` or `CLOSED_SEPARATION` is refused with `ERR_ESCALATION_TERMINAL` (409)."
    PRD 3.5: "`WRITTEN_WARNING → PERFORMANCE_PLAN` and `PERFORMANCE_PLAN → REFERRED`
    leave both counters untouched, because the case was already inside the band."

    Design: Corner/state_machines/escalation_ladder_refuses_manual_moves_at_the_ceiling_and_in_a_terminal_stage
    """
    scenario = setup_standard_breach(
        cycle_overrides={"cycle_label": "FY27-CRN29"},
        employee_overrides={"employee_number": "E-1001"},
    )
    team_id = scenario["team"]["id"]
    cured_employee = register_employee(team_id, employee_number="E-1002",
                                       demographic_band="BAND_B")
    cured_week = open_and_finalize_week(
        cured_employee["id"], "2026-W37",
        ["2026-09-08", "2026-09-09", "2026-09-10"],
    )
    cured_case_id = first_case_for(cured_employee["id"])["id"]
    amend(cured_week["id"], "badge feed replayed for the whole week")

    live_case_id = scenario["case"]["id"]
    assert read_case(live_case_id)["stage"] == "WRITTEN_WARNING"
    assert read_case(live_case_id)["discretionary_hold"] is False
    assert read_case(cured_case_id)["stage"] == "CURED"
    assert read_team(team_id)["escalated_headcount"] == 1, (
        "the cured case withdrew its contribution"
    )
    assert read_team(team_id)["formal_action_count"] == 1

    first_step = validate_success(
        api_client.escalate_case(
            live_case_id,
            escalation_action_payload("second coaching conversation had no effect"),
            HRBP,
        )
    )
    assert first_step["stage"] == "PERFORMANCE_PLAN", "exactly one rung per call"
    assert first_step["discretionary_hold"] is True
    assert first_step["last_action_by_user_id"] == "hrbp-1"
    assert read_team(team_id)["formal_action_count"] == 1, (
        "the case was already inside the formal-action band"
    )

    second_step = validate_success(
        api_client.escalate_case(
            live_case_id,
            escalation_action_payload("performance plan milestones missed"),
            HRBP,
        )
    )
    assert second_step["stage"] == "REFERRED"
    assert read_employee(scenario["employee"]["id"])["escalation_stage"] == "REFERRED"
    assert read_team(team_id)["formal_action_count"] == 1

    validate_error(
        api_client.escalate_case(
            live_case_id,
            escalation_action_payload("attempt to push past the top rung"),
            HRBP,
        ),
        ApiErrorId.ERR_ESCALATION_AT_CEILING.value,
        409,
    )
    at_ceiling = read_case(live_case_id)
    assert at_ceiling["stage"] == "REFERRED"
    assert at_ceiling["version"] == second_step["version"], (
        "the refusal at the ceiling wrote nothing"
    )

    stepped_down = validate_success(
        api_client.de_escalate_case(
            live_case_id,
            escalation_action_payload("referral withdrawn after review"),
            MANAGER,
        )
    )
    assert stepped_down["stage"] == "PERFORMANCE_PLAN", (
        "the top rung is a ceiling, not a terminal stage"
    )
    assert stepped_down["discretionary_hold"] is False

    for lever, headers, note in (
        (api_client.escalate_case, HRBP, "attempt to reopen a cured case"),
        (api_client.de_escalate_case, MANAGER, "attempt to step a cured case down"),
    ):
        validate_error(
            lever(cured_case_id, escalation_action_payload(note), headers),
            ApiErrorId.ERR_ESCALATION_TERMINAL.value,
            409,
        )
    assert read_case(cured_case_id)["stage"] == "CURED"
    assert read_employee(cured_employee["id"])["escalation_stage"] == "NONE"


def test_06_the_cured_case_is_the_navigable_head_of_a_two_link_history():
    """A cure then a re-settlement threads a second case onto the first.

    PRD 3.5: "A later breach opens a brand-new case whose `prior_case_id` points back
    at the cured one, which is how the self-referential case history is threaded."
    PRD 3.5: "Reaching `CURED` from `COACHING` sets `escalation_stage` back to `NONE`,
    decrements `escalated_headcount` by one, and refreshes the cycle's
    `aggregate_compliance_rate`; reaching `CURED` from `WRITTEN_WARNING` does all of
    that **and** decrements `formal_action_count`, refreshing `formal_action_total` as
    well."
    PRD 3.5: "Because `FINALIZED → AMENDED → FINALIZED` is a cycle, a week may be
    corrected and re-settled any number of times."
    PRD 3.5: "Re-settlement after an amendment replays this identical chain against
    whatever signals and approved exceptions exist at that later moment."

    Design: Corner/entities/escalation_case_prior_case_chain_is_navigable_from_the_cured_row
    """
    scenario = setup_standard_breach(
        cycle_overrides={"cycle_label": "FY27-CRN12"},
        employee_overrides={"employee_number": "E-1001"},
    )
    employee_id = scenario["employee"]["id"]
    first_case_id = scenario["case"]["id"]
    assert scenario["week"]["shortfall_days"] == 2
    assert scenario["employee"]["non_compliance_pressure"] == 4.00
    assert scenario["case"]["stage"] == "WRITTEN_WARNING"
    assert scenario["case"]["prior_case_id"] is None

    amended = amend(
        scenario["week"]["id"], "badge feed for the whole week was replayed"
    )
    assert amended["status"] == "AMENDED"
    assert amended["credited_days"] == 0
    assert amended["shortfall_days"] == 0
    assert read_employee(employee_id)["non_compliance_pressure"] == 0.00
    assert read_case(first_case_id)["stage"] == "CURED"
    assert read_team(scenario["team"]["id"])["escalated_headcount"] == 0
    assert read_team(scenario["team"]["id"])["formal_action_count"] == 0
    assert read_cycle(scenario["cycle"]["id"])["formal_action_total"] == 0

    resettled = finalize(scenario["week"]["id"])
    assert resettled["credited_days"] == 3, (
        "the same three signals are re-counted on the second pass"
    )
    assert resettled["shortfall_days"] == 2
    assert read_employee(employee_id)["non_compliance_pressure"] == 4.00

    successors, successor_meta = list_all(
        api_client.list_escalation_cases, HRBP, {"prior_case_id": first_case_id}
    )
    assert successor_meta["total_count"] == 1, (
        "the re-settlement opened a new case rather than reopening the cured one"
    )
    successor = successors[0]
    assert successor["id"] != first_case_id
    assert successor["stage"] == "WRITTEN_WARNING"
    assert successor["opened_pressure"] == 4.00
    assert successor["prior_case_id"] == first_case_id

    cured_rows, cured_meta = list_all(
        api_client.list_escalation_cases,
        HRBP,
        {"employee_id": employee_id, "stage": "CURED"},
    )
    assert cured_meta["total_count"] == 1
    assert cured_rows[0]["id"] == first_case_id, (
        "the two rows of the chain are distinguishable by stage"
    )
    assert len(cases_for(employee_id)) == 2


def test_07_the_hold_endpoint_sets_one_boolean_and_realignment_waits_for_a_cascade():
    """Holding, clearing and finally re-syncing shows the deliberate two-step lag.

    PRD 3.5: "The **discretionary hold** is the third lever and belongs exclusively
    to `HRBusinessPartner`."
    PRD 3.5: "Setting or clearing the hold changes no stage and no roll-up on that
    call; it records `last_action_by_user_id` and nothing else."
    PRD 3.5: "While the flag is true, the pressure-derived stage assignment is skipped
    entirely for that case and cascades leave `stage` untouched — but pressure itself
    keeps accumulating on the employee, so clearing the hold later exposes the case to
    whatever stage the accumulated pressure now implies."
    PRD 3.5: "Reaching `CURED` from `COACHING` sets `escalation_stage` back to `NONE`,
    decrements `escalated_headcount` by one, and refreshes the cycle's
    `aggregate_compliance_rate`; reaching `CURED` from `WRITTEN_WARNING` does all of
    that **and** decrements `formal_action_count`, refreshing `formal_action_total` as
    well."

    Design: Corner/endpoints/the_hold_endpoint_flips_one_flag_and_deliberately_moves_nothing_else
    """
    scenario = _held_case_scenario()
    case_id = scenario["case"]["id"]
    employee_id = scenario["employee"]["id"]
    team_id = scenario["team"]["id"]
    cycle_id = scenario["cycle"]["id"]

    assert scenario["w37"]["credited_days"] == 1
    assert scenario["w37"]["shortfall_days"] == 2
    assert scenario["case"]["stage"] == "COACHING"
    assert read_employee(employee_id)["non_compliance_pressure"] == 3.00

    held = set_hold(case_id, True)
    assert held["discretionary_hold"] is True
    assert held["last_action_by_user_id"] == "hrbp-1"
    assert held["stage"] == "COACHING", "the hold call declares no stage change"
    assert read_team(team_id)["escalated_headcount"] == 1
    assert read_team(team_id)["formal_action_count"] == 0

    amended = amend(scenario["w37"]["id"], "badge feed backfilled the rest of the week")
    assert amended["status"] == "AMENDED"
    assert amended["shortfall_days"] == 0
    employee = read_employee(employee_id)
    assert employee["non_compliance_pressure"] == 0.00
    assert employee["compliance_state"] == "COMPLIANT"
    assert read_case(case_id)["stage"] == "COACHING", (
        "the held case skips the pressure-derived stage assignment"
    )
    assert read_team(team_id)["escalated_headcount"] == 1, (
        "a compliant employee still counts while their case is held open"
    )

    cleared = set_hold(case_id, False)
    assert cleared["discretionary_hold"] is False
    assert cleared["stage"] == "COACHING", (
        "clearing the hold does not re-derive the stage on the same call"
    )
    assert read_team(team_id)["escalated_headcount"] == 1

    w38 = open_week(employee_id, "2026-W38")
    for observed in ("2026-09-15", "2026-09-16", "2026-09-17"):
        add_signal(w38["id"], observed, "BADGE", minutes_present=480)
    settled = finalize(w38["id"])
    assert settled["required_days"] == 3
    assert settled["credited_days"] == 3
    assert settled["shortfall_days"] == 0

    employee = read_employee(employee_id)
    assert employee["consecutive_breach_weeks"] == 0
    assert employee["non_compliance_pressure"] == 0.00
    assert read_case(case_id)["stage"] == "CURED", (
        "the next cascade over an unheld case finally re-syncs the stage"
    )
    assert employee["escalation_stage"] == "NONE"
    assert read_team(team_id)["escalated_headcount"] == 0
    assert read_cycle(cycle_id)["formal_action_total"] == 0, (
        "the case never entered the formal-action band, so no roll-up could drift"
    )
