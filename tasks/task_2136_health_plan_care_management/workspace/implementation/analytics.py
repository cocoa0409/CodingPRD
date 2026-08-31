"""Stratification, auto-assignment, ROI measurement and the accreditation file."""
from datetime import timedelta
from decimal import Decimal

import core
import domain
from core import (add_days, clock, date_str, db, month_start, add_months, rhu,
                  trunc_toward_zero)
from errors import ApiError


# --------------------------------------------------------------------------
# risk_stratification_score (PRD 3.2)
# --------------------------------------------------------------------------
RETRO_TYPES = ("INPATIENT_ADMISSION", "ED_VISIT", "OBSERVATION_STAY")


def open_social_need_count(member_id):
    enrollment_ids = set()
    for enrollment in db.enrollments.values():
        if (enrollment["member_id"] == member_id
                and enrollment["enrollment_status"] in ("PENDING", "ACTIVE")):
            enrollment_ids.add(enrollment["id"])
    count = 0
    for need in db.social_needs.values():
        if (need["enrollment_id"] in enrollment_ids
                and need["status"] in ("IDENTIFIED", "REFERRED", "UNMET_ESCALATED")):
            count += 1
    return count


def compute_stratification(member, variant):
    now = clock.now()
    lookback_start = now - timedelta(days=core.LOOKBACK_DAYS)
    forward_end = now + timedelta(days=core.FORWARD_DAYS)

    included = []
    for event in domain.member_events(member["id"]):
        etype = event["event_type"]
        occurred = event["occurred_at"]
        if etype in RETRO_TYPES:
            if not (lookback_start <= occurred < now):
                continue
            if variant == "CONCURRENT" and event["adjudication_status"] != "CLOSED":
                continue
            included.append(event)
        elif etype == "SCHEDULED_ADMISSION" and variant == "PROSPECTIVE":
            if now < occurred <= forward_end:
                included.append(event)

    utilization = Decimal("0")
    for event in included:
        base = core.EVENT_POINTS[event["event_type"]]
        if event["event_type"] == "SCHEDULED_ADMISSION":
            factor = Decimal("1.0")
        else:
            age_days = (Decimal(str((now - event["occurred_at"]).total_seconds()))
                        / Decimal("86400"))
            factor = (Decimal("1.0") if age_days <= core.RECENCY_FULL_DAYS
                      else core.RECENCY_DECAY_FACTOR)
        utilization += base * factor
    utilization = rhu(utilization, 1)

    chronic = rhu(Decimal(member["chronic_condition_count"]) * core.CHRONIC_POINT_VALUE, 1)
    need_count = open_social_need_count(member["id"])
    social = min(core.SDOH_POINT_CAP, Decimal(need_count) * core.SDOH_POINT_VALUE)
    social = rhu(social, 1)

    raw = rhu(utilization + chronic + social, 1)
    score = min(100, int(rhu(raw, 0)))
    if score >= 85:
        tier = "HIGH"
    elif score >= 60:
        tier = "RISING"
    elif score >= 35:
        tier = "MODERATE"
    else:
        tier = "LOW"

    record = domain.base_record(versioned=False)
    record.update({
        "member_id": member["id"],
        "variant": variant,
        "as_of_date": date_str(now),
        "utilization_points": utilization,
        "chronic_points": chronic,
        "social_need_points": social,
        "raw_score": raw,
        "score": score,
        "tier": tier,
        "included_event_count": len(included),
    })
    return record


def member_stratifications(member_id, variant=None):
    rows = [s for s in db.stratifications.values() if s["member_id"] == member_id]
    if variant is not None:
        rows = [s for s in rows if s["variant"] == variant]
    return rows


def latest_stratification(member_id, variant):
    rows = member_stratifications(member_id, variant)
    if not rows:
        return None
    rows.sort(key=lambda s: (s["as_of_date"], s["created_at"], s["_seq"]))
    return rows[-1]


def strat_history_sorted(rows):
    """Newest as_of_date first, then newest created."""
    return sorted(rows,
                  key=lambda s: (s["as_of_date"], s["created_at"], s["_seq"]),
                  reverse=True)


def refresh_member_cache(member, variant):
    latest = latest_stratification(member["id"], variant)
    prefix = "latest_concurrent" if variant == "CONCURRENT" else "latest_prospective"
    member[prefix + "_score"] = latest["score"] if latest else None
    member[prefix + "_tier"] = latest["tier"] if latest else None
    domain.touch_record(member)


# --------------------------------------------------------------------------
# care_manager_auto_assignment (PRD 3.3)
# --------------------------------------------------------------------------
def auto_select_care_manager(program, member, tier):
    candidate_weight = rhu(core.TIER_POINTS[tier] * Decimal("1.0"), 1)
    candidates = []
    for manager in db.care_managers.values():
        if manager["credential_level"] not in program["required_credential_levels"]:
            continue
        if member["state_code"] not in manager["licensed_state_codes"]:
            continue
        if manager["capacity_status"] != "OPEN":
            continue
        if manager["assigned_caseload_points"] + candidate_weight > manager["capacity_points"]:
            continue
        candidates.append(manager)
    if not candidates:
        return None
    candidates.sort(key=lambda m: (
        -rhu(m["capacity_points"] - m["assigned_caseload_points"], 1),
        m["created_at"],
        m["_seq"],
    ))
    return candidates[0]


# --------------------------------------------------------------------------
# roi_savings_measurement (PRD 3.9)
# --------------------------------------------------------------------------
def _closed_events(member_id):
    return [e for e in db.transition_events.values()
            if e["member_id"] == member_id and e["adjudication_status"] == "CLOSED"]


def intervention_months(activated_at, end_at):
    months = []
    if activated_at is None or end_at is None:
        return months
    cursor = month_start(activated_at)
    if cursor < activated_at:
        cursor = add_months(cursor, 1)
    while True:
        nxt = add_months(cursor, 1)
        if nxt > end_at:
            break
        months.append((cursor, nxt))
        cursor = nxt
    return months


def compute_roi(enrollment, method):
    end_at = clock.now()
    activated_at = enrollment.get("activated_at")
    months = intervention_months(activated_at, end_at)
    if not months:
        raise ApiError("ERR_MEASUREMENT_PERIOD_EMPTY")

    member_id = enrollment["member_id"]
    closed = _closed_events(member_id)

    def month_cost(start, nxt):
        return sum(e["episode_cost_cents"] for e in closed
                   if start <= e["occurred_at"] < nxt)

    if method == "PRE_POST":
        base_month = month_start(activated_at)
        baseline_start = add_months(base_month, -core.BASELINE_MONTHS)
        baseline_total = sum(e["episode_cost_cents"] for e in closed
                             if baseline_start <= e["occurred_at"] < base_month)
        baseline_pmpm = int(rhu(Decimal(baseline_total) / Decimal(core.BASELINE_MONTHS), 0))
        monthly_projected = int(rhu(Decimal(baseline_pmpm) * core.TREND_FACTOR, 0))
    else:
        program = domain.program_of_enrollment(enrollment)
        benchmark = program["cohort_benchmark_pmpm_cents"] if program else 0
        factor = core.COHORT_RISK_FACTOR.get(
            enrollment.get("risk_tier_at_enrollment"), Decimal("1.0"))
        baseline_pmpm = 0
        monthly_projected = int(rhu(Decimal(benchmark) * factor, 0))

    monthly_actuals = [month_cost(start, nxt) for start, nxt in months]
    intervention_month_count = len(months)
    projected_cost = monthly_projected * intervention_month_count
    actual_cost = sum(monthly_actuals)
    gross = sum(monthly_projected - actual for actual in monthly_actuals)

    program_cost = 0
    for plan in domain.enrollment_plans(enrollment["id"]):
        for goal in domain.plan_goals(plan["id"]):
            for intervention in domain.goal_interventions(goal["id"]):
                if intervention["status"] == "COMPLETED":
                    program_cost += intervention["cost_cents"]

    net = gross - program_cost
    roi_ratio = None
    if program_cost != 0:
        roi_ratio = rhu(Decimal(net) / Decimal(program_cost), 2)

    record = domain.base_record(versioned=False)
    record.update({
        "enrollment_id": enrollment["id"],
        "method": method,
        "baseline_pmpm_cents": baseline_pmpm,
        "monthly_projected_cost_cents": monthly_projected,
        "intervention_month_count": intervention_month_count,
        "projected_cost_cents": projected_cost,
        "actual_cost_cents": actual_cost,
        "gross_savings_cents": gross,
        "program_cost_cents": program_cost,
        "net_savings_cents": net,
        "roi_ratio": roi_ratio,
        "measurement_end_at": end_at,
        "superseded": False,
    })
    return record


# --------------------------------------------------------------------------
# accreditation_compliance_file (PRD 3.9)
# --------------------------------------------------------------------------
def build_accreditation_file(program):
    now = clock.now()
    sample = [e for e in db.enrollments.values()
              if e["program_id"] == program["id"]
              and e["enrollment_status"] == "ACTIVE"]
    sample = domain.sorted_rows(sample)

    counts = dict((code, 0) for code in core.DEFICIENCY_CODES)
    deficient_ids = []

    for enrollment in sample:
        codes = set()
        plans = domain.enrollment_plans(enrollment["id"])
        active_plans = [p for p in plans if p["status"] == "ACTIVE"]
        if not active_plans:
            codes.add("CARE_PLAN_MISSING")
        for plan in active_plans:
            due = plan.get("next_review_due_at")
            if due is not None and due < now:
                codes.add("CARE_PLAN_STALE")
        if enrollment.get("next_touch_due_at") is not None and enrollment["next_touch_due_at"] < now:
            codes.add("TOUCH_OVERDUE")
        if enrollment.get("toc_due_at") is not None and enrollment["toc_due_at"] < now:
            codes.add("TOC_OUTREACH_MISSED")
        for need in domain.enrollment_social_needs(enrollment["id"]):
            for referral in db.referrals.values():
                if referral["social_need_id"] != need["id"]:
                    continue
                if referral["status"] not in ("SENT", "ACCEPTED"):
                    continue
                if add_days(referral["sent_at"], program["referral_loop_days"]) < now:
                    codes.add("REFERRAL_LOOP_OPEN")
        for touch in domain.enrollment_touches(enrollment["id"]):
            if touch["status"] == "COMPLETED" and touch["outcome"] == "REACHED":
                note = touch.get("documentation_note")
                if note is None or not str(note).strip():
                    codes.add("MISSING_CONTACT_NOTE")
        for code in codes:
            counts[code] += 1
        if codes:
            deficient_ids.append(enrollment["id"])

    active_count = len(sample)
    with_deficiency = len(deficient_ids)
    if active_count == 0:
        rate = Decimal("100.0")
    else:
        rate = rhu(Decimal(100) * Decimal(active_count - with_deficiency)
                   / Decimal(active_count), 1)

    return {
        "program_id": program["id"],
        "evaluated_at": core.fmt_instant(now),
        "active_enrollment_count": active_count,
        "enrollments_with_deficiency_count": with_deficiency,
        "compliance_rate_pct": float(rate),
        "deficiency_counts": counts,
        "deficient_enrollment_ids": deficient_ids,
    }
