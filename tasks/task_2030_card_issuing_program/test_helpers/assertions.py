"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ---------------------------------------------------------------------------
# Generic entity shape
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict, entity_label: str):
    assert isinstance(data, dict), f"{entity_label} must be a dict"
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer"
    )


def _assert_append_only_fields(data: dict, entity_label: str):
    assert isinstance(data, dict), f"{entity_label} must be a dict"
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    # Append-only resources never carry updated_at or version (PRD §2.4)
    assert "updated_at" not in data, f"{entity_label} must NOT carry updated_at"
    assert "version" not in data, f"{entity_label} must NOT carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_card_program(data: dict):
    _assert_common_fields(data, "CardProgram")
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert data["product_class"] in (
        "CONSUMER_PREPAID", "CORPORATE_FLEET", "DEBIT_CONSUMER", "COMMERCIAL_CREDIT",
    )
    assert data["network"] in ("VISA", "MASTERCARD", "STAR", "PULSE")
    assert isinstance(data["currency_code"], str) and len(data["currency_code"]) == 3
    assert isinstance(data["daily_spend_cap_cents"], int) and data["daily_spend_cap_cents"] > 0
    assert isinstance(data["authorization_rules_locked"], bool)
    assert isinstance(data["open_card_count"], int) and data["open_card_count"] >= 0
    assert data["posture"] in ("DRAFT", "LIVE", "SUNSETTING", "TERMINATED")


def assert_bin_range(data: dict):
    _assert_common_fields(data, "BinRange")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["bin_prefix"], str) and data["bin_prefix"].isdigit()
    assert len(data["bin_prefix"]) in (6, 8)
    assert isinstance(data["range_size"], int)
    assert isinstance(data["pans_allocated"], int) and data["pans_allocated"] >= 0
    assert isinstance(data["pans_available"], int)
    assert data["pans_available"] == data["range_size"] - data["pans_allocated"], (
        f"pans_available ({data['pans_available']}) must equal "
        f"range_size - pans_allocated ({data['range_size'] - data['pans_allocated']})"
    )
    assert data["status"] in (
        "PENDING_ACTIVATION", "ACTIVE", "DEPLETED", "FROZEN", "RETIRED",
    )


def assert_production_vendor(data: dict):
    _assert_common_fields(data, "ProductionVendor")
    assert isinstance(data["vendor_code"], str) and data["vendor_code"]
    assert isinstance(data["capability_flags"], list) and len(data["capability_flags"]) >= 1
    for flag in data["capability_flags"]:
        assert flag in ("EMV_CHIP", "CONTACTLESS", "MAGSTRIPE", "VIRTUAL", "DUAL_INTERFACE")
    assert isinstance(data["daily_capacity_cards"], int) and data["daily_capacity_cards"] > 0
    assert isinstance(data["supported_networks"], list)
    for net in data["supported_networks"]:
        assert net in ("VISA", "MASTERCARD", "STAR", "PULSE")
    assert isinstance(data["is_active"], bool)


def assert_production_batch(data: dict):
    _assert_common_fields(data, "ProductionBatch")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["vendor_id"], str) and data["vendor_id"]
    assert isinstance(data["scheduled_for_utc_date"], str)
    assert isinstance(data["requested_card_count"], int) and data["requested_card_count"] > 0
    assert isinstance(data["fulfilled_card_count"], int) and data["fulfilled_card_count"] >= 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert data["status"] in (
        "PLANNED", "SUBMITTED", "IN_PRODUCTION", "SHIPPED", "DELIVERED",
        "CANCELLED", "FAILED",
    )


def assert_card_account(data: dict):
    _assert_common_fields(data, "CardAccount")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["external_account_ref"], str) and data["external_account_ref"]
    assert data["account_class"] in ("INDIVIDUAL", "BUSINESS", "FLEET_POOL")
    assert isinstance(data["currency_code"], str) and len(data["currency_code"]) == 3
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["available_balance_cents"], int)
    assert data["lifecycle_status"] in (
        "ONBOARDING", "OPEN", "SUSPENDED", "CLOSED", "CONVERTED_OUT",
    )
    assert data["risk_tier"] in ("STANDARD", "ELEVATED", "RESTRICTED")
    assert isinstance(data["daily_spend_cap_cents"], int)


def assert_card(data: dict):
    _assert_common_fields(data, "Card")
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["bin_range_id"], str) and data["bin_range_id"]
    assert isinstance(data["pan_token"], str) and data["pan_token"]
    assert isinstance(data["last4"], str) and len(data["last4"]) == 4
    assert isinstance(data["expiry_month"], int) and 1 <= data["expiry_month"] <= 12
    assert isinstance(data["expiry_year"], int)
    assert data["form_factor"] in ("PHYSICAL", "VIRTUAL")
    assert data["lifecycle_status"] in (
        "ISSUED", "ACTIVE", "SUSPENDED", "REPLACED", "EXPIRED", "CANCELLED", "COMPROMISED",
    )
    assert data["pin_status"] in ("UNSET", "SET", "BLOCKED", "RESET_PENDING")


def assert_activation_token(data: dict):
    _assert_common_fields(data, "ActivationToken")
    assert isinstance(data["card_id"], str) and data["card_id"]
    assert isinstance(data["token_value"], str) and data["token_value"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("PENDING", "CONSUMED", "EXPIRED", "REVOKED")


def assert_authorization_rule(data: dict):
    _assert_common_fields(data, "AuthorizationRule")
    assert data["subject_kind"] in ("PROGRAM", "ACCOUNT")
    assert isinstance(data["subject_ref"], str) and data["subject_ref"]
    assert data["rule_kind"] in ("VELOCITY", "MCC_ALLOW", "MCC_BLOCK", "GEO_BLOCK")
    assert isinstance(data["priority_rank"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_mandate(data: dict):
    _assert_common_fields(data, "Mandate")
    assert data["network"] in ("VISA", "MASTERCARD", "STAR", "PULSE")
    assert isinstance(data["mandate_code"], str) and data["mandate_code"]
    assert isinstance(data["title"], str) and data["title"]
    assert is_iso8601_timestamp(data["effective_at"])
    assert is_iso8601_timestamp(data["compliance_deadline"])
    assert data["severity"] in ("ADVISORY", "REQUIRED", "EMERGENCY")
    assert data["status"] in ("ANNOUNCED", "EFFECTIVE", "RETIRED")


def assert_mandate_ack(data: dict):
    _assert_common_fields(data, "MandateAck")
    assert isinstance(data["mandate_id"], str) and data["mandate_id"]
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["implementation_notes"], str)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "RETURNED", "VERIFIED", "REJECTED")


def assert_authorization_event(data: dict):
    _assert_append_only_fields(data, "AuthorizationEvent")
    assert isinstance(data["card_id"], str) and data["card_id"]
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["mcc"], str) and len(data["mcc"]) == 4
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert data["decision"] in (
        "APPROVED", "DECLINED_LIMIT", "DECLINED_RULE", "DECLINED_STATE", "DECLINED_VELOCITY",
    )
    assert isinstance(data["decision_reason"], str) and data["decision_reason"]
    assert is_iso8601_timestamp(data["authorized_at"])


def assert_settlement(data: dict):
    _assert_append_only_fields(data, "Settlement")
    assert isinstance(data["authorization_event_id"], str) and data["authorization_event_id"]
    assert isinstance(data["card_id"], str) and data["card_id"]
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["settled_amount_cents"], int) and data["settled_amount_cents"] > 0
    assert isinstance(data["interchange_cents"], int) and data["interchange_cents"] >= 0
    assert data["qualification_tier"] in ("QUALIFIED", "MID_QUALIFIED", "NON_QUALIFIED")
    assert is_iso8601_timestamp(data["settled_at"])


def assert_reissue_campaign(data: dict):
    _assert_common_fields(data, "ReissueCampaign")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert data["campaign_kind"] in (
        "EXPIRY_SWEEP", "COMPROMISE_BLAST", "NETWORK_MANDATE_REISSUE",
    )
    assert is_iso8601_timestamp(data["scheduled_for"])
    assert isinstance(data["selection_filter"], dict)
    assert isinstance(data["estimated_card_count"], int) and data["estimated_card_count"] >= 0
    assert data["status"] in (
        "DRAFT", "SCHEDULED", "EXECUTING", "COMPLETED", "CANCELLED", "FAILED",
    )


def assert_conversion_job(data: dict):
    _assert_common_fields(data, "ConversionJob")
    assert isinstance(data["source_program_id"], str) and data["source_program_id"]
    assert isinstance(data["target_program_id"], str) and data["target_program_id"]
    assert is_iso8601_timestamp(data["execution_at"])
    assert isinstance(data["accounts_planned"], int) and data["accounts_planned"] >= 0
    assert isinstance(data["accounts_converted"], int) and data["accounts_converted"] >= 0
    assert data["status"] in ("SCHEDULED", "EXECUTING", "COMPLETED", "FAILED", "CANCELLED")


def assert_program_economics(data: dict):
    assert isinstance(data, dict)
    assert isinstance(data["month"], str) and len(data["month"]) == 7
    assert isinstance(data["variant"], str)
    assert isinstance(data["interchange_revenue_cents"], int)
    assert isinstance(data["production_cost_cents"], int)
    assert isinstance(data["reissue_fee_cents"], int)
    assert isinstance(data["net_economics_cents"], int)
