"""Business logic: fraud scoring, trust tiers, cascades, waitlist promotion,
conflict detection, messaging allowance, outcome report, and serializers."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import now
from util import canonical


ACTIVE_APP_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INTERVIEWING", "OFFER_EXTENDED")
TERMINAL_APP_STATUSES = ("ACCEPTED", "DECLINED", "REJECTED", "WITHDRAWN", "AUTO_WITHDRAWN")
PLACED_OUTCOMES = ("EMPLOYED", "GRAD_SCHOOL")

# --- fraud_risk_score constants (calculations.fraud_risk_score) ---
FRAUD_BASE_SCORE = 50
EMAIL_DOMAIN_MATCH_POINTS = 25
ESTABLISHED_TLD_POINTS = 15
HYPHEN_POINTS = 10
SHORT_NAME_POINTS = 10
FLAG_PENALTY = 10
TIER_LOW_RISK_MAX = 20
TIER_STANDARD_MAX = 50
TIER_ELEVATED_MAX = 79

# --- messaging_allowance constants ---
BASE_DAILY_CAP = 5
TIER_MULTIPLIER_PERCENT = {"LOW_RISK": 200, "STANDARD": 100, "ELEVATED": 40, "HIGH_RISK": 0}

BUFFER_MINUTES = 15


def clamp_score(score):
    return max(0, min(100, score))


def tier_for(score):
    if score <= TIER_LOW_RISK_MAX:
        return "LOW_RISK"
    if score <= TIER_STANDARD_MAX:
        return "STANDARD"
    if score <= TIER_ELEVATED_MAX:
        return "ELEVATED"
    return "HIGH_RISK"


def fraud_auto_score(employer):
    """auto_screen variant: computed from registration fields only."""
    score = FRAUD_BASE_SCORE
    domain = employer["website_domain"]
    if employer["contact_email"].endswith("@" + domain):
        score -= EMAIL_DOMAIN_MATCH_POINTS
    if domain.endswith(".edu") or domain.endswith(".gov"):
        score -= ESTABLISHED_TLD_POINTS
    if "-" in domain:
        score += HYPHEN_POINTS
    if len(employer["company_name"]) < 4:
        score += SHORT_NAME_POINTS
    return clamp_score(score)


def fraud_analyst_score(employer, adjustment, decision):
    """analyst_screen variant: stored score + adjustment (+ FLAG penalty)."""
    score = employer["fraud_risk_score"] + adjustment
    if decision == "FLAG":
        score += FLAG_PENALTY
    return clamp_score(score)


def messaging_effective_cap(employer, university):
    tier_cap = (BASE_DAILY_CAP * TIER_MULTIPLIER_PERCENT[employer["trust_tier"]]) // 100
    return min(university["employer_daily_message_cap"], tier_cap)


def messages_sent_today(employer_id, university_id):
    day = now().strftime("%Y-%m-%d")
    return sum(
        1 for m in db.all_of("outreach_messages")
        if m["employer_id"] == employer_id
        and m["university_id"] == university_id
        and m["sent_day"] == day
    )


def student_visible_to_employer(student, employer_id):
    if student["profile_visibility"] != "PUBLIC_TO_APPROVED_EMPLOYERS":
        return False
    return any(
        a["employer_id"] == employer_id
        and a["university_id"] == student["university_id"]
        and a["status"] == "APPROVED"
        for a in db.all_of("employer_approvals")
    )


def approval_exists(employer_id, university_id):
    return any(
        a["employer_id"] == employer_id
        and a["university_id"] == university_id
        and a["status"] == "APPROVED"
        for a in db.all_of("employer_approvals")
    )


def posting_reported_status(posting):
    """Read-time EXPIRED projection; stored status is never rewritten."""
    if posting["status"] == "PUBLISHED" and now() > posting["application_deadline"]:
        return "EXPIRED"
    return posting["status"]


def posting_visible_to_university(posting, university_id):
    university = db.get("universities", university_id)
    if university is None or university["status"] != "ACTIVE":
        return False
    if posting_reported_status(posting) != "PUBLISHED":
        return False
    if university_id in posting["blocked_university_ids"]:
        return False
    employer = db.get("employers", posting["employer_id"])
    if employer is None or employer["status"] != "APPROVED":
        return False
    return approval_exists(posting["employer_id"], university_id)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cancel_scheduled_interviews(application):
    for interview in db.all_of("interviews"):
        if interview["application_id"] == application["id"] and interview["status"] == "SCHEDULED":
            interview["status"] = "CANCELLED"
            db.touch(interview)


def terminate_application(application, target):
    """Terminal transition side effects: interviews CANCELLED, decided_at stamped.

    active_application_count is a computed readout, so it re-derives itself.
    """
    application["status"] = target
    application["decided_at"] = now()
    db.touch(application)
    cancel_scheduled_interviews(application)


def promote_waitlist(session):
    """Fire only when the session is still SCHEDULED; earliest created_at,
    tie-break student email ascending."""
    if session["status"] != "SCHEDULED":
        return
    candidates = [
        s for s in db.all_of("event_signups")
        if s["event_session_id"] == session["id"] and s["status"] == "WAITLISTED"
    ]
    if not candidates:
        return

    def sort_key(signup):
        student = db.get("students", signup["student_id"])
        email = student["email"] if student else ""
        return (signup["created_at"], email, signup["_seq"])

    chosen = min(candidates, key=sort_key)
    chosen["status"] = "REGISTERED"
    chosen["registered_at"] = now()
    chosen["promoted_from_waitlist"] = True
    db.touch(chosen)


def withdraw_student_cascade(student):
    # HOP 1: active applications -> WITHDRAWN (HOP 2 interviews ride along).
    for application in db.all_of("applications"):
        if application["student_id"] == student["id"] and application["status"] in ACTIVE_APP_STATUSES:
            terminate_application(application, "WITHDRAWN")
    # HOP 1 (parallel branch): signups -> CANCELLED; REGISTERED ones promote.
    for signup in db.all_of("event_signups"):
        if signup["student_id"] != student["id"]:
            continue
        if signup["status"] not in ("REGISTERED", "WAITLISTED"):
            continue
        was_registered = signup["status"] == "REGISTERED"
        signup["status"] = "CANCELLED"
        db.touch(signup)
        if was_registered:
            session = db.get("event_sessions", signup["event_session_id"])
            if session is not None:
                promote_waitlist(session)


def auto_withdraw_for_block(posting, university_id):
    """Applications from this university's students to this posting in
    SUBMITTED/UNDER_REVIEW/INTERVIEWING -> AUTO_WITHDRAWN. OFFER_EXTENDED
    survives (conditional cascade)."""
    for application in db.all_of("applications"):
        if application["job_posting_id"] != posting["id"]:
            continue
        if application["status"] not in ("SUBMITTED", "UNDER_REVIEW", "INTERVIEWING"):
            continue
        student = db.get("students", application["student_id"])
        if student is None or student["university_id"] != university_id:
            continue
        terminate_application(application, "AUTO_WITHDRAWN")


def block_posting_at_university(posting, university_id):
    if university_id not in posting["blocked_university_ids"]:
        posting["blocked_university_ids"].append(university_id)
    db.touch(posting)
    auto_withdraw_for_block(posting, university_id)


def employer_block_cascade(employer_id, university_id):
    """Employer-approval BLOCK/REVOKE: every PUBLISHED posting of the employer
    gets the university appended, then the application/interview cascade."""
    for posting in db.all_of("job_postings"):
        if posting["employer_id"] == employer_id and posting["status"] == "PUBLISHED":
            block_posting_at_university(posting, university_id)


def cancel_event_cascade(event):
    for session in db.all_of("event_sessions"):
        if session["career_event_id"] != event["id"] or session["status"] != "SCHEDULED":
            continue
        session["status"] = "CANCELLED"
        db.touch(session)
        for signup in db.all_of("event_signups"):
            if signup["event_session_id"] == session["id"] and signup["status"] in ("REGISTERED", "WAITLISTED"):
                signup["status"] = "CANCELLED"
                db.touch(signup)
        # No waitlist promotion: the session itself is gone.


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def room_conflict(event_id, room_id, starts_at, ends_at):
    """Half-open [start, end) overlap; adjacency is not a conflict."""
    for s in db.all_of("event_sessions"):
        if s["career_event_id"] != event_id or s["status"] == "CANCELLED":
            continue
        if s["mode"] != "IN_PERSON" or s["room_id"] != room_id:
            continue
        if starts_at < s["ends_at"] and s["starts_at"] < ends_at:
            return True
    return False


def interview_conflict(interviewer_email, starts_at, ends_at):
    """Buffered overlap: a gap of exactly BUFFER_MINUTES passes."""
    buffer = timedelta(minutes=BUFFER_MINUTES)
    for iv in db.all_of("interviews"):
        if iv["interviewer_email"] != interviewer_email or iv["status"] != "SCHEDULED":
            continue
        if starts_at < iv["ends_at"] + buffer and iv["starts_at"] < ends_at + buffer:
            return True
    return False


# ---------------------------------------------------------------------------
# Outcome report (nested round-half-up order is pinned)
# ---------------------------------------------------------------------------

def _round4(value):
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def build_outcome_report(university):
    alumni = [
        s for s in db.all_of("students")
        if s["university_id"] == university["id"] and s["status"] == "ALUMNUS"
    ]
    respondents = [s for s in alumni if s["outcome_status"] != "UNREPORTED"]
    placed = [s for s in respondents if s["outcome_status"] in PLACED_OUTCOMES]
    alumni_count = len(alumni)
    respondents_count = len(respondents)
    placed_count = len(placed)
    per_major = []
    placement_rate_cohort = None
    placement_rate_respondent = None
    if alumni_count > 0:
        placement_rate_cohort = float(_round4(Decimal(placed_count) / Decimal(alumni_count)))
        if respondents_count > 0:
            weighted_sum = Decimal(0)
            for major in sorted({s["major"] for s in respondents}):
                rm = [s for s in respondents if s["major"] == major]
                pm = sum(1 for s in rm if s["outcome_status"] in PLACED_OUTCOMES)
                rate_m = _round4(Decimal(pm) / Decimal(len(rm)))
                weighted_sum += rate_m * len(rm)
                per_major.append({
                    "major": major,
                    "respondents_count": len(rm),
                    "placed_count": pm,
                    "placement_rate": float(rate_m),
                })
            placement_rate_respondent = float(
                _round4(weighted_sum / Decimal(respondents_count))
            )
    return {
        "alumni_count": alumni_count,
        "respondents_count": respondents_count,
        "placed_count": placed_count,
        "placement_rate_cohort": placement_rate_cohort,
        "placement_rate_respondent": placement_rate_respondent,
        "per_major": per_major,
    }


# ---------------------------------------------------------------------------
# Serializers (computed fields are derived here, never stored)
# ---------------------------------------------------------------------------

def university_view(u):
    enrolled = sum(
        1 for s in db.all_of("students")
        if s["university_id"] == u["id"] and s["status"] == "ENROLLED"
    )
    approved = sum(
        1 for a in db.all_of("employer_approvals")
        if a["university_id"] == u["id"] and a["status"] == "APPROVED"
    )
    return {
        "id": u["id"],
        "name": u["name"],
        "primary_domain": u["primary_domain"],
        "status": u["status"],
        "employer_daily_message_cap": u["employer_daily_message_cap"],
        "enrolled_student_count": enrolled,
        "approved_employer_count": approved,
        "created_at": canonical(u["created_at"]),
        "updated_at": canonical(u["updated_at"]),
        "version": u["version"],
    }


def student_view(s):
    return {
        "id": s["id"],
        "university_id": s["university_id"],
        "email": s["email"],
        "full_name": s["full_name"],
        "major": s["major"],
        "graduation_year": s["graduation_year"],
        "work_authorization": s["work_authorization"],
        "profile_visibility": s["profile_visibility"],
        "status": s["status"],
        "outcome_status": s["outcome_status"],
        "outcome_employer_name": s["outcome_employer_name"],
        "outcome_recorded_at": canonical(s["outcome_recorded_at"]) if s["outcome_recorded_at"] else None,
        "created_at": canonical(s["created_at"]),
        "updated_at": canonical(s["updated_at"]),
        "version": s["version"],
    }


def employer_view(e):
    return {
        "id": e["id"],
        "company_name": e["company_name"],
        "website_domain": e["website_domain"],
        "contact_email": e["contact_email"],
        "status": e["status"],
        "domain_verification_token": e["domain_verification_token"],
        "fraud_risk_score": e["fraud_risk_score"],
        "trust_tier": e["trust_tier"],
        "screen_count": e["screen_count"],
        "last_trust_decision_at": canonical(e["last_trust_decision_at"]) if e["last_trust_decision_at"] else None,
        "created_at": canonical(e["created_at"]),
        "updated_at": canonical(e["updated_at"]),
        "version": e["version"],
    }


def approval_view(a):
    return {
        "id": a["id"],
        "employer_id": a["employer_id"],
        "university_id": a["university_id"],
        "status": a["status"],
        "decision_reason": a["decision_reason"],
        "decided_at": canonical(a["decided_at"]) if a["decided_at"] else None,
        "trust_tier_at_decision": a["trust_tier_at_decision"],
        "supersedes_approval_id": a["supersedes_approval_id"],
        "created_at": canonical(a["created_at"]),
        "updated_at": canonical(a["updated_at"]),
        "version": a["version"],
    }


def posting_view(p):
    active_count = sum(
        1 for a in db.all_of("applications")
        if a["job_posting_id"] == p["id"] and a["status"] in ACTIVE_APP_STATUSES
    )
    return {
        "id": p["id"],
        "employer_id": p["employer_id"],
        "title": p["title"],
        "position_type": p["position_type"],
        "required_majors": list(p["required_majors"]),
        "min_graduation_year": p["min_graduation_year"],
        "max_graduation_year": p["max_graduation_year"],
        "accepted_work_authorizations": list(p["accepted_work_authorizations"]),
        "required_documents": list(p["required_documents"]),
        "application_deadline": canonical(p["application_deadline"]),
        "status": posting_reported_status(p),
        "blocked_university_ids": list(p["blocked_university_ids"]),
        "active_application_count": active_count,
        "created_at": canonical(p["created_at"]),
        "updated_at": canonical(p["updated_at"]),
        "version": p["version"],
    }


def event_view(ev):
    return {
        "id": ev["id"],
        "university_id": ev["university_id"],
        "title": ev["title"],
        "starts_at": canonical(ev["starts_at"]),
        "ends_at": canonical(ev["ends_at"]),
        "status": ev["status"],
        "last_session_added_at": canonical(ev["last_session_added_at"]) if ev["last_session_added_at"] else None,
        "created_at": canonical(ev["created_at"]),
        "updated_at": canonical(ev["updated_at"]),
        "version": ev["version"],
    }


def session_view(s):
    occupied = sum(
        1 for g in db.all_of("event_signups")
        if g["event_session_id"] == s["id"] and g["status"] == "REGISTERED"
    )
    return {
        "id": s["id"],
        "career_event_id": s["career_event_id"],
        "title": s["title"],
        "mode": s["mode"],
        "room_id": s["room_id"],
        "starts_at": canonical(s["starts_at"]),
        "ends_at": canonical(s["ends_at"]),
        "signup_deadline": canonical(s["signup_deadline"]),
        "capacity": s["capacity"],
        "occupied_seats": occupied,
        "status": s["status"],
        "created_at": canonical(s["created_at"]),
        "updated_at": canonical(s["updated_at"]),
        "version": s["version"],
    }


def signup_view(s):
    return {
        "id": s["id"],
        "event_session_id": s["event_session_id"],
        "student_id": s["student_id"],
        "status": s["status"],
        "registered_at": canonical(s["registered_at"]) if s["registered_at"] else None,
        "promoted_from_waitlist": s["promoted_from_waitlist"],
        "created_at": canonical(s["created_at"]),
        "updated_at": canonical(s["updated_at"]),
        "version": s["version"],
    }


def application_view(a):
    posting = db.get("job_postings", a["job_posting_id"])
    required = posting["required_documents"] if posting else []
    submitted_types = [
        d.get("doc_type") for d in a["submitted_documents"] if isinstance(d, dict)
    ]
    documents_status = (
        "COMPLETE" if all(t in submitted_types for t in required) else "INCOMPLETE"
    )
    return {
        "id": a["id"],
        "student_id": a["student_id"],
        "job_posting_id": a["job_posting_id"],
        "status": a["status"],
        "submitted_documents": a["submitted_documents"],
        "documents_status": documents_status,
        "submitted_at": canonical(a["submitted_at"]),
        "decided_at": canonical(a["decided_at"]) if a["decided_at"] else None,
        "created_at": canonical(a["created_at"]),
        "updated_at": canonical(a["updated_at"]),
        "version": a["version"],
    }


def interview_view(iv):
    return {
        "id": iv["id"],
        "application_id": iv["application_id"],
        "interviewer_email": iv["interviewer_email"],
        "mode": iv["mode"],
        "starts_at": canonical(iv["starts_at"]),
        "ends_at": canonical(iv["ends_at"]),
        "status": iv["status"],
        "created_at": canonical(iv["created_at"]),
        "updated_at": canonical(iv["updated_at"]),
        "version": iv["version"],
    }


def message_view(m):
    return {
        "id": m["id"],
        "employer_id": m["employer_id"],
        "student_id": m["student_id"],
        "university_id": m["university_id"],
        "body": m["body"],
        "sent_day": m["sent_day"],
        "created_at": canonical(m["created_at"]),
        "updated_at": canonical(m["updated_at"]),
        "version": m["version"],
    }
