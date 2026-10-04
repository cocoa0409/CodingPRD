"""Shared domain helpers: enums, validators, getters, lazy expiry, derived
fields, documentation predicate, system audit notes, and serializers."""
from datetime import timedelta

from flask import request

from errors import ApiError
from store import db
from util import now, new_id, fmt_dt, parse_dt, parse_day

# ---------------------------------------------------------------------------
# Enums and constants (from SCAFFOLD.yaml / PRD.md)
# ---------------------------------------------------------------------------
BRANCHES = ("ARMY", "NAVY", "AIR_FORCE", "MARINES", "COAST_GUARD", "SPACE_FORCE")
COMPONENTS = ("ARMY_RESERVE", "NAVY_RESERVE", "MARINE_RESERVE", "ARMY_GUARD", "AIR_GUARD")
SECTORS = ("MANUFACTURING", "RETAIL", "HEALTHCARE", "LOGISTICS", "GOVERNMENT",
           "CONSTRUCTION", "HOSPITALITY", "TECHNOLOGY")
SIZE_TIERS = ("SMALL", "MEDIUM", "LARGE")
ORDERS_TYPES = ("DRILL", "ANNUAL_TRAINING", "ACTIVE_DUTY", "NATIONAL_EMERGENCY",
                "PRESIDENTIAL_CALLUP")
ISSUE_TYPES = ("REEMPLOYMENT", "BENEFITS", "PENSION", "DISCRIMINATION", "RETALIATION")
EXCUSE_CATEGORIES = ("ORDERS_SHORT_FUSE", "OPERATIONAL_NECESSITY", "CLASSIFIED_MISSION")
CASE_STATUSES = ("INTAKE", "TRIAGE", "ASSIGNED", "IN_MEDIATION", "AWAITING_RESPONSE",
                 "ESCALATION_PENDING", "RESOLVED_INFORMAL", "REFERRED",
                 "CLOSED_WITHDRAWN", "CLOSED_UNRESOLVED")
OMBUDSMAN_STATUSES = ("TRAINEE", "CERTIFIED", "ON_LEAVE", "EXPIRED", "DECERTIFIED")
ADDRESSED_TO = ("EMPLOYER", "MEMBER")
RESPONSES = ("ACCEPT", "COUNTER", "DECLINE")
NOTE_TYPES = ("INTAKE", "CONTACT", "EMPLOYER_EDUCATION", "RESOLUTION", "AUDIT")
VARIANTS = ("STRICT", "LENIENT")
AGENCIES = ("DOL_VETS", "DOJ_CIVIL_RIGHTS", "OPM")
REFERRAL_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED_FOR_INFO", "ACKNOWLEDGED", "WITHDRAWN")
STATEMENT_STATUSES = ("PLEDGED", "SIGNED", "LAPSED", "REVOKED")
AWARD_TIERS = ("BRONZE", "SILVER", "GOLD")
AWARD_STATUSES = ("NOMINATED", "VETTED", "CONFERRED", "DECLINED")
EVENT_TOPICS = ("RIGHTS_OVERVIEW", "BENEFITS_BRIEFING", "EMPLOYER_RECOGNITION", "HIRING_FAIR")
EVENT_STATUSES = ("PLANNED", "OPEN", "CONCLUDED", "CANCELLED")
MODULE_CODES = ("CORE_LAW", "MEDIATION_SKILLS", "DOCUMENTATION", "ETHICS_NEUTRALITY", "ELECTIVE")

ACTIVE_CASELOAD_STATUSES = ("ASSIGNED", "IN_MEDIATION", "AWAITING_RESPONSE", "ESCALATION_PENDING")
OPEN_CASE_STATUSES = ("INTAKE", "TRIAGE", "ASSIGNED", "IN_MEDIATION",
                      "AWAITING_RESPONSE", "ESCALATION_PENDING")
EXEMPT_ORDERS = ("NATIONAL_EMERGENCY", "PRESIDENTIAL_CALLUP")
CORE_MODULES = ("CORE_LAW", "MEDIATION_SKILLS", "DOCUMENTATION")

MAX_ACTIVE_CASELOAD = 4
NOTICE_MIN_HOURS = 24
FIVE_YEAR_CAP_DAYS = 1825
CERT_MIN_HOURS = 20
RECERT_MIN_HOURS = 8
HEALTH_CAP_MONTHS = 24
RESPONSE_WINDOW_DAYS = 14
REFERRAL_WINDOW_DAYS = 30
REOPEN_WINDOW_DAYS = 60
CERT_TERM_MONTHS = 24
RECERT_WINDOW_MONTHS = 24
VENUE_BUFFER_MINUTES = 60
DAYS_PER_MONTH = "30.44"

BAND_SHORT_MAX_DAYS = 30
BAND_MID_MAX_DAYS = 180
DEADLINE_DAYS_SHORT = 1
DEADLINE_DAYS_MID = 14
DEADLINE_DAYS_LONG = 90

POINTS_PER_RESOLVED_CASE = 10
POINTS_SIGNED_STATEMENT = 15
PENALTY_PER_OPEN_CASE = 10
TIER_GATE_BASE_BRONZE = 20
TIER_GATE_BASE_SILVER = 40
TIER_GATE_BASE_GOLD = 60
BONUS_BRONZE = 5
BONUS_SILVER = 15
BONUS_GOLD = 30
VET_RESOLVED_GATE = {"BRONZE": 1, "SILVER": 3, "GOLD": 5}
TIER_BONUS = {"BRONZE": BONUS_BRONZE, "SILVER": BONUS_SILVER, "GOLD": BONUS_GOLD}
TIER_RANK = {"NONE": 0, "BRONZE": 1, "SILVER": 2, "GOLD": 3}

# ---------------------------------------------------------------------------
# Request-body shape validators (validation priority 3 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------


def body_json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' is required" % name)
    return v


def opt_str(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a string" % name)
    return v


def req_enum(body, name, allowed):
    v = req_str(body, name)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be one of %s" % (name, ", ".join(allowed)))
    return v


def opt_enum(body, name, allowed, default=None):
    v = body.get(name, default)
    if v is not None and v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be one of %s" % (name, ", ".join(allowed)))
    return v


def opt_bool(body, name, default=False):
    v = body.get(name, default)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a boolean" % name)
    return v


def req_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be an integer" % name)
    return v


def opt_int(body, name, default=None):
    v = body.get(name, default)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be an integer" % name)
    return v


def req_num(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a number" % name)
    return v


def req_dt(body, name):
    v = body.get(name)
    dt = parse_dt(v)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be an ISO-8601 datetime" % name)
    return dt


def opt_dt(body, name):
    v = body.get(name)
    if v is None:
        return None
    dt = parse_dt(v)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be an ISO-8601 datetime" % name)
    return dt


def req_day(body, name):
    v = body.get(name)
    dt = parse_day(v)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be an ISO-8601 datetime" % name)
    return dt


def opt_day(body, name):
    v = body.get(name)
    if v is None:
        return None
    dt = parse_day(v)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be an ISO-8601 datetime" % name)
    return dt


# ---------------------------------------------------------------------------
# Entity getters (validation priority 4 -> per-family 404 errors)
# ---------------------------------------------------------------------------


def _get(collection, key, error_id, label):
    e = collection.get(key)
    if e is None:
        raise ApiError(error_id, 404, "No %s with id %s" % (label, key))
    return e


def get_member(mid):
    return _get(db.members, mid, "ERR_MEMBER_NOT_FOUND", "ServiceMember")


def get_employer(eid):
    return _get(db.employers, eid, "ERR_EMPLOYER_NOT_FOUND", "Employer")


def get_ombudsman(oid):
    return _get(db.ombudsmen, oid, "ERR_OMBUDSMAN_NOT_FOUND", "Ombudsman")


def get_case(cid):
    return _get(db.cases, cid, "ERR_CASE_NOT_FOUND", "ReemploymentCase")


def get_round(rid):
    return _get(db.rounds, rid, "ERR_ROUND_NOT_FOUND", "MediationRound")


def get_referral(rid):
    return _get(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND", "Referral")


def get_statement(sid):
    return _get(db.statements, sid, "ERR_STATEMENT_NOT_FOUND", "StatementOfSupport")


def get_award(aid):
    return _get(db.awards, aid, "ERR_AWARD_NOT_FOUND", "RecognitionAward")


def get_event(eid):
    return _get(db.events, eid, "ERR_EVENT_NOT_FOUND", "OutreachEvent")


# ---------------------------------------------------------------------------
# Mutation bookkeeping and system audit notes
# ---------------------------------------------------------------------------


def touch(entity):
    entity["updated_at"] = now()
    entity["version"] += 1


def add_audit_note(case_id, text):
    nid = new_id()
    db.notes[nid] = {
        "id": nid,
        "case_id": case_id,
        "note_type": "AUDIT",
        "body": text,
        "author_role": "SYSTEM",
        "author_id": "system",
        "created_at": now(),
        "_seq": db.next_seq(),
    }


# ---------------------------------------------------------------------------
# Lazy expiry (strictly-greater comparisons against the logical clock)
# ---------------------------------------------------------------------------


def apply_ombudsman_expiry(o):
    exp = o.get("certification_expires_on")
    if o["status"] == "CERTIFIED" and exp is not None and now() > exp:
        o["status"] = "EXPIRED"
        touch(o)


def apply_statement_lapse(s):
    exp = s.get("expires_on")
    if s["status"] == "SIGNED" and exp is not None and now() > exp:
        s["status"] = "LAPSED"
        touch(s)


def apply_round_expiry(r):
    if r["status"] == "PROPOSED" and now() > r["response_deadline"]:
        r["status"] = "EXPIRED"
        touch(r)
        case = db.cases.get(r["case_id"])
        if case is not None and case["status"] == "AWAITING_RESPONSE":
            case["status"] = "IN_MEDIATION"
            touch(case)


def apply_case_round_expiry(case):
    for r in db.rounds.values():
        if r["case_id"] == case["id"] and r["status"] == "PROPOSED":
            apply_round_expiry(r)


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------


def active_caseload(ombudsman_id):
    return sum(
        1
        for c in db.cases.values()
        if c["assigned_ombudsman_id"] == ombudsman_id
        and c["status"] in ACTIVE_CASELOAD_STATUSES
    )


def total_training_hours(ombudsman_id):
    return sum(
        t["hours"] for t in db.training_records.values()
        if t["ombudsman_id"] == ombudsman_id
    )


def employer_resolved_count(employer_id):
    return sum(
        1 for c in db.cases.values()
        if c["employer_id"] == employer_id and c["status"] == "RESOLVED_INFORMAL"
    )


def employer_open_count(employer_id):
    return sum(
        1 for c in db.cases.values()
        if c["employer_id"] == employer_id and c["status"] in OPEN_CASE_STATUSES
    )


def employer_recognition_tier(employer_id):
    best = "NONE"
    for a in db.awards.values():
        if a["employer_id"] == employer_id and a["status"] == "CONFERRED":
            t = a.get("tier_qualified") or "NONE"
            if TIER_RANK[t] > TIER_RANK[best]:
                best = t
    return best


def documentation_complete(case):
    """AUDIT notes never count toward any category."""
    notes = [n for n in db.notes.values() if n["case_id"] == case["id"]]

    def cnt(t):
        return sum(1 for n in notes if n["note_type"] == t)

    rounds_total = sum(1 for r in db.rounds.values() if r["case_id"] == case["id"])
    intake_ok = cnt("INTAKE") >= 1
    contact_ok = cnt("CONTACT") >= rounds_total
    resolution_ok = cnt("RESOLUTION") >= 1
    education_ok = True
    if case["issue_type"] in ("BENEFITS", "PENSION"):
        education_ok = cnt("EMPLOYER_EDUCATION") >= 1
    return intake_ok and contact_ok and resolution_ok and education_ok


def completed_periods(member_id, employer_id):
    """Completed ServicePeriod rows of the (member, employer) pair:
    end_date IS NOT NULL AND end_date <= logical clock."""
    t = now()
    return [
        p for p in db.service_periods.values()
        if p["member_id"] == member_id
        and p["employer_id"] == employer_id
        and p["end_date"] is not None
        and p["end_date"] <= t
    ]


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def ser_member(m):
    return {
        "id": m["id"],
        "full_name": m["full_name"],
        "email": m["email"],
        "branch": m["branch"],
        "component": m["component"],
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
    }


def ser_employer(e):
    return {
        "id": e["id"],
        "legal_name": e["legal_name"],
        "sector": e["sector"],
        "size_tier": e["size_tier"],
        "resolved_case_count": employer_resolved_count(e["id"]),
        "open_case_count": employer_open_count(e["id"]),
        "recognition_tier": employer_recognition_tier(e["id"]),
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_ombudsman(o):
    apply_ombudsman_expiry(o)
    return {
        "id": o["id"],
        "full_name": o["full_name"],
        "email": o["email"],
        "employer_affiliation_id": o["employer_affiliation_id"],
        "status": o["status"],
        "certified_on": fmt_dt(o["certified_on"]),
        "certification_expires_on": fmt_dt(o["certification_expires_on"]),
        "active_caseload": active_caseload(o["id"]),
        "total_training_hours": total_training_hours(o["id"]),
        "created_at": fmt_dt(o["created_at"]),
        "updated_at": fmt_dt(o["updated_at"]),
        "version": o["version"],
    }


def ser_service_period(p):
    return {
        "id": p["id"],
        "member_id": p["member_id"],
        "employer_id": p["employer_id"],
        "start_date": fmt_dt(p["start_date"]),
        "end_date": fmt_dt(p["end_date"]),
        "orders_type": p["orders_type"],
        "notice_given_at": fmt_dt(p["notice_given_at"]),
        "duration_days": p["duration_days"],
        "chargeable": p["chargeable"],
        "created_at": fmt_dt(p["created_at"]),
    }


def ser_case(c):
    apply_case_round_expiry(c)
    open_round_count = sum(
        1 for r in db.rounds.values()
        if r["case_id"] == c["id"] and r["status"] == "PROPOSED"
    )
    return {
        "id": c["id"],
        "member_id": c["member_id"],
        "employer_id": c["employer_id"],
        "issue_type": c["issue_type"],
        "description": c["description"],
        "application_submitted_at": fmt_dt(c["application_submitted_at"]),
        "excuse_claimed": c["excuse_claimed"],
        "excuse_category": c["excuse_category"],
        "assigned_ombudsman_id": c["assigned_ombudsman_id"],
        "status": c["status"],
        "open_round_count": open_round_count,
        "documentation_complete": documentation_complete(c),
        "escalated_at": fmt_dt(c["escalated_at"]),
        "closed_at": fmt_dt(c["closed_at"]),
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_round(r):
    apply_round_expiry(r)
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "round_number": r["round_number"],
        "proposal_text": r["proposal_text"],
        "addressed_to": r["addressed_to"],
        "response_deadline": fmt_dt(r["response_deadline"]),
        "status": r["status"],
        "response": r["response"],
        "counter_text": r["counter_text"],
        "responded_at": fmt_dt(r["responded_at"]),
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_note(n):
    return {
        "id": n["id"],
        "case_id": n["case_id"],
        "note_type": n["note_type"],
        "body": n["body"],
        "author_role": n["author_role"],
        "author_id": n["author_id"],
        "created_at": fmt_dt(n["created_at"]),
    }


def ser_analysis(a):
    return {
        "id": a["id"],
        "case_id": a["case_id"],
        "sequence_number": a["sequence_number"],
        "variant": a["variant"],
        "notice_hours_advance": a["notice_hours_advance"],
        "notice_satisfied": a["notice_satisfied"],
        "cumulative_chargeable_days": a["cumulative_chargeable_days"],
        "service_limit_ok": a["service_limit_ok"],
        "disputed_period_duration_days": a["disputed_period_duration_days"],
        "duration_band": a["duration_band"],
        "application_deadline_days": a["application_deadline_days"],
        "application_deadline_date": fmt_dt(a["application_deadline_date"]),
        "deadline_satisfied": a["deadline_satisfied"],
        "escalator_position_class": a["escalator_position_class"],
        "overall_eligible": a["overall_eligible"],
        "created_at": fmt_dt(a["created_at"]),
    }


def ser_assessment(b):
    case = db.cases.get(b["case_id"])
    education_satisfied = False
    if case is not None:
        education_satisfied = any(
            n["case_id"] == b["case_id"] and n["note_type"] == "EMPLOYER_EDUCATION"
            for n in db.notes.values()
        )
    return {
        "id": b["id"],
        "case_id": b["case_id"],
        "health_continuation_months": float(b["health_continuation_months"]),
        "pension_credit_months_official": float(b["pension_credit_months_official"]),
        "pension_credit_months_alternate": float(b["pension_credit_months_alternate"]),
        "education_required": b["education_required"],
        "education_satisfied": education_satisfied,
        "created_at": fmt_dt(b["created_at"]),
    }


def ser_referral(r):
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "agency": r["agency"],
        "summary": r["summary"],
        "status": r["status"],
        "submitted_at": fmt_dt(r["submitted_at"]),
        "info_request_note": r["info_request_note"],
        "created_by_ombudsman_id": r["created_by_ombudsman_id"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_statement(s):
    apply_statement_lapse(s)
    return {
        "id": s["id"],
        "employer_id": s["employer_id"],
        "signer_name": s["signer_name"],
        "signer_title": s["signer_title"],
        "term_months": s["term_months"],
        "status": s["status"],
        "signed_on": fmt_dt(s["signed_on"]),
        "expires_on": fmt_dt(s["expires_on"]),
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_award(a):
    return {
        "id": a["id"],
        "employer_id": a["employer_id"],
        "tier": a["tier"],
        "rationale": a["rationale"],
        "nominated_by_id": a["nominated_by_id"],
        "nominated_by_role": a["nominated_by_role"],
        "status": a["status"],
        "score_base": a["score_base"],
        "tier_qualified": a["tier_qualified"],
        "score_bonus": a["score_bonus"],
        "score_final": a["score_final"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def ser_event(e):
    return {
        "id": e["id"],
        "title": e["title"],
        "venue": e["venue"],
        "starts_at": fmt_dt(e["starts_at"]),
        "ends_at": fmt_dt(e["ends_at"]),
        "topic": e["topic"],
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_training(t):
    return {
        "id": t["id"],
        "ombudsman_id": t["ombudsman_id"],
        "module_code": t["module_code"],
        "hours": t["hours"],
        "exam_score": t["exam_score"],
        "completed_on": fmt_dt(t["completed_on"]),
        "proctor_id": t["proctor_id"],
        "created_at": fmt_dt(t["created_at"]),
    }
