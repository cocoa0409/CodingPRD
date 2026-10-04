"""Entity -> public-dict serializers.

Reads resolve lazy clock-driven states (recorders, sessions, meetings) and
on-read computed fields (recommendation aging, dissenting members). Internal
bookkeeping keys (``_seq``) never leave the process.
"""

import domain
from aging import compute_aging


def decision_public(decision):
    return {
        "decision_id": decision["decision_id"],
        "mode": decision["mode"],
        "status": decision["status"],
        "proposed_by_user_id": decision["proposed_by_user_id"],
        "proposed_at": decision["proposed_at"],
        "adopted_at": decision["adopted_at"],
        "snapshot_statutory_score": decision["snapshot_statutory_score"],
        "snapshot_risk_adjusted_score": decision["snapshot_risk_adjusted_score"],
        "rationale": decision["rationale"],
    }


def case_public(case):
    return {
        "id": case["id"],
        "report_number": case["report_number"],
        "category": case["category"],
        "occurred_at": case["occurred_at"],
        "location_state": case["location_state"],
        "fatalities_count": case["fatalities_count"],
        "injuries_count": case["injuries_count"],
        "damage_estimate_cents": case["damage_estimate_cents"],
        "is_public_transport": case["is_public_transport"],
        "statutory_score": case["statutory_score"],
        "risk_adjusted_score": case["risk_adjusted_score"],
        "suggested_mode": case["suggested_mode"],
        "status": case["status"],
        "launch_decisions": [
            decision_public(d) for d in case["launch_decisions"]
        ],
        "created_at": case["created_at"],
        "updated_at": case["updated_at"],
        "version": case["version"],
    }


def investigation_public(investigation):
    return {
        "id": investigation["id"],
        "accident_case_id": investigation["accident_case_id"],
        "iic_user_id": investigation["iic_user_id"],
        "phase": investigation["phase"],
        "docket_status": investigation["docket_status"],
        "docket_completeness_pct": investigation["docket_completeness_pct"],
        "created_at": investigation["created_at"],
        "updated_at": investigation["updated_at"],
        "version": investigation["version"],
    }


def organization_public(organization):
    return {
        "id": organization["id"],
        "legal_name": organization["legal_name"],
        "org_type": organization["org_type"],
        "created_at": organization["created_at"],
        "updated_at": organization["updated_at"],
        "version": organization["version"],
    }


def seat_public(seat):
    return {
        "seat_id": seat["seat_id"],
        "group_id": seat["group_id"],
        "status": seat["status"],
        "strike_count": seat["strike_count"],
        "conduct_log": list(seat["conduct_log"]),
    }


def designation_public(designation):
    return {
        "id": designation["id"],
        "investigation_id": designation["investigation_id"],
        "organization_id": designation["organization_id"],
        "status": designation["status"],
        "designated_at": designation["designated_at"],
        "expulsion_reason": designation["expulsion_reason"],
        "group_seats": [seat_public(s) for s in designation["group_seats"]],
        "created_at": designation["created_at"],
        "updated_at": designation["updated_at"],
        "version": designation["version"],
    }


def report_public(report):
    return {
        "report_id": report["report_id"],
        "report_kind": report["report_kind"],
        "content": report["content"],
        "recorder_id": report["recorder_id"],
        "status": report["status"],
        "submitted_by_user_id": report["submitted_by_user_id"],
        "submitted_at": report["submitted_at"],
        "verified_at": report["verified_at"],
    }


def group_public(group):
    return {
        "id": group["id"],
        "investigation_id": group["investigation_id"],
        "specialty": group["specialty"],
        "chairman_user_id": group["chairman_user_id"],
        "status": group["status"],
        "seated_count": group["seated_count"],
        "factual_reports": [report_public(r) for r in group["factual_reports"]],
        "created_at": group["created_at"],
        "updated_at": group["updated_at"],
        "version": group["version"],
    }


def session_public(session):
    domain.refresh_session(session)
    return {
        "session_id": session["session_id"],
        "bench_id": session["bench_id"],
        "window_start_utc": session["window_start_utc"],
        "window_end_utc": session["window_end_utc"],
        "status": session["status"],
    }


def recorder_public(recorder):
    domain.refresh_recorder(recorder)
    return {
        "id": recorder["id"],
        "investigation_id": recorder["investigation_id"],
        "recorder_type": recorder["recorder_type"],
        "condition": recorder["condition"],
        "status": recorder["status"],
        "readout_sessions": [
            session_public(s) for s in recorder["readout_sessions"]
        ],
        "created_at": recorder["created_at"],
        "updated_at": recorder["updated_at"],
        "version": recorder["version"],
    }


def recommendation_public(recommendation):
    calendar_days, business_days, overdue, bucket = compute_aging(recommendation)
    return {
        "id": recommendation["id"],
        "investigation_id": recommendation["investigation_id"],
        "addressee_org_id": recommendation["addressee_org_id"],
        "recommendation_text": recommendation["recommendation_text"],
        "status": recommendation["status"],
        "issued_at": recommendation["issued_at"],
        "response_log": list(recommendation["response_log"]),
        "unacceptable_streak": recommendation["unacceptable_streak"],
        "calendar_elapsed_days": calendar_days,
        "business_elapsed_days": business_days,
        "overdue": overdue,
        "aging_bucket": bucket,
        "created_at": recommendation["created_at"],
        "updated_at": recommendation["updated_at"],
        "version": recommendation["version"],
    }


def vote_public(vote):
    return {
        "member_user_id": vote["member_user_id"],
        "position": vote["position"],
        "dissent_text": vote["dissent_text"],
        "cast_at": vote["cast_at"],
    }


def meeting_public(meeting):
    domain.refresh_meeting(meeting)
    return {
        "id": meeting["id"],
        "investigation_id": meeting["investigation_id"],
        "room_id": meeting["room_id"],
        "window_start_utc": meeting["window_start_utc"],
        "window_end_utc": meeting["window_end_utc"],
        "sitting_member_ids": list(meeting["sitting_member_ids"]),
        "status": meeting["status"],
        "member_votes": [vote_public(v) for v in meeting["member_votes"]],
        "adopt_count": meeting["adopt_count"],
        "reject_count": meeting["reject_count"],
        "abstain_count": meeting["abstain_count"],
        "dissenting_member_ids": domain.dissenting_members(meeting),
        "outcome": meeting["outcome"],
        "created_at": meeting["created_at"],
        "updated_at": meeting["updated_at"],
        "version": meeting["version"],
    }
