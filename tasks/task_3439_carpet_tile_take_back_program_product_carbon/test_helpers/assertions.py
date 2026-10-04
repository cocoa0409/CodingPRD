"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

assert_{entity}(data) validates the structural shape of one resource object:
server-minted UUID id, ISO 8601 timestamps, enum membership, and field
presence/types. Value assertions (computed footprints, credits, quotes) belong
in the tests themselves.

OffsetRetirement is the single exception to the common-fields convention
(PRD §2.4): it carries id and created_at only, and updated_at / version are
absent — assert_offset_retirement pins that absence.
"""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)


def validate_created(response) -> dict:
    """validate_success pinned at 201 — the PRD §4 status for every creation
    endpoint (collection, batch, lot, site, zone, order, take-back, report,
    claim, offset retirement, manufacturing target, spec package)."""
    return validate_success(response, 201)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _assert_common_fields(data: dict, entity: str):
    """PRD §2.4 common fields: id, created_at, updated_at, version (>= 1)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and not isinstance(
        data.get("version"), bool
    ), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def _assert_nullable_str(data: dict, field: str, entity: str):
    assert field in data, f"{entity}.{field} must be present (null allowed)"
    if data[field] is not None:
        assert isinstance(data[field], str), f"{entity}.{field} must be a string"


def _assert_nullable_number(data: dict, field: str, entity: str):
    assert field in data, f"{entity}.{field} must be present (null allowed)"
    if data[field] is not None:
        assert _is_number(data[field]), f"{entity}.{field} must be numeric"


def assert_collection(data: dict):
    _assert_common_fields(data, "ProductCollection")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["pattern_code"], str) and data["pattern_code"]
    assert data["backing_type"] in ["STANDARD", "ADHESIVE_FREE_CAPABLE"]
    assert data["lifecycle_boundary"] in ["CRADLE_TO_GATE", "CRADLE_TO_GRAVE"]
    assert data["claim_intent"] in ["NONE", "CARBON_NEUTRAL", "CARBON_NEGATIVE"]
    assert data["status"] in ["ACTIVE", "SUNSET"]


def assert_batch(data: dict):
    _assert_common_fields(data, "TileBatch")
    assert is_valid_uuid(data.get("collection_id", "")), "collection_id must be a UUID"
    assert isinstance(data["dye_lot_code"], str) and data["dye_lot_code"]
    assert is_iso8601_timestamp(data.get("production_date", "")), (
        "production_date must be ISO 8601"
    )
    assert _is_number(data["produced_m2"]) and data["produced_m2"] > 0
    assert _is_number(data["mfg_intensity_kgco2e_per_m2"])
    assert _is_number(data["delta_e"]) and data["delta_e"] >= 0
    assert isinstance(data["feedstock_mix"], list)
    for entry in data["feedstock_mix"]:
        assert isinstance(entry.get("lot_id"), str) and entry["lot_id"]
        assert _is_number(entry.get("quantity_kg"))
    assert _is_number(data["allocated_mass_kg"])
    assert _is_number(data["available_m2"])
    _assert_nullable_number(data, "recycled_content_pct", "TileBatch")
    _assert_nullable_number(data, "embodied_carbon_kg_per_m2", "TileBatch")
    assert data["status"] in ["QUARANTINE", "RELEASED", "EXHAUSTED"]


def assert_feedstock_lot(data: dict):
    _assert_common_fields(data, "FeedstockLot")
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert data["source_type"] in [
        "RECLAIMED_FISHING_NET",
        "POST_CONSUMER_TILE",
        "POST_INDUSTRIAL_SCRAP",
        "VIRGIN",
    ]
    assert _is_number(data["quantity_kg"]) and data["quantity_kg"] > 0
    assert _is_number(data["carbon_factor_kgco2e_per_kg"])
    assert "origin_takeback_id" in data, "origin_takeback_id must be present (null allowed)"
    _assert_nullable_number(data, "supplier_reliability_pct", "FeedstockLot")
    assert _is_number(data["available_kg"])
    assert _is_number(data["allocated_kg"])
    assert data["status"] in ["RECEIVED", "QC_PASSED", "QC_FAILED", "DEPLETED"]


def assert_lot_mass_conserved(lot: dict):
    """Invariant (PRD §3.2): available_kg + allocated_kg == quantity_kg after
    every allocate/deallocate step."""
    total = lot["available_kg"] + lot["allocated_kg"]
    assert abs(total - lot["quantity_kg"]) < 1e-6, (
        f"lot mass drift: {lot['available_kg']} + {lot['allocated_kg']} "
        f"!= {lot['quantity_kg']}"
    )


def assert_site(data: dict):
    _assert_common_fields(data, "CustomerSite")
    assert isinstance(data["created_by"], str) and data["created_by"]
    assert isinstance(data["contractor_name"], str) and data["contractor_name"]
    assert isinstance(data["address"], str)
    assert is_iso8601_timestamp(data.get("install_window_start", ""))
    assert is_iso8601_timestamp(data.get("install_window_end", ""))
    assert data["installation_system"] in ["ADHESIVE_FREE", "CONVENTIONAL"]
    assert isinstance(data["adhesive_free_certified"], bool)
    assert is_iso8601_timestamp(data.get("cert_expires_on", ""))
    assert isinstance(data["annual_replacement_budget_cents"], int)
    assert isinstance(data["spent_replacement_cents"], int)
    assert data["status"] in ["PLANNED", "INSTALLED", "IN_SERVICE", "DECOMMISSIONED"]


def assert_zone(data: dict):
    _assert_common_fields(data, "InstalledZone")
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert is_valid_uuid(data.get("batch_id", "")), "batch_id must be a UUID"
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert _is_number(data["area_m2"]) and data["area_m2"] > 0
    assert data["status"] in ["IN_SERVICE", "REPLACED", "RECLAIMED"]


def assert_replacement_order(data: dict):
    _assert_common_fields(data, "ReplacementOrder")
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a UUID"
    assert data["reason"] in ["WEAR", "DAMAGE", "DESIGN_CHANGE"]
    assert isinstance(data["new_zone_code"], str) and data["new_zone_code"]
    assert "matched_batch_id" in data, "matched_batch_id must be present (null allowed)"
    if data["matched_batch_id"] is not None:
        assert is_valid_uuid(data["matched_batch_id"])
    assert "quoted_cost_cents" in data, "quoted_cost_cents must be present (null allowed)"
    if data["quoted_cost_cents"] is not None:
        assert isinstance(data["quoted_cost_cents"], int)
    assert data["status"] in [
        "DRAFT",
        "MATCHED",
        "MATCH_FAILED",
        "COMPLETED",
        "CANCELLED",
    ]
    assert isinstance(data["created_by"], str) and data["created_by"]


def assert_takeback_request(data: dict):
    _assert_common_fields(data, "TakeBackRequest")
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert is_valid_uuid(data.get("collection_id", "")), "collection_id must be a UUID"
    assert data["condition_grade"] in ["A", "B", "C"]
    assert _is_number(data["declared_area_m2"]) and data["declared_area_m2"] > 0
    _assert_nullable_str(data, "pickup_window_start", "TakeBackRequest")
    _assert_nullable_str(data, "pickup_window_end", "TakeBackRequest")
    _assert_nullable_number(data, "collected_kg", "TakeBackRequest")
    _assert_nullable_number(data, "reuse_kg", "TakeBackRequest")
    _assert_nullable_number(data, "depolymerize_kg", "TakeBackRequest")
    _assert_nullable_number(data, "downcycle_kg", "TakeBackRequest")
    _assert_nullable_number(data, "landfill_kg", "TakeBackRequest")
    assert "credit_variant" in data, "credit_variant must be present (null allowed)"
    if data["credit_variant"] is not None:
        assert data["credit_variant"] in ["STANDARD", "CIRCULAR"]
    assert "credit_cents" in data, "credit_cents must be present (null allowed)"
    if data["credit_cents"] is not None:
        assert isinstance(data["credit_cents"], int)
    _assert_nullable_str(data, "credited_at", "TakeBackRequest")
    assert data["status"] in [
        "REQUESTED",
        "SCHEDULED",
        "COLLECTED",
        "CREDITED",
        "CANCELLED",
    ]
    assert isinstance(data["created_by"], str) and data["created_by"]


def assert_pcf_report(data: dict):
    _assert_common_fields(data, "PCFReport")
    assert is_valid_uuid(data.get("collection_id", "")), "collection_id must be a UUID"
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert data["boundary"] in ["CRADLE_TO_GATE", "CRADLE_TO_GRAVE"]
    _assert_nullable_number(data, "operational_kgco2e_per_m2", "PCFReport")
    _assert_nullable_number(data, "lifecycle_kgco2e_per_m2", "PCFReport")
    _assert_nullable_str(data, "submitted_by", "PCFReport")
    _assert_nullable_str(data, "verifier_org", "PCFReport")
    _assert_nullable_str(data, "verified_by", "PCFReport")
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "IN_VERIFICATION",
        "VERIFIED",
        "REJECTED",
        "PUBLISHED",
        "SUPERSEDED",
    ]


def assert_carbon_claim(data: dict):
    _assert_common_fields(data, "CarbonClaim")
    assert is_valid_uuid(data.get("collection_id", "")), "collection_id must be a UUID"
    assert is_valid_uuid(data.get("report_id", "")), "report_id must be a UUID"
    assert "manufacturing_target_id" in data, (
        "manufacturing_target_id must be present (null allowed)"
    )
    if data["manufacturing_target_id"] is not None:
        assert is_valid_uuid(data["manufacturing_target_id"])
    assert data["claim_type"] in ["CARBON_NEUTRAL", "CARBON_NEGATIVE"]
    assert _is_number(data["claimed_volume_m2"]) and data["claimed_volume_m2"] > 0
    assert data["boundary"] in ["CRADLE_TO_GATE", "CRADLE_TO_GRAVE"]
    _assert_nullable_number(data, "required_offset_kgco2e", "CarbonClaim")
    assert _is_number(data["retired_kgco2e"])
    assert data["offset_coverage"] in ["NONE", "PARTIAL", "FULL"]
    assert isinstance(data["created_by"], str) and data["created_by"]
    _assert_nullable_str(data, "reviewed_by", "CarbonClaim")
    assert data["status"] in [
        "DRAFT",
        "IN_REVIEW",
        "APPROVED",
        "REJECTED",
        "PUBLISHED",
        "RETIRED",
    ]


def assert_offset_retirement(data: dict):
    """Immutable event record (PRD §2.4): id + created_at only; updated_at and
    version are absent. No operation ever mutates a retirement."""
    assert is_valid_uuid(data.get("id", "")), "OffsetRetirement.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "OffsetRetirement must not carry updated_at"
    assert "version" not in data, "OffsetRetirement must not carry version"
    assert is_valid_uuid(data.get("claim_id", "")), "claim_id must be a UUID"
    assert data["registry"] in ["VERRA", "GOLD_STANDARD", "ACR"]
    assert isinstance(data["vintage_year"], int)
    assert _is_number(data["quantity_kgco2e"]) and data["quantity_kgco2e"] > 0
    assert is_iso8601_timestamp(data.get("retired_at", "")), (
        "retired_at must be ISO 8601"
    )


def assert_manufacturing_target(data: dict):
    _assert_common_fields(data, "ManufacturingTarget")
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert _is_number(data["baseline_intensity_kgco2e_per_m2"])
    assert data["baseline_intensity_kgco2e_per_m2"] > 0
    assert _is_number(data["target_reduction_pct"])
    assert 0 < data["target_reduction_pct"] < 1
    assert _is_number(data["current_intensity_kgco2e_per_m2"])
    assert data["posture"] in ["ON_TRACK", "AT_RISK", "BREACHED"]
    assert isinstance(data["readings_log"], list)
    for reading in data["readings_log"]:
        assert is_iso8601_timestamp(reading.get("period_end", ""))
        assert _is_number(reading.get("intensity_kgco2e_per_m2"))
        assert is_iso8601_timestamp(reading.get("recorded_at", ""))


def assert_spec_package(data: dict):
    _assert_common_fields(data, "SpecPackage")
    assert isinstance(data["architect_firm"], str) and data["architect_firm"]
    assert is_valid_uuid(data.get("collection_id", "")), "collection_id must be a UUID"
    assert is_valid_uuid(data.get("report_id", "")), "report_id must be a UUID"
    assert "claim_id" in data, "claim_id must be present (null allowed)"
    if data["claim_id"] is not None:
        assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["package_version"], int) and data["package_version"] >= 1
    assert data["status"] in ["ISSUED", "SUPERSEDED", "REVOKED"]
    assert isinstance(data["created_by"], str) and data["created_by"]
