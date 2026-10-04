"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Computed financial fields that the PRD defers to a
later lifecycle point (lease economics at approve, claim adjudication figures
at APPROVED/PARTIAL_APPROVED, irrigation design fields at DESIGN_SUBMITTED)
are checked only when present, so a correctly minimal serializer never fails.
"""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AppraisalStatus,
    CertStatus,
    DistributorStatus,
    FleetLeaseStatus,
    GolfCourseStatus,
    IrrigationProjectStatus,
    LeaseUnitStatus,
    ModelLifecycleStatus,
    PartsOrderStatus,
    PartSupportStatus,
    WarrantyClaimStatus,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_distributor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["territory_codes"], list)
    assert data["channel"] in ("EQUIPMENT", "IRRIGATION")
    assert isinstance(data["min_parts_stock_value_cents"], int)
    assert isinstance(data["labor_rate_cents"], int)
    assert isinstance(data["annual_claim_cap_cents"], int)
    assert data["status"] in {s.value for s in DistributorStatus}
    # Computed compliance counters (PRD §3.1) are carried on distributor reads.
    assert isinstance(data["fill_rate"], (int, float))
    assert isinstance(data["stock_value_trailing_cents"], int)
    assert isinstance(data["committed_parts_cents"], int)
    assert isinstance(data["service_credit_balance_cents"], int)
    assert isinstance(data["claims_paid_ytd_cents"], int)


def assert_technician(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("distributor_id", "")), "distributor_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["cert_status"] in {s.value for s in CertStatus}
    # cert_level / cert_expires_at are null until the first certification.
    if data.get("cert_level") is not None:
        assert data["cert_level"] in ("APPRENTICE", "JOURNEYMAN", "MASTER")
    if data.get("cert_expires_at") is not None:
        assert is_iso8601_timestamp(data["cert_expires_at"])


def assert_course(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["turf_profile"] in ("BENTGRASS", "BERMUDA", "POA_ANNUA", "MIXED")
    assert data["cut_quality_standard"] in ("CHAMPIONSHIP", "CLUB", "MAINTENANCE")
    assert isinstance(data["credit_limit_cents"], int)
    assert is_valid_uuid(data.get("assigned_distributor_id", ""))
    assert data["status"] in {s.value for s in GolfCourseStatus}


def assert_model(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert data["category"] in ("MOWER", "UTILITY_VEHICLE", "AERATOR", "IRRIGATION_CONTROLLER")
    assert data["tier"] in ("TOURNAMENT", "PRO", "STANDARD")
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["eligible_turf_types"], list)
    assert isinstance(data["factory_warranty_months"], int)
    assert isinstance(data["warranty_labor_hourly_cap_cents"], int)
    assert isinstance(data["parts_support_years"], int)
    assert data["lifecycle_status"] in {s.value for s in ModelLifecycleStatus}


def assert_part(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data.get("primary_model_id", ""))
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["min_stock_qty"], int)
    assert data["support_status"] in {s.value for s in PartSupportStatus}
    # superseded_by_part_id is null until the part is SUPERSEDED.
    if data.get("superseded_by_part_id") is not None:
        assert is_valid_uuid(data["superseded_by_part_id"])


def assert_parts_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("distributor_id", ""))
    assert data["order_type"] in ("STOCK", "CUSTOMER")
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert is_valid_uuid(line.get("part_id", "")), "line part_id must be a UUID"
        assert isinstance(line.get("qty"), int) and line["qty"] >= 1
    assert data["status"] in {s.value for s in PartsOrderStatus}
    # subtotal_cents and ordered_units are computed at creation.
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["ordered_units"], int)
    assert isinstance(data["received_units"], int)
    # Incentive fields are deferred to submit; present from create with 0/False.
    assert data["off_season_applied"] in (True, False)
    if "discount_tier_pct" in data:
        assert isinstance(data["discount_tier_pct"], (int, float))
    if "discount_cents" in data and data["discount_cents"] is not None:
        assert_cost_precision(data["discount_cents"])
    if "total_cents" in data and data["total_cents"] is not None:
        assert_cost_precision(data["total_cents"])


def assert_lease(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("course_id", ""))
    assert is_valid_uuid(data.get("distributor_id", ""))
    assert isinstance(data["cycle_months"], int) and data["cycle_months"] >= 1
    assert isinstance(data["start_date"], str) and len(data["start_date"]) == 10
    assert isinstance(data["end_date"], str) and len(data["end_date"]) == 10
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert is_valid_uuid(line.get("model_id", "")), "line model_id must be a UUID"
        assert isinstance(line.get("qty"), int) and line["qty"] >= 1
    assert data["status"] in {s.value for s in FleetLeaseStatus}
    # Financials are computed at approve; null/absent until then.
    for field in (
        "base_value_cents",
        "total_contract_value_cents",
        "trade_in_credit_cents",
        "net_contract_value_cents",
        "monthly_rate_cents",
        "billed_to_date_cents",
        "remaining_balance_cents",
    ):
        if data.get(field) is not None:
            assert_cost_precision(data[field])


def assert_lease_unit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lease_id", ""))
    assert is_valid_uuid(data.get("model_id", ""))
    assert isinstance(data["unit_seq"], int) and data["unit_seq"] >= 1
    assert data["status"] in {s.value for s in LeaseUnitStatus}
    if data.get("serial_number") is not None:
        assert isinstance(data["serial_number"], str) and data["serial_number"]
    if data.get("hours_used") is not None:
        assert isinstance(data["hours_used"], int) and data["hours_used"] >= 0
    if data.get("condition_grade") is not None:
        assert data["condition_grade"] in ("A", "B", "C", "D")
    if data.get("delivered_at") is not None:
        assert is_iso8601_timestamp(data["delivered_at"])
    if data.get("returned_at") is not None:
        assert is_iso8601_timestamp(data["returned_at"])
    for field in ("asking_price_cents", "floor_price_cents", "sale_price_cents"):
        if data.get(field) is not None:
            assert_cost_precision(data[field])
    if data.get("reserved_by_course_id") is not None:
        assert is_valid_uuid(data["reserved_by_course_id"])
    if data.get("reservation_expires_at") is not None:
        assert is_iso8601_timestamp(data["reservation_expires_at"])


def assert_appraisal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lease_id", ""))
    assert is_valid_uuid(data.get("model_id", ""))
    assert isinstance(data["external_serial"], str) and data["external_serial"]
    assert isinstance(data["hours"], int) and data["hours"] >= 0
    assert data["condition_grade"] in ("A", "B", "C", "D")
    assert data["policy"] in ("BOOK", "MARKET")
    # Both valuation variants are computed immediately at creation.
    assert_cost_precision(data["book_value_cents"])
    assert_cost_precision(data["market_value_cents"])
    assert_cost_precision(data["valued_cents"])
    assert data["status"] in {s.value for s in AppraisalStatus}


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("distributor_id", ""))
    assert is_valid_uuid(data.get("lease_unit_id", ""))
    assert is_valid_uuid(data.get("technician_id", ""))
    assert isinstance(data["labor_hours"], (int, float)) and data["labor_hours"] > 0
    assert isinstance(data["parts_cost_cents"], int)
    # claimed_labor_cents and factory_allowance_cents are computed at creation.
    assert_cost_precision(data["claimed_labor_cents"])
    assert_cost_precision(data["factory_allowance_cents"])
    assert data["status"] in {s.value for s in WarrantyClaimStatus}
    if data.get("approved_labor_hours") is not None:
        assert 0 < data["approved_labor_hours"] < data["labor_hours"]
    for field in ("adjudicated_labor_cents", "parts_reimbursed_cents", "payable_total_cents"):
        if data.get(field) is not None:
            assert_cost_precision(data[field])
    if data.get("paid_at") is not None:
        assert is_iso8601_timestamp(data["paid_at"])


def assert_irrigation_project(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["acreage"], int) and data["acreage"] >= 1
    assert isinstance(data["zone_count"], int) and data["zone_count"] >= 1
    assert data["status"] in {s.value for s in IrrigationProjectStatus}
    # Design fields are pinned at DESIGN_SUBMITTED; null/absent until then.
    if data.get("controller_model_id") is not None:
        assert is_valid_uuid(data["controller_model_id"])
    if data.get("controllers_required") is not None:
        assert isinstance(data["controllers_required"], int) and data["controllers_required"] >= 1
    if data.get("design_fee_cents") is not None:
        assert_cost_precision(data["design_fee_cents"])
    if data.get("water_budget_gpd") is not None:
        assert isinstance(data["water_budget_gpd"], int)
    if data.get("pinned_config_version") is not None:
        assert isinstance(data["pinned_config_version"], int)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_lease_billing_invariant(lease: dict):
    """PRD §3.6: at every observable instant, billed_to_date_cents +
    remaining_balance_cents == net_contract_value_cents exactly."""
    if lease.get("net_contract_value_cents") is None:
        return  # financials not computed until approve
    billed = lease["billed_to_date_cents"]
    remaining = lease["remaining_balance_cents"]
    net = lease["net_contract_value_cents"]
    assert billed + remaining == net, (
        f"billing invariant violated: billed {billed} + remaining {remaining} "
        f"!= net {net}"
    )
    assert 0 <= billed <= net
    assert 0 <= remaining <= net


def assert_appraisal_valuation_consistency(appraisal: dict):
    """valued_cents selects the variant named by policy (PRD §3.5)."""
    policy = appraisal["policy"]
    expected = (
        appraisal["book_value_cents"] if policy == "BOOK" else appraisal["market_value_cents"]
    )
    assert appraisal["valued_cents"] == expected, (
        f"valued_cents {appraisal['valued_cents']} != {policy} variant value {expected}"
    )


def assert_remarketing_floor_holds(unit: dict):
    """PRD §3.7: the ask never decays below floor_price_cents."""
    if unit.get("asking_price_cents") is None or unit.get("floor_price_cents") is None:
        return
    assert unit["asking_price_cents"] >= unit["floor_price_cents"], (
        f"asking {unit['asking_price_cents']} below floor {unit['floor_price_cents']}"
    )
