"""Entity serializers.  Field lists follow the scaffold entity tables exactly.

Mutable entities carry id / created_at / updated_at / version.
Append-only entities (ClickEvent, AttributionDecision, MonitoringScan,
CommissionLedgerEntry) carry only id / created_at.
"""

MUTABLE_TAIL = ("id", "created_at", "updated_at", "version")
IMMUTABLE_TAIL = ("id", "created_at")

NETWORK_FIELDS = ("name", "fee_model", "fee_bps", "flat_fee_cents",
                  "statement_currency")

AFFILIATE_FIELDS = (
    "legal_name", "contact_email", "partner_type", "network_id",
    "parent_affiliate_id", "sub_affiliate_depth", "payout_currency", "status",
    "suspension_cause", "fraud_risk_score", "fraud_risk_score_trailing",
    "incrementality_score_bps", "incrementality_tier",
    "attributed_conversion_count", "new_customer_attributed_count",
    "coupon_assisted_conversion_count", "accrued_balance_cents",
    "reserved_balance_cents", "lifetime_paid_cents", "tax_document_status",
    "open_violation_case_count", "tracking_link_count",
)

APPLICATION_FIELDS = (
    "affiliate_id", "site_url", "primary_traffic_source",
    "monthly_traffic_estimate", "declared_promo_methods", "product_categories",
    "review_state", "site_quality_score", "brand_suitability_score",
    "screening_outcome", "screened_by_user_id", "decided_by_user_id",
    "revision_round_count", "decision_notes", "conditional_requirements",
)

POLICY_FIELDS = (
    "policy_code", "product_category", "partner_type_scope",
    "new_customer_rate_bps", "returning_customer_rate_bps", "effective_from",
    "effective_to", "status", "superseded_by_policy_id",
)

LINK_FIELDS = ("affiliate_id", "landing_url", "sub_id", "cookie_window_days",
               "device_graph_enabled", "status", "disabled_reason")

CLICK_FIELDS = ("tracking_link_id", "occurred_at", "device_id", "household_id",
                "click_type", "referrer_domain", "paid_search_keyword",
                "is_trademark_term")

CONVERSION_FIELDS = (
    "order_ref", "order_total_cents", "product_category", "customer_ref",
    "is_new_customer", "placed_at", "device_id", "household_id",
    "coupon_code_used", "other_channel_touch", "other_channel_touch_at",
    "attribution_status", "validation_status", "attributed_affiliate_id",
    "attributed_click_id", "commission_policy_id", "candidate_click_count",
    "gross_commission_cents", "payable_commission_cents", "clawed_back_cents",
    "returned_amount_cents",
)

DECISION_FIELDS = (
    "conversion_id", "algorithm_variant", "selected", "candidate_click_count",
    "winning_click_occurred_at", "device_match_mode", "credit_share_bps",
    "computed_commission_cents", "dedup_reason", "evaluated_at",
)

SCAN_FIELDS = ("affiliate_id", "engine", "window_start", "window_end",
               "trademark_hits", "forced_click_ratio_bps",
               "cookie_stuffing_index", "unauthorized_coupon_hits",
               "opened_case_count")

CASE_FIELDS = ("affiliate_id", "source_scan_id", "violation_type",
               "evidence_ref", "detected_at", "state", "severity_weight",
               "failed_verification_count", "remediation_evidence_ref",
               "opened_by_user_id", "last_note")

TAX_FIELDS = ("affiliate_id", "form_type", "tax_id_last4",
              "treaty_withholding_bps", "expires_on", "status",
              "verified_by_user_id")

LEDGER_FIELDS = ("affiliate_id", "conversion_id", "payout_batch_id",
                 "entry_type", "amount_cents", "memo")

BATCH_FIELDS = (
    "network_id", "period_start", "period_end", "state", "line_count",
    "gross_commission_cents", "clawback_cents", "network_fee_cents",
    "withholding_cents", "net_payable_cents", "statement_gross_cents",
    "statement_fee_cents", "network_fee_variance_cents",
    "network_fee_variance_bps", "reconciliation_status", "prepared_by_user_id",
    "approved_by_user_id", "payment_reference", "void_reason",
)

LINE_FIELDS = ("payout_batch_id", "affiliate_id", "gross_cents",
               "clawback_cents", "net_before_fees_cents", "conversion_count",
               "network_fee_cents", "withholding_bps", "withholding_cents",
               "net_cents", "state", "hold_reason", "released_by_user_id")


def _pick(row, fields, tail):
    out = {}
    for name in fields:
        out[name] = row.get(name)
    for name in tail:
        out[name] = row.get(name)
    return out


def network_out(row):
    return _pick(row, NETWORK_FIELDS, MUTABLE_TAIL)


def affiliate_out(row):
    return _pick(row, AFFILIATE_FIELDS, MUTABLE_TAIL)


def application_out(row):
    return _pick(row, APPLICATION_FIELDS, MUTABLE_TAIL)


def policy_out(row):
    return _pick(row, POLICY_FIELDS, MUTABLE_TAIL)


def link_out(row):
    return _pick(row, LINK_FIELDS, MUTABLE_TAIL)


def click_out(row):
    return _pick(row, CLICK_FIELDS, IMMUTABLE_TAIL)


def conversion_out(row):
    return _pick(row, CONVERSION_FIELDS, MUTABLE_TAIL)


def decision_out(row):
    return _pick(row, DECISION_FIELDS, IMMUTABLE_TAIL)


def scan_out(row):
    return _pick(row, SCAN_FIELDS, IMMUTABLE_TAIL)


def case_out(row):
    return _pick(row, CASE_FIELDS, MUTABLE_TAIL)


def tax_out(row):
    return _pick(row, TAX_FIELDS, MUTABLE_TAIL)


def ledger_out(row):
    return _pick(row, LEDGER_FIELDS, IMMUTABLE_TAIL)


def batch_out(row):
    return _pick(row, BATCH_FIELDS, MUTABLE_TAIL)


def line_out(row):
    return _pick(row, LINE_FIELDS, MUTABLE_TAIL)
