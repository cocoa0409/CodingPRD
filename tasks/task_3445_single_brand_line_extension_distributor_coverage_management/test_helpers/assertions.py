"""Entity assertions and domain invariant checkers.

Each assert_<entity>() validates the system-managed fields and the
entity's own field types against the PRD. SellThroughReport is immutable:
its assertion REQUIRES the absence of version and updated_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _assert_system_fields(data: dict):
    """Standard system-managed fields present on every mutable resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def _assert_nullable_iso(data: dict, field: str):
    """Field is either null or an ISO 8601 timestamp."""
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), \
        f"{field} must be null or ISO 8601, got {value!r}"


def _assert_channel(value, field="channel"):
    assert value in ("HARDWARE", "AUTOMOTIVE", "INDUSTRIAL", "MASS"), \
        f"{field} must be a declared channel, got {value!r}"


def _assert_channel_list(value, field):
    assert isinstance(value, list) and len(value) > 0, f"{field} must be a non-empty array"
    for item in value:
        _assert_channel(item, field)


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------

def assert_brand(data: dict):
    """Brand shape including computed posture, dilution, identity share, risk."""
    _assert_system_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["legal_entity_name"], str) and data["legal_entity_name"]
    assert isinstance(data["equity_budget_bps"], int) and data["equity_budget_bps"] > 0
    assert data["status"] in ("OPERATING", "PROTECTIVE_LOCKDOWN")
    assert data.get("lockdown_reason") in (None, "CONFIDENTIALITY_BREACH",
                                           "COUNTERFEIT_SURGE", "MANUAL")
    assert data["protection_posture"] in ("NORMAL", "ELEVATED", "CRITICAL")
    assert isinstance(data["dilution_consumed_bps"], int)
    assert isinstance(data["core_identity_share_bps"], int)
    assert isinstance(data["genericization_risk_bps"], int)


def assert_product_line(data: dict):
    """ProductLine shape including dilution cost and review bookkeeping."""
    _assert_system_fields(data)
    assert is_valid_uuid(data.get("brand_id", ""))
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["is_core"], bool)
    _assert_channel_list(data["target_channels"], "target_channels")
    assert data["status"] in ("FORMULATION", "PILOT", "LAUNCHED", "DISCONTINUED")
    assert isinstance(data["brand_review_attempts"], int) and data["brand_review_attempts"] >= 0
    assert isinstance(data["dilution_cost_bps"], int)
    _assert_nullable_iso(data, "launched_at")


def assert_formulation(data: dict):
    """Formulation shape."""
    _assert_system_fields(data)
    assert is_valid_uuid(data.get("product_line_id", ""))
    assert isinstance(data["version_label"], str) and data["version_label"]
    master = data.get("master_formulation_id")
    assert master is None or is_valid_uuid(master)
    assert isinstance(data["component_codes"], list) and 1 <= len(data["component_codes"]) <= 12
    for code in data["component_codes"]:
        assert isinstance(code, str) and code, "component codes must be non-empty strings"
    assert data["voc_class"] in ("STANDARD", "LOW_VOC")
    assert data["status"] in ("DRAFT", "SEALED", "COMPARTMENTALIZED")
    _assert_nullable_iso(data, "sealed_at")


def assert_contract_manufacturer(data: dict):
    """ContractManufacturer shape including computed disclosed_component_count."""
    _assert_system_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["site_country"], str) and data["site_country"]
    assert isinstance(data["capabilities"], list) and len(data["capabilities"]) > 0
    for cap in data["capabilities"]:
        assert cap in ("BLENDING", "AEROSOL_FILL", "LIQUID_FILL", "PACKAGING")
    assert isinstance(data.get("sponsoring_officer_id"), str)
    assert data["status"] in ("VETTING", "QUALIFIED", "SUSPENDED")
    _assert_nullable_iso(data, "suspended_at")
    assert isinstance(data["disclosed_component_count"], int) \
        and data["disclosed_component_count"] >= 0


def assert_confidentiality_grant(data: dict):
    """ConfidentialityGrant shape."""
    _assert_system_fields(data)
    assert is_valid_uuid(data.get("manufacturer_id", ""))
    assert is_valid_uuid(data.get("formulation_id", ""))
    assert isinstance(data["component_scope"], list) and len(data["component_scope"]) > 0
    assert data["grant_reason"] in ("PRODUCTION", "PILOT_SUPPLY", "SECOND_SOURCE")
    assert is_iso8601_timestamp(data.get("expires_on", ""))
    assert data["status"] in ("REQUESTED", "GRANTED", "ACTIVE", "REVOKED", "EXPIRED")
    granted_by = data.get("granted_by_user_id")
    assert granted_by is None or isinstance(granted_by, str)
    assert isinstance(data.get("revoked_for_cause"), bool)
    _assert_nullable_iso(data, "revoked_at")


def assert_distributor(data: dict):
    """Distributor shape including computed attainment fields and tier."""
    _assert_system_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert is_valid_uuid(data.get("home_market_id", ""))
    _assert_channel_list(data["channels_served"], "channels_served")
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] > 0
    assert data["status"] in ("APPLICANT", "APPROVED", "SUSPENDED", "TERMINATED")
    assert isinstance(data["suspension_count"], int) and data["suspension_count"] >= 0
    for field in ("attainment_actual_bps", "attainment_projected_bps"):
        value = data.get(field)
        assert value is None or isinstance(value, int), \
            f"{field} must be null or an integer, got {value!r}"
    assert data.get("quota_compliance_tier") in (None, "GOLD", "STANDARD", "WATCH", "SANCTION")


def assert_market(data: dict):
    """Market shape."""
    _assert_system_fields(data)
    assert isinstance(data["country_code"], str) and data["country_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["registration_required"], bool)
    assert data["voc_regime"] in ("STANDARD", "STRICT")
    _assert_channel_list(data["allowed_channels"], "allowed_channels")
    assert data["status"] in ("OPEN", "CLOSED")


def assert_market_registration(data: dict):
    """MarketRegistration shape."""
    _assert_system_fields(data)
    assert is_valid_uuid(data.get("market_id", ""))
    assert is_valid_uuid(data.get("product_line_id", ""))
    assert is_valid_uuid(data.get("formulation_id", ""))
    reg_no = data.get("registration_number")
    assert reg_no is None or isinstance(reg_no, str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "REJECTED", "ACTIVE",
                              "RENEWAL_DUE", "EXPIRED", "REVOKED")
    assert is_iso8601_timestamp(data.get("expires_on", ""))
    assert isinstance(data["revise_count"], int) and data["revise_count"] >= 0
    _assert_nullable_iso(data, "submitted_at")
    _assert_nullable_iso(data, "approved_at")


def assert_coverage_assignment(data: dict):
    """CoverageAssignment shape."""
    _assert_system_fields(data)
    assert is_valid_uuid(data.get("distributor_id", ""))
    assert is_valid_uuid(data.get("market_id", ""))
    assert is_valid_uuid(data.get("product_line_id", ""))
    _assert_channel(data["channel"])
    assert isinstance(data["exclusive"], bool)
    assert isinstance(data["starts_on"], str) and data["starts_on"]
    assert isinstance(data["ends_on"], str) and data["ends_on"]
    assert isinstance(data["annual_quota_units"], int) and data["annual_quota_units"] > 0
    assert data["status"] in ("PROPOSED", "ACTIVE", "SUSPENDED", "SUPERSEDED",
                              "WITHDRAWN", "CLOSED", "TERMINATED")
    sup = data.get("supersedes_assignment_id")
    assert sup is None or is_valid_uuid(sup)


def assert_pack_format(data: dict):
    """PackFormat shape."""
    _assert_system_fields(data)
    assert is_valid_uuid(data.get("product_line_id", ""))
    assert isinstance(data["size_ml"], int) and data["size_ml"] > 0
    assert data["delivery_system"] in ("AEROSOL", "TRIGGER_SPRAY", "PUMP",
                                       "PRECISION_PEN", "BULK_CONTAINER")
    _assert_channel_list(data["channel_restrictions"], "channel_restrictions")
    assert isinstance(data["case_pack_qty"], int) and data["case_pack_qty"] >= 1
    assert data["status"] in ("DESIGNED", "TOOLED", "IN_PRODUCTION", "RETIRED")


def assert_channel_price_list(data: dict):
    """ChannelPriceList shape."""
    _assert_system_fields(data)
    assert is_valid_uuid(data.get("pack_format_id", ""))
    _assert_channel(data["channel"])
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert isinstance(data["map_price_cents"], int) and data["map_price_cents"] > 0
    assert data["map_price_cents"] <= data["list_price_cents"], \
        "map_price_cents must not exceed list_price_cents"
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))
    assert data["status"] in ("SCHEDULED", "EFFECTIVE", "SUPERSEDED", "EXPIRED")


def assert_promotion(data: dict):
    """Promotion shape including funding bookkeeping."""
    _assert_system_fields(data)
    assert is_valid_uuid(data.get("product_line_id", ""))
    _assert_channel(data["channel"])
    assert isinstance(data["discount_pct"], (int, float))
    assert 0 < float(data["discount_pct"]) <= 90.00
    assert isinstance(data["starts_on"], str) and data["starts_on"]
    assert isinstance(data["ends_on"], str) and data["ends_on"]
    assert isinstance(data["funding_budget_cents"], int) and data["funding_budget_cents"] > 0
    assert isinstance(data["accrued_funding_cents"], int) and data["accrued_funding_cents"] >= 0
    assert isinstance(data["redemptions_count"], int) and data["redemptions_count"] >= 0
    prov = data.get("unit_funding_provisional_cents")
    assert prov is None or isinstance(prov, int)
    assert data["status"] in ("DRAFT", "PENDING_APPROVAL", "APPROVED",
                              "LIVE", "SUSPENDED", "ENDED")
    assert isinstance(data.get("created_by_user_id"), str)
    approver = data.get("approved_by_user_id")
    assert approver is None or isinstance(approver, str)


def assert_counterfeit_case(data: dict):
    """CounterfeitCase shape."""
    _assert_system_fields(data)
    assert is_valid_uuid(data.get("brand_id", ""))
    assert is_valid_uuid(data.get("market_id", ""))
    _assert_channel(data["channel"])
    assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 5
    assert isinstance(data["units_seized"], int) and data["units_seized"] >= 0
    assert data["status"] in ("REPORTED", "ACTION_TAKEN", "CLOSED")


def assert_use_case_submission(data: dict):
    """UseCaseSubmission shape."""
    _assert_system_fields(data)
    assert is_valid_uuid(data.get("product_line_id", ""))
    assert isinstance(data["submitter_ref"], str) and data["submitter_ref"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["description"], str)
    assert isinstance(data["generic_use_flag"], bool)
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "PUBLISHED", "RETRACTED")


def assert_sell_through_report(data: dict):
    """SellThroughReport shape — immutable: NO version, NO updated_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "version" not in data, "SellThroughReport must not carry version"
    assert "updated_at" not in data, "SellThroughReport must not carry updated_at"
    assert is_valid_uuid(data.get("distributor_id", ""))
    assert is_valid_uuid(data.get("coverage_assignment_id", ""))
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert isinstance(data["units_sold"], int) and data["units_sold"] >= 0
    assert isinstance(data["units_returned"], int) and data["units_returned"] >= 0
    assert isinstance(data["net_units"], int) and data["net_units"] >= 0
    assert data["net_units"] == max(0, data["units_sold"] - data["units_returned"]), \
        "net_units must equal max(0, units_sold - units_returned)"


# ---------------------------------------------------------------------------
# Computed-read response assertions
# ---------------------------------------------------------------------------

def assert_rebate_preview(data: dict):
    """Rebate-preview response shape (attainment variants, tier, rate, estimate)."""
    for field in ("attainment_actual_bps", "attainment_projected_bps"):
        value = data.get(field)
        assert value is None or isinstance(value, int), \
            f"{field} must be null or an integer, got {value!r}"
    assert data.get("quota_compliance_tier") in (None, "GOLD", "STANDARD", "WATCH", "SANCTION")
    assert isinstance(data["rebate_bps"], int) and data["rebate_bps"] >= 0
    assert isinstance(data["window_net_units"], int) and data["window_net_units"] >= 0
    assert isinstance(data["rebate_estimate_cents"], int) and data["rebate_estimate_cents"] >= 0


def assert_effective_price(data: dict):
    """Effective-price response shape."""
    assert is_valid_uuid(data.get("price_list_id", ""))
    _assert_channel(data["channel"])
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert isinstance(data["map_price_cents"], int) and data["map_price_cents"] > 0
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))


def assert_redemption(data: dict):
    """Redemption response shape."""
    assert isinstance(data.get("redemption_id"), str) and data["redemption_id"]
    assert isinstance(data["unit_funding_cents"], int) and data["unit_funding_cents"] >= 0
    assert isinstance(data["promo_unit_price_cents"], int)
    assert isinstance(data["promo_case_price_cents"], int)
    assert isinstance(data["total_funding_cents"], int) and data["total_funding_cents"] >= 0
    assert isinstance(data["accrued_funding_cents"], int) and data["accrued_funding_cents"] >= 0
    assert isinstance(data["remaining_budget_cents"], int)


def assert_clock_response(data: dict):
    """Clock-set response echoes the new logical time as current_utc."""
    assert is_iso8601_timestamp(data.get("current_utc", "")), \
        f"current_utc must be ISO 8601, got {data.get('current_utc')!r}"


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_brand_invariants(data: dict):
    """Brand invariants that must hold after any operation."""
    assert_brand(data)
    assert data["core_identity_share_bps"] == max(0, 10000 - data["dilution_consumed_bps"]), \
        "core_identity_share_bps must equal max(0, 10000 - dilution_consumed_bps)"
    assert 0 <= data["genericization_risk_bps"] <= 10000
    assert data["dilution_consumed_bps"] >= 0
    if data["status"] == "OPERATING":
        assert data["lockdown_reason"] is None, \
            "lockdown_reason must be null while OPERATING"


def assert_distributor_invariants(data: dict):
    """Distributor invariants that must hold after any operation."""
    assert_distributor(data)
    assert data["suspension_count"] <= 3, "suspension_count never exceeds 3"
    if data["status"] == "TERMINATED":
        assert data["suspension_count"] >= 0
