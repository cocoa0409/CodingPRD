"""Wire projections for the eleven entity types (PRD section 3).

Nine types carry `updated_at` and `version`; StreamRateCard and DspRevenueLine
are immutable and expose only `id` and `created_at` (PRD section 2.4).
"""

import db

MUTABLE_COMMON = ("id", "created_at", "updated_at", "version")
IMMUTABLE_COMMON = ("id", "created_at")

DISTRIBUTOR_FIELDS = ("name", "legal_entity", "default_returns_reserve_pct")
ARTIST_FIELDS = ("legal_name", "email")
DEAL_FIELDS = (
    "distributor_id", "deal_type", "distribution_fee_pct", "profit_share_label_pct",
    "services_fee_pct", "services_monthly_fee_cents", "term_start_date",
    "term_end_date", "territory_codes", "cross_collateralized",
    "advance_amount_cents", "marketing_budget_cents", "objection_window_days",
    "post_term_collection_days", "status", "advance_payment_reference",
    "executed_at", "termination_effective_date", "post_term_collection_end_date",
    "advance_recouped_cents", "unrecouped_advance_cents",
    "net_receipts_to_date_cents", "post_recoupment_net_receipts_cents",
    "recoupment_status", "marketing_committed_cents",
)
RELEASE_FIELDS = (
    "deal_id", "primary_artist_id", "upc", "title", "planned_release_date",
    "actual_release_date", "formats", "advance_share_cents", "status",
    "reversion_eligible_date", "net_receipts_to_date_cents",
    "release_advance_recouped_cents", "unrecouped_advance_share_cents",
    "recoupable_marketing_applied_cents",
)
AGREEMENT_FIELDS = (
    "artist_id", "release_id", "royalty_rate_pct", "escalated_royalty_rate_pct",
    "advance_amount_cents", "recording_costs_cents", "recording_recoupable_pct",
    "marketing_recoup_share_pct", "supersedes_agreement_id", "status",
    "active_royalty_rate_pct", "proposed_royalty_rate_pct",
    "proposed_advance_amount_cents", "unrecouped_artist_advance_cents",
    "unrecouped_recording_cents", "post_term_collection_end_date",
)
SPEND_FIELDS = (
    "release_id", "category", "amount_cents", "vendor", "recoupability",
    "status", "requested_by_user_id", "decided_by_user_id", "approved_at",
    "settled_amount_cents", "revision_note",
)
RATE_CARD_FIELDS = (
    "dsp_code", "territory_code", "tier", "rate_micros_per_stream",
    "effective_from", "effective_to",
)
REPORT_FIELDS = (
    "deal_id", "dsp_code", "period_start", "period_end", "status",
    "submitted_by_user_id", "gross_receipts_cents", "distributor_share_cents",
    "net_receipts_cents", "advance_applied_cents", "accepted_at",
    "dispute_reason",
)
LINE_FIELDS = (
    "report_id", "release_id", "territory_code", "tier", "stream_count",
    "applied_rate_micros_per_stream", "resolved_revenue_cents",
    "net_receipts_cents",
)
RUN_FIELDS = (
    "release_id", "distributor_id", "units_planned",
    "unit_manufacturing_cost_cents", "window_start", "window_end",
    "returns_reserve_pct", "status", "reserve_status", "units_manufactured",
    "units_shipped", "units_returned", "wholesale_unit_price_cents",
    "returns_rate", "effective_reserve_pct", "reserve_initial_cents",
    "reserve_held_cents", "reserve_liquidated_cents", "manufacturing_cost_cents",
    "physical_net_receipts_cents",
)
STATEMENT_FIELDS = (
    "artist_agreement_id", "period_start", "period_end", "basis_variant",
    "status", "audit_status", "prepared_by_user_id", "issued_by_user_id",
    "issued_at", "objection_deadline", "finalized_at",
    "applied_royalty_rate_pct", "digital_royalty_base_cents",
    "physical_royalty_base_cents", "gross_royalty_cents", "marketing_cap_cents",
    "advance_applied_cents", "recording_applied_cents", "marketing_applied_cents",
    "reserve_withheld_cents", "net_payable_cents", "objection_reason_code",
    "objection_disputed_amount_cents", "objection_narrative",
    "objection_filed_at", "objection_resolution", "objection_adjustment_cents",
    "audit_scope_period_start", "audit_scope_period_end", "auditor_name",
    "audit_findings_adjustment_cents", "audit_cost_bearer", "revision_count",
)

ACTIVE_DEAL_STATUSES = ("EXECUTED", "TERMINATION_NOTICE", "POST_TERM_COLLECTION")
ROLLUP_AGREEMENT_STATUSES = ("ACTIVE", "AMENDMENT_PENDING", "POST_TERM")


def _project(record, fields, common):
    out = {}
    for key in common:
        out[key] = record.get(key)
    for key in fields:
        out[key] = record.get(key)
    return out


def distributor(record):
    out = _project(record, DISTRIBUTOR_FIELDS, MUTABLE_COMMON)
    out["active_deal_count"] = sum(
        1 for deal in db.store.deals.values()
        if deal["distributor_id"] == record["id"]
        and deal["status"] in ACTIVE_DEAL_STATUSES
    )
    return out


def artist(record):
    out = _project(record, ARTIST_FIELDS, MUTABLE_COMMON)
    agreements = [
        a for a in db.store.agreements.values() if a["artist_id"] == record["id"]
    ]
    agreement_ids = set(a["id"] for a in agreements)
    lifetime = 0
    for statement in db.store.statements.values():
        if statement["artist_agreement_id"] in agreement_ids \
                and statement["status"] == "FINALIZED":
            lifetime += statement.get("net_payable_cents") or 0
    out["lifetime_paid_cents"] = lifetime
    out["unrecouped_advance_total_cents"] = sum(
        a.get("unrecouped_artist_advance_cents") or 0
        for a in agreements
        if a["status"] in ROLLUP_AGREEMENT_STATUSES
    )
    return out


def deal(record):
    return _project(record, DEAL_FIELDS, MUTABLE_COMMON)


def release(record):
    return _project(record, RELEASE_FIELDS, MUTABLE_COMMON)


def agreement(record):
    return _project(record, AGREEMENT_FIELDS, MUTABLE_COMMON)


def spend(record):
    return _project(record, SPEND_FIELDS, MUTABLE_COMMON)


def rate_card(record):
    return _project(record, RATE_CARD_FIELDS, IMMUTABLE_COMMON)


def report(record):
    return _project(record, REPORT_FIELDS, MUTABLE_COMMON)


def line(record):
    return _project(record, LINE_FIELDS, IMMUTABLE_COMMON)


def run(record):
    return _project(record, RUN_FIELDS, MUTABLE_COMMON)


def statement(record):
    return _project(record, STATEMENT_FIELDS, MUTABLE_COMMON)
