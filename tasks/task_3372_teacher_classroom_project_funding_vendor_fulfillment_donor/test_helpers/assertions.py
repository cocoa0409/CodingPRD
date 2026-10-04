"""Domain assertions for the teacher-classroom-funding API.

Instants compare on a canonical three-digit form rather than on raw strings;
money compares as integer cents; the common field quartet is checked once here
instead of in every test. The two ledger conservation identities of the
contract get their own checkers.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant


# ── Instants ───────────────────────────────────────────────────────────────

def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_instant_format(value: str, label: str = "instant") -> None:
    """Assert a value is an ISO 8601 UTC instant rendered with a Z suffix."""
    assert is_iso8601_timestamp(value), f"{label}: not an ISO 8601 timestamp: {value!r}"
    assert value.endswith("Z"), f"{label}: must be rendered in UTC with a Z suffix: {value!r}"


# ── Numbers ────────────────────────────────────────────────────────────────

def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a money amount: the contract carries money as integer cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: money must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_one_dp(actual: Any, expected: float, label: str = "value") -> None:
    """Assert a one-decimal-place figure, the precision the weighted score uses."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert round(float(actual), 1) == round(float(expected), 1), (
        f"{label}: expected {expected} at one decimal place, got {actual}"
    )


# ── Common fields ──────────────────────────────────────────────────────────

def assert_identity_fields(data: Dict[str, Any], label: str = "resource") -> None:
    """Assert a resource carries a server-minted UUID and a UTC creation instant."""
    assert is_valid_uuid(data.get("id")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_instant_format(data["created_at"], f"{label}.created_at")


def assert_common_fields(data: Dict[str, Any], label: str = "resource") -> None:
    """Assert the full identity quartet on a mutable resource."""
    assert_identity_fields(data, label)
    assert_instant_format(data["updated_at"], f"{label}.updated_at")
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version must be >= 1, got {data['version']}"


def assert_append_only_fields(data: Dict[str, Any], label: str = "resource") -> None:
    """Assert an append-only record carries an id and creation instant only.

    The thank-you package is never versioned or update-stamped.
    """
    assert_identity_fields(data, label)
    assert "version" not in data, f"{label} must not expose version"
    assert "updated_at" not in data, f"{label} must not expose updated_at"


# ── Entity shapes ──────────────────────────────────────────────────────────

def assert_school(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "school")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["district"], str)
    assert 0.0 <= float(data["poverty_pct"]) <= 100.0
    assert 0.0 <= float(data["ell_pct"]) <= 100.0
    assert isinstance(data["equity_score_banded"], int)
    assert data["equity_score_banded"] in (10, 50, 80, 100)
    assert_one_dp(data["equity_score_weighted"], float(data["equity_score_weighted"]), "school.equity_score_weighted")


def assert_teacher(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "teacher")
    assert is_valid_uuid(data.get("school_id")), "teacher.school_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data.get("subjects_taught", []), list)
    assert data["employment_status"] in ("PENDING_VERIFICATION", "VERIFIED", "SUSPENDED")


def assert_vendor(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "vendor")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["ship_from_state"], str) and len(data["ship_from_state"]) == 2
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_catalog_item(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "catalog_item")
    assert is_valid_uuid(data.get("vendor_id")), "catalog_item.vendor_id must be a UUID"
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in ("BOOKS", "TECHNOLOGY", "FURNITURE", "SUPPLIES", "LAB_EQUIPMENT", "SPORTS")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 1
    assert isinstance(data["weight_oz"], int) and data["weight_oz"] >= 1
    assert data["shipping_zone"] in ("A", "B", "C")
    assert isinstance(data["fragile"], bool)
    assert "max_quantity_per_project" in data
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_project(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "project")
    assert is_valid_uuid(data.get("teacher_id")), "project.teacher_id must be a UUID"
    assert is_valid_uuid(data.get("school_id")), "project.school_id must be a UUID"
    assert data["subject"] in ("MATH", "SCIENCE", "LITERACY", "ARTS", "SOCIAL_STUDIES", "HEALTH_PE", "OTHER")
    assert data["grade_band"] in ("K_2", "G3_5", "G6_8", "G9_12")
    assert 30 <= data["funding_window_days"] <= 180
    assert data["status"] in (
        "DRAFT", "IN_REVIEW", "VETTING", "RETURNED", "REJECTED", "FUNDING",
        "FUNDED", "EXPIRED", "CANCELLED", "FULFILLED", "CLOSED",
    )
    assert isinstance(data["funded_cents"], int) and data["funded_cents"] >= 0


def assert_project_item(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "project_item")
    assert is_valid_uuid(data.get("project_id"))
    assert is_valid_uuid(data.get("catalog_item_id"))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_donor(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "donor")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    for field in ("lifetime_donated_cents", "lifetime_refunded_cents", "lifetime_reallocated_cents"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_donation(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "donation")
    assert is_valid_uuid(data.get("project_id"))
    assert data["kind"] in ("DONOR", "EQUITY_GRANT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["matched_cents"], int) and data["matched_cents"] >= 0
    assert data["status"] in ("CAPTURED", "CHOICE_PENDING", "REFUNDED", "REALLOCATED")


def assert_match_campaign(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "match_campaign")
    assert isinstance(data["sponsor_name"], str) and data["sponsor_name"]
    assert 0 < float(data["match_ratio"]) <= 2.0
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] >= 1
    assert isinstance(data["matched_so_far_cents"], int)
    assert isinstance(data["remaining_budget_cents"], int)
    assert data["target_type"] in ("SCHOOL", "SUBJECT", "STATE")
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "CLOSED")
    assert_instant_format(data["starts_at"], "match_campaign.starts_at")
    assert_instant_format(data["ends_at"], "match_campaign.ends_at")


def assert_purchase_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "purchase_order")
    assert is_valid_uuid(data.get("project_id"))
    assert is_valid_uuid(data.get("vendor_id"))
    assert isinstance(data["line_items"], list) and len(data["line_items"]) >= 1
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["shipping_fee_cents"], int)
    assert data["status"] in ("ISSUED", "SHIPPED", "DELIVERED", "DIVERSION_REPORTED", "CANCELLED")


def assert_thank_you_package(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data, "thank_you_package")
    assert is_valid_uuid(data.get("project_id"))
    assert data["status"] in ("PENDING", "SUBMITTED")


def assert_fraud_case(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "fraud_case")
    assert is_valid_uuid(data.get("teacher_id"))
    assert is_valid_uuid(data.get("project_id"))
    assert is_valid_uuid(data.get("purchase_order_id"))
    assert isinstance(data["reason"], str)
    assert data["status"] in ("OPEN", "CONFIRMED", "DISMISSED")


def assert_equity_fund(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "equity_fund")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert 0.0 <= float(data["min_poverty_pct"]) <= 100.0
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] >= 1
    assert isinstance(data["remaining_cents"], int)
    assert data["status"] in ("ACTIVE", "DEPLETED", "CLOSED")
    assert_instant_format(data["window_start"], "equity_fund.window_start")
    assert_instant_format(data["window_end"], "equity_fund.window_end")


# ── Conservation invariants ────────────────────────────────────────────────

def assert_donor_conservation(donor: Dict[str, Any], active_amount_cents: int) -> None:
    """Donor conservation: lifetime_donated == active + refunded + reallocated.

    ``active_amount_cents`` is the sum of ``amount_cents`` over the donor's
    donations currently in CAPTURED or CHOICE_PENDING, which the test knows
    from its own setup.
    """
    total = donor["lifetime_donated_cents"]
    refunded = donor["lifetime_refunded_cents"]
    reallocated = donor["lifetime_reallocated_cents"]
    assert total == active_amount_cents + refunded + reallocated, (
        f"donor conservation broken: donated {total} != active {active_amount_cents} "
        f"+ refunded {refunded} + reallocated {reallocated}"
    )


def assert_campaign_budget_invariant(campaign: Dict[str, Any]) -> None:
    """Campaign budget conservation: budget == matched_so_far + remaining."""
    budget = campaign["budget_cents"]
    so_far = campaign["matched_so_far_cents"]
    remaining = campaign["remaining_budget_cents"]
    assert budget == so_far + remaining, (
        f"campaign budget conservation broken: budget {budget} != "
        f"matched_so_far {so_far} + remaining {remaining}"
    )
