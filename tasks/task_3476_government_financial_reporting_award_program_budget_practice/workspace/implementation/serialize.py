"""Entity serializers.

Every declared field is emitted (nulls included); internal helper fields
(prefixed `_`) never leak. Derived/computed fields are evaluated here on read:
cycle posture, reviewer counters, submission provisional_score /
major_deficiency_total, publication comment counters, fund remaining_cents and
status. ReviewFinding carries only id + created_at (PRD 2.5).
"""

from clock import clock
from domain import (
    fund_remaining_cents,
    fund_status,
    posture_of,
    provisional_and_majors,
    reviewer_completed_count,
    reviewer_declined_count,
    reviewer_open_count,
)
from store import store


def _num(value):
    """Decimal -> float for JSON (shortest-repr round-trips 2dp values)."""
    return None if value is None else float(value)


def government(g):
    return {
        "id": g["id"],
        "legal_name": g["legal_name"],
        "gov_type": g["gov_type"],
        "population_band": g["population_band"],
        "state_code": g["state_code"],
        "lifetime_award_count": g["lifetime_award_count"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def member(m):
    return {
        "id": m["id"],
        "full_name": m["full_name"],
        "email": m["email"],
        "government_size_band": m["government_size_band"],
        "independent_finance_officer": m["independent_finance_officer"],
        "annual_dues_cents": m["annual_dues_cents"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def reviewer_profile(p):
    return {
        "id": p["id"],
        "member_id": p["member_id"],
        "employer_government_id": p["employer_government_id"],
        "conflicted_government_ids": list(p["conflicted_government_ids"]),
        "unavailability_windows": [
            {"start_date": w["start_date"], "end_date": w["end_date"]}
            for w in p["unavailability_windows"]
        ],
        "independence_attested": p["independence_attested"],
        "status": p["status"],
        "trained_at": p["trained_at"],
        "open_assignment_count": reviewer_open_count(p["id"]),
        "completed_review_count": reviewer_completed_count(p["id"]),
        "declined_assignment_count": reviewer_declined_count(p["id"]),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def checklist_version(c):
    return {
        "id": c["id"],
        "program_type": c["program_type"],
        "version_label": c["version_label"],
        "pass_score": _num(c["pass_score"]),
        "criteria": [
            {"criterion_code": e["criterion_code"], "weight": e["weight"]}
            for e in c["criteria"]
        ],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def standards_reference(s):
    return {
        "id": s["id"],
        "topic_code": s["topic_code"],
        "title": s["title"],
        "program_type": s["program_type"],
        "effective_date": s["effective_date"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def award_cycle(c):
    return {
        "id": c["id"],
        "program_type": c["program_type"],
        "fiscal_year": c["fiscal_year"],
        "submission_opens_at": c["submission_opens_at"],
        "submission_deadline_at": c["submission_deadline_at"],
        "review_close_at": c["review_close_at"],
        "checklist_version_id": c["checklist_version_id"],
        "posture": posture_of(c, clock.now()),
        "submitted_count": c["submitted_count"],
        "decision_ready_count": c["decision_ready_count"],
        "conferred_count": c["conferred_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def report_submission(s):
    provisional, majors = provisional_and_majors(s)
    return {
        "id": s["id"],
        "government_id": s["government_id"],
        "cycle_id": s["cycle_id"],
        "budget_documents": [
            {"doc_type": d["doc_type"], "title": d["title"], "page_count": d["page_count"]}
            for d in s["budget_documents"]
        ],
        "program_type": s["program_type"],
        "pinned_checklist_version_id": s["pinned_checklist_version_id"],
        "pinned_checklist_stale": s["pinned_checklist_stale"],
        "appeal_round": s["appeal_round"],
        "status": s["status"],
        "provisional_score": _num(provisional),
        "final_score": _num(s["final_score"]),
        "major_deficiency_total": majors,
        "required_improvements": list(s["required_improvements"]),
        "award_conferred": s["award_conferred"],
        "submitted_at": s["submitted_at"],
        "decided_at": s["decided_at"],
        "conferred_at": s["conferred_at"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def review_assignment(a, caller_role=None):
    """Blind review (PRD 2.11): reviewer_id is masked to null for
    GovernmentContact callers; only the blind reviewer_alias stays visible."""
    masked = caller_role == "GovernmentContact"
    return {
        "id": a["id"],
        "submission_id": a["submission_id"],
        "reviewer_id": None if masked else a["reviewer_id"],
        "reviewer_alias": a["reviewer_alias"],
        "appeal_round": a["appeal_round"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def review_finding(f):
    return {
        "id": f["id"],
        "assignment_id": f["assignment_id"],
        "appeal_round": f["appeal_round"],
        "criterion_scores": [
            {"criterion_code": e["criterion_code"], "score": _num(e["_score_decimal"])}
            for e in f["criterion_scores"]
        ],
        "comments": [
            {"criterion_code": c["criterion_code"], "severity": c["severity"], "text": c["text"]}
            for c in f["comments"]
        ],
        "weighted_score": _num(f["weighted_score"]),
        "major_deficiency_count": f["major_deficiency_count"],
        "created_at": f["created_at"],
    }


def publication(p):
    pending = 0
    resolved = 0
    for c in store.member_comments.values():
        if c["publication_id"] != p["id"]:
            continue
        if c["resolution"] == "PENDING":
            pending += 1
        else:
            resolved += 1
    return {
        "id": p["id"],
        "committee_name": p["committee_name"],
        "chair_member_id": p["chair_member_id"],
        "member_ids": list(p["member_ids"]),
        "created_by_member_id": p["created_by_member_id"],
        "title": p["title"],
        "topic_code": p["topic_code"],
        "pinned_standards_reference_id": p["pinned_standards_reference_id"],
        "comment_window_opens_at": p["comment_window_opens_at"],
        "comment_window_closes_at": p["comment_window_closes_at"],
        "draft_number": p["draft_number"],
        "pending_comment_count": pending,
        "resolved_comment_count": resolved,
        "status": p["status"],
        "published_at": p["published_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def member_comment(c):
    return {
        "id": c["id"],
        "publication_id": c["publication_id"],
        "member_id": c["member_id"],
        "body": c["body"],
        "resolution": c["resolution"],
        "resolution_note": c["resolution_note"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def scholarship_fund(f):
    return {
        "id": f["id"],
        "fiscal_year": f["fiscal_year"],
        "program_label": f["program_label"],
        "pool_total_cents": f["pool_total_cents"],
        "per_applicant_cap_cents": f["per_applicant_cap_cents"],
        "allocation_policy": f["allocation_policy"],
        "remaining_cents": fund_remaining_cents(f),
        "status": fund_status(f),
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def scholarship_application(a):
    return {
        "id": a["id"],
        "fund_id": a["fund_id"],
        "government_id": a["government_id"],
        "purpose": a["purpose"],
        "requested_cents": a["requested_cents"],
        "granted_cents": a["granted_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }
