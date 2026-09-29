"""Entity assertions, envelope helpers and domain invariant checkers."""
import re
from typing import Iterable, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

_INSTANT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?Z$")


def normalize_instant(value: str) -> str:
    """Canonicalise an ISO 8601 UTC instant to millisecond precision.

    Timestamps are compared through this helper so that a difference in how
    many fractional digits the serialiser prints is never mistaken for a
    difference in the instant itself.
    """
    assert isinstance(value, str), f"expected an ISO 8601 instant string, got {value!r}"
    match = _INSTANT_RE.match(value)
    assert match, f"'{value}' is not an ISO 8601 UTC instant"
    seconds, fraction = match.group(1), match.group(2) or ""
    millis = (fraction + "000")[:3]
    return f"{seconds}.{millis}Z"


def assert_instant_equals(actual, expected: str, field: str = "timestamp") -> None:
    assert actual is not None, f"{field} must be set, got None"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"Expected {field} {expected}, got {actual}"
    )


def assert_instant_format(value, field: str = "timestamp") -> None:
    assert value is not None, f"{field} must be set, got None"
    assert is_iso8601_timestamp(value), f"{field} must be an ISO 8601 UTC instant, got {value!r}"


def assert_unset(data: dict, *fields: str) -> None:
    """A field the PRD describes as unset is either absent or null."""
    for field in fields:
        assert data.get(field) is None, f"Expected {field} to be unset, got {data.get(field)!r}"


def assert_keys_absent(data: dict, *fields: str) -> None:
    """The key itself must not be present in the representation."""
    for field in fields:
        assert field not in data, f"Expected key '{field}' to be absent, found {data.get(field)!r}"


def assert_versioned_record(data: dict, expected_version: Optional[int] = None) -> None:
    """Shared shape of the twelve record types that carry updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert "_" not in str(data.get("id", "")), "id carries no type prefix"
    assert_instant_format(data.get("created_at"), "created_at")
    assert_instant_format(data.get("updated_at"), "updated_at")
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_configuration_row(data: dict) -> None:
    """Shared shape of the three configuration row types: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert_instant_format(data.get("created_at"), "created_at")
    assert_keys_absent(data, "updated_at", "version")


def assert_integer_cents(data: dict, *fields: str) -> None:
    for field in fields:
        value = data.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer count of cents, got {value!r}"
        )


def assert_six_decimal_pct(value, field: str = "percentage") -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 6) == float(value), (
        f"{field} must be rounded to six decimal places, got {value!r}"
    )


def assert_two_decimal_score(value, field: str = "score") -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{field} must be rounded to two decimal places, got {value!r}"
    )


# ---------------------------------------------------------------------------
# List / single-resource envelope helpers
# ---------------------------------------------------------------------------

def assert_paginated_list(
    response,
    expected_total: Optional[int] = None,
    expected_page_size: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> Tuple[list, dict]:
    """Validate a list endpoint's response, which carries the four page fields."""
    data, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"Expected total_count {expected_total}, got {meta['total_count']}"
        )
    if expected_page_size is not None:
        assert len(data) == expected_page_size, (
            f"Expected {expected_page_size} records on the page, got {len(data)}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, f"Expected limit {expected_limit}, got {meta['limit']}"
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, f"Expected offset {expected_offset}, got {meta['offset']}"
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"Expected has_more {expected_has_more}, got {meta['has_more']}"
        )
    return data, meta


def assert_unpaginated_list(response, expected_length: Optional[int] = None) -> list:
    """Validate a 200 response whose `data` is a plain array with no page window."""
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    body = response.json()
    assert body.get("response_type") == "array", (
        f"Expected response_type 'array', got {body.get('response_type')!r}"
    )
    data = body["data"]
    assert isinstance(data, list), f"Expected data to be an array, got {type(data)}"
    if expected_length is not None:
        assert len(data) == expected_length, f"Expected {expected_length} records, got {len(data)}"
    return data


def assert_no_pagination_meta(response) -> dict:
    """A single-resource response carries none of the four page fields."""
    body = response.json()
    meta = body["meta"]
    assert_keys_absent(meta, "limit", "offset", "total_count", "has_more")
    return body["data"]


def assert_no_content(response) -> None:
    """The single delete endpoint answers 204 with no response body at all."""
    assert response.status_code == 204, (
        f"Expected 204 No Content, got {response.status_code}: {response.text}"
    )
    assert response.text == "" or response.text is None, (
        f"Expected an empty body, got {response.text!r}"
    )


def ids_of(records: Iterable[dict]) -> List[str]:
    return [record["id"] for record in records]


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_desk_policy(data: dict) -> None:
    assert_versioned_record(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED"), f"unexpected status {data['status']!r}"
    assert 0.0 < data["absolute_margin_floor_pct"] < data["margin_floor_pct"] < 1.0, (
        "the hard floor is configured strictly below the soft floor and both lie strictly between 0 and 1"
    )
    assert data["quote_validity_days"] >= 1
    assert data["standard_payment_terms_days"] >= 1
    assert 0.0 <= data["uplift_rate_per_30_days"] < 1.0
    assert 0.0 < data["max_stack_discount_pct"] < 1.0
    assert data["volume_rebate_tier2_min_cents"] > data["volume_rebate_tier1_min_cents"] >= 0
    assert data["volume_rebate_tier2_pct"] > data["volume_rebate_tier1_pct"] >= 0.0
    assert data["surge_window_days"] >= 1
    assert data["surge_sla_multiplier"] > 0
    assert data["price_hold_cooldown_days"] >= 0
    assert data["exception_allowance_cents"] >= 0
    assert 0.0 <= data["terms_review_risk_threshold"] <= 100.0
    assert 0.0 <= data["terms_cfo_risk_threshold"] <= 100.0


def assert_approval_tier(data: dict) -> None:
    assert_configuration_row(data)
    assert data["tier_level"] in (1, 2, 3, 4), f"tier_level must be 1-4, got {data['tier_level']}"
    assert 0.0 <= data["min_discount_pct"] < 1.0
    assert data["min_discount_pct"] < data["max_discount_pct"] <= 1.0
    assert data["required_role"] in ("DealDeskAnalyst", "SalesDirector", "VPSales", "CFO")
    assert data["sla_hours"] >= 1
    assert data["max_delegation_levels"] in (0, 1)


def assert_product(data: dict) -> None:
    assert_versioned_record(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["product_type"] in (
        "SUBSCRIPTION_LICENSE",
        "USAGE_METERED",
        "PROFESSIONAL_SERVICES",
        "SUPPORT_PLAN",
    )
    assert data["rev_rec_category"] in ("RATABLE", "POINT_IN_TIME", "USAGE_AS_INCURRED")
    assert_integer_cents(data, "list_unit_price_cents", "unit_cost_cents")
    assert data["list_unit_price_cents"] > 0
    assert 0 <= data["unit_cost_cents"] < data["list_unit_price_cents"]
    assert data["min_term_months"] >= 1


def assert_volume_tier(data: dict) -> None:
    assert_configuration_row(data)
    assert data["tier_level"] >= 1
    assert data["min_quantity"] >= 1
    if data.get("max_quantity") is not None:
        assert data["max_quantity"] >= data["min_quantity"]
    assert 0.0 <= data["tier_discount_pct"] < 1.0


def assert_bundle_rule(data: dict) -> None:
    assert_configuration_row(data)
    assert data["anchor_product_id"] != data["attached_product_id"], (
        "the attached product may not be the anchor"
    )
    assert 0.0 < data["bundle_discount_pct"] < 1.0
    assert data["min_attach_quantity_ratio"] > 0


def assert_account(data: dict) -> None:
    assert_versioned_record(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["segment"] in ("ENTERPRISE", "MID_MARKET", "SMB")
    assert isinstance(data["region"], str) and data["region"]
    assert_integer_cents(
        data, "existing_arr_cents", "booked_arr_cents", "exception_allowance_used_cents"
    )
    assert data["existing_arr_cents"] >= 0
    assert data["credit_status"] in ("CLEAR", "WATCH", "HOLD")


def assert_quote(data: dict) -> None:
    assert_versioned_record(data)
    assert data["status"] in (
        "DRAFT",
        "PENDING_APPROVAL",
        "CHANGES_REQUESTED",
        "APPROVED",
        "REJECTED",
        "EXPIRED",
        "SUPERSEDED",
        "BOOKED",
    )
    assert 1 <= data["term_months"] <= 60
    assert 1 <= data["payment_terms_days"] <= 180
    assert data["billing_frequency"] in ("ANNUAL", "SEMI_ANNUAL", "QUARTERLY", "MONTHLY")
    assert_integer_cents(
        data,
        "list_total_cents",
        "cost_total_cents",
        "provisional_net_total_cents",
        "final_net_total_cents",
        "volume_rebate_cents",
        "payment_terms_uplift_cents",
    )
    for field in (
        "provisional_blended_discount_pct",
        "final_blended_discount_pct",
        "provisional_margin_pct",
        "final_margin_pct",
    ):
        assert_six_decimal_pct(data[field], field)
    for field in ("terms_risk_score_aggregate", "terms_risk_score_dominant"):
        assert_two_decimal_score(data[field], field)
        assert 0.0 <= data[field] <= 100.0, f"{field} is capped at 100"
    assert data["required_approval_level"] in (0, 1, 2, 3, 4)
    assert data["arrangement_type"] in ("SINGLE_ELEMENT", "MULTI_ELEMENT", "USAGE_BASED_HYBRID")
    assert isinstance(data["policy_revalidation_required"], bool)
    assert data["revision_count"] >= 0
    assert data["renegotiation_count"] >= 0
    assert_instant_format(data.get("expires_at"), "expires_at")
    assert isinstance(data["owner_rep_user_id"], str) and data["owner_rep_user_id"]


def assert_quote_line(data: dict) -> None:
    assert_versioned_record(data)
    assert 1 <= data["quantity"] <= 1_000_000
    assert 0.0 <= data["requested_discount_pct"] < 1.0
    assert_integer_cents(
        data,
        "unit_list_price_cents",
        "unit_cost_cents",
        "extended_list_cents",
        "extended_cost_cents",
        "provisional_net_cents",
        "final_net_cents",
    )
    assert data["extended_list_cents"] == data["quantity"] * data["unit_list_price_cents"], (
        "extended_list_cents is the quantity multiplied by the snapshotted unit list price"
    )
    assert data["extended_cost_cents"] == data["quantity"] * data["unit_cost_cents"], (
        "extended_cost_cents is the quantity multiplied by the snapshotted unit cost"
    )
    assert data["rev_rec_category"] in ("RATABLE", "POINT_IN_TIME", "USAGE_AS_INCURRED")
    assert data["volume_tier_level_applied"] >= 0
    assert_six_decimal_pct(data["effective_stack_discount_pct"], "effective_stack_discount_pct")
    assert data["final_net_cents"] >= data["provisional_net_cents"], (
        "the marginal-progressive figure is never smaller than the whole-quantity-average figure"
    )


def assert_nonstandard_term(data: dict) -> None:
    assert_versioned_record(data)
    assert data["term_category"] in (
        "PAYMENT_TERMS",
        "SLA_COMMITMENT",
        "INDEMNITY_CAP",
        "TERMINATION_FOR_CONVENIENCE",
        "PRICE_HOLD_RENEWAL",
    )
    assert data["requested_numeric_value"] >= 0
    assert data["review_state"] in ("PENDING", "APPROVED", "REJECTED", "WITHDRAWN")
    assert 0.0 <= data["severity_factor"] <= 1.0, "severity_factor is clamped into [0, 1]"
    assert_six_decimal_pct(data["severity_factor"], "severity_factor")
    assert_two_decimal_score(data["risk_contribution"], "risk_contribution")
    assert isinstance(data["requires_cfo_cosign"], bool)


def assert_competitive_exception(data: dict) -> None:
    assert_versioned_record(data)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED", "REVOKED", "RELEASED")
    assert isinstance(data["competitor_name"], str) and data["competitor_name"]
    assert_integer_cents(data, "competitor_quoted_total_cents", "allowance_consumed_cents")
    assert data["competitor_quoted_total_cents"] > 0
    assert data["allowance_consumed_cents"] >= 0
    assert isinstance(data["documented_by_user_id"], str) and data["documented_by_user_id"]


def assert_revrec_assessment(data: dict) -> None:
    assert_versioned_record(data)
    assert data["status"] in ("ASSESSED", "CLEARED", "BLOCKED", "STALE")
    assert data["arrangement_type"] in ("SINGLE_ELEMENT", "MULTI_ELEMENT", "USAGE_BASED_HYBRID")
    assert_integer_cents(
        data, "usage_excluded_cents", "allocable_amount_cents", "allocation_residual_cents"
    )
    assert data["allocation_residual_cents"] >= 0, "the residual is never negative"
    assert isinstance(data["allocation_lines"], list)
    for line in data["allocation_lines"]:
        assert "quote_line_id" in line and "ssp_cents" in line and "allocated_cents" in line
    assert isinstance(data["snapshot_quote_version"], int)


def assert_approval_request(data: dict) -> None:
    assert_versioned_record(data)
    assert data["status"] in (
        "OPEN",
        "APPROVED",
        "REJECTED",
        "CHANGES_REQUESTED",
        "CANCELLED",
        "EXPIRED",
    )
    assert data["discount_track_state"] in ("NOT_REQUIRED", "PENDING", "CLEARED", "BLOCKED")
    assert data["terms_track_state"] in ("NOT_REQUIRED", "PENDING_LEGAL", "CLEARED", "BLOCKED")
    assert data["sla_state"] in ("ON_TRACK", "BREACHED", "MET")
    assert data["required_level"] in (0, 1, 2, 3, 4)
    assert data["current_level"] in (0, 1, 2, 3, 4)
    assert data["escalation_count"] >= 0
    assert isinstance(data["at_backstop"], bool)
    assert isinstance(data["requires_cfo_cosign"], bool)
    if data.get("total_turnaround_hours") is not None:
        assert_two_decimal_score(data["total_turnaround_hours"], "total_turnaround_hours")


def assert_approval_step(data: dict) -> None:
    assert_versioned_record(data)
    assert data["decision"] in (
        "PENDING",
        "APPROVED",
        "REJECTED",
        "CHANGES_REQUESTED",
        "ESCALATED",
        "VOIDED",
    )
    assert data["level"] in (1, 2, 3, 4)
    assert data["assigned_role"] in ("DealDeskAnalyst", "SalesDirector", "VPSales", "CFO")
    assert isinstance(data["in_surge_window"], bool)
    assert_two_decimal_score(data["sla_hours_effective"], "sla_hours_effective")
    assert_instant_format(data.get("sla_due_at"), "sla_due_at")
    if data.get("turnaround_hours") is not None:
        assert_two_decimal_score(data["turnaround_hours"], "turnaround_hours")


def assert_delegation_grant(data: dict) -> None:
    assert_versioned_record(data)
    assert data["status"] in ("ACTIVE", "REVOKED", "EXPIRED")
    assert data["tier_level"] in (1, 2, 3, 4)
    assert 0.0 <= data["max_discount_pct"] <= 1.0
    assert_instant_format(data.get("starts_at"), "starts_at")
    assert_instant_format(data.get("ends_at"), "ends_at")
    assert normalize_instant(data["starts_at"]) < normalize_instant(data["ends_at"]), (
        "a delegation window has its starts_at strictly before its ends_at"
    )
    assert data["used_step_count"] >= 0
    assert isinstance(data["grantor_user_id"], str) and data["grantor_user_id"]
    assert isinstance(data["grantee_user_id"], str) and data["grantee_user_id"]


def assert_order_form(data: dict) -> None:
    assert_versioned_record(data)
    assert data["status"] in (
        "GENERATED",
        "OUT_FOR_SIGNATURE",
        "SIGNED",
        "DECLINED",
        "BOOKED",
        "VOID",
    )
    assert isinstance(data["signer_name"], str) and data["signer_name"]
    assert isinstance(data["signer_email"], str) and data["signer_email"]
    assert_integer_cents(data, "booked_arr_cents", "booked_tcv_cents")
    assert isinstance(data["generated_from_quote_version"], int)
    assert data["booking_reversal_count"] >= 0
    if data.get("void_reason") is not None:
        assert data["void_reason"] in (
            "QUOTE_EXPIRED",
            "SUPERSEDED_BY_NEW_ORDER_FORM",
            "BOOKING_REVERSED",
        )


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_account_ledgers(
    account: dict, expected_booked_arr_cents: int, expected_allowance_used_cents: int
) -> None:
    """The two conserved account counters."""
    assert account["booked_arr_cents"] == expected_booked_arr_cents, (
        f"Expected Account.booked_arr_cents {expected_booked_arr_cents}, "
        f"got {account['booked_arr_cents']}"
    )
    assert account["exception_allowance_used_cents"] == expected_allowance_used_cents, (
        f"Expected Account.exception_allowance_used_cents {expected_allowance_used_cents}, "
        f"got {account['exception_allowance_used_cents']}"
    )


def assert_quote_money(quote: dict, **expected: int) -> None:
    """Assert a set of the quote's money and percentage fields by exact value."""
    for field, value in expected.items():
        actual = quote.get(field)
        if isinstance(value, float):
            assert actual == value, f"Expected {field} {value}, got {actual}"
        else:
            assert actual == value, f"Expected {field} {value}, got {actual}"
