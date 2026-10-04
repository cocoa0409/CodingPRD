"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only rows must not expose updated_at"
    assert "version" not in data, "append-only rows must not expose version"


def assert_licensee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["legal_entity_code"], str) and data["legal_entity_code"]


def assert_host_venue(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["venue_type"] in ["GROCERY", "AIRPORT", "CAMPUS", "HOSPITAL"]
    assert isinstance(data["open_time_utc"], str)
    assert isinstance(data["close_time_utc"], str)
    assert isinstance(data["access_restricted"], bool)
    assert isinstance(data["security_badge_required"], bool)
    assert isinstance(data["max_equipment_footprint_units"], int)
    assert data["max_equipment_footprint_units"] >= 1


def assert_license_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["licensee_id"], str)
    assert isinstance(data["venue_id"], str)
    assert isinstance(data["royalty_tiers"], list) and data["royalty_tiers"]
    assert data["royalty_basis"] in ["CASH", "ACCRUAL"]
    assert isinstance(data["term_start_date"], str)
    assert isinstance(data["term_end_date"], str)
    assert data["status"] in [
        "DRAFT", "PENDING_ACCEPTANCE", "ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED",
    ]
    assert isinstance(data["breach_strikes"], int) and data["breach_strikes"] >= 0


def assert_licensed_store(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["equipment_footprint_units"], int)
    assert data["equipment_footprint_units"] >= 1
    assert data["operating_status"] in [
        "PROVISIONING", "CERT_PENDING", "OPERATING", "SUSPENDED", "DELICENSED",
    ]
    assert data["compliance_posture"] in ["GOOD_STANDING", "WATCH", "PROBATION"]


def assert_product_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in [
        "BEVERAGE_CORE", "BEVERAGE_SEASONAL", "FOOD", "MERCHANDISE", "PROPRIETARY_INGREDIENT",
    ]
    assert isinstance(data["proprietary"], bool)
    assert isinstance(data["venue_type_restrictions"], list)
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 1
    assert isinstance(data["case_pack_units"], int) and data["case_pack_units"] >= 1
    assert isinstance(data["footprint_units"], int) and data["footprint_units"] >= 0


def assert_store_assortment_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["product_item_id"], str)
    assert isinstance(data["par_level"], int) and 0 <= data["par_level"] <= 1000
    assert isinstance(data["on_hand"], int) and data["on_hand"] >= 0
    assert isinstance(data["active"], bool)


def assert_distributor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["approved"], bool)
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0


def assert_supply_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["distributor_id"], str)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "IN_TRANSIT",
        "RECEIVED", "DISPUTED", "CLOSED", "CANCELLED",
    ]
    assert isinstance(data["total_cost_cents"], int) and data["total_cost_cents"] >= 0
    assert isinstance(data["received_value_cents"], int) and data["received_value_cents"] >= 0
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0


def assert_supply_order_line(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["supply_order_id"], str)
    assert isinstance(data["product_item_id"], str)
    assert isinstance(data["quantity_ordered"], int) and data["quantity_ordered"] >= 1
    assert isinstance(data["quantity_received"], int) and data["quantity_received"] >= 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 1
    assert isinstance(data["discount_bps"], int) and data["discount_bps"] in (0, 500)
    assert isinstance(data["line_cost_cents"], int) and data["line_cost_cents"] >= 0


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["licensee_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_tag"] in ["BARISTA", "SHIFT_LEAD", "STORE_MANAGER"]
    assert isinstance(data["active"], bool)


def assert_certification(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert data["status"] in ["ENROLLED", "EXAM_PASSED", "CERTIFIED", "AUDIT_FAILED", "EXPIRED"]
    assert isinstance(data["exam_attempts"], int) and data["exam_attempts"] >= 0


def assert_sales_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["period_start_date"], str)
    assert isinstance(data["period_end_date"], str)
    assert isinstance(data["gross_sales_cents"], int) and data["gross_sales_cents"] >= 0
    assert isinstance(data["returns_cents"], int) and data["returns_cents"] >= 0
    assert isinstance(data["loyalty_redemption_cents"], int) and data["loyalty_redemption_cents"] >= 0
    assert data["status"] in ["DRAFT", "FINALIZED"]


def assert_royalty_statement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["period_start_date"], str)
    assert isinstance(data["period_end_date"], str)
    assert data["basis"] in ["CASH", "ACCRUAL"]
    assert isinstance(data["recognized_sales_cents"], int) and data["recognized_sales_cents"] >= 0
    assert isinstance(data["royalty_amount_cents"], int) and data["royalty_amount_cents"] >= 0
    assert data["status"] in ["DRAFT", "ISSUED", "DISPUTED", "ADJUSTED", "FINAL", "SUPERSEDED"]


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["inspector_id"], str)
    assert isinstance(data["scheduled_start_utc"], str)
    assert isinstance(data["scheduled_end_utc"], str)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]
    assert data["result"] in ["NONE", "PASSED", "FAILED"]


def assert_corrective_action(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["inspection_id"], str)
    assert isinstance(data["finding_code"], str) and data["finding_code"]
    assert isinstance(data["due_at"], str)
    assert data["status"] in ["OPEN", "SUBMITTED", "VERIFIED", "REOPENED", "ESCALATED"]
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0


def assert_loyalty_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["points_balance"], int) and data["points_balance"] >= 0
    assert isinstance(data["lifetime_earned"], int)
    assert isinstance(data["lifetime_redeemed"], int)


def assert_loyalty_account_event(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["member_id"], str)
    assert data["store_format"] in ["LICENSED", "COMPANY_OPERATED"]
    assert data["event_type"] in ["EARN", "REDEEM", "ADJUST"]
    assert isinstance(data["points"], int)


def assert_promotion_campaign(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["discount_pct"], int) and 1 <= data["discount_pct"] <= 90
    assert isinstance(data["floor_price_cents"], int) and data["floor_price_cents"] >= 1
    assert data["status"] in ["PLANNED", "ACTIVE", "ENDED", "RECONCILED", "CANCELLED"]
    assert isinstance(data["reconciled"], bool)


def assert_member_balance_invariant(member: dict):
    """points_balance == lifetime_earned - lifetime_redeemed after every event."""
    assert member["points_balance"] == member["lifetime_earned"] - member["lifetime_redeemed"], (
        f"points invariant violated: balance {member['points_balance']} != "
        f"earned {member['lifetime_earned']} - redeemed {member['lifetime_redeemed']}"
    )


def assert_order_spend_invariant(order: dict):
    """total_cost_cents == received_value_cents + credit_cents once a dispute resolves
    with a credit equal to the shortage."""
    assert order["total_cost_cents"] == order["received_value_cents"] + order["credit_cents"], (
        f"order spend invariant violated: total {order['total_cost_cents']} != "
        f"received {order['received_value_cents']} + credit {order['credit_cents']}"
    )
