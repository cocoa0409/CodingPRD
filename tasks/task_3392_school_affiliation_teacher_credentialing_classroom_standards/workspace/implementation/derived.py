"""Computed fields and calculation rules (PRD 2.4, 2.9; scaffold 1.3).

All computed fields are derived on read; none of them bump School.version.
"""

from decimal import Decimal, ROUND_HALF_UP

from store import db, now_date, parse_datetime, add_months, active_catalog

# --- calculations.annual_membership_dues constants -------------------------
BASE_DUES_AFFILIATE_CENTS = 40000   # APPLICANT quotes the AFFILIATE schedule
BASE_DUES_MEMBER_CENTS = 90000
BASE_DUES_ACCREDITED_CENTS = 150000
TIER1_UP_TO = 100
TIER1_RATE_CENTS = 1500
TIER2_UP_TO = 300
TIER2_RATE_CENTS = 1200
TIER3_RATE_CENTS = 900
PER_CLASSROOM_SURCHARGE_CENTS = 8000
MIN_DUES_CENTS = 60000
MAX_DUES_CENTS = 1500000

# --- calculations.renewal_fee constants ------------------------------------
RENEWAL_BASE_FEE_CENTS = 8500
LATE_FEE_CENTS = 5000

# --- calculations.school_classroom_clearance constants ---------------------
CYCLE_WINDOW_MONTHS = 12

_BASE_DUES = {
    "APPLICANT": BASE_DUES_AFFILIATE_CENTS,
    "AFFILIATE": BASE_DUES_AFFILIATE_CENTS,
    "MEMBER": BASE_DUES_MEMBER_CENTS,
    "ACCREDITED": BASE_DUES_ACCREDITED_CENTS,
}


# ---------------------------------------------------------------------------
# School derived fields
# ---------------------------------------------------------------------------

def school_classrooms(school_id):
    return [c for c in db.classrooms.values() if c["school_id"] == school_id]


def total_enrollment(school_id):
    return sum(c["enrolled_student_count"] for c in school_classrooms(school_id))


def dues_current(school):
    dpt = school.get("dues_paid_through")
    if not dpt:
        return False
    from store import parse_date
    d = parse_date(dpt)
    return d is not None and d >= now_date()


def brand_compliant(school):
    if not school["uses_method_name"]:
        return True
    if school["membership_level"] == "ACCREDITED":
        return True
    descriptor = school.get("descriptor")
    return bool(descriptor) and descriptor in school["display_name"]


def directory_visible(school):
    return (
        school["membership_level"] in ("MEMBER", "ACCREDITED")
        and school["standing"] == "GOOD_STANDING"
        and brand_compliant(school)
        and dues_current(school)
    )


def annual_dues_cents(school):
    """Tiered dues: base by level + marginal per-student fee + per-classroom
    surcharge; floor applies before cap."""
    base = _BASE_DUES[school["membership_level"]]
    n = total_enrollment(school["id"])
    fee = TIER1_RATE_CENTS * min(n, TIER1_UP_TO)
    fee += TIER2_RATE_CENTS * max(0, min(n, TIER2_UP_TO) - TIER1_UP_TO)
    fee += TIER3_RATE_CENTS * max(0, n - TIER2_UP_TO)
    surcharge = PER_CLASSROOM_SURCHARGE_CENTS * len(school_classrooms(school["id"]))
    raw = base + fee + surcharge
    return min(MAX_DUES_CENTS, max(MIN_DUES_CENTS, raw))


# ---------------------------------------------------------------------------
# Classroom derived fields
# ---------------------------------------------------------------------------

def classroom_audits(classroom_id):
    return [a for a in db.audits.values() if a["classroom_id"] == classroom_id]


def latest_audit(classroom_id):
    """Most recent audit by created_at; same-instant filings tie-break by
    server receipt order (the later-filed request wins), never by id."""
    audits = classroom_audits(classroom_id)
    if not audits:
        return None
    return max(audits, key=lambda a: (a["created_at"], a["_seq"]))


def latest_audit_verdict(classroom_id):
    a = latest_audit(classroom_id)
    return a["verdict"] if a else None


def compliant_classroom_count(school_id):
    count = 0
    for c in school_classrooms(school_id):
        if c["compliance_override"] != "NONE":
            continue
        a = latest_audit(c["id"])
        if a is not None and a["verdict"] == "COMPLIANT":
            count += 1
    return count


# ---------------------------------------------------------------------------
# School classroom clearance variants (application submit)
# ---------------------------------------------------------------------------

def school_clearance(school_id, variant):
    """LATEST_PASS (MEMBERSHIP) or NO_FAIL_IN_CYCLE (ACCREDITATION)."""
    rooms = school_classrooms(school_id)
    if not rooms:
        return False
    today = now_date()
    for room in rooms:
        if room["compliance_override"] != "NONE":
            return False
        audits = classroom_audits(room["id"])
        if variant == "LATEST_PASS":
            latest = latest_audit(room["id"])
            if latest is None or latest["verdict"] != "COMPLIANT":
                return False
        else:  # NO_FAIL_IN_CYCLE
            window_start = add_months(today, -CYCLE_WINDOW_MONTHS)
            in_window = [
                a for a in audits
                if window_start <= parse_datetime(a["observed_at"]).date() <= today
            ]
            if not in_window:
                return False
            if any(a["verdict"] == "NONCOMPLIANT" for a in in_window):
                return False
    return True


# ---------------------------------------------------------------------------
# Credential CE totals (calculations.ce_hours_qualification)
# ---------------------------------------------------------------------------

def ce_totals(credential):
    """Return (CYCLE, ROLLING) hour totals as Decimals over ACTIVE entries."""
    entries = [
        e for e in db.ce_entries.values()
        if e["credential_id"] == credential["id"] and e["status"] == "ACTIVE"
    ]
    from store import parse_date
    cycle_start = parse_date(credential["cycle_start"])
    cycle = Decimal("0")
    rolling = Decimal("0")
    today = now_date()
    cat = active_catalog()
    window_start = None
    if cat is not None:
        window_start = add_months(today, -int(cat["credential_validity_months"]))
    for e in entries:
        earned = parse_datetime(e["earned_at"]).date()
        if cycle_start is not None and earned >= cycle_start:
            cycle += e["hours"]
        if window_start is not None and window_start <= earned <= today:
            rolling += e["hours"]
    return cycle, rolling


def round2(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round4(value):
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
