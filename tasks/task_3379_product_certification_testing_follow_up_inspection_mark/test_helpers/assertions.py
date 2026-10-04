"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>(data)`` checks the shape the PRD promises for that
resource: a server-minted UUID id, ISO 8601 timestamps, an integer version,
and the declared fields with values inside the declared enums. The invariant
checkers encode cross-field rules the PRD states (quota accounting on a mark
license, conformity score bounds on a factory, the listing-number format).
"""

import re
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import types as t

__all__ = [
    "assert_common_fields",
    "assert_manufacturer",
    "assert_factory",
    "assert_standard",
    "assert_jurisdiction",
    "assert_project",
    "assert_sample",
    "assert_construction_record",
    "assert_certification",
    "assert_substitution_request",
    "assert_inspection",
    "assert_mark_license",
    "assert_label_batch",
    "assert_field_evaluation",
    "assert_withdrawal_notice",
    "assert_listing_number",
    "assert_mark_license_quota_invariants",
    "assert_factory_conformity_invariants",
    "assert_test_result",
    "assert_component_entry",
    "assert_finding_entry",
]


def _enum_values(enum_cls) -> List[str]:
    return [member.value for member in enum_cls]


def assert_common_fields(data: Dict[str, Any], context: str = "resource") -> None:
    """The four system-managed properties every resource carries (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{context}: id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{context}: created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{context}: updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{context}: version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_optional_instant(data: Dict[str, Any], field: str, context: str) -> None:
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{context}: {field} must be null or ISO 8601, got {value!r}"
    )


def _assert_non_empty_str(data: Dict[str, Any], field: str, context: str) -> None:
    assert isinstance(data.get(field), str) and len(data[field]) > 0, (
        f"{context}: {field} must be a non-empty string, got {data.get(field)!r}"
    )


# ── Nested shapes ──────────────────────────────────────────────────────────

def assert_test_result(entry: Dict[str, Any], context: str = "result") -> None:
    _assert_non_empty_str(entry, "protocol_code", context)
    assert isinstance(entry.get("measured_value"), (int, float)), (
        f"{context}: measured_value must be numeric, got {entry.get('measured_value')!r}"
    )
    assert entry.get("outcome") in _enum_values(t.TestOutcome), (
        f"{context}: outcome must be PASS/CONDITIONAL/FAIL, got {entry.get('outcome')!r}"
    )
    assert isinstance(entry.get("margin"), (int, float)), (
        f"{context}: margin must be numeric, got {entry.get('margin')!r}"
    )
    _assert_non_empty_str(entry, "recorded_by", context)
    assert is_iso8601_timestamp(entry.get("recorded_at", "")), (
        f"{context}: recorded_at must be ISO 8601, got {entry.get('recorded_at')!r}"
    )


def assert_component_entry(entry: Dict[str, Any], context: str = "component") -> None:
    for field in ("slot", "component_name", "material", "part_number", "rating"):
        assert field in entry, f"{context}: missing field {field!r}"
        assert isinstance(entry[field], str), (
            f"{context}: {field} must be a string, got {entry[field]!r}"
        )


def assert_finding_entry(entry: Dict[str, Any], context: str = "finding") -> None:
    _assert_non_empty_str(entry, "finding_ref", context)
    assert entry.get("severity") in _enum_values(t.FindingSeverity), (
        f"{context}: severity must be CRITICAL/MAJOR/MINOR, got {entry.get('severity')!r}"
    )
    _assert_non_empty_str(entry, "description", context)
    # certification_id is optional on a finding.
    if "certification_id" in entry and entry["certification_id"] is not None:
        assert isinstance(entry["certification_id"], str), (
            f"{context}: certification_id must be a string when present"
        )


# ── Entities ───────────────────────────────────────────────────────────────

def assert_manufacturer(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Manufacturer")
    _assert_non_empty_str(data, "legal_name", "Manufacturer")
    _assert_non_empty_str(data, "home_jurisdiction_code", "Manufacturer")
    assert data.get("annual_revenue_tier") in _enum_values(t.RevenueTier), (
        f"Manufacturer: bad annual_revenue_tier {data.get('annual_revenue_tier')!r}"
    )
    assert data.get("status") in _enum_values(t.ManufacturerStatus), (
        f"Manufacturer: bad status {data.get('status')!r}"
    )
    assert data.get("suspension_reason") is None or isinstance(data["suspension_reason"], str)


def assert_factory(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Factory")
    _assert_non_empty_str(data, "manufacturer_id", "Factory")
    _assert_non_empty_str(data, "site_code", "Factory")
    _assert_non_empty_str(data, "country_code", "Factory")
    _assert_non_empty_str(data, "jurisdiction_code", "Factory")
    assert data.get("conformity_regime") in _enum_values(t.ConformityRegime), (
        f"Factory: bad conformity_regime {data.get('conformity_regime')!r}"
    )
    assert isinstance(data.get("open_critical_findings"), int) and data["open_critical_findings"] >= 0
    _assert_optional_instant(data, "last_inspection_completed_on", "Factory")
    _assert_optional_instant(data, "next_inspection_due_on", "Factory")
    assert_factory_conformity_invariants(data)


def assert_factory_conformity_invariants(data: Dict[str, Any]) -> None:
    """Score bounds from PRD 3.6: 100 minus penalties, never below zero."""
    score = data.get("conformity_score")
    assert isinstance(score, (int, float)), f"Factory: conformity_score must be numeric, got {score!r}"
    assert 0 <= score <= 100, f"Factory: conformity_score {score} outside [0, 100]"


def assert_standard(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Standard")
    _assert_non_empty_str(data, "category_code", "Standard")
    _assert_non_empty_str(data, "standard_code", "Standard")
    _assert_non_empty_str(data, "edition_label", "Standard")
    assert is_iso8601_timestamp(data.get("effective_from", "")), (
        f"Standard: effective_from must be ISO 8601, got {data.get('effective_from')!r}"
    )
    _assert_optional_instant(data, "effective_to", "Standard")
    assert isinstance(data.get("construction_requirements"), list)
    assert all(isinstance(slot, str) for slot in data["construction_requirements"])
    protocols = data.get("test_protocols")
    assert isinstance(protocols, list), "Standard: test_protocols must be a list"
    for protocol in protocols:
        _assert_non_empty_str(protocol, "protocol_code", "test_protocols entry")
        assert isinstance(protocol.get("mandatory"), bool)
        assert isinstance(protocol.get("safety_critical"), bool)
        assert isinstance(protocol.get("pass_threshold"), (int, float))
        assert isinstance(protocol.get("base_fee_cents"), int)
    assert data.get("status") in _enum_values(t.StandardStatus), (
        f"Standard: bad status {data.get('status')!r}"
    )


def assert_jurisdiction(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Jurisdiction")
    _assert_non_empty_str(data, "jurisdiction_code", "Jurisdiction")
    _assert_non_empty_str(data, "name", "Jurisdiction")
    assert isinstance(data.get("accepts_field_labels"), bool)
    assert isinstance(data.get("accepts_reciprocity"), bool)
    assert isinstance(data.get("reciprocity_sources"), list)
    assert data.get("reciprocity_group") in _enum_values(t.ReciprocityGroup), (
        f"Jurisdiction: bad reciprocity_group {data.get('reciprocity_group')!r}"
    )


def assert_project(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "CertificationProject")
    _assert_non_empty_str(data, "manufacturer_id", "CertificationProject")
    _assert_non_empty_str(data, "factory_id", "CertificationProject")
    _assert_non_empty_str(data, "category_code", "CertificationProject")
    _assert_non_empty_str(data, "standard_id", "CertificationProject")
    _assert_non_empty_str(data, "product_model", "CertificationProject")
    assert isinstance(data.get("retest_count"), int) and data["retest_count"] >= 0
    fee = data.get("fee_snapshot_cents")
    assert fee is None or (isinstance(fee, int) and fee >= 0), (
        f"CertificationProject: fee_snapshot_cents must be null or non-negative int, got {fee!r}"
    )
    assert data.get("status") in _enum_values(t.ProjectStatus), (
        f"CertificationProject: bad status {data.get('status')!r}"
    )
    assert data.get("decided_by") is None or isinstance(data["decided_by"], str)
    _assert_optional_instant(data, "decided_on", "CertificationProject")


def assert_sample(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Sample")
    _assert_non_empty_str(data, "project_id", "Sample")
    _assert_non_empty_str(data, "serial_no", "Sample")
    assert data.get("condition") in _enum_values(t.SampleCondition), (
        f"Sample: bad condition {data.get('condition')!r}"
    )
    assert data.get("status") in _enum_values(t.SampleStatus), (
        f"Sample: bad status {data.get('status')!r}"
    )
    assert data.get("triaged_by") is None or isinstance(data["triaged_by"], str)
    results = data.get("results")
    assert isinstance(results, list), "Sample: results must be a list"
    for entry in results:
        assert_test_result(entry, f"Sample.results[{entry.get('protocol_code')!r}]")


def assert_construction_record(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ConstructionRecord")
    _assert_non_empty_str(data, "project_id", "ConstructionRecord")
    assert isinstance(data.get("revision_no"), int) and data["revision_no"] >= 1, (
        f"ConstructionRecord: revision_no must be >= 1, got {data.get('revision_no')!r}"
    )
    components = data.get("components")
    assert isinstance(components, list), "ConstructionRecord: components must be a list"
    for entry in components:
        assert_component_entry(entry, f"ConstructionRecord.components[{entry.get('slot')!r}]")
    assert data.get("status") in _enum_values(t.ConstructionRecordStatus), (
        f"ConstructionRecord: bad status {data.get('status')!r}"
    )


def assert_certification(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Certification")
    _assert_non_empty_str(data, "project_id", "Certification")
    _assert_non_empty_str(data, "manufacturer_id", "Certification")
    _assert_non_empty_str(data, "factory_id", "Certification")
    _assert_non_empty_str(data, "standard_id", "Certification")
    _assert_non_empty_str(data, "construction_record_id", "Certification")
    assert isinstance(data.get("construction_record_revision"), int) and data[
        "construction_record_revision"
    ] >= 1
    assert_listing_number(data.get("listing_number"))
    variations = data.get("permitted_variations")
    assert isinstance(variations, list), "Certification: permitted_variations must be a list"
    for variation in variations:
        _assert_non_empty_str(variation, "slot", "permitted_variations entry")
        assert isinstance(variation.get("allowed_alternates"), list)
    assert is_iso8601_timestamp(data.get("issued_on", "")), (
        f"Certification: issued_on must be ISO 8601, got {data.get('issued_on')!r}"
    )
    _assert_optional_instant(data, "expires_on", "Certification")
    assert data.get("status") in _enum_values(t.CertificationStatus), (
        f"Certification: bad status {data.get('status')!r}"
    )
    causes = data.get("suspension_causes")
    assert isinstance(causes, list), "Certification: suspension_causes must be a list"
    assert all(isinstance(cause, str) for cause in causes)


def assert_listing_number(value: Any) -> None:
    """Listing numbers are 'E' followed by a zero-padded six-digit sequence."""
    assert isinstance(value, str) and re.fullmatch(r"E\d{6}", value), (
        f"listing_number must match ^E\\d{{6}}$, got {value!r}"
    )


def assert_substitution_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "SubstitutionRequest")
    _assert_non_empty_str(data, "certification_id", "SubstitutionRequest")
    _assert_non_empty_str(data, "slot", "SubstitutionRequest")
    assert_component_entry(data.get("proposed_component", {}), "SubstitutionRequest.proposed_component")
    _assert_non_empty_str(data, "rationale", "SubstitutionRequest")
    assert data.get("status") in _enum_values(t.SubstitutionRequestStatus), (
        f"SubstitutionRequest: bad status {data.get('status')!r}"
    )
    assert data.get("decided_by") is None or isinstance(data["decided_by"], str)
    _assert_optional_instant(data, "decided_on", "SubstitutionRequest")


def assert_inspection(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "FollowUpInspection")
    _assert_non_empty_str(data, "factory_id", "FollowUpInspection")
    assert is_iso8601_timestamp(data.get("scheduled_for", "")), (
        f"FollowUpInspection: scheduled_for must be ISO 8601, got {data.get('scheduled_for')!r}"
    )
    _assert_non_empty_str(data, "inspector_ref", "FollowUpInspection")
    _assert_optional_instant(data, "completed_on", "FollowUpInspection")
    assert data.get("result") is None or data["result"] in _enum_values(t.InspectionResult), (
        f"FollowUpInspection: bad result {data.get('result')!r}"
    )
    findings = data.get("findings")
    assert isinstance(findings, list), "FollowUpInspection: findings must be a list"
    for entry in findings:
        assert_finding_entry(entry, f"FollowUpInspection.findings[{entry.get('finding_ref')!r}]")
    assert data.get("status") in _enum_values(t.InspectionStatus), (
        f"FollowUpInspection: bad status {data.get('status')!r}"
    )


def assert_mark_license(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "MarkLicense")
    _assert_non_empty_str(data, "certification_id", "MarkLicense")
    assert data.get("label_type") in _enum_values(t.LabelType), (
        f"MarkLicense: bad label_type {data.get('label_type')!r}"
    )
    assert isinstance(data.get("declared_annual_volume"), int) and data["declared_annual_volume"] >= 0
    assert data.get("quota_variant") in _enum_values(t.QuotaVariant), (
        f"MarkLicense: bad quota_variant {data.get('quota_variant')!r}"
    )
    assert data.get("status") in _enum_values(t.MarkLicenseStatus), (
        f"MarkLicense: bad status {data.get('status')!r}"
    )
    assert isinstance(data.get("serial_prefix"), str) and len(data["serial_prefix"]) > 0
    assert_mark_license_quota_invariants(data)


def assert_mark_license_quota_invariants(data: Dict[str, Any]) -> None:
    """Quota accounting from PRD 3.7: used_quantity is the sum over ISSUED
    batches and can never exceed authorized_quantity; serials start at 1 and
    next_serial never rewinds; authorized_quantity is a whole lot of 100."""
    authorized = data.get("authorized_quantity")
    used = data.get("used_quantity")
    next_serial = data.get("next_serial")
    assert isinstance(authorized, int) and authorized >= 100 and authorized % 100 == 0, (
        f"MarkLicense: authorized_quantity must be a multiple of 100 >= 100, got {authorized!r}"
    )
    assert isinstance(used, int) and 0 <= used <= authorized, (
        f"MarkLicense: used_quantity {used!r} outside [0, {authorized!r}]"
    )
    assert isinstance(next_serial, int) and next_serial >= 1, (
        f"MarkLicense: next_serial must be >= 1, got {next_serial!r}"
    )


def assert_label_batch(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "LabelBatch")
    _assert_non_empty_str(data, "license_id", "LabelBatch")
    assert isinstance(data.get("quantity"), int) and data["quantity"] >= 1, (
        f"LabelBatch: quantity must be >= 1, got {data.get('quantity')!r}"
    )
    serial_start = data.get("serial_start")
    serial_end = data.get("serial_end")
    assert isinstance(serial_start, int) and serial_start >= 1
    assert isinstance(serial_end, int), "LabelBatch: serial_end must be an int"
    assert serial_end == serial_start + data["quantity"] - 1, (
        f"LabelBatch: serial_end {serial_end} != serial_start {serial_start} + quantity "
        f"{data['quantity']} - 1"
    )
    assert data.get("status") in _enum_values(t.LabelBatchStatus), (
        f"LabelBatch: bad status {data.get('status')!r}"
    )


def assert_field_evaluation(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "FieldEvaluation")
    _assert_non_empty_str(data, "manufacturer_id", "FieldEvaluation")
    _assert_non_empty_str(data, "standard_id", "FieldEvaluation")
    _assert_non_empty_str(data, "evaluating_jurisdiction_id", "FieldEvaluation")
    _assert_non_empty_str(data, "site_jurisdiction_id", "FieldEvaluation")
    _assert_non_empty_str(data, "equipment_description", "FieldEvaluation")
    _assert_non_empty_str(data, "site_address", "FieldEvaluation")
    assert data.get("eval_status") in _enum_values(t.EvalStatus), (
        f"FieldEvaluation: bad eval_status {data.get('eval_status')!r}"
    )
    assert data.get("acceptance_status") in _enum_values(t.AcceptanceStatus), (
        f"FieldEvaluation: bad acceptance_status {data.get('acceptance_status')!r}"
    )
    assert data.get("evaluated_by") is None or isinstance(data["evaluated_by"], str)
    assert data.get("ahj_decided_by") is None or isinstance(data["ahj_decided_by"], str)
    _assert_optional_instant(data, "label_issued_on", "FieldEvaluation")


def assert_withdrawal_notice(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "WithdrawalNotice")
    _assert_non_empty_str(data, "certification_id", "WithdrawalNotice")
    assert data.get("reason_code") in _enum_values(t.WithdrawalReasonCode), (
        f"WithdrawalNotice: bad reason_code {data.get('reason_code')!r}"
    )
    _assert_non_empty_str(data, "public_text", "WithdrawalNotice")
    _assert_optional_instant(data, "published_on", "WithdrawalNotice")
    _assert_optional_instant(data, "effective_on", "WithdrawalNotice")
    assert data.get("status") in _enum_values(t.WithdrawalNoticeStatus), (
        f"WithdrawalNotice: bad status {data.get('status')!r}"
    )
