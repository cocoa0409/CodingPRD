"""Public serializers — exact output field sets per SCAFFOLD entity tables.

All resource datetimes serialize as ISO 8601 UTC with three fractional digits
(PRD section 2.8). Internal bookkeeping fields (prefixed with '_') are never
serialized.
"""
from datetime import timezone


def fmt_dt(value):
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def fmt_clock(value):
    """Clock echo: whole-second instants render without a fractional part,
    matching the pinned startup default 2026-09-01T00:00:00Z."""
    value = value.astimezone(timezone.utc)
    if value.microsecond == 0:
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_dt(value)


def organization(o):
    return {
        "id": o["id"],
        "org_code": o["org_code"],
        "name": o["name"],
        "org_type": o["org_type"],
        "status": o["status"],
        "suspended_reason": o["suspended_reason"],
        "late_report_count": o["late_report_count"],
        "compliance_posture": o["compliance_posture"],
        "published_par_total": o["published_par_total"],
        "active_professional_count": o["active_professional_count"],
        "created_at": fmt_dt(o["created_at"]),
        "updated_at": fmt_dt(o["updated_at"]),
        "version": o["version"],
    }


def rule_proposal(p):
    return {
        "id": p["id"],
        "rule_code": p["rule_code"],
        "title": p["title"],
        "body": p["body"],
        "category": p["category"],
        "supersedes_proposal_id": p["supersedes_proposal_id"],
        "status": p["status"],
        "expedited": p["expedited"],
        "comment_period_days": p["comment_period_days"],
        "comment_window_start": fmt_dt(p["comment_window_start"]),
        "comment_window_end": fmt_dt(p["comment_window_end"]),
        "comment_round": p["comment_round"],
        "submitted_by_user_id": p["submitted_by_user_id"],
        "decided_by_user_id": p["decided_by_user_id"],
        "decision_reason": p["decision_reason"],
        "approval_at": fmt_dt(p["approval_at"]),
        "effective_at": fmt_dt(p["effective_at"]),
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def comment_letter(c):
    return {
        "id": c["id"],
        "proposal_id": c["proposal_id"],
        "author_name": c["author_name"],
        "body": c["body"],
        "sentiment": c["sentiment"],
        "status": c["status"],
        "moderation_reason": c["moderation_reason"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def disclosure_submission(s):
    return {
        "id": s["id"],
        "issuer_org_id": s["issuer_org_id"],
        "submission_type": s["submission_type"],
        "event_category": s["event_category"],
        "event_occurred_at": fmt_dt(s["event_occurred_at"]),
        "period_start": fmt_dt(s["period_start"]),
        "period_end": fmt_dt(s["period_end"]),
        "document_uri": s["document_uri"],
        "cusip": s["cusip"],
        "status": s["status"],
        "timeliness": s["timeliness"],
        "deficiency_reason": s["deficiency_reason"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def professional(m):
    return {
        "id": m["id"],
        "full_name": m["full_name"],
        "employer_org_id": m["employer_org_id"],
        "professional_class": m["professional_class"],
        "qualification_status": m["qualification_status"],
        "standing": m["standing"],
        "qualified_at": fmt_dt(m["qualified_at"]),
        "ce_cycle_end": fmt_dt(m["ce_cycle_end"]),
        "ce_grace_end": fmt_dt(m["ce_grace_end"]),
        "ce_credits_total": m["ce_credits_total"],
        "ce_ethics_credits": m["ce_ethics_credits"],
        "may_transact": m["may_transact"],
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
    }


def exam_attempt(a):
    return {
        "id": a["id"],
        "professional_id": a["professional_id"],
        "series_code": a["series_code"],
        "score": a["score"],
        "result": a["result"],
        "created_at": fmt_dt(a["created_at"]),
    }


def trade_report(t):
    return {
        "id": t["id"],
        "dealer_org_id": t["dealer_org_id"],
        "cusip": t["cusip"],
        "trade_type": t["trade_type"],
        "par_amount": t["par_amount"],
        "price": t["price"],
        "executed_at": fmt_dt(t["executed_at"]),
        "reported_at": fmt_dt(t["reported_at"]),
        "late_flag": t["late_flag"],
        "seconds_late": t["seconds_late"],
        "published_par": t["published_par"],
        "capped_flag": t["capped_flag"],
        "status": t["status"],
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def data_subscription(s):
    return {
        "id": s["id"],
        "product_code": s["product_code"],
        "licensee_org_id": s["licensee_org_id"],
        "subscriber_principal": s["subscriber_principal"],
        "license_scope": s["license_scope"],
        "seats": s["seats"],
        "status": s["status"],
        "monthly_fee_cents": s["monthly_fee_cents"],
        "annual_invoice_cents": s["annual_invoice_cents"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def enforcement_referral(r):
    return {
        "id": r["id"],
        "rule_code": r["rule_code"],
        "subject_org_id": r["subject_org_id"],
        "subject_professional_id": r["subject_professional_id"],
        "violation_summary": r["violation_summary"],
        "examining_authority": r["examining_authority"],
        "status": r["status"],
        "created_by_user_id": r["created_by_user_id"],
        "referred_at": fmt_dt(r["referred_at"]),
        "closed_by_user_id": r["closed_by_user_id"],
        "closure_notes": r["closure_notes"],
        "guidance_text": r["guidance_text"],
        "needs_rule_review": r["needs_rule_review"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def solicitation_record(s):
    return {
        "id": s["id"],
        "advisor_org_id": s["advisor_org_id"],
        "municipal_entity_name": s["municipal_entity_name"],
        "compensation_type": s["compensation_type"],
        "compensation_cents": s["compensation_cents"],
        "disclosure_provided": s["disclosure_provided"],
        "created_at": fmt_dt(s["created_at"]),
    }
