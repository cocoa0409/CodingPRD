"""Entity assertions and domain invariant checkers.

assert_<entity>(data) checks the fields the PRD says every serializer returns:
the common fields (id / created_at / updated_at / version) plus the
entity-specific fields and their status vocabularies. Invariant checkers
encode the PRD's derived-state rules (sample-ledger conservation, screening
score precision, compensation integer cents, contact interval map).
"""
from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .constants import CONTACT_INTERVAL_DAYS


# =============================================================================
# Response validators with explicit status codes
# =============================================================================

def validate_created(response) -> dict:
    """Create endpoints return 201; never let a bare validate_success default
    of 200 wrap a create call."""
    return validate_success(response, expected_status=201)


def validate_ok(response) -> dict:
    """Reads, advances, updates and other actions on existing resources -> 200."""
    return validate_success(response, expected_status=200)


# =============================================================================
# Common-field building blocks
# =============================================================================

def assert_common_fields(data: Dict[str, Any]) -> None:
    """Every entity carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_optional_timestamp(data: Dict[str, Any], field: str) -> None:
    """A stamped-at-event field is null until its event; then ISO 8601."""
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or ISO 8601, got {value!r}"
    )


def assert_score_2dp(value: float) -> None:
    """Screening scores are carried to exactly 2 decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    scaled = round(value * 100)
    assert abs(value * 100 - scaled) < 1e-6, f"score {value!r} exceeds 2 decimal places"


def assert_integer_cents(value: int) -> None:
    """Compensation amounts are integer cents throughout."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"amount {value!r} must be integer cents"
    )


# =============================================================================
# Per-entity assertions
# =============================================================================

def assert_jurisdiction(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper() and data["state_code"].isalpha()
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["has_post_conviction_dna_statute"], bool)
    assert data["post_conviction_deadline_years"] is None or (
        isinstance(data["post_conviction_deadline_years"], int)
        and data["post_conviction_deadline_years"] >= 1
    )
    assert isinstance(data["clemency_available"], bool)
    assert isinstance(data["compensation_statute_exists"], bool)
    assert data["compensation_cap_cents"] is None or (
        isinstance(data["compensation_cap_cents"], int) and data["compensation_cap_cents"] >= 0
    )
    assert isinstance(data["actual_innocence_enhancement_pct"], int)
    assert 0 <= data["actual_innocence_enhancement_pct"] <= 100


def assert_client(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["inmate_number"], str) and data["inmate_number"]
    assert data.get("facility_name") is None or isinstance(data["facility_name"], str)


def assert_intake_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert is_iso8601_timestamp(data["conviction_date"])
    assert isinstance(data["conviction_summary"], str)
    assert isinstance(data["claim_of_actual_innocence"], bool)
    assert data["claim_strength"] in ("WEAK", "MODERATE", "STRONG", "COMPELLING")
    assert data["evidence_potential"] in (
        "NONE_KNOWN", "UNCERTAIN", "LIKELY_STORED", "CONFIRMED_STORED"
    )
    assert isinstance(data["years_served"], int) and data["years_served"] >= 0
    assert data["health_urgency"] in ("NONE", "MODERATE", "CRITICAL")
    assert isinstance(data["expedited_review"], bool)
    assert data["status"] in (
        "RECEIVED", "SCREENING", "MORE_INFO_REQUESTED", "DECISION_PENDING",
        "ACCEPTED", "REJECTED", "WAITLISTED",
    )
    for score_field in (
        "screening_score_standard", "screening_score_expedited", "waitlist_priority_score"
    ):
        value = data.get(score_field)
        if value is not None:
            assert_score_2dp(value)
    assert data.get("recommendation") in (None, "ACCEPT", "REJECT", "WAITLIST")
    assert data.get("recommended_by_user_id") is None or isinstance(
        data["recommended_by_user_id"], str
    )
    assert data.get("decided_by_user_id") is None or isinstance(data["decided_by_user_id"], str)
    assert data.get("decision") in (None, "ACCEPTED", "REJECTED", "WAITLISTED")
    assert data.get("decision_reason") is None or isinstance(data["decision_reason"], str)
    assert data.get("accepted_case_id") is None or is_valid_uuid(data["accepted_case_id"])
    assert data.get("supplement_notes") is None or isinstance(data["supplement_notes"], str)


def assert_case(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["intake_request_id"])
    assert data.get("assigned_attorney_id") is None or isinstance(
        data["assigned_attorney_id"], str
    )
    assert data["status"] in (
        "OPEN", "INVESTIGATION", "TESTING", "LITIGATION", "EXONERATED", "CLOSED"
    )
    assert data.get("resolution") in (
        None, "UNSUBSTANTIATED", "EVIDENCE_LOST", "CLIENT_WITHDREW", "OTHER"
    )
    assert data["evidence_posture"] in (
        "NO_EVIDENCE", "SEEKING", "SECURED", "PARTIALLY_COMPROMISED",
        "FULLY_COMPROMISED", "EXCULPATORY",
    )
    assert isinstance(data["destroyed_evidence_count"], int) and data["destroyed_evidence_count"] >= 0
    assert isinstance(data["exculpatory_evidence_flag"], bool)
    assert data.get("strategy_notes") is None or isinstance(data["strategy_notes"], str)
    assert data.get("theory_of_case") is None or isinstance(data["theory_of_case"], str)
    assert is_iso8601_timestamp(data["last_contact_at"])
    assert isinstance(data["contact_count"], int) and data["contact_count"] >= 0
    assert isinstance(data["contact_overdue"], bool)
    expected_interval = CONTACT_INTERVAL_DAYS.get(data["status"], "unset")
    if expected_interval != "unset":
        assert data["contact_interval_days"] == expected_interval, (
            f"contact_interval_days must be {expected_interval} while status is "
            f"{data['status']}, got {data['contact_interval_days']!r}"
        )
    assert data.get("last_expectation_setting") in (None, "CAUTIOUS", "NEUTRAL", "OPTIMISTIC")
    assert_optional_timestamp(data, "exoneration_date")
    assert isinstance(data["release_housing_ready"], bool)
    assert isinstance(data["release_id_documents_ready"], bool)
    assert isinstance(data["release_transportation_ready"], bool)
    assert_optional_timestamp(data, "scheduled_release_date")
    assert data["release_readiness"] in ("NOT_APPLICABLE", "PLANNING", "READY", "RELEASED")


def assert_evidence_item(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert isinstance(data["description"], str) and data["description"]
    assert data["evidence_type"] in (
        "BIOLOGICAL_SWAB", "CLOTHING", "WEAPON", "FINGERPRINT_CARD", "OTHER"
    )
    assert data["custodian_type"] in (
        "COURT_CLERK", "POLICE_PROPERTY", "CRIME_LAB", "MEDICAL_EXAMINER"
    )
    assert data["location_status"] in (
        "IDENTIFIED", "SEARCHING", "LOCATED", "REPORTED_MISSING",
        "REPORTED_DESTROYED", "CUSTODY_CONFIRMED", "DESTRUCTION_VERIFIED",
    )
    assert data["testing_status"] in (
        "UNTESTED", "TESTING_AUTHORIZED", "SAMPLE_RESERVED", "TESTED", "SAMPLE_EXHAUSTED"
    )
    assert isinstance(data["initial_sample_ng"], int) and data["initial_sample_ng"] >= 1
    assert isinstance(data["remaining_sample_ng"], int) and data["remaining_sample_ng"] >= 0


def assert_records_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert data["agency_type"] in ("COURT", "POLICE", "LABORATORY", "MEDICAL_EXAMINER")
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert isinstance(data["request_summary"], str)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "FULFILLED", "PARTIALLY_FULFILLED", "DENIED", "APPEALED"
    )
    assert data.get("response_disposition") in (
        None, "FULFILLED", "PARTIALLY_FULFILLED", "DENIED"
    )
    assert isinstance(data["items_revealed"], list)
    for entry in data["items_revealed"]:
        assert is_valid_uuid(entry["evidence_item_id"])
        assert entry["disposition"] in ("LOCATED", "DESTROYED", "MISSING")


def assert_testing_authorization(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["evidence_item_id"])
    assert data["kind"] in ("AGREEMENT", "MOTION")
    assert data["status"] in (
        "DRAFTED", "PROPOSED", "NEGOTIATING", "SIGNED", "REJECTED_BY_PROSECUTION",
        "FILED", "GRANTED", "DENIED", "APPEALED",
    )
    assert data.get("terms") is None or isinstance(data["terms"], str)
    assert data.get("proposed_test_types") is None or isinstance(
        data["proposed_test_types"], list
    )
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data.get("last_ruling") in (None, "GRANTED", "DENIED")


def assert_lab_analysis(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["evidence_item_id"])
    assert is_valid_uuid(data["authorization_id"])
    assert isinstance(data["lab_name"], str) and data["lab_name"]
    assert data["test_type"] in (
        "DNA_STR", "DNA_TOUCH", "DNA_YSTR", "MITOCHONDRIAL_DNA", "SEROLOGY"
    )
    assert isinstance(data["required_sample_ng"], int) and data["required_sample_ng"] >= 1
    assert isinstance(data["reserved_sample_ng"], int) and data["reserved_sample_ng"] >= 1
    consumed = data.get("actual_consumed_ng")
    if consumed is not None:
        assert isinstance(consumed, int) and 1 <= consumed <= data["reserved_sample_ng"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in (
        "SCHEDULED", "SAMPLE_SHIPPED", "RESULT_RECORDED", "INTERPRETED", "CANCELLED"
    )
    assert data.get("outcome") in (
        None, "EXCLUSIONARY", "INCLUSIONARY", "INCONCLUSIVE", "NO_PROFILE"
    )
    assert data.get("profile_obtained") is None or isinstance(data["profile_obtained"], bool)
    assert data.get("expert_name") is None or isinstance(data["expert_name"], str)
    assert data.get("expert_interpretation") in (
        None, "SUPPORTS_INNOCENCE", "NEUTRAL", "SUPPORTS_CONVICTION"
    )
    assert data["db_comparison_status"] in (
        "NOT_RUN", "COMPLETED_HIT", "COMPLETED_NO_HIT", "COMPLETED_PARTIAL"
    )
    assert data.get("db_matched_subject_name") is None or isinstance(
        data["db_matched_subject_name"], str
    )


def assert_legal_petition(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert data["petition_type"] in (
        "POST_CONVICTION", "DIRECT_APPEAL", "CLEMENCY", "HABEAS_CORPUS"
    )
    assert isinstance(data["court_name"], str) and data["court_name"]
    assert data["claim_basis"] in ("ACTUAL_INNOCENCE", "PROCEDURAL", "BOTH")
    assert data["status"] in (
        "DRAFT", "FILED", "DECIDED_GRANTED", "DECIDED_DENIED", "APPEAL_FILED"
    )
    assert data.get("decision_vacates_conviction") is None or isinstance(
        data["decision_vacates_conviction"], bool
    )
    assert_optional_timestamp(data, "filed_at")
    assert_optional_timestamp(data, "decided_at")


def assert_compensation_claim(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert isinstance(data["years_incarcerated_claimed"], int)
    assert data["years_incarcerated_claimed"] >= 1
    assert isinstance(data["documented_legal_fees_cents"], int)
    assert data["documented_legal_fees_cents"] >= 0
    assert_integer_cents(data["provisional_estimate_cents"])
    if data.get("final_award_cents") is not None:
        assert_integer_cents(data["final_award_cents"])
    if data.get("paid_amount_cents") is not None:
        assert_integer_cents(data["paid_amount_cents"])
    assert data["status"] in ("DRAFT", "FILED", "APPROVED", "DENIED", "APPEALED", "PAID")


def assert_reentry_provider(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["service_type"] in ("HOUSING", "EMPLOYMENT", "MEDICAL", "COUNSELING")
    assert isinstance(data["total_capacity"], int) and data["total_capacity"] >= 1
    assert isinstance(data["slots_in_use"], int) and data["slots_in_use"] >= 0


def assert_reentry_referral(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["provider_id"])
    assert is_iso8601_timestamp(data["service_start"])
    assert is_iso8601_timestamp(data["service_end"])
    assert data["status"] in ("PENDING", "ACTIVE", "COMPLETED", "CANCELLED")


def assert_policy_initiative(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["jurisdiction_id"])
    assert data["topic"] in (
        "EVIDENCE_PRESERVATION", "COMPENSATION_REFORM", "DATABASE_ACCESS",
        "RECORDS_TRANSPARENCY",
    )
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in ("PROPOSED", "RESEARCHING", "DRAFTED", "ADOPTED", "STALLED")
    assert isinstance(data["pattern_case_count"], int) and data["pattern_case_count"] >= 0


# =============================================================================
# Domain invariant checkers
# =============================================================================

def assert_sample_ledger_conservation(
    item: Dict[str, Any], analyses: Iterable[Dict[str, Any]]
) -> None:
    """Sample-mass conservation over one evidence item (PRD section 3.5):
    initial == remaining + reserved(SCHEDULED|SAMPLE_SHIPPED)
                      + consumed(RESULT_RECORDED|INTERPRETED)."""
    reserved = sum(
        a["reserved_sample_ng"]
        for a in analyses
        if a["status"] in ("SCHEDULED", "SAMPLE_SHIPPED")
    )
    consumed = sum(
        a["actual_consumed_ng"] or 0
        for a in analyses
        if a["status"] in ("RESULT_RECORDED", "INTERPRETED")
    )
    assert item["initial_sample_ng"] == item["remaining_sample_ng"] + reserved + consumed, (
        f"ledger drift on item {item['id']}: initial {item['initial_sample_ng']} != "
        f"remaining {item['remaining_sample_ng']} + reserved {reserved} + consumed {consumed}"
    )


def assert_new_case_defaults(case: Dict[str, Any], intake_request_id: str) -> None:
    """The ACCEPTED-decision cascade's initial Case state (PRD section 3.2)."""
    assert_case(case)
    assert case["intake_request_id"] == intake_request_id
    assert case["status"] == "OPEN"
    assert case["exculpatory_evidence_flag"] is False
    assert case["destroyed_evidence_count"] == 0
    assert case["evidence_posture"] == "NO_EVIDENCE"
    assert case["release_readiness"] == "NOT_APPLICABLE"
    assert case["contact_count"] == 0
    assert case["contact_overdue"] is False
    assert case["contact_interval_days"] == 90
    assert case["resolution"] is None
    assert case["exoneration_date"] is None
    assert case["release_housing_ready"] is False
    assert case["release_id_documents_ready"] is False
    assert case["release_transportation_ready"] is False
    assert case["version"] == 1


def assert_contact_interval_matches_status(case: Dict[str, Any]) -> None:
    """contact_interval_days mirrors the status map; null when CLOSED."""
    expected = CONTACT_INTERVAL_DAYS[case["status"]]
    assert case["contact_interval_days"] == expected, (
        f"status {case['status']} expects interval {expected}, "
        f"got {case['contact_interval_days']!r}"
    )


def assert_slots_in_use_consistent(
    provider: Dict[str, Any], referrals: Iterable[Dict[str, Any]]
) -> None:
    """slots_in_use == count of this provider's referrals in PENDING or ACTIVE
    (window-independent)."""
    live = [
        r for r in referrals
        if r["provider_id"] == provider["id"] and r["status"] in ("PENDING", "ACTIVE")
    ]
    assert provider["slots_in_use"] == len(live), (
        f"provider {provider['id']} slots_in_use {provider['slots_in_use']} != "
        f"live referral count {len(live)}"
    )
