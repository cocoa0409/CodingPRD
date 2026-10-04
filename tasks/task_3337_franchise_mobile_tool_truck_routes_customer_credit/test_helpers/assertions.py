"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict, expect_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    if expect_version:
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            f"version must be an integer >= 1, got {data.get('version')!r}"


def assert_franchisee(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["training_status"] in ("NOT_ENROLLED", "ENROLLED", "CERTIFIED")
    assert isinstance(data["can_resell_territory"], bool)
    assert data["can_resell_territory"] == (data["training_status"] == "CERTIFIED")
    assert data["active_route_count"] >= 0
    assert data["total_route_count"] >= data["active_route_count"]
    assert data["franchisee_capital_at_risk_cents"] == (
        data["outstanding_credit_cents"] - data["recourse_exposure_cents"])


def assert_route(data: dict):
    assert_common_fields(data)
    assert data["route_status"] in ("DRAFT", "IN_SERVICE", "SUSPENDED",
                                    "PENDING_TRANSFER", "RETIRED")
    assert data["territory_development_status"] in ("UNASSIGNED", "IN_DEVELOPMENT",
                                                    "QUALIFIED", "SURRENDERED")
    assert data["resale_status"] in ("NONE", "PENDING", "APPROVED", "DECLINED")
    assert 1 <= data["visit_weekday"] <= 7
    assert isinstance(data["zip_codes"], list)
    assert data["inventory_at_risk_cents"] >= 0
    assert data["over_pledge_cents"] >= 0
    assert is_iso8601_timestamp(data["schedule_anchor_utc"])


def assert_shop(data: dict):
    assert_common_fields(data)
    assert data["shop_status"] in ("ACTIVE", "INACTIVE")
    assert data["active_technician_count"] >= 0


def assert_technician(data: dict):
    assert_common_fields(data)
    assert data["technician_status"] in ("ACTIVE", "SHOP_CHANGE_PENDING", "TRADE_EXITED")
    assert data["credit_line_status"] in ("ACTIVE", "RESTRICTED", "TERMINATED")
    assert data["revolving_used_cents"] >= 0
    assert data["revolving_available_cents"] == max(
        0, data["credit_line_limit_cents"] - data["revolving_used_cents"])
    assert data["open_account_count"] >= 0


def assert_credit_application(data: dict):
    assert_common_fields(data)
    assert data["application_status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED",
                                          "DECLINED", "WITHDRAWN")
    assert data["requested_kind"] in ("REVOLVING", "LEASE")
    assert data["decision_source"] in ("FRANCHISOR", "FRANCHISEE")
    assert 1 <= data["decision_score"] <= 100
    assert data["approved_limit_cents"] >= 0


def assert_credit_account(data: dict):
    assert_common_fields(data)
    assert data["account_status"] in ("ACTIVE", "SUSPENDED", "DELINQUENT",
                                      "CHARGED_OFF", "CLOSED")
    assert data["account_kind"] in ("REVOLVING", "LEASE")
    assert data["recourse_holder"] in ("FRANCHISEE", "FRANCHISOR")
    assert data["is_revolving_program"] != data["is_lease_program"]
    assert data["use_final_basis"] == data["is_lease_program"]
    assert is_iso8601_timestamp(data["account_status_changed_at"])
    assert data["credit_available_cents"] == max(
        0, data["credit_limit_cents"] - data["current_balance_cents"])
    assert data["current_balance_cents"] == (data["principal_balance_cents"]
                                             + data["accrued_finance_charge_cents"])


def assert_finance_charge(data: dict):
    assert_common_fields(data)
    assert is_iso8601_timestamp(data["accrual_iso_week"])
    assert data["accrual_seq"] >= 1
    assert data["charge_status"] in ("OPEN", "CLOSED")
    assert data["collection_applied_cents"] <= data["charge_amount_cents"]
    if data["charge_status"] == "CLOSED":
        assert data["collection_applied_cents"] == data["charge_amount_cents"]


def assert_payment(data: dict):
    assert_common_fields(data)
    assert data["payment_status"] in ("BOOKED", "COLLECTED", "MISSED",
                                      "CANCELLED", "REVERSED")
    assert data["amount_cents"] > 0
    assert data["collection_source"] in ("TRUCK_COLLECTION", "FRANCHISOR_DRAFT",
                                         "SETTLEMENT_APPLIED")


def assert_sales_order(data: dict):
    assert_common_fields(data)
    assert data["order_status"] in ("DRAFT", "CONFIRMED", "DELIVERED", "SETTLED",
                                    "CANCELLED")
    assert data["mix_profile"] in ("DIAGNOSTIC_WEIGHTED", "TOOL_STORAGE", "POWER_TOOLS")
    assert data["line_count"] == len(data["lines"])
    assert data["gross_total_cents"] >= 0
    assert is_iso8601_timestamp(data["sale_iso_week"])


def assert_warranty_claim(data: dict):
    assert_common_fields(data)
    assert data["claim_status"] in ("OPEN", "SUBMITTED", "APPROVED", "REJECTED")
    assert data["claim_kind"] in ("WARRANTY_REPLACEMENT", "CLAIM")
    assert is_iso8601_timestamp(data["filed_iso_week"])
    assert data["replacement_charge_cents"] >= 0
    assert data["warranty_credit_amount_cents"] >= 0
    assert data["principal_allocated_cents"] >= 0


def assert_product(data: dict):
    assert_common_fields(data)
    assert data["category"] in ("DIAGNOSTICS", "TOOL_STORAGE", "POWER_TOOLS")
    assert data["launch_status"] in ("ANNOUNCED", "ALLOCATED", "LIVE")
    assert data["unit_cost_cents"] >= 0
    assert data["retail_price_cents"] >= 0


def assert_inventory_position(data: dict):
    assert_common_fields(data)
    assert data["on_hand_qty"] >= 0
    assert data["reserved_qty"] >= 0
    assert data["remaining_qty"] == data["on_hand_qty"] - data["reserved_qty"]
    assert data["unit_cost_cents"] >= 0


def assert_product_order(data: dict):
    assert_common_fields(data)
    assert data["product_order_status"] in ("DRAFT", "SUBMITTED", "SHIPPED",
                                            "RECEIVED", "ALLOCATED", "CANCELLED")
    assert data["ordered_cost_cents"] <= data["investment_ceiling_cents"]
    assert isinstance(data["is_fully_covered"], bool)
    assert isinstance(data["ordered_lines"], list)
    assert isinstance(data["deferred_lines"], list)


def assert_share_pledge(data: dict):
    assert_common_fields(data)
    assert data["pledge_status"] in ("HELD", "BOUND", "RELEASED", "CONSUMED")
    assert data["sustained_amount_cents"] >= 0


def assert_launch_allocation(data: dict):
    assert_common_fields(data)
    assert data["allocation_status"] in ("PLANNED", "ALLOCATED", "REALLOCATED",
                                         "REVIEW")
    assert data["launch_risk_band"] in ("LOW", "MEDIUM", "HIGH")
    assert data["allocated_qty"] >= 0
    assert data["allocated_amount_cents"] >= 0


def assert_route_inventory_invariants(route: dict, positions: list):
    """Route-level aggregates reconcile with the underlying positions."""
    risk = sum(p["reserved_qty"] * p["unit_cost_cents"] for p in positions)
    over = sum(max(0, p["reserved_qty"] - p["on_hand_qty"]) * p["unit_cost_cents"]
               for p in positions)
    assert route["inventory_at_risk_cents"] == risk, (
        f"inventory_at_risk_cents {route['inventory_at_risk_cents']} != {risk}")
    assert route["over_pledge_cents"] == over, (
        f"over_pledge_cents {route['over_pledge_cents']} != {over}")
