"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AppointmentStatus, AssessmentStatus, AuthorizationStatus, ClaimDenialReason,
    ClaimStatus, ContractScheduling, ContractStatus, CredentialingStatus,
    DocumentationStatus, ExtensionRequestStatus, GeoClassification, PriorityBand,
    PrescriptionFillStatus, SchedulingResponsibility, ServiceCategory,
    TimelinessAnchor, UrgentCareVisitStatus,
)


def _values(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_fields(data: dict):
    """Every resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_care_station(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["latitude"], (int, float)) and -90 <= data["latitude"] <= 90
    assert isinstance(data["longitude"], (int, float)) and -180 <= data["longitude"] <= 180
    assert isinstance(data["primary_wait_days"], int) and data["primary_wait_days"] >= 0
    assert isinstance(data["specialty_wait_days"], int) and data["specialty_wait_days"] >= 0
    assert isinstance(data["service_codes"], list)


def assert_tpa(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["contract_status"] in _values(ContractStatus)
    assert isinstance(data["adjudicated_events"], int) and data["adjudicated_events"] >= 0
    assert isinstance(data["denied_events"], int) and data["denied_events"] >= 0
    assert data["denied_events"] <= data["adjudicated_events"]
    assert isinstance(data["denial_rate"], (int, float))


def assert_community_provider(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("tpa_id", "")), "tpa_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["service_codes"], list)
    assert isinstance(data["contract_rates"], dict)
    assert data["contract_scheduling"] in _values(ContractScheduling)
    assert data["credentialing_status"] in _values(CredentialingStatus)
    assert isinstance(data["latitude"], (int, float))
    assert isinstance(data["longitude"], (int, float))
    assert_payment_buckets_conserved(data)


def assert_veteran(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data.get("home_station_id", "")), "home_station_id must be a UUID"
    assert isinstance(data["priority_group"], int) and 1 <= data["priority_group"] <= 8
    assert isinstance(data["home_latitude"], (int, float))
    assert isinstance(data["home_longitude"], (int, float))


def assert_eligibility_assessment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("veteran_id", "")), "veteran_id must be a UUID"
    assert isinstance(data["service_code"], str) and data["service_code"]
    assert data["service_category"] in _values(ServiceCategory)
    assert data["geo_classification"] in _values(GeoClassification)
    assert isinstance(data["choice_requested"], bool)
    assert isinstance(data["drive_time_minutes"], (int, float))
    assert isinstance(data["wait_days"], int) and data["wait_days"] >= 0
    for flag in ("service_available", "drive_standard_failed",
                 "wait_standard_failed", "choice_granted", "eligible"):
        assert isinstance(data[flag], bool), f"{flag} must be bool"
    # eligible is the OR of its four legs
    expected = ((not data["service_available"]) or data["drive_standard_failed"]
                or data["wait_standard_failed"] or data["choice_granted"])
    assert data["eligible"] == expected, \
        f"eligible {data['eligible']} != OR of legs ({expected})"
    assert data["status"] in _values(AssessmentStatus)


def assert_referral_authorization(data: dict):
    assert_common_fields(data)
    for fk in ("veteran_id", "assessment_id", "provider_id", "tpa_id"):
        assert is_valid_uuid(data.get(fk, "")), f"{fk} must be a UUID"
    assert isinstance(data["service_code"], str) and data["service_code"]
    assert 1 <= data["authorized_visits"] <= 12
    assert 1 <= data["duration_days"] <= 365
    assert isinstance(data["start_date"], str) and len(data["start_date"]) == 10
    assert isinstance(data["end_date_exclusive"], str)
    for field in ("extended_visits", "reserved_visits", "completed_visits",
                  "remaining_visits"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["scheduling_responsibility"] in _values(SchedulingResponsibility)
    assert data["authorized_at"] is None or is_iso8601_timestamp(data["authorized_at"])
    assert data["docs_suspension_return_state"] in (None, "AUTHORIZED", "ACTIVE")
    assert data["status"] in _values(AuthorizationStatus)
    assert_visit_ledger_conserved(data)


def assert_extension_request(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("referral_authorization_id", ""))
    assert isinstance(data["requested_visits"], int) and data["requested_visits"] >= 1
    assert isinstance(data["requested_extra_days"], int) and data["requested_extra_days"] >= 0
    assert data["status"] in _values(ExtensionRequestStatus)
    if data["status"] == "PENDING":
        assert data["decided_at"] is None
    else:
        assert is_iso8601_timestamp(data["decided_at"])


def assert_appointment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("referral_authorization_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert isinstance(data["requested_date"], str) and len(data["requested_date"]) == 10
    assert data["timeliness_anchor"] in _values(TimelinessAnchor)
    assert isinstance(data["within_standard"], bool)
    assert data["status"] in _values(AppointmentStatus)
    if data["status"] == "COMPLETED":
        assert is_iso8601_timestamp(data["completed_at"])
    else:
        assert data["completed_at"] is None


def assert_medical_documentation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("appointment_id", ""))
    assert is_valid_uuid(data.get("referral_authorization_id", ""))
    assert data["status"] in _values(DocumentationStatus)
    assert is_iso8601_timestamp(data["deadline_at"])
    assert isinstance(data["rejection_count"], int) and data["rejection_count"] >= 0
    if data["status"] in ("RECEIVED", "ACCEPTED"):
        assert data["content_ref"], "submitted record must carry content_ref"
        assert is_iso8601_timestamp(data["submitted_at"])


def assert_claim(data: dict):
    assert_common_fields(data)
    for fk in ("referral_authorization_id", "provider_id", "tpa_id"):
        assert is_valid_uuid(data.get(fk, "")), f"{fk} must be a UUID"
    assert isinstance(data["service_date"], str) and len(data["service_date"]) == 10
    assert isinstance(data["service_lines"], list) and len(data["service_lines"]) >= 1
    total = 0
    for line in data["service_lines"]:
        assert isinstance(line["units"], int)
        assert isinstance(line["unit_billed_cents"], int)
        assert line["service_category"] in _values(ServiceCategory)
        total += line["unit_billed_cents"] * line["units"]
    assert data["billed_total_cents"] == total, \
        f"billed_total_cents {data['billed_total_cents']} != sum over lines {total}"
    assert data["status"] in _values(ClaimStatus)
    assert isinstance(data["resubmit_count"], int) and 0 <= data["resubmit_count"] <= 2
    assert is_iso8601_timestamp(data["submitted_at"])
    if data["status"] in ("PAID", "REVERSED"):
        assert isinstance(data["paid_amount_cents"], int)
    else:
        assert data["paid_amount_cents"] is None
    if data["status"] == "DENIED":
        assert data["denial_reason"] in _values(ClaimDenialReason)
    if data["status"] == "REVERSED":
        assert isinstance(data["reversed_reason"], str) and data["reversed_reason"]


def assert_urgent_care_visit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("veteran_id", ""))
    assert isinstance(data["facility_name"], str) and data["facility_name"]
    assert isinstance(data["visit_date"], str) and len(data["visit_date"]) == 10
    assert isinstance(data["fiscal_year"], int)
    # FY starts October 1: month >= 10 -> year + 1, else year
    month = int(data["visit_date"][5:7])
    year = int(data["visit_date"][0:4])
    expected_fy = year + 1 if month >= 10 else year
    assert data["fiscal_year"] == expected_fy, \
        f"fiscal_year {data['fiscal_year']} != {expected_fy} for {data['visit_date']}"
    assert data["priority_band"] in _values(PriorityBand)
    assert isinstance(data["visit_index_in_fy"], int) and data["visit_index_in_fy"] >= 1
    assert isinstance(data["copay_cents"], int) and data["copay_cents"] >= 0
    assert data["status"] in _values(UrgentCareVisitStatus)


def assert_prescription_fill_request(data: dict):
    assert_common_fields(data)
    links = [data.get("urgent_care_visit_id"), data.get("appointment_id")]
    assert sum(1 for link in links if link) == 1, \
        "exactly one of urgent_care_visit_id / appointment_id must be set"
    assert isinstance(data["medication_name"], str) and data["medication_name"]
    assert isinstance(data["days_supply"], int) and data["days_supply"] >= 1
    assert isinstance(data["controlled_substance"], bool)
    assert data["status"] in _values(PrescriptionFillStatus)
    if data["status"] == "REQUESTED":
        assert data["decided_at"] is None
    else:
        assert is_iso8601_timestamp(data["decided_at"])
    if data["status"] == "REFUSED":
        assert isinstance(data["refusal_reason"], str) and data["refusal_reason"]


# ---------------------------------------------------------------------------
# Domain invariants (conserved ledgers)
# ---------------------------------------------------------------------------

def assert_visit_ledger_conserved(authorization: dict):
    """authorized + extended == completed + reserved + remaining at all times."""
    lhs = authorization["authorized_visits"] + authorization["extended_visits"]
    rhs = (authorization["completed_visits"] + authorization["reserved_visits"]
           + authorization["remaining_visits"])
    assert lhs == rhs, (
        f"Visit ledger unbalanced: {authorization['authorized_visits']} + "
        f"{authorization['extended_visits']} != {authorization['completed_visits']} + "
        f"{authorization['reserved_visits']} + {authorization['remaining_visits']}"
    )


def assert_payment_buckets_conserved(provider: dict):
    """lifetime_paid_cents == current_paid_cents + reversed_cents at all times."""
    for field in ("lifetime_paid_cents", "current_paid_cents", "reversed_cents"):
        assert isinstance(provider[field], int) and provider[field] >= 0
    assert provider["lifetime_paid_cents"] == (
        provider["current_paid_cents"] + provider["reversed_cents"]
    ), (
        f"Payment buckets unbalanced: lifetime {provider['lifetime_paid_cents']} != "
        f"current {provider['current_paid_cents']} + reversed {provider['reversed_cents']}"
    )
