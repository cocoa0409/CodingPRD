"""Entity -> JSON projections. Field sets come straight from the entity tables."""
from response import jsonable

COMMON = ["id", "created_at", "updated_at", "version"]

ISSUER_FIELDS = COMMON + [
    "name",
    "state_code",
    "entity_type",
    "prior_late_annual_filings",
    "prior_late_event_notices",
    "has_prior_material_event",
    "is_bank_qualified_eligible",
    "disclosure_risk_score",
]

FIRM_FIELDS = COMMON + [
    "name",
    "firm_type",
    "msrb_registration_id",
    "is_suspended",
]

DEAL_FIELDS = COMMON + [
    "issuer_id",
    "municipal_advisor_firm_id",
    "series_designation",
    "tax_status",
    "dated_date",
    "expected_par_amount_usd",
    "par_amount_usd",
    "sale_method",
    "status",
    "disclosure_clearance",
    "requires_g17_letter",
    "requires_notice_of_sale",
    "gross_spread_basis",
    "takedown_per_bond_usd",
    "management_fee_per_bond_usd",
    "expenses_per_bond_usd",
    "winning_bid_price_pct",
    "issue_price_total_usd",
    "gross_spread_total_usd",
    "gross_spread_per_bond_usd",
    "credit_enhancement_premium_usd",
    "net_proceeds_to_issuer_usd",
    "arbitrage_yield_pct",
    "par_allotted_total_usd",
    "post_issuance_handoff_status",
    "record_retention_years",
    "cancellation_reason",
]

TRANCHE_FIELDS = COMMON + [
    "deal_id",
    "sequence_number",
    "maturity_date",
    "principal_amount_usd",
    "coupon_rate_pct",
    "yield_pct",
    "is_callable",
    "first_call_date",
    "call_price_pct",
    "periods_to_maturity",
    "periods_to_call",
    "price_to_maturity_pct",
    "price_to_call_pct",
    "reoffering_price_pct",
    "is_priced_to_call",
    "is_insured",
    "rating_basis",
    "par_allotted_usd",
    "par_unsold_usd",
    "refunded_tranche_id",
]

ENHANCEMENT_FIELDS = COMMON + [
    "deal_id",
    "provider_name",
    "enhancement_type",
    "enhanced_rating",
    "premium_bps",
    "insured_tranche_ids",
    "status",
    "insured_debt_service_usd",
    "premium_usd",
    "withdrawal_reason",
]

STATEMENT_FIELDS = COMMON + [
    "deal_id",
    "version_label",
    "is_preliminary",
    "status",
    "draft_round",
    "mandatory_sections_approved",
    "posted_preliminary_at",
    "posted_final_at",
    "revision_reason",
]

SECTION_FIELDS = COMMON + [
    "official_statement_id",
    "parent_section_id",
    "section_code",
    "title",
    "body_text",
    "section_type",
    "is_material_risk",
    "references_credit_enhancement",
    "review_status",
    "authored_by_user_id",
    "approved_by_user_id",
    "word_count",
]

UNDERTAKING_FIELDS = COMMON + [
    "deal_id",
    "annual_report_due_days",
    "material_event_notice_days",
    "dissemination_agent",
    "audited_financials_included",
    "status",
]

ENGAGEMENT_FIELDS = COMMON + [
    "deal_id",
    "agency",
    "status",
    "assigned_analyst_user_id",
    "info_request_count",
    "latest_information_request",
    "assigned_rating",
    "outlook",
]

PRESENTATION_FIELDS = COMMON + [
    "rating_engagement_id",
    "starts_at",
    "ends_at",
    "attendee_count",
    "status",
    "cancellation_reason",
]

MEMBER_FIELDS = COMMON + [
    "deal_id",
    "firm_id",
    "member_role",
    "liability_pct",
    "takedown_share_pct",
    "priority_rank",
    "status",
    "liability_par_usd",
    "takedown_credit_usd",
]

PERIOD_FIELDS = COMMON + [
    "deal_id",
    "period_type",
    "opens_at",
    "closes_at",
    "priority_policy",
    "status",
    "allotment_run_count",
    "orders_received_count",
    "allotted_order_count",
    "reopen_reason",
]

ORDER_FIELDS = COMMON + [
    "order_period_id",
    "maturity_tranche_id",
    "syndicate_member_id",
    "order_type",
    "par_requested_usd",
    "price_or_yield_pct",
    "submitted_at",
    "par_allotted_usd",
    "status",
    "cancellation_reason",
]

DOCUMENT_FIELDS = COMMON + [
    "deal_id",
    "doc_type",
    "is_required",
    "execution_status",
    "signatory_role",
    "signatory_name",
    "executed_at",
    "waiver_reason",
]


def _project(row, fields):
    return dict((name, jsonable(row.get(name))) for name in fields)


def issuer(row):
    return _project(row, ISSUER_FIELDS)


def firm(row):
    return _project(row, FIRM_FIELDS)


def deal(row):
    return _project(row, DEAL_FIELDS)


def tranche(row):
    return _project(row, TRANCHE_FIELDS)


def enhancement(row):
    return _project(row, ENHANCEMENT_FIELDS)


def statement(row):
    return _project(row, STATEMENT_FIELDS)


def section(row):
    return _project(row, SECTION_FIELDS)


def undertaking(row):
    return _project(row, UNDERTAKING_FIELDS)


def engagement(row):
    return _project(row, ENGAGEMENT_FIELDS)


def presentation(row):
    return _project(row, PRESENTATION_FIELDS)


def member(row):
    return _project(row, MEMBER_FIELDS)


def period(row):
    return _project(row, PERIOD_FIELDS)


def order(row):
    return _project(row, ORDER_FIELDS)


def document(row):
    return _project(row, DOCUMENT_FIELDS)
