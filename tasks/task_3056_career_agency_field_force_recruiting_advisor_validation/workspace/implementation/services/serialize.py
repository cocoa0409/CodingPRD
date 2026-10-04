"""JSON projections for every entity.

Field names are exactly those declared in scaffold §1.1; the common field set
(id, created_at, updated_at, version) is carried by every entity (PRD §2.5).
Decimal quantities are exposed as JSON numbers.
"""

from datetime import datetime
from decimal import Decimal

from db import ts


def _num(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        # PRD §2.2: timestamps are ISO 8601 UTC with three fractional digits.
        return ts(value)
    return value


def _out(row, fields):
    result = {
        "id": row.get("id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "version": row.get("version", 1),
    }
    for name in fields:
        result[name] = _num(row.get(name))
    return result


_ADVISOR = [
    "full_name", "email", "district_office_id", "sponsoring_advisor_id", "rank",
    "contract_status", "validation_posture", "insurance_license_status",
    "licensing_locked", "securities_registration_status", "appointment_status",
    "team_production_cents", "override_income_cents", "chargeback_balance_cents",
    "renewal_commission_cents", "orphan_pool_access", "terminated_at",
]
_OFFICE = [
    "office_code", "name", "region_code", "state_code", "override_rate_pct",
    "override_cap_cents", "override_paid_cents", "status",
]
_CANDIDATE = [
    "full_name", "source_channel", "campus_name", "district_office_id",
    "prior_candidate_id", "stage", "reengagement_count", "entered_stage_at", "notes",
]
_ASSESSMENT = [
    "candidate_id", "assessment_version", "scheduled_date", "scored_date",
    "raw_score", "competency_scores", "weighted_score", "outcome",
    "locked_weights", "status",
]
_CONTRACT = [
    "advisor_id", "candidate_id", "contract_type", "start_date", "end_date",
    "training_allowance_total_cents", "training_allowance_paid_cents",
    "validation_requirement_cents", "training_allowance_mode", "contract_status",
]
_PERIOD = [
    "contract_id", "advisor_id", "period_number", "start_date", "end_date",
    "required_production_cents", "achieved_production_cents", "extension_count",
    "extended_end_date", "evaluated_at", "status",
]
_LICENSE = [
    "advisor_id", "product_line", "license_number", "effective_date", "expires_at",
    "appointment_required", "status",
]
_REGISTRATION = [
    "advisor_id", "registration_type", "crd_number", "effective_date",
    "expires_at", "prerequisite_registration_id", "status",
]
_APPOINTMENT = [
    "advisor_id", "requires_license_id", "carrier_name", "state_code",
    "requested_date", "appointment_date", "appointment_status",
]
_POLICY = [
    "policy_number", "writing_advisor_id", "carrier_name", "product_line",
    "annual_premium_cents", "issue_date", "lapse_date", "reinstatement_date",
    "is_advanced_commission", "months_inforce", "orphaned", "status",
]
_JOINT = [
    "policy_id", "lead_advisor_id", "support_advisor_id", "split_pct_lead",
    "status", "submitted_at",
]
_CREDIT = [
    "policy_id", "advisor_id", "credit_type", "credit_pct",
    "gross_commission_cents", "net_commission_cents", "advanced_paid_cents",
    "case_gross_commission_cents", "chargeback_assessed_cents", "recovered_cents",
    "chargeback_reason", "status",
]
_PERSISTENCY = [
    "advisor_id", "measurement_period", "measurement_start", "measurement_end",
    "policies_issued", "policies_persisted", "persistency_pct",
    "persistency_tier", "renewal_rate_pct", "renewal_commission_cents", "status",
]
_ORPHAN = [
    "policy_id", "from_advisor_id", "to_advisor_id", "assignment_method",
    "assigned_at", "status", "rejection_reason",
]


def advisor(r):
    return _out(r, _ADVISOR)


def office(r):
    return _out(r, _OFFICE)


def candidate(r):
    return _out(r, _CANDIDATE)


def assessment(r):
    return _out(r, _ASSESSMENT)


def contract(r):
    return _out(r, _CONTRACT)


def period(r):
    return _out(r, _PERIOD)


def license_(r):
    return _out(r, _LICENSE)


def registration(r):
    return _out(r, _REGISTRATION)


def appointment(r):
    return _out(r, _APPOINTMENT)


def policy(r):
    return _out(r, _POLICY)


def joint(r):
    return _out(r, _JOINT)


def credit(r):
    return _out(r, _CREDIT)


def persistency(r):
    return _out(r, _PERSISTENCY)


def orphan(r):
    return _out(r, _ORPHAN)