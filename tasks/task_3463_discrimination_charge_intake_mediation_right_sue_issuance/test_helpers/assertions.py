"""Entity assertions and domain invariant checkers.

Status-code discipline (PRD section 4): creates return 201, every other
success returns 200. Use validate_created()/validate_ok() — both pin the
expected status explicitly; never rely on an assumed default for creates.

The expected_* calculators mirror the PRD's pinned arithmetic so tests can
compare observed values against an independently computed expectation.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .constants import (
    ANNUAL_INTEREST_RATE,
    BASIS_SEVERITY_WEIGHT,
    CAP_TIER_CENTS,
    ESCALATION_THRESHOLD,
    INTEREST_DIVISOR_DAYS,
    OVERDUE_COMPONENT_CAP,
    OVERDUE_PER_REQUEST,
    PRIORITY_AGE_TIERS,
    SCORE_CEILING,
    SYSTEMIC_MULTIPLIER,
    expected_size_band,
)
from .types import (
    BasisCode,
    ChargeStatus,
    ConciliationStatus,
    DeterminationOutcome,
    DeterminationStatus,
    DisclosureHold,
    EvidenceRequestStatus,
    EvidenceRequestType,
    InvestigationCaseStatus,
    InvestigationOwner,
    IssuanceBasis,
    JurisdictionOutcome,
    LegalBasis,
    MediationCaseStatus,
    MediationSessionStatus,
    OfferSide,
    PartyResponse,
    RightToSueStatus,
    SettledVia,
    SizeBand,
    SystemicCaseStatus,
    ValuationVariant,
    WorkSharingPolicy,
)


# ---------------------------------------------------------------------------
# Explicit-status success validators (PRD section 4)
# ---------------------------------------------------------------------------
def validate_created(response) -> dict:
    """For endpoints that create a resource: 201."""
    return validate_success(response, 201)


def validate_ok(response) -> dict:
    """For reads and non-create actions: 200."""
    return validate_success(response, 200)


# ---------------------------------------------------------------------------
# Pinned arithmetic (PRD sections 3.5 and 3.7)
# ---------------------------------------------------------------------------
def round_half_up(value) -> int:
    """Round half-up to a whole number (PRD section 2.10)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_priority_score(
    basis_codes: List[str],
    days_elapsed_since_filing: int,
    overdue_request_count: int,
    systemic_linked: bool,
) -> int:
    """PRD section 3.5 priority formula: MAX severity + tiered age points +
    capped per-request overdue points, optionally multiplied by 1.5, rounded
    half-up once after multiplication, clamped to 100."""
    severity = max(BASIS_SEVERITY_WEIGHT[b] for b in basis_codes)
    age_points = 0
    for min_days, points in PRIORITY_AGE_TIERS:
        if days_elapsed_since_filing >= min_days:
            age_points = points
    overdue_points = min(
        OVERDUE_PER_REQUEST * overdue_request_count, OVERDUE_COMPONENT_CAP
    )
    multiplier = Decimal(str(SYSTEMIC_MULTIPLIER)) if systemic_linked else Decimal("1.0")
    raw = (Decimal(severity + age_points + overdue_points)) * multiplier
    score = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return min(SCORE_CEILING, score)


def expected_priority_escalated(
    basis_codes: List[str],
    days_elapsed_since_filing: int,
    overdue_request_count: int,
    systemic_linked: bool,
) -> bool:
    """True when the recomputed score reaches ESCALATION_THRESHOLD (80)."""
    return (
        expected_priority_score(
            basis_codes, days_elapsed_since_filing, overdue_request_count,
            systemic_linked,
        )
        >= ESCALATION_THRESHOLD
    )


def expected_interest_cents(component_cents: int, interest_days: int) -> int:
    """round_half_up(component * 0.05 * interest_days / 365) — per component,
    before any summation (PRD section 3.7 pins this order)."""
    raw = (
        Decimal(component_cents)
        * Decimal(str(ANNUAL_INTEREST_RATE))
        * Decimal(interest_days)
        / Decimal(INTEREST_DIVISOR_DAYS)
    )
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_remedy_valuation(
    back_pay_cents: int,
    front_pay_cents: int,
    compensatory_damages_cents: int,
    punitive_damages_cents: int,
    band_used: str,
    interest_days: int,
) -> dict:
    """Full PRD section 3.7 valuation in the pinned round-then-sum order."""
    back_interest = expected_interest_cents(back_pay_cents, interest_days)
    front_interest = expected_interest_cents(front_pay_cents, interest_days)
    nonpecuniary = compensatory_damages_cents + punitive_damages_cents
    capped = min(nonpecuniary, CAP_TIER_CENTS[band_used])
    total = (
        back_pay_cents + front_pay_cents + back_interest + front_interest + capped
    )
    return {
        "band_used": band_used,
        "interest_days": interest_days,
        "back_pay_interest_cents": back_interest,
        "front_pay_interest_cents": front_interest,
        "capped_nonpecuniary_cents": capped,
        "total_cents": total,
    }


# ---------------------------------------------------------------------------
# Internal field helpers
# ---------------------------------------------------------------------------
def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def _assert_enum(value, enum_cls, field: str):
    members = [m.value for m in enum_cls]
    assert value in members, f"{field} must be one of {members}, got {value!r}"


def _assert_optional_str(data: dict, field: str):
    assert field in data, f"{field} must be present (null allowed)"
    assert data[field] is None or isinstance(data[field], str)


def _assert_optional_int(data: dict, field: str):
    assert field in data, f"{field} must be present (null allowed)"
    assert data[field] is None or isinstance(data[field], int)


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_complainant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_employer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["employee_count_current"], int)
    assert data["employee_count_current"] >= 0
    _assert_enum(data["size_band"], SizeBand, "size_band")
    assert data["size_band"] == expected_size_band(data["employee_count_current"]), (
        f"size_band {data['size_band']} inconsistent with "
        f"employee_count_current {data['employee_count_current']}"
    )


def assert_deferral_agency(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert data["filing_deadline_days"] in (180, 300), (
        "filing_deadline_days accepts only 180 or 300 (PRD section 3.1)"
    )
    _assert_enum(data["work_sharing_policy"], WorkSharingPolicy, "work_sharing_policy")
    assert isinstance(data["covers_age"], bool)


def assert_charge(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["complainant_id"])
    assert is_valid_uuid(data["employer_id"])
    assert "deferral_agency_id" in data
    assert data["deferral_agency_id"] is None or is_valid_uuid(data["deferral_agency_id"])
    assert isinstance(data["basis_codes"], list) and len(data["basis_codes"]) >= 1
    for b in data["basis_codes"]:
        _assert_enum(b, BasisCode, "basis_codes[]")
    assert isinstance(data["covered_bases"], list)
    for b in data["covered_bases"]:
        _assert_enum(b, BasisCode, "covered_bases[]")
    assert set(data["covered_bases"]).issubset(set(data["basis_codes"])), (
        "covered_bases must be a subset of basis_codes (PRD section 3.2)"
    )
    assert isinstance(data["incident_date"], str) and data["incident_date"]
    assert isinstance(data["harm_description"], str)
    assert isinstance(data["employee_count_at_incident"], int)
    assert data["employee_count_at_incident"] >= 0
    assert isinstance(data["received_date"], str) and data["received_date"]
    _assert_enum(data["case_status"], ChargeStatus, "case_status")
    _assert_enum(data["disclosure_hold"], DisclosureHold, "disclosure_hold")
    _assert_enum(data["jurisdiction_outcome"], JurisdictionOutcome, "jurisdiction_outcome")
    assert isinstance(data["filing_deadline_date"], str) and data["filing_deadline_date"]
    _assert_enum(data["investigation_owner"], InvestigationOwner, "investigation_owner")
    assert isinstance(data["dual_filed"], bool)
    assert "investigation_case_id" in data
    assert data["investigation_case_id"] is None or is_valid_uuid(
        data["investigation_case_id"]
    )
    assert isinstance(data["priority_escalated"], bool)
    assert isinstance(data["settled_amount_cents"], int)
    assert data["settled_amount_cents"] >= 0
    assert "settled_via" in data
    if data["settled_via"] is not None:
        _assert_enum(data["settled_via"], SettledVia, "settled_via")
    assert "settled_at" in data
    assert data["settled_at"] is None or isinstance(data["settled_at"], str)
    assert "systemic_case_id" in data
    assert data["systemic_case_id"] is None or is_valid_uuid(data["systemic_case_id"])
    assert isinstance(data["days_elapsed_since_filing"], int)
    assert data["days_elapsed_since_filing"] >= 0


def assert_mediation_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["charge_id"])
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    _assert_enum(data["complainant_response"], PartyResponse, "complainant_response")
    _assert_enum(data["respondent_response"], PartyResponse, "respondent_response")
    _assert_enum(data["status"], MediationCaseStatus, "status")
    _assert_optional_int(data, "settlement_amount_cents")
    if data["settlement_amount_cents"] is not None:
        assert data["settlement_amount_cents"] > 0
    assert "concluded_at" in data
    assert data["concluded_at"] is None or isinstance(data["concluded_at"], str)


def assert_mediation_session(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["mediation_case_id"])
    assert isinstance(data["mediator_user_id"], str) and data["mediator_user_id"]
    assert isinstance(data["scheduled_start"], str) and data["scheduled_start"]
    assert isinstance(data["scheduled_end"], str) and data["scheduled_end"]
    _assert_enum(data["status"], MediationSessionStatus, "status")


def assert_investigation_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["charge_id"])
    assert "assigned_investigator_id" in data
    assert data["assigned_investigator_id"] is None or isinstance(
        data["assigned_investigator_id"], str
    )
    _assert_enum(data["status"], InvestigationCaseStatus, "status")
    assert isinstance(data["open_request_count"], int)
    assert data["open_request_count"] >= 0
    assert isinstance(data["overdue_request_count"], int)
    assert data["overdue_request_count"] >= 0
    assert data["overdue_request_count"] <= data["open_request_count"], (
        "OVERDUE requests are a subset of open (PENDING+OVERDUE) requests"
    )
    assert isinstance(data["priority_score"], int)
    assert 0 <= data["priority_score"] <= SCORE_CEILING


def assert_evidence_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["investigation_case_id"])
    _assert_enum(data["request_type"], EvidenceRequestType, "request_type")
    assert isinstance(data["issued_date"], str) and data["issued_date"]
    assert isinstance(data["due_date"], str) and data["due_date"]
    _assert_enum(data["status"], EvidenceRequestStatus, "status")
    _assert_optional_str(data, "response_text")
    assert isinstance(data["responded_late"], bool)


def assert_witness_interview(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["investigation_case_id"])
    assert isinstance(data["investigator_user_id"], str)
    assert data["investigator_user_id"]
    assert isinstance(data["witness_name"], str) and data["witness_name"]
    assert isinstance(data["interview_start"], str) and data["interview_start"]
    assert isinstance(data["interview_end"], str) and data["interview_end"]
    assert isinstance(data["summary"], str)


def assert_determination(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["investigation_case_id"])
    _assert_enum(data["outcome"], DeterminationOutcome, "outcome")
    assert isinstance(data["rationale"], str) and data["rationale"]
    for field in (
        "back_pay_cents",
        "front_pay_cents",
        "compensatory_damages_cents",
        "punitive_damages_cents",
    ):
        _assert_optional_int(data, field)
        if data[field] is not None:
            assert data[field] >= 0
    assert "harm_start_date" in data
    assert data["harm_start_date"] is None or isinstance(data["harm_start_date"], str)
    if data["outcome"] == DeterminationOutcome.CAUSE.value:
        for field in (
            "back_pay_cents",
            "front_pay_cents",
            "compensatory_damages_cents",
            "punitive_damages_cents",
            "harm_start_date",
        ):
            assert data[field] is not None, f"CAUSE requires {field} (PRD section 3.6)"
    else:
        for field in (
            "back_pay_cents",
            "front_pay_cents",
            "compensatory_damages_cents",
            "punitive_damages_cents",
            "harm_start_date",
        ):
            assert data[field] is None, (
                f"{field} must be null for outcome {data['outcome']} (PRD section 3.6)"
            )
    _assert_enum(data["status"], DeterminationStatus, "status")
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    _assert_optional_str(data, "reviewed_by_user_id")
    _assert_optional_str(data, "return_reason")


def assert_conciliation_process(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["charge_id"])
    assert isinstance(data["origin_determination_id"], str)
    assert data["origin_determination_id"]
    _assert_enum(data["status"], ConciliationStatus, "status")
    _assert_optional_int(data, "current_offer_cents")
    assert "last_offer_by" in data
    if data["last_offer_by"] is not None:
        _assert_enum(data["last_offer_by"], OfferSide, "last_offer_by")
    assert isinstance(data["rounds_count"], int) and data["rounds_count"] >= 0


def assert_remedy_package(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["conciliation_process_id"])
    _assert_enum(data["valuation_variant"], ValuationVariant, "valuation_variant")
    for field in (
        "back_pay_cents",
        "front_pay_cents",
        "compensatory_damages_cents",
        "punitive_damages_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["harm_start_date"], str) and data["harm_start_date"]
    _assert_enum(data["band_used"], SizeBand, "band_used")
    assert isinstance(data["projection_date"], str) and data["projection_date"]
    assert isinstance(data["interest_days"], int)
    for field in (
        "back_pay_interest_cents",
        "front_pay_interest_cents",
        "capped_nonpecuniary_cents",
        "total_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    # Self-consistency: total is the sum of its components (PRD section 3.7).
    assert data["total_cents"] == (
        data["back_pay_cents"]
        + data["front_pay_cents"]
        + data["back_pay_interest_cents"]
        + data["front_pay_interest_cents"]
        + data["capped_nonpecuniary_cents"]
    ), "total_cents must equal the sum of the five components (PRD section 3.7)"


def assert_right_to_sue_notice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["charge_id"])
    _assert_enum(data["issuance_basis"], IssuanceBasis, "issuance_basis")
    assert isinstance(data["requested_by_role"], str) and data["requested_by_role"]
    assert isinstance(data["issued_date"], str) and data["issued_date"]
    assert isinstance(data["court_filing_deadline"], str)
    assert data["court_filing_deadline"]
    _assert_enum(data["status"], RightToSueStatus, "status")


def assert_systemic_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["basis_focus"], list) and len(data["basis_focus"]) >= 1
    for b in data["basis_focus"]:
        _assert_enum(b, BasisCode, "basis_focus[]")
    assert isinstance(data["commissioner_user_id"], str)
    assert data["commissioner_user_id"]
    _assert_enum(data["status"], SystemicCaseStatus, "status")
    assert isinstance(data["linked_charge_count"], int)
    assert data["linked_charge_count"] >= 0


def assert_disclosure_record(data: dict):
    """Append-only row: id + created_at, NO updated_at and NO version
    (PRD section 2.5 makes DisclosureRecord the sole exception)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "DisclosureRecord must not expose updated_at"
    assert "version" not in data, "DisclosureRecord must not expose version"
    assert is_valid_uuid(data["charge_id"])
    assert isinstance(data["accessor_role"], str) and data["accessor_role"]
    assert isinstance(data["accessor_user_id"], str) and data["accessor_user_id"]
    _assert_enum(data["legal_basis"], LegalBasis, "legal_basis")
    _assert_optional_str(data, "target_description")
    assert isinstance(data["disclosed_at"], str) and data["disclosed_at"]
