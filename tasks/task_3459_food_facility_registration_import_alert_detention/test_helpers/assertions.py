"""Entity assertions and domain invariant checkers.

Structural assertions follow PRD §2.5 (common fields) and the per-entity field
inventories of PRD §3. Nullable system fields (e.g. a prior notice's
``parent_pn_id`` on initial filings, an entry's ``detained_at`` while
non-detained) are checked for presence with None allowed.
"""

import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_FFR_RE = re.compile(r"^FFR-\d{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_nullable_iso(data: dict, field: str):
    assert field in data, f"missing field {field!r}"
    value = data[field]
    if value is not None:
        assert is_iso8601_timestamp(value), f"{field} must be ISO 8601, got {value!r}"


def _assert_nullable_uuid(data: dict, field: str):
    assert field in data, f"missing field {field!r}"
    value = data[field]
    if value is not None:
        assert is_valid_uuid(value), f"{field} must be a UUID, got {value!r}"


# ---------------------------------------------------------------------------
# Facility (PRD §3.1)
# ---------------------------------------------------------------------------


def assert_registration_number(value: str):
    assert isinstance(value, str) and _FFR_RE.match(value), (
        f"registration_number must match FFR-NNNNNN, got {value!r}"
    )


def assert_facility(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["facility_kind"] in ("DOMESTIC", "FOREIGN")
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert isinstance(data["ufi"], str) and data["ufi"]
    assert_registration_number(data["registration_number"])
    assert data["registration_status"] in ("REGISTERED", "EXPIRED", "SUSPENDED")
    assert is_iso8601_timestamp(data["registered_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["violation_count"], int) and data["violation_count"] >= 0
    assert (
        isinstance(data["open_detention_count"], int)
        and data["open_detention_count"] >= 0
    )


# ---------------------------------------------------------------------------
# ImporterFirm / Laboratory (PRD §3.2)
# ---------------------------------------------------------------------------


def assert_importer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["firm_name"], str) and data["firm_name"]
    assert isinstance(data["account_code"], str) and data["account_code"]
    assert data["standing"] in ("GOOD_STANDING", "PROBATION", "REVOKED")
    assert isinstance(data["refusal_count"], int) and data["refusal_count"] >= 0
    assert (
        isinstance(data["terminal_entry_count"], int)
        and data["terminal_entry_count"] >= 0
    )


def assert_laboratory(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lab_code"], str) and data["lab_code"]
    assert (
        isinstance(data["daily_sample_capacity"], int)
        and data["daily_sample_capacity"] > 0
    )


# ---------------------------------------------------------------------------
# PriorNotice (PRD §3.3)
# ---------------------------------------------------------------------------


def assert_prior_notice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["importer_id"])
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data["product_risk_class"] in ("LOW", "STANDARD", "HIGH")
    assert data["transport_mode"] in ("VESSEL", "AIR", "RAIL", "ROAD")
    assert is_iso8601_timestamp(data["arrival_eta"])
    assert isinstance(data["declared_units"], int) and data["declared_units"] > 0
    assert isinstance(data["unit_value_cents"], int) and data["unit_value_cents"] >= 0
    assert isinstance(data["port_code"], str) and data["port_code"]
    assert data["status"] in ("CONFIRMED", "SUPERSEDED", "COMPROMISED", "CONSUMED")
    assert isinstance(data["is_amendment"], bool)
    _assert_nullable_uuid(data, "parent_pn_id")


# ---------------------------------------------------------------------------
# ImportEntry (PRD §3.4–§3.6)
# ---------------------------------------------------------------------------


def assert_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["prior_notice_id"])
    assert is_valid_uuid(data["importer_id"])
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data["product_risk_class"] in ("LOW", "STANDARD", "HIGH")
    assert isinstance(data["declared_units"], int) and data["declared_units"] > 0
    assert isinstance(data["unit_value_cents"], int) and data["unit_value_cents"] >= 0
    assert isinstance(data["is_amendment_pn"], bool)
    assert data["review_status"] in ("PENDING_SCREENING", "SCREENED")
    assert data["disposition_status"] in (
        "PENDING",
        "DETAINED",
        "RELEASED",
        "REFUSED",
        "EXPORTED",
        "RECONDITIONED",
    )
    assert data["screening_decision"] in ("NONE", "RELEASE", "SAMPLE", "DETAIN")
    assert "screening_score" in data
    if data["screening_score"] is not None:
        assert isinstance(data["screening_score"], int)
        assert 0 <= data["screening_score"] <= 100
    assert "scoring_variant_applied" in data
    if data["scoring_variant_applied"] is not None:
        assert data["scoring_variant_applied"] in ("BASE", "HISTORY_WEIGHTED")
    assert data["probation_adjustment_applied"] in (0, 15)
    _assert_nullable_iso(data, "detained_at")
    _assert_nullable_iso(data, "response_deadline_at")
    _assert_nullable_uuid(data, "detained_under_alert_id")
    for bucket in (
        "units_held",
        "units_released",
        "units_refused",
        "units_exported",
        "units_destroyed",
    ):
        assert isinstance(data[bucket], int) and data[bucket] >= 0, (
            f"{bucket} must be a non-negative integer, got {data[bucket]!r}"
        )
    assert "bond_amount_cents" in data
    if data["bond_amount_cents"] is not None:
        assert isinstance(data["bond_amount_cents"], int)
        assert data["bond_amount_cents"] >= 0
    _assert_nullable_iso(data, "disposition_completed_at")


def assert_entry_units_conserved(data: dict):
    """PRD §2.8: the five unit buckets always sum to declared_units."""
    total = (
        data["units_held"]
        + data["units_released"]
        + data["units_refused"]
        + data["units_exported"]
        + data["units_destroyed"]
    )
    assert total == data["declared_units"], (
        f"unit buckets sum to {total}, expected declared_units "
        f"{data['declared_units']}"
    )


# ---------------------------------------------------------------------------
# SampleAnalysis (PRD §3.5)
# ---------------------------------------------------------------------------


def assert_sample(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["entry_id"])
    assert isinstance(data["lab_code"], str) and data["lab_code"]
    assert isinstance(data["sample_units"], int) and data["sample_units"] > 0
    assert isinstance(data["analysis_date"], str) and _DATE_RE.match(
        data["analysis_date"]
    ), f"analysis_date must be YYYY-MM-DD, got {data['analysis_date']!r}"
    assert data["status"] in ("SCHEDULED", "RESULT_RECORDED")
    assert data["result"] in ("PENDING", "COMPLIANT", "VIOLATIVE")


# ---------------------------------------------------------------------------
# ImportAlert / AlertPetition (PRD §3.7)
# ---------------------------------------------------------------------------


def assert_import_alert(data: dict):
    _assert_common_fields(data)
    assert data["scope_type"] in ("FIRM", "COUNTRY_PRODUCT")
    if data["scope_type"] == "FIRM":
        _assert_nullable_uuid(data, "facility_id")
        assert data.get("country_code") is None
        assert data.get("product_code") is None
    else:
        assert data.get("facility_id") is None
        assert isinstance(data["country_code"], str)
        assert isinstance(data["product_code"], str)
    assert isinstance(data["reason"], str)
    assert data["status"] in ("ACTIVE", "LIFTED")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    _assert_nullable_iso(data, "lifted_at")


def assert_alert_petition(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["alert_id"])
    assert is_valid_uuid(data["filed_by_facility_id"])
    assert isinstance(data["evidence_links"], list)
    assert data["status"] in ("EVIDENCE_REVIEW", "APPROVED", "DENIED")
    assert "consecutive_compliant_count" in data
    if data["consecutive_compliant_count"] is not None:
        assert isinstance(data["consecutive_compliant_count"], int)
        assert data["consecutive_compliant_count"] >= 0


# ---------------------------------------------------------------------------
# Inspection (PRD §3.8)
# ---------------------------------------------------------------------------


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["inspector_user_id"], str) and data["inspector_user_id"]
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert data["scheduled_end_at"] > data["scheduled_start_at"]
    assert data["status"] in ("SCHEDULED", "COMPLETED", "REFUSED_BY_FACILITY")
    # findings_violation_count is recorded at completion; before that it may be
    # absent or null. When present it must be a non-negative integer.
    if data.get("findings_violation_count") is not None:
        assert isinstance(data["findings_violation_count"], int)
        assert data["findings_violation_count"] >= 0


# ---------------------------------------------------------------------------
# Recall (PRD §3.9)
# ---------------------------------------------------------------------------


def assert_recall(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert (
        isinstance(data["quantity_distributed"], int)
        and data["quantity_distributed"] > 0
    )
    assert data["classification"] in ("NONE", "CLASS_I", "CLASS_II", "CLASS_III")
    assert data["status"] in ("INITIATED", "CLASSIFIED", "TERMINATED")
    for field in (
        "quantity_recovered",
        "quantity_corrected",
        "quantity_destroyed",
        "quantity_outstanding",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data[field]!r}"
        )
    assert isinstance(data["effectiveness_pct"], (int, float))
    assert 0.0 <= data["effectiveness_pct"] <= 100.0
    assert (
        isinstance(data["consignees_contacted"], int)
        and data["consignees_contacted"] >= 0
    )
    assert isinstance(data["consignees_total"], int) and data["consignees_total"] >= 0
    assert isinstance(data["consignee_contact_pct"], (int, float))
    assert 0.0 <= data["consignee_contact_pct"] <= 100.0


def assert_recall_quantities_conserved(data: dict):
    """PRD §2.8: accounted buckets plus outstanding always equal distributed."""
    total = (
        data["quantity_recovered"]
        + data["quantity_corrected"]
        + data["quantity_destroyed"]
        + data["quantity_outstanding"]
    )
    assert total == data["quantity_distributed"], (
        f"quantity buckets sum to {total}, expected quantity_distributed "
        f"{data['quantity_distributed']}"
    )
