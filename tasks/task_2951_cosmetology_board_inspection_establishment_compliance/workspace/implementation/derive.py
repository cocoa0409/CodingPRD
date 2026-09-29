"""Constants, serializers, the compliance ledger and every derived quantity."""
from datetime import timedelta
from decimal import Decimal

import store
from store import iso
from validate import cents, d2, f2, iso_date

# --------------------------------------------------------------- constants
SEVERITY_WEIGHT = {
    "MINOR": Decimal("1.0"),
    "MAJOR": Decimal("2.5"),
    "CRITICAL": Decimal("5.0"),
    "IMMINENT_HAZARD": Decimal("8.0"),
}
SEVERITY_RANK = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3, "IMMINENT_HAZARD": 4}
REPEAT_LOOKBACK_DAYS = 730
PROVISIONAL_ON_SITE_CREDIT = Decimal("0.50")
FINAL_ON_SITE_CREDIT = Decimal("0.25")
PASS_CEILING = Decimal("10.00")
CONDITIONAL_PASS_CEILING = Decimal("40.00")

SCHOOL_DAILY_CAP_HOURS = Decimal("8.0")
APPRENTICE_WEEKLY_CAP_HOURS = Decimal("40.0")
APPRENTICE_CREDIT_RATIO = Decimal("0.60")
SCHOOL_EQUIVALENCE_RATIO = Decimal("1.00")
APPRENTICE_STANDALONE_REQUIRED_HOURS = Decimal("1600.00")
LICENSE_TERM_DAYS = 730

PER_POINT_SURCHARGE_CENTS = Decimal("400")
EXCESS_POINT_THRESHOLD = Decimal("30.00")
FINE_FLOOR_CENTS = 5000
FINE_CEILING_CENTS = 250000
SUBJECT_FACTOR = {"ESTABLISHMENT": Decimal("1.00"), "PRACTITIONER": Decimal("0.50")}
ADMIN_FEE_TIER_1_CEILING_CENTS = 25000
ADMIN_FEE_TIER_2_CEILING_CENTS = 100000
ADMIN_FEE_PCT_TIER_1 = Decimal("0.05")
ADMIN_FEE_PCT_TIER_2 = Decimal("0.08")
ADMIN_FEE_PCT_TIER_3 = Decimal("0.12")
PAYMENT_TERM_DAYS = 30
CONTEST_WINDOW_DAYS = 20
LATE_PENALTY_PCT = Decimal("0.10")
MAX_HEARING_ROUNDS = 2

WATCH_DEMERIT_THRESHOLD = Decimal("20.00")
RESTRICTED_DEMERIT_THRESHOLD = Decimal("50.00")
PROBATION_DEMERIT_THRESHOLD = Decimal("100.00")
REVOCATION_DEMERIT_THRESHOLD = Decimal("200.00")
BIOFILM_CURRENCY_DAYS = 7
HAZARD_CLEARANCE_MAX_SCORE = Decimal("10.00")

SUBSTANTIATED_SANCTION_POINTS = Decimal("10.00")
SANCTION_SUSPENSION_THRESHOLD = Decimal("15.00")

MULTI_CASE_THRESHOLD = 2
NOTIFY_WINDOW_HOURS_MULTI = 24
NOTIFY_WINDOW_HOURS_SINGLE = 72

MIN_CONTACT_MINUTES = {
    "IMPLEMENT_DISINFECTION": Decimal("10"),
    "FOOT_SPA_AFTER_CLIENT": Decimal("10"),
    "FOOT_SPA_END_OF_DAY": Decimal("10"),
    "FOOT_SPA_WEEKLY_BIOFILM": Decimal("360"),
}
FOOT_SPA_LOG_TYPES = ("FOOT_SPA_AFTER_CLIENT", "FOOT_SPA_END_OF_DAY", "FOOT_SPA_WEEKLY_BIOFILM")
IMPLEMENT_STATION_TYPES = ("STYLING_CHAIR", "NAIL_TABLE", "FACIAL_ROOM")
FOOT_SPA_CYCLE_GAP_MINUTES = 5
INSPECTION_COOLDOWN_HOURS = 24

OPERABLE_STATUSES = ("PENDING_INSPECTION", "ACTIVE", "PROBATION")
NON_TERMINAL_INSPECTION = ("SCHEDULED", "IN_PROGRESS", "PENDING_REVIEW")
CLOSED_CITATION_STATUSES = ("DISMISSED", "SETTLED")

ESTABLISHMENT_TYPES = ("SALON", "BARBERSHOP", "NAIL_SALON", "ESTHETICS_SPA", "SCHOOL_CLINIC")
LICENSE_STATUSES_EST = (
    "PENDING_INSPECTION", "ACTIVE", "PROBATION", "SUSPENDED", "CLOSED_IMMINENT_HAZARD", "REVOKED",
)
POSTURES = ("CLEAR", "WATCH", "RESTRICTED", "FROZEN")
LICENSE_TYPES = ("COSMETOLOGIST", "BARBER", "NAIL_TECHNICIAN", "ESTHETICIAN", "INSTRUCTOR", "APPRENTICE")
SPONSOR_LICENSE_TYPES = ("COSMETOLOGIST", "BARBER", "NAIL_TECHNICIAN", "ESTHETICIAN", "INSTRUCTOR")
PRAC_STATUSES = ("STUDENT", "EXAM_ELIGIBLE", "ACTIVE", "PROBATION", "SUSPENDED", "LAPSED", "REVOKED")
ACCREDITATION_STATUSES = ("ACCREDITED", "PROBATIONARY", "WITHDRAWN")
CREDIT_TYPES = ("SCHOOL_CLOCK_HOUR", "APPRENTICE_HOUR")
DISCIPLINES = ("THEORY", "PRACTICAL", "SANITATION", "DISINFECTION", "BUSINESS_LAW")
STATION_TYPES = ("STYLING_CHAIR", "NAIL_TABLE", "FOOT_SPA", "FACIAL_ROOM")
POSTING_STATUSES = ("MISSING_POSTING", "STALE_POSTING", "COMPLIANT")
RENTAL_TYPES = ("EMPLOYEE", "BOOTH_RENTER_INDEPENDENT_CONTRACTOR")
RENTAL_STATUSES = ("PROPOSED", "ACTIVE", "TERMINATED", "VOIDED")
INSPECTION_TYPES = ("ROUTINE", "COMPLAINT_DRIVEN", "REINSPECTION")
INSPECTION_STATUSES = ("SCHEDULED", "IN_PROGRESS", "PENDING_REVIEW", "FINALIZED")
HAZARD_STATES = ("NONE", "HAZARD_DECLARED", "HAZARD_CLEARED")
OUTCOMES = ("PASS", "CONDITIONAL_PASS", "FAIL", "IMMEDIATE_CLOSURE")
VIOLATION_CATEGORIES = (
    "SANITATION", "DISINFECTION", "IMPLEMENT_HANDLING", "FOOT_SPA",
    "LICENSING_POSTING", "FACILITY", "EQUIPMENT", "RECORDKEEPING",
)
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL", "IMMINENT_HAZARD")
SUBJECT_TYPES = ("ESTABLISHMENT", "PRACTITIONER")
CITATION_STATUSES = (
    "ISSUED", "CONTESTED", "HEARING_SCHEDULED", "AFFIRMED", "AMENDED",
    "DISMISSED", "SETTLED", "DELINQUENT",
)
DECISIONS = ("AFFIRMED", "AMENDED", "DISMISSED")
LOG_TYPES = ("IMPLEMENT_DISINFECTION", "FOOT_SPA_AFTER_CLIENT", "FOOT_SPA_END_OF_DAY", "FOOT_SPA_WEEKLY_BIOFILM")
INCIDENT_STATUSES = (
    "REPORTED", "NOTIFIED", "ESCALATED_OVERDUE", "RESOLVED_SUBSTANTIATED", "RESOLVED_UNSUBSTANTIATED",
)
RESOLUTIONS = ("SUBSTANTIATED", "UNSUBSTANTIATED")
LEDGER_TYPES = ("FINE_CENTS", "DEMERIT_POINTS", "SANCTION_POINTS")
ENTRY_REASONS = (
    "CITATION_ASSESSMENT", "CITATION_PAYMENT", "CITATION_LATE_PENALTY",
    "CITATION_AMENDMENT_ADJUSTMENT", "CITATION_DISMISSAL_REVERSAL",
    "INSPECTION_DEMERIT_ASSESSMENT", "INSPECTION_DEMERIT_REVERSAL",
    "INFECTION_SANCTION_ASSESSMENT", "REINSTATEMENT_SANCTION_REVERSAL",
)
LICENSE_ACTIONS = (
    "GRANT_EXAM_ELIGIBILITY", "ISSUE_LICENSE", "PLACE_ON_PROBATION",
    "SUSPEND", "REINSTATE", "REVOKE",
)
LICENSE_ACTION_LEGAL_FROM = {
    "GRANT_EXAM_ELIGIBILITY": ("STUDENT",),
    "ISSUE_LICENSE": ("EXAM_ELIGIBLE",),
    "PLACE_ON_PROBATION": ("ACTIVE",),
    "SUSPEND": ("ACTIVE", "PROBATION"),
    "REINSTATE": ("PROBATION", "SUSPENDED", "LAPSED"),
    "REVOKE": ("ACTIVE", "PROBATION", "SUSPENDED"),
}


# -------------------------------------------------------------- serializers
def ser_establishment(e):
    return {
        "id": e["id"],
        "legal_name": e["legal_name"],
        "establishment_type": e["establishment_type"],
        "county_code": e["county_code"],
        "station_capacity": e["station_capacity"],
        "station_count": e["station_count"],
        "license_status": e["license_status"],
        "compliance_posture": e["compliance_posture"],
        "demerit_balance": f2(e["demerit_balance"]),
        "open_critical_citation_count": e["open_critical_citation_count"],
        "outstanding_fine_total_cents": e["outstanding_fine_total_cents"],
        "delinquent_fine_total_cents": e["delinquent_fine_total_cents"],
        "foot_spa_biofilm_current": e["foot_spa_biofilm_current"],
        "last_finalized_inspection_at": iso(e["last_finalized_inspection_at"]),
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def ser_practitioner(p):
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "license_type": p["license_type"],
        "school_id": p["school_id"],
        "license_status": p["license_status"],
        "license_expires_on": iso_date(p["license_expires_on"]),
        "credited_hours_school": f2(p["credited_hours_school"]),
        "credited_hours_apprentice": f2(p["credited_hours_apprentice"]),
        "credited_hours_total": f2(p["credited_hours_total"]),
        "required_clock_hours_effective": f2(p["required_clock_hours_effective"]),
        "exam_eligible": p["exam_eligible"],
        "sanction_points": f2(p["sanction_points"]),
        "suspension_cause_points": f2(p["suspension_cause_points"]) if p["suspension_cause_points"] is not None else None,
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def ser_school(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "county_code": s["county_code"],
        "required_clock_hours": f2(s["required_clock_hours"]),
        "accreditation_status": s["accreditation_status"],
        "apprenticeship_program_approved": s["apprenticeship_program_approved"],
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def ser_training_record(t):
    return {
        "id": t["id"],
        "practitioner_id": t["practitioner_id"],
        "credit_type": t["credit_type"],
        "hours": f2(t["hours"]),
        "performed_on": iso_date(t["performed_on"]),
        "discipline": t["discipline"],
        "school_id": t["school_id"],
        "sponsor_practitioner_id": t["sponsor_practitioner_id"],
        "created_at": iso(t["created_at"]),
    }


def ser_workstation(w):
    return {
        "id": w["id"],
        "establishment_id": w["establishment_id"],
        "station_number": w["station_number"],
        "station_type": w["station_type"],
        "posted_practitioner_id": w["posted_practitioner_id"],
        "posting_status": w["posting_status"],
        "last_biofilm_cycle_at": iso(w["last_biofilm_cycle_at"]),
        "created_at": iso(w["created_at"]),
        "updated_at": iso(w["updated_at"]),
        "version": w["version"],
    }


def ser_booth_rental(r):
    return {
        "id": r["id"],
        "workstation_id": r["workstation_id"],
        "practitioner_id": r["practitioner_id"],
        "rental_type": r["rental_type"],
        "term_start_at": iso(r["term_start_at"]),
        "term_end_at": iso(r["term_end_at"]),
        "monthly_rent_cents": r["monthly_rent_cents"],
        "status": r["status"],
        "terminated_at": iso(r["terminated_at"]),
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def ser_inspection(i):
    return {
        "id": i["id"],
        "establishment_id": i["establishment_id"],
        "inspection_type": i["inspection_type"],
        "reinspection_of_id": i["reinspection_of_id"],
        "inspector_user_id": i["inspector_user_id"],
        "complaint_reference": i["complaint_reference"],
        "window_start_at": iso(i["window_start_at"]),
        "window_end_at": iso(i["window_end_at"]),
        "status": i["status"],
        "hazard_state": i["hazard_state"],
        "started_at": iso(i["started_at"]),
        "submitted_at": iso(i["submitted_at"]),
        "finalized_at": iso(i["finalized_at"]),
        "finding_count": i["finding_count"],
        "provisional_adjusted_score": f2(i["provisional_adjusted_score"]) if i["provisional_adjusted_score"] is not None else None,
        "final_adjusted_score": f2(i["final_adjusted_score"]) if i["final_adjusted_score"] is not None else None,
        "provisional_outcome": i["provisional_outcome"],
        "final_outcome": i["final_outcome"],
        "demerit_balance_before_finalize": f2(i["demerit_balance_before_finalize"]) if i["demerit_balance_before_finalize"] is not None else None,
        "citation_count": i["citation_count"],
        "created_at": iso(i["created_at"]),
        "updated_at": iso(i["updated_at"]),
        "version": i["version"],
    }


def ser_violation_code(v):
    return {
        "id": v["id"],
        "code": v["code"],
        "category": v["category"],
        "severity": v["severity"],
        "base_points": f2(v["base_points"]),
        "fine_cents_base": v["fine_cents_base"],
        "created_at": iso(v["created_at"]),
    }


def ser_finding(f):
    return {
        "id": f["id"],
        "inspection_id": f["inspection_id"],
        "violation_code_id": f["violation_code_id"],
        "attributed_practitioner_id": f["attributed_practitioner_id"],
        "workstation_id": f["workstation_id"],
        "observed_count": f["observed_count"],
        "corrected_on_site": f["corrected_on_site"],
        "severity": f["severity"],
        "repeat_factor_provisional": float(f["repeat_factor_provisional"]) if f["repeat_factor_provisional"] is not None else None,
        "repeat_factor_final": float(f["repeat_factor_final"]) if f["repeat_factor_final"] is not None else None,
        "provisional_points": f2(f["provisional_points"]) if f["provisional_points"] is not None else None,
        "final_points": f2(f["final_points"]) if f["final_points"] is not None else None,
        "declared_hazard": f["declared_hazard"],
        "note": f["note"],
        "created_at": iso(f["created_at"]),
        "updated_at": iso(f["updated_at"]),
        "version": f["version"],
    }


def ser_citation(c):
    return {
        "id": c["id"],
        "inspection_id": c["inspection_id"],
        "subject_type": c["subject_type"],
        "subject_practitioner_id": c["subject_practitioner_id"],
        "citation_number": c["citation_number"],
        "max_finding_severity": c["max_finding_severity"],
        "demerit_tier_multiplier": float(c["demerit_tier_multiplier"]),
        "assessed_fine_cents": c["assessed_fine_cents"],
        "administrative_fee_cents": c["administrative_fee_cents"],
        "total_due_cents": c["total_due_cents"],
        "outstanding_fine_cents": c["outstanding_fine_cents"],
        "status": c["status"],
        "issued_at": iso(c["issued_at"]),
        "due_at": iso(c["due_at"]),
        "contest_deadline_at": iso(c["contest_deadline_at"]),
        "hearing_round_count": c["hearing_round_count"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_hearing(h):
    return {
        "id": h["id"],
        "citation_id": h["citation_id"],
        "presiding_officer_user_id": h["presiding_officer_user_id"],
        "scheduled_at": iso(h["scheduled_at"]),
        "status": h["status"],
        "decision": h["decision"],
        "amended_fine_cents": h["amended_fine_cents"],
        "rationale": h["rationale"],
        "round_index": h["round_index"],
        "decided_at": iso(h["decided_at"]),
        "created_at": iso(h["created_at"]),
        "updated_at": iso(h["updated_at"]),
        "version": h["version"],
    }


def ser_sanitation_log(s):
    return {
        "id": s["id"],
        "workstation_id": s["workstation_id"],
        "log_type": s["log_type"],
        "performed_at": iso(s["performed_at"]),
        "contact_minutes": f2(s["contact_minutes"]),
        "disinfectant_epa_reg_number": s["disinfectant_epa_reg_number"],
        "implement_batch_count": s["implement_batch_count"],
        "occupancy_end_at": iso(s["occupancy_end_at"]),
        "created_at": iso(s["created_at"]),
    }


def ser_incident(i):
    return {
        "id": i["id"],
        "establishment_id": i["establishment_id"],
        "suspected_practitioner_id": i["suspected_practitioner_id"],
        "case_count": i["case_count"],
        "onset_date": iso_date(i["onset_date"]),
        "narrative": i["narrative"],
        "status": i["status"],
        "reported_at": iso(i["reported_at"]),
        "notification_deadline_at": iso(i["notification_deadline_at"]),
        "notified_at": iso(i["notified_at"]),
        "health_authority_reference": i["health_authority_reference"],
        "findings_summary": i["findings_summary"],
        "created_at": iso(i["created_at"]),
        "updated_at": iso(i["updated_at"]),
        "version": i["version"],
    }


def ser_ledger_entry(l):
    return {
        "id": l["id"],
        "ledger_type": l["ledger_type"],
        "entry_reason": l["entry_reason"],
        "delta_cents": l["delta_cents"],
        "delta_points": f2(l["delta_points"]) if l["delta_points"] is not None else None,
        "citation_id": l["citation_id"],
        "establishment_id": l["establishment_id"],
        "practitioner_id": l["practitioner_id"],
        "inspection_id": l["inspection_id"],
        "occurred_at": iso(l["occurred_at"]),
        "created_at": iso(l["created_at"]),
    }


# ------------------------------------------------------------------- ledger
def post_ledger(ledger_type, entry_reason, delta_cents=None, delta_points=None,
                citation_id=None, establishment_id=None, practitioner_id=None,
                inspection_id=None):
    row = store.make_row(with_common=False)
    row.update({
        "ledger_type": ledger_type,
        "entry_reason": entry_reason,
        "delta_cents": int(delta_cents) if delta_cents is not None else None,
        "delta_points": d2(delta_points) if delta_points is not None else None,
        "citation_id": citation_id,
        "establishment_id": establishment_id,
        "practitioner_id": practitioner_id,
        "inspection_id": inspection_id,
        "occurred_at": store.now_utc(),
    })
    store.ledger_entries[row["id"]] = row
    return row


def citation_outstanding(citation_id):
    total = 0
    for l in store.ledger_entries.values():
        if l["ledger_type"] == "FINE_CENTS" and l["citation_id"] == citation_id:
            total += l["delta_cents"]
    return total


def recompute_citation_outstanding(cit):
    cit["outstanding_fine_cents"] = citation_outstanding(cit["id"])
    return cit["outstanding_fine_cents"]


def establishment_demerit_balance(establishment_id):
    total = Decimal("0")
    for l in store.ledger_entries.values():
        if l["ledger_type"] == "DEMERIT_POINTS" and l["establishment_id"] == establishment_id:
            total += l["delta_points"]
    return d2(total)


def practitioner_sanction_points(practitioner_id):
    total = Decimal("0")
    for l in store.ledger_entries.values():
        if l["ledger_type"] == "SANCTION_POINTS" and l["practitioner_id"] == practitioner_id:
            total += l["delta_points"]
    return d2(total)


# ------------------------------------------------------- collection accessors
def workstations_of(establishment_id):
    return [w for w in store.workstations.values() if w["establishment_id"] == establishment_id]


def rentals_of_workstation(ws_id):
    return [r for r in store.booth_rentals.values() if r["workstation_id"] == ws_id]


def rentals_of_establishment(establishment_id):
    ws_ids = set(w["id"] for w in workstations_of(establishment_id))
    return [r for r in store.booth_rentals.values() if r["workstation_id"] in ws_ids]


def rentals_of_practitioner(practitioner_id):
    return [r for r in store.booth_rentals.values() if r["practitioner_id"] == practitioner_id]


def inspections_of(establishment_id):
    return [i for i in store.inspections.values() if i["establishment_id"] == establishment_id]


def findings_of(inspection_id):
    rows = [f for f in store.violation_findings.values() if f["inspection_id"] == inspection_id]
    rows.sort(key=lambda f: (f["created_at"], f["_seq"]))
    return rows


def citations_of_inspection(inspection_id):
    return [c for c in store.citations.values() if c["inspection_id"] == inspection_id]


def citations_of_establishment(establishment_id):
    insp_ids = set(i["id"] for i in inspections_of(establishment_id))
    return [c for c in store.citations.values() if c["inspection_id"] in insp_ids]


def logs_of_workstation(ws_id):
    rows = [s for s in store.sanitation_logs.values() if s["workstation_id"] == ws_id]
    rows.sort(key=lambda s: (s["performed_at"], s["created_at"], s["_seq"]))
    return rows


def training_records_of(practitioner_id):
    rows = [t for t in store.training_records.values() if t["practitioner_id"] == practitioner_id]
    rows.sort(key=lambda t: (t["performed_on"], t["created_at"], t["_seq"]))
    return rows


def hearings_of_citation(citation_id):
    rows = [h for h in store.hearings.values() if h["citation_id"] == citation_id]
    rows.sort(key=lambda h: h["round_index"])
    return rows


# ---------------------------------------------------- workstation derivation
def compute_workstation(ws):
    """PRD 3.3: derive posting_status and last_biofilm_cycle_at (no version bump)."""
    biofilm = [s for s in store.sanitation_logs.values()
               if s["workstation_id"] == ws["id"] and s["log_type"] == "FOOT_SPA_WEEKLY_BIOFILM"]
    if biofilm:
        biofilm.sort(key=lambda s: (s["performed_at"], s["created_at"], s["_seq"]), reverse=True)
        ws["last_biofilm_cycle_at"] = biofilm[0]["performed_at"]
    else:
        ws["last_biofilm_cycle_at"] = None

    pid = ws.get("posted_practitioner_id")
    if pid is None:
        ws["posting_status"] = "MISSING_POSTING"
        return ws
    now = store.now_utc()
    p = store.practitioners.get(pid)
    valid = False
    if p is not None and p["license_status"] == "ACTIVE":
        expires = p["license_expires_on"]
        if expires is not None and expires >= now.date():
            for r in rentals_of_workstation(ws["id"]):
                if r["practitioner_id"] != pid or r["status"] != "ACTIVE":
                    continue
                if r["term_start_at"] <= now and (r["term_end_at"] is None or now < r["term_end_at"]):
                    valid = True
                    break
    ws["posting_status"] = "COMPLIANT" if valid else "STALE_POSTING"
    return ws


def ws_snapshot(ws):
    return (ws["posting_status"], ws["last_biofilm_cycle_at"], ws["posted_practitioner_id"])


# -------------------------------------------------- establishment derivation
def foot_spa_biofilm_current(establishment_id):
    cutoff = store.now_utc() - timedelta(days=BIOFILM_CURRENCY_DAYS)
    spas = [w for w in workstations_of(establishment_id) if w["station_type"] == "FOOT_SPA"]
    if not spas:
        return True
    for w in spas:
        fresh = False
        for s in store.sanitation_logs.values():
            if (s["workstation_id"] == w["id"]
                    and s["log_type"] == "FOOT_SPA_WEEKLY_BIOFILM"
                    and s["performed_at"] >= cutoff):
                fresh = True
                break
        if not fresh:
            return False
    return True


def compute_establishment(e):
    """PRD 2.6: recompute the whole derived summary (no version bump)."""
    eid = e["id"]
    e["station_count"] = len(workstations_of(eid))
    e["demerit_balance"] = establishment_demerit_balance(eid)

    cits = citations_of_establishment(eid)
    open_cits = [c for c in cits if c["status"] not in CLOSED_CITATION_STATUSES]
    e["outstanding_fine_total_cents"] = sum(c["outstanding_fine_cents"] for c in open_cits)
    e["delinquent_fine_total_cents"] = sum(
        c["outstanding_fine_cents"] for c in cits if c["status"] == "DELINQUENT")
    e["open_critical_citation_count"] = len(
        [c for c in open_cits if c["max_finding_severity"] in ("CRITICAL", "IMMINENT_HAZARD")])
    e["foot_spa_biofilm_current"] = foot_spa_biofilm_current(eid)

    finalized = [i for i in inspections_of(eid) if i["status"] == "FINALIZED" and i["finalized_at"]]
    if finalized:
        finalized.sort(key=lambda i: (i["finalized_at"], i["created_at"], i["_seq"]), reverse=True)
        e["last_finalized_inspection_at"] = finalized[0]["finalized_at"]
    else:
        e["last_finalized_inspection_at"] = None

    balance = e["demerit_balance"]
    if e["license_status"] in ("SUSPENDED", "CLOSED_IMMINENT_HAZARD", "REVOKED") \
            or balance >= PROBATION_DEMERIT_THRESHOLD:
        e["compliance_posture"] = "FROZEN"
    elif balance >= RESTRICTED_DEMERIT_THRESHOLD or e["open_critical_citation_count"] >= 1:
        e["compliance_posture"] = "RESTRICTED"
    elif balance >= WATCH_DEMERIT_THRESHOLD:
        e["compliance_posture"] = "WATCH"
    else:
        e["compliance_posture"] = "CLEAR"
    return e


def est_snapshot(e):
    return (
        e["license_status"], e["compliance_posture"], e["station_count"], e["demerit_balance"],
        e["open_critical_citation_count"], e["outstanding_fine_total_cents"],
        e["delinquent_fine_total_cents"], e["foot_spa_biofilm_current"],
        e["last_finalized_inspection_at"],
    )


def refresh_establishment(e, force=True):
    """Recompute derived fields; bump version when something moved (or when forced)."""
    before = est_snapshot(e)
    compute_establishment(e)
    if force or est_snapshot(e) != before:
        store.bump(e)
    return e


def refresh_workstation(ws, force=True):
    before = ws_snapshot(ws)
    compute_workstation(ws)
    if force or ws_snapshot(ws) != before:
        store.bump(ws)
    return ws


# --------------------------------------------------- practitioner derivation
def _capped_by_day(records, cap):
    by_day = {}
    for t in records:
        by_day[t["performed_on"]] = by_day.get(t["performed_on"], Decimal("0")) + t["hours"]
    total = Decimal("0")
    for key in sorted(by_day):
        total += min(by_day[key], cap)
    return total


def compute_practitioner(p):
    """PRD 3.2: recompute the whole credited-hour ledger and eligibility."""
    recs = training_records_of(p["id"])

    school_recs = [t for t in recs if t["credit_type"] == "SCHOOL_CLOCK_HOUR"]
    p["credited_hours_school"] = d2(_capped_by_day(school_recs, SCHOOL_DAILY_CAP_HOURS))

    appr_recs = [t for t in recs if t["credit_type"] == "APPRENTICE_HOUR"]
    if p["license_type"] == "APPRENTICE":
        by_week = {}
        for t in appr_recs:
            iso_year, iso_week, _ = t["performed_on"].isocalendar()
            key = (iso_year, iso_week)
            by_week[key] = by_week.get(key, Decimal("0")) + t["hours"]
        total = Decimal("0")
        for key in sorted(by_week):
            capped = min(by_week[key], APPRENTICE_WEEKLY_CAP_HOURS)
            total += d2(capped * APPRENTICE_CREDIT_RATIO)
        p["credited_hours_apprentice"] = d2(total)
    else:
        total = _capped_by_day(appr_recs, SCHOOL_DAILY_CAP_HOURS) * SCHOOL_EQUIVALENCE_RATIO
        p["credited_hours_apprentice"] = d2(total)

    p["credited_hours_total"] = d2(p["credited_hours_school"] + p["credited_hours_apprentice"])

    school = store.schools.get(p["school_id"]) if p["school_id"] else None
    if school is not None:
        p["required_clock_hours_effective"] = d2(school["required_clock_hours"])
    else:
        p["required_clock_hours_effective"] = APPRENTICE_STANDALONE_REQUIRED_HOURS

    p["exam_eligible"] = p["credited_hours_total"] >= p["required_clock_hours_effective"]
    p["sanction_points"] = practitioner_sanction_points(p["id"])
    return p


def prac_snapshot(p):
    return (
        p["license_status"], p["license_expires_on"], p["credited_hours_school"],
        p["credited_hours_apprentice"], p["credited_hours_total"],
        p["required_clock_hours_effective"], p["exam_eligible"], p["sanction_points"],
        p["suspension_cause_points"],
    )


def refresh_practitioner(p, force=True):
    before = prac_snapshot(p)
    compute_practitioner(p)
    if force or prac_snapshot(p) != before:
        store.bump(p)
    return p


# -------------------------------------------------------- cascade primitives
def clear_posting_if(ws, practitioner_id):
    """Clear a station's posting when it names this practitioner (PRD 3.2/3.3/3.7)."""
    if ws is None or ws["posted_practitioner_id"] != practitioner_id:
        return False
    ws["posted_practitioner_id"] = None
    compute_workstation(ws)
    store.bump(ws)
    return True


def practitioner_personnel_cascade(practitioner_id, at):
    """Suspension/revocation cascade: ACTIVE -> TERMINATED, PROPOSED -> VOIDED."""
    for r in rentals_of_practitioner(practitioner_id):
        if r["status"] == "ACTIVE":
            r["status"] = "TERMINATED"
        elif r["status"] == "PROPOSED":
            r["status"] = "VOIDED"
        else:
            continue
        r["terminated_at"] = at
        store.bump(r)
        clear_posting_if(store.workstations.get(r["workstation_id"]), practitioner_id)


def establishment_personnel_cascade(establishment_id, mode, at):
    """PRD 3.7 hop five: PROBATION voids PROPOSED; REVOKED also terminates ACTIVE."""
    for r in rentals_of_establishment(establishment_id):
        if r["status"] == "PROPOSED":
            r["status"] = "VOIDED"
        elif mode == "REVOKED" and r["status"] == "ACTIVE":
            r["status"] = "TERMINATED"
        else:
            continue
        r["terminated_at"] = at
        store.bump(r)
        clear_posting_if(store.workstations.get(r["workstation_id"]), r["practitioner_id"])


def repost_practitioner_stations(practitioner_id):
    """Recompute the posting verdict on every station posting this practitioner."""
    for ws in store.workstations.values():
        if ws["posted_practitioner_id"] == practitioner_id:
            refresh_workstation(ws, force=False)


def auto_suspend_practitioner(p, at):
    """PRD 3.9: sanction points at or above 15.00 suspend an ACTIVE/PROBATION licence."""
    if p["sanction_points"] < SANCTION_SUSPENSION_THRESHOLD:
        return False
    if p["license_status"] not in ("ACTIVE", "PROBATION"):
        return False
    p["license_status"] = "SUSPENDED"
    p["suspension_cause_points"] = d2(p["sanction_points"])
    practitioner_personnel_cascade(p["id"], at)
    return True


# ------------------------------------------------------- inspection scoring
def repeat_count(finding, establishment_id, cutoff):
    """PRD 3.5: prior findings of the same code on other FINALIZED inspections."""
    low = cutoff - timedelta(days=REPEAT_LOOKBACK_DAYS)
    count = 0
    for other in store.violation_findings.values():
        if other["inspection_id"] == finding["inspection_id"]:
            continue
        if other["violation_code_id"] != finding["violation_code_id"]:
            continue
        insp = store.inspections.get(other["inspection_id"])
        if insp is None or insp["establishment_id"] != establishment_id:
            continue
        if insp["status"] != "FINALIZED":
            continue
        fin = insp["finalized_at"]
        if fin is None:
            continue
        if low <= fin < cutoff:
            count += 1
    return count


def repeat_factor(count):
    if count == 0:
        return Decimal("1.0")
    if count == 1:
        return Decimal("1.5")
    return Decimal("2.0")


def outcome_band(insp, score, findings):
    """PRD 3.5: strict-order outcome band for one variant's score."""
    if insp["hazard_state"] == "HAZARD_DECLARED":
        return "IMMEDIATE_CLOSURE"
    severities = set(f["severity"] for f in findings)
    if score > CONDITIONAL_PASS_CEILING or "CRITICAL" in severities or "IMMINENT_HAZARD" in severities:
        return "FAIL"
    if score > PASS_CEILING:
        return "CONDITIONAL_PASS"
    return "PASS"


def score_inspection(insp, variant):
    """One calculation, two variants (PRD 3.5).  Rounds per finding, then the sum."""
    if variant == "provisional":
        cutoff = insp["submitted_at"]
        credit_rate = PROVISIONAL_ON_SITE_CREDIT
        factor_field, points_field = "repeat_factor_provisional", "provisional_points"
        score_field, outcome_field = "provisional_adjusted_score", "provisional_outcome"
    else:
        cutoff = insp["finalized_at"]
        credit_rate = FINAL_ON_SITE_CREDIT
        factor_field, points_field = "repeat_factor_final", "final_points"
        score_field, outcome_field = "final_adjusted_score", "final_outcome"

    findings = findings_of(insp["id"])
    total = Decimal("0")
    for f in findings:
        code = store.violation_codes[f["violation_code_id"]]
        rf = repeat_factor(repeat_count(f, insp["establishment_id"], cutoff))
        if f["corrected_on_site"] and f["severity"] in ("MINOR", "MAJOR"):
            credit = credit_rate
        else:
            credit = Decimal("0.00")
        points = d2(code["base_points"]
                    * SEVERITY_WEIGHT[f["severity"]]
                    * Decimal(f["observed_count"])
                    * rf
                    * (Decimal("1") - credit))
        f[factor_field] = rf
        f[points_field] = points
        store.bump(f)
        total += points

    score = d2(total)
    insp[score_field] = score
    insp[outcome_field] = outcome_band(insp, score, findings)
    return score


def max_finding_severity(findings):
    best = None
    for f in findings:
        if best is None or SEVERITY_RANK[f["severity"]] > SEVERITY_RANK[best]:
            best = f["severity"]
    return best


# ------------------------------------------------------------ citation money
def demerit_tier_multiplier(snapshot):
    """PRD 3.7: tier read from the pre-finalize demerit snapshot."""
    if snapshot is None:
        snapshot = Decimal("0.00")
    if snapshot >= REVOCATION_DEMERIT_THRESHOLD:
        return Decimal("2.00")
    if snapshot >= RESTRICTED_DEMERIT_THRESHOLD:
        return Decimal("1.60")
    if snapshot >= WATCH_DEMERIT_THRESHOLD:
        return Decimal("1.25")
    return Decimal("1.00")


def admin_fee_cents(assessed_fine_cents):
    """PRD 3.7 step two/three: the fee percentage is keyed on the assessed fine alone."""
    if assessed_fine_cents <= ADMIN_FEE_TIER_1_CEILING_CENTS:
        pct = ADMIN_FEE_PCT_TIER_1
    elif assessed_fine_cents <= ADMIN_FEE_TIER_2_CEILING_CENTS:
        pct = ADMIN_FEE_PCT_TIER_2
    else:
        pct = ADMIN_FEE_PCT_TIER_3
    return cents(Decimal(assessed_fine_cents) * pct)


def assess_citation_fine(insp, subject_type, snapshot, findings):
    """PRD 3.7: base + surcharge + tier + subject factor, clamped into the band."""
    base = 0
    for f in findings:
        base += store.violation_codes[f["violation_code_id"]]["fine_cents_base"]
    score = insp["final_adjusted_score"] or Decimal("0.00")
    excess = score - EXCESS_POINT_THRESHOLD
    if excess < 0:
        excess = Decimal("0")
    surcharge = cents(excess * PER_POINT_SURCHARGE_CENTS)
    tier = demerit_tier_multiplier(snapshot)
    raw = cents(Decimal(base) * tier * SUBJECT_FACTOR[subject_type]) + surcharge
    assessed = raw
    if assessed < FINE_FLOOR_CENTS:
        assessed = FINE_FLOOR_CENTS
    if assessed > FINE_CEILING_CENTS:
        assessed = FINE_CEILING_CENTS
    return tier, assessed


# -------------------------------------------------------------- misc derived
def notification_deadline(reported_at, case_count):
    """PRD 3.9: 24h for a cluster of two or more cases, 72h for a single case."""
    hours = NOTIFY_WINDOW_HOURS_MULTI if case_count >= MULTI_CASE_THRESHOLD else NOTIFY_WINDOW_HOURS_SINGLE
    return reported_at + timedelta(hours=hours)


def establishment_of_citation(cit):
    insp = store.inspections.get(cit["inspection_id"])
    if insp is None:
        return None
    return store.establishments.get(insp["establishment_id"])
