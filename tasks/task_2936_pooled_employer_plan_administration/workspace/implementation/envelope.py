"""PRD 2.2 response envelope, PRD 2.3 pagination and entity serialisation."""

import json
import random
import re
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import Response, request

import errors

_ALNUM = string.ascii_uppercase + string.digits
_DEC_MARK = "@@__dec__@@"
_DEC_RE = re.compile(r'"' + re.escape(_DEC_MARK) + r'(-?[0-9.]+)' + re.escape(_DEC_MARK) + r'"')


def _default(obj):
    if isinstance(obj, Decimal):
        return _DEC_MARK + format(obj, "f") + _DEC_MARK
    raise TypeError(repr(obj) + " is not JSON serialisable")


def _dump(payload):
    text = json.dumps(payload, default=_default)
    return _DEC_RE.sub(r"\1", text)


def api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def api_request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _meta():
    return {
        "api_request_id": api_request_id(),
        "api_request_timestamp": api_request_timestamp(),
    }


def respond(payload, status):
    return Response(_dump(payload), status=status, mimetype="application/json")


def ok_object(data, status=200):
    return respond({"meta": _meta(), "response_type": "object", "data": data}, status)


def ok_created(data):
    return ok_object(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return respond({"meta": meta, "response_type": "array", "data": rows}, 200)


def error_response(error_id, message=None):
    err = errors.ApiError(error_id, message)
    return respond(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message},
        },
        err.http_status,
    )


# --------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0,
# min 0, no upper bound. Out-of-range is ERR_VALIDATION, never clamped.
# --------------------------------------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0

_INT_RE = re.compile(r"^[+-]?\d+$")


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name, None)
    if raw is None:
        return default
    raw = raw.strip()
    if not _INT_RE.match(raw):
        errors.fail("ERR_VALIDATION", "`%s` must be an integer." % name)
    value = int(raw)
    if value < minimum:
        errors.fail("ERR_VALIDATION", "`%s` must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        errors.fail("ERR_VALIDATION", "`%s` may not exceed %d." % (name, maximum))
    return value


def page_params():
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paginate(rows, view):
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([view(r) for r in window], limit, offset, total)


# --------------------------------------------------------------------------
# Entity serialisation. Field order follows the entity declaration order;
# `id`, `created_at`, `updated_at` and `version` are the common properties of
# PRD 2.4. A FeeDisclosure carries only `id` and `created_at`.
# --------------------------------------------------------------------------

FIELDS = {
    "providers": [
        "legal_name",
        "ein",
        "fidelity_bond_amount_cents",
        "registration_status",
        "registration_number",
        "registration_effective_date",
        "registered_at",
    ],
    "plans": [
        "pooled_plan_provider_id",
        "plan_name",
        "plan_number",
        "plan_year_end_date",
        "status",
        "effective_date",
        "base_eligibility_min_age",
        "base_eligibility_service_months",
        "base_vesting_schedule",
        "base_match_formula_code",
        "participant_count",
        "cumulative_enrolled_participant_count",
        "transferred_out_participant_count",
        "headcount_control_delta",
        "active_employer_count",
        "suspended_employer_count",
        "compliance_posture",
        "audit_required",
        "total_validated_contributions_cents",
        "aggregate_receivable_cents",
        "total_assets_cents",
        "total_corrections_funded_cents",
        "transferred_out_cents",
        "expense_recovered_cents",
        "contribution_control_delta_cents",
    ],
    "service_providers": [
        "plan_document_id",
        "legal_name",
        "provider_type",
        "revenue_sharing_bps",
        "direct_fee_cents_per_participant",
        "affiliated_service_provider_id",
        "holds_fiduciary_role",
    ],
    "allocations": [
        "plan_document_id",
        "service_provider_id",
        "fiduciary_role",
        "effective_from",
        "effective_to",
        "status",
        "acknowledged_at",
        "acknowledgment_statement",
        "revoked_at",
        "revoked_reason",
    ],
    "employers": [
        "plan_document_id",
        "legal_name",
        "ein",
        "election_window_close_date",
        "adoption_status",
        "effective_adoption_date",
        "participant_count",
        "hce_count",
        "nhce_count",
        "benefiting_hce_count",
        "benefiting_nhce_count",
        "hce_avg_deferral_pct",
        "nhce_avg_deferral_pct",
        "is_small_plan",
        "employer_audit_required",
        "contribution_hold",
        "open_correction_count",
        "account_balance_cents",
        "contribution_receivable_cents",
        "revenue_sharing_credit_cents",
        "exited_at",
    ],
    "elections": [
        "adopting_employer_id",
        "election_sequence",
        "eligibility_min_age",
        "eligibility_service_months",
        "vesting_schedule",
        "match_formula_code",
        "match_tier_1_pct",
        "match_tier_1_limit_pct",
        "match_tier_2_pct",
        "match_tier_2_limit_pct",
        "nondiscrimination_track",
        "status",
        "signatory_name",
        "return_reason",
        "deficiency_code",
        "approved_at",
    ],
    "batches": [
        "adopting_employer_id",
        "pay_period_start",
        "pay_period_end",
        "pay_date",
        "withholding_date",
        "payroll_provider_reference",
        "total_eligible_compensation_cents",
        "total_deferral_cents",
        "total_match_cents",
        "total_loan_repayment_cents",
        "participant_line_count",
        "expected_match_cents",
        "batch_total_cents",
        "deposit_rule",
        "deposit_due_date",
        "status",
        "validated_at",
        "reconciliation_note",
    ],
    "deposits": [
        "payroll_batch_id",
        "deposit_date",
        "amount_cents",
        "deposit_reference",
        "deposit_status",
        "timeliness_status",
        "business_days_elapsed",
        "late_by_business_days",
        "posted_at",
        "posting_reference",
        "correction_method",
        "recovery_date",
        "actual_investment_return_cents",
        "lost_earnings_cents",
        "restoration_cents",
        "excise_tax_cents",
        "form_5330_reference",
        "funded_at",
        "reversal_reason",
    ],
    "tests": [
        "plan_document_id",
        "adopting_employer_id",
        "test_type",
        "scope",
        "plan_year",
        "status",
        "population_hce_count",
        "population_nhce_count",
        "benefiting_hce_count",
        "benefiting_nhce_count",
        "hce_benefiting_pct",
        "nhce_benefiting_pct",
        "ratio_pct",
        "hce_avg_deferral_pct",
        "nhce_avg_deferral_pct",
        "adp_limit_pct",
        "exemption_applied",
        "run_at",
        "failure_reason",
        "closed_reason",
    ],
    "filings": [
        "plan_document_id",
        "plan_year",
        "filing_status",
        "prepared_by_user_id",
        "prepared_at",
        "audit_attested_at",
        "audit_opinion",
        "audit_firm_service_provider_id",
        "employer_data_certified_at",
        "certified_by_user_id",
        "certified_employer_count",
        "late_deposit_schedule_h_line_cents",
        "fidelity_bond_minimum_cents",
        "audit_required",
        "filing_deadline_date",
        "filed_date",
        "is_late_filing",
        "acknowledgment_reference",
    ],
    "exits": [
        "adopting_employer_id",
        "exit_type",
        "requested_exit_date",
        "blackout_start_date",
        "blackout_end_date",
        "successor_plan_name",
        "status",
        "transferred_participant_count",
        "gross_account_balance_cents",
        "admin_recovery_cents",
        "flat_exit_fee_cents",
        "deductions_applied_cents",
        "unrecovered_deduction_cents",
        "transfer_amount_cents",
        "settled_amount_cents",
        "approved_at",
        "settled_at",
        "reversal_reason",
    ],
    "disclosures": [
        "plan_document_id",
        "disclosure_period_start",
        "disclosure_period_end",
        "allocation_method",
        "revenue_sharing_pool_cents",
        "gross_direct_fees_cents",
        "expense_rebate_pct",
        "revenue_sharing_offset_cents",
        "net_plan_expense_cents",
        "total_revenue_sharing_allocated_cents",
        "residual_cents_distributed",
        "allocation_lines",
        "eligible_employer_count",
        "disclosed_at",
    ],
}

# A FeeDisclosure is an immutable event row: no updated_at, no version.
UNVERSIONED = {"disclosures"}


def view(collection):
    fields = FIELDS[collection]
    versioned = collection not in UNVERSIONED

    def render(record):
        out = {"id": record["id"]}
        for name in fields:
            out[name] = record.get(name)
        out["created_at"] = record["created_at"]
        if versioned:
            out["updated_at"] = record["updated_at"]
            out["version"] = record["version"]
        return out

    return render


VIEWS = {name: view(name) for name in FIELDS}
