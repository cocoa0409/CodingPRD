"""Entity assertions and domain invariant checkers (PRD §2.5 common fields)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant tolerant of 'Z' vs '+00:00' and fractional digits.

    PRD pins instants, not serialization cosmetics, so tests compare parsed
    instants rather than raw strings.
    """
    assert isinstance(value, str) and value.strip(), f"expected ISO instant string, got {value!r}"
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_photographer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["photographer_type"] in ("STAFF", "FREELANCE")
    assert isinstance(data["day_rate_cents"], int)
    assert isinstance(data["per_image_fee_cents"], int)
    assert isinstance(data["royalty_rate_per_use_cents"], int)
    assert isinstance(data["rights_reversion_months"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["accrued_earnings_cents"], int) and data["accrued_earnings_cents"] >= 0
    assert isinstance(data["paid_out_cents"], int)


def assert_story_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["headline"], str) and data["headline"]
    assert isinstance(data["slug"], str) and data["slug"]
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert data["status"] in ("OPEN", "DECIDED", "FULFILLED", "CANCELLED")


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("story_request_id", ""))
    assert is_valid_uuid(data.get("photographer_id", ""))
    assert isinstance(data["brief"], str)
    assert isinstance(data["day_count"], int) and data["day_count"] >= 1
    assert isinstance(data["min_image_count"], int)
    assert isinstance(data["max_image_count"], int)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["kill_fee_cents"], int)
    assert data["status"] in (
        "COMMISSIONED", "IN_PROGRESS", "SUBMITTED",
        "REVISION_REQUESTED", "ACCEPTED", "CANCELLED",
    )


def assert_image(data: dict):
    _assert_common_fields(data)
    assert data["source_type"] in ("ASSIGNMENT", "WIRE", "STOCK")
    assert isinstance(data["base_license_fee_cents"], int)
    assert isinstance(data["times_used"], int) and data["times_used"] >= 0
    assert isinstance(data["rights_reverted"], bool)
    assert data["status"] in ("INGESTED", "CLEARED", "PUBLISHED", "ARCHIVED")
    assert data["restriction_status"] in ("NONE", "RESTRICTED")


def assert_license(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("image_id", ""))
    assert data["usage_scope"] in ("PRINT", "DIGITAL", "SOCIAL", "SYNDICATION")
    assert data["territory"] in ("DOMESTIC", "INTERNATIONAL", "GLOBAL")
    assert isinstance(data["exclusive"], bool)
    assert data["pricing_variant"] in ("FIRST_USE", "REUSE")
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "REVOKED")


def assert_release_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("image_id", ""))
    assert data["subject_type"] in ("MODEL", "PROPERTY")
    assert isinstance(data["subject_name"], str) and data["subject_name"]
    assert isinstance(data["document_ref"], str) and data["document_ref"]
    assert data["status"] in ("ACTIVE", "REVOKED", "EXPIRED")


def assert_usage_run(data: dict):
    """UsageRun is the immutable ledger entry of PRD §2.5: id + created_at only,
    no updated_at and no version field."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "UsageRun must not carry updated_at"
    assert "version" not in data, "UsageRun must not carry version"
    assert is_valid_uuid(data.get("image_id", ""))
    assert is_valid_uuid(data.get("license_id", ""))
    assert data["channel"] in ("PRINT", "DIGITAL", "SOCIAL", "SYNDICATION")
    assert isinstance(data["story_slug"], str) and data["story_slug"]
    assert isinstance(data["royalty_cents"], int) and data["royalty_cents"] >= 0


def assert_infringement_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("image_id", ""))
    assert isinstance(data["claimant_name"], str) and data["claimant_name"]
    assert data["claim_type"] in (
        "UNLICENSED_USE", "COPYRIGHT_DISPUTE", "MODEL_RELEASE_VIOLATION",
    )
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["intaken_by_user_id"], str) and data["intaken_by_user_id"]
    assert data["status"] in (
        "INTAKE", "UNDER_REVIEW", "SETTLEMENT_OFFERED", "COUNTERED",
        "ESCALATED", "RESOLVED", "DISMISSED",
    )


def assert_payment_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("photographer_id", ""))
    assert data["method"] in ("GUARANTEE", "ROYALTY")
    assert isinstance(data["guarantee_amount_cents"], int)
    assert isinstance(data["royalty_amount_cents"], int)
    assert isinstance(data["clawback_cents"], int)
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert data["status"] in ("DRAFT", "APPROVED", "PAID", "VOIDED")
