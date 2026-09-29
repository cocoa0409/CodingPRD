"""Entity projections (PRD 2.4) plus the lazy aggregate refreshers of 2.10.

Aggregates are functions of the current row set, so they are re-derived
immediately before serialization as well as after every mutation.
"""

import calc
from store import db

AUDIT = ("created_at", "updated_at", "version")

PROGRAM_FIELDS = (
    "id", "name", "fiscal_year", "qualification_metric",
    "sales_period_start", "sales_period_end", "budget_total_cents",
    "status", "gross_up_policy", "gross_up_policy_locked",
    "per_person_cost_basis_cents", "committed_budget_cents",
    "budget_headroom_cents", "budget_posture", "cancellation_exposure_cents",
    "reported_award_total_cents", "sales_lift_pct", "satisfaction_index",
    "qualified_count", "travelled_count", "cancellation_reason",
) + AUDIT

TIER_FIELDS = (
    "id", "program_id", "tier_code", "tier_rank", "qualification_threshold",
    "budget_per_qualifier_cents", "guest_allowance", "air_cabin_class",
    "upgrade_allowance_cents", "service_load_bp", "created_at",
)

QUALIFIER_FIELDS = (
    "id", "program_id", "employee_code", "full_name", "baseline_metric",
    "actual_metric", "guest_count", "award_status", "tax_status",
    "assigned_tier_id", "committed_cost_cents", "taxable_award_cents",
    "notified_at",
) + AUDIT

DESTINATION_FIELDS = (
    "id", "program_id", "city", "country_code", "per_person_cost_cents",
    "risk_score", "air_gateway_code", "status", "inspection_status",
    "inspection_score", "inspected_by_user_id", "inspected_at",
) + AUDIT

CONTRACT_FIELDS = (
    "id", "program_id", "destination_id", "supplier_name", "supplier_kind",
    "status", "round_count", "room_block_count", "contracted_nights",
    "stay_start_at", "stay_end_at", "nightly_rate_cents",
    "attrition_allowance_bp", "force_majeure_clause", "exposure_basis",
    "room_nights_blocked", "room_nights_confirmed", "room_nights_available",
    "attrition_posture", "last_proposed_by_user_id",
    "last_countered_by_user_id", "executed_by_user_id", "executed_at",
    "withdrawal_reason",
) + AUDIT

MILESTONE_FIELDS = (
    "id", "contract_id", "sequence", "due_at", "amount_cents",
    "refundable_bp", "status", "requires_finance_review", "paid_at",
) + AUDIT

REGISTRATION_FIELDS = (
    "id", "program_id", "qualifier_id", "registration_kind",
    "guest_of_registration_id", "attendance_status", "arrival_date",
    "departure_date", "rooms", "room_nights", "waiver_on_file",
    "air_status", "air_cabin_class", "air_deviation_pre_days",
    "air_deviation_post_days", "air_base_fare_cents",
    "air_upgrade_cost_cents", "air_deviation_fee_cents", "air_change_count",
    "air_change_fee_total_cents", "cost_cents", "satisfaction_score",
    "cancellation_reason",
) + AUDIT

ACTIVITY_FIELDS = (
    "id", "program_id", "name", "start_at", "end_at", "capacity",
    "risk_level", "status", "booked_count", "waitlist_count",
) + AUDIT

SIGNUP_FIELDS = (
    "id", "activity_id", "registration_id", "status", "promoted_at",
) + AUDIT

REPORT_FIELDS = (
    "id", "qualifier_id", "tax_year", "award_value_cents", "gross_up_method",
    "combined_rate_bp", "gross_up_cents", "reported_value_cents", "status",
    "filed_by_user_id", "filed_at", "voided_by_user_id", "void_reason",
) + AUDIT


def _project(row, fields):
    return {name: row.get(name) for name in fields}


# ----------------------------------------------------------------- refreshers
def refresh_program(program):
    """Re-derive every rollup that is a pure function of the row set.

    The budget rollup is only re-derived once it has actually run for this
    program (PRD 3.1: the budget identity "takes hold the first time the budget
    rollup runs"); until then the charter's seeded zeros are what the program
    reports, including budget_headroom_cents.
    """
    if program.get("budget_rollup_armed"):
        calc.program_budget_rollup(db, program)
    calc.program_counts(db, program)
    calc.reported_award_total(db, program)
    return program


def refresh_contract(contract):
    calc.room_night_ledger(db, contract)
    return contract


def refresh_activity(activity):
    calc.activity_counts(db, activity)
    return activity


# ---------------------------------------------------------------- serializers
def program(row):
    return _project(refresh_program(row), PROGRAM_FIELDS)


def award_tier(row):
    return _project(row, TIER_FIELDS)


def qualifier(row):
    return _project(row, QUALIFIER_FIELDS)


def destination(row):
    return _project(row, DESTINATION_FIELDS)


def supplier_contract(row):
    return _project(refresh_contract(row), CONTRACT_FIELDS)


def deposit_milestone(row):
    return _project(row, MILESTONE_FIELDS)


def registration(row):
    return _project(row, REGISTRATION_FIELDS)


def onsite_activity(row):
    return _project(refresh_activity(row), ACTIVITY_FIELDS)


def activity_signup(row):
    return _project(row, SIGNUP_FIELDS)


def tax_award_report(row):
    return _project(row, REPORT_FIELDS)
