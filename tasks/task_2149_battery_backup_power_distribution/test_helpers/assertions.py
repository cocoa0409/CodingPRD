"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ACCOUNT_TIERS = ["PLATINUM", "GOLD", "STANDARD"]
CHEMISTRIES = [
    "FLOODED_LEAD_ACID", "AGM", "GEL", "LITHIUM_IRON_PHOSPHATE", "NICKEL_CADMIUM",
]
HAZMAT_CLASSES = [
    "NON_REGULATED", "UN2800_EXCEPTED", "UN2795", "UN2800", "UN2794",
    "UN3480_SECTION_II", "UN3480_SECTION_IA",
]


def assert_common_fields(data: dict):
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer starting at 1, got {data.get('version')}"


def assert_account(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["account_tier"] in ACCOUNT_TIERS
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert 1 <= data["storm_priority_rank"] <= 9
    assert data["credit_limit_cents"] >= 0
    assert data["status"] in ["ACTIVE", "CREDIT_HOLD"]
    assert data["core_deposit_balance_cents"] >= 0, \
        "core-deposit liability is floored at 0"
    assert data["warranty_credit_cents"] >= 0


def assert_battery_model(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["chemistry"] in CHEMISTRIES
    assert data["nominal_voltage"] > 0
    assert data["amp_hour_capacity"] > 0
    assert 1.0 <= data["peukert_exponent"] <= 1.5
    assert data["unit_weight_kg"] > 0
    assert data["lead_content_kg"] >= 0
    assert data["core_deposit_cents"] >= 0
    assert data["list_price_cents"] > 0
    assert data["hazmat_class_code"] in HAZMAT_CLASSES
    assert 0 <= data["hazmat_severity_rank"] <= 6
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]


def assert_warehouse(data: dict):
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert len(data["state_code"]) == 2
    assert isinstance(data["hazmat_endorsement"], bool)
    assert 0.0 <= data["storm_reserve_pct"] <= 0.5
    assert data["dock_capacity_kg_per_window"] > 0


def assert_carrier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["accepts_hazmat_classes"], list)
    for cls in data["accepts_hazmat_classes"]:
        assert cls in HAZMAT_CLASSES
    assert data["max_lithium_watt_hours_per_package"] >= 0
    assert isinstance(data["ground_only"], bool)


def assert_inventory_lot(data: dict):
    assert_common_fields(data)
    assert data["quantity_on_hand"] >= 0
    assert data["quantity_reserved"] >= 0
    assert data["condition_state"] in [
        "SELLABLE", "REFRESH_REQUIRED", "SHELF_EXPIRED", "SCRAPPED",
    ]
    assert 0.0 <= data["state_of_charge_pct"] <= 100.0, \
        "state of charge is floored at 0.0 and never exceeds 100.0"


def assert_order(data: dict):
    assert_common_fields(data)
    assert data["fulfillment_status"] in [
        "DRAFT", "SUBMITTED", "ALLOCATED", "SHIPPED", "DELIVERED", "CANCELLED",
    ]
    assert data["credit_status"] in ["PENDING", "CLEARED", "HELD", "CLOSED"]
    assert isinstance(data["hazmat_fee_waived"], bool)
    assert data["total_cents"] == (
        data["subtotal_cents"] + data["core_deposit_charge_cents"]
        + data["hazmat_fee_cents"] + data["service_contract_fee_cents"]
    ), "total_cents is the subtotal plus core deposit plus hazmat fee plus contract fee"


def assert_order_line(data: dict):
    assert_common_fields(data)
    assert data["quantity"] >= 1
    assert 0 <= data["core_expected_count"] <= data["quantity"]
    assert 0.0 <= data["discount_pct"] <= 0.15, "the combined discount is capped at 15 percent"


def assert_shipment(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "PACKED", "CERTIFIED", "HAZMAT_REJECTED", "DISPATCHED", "DELIVERED", "VOIDED",
    ]
    assert data["hazmat_class_code"] in HAZMAT_CLASSES
    assert data["total_weight_kg"] >= 0
    assert data["package_count"] >= 0


def assert_core_return(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SUBMITTED", "INSPECTED", "DISPUTED", "REJECTED", "CREDITED"]
    assert data["declared_core_count"] >= 1
    assert 0 <= data["accepted_core_count"] <= data["declared_core_count"]
    assert 0 <= data["inspection_round"] <= 3


def assert_warranty_claim(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "SUBMITTED", "APPROVED_FREE", "APPROVED_PRORATA", "DENIED", "SETTLED",
    ]
    assert data["months_in_service"] >= 0
    assert data["credit_cents"] >= 0


def assert_service_contract(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "SIZED", "ATTACHED", "ACTIVE", "SUPERSEDED", "CANCELLED",
    ]
    assert data["coverage_tier"] in ["BRONZE", "SILVER", "GOLD"]
    assert isinstance(data["allowed_chemistries"], list) and data["allowed_chemistries"]


def assert_storm_event(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DECLARED", "ALLOCATING", "CLOSED"]
    assert data["severity_tier"] in ["WATCH", "WARNING", "EMERGENCY"]
    assert data["remaining_pool_units"] == (
        data["allocation_pool_units"] - data["allocated_units"]
    ), "remaining pool is the declared pool less the units drawn"


def assert_disposal_manifest(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "FILED"]
    assert data["total_lead_kg"] <= 1000.000, \
        "a manifest's total_lead_kg may never exceed 1000.000 kilograms"
    assert data["attached_core_return_count"] >= 0
    assert data["scrapped_lot_count"] >= 0


def assert_lead_mass_precision(value: float):
    """Lead mass in kilograms carries 3 decimal places."""
    assert round(float(value), 3) == float(value), \
        f"lead mass must carry 3 decimals, got {value}"


def assert_whole_cents(value):
    assert isinstance(value, int), f"monetary quantities are whole cents, got {value!r}"
