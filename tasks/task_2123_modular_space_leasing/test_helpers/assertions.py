"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssessmentStatus,
    BillingStatus,
    BranchStatus,
    ComplianceStatus,
    ConditionGrade,
    ConfigurationStatus,
    CreditTier,
    JobStatus,
    JobType,
    OccupancyStatus,
    PermitStatus,
    RefurbishmentStatus,
    UnitStatus,
    YARD_STATUSES,
)


def _assert_common_fields(data: dict, label: str) -> None:
    """id / created_at / updated_at / version ride on every top-level resource."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a bare UUID, got {data.get('id')!r}")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int), (
        f"{label}.version must be an integer, got {data.get('version')!r}")


def assert_branch(data: dict) -> None:
    _assert_common_fields(data, "Branch")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["yard_capacity_units"], int)
    assert isinstance(data["daily_dispatch_capacity"], int)
    assert isinstance(data["labor_rate_cents_per_hour"], int)
    assert data["status"] in [s.value for s in BranchStatus], (
        f"Unexpected Branch.status {data['status']!r}")
    assert_branch_counters(data)


def assert_branch_counters(data: dict) -> None:
    """The three derived yard counters must stay internally consistent."""
    assert isinstance(data["units_in_yard"], int) and data["units_in_yard"] >= 0
    assert isinstance(data["units_available"], int) and data["units_available"] >= 0
    assert data["units_available"] <= data["units_in_yard"], (
        f"units_available {data['units_available']} exceeds units_in_yard "
        f"{data['units_in_yard']}")
    assert isinstance(data["utilization_pct"], (int, float))
    assert 0.0 <= float(data["utilization_pct"]) <= 100.0, (
        f"utilization_pct out of range: {data['utilization_pct']}")
    assert round(float(data["utilization_pct"]), 2) == float(data["utilization_pct"]), (
        f"utilization_pct must carry at most two decimals, "
        f"got {data['utilization_pct']}")


def assert_jurisdiction(data: dict) -> None:
    _assert_common_fields(data, "Jurisdiction")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["permit_required"], bool)
    assert isinstance(data["ada_ramp_required"], bool)
    assert isinstance(data["permit_lead_days"], int)
    assert data["wind_zone"] in (1, 2, 3, 4)
    assert data["anchoring_standard"] in (
        "NONE", "GROUND_ANCHOR", "PIER_FOUNDATION", "ENGINEERED_SLAB")
    assert float(data["min_ramp_run_ratio"]) > 0


def assert_building_spec(data: dict) -> None:
    _assert_common_fields(data, "BuildingSpec")
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert float(data["width_ft"]) > 0 and float(data["length_ft"]) > 0
    assert 1 <= int(data["sections"]) <= 4
    assert float(data["floor_height_in"]) >= 0
    for money in ("base_monthly_rate_cents", "delivery_base_cents",
                  "install_base_cents", "replacement_value_cents"):
        assert isinstance(data[money], int) and data[money] >= 0, (
            f"BuildingSpec.{money} must be a non-negative integer number of cents")
    assert int(data["max_occupancy"]) >= 1
    assert float(data["floor_area_sqft"]) == float(data["width_ft"]) * float(
        data["length_ft"]), (
        "floor_area_sqft must be width_ft * length_ft")


def assert_floorplan_configuration(data: dict) -> None:
    _assert_common_fields(data, "FloorplanConfiguration")
    assert is_valid_uuid(data["building_spec_id"])
    assert data["status"] in [s.value for s in ConfigurationStatus]
    assert isinstance(data["config_surcharge_cents"], int)
    assert data["config_surcharge_cents"] >= 0
    assert int(data["private_offices"]) >= 0
    assert int(data["restrooms"]) >= 0
    assert float(data["partition_linear_ft"]) >= 0
    assert float(data["hvac_tons"]) >= 0


def assert_unit(data: dict) -> None:
    _assert_common_fields(data, "Unit")
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert is_valid_uuid(data["building_spec_id"])
    assert is_valid_uuid(data["current_branch_id"])
    assert data["status"] in [s.value for s in UnitStatus], (
        f"Unexpected Unit.status {data['status']!r}")
    assert data["condition_grade"] in [g.value for g in ConditionGrade]
    for counter in ("lifetime_relocations", "refurb_cycles",
                    "accumulated_damage_cents", "latest_quote_estimate_cents"):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"Unit.{counter} must be a non-negative integer")
    if data["installed_config_id"] is not None:
        assert is_valid_uuid(data["installed_config_id"])


def assert_customer(data: dict) -> None:
    _assert_common_fields(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]
    assert data["credit_tier"] in [t.value for t in CreditTier]
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["credit_hold"], bool)
    assert_credit_hold_consistent(data)


def assert_credit_hold_consistent(data: dict) -> None:
    """credit_hold is true exactly when the balance is STRICTLY over the limit."""
    expected = data["outstanding_balance_cents"] > data["credit_limit_cents"]
    assert data["credit_hold"] is expected, (
        f"credit_hold {data['credit_hold']} disagrees with balance "
        f"{data['outstanding_balance_cents']} vs limit {data['credit_limit_cents']}")


def assert_lease(data: dict) -> None:
    _assert_common_fields(data, "Lease")
    for fk in ("customer_id", "unit_id", "jurisdiction_id",
               "floorplan_configuration_id"):
        assert is_valid_uuid(data[fk]), f"Lease.{fk} must be a UUID"
    assert data["occupancy_status"] in [s.value for s in OccupancyStatus], (
        f"Unexpected Lease.occupancy_status {data['occupancy_status']!r}")
    assert data["billing_status"] in [s.value for s in BillingStatus], (
        f"Unexpected Lease.billing_status {data['billing_status']!r}")
    assert data["pinned_credit_tier"] in [t.value for t in CreditTier]
    assert isinstance(data["term_months"], int) and data["term_months"] >= 1
    for money in ("monthly_base_rate_cents", "monthly_accessory_rate_cents",
                  "mobilization_fee_cents", "quoted_total_cents",
                  "relocation_surcharge_cents", "billed_to_date_cents",
                  "credited_cents"):
        assert isinstance(data[money], int), (
            f"Lease.{money} must be an integer number of cents, got {data[money]!r}")
    assert isinstance(data["assessment_round"], int)
    assert len(data["start_date"]) == 10 and data["start_date"][4] == "-"
    assert len(data["end_date"]) == 10 and data["end_date"][4] == "-"


def assert_accessory_package(data: dict) -> None:
    _assert_common_fields(data, "AccessoryPackage")
    assert is_valid_uuid(data["lease_id"])
    assert data["package_type"] in ("STEPS", "RAMP_ADA", "COMBO")
    assert float(data["ramp_run_ft"]) >= 0
    assert int(data["landing_count"]) >= 0
    assert int(data["step_count"]) >= 0
    assert isinstance(data["monthly_accessory_rate_cents"], int)
    assert data["compliance_status"] in [c.value for c in ComplianceStatus]


def assert_permit_application(data: dict) -> None:
    _assert_common_fields(data, "PermitApplication")
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert data["foundation_type"] in (
        "NONE", "GROUND_ANCHOR", "PIER_FOUNDATION", "ENGINEERED_SLAB")
    assert data["status"] in [s.value for s in PermitStatus]
    assert isinstance(data["permit_fee_cents"], int)
    assert data["permit_fee_cents"] >= 0


def assert_logistics_job(data: dict) -> None:
    _assert_common_fields(data, "LogisticsJob")
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["origin_branch_id"])
    assert data["job_type"] in [t.value for t in JobType]
    assert data["status"] in [s.value for s in JobStatus]
    assert isinstance(data["transport_cost_cents"], int)
    assert data["transport_cost_cents"] >= 0
    assert float(data["mileage_miles"]) >= 0
    assert float(data["crew_hours"]) >= 0
    if data["job_type"] == JobType.TEARDOWN_RETURN.value:
        assert is_valid_uuid(data["destination_branch_id"] or ""), (
            "a teardown-and-return job must carry destination_branch_id")
    if data["job_type"] == JobType.RELOCATION.value:
        assert data["new_site_address"], (
            "a relocation job must carry new_site_address")


def assert_damage_assessment(data: dict) -> None:
    _assert_common_fields(data, "DamageAssessment")
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["logistics_job_id"])
    assert isinstance(data["assessor_user_id"], str) and data["assessor_user_id"]
    assert data["status"] in [s.value for s in AssessmentStatus]
    assert isinstance(data["dispute_rounds"], int) and data["dispute_rounds"] >= 0
    assert data["condition_grade_before"] in [g.value for g in ConditionGrade]
    if data["condition_grade_after"] is not None:
        assert data["condition_grade_after"] in [g.value for g in ConditionGrade]
    for money in ("gross_damage_cents", "wear_allowance_cents", "chargeable_cents"):
        assert isinstance(data[money], int) and data[money] >= 0, (
            f"DamageAssessment.{money} must be a non-negative integer")


def assert_damage_line_item(data: dict) -> None:
    """A line item is append-only: only id and created_at ride along."""
    assert is_valid_uuid(data.get("id", "")), "DamageLineItem.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "DamageLineItem.created_at must be an ISO 8601 UTC timestamp")
    assert "updated_at" not in data, (
        "a damage line item has no updated_at field")
    assert "version" not in data, (
        "a damage line item has no version field")
    assert data["component"] in (
        "FLOOR", "WALL", "HVAC", "ROOF", "DOOR", "ELECTRICAL")
    assert data["severity"] in ("MINOR", "MODERATE", "SEVERE")
    assert float(data["quantity"]) > 0
    assert isinstance(data["wear_and_tear"], bool)
    assert isinstance(data["repair_cost_cents"], int)


def assert_refurbishment_order(data: dict) -> None:
    _assert_common_fields(data, "RefurbishmentOrder")
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["branch_id"])
    assert is_valid_uuid(data["damage_assessment_id"])
    assert data["scope"] in ("COSMETIC", "STANDARD", "FULL")
    assert data["status"] in [s.value for s in RefurbishmentStatus]
    assert data["target_condition_grade"] in [g.value for g in ConditionGrade]
    assert float(data["labor_hours"]) >= 0
    assert isinstance(data["parts_cost_cents"], int) and data["parts_cost_cents"] >= 0
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["estimated_cost_cents"] >= 0


# ─── Domain invariants ───────────────────────────────────────────────────────

def assert_yard_count_matches_units(branch: dict, units: list) -> None:
    """units_in_yard equals the count of this branch's on-yard units."""
    expected = len([
        u for u in units
        if u["current_branch_id"] == branch["id"] and u["status"] in YARD_STATUSES
    ])
    assert branch["units_in_yard"] == expected, (
        f"Branch.units_in_yard {branch['units_in_yard']} does not match the "
        f"{expected} on-yard units assigned to it")


def assert_available_count_matches_units(branch: dict, units: list) -> None:
    expected = len([
        u for u in units
        if u["current_branch_id"] == branch["id"]
        and u["status"] == UnitStatus.IN_FLEET.value
    ])
    assert branch["units_available"] == expected, (
        f"Branch.units_available {branch['units_available']} does not match the "
        f"{expected} IN_FLEET units assigned to it")


def assert_exposure_matches_leases(customer: dict, leases: list) -> None:
    """outstanding_balance_cents is billed minus credited over every lease."""
    expected = sum(
        lease["billed_to_date_cents"] - lease["credited_cents"]
        for lease in leases if lease["customer_id"] == customer["id"]
    )
    assert customer["outstanding_balance_cents"] == expected, (
        f"Customer.outstanding_balance_cents {customer['outstanding_balance_cents']} "
        f"does not match the {expected} summed over its leases")
