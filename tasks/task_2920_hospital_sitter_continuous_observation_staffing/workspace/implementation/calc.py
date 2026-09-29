"""Derived figures and the calculation rules of PRD 3.2-3.9.

Every aggregate here is a *full recomputation* over the store, never an
incremental counter, which is what makes the conserved-quantity invariants of
PRD 2.10 exact.
"""
from datetime import timedelta
from decimal import Decimal

import db as D
from db import (
    AGE_ADJUSTMENT_POINTS,
    AGE_ADJUSTMENT_THRESHOLD_YEARS,
    ATTEMPT_EVENT_POINTS,
    ATTEMPT_WINDOW_HOURS,
    DEFAULT_INTERVAL_HOURS,
    ESCALATING_EVENT_KINDS,
    FEED_ACUITY_WEIGHTS,
    HARM_EVENT_KINDS,
    HARM_EVENT_POINTS,
    NIGHT_DIFFERENTIAL,
    NIGHT_END_HOUR_UTC,
    NIGHT_START_HOUR_UTC,
    ORDER_NON_TERMINAL,
    PENALTY_TIER_1_MIN_WEIGHT,
    PENALTY_TIER_2_MIN_WEIGHT,
    POOL_MULTIPLIER,
    RISK_CATEGORY_WEIGHTS,
    SCORE_CEILING,
    SPAN_FLOOR,
    SURCHARGE_TIERS,
    TIER_12H_MIN_SCORE,
    TIER_4H_MIN_SCORE,
    TIER_8H_MIN_SCORE,
    VIDEO_SCORE_CEILING,
    cents,
    db,
    one_dp,
    whole_minutes,
)


# ---------------------------------------------------------------------------
# Simple lookups
# ---------------------------------------------------------------------------
def unit_of_patient(patient):
    if patient is None:
        return None
    return db.units.get(patient.get("unit_id"))


def unit_of_order(order):
    if order is None:
        return None
    return unit_of_patient(db.patients.get(order.get("patient_id")))


def unit_of_assignment(assignment):
    if assignment is None:
        return None
    return unit_of_order(db.orders.get(assignment.get("order_id")))


def patients_of_unit(unit):
    return [p for p in db.patients.values() if p["unit_id"] == unit["id"]]


def orders_of_unit(unit):
    patient_ids = set(p["id"] for p in db.patients.values() if p["unit_id"] == unit["id"])
    return [o for o in db.orders.values() if o["patient_id"] in patient_ids]


def assignments_of_order(order_id):
    return [a for a in db.assignments.values() if a["order_id"] == order_id]


def feeds_of_order(order_id):
    return [f for f in db.feeds.values() if f["order_id"] == order_id]


def events_of_order(order_id):
    return [e for e in db.events.values() if e["order_id"] == order_id]


def cost_entries_of_assignment(assignment_id):
    return [c for c in db.cost_entries.values() if c["assignment_id"] == assignment_id]


def cost_entries_of_unit(unit_id):
    return [c for c in db.cost_entries.values() if c["unit_id"] == unit_id]


def feeds_of_station(station_id):
    return [f for f in db.feeds.values() if f["station_id"] == station_id]


# ---------------------------------------------------------------------------
# Unit derived figures
# ---------------------------------------------------------------------------
def ledger_head(unit):
    """calculations.unit_cost_ledger_head - exact integer cents, full recompute."""
    total = 0
    for entry in db.cost_entries.values():
        if entry["unit_id"] == unit["id"] and entry["status"] == "POSTED":
            total += entry["amount_cents"]
    return total


def open_order_count(unit):
    count = 0
    for order in orders_of_unit(unit):
        if order["status"] in ORDER_NON_TERMINAL:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Staff derived figures
# ---------------------------------------------------------------------------
def assignments_of_staff(staff_id):
    return [a for a in db.assignments.values() if a["staff_id"] == staff_id]


def last_shift_end_at(staff):
    best = None
    for a in assignments_of_staff(staff["id"]):
        if a["watch_status"] == "VOIDED":
            continue
        if best is None or a["shift_end_at"] > best:
            best = a["shift_end_at"]
    return best


def total_watch_minutes(staff):
    total = 0
    for a in assignments_of_staff(staff["id"]):
        if a["watch_status"] == "VOIDED":
            continue
        total += watched_minutes(a)
    return total


# ---------------------------------------------------------------------------
# SitterAssignment derived figures
# ---------------------------------------------------------------------------
def posted_final_segments(assignment):
    rows = [
        c
        for c in cost_entries_of_assignment(assignment["id"])
        if c["entry_kind"] == "FINAL_SEGMENT" and c["status"] == "POSTED"
    ]
    rows.sort(key=D.sort_key)
    return rows


def watch_segment_count(assignment):
    return len(posted_final_segments(assignment))


def watched_minutes(assignment):
    return sum(c["segment_minutes"] or 0 for c in posted_final_segments(assignment))


def scheduled_minutes(assignment):
    return whole_minutes(assignment["shift_end_at"] - assignment["shift_start_at"])


def final_cost_from_ledger(assignment):
    return sum(c["amount_cents"] for c in posted_final_segments(assignment))


# ---------------------------------------------------------------------------
# MonitoringStation derived figures - calculations.station_effective_span_limit
# and calculations.station_span_occupancy_head
# ---------------------------------------------------------------------------
def active_feed_count(station):
    return len([f for f in feeds_of_station(station["id"]) if f["status"] == "ACTIVE"])


def active_acuity_weight(station):
    total = Decimal("0")
    for f in feeds_of_station(station["id"]):
        if f["status"] == "ACTIVE":
            total += f["acuity_weight"]
    return one_dp(total)


def span_penalty(weight):
    if weight >= PENALTY_TIER_2_MIN_WEIGHT:
        return 2
    if weight >= PENALTY_TIER_1_MIN_WEIGHT:
        return 1
    return 0


def effective_span_limit(station):
    penalty = span_penalty(active_acuity_weight(station))
    return max(SPAN_FLOOR, station["declared_max_span"] - penalty)


def feed_acuity_weight(risk_categories):
    total = Decimal("0")
    for c in risk_categories:
        total += FEED_ACUITY_WEIGHTS[c]
    return one_dp(total)


# ---------------------------------------------------------------------------
# ObservationOrder derived figures
# ---------------------------------------------------------------------------
def reassessment_count(order):
    return len([r for r in db.reassessments.values() if r["order_id"] == order["id"]])


# ---------------------------------------------------------------------------
# calculations.patient_elopement_risk_score
# ---------------------------------------------------------------------------
def event_component_rolling(order_id):
    now = db.clock
    window_start = now - timedelta(hours=ATTEMPT_WINDOW_HOURS)
    component = Decimal("0")
    for event in events_of_order(order_id):
        kind = event["event_kind"]
        if kind in ESCALATING_EVENT_KINDS:
            if event["occurred_at"] >= window_start:
                component += ATTEMPT_EVENT_POINTS
        elif kind in HARM_EVENT_KINDS:
            component += HARM_EVENT_POINTS
    return component


def risk_score(risk_categories, age_years, variant, order_id=None):
    """Weighted scoring; the 10.0 ceiling is applied BEFORE the rounding."""
    base = Decimal("0")
    for c in risk_categories:
        base += RISK_CATEGORY_WEIGHTS[c]
    age_adjustment = (
        AGE_ADJUSTMENT_POINTS if age_years >= AGE_ADJUSTMENT_THRESHOLD_YEARS else Decimal("0.0")
    )
    if variant == "ADMISSION_BASELINE":
        event_component = Decimal("0.0")
    else:
        event_component = event_component_rolling(order_id)
    raw = base + age_adjustment + event_component
    if raw > SCORE_CEILING:
        raw = SCORE_CEILING
    return one_dp(raw)


# ---------------------------------------------------------------------------
# calculations.reassessment_interval_hours
# ---------------------------------------------------------------------------
def interval_hours_for_score(score):
    if score >= TIER_4H_MIN_SCORE:
        return 4
    if score >= TIER_8H_MIN_SCORE:
        return 8
    if score >= TIER_12H_MIN_SCORE:
        return 12
    return DEFAULT_INTERVAL_HOURS


# ---------------------------------------------------------------------------
# calculations.video_modality_gate
# ---------------------------------------------------------------------------
def video_permitted(unit, risk_categories, score):
    if unit is None or not unit.get("video_monitoring_enabled"):
        return False
    if "SELF_HARM" in risk_categories:
        return False
    return score < VIDEO_SCORE_CEILING


# ---------------------------------------------------------------------------
# calculations.assignment_labor_cost
# ---------------------------------------------------------------------------
def is_night(instant):
    hour = instant.astimezone(D.timezone.utc).hour
    return hour >= NIGHT_START_HOUR_UTC or hour < NIGHT_END_HOUR_UTC


def provisional_cost(hourly_rate_cents, minutes, source_pool):
    raw = (
        Decimal(hourly_rate_cents)
        * (Decimal(minutes) / Decimal(60))
        * POOL_MULTIPLIER[source_pool]
    )
    return cents(raw)


def segment_cost(hourly_rate_cents, minutes, source_pool, night):
    raw = (
        Decimal(hourly_rate_cents)
        * (Decimal(minutes) / Decimal(60))
        * POOL_MULTIPLIER[source_pool]
        * (NIGHT_DIFFERENTIAL if night else Decimal("1.0"))
    )
    return cents(raw)


# ---------------------------------------------------------------------------
# calculations.feed_admission_overlap_capacity
# ---------------------------------------------------------------------------
def overlapping_active_feeds(station_id, start, end):
    count = 0
    for f in feeds_of_station(station_id):
        if f["status"] != "ACTIVE":
            continue
        if f["monitor_start_at"] < end and start < f["monitor_end_at"]:
            count += 1
    return count


# ---------------------------------------------------------------------------
# calculations.unit_daily_observation_charge
# ---------------------------------------------------------------------------
def surcharge_pct_for_subtotal(subtotal_cents):
    for threshold, pct in SURCHARGE_TIERS:
        if subtotal_cents >= threshold:
            return pct
    return Decimal("0.00")


def unit_daily_observation_charge(unit, close_through_utc):
    subtotal = 0
    for entry in cost_entries_of_unit(unit["id"]):
        if entry["status"] != "POSTED":
            continue
        if entry["posted_at"] < close_through_utc:
            subtotal += entry["amount_cents"]
    pct = surcharge_pct_for_subtotal(subtotal)
    surcharge = cents(Decimal(subtotal) * pct)
    return subtotal, pct, surcharge, subtotal + surcharge


# ---------------------------------------------------------------------------
# calculations.staff_shift_conflict_check
# ---------------------------------------------------------------------------
def shift_peers(staff_id):
    peers = [a for a in assignments_of_staff(staff_id) if a["watch_status"] != "VOIDED"]
    peers.sort(key=D.sort_key)
    return peers
