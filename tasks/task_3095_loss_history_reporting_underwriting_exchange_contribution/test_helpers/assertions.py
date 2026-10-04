"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AuditEventType,
    BatchStatus,
    CarrierStatus,
    ClaimStatus,
    ClaimStatusCode,
    DisputeStatus,
    LossType,
    MatchDisposition,
    MatchGrade,
    NoticeStatus,
    ReportBlockedReason,
    ReportStatus,
)


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version on a primary resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_carrier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["naic_code"], str) and data["naic_code"]
    assert data["status"] in [s.value for s in CarrierStatus]
    assert isinstance(data["accepted_batch_count"], int)
    assert isinstance(data["accepted_claim_count"], int)


def assert_consumer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["address_line"], str) and data["address_line"]
    assert isinstance(data["driver_license_number"], str) and data["driver_license_number"]
    assert isinstance(data["file_frozen"], bool)
    assert data.get("frozen_until") is None or is_iso8601_timestamp(data["frozen_until"])


def assert_batch(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in BatchStatus]
    assert isinstance(data["claim_count"], int)
    assert isinstance(data["accepted_count"], int)
    assert isinstance(data["rejected_count"], int)
    assert is_iso8601_timestamp(data["submitted_at"])


def assert_claim(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in ClaimStatus]
    assert data["loss_type"] in [s.value for s in LossType]
    assert data["claim_status_code"] in [s.value for s in ClaimStatusCode]
    assert isinstance(data["paid_amount_cents"], int) and data["paid_amount_cents"] >= 0


def assert_inquiry(data: dict):
    assert_common_fields(data)
    assert data["match_disposition"] in [s.value for s in MatchDisposition]
    assert data["report_blocked_reason"] in [s.value for s in ReportBlockedReason]
    assert isinstance(data["match_score"], int)
    if data["individual_match_grade"] is not None:
        assert data["individual_match_grade"] in [g.value for g in MatchGrade]
        assert data["address_match_grade"] in [g.value for g in MatchGrade]
        assert data["vehicle_match_grade"] in [g.value for g in MatchGrade]


def assert_report(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in ReportStatus]
    assert data["match_disposition"] in [
        MatchDisposition.DEFINITE.value,
        MatchDisposition.PROBABLE.value,
        MatchDisposition.POSSIBLE.value,
    ]
    assert isinstance(data["risk_score_count"], int)
    assert isinstance(data["risk_score_premium_weighted_cents"], int)
    assert isinstance(data["claim_count_reported"], int)
    assert is_iso8601_timestamp(data["delivered_at"])


def assert_report_entry(data: dict):
    # Snapshot kind: id + created_at only; updated_at / version are absent.
    assert is_valid_uuid(data.get("id", "")), "entry id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "entry created_at must be ISO 8601"
    assert "updated_at" not in data, "snapshot entries must not carry updated_at"
    assert "version" not in data, "snapshot entries must not carry version"
    assert isinstance(data["entry_sequence"], int) and data["entry_sequence"] >= 1
    assert isinstance(data["paid_amount_cents"], int)


def assert_dispute(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in DisputeStatus]
    assert is_iso8601_timestamp(data["filed_at"])
    assert is_iso8601_timestamp(data["reinvestigation_due_at"])


def assert_notice(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in NoticeStatus]
    assert isinstance(data["report_influence_rank"], int)
    assert is_iso8601_timestamp(data["disclosure_deadline"])


def assert_audit_event(data: dict):
    # Snapshot kind: id + created_at only; updated_at / version are absent.
    assert is_valid_uuid(data.get("id", "")), "event id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "event created_at must be ISO 8601"
    assert "updated_at" not in data, "audit events must not carry updated_at"
    assert "version" not in data, "audit events must not carry version"
    assert data["event_type"] in [e.value for e in AuditEventType]
    assert is_iso8601_timestamp(data["event_at"])
