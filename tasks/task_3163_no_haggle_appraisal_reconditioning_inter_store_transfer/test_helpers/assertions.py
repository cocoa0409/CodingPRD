"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

from .types import (
    StoreStatus, VehicleLifecycleStatus, VehicleHoldStatus, ConditionGrade,
    AppraisalStatus, InspectionStatus, InspectionDisposition, LineStatus,
    PricingTriggerKind, TransferRequestStatus, SaleStatus,
    FinancingApplicationStatus, ApprovalTier, OfferStatus,
    ReturnRequestStatus, AuctionLotStatus, LedgerEntryKind,
    Region, AssociateRoleKind, AssociateStatus, RepairCategory, LenderCode,
    ReturnReasonCode,
)


def _assert_common_fields(data):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_append_only_fields(data):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only resource must omit updated_at"
    assert "version" not in data, "append-only resource must omit version"


def assert_store(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["region"] in [e.value for e in Region]
    assert data["status"] in [e.value for e in StoreStatus]
    assert isinstance(data["retail_threshold_pct"], (int, float))
    assert isinstance(data["transfer_hold_days"], int)


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["credit_score"], int)
    assert 300 <= data["credit_score"] <= 850
    assert isinstance(data["stated_annual_income_cents"], int)
    assert data["stated_annual_income_cents"] >= 0


def assert_associate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert is_valid_uuid(data["store_id"])
    assert data["role_kind"] in [e.value for e in AssociateRoleKind]
    assert isinstance(data["flat_commission_cents"], int)
    assert data["status"] in [e.value for e in AssociateStatus]


def assert_vehicle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17
    assert isinstance(data["make"], str) and data["make"]
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["model_year"], int)
    assert 1990 <= data["model_year"] <= 2027
    assert isinstance(data["odometer_miles"], int)
    assert data["odometer_miles"] >= 0
    assert isinstance(data["book_value_cents"], int)
    assert data["book_value_cents"] > 0
    assert is_valid_uuid(data["current_store_id"])
    assert data["lifecycle_status"] in [e.value for e in VehicleLifecycleStatus]
    assert data["hold_status"] in [e.value for e in VehicleHoldStatus]
    assert data["condition_grade"] in [e.value for e in ConditionGrade]
    assert data["current_list_price_cents"] is None or \
        isinstance(data["current_list_price_cents"], int)
    assert is_iso8601_timestamp(data["inventory_acquired_at"])
    assert isinstance(data["days_in_inventory"], int)
    assert data["days_in_inventory"] >= 0
    assert isinstance(data["recon_cost_total_cents"], int)


def assert_appraisal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["appraiser_id"])
    assert isinstance(data["provisional_offer_cents"], int)
    assert data["provisional_offer_cents"] > 0
    assert data["final_offer_cents"] is None or \
        isinstance(data["final_offer_cents"], int)
    assert data["status"] in [e.value for e in AppraisalStatus]


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["inspector_id"])
    assert is_iso8601_timestamp(data["opened_at"])
    assert isinstance(data["estimated_repair_total_cents"], int)
    assert data["estimated_repair_total_cents"] >= 0
    assert data["disposition"] in [e.value for e in InspectionDisposition]
    assert data["status"] in [e.value for e in InspectionStatus]


def assert_line_item(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["inspection_id"])
    assert data["category"] in [e.value for e in RepairCategory]
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] > 0
    assert data["line_status"] in [e.value for e in LineStatus]


def assert_pricing_event(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["vehicle_id"])
    assert data["trigger_kind"] in [e.value for e in PricingTriggerKind]
    assert data["old_price_cents"] is None or \
        isinstance(data["old_price_cents"], int)
    assert isinstance(data["new_price_cents"], int)
    assert isinstance(data["days_in_inventory_at_event"], int)


def assert_transfer_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["from_store_id"])
    assert is_valid_uuid(data["to_store_id"])
    assert data["from_store_id"] != data["to_store_id"]
    assert isinstance(data["expedited"], bool)
    assert isinstance(data["shipping_fee_cents"], int)
    assert data["shipping_fee_cents"] > 0
    assert data["hold_expires_at"] is None or \
        is_iso8601_timestamp(data["hold_expires_at"])
    assert data["status"] in [e.value for e in TransferRequestStatus]


def assert_sale(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["associate_id"])
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["sale_price_cents"], int)
    assert data["sale_price_cents"] > 0
    assert isinstance(data["trade_in_credit_cents"], int)
    assert data["trade_in_credit_cents"] >= 0
    assert isinstance(data["amount_due_cents"], int)
    assert data["amount_due_cents"] >= 0
    assert data["amount_due_cents"] == max(
        0, data["sale_price_cents"] - data["trade_in_credit_cents"])
    assert data["status"] in [e.value for e in SaleStatus]


def assert_financing_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sale_id"])
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["requested_amount_cents"], int)
    assert data["requested_amount_cents"] >= 0
    assert data["approval_tier"] in [e.value for e in ApprovalTier]
    assert data["status"] in [e.value for e in FinancingApplicationStatus]


def assert_lender_offer(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert data["lender_code"] in [e.value for e in LenderCode]
    assert isinstance(data["apr_bps"], int) and data["apr_bps"] > 0
    assert isinstance(data["max_amount_cents"], int)
    assert data["offer_status"] in [e.value for e in OfferStatus]


def assert_return_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sale_id"])
    assert data["reason_code"] in [e.value for e in ReturnReasonCode]
    assert is_iso8601_timestamp(data["opened_at"])
    assert isinstance(data["odometer_at_return"], int)
    assert data["odometer_at_return"] >= 0
    assert data["refund_total_cents"] is None or \
        isinstance(data["refund_total_cents"], int)
    assert data["status"] in [e.value for e in ReturnRequestStatus]


def assert_auction_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["vehicle_id"])
    assert isinstance(data["reserve_price_cents"], int)
    assert data["reserve_price_cents"] > 0
    assert data["hammer_price_cents"] is None or \
        isinstance(data["hammer_price_cents"], int)
    assert isinstance(data["auction_round"], int)
    assert data["auction_round"] >= 1
    assert data["status"] in [e.value for e in AuctionLotStatus]


def assert_ledger_entry(data: dict):
    _assert_append_only_fields(data)
    assert data["entry_kind"] in [e.value for e in LedgerEntryKind]
    assert isinstance(data["amount_cents"], int)
    assert data["ref_entity"] in ("Sale", "TransferRequest", "ReturnRequest",
                                  "AuctionLot")
    assert is_valid_uuid(data["ref_id"])
    assert is_valid_uuid(data["store_id"])


def assert_ledger_entries_for(entries, ref_id, entry_kind):
    """Return all ledger entries of `entry_kind` whose ref_id matches."""
    return [e for e in entries
            if e["ref_id"] == ref_id and e["entry_kind"] == entry_kind]


def assert_vehicle_invariants(data: dict):
    """Domain invariants that must hold for any vehicle read."""
    assert data["recon_cost_total_cents"] >= 0
    if data["current_list_price_cents"] is not None:
        assert data["current_list_price_cents"] > 0
    assert data["days_in_inventory"] >= 0
