"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


ACCOUNT_STATUSES = ["PENDING_VERIFICATION", "ACTIVE", "SUSPENDED", "APPEAL_PENDING", "SUSPENDED_FINAL"]
VERIFICATION_STATUSES = ["SUBMITTED", "APPROVED", "REJECTED"]
APPEAL_STATUSES = ["SUBMITTED", "UNDER_REVIEW", "UPHELD", "OVERTURNED"]
CAMPAIGN_STATUSES = ["DRAFT", "ACTIVE", "PAUSED", "ENDED"]
PAUSE_ORIGINS = ["NONE", "ADVERTISER", "SUSPENSION", "NO_ELIGIBLE_ADS"]
AD_STATUSES = ["DRAFT", "UNDER_REVIEW", "ELIGIBLE", "DISAPPROVED"]
AD_CATEGORIES = ["GENERAL", "ALCOHOL", "GAMBLING", "HEALTHCARE", "FINANCIAL"]
MATCH_TYPES = ["EXACT", "PHRASE", "BROAD"]
REVIEW_OUTCOMES = ["PENDING_AUTO", "AUTO_APPROVED", "NEEDS_HUMAN", "HUMAN_APPROVED", "HUMAN_VIOLATION"]
AUTOMATED_VERDICTS = ["CLEAN", "FLAGGED_RESTRICTED"]
INVOICE_KINDS = ["THRESHOLD", "MONTHLY"]
INVOICE_STATUSES = ["ISSUED", "PARTIALLY_PAID", "PAID", "OVERDUE"]


def assert_advertiser_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["business_name"], str) and len(data["business_name"]) > 0
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert data["status"] in ACCOUNT_STATUSES
    assert isinstance(data["upheld_appeal_count"], int) and data["upheld_appeal_count"] >= 0
    assert isinstance(data["lifetime_valid_served_cents"], int)
    assert isinstance(data["lifetime_billed_cents"], int)
    assert isinstance(data["lifetime_overdelivery_credit_cents"], int)
    assert isinstance(data["lifetime_invalid_click_credit_cents"], int)


def assert_identity_verification(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in VERIFICATION_STATUSES
    assert isinstance(data["legal_business_name"], str)
    assert isinstance(data["registration_number"], str)
    assert data["document_type"] in ["BUSINESS_LICENSE", "TAX_CERTIFICATE", "GOVERNMENT_ID"]
    assert isinstance(data["disclosure_consent"], bool)


def assert_appeal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in APPEAL_STATUSES
    assert isinstance(data["argument_text"], str)


def assert_billing_profile(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["payment_method_type"] in ["CARD", "INVOICING"]
    assert isinstance(data["billing_threshold_cents"], int) and data["billing_threshold_cents"] > 0
    assert isinstance(data["unbilled_cost_cents"], int)
    assert isinstance(data["pending_credit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_campaign(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in CAMPAIGN_STATUSES
    assert data["pause_origin"] in PAUSE_ORIGINS
    assert isinstance(data["daily_budget_cents"], int) and data["daily_budget_cents"] >= 100
    assert isinstance(data["eligible_ad_count"], int) and data["eligible_ad_count"] >= 0
    assert isinstance(data["served_lifetime_cents"], int)
    assert isinstance(data["click_count_lifetime"], int)
    assert isinstance(data["monthly_cap_provisional_cents"], int)


def assert_ad_group(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0


def assert_ad(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in AD_STATUSES
    assert data["category"] in AD_CATEGORIES
    assert isinstance(data["headline"], str) and len(data["headline"]) > 0
    assert isinstance(data["quality_ectr_score"], int) and 1 <= data["quality_ectr_score"] <= 10
    assert isinstance(data["quality_relevance_score"], int) and 1 <= data["quality_relevance_score"] <= 10
    assert isinstance(data["quality_lp_score"], int) and 1 <= data["quality_lp_score"] <= 10
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0


def assert_keyword(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["match_type"] in MATCH_TYPES
    assert isinstance(data["is_negative"], bool)
    assert isinstance(data["text"], str)
    assert isinstance(data["normalized_text"], str)


def assert_policy_review(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["outcome"] in REVIEW_OUTCOMES
    assert data["automated_verdict"] in AUTOMATED_VERDICTS


def assert_auction_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["clicked"], bool)
    assert isinstance(data["is_invalid_click"], bool)
    assert isinstance(data["winner_ad_rank"], int)
    assert isinstance(data["charged_cents"], int)
    assert isinstance(data["quality_score_final_centi"], int)


def assert_daily_spend_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["served_cents"], int)
    assert isinstance(data["click_count"], int)


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["kind"] in INVOICE_KINDS
    assert data["status"] in INVOICE_STATUSES
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["overdelivery_credit_cents"], int)
    assert isinstance(data["invalid_click_credit_cents"], int)


def quality_score_centi(ectr: int, relevance: int, lp: int) -> int:
    """Quality score formula: 50*ectr + 30*relevance + 20*lp (integer centi-score)."""
    return 50 * ectr + 30 * relevance + 20 * lp


def actual_cpc_cents(winner_bid_cents: int, runner_up_ad_rank, winner_quality_centi: int) -> int:
    """Actual CPC: floor(runner_up_rank / winner_quality) + 1, capped at winner bid;
    without runner-up, min(winner bid, 5)."""
    if runner_up_ad_rank is None:
        return min(winner_bid_cents, 5)
    base = runner_up_ad_rank // winner_quality_centi
    return min(winner_bid_cents, base + 1)


def provisional_monthly_cap_cents(daily_budget_cents: int) -> int:
    """Forward-looking monthly cap: daily_budget * 304 // 10."""
    return daily_budget_cents * 304 // 10


def assert_account_fiscal_invariant(account: dict, billing_profile: dict):
    """Conserved fiscal quantity across invoices, unbilled cost and pending credit."""
    lhs = (
        account["lifetime_billed_cents"]
        + billing_profile["unbilled_cost_cents"]
        - billing_profile["pending_credit_cents"]
    )
    rhs = (
        account["lifetime_valid_served_cents"]
        - account["lifetime_overdelivery_credit_cents"]
    )
    assert lhs == rhs, f"Fiscal invariant broken: {lhs} != {rhs}"


def assert_campaign_ledger_consistency(campaign: dict, daily_records: list):
    """Campaign aggregates must equal the sum of their daily parts."""
    total_served = sum(r["served_cents"] for r in daily_records)
    total_clicks = sum(r["click_count"] for r in daily_records)
    assert campaign["served_lifetime_cents"] == total_served, (
        f"served_lifetime_cents {campaign['served_lifetime_cents']} != sum of daily {total_served}"
    )
    assert campaign["click_count_lifetime"] == total_clicks, (
        f"click_count_lifetime {campaign['click_count_lifetime']} != sum of daily {total_clicks}"
    )
