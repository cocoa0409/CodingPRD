"""Per-entity shape assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import COMPLIANCE_SCORE_FLOOR


def assert_common_fields(data: dict):
    """The full common-field set every primary resource carries."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_append_only_fields(data: dict):
    """Append-only resources carry id and created_at but never updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only resources must not expose updated_at"
    assert "version" not in data, "append-only resources must not expose version"


def assert_supplier_account(data: dict):
    assert_common_fields(data)
    assert isinstance(data["account_name"], str) and data["account_name"]
    assert isinstance(data["region"], str) and data["region"]
    assert data["status"] in ("ACTIVE", "OFFBOARDED")


def assert_subscription_contract(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("supplier_account_id", "")), "supplier_account_id must be a UUID"
    assert data["tier"] in ("TIER_CATEGORY", "TIER_BRAND", "TIER_PORTFOLIO")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    for field in (
        "report_credit_allowance",
        "report_credits_reserved",
        "report_credits_consumed",
        "report_credits_available",
        "activation_budget_cents",
        "activation_budget_spent_cents",
        "compliance_score",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["redistribution_allowed"], bool)
    assert isinstance(data["modeled_derivation_allowed"], bool)


def assert_credit_ledger_invariant(contract: dict):
    """allowance == available + reserved + consumed, at every observation."""
    total = (
        contract["report_credits_available"]
        + contract["report_credits_reserved"]
        + contract["report_credits_consumed"]
    )
    assert contract["report_credit_allowance"] == total, (
        f"credit ledger invariant violated: allowance {contract['report_credit_allowance']} "
        f"!= available {contract['report_credits_available']} + reserved "
        f"{contract['report_credits_reserved']} + consumed {contract['report_credits_consumed']}"
    )


def assert_query_budget_invariant(grant: dict):
    """query_budget_total == query_budget_consumed + query_budget_remaining."""
    total = grant["query_budget_consumed"] + grant["query_budget_remaining"]
    assert grant["query_budget_total"] == total, (
        f"query budget invariant violated: total {grant['query_budget_total']} "
        f"!= consumed {grant['query_budget_consumed']} + remaining {grant['query_budget_remaining']}"
    )


def assert_compliance_score_floor(contract: dict):
    assert contract["compliance_score"] >= COMPLIANCE_SCORE_FLOOR, "compliance_score floored at zero"


def assert_category_scope(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert isinstance(data["category_code"], str) and data["category_code"]
    assert isinstance(data["brand_codes"], list)


def assert_insight_report(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert data["report_type"] in ("CATEGORY", "BRAND_OWN", "COMPETITOR_BLIND")
    assert data["status"] in ("REQUESTED", "GENERATING", "READY", "SUPPRESSED", "DELIVERED", "CANCELLED")
    assert data["credit_cost"] in (1, 2, 3)
    assert isinstance(data["category_code"], str) and data["category_code"]


def assert_audience_segment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert isinstance(data["segment_name"], str) and data["segment_name"]
    assert isinstance(data["category_code"], str) and data["category_code"]
    assert isinstance(data["size"], int) and data["size"] >= 0
    assert data["status"] in ("DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED")


def assert_segment_activation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("segment_id", "")), "segment_id must be a UUID"
    assert isinstance(data["channels"], list) and data["channels"]
    assert set(data["channels"]) <= {"COUPON", "RETAIL_MEDIA"}
    assert data["status"] in ("PENDING", "LAUNCHED", "HALTED", "COMPLETED", "CANCELLED")
    assert isinstance(data["channel_lines"], list)
    assert isinstance(data["total_fee_cents"], int)
    for line in data["channel_lines"]:
        assert line["channel"] in ("COUPON", "RETAIL_MEDIA")
        assert isinstance(line["households_reached"], int) and line["households_reached"] >= 0
        assert isinstance(line["line_fee_cents"], int) and line["line_fee_cents"] >= 0


def assert_incrementality_study(data: dict):
    assert_common_fields(data)
    assert isinstance(data["brand_code"], str) and data["brand_code"]
    assert isinstance(data["category_code"], str) and data["category_code"]
    assert data["status"] in ("DRAFT", "RUNNING", "ANALYSIS", "IN_REVIEW", "PUBLISHED")
    assert isinstance(data["matched_pairs"], list)


def assert_clean_room_grant(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("supplier_account_id", "")), "supplier_account_id must be a UUID"
    assert isinstance(data["query_budget_total"], int)
    assert isinstance(data["query_budget_consumed"], int)
    assert isinstance(data["query_budget_remaining"], int)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "REVOKED", "EXPIRED")
    assert isinstance(data["requested_by_user_id"], str) and data["requested_by_user_id"]


def assert_clean_room_query(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data.get("grant_id", "")), "grant_id must be a UUID"
    assert isinstance(data["dataset_joins"], list)
    assert isinstance(data["estimated_rows"], int)
    assert isinstance(data["query_cost"], int)
    assert data["status"] in ("SUBMITTED", "EXECUTED", "SUPPRESSED", "REJECTED")


def assert_line_review_cycle(data: dict):
    assert_common_fields(data)
    assert isinstance(data["category_code"], str) and data["category_code"]
    assert data["status"] in ("SCHEDULED", "OPEN", "LOCKED", "COMPLETED")
    assert isinstance(data["planned_open_count"], int) and data["planned_open_count"] >= 0
    assert is_iso8601_timestamp(data.get("open_at", "")), "open_at must be ISO 8601"


def assert_review_deliverable(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a UUID"
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert is_valid_uuid(data.get("insight_report_id", "")), "insight_report_id must be a UUID"
    assert data["status"] in ("PLANNED", "SUBMITTED", "ACCEPTED", "REJECTED", "BLOCKED", "MISSED")
    assert isinstance(data["is_late"], bool)


def assert_new_item_forecast(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert isinstance(data["product_ref"], str) and data["product_ref"]
    assert isinstance(data["analogs"], list) and data["analogs"]
    assert data["variant"] in ("SIMPLE_AVERAGE", "SIMILARITY_WEIGHTED")
    assert data["status"] in ("PUBLISHED", "SUPERSEDED")


def assert_audit_event(data: dict):
    assert_append_only_fields(data)
    assert data["event_type"] in (
        "REPORT_EXPORTED",
        "QUERY_EXECUTED",
        "QUERY_SUPPRESSED",
        "GRANT_APPROVED",
        "GRANT_DENIED",
        "GRANT_REVOKED",
        "ACTIVATION_LAUNCHED",
    )
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]
    assert isinstance(data["subject_type"], str) and data["subject_type"]
    assert isinstance(data["subject_id"], str) and data["subject_id"]
