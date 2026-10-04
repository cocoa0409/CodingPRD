"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    AssignmentStatus,
    CycleStatus,
    EncounterStatus,
    HandoffStatus,
    ManifestStatus,
    Posture,
    SiteStatus,
    StationStatus,
    TicketStatus,
    VerificationStatus,
    VolunteerStatus,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """Append-only resources carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "append-only resource must not expose updated_at"
    assert "version" not in data, "append-only resource must not expose version"


def assert_clinic_event(data: dict):
    _assert_common_fields(data)
    assert data["posture"] in [p.value for p in Posture]
    assert isinstance(data["total_patient_capacity"], int)
    for counter in (
        "dental_chair_count",
        "vision_lane_count",
        "medical_bay_count",
        "verified_volunteer_count",
        "tickets_issued_count",
        "tickets_served_count",
        "unmet_demand_count",
        "sterilization_cycles_completed",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
        assert data[counter] >= 0, f"{counter} must be non-negative"
    assert isinstance(data["projected_servable_patients"], (int, float))


def assert_site(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in SiteStatus]
    assert data["site_type"] in ("ARENA", "FAIRGROUND", "SCHOOL")
    assert isinstance(data["square_footage"], int)
    assert isinstance(data["has_loading_dock"], bool)
    assert isinstance(data["sterilization_capable"], bool)


def assert_site_agreement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in AgreementStatus]
    assert isinstance(data["liability_cap_cents"], int)
    assert isinstance(data["cost_share_cents"], int)
    assert data["cost_share_cents"] >= 0


def assert_volunteer(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in VolunteerStatus]
    assert data["discipline"] in ("DENTAL", "VISION", "MEDICAL", "GENERAL")


def assert_license_verification(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in VerificationStatus]
    assert isinstance(data["attempt_sequence"], int)
    assert data["attempt_sequence"] >= 1


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in AssignmentStatus]
    assert data["shift_code"] in ("FULL_DAY", "MORNING", "AFTERNOON")


def assert_station(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in StationStatus]
    assert data["station_type"] in (
        "TRIAGE",
        "DENTAL",
        "VISION",
        "MEDICAL",
        "GLASSES_LAB",
        "DENTURE_LAB",
    )
    assert isinstance(data["chair_count"], int) and data["chair_count"] >= 1


def assert_ticket(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in TicketStatus]
    assert data["requested_service"] in ("DENTAL", "VISION", "MEDICAL")
    assert data["priority_tier"] in ("STANDARD", "VULNERABLE")
    assert isinstance(data["queue_position"], int)


def assert_encounter(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in EncounterStatus]
    assert data["encounter_type"] in (
        "TRIAGE",
        "EXTRACTION",
        "DENTURE_FIT",
        "EYE_EXAM",
        "GLASSES_DISPENSE",
        "MEDICAL_CONSULT",
    )
    assert isinstance(data["requires_followup"], bool)


def assert_referral(data: dict):
    _assert_append_only_fields(data)
    assert data["referral_type"] in (
        "DENTAL_FOLLOWUP",
        "VISION_FOLLOWUP",
        "MEDICAL_FOLLOWUP",
        "URGENT_CARE",
    )
    assert data["urgency"] in ("ROUTINE", "URGENT", "EMERGENT")


def assert_manifest(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ManifestStatus]
    assert isinstance(data["item_count"], int) and data["item_count"] >= 1
    assert isinstance(data["contains_sterilizer"], bool)
    assert isinstance(data["requires_loading_dock"], bool)


def assert_cycle(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in CycleStatus]
    assert isinstance(data["cycle_sequence"], int) and data["cycle_sequence"] >= 1
    assert isinstance(data["instrument_batch_size"], int)


def assert_unmet_demand_report(data: dict):
    _assert_append_only_fields(data)
    assert data["report_variant"] in ("OBSERVED_ONLY", "WITH_EXTRAPOLATION")
    assert isinstance(data["turned_away_count"], int)
    assert isinstance(data["estimated_unserved_beyond_queue"], int)
    assert isinstance(data["projected_shortfall_patients"], int)


def assert_handoff(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in HandoffStatus]
    assert isinstance(data["teardown_checklist_complete"], bool)
    assert isinstance(data["referral_packet_count"], int)
