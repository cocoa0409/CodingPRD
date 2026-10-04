from decimal import Decimal, ROUND_HALF_UP
import math
from datetime import timezone

import db
from clock import parse_iso, period_end


def round_half_up_int(value):
    """Round a Decimal/float to int, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_cents(value):
    return round_half_up_int(value)


def round_half_up_2dp(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value):
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def quality_total_score(accuracy_weight, accuracy_score, compliance_score):
    w = Decimal(str(accuracy_weight))
    a = Decimal(str(accuracy_score))
    c = Decimal(str(compliance_score))
    total = w * a + (Decimal("1") - w) * c
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cert_standing_at(cert, t):
    if cert.get("invalidated_at") is not None:
        return False
    vu = parse_iso(cert["valid_until"])
    return vu > t


def active_window_for(contract_id, program_code, t):
    """ACTIVE surge window at instant t, else most-recently EXPIRED by ends_on then latest created_at, else None."""
    active = [w for w in db.surge_windows.values()
              if w["contract_id"] == contract_id and w["program_code"] == program_code and w["status"] == "ACTIVE"]
    if active:
        active.sort(key=lambda w: (w["created_at"], w["id"]))
        return active[0]
    expired = [w for w in db.surge_windows.values()
               if w["contract_id"] == contract_id and w["program_code"] == program_code and w["status"] == "EXPIRED"]
    if expired:
        expired.sort(key=lambda w: (w["ends_on"], w["created_at"]), reverse=True)
        return expired[0]
    return None


def surge_mult(contract_id, program_code, t):
    w = active_window_for(contract_id, program_code, t)
    if w is None:
        return 1.0
    return float(w["expected_volume_factor"])


def staffing_target_for(contract_id, program_code, t):
    mult = surge_mult(contract_id, program_code, t)
    return int(math.ceil(10 * mult))


def staffing_actual(program_code, t):
    seen = set()
    for cert in db.certifications.values():
        if cert["program_code"] != program_code:
            continue
        if not cert_standing_at(cert, t):
            continue
        agent = db.agents.get(cert["agent_id"])
        if agent is None:
            continue
        if agent["employment_status"] != "ACTIVE":
            continue
        seen.add(agent["id"])
    return len(seen)


def gross_cents_for(contract, period):
    pend = period_end(period)
    # Program set: distinct program_code with any ServiceLevel that reached EFFECTIVE at any time on/before period end.
    program_set = set()
    for sl in db.service_levels.values():
        if sl["contract_id"] != contract["id"]:
            continue
        if sl["status"] not in ("EFFECTIVE", "SUPERSEDED", "ARCHIVED"):
            continue
        if parse_iso(sl["effective_from"]) <= pend:
            program_set.add(sl["program_code"])
    total = Decimal("0")
    for p in program_set:
        c_count = 0
        for cert in db.certifications.values():
            if cert["program_code"] != p:
                continue
            if not cert_standing_at(cert, pend):
                continue
            agent = db.agents.get(cert["agent_id"])
            if agent is None or agent["employment_status"] != "ACTIVE":
                continue
            c_count += 1
        mult = max(1.0, surge_mult(contract["id"], p, pend))
        total += Decimal(4000) * Decimal(c_count) * Decimal(str(mult))
    return 50000 + int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _calls_in_window(contract_id, program_code, period):
    start, end = _window(period)
    out = []
    for c in db.calls.values():
        if c["contract_id"] != contract_id:
            continue
        if c["program_code"] != program_code:
            continue
        enq = parse_iso(c["enqueued_at"])
        if start <= enq < end:
            out.append(c)
    return out


def _window(period):
    from datetime import datetime
    year, month = int(period[:4]), int(period[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    return start, period_end(period)


def measured_asa(contract_id, program_code, period):
    calls = _calls_in_window(contract_id, program_code, period)
    calls = [c for c in calls if c["status"] in ("ANSWERED", "COMPLETED")]
    calls.sort(key=lambda c: (c["enqueued_at"], c["created_at"]))
    if not calls:
        return 0
    total = sum(int(c["answer_seconds"] or 0) for c in calls)
    mean = Decimal(total) / Decimal(len(calls))
    return int(mean.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def measured_abandon(contract_id, program_code, period):
    calls = _calls_in_window(contract_id, program_code, period)
    calls = [c for c in calls if c["status"] in ("ANSWERED", "COMPLETED", "ABANDONED")]
    if not calls:
        return 0.0
    ab = sum(1 for c in calls if c["status"] == "ABANDONED")
    rate = Decimal(ab) / Decimal(len(calls))
    return float(rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def measured_qa_avg(contract_id, program_code, period):
    calls = _calls_in_window(contract_id, program_code, period)
    call_ids = {c["id"] for c in calls}
    reviews = [r for r in db.quality_reviews.values()
               if r["call_id"] in call_ids and r.get("final")]
    if not reviews:
        return None
    total = sum(int(r["total_score"]) for r in reviews)
    mean = Decimal(total) / Decimal(len(reviews))
    return float(mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def is_compliant(metric, measured_value, target, staffing_actual_v, staffing_target_v):
    if staffing_actual_v < staffing_target_v:
        return False
    if metric == "QA_AVG":
        if measured_value is None:
            return False
        return measured_value >= target
    if metric == "ASA":
        return measured_value <= target
    if metric == "ABANDON":
        return measured_value <= target
    return False


def tier_rate(miss_ratio):
    mr = Decimal(str(miss_ratio))
    if mr < Decimal("0.05"):
        return Decimal("0.1")
    if mr < Decimal("0.15"):
        return Decimal("0.25")
    return Decimal("0.4")


def miss_for(metric, measured_value, target):
    if metric == "ASA":
        miss = Decimal(str(measured_value)) - Decimal(str(target))
    elif metric == "ABANDON":
        miss = Decimal(str(measured_value)) - Decimal(str(target))
    else:  # QA_AVG
        if measured_value is None:
            miss = Decimal(str(target))
        else:
            miss = Decimal(str(target)) - Decimal(str(measured_value))
    return miss


def compute_line_withholding(line, sl, contract, gross_cents, cumulative_gross_through, withheld_cum_before):
    """Return withheld cents for a non-compliant line after tier + per-line cap + cumulative cap."""
    target = sl["target"]
    miss = miss_for(line["metric"], line["measured_value"], target)
    if Decimal(str(target)) == 0:
        ratio = Decimal("999")  # any miss against a zero target goes to the top tier
    else:
        ratio = miss / Decimal(str(target))
    rate = tier_rate(ratio)
    raw = (Decimal(gross_cents) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    cap = (Decimal(str(sl["cap_pct_of_gross"])) * Decimal(gross_cents)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    w = min(raw, cap)
    if not contract["cap_absolutes"]:
        floor = Decimal(cumulative_gross_through) - Decimal(withheld_cum_before)
        if floor < 0:
            floor = Decimal(0)
        if w > floor:
            w = floor
    if w < 0:
        w = Decimal(0)
    return int(w)


def binding_service_level(contract_id, program_code, metric, t):
    """Binding SL at instant t: EFFECTIVE with effective_from <= t, tie by latest effective_from then latest created_at."""
    candidates = [sl for sl in db.service_levels.values()
                  if sl["contract_id"] == contract_id
                  and sl["program_code"] == program_code
                  and sl["metric"] == metric
                  and sl["status"] == "EFFECTIVE"
                  and parse_iso(sl["effective_from"]) <= t]
    if not candidates:
        return None
    candidates.sort(key=lambda sl: (sl["effective_from"], sl["created_at"]), reverse=True)
    return candidates[0]
