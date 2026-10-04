"""Business logic: penalty pricing, coverage math, sweeps, cascades."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP

from db import db
from helpers import (
    BASE_BY_VRF, COVERAGE_GAP_THRESHOLD, GAP_AGGRAVATION, HIGH_MULTIPLIER,
    OPEN_VIOLATION_STATUSES, RECIDIVISM_CAP, RECIDIVISM_RATE,
    SELF_LOG_DISCOUNT, SELF_REPORT_DISCOUNT, SEVERE_MULTIPLIER,
    clock_now, entity_applicable_standards, new_common, new_id, touch,
)


# ---------------------------------------------------------------------------
# Entity derived fields
# ---------------------------------------------------------------------------

def recompute_applicable(entity):
    standards = entity_applicable_standards(entity["registration_functions"])
    entity["applicable_standards"] = standards
    entity["applicable_standard_count"] = len(standards)


def recompute_open_violation_count(entity):
    count = sum(
        1 for v in db.violations.values()
        if v["entity_id"] == entity["id"] and v["status"] in OPEN_VIOLATION_STATUSES
    )
    entity["open_violation_count"] = count


def recompute_unresolved_appeal_count(entity):
    count = sum(
        1 for a in db.appeals.values()
        if db.violations.get(a["violation_id"], {}).get("entity_id") == entity["id"]
        and a["status"] == "APPEAL_PENDING_REVIEW"
    )
    entity["unresolved_appeal_count"] = count


# ---------------------------------------------------------------------------
# Coverage math (scaffold §1.3 covered_period / coverage_fraction)
# ---------------------------------------------------------------------------

def covered_period_seconds(engagement, standard_id):
    """Union length (integer seconds) of SUBMITTED/ACCEPTED coverage windows for
    one standard inside the engagement period, half-open intervals, adjacent merge."""
    intervals = []
    for art in db.evidence.values():
        if (
            art["engagement_id"] == engagement["id"]
            and art["standard_id"] == standard_id
            and art["status"] in ("SUBMITTED", "ACCEPTED")
        ):
            intervals.append((art["coverage_start"], art["coverage_end"]))
    if not intervals:
        return 0
    intervals.sort(key=lambda iv: iv[0])
    merged = []
    cur_start, cur_end = intervals[0]
    for s, e in intervals[1:]:
        if s <= cur_end:  # overlapping or adjacent (gap == 0)
            if e > cur_end:
                cur_end = e
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = s, e
    merged.append((cur_start, cur_end))

    p_start, p_end = engagement["period_start"], engagement["period_end"]
    total = 0
    for a, b in merged:
        lo = max(a, p_start)
        hi = min(b, p_end)
        delta = (hi - lo).total_seconds()
        if delta > 0:
            total += int(delta)
    return total


def recompute_coverage_fraction(engagement):
    p_len = (engagement["period_end"] - engagement["period_start"]).total_seconds()
    stds = engagement["standard_ids"]
    if not stds or p_len <= 0:
        engagement["coverage_fraction"] = 0.0
        return
    per = []
    for s in stds:
        per.append(Decimal(covered_period_seconds(engagement, s)) / Decimal(int(p_len)))
    avg = sum(per) / Decimal(len(per))
    frac = avg.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    engagement["coverage_fraction"] = float(frac)


# ---------------------------------------------------------------------------
# Penalty pricing (scaffold §1.3 propose_penalty / final_penalty)
# ---------------------------------------------------------------------------

def compute_penalty(violation, closing=False, closure_time=None):
    """Return (base_amount, adjustment_factor, amount).

    closing=True applies the stale-violation discount to the base when the
    violation ended more than 365 days before the closure time.
    """
    vrf = violation["violation_risk_factor"]
    base = Decimal(BASE_BY_VRF[vrf])
    if closing:
        ct = closure_time if closure_time is not None else clock_now()
        if violation["violation_end"] < ct - timedelta(days=365):
            base = (base * Decimal("0.9")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    factor = Decimal("1.0")
    if violation["severity_level"] == "SEVERE":
        factor *= Decimal(str(SEVERE_MULTIPLIER))
    if violation["severity_level"] == "HIGH":
        factor *= Decimal(str(HIGH_MULTIPLIER))
    if violation["source_type"] == "SELF_REPORT":
        factor *= Decimal(str(SELF_REPORT_DISCOUNT))
    if violation["source_type"] == "SELF_LOG":
        factor *= Decimal(str(SELF_LOG_DISCOUNT))
    eng_id = violation.get("source_engagement_id")
    if eng_id is not None:
        eng = db.engagements.get(eng_id)
        if eng is not None and eng.get("coverage_fraction", 1.0) < COVERAGE_GAP_THRESHOLD:
            factor *= Decimal(str(GAP_AGGRAVATION))

    prior_confirmed = sum(
        1 for v in db.violations.values()
        if v["entity_id"] == violation["entity_id"]
        and v["id"] != violation["id"]
        and v["status"] == "CLOSED"
        and v.get("final_penalty") is not None
    )
    capped = min(prior_confirmed, RECIDIVISM_CAP)
    factor *= (Decimal("1.0") + Decimal(str(RECIDIVISM_RATE)) * Decimal(capped))

    factor = factor.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
    amount = (base * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(base), float(factor), float(amount)


# ---------------------------------------------------------------------------
# Violation close cascade
# ---------------------------------------------------------------------------

def close_violation(violation):
    """Violation -> CLOSED: final_penalty, counters, penalty upsert."""
    entity = db.registered_entities[violation["entity_id"]]
    closure_time = clock_now()
    base, factor, amount = compute_penalty(violation, closing=True, closure_time=closure_time)
    violation["final_penalty"] = amount
    violation["status"] = "CLOSED"
    touch(violation)

    recompute_open_violation_count(entity)
    touch(entity)

    upsert_penalty(violation, base, factor, amount)


def upsert_penalty(violation, base, factor, amount):
    """Create-or-update the Penalty row for this violation with amount = final."""
    existing = None
    for p in db.penalties.values():
        if p["violation_id"] == violation["id"]:
            existing = p
            break
    now = clock_now()
    if existing is None:
        row = new_common()
        row.update({
            "violation_id": violation["id"],
            "base_amount": base,
            "adjustment_factor": factor,
            "amount": amount,
            "issued_at": now,
            "due_date": now + timedelta(days=30),
            "status": "ASSESSED",
        })
        db.penalties[row["id"]] = row
        return row
    existing["base_amount"] = base
    existing["adjustment_factor"] = factor
    existing["amount"] = amount
    touch(existing)
    return existing


# ---------------------------------------------------------------------------
# Restriction rule (§2.8 / restriction_due)
# ---------------------------------------------------------------------------

def restriction_check(entity):
    """Set compliance_status RESTRICTED iff a CONFIRMED past-due penalty exists
    for the entity; else ACTIVE. Bumps entity version when it changes."""
    now = clock_now()
    restricted = False
    for p in db.penalties.values():
        if p["status"] != "CONFIRMED":
            continue
        v = db.violations.get(p["violation_id"])
        if v is None or v["entity_id"] != entity["id"]:
            continue
        if p["due_date"] < now:
            restricted = True
            break
    target = "RESTRICTED" if restricted else "ACTIVE"
    if entity["compliance_status"] != target:
        entity["compliance_status"] = target
        touch(entity)


def restriction_sweep_all():
    for entity in db.registered_entities.values():
        restriction_check(entity)


# ---------------------------------------------------------------------------
# Clock sweeps
# ---------------------------------------------------------------------------

def advance_sweep():
    """Milestone MISSED sweep + restriction sweep."""
    now = clock_now()
    for m in db.milestones.values():
        if m["status"] == "PENDING" and m["due_date"] < now:
            m["status"] = "MISSED"
            touch(m)
    restriction_sweep_all()
