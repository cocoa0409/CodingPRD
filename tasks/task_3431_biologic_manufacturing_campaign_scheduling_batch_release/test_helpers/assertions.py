"""Entity shape assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, label: str):
    """id + created_at + updated_at + version, per PRD §2.5."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be a positive integer"


def assert_site(data: dict):
    _assert_common_fields(data, "site")
    for field in ("name", "region"):
        assert isinstance(data[field], str) and data[field], f"site.{field} must be a non-empty string"
    assert isinstance(data["monthly_capacity_hours"], int) and data["monthly_capacity_hours"] > 0
    assert isinstance(data["cold_storage_capacity_units"], int) and data["cold_storage_capacity_units"] > 0
    assert isinstance(data["licensed_authorities"], list)
    assert data["release_posture"] in ("CLEAR", "CONDITIONAL", "FROZEN")
    assert isinstance(data["open_critical_deviation_count"], int)
    assert isinstance(data["open_critical_finding_count"], int)


def assert_product(data: dict):
    _assert_common_fields(data, "product")
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data["molecule_type"] in ("MONOCLONAL_ANTIBODY", "FUSION_PROTEIN", "RECOMBINANT_ENZYME")
    assert data["market_scope"] in ("CLINICAL_ONLY", "COMMERCIAL_ONLY", "BOTH")
    assert isinstance(data["requires_cold_chain"], bool)
    assert data["max_storage_temp_c"] > data["min_storage_temp_c"], "product storage band must be non-degenerate"
    assert isinstance(data["shelf_life_hours"], int) and data["shelf_life_hours"] > 0
    assert isinstance(data["changeover_hours"], int) and data["changeover_hours"] >= 0
    assert isinstance(data["same_product_turnaround_hours"], int) and data["same_product_turnaround_hours"] >= 0
    assert isinstance(data["required_materials"], list)


def assert_train(data: dict):
    _assert_common_fields(data, "train")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["train_code"], str) and data["train_code"]
    assert isinstance(data["capacity_liters"], int) and data["capacity_liters"] > 0
    assert isinstance(data["supported_molecule_types"], list) and len(data["supported_molecule_types"]) >= 1


def assert_material_lot(data: dict):
    _assert_common_fields(data, "material_lot")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["material_name"], str) and data["material_name"]
    assert isinstance(data["is_single_source"], bool)
    assert isinstance(data["quantity_available"], (int, float)) and data["quantity_available"] >= 0
    assert data["status"] in ("AVAILABLE", "QUARANTINED")


def assert_inspection(data: dict):
    _assert_common_fields(data, "inspection")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert data["authority"] in ("FDA", "EMA", "PMDA", "MHRA")
    assert data["status"] in ("ANNOUNCED", "FINDINGS_ISSUED", "CLOSED")
    assert isinstance(data["findings"], list)
    assert isinstance(data["open_critical_finding_count"], int) and data["open_critical_finding_count"] >= 0
    assert "response_summary" in data


def assert_comparability_study(data: dict):
    _assert_common_fields(data, "study")
    assert isinstance(data["product_id"], str) and data["product_id"]
    assert data["change_type"] in ("PROCESS_CHANGE", "SITE_TRANSFER", "SCALE_UP")
    assert isinstance(data["baseline_attribute_values"], list) and len(data["baseline_attribute_values"]) >= 3
    assert isinstance(data["candidate_batch_ids"], list) and len(data["candidate_batch_ids"]) >= 1
    assert data["status"] in ("PLANNED", "PROTOCOL_APPROVED", "COMPARABLE", "NOT_COMPARABLE", "FILED")
    for field in ("authority", "baseline_mean", "equivalence_margin"):
        assert field in data, f"study.{field} must be present (null until supplied by the workflow)"


def assert_campaign(data: dict):
    _assert_common_fields(data, "campaign")
    assert isinstance(data["train_id"], str) and data["train_id"]
    assert isinstance(data["product_id"], str) and data["product_id"]
    assert data["demand_type"] in ("CLINICAL", "COMMERCIAL")
    assert is_iso8601_timestamp(data["planned_start_utc"])
    assert is_iso8601_timestamp(data["planned_end_utc"])
    assert isinstance(data["upstream_hours"], int) and data["upstream_hours"] > 0
    assert isinstance(data["downstream_hours"], int) and data["downstream_hours"] > 0
    assert isinstance(data["allocated_hours"], int) and data["allocated_hours"] >= 0
    assert data["status"] in ("PROPOSED", "ALLOCATED", "SEED_IN_PROGRESS",
                              "PRODUCTION_IN_PROGRESS", "COMPLETED", "PREEMPTED")


def assert_seed_stage(data: dict):
    _assert_common_fields(data, "seed_stage")
    assert isinstance(data["campaign_id"], str) and data["campaign_id"]
    assert isinstance(data["stage_index"], int) and data["stage_index"] > 0
    assert isinstance(data["planned_duration_hours"], int) and data["planned_duration_hours"] > 0
    assert data["status"] in ("PENDING", "RUNNING", "COMPLETED", "FAILED", "EXPIRED")
    for field in ("started_at", "completed_at"):
        assert field in data, f"seed_stage.{field} must be present (null until reached)"


def assert_batch(data: dict):
    _assert_common_fields(data, "batch")
    assert isinstance(data["campaign_id"], str) and data["campaign_id"]
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert isinstance(data["product_id"], str) and data["product_id"]
    assert data["process_status"] in ("UPSTREAM", "DOWNSTREAM", "PROCESS_COMPLETE", "TERMINATED")
    assert data["quality_status"] in ("IN_TESTING", "READY_FOR_REVIEW", "PENDING_DISPOSITION",
                                      "UNDER_INVESTIGATION", "RELEASED", "REJECTED", "QUARANTINED")
    assert isinstance(data["manufactured_by_user_id"], str) and data["manufactured_by_user_id"]
    assert isinstance(data["quantity_units"], int) and data["quantity_units"] >= 0
    assert isinstance(data["provisional_yield_units"], int) and data["provisional_yield_units"] >= 0
    assert isinstance(data["available_to_ship_units"], int)
    for field in ("quality_hold_return_status", "final_yield_units",
                  "process_completed_at", "expiry_utc"):
        assert field in data, f"batch.{field} must be present (null until reached)"


def assert_in_process_test(data: dict):
    _assert_common_fields(data, "test")
    assert isinstance(data["batch_lot_id"], str) and data["batch_lot_id"]
    assert data["test_type"] in ("CELL_VIABILITY", "TITER", "PURITY", "STERILITY", "ENDOTOXIN")
    assert data["phase"] in ("UPSTREAM", "DOWNSTREAM")
    assert isinstance(data["measured_value"], (int, float))
    assert isinstance(data["unit"], str) and data["unit"]
    assert data["spec_min"] < data["spec_max"], "spec bounds must be a non-degenerate interval"
    assert isinstance(data["is_in_spec"], bool)
    assert data["status"] in ("RECORDED", "VERIFIED", "OOS_SUSPECT", "OOS_CONFIRMED", "INVALIDATED")
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]
    for field in ("supersedes_test_id", "verified_by_user_id"):
        assert field in data, f"test.{field} must be present (null until supplied)"


def assert_deviation(data: dict):
    _assert_common_fields(data, "deviation")
    assert isinstance(data["batch_lot_id"], str) and data["batch_lot_id"]
    assert data["kind"] in ("PROCESS", "OOS", "COMPLAINT")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert isinstance(data["description"], str) and data["description"]
    assert data["status"] in ("OPEN", "CLOSED", "REOPENED")
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    for field in ("linked_test_id", "conclusion", "capa_summary", "closed_by_user_id"):
        assert field in data, f"deviation.{field} must be present (null while open)"


def assert_shipment(data: dict):
    _assert_common_fields(data, "shipment")
    assert isinstance(data["batch_lot_id"], str) and data["batch_lot_id"]
    assert isinstance(data["destination_region"], str) and data["destination_region"]
    assert data["market_type"] in ("CLINICAL", "COMMERCIAL")
    assert isinstance(data["quantity_units"], int) and data["quantity_units"] >= 1
    assert data["status"] in ("PLANNED", "IN_TRANSIT", "EXCURSION_HOLD",
                              "DELIVERED", "QUARANTINED", "CANCELLED")
    assert data["excursion_evaluation"] in ("NONE", "PENDING", "ACCEPTABLE", "UNACCEPTABLE")
    assert data["evaluation_variant"] in ("NONE", "SCREENING", "MKT")
    for field in ("shipped_at", "delivered_at"):
        assert field in data, f"shipment.{field} must be present (null until reached)"


def assert_temperature_reading(data: dict):
    """Immutable log entry: id + created_at only — no updated_at, no version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "reading.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "reading.created_at must be ISO 8601"
    assert "updated_at" not in data, "reading.updated_at must be absent"
    assert "version" not in data, "reading.version must be absent"
    assert isinstance(data["shipment_id"], str) and data["shipment_id"]
    assert is_iso8601_timestamp(data["recorded_at"])
    assert isinstance(data["temperature_c"], (int, float))


def assert_site_posture_invariants(data: dict):
    """Posture counters are non-negative and posture is one of the three values (PRD §2.9)."""
    assert data["open_critical_deviation_count"] >= 0
    assert data["open_critical_finding_count"] >= 0
    assert data["release_posture"] in ("CLEAR", "CONDITIONAL", "FROZEN")


def assert_batch_ledger_invariants(data: dict):
    """available_to_ship_units never exceeds quantity_units and never goes negative (PRD §3.4)."""
    assert 0 <= data["available_to_ship_units"] <= data["quantity_units"]
    assert data["quantity_units"] >= 0
