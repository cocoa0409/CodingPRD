"""Entity assertions and envelope helpers for the Meat & Poultry Inspection API.

``validate_success`` here intentionally differs from the framework's: the
expected HTTP status is a REQUIRED argument with no default. The PRD (§4)
splits success statuses — "Operations that create a new resource return
``201 Created``; operations that modify an existing resource, drive a state
transition, or read data return ``200 OK``" — so every call site must say
which one it expects. Pass ``201`` at create endpoints, ``200`` everywhere
else.
"""

from typing import Any, Dict, Iterable, Optional

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)
from prd_bench_local_runner.testing import validate_success as _framework_validate_success

from .api_client import canonical_instant


# ── Strict success validation ────────────────────────────────────────────────

def validate_success(response: requests.Response, expected_status: int) -> Dict[str, Any]:
    """Assert the success envelope at the EXPLICITLY given status.

    No default: creates must pass 201, reads/actions must pass 200 (PRD §4).
    Returns the ``data`` payload.
    """
    return _framework_validate_success(response, expected_status=expected_status)


# ── Timestamp helpers ────────────────────────────────────────────────────────

def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Compare two instants on their canonical three-fractional-digit form."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_instant_format(value: str, label: str = "instant") -> None:
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"{label} must be an ISO 8601 UTC timestamp, got {value!r}"
    )


# ── Envelope helpers ─────────────────────────────────────────────────────────

def assert_envelope_meta(body: Dict[str, Any]) -> None:
    meta = body.get("meta", {})
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith("req_"), (
        "meta.api_request_id must be present and start with 'req_'"
    )
    assert_instant_format(meta.get("api_request_timestamp", ""), "meta.api_request_timestamp")


def assert_list_page(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    """Assert the four pagination fields of a list response (PRD §2.3)."""
    assert meta.get("limit") == limit, f"limit: expected {limit}, got {meta.get('limit')}"
    assert meta.get("offset") == offset, f"offset: expected {offset}, got {meta.get('offset')}"
    assert meta.get("total_count") == total_count, (
        f"total_count: expected {total_count}, got {meta.get('total_count')}"
    )
    assert meta.get("has_more") == has_more, f"has_more: expected {has_more}, got {meta.get('has_more')}"


# ── Common-field helpers ─────────────────────────────────────────────────────

def _assert_mutable_common_fields(data: Dict[str, Any], label: str) -> None:
    """id + created_at + updated_at + version (PRD §2.6: version starts at 1)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID, got {data.get('id')!r}"
    assert_instant_format(data.get("created_at", ""), f"{label}.created_at")
    assert_instant_format(data.get("updated_at", ""), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_number(value: Any, label: str) -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {value!r}"
    )


def _assert_enum_member(value: Any, allowed: Iterable[str], label: str) -> None:
    allowed = list(allowed)
    assert value in allowed, f"{label} must be one of {allowed}, got {value!r}"


# ── Per-entity assertions ────────────────────────────────────────────────────

SPECIES_CLASSES = ["CATTLE", "SWINE", "POULTRY", "SHEEP"]
REGULATION_FAMILIES = ["SANITATION", "HACCP", "HUMANE", "LABELING", "OTHER"]


def assert_establishment(data: Dict[str, Any]) -> None:
    """Full Establishment shape, including the computed fields the PRD (§2.10)
    pins on every read: open_nr_count, suspension_count, compliance_score,
    enforcement_priority_score, rolling_risk_score, lifetime_risk_score,
    pathogen_category."""
    _assert_mutable_common_fields(data, "Establishment")
    assert isinstance(data.get("name"), str) and data["name"], "Establishment.name required"
    assert isinstance(data.get("species_classes"), list) and len(data["species_classes"]) >= 1, (
        "Establishment.species_classes must be a non-empty array"
    )
    for member in data["species_classes"]:
        _assert_enum_member(member, SPECIES_CLASSES, "Establishment.species_classes member")
    assert isinstance(data.get("slaughter_capable"), bool), "Establishment.slaughter_capable must be a boolean"
    _assert_enum_member(data.get("grant_status"), ["UNGRANTED", "GRANTED", "WITHDRAWN"], "Establishment.grant_status")
    _assert_enum_member(data.get("inspection_status"), ["INACTIVE", "ACTIVE", "SUSPENDED"], "Establishment.inspection_status")
    assert data.get("pathogen_category") is None or data["pathogen_category"] in ["CAT_1", "CAT_2", "CAT_3"], (
        f"Establishment.pathogen_category must be null or CAT_1/2/3, got {data.get('pathogen_category')!r}"
    )
    assert isinstance(data.get("open_nr_count"), int), "Establishment.open_nr_count must be an integer"
    assert isinstance(data.get("suspension_count"), int), "Establishment.suspension_count must be an integer"
    _assert_number(data.get("compliance_score"), "Establishment.compliance_score")
    assert isinstance(data.get("enforcement_priority_score"), int), (
        "Establishment.enforcement_priority_score must be an integer"
    )
    assert isinstance(data.get("rolling_risk_score"), int), "Establishment.rolling_risk_score must be an integer"
    assert isinstance(data.get("lifetime_risk_score"), int), "Establishment.lifetime_risk_score must be an integer"


def assert_grant_application(data: Dict[str, Any]) -> None:
    _assert_mutable_common_fields(data, "GrantApplication")
    assert is_valid_uuid(data.get("establishment_id", "")), "GrantApplication.establishment_id must be a UUID"
    for ref in ("facility_doc_ref", "sanitation_plan_ref", "haccp_plan_ref"):
        assert isinstance(data.get(ref), str) and data[ref], f"GrantApplication.{ref} required"
    for finding in ("facility_finding", "sanitation_finding", "haccp_finding"):
        _assert_enum_member(data.get(finding), ["PENDING", "ADEQUATE", "DEFICIENT"], f"GrantApplication.{finding}")
    _assert_enum_member(
        data.get("status"),
        ["SUBMITTED", "UNDER_REVIEW", "GRANTED", "DENIED", "WITHDRAWN"],
        "GrantApplication.status",
    )
    assert isinstance(data.get("revision_count"), int) and data["revision_count"] >= 0, (
        "GrantApplication.revision_count must be an integer >= 0"
    )
    assert "decided_at" in data, "GrantApplication.decided_at must be present (null until decided)"
    if data["decided_at"] is not None:
        assert_instant_format(data["decided_at"], "GrantApplication.decided_at")


def assert_inspector(data: Dict[str, Any]) -> None:
    _assert_mutable_common_fields(data, "Inspector")
    assert isinstance(data.get("full_name"), str) and data["full_name"], "Inspector.full_name required"
    assert isinstance(data.get("badge_number"), str) and data["badge_number"], "Inspector.badge_number required"
    assert isinstance(data.get("species_qualifications"), list), "Inspector.species_qualifications must be an array"
    for member in data["species_qualifications"]:
        _assert_enum_member(member, SPECIES_CLASSES, "Inspector.species_qualifications member")
    _assert_enum_member(data.get("employment_status"), ["ACTIVE", "INACTIVE"], "Inspector.employment_status")


def assert_shift_window(data: Dict[str, Any]) -> None:
    _assert_mutable_common_fields(data, "ShiftWindow")
    assert is_valid_uuid(data.get("establishment_id", "")), "ShiftWindow.establishment_id must be a UUID"
    assert_instant_format(data.get("start_utc", ""), "ShiftWindow.start_utc")
    assert_instant_format(data.get("end_utc", ""), "ShiftWindow.end_utc")
    _assert_enum_member(data.get("shift_type"), ["SLAUGHTER", "PROCESSING"], "ShiftWindow.shift_type")
    assert isinstance(data.get("planned_line_count"), int) and data["planned_line_count"] >= 1, (
        "ShiftWindow.planned_line_count must be an integer >= 1"
    )
    _assert_enum_member(
        data.get("status"),
        ["PLANNED", "VERIFIED_COVERED", "COVERAGE_GAP_FLAGGED", "BLOCKED"],
        "ShiftWindow.status",
    )
    # Both gap fields "remain null until the first coverage verification" (PRD §3.2).
    assert "provisional_gap_minutes" in data, "ShiftWindow.provisional_gap_minutes must be present (null until verified)"
    assert "final_gap_minutes" in data, "ShiftWindow.final_gap_minutes must be present (null until verified)"
    for gap in ("provisional_gap_minutes", "final_gap_minutes"):
        if data[gap] is not None:
            assert isinstance(data[gap], int) and data[gap] >= 0, (
                f"ShiftWindow.{gap} must be a non-negative integer, got {data[gap]!r}"
            )


def assert_shift_assignment(data: Dict[str, Any]) -> None:
    _assert_mutable_common_fields(data, "ShiftAssignment")
    assert is_valid_uuid(data.get("shift_window_id", "")), "ShiftAssignment.shift_window_id must be a UUID"
    # establishment_id is denormalized from the window at creation (PRD §3.2).
    assert is_valid_uuid(data.get("establishment_id", "")), "ShiftAssignment.establishment_id must be a UUID"
    assert is_valid_uuid(data.get("inspector_id", "")), "ShiftAssignment.inspector_id must be a UUID"
    assert isinstance(data.get("line_index"), int) and data["line_index"] >= 1, (
        "ShiftAssignment.line_index must be a 1-based integer"
    )
    assert_instant_format(data.get("start_utc", ""), "ShiftAssignment.start_utc")
    assert_instant_format(data.get("end_utc", ""), "ShiftAssignment.end_utc")
    _assert_enum_member(data.get("status"), ["SCHEDULED", "CONFIRMED", "CANCELLED"], "ShiftAssignment.status")


def assert_noncompliance_record(data: Dict[str, Any]) -> None:
    _assert_mutable_common_fields(data, "NoncomplianceRecord")
    assert is_valid_uuid(data.get("establishment_id", "")), "NoncomplianceRecord.establishment_id must be a UUID"
    assert is_valid_uuid(data.get("issued_by_inspector_id", "")), (
        "NoncomplianceRecord.issued_by_inspector_id must be a UUID"
    )
    assert "shift_window_id" in data, "NoncomplianceRecord.shift_window_id must be present (null when unlinked)"
    if data["shift_window_id"] is not None:
        assert is_valid_uuid(data["shift_window_id"]), "NoncomplianceRecord.shift_window_id must be a UUID when set"
    _assert_enum_member(data.get("regulation_family"), REGULATION_FAMILIES, "NoncomplianceRecord.regulation_family")
    assert isinstance(data.get("description"), str) and data["description"], "NoncomplianceRecord.description required"
    assert_instant_format(data.get("observed_at", ""), "NoncomplianceRecord.observed_at")
    assert_instant_format(data.get("issued_at", ""), "NoncomplianceRecord.issued_at")
    _assert_enum_member(
        data.get("status"),
        ["OPEN", "RESPONSE_SUBMITTED", "ESCALATED", "APPEALED", "VERIFIED", "VACATED"],
        "NoncomplianceRecord.status",
    )
    assert "status_before_appeal" in data, "NoncomplianceRecord.status_before_appeal must be present (null until appealed)"
    assert "response_text" in data, "NoncomplianceRecord.response_text must be present (null until answered)"


def assert_enforcement_action(data: Dict[str, Any]) -> None:
    _assert_mutable_common_fields(data, "EnforcementAction")
    assert is_valid_uuid(data.get("establishment_id", "")), "EnforcementAction.establishment_id must be a UUID"
    _assert_enum_member(
        data.get("action_type"),
        ["NOTICE_OF_INTENDED_ENFORCEMENT", "WITHHOLD_MARKS", "SUSPENSION", "WITHDRAWAL"],
        "EnforcementAction.action_type",
    )
    _assert_enum_member(
        data.get("basis"),
        ["NR_LINKAGE", "EGREGIOUS_HUMANE", "CATEGORY_3_PATHOGEN", "ADMINISTRATIVE"],
        "EnforcementAction.basis",
    )
    assert "regulation_family" in data, "EnforcementAction.regulation_family must be present (null unless NR_LINKAGE)"
    if data["regulation_family"] is not None:
        _assert_enum_member(data["regulation_family"], REGULATION_FAMILIES, "EnforcementAction.regulation_family")
    _assert_enum_member(data.get("status"), ["PROPOSED", "IN_EFFECT", "LIFTED"], "EnforcementAction.status")
    assert isinstance(data.get("auto_created"), bool), "EnforcementAction.auto_created must be a boolean"
    assert "effective_at" in data, "EnforcementAction.effective_at must be present (null until activated)"
    if data["effective_at"] is not None:
        assert_instant_format(data["effective_at"], "EnforcementAction.effective_at")
    assert "abatement_evidence" in data, "EnforcementAction.abatement_evidence must be present (null until lifted)"


def assert_humane_event(data: Dict[str, Any]) -> None:
    _assert_mutable_common_fields(data, "HumaneHandlingEvent")
    assert is_valid_uuid(data.get("establishment_id", "")), "HumaneHandlingEvent.establishment_id must be a UUID"
    assert is_valid_uuid(data.get("reported_by_inspector_id", "")), (
        "HumaneHandlingEvent.reported_by_inspector_id must be a UUID"
    )
    _assert_enum_member(data.get("species"), SPECIES_CLASSES, "HumaneHandlingEvent.species")
    _assert_enum_member(data.get("severity"), ["EGREGIOUS", "NON_EGREGIOUS"], "HumaneHandlingEvent.severity")
    assert_instant_format(data.get("observed_at", ""), "HumaneHandlingEvent.observed_at")
    assert isinstance(data.get("description"), str) and data["description"], "HumaneHandlingEvent.description required"
    _assert_enum_member(data.get("status"), ["REPORTED", "CONFIRMED", "DISMISSED"], "HumaneHandlingEvent.status")


def assert_pathogen_sample(data: Dict[str, Any]) -> None:
    _assert_mutable_common_fields(data, "PathogenSample")
    assert is_valid_uuid(data.get("establishment_id", "")), "PathogenSample.establishment_id must be a UUID"
    assert is_valid_uuid(data.get("collected_by_inspector_id", "")), (
        "PathogenSample.collected_by_inspector_id must be a UUID"
    )
    _assert_enum_member(data.get("pathogen"), ["SALMONELLA", "CAMPYLOBACTER"], "PathogenSample.pathogen")
    assert_instant_format(data.get("collected_at", ""), "PathogenSample.collected_at")
    _assert_enum_member(data.get("result"), ["PENDING", "POSITIVE", "NEGATIVE"], "PathogenSample.result")
    assert "resulted_at" in data, "PathogenSample.resulted_at must be present (null until resulted)"
    if data["resulted_at"] is not None:
        assert_instant_format(data["resulted_at"], "PathogenSample.resulted_at")


def assert_label_application(data: Dict[str, Any]) -> None:
    _assert_mutable_common_fields(data, "LabelApplication")
    assert is_valid_uuid(data.get("establishment_id", "")), "LabelApplication.establishment_id must be a UUID"
    assert isinstance(data.get("product_name"), str) and data["product_name"], "LabelApplication.product_name required"
    _assert_enum_member(
        data.get("label_claim"),
        ["GRASS_FED", "NO_ANTIBIOTICS", "ORGANIC", "BREED_SPECIFIC"],
        "LabelApplication.label_claim",
    )
    assert isinstance(data.get("documentation_refs"), list), "LabelApplication.documentation_refs must be an array"
    _assert_enum_member(
        data.get("status"),
        ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "RETURNED", "HELD"],
        "LabelApplication.status",
    )
    assert isinstance(data.get("revision_count"), int) and data["revision_count"] >= 0, (
        "LabelApplication.revision_count must be an integer >= 0"
    )


def assert_recall(data: Dict[str, Any]) -> None:
    _assert_mutable_common_fields(data, "Recall")
    assert is_valid_uuid(data.get("establishment_id", "")), "Recall.establishment_id must be a UUID"
    assert isinstance(data.get("product_description"), str) and data["product_description"], (
        "Recall.product_description required"
    )
    _assert_number(data.get("quantity_lbs"), "Recall.quantity_lbs")
    assert data["quantity_lbs"] > 0, "Recall.quantity_lbs must be > 0"
    _assert_enum_member(data.get("reason_code"), ["PATHOGEN", "MISBRANDING", "FOREIGN_MATTER"], "Recall.reason_code")
    assert "recall_class" in data, "Recall.recall_class must be present (null until determine-class)"
    if data["recall_class"] is not None:
        _assert_enum_member(data["recall_class"], ["CLASS_I", "CLASS_II", "CLASS_III"], "Recall.recall_class")
    _assert_enum_member(
        data.get("status"),
        ["INITIATED", "CLASS_DETERMINED", "CLOSED_EFFECTIVE", "CLOSED_INEFFECTIVE"],
        "Recall.status",
    )
    assert "required_min_checks" in data, "Recall.required_min_checks must be present (null until classified)"
    assert "required_effectiveness_ratio" in data, (
        "Recall.required_effectiveness_ratio must be present (null until classified)"
    )
    assert isinstance(data.get("checks_performed"), int) and data["checks_performed"] >= 0, (
        "Recall.checks_performed must be an integer >= 0"
    )
    assert isinstance(data.get("checks_effective"), int) and data["checks_effective"] >= 0, (
        "Recall.checks_effective must be an integer >= 0"
    )
    assert "effectiveness_ratio" in data, "Recall.effectiveness_ratio must be present (null while no checks recorded)"
    if data["effectiveness_ratio"] is not None:
        _assert_number(data["effectiveness_ratio"], "Recall.effectiveness_ratio")


def assert_effectiveness_check(data: Dict[str, Any]) -> None:
    """Append-only event record (PRD §2.6): id + created_at are the only system
    fields — ``updated_at`` and ``version`` MUST NOT appear on the payload."""
    assert is_valid_uuid(data.get("id", "")), "RecallEffectivenessCheck.id must be a valid UUID"
    assert_instant_format(data.get("created_at", ""), "RecallEffectivenessCheck.created_at")
    assert "updated_at" not in data, "RecallEffectivenessCheck must not carry updated_at (append-only)"
    assert "version" not in data, "RecallEffectivenessCheck must not carry version (append-only)"
    assert is_valid_uuid(data.get("recall_id", "")), "RecallEffectivenessCheck.recall_id must be a UUID"
    assert isinstance(data.get("consignee_name"), str) and data["consignee_name"], (
        "RecallEffectivenessCheck.consignee_name required"
    )
    _assert_enum_member(data.get("outcome"), ["EFFECTIVE", "INEFFECTIVE"], "RecallEffectivenessCheck.outcome")
    assert_instant_format(data.get("checked_at", ""), "RecallEffectivenessCheck.checked_at")


def assert_appeal(data: Dict[str, Any]) -> None:
    _assert_mutable_common_fields(data, "Appeal")
    assert is_valid_uuid(data.get("noncompliance_record_id", "")), "Appeal.noncompliance_record_id must be a UUID"
    assert isinstance(data.get("grounds"), str) and len(data["grounds"]) >= 10, (
        "Appeal.grounds must be at least 10 characters (PRD §3.9)"
    )
    _assert_enum_member(data.get("status"), ["FILED", "AFFIRMED", "REMANDED", "VACATED"], "Appeal.status")
    assert "decided_by_reviewer_id" in data, "Appeal.decided_by_reviewer_id must be present (null until decided)"
    assert "decided_at" in data, "Appeal.decided_at must be present (null until decided)"
    if data["decided_at"] is not None:
        assert_instant_format(data["decided_at"], "Appeal.decided_at")


# ── Domain invariant checkers ────────────────────────────────────────────────

def assert_establishment_scores(data: Dict[str, Any]) -> None:
    """Cross-field invariants on the derived Establishment scores (PRD §2.10):
    the lifetime risk is unwindowed and unweighted by recency, so "for
    identical record sets the lifetime value is always greater than or equal
    to the rolling value"; the compliance score starts at 100 minus penalties
    and is read against the 80.0 benchmark."""
    assert data["lifetime_risk_score"] >= data["rolling_risk_score"], (
        f"lifetime_risk_score ({data['lifetime_risk_score']}) must be >= "
        f"rolling_risk_score ({data['rolling_risk_score']})"
    )
    assert data["open_nr_count"] >= 0 and data["suspension_count"] >= 0
    _assert_number(data.get("compliance_score"), "Establishment.compliance_score")
    assert isinstance(data.get("enforcement_priority_score"), int)
