"""Domain logic: serializers, computed fields, calculations, lazy evaluation,
and cascade helpers. All rules trace to PRD §3 and the SCAFFOLD tables."""

from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from store import STORE, CLOCK, bump, parse_date


# ---------------------------------------------------------------------------
# Calculation constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

PELL_MAX_CENTS = 739500
COA_BY_INTENSITY = {
    "FULL_TIME": 800000,
    "HALF_TIME": 500000,
    "LESS_THAN_HALF_TIME": 200000,
}
R2T4_EARNED_CLIFF = Fraction(60, 100)  # 0.60, strict > comparison
INST_HALF_REFUND_WINDOW_DAYS = 14
ADJUNCT_SECTION_SIZE = 30
MAX_CONTACTS_PER_7D = 3
CADENCE_WINDOW_HOURS = 168
MIN_DAYS_BETWEEN_OUTREACH = 14
TRANSFER_CAP_NUM = 3
TRANSFER_CAP_DEN = 4


# ---------------------------------------------------------------------------
# Serializers (public fields only, per entity table)
# ---------------------------------------------------------------------------

def ser_term(t):
    return {
        "id": t["id"],
        "name": t["name"],
        "start_date": t["start_date"],
        "add_drop_end_date": t["add_drop_end_date"],
        "census_date": t["census_date"],
        "end_date": t["end_date"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_program(p):
    return {
        "id": p["id"],
        "code": p["code"],
        "title": p["title"],
        "total_credits_required": p["total_credits_required"],
        "licensure_flag": p["licensure_flag"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_state_auth(a):
    # StateAuthorization rows carry only id + created_at (no updated_at/version).
    return {
        "id": a["id"],
        "program_id": a["program_id"],
        "state_code": a["state_code"],
        "authorization_status": a["authorization_status"],
        "effective_from": a["effective_from"],
        "effective_to": a["effective_to"],
        "disclosure_text": a["disclosure_text"],
        "created_at": a["created_at"],
    }


def ser_staff(s):
    return {
        "id": s["id"],
        "full_name": s["full_name"],
        "email": s["email"],
        "staff_type": s["staff_type"],
        "compensation_plan": s["compensation_plan"],
        "caseload_cap": s["caseload_cap"],
        "active_caseload_count": active_caseload_count(s),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_applicant(a):
    log = [
        {"channel": e["channel"], "outcome": e["outcome"], "attempted_at": e["attempted_at"]}
        for e in a["contact_log"]
    ]
    return {
        "id": a["id"],
        "full_name": a["full_name"],
        "email": a["email"],
        "state_code": a["state_code"],
        "status": a["status"],
        "assigned_counselor_id": a["assigned_counselor_id"],
        "contact_log": log,
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_application(a):
    return {
        "id": a["id"],
        "applicant_id": a["applicant_id"],
        "term_id": a["term_id"],
        "program_id": a["program_id"],
        "disclosure_acknowledged": a["disclosure_acknowledged"],
        "licensure_disclosure_acknowledged": a["licensure_disclosure_acknowledged"],
        "status": a["status"],
        "decision_reason": a["decision_reason"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_tce(t):
    return {
        "id": t["id"],
        "application_id": t["application_id"],
        "status": t["status"],
        "accepted_credits": t["accepted_credits"],
        "in_progress_credits": t["in_progress_credits"],
        "capped_credits": t["capped_credits"],
        "remaining_credits": t["remaining_credits"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_enrollment(e):
    return {
        "id": e["id"],
        "application_id": e["application_id"],
        "term_id": e["term_id"],
        "advisor_id": e["advisor_id"],
        "enrollment_intensity": e["enrollment_intensity"],
        "tuition_cents": e["tuition_cents"],
        "status": e["status"],
        "financial_hold": financial_hold(e),
        "withdrawal_date": e["withdrawal_date"],
        "institutional_refund_cents": e["institutional_refund_cents"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_section(s):
    return {
        "id": s["id"],
        "term_id": s["term_id"],
        "course_code": s["course_code"],
        "capacity": s["capacity"],
        "forecast_enrollment": s["forecast_enrollment"],
        "adjuncts_required": s["adjuncts_required"],
        "adjunct_hires": s["adjunct_hires"],
        "enrolled_count": s["enrolled_count"],
        "seats_available": s["seats_available"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_package(p):
    schedule = [
        {
            "sequence": e["sequence"],
            "release_date": e["release_date"],
            "amount_cents": e["amount_cents"],
            "entry_status": e["entry_status"],
        }
        for e in p["disbursement_schedule"]
    ]
    return {
        "id": p["id"],
        "enrollment_id": p["enrollment_id"],
        "efc_cents": p["efc_cents"],
        "status": p["status"],
        "estimated_award_cents": p["estimated_award_cents"],
        "certified_award_cents": p["certified_award_cents"],
        "disbursement_schedule": schedule,
        "disbursed_cents": p["disbursed_cents"],
        "returned_cents": p["returned_cents"],
        "retained_cents": p["retained_cents"],
        "cancelled_cents": p["cancelled_cents"],
        "created_by_officer_id": p["created_by_officer_id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_alert(a):
    return {
        "id": a["id"],
        "enrollment_id": a["enrollment_id"],
        "trigger_type": a["trigger_type"],
        "observed_grade_percent": a["observed_grade_percent"],
        "days_late": a["days_late"],
        "severity": a["severity"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_outreach(o):
    return {
        "id": o["id"],
        "enrollment_id": o["enrollment_id"],
        "applicant_id": o["applicant_id"],
        "target_term_id": o["target_term_id"],
        "status": o["status"],
        "sent_at": o["sent_at"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


# ---------------------------------------------------------------------------
# Computed fields
# ---------------------------------------------------------------------------

def active_caseload_count(staff):
    """COUNSELOR: assigned applicants in PROSPECT/APPLIED/ADMITTED.
    ADVISOR: advisee enrollments in REGISTERED/ACTIVE/DEFERRED."""
    if staff["staff_type"] == "COUNSELOR":
        return sum(
            1
            for a in STORE.applicants.values()
            if a["assigned_counselor_id"] == staff["id"]
            and a["status"] in ("PROSPECT", "APPLIED", "ADMITTED")
        )
    return sum(
        1
        for e in STORE.enrollments.values()
        if e["advisor_id"] == staff["id"] and e["status"] in ("REGISTERED", "ACTIVE", "DEFERRED")
    )


def financial_hold(enrollment):
    """True iff the latest FinancialAidPackage is still PACKAGED and the
    current logical date is later than the term's census_date. Computed, not
    stored; never touches the store."""
    pkgs = [p for p in STORE.packages.values() if p["enrollment_id"] == enrollment["id"]]
    if not pkgs:
        return False
    latest = max(pkgs, key=lambda p: p["_seq"])
    if latest["status"] != "PACKAGED":
        return False
    term = STORE.terms.get(enrollment["term_id"])
    if term is None:
        return False
    return CLOCK.today() > parse_date(term["census_date"])


# ---------------------------------------------------------------------------
# State authorization
# ---------------------------------------------------------------------------

def current_auth_row(program_id, state_code):
    """The row whose half-open [effective_from, effective_to) window covers the
    current logical date; None if no row covers it."""
    today = CLOCK.today()
    for row in STORE.state_auths.values():
        if row["program_id"] != program_id or row["state_code"] != state_code:
            continue
        start = parse_date(row["effective_from"])
        end = parse_date(row["effective_to"]) if row["effective_to"] else None
        if start <= today and (end is None or today < end):
            return row
    return None


def auth_windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open window overlap; adjacency (a.from == b.to) is allowed."""
    # None = open-ended
    if a_to is not None and a_to <= b_from:
        return False
    if b_to is not None and b_to <= a_from:
        return False
    return True


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def counselor_assignment():
    """Rank COUNSELOR staff by (active count ASC, cap DESC, created_at ASC);
    winner is first; empty pool -> None (not an error)."""
    candidates = [
        s
        for s in STORE.staff.values()
        if s["staff_type"] == "COUNSELOR" and active_caseload_count(s) < s["caseload_cap"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (active_caseload_count(s), -s["caseload_cap"], s["_seq"]))
    return candidates[0]


def adjuncts_required(forecast_enrollment, capacity):
    shortfall = max(0, forecast_enrollment - capacity)
    return -(-shortfall // ADJUNCT_SECTION_SIZE)  # ceil


def degree_path(total_credits_required, accepted_credits, in_progress_credits):
    cap = (total_credits_required * TRANSFER_CAP_NUM) // TRANSFER_CAP_DEN  # floor
    capped = min(accepted_credits, cap)
    remaining = max(0, total_credits_required - capped - in_progress_credits)
    return capped, remaining


def award_packaging(efc_cents, intensity):
    coa = COA_BY_INTENSITY[intensity]
    return min(PELL_MAX_CENTS, max(0, coa - efc_cents))


def build_disbursement_schedule(certified_award_cents, term):
    """Two entries: half (floor) at census_date; remainder at the term midpoint
    (start + floor(total_days/2) days). The odd cent goes to the second entry."""
    start = parse_date(term["start_date"])
    end = parse_date(term["end_date"])
    total_days = (end - start).days + 1
    midpoint = start + timedelta(days=total_days // 2)
    first = certified_award_cents // 2
    return [
        {
            "sequence": 1,
            "release_date": term["census_date"],
            "amount_cents": first,
            "entry_status": "SCHEDULED",
        },
        {
            "sequence": 2,
            "release_date": midpoint.isoformat(),
            "amount_cents": certified_award_cents - first,
            "entry_status": "SCHEDULED",
        },
    ]


def recompute_package_totals(pkg):
    """disbursed = gross sum of DISBURSED or RETURNED entries;
    cancelled = sum of CANCELLED; retained = disbursed - returned."""
    disbursed = sum(
        e["amount_cents"]
        for e in pkg["disbursement_schedule"]
        if e["entry_status"] in ("DISBURSED", "RETURNED")
    )
    cancelled = sum(
        e["amount_cents"]
        for e in pkg["disbursement_schedule"]
        if e["entry_status"] == "CANCELLED"
    )
    pkg["disbursed_cents"] = disbursed
    pkg["cancelled_cents"] = cancelled
    pkg["retained_cents"] = disbursed - pkg["returned_cents"]


def r2t4_title_iv(disbursed_cents, term, withdrawal_date):
    """Pro-rata federal return with a strict > 0.60 earned cliff
    (earned == 0.60 still returns). Exact rational arithmetic, round half-up."""
    start = parse_date(term["start_date"])
    end = parse_date(term["end_date"])
    total_days = (end - start).days + 1
    days_done = (withdrawal_date - start).days + 1
    earned = Fraction(days_done, total_days)
    if earned > R2T4_EARNED_CLIFF:
        return 0
    value = disbursed_cents * (1 - earned)
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def r2t4_institutional(tuition_cents, term, withdrawal_date):
    """Step function on tuition keyed to census_date; round half-up on half."""
    census = parse_date(term["census_date"])
    if withdrawal_date <= census:
        return tuition_cents
    if withdrawal_date <= census + timedelta(days=INST_HALF_REFUND_WINDOW_DAYS):
        return (tuition_cents + 1) // 2
    return 0


# ---------------------------------------------------------------------------
# Lazy evaluation (PRD §2.10)
# ---------------------------------------------------------------------------

def lazy_release_package(pkg):
    """On any read or mutation of a package: SCHEDULED entries whose
    release_date <= current logical date transition to DISBURSED while the
    term is IN_SESSION. Bumps the package when anything changes."""
    if not pkg["disbursement_schedule"]:
        return
    enr = STORE.enrollments.get(pkg["enrollment_id"])
    term = STORE.terms.get(enr["term_id"]) if enr else None
    if term is None or term["status"] != "IN_SESSION":
        return
    today = CLOCK.today()
    changed = False
    for entry in pkg["disbursement_schedule"]:
        if entry["entry_status"] == "SCHEDULED" and parse_date(entry["release_date"]) <= today:
            entry["entry_status"] = "DISBURSED"
            changed = True
    if changed:
        recompute_package_totals(pkg)
        bump(pkg)


def lazy_expire_outreach(outreach):
    """QUEUED or SENT outreach expires when the current logical date passes the
    target term's start_date. target_term_id is not FK-validated, so a missing
    term means no expiry can be evaluated."""
    if outreach["status"] not in ("QUEUED", "SENT"):
        return
    term = STORE.terms.get(outreach["target_term_id"])
    if term is None:
        return
    if CLOCK.today() > parse_date(term["start_date"]):
        outreach["status"] = "EXPIRED"
        bump(outreach)


# ---------------------------------------------------------------------------
# Shared lookups
# ---------------------------------------------------------------------------

def packages_for_enrollment(enrollment_id):
    return [p for p in STORE.packages.values() if p["enrollment_id"] == enrollment_id]


def latest_non_void_tce(application_id):
    rows = [
        t for t in STORE.tces.values()
        if t["application_id"] == application_id and t["status"] != "VOID"
    ]
    if not rows:
        return None
    return max(rows, key=lambda t: t["_seq"])


def decimal_of(x):
    return Decimal(str(x))
