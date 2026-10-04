"""Entity assertions and domain invariant checkers (PRD sections 2.2, 2.5, 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_factory(data: dict):
    _assert_common_fields(data, "Factory")
    assert isinstance(data["factory_name"], str) and data["factory_name"]
    assert data["location_type"] in ("DOMESTIC", "OVERSEAS")
    assert isinstance(data["government_cleared"], bool)
    assert isinstance(data["weekly_capacity_units"], int) and data["weekly_capacity_units"] > 0
    assert isinstance(data["line_count"], int) and data["line_count"] >= 1
    assert isinstance(data["labor_rate_cents_per_minute"], int) and data["labor_rate_cents_per_minute"] >= 0
    assert isinstance(data["overhead_cents_per_pair"], int) and data["overhead_cents_per_pair"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["skill_coverage_certified_pct"], (int, float))
    assert isinstance(data["skill_coverage_pipeline_pct"], (int, float))


def assert_model(data: dict):
    _assert_common_fields(data, "ShoeModel")
    assert isinstance(data["style_code"], str) and data["style_code"]
    assert data["production_policy"] in ("DOMESTIC_ONLY", "IMPORT_ONLY", "DUAL_SOURCE")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["import_cost_basis_cents"], int) and data["import_cost_basis_cents"] > 0
    assert isinstance(data["bom_lines"], list) and len(data["bom_lines"]) >= 1
    for line in data["bom_lines"]:
        assert is_valid_uuid(line.get("component_id", "")), "bom line component_id must be a UUID"
        assert line["quantity_per_pair"] > 0
        assert line["sourcing_requirement"] in (
            "DOMESTIC_REQUIRED", "DOMESTIC_PREFERRED", "IMPORT_ALLOWED",
        )
        assert isinstance(line["planned_unit_cost_cents"], int) and line["planned_unit_cost_cents"] >= 0
        assert isinstance(line["planned_is_domestic"], bool)
    for f in ("standard_stitching_minutes", "standard_lasting_minutes", "standard_assembly_minutes"):
        assert isinstance(data[f], int) and data[f] >= 0
    assert data["domestic_unit_cost_cents"] is None or isinstance(data["domestic_unit_cost_cents"], int)
    assert data["domestic_price_cents"] is None or isinstance(data["domestic_price_cents"], int)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_component(data: dict):
    _assert_common_fields(data, "Component")
    assert isinstance(data["component_name"], str) and data["component_name"]
    assert data["component_type"] in (
        "UPPER", "MIDSOLE", "OUTSOLE", "INSOLE", "LACES", "EYELETS", "ADHESIVE", "THREAD", "OTHER",
    )


def assert_lot(data: dict):
    _assert_common_fields(data, "MaterialLot")
    assert is_valid_uuid(data.get("component_id", ""))
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert isinstance(data["is_domestic"], bool)
    assert isinstance(data["quantity_received"], int) and data["quantity_received"] > 0
    assert isinstance(data["quantity_remaining"], int) and data["quantity_remaining"] >= 0
    assert data["quantity_remaining"] <= data["quantity_received"], (
        "quantity_remaining may never exceed quantity_received"
    )
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert is_iso8601_timestamp(data.get("received_at", "")), "received_at must be ISO 8601"


def assert_run(data: dict):
    _assert_common_fields(data, "ProductionRun")
    assert is_valid_uuid(data.get("model_id", ""))
    assert is_valid_uuid(data.get("factory_id", ""))
    assert data["run_type"] in ("STOCK", "CUSTOM_BATCH", "GOVERNMENT")
    assert isinstance(data["planned_units"], int) and data["planned_units"] >= 1
    assert isinstance(data["line_index"], int) and data["line_index"] >= 1
    assert isinstance(data["start_day"], str) and isinstance(data["end_day"], str)
    assert data["end_day"] > data["start_day"], "end_day must be strictly after start_day"
    assert isinstance(data["iso_week"], str)
    for f in ("actual_stitching_minutes", "actual_lasting_minutes", "actual_assembly_minutes"):
        assert data[f] is None or isinstance(data[f], int)
    assert isinstance(data["consumed_lots"], list)
    for entry in data["consumed_lots"]:
        assert is_valid_uuid(entry.get("lot_id", ""))
        assert is_valid_uuid(entry.get("component_id", ""))
        assert isinstance(entry["units_consumed"], int) and entry["units_consumed"] > 0
        assert isinstance(entry["unit_cost_cents"], int) and entry["unit_cost_cents"] >= 0
        assert isinstance(entry["is_domestic"], bool)
    assert data["certified_unit_cost_cents"] is None or isinstance(data["certified_unit_cost_cents"], int)
    assert data["status"] in (
        "PLANNED", "MATERIAL_RESERVED", "IN_PRODUCTION", "QUALITY_HOLD", "COMPLETED", "CANCELLED",
    )


def assert_report(data: dict):
    _assert_common_fields(data, "DomesticContentReport")
    assert is_valid_uuid(data.get("run_id", ""))
    assert data["variant"] in ("PROVISIONAL", "CERTIFIED")
    for f in (
        "material_cost_cents", "domestic_material_cost_cents", "labor_cost_cents",
        "overhead_cost_cents", "domestic_value_cents", "total_cost_cents",
    ):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be non-negative integer cents"
    assert data["domestic_material_cost_cents"] <= data["material_cost_cents"]
    assert data["domestic_value_cents"] <= data["total_cost_cents"]
    assert isinstance(data["us_content_pct"], (int, float))
    assert 0.0 <= data["us_content_pct"] <= 100.0
    assert isinstance(data["final_assembly_domestic"], bool)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_order(data: dict):
    _assert_common_fields(data, "CustomOrder")
    assert is_valid_uuid(data.get("model_id", ""))
    assert isinstance(data["buyer_ref"], str) and data["buyer_ref"]
    assert isinstance(data["colorway"], str) and data["colorway"]
    assert isinstance(data["size"], str) and data["size"]
    assert isinstance(data["quantity_units"], int) and 1 <= data["quantity_units"] <= 12
    assert data["quoted_price_cents"] is None or isinstance(data["quoted_price_cents"], int)
    assert data["production_run_id"] is None or is_valid_uuid(data["production_run_id"])
    assert data["production_status"] in (
        "SUBMITTED", "ACCEPTED", "SCHEDULED", "IN_PRODUCTION", "FULFILLED", "CANCELLED",
    )


def assert_claim(data: dict):
    _assert_common_fields(data, "LabelClaim")
    assert is_valid_uuid(data.get("model_id", ""))
    assert data["claim_type"] in (
        "MADE_IN_USA", "MADE_IN_USA_OF_IMPORTED_MATERIALS", "ASSEMBLED_IN_USA", "IMPORTED",
    )
    assert data["report_id"] is None or is_valid_uuid(data["report_id"])
    assert data["substantiated_at"] is None or is_iso8601_timestamp(data["substantiated_at"])
    assert data["published_at"] is None or is_iso8601_timestamp(data["published_at"])
    assert data["status"] in ("DRAFT", "SUBSTANTIATED", "PUBLISHED", "CHALLENGED", "REVOKED")


def assert_document(data: dict):
    _assert_common_fields(data, "EvidenceDocument")
    assert data["doc_type"] in (
        "SUPPLIER_ORIGIN_CERT", "ASSEMBLY_LABOR_RECORD", "COST_BREAKDOWN", "CUSTOMS_ENTRY",
    )
    links = [data.get("claim_id"), data.get("material_lot_id"), data.get("production_run_id")]
    assert sum(1 for link in links if link is not None) == 1, (
        "exactly one of claim_id / material_lot_id / production_run_id must be set"
    )
    assert isinstance(data["issuer"], str) and data["issuer"]
    assert data["valid_until"] > data["valid_from"], "valid_until must be strictly after valid_from"
    assert isinstance(data["uploaded_by"], str) and data["uploaded_by"]
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED")


def assert_worker(data: dict):
    _assert_common_fields(data, "Worker")
    assert is_valid_uuid(data.get("factory_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["certifications"], list)
    for cert in data["certifications"]:
        assert cert["operation"] in ("STITCHING", "LASTING", "ASSEMBLY")
        assert cert["level"] in (1, 2, 3)
        assert cert["cert_status"] in ("CERTIFIED", "SUSPENDED")


def assert_enrollment(data: dict):
    _assert_common_fields(data, "TrainingEnrollment")
    assert is_valid_uuid(data.get("worker_id", ""))
    assert data["operation"] in ("STITCHING", "LASTING", "ASSEMBLY")
    assert data["target_level"] in (1, 2, 3)
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    assert data["last_score"] is None or (isinstance(data["last_score"], int) and 0 <= data["last_score"] <= 100)
    assert data["status"] in ("ENROLLED", "REMEDIATION", "CERTIFIED", "FAILED")


def assert_allocation(data: dict):
    _assert_common_fields(data, "CapacityAllocation")
    assert is_valid_uuid(data.get("factory_id", ""))
    assert isinstance(data["iso_week"], str)
    assert isinstance(data["total_reserved_units"], int) and data["total_reserved_units"] >= 0
    assert isinstance(data["domestic_reserved_units"], int) and data["domestic_reserved_units"] >= 0
    assert isinstance(data["import_reserved_units"], int) and data["import_reserved_units"] >= 0
    assert data["domestic_reserved_units"] + data["import_reserved_units"] == data["total_reserved_units"], (
        "pool-sum invariant: domestic + import == total_reserved_units"
    )
    assert data["status"] in ("OPEN", "LOCKED", "RECONCILED")


def assert_contract(data: dict):
    _assert_common_fields(data, "GovContract")
    assert isinstance(data["contract_number"], str) and data["contract_number"]
    assert is_valid_uuid(data.get("model_id", ""))
    assert is_valid_uuid(data.get("factory_id", ""))
    assert isinstance(data["awarded_units"], int) and data["awarded_units"] >= 1
    assert data["fulfillment_end"] > data["fulfillment_start"], (
        "fulfillment_end must be strictly after fulfillment_start"
    )
    assert isinstance(data["fulfilled_units"], int) and data["fulfilled_units"] >= 0
    assert data["audit_passed"] is None or isinstance(data["audit_passed"], bool)
    assert data["status"] in ("AWARDED", "IN_FULFILLMENT", "COMPLIANCE_AUDIT", "CLOSED", "DEFAULTED")
