"""Domain assertions for the Protective Coating Specification API.

Structural checks (UUID identity, ISO 8601 rendering, envelope shape) are
defined once here and reused by every test; entity assertions check the common
quartet plus status membership. Nothing here asserts a wall-clock value: the
contract ties only rule evaluation to the logical clock, so timestamps are
checked for shape, not for a specific reading.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant


# ── Instants ───────────────────────────────────────────────────────────────

def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_instant_format(value: str, label: str = "instant") -> None:
    """Assert a value is an ISO 8601 UTC instant."""
    assert is_iso8601_timestamp(value), f"{label}: not an ISO 8601 UTC instant: {value!r}"


# ── Numbers ────────────────────────────────────────────────────────────────

def assert_quantity(actual: Any, expected: float, places: int = 1, label: str = "value") -> None:
    """Assert a fixed-precision quantity equals the expected figure at that precision."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert round(float(actual), places) == round(float(expected), places), (
        f"{label}: expected {expected} at {places} decimal places, got {actual}"
    )


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a money amount, carried as an integer number of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: money must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_score(actual: Any, expected: int, label: str = "quality_history_score") -> None:
    """Assert a quality-history score: pure integer arithmetic, no rounding."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: score must be an integer, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


# ── Envelope and common fields ─────────────────────────────────────────────

def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Assert the meta block carries a prefixed request id and a UTC instant."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_instant_format(meta["api_request_timestamp"], "meta.api_request_timestamp")


def assert_mutable_common_fields(data: Dict[str, Any], label: str = "entity") -> None:
    """Assert the full identity quartet on a mutable resource."""
    assert is_valid_uuid(data.get("id")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_instant_format(data["created_at"], f"{label}.created_at")
    assert_instant_format(data["updated_at"], f"{label}.updated_at")
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version must be positive, got {data['version']}"


# ── Listing envelope ───────────────────────────────────────────────────────

def assert_list_page(meta: Dict[str, Any], limit: int, offset: int, total: int, has_more: bool) -> None:
    """Assert a list response reports the page it served and the collection size."""
    assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"meta.offset: expected {offset}, got {meta['offset']}"
    assert meta["total_count"] == total, (
        f"meta.total_count: expected {total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more: expected {has_more}, got {meta['has_more']}"
    )


# ── Entity assertions ──────────────────────────────────────────────────────

def assert_coating_system(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "coating_system")
    assert isinstance(data["system_code"], str) and data["system_code"]
    assert data["status"] in ("ACTIVE", "OBSOLETE")
    assert isinstance(data["spec_revision"], int) and data["spec_revision"] >= 1
    assert data["surface_prep_standard"] in (
        "SSPC_SP10_NEAR_WHITE", "SSPC_SP6_COMMERCIAL", "SSPC_SP11_POWER_TOOL", "SSPC_SP1_SOLVENT"
    )


def assert_voc_regulation(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "voc_regulation")
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert data["application_method"] in ("SPRAY_AIRLESS", "SPRAY_CONVENTIONAL", "BRUSH_ROLLER")
    assert isinstance(data["voc_limit_gpl"], int)
    assert_instant_format(data["effective_from"], "voc_regulation.effective_from")
    assert_instant_format(data["effective_to"], "voc_regulation.effective_to")


def assert_applicator(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "applicator")
    assert data["status"] in ("REGISTERED", "ACTIVE")
    assert isinstance(data["quality_history_score"], int)
    assert 0 <= data["quality_history_score"] <= 1000
    assert isinstance(data["consecutive_passed_inspections"], int)
    assert data["consecutive_passed_inspections"] >= 0


def assert_qualification_program(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "qualification_program")
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert is_valid_uuid(data.get("coating_system_id"))


def assert_applicator_qualification(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "applicator_qualification")
    assert data["status"] in ("CANDIDATE", "CERTIFIED", "SUSPENDED", "PROBATION", "REVOKED")
    assert is_valid_uuid(data.get("applicator_id"))
    assert is_valid_uuid(data.get("program_id"))
    assert isinstance(data["suspension_count"], int) and data["suspension_count"] >= 0


def assert_project(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "project")
    assert data["status"] in ("PLANNING", "SPECIFIED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["asset_type"] in (
        "BRIDGE", "TANK_EXTERIOR", "TANK_INTERIOR", "PIPELINE", "STRUCTURAL_STEEL"
    )
    assert isinstance(data["committed_warranty_exposure_cents"], int)
    assert data["committed_warranty_exposure_cents"] >= 0


def assert_project_specification(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "project_specification")
    assert data["status"] in ("DRAFT", "ISSUED", "SUPERSEDED", "WITHDRAWN")
    assert data["application_method"] in ("SPRAY_AIRLESS", "SPRAY_CONVENTIONAL", "BRUSH_ROLLER")


def assert_substitution_request(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "substitution_request")
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUESTED", "APPROVED", "REJECTED")
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1


def assert_work_order(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "work_order")
    assert data["status"] in (
        "SCHEDULED", "PREP_INSPECTION", "PREP_APPROVED",
        "COATING_IN_PROGRESS", "ON_HOLD", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["hold_point_prep_released"], bool)


def assert_prep_inspection(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "prep_inspection")
    assert data["result"] in ("PASSED", "FAILED")
    assert isinstance(data["failure_reasons"], list)


def assert_coating_application(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "coating_application")
    assert data["cure_state"] in ("WET", "CURED", "INVALID")
    assert data["acceptance_state"] in ("UNTESTED", "TESTED", "WAIVED")


def assert_inspection_report(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "inspection_report")
    assert data["dft_verdict"] in ("PASS", "FAIL")
    assert data["adhesion_verdict"] in ("PASS", "FAIL")
    assert data["holiday_verdict"] in ("PASS", "FAIL")
    assert data["overall_verdict"] in ("ACCEPTED", "REJECTED")


def assert_warranty(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "warranty")
    assert data["status"] in ("ACTIVE", "CLAIMED", "RESOLVED", "DENIED", "VOIDED")
    assert isinstance(data["exposure_cents"], int)


def assert_failure_investigation(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "failure_investigation")
    assert data["status"] in (
        "OPENED", "EVIDENCE_GATHERING", "ADJUDICATED_PRODUCT_DEFECT",
        "ADJUDICATED_APPLICATION_ERROR", "ADJUDICATED_SHARED", "CLOSED_NO_DEFECT",
    )


# ── Domain invariants ──────────────────────────────────────────────────────

def assert_warranty_shares_balance(warranty: Dict[str, Any], label: str = "warranty") -> None:
    """The liability split invariant: the two shares sum exactly to the exposure."""
    material = warranty["material_share_cents"]
    application = warranty["application_share_cents"]
    exposure = warranty["exposure_cents"]
    assert_cents(material, material, f"{label}.material_share_cents")
    assert_cents(application, application, f"{label}.application_share_cents")
    assert material + application == exposure, (
        f"{label}: shares {material} + {application} must equal exposure {exposure}"
    )
