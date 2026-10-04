"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_plasma_center(data: dict):
    assert is_valid_uuid(data.get("id", "")), "center id must be a valid UUID"
    assert isinstance(data.get("center_code"), str) and data["center_code"]
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("state_code"), str) and len(data["state_code"]) == 2
    assert isinstance(data.get("screening_lanes"), int) and data["screening_lanes"] >= 1
    assert isinstance(data.get("donor_floor_beds"), int) and data["donor_floor_beds"] >= 1
    assert isinstance(data.get("observation_chairs"), int) and data["observation_chairs"] >= 1
    assert data.get("status") in ("OPERATIONAL", "INSPECTION_HOLD", "DECOMMISSIONED")
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_donor(data: dict):
    assert is_valid_uuid(data.get("id", "")), "donor id must be a valid UUID"
    assert isinstance(data.get("external_donor_ref"), str) and data["external_donor_ref"]
    assert data.get("donor_status") in (
        "APPLICANT", "QUALIFIED", "DEFERRED_TEMP", "DEFERRED_PERM",
    )
    assert isinstance(data.get("lifetime_donation_count"), int)
    assert data["lifetime_donation_count"] >= 0
    assert isinstance(data.get("ytd_compensation_cents"), int)
    assert isinstance(data.get("requires_1099"), bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_screening_visit(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("visit_status") in (
        "SCHEDULED", "IN_PROGRESS", "CLEARED", "FAILED", "EXPIRED",
    )
    for flag in (
        "identity_verified",
        "health_history_recorded",
        "physical_exam_recorded",
        "viral_marker_recorded",
    ):
        assert isinstance(data.get(flag), bool), f"{flag} must be boolean"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_donation_visit(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("visit_status") in (
        "SCHEDULED", "IN_PROGRESS", "OBSERVATION",
        "COMPLETED", "ABORTED_REACTION", "NO_SHOW",
    )
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_donation_unit(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("unit_status") in (
        "QUARANTINED", "RELEASED", "DESTROYED", "LOOKBACK_HOLD",
    )
    assert isinstance(data.get("volume_ml"), int) and data["volume_ml"] > 0
    assert is_iso8601_timestamp(data.get("collected_at", ""))


def assert_compensation_schedule(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("schedule_status") in ("ACTIVE", "SUPERSEDED", "RETIRED")
    assert isinstance(data.get("base_cents_first_donation"), int)
    assert isinstance(data.get("base_cents_second_donation"), int)
    assert isinstance(data.get("base_cents_subsequent_donation"), int)
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_compensation_payment(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("payment_status") in ("PROVISIONAL", "FINALIZED", "CLAWED_BACK")
    assert data.get("variant") in ("PROVISIONAL", "FINAL")
    assert isinstance(data.get("base_cents"), int)
    assert isinstance(data.get("promo_cents"), int)
    assert isinstance(data.get("net_cents"), int)


def assert_deferral_entry(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("deferral_type") in ("TEMPORARY", "PERMANENT")
    assert data.get("registry_status") in ("ACTIVE", "CLEARED", "OVERRIDDEN")
    assert isinstance(data.get("reason_code"), str) and data["reason_code"]


def assert_lookback_case(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("case_status") in (
        "OPEN", "UNITS_QUARANTINED", "RESOLVED_DESTROYED", "RESOLVED_RELEASED",
    )
    assert data.get("lookback_window_days") == 180
