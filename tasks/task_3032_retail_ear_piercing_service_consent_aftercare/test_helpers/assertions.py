"""Entity assertions and domain invariant checkers.

Structural checks reuse the framework's generic format validators; the
domain invariants encode the conservation rules the PRD states.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper(), "state_code must be two uppercase letters"
    assert isinstance(data["permitted_sites"], list)
    assert all(
        s in ("LOBE", "UPPER_LOBE", "HELIX", "TRAGUS", "INDUSTRIAL", "NOSTRIL")
        for s in data["permitted_sites"]
    ), "permitted_sites entries must be enumerated anatomical sites"
    assert isinstance(data["requires_guardian_presence"], bool)
    assert isinstance(data["record_retention_years"], int)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_store_location(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_valid_uuid(data["jurisdiction_id"]), "jurisdiction_id must be a UUID"
    assert isinstance(data["piercing_room_count"], int)
    assert data["compliance_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["open_incident_count"], int) and data["open_incident_count"] >= 0
    assert data["status"] in ("OPEN", "RESTRICTED", "CLOSED")


def assert_piercer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_valid_uuid(data["home_store_id"]), "home_store_id must be a UUID"
    assert isinstance(data["eligibility_score"], int)
    assert 0 <= data["eligibility_score"] <= 100, "eligibility_score must be clamped into 0..100"
    assert isinstance(data["assigned_session_count"], int) and data["assigned_session_count"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "INACTIVE")


def assert_certification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["piercer_id"]), "piercer_id must be a UUID"
    assert data["certification_level"] in ("APPRENTICE", "STANDARD", "SENIOR", "INSTRUCTOR")
    assert isinstance(data["sterilization_protocol_code"], str)
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert is_iso8601_timestamp(data["recertification_due_at"])
    assert isinstance(data["attempted_practical_count"], int) and data["attempted_practical_count"] >= 0
    assert data["status"] in ("VALID", "EXPIRING_SOON", "EXPIRED", "RECERTIFICATION_PENDING", "REVOKED")


def assert_sterilization_cycle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["store_location_id"]), "store_location_id must be a UUID"
    assert isinstance(data["autoclave_unit_id"], str)
    assert isinstance(data["temperature_celsius"], (int, float))
    assert isinstance(data["biological_indicator_passed"], bool)
    assert isinstance(data["quarantine_scope_units"], int) and data["quarantine_scope_units"] >= 0
    assert data["status"] in ("IN_PROGRESS", "PASSED", "FAILED", "QUARANTINED", "RELEASED")


def assert_cartridge_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["store_location_id"]), "store_location_id must be a UUID"
    assert is_valid_uuid(data["sterilization_cycle_id"]), "sterilization_cycle_id must be a UUID"
    assert data["site_type"] in ("LOBE", "UPPER_LOBE", "HELIX", "TRAGUS", "INDUSTRIAL", "NOSTRIL")
    assert isinstance(data["units_received"], int)
    for field in ("units_available", "units_consumed", "units_quarantined"):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must be non-negative"
    assert data["status"] in ("AVAILABLE", "DEPLETED", "QUARANTINED", "DISCARDED")


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_iso8601_timestamp(data["date_of_birth"])
    for field in ("aftercare_credit_cents", "refunded_cents", "retained_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer number of cents"
    assert data["status"] in ("ACTIVE", "FLAGGED", "CLOSED")


def assert_consent(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"]), "customer_id must be a UUID"
    assert is_valid_uuid(data["jurisdiction_id"]), "jurisdiction_id must be a UUID"
    assert data["consent_type"] in ("SELF", "GUARDIAN_PRESENT", "GUARDIAN_NOTARIZED", "COURT_ORDER")
    assert data["guardian_verification_status"] in (
        "NOT_REQUIRED", "PENDING_VERIFICATION", "VERIFIED", "FAILED"
    )
    assert data["identification_type"] in (
        "GOVERNMENT_PHOTO_ID", "BIRTH_CERTIFICATE", "PASSPORT", "STATE_ID"
    )
    assert data["required_identification_type"] in (
        "GOVERNMENT_PHOTO_ID", "BIRTH_CERTIFICATE", "PASSPORT", "STATE_ID", "NONE"
    )
    assert data["consent_status"] in ("PENDING", "ACTIVE", "EXPIRED", "REVOKED", "REJECTED")


def assert_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["store_location_id"])
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["piercer_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert data["intake_type"] in ("SCHEDULED", "WALK_IN")
    assert data["site_requested"] in ("LOBE", "UPPER_LOBE", "HELIX", "TRAGUS", "INDUSTRIAL", "NOSTRIL")
    assert is_iso8601_timestamp(data["slot_start_at"])
    assert is_iso8601_timestamp(data["slot_end_at"])
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0
    assert data["status"] in (
        "BOOKED", "CONFIRMED", "CHECKED_IN", "SCREENED", "IN_SERVICE",
        "COMPLETED", "RESCHEDULED", "CANCELLED", "NO_SHOW", "REFUSED",
    )


def assert_screening(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["appointment_id"])
    assert is_valid_uuid(data["piercer_id"])
    assert isinstance(data["anatomy_sites_examined"], list)
    assert isinstance(data["contraindication_codes"], list)
    assert all(
        c in (
            "KELOID_HISTORY", "ACTIVE_INFECTION", "BLOOD_THINNER_THERAPY", "METAL_ALLERGY",
            "UNCONTROLLED_DIABETES", "PREGNANCY", "HYPERTROPHIC_SCAR",
        )
        for c in data["contraindication_codes"]
    ), "contraindication_codes entries must be enumerated codes"
    assert data["outcome"] in ("PENDING", "CLEARED", "REFUSED", "ESCALATED")


def assert_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["appointment_id"])
    assert is_valid_uuid(data["piercer_id"])
    assert data["site_pierced"] in ("LOBE", "UPPER_LOBE", "HELIX", "TRAGUS", "INDUSTRIAL", "NOSTRIL")
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["aftercare_kit_included"], bool)
    assert isinstance(data["follow_up_acknowledged"], bool)
    assert isinstance(data["net_fee_cents"], int)
    assert data["net_fee_cents"] >= 0
    assert data["service_status"] in ("IN_PROGRESS", "COMPLETED", "ABORTED")
    assert data["healing_status"] in ("HEALING", "HEALED", "FAILED", "RE_PIERCED")


def assert_incident(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["session_id"])
    assert is_iso8601_timestamp(data["reported_at"])
    assert data["severity"] in ("MINOR", "MODERATE", "SEVERE", "MEDICAL_EMERGENCY")
    assert all(
        c in (
            "REDNESS", "SWELLING", "DISCHARGE", "EMBEDDED_BACK", "INFECTION",
            "ALLERGIC_REACTION", "KELOID", "NERVE_DAMAGE",
        )
        for c in data["reaction_codes"]
    ), "reaction_codes entries must be enumerated codes"
    assert data["escalation_status"] in (
        "LOGGED", "TRIAGED", "ESCALATED", "RESOLVED", "REFUND_ISSUED", "REOPENED"
    )
    assert isinstance(data["refund_amount_cents"], int) and data["refund_amount_cents"] >= 0
    assert data["refund_status"] in ("NONE", "PENDING", "SETTLED", "DECLINED")


def assert_healing_outcome(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["session_id"])
    assert is_iso8601_timestamp(data["assessed_at"])
    assert data["healing_result"] in ("PENDING_ASSESSMENT", "HEALED", "FAILED", "DOWNGRADED")
    assert isinstance(data["downgrade_credited_cents"], int) and data["downgrade_credited_cents"] >= 0
    assert isinstance(data["re_pierce_eligible"], bool)
    assert isinstance(data["re_pierce_claim_count"], int) and data["re_pierce_claim_count"] >= 0
    assert data["status"] in ("ASSESSED", "RE_PIERCE_ELIGIBLE", "RE_PIERCED", "DOWNGRADED", "CLOSED")


# ─── Domain invariants ─────────────────────────────────────────────────────

def assert_cartridge_unit_conservation(lot: dict):
    """The unit counts of a lot never exceed what was received."""
    total = lot["units_available"] + lot["units_consumed"] + lot["units_quarantined"]
    assert total <= lot["units_received"], (
        f"unit counts ({total}) exceed units_received ({lot['units_received']})"
    )


def assert_customer_ledger_identity(customer: dict, net_fee_cents: int):
    """Refunded plus retained amounts account for the session fee after settlement."""
    assert customer["refunded_cents"] + customer["retained_cents"] == net_fee_cents, (
        f"refunded ({customer['refunded_cents']}) + retained ({customer['retained_cents']}) "
        f"!= net fee ({net_fee_cents})"
    )