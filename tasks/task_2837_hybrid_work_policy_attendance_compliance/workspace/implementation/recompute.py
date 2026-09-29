"""Cascade engine: roll-ups, the escalation ladder and week recomputation."""
import clock
import calc
import db


# --------------------------------------------------------------------------
# graph helpers
# --------------------------------------------------------------------------
def team_of_employee(employee):
    return db.get("team", employee["team_id"])


def cycle_of_team(team):
    return db.get("policy_cycle", team["policy_cycle_id"])


def cycle_of_employee(employee):
    team = team_of_employee(employee)
    return cycle_of_team(team) if team else None


def employee_of_week(week):
    return db.get("employee", week["employee_id"])


def live_case(employee):
    cases = [c for c in db.find("escalation_case", employee_id=employee["id"])
             if c["stage"] in calc.LIVE_CASE_STAGES]
    cases.sort(key=db.seq_key)
    return cases[-1] if cases else None


def most_recent_cured_case(employee):
    cases = [c for c in db.find("escalation_case", employee_id=employee["id"])
             if c["stage"] == "CURED"]
    if not cases:
        return None
    cases.sort(key=db.seq_key)
    return cases[-1]


# --------------------------------------------------------------------------
# roll-ups
# --------------------------------------------------------------------------
def recompute_team_counters(team):
    if team is None:
        return
    employees = db.find("employee", team_id=team["id"])
    escalated = 0
    formal = 0
    for employee in employees:
        for case in db.find("escalation_case", employee_id=employee["id"]):
            if case["stage"] in calc.LIVE_CASE_STAGES:
                escalated += 1
            if case["stage"] in calc.FORMAL_ACTION_STAGES:
                formal += 1
    db.apply_changes(team, {"escalated_headcount": escalated, "formal_action_count": formal})


def recompute_cycle_rollups(cycle):
    if cycle is None:
        return
    teams = db.find("team", policy_cycle_id=cycle["id"])
    db.apply_changes(cycle, {
        "enrolled_team_count": len(teams),
        "formal_action_total": sum(t["formal_action_count"] for t in teams),
        "aggregate_compliance_rate": calc.aggregate_compliance_rate(cycle),
    })


def recompute_neighborhood(neighborhood, cycle=None):
    if neighborhood is None:
        return
    if cycle is None:
        cycle = db.get("policy_cycle", neighborhood["policy_cycle_id"])
    if cycle is None:
        return
    db.apply_changes(neighborhood, calc.neighborhood_derived(neighborhood, cycle))


# --------------------------------------------------------------------------
# employee settlement (LINK 2 -> LINK 6)
# --------------------------------------------------------------------------
def approved_relief_total(employee):
    approved = db.find("exception_request", employee_id=employee["id"], status="APPROVED")
    return sum(r["granted_relief_days"] for r in approved)


def settle_employee(employee, allow_case_open=True):
    """LINK 2..LINK 6: employee counters, ladder, team counters, cycle roll-ups."""
    raw_shortfall, streak, pressure = calc.non_compliance_pressure(employee)
    state = calc.compliance_state(pressure)
    db.apply_changes(employee, {
        "cumulative_shortfall_days": raw_shortfall,
        "consecutive_breach_weeks": streak,
        "approved_relief_days_total": approved_relief_total(employee),
        "non_compliance_pressure": pressure,
        "compliance_state": state,
    })
    apply_ladder(employee, pressure, state, allow_case_open=allow_case_open)
    team = team_of_employee(employee)
    recompute_team_counters(team)
    recompute_cycle_rollups(cycle_of_team(team) if team else None)


def apply_ladder(employee, pressure, state, allow_case_open=True):
    case = live_case(employee)
    if case is None:
        if state == "BREACH" and allow_case_open:
            prior = most_recent_cured_case(employee)
            case = db.insert("escalation_case", {
                "employee_id": employee["id"],
                "prior_case_id": prior["id"] if prior else None,
                "stage": "COACHING",
                "opened_pressure": pressure,
                "discretionary_hold": False,
                "last_action_by_user_id": None,
                "action_note": None,
            })
        else:
            mirror_stage(employee, None)
            return
    if not case["discretionary_hold"]:
        derived = calc.pressure_derived_stage(pressure)
        db.apply_changes(case, {"stage": derived})
    mirror_stage(employee, case)


def mirror_stage(employee, case):
    if case is not None and case["stage"] in calc.LIVE_CASE_STAGES:
        db.apply_changes(employee, {"escalation_stage": case["stage"]})
    else:
        db.apply_changes(employee, {"escalation_stage": "NONE"})


def refresh_eligibility(employee):
    db.apply_changes(employee, {"current_eligibility_class": calc.current_eligibility_class(employee)})


# --------------------------------------------------------------------------
# attendance-week recomputation
# --------------------------------------------------------------------------
def week_accounting(week, employee, team):
    """LINK 1: required_days, variant, credited_days, relief and shortfall."""
    required = calc.required_days_for_week(employee, team)
    week["required_days"] = required
    credited, variant = calc.credited_office_days(week, team)
    relief = calc.relief_days_credited(employee, dict(week, required_days=required))
    shortfall = max(0, required - credited - relief)
    return {
        "required_days": required,
        "variant_applied": variant,
        "credited_days": credited,
        "relief_days_credited": relief,
        "shortfall_days": shortfall,
    }


def recompute_relief_for_settled_weeks(employee, start_date, end_date):
    """Recompute relief + shortfall on settled weeks intersecting a relief window."""
    weeks = [w for w in db.find("attendance_week", employee_id=employee["id"])
             if w["status"] in calc.SETTLED_WEEK_STATUSES]
    affected = []
    for week in weeks:
        days = clock.week_dates(week["iso_week"])
        if not days:
            continue
        if end_date < days[0] or start_date > days[-1]:
            continue
        affected.append(week)
    affected.sort(key=lambda w: (w["week_start_date"], db.seq_key(w)))
    for week in affected:
        relief = calc.relief_days_credited(employee, week)
        shortfall = max(0, week["required_days"] - week["credited_days"] - relief)
        db.apply_changes(week, {
            "relief_days_credited": relief,
            "shortfall_days": shortfall,
        })
