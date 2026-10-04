"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ORDER_STATUSES = (
    "PENDING_ELIGIBILITY", "ELIGIBLE", "REJECTED_INELIGIBLE", "KIT_ORDERED",
    "KIT_SHIPPED", "KIT_RETURNED", "IN_LAB", "RESULTED", "CANCELLED",
    "ABANDONED", "RECOLLECTION_REQUESTED",
)
KIT_STATUSES = (
    "ORDERED", "SHIPPED", "RETURNED", "IN_PROCESSING", "CONSUMED",
    "EXPIRED_STABILIZATION", "CANCELLED",
)
SPECIMEN_STATUSES = ("ACCESSIONED", "PROCESSING", "ADEQUATE", "INADEQUATE", "RESULTED")
COHORT_STATUSES = ("ELIGIBLE", "OUTREACH_SENT", "ORDERED", "SCREENED", "EXCLUDED")
REMINDER_STATUSES = ("SCHEDULED", "SENT", "SKIPPED")
NAVIGATION_STATUSES = ("NOT_REQUIRED", "PENDING", "SCHEDULED", "COMPLETED", "LAPSED")
QUALITY_OUTCOMES = (
    "UNRESOLVED", "ADHERENT_NEGATIVE", "ADHERENT_POSITIVE_NAVIGATED",
    "POSITIVE_NAVIGATION_PENDING", "POSITIVE_NAVIGATION_LAPSED",
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int), "version must be int"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert data["outreach_mode"] in ("PUSH", "SELF_SERVE")
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["population_size"], int)
    assert isinstance(data["attributed_count"], int)
    assert isinstance(data["adherent_count"], int)
    assert isinstance(data["measure_year"], int)


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert data["risk_category"] in ("AVERAGE", "ELEVATED", "HIGH")
    assert isinstance(data["contraindication_flags"], list)
    assert isinstance(data["recent_symptoms"], bool)
    assert isinstance(data["comorbidity"], bool)
    assert isinstance(data["family_history"], bool)
    assert data["status"] in ("ACTIVE", "DECEASED", "OPTED_OUT")


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["channel"] in ("ORDERING", "TELEHEALTH")
    assert isinstance(data["is_active"], bool)


def assert_cohort(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert data["status"] in COHORT_STATUSES
    assert isinstance(data["attributed"], bool)
    assert isinstance(data["adherence_window_start"], str)
    assert isinstance(data["adherence_window_end"], str)


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert data["status"] in ORDER_STATUSES
    assert data["order_channel"] in ("ORDERING", "TELEHEALTH")
    assert data["quality_outcome"] in QUALITY_OUTCOMES
    assert isinstance(data["recollection_round"], int)


def assert_kit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data["kit_serial"], str) and data["kit_serial"]
    assert data["status"] in KIT_STATUSES


def assert_specimen(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("kit_id", ""))
    assert is_valid_uuid(data.get("order_id", ""))
    assert data["status"] in SPECIMEN_STATUSES
    assert data["adequacy"] in ("PENDING", "ADEQUATE", "INADEQUATE")


def assert_result(data: dict):
    # Append-only family: id + created_at only; no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ScreeningResult must not carry updated_at"
    assert "version" not in data, "ScreeningResult must not carry version"
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("specimen_id", ""))
    assert data["outcome"] in ("NEGATIVE", "POSITIVE")
    assert data["navigation_status"] in NAVIGATION_STATUSES


def assert_outreach_event(data: dict):
    # Append-only family: id + created_at only; no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "OutreachEvent must not carry updated_at"
    assert "version" not in data, "OutreachEvent must not carry version"
    assert is_valid_uuid(data.get("cohort_id", ""))
    assert data["channel"] in ("MAIL", "SMS", "PHONE")
    assert isinstance(data["template_code"], str) and data["template_code"]


def assert_reminder(data: dict):
    # Append-only family: id + created_at only; no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Reminder must not carry updated_at"
    assert "version" not in data, "Reminder must not carry version"
    assert is_valid_uuid(data.get("order_id", ""))
    assert data["status"] in REMINDER_STATUSES
    assert isinstance(data["sequence_no"], int)


def assert_quality_measure_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["measure_year"], int)
    assert isinstance(data["numerator"], int)
    assert isinstance(data["denominator"], int)
    assert isinstance(data["adherence_rate"], (int, float))
    assert isinstance(data["snapshot_at"], str) and data["snapshot_at"]
