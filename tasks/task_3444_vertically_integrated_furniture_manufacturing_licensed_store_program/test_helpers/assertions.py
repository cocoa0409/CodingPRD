"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Every assert_{entity} validates the four common system-managed properties
(PRD §2.4) plus the entity's own fields and enum domains. Value-level claims
(specific totals, fees, scores) live in the tests themselves.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """PRD §2.4: id (UUID), created_at/updated_at (ISO 8601 UTC), version (int)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_factory(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["region"] in ("DOMESTIC", "OVERSEAS")
    assert isinstance(data["component_lines"], list) and len(data["component_lines"]) > 0
    assert all(c in ("FOAM", "FRAMES", "UPHOLSTERY") for c in data["component_lines"])
    assert isinstance(data["weekly_capacity_units"], int) and data["weekly_capacity_units"] > 0
    assert data["status"] in ("ACTIVE", "CONSTRAINED", "OFFLINE")


def assert_product_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in ("UPHOLSTERY", "CASEGOODS", "BEDDING")
    assert isinstance(data["style_code"], str) and data["style_code"]
    assert isinstance(data["price_point_cents"], int)
    assert data["lifecycle"] in ("CONCEPT", "ACTIVE", "CLEARANCE", "RETIRED")
    assert isinstance(data["clearance_price_cents"], int)


def assert_licensee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["royalty_rate"], (int, float))
    assert isinstance(data["merchandising_standard_version"], str)
    assert isinstance(data["latest_audit_score"], int)
    assert data["status"] in ("APPLICANT", "ACTIVE", "PROBATION", "SUSPENDED", "TERMINATED")
    assert data["last_cycle_score"] is None or isinstance(data["last_cycle_score"], (int, float))
    assert data["seasoned_score"] is None or isinstance(data["seasoned_score"], (int, float))
    assert isinstance(data["royalty_accrued_cents"], int)
    assert isinstance(data["chargeback_cents"], int)
    assert isinstance(data["net_royalty_cents"], int)


def assert_territory(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["population_tier"] in ("METRO", "SUBURBAN", "RURAL")
    assert data["status"] in ("OPEN", "ASSIGNED")
    assert data["assigned_licensee_id"] is None or is_valid_uuid(data["assigned_licensee_id"])
    assert data["assigned_at"] is None or is_iso8601_timestamp(data["assigned_at"])
    assert data["revoked_at"] is None or is_iso8601_timestamp(data["revoked_at"])


def assert_retail_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] > 0
    assert isinstance(data["credit_used_cents"], int)
    assert data["status"] in ("ACTIVE", "HOLD", "CLOSED")


def assert_distribution_center(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["supports_home_delivery"], bool)
    assert isinstance(data["daily_crew_units"], int)
    assert isinstance(data["region_codes"], list)


def assert_allocation_cycle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["factory_id"])
    assert is_iso8601_timestamp(data["week_start"])
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] > 0
    assert data["status"] in ("OPEN", "ALLOCATED", "CLOSED")
    assert isinstance(data["licensee_reserved_units"], int)
    assert isinstance(data["wholesale_reserved_units"], int)
    assert isinstance(data["available_units"], int)
    assert data["run_at"] is None or is_iso8601_timestamp(data["run_at"])
    assert data["closed_at"] is None or is_iso8601_timestamp(data["closed_at"])


def assert_supply_order(data: dict):
    _assert_common_fields(data)
    assert data["buyer_type"] in ("LICENSEE", "RETAIL_ACCOUNT")
    if data["buyer_type"] == "LICENSEE":
        assert is_valid_uuid(data["licensee_id"])
        assert data["retail_account_id"] is None
    else:
        assert is_valid_uuid(data["retail_account_id"])
        assert data["licensee_id"] is None
    assert is_valid_uuid(data["allocation_cycle_id"])
    assert is_valid_uuid(data["product_line_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["delivery_mode"] in ("FREIGHT_TO_STORE", "HOME_DELIVERY")
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["provisional_total_cents"], int)
    assert data["final_total_cents"] is None or isinstance(data["final_total_cents"], int)
    assert data["allocation_state"] in (
        "UNALLOCATED", "RESERVED", "ALLOCATED", "WAITLISTED", "DROPPED",
    )
    assert data["fulfillment_state"] in (
        "PENDING", "PICKED", "SHIPPED", "DELIVERED", "CANCELLED",
    )
    assert data["submitted_at"] is None or is_iso8601_timestamp(data["submitted_at"])
    assert data["delivered_at"] is None or is_iso8601_timestamp(data["delivered_at"])
    assert data["cancel_reason"] is None or isinstance(data["cancel_reason"], str)


def assert_delivery_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["supply_order_id"])
    assert is_valid_uuid(data["licensee_id"])
    assert is_valid_uuid(data["dc_id"])
    assert data["zone"] in ("LOCAL", "REGIONAL", "EXTENDED")
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["crew_units"], int)
    assert isinstance(data["stairs_flights"], int) and data["stairs_flights"] >= 0
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "MISSED", "CANCELLED")
    assert isinstance(data["estimate_fee_cents"], int)
    assert data["final_fee_cents"] is None or isinstance(data["final_fee_cents"], int)
    assert data["actual_duration_minutes"] is None or isinstance(
        data["actual_duration_minutes"], int
    )
    assert data["completed_at"] is None or is_iso8601_timestamp(data["completed_at"])


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["supply_order_id"])
    assert is_valid_uuid(data["licensee_id"])
    assert data["claim_type"] in ("DEFECT", "DAMAGE_IN_TRANSIT", "MISSING_PARTS")
    assert isinstance(data["description"], str)
    assert data["status"] in (
        "UNDER_REVIEW", "INFO_REQUESTED", "PARTS_ORDERED", "RESOLVED", "DENIED",
    )
    assert isinstance(data["info_request_count"], int)
    assert data["decision"] is None or data["decision"] in ("APPROVED", "DENIED")
    assert data["decision_note"] is None or isinstance(data["decision_note"], str)
    assert data["chargeback_cents"] is None or isinstance(data["chargeback_cents"], int)
    assert data["resolved_at"] is None or is_iso8601_timestamp(data["resolved_at"])


def assert_parts_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["status"] in ("QUEUED", "SHIPPED", "DELIVERED")


def assert_cycle_capacity_conserved(cycle: dict):
    """PRD §3.4: available_units == capacity_units - licensee_reserved_units -
    wholesale_reserved_units, never negative."""
    expected = (
        cycle["capacity_units"]
        - cycle["licensee_reserved_units"]
        - cycle["wholesale_reserved_units"]
    )
    assert cycle["available_units"] == expected, (
        f"capacity not conserved: available {cycle['available_units']} != "
        f"{cycle['capacity_units']} - {cycle['licensee_reserved_units']} - "
        f"{cycle['wholesale_reserved_units']}"
    )
    assert cycle["available_units"] >= 0


def assert_licensee_ledger_consistent(licensee: dict):
    """PRD §3.2/§3.7: net_royalty_cents == royalty_accrued_cents - chargeback_cents."""
    assert (
        licensee["net_royalty_cents"]
        == licensee["royalty_accrued_cents"] - licensee["chargeback_cents"]
    ), (
        f"ledger inconsistent: net {licensee['net_royalty_cents']} != "
        f"{licensee['royalty_accrued_cents']} - {licensee['chargeback_cents']}"
    )
