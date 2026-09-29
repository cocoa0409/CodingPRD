"""Entity assertions and domain invariant checkers.

Instant comparisons go through ``assert_instant`` so that a serialiser writing
``...:00Z`` and one writing ``...:00.000Z`` are both accepted — the PRD fixes
the moment, not the character width of the fraction.
"""

from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant, instants_equal


# --------------------------------------------------------------------------
# Generic shape helpers
# --------------------------------------------------------------------------
def assert_identity_fields(data: dict, versioned: bool = True) -> None:
    """id is a UUID with no prefix, created_at is ISO-8601, version starts at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')!r}"
    if versioned:
        assert isinstance(data.get("version"), int), "version must be an integer"
        assert data["version"] >= 1, "version starts at 1"


def assert_append_only_identity(data: dict) -> None:
    """Append-only rows carry an id and a created_at and nothing else generic."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')!r}"


def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Compare two instants for the same moment, ignoring fractional width."""
    assert instants_equal(actual, expected), (
        f"{label}: expected {expected!r}, got {actual!r} "
        f"(canonical {canonical_instant(expected)!r} vs {canonical_instant(actual)!r})"
    )


def assert_null(value, label: str = "field") -> None:
    assert value is None, f"{label} must be null, got {value!r}"


def assert_pagination_meta(meta: dict, total_count: int, has_more: bool = False) -> None:
    assert meta["total_count"] == total_count, (
        f"total_count: expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"has_more: expected {has_more}, got {meta['has_more']}"
    )


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------
def assert_customer(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["email"], str) and data["email"].strip() != ""
    assert isinstance(data["full_name"], str)
    assert data["loyalty_tier"] in ("STANDARD", "PLUS")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["credit_balance_minor"], int)
    assert data["credit_balance_minor"] >= 0
    assert isinstance(data["diverted_grams_total"], int)
    assert data["diverted_grams_total"] >= 0


def assert_grade_policy(data: dict) -> None:
    assert_identity_fields(data)
    assert data["product_category"] in ("FOOTWEAR", "OUTERWEAR", "BAG")
    assert data["condition_grade"] in ("A", "B", "C", "SALVAGE")
    for field in (
        "base_credit_pct_bp",
        "resale_price_pct_bp",
        "refurb_budget_cap_pct_bp",
        "restock_fee_pct_bp",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer basis-point value"
        assert 0 <= data[field] <= 10000, f"{field} must be between 0 and 10000"
    assert isinstance(data["warranty_days"], int) and data["warranty_days"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_credit_policy(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["code"], str) and data["code"].strip() != ""
    assert isinstance(data["expiry_days"], int) and data["expiry_days"] >= 1
    assert 0 <= data["mail_in_bonus_pct_bp"] <= 10000
    assert 1 <= data["max_redemption_pct_bp"] <= 10000
    assert isinstance(data["min_cash_remainder_minor"], int)
    assert data["min_cash_remainder_minor"] >= 0
    assert data["eligible_assortment"] in ("NEW_ONLY", "RESALE_ONLY", "BOTH")
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_store_location(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["code"], str) and data["code"].strip() != ""
    assert isinstance(data["region_code"], str) and data["region_code"].strip() != ""
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_refurb_bay(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["store_location_id"])
    assert isinstance(data["code"], str) and data["code"].strip() != ""
    assert data["bay_type"] in ("CLEANING", "REPAIR", "REPACKAGING")
    assert data["status"] in ("AVAILABLE", "OUT_OF_SERVICE")


def assert_channel(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["code"], str) and data["code"].strip() != ""
    assert data["channel_type"] in ("FULL_PRICE_DTC", "RESALE_MARKETPLACE", "OUTLET")
    assert data["allowed_assortment"] in ("NEW_ONLY", "RESALE_ONLY", "BOTH")
    assert 1 <= data["max_resale_price_ratio_bp"] <= 10000
    assert isinstance(data["region_code"], str) and data["region_code"].strip() != ""
    assert data["status"] in ("ACTIVE", "PAUSED")


def assert_trade_in(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["channel"] in ("MAIL_IN", "IN_STORE")
    assert data["product_category"] in ("FOOTWEAR", "OUTERWEAR", "BAG")
    assert data["declared_grade"] in ("A", "B", "C", "SALVAGE")
    assert isinstance(data["msrp_minor"], int) and data["msrp_minor"] >= 1
    assert isinstance(data["item_mass_grams"], int) and data["item_mass_grams"] >= 1
    assert data["status"] in (
        "SUBMITTED",
        "RECEIVED",
        "AUTHENTICATED",
        "APPEALED",
        "ACCEPTED",
        "REJECTED",
    )
    assert data["authenticity_result"] in (
        "PENDING",
        "GENUINE",
        "COUNTERFEIT",
        "INCONCLUSIVE",
    )
    assert isinstance(data["appeal_count"], int) and 0 <= data["appeal_count"] <= 1
    assert isinstance(data["appraised_credit_minor"], int)
    assert 0 <= data["appraised_credit_minor"] <= 60000
    assert is_iso8601_timestamp(data["receive_deadline_at"])
    if data["channel"] == "MAIL_IN":
        assert data.get("store_location_id") is None, (
            "store_location_id must be null on a MAIL_IN trade-in"
        )
    else:
        assert is_valid_uuid(data["store_location_id"])


def assert_credit_grant(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["trade_in_id"])
    assert is_valid_uuid(data["credit_policy_id"])
    assert isinstance(data["credit_policy_version"], int)
    assert isinstance(data["issued_amount_minor"], int) and data["issued_amount_minor"] >= 0
    assert isinstance(data["remaining_minor"], int) and data["remaining_minor"] >= 0
    assert data["remaining_minor"] <= data["issued_amount_minor"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("ISSUED", "PARTIALLY_REDEEMED", "EXHAUSTED", "EXPIRED")


def assert_credit_ledger_entry(data: dict) -> None:
    """A ledger row is append-only: id + created_at only, no version."""
    assert_append_only_identity(data)
    assert is_valid_uuid(data["credit_grant_id"])
    assert data["entry_type"] in ("ISSUE", "REDEEM", "RELEASE", "EXPIRE")
    assert isinstance(data["amount_minor"], int)
    assert isinstance(data["balance_after_minor"], int)
    assert data["balance_after_minor"] >= 0
    assert is_iso8601_timestamp(data["occurred_at"])


def assert_resale_unit(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["trade_in_id"])
    assert data["product_category"] in ("FOOTWEAR", "OUTERWEAR", "BAG")
    assert data["condition_grade"] in ("A", "B", "C", "SALVAGE")
    assert isinstance(data["mass_grams"], int) and data["mass_grams"] >= 1
    assert isinstance(data["reference_msrp_minor"], int)
    assert data["ownership_treatment"] in ("OWNED_INVENTORY", "CONSIGNED")
    assert data["lifecycle_state"] in (
        "INTAKE",
        "IN_REFURB",
        "READY",
        "LISTED",
        "RESERVED",
        "SOLD",
        "RETURNED",
        "SALVAGED",
    )
    assert data["accounting_state"] in (
        "UNCAPITALIZED",
        "CAPITALIZED",
        "WRITTEN_DOWN",
        "EXPENSED",
    )
    assert isinstance(data["capitalized_cost_minor"], int)
    assert data["capitalized_cost_minor"] >= 0
    assert isinstance(data["markdown_step_count"], int)
    assert data["markdown_step_count"] >= 0


def assert_refurb_order(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["resale_unit_id"])
    assert is_valid_uuid(data["refurb_bay_id"])
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert canonical_instant(data["window_end_at"]) > canonical_instant(
        data["window_start_at"]
    ), "window_end_at must be strictly after window_start_at"
    assert data["status"] in (
        "SCHEDULED",
        "IN_PROGRESS",
        "QC_PENDING",
        "QC_FAILED",
        "COMPLETED",
        "SALVAGED",
        "SUPERSEDED",
    )
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert isinstance(data["logged_cost_minor"], int) and data["logged_cost_minor"] >= 0
    assert isinstance(data["viability_ratio_bp"], int)


def assert_refurb_task(data: dict) -> None:
    """An effort line is append-only: id + created_at only, no version."""
    assert_append_only_identity(data)
    assert is_valid_uuid(data["refurb_order_id"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert data["task_type"] in ("CLEANING", "REPAIR", "REPACKAGING")
    assert isinstance(data["labor_minutes"], int) and data["labor_minutes"] >= 0
    assert isinstance(data["parts_cost_minor"], int) and data["parts_cost_minor"] >= 0
    assert isinstance(data["cost_minor"], int) and data["cost_minor"] >= 0
    assert isinstance(data["logged_by_user_id"], str) and data["logged_by_user_id"] != ""


def assert_markdown_campaign(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["channel_id"])
    assert data["product_category"] in ("FOOTWEAR", "OUTERWEAR", "BAG")
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert isinstance(data["cadence_days"], int) and data["cadence_days"] >= 1
    assert 1 <= data["step_bp"] <= 9999
    assert 1 <= data["floor_pct_bp"] <= 10000
    assert data["status"] in ("SCHEDULED", "ACTIVE", "CLOSED")
    assert isinstance(data["run_count"], int) and data["run_count"] >= 0


def assert_resale_order(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["channel_id"])
    assert is_valid_uuid(data["resale_unit_id"])
    for field in (
        "gross_price_minor",
        "channel_fee_minor",
        "order_total_minor",
        "credit_applied_minor",
        "cash_due_minor",
        "restock_fee_minor",
        "refund_cash_minor",
        "refund_credit_minor",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer of minor units"
        assert data[field] >= 0, f"{field} must never be negative"
    assert data["order_total_minor"] == data["gross_price_minor"] + data["channel_fee_minor"]
    assert data["cash_due_minor"] == data["order_total_minor"] - data["credit_applied_minor"]
    assert data["status"] in (
        "PLACED",
        "FULFILLED",
        "RETURN_REQUESTED",
        "RETURNED",
        "REPLACED",
    )
    assert data["reason_type"] in ("NONE", "BUYER_REMORSE", "WARRANTY_DEFECT")


def assert_diversion_report(data: dict) -> None:
    assert_identity_fields(data)
    assert is_iso8601_timestamp(data["period_start_at"])
    assert is_iso8601_timestamp(data["period_end_at"])
    assert isinstance(data["units_diverted_count"], int)
    assert isinstance(data["diverted_grams"], int) and data["diverted_grams"] >= 0
    assert isinstance(data["salvage_grams"], int) and data["salvage_grams"] >= 0
    assert 0 <= data["landfill_diversion_rate_bp"] <= 10000
    assert isinstance(data["credit_liability_minor"], int)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_grant_conservation(grant: dict, entries: list) -> None:
    """A grant's remaining_minor is its issued amount plus every signed entry.

    The ISSUE row carries the positive issuance, REDEEM rows are negative and
    RELEASE rows positive, so the signed sum of every row after the ISSUE row
    must land exactly on remaining_minor.
    """
    issue_rows = [e for e in entries if e["entry_type"] == "ISSUE"]
    assert len(issue_rows) == 1, "a grant has exactly one ISSUE entry"
    assert issue_rows[0]["amount_minor"] == grant["issued_amount_minor"]
    signed_sum = sum(e["amount_minor"] for e in entries)
    assert signed_sum == grant["remaining_minor"], (
        f"ledger conservation: signed sum {signed_sum} != remaining "
        f"{grant['remaining_minor']}"
    )


def assert_ledger_balances_run(entries: list) -> None:
    """Each entry's balance_after_minor is the running total of the ledger."""
    running = 0
    for entry in entries:
        running += entry["amount_minor"]
        assert entry["balance_after_minor"] == running, (
            f"balance_after_minor should be {running} on the "
            f"{entry['entry_type']} entry, got {entry['balance_after_minor']}"
        )


def assert_unit_dimensions(
    unit: dict, lifecycle_state: str, accounting_state: str
) -> None:
    """The unit's two independent dimensions both land where expected."""
    assert unit["lifecycle_state"] == lifecycle_state, (
        f"lifecycle_state: expected {lifecycle_state}, got {unit['lifecycle_state']}"
    )
    assert unit["accounting_state"] == accounting_state, (
        f"accounting_state: expected {accounting_state}, got {unit['accounting_state']}"
    )


def assert_money_fields_are_integers(data: dict) -> None:
    """No money or mass field may be serialised as a string or a float."""
    for key, value in data.items():
        if key.endswith("_minor") or key.endswith("_grams") or key.endswith("_bp"):
            if value is None:
                continue
            assert isinstance(value, int) and not isinstance(value, bool), (
                f"{key} must be a JSON integer, got {type(value).__name__}: {value!r}"
            )
