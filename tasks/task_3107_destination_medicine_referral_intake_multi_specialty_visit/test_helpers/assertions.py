"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

REFERRAL_STATES = {"SUBMITTED", "RECORDS_PENDING", "IN_REVIEW", "REVIEWED", "DECLINED", "CLOSED"}
RECORD_STATES = {"RECEIVED", "VERIFIED", "REJECTED"}
CASE_STATES = {
    "INTAKE", "AWAITING_FINANCIAL", "FINANCIAL_CLEARED", "SCHEDULING", "SCHEDULED",
    "READY_TO_TRAVEL", "COMPLETED", "WITHDRAWN", "DECLINED",
}
CLEARANCE_STATES = {"PENDING", "CLEARED", "FORFEITED", "SETTLED", "WAIVED"}
ITINERARY_STATES = {"DRAFT", "CONFIRMED", "LOCKED", "CANCELLED"}
SLOT_STATES = {"OPEN", "HELD", "CONFIRMED", "RELEASED", "CANCELLED"}
VISIT_STATES = {"PENDING", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW"}
LOGISTICS_STATES = {"REQUESTED", "BOOKED", "CANCELLED"}
LETTER_STATES = {"ISSUED", "SUPERSEDED"}


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_specialty_service(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["destination_daily_capacity"], int)
    assert data["destination_daily_capacity"] >= 1
    assert isinstance(data["service_window_start_min"], int)
    assert isinstance(data["service_window_end_min"], int)
    assert isinstance(data["supports_imaging"], bool)
    assert isinstance(data["supports_remote_products"], bool)


def assert_referral(data: dict):
    _assert_common(data)
    assert data["status"] in REFERRAL_STATES
    assert isinstance(data["referring_physician_name"], str)
    assert isinstance(data["reason"], str)


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["residence_country"], str)
    assert isinstance(data["is_international"], bool)
    assert isinstance(data["requires_interpreter"], bool)


def assert_medical_record(data: dict):
    _assert_common(data)
    assert data["status"] in RECORD_STATES
    assert data["record_type"] in {
        "IMAGING", "LAB", "PATHOLOGY", "CLINICAL_NOTES", "MEDICATION_LIST",
    }
    assert isinstance(data["referral_id"], str)


def assert_visit_case(data: dict):
    _assert_common(data)
    assert data["status"] in CASE_STATES
    assert data["case_type"] in {"DESTINATION", "SECOND_OPINION", "REMOTE_CONSULT"}
    assert isinstance(data["fatigue_score"], int)
    assert isinstance(data["version"], int)


def assert_financial_clearance(data: dict):
    _assert_common(data)
    assert data["status"] in CLEARANCE_STATES
    assert isinstance(data["deposit_paid_cents"], int)
    assert isinstance(data["required_deposit_cents"], int)
    assert isinstance(data["holds_released"], bool)


def assert_itinerary(data: dict):
    _assert_common(data)
    assert data["status"] in ITINERARY_STATES
    assert isinstance(data["revision"], int)
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["final_total_cents"], int)


def assert_appointment_slot(data: dict):
    _assert_common(data)
    assert data["status"] in SLOT_STATES
    assert isinstance(data["start_min"], int)
    assert isinstance(data["end_min"], int)


def assert_visit(data: dict):
    _assert_common(data)
    assert data["status"] in VISIT_STATES
    assert data["visit_type"] in {"CONSULT", "IMAGING", "LAB_TEST", "PROCEDURE"}
    assert isinstance(data["listed_price_cents"], int)
    assert isinstance(data["sequencing_priority"], int)


def assert_logistics_arrangement(data: dict):
    _assert_common(data)
    assert data["status"] in LOGISTICS_STATES
    assert data["arrangement_type"] in {"TRAVEL", "LODGING", "INTERPRETER"}


def assert_estimate_letter(data: dict):
    _assert_common(data)
    assert data["status"] in LETTER_STATES
    assert isinstance(data["is_stale"], bool)
    assert isinstance(data["deposit_amount_cents"], int)
    assert isinstance(data["provisional_estimate_cents"], int)
    assert isinstance(data["final_estimate_cents"], int)


def assert_billing_transaction(data: dict):
    _assert_common(data)
    assert data["txn_type"] in {"DEPOSIT", "SETTLEMENT", "REFUND"}
    assert data["status"] in {"POSTED", "VOID"}
    assert isinstance(data["amount_cents"], int)
