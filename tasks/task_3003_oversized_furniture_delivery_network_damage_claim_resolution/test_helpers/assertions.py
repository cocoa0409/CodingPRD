"""Entity assertions and domain invariant checkers for the
Oversize Freight Network API."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

from .types import (
    SupplierStatus,
    ItemStatus,
    FreightClass,
    HubStatus,
    ServiceLevel,
    OrderState,
    FulfillmentState,
    LegMode,
    FulfillmentMode,
    ShipmentState,
    LinehaulStatus,
    AppointmentStatus,
    ClaimantRole,
    Concealment,
    ResolutionType,
    LiabilityParty,
    DamageClaimStatus,
    ChargebackStatus,
    ChargebackReasonCode,
    ReturnReason,
    ReturnDisposition,
    ReturnAuthorizationStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer >= 1"
    )


def assert_supplier(data: dict):
    _assert_common(data)
    assert isinstance(data["supplier_code"], str) and data["supplier_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["drop_ship_enabled"], bool)
    assert isinstance(data["lead_time_days"], int)
    assert isinstance(data["compliance_score"], (int, float))
    assert isinstance(data["on_time_ship_rate"], (int, float))
    assert isinstance(data["chargeback_rate"], (int, float))
    assert data["status"] in [s.value for s in SupplierStatus]


def assert_item(data: dict):
    _assert_common(data)
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["dim_length_in"] > 0
    assert data["dim_width_in"] > 0
    assert data["dim_height_in"] > 0
    assert data["weight_lb"] > 0
    assert isinstance(data["declared_value_cents"], int)
    assert isinstance(data["white_glove_eligible"], bool)
    assert isinstance(data["cube_score"], (int, float))
    assert data["freight_class"] in [c.value for c in FreightClass]
    assert isinstance(data["declared_girth_in"], int)
    assert isinstance(data["parcel_ok"], bool)
    assert data["status"] in [s.value for s in ItemStatus]


def assert_hub(data: dict):
    _assert_common(data)
    assert isinstance(data["hub_code"], str) and data["hub_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["serves_zones"], list)
    assert isinstance(data["white_glove_capable"], bool)
    assert isinstance(data["daily_capacity"], int)
    assert data["status"] in [s.value for s in HubStatus]


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["destination_zone"], str) and data["destination_zone"]


def assert_order(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["item_id"], str)
    assert data["service_level"] in [s.value for s in ServiceLevel]
    assert isinstance(data["shipping_amount_cents"], int)
    assert isinstance(data["oversized_surcharge_cents"], int)
    assert isinstance(data["handling_fee_cents"], int)
    assert isinstance(data["order_total_cents"], int)
    assert data["order_state"] in [s.value for s in OrderState]
    assert data["fulfillment_state"] in [s.value for s in FulfillmentState]


def assert_freight_lane(data: dict):
    _assert_common(data)
    assert data["leg_mode"] in [m.value for m in LegMode]
    assert isinstance(data["dest_zone"], str) and data["dest_zone"]
    assert isinstance(data["base_rate_cents"], int)
    assert isinstance(data["per_lb_rate_cents"], int)
    assert isinstance(data["transit_days"], int) and data["transit_days"] >= 1
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_shipment(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["item_id"], str)
    assert isinstance(data["supplier_id"], str)
    assert data["fulfillment_mode"] in [m.value for m in FulfillmentMode]
    assert data["leg_mode"] in [m.value for m in LegMode]
    assert isinstance(data["linehaul_misses"], int) and data["linehaul_misses"] >= 0
    assert data["current_state"] in [s.value for s in ShipmentState]


def assert_linehaul(data: dict):
    _assert_common(data)
    assert isinstance(data["hub_id"], str)
    assert isinstance(data["planned_arrival_date"], str)
    assert isinstance(data["origin_ship_date"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["committed_count"], int) and data["committed_count"] >= 0
    assert data["committed_count"] <= data["capacity"], (
        "committed_count must never exceed capacity"
    )
    assert data["status"] in [s.value for s in LinehaulStatus]


def assert_delivery_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["shipment_id"], str)
    assert data["service_level"] in [s.value for s in ServiceLevel]
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert isinstance(data["hub_id"], str)
    assert isinstance(data["crew_id"], str) and data["crew_id"]
    assert data["status"] in [s.value for s in AppointmentStatus]


def assert_damage_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["shipment_id"], str)
    assert data["claimant_role"] in [r.value for r in ClaimantRole]
    assert data["concealment"] in [c.value for c in Concealment]
    assert isinstance(data["replacement_cost_cents"], int)
    assert isinstance(data["chargeback_amount_cents"], int)
    assert data["status"] in [s.value for s in DamageClaimStatus]


def assert_chargeback(data: dict):
    _assert_common(data)
    assert isinstance(data["damage_claim_id"], str)
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["shipment_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["reason_code"] in [r.value for r in ChargebackReasonCode]
    assert data["status"] in [s.value for s in ChargebackStatus]


def assert_return_authorization(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert data["reason"] in [r.value for r in ReturnReason]
    assert data["status"] in [s.value for s in ReturnAuthorizationStatus]


def assert_supplier_metrics_invariants(data: dict):
    """Supplier metric invariants that must hold after any operation."""
    assert 0.00 <= data["chargeback_rate"] <= 100.00, (
        "chargeback_rate is a percentage"
    )
    assert 0.00 <= data["on_time_ship_rate"] <= 100.00, (
        "on_time_ship_rate is a percentage"
    )
    assert 0.00 <= data["compliance_score"] <= 100.00, (
        "compliance_score is a weighted blend of two percentages"
    )
