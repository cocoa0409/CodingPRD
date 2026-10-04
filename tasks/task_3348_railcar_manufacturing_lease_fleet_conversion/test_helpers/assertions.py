"""Entity assertions and domain invariant checkers.

``assert_{entity}(data)`` validates the shape and the field-level rules the PRD
states for one resource.  ``assert_{entity}_invariants(data)`` validates the
cross-field relationships that must hold after any operation.

Every monetary value in this API is an integer number of cents, so money
assertions check for a true ``int`` rather than merely a number: a decimal money
value is a contract violation, not a formatting preference.
"""

import re

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_errors import ApiErrorId  # noqa: F401  (re-exported for convenience)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ─── Field-level helpers ──────────────────────────────

def assert_common_fields(data: dict, entity: str = "resource"):
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    version = data.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"{entity}.version must be an integer, got {version!r}"
    )
    assert version >= 1, f"{entity}.version starts at 1, got {version}"


def assert_iso_date(value, field: str):
    """Business dates are ISO 8601 calendar dates."""
    assert isinstance(value, str) and _ISO_DATE_RE.match(value), (
        f"{field} must be an ISO 8601 calendar date (YYYY-MM-DD), got {value!r}"
    )


def assert_cents(value, field: str):
    """Monetary values are integer numbers of cents with no fractional part."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )
    assert_cost_precision(value)


def assert_whole_number(value, field: str):
    """Quantities, distances and durations are whole numbers in natural units."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be a whole number, got {value!r}"
    )


def assert_optional_str(value, field: str):
    assert value is None or isinstance(value, str), (
        f"{field} must be a string or null, got {value!r}"
    )


def assert_enum(value, allowed, field: str):
    assert value in allowed, f"{field} must be one of {list(allowed)}, got {value!r}"


def assert_half_open_interval(start, end, field: str = "interval"):
    """An end date is exclusive, so it must fall strictly after its start."""
    assert_iso_date(start, f"{field}.start")
    assert_iso_date(end, f"{field}.end")
    assert start < end, f"{field} must end after it starts: {start} -> {end}"


# ─── CarType ──────────────────────────────────────────

def assert_car_type(data: dict):
    assert_common_fields(data, "CarType")
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert_enum(
        data["car_class"], ("BOXCAR", "TANK", "HOPPER", "FLATCARS", "GONDOLA"),
        "CarType.car_class",
    )
    assert_whole_number(data["build_hours"], "CarType.build_hours")
    assert data["build_hours"] >= 1
    assert_whole_number(data["regulatory_life_years"], "CarType.regulatory_life_years")
    assert data["regulatory_life_years"] >= 10
    assert isinstance(data["line_count_family"], str) and data["line_count_family"]
    assert_enum(data["status"], ("ACTIVE", "RETIRED"), "CarType.status")


def assert_car_type_invariants(data: dict):
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert data["build_hours"] >= 1
    assert data["regulatory_life_years"] >= 10


# ─── Component ────────────────────────────────────────

def assert_component(data: dict):
    assert_common_fields(data, "Component")
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert_enum(
        data["component_class"], ("WHEELSET", "CASTING", "COATING"),
        "Component.component_class",
    )
    assert_cents(data["unit_cost_cents"], "Component.unit_cost_cents")
    assert data["unit_cost_cents"] >= 0
    assert_whole_number(data["lead_time_days"], "Component.lead_time_days")
    assert data["lead_time_days"] >= 0
    assert_whole_number(data["on_hand_qty"], "Component.on_hand_qty")
    assert data["on_hand_qty"] >= 0
    assert_whole_number(data["reserved_qty"], "Component.reserved_qty")
    assert data["reserved_qty"] >= 0


def assert_component_invariants(data: dict):
    """Stock relationships that must hold after any allocation event."""
    on_hand = data["on_hand_qty"]
    reserved = data["reserved_qty"]
    assert on_hand >= 0, "on_hand_qty never goes negative"
    assert reserved >= 0, "reserved_qty never goes negative"
    if "shortfall_qty" in data:
        assert data["shortfall_qty"] == max(0, reserved - on_hand), (
            "shortfall_qty is the amount by which reserved_qty exceeds on_hand_qty, "
            f"or zero: got {data['shortfall_qty']} for reserved={reserved}, "
            f"on_hand={on_hand}"
        )


# ─── CarTypeComponentRequirement ──────────────────────

def assert_car_type_component_requirement(data: dict):
    assert_common_fields(data, "CarTypeComponentRequirement")
    assert is_valid_uuid(data["car_type_id"]), "car_type_id must be a UUID"
    assert is_valid_uuid(data["component_id"]), "component_id must be a UUID"
    assert_whole_number(data["qty_per_car"], "qty_per_car")
    assert data["qty_per_car"] >= 1


# ─── ProductionOrder ──────────────────────────────────

def assert_production_order(data: dict):
    assert_common_fields(data, "ProductionOrder")
    assert is_valid_uuid(data["car_type_id"]), "ProductionOrder.car_type_id"
    assert_whole_number(data["quantity"], "ProductionOrder.quantity")
    assert data["quantity"] >= 1
    assert_whole_number(data["completed_qty"], "ProductionOrder.completed_qty")
    assert_cents(data["unit_price_cents"], "ProductionOrder.unit_price_cents")
    assert_whole_number(data["planned_shop_days"], "ProductionOrder.planned_shop_days")
    assert_enum(data["disposition"], ("SOLD", "RETAINED"), "ProductionOrder.disposition")
    assert_whole_number(data["priority_rank"], "ProductionOrder.priority_rank")
    assert data["priority_rank"] >= 1
    assert_iso_date(data["order_date"], "ProductionOrder.order_date")
    assert_iso_date(
        data["required_delivery_date"], "ProductionOrder.required_delivery_date"
    )
    assert_enum(
        data["status"],
        ("DRAFT", "COMPONENT_RESERVED", "RELEASED", "IN_PRODUCTION",
         "COMPLETED", "CANCELLED"),
        "ProductionOrder.status",
    )
    assert_optional_str(
        data.get("supersedes_production_order_id"), "supersedes_production_order_id"
    )
    assert_optional_str(data.get("retention_reason"), "retention_reason")


def assert_production_order_invariants(data: dict):
    assert data["completed_qty"] <= data["quantity"], (
        f"completed_qty {data['completed_qty']} exceeds quantity {data['quantity']}"
    )
    assert data["unit_price_cents"] >= 0
    assert data["order_date"] <= data["required_delivery_date"]


# ─── SubstitutionEndorsement ──────────────────────────

def assert_substitution_endorsement(data: dict):
    assert_common_fields(data, "SubstitutionEndorsement")
    assert is_valid_uuid(data["production_order_id"]), "production_order_id"
    assert is_valid_uuid(data["original_component_id"]), "original_component_id"
    assert is_valid_uuid(data["substitute_component_id"]), "substitute_component_id"
    assert_whole_number(data["substitute_qty_per_car"], "substitute_qty_per_car")
    assert data["substitute_qty_per_car"] >= 1
    assert_enum(
        data["status"],
        ("PENDING", "APPROVED", "APPLIED", "REJECTED", "SUPERSEDED"),
        "SubstitutionEndorsement.status",
    )
    assert isinstance(data["decides_material"], bool), "decides_material must be boolean"


# ─── LeaseContract ────────────────────────────────────

def assert_lease_contract(data: dict):
    assert_common_fields(data, "LeaseContract")
    assert is_valid_uuid(data["lessee_id"]), "LeaseContract.lessee_id"
    assert_enum(data["lease_type"], ("FULL_SERVICE", "NET"), "lease_type")
    assert_cents(data["per_diem_rate_cents"], "per_diem_rate_cents")
    assert data["per_diem_rate_cents"] >= 0
    assert_enum(data["liability_bearer"], ("LESSOR", "LESSEE"), "liability_bearer")
    assert_half_open_interval(
        data["term_start_date"], data["term_end_date"], "LeaseContract.term"
    )
    assert_enum(
        data["status"],
        ("DRAFT", "ACTIVE", "AMENDMENT_DRAFTED", "TERMINATED", "EXPIRED"),
        "LeaseContract.status",
    )
    assert_whole_number(data["amendment_seq"], "amendment_seq")
    assert data["amendment_seq"] >= 0
    assert_cents(data["capital_allocation_cents"], "capital_allocation_cents")


def assert_lease_contract_invariants(data: dict):
    assert data["amendment_seq"] >= 0
    assert data["capital_allocation_cents"] >= 0
    assert data["per_diem_rate_cents"] >= 0
    assert data["term_end_date"] > data["term_start_date"]


# ─── Lessee ───────────────────────────────────────────

def assert_lessee(data: dict):
    assert_common_fields(data, "Lessee")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert_enum(data["credit_tier"], ("A", "B", "C", "D"), "Lessee.credit_tier")
    assert_whole_number(
        data["utilization_threshold_pct"], "utilization_threshold_pct"
    )
    assert 0 <= data["utilization_threshold_pct"] <= 100
    assert_cents(data["credit_ceiling_cents"], "credit_ceiling_cents")
    assert_cents(data["outstanding_balance_cents"], "outstanding_balance_cents")
    assert_enum(data["status"], ("ACTIVE", "SUSPENDED", "CLOSED"), "Lessee.status")


def assert_lessee_invariants(data: dict):
    """The balance is floored at zero after aggregation."""
    assert data["outstanding_balance_cents"] >= 0, (
        "outstanding_balance_cents is floored at zero"
    )
    assert 0 <= data["utilization_threshold_pct"] <= 100
    assert data["credit_ceiling_cents"] >= 0


# ─── LeaseFleetCar ────────────────────────────────────

def assert_lease_fleet_car(data: dict):
    assert_common_fields(data, "LeaseFleetCar")
    assert is_valid_uuid(data["car_type_id"]), "LeaseFleetCar.car_type_id"
    assert_optional_str(data.get("production_order_id"), "production_order_id")
    assert_optional_str(data.get("lease_contract_id"), "lease_contract_id")
    assert_cents(data["acquisition_cost_cents"], "acquisition_cost_cents")
    assert_whole_number(data["accumulated_mileage"], "accumulated_mileage")
    assert_enum(
        data["status"],
        ("HELD", "ASSIGNED", "UNDER_REPAIR", "SOLD", "SCRAPPED"),
        "LeaseFleetCar.status",
    )
    assert_iso_date(data["built_date"], "LeaseFleetCar.built_date")
    assert_iso_date(
        data["regulatory_life_end_date"], "LeaseFleetCar.regulatory_life_end_date"
    )
    assert isinstance(data["retrofit_required"], bool), "retrofit_required must be boolean"


def assert_lease_fleet_car_invariants(data: dict):
    assert data["acquisition_cost_cents"] >= 0
    assert data["accumulated_mileage"] >= 0
    assert data["regulatory_life_end_date"] > data["built_date"]


# ─── CarAssignment ────────────────────────────────────

def assert_car_assignment(data: dict):
    assert_common_fields(data, "CarAssignment")
    assert is_valid_uuid(data["lease_fleet_car_id"]), "lease_fleet_car_id"
    assert is_valid_uuid(data["lease_contract_id"]), "lease_contract_id"
    assert_half_open_interval(data["start_date"], data["end_date"], "CarAssignment")
    assert_cents(data["per_diem_rate_cents"], "per_diem_rate_cents")
    assert_whole_number(data["mileage_allowance"], "mileage_allowance")
    assert data["mileage_allowance"] >= 0
    assert_whole_number(data["mileage_used"], "mileage_used")
    assert_cents(data["per_diem_accrued_cents"], "per_diem_accrued_cents")
    assert_cents(data["mileage_charge_cents"], "mileage_charge_cents")
    assert_cents(data["maintenance_cost_cents"], "maintenance_cost_cents")
    assert_enum(
        data["status"], ("ACTIVE", "SUSPENDED", "REASSIGNED", "COMPLETED"),
        "CarAssignment.status",
    )


def assert_car_assignment_invariants(data: dict):
    assert data["mileage_used"] >= 0
    assert data["per_diem_accrued_cents"] >= 0
    assert data["mileage_charge_cents"] >= 0
    assert data["maintenance_cost_cents"] >= 0
    assert data["per_diem_rate_cents"] >= 0
    assert data["start_date"] < data["end_date"]


# ─── CarReturn ────────────────────────────────────────

def assert_car_return(data: dict):
    assert_common_fields(data, "CarReturn")
    assert is_valid_uuid(data["lease_fleet_car_id"]), "lease_fleet_car_id"
    assert is_valid_uuid(data["car_assignment_id"]), "car_assignment_id"
    assert_iso_date(data["return_date"], "CarReturn.return_date")
    assert_whole_number(data["mileage_since_last"], "mileage_since_last")
    assert data["mileage_since_last"] >= 0
    assert_enum(data["condition_grade"], ("A", "B", "C", "D"), "condition_grade")
    assert_cents(data["maintenance_parts_cents"], "maintenance_parts_cents")
    assert_cents(data["mileage_overage_cents"], "mileage_overage_cents")
    assert_enum(data["settlement_status"], ("PENDING", "SETTLED"), "settlement_status")


def assert_car_return_invariants(data: dict):
    """The parts cost is the condition grade's fixed table value."""
    from .constants import CONDITION_PARTS_CENTS

    grade = data["condition_grade"]
    assert data["maintenance_parts_cents"] == CONDITION_PARTS_CENTS[grade], (
        f"condition grade {grade} maps to "
        f"{CONDITION_PARTS_CENTS[grade]} cents, got "
        f"{data['maintenance_parts_cents']}"
    )
    assert data["mileage_overage_cents"] >= 0
    assert data["mileage_since_last"] >= 0


# ─── RetrofitProgram ──────────────────────────────────

def assert_retrofit_program(data: dict):
    assert_common_fields(data, "RetrofitProgram")
    assert isinstance(data["mandate_code"], str) and data["mandate_code"]
    assert isinstance(data["description"], str)
    assert_iso_date(data["compliance_deadline_date"], "compliance_deadline_date")
    assert_whole_number(data["required_shop_days_per_car"], "required_shop_days_per_car")
    assert data["required_shop_days_per_car"] >= 1
    assert_optional_str(data.get("required_component_id"), "required_component_id")
    assert_cents(data["program_cost_cents"], "program_cost_cents")
    assert_enum(
        data["status"], ("PLANNED", "IN_PROGRESS", "COMPLETED", "VOIDED"),
        "RetrofitProgram.status",
    )


def assert_retrofit_program_invariants(data: dict):
    assert data["program_cost_cents"] >= 0
    assert data["required_shop_days_per_car"] >= 1


# ─── RetrofitProgramCarType ───────────────────────────

def assert_retrofit_program_car_type(data: dict):
    assert_common_fields(data, "RetrofitProgramCarType")
    assert is_valid_uuid(data["retrofit_program_id"]), "retrofit_program_id"
    assert is_valid_uuid(data["car_type_id"]), "car_type_id"


# ─── RetrofitWorkOrder ────────────────────────────────

def assert_retrofit_work_order(data: dict):
    assert_common_fields(data, "RetrofitWorkOrder")
    assert is_valid_uuid(data["retrofit_program_id"]), "retrofit_program_id"
    assert is_valid_uuid(data["lease_fleet_car_id"]), "lease_fleet_car_id"
    assert isinstance(data["shop_line"], str) and data["shop_line"]
    assert_half_open_interval(
        data["scheduled_start_date"], data["scheduled_end_date"], "RetrofitWorkOrder"
    )
    assert_whole_number(data["shop_days"], "shop_days")
    assert data["shop_days"] >= 1
    assert_whole_number(data["component_qty_consumed"], "component_qty_consumed")
    assert data["component_qty_consumed"] >= 1
    assert_enum(
        data["status"], ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"),
        "RetrofitWorkOrder.status",
    )


def assert_retrofit_work_order_invariants(data: dict, required_shop_days_per_car=None):
    """The booked shop occupancy must equal the mandate's demanded occupancy."""
    assert data["shop_days"] >= 1
    assert data["component_qty_consumed"] >= 1
    if required_shop_days_per_car is not None:
        assert data["shop_days"] == required_shop_days_per_car, (
            f"shop_days {data['shop_days']} must equal the program's "
            f"required_shop_days_per_car {required_shop_days_per_car}"
        )


# ─── ComponentPurchaseOrder ───────────────────────────

def assert_component_purchase_order(data: dict):
    assert_common_fields(data, "ComponentPurchaseOrder")
    assert is_valid_uuid(data["component_id"]), "component_id"
    assert_whole_number(data["qty_ordered"], "qty_ordered")
    assert data["qty_ordered"] >= 1
    assert_cents(data["unit_cost_cents"], "unit_cost_cents")
    assert_iso_date(data["order_date"], "order_date")
    assert_iso_date(data["expected_receipt_date"], "expected_receipt_date")
    assert_enum(
        data["status"], ("PLACED", "CONFIRMED", "RECEIVED", "CANCELLED"),
        "ComponentPurchaseOrder.status",
    )


def assert_component_purchase_order_invariants(data: dict):
    assert data["qty_ordered"] >= 1
    assert data["unit_cost_cents"] >= 0
    assert data["expected_receipt_date"] >= data["order_date"]


# ─── ComponentReceipt ─────────────────────────────────

def assert_component_receipt(data: dict):
    assert_common_fields(data, "ComponentReceipt")
    assert is_valid_uuid(data["component_purchase_order_id"]), "purchase order id"
    assert is_valid_uuid(data["component_id"]), "component_id"
    assert_whole_number(data["qty_received"], "qty_received")
    assert data["qty_received"] >= 1
    assert_iso_date(data["receipt_date"], "receipt_date")


# ─── LeaseFleetSale ───────────────────────────────────

def assert_lease_fleet_sale(data: dict):
    assert_common_fields(data, "LeaseFleetSale")
    assert is_valid_uuid(data["lease_fleet_car_id"]), "lease_fleet_car_id"
    assert_optional_str(data.get("lease_contract_id"), "lease_contract_id")
    assert isinstance(data["buyer_name"], str) and data["buyer_name"]
    assert_cents(data["sale_price_cents"], "sale_price_cents")
    assert data["sale_price_cents"] >= 0
    assert_cents(data["net_book_value_cents"], "net_book_value_cents")
    assert data["net_book_value_cents"] >= 0
    assert_cents(data["writeback_liability_cents"], "writeback_liability_cents")
    assert data["writeback_liability_cents"] >= 0
    assert_iso_date(data["sale_date"], "sale_date")
    assert_enum(
        data["status"], ("PENDING_SETTLEMENT", "SETTLED", "VOIDED"),
        "LeaseFleetSale.status",
    )
    assert_cents(data["gain_loss_cents"], "gain_loss_cents")


def assert_lease_fleet_sale_invariants(data: dict):
    assert data["writeback_liability_cents"] >= 0
    assert data["net_book_value_cents"] >= 0


# ─── PortfolioLedger ──────────────────────────────────

def assert_portfolio_ledger(data: dict):
    assert_common_fields(data, "PortfolioLedger")
    assert data["status"] == "OPEN", "the portfolio ledger is always in status OPEN"
    assert_cents(data["committed_capital_cents"], "committed_capital_cents")
    assert data["committed_capital_cents"] >= 0
    assert_cents(data["realized_gain_cents"], "realized_gain_cents")
    assert_cents(data["fleet_nbv_cents"], "fleet_nbv_cents")


def assert_portfolio_ledger_reconciliation(data: dict):
    """Both bases of fleet capital and their drift are reported together."""
    for field in ("oldest_basis_cents", "newest_basis_cents", "drift_cents",
                  "committed_capital_cents", "realized_gain_cents"):
        assert_cents(data[field], field)
    assert data["newest_basis_cents"] >= 0, "each car's value is floored at zero"
    assert data["drift_cents"] == data["oldest_basis_cents"] - data["newest_basis_cents"], (
        "drift_cents is the committed basis minus the newest basis"
    )


# ─── Lessee outstanding balance read ──────────────────

def assert_lessee_outstanding_balance(data: dict):
    """The balance read exposes its components alongside the balance."""
    assert_cents(data["outstanding_balance_cents"], "outstanding_balance_cents")
    assert_cents(data["settled_charges_cents"], "settled_charges_cents")
    assert_cents(data["credits_applied_cents"], "credits_applied_cents")
    assert data["outstanding_balance_cents"] >= 0, (
        "the balance is clamped at zero"
    )


__all__ = [
    # field-level helpers
    "assert_common_fields", "assert_iso_date", "assert_cents",
    "assert_whole_number", "assert_optional_str", "assert_enum",
    "assert_half_open_interval",
    # per-entity shape assertions
    "assert_car_type", "assert_component",
    "assert_car_type_component_requirement", "assert_production_order",
    "assert_substitution_endorsement", "assert_lease_contract", "assert_lessee",
    "assert_lease_fleet_car", "assert_car_assignment", "assert_car_return",
    "assert_retrofit_program", "assert_retrofit_program_car_type",
    "assert_retrofit_work_order", "assert_component_purchase_order",
    "assert_component_receipt", "assert_lease_fleet_sale", "assert_portfolio_ledger",
    # domain invariant checkers
    "assert_car_type_invariants", "assert_component_invariants",
    "assert_production_order_invariants", "assert_lease_contract_invariants",
    "assert_lessee_invariants", "assert_lease_fleet_car_invariants",
    "assert_car_assignment_invariants", "assert_car_return_invariants",
    "assert_retrofit_program_invariants", "assert_retrofit_work_order_invariants",
    "assert_component_purchase_order_invariants", "assert_lease_fleet_sale_invariants",
    "assert_portfolio_ledger_reconciliation", "assert_lessee_outstanding_balance",
]
