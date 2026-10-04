"""Business logic: credit tiering, aggregation, gates, eligibility, CE math."""
import uuid
from decimal import Decimal, ROUND_HALF_UP

from dates import add_months, parse_date
from store import db

NATIONAL_TOTAL_HOURS = 3740

AREA_MINIMA = {
    "PRACTICE_MANAGEMENT": 160,
    "PROJECT_MANAGEMENT": 360,
    "PROGRAMMING_ANALYSIS": 260,
    "PROJECT_PLANNING_DESIGN": 1360,
    "PROJECT_DEVELOPMENT_DOCUMENTATION": 1520,
    "CONSTRUCTION_EVALUATION": 80,
}

PRACTICE_AREAS = list(AREA_MINIMA.keys())

DIVISION_CODES = ["PCM", "PJM", "PA", "PPD", "PDD", "CE"]

FULL_CREDIT_WINDOW_MONTHS = 8
HALF_CREDIT_HORIZON_MONTHS = 60
HALF_CREDIT_PCT = 50
REASSIGN_WINDOW_DAYS = 45
RETAKE_WAIT_DAYS = 60
ATTEMPT_LIMIT_COUNT = 3
ATTEMPT_LIMIT_WINDOW_DAYS = 365
ROLLING_CLOCK_MONTHS = 60
SUPPLEMENTAL_RETAKE_DAYS = 90
ALTERNATIVE_PATH_MIN_CREDITS = 64
CE_PERIOD_MONTHS = 24
CE_CARRY_OVER_MAX = 12
RENEWAL_OPEN_DAYS = 60
REINSTATEMENT_WINDOW_MONTHS = 12
REINSTATEMENT_PENALTY_HSW = 4
CE_ENTRY_MAX_HOURS = 24
MIN_REPORT_HOURS = 1
MAX_REPORT_HOURS = 2000


def jurisdiction_by_code(code):
    for j in db["jurisdictions"].values():
        if j["code"] == code:
            return j
    return None


def round_half_up_int(value):
    """Decimal round-half-up to integer (3.5 -> 4), applied per report."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def credited_for(hours, credit_pct):
    return round_half_up_int(Decimal(str(hours)) * Decimal(credit_pct) / Decimal(100))


def credit_tier_for(submit_date, work_end):
    """100 within 8 months of work end (inclusive); 50 within 60 months
    (inclusive); None when the report is too old to count."""
    if submit_date <= add_months(work_end, FULL_CREDIT_WINDOW_MONTHS):
        return 100
    if submit_date <= add_months(work_end, HALF_CREDIT_HORIZON_MONTHS):
        return HALF_CREDIT_PCT
    return None


# ---------------------------------------------------------------- experience

def candidate_reports(candidate_id):
    return [r for r in db["reports"].values() if r["candidate_id"] == candidate_id]


def verified_area_sums(candidate_id):
    sums = {area: 0 for area in AREA_MINIMA}
    for r in candidate_reports(candidate_id):
        if r["status"] == "VERIFIED":
            sums[r["practice_area"]] += r["credited_hours"]
    return sums


def experience_gate_met(candidate):
    """All six area minima (inclusive) AND total >= max(3740, jurisdiction min)."""
    sums = verified_area_sums(candidate["id"])
    for area, minimum in AREA_MINIMA.items():
        if sums[area] < minimum:
            return False
    j = jurisdiction_by_code(candidate["home_jurisdiction_code"])
    jmin = j["min_total_experience_hours"] if j else NATIONAL_TOTAL_HOURS
    return sum(sums.values()) >= max(NATIONAL_TOTAL_HOURS, jmin)


def period_has_overlap(candidate_id, start, end, exclude_id=None):
    """Half-open [start, end) overlap against SUBMITTED/VERIFIED reports of the
    same candidate; mere adjacency (end == start) is allowed."""
    for r in candidate_reports(candidate_id):
        if r["id"] == exclude_id or r["status"] not in ("SUBMITTED", "VERIFIED"):
            continue
        rs = parse_date(r["work_period_start"])
        re_ = parse_date(r["work_period_end"])
        if start < re_ and rs < end:
            return True
    return False


# --------------------------------------------------------------------- exam

def divisions_of(candidate_id):
    return [d for d in db["divisions"].values() if d["candidate_id"] == candidate_id]


def all_divisions_passed(candidate_id):
    rows = divisions_of(candidate_id)
    return len(rows) == len(DIVISION_CODES) and all(
        d["status"] == "PASSED" for d in rows)


def supplementals_of(candidate_id):
    return [s for s in db["supplementals"].values() if s["candidate_id"] == candidate_id]


def exam_day_conflict(candidate_id, day_iso, exclude_division_id=None,
                      exclude_supplemental_id=None):
    """Same-calendar-day conflict: any other SCHEDULED division or REGISTERED
    supplemental exam of this candidate on the given ISO date."""
    for d in divisions_of(candidate_id):
        if (d["id"] != exclude_division_id and d["status"] == "SCHEDULED"
                and d["scheduled_date"] == day_iso):
            return True
    for s in supplementals_of(candidate_id):
        if (s["id"] != exclude_supplemental_id and s["status"] == "REGISTERED"
                and s["exam_date"] == day_iso):
            return True
    return False


# -------------------------------------------------------------- eligibility

def recompute_eligibility(candidate):
    """Persisted certificate_eligible recompute. Returns True when it changed."""
    ed_ok = candidate["education_status"] == "SATISFIED"
    ex_ok = candidate["experience_status"] == "COMPLETE"
    exam_ok = all_divisions_passed(candidate["id"])
    sup_ok = True
    j = jurisdiction_by_code(candidate["home_jurisdiction_code"])
    if j and j["requires_supplemental_exam"]:
        sup_ok = any(
            s["status"] == "PASSED"
            and s["jurisdiction_code"] == candidate["home_jurisdiction_code"]
            for s in supplementals_of(candidate["id"]))
    standing_ok = candidate["record_standing"] == "CLEAR"
    new_value = bool(ed_ok and ex_ok and exam_ok and sup_ok and standing_ok)
    changed = new_value != candidate.get("certificate_eligible", False)
    candidate["certificate_eligible"] = new_value
    return changed


# -------------------------------------------------------------- certificates

def certificates_of(candidate_id):
    return [c for c in db["certificates"].values() if c["candidate_id"] == candidate_id]


def live_certificate_of(candidate_id):
    """The candidate's non-REVOKED certificate, if any (0-1 by construction)."""
    for c in certificates_of(candidate_id):
        if c["status"] != "REVOKED":
            return c
    return None


def mint_serial():
    return "CERT-" + uuid.uuid4().hex[:12].upper()


def ce_entries_of(certificate_id):
    return [e for e in db["ce_entries"].values()
            if e["certificate_id"] == certificate_id]


def ce_totals(cert):
    """(current-period hours, current-period HSW hours, lifetime hours) over
    non-voided entries; the period window is half-open [start, end)."""
    ps = parse_date(cert["period_start"])
    pe = parse_date(cert["period_end"])
    hours = 0
    hsw = 0
    lifetime = 0
    for e in ce_entries_of(cert["id"]):
        if e["voided"]:
            continue
        lifetime += e["hours"]
        cd = parse_date(e["completed_date"])
        if ps <= cd < pe:
            hours += e["hours"]
            if e["hsw"]:
                hsw += e["hours"]
    return hours, hsw, lifetime


def compute_carry(cert):
    """min(max(0, previous-period total - ce_hours_required), 12); the previous
    period is zero for the first period and after any reinstatement."""
    prev = cert.get("_prev_period")
    if not prev:
        return 0
    ps = parse_date(prev[0])
    pe = parse_date(prev[1])
    total = 0
    for e in ce_entries_of(cert["id"]):
        if e["voided"]:
            continue
        cd = parse_date(e["completed_date"])
        if ps <= cd < pe:
            total += e["hours"]
    return min(max(0, total - cert["ce_hours_required"]), CE_CARRY_OVER_MAX)


def ce_renewal_ok(cert):
    """ACTIVE renewal: strict or carry-over variant per the home jurisdiction's
    ce_carry_over_allowed flag read live at renewal time; thresholds come from
    the certificate's snapshots."""
    hours, hsw, _ = ce_totals(cert)
    carry = 0
    j = jurisdiction_by_code(cert["home_jurisdiction_code"])
    if j and j["ce_carry_over_allowed"]:
        carry = compute_carry(cert)
    return (hours + carry) >= cert["ce_hours_required"] and \
        hsw >= cert["ce_hsw_hours_required"]


def ce_reinstatement_ok(cert):
    """LAPSED reinstatement: strict accounting over the closed period, never
    carry, HSW bar raised by the +4 penalty."""
    hours, hsw, _ = ce_totals(cert)
    return hours >= cert["ce_hours_required"] and \
        hsw >= cert["ce_hsw_hours_required"] + REINSTATEMENT_PENALTY_HSW


# -------------------------------------------------------------- disciplinary

def open_disciplinary_count(candidate_id):
    return sum(1 for r in db["disciplinary"].values()
               if r["candidate_id"] == candidate_id and r["status"] == "OPEN")
