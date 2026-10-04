"""Per-entity assertions and domain invariant checkers.

Timestamp discipline (PRD §2.4/§2.5) — TWO families, never a uniform format:
- Bookkeeping timestamps (created_at, updated_at, envelope
  api_request_timestamp): ISO 8601 UTC with EXACTLY three fractional digits.
- Domain datetimes stamped from the logical clock (comment_opened_at,
  ballot_opened_at, cast_at, settled_at, returned_at, response_deadline,
  submitted_at, paid_at): rendered as the clock reads — asserted ISO 8601 only.
- Date-only fields render as YYYY-MM-DD.

Common-fields discipline (PRD §2.5): SettlementWindow, ReturnRecord and
AccountValidation carry ONLY id + created_at; assertions on them require the
ABSENCE of updated_at and version.
"""

import re

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from . import constants as C
from .types import (
    REASON_CLASS_BY_CODE,
    AccountValidationStatus,
    AuditReportStatus,
    AuthorizationType,
    BallotOutcome,
    BallotStatus,
    ComplianceAttestationStatus,
    EnforcementActionStatus,
    EntryClass,
    GuidanceDocumentStatus,
    InquiryCaseStatus,
    InquiryReturnClass,
    OriginatorStatus,
    ParticipantStatus,
    ParticipantType,
    PaymentEntryStatus,
    ReturnRateSnapshotStatus,
    ReturnReasonClass,
    ReturnReasonCode,
    RiskTier,
    RuleProposalStatus,
    ValidationMethod,
    ViolationCode,
    Vote,
)

_BOOKKEEPING_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CUTOFF_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_ROUTING_RE = re.compile(r"^\d{9}$")
_CODE_RE = re.compile(r"^[A-Z]{2,3}$")


# =============================================================================
# Scalar / format assertions
# =============================================================================


def validate_create_success(response) -> dict:
    """Success validator for POST-create endpoints (PRD §4: creates return 201).

    All other call sites pass their expected status explicitly to the
    framework's validate_success(response, expected_status) — no global default
    is assumed anywhere in the suite.
    """
    return validate_success(response, expected_status=201)


def assert_bookkeeping_timestamp(value, field="timestamp"):
    """Bookkeeping family: exactly three fractional digits (created_at,
    updated_at, api_request_timestamp)."""
    assert isinstance(value, str) and _BOOKKEEPING_TS_RE.match(value), (
        f"{field} must be ISO 8601 UTC with exactly 3 fractional digits, got {value!r}"
    )


def assert_logical_timestamp(value, field="timestamp"):
    """Domain family: a logical-clock stamp, ISO 8601, no forced milliseconds."""
    assert is_iso8601_timestamp(value), f"{field} must be ISO 8601, got {value!r}"


def assert_iso_date(value, field="date"):
    assert isinstance(value, str) and _ISO_DATE_RE.match(value), (
        f"{field} must be a YYYY-MM-DD date, got {value!r}"
    )


def assert_optional_logical_timestamp(value, field="timestamp"):
    if value is not None:
        assert_logical_timestamp(value, field)


def assert_optional_iso_date(value, field="date"):
    if value is not None:
        assert_iso_date(value, field)


def assert_rate_4dp(value, field="rate"):
    """Return rates: decimal, round-half-up to exactly four decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 4) == float(value), (
        f"{field} must have at most 4 decimal places, got {value!r}"
    )


# =============================================================================
# Common-field assertions
# =============================================================================


def assert_common_fields(data, entity="resource"):
    """id + created_at + updated_at + version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert_bookkeeping_timestamp(data.get("created_at"), f"{entity}.created_at")
    assert_bookkeeping_timestamp(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_immutable_record_fields(data, entity="record"):
    """id + created_at ONLY — updated_at and version are absent entirely."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert_bookkeeping_timestamp(data.get("created_at"), f"{entity}.created_at")
    assert "updated_at" not in data, f"{entity} must NOT carry updated_at"
    assert "version" not in data, f"{entity} must NOT carry version"


# =============================================================================
# Per-entity assertions
# =============================================================================


def assert_participant(data: dict):
    assert_common_fields(data, "Participant")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["participant_type"] in {e.value for e in ParticipantType}
    assert isinstance(data["routing_number"], str) and _ROUTING_RE.match(data["routing_number"]), (
        f"routing_number must be exactly 9 digits, got {data.get('routing_number')!r}"
    )
    assert data["status"] in {e.value for e in ParticipantStatus}
    assert data["current_period"] is None or (
        isinstance(data["current_period"], str) and _PERIOD_RE.match(data["current_period"])
    ), f"current_period must be null or YYYY-MM, got {data.get('current_period')!r}"
    assert isinstance(data["current_period_fees_cents"], int)


def assert_originator(data: dict):
    assert_common_fields(data, "Originator")
    assert is_valid_uuid(data.get("participant_id", "")), "participant_id must be a UUID"
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["risk_tier"] in {e.value for e in RiskTier}
    assert isinstance(data["exposure_limit_cents"], int) and data["exposure_limit_cents"] > 0
    assert isinstance(data["committed_exposure_cents"], int)
    assert isinstance(data["contingent_exposure_cents"], int)
    assert data["status"] in {e.value for e in OriginatorStatus}


def assert_transaction_code(data: dict):
    assert_common_fields(data, "TransactionCode")
    assert isinstance(data["code"], str) and _CODE_RE.match(data["code"]), (
        f"code must be 2-3 uppercase letters, got {data.get('code')!r}"
    )
    assert data["entry_class"] in {e.value for e in EntryClass}
    assert data["authorization_requirement"] in {e.value for e in AuthorizationType}
    assert isinstance(data["return_timeframe_banking_days"], int)
    assert data["return_timeframe_banking_days"] >= 1
    assert isinstance(data["account_validation_required"], bool)
    assert isinstance(data["warranty_obligations"], str)


def assert_settlement_window(data: dict):
    assert_immutable_record_fields(data, "SettlementWindow")
    assert isinstance(data["window_code"], str) and data["window_code"]
    assert isinstance(data["cutoff_time_utc"], str) and _CUTOFF_RE.match(data["cutoff_time_utc"]), (
        f"cutoff_time_utc must be HH:MM 24h, got {data.get('cutoff_time_utc')!r}"
    )
    assert isinstance(data["per_entry_limit_cents"], int)
    assert isinstance(data["odfi_window_cap_cents"], int)


def assert_rule_proposal(data: dict):
    assert_common_fields(data, "RuleProposal")
    assert is_valid_uuid(data.get("transaction_code_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["summary"], str)
    assert_iso_date(data["effective_date"], "effective_date")
    assert data["status"] in {e.value for e in RuleProposalStatus}
    assert data["outcome"] is None or data["outcome"] in {e.value for e in BallotOutcome}
    assert_optional_logical_timestamp(data.get("comment_opened_at"), "comment_opened_at")
    assert_optional_logical_timestamp(data.get("ballot_opened_at"), "ballot_opened_at")
    assert isinstance(data["yea_count"], int) and data["yea_count"] >= 0
    assert isinstance(data["nay_count"], int) and data["nay_count"] >= 0
    assert isinstance(data["abstain_count"], int) and data["abstain_count"] >= 0


def assert_ballot(data: dict):
    assert_common_fields(data, "Ballot")
    assert is_valid_uuid(data.get("rule_proposal_id", ""))
    assert is_valid_uuid(data.get("participant_id", ""))
    assert data["vote"] in {e.value for e in Vote}
    assert data["status"] in {e.value for e in BallotStatus}
    assert_logical_timestamp(data["cast_at"], "cast_at")


def assert_guidance_document(data: dict):
    assert_common_fields(data, "GuidanceDocument")
    assert is_valid_uuid(data.get("rule_proposal_id", ""))
    assert is_valid_uuid(data.get("transaction_code_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["body_ref"], str) and data["body_ref"]
    assert_iso_date(data["effective_from"], "effective_from")
    assert_optional_iso_date(data.get("effective_until"), "effective_until")
    assert data["status"] in {e.value for e in GuidanceDocumentStatus}


def assert_payment_entry(data: dict):
    assert_common_fields(data, "PaymentEntry")
    assert is_valid_uuid(data.get("originator_id", ""))
    assert is_valid_uuid(data.get("originating_participant_id", ""))
    assert is_valid_uuid(data.get("transaction_code_id", ""))
    assert is_valid_uuid(data.get("settlement_window_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["receiver_account_number_hash"], str)
    assert data["receiver_account_number_hash"]
    assert isinstance(data["receiver_name"], str)
    assert data["authorization_type"] in {e.value for e in AuthorizationType}
    assert isinstance(data["same_day"], bool)
    assert data["entry_fee_cents"] is None or isinstance(data["entry_fee_cents"], int)
    assert data["status"] in {e.value for e in PaymentEntryStatus}
    assert_optional_logical_timestamp(data.get("settled_at"), "settled_at")
    assert_optional_iso_date(data.get("settled_date"), "settled_date")


def assert_return_record(data: dict):
    assert_immutable_record_fields(data, "ReturnRecord")
    assert is_valid_uuid(data.get("payment_entry_id", ""))
    assert is_valid_uuid(data.get("returning_participant_id", ""))
    assert data["reason_code"] in {e.value for e in ReturnReasonCode}
    assert data["reason_class"] in {e.value for e in ReturnReasonClass}
    assert data["reason_class"] == REASON_CLASS_BY_CODE[data["reason_code"]], (
        f"reason_class {data['reason_class']!r} does not match reason_code "
        f"{data['reason_code']!r} (PRD §3.7 derivation)"
    )
    assert_logical_timestamp(data["returned_at"], "returned_at")


def assert_account_validation(data: dict):
    assert_immutable_record_fields(data, "AccountValidation")
    assert is_valid_uuid(data.get("originator_id", ""))
    assert isinstance(data["account_number_hash"], str) and data["account_number_hash"]
    assert data["method"] in {e.value for e in ValidationMethod}
    assert_iso_date(data["validated_until"], "validated_until")
    assert data["status"] in {e.value for e in AccountValidationStatus}


def assert_return_rate_snapshot(data: dict):
    assert_common_fields(data, "ReturnRateSnapshot")
    assert is_valid_uuid(data.get("participant_id", ""))
    assert isinstance(data["period"], str) and _PERIOD_RE.match(data["period"])
    for count_field in (
        "forward_count",
        "origination_forward_count",
        "unauth_return_count",
        "admin_return_count",
        "other_return_count",
        "origination_unauth_count",
        "origination_admin_count",
    ):
        assert isinstance(data[count_field], int) and data[count_field] >= 0, (
            f"{count_field} must be a non-negative integer"
        )
    for rate_field in (
        "settlement_unauth_rate",
        "settlement_admin_rate",
        "settlement_overall_rate",
        "origination_unauth_rate",
        "origination_admin_rate",
    ):
        assert_rate_4dp(data[rate_field], rate_field)
    for flag in ("unauth_breach", "admin_breach", "overall_breach"):
        assert isinstance(data[flag], bool)
    assert data["status"] in {e.value for e in ReturnRateSnapshotStatus}


def assert_inquiry_case(data: dict):
    assert_common_fields(data, "InquiryCase")
    assert is_valid_uuid(data.get("participant_id", ""))
    assert is_valid_uuid(data.get("return_rate_snapshot_id", ""))
    assert data["return_class"] in {e.value for e in InquiryReturnClass}
    assert_logical_timestamp(data["response_deadline"], "response_deadline")
    assert data["response_text"] is None or isinstance(data["response_text"], str)
    assert data["status"] in {e.value for e in InquiryCaseStatus}


def assert_enforcement_action(data: dict):
    assert_common_fields(data, "EnforcementAction")
    assert is_valid_uuid(data.get("participant_id", ""))
    assert data["inquiry_case_id"] is None or is_valid_uuid(data["inquiry_case_id"])
    assert data["violation_code"] in {e.value for e in ViolationCode}
    assert isinstance(data["escalation_tier"], int)
    assert 0 <= data["escalation_tier"] <= C.ESCALATION_TIER_CAP
    assert isinstance(data["fine_base_cents"], int) and data["fine_base_cents"] >= 0
    assert data["fine_total_cents"] is None or isinstance(data["fine_total_cents"], int)
    assert data["escalated_by_user_id"] is None or isinstance(data["escalated_by_user_id"], str)
    assert_iso_date(data["issued_date"], "issued_date")
    assert_optional_logical_timestamp(data.get("paid_at"), "paid_at")
    assert data["status"] in {e.value for e in EnforcementActionStatus}


def assert_attestation(data: dict):
    assert_common_fields(data, "ComplianceAttestation")
    assert is_valid_uuid(data.get("participant_id", ""))
    assert isinstance(data["period_year"], int)
    assert_iso_date(data["due_date"], "due_date")
    assert data["due_date"] == C.compute_attestation_due_date(data["period_year"]), (
        f"due_date must be {data['period_year'] + 1}-03-01, got {data['due_date']!r}"
    )
    assert_optional_logical_timestamp(data.get("submitted_at"), "submitted_at")
    assert isinstance(data["late_submission"], bool)
    assert data["attestation_text"] is None or isinstance(data["attestation_text"], str)
    assert data["status"] in {e.value for e in ComplianceAttestationStatus}


def assert_audit(data: dict):
    assert_common_fields(data, "AuditReport")
    assert is_valid_uuid(data.get("participant_id", ""))
    assert_iso_date(data["start_date"], "start_date")
    assert_iso_date(data["end_date"], "end_date")
    assert data["end_date"] >= data["start_date"], "end_date must be >= start_date"
    assert data["findings_count"] is None or (
        isinstance(data["findings_count"], int) and data["findings_count"] >= 0
    )
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data["completed_by_user_id"] is None or isinstance(data["completed_by_user_id"], str)
    assert data["status"] in {e.value for e in AuditReportStatus}


# =============================================================================
# Domain invariant checkers
# =============================================================================


def assert_originator_exposure_invariants(originator: dict):
    """PRD §3.2: contingent = committed + returnable SETTLED set, so the
    contingent reading never falls below the committed reading, and neither
    can go negative."""
    committed = originator["committed_exposure_cents"]
    contingent = originator["contingent_exposure_cents"]
    assert committed >= 0, f"committed_exposure_cents went negative: {committed}"
    assert contingent >= committed, (
        f"contingent_exposure_cents ({contingent}) < committed_exposure_cents ({committed})"
    )


def assert_snapshot_breach_flags(snapshot: dict):
    """PRD §3.7: breach flags recomputed by exact integer cross-multiplication
    (strictly greater-than — a rate exactly on the threshold does not breach)."""
    forward = snapshot["forward_count"]
    unauth = snapshot["unauth_return_count"]
    admin = snapshot["admin_return_count"]
    other = snapshot["other_return_count"]
    assert snapshot["unauth_breach"] == C.is_unauth_breach(forward, unauth), (
        f"unauth_breach mismatch: {unauth} returns over {forward} forward"
    )
    assert snapshot["admin_breach"] == C.is_admin_breach(forward, admin), (
        f"admin_breach mismatch: {admin} returns over {forward} forward"
    )
    assert snapshot["overall_breach"] == C.is_overall_breach(forward, unauth, admin, other), (
        f"overall_breach mismatch: {unauth + admin + other} returns over {forward} forward"
    )


def assert_envelope_api_request_timestamp(response):
    """Envelope meta.api_request_timestamp is in the bookkeeping family
    (exactly three fractional digits)."""
    body = response.json()
    assert "meta" in body and "api_request_timestamp" in body["meta"], (
        "envelope missing meta.api_request_timestamp"
    )
    assert_bookkeeping_timestamp(body["meta"]["api_request_timestamp"], "api_request_timestamp")
