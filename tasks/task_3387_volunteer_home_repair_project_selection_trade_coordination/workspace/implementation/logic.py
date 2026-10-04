"""Business logic: calculations, ledger, posture, eligibility, cascades.

Implements PRD section 2.6 (ledger), 2.7 (money/rounding), 2.8 (readiness
posture), 3.1-3.9 (workflows and compensating cascades) and the scaffold
calculation table. All monetary math is integer cents; fractions are rounded
half-up via Decimal and never materialized as floats.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORES, get_clock
from helpers import now_iso, parse_dt, parse_date, clock_date

# ------------------------------------------------------------- constants ---
AMI_BY_HOUSEHOLD_SIZE = {
    1: 5400000, 2: 6170000, 3: 6940000, 4: 7710000,
    5: 8330000, 6: 8950000, 7: 9560000, 8: 10180000,
}
INCOME_LIMIT_NUMERATOR = 80
OLDER_ADULT_POINTS = 40
VETERAN_POINTS = 25
DISABILITY_POINTS = 30
HAZARD_SEVERITY_POINTS = 10
TIER_MULTIPLIER = {"DEEP": Decimal("1.5"), "LOW": Decimal("1.25"),
                   "STD": Decimal("1")}
ENVELOPE_TIER1_MAX_CENTS = 500000
ENVELOPE_TIER2_MAX_CENTS = 2000000
DELIVERY_FEE_RATE = Decimal("0.035")
WARRANTY_RATE = Decimal("0.08")
WARRANTY_CAP_CENTS = 250000

ACTIVE_ENROLLMENT_STATES = ("ENROLLED", "CONFIRMED", "CHECKED_IN")
COVERING_WO_STATES = ("SCHEDULED", "IN_PROGRESS", "PENDING_INSPECTION",
                      "INSPECTED", "INVOICED", "PAID")
CANCELLABLE_PROJECT_STATES = ("PLANNING", "READY")
SUSPENSION_CANCELLABLE_WO = ("QUOTE_REQUESTED", "QUOTED", "APPROVED",
                             "SCHEDULED")


# ---------------------------------------------------------------- helpers ---
def bump(rec):
    """Every mutation refreshes updated_at and increments version by one."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 0) + 1


def get_cycle(rid):
    return STORES["funding_cycles"].get(rid)


def get_application(rid):
    return STORES["applications"].get(rid)


def get_project(rid):
    return STORES["projects"].get(rid)


def get_event(rid):
    return STORES["events"].get(rid)


def get_volunteer(rid):
    return STORES["volunteers"].get(rid)


def cycle_projects(cycle_id):
    return [p for p in STORES["projects"].values()
            if p["funding_cycle_id"] == cycle_id]


def project_items(project):
    return [i for i in STORES["scope_items"].values()
            if i["assessment_id"] == project.get("_assessment_id")]


def project_work_orders(project_id):
    return [w for w in STORES["work_orders"].values()
            if w["project_id"] == project_id]


def project_material_orders(project_id):
    return [m for m in STORES["material_orders"].values()
            if m["project_id"] == project_id]


def project_events(project_id):
    return [e for e in STORES["events"].values()
            if e["project_id"] == project_id]


def event_enrollments(event_id):
    return [e for e in STORES["enrollments"].values()
            if e["event_id"] == event_id]


def assessments_of(application_id):
    return sorted(
        (a for a in STORES["assessments"].values()
         if a["application_id"] == application_id),
        key=lambda a: a["_seq"])


def latest_assessment(application_id):
    lst = assessments_of(application_id)
    return lst[-1] if lst else None


def latest_scoped_assessment(application_id):
    scoped = [a for a in assessments_of(application_id)
              if a["status"] == "SCOPED"]
    return scoped[-1] if scoped else None


# ------------------------------------------------------------ calculations ---
def midpoint_cents(est_low, est_high):
    """round_half_up((low + high) / 2) in integer arithmetic."""
    return (est_low + est_high + 1) // 2


def income_tier(income_cents, household_size):
    """Cross-multiplied integer comparisons; ratios never become floats."""
    ami = AMI_BY_HOUSEHOLD_SIZE[household_size]
    if income_cents * 100 <= 30 * ami:
        return "DEEP"
    if income_cents * 100 <= 50 * ami:
        return "LOW"
    return "STD"


def income_eligible(income_cents, household_size):
    ami = AMI_BY_HOUSEHOLD_SIZE[household_size]
    return income_cents * 100 <= INCOME_LIMIT_NUMERATOR * ami


def compute_priority_score(app, hazard_severity):
    """Pinned order: multiply base by tier factor, add hazard bonus,
    round half up, clamp to [0, 100]."""
    base = 0
    if app["is_older_adult"]:
        base += OLDER_ADULT_POINTS
    if app["is_veteran"]:
        base += VETERAN_POINTS
    if app["has_disability"]:
        base += DISABILITY_POINTS
    tier = income_tier(app["household_income_cents"], app["household_size"])
    cycle = get_cycle(app["funding_cycle_id"])
    bonus = 0
    if (cycle is not None and cycle["priority_mode"] == "HAZARD_PRIORITY"
            and hazard_severity):
        bonus = HAZARD_SEVERITY_POINTS * hazard_severity
    raw = Decimal(base) * TIER_MULTIPLIER[tier] + Decimal(bonus)
    score = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return max(0, min(100, score))


def envelope_for(est):
    """Tiered contingency keyed on the pre-contingency estimate."""
    if est < ENVELOPE_TIER1_MAX_CENTS:
        rate = Decimal("0.15")
    elif est < ENVELOPE_TIER2_MAX_CENTS:
        rate = Decimal("0.10")
    else:
        rate = Decimal("0.05")
    return int((Decimal(est) * (Decimal(1) + rate)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def material_line_cents(quantity, unit_price_dollars):
    amt = Decimal(quantity) * Decimal(str(unit_price_dollars)) * 100
    return int(amt.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def material_totals(lines):
    """Pinned rounding: per-line first, then sum, then fee on the subtotal."""
    subtotal = sum(material_line_cents(l["quantity"], l["unit_price_dollars"])
                   for l in lines)
    fee = int((Decimal(subtotal) * DELIVERY_FEE_RATE).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    return subtotal, fee, subtotal + fee


def cycle_ledger(cycle):
    """Derived ledger figures (PRD 2.6); computed, never stored."""
    cid = cycle["id"]
    pool = cycle["total_budget_cents"] + sum(
        c["amount_cents"] for c in STORES["commitments"].values()
        if c["funding_cycle_id"] == cid
        and c["status"] in ("RECEIVED", "ALLOCATED"))
    projects = cycle_projects(cid)
    reserved = sum(p["reserved_balance_cents"] for p in projects)
    pids = {p["id"] for p in projects}
    spent = sum(
        (w["invoice_cents"] or 0) for w in STORES["work_orders"].values()
        if w["project_id"] in pids and w["status"] == "PAID")
    spent += sum(
        m["total_cents"] for m in STORES["material_orders"].values()
        if m["project_id"] in pids and m["status"] == "DELIVERED")
    spent += sum(
        (c["payout_cents"] or 0) for c in STORES["warranty_claims"].values()
        if c["project_id"] in pids and c["status"] == "RESOLVED")
    return {"pool_cents": pool, "reserved_cents": reserved,
            "spent_cents": spent,
            "available_cents": pool - reserved - spent}


def provisional_estimate(project):
    return sum(i["midpoint_cents"] for i in project_items(project)
               if i["status"] == "INCLUDED")


def reconciled_cost(project):
    pid = project["id"]
    invoiced_paid = [w for w in project_work_orders(pid)
                     if w["status"] in ("INVOICED", "PAID")]
    total = sum((w["invoice_cents"] or 0) for w in invoiced_paid)
    covered = set()
    for w in invoiced_paid:
        covered.update(w["scope_item_ids"])
    for i in project_items(project):
        if (i["volunteer_performable"] and i["status"] in ("INCLUDED", "COMPLETED")
                and i["id"] not in covered):
            total += i["midpoint_cents"]
    total += sum(m["total_cents"] for m in project_material_orders(pid)
                 if m["status"] == "DELIVERED")
    return total


def compute_posture(project):
    """READY iff every INCLUDED licensed-trade item is covered by a live
    work order AND no material order is in flight (ORDERED/STAGED)."""
    wos = project_work_orders(project["id"])
    for item in project_items(project):
        if item["status"] == "INCLUDED" and not item["volunteer_performable"]:
            covered = any(
                w["status"] in COVERING_WO_STATES
                and item["id"] in w["scope_item_ids"] for w in wos)
            if not covered:
                return "BLOCKED"
    if any(m["status"] in ("ORDERED", "STAGED")
           for m in project_material_orders(project["id"])):
        return "BLOCKED"
    return "READY"


def sync_posture(project, touch=True):
    """Automatic PLANNING<->READY promotion/demotion driven by posture.
    EVENT_SCHEDULED projects are never moved by this (PRD 3.7).
    Callers that already bump the project in the same operation pass
    touch=False so the whole operation increments version exactly once."""
    if project["status"] == "PLANNING" and compute_posture(project) == "READY":
        project["status"] = "READY"
        if touch:
            bump(project)
    elif (project["status"] == "READY"
          and compute_posture(project) == "BLOCKED"):
        project["status"] = "PLANNING"
        if touch:
            bump(project)


def is_eligible(vol):
    """REGISTERED + waiver signed + training present + training within
    365 days of the logical clock date (inclusive)."""
    if vol["status"] != "REGISTERED":
        return False
    if not vol["waiver_signed_on"] or not vol["safety_training_completed_on"]:
        return False
    trained = parse_date(vol["safety_training_completed_on"])
    if trained is None:
        return False
    today = clock_date()
    if today is None:
        return False
    return trained + timedelta(days=365) >= today


def active_enrollment_count(event_id):
    return sum(1 for e in event_enrollments(event_id)
               if e["status"] in ACTIVE_ENROLLMENT_STATES)


def open_slots(event):
    return event["max_volunteers"] - active_enrollment_count(event["id"])


def warranty_reserve_remaining(project):
    reserve = min(
        int((WARRANTY_RATE * Decimal(reconciled_cost(project))).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)),
        WARRANTY_CAP_CENTS)
    used = sum((c["payout_cents"] or 0)
               for c in STORES["warranty_claims"].values()
               if c["project_id"] == project["id"]
               and c["status"] in ("APPROVED", "RESOLVED"))
    return reserve - used


def add_calendar_months(dt, months):
    """Add calendar months to a datetime, clamping the day to month end."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    days_in_month = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                     else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(dt.day, days_in_month[month - 1])
    return dt.replace(year=year, month=month, day=day)
