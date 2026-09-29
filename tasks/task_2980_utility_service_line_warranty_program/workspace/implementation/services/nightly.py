"""The nightly operations run: six phases in a pinned order, created_at ASC.

Every phase is guarded by a condition its own action falsifies, so invoking the
run twice against an unmoved clock leaves the state it found and reports eleven
empty lists the second time.
"""

import config
import derive
import serializers
import timeutil
from services import cascades
from store import ordered, store, touch


def run():
    result = {
        "ran_at": store.now_iso(),
        "sla_breached_dispatch_ids": [],
        "probated_contractor_ids": [],
        "cancelled_dispatch_ids": [],
        "overdue_complaint_ids": [],
        "escalated_complaint_ids": [],
        "activated_enrollment_ids": [],
        "suspended_enrollment_ids": [],
        "lapsed_enrollment_ids": [],
        "closed_claim_ids": [],
        "renewed_enrollment_ids": [],
        "cap_year_reset_enrollment_ids": [],
    }
    _phase_1_breaches(result)
    _phase_2_probation(result)
    _phase_3_complaints(result)
    _phase_4_coverage(result)
    _phase_5_stale_denials(result)
    _phase_6_renewals(result)
    return result


def _phase_1_breaches(result):
    """An ASSIGNED dispatch at or past its response deadline breaches."""
    now = store.now()
    for dispatch in ordered(store.dispatches, lambda d: d["status"] == "ASSIGNED"):
        deadline = timeutil.parse_instant(dispatch.get("sla_deadline_at"))
        if deadline is None or deadline > now:
            continue
        dispatch["status"] = "SLA_BREACHED"
        touch(dispatch)
        contractor = store.contractors.get(dispatch["contractor_id"])
        if contractor is not None:
            contractor["sla_breach_count"] = contractor.get("sla_breach_count", 0) + 1
            touch(contractor)
        result["sla_breached_dispatch_ids"].append(dispatch["id"])


def _phase_2_probation(result):
    """Breaches recorded moments ago count toward the probation threshold."""
    for contractor in ordered(store.contractors, lambda c: c["status"] == "ACTIVE"):
        if contractor.get("sla_breach_count", 0) < config.SLA_BREACH_PROBATION_THRESHOLD:
            continue
        contractor["status"] = "PROBATION"
        touch(contractor)
        result["probated_contractor_ids"].append(contractor["id"])
        for dispatch in ordered(
            store.dispatches,
            lambda d: d["contractor_id"] == contractor["id"] and d["status"] == "ASSIGNED",
        ):
            cascades.cancel_dispatch(dispatch, "CONTRACTOR_PROBATION")
            result["cancelled_dispatch_ids"].append(dispatch["id"])
            claim = derive.claim_of_dispatch(dispatch)
            if claim is not None:
                cascades.revert_claim_if_idle(claim)


def _phase_3_complaints(result):
    """Both hops may reach the same complaint when it is far enough past due."""
    for complaint in ordered(store.complaints, lambda c: c["status"] == "OPEN"):
        due = timeutil.parse_instant(complaint["response_due_at"])
        if due is None or due > store.now():
            continue
        complaint["status"] = "OVERDUE"
        touch(complaint)
        result["overdue_complaint_ids"].append(complaint["id"])
    for complaint in ordered(store.complaints, lambda c: c["status"] == "OVERDUE"):
        if serializers.complaint_days_overdue(complaint) < config.COMPLAINT_ESCALATION_DAYS:
            continue
        complaint["status"] = "ESCALATED"
        complaint["escalation_count"] = complaint.get("escalation_count", 0) + 1
        touch(complaint)
        result["escalated_complaint_ids"].append(complaint["id"])


def _phase_4_coverage(result):
    """One pass per policy, first matching transition wins."""
    today = store.today()
    now = store.now()
    for enrollment in ordered(store.enrollments):
        status = enrollment["coverage_status"]
        if status == "PENDING_WAITING_PERIOD":
            effective = timeutil.parse_instant(enrollment["coverage_effective_at"])
            if effective is not None and effective <= now:
                enrollment["coverage_status"] = "ACTIVE"
                touch(enrollment)
                result["activated_enrollment_ids"].append(enrollment["id"])
            continue
        past_due = timeutil.parse_date(enrollment.get("past_due_since")) if enrollment.get("past_due_since") else None
        if status == "ACTIVE" and enrollment["billing_status"] == "PAST_DUE" and past_due is not None:
            if timeutil.whole_days_between(past_due, today) >= config.ARREARS_SUSPEND_DAYS:
                enrollment["coverage_status"] = "SUSPENDED_NONPAY"
                touch(enrollment)
                result["suspended_enrollment_ids"].append(enrollment["id"])
            continue
        if status == "SUSPENDED_NONPAY" and past_due is not None:
            if timeutil.whole_days_between(past_due, today) >= config.ARREARS_LAPSE_DAYS:
                enrollment["coverage_status"] = "LAPSED"
                enrollment["retention_hold"] = False
                touch(enrollment)
                result["lapsed_enrollment_ids"].append(enrollment["id"])
            continue


def _phase_5_stale_denials(result):
    """A denial left alone for more than 30 days closes for good."""
    now = store.now()
    for claim in ordered(store.claims, lambda c: c["status"] == "DENIED"):
        denied_at = timeutil.parse_instant(claim.get("denied_at"))
        if denied_at is None:
            continue
        if timeutil.add_days(denied_at, config.CLAIM_CLOSE_DAYS) < now:
            claim["status"] = "CLOSED"
            touch(claim)
            result["closed_claim_ids"].append(claim["id"])


def _phase_6_renewals(result):
    """The term rolls over whether or not a compliant notice was issued."""
    today = store.today()
    for enrollment in ordered(store.enrollments):
        if enrollment["coverage_status"] not in config.LIVE_COVERAGE_STATUSES:
            continue
        term_end = timeutil.parse_date(enrollment["term_end"])
        if term_end is None or term_end > today:
            continue
        noticed = (
            enrollment["renewal_notice_status"] == "SENT"
            and enrollment.get("renewal_effective_date") == enrollment["term_end"]
            and enrollment.get("renewal_price_cents") is not None
        )
        if noticed:
            enrollment["monthly_price_cents"] = enrollment["renewal_price_cents"]
            enrollment["renewal_notice_status"] = "APPLIED"
        else:
            enrollment["renewal_notice_status"] = "NOT_APPLIED_NO_COMPLIANT_NOTICE"
        enrollment["term_end"] = timeutil.render_date(timeutil.add_years(term_end, 1))
        cap_year_start = timeutil.parse_date(enrollment["cap_year_start"])
        enrollment["cap_year_start"] = timeutil.render_date(timeutil.add_years(cap_year_start, 1))
        enrollment["renewal_count"] = enrollment.get("renewal_count", 0) + 1
        enrollment["cap_status"] = "WITHIN_CAP"
        touch(enrollment)
        result["renewed_enrollment_ids"].append(enrollment["id"])
        result["cap_year_reset_enrollment_ids"].append(enrollment["id"])
