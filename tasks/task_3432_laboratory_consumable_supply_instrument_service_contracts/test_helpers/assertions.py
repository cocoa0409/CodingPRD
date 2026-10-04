"""Entity assertions and domain invariant checkers.

The generic envelope validators come from the shared runner package and are
re-exported here so a test file has a single import site.  Everything added
on top encodes a promise the PRD makes about this domain: field presence and
typing per resource (PRD sections 2.5 and 3), the tier entitlement table of
section 3.4, the available-stock identity of section 3.6, and the billing
partition identity of section 3.5.
"""

from prd_bench_local_runner.testing import (  # noqa: F401  (re-exported)
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .constants import (
    EA_DISCOUNT_PCT,
    LOANER_ELIGIBLE_TIERS,
    MONTHLY_VALUE_CENTS,
    PARTS_COVERAGE_PCT,
    PM_VISITS_PER_YEAR,
    RESPONSE_HOURS,
)

# --- Shared field groups -------------------------------------------------------

_SEGMENTS = ["ACADEMIC", "PHARMA", "CLINICAL", "INDUSTRIAL"]
_PRIORITY_CLASSES = ["STANDARD", "PRIORITY", "CRITICAL"]
_ACCOUNT_STATUSES = ["ACTIVE", "SUSPENDED", "CLOSED"]
_CREDIT_STATUSES = ["GOOD", "HOLD"]
_AGREEMENT_STATUSES = ["ACTIVE", "EXPIRING", "EXPIRED", "TERMINATED"]
_AGREEMENT_TIERS = ["BASE", "SILVER", "GOLD", "PLATINUM"]
_PLACEMENT_TYPES = ["CAPITAL", "REAGENT_RENTAL", "LEASE"]
_PLACEMENT_STATUSES = ["ORDERED", "INSTALLED", "DECOMMISSIONED"]
_OPERATIONAL_STATUSES = ["UP", "DOWN"]
_CONTRACT_TIERS = ["BRONZE", "SILVER", "GOLD", "PLATINUM"]
_CONTRACT_STATUSES = ["ACTIVE", "RENEWAL_DUE", "EXPIRED", "CANCELLED"]
_ENGINEER_SKILLS = ["BREAK_FIX", "PM", "APP_SUPPORT", "METHOD_DEV", "INSTALL"]
_ENGINEER_STATUSES = ["ACTIVE", "INACTIVE"]
_REQUEST_TYPES = ["BREAK_FIX", "PREVENTIVE_MAINTENANCE", "APP_SUPPORT", "METHOD_DEV"]
_SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
_REQUEST_STATUSES = ["OPEN", "DISPATCHED", "RESOLVED"]
_LOANER_STATUSES = ["AVAILABLE", "RESERVED"]
_ITEM_CLASSES = ["STANDARD", "COLD_CHAIN", "HAZARDOUS", "CONTROLLED"]
_ALLOCATION_GROUPS = ["GROUP_A", "GROUP_B", "GROUP_C"]
_ORDER_STATUSES = [
    "DRAFT",
    "ALLOCATED",
    "BACKORDERED",
    "SHIPPED",
    "DELIVERED",
    "CANCELLED",
]
_SURGE_STATUSES = ["ACTIVE", "RESOLVED"]


def _assert_common(data, context):
    assert is_valid_uuid(data.get("id", "")), "{0}: id must be a UUID".format(context)
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "{0}: created_at must be ISO 8601".format(context)
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "{0}: updated_at must be ISO 8601".format(context)
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "{0}: version must be an integer >= 1".format(context)
    )


def _assert_optional_instant(data, field, context):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        "{0}: {1} must be null or ISO 8601".format(context, field)
    )


def _assert_money(data, field, context, minimum=0):
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        "{0}: {1} must be integer cents".format(context, field)
    )
    assert value >= minimum, "{0}: {1} must be >= {2}".format(context, field, minimum)


# --- Account ---------------------------------------------------------------------
def assert_account(data):
    ctx = "Account"
    _assert_common(data, ctx)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["segment"] in _SEGMENTS
    assert data["priority_class"] in _PRIORITY_CLASSES
    assert isinstance(data["territory_code"], str) and len(data["territory_code"]) > 0
    assert isinstance(data["controlled_substance_license"], bool)
    assert data["status"] in _ACCOUNT_STATUSES
    assert data["credit_status"] in _CREDIT_STATUSES
    _assert_money(data, "outstanding_balance_cents", ctx)
    _assert_money(data, "trailing_spend_cents", ctx)


# --- EnterpriseAgreement -----------------------------------------------------------
def assert_enterprise_agreement(data):
    ctx = "EnterpriseAgreement"
    _assert_common(data, ctx)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert is_iso8601_timestamp(data.get("start_date", ""))
    assert is_iso8601_timestamp(data.get("end_date", ""))
    _assert_money(data, "committed_annual_spend_cents", ctx)
    assert data["status"] in _AGREEMENT_STATUSES
    assert data["current_tier"] in _AGREEMENT_TIERS
    assert data["discount_pct"] in EA_DISCOUNT_PCT.values()
    assert data["discount_pct"] == EA_DISCOUNT_PCT[data["current_tier"]], (
        "discount_pct must equal the band rate of current_tier"
    )
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0
    _assert_optional_instant(data, "terminated_at", ctx)


# --- Instrument ----------------------------------------------------------------------
def assert_instrument(data):
    ctx = "Instrument"
    _assert_common(data, ctx)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["model"], str) and len(data["model"]) > 0
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert data["placement_type"] in _PLACEMENT_TYPES
    _assert_money(data, "monthly_consumable_commitment_cents", ctx)
    _assert_money(data, "monthly_baseline_consumable_cents", ctx)
    assert data["placement_status"] in _PLACEMENT_STATUSES
    assert data["operational_status"] in _OPERATIONAL_STATUSES
    _assert_optional_instant(data, "installed_at", ctx)


# --- ServiceContract --------------------------------------------------------------------
def assert_service_contract(data):
    """Field shape plus the entitlement table of PRD section 3.4: every tier-
    driven field must equal the tier's pinned value."""
    ctx = "ServiceContract"
    _assert_common(data, ctx)
    assert is_valid_uuid(data.get("instrument_id", "")), "instrument_id must be a UUID"
    tier = data["tier"]
    assert tier in _CONTRACT_TIERS
    assert data["response_hours"] == RESPONSE_HOURS[tier]
    assert data["pm_visits_per_year"] == PM_VISITS_PER_YEAR[tier]
    assert data["parts_coverage_pct"] == PARTS_COVERAGE_PCT[tier]
    assert data["loaner_eligible"] == (tier in LOANER_ELIGIBLE_TIERS)
    assert data["monthly_value_cents"] == MONTHLY_VALUE_CENTS[tier]
    assert is_iso8601_timestamp(data.get("start_date", ""))
    assert is_iso8601_timestamp(data.get("end_date", ""))
    assert data["status"] in _CONTRACT_STATUSES
    assert isinstance(data["used_pm_visits"], int) and data["used_pm_visits"] >= 0
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0
    _assert_optional_instant(data, "cancelled_at", ctx)


# --- Engineer ----------------------------------------------------------------------------
def assert_engineer(data):
    ctx = "Engineer"
    _assert_common(data, ctx)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["territory_code"], str) and len(data["territory_code"]) > 0
    assert isinstance(data["skills"], list) and len(data["skills"]) >= 1, (
        "skills must be a non-empty array"
    )
    for skill in data["skills"]:
        assert skill in _ENGINEER_SKILLS, "unknown skill {0}".format(skill)
    assert data["status"] in _ENGINEER_STATUSES
    assert isinstance(data["open_ticket_count"], int)
    assert data["open_ticket_count"] >= 0


# --- ServiceRequest -------------------------------------------------------------------------
def assert_service_request(data):
    ctx = "ServiceRequest"
    _assert_common(data, ctx)
    assert is_valid_uuid(data.get("instrument_id", "")), "instrument_id must be a UUID"
    assert data["engineer_id"] is None or is_valid_uuid(data["engineer_id"])
    assert data["loaner_unit_id"] is None or is_valid_uuid(data["loaner_unit_id"])
    assert data["request_type"] in _REQUEST_TYPES
    assert data["severity"] in _SEVERITIES
    _assert_optional_instant(data, "scheduled_for", ctx)
    assert data["status"] in _REQUEST_STATUSES
    assert is_iso8601_timestamp(data.get("opened_at", ""))
    assert is_iso8601_timestamp(data.get("response_deadline", ""))
    _assert_optional_instant(data, "resolved_at", ctx)
    assert isinstance(data["sla_breached"], bool)
    _assert_money(data, "parts_cost_cents", ctx)
    _assert_money(data, "billable_cents", ctx)
    _assert_money(data, "covered_cents", ctx)
    _assert_money(data, "credit_memo_cents", ctx)


# --- LoanerUnit --------------------------------------------------------------------------------
def assert_loaner_unit(data):
    ctx = "LoanerUnit"
    _assert_common(data, ctx)
    assert isinstance(data["model"], str) and len(data["model"]) > 0
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert data["status"] in _LOANER_STATUSES


# --- CatalogItem ----------------------------------------------------------------------------------
def assert_catalog_item(data):
    ctx = "CatalogItem"
    _assert_common(data, ctx)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["item_class"] in _ITEM_CLASSES
    assert data["allocation_group"] in _ALLOCATION_GROUPS
    _assert_money(data, "base_price_cents", ctx, minimum=1)
    _assert_money(data, "stock_on_hand", ctx)
    _assert_money(data, "reserved_quantity", ctx)
    _assert_money(data, "available_stock", ctx)
    assert_stock_invariant(data)


def assert_stock_invariant(item):
    """PRD section 3.6: available_stock is stock_on_hand minus reserved_quantity
    and never goes negative."""
    assert item["available_stock"] == item["stock_on_hand"] - item["reserved_quantity"], (
        "available_stock must equal stock_on_hand - reserved_quantity"
    )
    assert item["available_stock"] >= 0, "available_stock must never be negative"


# --- Order --------------------------------------------------------------------------------------
def assert_order(data):
    ctx = "Order"
    _assert_common(data, ctx)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1, (
        "lines must be a non-empty array"
    )
    for line in data["lines"]:
        assert isinstance(line.get("sku"), str) and len(line["sku"]) > 0
        assert isinstance(line.get("quantity"), int) and line["quantity"] > 0
    assert data["status"] in _ORDER_STATUSES
    assert data["shipping_class"] is None or data["shipping_class"] in _ITEM_CLASSES
    _assert_money(data, "handling_fee_cents", ctx)
    assert isinstance(data["discount_pct"], int) and 0 <= data["discount_pct"] <= 100
    _assert_money(data, "goods_subtotal_cents", ctx)
    _assert_money(data, "total_cents", ctx)
    assert isinstance(data["total_quantity"], int) and data["total_quantity"] >= 1
    score = data.get("allocation_score")
    assert score is None or isinstance(score, (int, float)), (
        "allocation_score must be null or a number"
    )
    _assert_optional_instant(data, "submitted_at", ctx)
    _assert_optional_instant(data, "shipped_at", ctx)
    _assert_optional_instant(data, "delivered_at", ctx)


def assert_order_pricing_invariant(order):
    """PRD section 3.6: total_cents is goods_subtotal_cents plus the single
    per-order handling fee, frozen at submission."""
    assert order["total_cents"] == (
        order["goods_subtotal_cents"] + order["handling_fee_cents"]
    ), "total_cents must equal goods_subtotal_cents + handling_fee_cents"
    assert order["total_quantity"] == sum(
        line["quantity"] for line in order["lines"]
    ), "total_quantity must equal the sum of line quantities"


# --- SurgeEvent ------------------------------------------------------------------------------------
def assert_surge_event(data):
    ctx = "SurgeEvent"
    _assert_common(data, ctx)
    assert data["allocation_group"] in _ALLOCATION_GROUPS
    assert isinstance(data["reason"], str)
    assert data["status"] in _SURGE_STATUSES
    assert is_iso8601_timestamp(data.get("started_at", ""))
    _assert_optional_instant(data, "resolved_at", ctx)


# --- Pull-through projection -------------------------------------------------------------------------
def assert_pull_through_projection(data):
    for field in (
        "installed_base_monthly_cents",
        "forward_looking_monthly_cents",
        "installed_instrument_count",
        "ordered_instrument_count",
    ):
        assert isinstance(data.get(field), int) and data[field] >= 0, (
            "{0} must be a non-negative integer".format(field)
        )
    assert data["forward_looking_monthly_cents"] >= data["installed_base_monthly_cents"], (
        "the forward-looking figure adds half the ORDERED pipeline to the "
        "installed base, so it can never fall below it"
    )


# --- Billing partition invariant ------------------------------------------------------------------------
def assert_billing_split_invariant(request, hours_on_site, labor_rate_cents):
    """PRD section 3.5: whenever a live contract pays, billable plus covered
    equals labor plus parts exactly - the partition conserves total cost."""
    labor_cents = labor_rate_cents * hours_on_site
    total = labor_cents + request["parts_cost_cents"]
    assert request["billable_cents"] + request["covered_cents"] == total, (
        "billable_cents + covered_cents must equal labor + parts exactly"
    )
