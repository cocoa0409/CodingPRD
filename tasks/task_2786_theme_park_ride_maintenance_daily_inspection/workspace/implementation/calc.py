"""The four computed reads and the overhaul cost estimate (PRD 3.4, 3.6, 3.7,
3.9). Every intermediate is an exact rational; rounding happens only where the
PRD says it happens."""

from datetime import datetime, time, timedelta
from fractions import Fraction

import derive
import num
import store
from store import UTC

PEAK_START_HOUR = 11
PEAK_END_HOUR = 17
PEAK_WEIGHT = Fraction(1)
OFF_PEAK_WEIGHT = Fraction(55, 100)
RECOVERY_CREDIT = Fraction(85, 100)

CAPACITY_STATUSES = ("RESOLVED", "CLOSED", "OPEN", "DIAGNOSED", "AWAITING_PARTS")
PROJECTED_STATUSES = ("OPEN", "DIAGNOSED", "AWAITING_PARTS")

LABOR_RATE_CENTS_PER_HOUR = 9500
OFF_SEASON_DISCOUNT = Fraction(6, 100)

SEVERITY_BASE = {"ADVISORY": Fraction(10), "MANDATORY": Fraction(40),
                 "RECALL": Fraction(70)}
RIDE_CLASS_FACTOR = {"KIDDIE": Fraction(6, 10), "FAMILY": Fraction(8, 10),
                     "WATER": Fraction(1), "THRILL": Fraction(12, 10)}
ACTION_STATUS_FACTOR = {"PENDING": Fraction(1), "IN_WORK": Fraction(6, 10),
                        "DEFERRED": Fraction(14, 10)}
OVERDUE_POINTS_PER_DAY = Fraction(15, 10)
OVERDUE_POINTS_CAP = Fraction(30)
SCORE_CEILING = Fraction(100)
ESCALATION_STEP = Fraction(5, 100)


# ---------------------------------------------------------------------------
# minute geometry (PRD 3.4)
# ---------------------------------------------------------------------------

def _minutes(start, end):
    if end <= start:
        return 0
    return int((end - start).total_seconds() // 60)


def geometry(started_at, ended_at, service_date):
    """duration / peak / off-peak minutes of one occupancy interval."""
    duration = _minutes(started_at, ended_at)
    peak_start = datetime.combine(service_date, time(PEAK_START_HOUR, 0),
                                  tzinfo=UTC)
    peak_end = datetime.combine(service_date, time(PEAK_END_HOUR, 0),
                                tzinfo=UTC)
    peak = _minutes(max(started_at, peak_start), min(ended_at, peak_end))
    if peak > duration:
        peak = duration
    return duration, peak, duration - peak


def weighted_lost_hours(peak_minutes, off_peak_minutes):
    return (Fraction(peak_minutes, 60) * PEAK_WEIGHT
            + Fraction(off_peak_minutes, 60) * OFF_PEAK_WEIGHT)


def settled_hundredths(attraction, peak_minutes, off_peak_minutes):
    capacity = attraction["theoretical_hourly_capacity"]
    return num.hundredths(capacity * weighted_lost_hours(peak_minutes,
                                                         off_peak_minutes))


# ---------------------------------------------------------------------------
# capacity impact (PRD 3.4)
# ---------------------------------------------------------------------------

def capacity_events(attraction, window_start, window_end):
    selected = []
    for event in derive._kids("downtime_events", "attraction_id",
                              attraction["id"]):
        if event["status"] not in CAPACITY_STATUSES:
            continue
        service_date = store.date_of(event["service_date"])
        if service_date is None or service_date < window_start:
            continue
        if service_date > window_end:
            continue
        selected.append(event)
    return sorted(selected, key=lambda e: (e["service_date"], e["started_at"],
                                           e["created_at"], e["_seq"]))


def _projected_end(attraction, event):
    started = store.instant_of(event["started_at"])
    service_date = store.date_of(event["service_date"])
    projected = started + timedelta(minutes=attraction["mean_repair_minutes"])
    midnight = datetime.combine(service_date + timedelta(days=1), time(0, 0),
                                tzinfo=UTC)
    return min(projected, midnight)


def capacity_impact(attraction, window_start, window_end):
    events = capacity_events(attraction, window_start, window_end)
    capacity = attraction["theoretical_hourly_capacity"]

    settled_total = 0
    peak_sum = 0
    off_peak_sum = 0
    for event in events:
        service_date = store.date_of(event["service_date"])
        started = store.instant_of(event["started_at"])
        ended = store.instant_of(event["ended_at"])
        if ended is not None:
            stamped = event.get("_settled_hundredths")
            duration, peak, off_peak = geometry(started, ended, service_date)
            if stamped is None:
                stamped = settled_hundredths(attraction, peak, off_peak)
            settled_total += stamped
        else:
            projected = _projected_end(attraction, event)
            duration, peak, off_peak = geometry(started, projected, service_date)
        peak_sum += peak
        off_peak_sum += off_peak

    settled = num.round_half_up(Fraction(settled_total, 100), 2)
    raw = num.round_half_up(
        capacity * weighted_lost_hours(peak_sum, off_peak_sum), 2)
    provisional = num.round_half_up(raw * RECOVERY_CREDIT, 2)
    divergence = num.round_half_up(settled - provisional, 2)
    return {
        "attraction_id": attraction["id"],
        "window_start_date": window_start.isoformat(),
        "window_end_date": window_end.isoformat(),
        "event_count": len(events),
        "settled_guest_slots_lost": num.dec2(settled),
        "provisional_guest_slots_lost": num.dec2(provisional),
        "divergence_guest_slots": num.dec2(divergence),
    }


# ---------------------------------------------------------------------------
# fleet risk scoring (PRD 3.6)
# ---------------------------------------------------------------------------

def _days_overdue(bulletin):
    deadline = store.date_of(bulletin["compliance_deadline_date"])
    if deadline is None:
        return 0
    days = (store.today() - deadline).days
    return days if days > 0 else 0


def bulletin_risk(bulletin):
    actions = [a for a in derive.actions_of(bulletin["id"])
               if a["status"] in derive.EVALUATED_ACTION]

    def action_key(action):
        attraction = store.db.attractions.get(action["attraction_id"])
        return (attraction["created_at"] if attraction else "",
                attraction["_seq"] if attraction else 0)

    actions = sorted(actions, key=action_key)

    overdue_points = min(_days_overdue(bulletin) * OVERDUE_POINTS_PER_DAY,
                         OVERDUE_POINTS_CAP)
    severity_base = SEVERITY_BASE[bulletin["severity"]]

    scores = []
    deferred = 0
    for action in actions:
        attraction = store.db.attractions.get(action["attraction_id"])
        ride_class = RIDE_CLASS_FACTOR[attraction["ride_class"]]
        status_factor = ACTION_STATUS_FACTOR[action["status"]]
        if action["status"] == "DEFERRED":
            deferred += 1
        raw = severity_base * ride_class * status_factor + overdue_points
        score = num.round_half_up(raw, 2)
        if score > SCORE_CEILING:
            score = SCORE_CEILING
        scores.append(score)

    escalation = 1 + ESCALATION_STEP * deferred
    if scores:
        mean = num.round_half_up(sum(scores) / Fraction(len(scores)), 2)
        aggregate = num.round_half_up(mean * escalation, 2)
        if aggregate > SCORE_CEILING:
            aggregate = SCORE_CEILING
        per_unit_max = max(scores)
    else:
        aggregate = Fraction(0)
        per_unit_max = Fraction(0)
    divergence = num.round_half_up(per_unit_max - aggregate, 2)
    return {
        "bulletin_id": bulletin["id"],
        "evaluated_action_count": len(actions),
        "deferred_action_count": deferred,
        "escalation_factor": num.dec2(escalation),
        "fleet_aggregate_score": num.dec2(aggregate),
        "per_unit_max_score": num.dec2(per_unit_max),
        "divergence": num.dec2(divergence),
    }


# ---------------------------------------------------------------------------
# dispatch readiness (PRD 3.7)
# ---------------------------------------------------------------------------

BASE_WEIGHT = Fraction(40, 100)
RESTRAINT_WEIGHT = Fraction(60, 100)
RESTRAINT_FLOOR = Fraction(60)
RESTRAINT_SPAN = Fraction(40)
PENALTY_PER_FAIL = Fraction(8)
PENALTY_CAP = Fraction(40)


def latest_signed_off_inspection(attraction):
    candidates = derive.signed_off_inspections(attraction)
    if not candidates:
        return None
    candidates = sorted(candidates,
                        key=lambda i: (i["service_date"], i["created_at"],
                                       i["_seq"]))
    best_date = candidates[-1]["service_date"]
    for inspection in candidates:
        if inspection["service_date"] == best_date:
            return inspection
    return None


def dispatch_readiness(attraction):
    posture = derive.operational_posture(attraction)
    certified = derive.certified_certifications(attraction)
    count = len(certified)

    mean_restraint = Fraction(0)
    if certified:
        total = sum(c["restraint_verification_score"] for c in certified)
        mean_restraint = Fraction(total, count)

    inspection = latest_signed_off_inspection(attraction)
    essential_fails = (derive.essential_fail_count(inspection)
                       if inspection is not None else 0)

    if posture != "OPEN" or count == 0:
        index = Fraction(0)
    else:
        staffing = Fraction(count, attraction["min_operators_required"])
        if staffing > 1:
            staffing = Fraction(1)
        restraint_factor = (mean_restraint - RESTRAINT_FLOOR) / RESTRAINT_SPAN
        if restraint_factor < 0:
            restraint_factor = Fraction(0)
        if restraint_factor > 1:
            restraint_factor = Fraction(1)
        penalty = min(PENALTY_PER_FAIL * essential_fails, PENALTY_CAP)
        raw = (100 * staffing
               * (BASE_WEIGHT + RESTRAINT_WEIGHT * restraint_factor)) - penalty
        index = num.round_half_up(raw, 2)
        if index < 0:
            index = Fraction(0)
    return {
        "attraction_id": attraction["id"],
        "operational_posture": posture,
        "certified_operator_count": count,
        "mean_restraint_score": num.dec2(mean_restraint),
        "essential_fail_count": essential_fails,
        "dispatch_readiness_index": num.dec2(index),
    }


# ---------------------------------------------------------------------------
# overhaul cost estimate (PRD 3.9)
# ---------------------------------------------------------------------------

def is_off_season_window(window_start, window_end):
    day = window_start
    while day <= window_end:
        month_day = (day.month, day.day)
        if not (month_day >= (11, 1) or month_day <= (2, 28)):
            return False
        day = day + timedelta(days=1)
    return True


def expedite_percentage(discounted_base_cents, expedite_requested):
    if not expedite_requested:
        return Fraction(0)
    if discounted_base_cents < 5000000:
        return Fraction(12, 100)
    if discounted_base_cents < 20000000:
        return Fraction(8, 100)
    return Fraction(5, 100)


def overhaul_estimate(parts_subtotal_cents, labor_hours, window_start,
                      window_end, expedite_requested):
    labor_cost = num.cents(num.frac(labor_hours) * LABOR_RATE_CENTS_PER_HOUR)
    base_total = parts_subtotal_cents + labor_cost
    off_season = is_off_season_window(window_start, window_end)
    discount = num.cents(base_total * OFF_SEASON_DISCOUNT) if off_season else 0
    discounted_base = base_total - discount
    pct = expedite_percentage(discounted_base, expedite_requested)
    fee = num.cents(discounted_base * pct) if expedite_requested else 0
    return {
        "off_season": off_season,
        "base_total_cents": base_total,
        "off_season_discount_cents": discount,
        "discounted_base_cents": discounted_base,
        "expedite_pct": float(pct),
        "expedite_fee_cents": fee,
        "estimated_total_cents": discounted_base + fee,
    }
