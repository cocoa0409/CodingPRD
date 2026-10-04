"""Entity assertions and domain invariant checkers.

``assert_success`` deliberately takes the expected HTTP status as a required
argument: this API returns 201 for creates and 200 for modifications and
reads, and a defaulted status would silently corrupt half the assertions.
``assert_created`` / ``assert_ok`` are the two explicit conveniences.

Timestamps the API reports come from the logical clock; comparisons go
through ``canonical_instant`` so two spellings of one instant
(``...T00:00:00Z`` and ``...T00:00:00.000Z``) compare equal.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .types import (
    CertificationStatus,
    CheckStatus,
    ConvictionSeverity,
    DisqualificationBasis,
    DisqualificationStatus,
    FeeTier,
    InvoiceStatus,
    LawfulStatusBasis,
    LicenseClass,
    LicenseStatus,
    MembershipStatus,
    ParticipationStatus,
    RecordStatus,
    SystemName,
    TitleBrand,
    TitleStatus,
    TitleTransferStatus,
    TransferStatus,
)


# ── Response-level validators ────────────────────────────────────────────────

def assert_success(response: requests.Response, expected_status: int) -> Dict[str, Any]:
    """Validate a success envelope; the expected status is mandatory.

    Creates in this API answer 201; modifications and reads answer 200.
    """
    return validate_success(response, expected_status)


def assert_created(response: requests.Response) -> Dict[str, Any]:
    """Validate a 201 creation response and return its data payload."""
    return validate_success(response, 201)


def assert_ok(response: requests.Response) -> Dict[str, Any]:
    """Validate a 200 modification/read response and return its data payload."""
    return validate_success(response, 200)


def assert_error(response: requests.Response, error_id) -> Dict[str, Any]:
    """Validate an error envelope; the HTTP status is cross-checked against
    the registered catalogue for this error id."""
    return validate_error(response, str(getattr(error_id, "value", error_id)))


def assert_list_page(response: requests.Response):
    """Validate a paginated list response; returns (rows, meta)."""
    return validate_paginated(response)


# ── Instant normalisation ────────────────────────────────────────────────────

def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to ``YYYY-MM-DDTHH:MM:SS.mmmZ`` so
    two spellings of one instant compare equal."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


def assert_same_instant(actual: Optional[str], expected: str, label: str = "instant") -> None:
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {canonical_instant(expected)}, got {canonical_instant(actual)}"
    )


# ── Common-field helpers ─────────────────────────────────────────────────────

def assert_mutable_common_fields(data: Dict[str, Any]) -> None:
    """id + created_at + updated_at + version, per the common-field rules."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_nullable_instant(data: Dict[str, Any], field: str) -> None:
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or an ISO 8601 timestamp, got {value!r}"
    )


# ── Per-entity assertions ────────────────────────────────────────────────────

def assert_jurisdiction(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) == 2
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["fee_tier"] in {t.value for t in FeeTier}
    assert data["membership_status"] in {s.value for s in MembershipStatus}
    assert isinstance(data["certified_systems_count"], int) and data["certified_systems_count"] >= 0
    assert isinstance(data["timeliness_score_bp"], int) and 0 <= data["timeliness_score_bp"] <= 10000


def assert_participation(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("jurisdiction_id", "")), "jurisdiction_id must be a UUID"
    assert data["system"] in {s.value for s in SystemName}
    assert data["status"] in {s.value for s in ParticipationStatus}
    _assert_nullable_instant(data, "granted_at")
    _assert_nullable_instant(data, "suspended_at")


def assert_certification(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("participation_id", "")), "participation_id must be a UUID"
    assert is_iso8601_timestamp(data.get("window_start", "")), "window_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("window_end", "")), "window_end must be ISO 8601"
    assert data["status"] in {s.value for s in CertificationStatus}
    if data["status"] == CertificationStatus.SCHEDULED.value:
        assert data.get("score") is None and data.get("completed_at") is None, (
            "a SCHEDULED certification keeps score and completed_at null"
        )
    else:
        if data.get("score") is not None:
            assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
        assert is_iso8601_timestamp(data.get("completed_at", "")), (
            "a completed certification records completed_at"
        )


def assert_driver_identity(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str) and len(data["date_of_birth"]) == 10
    assert isinstance(data["ssn_last4_hash"], str) and len(data["ssn_last4_hash"]) > 0
    assert data["lawful_status_basis"] in {b.value for b in LawfulStatusBasis}


def assert_driver_record(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a UUID"
    assert is_valid_uuid(data.get("holding_jurisdiction_id", "")), (
        "holding_jurisdiction_id must be a UUID"
    )
    assert data["status"] in {s.value for s in RecordStatus}
    assert isinstance(data["points_total"], int) and data["points_total"] >= 0
    assert isinstance(data["abstract_points_total"], int) and data["abstract_points_total"] >= 0


def assert_conviction(data: Dict[str, Any]) -> None:
    """Convictions are immutable: they carry id and created_at only — the
    response must NOT carry updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "an immutable conviction carries no updated_at"
    assert "version" not in data, "an immutable conviction carries no version"
    assert is_valid_uuid(data.get("record_id", "")), "record_id must be a UUID"
    assert isinstance(data["offense_date"], str) and len(data["offense_date"]) == 10
    assert isinstance(data["conviction_date"], str) and len(data["conviction_date"]) == 10
    assert data["severity"] in {s.value for s in ConvictionSeverity}
    assert isinstance(data["points"], int) and 1 <= data["points"] <= 6
    assert is_iso8601_timestamp(data.get("posted_at", "")), "posted_at must be ISO 8601"
    assert isinstance(data["is_late"], bool)


def assert_disqualification(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("record_id", "")), "record_id must be a UUID"
    assert data["basis"] in {b.value for b in DisqualificationBasis}
    assert isinstance(data["start_date"], str) and len(data["start_date"]) == 10
    assert isinstance(data["end_date"], str) and len(data["end_date"]) == 10
    assert data["end_date"] >= data["start_date"], "end_date must not precede start_date"
    assert data["status"] in {s.value for s in DisqualificationStatus}
    _assert_nullable_instant(data, "overturned_at")
    if data["status"] == DisqualificationStatus.OVERTURNED.value:
        assert data.get("overturned_at") is not None, (
            "an OVERTURNED disqualification records overturned_at"
        )


def assert_license(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a UUID"
    assert is_valid_uuid(data.get("issuing_jurisdiction_id", "")), (
        "issuing_jurisdiction_id must be a UUID"
    )
    assert is_valid_uuid(data.get("record_id", "")), "record_id must be a UUID"
    assert data["license_class"] in {c.value for c in LicenseClass}
    assert data["status"] in {s.value for s in LicenseStatus}
    assert data["ssn_check_status"] in {s.value for s in CheckStatus}
    assert data["lawful_status_check_status"] in {s.value for s in CheckStatus}


def assert_license_transfer(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a UUID"
    assert is_valid_uuid(data.get("from_jurisdiction_id", "")), "from_jurisdiction_id must be a UUID"
    assert is_valid_uuid(data.get("to_jurisdiction_id", "")), "to_jurisdiction_id must be a UUID"
    assert is_valid_uuid(data.get("prior_license_id", "")), "prior_license_id must be a UUID"
    assert data["status"] in {s.value for s in TransferStatus}
    if data["status"] == TransferStatus.COMPLETED.value:
        assert is_valid_uuid(data.get("new_license_id", "")), (
            "a COMPLETED transfer records new_license_id"
        )
    else:
        assert data.get("new_license_id") is None, (
            "new_license_id stays null until COMPLETED"
        )
    if data["status"] == TransferStatus.CONTESTED.value:
        assert isinstance(data.get("contest_reason"), str) and data["contest_reason"], (
            "a CONTESTED transfer records contest_reason"
        )


def assert_vehicle_title(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17
    assert is_valid_uuid(data.get("holding_jurisdiction_id", "")), (
        "holding_jurisdiction_id must be a UUID"
    )
    assert isinstance(data["brands"], list)
    assert set(data["brands"]) <= {b.value for b in TitleBrand}
    assert data["status"] in {s.value for s in TitleStatus}
    assert isinstance(data["washing_alert"], bool)


def assert_title_transfer(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("vehicle_title_id", "")), "vehicle_title_id must be a UUID"
    assert is_valid_uuid(data.get("to_jurisdiction_id", "")), "to_jurisdiction_id must be a UUID"
    assert isinstance(data["disclosed_brands"], list)
    assert set(data["disclosed_brands"]) <= {b.value for b in TitleBrand}
    assert isinstance(data["carried_brands"], list)
    assert set(data["carried_brands"]) <= {b.value for b in TitleBrand}
    assert data["carried_brands"] == sorted(set(data["carried_brands"])), (
        "carried_brands is the alphabetically sorted union"
    )
    assert data["status"] in {s.value for s in TitleTransferStatus}
    if data["status"] == TitleTransferStatus.COMPLETED.value:
        assert is_valid_uuid(data.get("new_title_id", "")), (
            "a COMPLETED title transfer records new_title_id"
        )
    else:
        assert data.get("new_title_id") is None, "new_title_id stays null until COMPLETED"


def assert_fee_invoice(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("jurisdiction_id", "")), "jurisdiction_id must be a UUID"
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["projected_volume"], int) and data["projected_volume"] >= 0
    assert isinstance(data["certified_count_at_issue"], int) and data["certified_count_at_issue"] >= 0
    assert isinstance(data["provisional_amount_cents"], int) and data["provisional_amount_cents"] >= 0
    assert data["status"] in {s.value for s in InvoiceStatus}
    assert data.get("dispute_reason") is None or isinstance(data["dispute_reason"], str)
    if data["status"] == InvoiceStatus.DISPUTED.value:
        assert isinstance(data.get("dispute_reason"), str) and data["dispute_reason"], (
            "a DISPUTED invoice records dispute_reason"
        )
    if data["status"] in (InvoiceStatus.SETTLED.value, InvoiceStatus.AUDITED.value):
        assert isinstance(data.get("settled_amount_cents"), int), (
            "a settled invoice records settled_amount_cents"
        )
    if data["status"] == InvoiceStatus.AUDITED.value:
        quarters = data.get("actual_volume_quarters")
        assert isinstance(quarters, list) and len(quarters) == 4, (
            "an audited invoice records exactly four quarterly volumes"
        )
        assert all(isinstance(q, int) and q >= 0 for q in quarters)
        assert isinstance(data.get("final_amount_cents"), int)
        assert isinstance(data.get("adjustment_amount_cents"), int)
        assert data["final_amount_cents"] - data["settled_amount_cents"] == data["adjustment_amount_cents"], (
            "adjustment_amount_cents reconciles final minus settled"
        )
