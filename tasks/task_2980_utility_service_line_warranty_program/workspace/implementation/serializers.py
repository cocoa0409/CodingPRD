"""Entity representations. Computed fields are derived freshly on every read."""

import derive
import timeutil
from money import decimal_out
from store import store


def _base(rec, fields):
    out = {"id": rec["id"]}
    for name in fields:
        out[name] = rec.get(name)
    return out


def _stamp(out, rec):
    out["created_at"] = rec["created_at"]
    out["updated_at"] = rec["updated_at"]
    out["version"] = rec["version"]
    return out


PARTNER_FIELDS = [
    "name",
    "utility_type",
    "state_code",
    "status",
    "brand_approval_required",
    "min_days_between_drops",
    "max_mailings_per_year",
    "rate_filing_required",
    "bill_insert_supported",
    "suspension_reason",
]


def partner(rec):
    out = _base(rec, PARTNER_FIELDS)
    out["enrolled_premises_count"] = derive.partner_enrolled_premises_count(rec)
    return _stamp(out, rec)


PRODUCT_FIELDS = [
    "partner_id",
    "name",
    "line_type",
    "ownership_boundary",
    "required_owned_segment",
    "monthly_price_cents",
    "waiting_period_days",
    "per_occurrence_cap_cents",
    "annual_cap_cents",
    "permit_covered",
    "restoration_covered_scope",
    "cap_reset_basis",
    "status",
]


def product(rec):
    return _stamp(_base(rec, PRODUCT_FIELDS), rec)


PREMISES_FIELDS = [
    "partner_id",
    "street_address",
    "state_code",
    "owned_segments",
    "do_not_mail",
    "address_status",
    "known_defect_reported_at",
    "regulator_hold",
    "last_mail_decision",
    "last_mail_suppression_reason",
    "last_mailed_campaign_id",
]


def premises(rec):
    out = _base(rec, PREMISES_FIELDS)
    out["mail_count_current_year"] = derive.premises_mail_count_current_year(rec)
    reason = derive.premises_suppression_reason(rec)
    out["suppression_reason"] = reason
    out["suppressed"] = reason != "NONE"
    return _stamp(out, rec)


CAMPAIGN_FIELDS = [
    "partner_id",
    "product_id",
    "name",
    "piece_type",
    "drop_date",
    "requested_quantity",
    "approved_quantity",
    "status",
    "submitted_by_user_id",
    "decision_by_user_id",
    "decision_note",
    "decided_at",
    "revision_count",
    "mailed_count",
    "suppressed_count",
    "mail_dropped_at",
]


def campaign(rec):
    return _stamp(_base(rec, CAMPAIGN_FIELDS), rec)


ENROLLMENT_FIELDS = [
    "premises_id",
    "product_id",
    "source_campaign_id",
    "billing_mode",
    "enrollment_date",
    "term_start",
    "term_end",
    "coverage_effective_at",
    "coverage_status",
    "billing_status",
    "cap_status",
    "monthly_price_cents",
    "prepaid_amount_cents",
    "cap_year_start",
    "past_due_since",
    "retention_hold",
    "renewal_price_cents",
    "renewal_effective_date",
    "renewal_notice_sent_at",
    "renewal_notice_status",
    "renewal_count",
    "cancellation_effective_date",
    "cancellation_reason",
    "refund_cents",
    "credit_cents",
    "cancellation_fee_cents",
]


def enrollment(rec):
    out = _base(rec, ENROLLMENT_FIELDS)
    out["annual_benefit_used_cents"] = derive.annual_benefit_used_cents(rec)
    out["annual_benefit_reserved_cents"] = derive.annual_benefit_reserved_cents(rec)
    out["premium_collected_cents"] = derive.premium_collected_cents(rec)
    out["premium_refunded_cents"] = derive.premium_refunded_cents(rec)
    return _stamp(out, rec)


CLAIM_FIELDS = [
    "enrollment_id",
    "recurrence_of_claim_id",
    "occurrence_root_claim_id",
    "line_type",
    "defect_location",
    "urgency",
    "incident_description",
    "reported_at",
    "status",
    "denial_reason",
    "triage_decided_by_user_id",
    "triage_decided_at",
    "denied_at",
    "appeal_opened_at",
    "appeal_source",
    "appeal_decided_by_user_id",
    "appeal_count",
    "sla_deadline_at",
]


def claim(rec):
    out = _base(rec, CLAIM_FIELDS)
    out["eligibility_assessment"] = derive.eligibility_assessment(rec)
    out["benefit_paid_cents"] = derive.claim_benefit_paid_cents(rec)
    out["occurrence_used_cents"] = derive.occurrence_used_cents(rec)
    return _stamp(out, rec)


CONTRACTOR_FIELDS = [
    "name",
    "state_code",
    "license_number",
    "license_expires_on",
    "line_types_certified",
    "hourly_rate_cents",
    "sla_compliance_pct",
    "max_open_dispatches",
    "permit_pull_authorized",
    "status",
    "sla_breach_count",
]


def contractor(rec):
    out = _base(rec, CONTRACTOR_FIELDS)
    out["open_dispatch_count"] = derive.contractor_open_dispatch_count(rec)
    return _stamp(out, rec)


DISPATCH_FIELDS = [
    "claim_id",
    "contractor_id",
    "supersedes_dispatch_id",
    "selection_mode",
    "selection_score",
    "assigned_at",
    "window_start",
    "window_end",
    "sla_deadline_at",
    "status",
    "responded_at",
    "response_minutes",
    "estimated_benefit_cents",
    "labor_cents",
    "materials_cents",
    "permit_fee_cents",
    "permit_number",
    "restoration_cents",
    "restoration_scope",
    "invoice_total_cents",
    "benefit_paid_cents",
    "customer_responsibility_cents",
    "cancellation_reason",
]


def dispatch(rec):
    out = _base(rec, DISPATCH_FIELDS)
    out["selection_score"] = decimal_out(rec.get("selection_score"))
    return _stamp(out, rec)


LEDGER_FIELDS = [
    "enrollment_id",
    "claim_id",
    "ledger_kind",
    "entry_type",
    "amount_cents",
    "effective_date",
    "cap_year_start",
    "memo",
]


def ledger_entry(rec):
    out = _base(rec, LEDGER_FIELDS)
    out["created_at"] = rec["created_at"]
    return out


COMPLAINT_FIELDS = [
    "partner_id",
    "claim_id",
    "enrollment_id",
    "regulator",
    "allegation",
    "received_at",
    "response_due_at",
    "status",
    "responded_at",
    "response_summary",
    "disposition",
    "remedy_type",
    "remedy_amount_cents",
    "escalation_count",
]


def complaint(rec):
    out = _base(rec, COMPLAINT_FIELDS)
    out["days_overdue"] = complaint_days_overdue(rec)
    return _stamp(out, rec)


def complaint_days_overdue(rec):
    """Whole days past the response deadline, floored and clamped at zero."""
    if rec.get("responded_at"):
        return 0
    due = timeutil.parse_instant(rec["response_due_at"])
    if due is None:
        return 0
    elapsed = timeutil.floor_days_between_instants(due, store.now())
    return max(0, elapsed)
