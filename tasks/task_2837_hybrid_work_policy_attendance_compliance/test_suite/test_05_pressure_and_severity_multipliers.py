"""Turning settled shortfall into non-compliance pressure, a state and a ladder rung."""
from test_helpers import (
    add_signal,
    api_client,
    approve_classification_for,
    cases_for,
    create_team,
    finalize,
    first_case_for,
    list_all,
    open_week,
    read_cycle,
    read_employee,
    read_team,
    register_employee,
    setup_cycle_team_employee,
    setup_employee_with_class,
)
from test_helpers.fixtures import HRBP


def _two_multipliers_scenario():
    """Two teams, an unclassified employee and a hybrid one, each with two empty weeks."""
    base = setup_cycle_team_employee(
        cycle_overrides={"cycle_label": "FY27-PRESS", "days_in_office_floor": 2},
        team_overrides={
            "team_code": "T1-CORE",
            "expected_days_in_office_per_week": 5,
            "core_collaboration_days": ["MON", "TUE", "WED", "THU", "FRI"],
            "headcount_planned": 25,
            "signal_corroboration_required": False,
        },
        employee_overrides={"employee_number": "E-1001"},
    )
    hybrid_team = create_team(
        base["cycle"]["id"],
        team_code="T2-FIELD",
        expected_days_in_office_per_week=3,
        core_collaboration_days=["TUE", "WED", "THU"],
        headcount_planned=12,
        signal_corroboration_required=False,
    )
    hybrid_employee = register_employee(
        hybrid_team["id"], employee_number="E-2001", demographic_band="BAND_B"
    )
    hybrid_employee = approve_classification_for(hybrid_employee, "HYBRID")["employee"]
    return {
        "cycle": base["cycle"],
        "onsite_team": base["team"],
        "onsite": base["employee"],
        "hybrid_team": hybrid_team,
        "hybrid": hybrid_employee,
        "onsite_weeks": [
            open_week(base["employee"]["id"], "2026-W37"),
            open_week(base["employee"]["id"], "2026-W38"),
        ],
        "hybrid_weeks": [
            open_week(hybrid_employee["id"], "2026-W37"),
            open_week(hybrid_employee["id"], "2026-W38"),
        ],
    }


def _settle_both_empty_weeks(scenario):
    """Settle W37 then W38 for each employee, leaving every week with no evidence."""
    settled = {"onsite": [], "hybrid": []}
    for index in (0, 1):
        settled["onsite"].append(finalize(scenario["onsite_weeks"][index]["id"]))
        settled["hybrid"].append(finalize(scenario["hybrid_weeks"][index]["id"]))
    return settled


def _boundary_scenario():
    """A hybrid employee on a three-day team with three weeks of graded evidence.

    W37 carries two full badge days, W38 carries one day at exactly the minute
    floor, two full days and one day one minute short of the floor, and W39
    carries a single full badge day.
    """
    base = setup_employee_with_class(
        "HYBRID",
        cycle_overrides={"cycle_label": "FY27-BP1", "days_in_office_floor": 2},
        team_overrides={
            "team_code": "T2-HYB",
            "expected_days_in_office_per_week": 3,
            "core_collaboration_days": ["TUE", "WED", "THU"],
            "headcount_planned": 12,
            "signal_corroboration_required": False,
        },
        employee_overrides={"employee_number": "E-2001"},
    )
    employee_id = base["employee"]["id"]

    base["w37"] = open_week(employee_id, "2026-W37")
    for observed in ("2026-09-08", "2026-09-09"):
        add_signal(base["w37"]["id"], observed, "BADGE", minutes_present=480)

    base["w38"] = open_week(employee_id, "2026-W38")
    for observed, minutes in (
        ("2026-09-15", 240),
        ("2026-09-16", 480),
        ("2026-09-17", 480),
        ("2026-09-18", 239),
    ):
        add_signal(base["w38"]["id"], observed, "BADGE", minutes_present=minutes)

    base["w39"] = open_week(employee_id, "2026-W39")
    add_signal(base["w39"]["id"], "2026-09-22", "BADGE", minutes_present=480)
    return base


def test_01_an_onsite_employee_with_two_empty_weeks_is_clamped_at_the_ceiling():
    """Ten shortfall days over a two-week streak raise a raw 17.00 that is stored as 12.00.

    PRD 3.4: "**Required days** are snapshotted at each settlement from the
    employee's class at that moment."
    PRD 3.4: "An `ONSITE_REQUIRED` employee is required for all five working days."
    PRD 3.5: "**Non-compliance pressure** combines three inputs in a pinned order."
    PRD 3.5: "Take the raw shortfall — the same sum as `cumulative_shortfall_days` —
    and multiply it by the severity multiplier for the employee's current
    eligibility class: 0.0 for `FULLY_REMOTE`, 1.0 for `HYBRID`, and 1.5 for
    `ONSITE_REQUIRED`."
    PRD 3.5: "Finally clamp it to a ceiling of 12.00, so no employee's pressure
    exceeds twelve however long the shortfall runs."
    PRD 3.5: "Thereafter, every cascade that touches the employee's pressure sets
    the open case's `stage` from the pressure directly, provided
    `discretionary_hold` is false: a pressure of 10.00 or more yields `REFERRED`,
    7.00 or more yields `PERFORMANCE_PLAN`, 4.00 or more yields `WRITTEN_WARNING`,
    2.00 or more yields `COACHING`, and anything below 2.00 yields `CURED`."

    Design: Difficulty/combinatorial_formula/pressure_three_input_conditional_multiplier_with_ceiling
    """
    scenario = _two_multipliers_scenario()
    assert read_employee(scenario["onsite"]["id"])["current_eligibility_class"] == (
        "ONSITE_REQUIRED"
    ), "an unclassified employee keeps the policy default"

    settled = _settle_both_empty_weeks(scenario)
    for week in settled["onsite"]:
        assert week["required_days"] == 5, (
            "five working days are demanded even though the team expects five too"
        )
        assert week["credited_days"] == 0
        assert week["shortfall_days"] == 5

    employee = read_employee(scenario["onsite"]["id"])
    assert employee["cumulative_shortfall_days"] == 10
    assert employee["consecutive_breach_weeks"] == 2
    assert employee["non_compliance_pressure"] == 12.00, (
        "ten days at 1.5 plus a two-week streak is a raw 17.00 clamped to the ceiling"
    )
    assert employee["compliance_state"] == "BREACH"
    assert employee["escalation_stage"] == "REFERRED", (
        "a clamped 12.00 still reaches the top rung, which needs only 10.00"
    )

    case = first_case_for(scenario["onsite"]["id"])
    assert case["stage"] == "REFERRED"
    assert case["opened_pressure"] == 8.50, (
        "opened_pressure is the pressure at the instant the case opened, which was "
        "the first settlement's 5 days at 1.5 plus a one-week streak"
    )
    assert case["discretionary_hold"] is False


def test_02_the_hybrid_half_of_the_same_fixture_is_never_clamped():
    """The identical two empty weeks yield 8.00 for a hybrid employee on a three-day team.

    PRD 3.4: "A `HYBRID` employee is required for exactly their team's
    `expected_days_in_office_per_week`."
    PRD 3.5: "To that product add the breach streak multiplied by a
    consecutive-week weight of 1.0."
    PRD 3.5: "Multiply first, then add the streak term, then round, then clamp —
    any other order can produce a different number."
    PRD 3.5: "`formal_action_count` is the number holding a case in the narrower
    formal-action band of `WRITTEN_WARNING`, `PERFORMANCE_PLAN` or `REFERRED`."
    PRD 3.2: "Registration also recomputes the parent cycle's
    `aggregate_compliance_rate`, which is the count of `ACTIVE` employees on teams
    of that cycle whose `compliance_state` is `COMPLIANT`, divided by the total
    count of `ACTIVE` employees on those teams, multiplied by 100 and rounded half
    up to two decimals; when no `ACTIVE` employee exists on the cycle's teams at
    all the rate is exactly 0.00 rather than an error."

    Design: Difficulty/combinatorial_formula/pressure_three_input_conditional_multiplier_with_ceiling
    """
    scenario = _two_multipliers_scenario()
    assert scenario["hybrid"]["current_eligibility_class"] == "HYBRID"

    settled = _settle_both_empty_weeks(scenario)
    for week in settled["hybrid"]:
        assert week["required_days"] == 3, (
            "the hybrid requirement is read off the team, not off a policy constant"
        )
        assert week["shortfall_days"] == 3

    hybrid = read_employee(scenario["hybrid"]["id"])
    assert hybrid["cumulative_shortfall_days"] == 6
    assert hybrid["consecutive_breach_weeks"] == 2
    assert hybrid["non_compliance_pressure"] == 8.00, (
        "six days at 1.0 plus a two-week streak is 8.00, comfortably under the ceiling"
    )
    assert hybrid["compliance_state"] == "BREACH"
    assert hybrid["escalation_stage"] == "PERFORMANCE_PLAN", (
        "8.00 has reached 7.00 but not 10.00"
    )

    assert read_team(scenario["onsite_team"]["id"])["formal_action_count"] == 1
    assert read_team(scenario["hybrid_team"]["id"])["formal_action_count"] == 1
    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["formal_action_total"] == 2, (
        "the cycle total is the sum across both teams"
    )
    assert cycle["aggregate_compliance_rate"] == 0.00, (
        "neither of the two ACTIVE employees is COMPLIANT"
    )


def test_03_a_pressure_of_exactly_two_is_a_breach_and_opens_the_ladder_at_coaching():
    """The lower boundary is inclusive on both the state and the bottom rung.

    PRD 3.5: "`compliance_state` follows directly from the pressure: `COMPLIANT`
    when the pressure is exactly 0.00, `AT_RISK` when it is above 0.00 but strictly
    below 2.00, and `BREACH` at 2.00 or above."
    PRD 3.5: "When a cascade leaves an employee in `BREACH` and no case of theirs
    sits outside the two terminal stages, the server opens one at `COACHING`,
    records `opened_pressure` as the employee's pressure at that instant, sets
    `discretionary_hold` to false, and sets `prior_case_id` to the `id` of that
    employee's most recently created `CURED` case — ordered by `created_at`
    descending — or null when this is their first case."
    PRD 3.5: "So `COACHING → WRITTEN_WARNING` increments `formal_action_count` by
    one because the case entered the band, and the cycle's `formal_action_total` —
    the sum of `formal_action_count` across the cycle's teams — is recomputed."

    Design: Difficulty/boundary_precision_check/pressure_exactly_two_and_exactly_four_are_inclusive
    """
    scenario = _boundary_scenario()

    first = finalize(scenario["w37"]["id"])
    assert first["required_days"] == 3
    assert first["credited_days"] == 2
    assert first["shortfall_days"] == 1

    employee = read_employee(scenario["employee"]["id"])
    assert employee["cumulative_shortfall_days"] == 1
    assert employee["consecutive_breach_weeks"] == 1
    assert employee["non_compliance_pressure"] == 2.00, (
        "one day at 1.0 plus a one-week streak lands exactly on the boundary"
    )
    assert employee["compliance_state"] == "BREACH", (
        "2.00 or above is a breach, so exactly 2.00 is not AT_RISK"
    )
    assert employee["escalation_stage"] == "COACHING"

    case = first_case_for(scenario["employee"]["id"])
    assert case["stage"] == "COACHING", (
        "the bottom rung needs 2.00 and exactly 2.00 reaches it"
    )
    assert case["opened_pressure"] == 2.00
    assert case["discretionary_hold"] is False
    assert case["prior_case_id"] is None

    assert read_team(scenario["team"]["id"])["escalated_headcount"] == 1
    assert read_team(scenario["team"]["id"])["formal_action_count"] == 0, (
        "COACHING sits outside the narrower formal-action band"
    )
    assert read_cycle(scenario["cycle"]["id"])["formal_action_total"] == 0


def test_04_the_minute_floor_cures_the_case_and_exactly_four_reopens_it_one_rung_higher():
    """A 240-minute day counts, a 239-minute day does not, and 4.00 is a written warning.

    PRD 3.4: "**Credited days** are counted date by date across the week's seven
    dates, against a minute floor of four hours — a badge or network observation
    must record at least 240 minutes present to count, while a manual attestation
    counts on the strength of its existence alone and its `minutes_present` is
    ignored entirely."
    PRD 3.5: "`consecutive_breach_weeks` is the length of the current breach
    streak: walk that same settled set from the most recent `week_start_date`
    backwards, counting each week whose `shortfall_days` is greater than zero, and
    stop at the first week whose `shortfall_days` is zero."
    PRD 3.5: "Every comparison is inclusive at two decimal places, so a pressure of
    exactly 4.00 yields `WRITTEN_WARNING` while 3.99 yields `COACHING`."
    PRD 3.5: "A later breach opens a brand-new case whose `prior_case_id` points
    back at the cured one, which is how the self-referential case history is
    threaded."

    Design: Difficulty/boundary_precision_check/pressure_exactly_two_and_exactly_four_are_inclusive
    """
    scenario = _boundary_scenario()
    finalize(scenario["w37"]["id"])
    cured_case_id = first_case_for(scenario["employee"]["id"])["id"]

    second = finalize(scenario["w38"]["id"])
    assert second["credited_days"] == 3, (
        "the 240-minute day is on the floor and counts while the 239-minute day "
        "falls short"
    )
    assert second["shortfall_days"] == 0

    employee = read_employee(scenario["employee"]["id"])
    assert employee["cumulative_shortfall_days"] == 1
    assert employee["consecutive_breach_weeks"] == 0, (
        "the streak walk starts at the newest settled week and breaks immediately"
    )
    assert employee["non_compliance_pressure"] == 1.00
    assert employee["compliance_state"] == "AT_RISK", (
        "1.00 is above zero and strictly below the breach boundary"
    )
    assert employee["escalation_stage"] == "NONE"
    cured = [row for row in cases_for(scenario["employee"]["id"])
             if row["id"] == cured_case_id][0]
    assert cured["stage"] == "CURED", "one unit below the boundary reverses the ladder"

    third = finalize(scenario["w39"]["id"])
    assert third["credited_days"] == 1
    assert third["shortfall_days"] == 2

    employee = read_employee(scenario["employee"]["id"])
    assert employee["cumulative_shortfall_days"] == 3
    assert employee["consecutive_breach_weeks"] == 1
    assert employee["non_compliance_pressure"] == 4.00, (
        "three days at 1.0 plus a one-week streak lands exactly on the second rung"
    )
    assert employee["escalation_stage"] == "WRITTEN_WARNING", (
        "exactly 4.00 is a written warning and not coaching"
    )

    rows, meta = list_all(
        api_client.list_escalation_cases,
        HRBP,
        {"employee_id": scenario["employee"]["id"]},
    )
    assert meta["total_count"] == 2
    newer = [row for row in rows if row["id"] != cured_case_id][0]
    assert newer["stage"] == "WRITTEN_WARNING"
    assert newer["opened_pressure"] == 4.00
    assert newer["prior_case_id"] == cured_case_id, (
        "the second case threads back to the cured one"
    )

    assert read_team(scenario["team"]["id"])["formal_action_count"] == 1
    assert read_cycle(scenario["cycle"]["id"])["formal_action_total"] == 1


def test_05_one_empty_week_yields_three_outcomes_from_three_eligibility_classes():
    """Identical evidence, identical team, three classes, three different judgements.

    PRD 3.4: "A `FULLY_REMOTE` employee is required to be in the office 0 days."
    PRD 3.4: "A `HYBRID` employee is required for exactly their team's
    `expected_days_in_office_per_week`."
    PRD 3.4: "An `ONSITE_REQUIRED` employee is required for all five working days."
    PRD 3.3: "Every role in the company is eventually classified as one of three
    eligibility classes — `FULLY_REMOTE`, `HYBRID` or `ONSITE_REQUIRED` — and until
    a classification has been approved the employee is treated as
    `ONSITE_REQUIRED`."
    PRD 3.5: "A `FULLY_REMOTE` employee therefore accumulates pressure from the
    streak term alone, because their multiplier is zero and their required days are
    zero in the first place."
    PRD 3.5: "Because the stage is assigned in one step rather than walked, a single
    settlement, amendment or exception cascade can move a case more than one rung at
    once — `COACHING` straight to `PERFORMANCE_PLAN` when the recomputed pressure
    reaches 7.00, or `PERFORMANCE_PLAN` straight to `CURED` when it falls under
    2.00."
    PRD 3.5: "A multi-rung move is the composition of the rungs it passes through,
    and its counter effects are computed **once** from band entry and exit, never
    once per rung skipped."

    Design: Corner/calculations/required_days_and_severity_multiplier_are_keyed_on_the_eligibility_class
    """
    base = setup_cycle_team_employee(
        cycle_overrides={"cycle_label": "FY27-CRN40", "days_in_office_floor": 2},
        team_overrides={
            "team_code": "T-A",
            "expected_days_in_office_per_week": 3,
            "core_collaboration_days": ["TUE", "WED", "THU"],
            "headcount_planned": 12,
            "signal_corroboration_required": False,
        },
        employee_overrides={"employee_number": "E-REM"},
    )
    remote = approve_classification_for(
        base["employee"], "FULLY_REMOTE", justification_code="TALENT_RETENTION"
    )["employee"]
    hybrid = approve_classification_for(
        register_employee(base["team"]["id"], employee_number="E-HYB",
                          demographic_band="BAND_B"),
        "HYBRID",
    )["employee"]
    onsite = register_employee(
        base["team"]["id"], employee_number="E-ONS", demographic_band="BAND_C"
    )
    assert onsite["current_eligibility_class"] == "ONSITE_REQUIRED"

    remote_week = finalize(open_week(remote["id"], "2026-W37")["id"])
    hybrid_week = finalize(open_week(hybrid["id"], "2026-W37")["id"])
    onsite_week = finalize(open_week(onsite["id"], "2026-W37")["id"])

    assert remote_week["required_days"] == 0
    assert remote_week["credited_days"] == 0
    assert remote_week["shortfall_days"] == 0
    remote_after = read_employee(remote["id"])
    assert remote_after["non_compliance_pressure"] == 0.00, (
        "a zero multiplier over zero required days cannot accumulate pressure"
    )
    assert remote_after["consecutive_breach_weeks"] == 0
    assert remote_after["compliance_state"] == "COMPLIANT"
    assert remote_after["escalation_stage"] == "NONE"
    assert cases_for(remote["id"]) == [], (
        "a fully remote employee with no office days opens no escalation case"
    )

    assert hybrid_week["required_days"] == 3, (
        "the hybrid requirement is the team's expectation and not a constant"
    )
    assert hybrid_week["shortfall_days"] == 3
    hybrid_after = read_employee(hybrid["id"])
    assert hybrid_after["non_compliance_pressure"] == 4.00
    assert hybrid_after["compliance_state"] == "BREACH"
    assert first_case_for(hybrid["id"])["stage"] == "WRITTEN_WARNING"

    assert onsite_week["required_days"] == 5, (
        "the onsite requirement is five working days even though the team expects three"
    )
    assert onsite_week["shortfall_days"] == 5
    onsite_after = read_employee(onsite["id"])
    assert onsite_after["non_compliance_pressure"] == 8.50, (
        "five days at 1.5 plus a one-week streak is 8.50"
    )
    onsite_case = first_case_for(onsite["id"])
    assert onsite_case["stage"] == "PERFORMANCE_PLAN", (
        "the cascade jumps straight past two rungs in a single step"
    )
    assert onsite_case["opened_pressure"] == 8.50

    team = read_team(base["team"]["id"])
    assert team["escalated_headcount"] == 2
    assert team["formal_action_count"] == 2, (
        "the multi-rung jump still counts the case exactly once"
    )
    cycle = read_cycle(base["cycle"]["id"])
    assert cycle["formal_action_total"] == 2
    assert cycle["aggregate_compliance_rate"] == 33.33, (
        "one of the three ACTIVE employees is COMPLIANT"
    )
