"""Output shapes -- one field list per entity of scaffold 1.1."""

from fractions import Fraction

from money import to_number

COMMON = ("id", "created_at", "updated_at", "version")

STUDIO = ("id", "legal_name", "contact_email", "country_code") + COMMON[1:]

PUBLISHER = STUDIO

PUBLISHER_USER = ("id", "publisher_id", "display_name", "function") + COMMON[1:]

AGREEMENT = (
    "id",
    "studio_id",
    "publisher_id",
    "title",
    "advance_total_cents",
    "royalty_rate_bps",
    "recoupable_cost_cap_bps",
    "platform_fee_bps",
    "live_ops_quarterly_funding_cents",
    "ship_date_original",
    "ship_date_current",
    "schedule_slip_days",
    "status",
    "funding_posture",
    "recoupment_state",
    "uplift_funded_cents",
    "funding_pool_cents",
    "committed_cents",
    "available_funding_cents",
    "accepted_value_cents",
    "advance_disbursed_cents",
    "holdback_reserve_cents",
    "withheld_payment_cents",
    "advance_recouped_cents",
    "unrecouped_advance_cents",
    "royalties_paid_to_date_cents",
    "breach_count",
    "accepted_milestone_ratio",
    "sequel_rights_holder",
    "ip_reversion_state",
    "post_launch_support_state",
    "live_ops_drawn_cents",
    "terminated_at",
) + COMMON[1:]

MILESTONE = (
    "id",
    "agreement_id",
    "depends_on_milestone_id",
    "sequence_index",
    "title",
    "gate_profile",
    "funded_amount_cents",
    "uplift_cents",
    "contractor_budget_cents",
    "acceptance_criteria",
    "status",
    "content_threshold_relief_pct",
    "cure_count",
    "cure_deadline_at",
    "open_condition_indexes",
    "latest_build_number",
    "accepted_at",
) + COMMON[1:]

BUILD = (
    "id",
    "milestone_id",
    "build_number",
    "feature_completeness_pct",
    "crash_free_sessions_pct",
    "content_completeness_pct",
    "known_blocker_count",
    "addressed_condition_indexes",
    "release_notes",
    "readiness_score",
    "gate_state",
    "submitted_at",
) + COMMON[1:]

# PRD 2.4: "PublisherReview is the single exception ... it exposes only id and
# created_at -- it has neither updated_at nor version".
REVIEW = (
    "id",
    "build_id",
    "reviewer_user_id",
    "verdict",
    "conditions",
    "cure_days",
    "review_window_start_at",
    "review_window_end_at",
    "cure_deadline_at",
    "notes",
    "decided_at",
    "created_at",
)

PAYMENT = (
    "id",
    "milestone_id",
    "authorized_by_user_id",
    "scheduled_amount_cents",
    "contractor_overrun_cents",
    "gross_amount_cents",
    "holdback_bps",
    "holdback_cents",
    "net_amount_cents",
    "status",
    "memo",
    "authorized_at",
) + COMMON[1:]

CHANGE_ORDER = (
    "id",
    "agreement_id",
    "target_milestone_id",
    "order_type",
    "requested_amount_cents",
    "ship_date_delta_days",
    "content_threshold_relief_pct",
    "rationale",
    "state",
    "decision_note",
    "decided_at",
) + COMMON[1:]

ENGAGEMENT = (
    "id",
    "milestone_id",
    "studio_id",
    "vendor_code",
    "scope_summary",
    "committed_cents",
    "start_date",
    "end_date",
    "status",
    "approved_invoice_total_cents",
) + COMMON[1:]

INVOICE = (
    "id",
    "engagement_id",
    "invoice_number",
    "amount_cents",
    "period_end_date",
    "description",
    "status",
    "rejection_reason",
    "decided_at",
) + COMMON[1:]

STATEMENT = (
    "id",
    "agreement_id",
    "period_label",
    "revenue_lines",
    "recoupable_cost_cents",
    "distributable_total_cents",
    "cost_deduction_cents",
    "recoupment_base_cents",
    "recoup_applied_cents",
    "royalty_base_cents",
    "provisional_royalty_payable_cents",
    "final_royalty_payable_cents",
    "state",
    "finalized_at",
) + COMMON[1:]


def _value(value):
    if isinstance(value, Fraction):
        return to_number(value)
    if isinstance(value, list):
        return [_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    return value


def pick(row, keys):
    return {key: _value(row.get(key)) for key in keys}


def studio(row):
    return pick(row, STUDIO)


def publisher(row):
    return pick(row, PUBLISHER)


def publisher_user(row):
    return pick(row, PUBLISHER_USER)


def agreement(row):
    return pick(row, AGREEMENT)


def milestone(row):
    return pick(row, MILESTONE)


def build(row):
    return pick(row, BUILD)


def review(row):
    return pick(row, REVIEW)


def payment(row):
    return pick(row, PAYMENT)


def change_order(row):
    return pick(row, CHANGE_ORDER)


def engagement(row):
    return pick(row, ENGAGEMENT)


def invoice(row):
    return pick(row, INVOICE)


def statement(row):
    return pick(row, STATEMENT)
