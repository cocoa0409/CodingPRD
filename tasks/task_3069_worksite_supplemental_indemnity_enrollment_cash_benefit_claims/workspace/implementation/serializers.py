"""Serializers: convert internal records to API representations."""
import db
import services


_COMMON = ("id", "created_at", "updated_at", "version")


def _base(rec, fields):
    out = {f: rec.get(f) for f in fields}
    for f in _COMMON:
        out[f] = rec.get(f)
    return out


def employer_group(rec):
    out = _base(rec, [
        "name", "group_code", "status",
        "participation_minimum_pct", "participation_minimum_count",
        "proration_convention",
    ])
    out["eligible_employee_count"] = services.eligible_employee_count(rec["id"])
    out["enrolled_count"] = services.enrolled_count(rec["id"])
    return out


def benefit_counselor(rec):
    return _base(rec, ["license_id", "full_name", "home_state", "status"])


def enrollment_campaign(rec):
    return _base(rec, [
        "employer_group_id", "counselor_id", "window_start", "window_end",
        "guaranteed_issue", "status", "required_enrollments", "participation_met",
    ])


def policy_series(rec):
    return _base(rec, ["series_code", "product_line", "status", "current_schedule_id"])


def benefit_schedule(rec):
    return _base(rec, [
        "policy_series_id", "schedule_version", "effective_date", "benefit_items",
        "monthly_premium_cents", "wellness_benefit_cents", "wellness_waiting_months",
        "preexisting_exclusion_months", "status",
    ])


def employee(rec):
    return _base(rec, [
        "employer_group_id", "employee_ref", "full_name", "hire_date",
        "preexisting_diagnosis_codes", "status",
    ])


def policy(rec):
    return _base(rec, [
        "campaign_id", "employee_id", "policy_series_id", "benefit_schedule_id",
        "certificate_number", "premium_mode", "monthly_premium_cents",
        "issue_date", "coverage_start_date", "lifetime_paid_cents",
        "paid_occurrences_by_year", "status",
    ])


def claim(rec):
    return _base(rec, [
        "policy_id", "event_code", "service_date", "diagnosis_code",
        "procedure_code", "claimed_occurrences", "provisional_payable_cents",
        "payable_amount_cents", "adjudicated_occurrences", "denial_reason", "status",
    ])


def claim_document(rec):
    return _base(rec, ["claim_id", "doc_type", "content_ref", "status"])


def wellness_benefit(rec):
    return _base(rec, ["policy_id", "calendar_year", "service_date", "amount_cents", "status"])


def payroll_cycle(rec):
    return _base(rec, [
        "employer_group_id", "period_start", "period_end", "total_posted_cents", "status",
    ])


def deduction_line(rec):
    return _base(rec, [
        "payroll_cycle_id", "policy_id", "employee_id", "tax_treatment",
        "coverage_days", "amount_cents", "status",
    ])
