"""Entity assertions and domain invariant checkers.

Each assert_<entity>(data) validates the structural shape of one API resource
body: common system properties (PRD section 2.5), status enum membership, and
field types. Nullable computed fields are asserted present and type-checked
only when non-null, since the PRD defines them as null until computed.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import (
    SHELF_LIFE_DAYS_BY_CHANNEL, NRV_CENTS_PER_CASE_BY_CHANNEL,
)
from .types import (
    SupplierQualificationStatus, SupplierAgreementStatus, LotQcStatus,
    SiteType, CertificationStatus, OperationalStatus, ProductStatus,
    LabelStatus, Claim, Channel, RunStatus, ProgramType, ProgramStatus,
    BatchDerivedStatus, ForecastStatus, WriteDownReason, WriteDownStatus,
    IsolateType,
)


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict):
    """The four system-managed properties every resource carries (PRD 2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def assert_supplier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["supplier_code"], str) and data["supplier_code"]
    assert data["isolate_type"] in _enum_values(IsolateType)
    assert data["qualification_status"] in _enum_values(SupplierQualificationStatus)
    assert data["agreement_status"] in _enum_values(SupplierAgreementStatus)
    if data.get("audit_score") is not None:
        assert isinstance(data["audit_score"], int)
        assert 0 <= data["audit_score"] <= 100
    assert isinstance(data["committed_volume_kg"], int)
    assert data["committed_volume_kg"] > 0
    assert isinstance(data["delivered_volume_kg"], int)
    assert data["delivered_volume_kg"] >= 0
    assert isinstance(data["open_lot_count"], int)
    assert data["open_lot_count"] >= 0
    for field in ("base_price_per_kg_cents", "price_floor_cents",
                  "price_cap_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["price_floor_cents"] < data["base_price_per_kg_cents"], \
        "price_floor_cents must sit strictly below the base"
    assert data["price_cap_cents"] > data["base_price_per_kg_cents"], \
        "price_cap_cents must sit strictly above the base"
    assert is_iso8601_timestamp(data["agreement_start_date"])
    assert is_iso8601_timestamp(data["agreement_end_date"])


def assert_ingredient_lot(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["supplier_id"])
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["quantity_kg"], int) and data["quantity_kg"] > 0
    assert isinstance(data["remaining_kg"], int)
    assert 0 <= data["remaining_kg"] <= data["quantity_kg"]
    assert is_iso8601_timestamp(data["received_at"])
    assert isinstance(data["market_index_pct"], (int, float))
    assert isinstance(data["moisture_pct"], (int, float))
    assert isinstance(data["protein_content_pct"], (int, float))
    assert isinstance(data["provisional_unit_cost_cents"], int), \
        "provisional landed cost is stamped at receipt"
    if data.get("final_unit_cost_cents") is not None:
        assert isinstance(data["final_unit_cost_cents"], int)
    assert data["qc_status"] in _enum_values(LotQcStatus)


def assert_production_line(data: dict):
    assert_common_fields(data)
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert data["site_type"] in _enum_values(SiteType)
    if data["site_type"] == SiteType.CO_MAN.value:
        assert isinstance(data["coman_partner_name"], str)
        assert isinstance(data["monthly_reserved_capacity_kg"], int)
    assert isinstance(data["hourly_capacity_kg"], int)
    assert data["hourly_capacity_kg"] > 0
    assert isinstance(data["supported_isolate_types"], list)
    assert len(data["supported_isolate_types"]) > 0
    for isolate in data["supported_isolate_types"]:
        assert isolate in _enum_values(IsolateType)
    assert data["certification_status"] in _enum_values(CertificationStatus)
    assert data["operational_status"] in _enum_values(OperationalStatus)
    assert isinstance(data["reserved_capacity_kg"], int)
    assert data["reserved_capacity_kg"] >= 0
    if data.get("last_audit_texture_score") is not None:
        assert isinstance(data["last_audit_texture_score"], int)
    if data.get("last_audit_moisture_variance_pct") is not None:
        assert isinstance(data["last_audit_moisture_variance_pct"], (int, float))


def assert_product(data: dict):
    assert_common_fields(data)
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["generation_number"], int)
    assert data["generation_number"] >= 1
    if data.get("supersedes_product_id") is not None:
        assert is_valid_uuid(data["supersedes_product_id"])
    assert data["isolate_type"] in _enum_values(IsolateType)
    assert data["status"] in _enum_values(ProductStatus)
    if data.get("unit_cost_per_kg_cents") is not None:
        assert isinstance(data["unit_cost_per_kg_cents"], int)
    if data.get("price_parity_index") is not None:
        assert isinstance(data["price_parity_index"], (int, float))
    if data.get("parity_goal_met") is not None:
        assert isinstance(data["parity_goal_met"], bool)


def assert_label_version(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["version_number"], int)
    assert isinstance(data["protein_g"], (int, float))
    assert isinstance(data["fat_g"], (int, float))
    assert isinstance(data["sodium_mg"], (int, float))
    assert isinstance(data["claims"], list)
    for claim in data["claims"]:
        assert claim in _enum_values(Claim)
    assert isinstance(data["ingredient_statement"], str)
    assert len(data["ingredient_statement"]) > 0
    assert data["status"] in _enum_values(LabelStatus)


def assert_production_run(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["production_line_id"])
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["label_version_id"])
    if data.get("program_id") is not None:
        assert is_valid_uuid(data["program_id"])
    assert data["is_dedicated"] == (data.get("program_id") is not None), \
        "is_dedicated is exactly the presence of program_id"
    assert data["channel"] in _enum_values(Channel)
    assert isinstance(data["planned_quantity_kg"], int)
    assert data["planned_quantity_kg"] > 0
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["scheduled_end"] > data["scheduled_start"]
    assert data["status"] in _enum_values(RunStatus)
    if data.get("actual_quantity_kg") is not None:
        assert isinstance(data["actual_quantity_kg"], int)
    if data.get("required_isolate_kg") is not None:
        assert isinstance(data["required_isolate_kg"], int)
    assert isinstance(data["consumed_lot_ids"], list)
    for lot_id in data["consumed_lot_ids"]:
        assert is_valid_uuid(lot_id)
    if data.get("cases_produced") is not None:
        assert isinstance(data["cases_produced"], int)
    if data.get("unit_cost_cents_per_case") is not None:
        assert isinstance(data["unit_cost_cents_per_case"], int)


def assert_growth_program(data: dict):
    assert_common_fields(data)
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert data["program_type"] in _enum_values(ProgramType)
    assert is_valid_uuid(data["product_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["window_end"] > data["window_start"]
    if data["program_type"] == ProgramType.FOODSERVICE_LTO.value:
        assert isinstance(data["partner_code"], str)
        assert isinstance(data["committed_cases"], int)
        assert data["committed_cases"] > 0
    else:
        assert isinstance(data["budget_cents"], int)
        assert isinstance(data["coupons_issued"], int)
        assert data["coupons_issued"] >= 0
    assert isinstance(data["dedicated_run_required"], bool)
    assert isinstance(data["coupons_redeemed"], int)
    assert data["coupons_redeemed"] >= 0
    assert isinstance(data["delivered_cases"], int)
    assert data["delivered_cases"] >= 0
    if data.get("attainment_pct") is not None:
        assert isinstance(data["attainment_pct"], (int, float))
    if data.get("redemption_rate_pct") is not None:
        assert isinstance(data["redemption_rate_pct"], (int, float))
    assert isinstance(data["commitment_met"], bool)
    assert data["status"] in _enum_values(ProgramStatus)


def assert_finished_goods_batch(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["production_run_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["channel"] in _enum_values(Channel)
    assert isinstance(data["quantity_cases"], int)
    assert data["quantity_cases"] >= 0
    for field in ("available_cases", "reserved_cases", "written_off_cases"):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must be non-negative"
    if data.get("reserved_for_program_id") is not None:
        assert is_valid_uuid(data["reserved_for_program_id"])
    assert is_iso8601_timestamp(data["produced_at"])
    assert is_iso8601_timestamp(data["expiry_date"])
    assert isinstance(data["unit_cost_cents_per_case"], int)
    assert isinstance(data["recall_flag"], bool)
    assert data["derived_status"] in _enum_values(BatchDerivedStatus)


def assert_batch_case_accounting(data: dict):
    """PRD section 3.7 invariant: quantity_cases always equals available_cases
    plus reserved_cases plus written_off_cases."""
    total = (data["available_cases"] + data["reserved_cases"]
             + data["written_off_cases"])
    assert data["quantity_cases"] == total, (
        f"case accounting broken: quantity_cases={data['quantity_cases']} != "
        f"available {data['available_cases']} + reserved "
        f"{data['reserved_cases']} + written_off {data['written_off_cases']}"
    )


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_batch_expiry_matches_shelf_life(data: dict):
    """PRD section 3.7: expiry_date is produced_at plus the channel's shelf
    life in days (45 FOODSERVICE / 60 RETAIL_REFRIGERATED / 270
    RETAIL_FROZEN / 30 SAMPLES)."""
    shelf_days = SHELF_LIFE_DAYS_BY_CHANNEL[data["channel"]]
    expected = _parse_iso(data["produced_at"]) + timedelta(days=shelf_days)
    actual = _parse_iso(data["expiry_date"])
    assert actual == expected, (
        f"expiry_date {data['expiry_date']} != produced_at "
        f"{data['produced_at']} + {shelf_days} days for channel "
        f"{data['channel']}"
    )


def assert_write_down_amounts(wd: dict, batch: dict):
    """PRD section 3.8 write-down valuation: provisional is full cost
    (quantity x batch unit cost); final, once POSTED, is the quantity times
    the unrecoverable portion (unit cost minus the channel's net realizable
    value per case, floored at zero)."""
    unit_cost = batch["unit_cost_cents_per_case"]
    assert wd["provisional_amount_cents"] == wd["quantity_cases"] * unit_cost
    if wd["status"] == "POSTED":
        nrv = NRV_CENTS_PER_CASE_BY_CHANNEL[batch["channel"]]
        expected_final = wd["quantity_cases"] * max(0, unit_cost - nrv)
        assert wd["final_amount_cents"] == expected_final, (
            f"final_amount_cents {wd['final_amount_cents']} != "
            f"{wd['quantity_cases']} * max(0, {unit_cost} - {nrv})"
        )



def assert_demand_forecast(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert data["channel"] in _enum_values(Channel)
    assert is_iso8601_timestamp(data["week_start"])
    assert isinstance(data["forecast_cases"], int)
    assert data["forecast_cases"] > 0
    if data.get("actual_cases") is not None:
        assert isinstance(data["actual_cases"], int)
        assert data["actual_cases"] >= 0
    if data.get("variance_pct") is not None:
        assert isinstance(data["variance_pct"], (int, float))
    if data.get("is_miss") is not None:
        assert isinstance(data["is_miss"], bool)
    assert data["status"] in _enum_values(ForecastStatus)


def assert_inventory_write_down(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["finished_goods_batch_id"])
    if data.get("demand_forecast_id") is not None:
        assert is_valid_uuid(data["demand_forecast_id"])
    assert data["reason"] in _enum_values(WriteDownReason)
    if data["reason"] == WriteDownReason.FORECAST_MISS.value:
        assert data.get("demand_forecast_id") is not None, \
            "FORECAST_MISS requires demand_forecast_id"
    assert isinstance(data["quantity_cases"], int)
    assert data["quantity_cases"] > 0
    assert isinstance(data["proposed_by_user_id"], str)
    assert data["proposed_by_user_id"]
    if data.get("decided_by_user_id") is not None:
        assert isinstance(data["decided_by_user_id"], str)
    assert isinstance(data["provisional_amount_cents"], int), \
        "provisional amount is valued at full cost at proposal"
    if data.get("final_amount_cents") is not None:
        assert isinstance(data["final_amount_cents"], int)
    assert data["status"] in _enum_values(WriteDownStatus)
