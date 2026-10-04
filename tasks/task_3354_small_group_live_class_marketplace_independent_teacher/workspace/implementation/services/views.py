"""Serialisers — every declared field of every entity, with computed fields
re-derived at read time so they can never drift from the stored state."""

from datetime import timedelta

from core import clock, constants as C, store

from . import calc


def _section_count(listing):
    return len([
        s for s in store.all_of("sections")
        if s["class_listing_id"] == listing["id"]
        and s["status"] not in ("CANCELLED", "COMPLETED")
    ])


def application_out(app):
    return {
        "id": app["id"],
        "created_at": app["created_at"],
        "updated_at": app["updated_at"],
        "version": app["version"],
        "applicant_user_id": app["applicant_user_id"],
        "applicant_email": app["applicant_email"],
        "display_name": app["display_name"],
        "status": app["status"],
        "screening_outcome": app["screening_outcome"],
        "screening_is_stale": calc.screening_is_stale(app),
        "screening_completed_period_index": app["screening_completed_period_index"],
        "teaching_sample_url": app["teaching_sample_url"],
        "teaching_sample_minutes": app["teaching_sample_minutes"],
        "reviewed_by_user_id": app["reviewed_by_user_id"],
        "reviewer_bound_period_index": app["reviewer_bound_period_index"],
        "decision": app["decision"],
        "decision_reason_code": app["decision_reason_code"],
        "revision_count": app["revision_count"],
        "eligible_for_appeal": calc.eligible_for_appeal(app),
    }


def teacher_out(teacher):
    scores = calc.risk_scores(teacher["id"])
    lifetime = calc.lifetime_net_earnings(teacher["id"])
    validity = teacher["screening_validity_period_index"]
    return {
        "id": teacher["id"],
        "created_at": teacher["created_at"],
        "updated_at": teacher["updated_at"],
        "version": teacher["version"],
        "application_id": teacher["application_id"],
        "display_name": teacher["display_name"],
        "status": teacher["status"],
        "screening_validity_period_index": validity,
        "payout_tax_document_status": calc.tax_document_status(lifetime),
        "suspension_reason": teacher["suspension_reason"],
        "suspension_trigger": teacher["suspension_trigger"],
        "open_report_count": scores["open_report_count"],
        "open_report_risk_score": scores["open_report_risk_score"],
        "upheld_report_risk_score": scores["upheld_report_risk_score"],
        "actionable_risk_score": scores["actionable_risk_score"],
        "peak_actionable_risk_score": teacher["peak_actionable_risk_score"],
        "lifetime_net_earnings_cents": lifetime,
        "lifetime_fee_reversed_cents": sum(
            p["platform_fee_reversed_cents"]
            for p in store.all_of("payouts")
            if p["teacher_id"] == teacher["id"] and p["status"] != "VOIDED"
        ),
        "lifetime_teacher_liability_cents": sum(
            p["teacher_liability_cents"]
            for p in store.all_of("payouts")
            if p["teacher_id"] == teacher["id"] and p["status"] != "VOIDED"
        ),
        "unpaid_earnings_cents": calc.unpaid_earnings(teacher["id"]),
        "re_screen_required": (
            validity is not None and clock.period() > validity
        ),
    }


def listing_out(listing):
    return {
        "id": listing["id"],
        "created_at": listing["created_at"],
        "updated_at": listing["updated_at"],
        "version": listing["version"],
        "teacher_id": listing["teacher_id"],
        "title": listing["title"],
        "format": listing["format"],
        "min_age": listing["min_age"],
        "max_age": listing["max_age"],
        "max_learners": listing["max_learners"],
        "list_price_cents": listing["list_price_cents"],
        "content_review_state": listing["content_review_state"],
        "policy_rejection_reason_code": listing["policy_rejection_reason_code"],
        "lifecycle_state": listing["lifecycle_state"],
        "listing_sequence": listing["listing_sequence"],
        "section_count": _section_count(listing),
    }


def section_out(section):
    occ = calc.occupancy(section)
    cutoff = section["start_utc_dt"] - timedelta(hours=C.AUTO_CANCEL_CUTOFF_HOURS)
    return {
        "id": section["id"],
        "created_at": section["created_at"],
        "updated_at": section["updated_at"],
        "version": section["version"],
        "class_listing_id": section["class_listing_id"],
        "timezone": section["timezone"],
        "start_utc": section["start_utc_raw"],
        "end_utc": section["end_utc_raw"],
        "min_learners": section["min_learners"],
        "capacity": section["capacity"],
        "expected_learners": section["expected_learners"],
        "status": section["status"],
        "scheduled_start_confirmed": clock.now() <= section["start_utc_dt"],
        "settled": occ["settled"],
        "enrolled_count": occ["enrolled_count"],
        "reserved_count": occ["reserved_count"],
        "seats_remaining": occ["seats_remaining"],
        "enrollment_min_met": occ["enrollment_min_met"],
        "outcome": section["outcome"],
        "cancellation_cutoff_utc": clock.fmt(cutoff),
    }


def learner_out(learner):
    tier = learner.get("subscription_tier") or "NONE"
    return {
        "id": learner["id"],
        "created_at": learner["created_at"],
        "updated_at": learner["updated_at"],
        "version": learner["version"],
        "display_name": learner["display_name"],
        "birth_date": learner["birth_date_raw"],
        "parent_user_id": learner["parent_user_id"],
        "subscription_tier": tier,
        "subscription_discount_pct": C.SUB_DISCOUNT[tier],
        "confirmation_credit_cents": learner["confirmation_credit_cents"],
        "enrollment_sequence": learner["enrollment_sequence"],
        "abuse_strike_count": learner["abuse_strike_count"],
    }


def enrollment_out(enrollment):
    return {
        "id": enrollment["id"],
        "created_at": enrollment["created_at"],
        "updated_at": enrollment["updated_at"],
        "version": enrollment["version"],
        "section_id": enrollment["section_id"],
        "learner_id": enrollment["learner_id"],
        "status": enrollment["status"],
        "coupon_code": enrollment["coupon_code"],
        "coupon_discount_cents": enrollment["coupon_discount_cents"],
        "subscription_discount_cents": enrollment["subscription_discount_cents"],
        "discounted_price_cents": enrollment["discounted_price_cents"],
        "refund_category": enrollment["refund_category"],
        "refund_cents": enrollment["refund_cents"],
        "cancelled_by": enrollment["cancelled_by"],
        "credit_applied_cents": enrollment["credit_applied_cents"],
        "cash_refund_cents": enrollment["cash_refund_cents"],
    }


def payout_out(payout):
    cap = calc.approval_cap_figures(payout)
    return {
        "id": payout["id"],
        "created_at": payout["created_at"],
        "updated_at": payout["updated_at"],
        "version": payout["version"],
        "teacher_id": payout["teacher_id"],
        "expected_teacher_version": payout["expected_teacher_version"],
        "period_start": payout["period_start_raw"],
        "period_end": payout["period_end_raw"],
        "status": payout["status"],
        "gross_earnings_cents": payout["gross_earnings_cents"],
        "fee_rate_applied": payout["fee_rate_applied"],
        "platform_fee_cents": payout["platform_fee_cents"],
        "net_payout_cents": payout["net_payout_cents"],
        "net_after_refunds_cents": calc.payout_net_after_refunds(payout),
        "payout_proration_factor": cap["payout_proration_factor"],
        "approval_status": payout["approval_status"],
        "tax_document_status": payout["tax_document_status"],
        "refund_period_index": payout["refund_period_index"],
        "teacher_liability_cents": payout["teacher_liability_cents"],
        "platform_fee_reversed_cents": payout["platform_fee_reversed_cents"],
    }


def report_out(report):
    return {
        "id": report["id"],
        "created_at": report["created_at"],
        "updated_at": report["updated_at"],
        "version": report["version"],
        "teacher_id": report["teacher_id"],
        "class_listing_id": report["class_listing_id"],
        "reported_by_user_id": report["reported_by_user_id"],
        "severity": report["severity"],
        "category": report["category"],
        "severity_weight": report["severity_weight"],
        "status": report["status"],
        "disposition": report["disposition"],
        "high_severity": report["severity"] == "HIGH",
        "is_terminal": report["status"] in ("RESOLVED", "CLOSED"),
    }
