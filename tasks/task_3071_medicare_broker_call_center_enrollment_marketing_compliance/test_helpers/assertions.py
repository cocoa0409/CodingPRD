"""Entity assertions and domain invariant checkers."""
import re

import pytest

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


_UTC_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z$"
)


def utc(value):
    """Canonicalise an ISO-8601 UTC instant literal to the server's spelling.

    PRD §2.10 fixes every server-managed timestamp at three fractional digits,
    so a literal written without them (``2026-10-01T00:00:00Z``) denotes the same
    instant as ``2026-10-01T00:00:00.000Z``. Wrapping the expected literal keeps
    an instant-equality assertion from failing on the spelling alone.
    """
    if not isinstance(value, str):
        return value
    match = _UTC_RE.match(value)
    if not match:
        return value
    fraction = (match.group(2) or "").ljust(3, "0")[:3]
    return f"{match.group(1)}.{fraction}Z"


# ─── Generic envelope helpers ────────────────────────────────

def assert_versioned_resource(data: dict, label: str = "resource"):
    """Every common-field resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an int"


def assert_append_only_resource(data: dict, label: str = "resource"):
    """Append-only pairings carry id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None


# ─── Entity assertions ───────────────────────────────────────

def assert_agency(data: dict):
    assert_versioned_resource(data, "Agency")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["service_center_code"], str) and data["service_center_code"]
    assert data["compliance_posture"] in ["OPEN", "RESTRICTED", "FROZEN"]
    assert isinstance(data["aep_daily_submission_capacity"], int)
    assert isinstance(data["commission_balance_cents"], (int, float))
    assert isinstance(data["open_complaint_count"], int)
    assert isinstance(data["substantiated_complaint_rate"], (int, float))
    assert isinstance(data["loss_ratio"], (int, float))


def assert_carrier(data: dict):
    assert_versioned_resource(data, "Carrier")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["contract_type"] in ["CONTRACTED", "MARKETING_ONLY"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["initial_commission_rate_pct"], (int, float))
    assert isinstance(data["renewal_commission_rate_pct"], (int, float))


def assert_agent(data: dict):
    assert_versioned_resource(data, "Agent")
    assert isinstance(data["agency_id"], str)
    assert data["status"] in [
        "PROVISIONING", "LICENSED", "CERTIFIED", "ACTIVE", "SUSPENDED", "TERMINATED"
    ]
    for field in ("licensed_state_count", "certified_carrier_count",
                  "appointed_carrier_count", "live_call_count",
                  "active_enrollment_count", "chargeback_tier",
                  "substantiated_complaint_count", "open_coaching_count"):
        assert isinstance(data[field], int), f"Agent.{field} must be an int"
    assert isinstance(data["coaching_flag"], bool)
    assert isinstance(data["compliance_risk_score"], (int, float))


def assert_agent_invariants(data: dict):
    """Domain invariants that must hold after ANY agent operation."""
    assert data["licensed_state_count"] >= 0
    assert data["certified_carrier_count"] >= 0
    assert data["appointed_carrier_count"] >= 0
    assert data["live_call_count"] >= 0
    assert data["active_enrollment_count"] >= 0
    assert data["open_coaching_count"] >= 0
    assert data["chargeback_tier"] >= 0
    assert data["substantiated_complaint_count"] >= 0
    assert data["compliance_risk_score"] >= 0
    assert_cost_precision(data["compliance_risk_score"])
    assert data["coaching_flag"] == (data["open_coaching_count"] > 0)


def assert_state_license(data: dict):
    assert_versioned_resource(data, "AgentStateLicense")
    assert isinstance(data["agent_id"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["license_status"] in ["VALID", "LAPSED"]
    assert is_iso8601_timestamp(data.get("issued_on", ""))
    assert is_iso8601_timestamp(data.get("expires_on", ""))


def assert_appointment(data: dict):
    assert_versioned_resource(data, "CarrierAppointment")
    assert data["status"] in ["REQUESTED", "APPOINTED", "REJECTED", "TERMINATED"]


def assert_certification(data: dict):
    assert_versioned_resource(data, "CarrierCertification")
    assert data["product_type"] in ["MA", "MAPD", "PDP", "SNP"]
    assert data["status"] in ["PENDING", "CERTIFIED", "EXPIRED", "REVOKED"]


def assert_member(data: dict):
    assert_versioned_resource(data, "Member")
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["medicare_beneficiary_id"], str)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["county_code"], str)
    assert isinstance(data.get("drug_list", []), list)
    assert isinstance(data.get("provider_npis", []), list)
    assert isinstance(data["enrollment_count"], int)


def assert_scope(data: dict):
    assert_versioned_resource(data, "ScopeOfAppointment")
    assert isinstance(data["member_id"], str)
    assert isinstance(data["agent_id"], str)
    assert data["capture_channel"] in ["TELEPHONIC_RECORDED", "WRITTEN", "ELECTRONIC"]
    assert isinstance(data["plan_types_authorized"], list)
    assert data["status"] in ["CAPTURED", "CONSUMED", "VOIDED"]
    assert is_iso8601_timestamp(data.get("captured_on", ""))
    assert is_iso8601_timestamp(data.get("expires_on", ""))
    assert is_iso8601_timestamp(data.get("retained_until", ""))


def assert_call_session(data: dict):
    assert_versioned_resource(data, "CallSession")
    assert isinstance(data["agent_id"], str)
    assert isinstance(data["member_id"], str)
    assert data["status"] in ["RINGING", "IN_PROGRESS", "COMPLETED", "DROPPED", "AMENDED"]
    assert is_iso8601_timestamp(data.get("started_at", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end_at", ""))
    assert is_iso8601_timestamp(data.get("recording_retained_until", ""))
    assert data["recording_status"] in ["RECORDED", "MISSING", "EXPIRED"]
    assert isinstance(data["disclaimer_delivered"], bool)


def assert_call_invariants(data: dict):
    """Recording status must agree with the recording identifier and the clock."""
    if data.get("recording_id") is None:
        assert data["recording_status"] == "MISSING", \
            "a call with no recording_id must report recording_status MISSING"
    else:
        assert data["recording_status"] in ["RECORDED", "EXPIRED"]


def assert_plan(data: dict):
    assert_versioned_resource(data, "Plan")
    assert isinstance(data["carrier_id"], str)
    assert data["plan_type"] in ["MA", "MAPD", "PDP", "SNP"]
    assert data["status"] in ["ACTIVE", "TERMINATED"]
    assert isinstance(data["monthly_premium_cents"], int)
    assert isinstance(data["annual_drug_deductible_cents"], int)
    assert 1.0 <= data["star_rating"] <= 5.0
    assert isinstance(data["enrolled_member_count"], int)


def assert_formulary_drug(data: dict):
    assert_versioned_resource(data, "FormularyDrug")
    assert 1 <= data["tier"] <= 5
    assert isinstance(data["monthly_copay_cents"], int)
    assert isinstance(data["covered"], bool)


def assert_pharmacy_network_entry(data: dict):
    assert_append_only_resource(data, "PharmacyNetworkEntry")
    assert data["network_tier"] in ["PREFERRED", "STANDARD", "OUT_OF_NETWORK"]
    assert isinstance(data["cost_share_multiplier_pct"], (int, float))


def assert_provider_directory_entry(data: dict):
    assert_versioned_resource(data, "ProviderDirectoryEntry")
    assert data["network_status"] in ["IN_NETWORK", "OUT_OF_NETWORK"]
    assert isinstance(data["accepting_new_patients"], bool)


def assert_enrollment(data: dict):
    assert_versioned_resource(data, "Enrollment")
    assert isinstance(data["call_session_id"], str)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["agent_id"], str)
    assert data["submission_status"] in [
        "SUBMITTED", "ACKNOWLEDGED", "EFFECTUATED", "REJECTED", "WITHDRAWN"
    ]
    assert data["disenrollment_status"] in [
        "NOT_APPLICABLE", "ENROLLED", "RAPID_DISENROLLED", "STANDARD_DISENROLLED"
    ]
    assert is_iso8601_timestamp(data.get("submitted_on", ""))


def assert_ledger_entry(data: dict):
    assert_versioned_resource(data, "CommissionLedgerEntry")
    assert data["entry_type"] in [
        "INITIAL", "RENEWAL", "CHARGEBACK", "ADJUSTMENT", "REVERSAL"
    ]
    assert data["status"] in ["PROVISIONAL", "FINALIZED", "REVERSED"]
    assert isinstance(data["amount_cents"], (int, float))
    assert isinstance(data["period_month"], str)


def assert_reconciliation(data: dict):
    assert_versioned_resource(data, "CarrierReconciliation")
    assert data["status"] in ["OPEN", "RECONCILED", "DISPUTED"]
    assert data["variance_variant"] in ["PROVISIONAL", "FINAL"]
    assert isinstance(data["internal_total_cents"], (int, float))
    assert isinstance(data["variance_cents"], (int, float))
    assert data["variance_cents"] == pytest.approx(
        data["carrier_reported_total_cents"] - data["internal_total_cents"], abs=0.01
    )


def assert_complaint(data: dict):
    assert_versioned_resource(data, "Complaint")
    assert data["complaint_type"] in [
        "MISREPRESENTATION", "SOA_MISSING", "DISCLAIMER_MISSING",
        "RECORDING_MISSING", "UNAPPROVED_MARKETING", "PLAN_MISREPRESENTATION",
        "DISENROLLMENT_DELAY",
    ]
    assert data["source"] in ["BENEFICIARY", "CMS", "CARRIER", "SECRET_SHOPPER"]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH"]
    assert data["status"] in [
        "OPEN", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED", "APPEALED", "CLOSED"
    ]


def assert_coaching_assignment(data: dict):
    assert_versioned_resource(data, "CoachingAssignment")
    assert data["coaching_type"] in [
        "SOA_RETRAINING", "DISCLAIMER_RETRAINING", "MARKETING_RULES",
        "PLAN_DETAIL_ACCURACY", "RECORDING_RETENTION",
    ]
    assert data["triggered_by"] in ["COMPLAINT", "SECRET_SHOPPER", "MANUAL"]
    assert data["status"] in ["ASSIGNED", "IN_PROGRESS", "COMPLETED", "OVERDUE"]
    assert isinstance(data["overdue_days"], int)
    assert data["overdue_days"] >= 0


# ─── Domain invariant checkers ───────────────────────────────

def assert_agency_invariants(data: dict):
    """Domain invariants that must hold after ANY agency operation."""
    assert data["commission_balance_cents"] >= 0 or True  # signed ledger, may be negative
    assert isinstance(data["open_complaint_count"], int) and data["open_complaint_count"] >= 0
    assert data["compliance_posture"] in ["OPEN", "RESTRICTED", "FROZEN"]
    assert 0.0 <= data["substantiated_complaint_rate"] <= 1.0
    assert data["loss_ratio"] >= 0


def assert_enrollment_money_invariants(data: dict):
    """Both commission figures are cent-precise."""
    assert_cost_precision(data["provisional_commission_cents"])
    assert_cost_precision(data["final_commission_cents"])


__all__ = [name for name in dir() if not name.startswith("_")]