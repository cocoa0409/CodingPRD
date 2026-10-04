"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

APPEND_ONLY_ENTITIES = {"OrderFeeLedgerEntry"}


def _assert_common(data: dict, entity_name: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_name}.created_at must be ISO 8601"
    if entity_name in APPEND_ONLY_ENTITIES:
        assert "updated_at" not in data, \
            f"{entity_name} is append-only and must not expose updated_at"
        assert "version" not in data, \
            f"{entity_name} is append-only and must not expose version"
        return
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity_name}.version must be an int"


# ─── Buyer ───────────────────────────────────────────
def assert_buyer(data: dict):
    _assert_common(data, "Buyer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["residency_state_code"], str) and len(data["residency_state_code"]) == 2
    assert data["credit_band"] in ["UNRATED", "PRIME", "NEAR_PRIME", "SUBPRIME"]
    assert isinstance(data["order_credit_balance_cents"], int)
    assert isinstance(data["identity_verified"], bool)
    assert data["status"] in ["PENDING_VERIFICATION", "ACTIVE", "SUSPENDED"]


# ─── StateJurisdiction ───────────────────────────────
def assert_jurisdiction(data: dict):
    _assert_common(data, "StateJurisdiction")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["direct_sales_permitted"], bool)
    assert isinstance(data["gallery_only_required"], bool)
    assert isinstance(data["out_of_state_delivery_required"], bool)
    assert isinstance(data["cooling_off_days"], int)
    assert isinstance(data["doc_fee_cap_cents"], int)
    assert isinstance(data["mobile_service_permitted"], bool)
    assert isinstance(data["delivery_buffer_minutes"], int)
    assert isinstance(data["allocation_window_days"], int)
    assert isinstance(data["transport_lead_days"], int)
    assert data["status"] in ["DRAFT", "ENACTED", "REPEALED"]


# ─── VehicleConfiguration & ConfigurationOption ──────
def assert_configuration(data: dict):
    _assert_common(data, "VehicleConfiguration")
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["configured_price_cents"], int)
    assert isinstance(data["option_count"], int)
    assert data["status"] in ["DRAFT", "PUBLISHED", "RETIRED"]


def assert_option(data: dict):
    _assert_common(data, "ConfigurationOption")
    assert isinstance(data["option_sku"], str) and data["option_sku"]
    assert data["option_category"] in ["PAINT", "WHEELS", "INTERIOR", "SOFTWARE_FEATURE", "TOWING"]
    assert isinstance(data["is_software_entitlement"], bool)
    assert isinstance(data["price_cents"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]


# ─── VehicleOrder ────────────────────────────────────
def assert_order(data: dict):
    _assert_common(data, "VehicleOrder")
    assert is_valid_uuid(data["buyer_id"])
    assert is_valid_uuid(data["configuration_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert is_valid_uuid(data["delivery_center_id"])
    assert isinstance(data["order_fee_cents"], int)
    assert isinstance(data["order_fee_paid_cents"], int)
    assert isinstance(data["order_total_due_cents"], int)
    assert data["delivery_readiness_posture"] in ["READY", "RESTRICTED", "FROZEN"]
    assert isinstance(data["estimate_shift_days_cumulative"], int)
    assert isinstance(data["issue_note_count"], int)
    assert data["status"] in [
        "DRAFT", "PLACED", "CONFIG_LOCKED", "ALLOCATED", "IN_TRANSIT",
        "AT_DELIVERY_CENTER", "DELIVERY_SCHEDULED", "DELIVERED", "CANCELLED",
    ]


def assert_order_invariants(data: dict):
    """Domain invariants that must hold after any operation on an order."""
    assert data["order_fee_paid_cents"] >= 0
    assert data["order_total_due_cents"] >= 0
    assert data["issue_note_count"] >= 0


# ─── OrderFeeLedgerEntry (append-only) ───────────────
def assert_ledger_entry(data: dict):
    _assert_common(data, "OrderFeeLedgerEntry")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["buyer_id"])
    assert data["entry_type"] in [
        "ORDER_FEE_PAYMENT", "ORDER_FEE_REFUND", "TRADE_IN_CREDIT",
        "TRADE_IN_CREDIT_REVERSAL", "DELIVERY_FEE_CHARGE", "DELIVERY_FEE_WAIVER",
    ]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["reason_code"], str)


# ─── TradeInAppraisal ────────────────────────────────
def assert_appraisal(data: dict):
    _assert_common(data, "TradeInAppraisal")
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["trade_vin"], str) and data["trade_vin"]
    assert isinstance(data["mileage"], int)
    assert isinstance(data["gross_offer_cents"], int)
    assert isinstance(data["reconditioning_estimate_cents"], int)
    assert isinstance(data["net_credit_cents"], int)
    assert data["net_credit_cents"] >= 25000, "net credit is clamped to the 25000-cent floor"
    assert data["status"] in [
        "DRAFT", "APPRAISED", "OFFERED", "EXPIRED", "REAPPRAISED", "ACCEPTED", "REJECTED",
    ]


# ─── FinancingApplication ────────────────────────────
def assert_financing_application(data: dict):
    _assert_common(data, "FinancingApplication")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["buyer_id"])
    assert isinstance(data["term_months"], int)
    assert isinstance(data["down_payment_cents"], int)
    assert isinstance(data["include_trade_in_credit"], bool)
    assert isinstance(data["amount_financed_cents"], int)
    assert data["amount_financed_cents"] >= 0, "the financed principal is floored at 0"
    if data["credit_band"] is not None:
        assert data["credit_band"] in ["PRIME", "NEAR_PRIME", "SUBPRIME"]
    assert data["status"] in [
        "SUBMITTED", "CONDITIONALLY_APPROVED", "CONTRACT_PENDING", "FUNDED", "DECLINED",
    ]


# ─── ProductionBatch & AllocationUnit ────────────────
def assert_batch(data: dict):
    _assert_common(data, "ProductionBatch")
    assert isinstance(data["factory_code"], str) and data["factory_code"]
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["unit_capacity"], int)
    assert isinstance(data["allocated_unit_count"], int)
    assert isinstance(data["unallocated_unit_count"], int)
    assert data["unallocated_unit_count"] == data["unit_capacity"] - data["allocated_unit_count"], \
        "allocated and unallocated unit counts must be conserved"
    assert isinstance(data["delay_days"], int)
    assert data["status"] in ["SCHEDULED", "IN_PRODUCTION", "DELAYED", "COMPLETED"]


def assert_allocation_unit(data: dict):
    _assert_common(data, "AllocationUnit")
    assert isinstance(data["vin"], str) and data["vin"]
    assert data["status"] in ["UNASSIGNED", "ALLOCATED", "IN_TRANSIT", "ARRIVED", "RELEASED"]


# ─── DeliveryEstimate ────────────────────────────────
def assert_delivery_estimate(data: dict):
    _assert_common(data, "DeliveryEstimate")
    assert is_valid_uuid(data["order_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["estimate_state"] in ["PROVISIONAL", "FIRM", "SUPERSEDED", "CONSUMED"]
    assert data["notification_state"] in [
        "UNNOTIFIED", "NOTIFIED", "ACKNOWLEDGED", "ESCALATED",
    ]
    assert isinstance(data["shift_days"], int)
    assert data["shift_days"] >= 0, "shift_days is floored at 0"


# ─── DeliveryCenter ──────────────────────────────────
def assert_delivery_center(data: dict):
    _assert_common(data, "DeliveryCenter")
    assert isinstance(data["center_name"], str) and data["center_name"]
    assert data["center_kind"] in ["DELIVERY_CENTER", "GALLERY", "SERVICE_CENTER", "PARTS_HUB"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["home_delivery_radius_miles"], int)
    assert isinstance(data["bay_count"], int)
    assert isinstance(data["booked_slot_count"], int)
    assert data["booked_slot_count"] >= 0
    assert isinstance(data["van_count"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "RETIRED"]


# ─── DeliveryAppointment ─────────────────────────────
def assert_delivery_appointment(data: dict):
    _assert_common(data, "DeliveryAppointment")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["delivery_center_id"])
    assert data["delivery_mode"] in ["CENTER", "HOME"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["buffer_minutes"], int)
    assert data["acceptance_inspection_result"] in [
        "NOT_PERFORMED", "CLEAN", "ISSUES_DOCUMENTED",
    ]
    assert isinstance(data["documented_issue_count"], int)
    assert data["status"] in ["BOOKED", "CONFIRMED", "AT_RISK", "COMPLETED", "CANCELLED"]


# ─── Vehicle ─────────────────────────────────────────
def assert_vehicle(data: dict):
    _assert_common(data, "Vehicle")
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["vin"], str) and data["vin"]
    assert isinstance(data["odometer_miles"], int)
    assert isinstance(data["software_version"], str)
    assert data["service_hold_state"] in ["NONE", "PARTS_HOLD", "AWAITING_PARTS_SHIPMENT"]
    assert data["status"] in ["IN_SERVICE", "SERVICE_HOLD", "RETIRED"]


# ─── RemoteDiagnosticReport ──────────────────────────
def assert_diagnostic_report(data: dict):
    _assert_common(data, "RemoteDiagnosticReport")
    assert is_valid_uuid(data["vehicle_id"])
    assert isinstance(data["fault_code"], str) and data["fault_code"]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert isinstance(data["is_driveable"], bool)
    assert data["triage_outcome"] in [
        "PENDING", "MOBILE_REQUIRED", "CENTER_REQUIRED", "OTA_RESOLVABLE", "NO_ACTION",
    ]
    assert isinstance(data["parts_required"], bool)
    assert is_iso8601_timestamp(data["reported_at"])


# ─── ServiceAppointment ──────────────────────────────
def assert_service_appointment(data: dict):
    _assert_common(data, "ServiceAppointment")
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["diagnostic_report_id"])
    assert is_valid_uuid(data["service_center_id"])
    assert isinstance(data["is_warranty_covered"], bool)
    assert data["status"] in [
        "TRIAGED", "CENTER_SCHEDULED", "MOBILE_DISPATCHED", "COMPLETED", "CANCELLED",
    ]


# ─── MobileServiceVisit ──────────────────────────────
def assert_mobile_visit(data: dict):
    _assert_common(data, "MobileServiceVisit")
    assert is_valid_uuid(data["service_appointment_id"])
    assert is_valid_uuid(data["parts_hub_id"])
    assert isinstance(data["van_code"], str) and data["van_code"]
    assert isinstance(data["labor_hours"], (int, float))
    assert isinstance(data["parts_cost_cents"], int)
    assert isinstance(data["visit_cost_cents"], int)
    assert data["visit_cost_cents"] >= 0
    assert data["status"] in [
        "DRAFT", "PARTS_RESERVED", "PARTS_SHIPPED", "EN_ROUTE", "IN_PROGRESS",
        "COMPLETED", "RESCHEDULED", "CANCELLED",
    ]


# ─── SoftwareEntitlement ─────────────────────────────
def assert_entitlement(data: dict):
    _assert_common(data, "SoftwareEntitlement")
    assert is_valid_uuid(data["vehicle_id"])
    assert isinstance(data["feature_code"], str) and data["feature_code"]
    assert data["entitlement_source"] in ["FACTORY_OPTION", "PURCHASE", "TRIAL", "TRANSFER"]
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["bundle_discount_bps"], int)
    assert isinstance(data["payable_cents"], int)
    assert isinstance(data["bundle_net_cents"], int)
    assert data["status"] in ["ACTIVE", "EXPIRED", "REVOKED"]


def assert_entitlement_bundle_invariants(rows: list):
    """Every row created by one bundle request carries the same bundle_net_cents,
    and the per-row shares reconcile to that total exactly."""
    assert rows, "a bundle request must return at least one row"
    nets = {row["bundle_net_cents"] for row in rows}
    assert len(nets) == 1, f"bundle_net_cents must be identical on every row, got {nets}"
    total = sum(row["payable_cents"] for row in rows)
    assert total == rows[0]["bundle_net_cents"], (
        f"per-row shares {total} must reconcile to bundle_net_cents "
        f"{rows[0]['bundle_net_cents']}"
    )


# ─── VehicleIssueNote ────────────────────────────────
def assert_issue_note(data: dict):
    _assert_common(data, "VehicleIssueNote")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert isinstance(data["issue_code"], str) and data["issue_code"]
    assert isinstance(data["observed_mileage"], int)
    assert isinstance(data["blocked_handover"], bool)
    assert data["status"] in ["OPEN", "RESOLVED", "WAIVED"]


# ─── Cross-entity invariants ─────────────────────────
def assert_ledger_conservation(buyer: dict, entries: list):
    """The buyer's order credit balance is the sum of amount_cents over every
    entry whose buyer_id is that buyer."""
    total = sum(e["amount_cents"] for e in entries)
    assert buyer["order_credit_balance_cents"] == total, (
        f"order_credit_balance_cents {buyer['order_credit_balance_cents']} must equal "
        f"the ledger sum {total}"
    )


__all__ = [name for name in dir() if not name.startswith("_")]