"""Per-entity structural assertions and domain invariant checkers."""
import pytest

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _assert_common_fields(data: dict):
    """Every resource carries a UUID id and ISO 8601 timestamps (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_participant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["participant_type"] in (
        "PRESCRIBER_CLINIC", "PHARMACY", "PAYER", "HUB"
    ), f"unexpected participant_type {data['participant_type']!r}"
    assert isinstance(data["npi"], str) and len(data["npi"]) > 0
    assert data["certification_status"] in (
        "UNCERTIFIED", "IN_CERTIFICATION", "CERTIFIED", "SUSPENDED"
    ), f"unexpected certification_status {data['certification_status']!r}"
    assert isinstance(data["certification_tests_passed"], list)
    assert data["volume_billing_mode"] in ("MONTHLY", "ROLLING_90_DAY")
    assert isinstance(data["directory_listed"], bool)
    assert data["delivery_reachability"] in ("FULL", "AT_RISK", "UNREACHABLE")
    assert isinstance(data["open_route_attempt_count"], int)
    assert data["fallback_channel"] in ("FAX", "PRINT")
    assert data["fax_number"] is None or isinstance(data["fax_number"], str)
    assert isinstance(data["plan_deductible_met_cents"], int)
    assert data["plan_deductible_met_cents"] >= 0


def assert_endpoint(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["participant_id"]), "participant_id must be a UUID"
    assert data["service_set"] in (
        "NEW_RX", "REFILL_RX", "CHANGE_CANCEL", "MED_HISTORY",
        "BENEFIT_COST", "ELIGIBILITY_FORMULARY",
    ), f"unexpected service_set {data['service_set']!r}"
    assert data["endpoint_role"] in ("SENDER", "RECEIVER", "BOTH")
    assert data["service_level"] in ("ELIGIBLE_A", "ELIGIBLE_B", "ELIGIBLE_C")
    assert isinstance(data["sla_response_minutes"], int)
    assert data["message_standard"] in ("NCPDP_SCRIPT_2017071", "NCPDP_SCRIPT_2022011")
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["effective_to"] is None or is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in ("PENDING_CERT", "ACTIVE", "DEGRADED", "DISABLED")
    assert isinstance(data["reported_attempt_count"], int)
    assert isinstance(data["acknowledged_count"], int)
    assert isinstance(data["reliability_ratio"], (int, float))
    assert isinstance(data["reliability_ratio_ewma"], (int, float))
    assert 0.0 <= float(data["reliability_ratio"]) <= 1.0
    assert 0.0 <= float(data["reliability_ratio_ewma"]) <= 1.0


def assert_prescription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["prescriber_id"])
    assert is_valid_uuid(data["receiving_pharmacy_id"])
    assert is_valid_uuid(data["patient_id"])
    assert data["transaction_type"] in (
        "NEW_RX", "REFILL_REQUEST", "REFILL_RESPONSE", "CHANGE_REQUEST",
        "CHANGE_RESPONSE", "CANCEL_REQUEST", "CANCEL_RESPONSE",
    )
    assert data["controlled_schedule"] in (
        "NON_CONTROLLED", "SCHEDULE_II", "SCHEDULE_III", "SCHEDULE_IV", "SCHEDULE_V"
    )
    assert data["message_standard"] in ("NCPDP_SCRIPT_2017071", "NCPDP_SCRIPT_2022011")
    assert data["clinical_status"] in (
        "DRAFT", "SIGNED", "ROUTED", "DELIVERED", "UNDELIVERABLE", "REJECTED", "CANCELLED"
    )
    assert data["routing_status"] in (
        "NOT_ROUTED", "ROUTING", "ROUTED", "BACKUP_SELECTION", "FALLBACK_PENDING",
        "FALLBACK_SENT", "ROUTE_FAILED",
    )
    assert isinstance(data["is_controlled"], bool)
    assert data["significance"] in ("STANDARD", "CRITICAL")
    assert isinstance(data["monitored_under_consent"], bool)
    assert isinstance(data["routing_attempt_count"], int)
    # Derived flags must agree with their inputs (PRD §3.3).
    expected_controlled = data["controlled_schedule"] != "NON_CONTROLLED"
    assert data["is_controlled"] is expected_controlled, (
        f"is_controlled {data['is_controlled']} disagrees with "
        f"controlled_schedule {data['controlled_schedule']!r}"
    )


def assert_signing_session(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["prescription_id"])
    assert data["identity_proofing_status"] in ("NOT_STARTED", "PASSED", "FAILED")
    assert data["two_factor_status"] in (
        "NOT_STARTED", "PENDING", "PASSED", "LOCKED", "FAILED"
    )
    assert data["session_status"] in ("OPEN", "SIGNED", "ABANDONED")
    assert isinstance(data["otp_attempt_count"], int)
    assert is_iso8601_timestamp(data["opened_at"])
    assert data["signed_at"] is None or is_iso8601_timestamp(data["signed_at"])


def assert_routing_attempt(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["prescription_id"])
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1
    assert data["channel"] in ("NETWORK", "FAX", "PRINT")
    assert data["outcome"] in (
        "IN_PROGRESS", "ACKNOWLEDGED", "REJECTED", "UNDELIVERABLE"
    )
    if data["channel"] in ("FAX", "PRINT"):
        assert data["target_endpoint_id"] is None, (
            "target_endpoint_id must be null for FAX and PRINT attempts"
        )


def assert_patient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["consent_status"] in ("NONE", "GRANTED", "REVOKED", "EXPIRED")
    assert isinstance(data["consent_version"], int)
    assert isinstance(data["history_record_count"], int)
    assert data["history_record_count"] >= 0


def assert_patient_consent(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["scope"] in ("MEDICATION_HISTORY", "BENEFIT_CHECK", "BOTH")
    assert isinstance(data["duration_days"], int)
    assert data["status"] in ("ACTIVE", "REVOKED", "EXPIRED")
    assert is_iso8601_timestamp(data["granted_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["revoked_at"] is None or is_iso8601_timestamp(data["revoked_at"])


def assert_history_batch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["trigger_reason"] in (
        "PRESCRIBER_QUERY", "CONSENT_GRANT", "SCHEDULED_REFRESH"
    )
    assert data["status"] in ("PENDING", "AGGREGATING", "COMPLETE", "FAILED")
    assert isinstance(data["subscription_generation"], int)
    assert isinstance(data["source_record_count"], int)
    assert isinstance(data["record_count"], int)
    assert isinstance(data["superseded_count"], int)
    assert isinstance(data["batch_cost_cents"], int)
    assert data["batch_cost_cents"] >= 0


def assert_history_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["source_participant_id"])
    assert data["source_type"] in ("PHARMACY_FILL", "PAYER_CLAIM")
    assert isinstance(data["dedupe_key"], str) and "|" in data["dedupe_key"], (
        "dedupe_key is the patient id, drug code, fill date and days supplied joined by bars"
    )
    assert isinstance(data["is_superseded"], bool)


def assert_benefit_check(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["prescription_id"])
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["payer_id"])
    assert isinstance(data["benchmark_price_cents"], int)
    assert data["formulary_status"] in (
        "UNKNOWN", "PREFERRED", "NON_PREFERRED", "NOT_COVERED", "PRIOR_AUTH_REQUIRED"
    )
    assert data["coverage_status"] in ("UNKNOWN", "ACTIVE", "INACTIVE")
    assert data["check_status"] in ("PENDING", "COMPLETE", "FAILED")
    assert data["pricing_variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["estimated_patient_pay_cents"], int)
    assert isinstance(data["estimated_plan_pay_cents"], int)
    assert data["estimated_patient_pay_cents"] >= 0
    assert data["estimated_plan_pay_cents"] >= 0


def assert_transaction_fee_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["participant_id"])
    assert isinstance(data["month_key"], str)
    assert data["transaction_type"] in (
        "NEW_RX", "REFILL_RESPONSE", "CHANGE_RESPONSE", "CANCEL_RESPONSE",
        "MED_HISTORY", "BENEFIT_COST", "ELIGIBILITY_FORMULARY",
    )
    assert data["direction"] in ("SENT", "RECEIVED")
    assert isinstance(data["transaction_count"], int)
    assert data["fee_tier"] in ("FREE", "STANDARD", "VOLUME")
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in ("PARTIAL", "POSTED", "REVERSED")
    assert data["entry_type"] in ("CHARGE", "CORRECTION", "MANUAL_REVERSAL")
    assert isinstance(data["period_net_total_cents"], int)
    if data["entry_type"] == "CHARGE":
        assert data["previous_count"] is None and data["new_count"] is None
        assert data["reversal_of_entry_id"] is None


# ─── Domain invariant checkers ───

def assert_fee_ledger_conserved(entry_after_reversal: dict, net_before_charge: int):
    """A charge followed by its compensating row leaves the participant-and-month
    period_net_total_cents at its pre-charge value (PRD §2.7)."""
    assert entry_after_reversal["period_net_total_cents"] == net_before_charge, (
        f"period_net_total_cents {entry_after_reversal['period_net_total_cents']} "
        f"did not return to {net_before_charge}"
    )


def assert_fee_entry_precision(data: dict):
    """Every monetary quantity is an integer number of cents (PRD §2.7)."""
    assert_cost_precision(data["fee_cents"], 0)
    assert_cost_precision(data["period_net_total_cents"], 0)


def assert_reliability_in_range(endpoint: dict):
    assert 0.0 <= float(endpoint["reliability_ratio"]) <= 1.0
    assert 0.0 <= float(endpoint["reliability_ratio_ewma"]) <= 1.0
    # Both columns are reported to four decimal places (PRD §2.6).
    assert round(float(endpoint["reliability_ratio"]), 4) == pytest.approx(
        float(endpoint["reliability_ratio"]), abs=1e-9
    )