"""Entity shape assertions and domain invariant checkers (PRD §2.4, §2.11)."""
import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import (
    SPICE_CODES, ALLERGEN_PROFILES, CHANGEOVER_CLASSES, SHELF_LIFE_DAYS,
)
from .types import (
    LotStatus, TestResult, TestType, FormulaStatus, BrandType, SelectionPolicy,
    BlendRunStatus, SpecStatus, ProductionRunStatus, CommercialStatus,
    QualityStatus, HoldCause, RecallTriggerType, ScopePolicy, RecallSource,
    RecallStatus, ConfidentialityLevel, KnowledgeTier,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_supplier(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["origin_country"], str)
    assert isinstance(data["certifications"], list)
    assert data["knowledge_tier"] in [e.value for e in KnowledgeTier]


def assert_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supplier_id", ""))
    assert data["spice_code"] in SPICE_CODES
    assert isinstance(data["crop_year"], int)
    assert data["quantity_kg"] > 0
    assert data["status"] in [e.value for e in LotStatus]
    assert data["allergen_profile"] in ALLERGEN_PROFILES
    for f in ("quantity_remaining_kg", "quantity_consumed_kg",
              "quantity_wasted_kg", "flavor_intensity_units", "moisture_pct"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_safety_test(data: dict):
    """Append-only event: id + created_at, but NO updated_at and NO version
    (PRD §2.4 sole exception to the common shape)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "safety test must not carry updated_at"
    assert "version" not in data, "safety test must not carry version"
    assert data["test_type"] in [e.value for e in TestType]
    assert data["result"] in [e.value for e in TestResult]
    assert isinstance(data["measured_value"], (int, float))
    assert data["measured_value"] >= 0
    assert isinstance(data["lab_code"], str)
    assert isinstance(data["analyst_user_id"], str)


def assert_formula(data: dict):
    _assert_common(data)
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data["brand_type"] in [e.value for e in BrandType]
    assert data["target_flavor_units"] > 0
    assert data["status"] in [e.value for e in FormulaStatus]
    assert isinstance(data["revision"], int) and data["revision"] >= 1


def assert_formula_line(data: dict):
    _assert_common(data)
    assert isinstance(data["masked_component_code"], str)
    assert data["masked_component_code"].startswith("CMP-")
    assert data["allergen_profile"] in ALLERGEN_PROFILES
    assert isinstance(data["organic_required"], bool)
    assert data["min_lot_flavor_units"] >= 0


def assert_blend_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert data["selection_policy"] in [e.value for e in SelectionPolicy]
    assert data["target_batch_kg"] > 0
    assert data["status"] in [e.value for e in BlendRunStatus]


def assert_line(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity_kg_per_shift"], int)
    assert data["capacity_kg_per_shift"] > 0
    classes = data["supported_changeover_classes"]
    assert isinstance(classes, list) and len(classes) > 0
    assert "NONE" in classes
    assert all(c in CHANGEOVER_CLASSES for c in classes)


def assert_production_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("line_id", ""))
    assert is_valid_uuid(data.get("formula_id", ""))
    assert is_valid_uuid(data.get("blend_run_id", ""))
    assert data["quantity_kg"] > 0
    assert data["status"] in [e.value for e in ProductionRunStatus]
    assert data["changeover_class_required"] in CHANGEOVER_CLASSES
    assert "predecessor_run_id" in data


def assert_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_run_id", ""))
    assert isinstance(data["product_code"], str)
    assert data["brand_type"] in [e.value for e in BrandType]
    assert data["shelf_life_days"] == SHELF_LIFE_DAYS
    assert data["commercial_status"] in [e.value for e in CommercialStatus]
    assert data["quality_status"] in [e.value for e in QualityStatus]
    assert data["quality_hold_cause"] in [e.value for e in HoldCause]
    assert isinstance(data["genealogy_lot_ids"], list)


def assert_recall_case(data: dict):
    _assert_common(data)
    assert data["trigger_type"] in [e.value for e in RecallTriggerType]
    assert data["scope_policy"] in [e.value for e in ScopePolicy]
    assert data["source"] in [e.value for e in RecallSource]
    assert data["status"] in [e.value for e in RecallStatus]
    assert isinstance(data["affected_batch_ids"], list)


def assert_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["retailer_name"], str) and data["retailer_name"]
    assert isinstance(data["product_codes"], list) and len(data["product_codes"]) > 0
    assert data["confidentiality_level"] in [e.value for e in ConfidentialityLevel]
    assert data["annual_commitment_kg"] > 0
    assert isinstance(data["produced_ytd_kg"], (int, float))
    assert isinstance(data["commitment_met"], bool)


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("line_id", ""))
    assert isinstance(data["reserved_kg_per_week"], int)
    assert data["reserved_kg_per_week"] > 0


def assert_lot_mass_invariant(lot: dict):
    """PRD §2.11: quantity_kg == remaining + consumed + wasted, always."""
    total = (lot["quantity_remaining_kg"] + lot["quantity_consumed_kg"]
             + lot["quantity_wasted_kg"])
    assert total == pytest.approx(lot["quantity_kg"], abs=1e-9), (
        f"lot mass invariant violated: {lot['quantity_kg']} != "
        f"{lot['quantity_remaining_kg']} + {lot['quantity_consumed_kg']} + "
        f"{lot['quantity_wasted_kg']}"
    )
