"""Entity assertions, envelope helpers and domain invariant checkers.

Two list-shape helpers are offered and they are not interchangeable:

* `assert_paginated_list(response)` — for the list endpoints whose `meta`
  carries `limit`, `offset`, `total_count` and `has_more` (PRD 2.3 states this
  for every list endpoint).
* `assert_unpaginated_list(response)` — for any list-shaped `data` array whose
  endpoint narrative does not promise the pagination `meta` block.

Timestamp comparison is canonicalised here rather than done by string equality,
so a server rendering three fractional digits is never compared byte-for-byte
against one rendering none.
"""

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .types import (
    AgeGroup,
    ClaimStatus,
    ComplianceStatus,
    ComponentCategory,
    CoverageVariant,
    DesignStatus,
    InspectionKind,
    InspectionResult,
    InstallerStatus,
    JobStatus,
    ModelCertificationStatus,
    ModelLifecycleStatus,
    PlacementStatus,
    PlayAreaStatus,
    PledgeStatus,
    PrepStatus,
    ProductionStatus,
    QuoteStatus,
    QuoteVariant,
    RenderingStatus,
    StandardStatus,
    SurfacingMaterial,
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ENUMS = {
    "standard_status": [s.value for s in StandardStatus],
    "category": [c.value for c in ComponentCategory],
    "age_group": [a.value for a in AgeGroup],
}


# --------------------------------------------------------------------------
# Envelope / shape helpers
# --------------------------------------------------------------------------
def assert_object_envelope(response, expected_status: int = 200) -> dict:
    """Validate a single-resource success envelope and return `data` once.

    `data` is unwrapped exactly once — never re-index `["data"]` on the result.
    """
    body = response.json()
    assert body.get("response_type") == "object", (
        f"Expected response_type 'object', got {body.get('response_type')!r}"
    )
    meta = body.get("meta") or {}
    assert isinstance(meta.get("api_request_id"), str) and meta[
        "api_request_id"
    ].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta.get('api_request_id')!r}"
    )
    return validate_success(response, expected_status)


def assert_paginated_list(response, expected_total: Optional[int] = None) -> Tuple[List, Dict]:
    """For list endpoints that carry the pagination meta block."""
    data, meta = validate_paginated(response)
    assert isinstance(data, list), f"Expected a list in data, got {type(data)}"
    body = response.json()
    assert body.get("response_type") == "array", (
        f"Expected response_type 'array', got {body.get('response_type')!r}"
    )
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"Expected total_count {expected_total}, got {meta['total_count']}"
        )
    return data, meta


def assert_unpaginated_list(response, expected_status: int = 200) -> List:
    """For any list-shaped response where only the array itself is asserted."""
    data = validate_success(response, expected_status)
    assert isinstance(data, list), f"Expected a list in data, got {type(data)}"
    return data


def assert_empty_data_object(response, expected_status: int = 204) -> None:
    """PRD 4: placement removal answers 204 with an empty `data` object."""
    assert response.status_code == expected_status, (
        f"Expected HTTP {expected_status}, got {response.status_code}: {response.text}"
    )
    if not response.text.strip():
        return
    body = response.json()
    assert body.get("data") in ({}, None), (
        f"Expected an empty data object, got {body.get('data')!r}"
    )


# --------------------------------------------------------------------------
# Common-field helpers
# --------------------------------------------------------------------------
def canonical_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant regardless of fractional-second width."""
    assert isinstance(value, str) and value, f"Expected an ISO-8601 instant, got {value!r}"
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def assert_same_instant(left: str, right: str, label: str = "timestamps") -> None:
    assert canonical_instant(left) == canonical_instant(right), (
        f"{label} differ: {left!r} vs {right!r}"
    )


def assert_common_fields(data: dict, expected_version: Optional[int] = None) -> None:
    """id + created_at + updated_at + version, as PRD 2.4 requires."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_freshly_created(data: dict) -> None:
    """A freshly created row: version 1 and updated_at equal to created_at."""
    assert_common_fields(data, expected_version=1)
    assert_same_instant(data["created_at"], data["updated_at"], "created_at/updated_at")


def assert_append_only_fields(data: dict) -> None:
    """Append-only evidence carries only id and created_at (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only records must not expose updated_at"
    assert "version" not in data, "append-only records must not expose version"


def assert_version_bumped_by(before: dict, after: dict, expected: int = 1) -> None:
    assert after["version"] == before["version"] + expected, (
        f"Expected version {before['version'] + expected}, got {after['version']}"
    )


def assert_date_string(value: Any, field: str = "date") -> None:
    assert isinstance(value, str) and _DATE_RE.match(value), (
        f"{field} must be a YYYY-MM-DD date, got {value!r}"
    )


def assert_cents(value: Any, field: str = "amount") -> None:
    """Money is an integer count of cents — never a float and never a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer count of cents, got {value!r} ({type(value).__name__})"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_standard(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 40
    assert re.match(r"^[A-Z0-9_]+$", data["code"]), (
        f"code must be uppercase letters, digits and underscore, got {data['code']!r}"
    )
    assert isinstance(data["edition_year"], int) and 2000 <= data["edition_year"] <= 2100
    assert_date_string(data["effective_from"], "effective_from")
    assert isinstance(data["min_use_zone_clearance_cm"], int)
    assert data["min_use_zone_clearance_cm"] >= 0
    for field in (
        "max_fall_height_cm_toddler",
        "max_fall_height_cm_preschool",
        "max_fall_height_cm_school_age",
    ):
        assert isinstance(data[field], int) and data[field] > 0, f"{field} must be > 0"
    assert isinstance(data["requires_accessible_route"], bool)
    assert data["status"] in _ENUMS["standard_status"], (
        f"unexpected standard status {data['status']!r}"
    )
    assert "superseded_by_standard_id" in data


def assert_component_model(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and 1 <= len(data["sku"]) <= 40
    assert data["category"] in _ENUMS["category"]
    assert data["age_group"] in _ENUMS["age_group"]
    assert isinstance(data["deck_height_cm"], int) and 0 <= data["deck_height_cm"] <= 400
    assert isinstance(data["use_zone_footprint_cm"], int)
    assert data["use_zone_footprint_cm"] >= 0
    assert isinstance(data["color_options"], list) and 1 <= len(data["color_options"]) <= 8
    assert len(set(data["color_options"])) == len(data["color_options"]), (
        "color_options must be distinct"
    )
    for colour in data["color_options"]:
        assert isinstance(colour, str) and colour == colour.upper(), (
            f"colour option must be uppercase, got {colour!r}"
        )
    assert_cents(data["unit_price_cents"], "unit_price_cents")
    assert data["unit_price_cents"] > 0
    assert isinstance(data["hardware_bag_count"], int) and data["hardware_bag_count"] >= 0
    assert isinstance(data["warranty_years"], int) and 1 <= data["warranty_years"] <= 50
    assert isinstance(data["parts_support_until_year"], int)
    assert 2000 <= data["parts_support_until_year"] <= 2200
    assert isinstance(data["accessible_transfer_ready"], bool)
    assert data["certification_status"] in [s.value for s in ModelCertificationStatus]
    assert data["lifecycle_status"] in [s.value for s in ModelLifecycleStatus]
    assert "certified_against_standard_id" in data
    assert "supersedes_model_id" in data


def assert_project(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["client_name"], str) and 1 <= len(data["client_name"]) <= 120
    assert isinstance(data["consultant_user_id"], str) and data["consultant_user_id"]
    assert isinstance(data["site_length_cm"], int) and 0 < data["site_length_cm"] <= 100000
    assert isinstance(data["site_width_cm"], int) and 0 < data["site_width_cm"] <= 100000
    assert data["site_soil_type"] in ("SANDY_LOAM", "GRAVEL", "CLAY")
    assert_cents(data["budget_cents"], "budget_cents")
    assert data["budget_cents"] > 0
    assert_date_string(data["fundraising_deadline"], "fundraising_deadline")
    assert isinstance(data["required_age_groups"], list)
    assert 1 <= len(data["required_age_groups"]) <= 3
    for band in data["required_age_groups"]:
        assert band in _ENUMS["age_group"]
    assert isinstance(data["accessible_route_required"], bool)
    assert data["design_status"] in [s.value for s in DesignStatus]
    assert data["compliance_status"] in [s.value for s in ComplianceStatus]
    assert isinstance(data["revision_rounds"], int) and data["revision_rounds"] >= 0
    assert "installed_on" in data
    if data["installed_on"] is not None:
        assert_date_string(data["installed_on"], "installed_on")
    for field in (
        "funds_collected_cents",
        "alloc_permit_freight_cents",
        "alloc_surfacing_cents",
        "alloc_structure_cents",
        "alloc_contingency_cents",
    ):
        assert_cents(data[field], field)
        assert data[field] >= 0, f"{field} must not be negative"
    assert_allocation_invariant(data)


def assert_allocation_invariant(project: dict) -> None:
    """PRD 3.6: the four buckets sum to exactly funds_collected_cents."""
    total = (
        project["alloc_permit_freight_cents"]
        + project["alloc_surfacing_cents"]
        + project["alloc_structure_cents"]
        + project["alloc_contingency_cents"]
    )
    assert total == project["funds_collected_cents"], (
        "allocation buckets must sum to funds_collected_cents: "
        f"{total} != {project['funds_collected_cents']}"
    )


def assert_play_area(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["age_group"] in _ENUMS["age_group"]
    assert isinstance(data["axis_origin_cm"], int) and data["axis_origin_cm"] >= 0
    assert isinstance(data["axis_length_cm"], int) and data["axis_length_cm"] > 0
    assert data["surfacing_material"] in [m.value for m in SurfacingMaterial]
    assert isinstance(data["surfacing_depth_cm"], int)
    assert 0 <= data["surfacing_depth_cm"] <= 120
    assert isinstance(data["critical_fall_height_cm"], int)
    assert data["critical_fall_height_cm"] >= 0
    assert isinstance(data["required_surfacing_depth_cm"], int)
    assert data["required_surfacing_depth_cm"] >= 15, (
        "required_surfacing_depth_cm never falls below the absolute minimum of 15"
    )
    assert data["status"] in [s.value for s in PlayAreaStatus]


def assert_placement(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["play_area_id"])
    assert is_valid_uuid(data["component_model_id"])
    assert "attached_to_placement_id" in data
    assert isinstance(data["color_choice"], str) and data["color_choice"]
    assert isinstance(data["x_start_cm"], int) and data["x_start_cm"] >= 0
    assert isinstance(data["quantity"], int) and 1 <= data["quantity"] <= 50
    assert isinstance(data["use_zone_start_cm"], int)
    assert isinstance(data["use_zone_end_cm"], int)
    assert data["use_zone_end_cm"] >= data["use_zone_start_cm"]
    assert data["status"] in [s.value for s in PlacementStatus]
    assert "retrofit_model_id" in data
    assert isinstance(data["retrofit_quantity"], int)
    for field in (
        "retrofit_unit_price_cents",
        "retrofit_handling_cents",
        "retrofit_total_cents",
    ):
        assert_cents(data[field], field)
    assert isinstance(data["legacy_surcharge_applied"], bool)


def assert_use_zone(placement: dict, model: dict) -> None:
    """PRD 3.3: derived use-zone interval, with slide run-out."""
    expected_start = placement["x_start_cm"] - model["use_zone_footprint_cm"]
    expected_end = placement["x_start_cm"] + model["use_zone_footprint_cm"]
    if model["category"] == "PLASTIC_SLIDE":
        expected_end += 122
    assert placement["use_zone_start_cm"] == expected_start, (
        f"use_zone_start_cm should be {expected_start}, got {placement['use_zone_start_cm']}"
    )
    assert placement["use_zone_end_cm"] == expected_end, (
        f"use_zone_end_cm should be {expected_end}, got {placement['use_zone_end_cm']}"
    )


def assert_rendering(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["pinned_standard_id"])
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["use_zone_snapshot"], dict)
    assert isinstance(data["yes_votes"], int) and data["yes_votes"] >= 0
    assert isinstance(data["no_votes"], int) and data["no_votes"] >= 0
    assert isinstance(data["community_approval_pct"], (int, float))
    assert not isinstance(data["community_approval_pct"], bool)
    assert data["status"] in [s.value for s in RenderingStatus]


def assert_use_zone_snapshot_entry(snapshot: dict, area: dict) -> None:
    """PRD 3.4: one snapshot entry per play area id, recording four numbers."""
    key = area["id"]
    assert key in snapshot, f"use_zone_snapshot must be keyed by play area id {key}"
    entry = snapshot[key]
    assert entry["critical_fall_height_cm"] == area["critical_fall_height_cm"]
    assert entry["required_surfacing_depth_cm"] == area["required_surfacing_depth_cm"]
    assert entry["surfacing_depth_cm"] == area["surfacing_depth_cm"]
    assert isinstance(entry["placement_count"], int)


def assert_quote(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["rendering_id"])
    assert data["variant"] in [v.value for v in QuoteVariant]
    assert_date_string(data["valid_until"], "valid_until")
    for field in ("subtotal_cents", "freight_cents", "discount_cents", "total_cents"):
        assert_cents(data[field], field)
    assert isinstance(data["priced_unit_count"], int) and data["priced_unit_count"] >= 1
    assert data["status"] in [s.value for s in QuoteStatus]
    assert_quote_arithmetic(data)


def assert_quote_arithmetic(quote: dict) -> None:
    """PRD 3.5 step six: total = subtotal + freight - discount."""
    expected = quote["subtotal_cents"] + quote["freight_cents"] - quote["discount_cents"]
    assert quote["total_cents"] == expected, (
        "total_cents must equal subtotal_cents + freight_cents - discount_cents: "
        f"{quote['total_cents']} != {expected}"
    )


def assert_freight(quote: dict) -> None:
    """PRD 3.5 step four: 48000 cents plus 1250 per priced unit."""
    expected = 48000 + 1250 * quote["priced_unit_count"]
    assert quote["freight_cents"] == expected, (
        f"freight_cents should be {expected}, got {quote['freight_cents']}"
    )


def assert_pledge(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert_cents(data["amount_cents"], "amount_cents")
    assert data["amount_cents"] > 0
    assert_date_string(data["pledged_at"], "pledged_at")
    assert data["status"] in [s.value for s in PledgeStatus]


def assert_order(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["quote_id"])
    assert data["production_status"] in [s.value for s in ProductionStatus]
    assert data["kitting_status"] in [s.value for s in PrepStatus]
    assert data["bagging_status"] in [s.value for s in PrepStatus]
    for field in ("kit_line_count", "hardware_bag_total", "instruction_package_revision"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data[field]!r}"
        )


def assert_installer(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["company_name"], str) and 1 <= len(data["company_name"]) <= 120
    assert data["certification_level"] in ("APPRENTICE", "CERTIFIED", "MASTER")
    assert isinstance(data["certified_categories"], list)
    assert 1 <= len(data["certified_categories"]) <= 5
    assert len(set(data["certified_categories"])) == len(data["certified_categories"])
    for category in data["certified_categories"]:
        assert category in _ENUMS["category"]
    assert isinstance(data["crew_capacity_per_day"], int)
    assert 1 <= data["crew_capacity_per_day"] <= 200
    assert_date_string(data["certification_expires_on"], "certification_expires_on")
    assert isinstance(data["region_code"], str) and re.match(
        r"^[A-Z]{2}$", data["region_code"]
    ), f"region_code must be exactly two uppercase letters, got {data['region_code']!r}"
    assert data["status"] in [s.value for s in InstallerStatus]
    assert isinstance(data["open_audit_failures"], int)
    assert data["open_audit_failures"] >= 0
    assert isinstance(data["committed_crew_days"], int)
    assert data["committed_crew_days"] >= 0


def assert_installation_job(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["installer_id"])
    assert_date_string(data["scheduled_start_date"], "scheduled_start_date")
    assert_date_string(data["scheduled_end_date"], "scheduled_end_date")
    assert data["scheduled_end_date"] >= data["scheduled_start_date"]
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1
    assert data["status"] in [s.value for s in JobStatus]
    assert isinstance(data["rework_cycles"], int) and data["rework_cycles"] >= 0
    assert "last_failed_inspection_kind" in data
    if data["last_failed_inspection_kind"] is not None:
        assert data["last_failed_inspection_kind"] in [k.value for k in InspectionKind]
    assert "install_inspector_user_id" in data
    assert isinstance(data["booked_crew_days"], int)
    assert_booked_crew_days(data)


def assert_booked_crew_days(job: dict) -> None:
    """PRD 3.8: crew_size times the inclusive day count of the booking window."""
    start = date.fromisoformat(job["scheduled_start_date"])
    end = date.fromisoformat(job["scheduled_end_date"])
    days = (end - start).days + 1
    expected = job["crew_size"] * days
    assert job["booked_crew_days"] == expected, (
        f"booked_crew_days should be {expected} ({job['crew_size']} x {days} days), "
        f"got {job['booked_crew_days']}"
    )


def assert_inspection(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["job_id"])
    assert data["kind"] in [k.value for k in InspectionKind]
    assert data["result"] in [r.value for r in InspectionResult]
    assert isinstance(data["performed_by_user_id"], str) and data["performed_by_user_id"]
    for field in (
        "deficiency_count",
        "fall_height_measured_cm",
        "surfacing_depth_measured_cm",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1


def assert_warranty_claim(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["placement_id"])
    assert is_valid_uuid(data["component_model_id"])
    assert data["claim_category"] in _ENUMS["category"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert_date_string(data["failure_date"], "failure_date")
    assert isinstance(data["elapsed_years"], int) and data["elapsed_years"] >= 0
    assert data["coverage_variant"] in [v.value for v in CoverageVariant]
    assert isinstance(data["covered_pct"], int) and 0 <= data["covered_pct"] <= 100, (
        f"covered_pct is a whole percent, got {data['covered_pct']!r}"
    )
    assert_cents(data["reimbursement_cents"], "reimbursement_cents")
    assert data["status"] in [s.value for s in ClaimStatus]


# --------------------------------------------------------------------------
# Derived-number helpers (expected values computed from PRD prose)
# --------------------------------------------------------------------------
def expected_base_attenuation_depth(
    critical_fall_height_cm: int, surfacing_material: str
) -> int:
    """PRD 3.3 base attenuation depth."""
    if critical_fall_height_cm == 0:
        return 0
    if surfacing_material == "ENGINEERED_WOOD_FIBER":
        if critical_fall_height_cm <= 150:
            return 23
        if critical_fall_height_cm <= 200:
            return 30
        return 38
    if critical_fall_height_cm <= 150:
        return 5
    if critical_fall_height_cm <= 200:
        return 8
    return 13


def expected_required_surfacing_depth(
    critical_fall_height_cm: int,
    surfacing_material: str,
    age_group: str,
    site_soil_type: str,
) -> int:
    """PRD 3.3: the greatest of the two non-additive candidates and 15."""
    base = expected_base_attenuation_depth(critical_fall_height_cm, surfacing_material)
    candidate_age = base + 5 if age_group == "TODDLER_6_23M" else base
    candidate_soil = base + 3 if site_soil_type == "CLAY" else base
    return max(candidate_age, candidate_soil, 15)


def assert_required_surfacing_depth(
    area: dict, site_soil_type: str, expected: Optional[int] = None
) -> None:
    computed = expected_required_surfacing_depth(
        area["critical_fall_height_cm"],
        area["surfacing_material"],
        area["age_group"],
        site_soil_type,
    )
    target = expected if expected is not None else computed
    assert area["required_surfacing_depth_cm"] == target, (
        f"required_surfacing_depth_cm should be {target}, "
        f"got {area['required_surfacing_depth_cm']}"
    )


def expected_covered_pct(
    category: str, warranty_years: int, elapsed_years: int
) -> int:
    """PRD 3.9 coverage variants, selected purely by category."""
    if category in ("POST", "DECK", "METAL_CLIMBER"):
        if elapsed_years >= warranty_years:
            return 0
        exact = 100 * (warranty_years - elapsed_years) / warranty_years
        return int(exact + 0.5) if exact >= 0 else 0
    halfway = -(-warranty_years // 2)  # rounded up
    if elapsed_years <= halfway:
        return 100
    if elapsed_years < warranty_years:
        return 50
    return 0


def days_between(start_date: str, end_date: str) -> int:
    return (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days


def shift_date(value: str, days: int) -> str:
    return (date.fromisoformat(value) + timedelta(days=days)).isoformat()


def instant_for_date(value: str) -> str:
    """Turn a YYYY-MM-DD date into the ISO-8601 UTC instant at its midnight."""
    assert_date_string(value, "date")
    return f"{value}T00:00:00Z"


def separation_cm(earlier_end_cm: int, later_start_cm: int) -> int:
    """PRD 3.3: whole centimetres strictly between two closed intervals."""
    return later_start_cm - earlier_end_cm - 1
