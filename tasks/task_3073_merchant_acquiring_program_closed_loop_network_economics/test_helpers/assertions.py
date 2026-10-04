"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Shared common-property checks ────────────────────

def _assert_common(data: dict):
    """id + created_at + updated_at + version — the shared mutable shape."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    """Append-only evidence rows carry ONLY id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only rows carry no updated_at"
    assert "version" not in data, "append-only rows carry no version"


# ─── Per-entity assertions ────────────────────────────

def assert_industry_category(data: dict):
    _assert_common(data)
    assert isinstance(data["industry_code"], str) and data["industry_code"]
    assert isinstance(data["industry_name"], str) and data["industry_name"]
    assert data["risk_tier"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["base_discount_rate_bps"], int)
    assert data["base_discount_rate_bps"] >= 0
    assert isinstance(data["high_risk_flag"], bool)


def assert_merchant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("industry_category_id", "")), "industry_category_id must be UUID"
    assert isinstance(data["merchant_name"], str) and data["merchant_name"]
    assert isinstance(data["region_code"], str)
    assert data["acquisition_channel"] in ("DIRECT", "THIRD_PARTY")
    assert data["volume_tier"] in ("ACTIVITY", "FIXED", "LOW")
    assert data["acceptance_status"] in ("PROSPECT", "ACCEPTED", "ACTIVE", "DORMANT", "SUPPRESSED")
    for field in (
        "applied_discount_rate_bps", "billed_volume_mtd_cents",
        "rolling_90d_billed_volume_cents", "rolling_90d_settled_volume_cents",
        "last_batch_discount_fee_cents", "reserve_required_cents",
        "reserve_held_cents", "status_version",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_declined_attempt(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data.get("merchant_id", "")), "merchant_id must be UUID"
    assert data["card_product"] in ("GREEN", "GOLD", "PLATINUM", "CENTURION")
    assert isinstance(data["attempted_amount_cents"], int)
    assert data["attempted_amount_cents"] > 0
    assert data["decline_reason"] in (
        "MERCHANT_NOT_ACCEPTED", "INSUFFICIENT_CREDIT", "FRAUD_SUSPECT", "EXPIRED_CARD")
    assert is_iso8601_timestamp(data.get("occurred_at", "")), "occurred_at must be ISO 8601"


def assert_acceptance_gap(data: dict):
    _assert_common(data)
    assert isinstance(data["region_code"], str)
    assert is_valid_uuid(data.get("industry_category_id", ""))
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["window_days"] in (30, 60, 90)
    assert isinstance(data["decline_count"], int) and data["decline_count"] >= 0
    assert isinstance(data["declined_volume_cents"], int)
    assert data["qualified_status"] in ("PROSPECTING", "BELOW_THRESHOLD", "DORMANT")
    assert isinstance(data["sweep_index"], int)


def assert_sweep_index_stamp(data: dict):
    _assert_append_only(data)
    assert isinstance(data["sweep_index"], int)
    assert is_iso8601_timestamp(data.get("rolled_at", ""))


def assert_offer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert data["audience_segment"] in (
        "HIGH_SPEND", "MEDIUM_SPEND", "LOW_SPEND", "ALL_CARDMEMBERS")
    assert isinstance(data["min_segment_spend_cents"], int)
    assert data["min_segment_spend_cents"] >= 0
    assert isinstance(data["reward_bps"], int)
    assert data["reward_bps"] >= 0
    assert data["privacy_state"] in (
        "DRAFT", "PRIVACY_REVIEW", "MERCHANT_CONSENT", "LIVE", "TERMINATED")
    assert isinstance(data["audience_size"], int)
    assert isinstance(data["aggregated_spend_cents"], int)
    assert isinstance(data["accepted_count"], int)


def assert_cardmember(data: dict):
    _assert_common(data)
    assert isinstance(data["member_name"], str) and data["member_name"]
    assert data["card_product"] in ("GREEN", "GOLD", "PLATINUM", "CENTURION")
    assert isinstance(data["annual_fee_cents"], int)
    assert isinstance(data["trailing_lowest_month_spend_cents"], int)
    assert isinstance(data["reward_points_balance"], int)
    assert data["lounge_access_tier"] in ("NONE", "STANDARD", "UNLIMITED")
    assert data["member_status"] in ("PENDING", "ACTIVE", "DELINQUENT", "CLOSED")


def assert_offer_acceptance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("offer_id", ""))
    assert is_valid_uuid(data.get("cardmember_id", ""))
    assert isinstance(data["trigger_amount_cents"], int)
    assert isinstance(data["reward_amount_cents"], int)
    assert data["acceptance_status"] in ("PENDING", "APPROVED", "PAID", "REVERSED")


def assert_redemption_pool(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("offer_id", ""))
    assert data["funder"] in ("MERCHANT", "NETWORK")
    for field in ("initial_funded_cents", "balance_cents",
                  "topup_total_cents", "consumed_total_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_annual_fee_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cardmember_id", ""))
    assert isinstance(data["statement_year"], int) and data["statement_year"] >= 2026
    for field in ("principal_fee_cents", "authorised_user_count", "per_user_fee_cents",
                  "gross_fee_assessed_cents", "value_fund_allocation_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["statement_status"] in ("DRAFT", "ASSESSED", "DISBURSED", "VOIDED")


def assert_value_fund_ledger_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("source_statement_id", ""))
    assert data["entry_kind"] in (
        "FEE_ALLOCATION", "FEE_ALLOCATION_REVERSAL", "LOUNGE_PASS_GRANT")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["created_seq"], int)


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert isinstance(data["settlement_cycle"], int) and data["settlement_cycle"] >= 1
    for field in ("gross_volume_cents", "refund_volume_cents", "post_refund_volume_cents",
                  "discount_fee_cents", "net_funding_cents", "final_discount_fee_cents",
                  "final_reserve_withholding_cents", "funding_batch_seq",
                  "finalized_at_batch_seq"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["settlement_status"] in ("CAPTURED", "IN_FUNDING", "SETTLED", "REVERSED")


def assert_dispute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cardmember_id", ""))
    assert is_valid_uuid(data.get("original_merchant_id", ""))
    assert is_valid_uuid(data.get("final_merchant_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["dispute_status"] in (
        "OPEN", "MERCHANT_RESPONDED", "AUTO_ACCEPTED", "WON", "LOST", "WITHDRAWN")
    assert data["representment_stage"] in ("NONE", "FIRST_ROUND", "CLOSED")
    assert isinstance(data["network_settled_cents"], int)
    assert isinstance(data["chargeback_count_reserved"], int)
    assert data["priority"] in ("HIGH", "STANDARD")


def assert_acceptance_complaint(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert is_valid_uuid(data.get("cardmember_id", ""))
    assert data["complaint_type"] in (
        "MERCHANT_NOT_ACCEPTED", "STAFF_ATTITUDE", "TERMINAL_TECHNICAL", "PRICING_SURCHARGE")
    assert data["complaint_status"] in ("FILED", "UNDER_REVIEW", "UPHELD", "DISMISSED")


def assert_merchant_risk_state(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert isinstance(data["rolling_chargeback_count"], int)
    assert isinstance(data["rolling_dispute_amount_cents"], int)
    assert isinstance(data["unresolved_chargeback_count"], int)
    assert isinstance(data["suppression_flag"], bool)


# ─── Domain invariant checkers ────────────────────────

def assert_settlement_invariants(data: dict):
    """Structural invariants that must hold regardless of which batch sealed it."""
    assert data["post_refund_volume_cents"] == (
        data["gross_volume_cents"] - data["refund_volume_cents"])
    assert data["funding_batch_seq"] >= 1
    if data["settlement_status"] == "REVERSED":
        assert data["final_discount_fee_cents"] == 0
        assert data["final_reserve_withholding_cents"] == 0
        assert data["net_funding_cents"] == 0


def assert_pool_invariants(data: dict):
    """A pool never over-consumes and never holds a negative balance."""
    assert data["balance_cents"] >= 0
    assert data["consumed_total_cents"] >= 0
    assert data["topup_total_cents"] >= 0


def assert_merchant_invariants(data: dict):
    assert data["reserve_required_cents"] >= 0
    assert data["reserve_held_cents"] >= 0
    assert data["billed_volume_mtd_cents"] >= 0