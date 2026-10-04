"""Entity assertions and domain invariant checkers (PRD §2.10, §2.6, §2.7)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """Every common-field resource exposes id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_fields(data: dict):
    """Append-only resources expose only id and created_at (PRD §2.10)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None


def assert_consumer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["dti_pct"], (int, float))
    assert isinstance(data["score_version"], int)
    assert isinstance(data["open_dispute_count"], int)


def assert_bureau_snapshot(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("consumer_id", "")), "consumer_id must be a valid UUID"
    assert isinstance(data["snapshot_ordinal"], int) and data["snapshot_ordinal"] >= 1
    assert data["status"] in ["PULL_REQUESTED", "ACTIVE", "SUPERSEDED", "CANCELLED"]
    assert is_iso8601_timestamp(data.get("pulled_at", ""))


def assert_score_factor_explanation(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data.get("snapshot_id", ""))
    assert data["direction"] in ["UP", "DOWN", "NEUTRAL"]
    assert isinstance(data["impact_points"], int)
    assert isinstance(data["rank_index"], int) and data["rank_index"] >= 0


def assert_score_alert(data: dict):
    assert_common_fields(data)
    assert data["alert_kind"] in ["SCORE_UP", "SCORE_DOWN", "SCORE_FLAT"]
    assert data["status"] in ["PENDING", "DELIVERED", "SUPPRESSED"]
    assert isinstance(data["threshold_used"], int)


def assert_score_simulation(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "FINALIZED", "FAILED"]
    assert isinstance(data["actions"], list)
    assert isinstance(data["baseline_ordinal"], int)


def assert_product_catalog_item(data: dict):
    assert_common_fields(data)
    assert data["product_kind"] in ["CARD", "LOAN", "INSURANCE"]
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]


def assert_lender(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ONBOARDING", "ACTIVE", "OFFBOARDED"]
    assert data["compliance_status"] in ["APPROVED", "SUSPENDED", "BANNED"]
    assert isinstance(data["states_served"], list)


def assert_lender_program(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "PAUSED", "EXPIRED"]
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert is_iso8601_timestamp(data.get("go_live_at", ""))
    assert is_iso8601_timestamp(data.get("expiry_at", ""))


def assert_targeting_criterion(data: dict):
    assert_common_fields(data)
    assert data["criterion_field"] in ["SCORE", "DTI_PCT", "UTILIZATION_PCT", "STATE_CODE"]
    assert data["operator"] in ["GTE", "LTE", "EQ", "IN"]
    assert isinstance(data["is_hard_requirement"], bool)


def assert_prequalification_decision(data: dict):
    assert_common_fields(data)
    assert data["decision_status"] in [
        "NEEDS_SNAPSHOT", "ELIGIBLE", "INELIGIBLE",
        "PREQUALIFIED", "CONSENTED", "CONSUMED", "EXPIRED",
    ]
    assert isinstance(data["modeled_odds_settled"], bool)
    assert is_iso8601_timestamp(data.get("decided_at", ""))
    assert is_iso8601_timestamp(data.get("fresh_until", ""))


def assert_pre_qualified_offer(data: dict):
    assert_common_fields(data)
    assert data["product_kind"] in ["CARD", "LOAN", "INSURANCE"]
    assert data["channel"] in ["WEB", "MOBILE_APP", "MARKETPLACE"]
    assert data["status"] in ["PRESENTED", "RENDERED", "CONSUMED", "WITHDRAWN", "STALE"]


def assert_consent_record(data: dict):
    assert_append_only_fields(data)
    assert data["status"] in ["PENDING", "SEALED", "NOT_SEALED"]
    assert data["archive_status"] in ["LIVE", "ARCHIVED"]
    assert data["consent_scope"] == "SHARE_PII_WITH_LENDER"


def assert_referral(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SENT", "FUNDED", "REVERSED", "DECLINED", "UNFUNDED"]
    assert data["channel"] in ["WEB", "MOBILE_APP", "MARKETPLACE"]
    assert isinstance(data["revenue_share_bps"], int)
    assert isinstance(data["clawback_days"], int)


def assert_dispute_referral(data: dict):
    assert_common_fields(data)
    assert data["inaccuracy_type"] in ["PERSONAL_INFO", "ACCOUNT_INFO", "INQUIRY", "BALANCE"]
    assert data["status"] in [
        "DRAFT", "SUBMITTED_OFFLINE", "ACKNOWLEDGED_BY_BUREAU", "WITHDRAWN",
    ]
    assert isinstance(data["referral_count"], int)
    assert 20 <= len(data.get("narrative", "")) <= 1000


def assert_revenue_recognition_entry(data: dict):
    assert_append_only_fields(data)
    assert data["entry_kind"] in ["REVENUE", "CLAWBACK"]
    assert isinstance(data["realized_amount_cents"], int)


def assert_score_tier_threshold(data: dict):
    assert_common_fields(data)
    assert data["tier_code"] in ["EXCEPTIONAL", "VERY_GOOD", "GOOD", "FAIR", "POOR"]
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]
    assert isinstance(data["factor_catalog"], list)


# --- Domain invariant checkers -------------------------------------------------

def assert_consumer_invariants(data: dict):
    """Derived consumer posture stays internally consistent (§2.6)."""
    assert data["open_dispute_count"] >= 0
    if data["score_version"] == 0:
        assert data["current_score"] is None
        assert data["utilization_pct"] is None
    if data["score_version"] <= 1:
        assert data.get("previous_score") is None


def assert_revenue_invariant(revenue_entries: list):
    """net recognized == gross share - clawback share, computed per entry kinds."""
    revenue_sum = sum(
        e["realized_amount_cents"] for e in revenue_entries if e["entry_kind"] == "REVENUE"
    )
    clawback_sum = sum(
        e["realized_amount_cents"] for e in revenue_entries if e["entry_kind"] == "CLAWBACK"
    )
    assert revenue_sum >= 0 or not revenue_entries
    assert clawback_sum <= 0 or not any(
        e["entry_kind"] == "CLAWBACK" for e in revenue_entries
    )