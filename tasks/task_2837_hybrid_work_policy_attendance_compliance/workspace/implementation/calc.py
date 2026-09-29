"""Every calculation in the PRD, with the pinned constants and step order."""
import datetime
import math
from decimal import Decimal, ROUND_HALF_UP

import clock
import db

D = Decimal
ZERO = D("0.00")

# --- pinned constants ------------------------------------------------------
ONSITE_REQUIRED_DAYS = 5
MIN_PRESENCE_MINUTES = 240
SEVERITY_MULTIPLIER = {
    "FULLY_REMOTE": D("0.0"),
    "HYBRID": D("1.0"),
    "ONSITE_REQUIRED": D("1.5"),
}
CONSECUTIVE_WEIGHT = D("1.0")
PRESSURE_CEILING = D("12.00")
STAGE_REFERRED = D("10.00")
STAGE_PERFORMANCE_PLAN = D("7.00")
STAGE_WRITTEN_WARNING = D("4.00")
STAGE_COACHING = D("2.00")

JURISDICTION_BASE_RISK = {"US_CA": 10, "US_TX": 6, "US_NY": 12, "IE": 18, "IN": 26, "BR": 30}
TIER_RISK = {"PUBLIC": 0, "INTERNAL": 8, "CONFIDENTIAL": 18, "RESTRICTED": 30}
LICENSING_PENALTY_PER_GAP = 7
LICENSING_PENALTY_CAP = 21
CONTROL_PENALTY_PER_GAP = 9
CONTROL_PENALTY_CAP = 27
NEXUS_COST_PER_POINT_CENTS = 250000
NEXUS_PENALTY_CAP = 12
RISK_CEILING = 100
APPROVAL_RISK_CEILING = 60
ALLOWED_RESTRICTED_JURISDICTIONS = ("US_CA", "US_TX", "US_NY")
TAX_NEXUS_BUDGET_CENTS = 5000000

BUFFER_TIERS = [
    {"max_base": 10, "buffer_pct": D("0.20")},
    {"max_base": 25, "buffer_pct": D("0.12")},
    {"max_base": None, "buffer_pct": D("0.06")},
]

SEAT_RATE_CENTS_PER_SEAT_WEEK = 4333
DISCOUNT_BPS_BY_EXPECTED_DAYS = {5: 10000, 4: 9500, 3: 9000, 2: 8500, 1: 8500, 0: 8500}
TIGHT_UTILIZATION_PCT = D("90.00")
MIN_BAND_N = 2
CHANGEOVER_BUFFER_DAYS = 1

SETTLED_WEEK_STATUSES = ("FINALIZED", "LOCKED")
LIVE_CASE_STAGES = ("COACHING", "WRITTEN_WARNING", "PERFORMANCE_PLAN", "REFERRED")
FORMAL_ACTION_STAGES = ("WRITTEN_WARNING", "PERFORMANCE_PLAN", "REFERRED")
LADDER = ["COACHING", "WRITTEN_WARNING", "PERFORMANCE_PLAN", "REFERRED"]


def rhu(value, places=2):
    quant = D(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# current_eligibility_class
# --------------------------------------------------------------------------
def current_eligibility_class(employee):
    candidates = [c for c in db.find("eligibility_classification",
                                     employee_id=employee["id"], state="APPROVED")]
    if not candidates:
        return "ONSITE_REQUIRED"
    candidates.sort(key=lambda c: (c["effective_from"], db.seq_key(c)), reverse=True)
    return candidates[0]["requested_class"]


def approved_classifications(employee):
    return db.find("eligibility_classification", employee_id=employee["id"], state="APPROVED")


# --------------------------------------------------------------------------
# required_days_for_week
# --------------------------------------------------------------------------
def required_days_for_week(employee, team):
    klass = employee["current_eligibility_class"]
    if klass == "FULLY_REMOTE":
        return 0
    if klass == "HYBRID":
        return team["expected_days_in_office_per_week"]
    return ONSITE_REQUIRED_DAYS


# --------------------------------------------------------------------------
# credited_office_days
# --------------------------------------------------------------------------
def credited_office_days(week, team):
    variant = "SIGNAL_CORROBORATED" if team["signal_corroboration_required"] else "SIGNAL_UNION"
    signals = db.find("compliance_signal", attendance_week_id=week["id"])
    by_date = {}
    for signal in signals:
        by_date.setdefault(signal["observed_date"], []).append(signal)
    credited = 0
    for day in clock.week_dates(week["iso_week"]):
        key = day.isoformat()
        day_signals = by_date.get(key, [])
        badge_ok = any(s["signal_source"] == "BADGE" and s["minutes_present"] >= MIN_PRESENCE_MINUTES
                       for s in day_signals)
        network_ok = any(s["signal_source"] == "NETWORK" and s["minutes_present"] >= MIN_PRESENCE_MINUTES
                         for s in day_signals)
        attest_ok = any(s["signal_source"] == "MANUAL_ATTEST" for s in day_signals)
        if variant == "SIGNAL_UNION":
            counts = badge_ok or network_ok or attest_ok
        else:
            counts = (badge_ok and network_ok) or attest_ok
        if counts:
            credited += 1
    return min(credited, 5), variant


# --------------------------------------------------------------------------
# relief_days_credited
# --------------------------------------------------------------------------
def relief_days_credited(employee, week):
    week_days = clock.week_dates(week["iso_week"])
    if not week_days:
        return 0
    approved = [r for r in db.find("exception_request",
                                   employee_id=employee["id"], status="APPROVED")]
    approved.sort(key=db.seq_key)
    running = 0
    for request in approved:
        start = clock.parse_date(request["start_date"])
        end = clock.parse_date(request["end_date"])
        if start is None or end is None:
            continue
        if end < week_days[0] or start > week_days[-1]:
            continue
        eligible = 0
        for day in week_days:
            if day.weekday() <= 4 and start <= day <= end:
                eligible += 1
        running += min(request["granted_relief_days"], eligible)
    return min(running, week["required_days"])


# --------------------------------------------------------------------------
# non_compliance_pressure / compliance_state / pressure_derived_stage
# --------------------------------------------------------------------------
def settled_weeks(employee):
    return [w for w in db.find("attendance_week", employee_id=employee["id"])
            if w["status"] in SETTLED_WEEK_STATUSES]


def pressure_inputs(employee):
    weeks = settled_weeks(employee)
    raw_shortfall = sum(w["shortfall_days"] for w in weeks)
    weeks.sort(key=lambda w: (w["week_start_date"], db.seq_key(w)), reverse=True)
    streak = 0
    for week in weeks:
        if week["shortfall_days"] > 0:
            streak += 1
        else:
            break
    return raw_shortfall, streak


def non_compliance_pressure(employee):
    raw_shortfall, streak = pressure_inputs(employee)
    multiplier = SEVERITY_MULTIPLIER[employee["current_eligibility_class"]]
    pressure = rhu(D(raw_shortfall) * multiplier + D(streak) * CONSECUTIVE_WEIGHT)
    if pressure > PRESSURE_CEILING:
        pressure = PRESSURE_CEILING
    return raw_shortfall, streak, pressure


def compliance_state(pressure):
    if pressure == ZERO:
        return "COMPLIANT"
    if pressure < D("2.00"):
        return "AT_RISK"
    return "BREACH"


def pressure_derived_stage(pressure):
    if pressure >= STAGE_REFERRED:
        return "REFERRED"
    if pressure >= STAGE_PERFORMANCE_PLAN:
        return "PERFORMANCE_PLAN"
    if pressure >= STAGE_WRITTEN_WARNING:
        return "WRITTEN_WARNING"
    if pressure >= STAGE_COACHING:
        return "COACHING"
    return "CURED"


# --------------------------------------------------------------------------
# relocation_risk_score
# --------------------------------------------------------------------------
def preliminary_risk_score(jurisdiction_code, tier):
    base = JURISDICTION_BASE_RISK[jurisdiction_code] + TIER_RISK[tier]
    return min(RISK_CEILING, base)


def final_risk_score(request):
    base = (JURISDICTION_BASE_RISK[request["jurisdiction_code"]]
            + TIER_RISK[request["data_classification_tier"]])
    licensing = min(LICENSING_PENALTY_CAP,
                    LICENSING_PENALTY_PER_GAP * request["licensing_gap_count"])
    control = min(CONTROL_PENALTY_CAP,
                  CONTROL_PENALTY_PER_GAP * request["control_gap_count"])
    nexus = min(NEXUS_PENALTY_CAP,
                request["tax_nexus_registration_cost_cents"] // NEXUS_COST_PER_POINT_CENTS)
    return min(RISK_CEILING, base + licensing + control + nexus)


# --------------------------------------------------------------------------
# team_seat_entitlement
# --------------------------------------------------------------------------
def team_seat_entitlement(headcount_planned, expected_days):
    expected_daily_attendance = int(math.ceil(D(headcount_planned) * D(expected_days) / D(5)))
    base = expected_daily_attendance
    buffer_pct = BUFFER_TIERS[-1]["buffer_pct"]
    for tier in BUFFER_TIERS:
        if tier["max_base"] is None or base <= tier["max_base"]:
            buffer_pct = tier["buffer_pct"]
            break
    buffer_seats = int(math.ceil(D(base) * buffer_pct))
    return {
        "expected_daily_attendance": expected_daily_attendance,
        "base_entitlement": base,
        "buffer_seats_entitled": buffer_seats,
        "entitled_seats": base + buffer_seats,
    }


# --------------------------------------------------------------------------
# neighborhood_peak_load
# --------------------------------------------------------------------------
def cycle_week_labels(cycle):
    start = clock.parse_date(cycle["effective_from"])
    end = clock.parse_date(cycle["effective_to"])
    labels = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() == 0:
            labels.append(clock.iso_week_label(cursor))
        cursor += datetime.timedelta(days=1)
    return labels


def allocation_load(allocations, week_label):
    index = clock.week_index(week_label)
    total = 0
    for allocation in allocations:
        start = clock.week_index(allocation["window_start_week"])
        end = clock.week_index(allocation["window_end_week"])
        if start is None or end is None:
            continue
        if start <= index < end:
            total += allocation["allocated_seats"]
    return total


def neighborhood_derived(neighborhood, cycle):
    capacity = neighborhood["seat_count"] - neighborhood["buffer_seats"]
    committed = db.find("seat_allocation", neighborhood_id=neighborhood["id"], status="COMMITTED")
    labels = cycle_week_labels(cycle)
    peak = 0
    for label in labels:
        load = allocation_load(committed, label)
        if load > peak:
            peak = load
    current_label = clock.current_week_label()
    current = allocation_load(committed, current_label) if current_label in labels else 0
    if capacity > 0:
        utilization = rhu(D(100) * D(peak) / D(capacity))
    else:
        utilization = ZERO
    if cycle["posture"] == "LOCKED":
        state = "FROZEN"
    elif utilization >= TIGHT_UTILIZATION_PCT:
        state = "TIGHT"
    else:
        state = "OPEN"
    return {
        "committed_seats": current,
        "peak_committed_seats": peak,
        "utilization_pct": utilization,
        "allocation_state": state,
    }


# --------------------------------------------------------------------------
# space_chargeback_cents
# --------------------------------------------------------------------------
def weeks_in_window(start_label, end_label):
    return clock.week_index(end_label) - clock.week_index(start_label)


def allocation_line_cents(allocation, team):
    weeks = allocation["weeks_in_window"]
    bps = DISCOUNT_BPS_BY_EXPECTED_DAYS[team["expected_days_in_office_per_week"]]
    raw = (D(SEAT_RATE_CENTS_PER_SEAT_WEEK) * D(allocation["allocated_seats"])
           * D(weeks) * D(bps) / D(10000))
    return int(rhu(raw, 0))


def cycle_space_chargeback_cents(cycle):
    neighborhoods = db.find("neighborhood", policy_cycle_id=cycle["id"])
    zone_ids = set(n["id"] for n in neighborhoods)
    lines = [a for a in db.all_rows("seat_allocation")
             if a["neighborhood_id"] in zone_ids and a["status"] == "COMMITTED"]
    lines.sort(key=db.seq_key)
    return sum(line["line_chargeback_cents"] for line in lines)


# --------------------------------------------------------------------------
# collaboration_index
# --------------------------------------------------------------------------
def collaboration_index(cycle):
    teams = db.find("team", policy_cycle_id=cycle["id"])
    teams.sort(key=lambda t: t["team_code"])
    participating = []
    for team in teams:
        employees = db.find("employee", team_id=team["id"])
        weeks = []
        for employee in employees:
            weeks.extend(settled_weeks(employee))
        if weeks:
            participating.append((team, weeks))
    if not participating:
        return ZERO
    weighted_total = ZERO
    headcount_total = 0
    for team, weeks in participating:
        credited = sum(w["credited_days"] for w in weeks)
        demanded = sum(w["required_days"] for w in weeks)
        sub_score = rhu(D(100) * D(credited) / D(max(1, demanded)))
        weighted_total += sub_score * D(team["headcount_planned"])
        headcount_total += team["headcount_planned"]
    if headcount_total == 0:
        return ZERO
    return rhu(weighted_total / D(headcount_total))


# --------------------------------------------------------------------------
# equity_variance
# --------------------------------------------------------------------------
def cycle_employees(cycle):
    teams = db.find("team", policy_cycle_id=cycle["id"])
    team_ids = set(t["id"] for t in teams)
    return [e for e in db.all_rows("employee") if e["team_id"] in team_ids]


def equity_variance(cycle):
    population = [e for e in cycle_employees(cycle) if e["status"] == "ACTIVE"]
    bands = {}
    for employee in population:
        bands.setdefault(employee["demographic_band"], []).append(employee)
    qualifying = []
    for band in sorted(bands.keys()):
        members = bands[band]
        if len(members) < MIN_BAND_N:
            continue
        compliant = sum(1 for e in members if e["compliance_state"] == "COMPLIANT")
        rate = rhu(D(100) * D(compliant) / D(len(members)))
        qualifying.append((band, rate))
    count = len(qualifying)
    if count < 2:
        return count, ZERO
    rates = [rate for _, rate in qualifying]
    return count, rhu(max(rates) - min(rates))


# --------------------------------------------------------------------------
# aggregate_compliance_rate
# --------------------------------------------------------------------------
def aggregate_compliance_rate(cycle):
    population = [e for e in cycle_employees(cycle) if e["status"] == "ACTIVE"]
    if not population:
        return ZERO
    compliant = sum(1 for e in population if e["compliance_state"] == "COMPLIANT")
    return rhu(D(100) * D(compliant) / D(len(population)))


# --------------------------------------------------------------------------
# desk_selector
# --------------------------------------------------------------------------
def changeover_conflict(neighborhood_id, desk_index, start_date, end_date,
                       ignore_assignment_id=None):
    for assignment in db.all_rows("desk_assignment"):
        if assignment["status"] != "ASSIGNED":
            continue
        if assignment["id"] == ignore_assignment_id:
            continue
        if assignment["desk_index"] != desk_index:
            continue
        allocation = db.get("seat_allocation", assignment["seat_allocation_id"])
        if allocation is None or allocation["neighborhood_id"] != neighborhood_id:
            continue
        existing_start = clock.parse_date(assignment["start_date"])
        existing_end = clock.parse_date(assignment["end_date"])
        buffer = datetime.timedelta(days=CHANGEOVER_BUFFER_DAYS)
        if start_date <= existing_end + buffer and existing_start <= end_date + buffer:
            return True
    return False


def desk_candidates(employee, start_date, end_date):
    labels = clock.weeks_touched(start_date, end_date)
    indexes = [clock.week_index(label) for label in labels]
    allocations = db.find("seat_allocation", team_id=employee["team_id"], status="COMMITTED")
    candidates = []
    for allocation in allocations:
        neighborhood = db.get("neighborhood", allocation["neighborhood_id"])
        if neighborhood is None:
            continue
        if neighborhood["allocation_state"] not in ("OPEN", "TIGHT"):
            continue
        window_start = clock.week_index(allocation["window_start_week"])
        window_end = clock.week_index(allocation["window_end_week"])
        if window_start is None or window_end is None:
            continue
        if not all(window_start <= idx < window_end for idx in indexes):
            continue
        for desk_index in range(neighborhood["desk_index_from"], neighborhood["desk_index_to"] + 1):
            if changeover_conflict(neighborhood["id"], desk_index, start_date, end_date):
                continue
            candidates.append((allocation, neighborhood, desk_index))
    candidates.sort(key=lambda item: (
        0 if item[1]["anchor_team_id"] == employee["team_id"] else 1,
        item[1]["utilization_pct"],
        item[2],
        db.seq_key(item[1]),
        db.seq_key(item[0]),
    ))
    return candidates
