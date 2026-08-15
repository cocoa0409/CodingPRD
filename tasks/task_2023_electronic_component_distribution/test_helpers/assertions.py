"""Entity assertions and domain invariant checkers (PRD §2.8, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_manufacturer_line(data: dict):
    _assert_common(data)
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["sourcing_channel"] in ("FRANCHISED", "OPEN_MARKET")
    assert isinstance(data["ncnr"], bool)
    assert isinstance(data["cancel_window_days"], int)
    assert isinstance(data["reschedule_window_days"], int)
    assert data["allocation_policy"] in ("BACKLOG_BASIS", "USAGE_BASIS")
    assert isinstance(data["open_debit_balance_cents"], int)


def assert_part(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("manufacturer_line_id", ""))
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["msl_level"], int) and 1 <= data["msl_level"] <= 6
    assert isinstance(data["floor_life_hours"], int)
    assert isinstance(data["date_code_limit_months"], int)
    assert isinstance(data["standard_cost_cents"], int)
    assert isinstance(data["book_price_cents"], int)
    assert isinstance(data["qty_on_hand"], int)
    assert isinstance(data["qty_reserved"], int)
    assert isinstance(data["open_demand_qty"], int)


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["open_balance_cents"], int)
    assert isinstance(data["trailing_12mo_purchases_cents"], int)
    assert isinstance(data["trailing_12mo_component_usage_units"], int)
    assert data["status"] in ("GOOD_STANDING", "CREDIT_HOLD")


def assert_design_registration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("part_id", ""))
    assert isinstance(data["end_customer_name"], str)
    assert isinstance(data["registered_cost_cents"], int)
    assert isinstance(data["max_registered_qty"], int)
    assert isinstance(data["registered_qty_remaining"], int)
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_to"], str)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "EXPIRED", "EXHAUSTED")


def assert_customer_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["status"] in ("SUBMITTED", "ACKNOWLEDGED", "ON_HOLD",
                              "PARTIALLY_SHIPPED", "COMPLETED", "CANCELLED")
    assert isinstance(data["open_exposure_cents"], int)
    assert isinstance(data["allocated_value_cents"], int)


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("part_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["ship_date"], str)
    assert data["status"] in ("OPEN", "ALLOCATED", "SHIPPED", "CANCELLED")
    assert isinstance(data["allocated_qty"], int)
    assert isinstance(data["shipped_qty"], int)
    assert isinstance(data["returned_qty"], int)


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("part_id", ""))
    assert isinstance(data["date_code"], str)
    assert isinstance(data["qty_received"], int) and data["qty_received"] > 0
    assert isinstance(data["qty_on_hand"], int)
    assert isinstance(data["qty_reserved"], int)
    assert isinstance(data["qty_shipped"], int)
    assert data["source_type"] in ("FRANCHISED", "OPEN_MARKET")
    assert data["authenticity"] in ("NOT_REQUIRED", "PENDING_INSPECTION",
                                    "AUTHENTICATED", "REJECTED")
    assert isinstance(data["msl_exposure_hours"], int)
    assert isinstance(data["received_by_user_id"], str)
    assert data["status"] in ("AVAILABLE", "IN_INSPECTION", "QUARANTINED",
                              "REJECTED", "DEPLETED")


def assert_moisture_exposure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_iso8601_timestamp(data.get("opened_at", ""))
    sealed_at = data.get("sealed_at")
    assert sealed_at is None or is_iso8601_timestamp(sealed_at), \
        "sealed_at must be null while open or an ISO 8601 UTC timestamp"


def assert_alternate_part_approval(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("primary_part_id", ""))
    assert is_valid_uuid(data.get("alternate_part_id", ""))
    assert data["status"] in ("PROPOSED", "APPROVED", "REJECTED", "REVOKED")


def assert_allocation_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("part_id", ""))
    assert data["basis"] in ("BACKLOG_BASIS", "USAGE_BASIS")
    assert isinstance(data["total_supply_qty"], int)
    assert isinstance(data["total_demand_qty"], int)
    assert isinstance(data["lines"], list)
    for run_line in data["lines"]:
        assert is_valid_uuid(run_line.get("order_line_id", ""))
        assert isinstance(run_line["allocated_qty"], int)
    assert data["status"] in ("PROVISIONAL", "PUBLISHED", "SUPERSEDED")


def assert_ship_and_debit_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("registration_id", ""))
    assert is_valid_uuid(data.get("order_line_id", ""))
    assert isinstance(data["qty"], int) and data["qty"] > 0
    assert isinstance(data["standard_cost_cents"], int)
    assert isinstance(data["registered_cost_cents"], int)
    assert isinstance(data["amount_provisional_cents"], int)
    assert data.get("audited_cost_cents") is None or isinstance(data["audited_cost_cents"], int)
    assert data.get("amount_final_cents") is None or isinstance(data["amount_final_cents"], int)
    assert data["status"] in ("SUBMITTED", "SUPPLIER_APPROVED", "SUPPLIER_REJECTED",
                              "DISPUTED", "SETTLED", "REVERSED")


def assert_buyback_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("order_line_id", ""))
    assert data["kind"] in ("EXCESS_RETURN", "SHORTAGE_BUYBACK")
    assert isinstance(data["qty"], int) and data["qty"] > 0
    assert isinstance(data["price_basis_cents"], int)
    assert isinstance(data["fee_pct"], (int, float))
    assert isinstance(data["provisional_credit_cents"], int)
    assert data.get("received_qty") is None or isinstance(data["received_qty"], int)
    assert data.get("final_credit_cents") is None or isinstance(data["final_credit_cents"], int)
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "RECEIVED")


def assert_lot_unit_conservation(lot: dict):
    """Physical-unit invariant: a lot's received units always partition into
    on-hand + reserved + shipped (PRD §3.4/§3.5 reservation bookkeeping)."""
    total = lot["qty_on_hand"] + lot["qty_reserved"] + lot["qty_shipped"]
    assert total == lot["qty_received"], (
        f"Unit conservation violated: {lot['qty_on_hand']} on_hand + "
        f"{lot['qty_reserved']} reserved + {lot['qty_shipped']} shipped "
        f"!= {lot['qty_received']} received"
    )
