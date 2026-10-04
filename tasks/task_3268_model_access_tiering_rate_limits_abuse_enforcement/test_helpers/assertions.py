"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_organization(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("legal_name"), str) and len(data["legal_name"]) > 0
    assert data.get("status") in ["PROVISIONAL", "ACTIVE", "RESTRICTED", "SUSPENDED", "TERMINATED"]
    assert data.get("tier") in ["TIER_1", "TIER_2", "TIER_3", "TIER_4", "ENTERPRISE"]
    assert isinstance(data.get("lifetime_spend_cents"), int)
    assert isinstance(data.get("qualifying_payment_count"), int)
    assert isinstance(data.get("credit_balance_cents"), int)
    assert data["credit_balance_cents"] >= 0, "credit balance may never go negative"
    assert "pinned_model_version_id" in data
    assert "enterprise_agreement_id" in data


def assert_payment_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only resource must not expose updated_at"
    assert "version" not in data, "append-only resource must not expose version"
    assert data.get("kind") in ["PREPAID_TOPUP", "INVOICE_SETTLEMENT", "REFUND"]
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("status") in ["PENDING", "SETTLED"]
    assert isinstance(data.get("organization_id"), str)


def assert_model_version(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("model_slug"), str) and len(data["model_slug"]) > 0
    assert isinstance(data.get("version_tag"), str) and len(data["version_tag"]) > 0
    assert data.get("status") in ["DRAFT", "GATED", "ACTIVE", "DEPRECATED", "SUNSET"]
    pricing = data.get("pricing") or {}
    for key in ("input_per_mtok_cents", "output_per_mtok_cents", "cached_per_mtok_cents"):
        assert isinstance(pricing.get(key), int) and pricing[key] >= 0
    assert "deprecation_announced_at" in data
    assert "sunset_at" in data
    assert "safety_evaluation_id" in data


def assert_safety_evaluation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("capability_class") in ["STANDARD", "ELEVATED", "FRONTIER"]
    assert data.get("status") in ["OPEN", "PASSED", "FAILED"]
    assert isinstance(data.get("model_version_id"), str)


def assert_enterprise_agreement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in ["DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"]
    assert isinstance(data.get("organization_id"), str)
    assert isinstance(data.get("committed_tpm"), int) and data["committed_tpm"] > 0
    assert isinstance(data.get("dedicated_capacity_pct"), int)
    assert 1 <= data["dedicated_capacity_pct"] <= 100
    assert isinstance(data.get("effective_at"), str)
    assert isinstance(data.get("expires_at"), str)


def assert_rate_limit_window(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("organization_id"), str)
    assert isinstance(data.get("model_version_id"), str)
    assert isinstance(data.get("window_start"), str)
    assert isinstance(data.get("requests_used"), int) and data["requests_used"] >= 0
    assert isinstance(data.get("tokens_used"), int) and data["tokens_used"] >= 0
    assert isinstance(data.get("burst_credits_used"), int) and data["burst_credits_used"] >= 0


def assert_queued_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in ["QUEUED", "ADMITTED", "EXPIRED", "DROPPED"]
    assert isinstance(data.get("requests_cost"), int) and data["requests_cost"] >= 1
    assert isinstance(data.get("tokens_cost"), int) and data["tokens_cost"] >= 1
    assert isinstance(data.get("organization_id"), str)
    assert isinstance(data.get("model_version_id"), str)


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in ["DRAFT", "FINALIZED"]
    assert isinstance(data.get("organization_id"), str)
    assert isinstance(data.get("period_start"), str)
    assert isinstance(data.get("period_end"), str)
    assert isinstance(data.get("subtotal_cents"), int) and data["subtotal_cents"] >= 0
    assert isinstance(data.get("batch_discount_cents"), int) and data["batch_discount_cents"] >= 0
    assert isinstance(data.get("total_cents"), int) and data["total_cents"] >= 0


def assert_invoice_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("kind") in ["INPUT_TOKENS", "OUTPUT_TOKENS", "CACHED_TOKENS"]
    assert isinstance(data.get("quantity"), int) and data["quantity"] >= 0
    assert isinstance(data.get("rate_per_mtok_cents"), int)
    assert isinstance(data.get("invoice_id"), str)
    assert isinstance(data.get("model_version_id"), str)


def assert_abuse_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("source") in ["AUTOMATED", "MANUAL"]
    assert data.get("severity") in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data.get("status") in ["OPEN", "UNDER_REVIEW", "ACTIONED", "REINSTATED"]
    assert isinstance(data.get("organization_id"), str)
    assert "assigned_analyst_id" in data


def assert_abuse_action(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("action_type") in ["WARN", "THROTTLE", "RESTRICT", "SUSPEND", "TERMINATE"]
    assert isinstance(data.get("abuse_case_id"), str)
    assert isinstance(data.get("issued_by"), str)
    assert "revoked_at" in data


def assert_appeal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in ["PENDING", "GRANTED"]
    assert isinstance(data.get("abuse_case_id"), str)
    assert isinstance(data.get("submitted_by"), str)
    assert "resolved_by" in data


def assert_credit_balance_non_negative(data: dict):
    """Domain invariant: the prepaid balance may never go negative."""
    assert data.get("credit_balance_cents", 0) >= 0, "credit_balance_cents must never be negative"
