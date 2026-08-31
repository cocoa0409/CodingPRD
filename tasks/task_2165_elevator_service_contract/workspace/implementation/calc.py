"""§1.3 Calculation rules: uptime, penalty, credit, performance score,
part-order pricing and the two downtime overlap rules."""

from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from common import (
    db, parse_dt, parse_date_str, month_bounds, month_of, previous_month,
    now_clock, clock_date, dec2, rhu, rhu_int, cars_of_contract, windows_of_car,
    callbacks_of_car, inspections_of_car, visits_of_car, windows_of_project,
    UPTIME_TARGET_PCT, SEVERE_SHORTFALL_PP, LATE_CALLBACK_FEE_CENTS,
    ENTRAPMENT_FEE_CENTS, MISSED_VISIT_FEE_CENTS, UPTIME_PENALTY_PER_PP_CENTS,
    PENALTY_CAP_PCT_A, SCHEDULE_B_BREACH_PCT, PENALTY_CAP_PCT_B,
    W_UPTIME, W_RESPONSE, W_VISIT, DRAG_DIVISOR_CENTS, PENALTY_DRAG_CAP_PTS,
    EXPEDITE_PCT_TIER_SMALL, EXPEDITE_PCT_TIER_MEDIUM, EXPEDITE_PCT_TIER_LARGE,
    EXPEDITE_DAYS_SAVED, MIN_LEAD_DAYS, OBSOLETE_SUBSTITUTION_PENALTY_DAYS,
    INTER_TYPE_BUFFER_MINUTES,
    FULL_MAINTENANCE_REQUIRED_TASK_CODES, OIL_AND_GREASE_REQUIRED_TASK_CODES,
)

OPEN_CALLBACK_STATES = ("REPORTED", "ESCALATED", "ON_SITE")
OCCUPYING_WINDOW_STATES = ("SCHEDULED", "COMPLETED")


# ==========================================================================
# Interval algebra
# ==========================================================================
def _clip(start, end, lo, hi):
    if start < lo:
        start = lo
    if end > hi:
        end = hi
    if end <= start:
        return None
    return (start, end)


def merge_intervals(intervals):
    """Union-merge, ordered by start ASC then end ASC."""
    ordered = sorted(intervals, key=lambda p: (p[0], p[1]))
    merged = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _total_seconds(intervals):
    total = 0
    for start, end in intervals:
        total += (end - start).total_seconds()
    return total


def _minutes(intervals):
    """Whole minutes, truncated toward zero."""
    return int(_total_seconds(intervals) // 60)


def subtract_intervals(base, cut):
    """base minus cut; both must already be merged."""
    result = []
    for start, end in base:
        pieces = [(start, end)]
        for c_start, c_end in cut:
            next_pieces = []
            for p_start, p_end in pieces:
                if c_end <= p_start or c_start >= p_end:
                    next_pieces.append((p_start, p_end))
                    continue
                if c_start > p_start:
                    next_pieces.append((p_start, c_start))
                if c_end < p_end:
                    next_pieces.append((c_end, p_end))
            pieces = next_pieces
        result.extend(pieces)
    return merge_intervals(result)


# ==========================================================================
# car_uptime_percentage
# ==========================================================================
def car_uptime(car, period_month):
    """Returns a dict with the full uptime report for one car and one month."""
    period_start, period_end = month_bounds(period_month)
    period_minutes = int((period_end - period_start).total_seconds() // 60)

    unplanned = []
    for cb in callbacks_of_car(car["id"]):
        if not cb.get("out_of_service"):
            continue
        reported = parse_dt(cb.get("reported_at"))
        if reported is None:
            continue
        if cb["status"] == "CLEARED":
            cleared = parse_dt(cb.get("cleared_at"))
            if cleared is None:
                continue
            piece = _clip(reported, cleared, period_start, period_end)
        elif cb["status"] in OPEN_CALLBACK_STATES:
            piece = _clip(reported, period_end, period_start, period_end)
        else:
            piece = None
        if piece:
            unplanned.append(piece)

    red_tag_lifted = parse_dt(car.get("red_tag_lifted_at"))
    for insp in inspections_of_car(car["id"]):
        if insp["status"] != "COMPLETED" or insp.get("result") != "FAIL":
            continue
        recorded = parse_dt(insp.get("result_recorded_at"))
        if recorded is None:
            continue
        end = red_tag_lifted if red_tag_lifted is not None else period_end
        piece = _clip(recorded, end, period_start, period_end)
        if piece:
            unplanned.append(piece)

    merged_unplanned = merge_intervals(unplanned)
    unplanned_minutes = _minutes(merged_unplanned)

    planned = []
    for w in windows_of_car(car["id"]):
        if w["status"] not in OCCUPYING_WINDOW_STATES:
            continue
        start = parse_dt(w["window_start"])
        end = parse_dt(w["window_end"])
        if start is None or end is None:
            continue
        piece = _clip(start, end, period_start, period_end)
        if piece:
            planned.append(piece)

    merged_planned = merge_intervals(planned)
    planned_only = subtract_intervals(merged_planned, merged_unplanned)
    planned_minutes = _minutes(planned_only)

    available_minutes = period_minutes - planned_minutes - unplanned_minutes

    exclusive_denominator = period_minutes - planned_minutes
    if exclusive_denominator <= 0:
        uptime_exclusive = Decimal("100.00")
    else:
        uptime_exclusive = dec2(
            Fraction(available_minutes * 100, exclusive_denominator))
    if period_minutes <= 0:
        uptime_inclusive = Decimal("100.00")
    else:
        uptime_inclusive = dec2(Fraction(available_minutes * 100, period_minutes))

    return {
        "car_id": car["id"],
        "period_month": period_month,
        "period_minutes": period_minutes,
        "unplanned_outage_minutes": unplanned_minutes,
        "planned_downtime_minutes": planned_minutes,
        "available_minutes": available_minutes,
        "uptime_pct_exclusive": uptime_exclusive,
        "uptime_pct_inclusive": uptime_inclusive,
        "outage_interval_count": len(merged_unplanned),
    }


def uptime_variant_for(contract):
    return "EXCLUSIVE" if contract["scope_type"] == "FULL_MAINTENANCE" else "INCLUSIVE"


def car_uptime_value(car, period_month, variant):
    report = car_uptime(car, period_month)
    if variant == "EXCLUSIVE":
        return report["uptime_pct_exclusive"]
    return report["uptime_pct_inclusive"]


def contract_uptime(contract, period_month, variant):
    """Arithmetic mean of the per-car (already 2dp) uptime values, 2dp."""
    car_set = cars_of_contract(contract["id"])
    if not car_set:
        return Decimal("100.00")
    values = [car_uptime_value(car, period_month, variant) for car in car_set]
    total = sum(values, Decimal("0"))
    return dec2(Fraction(
        int(total.scaleb(2)), len(values) * 100))


# ==========================================================================
# penalty_assessment_amount + contract_monthly_credit_cents
# ==========================================================================
def _period_counters(contract, period_month, car_set):
    period_start, period_end = month_bounds(period_month)
    car_ids = set(c["id"] for c in car_set)

    late = 0
    entrapment = 0
    for cb in db.callbacks.values():
        if cb["car_id"] not in car_ids:
            continue
        if cb["status"] != "CLEARED" or not cb.get("sla_breached"):
            continue
        reported = parse_dt(cb.get("reported_at"))
        if reported is None or not (period_start <= reported < period_end):
            continue
        if cb["callback_type"] == "ENTRAPMENT":
            entrapment += 1
        else:
            late += 1

    missed = 0
    for v in db.visits.values():
        if v["car_id"] not in car_ids:
            continue
        if v["period_month"] != period_month:
            continue
        if v["status"] in ("MISSED", "REJECTED"):
            missed += 1

    return late, entrapment, missed


def _tier_pct(uptime_pct):
    if uptime_pct >= Decimal("98.50"):
        return Decimal("0.00")
    if uptime_pct >= Decimal("97.00"):
        return Decimal("0.05")
    if uptime_pct >= Decimal("95.00"):
        return Decimal("0.10")
    return Decimal("0.20")


def assess_penalty(contract, period_month):
    variant = uptime_variant_for(contract)
    car_set = cars_of_contract(contract["id"])
    uptime_pct_applied = contract_uptime(contract, period_month, variant)
    shortfall_pp = UPTIME_TARGET_PCT - uptime_pct_applied
    if shortfall_pp < 0:
        shortfall_pp = Decimal("0.00")

    late, entrapment, missed = _period_counters(contract, period_month, car_set)
    fee = contract["monthly_base_fee_cents"]
    schedule = contract["penalty_schedule"]

    if schedule == "SCHEDULE_A":
        raw = (LATE_CALLBACK_FEE_CENTS * late
               + ENTRAPMENT_FEE_CENTS * entrapment
               + MISSED_VISIT_FEE_CENTS * missed
               + rhu_int(shortfall_pp * Decimal(UPTIME_PENALTY_PER_PP_CENTS)))
        cap = rhu_int(Decimal(fee) * PENALTY_CAP_PCT_A)
    else:
        tier_pct = _tier_pct(uptime_pct_applied)
        breach_pct = SCHEDULE_B_BREACH_PCT * Decimal(late + 2 * entrapment + missed)
        if entrapment > 0:
            severity = 3
        elif shortfall_pp >= SEVERE_SHORTFALL_PP:
            severity = 2
        else:
            severity = 1
        raw = rhu_int(Decimal(fee) * (tier_pct + breach_pct) * Decimal(severity))
        cap = rhu_int(Decimal(fee) * PENALTY_CAP_PCT_B)

    amount = min(raw, cap)

    # contract_monthly_credit_cents — round per car, THEN sum.
    n = len(car_set)
    credit = 0
    for car in car_set:
        u_car = car_uptime_value(car, period_month, variant)
        raw_credit = (Fraction(fee) * Fraction(1, n)
                      * (Fraction(100) - Fraction(str(u_car))) / Fraction(100))
        credit += rhu_int(raw_credit)

    return {
        "schedule_applied": schedule,
        "uptime_variant_applied": variant,
        "uptime_pct_applied": uptime_pct_applied,
        "late_callback_count": late,
        "entrapment_breach_count": entrapment,
        "missed_visit_count": missed,
        "raw_amount_cents": raw,
        "cap_amount_cents": cap,
        "amount_cents": amount,
        "service_credit_cents": credit,
    }


# ==========================================================================
# contract_performance_score
# ==========================================================================
SCORE_VISIT_STATES = ("VERIFIED", "DISPUTED", "REJECTED", "MISSED", "PERFORMED")


def performance_score(contract):
    score_month = previous_month(now_clock())
    car_set = cars_of_contract(contract["id"])
    variant = uptime_variant_for(contract)

    if not car_set:
        uptime_pct = Decimal("100.00")
    else:
        uptime_pct = contract_uptime(contract, score_month, variant)

    period_start, period_end = month_bounds(score_month)
    car_ids = set(c["id"] for c in car_set)

    total_cb = 0
    compliant_cb = 0
    for cb in db.callbacks.values():
        if cb["car_id"] not in car_ids or cb["status"] != "CLEARED":
            continue
        reported = parse_dt(cb.get("reported_at"))
        if reported is None or not (period_start <= reported < period_end):
            continue
        total_cb += 1
        if not cb.get("sla_breached"):
            compliant_cb += 1
    if total_cb == 0:
        response_pct = Decimal("100.00")
    else:
        response_pct = dec2(Fraction(100 * compliant_cb, total_cb))

    total_v = 0
    verified_v = 0
    for v in db.visits.values():
        if v["car_id"] not in car_ids:
            continue
        if v["period_month"] != score_month or v["status"] not in SCORE_VISIT_STATES:
            continue
        total_v += 1
        if v["status"] == "VERIFIED":
            verified_v += 1
    if total_v == 0:
        visit_pct = Decimal("100.00")
    else:
        visit_pct = dec2(Fraction(100 * verified_v, total_v))

    drag = dec2(Fraction(contract["penalty_balance_cents"], DRAG_DIVISOR_CENTS))
    if drag > PENALTY_DRAG_CAP_PTS:
        drag = PENALTY_DRAG_CAP_PTS

    raw = W_UPTIME * uptime_pct + W_RESPONSE * response_pct + W_VISIT * visit_pct - drag
    score = dec2(raw)
    if score > Decimal("100.00"):
        score = Decimal("100.00")
    if score < Decimal("0.00"):
        score = Decimal("0.00")
    return score


# ==========================================================================
# visit_task_compliance
# ==========================================================================
def required_task_codes(contract):
    if contract["scope_type"] == "FULL_MAINTENANCE":
        return list(FULL_MAINTENANCE_REQUIRED_TASK_CODES)
    return list(OIL_AND_GREASE_REQUIRED_TASK_CODES)


def task_compliance(contract, task_items):
    completed = sorted(set(
        item["task_code"] for item in task_items if item.get("completed") is True))
    required = required_task_codes(contract)
    missing = sorted(code for code in required if code not in completed)
    return completed, missing


# ==========================================================================
# part_order_cost_and_promise
# ==========================================================================
def resolve_supersession(part):
    """Walk superseded_by_part_id; returns (effective_part, hops, too_deep)."""
    hops = 0
    current = part
    too_deep = False
    while (current["lifecycle_state"] == "OBSOLETE"
           and current.get("superseded_by_part_id")):
        successor = db.parts.get(current["superseded_by_part_id"])
        if successor is None:
            break
        current = successor
        hops += 1
        if hops > 3:
            too_deep = True
            break
    return current, hops, too_deep


def expedite_pct_for(subtotal_cents):
    if subtotal_cents < 100000:
        return EXPEDITE_PCT_TIER_SMALL
    if subtotal_cents < 500000:
        return EXPEDITE_PCT_TIER_MEDIUM
    return EXPEDITE_PCT_TIER_LARGE


def price_part_order(effective_part, quantity, expedite, hops):
    subtotal = effective_part["unit_price_cents"] * quantity
    if expedite:
        surcharge = rhu_int(Decimal(subtotal) * expedite_pct_for(subtotal))
    else:
        surcharge = 0
    total = subtotal + surcharge
    lead = (effective_part["lead_time_days"]
            - (EXPEDITE_DAYS_SAVED if expedite else 0)
            + OBSOLETE_SUBSTITUTION_PENALTY_DAYS * hops)
    lead = max(MIN_LEAD_DAYS, lead)
    promised = clock_date() + timedelta(days=lead)
    return {
        "subtotal_cents": subtotal,
        "expedite_surcharge_cents": surcharge,
        "total_cost_cents": total,
        "lead_time_days_applied": lead,
        "promised_date": promised.isoformat(),
    }


# ==========================================================================
# downtime_overlap_rule
# ==========================================================================
def _gap_minutes(a_start, a_end, b_start, b_end):
    if a_end <= b_start:
        return int((b_start - a_end).total_seconds() // 60)
    if b_end <= a_start:
        return int((a_start - b_end).total_seconds() // 60)
    return 0


def rule1_conflict(car_id, cand_start, cand_end, cand_type, exclude_window_id=None):
    """RULE 1 — per-car, half-open minute precision, inter-type 120min buffer."""
    for w in windows_of_car(car_id):
        if exclude_window_id is not None and w["id"] == exclude_window_id:
            continue
        if w["status"] not in OCCUPYING_WINDOW_STATES:
            continue
        w_start = parse_dt(w["window_start"])
        w_end = parse_dt(w["window_end"])
        if w_start is None or w_end is None:
            continue
        if cand_start < w_end and w_start < cand_end:
            return True
        if w["window_type"] != cand_type:
            if _gap_minutes(cand_start, cand_end, w_start, w_end) < INTER_TYPE_BUFFER_MINUTES:
                return True
    return False


def _closed_date_range(start, end):
    first = start.astimezone(start.tzinfo).date()
    last = (end - timedelta(minutes=1)).date()
    days = set()
    cursor = first
    while cursor <= last:
        days.add(cursor)
        cursor = cursor + timedelta(days=1)
    return days


def rule2_conflict(car, cand_start, cand_end):
    """RULE 2 — contract-wide modernization capacity, closed calendar dates."""
    cand_dates = _closed_date_range(cand_start, cand_end)
    for other in cars_of_contract(car["contract_id"], include_decommissioned=True):
        if other["id"] == car["id"]:
            continue
        for w in windows_of_car(other["id"]):
            if w["window_type"] != "MODERNIZATION":
                continue
            if w["status"] not in OCCUPYING_WINDOW_STATES:
                continue
            w_start = parse_dt(w["window_start"])
            w_end = parse_dt(w["window_end"])
            if w_start is None or w_end is None:
                continue
            if cand_dates & _closed_date_range(w_start, w_end):
                return True
    return False


def recompute_scheduled_downtime(car):
    """scheduled_downtime_minutes = sum of duration over SCHEDULED|COMPLETED."""
    total = 0
    for w in windows_of_car(car["id"]):
        if w["status"] in OCCUPYING_WINDOW_STATES:
            total += w["duration_minutes"]
    changed = car["scheduled_downtime_minutes"] != total
    car["scheduled_downtime_minutes"] = total
    return changed


def recompute_project_target(project):
    """Latest window_end date over SCHEDULED|COMPLETED|RESCHEDULE_REQUIRED."""
    best = None
    for w in windows_of_project(project["id"]):
        if w["status"] not in ("SCHEDULED", "COMPLETED", "RESCHEDULE_REQUIRED"):
            continue
        end = parse_dt(w["window_end"])
        if end is None:
            continue
        end_date = end.date()
        if best is None or end_date > best:
            best = end_date
    return best


def recompute_window_count(project):
    total = 0
    for w in windows_of_project(project["id"]):
        if w["status"] in OCCUPYING_WINDOW_STATES:
            total += 1
    return total
