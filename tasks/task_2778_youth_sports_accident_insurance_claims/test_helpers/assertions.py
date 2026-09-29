"""Entity assertions and domain invariant checkers."""
from typing import Any, Dict, List

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import OPEN_CLAIM_ADJUDICATION_STATUSES, SERVICE_CATEGORIES
from .types import (
    ActivityType,
    BenefitLayer,
    BenefitPaymentStatus,
    BodyPart,
    CatCertificationStatus,
    ClaimAdjudicationStatus,
    ClaimCoordinationStatus,
    CoordinationRecordStatus,
    CoverageBasisElection,
    CoveragePosture,
    EnrollmentCoverageStatus,
    EnrollmentStatus,
    ExperienceTier,
    FamilyPlanCoverageState,
    FamilyPlanType,
    FamilyPlanVerificationStatus,
    HazardClass,
    InjuryReportStatus,
    LeaguePolicyStatus,
    LeagueSanctioningStatus,
    NetworkStatus,
    PayeeType,
    ProviderBillStatus,
    RenewalQuoteStatus,
    RosterStatus,
    SanctionedActivityStatus,
    SeverityTier,
)


def _members(enum_cls) -> List[str]:
    return [member.value for member in enum_cls]


def assert_common_resource_properties(data: Dict[str, Any]) -> None:
    """Every resource carries an id, both timestamps and a version counter."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_integer_cents(value: Any, field_name: str) -> None:
    """Money crosses the wire as an integer number of cents, never a string."""
    assert isinstance(value, int) and not isinstance(
        value, bool
    ), f"{field_name} must be an integer number of cents, got {value!r}"


def assert_basis_points(value: Any, field_name: str) -> None:
    assert isinstance(value, int) and not isinstance(
        value, bool
    ), f"{field_name} must be an integer number of basis points, got {value!r}"


def assert_league(data: Dict[str, Any]) -> None:
    assert_common_resource_properties(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["league_code"], str) and data["league_code"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["governing_body_code"], str) and data["governing_body_code"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["sanctioning_status"] in _members(
        LeagueSanctioningStatus
    ), f"unexpected sanctioning_status {data['sanctioning_status']!r}"


def assert_sport_classification(data: Dict[str, Any]) -> None:
    assert_common_resource_properties(data)
    assert data["hazard_class"] in _members(HazardClass)
    for field_name in (
        "base_rate_per_participant_cents",
        "deductible_cents",
        "per_injury_limit_cents",
        "cat_attachment_point_cents",
        "aggregate_limit_cents",
        "cat_lifetime_max_cents",
    ):
        assert_integer_cents(data[field_name], field_name)
    assert isinstance(data["minimum_participants"], int)
    assert isinstance(data["travel_buffer_minutes"], int)
    caps = data["service_category_caps"]
    assert isinstance(caps, dict), "service_category_caps must be an object"
    for category in caps:
        assert category in SERVICE_CATEGORIES, f"unknown benefit category {category!r}"


def assert_league_policy(data: Dict[str, Any]) -> None:
    assert_common_resource_properties(data)
    assert data["status"] in _members(LeaguePolicyStatus)
    assert data["coverage_posture"] in _members(CoveragePosture)
    assert data["coverage_basis_election"] in _members(CoverageBasisElection)
    assert isinstance(data["cat_layer_elected"], bool)
    assert data["experience_tier"] in _members(ExperienceTier)
    assert data["renewal_quote_status"] in _members(RenewalQuoteStatus)
    for field_name in (
        "gross_premium_cents",
        "cat_layer_charge_cents",
        "premium_subtotal_cents",
        "volume_credit_cents",
        "annual_premium_cents",
        "paid_loss_cents",
        "reserve_cents",
        "incurred_loss_cents",
    ):
        assert_integer_cents(data[field_name], field_name)
    for field_name in (
        "volume_credit_bps",
        "incurred_loss_ratio_bps",
        "paid_loss_ratio_bps",
    ):
        assert_basis_points(data[field_name], field_name)
    assert isinstance(data["open_claim_count"], int)


def assert_participant(data: Dict[str, Any]) -> None:
    assert_common_resource_properties(data)
    assert data["roster_status"] in _members(RosterStatus)
    assert isinstance(data["enrolled_policy_count"], int)


def assert_enrollment(data: Dict[str, Any]) -> None:
    assert_common_resource_properties(data)
    assert data["status"] in _members(EnrollmentStatus)
    assert data["coverage_status"] in _members(EnrollmentCoverageStatus)
    assert_integer_cents(
        data["lifetime_cat_benefit_used_cents"], "lifetime_cat_benefit_used_cents"
    )


def assert_family_health_plan(data: Dict[str, Any]) -> None:
    assert_common_resource_properties(data)
    assert data["plan_type"] in _members(FamilyPlanType)
    assert data["coverage_state"] in _members(FamilyPlanCoverageState)
    assert data["verification_status"] in _members(FamilyPlanVerificationStatus)
    assert_integer_cents(
        data["individual_deductible_cents"], "individual_deductible_cents"
    )
    assert_basis_points(data["coinsurance_bps"], "coinsurance_bps")


def assert_sanctioned_activity(data: Dict[str, Any]) -> None:
    assert_common_resource_properties(data)
    assert data["activity_type"] in _members(ActivityType)
    assert data["status"] in _members(SanctionedActivityStatus)
    assert isinstance(data["is_covered_activity"], bool)
    assert isinstance(data["travel_buffer_minutes"], int)


def assert_injury_report(data: Dict[str, Any]) -> None:
    assert_common_resource_properties(data)
    assert data["body_part"] in _members(BodyPart)
    assert data["severity_tier"] in _members(SeverityTier)
    assert data["status"] in _members(InjuryReportStatus)
    assert isinstance(data["days_to_report"], int)
    assert isinstance(data["correction_round_count"], int)


def assert_claim(data: Dict[str, Any]) -> None:
    assert_common_resource_properties(data)
    assert data["adjudication_status"] in _members(ClaimAdjudicationStatus)
    assert data["coordination_status"] in _members(ClaimCoordinationStatus)
    assert data["cat_certification_status"] in _members(CatCertificationStatus)
    for field_name in (
        "reserve_amount_cents",
        "allowed_amount_total_cents",
        "other_insurance_paid_cents",
        "deductible_applied_cents",
        "benefit_before_limit_cents",
        "base_layer_benefit_cents",
        "cat_layer_benefit_cents",
        "benefit_payable_cents",
        "paid_base_cents",
        "paid_cat_cents",
        "paid_to_date_cents",
        "balance_billed_total_cents",
        "family_responsibility_total_cents",
    ):
        assert_integer_cents(data[field_name], field_name)


def assert_provider_bill(data: Dict[str, Any]) -> None:
    assert_common_resource_properties(data)
    assert data["network_status"] in _members(NetworkStatus)
    assert data["service_category"] in SERVICE_CATEGORIES
    assert data["status"] in _members(ProviderBillStatus)
    for field_name in (
        "billed_charge_cents",
        "fee_schedule_amount_cents",
        "allowed_amount_cents",
        "other_plan_paid_cents",
    ):
        assert_integer_cents(data[field_name], field_name)
    # PRD 3.7: "A recorded bill enters `SUBMITTED` with `allowed_amount_cents` 0 and
    # with `negotiated_amount_cents`, `scheduled_cap_cents`, `balance_billed_cents`,
    # `family_responsibility_cents`, `repriced_at`, `repriced_by_user_id` and
    # `void_reason` all still unset." Those four figures are therefore null until the
    # charge has actually been repriced, and must be integers once it has been.
    for field_name in (
        "negotiated_amount_cents",
        "scheduled_cap_cents",
        "balance_billed_cents",
        "family_responsibility_cents",
    ):
        if data["status"] in ("REPRICED", "ADJUDICATED", "DENIED"):
            assert_integer_cents(data[field_name], field_name)
        elif data[field_name] is not None:
            assert_integer_cents(data[field_name], field_name)


def assert_coordination_record(data: Dict[str, Any]) -> None:
    assert_common_resource_properties(data)
    assert data["status"] in _members(CoordinationRecordStatus)
    for field_name in (
        "other_plan_allowed_cents",
        "other_plan_paid_cents",
        "patient_responsibility_cents",
    ):
        assert_integer_cents(data[field_name], field_name)


def assert_benefit_payment(data: Dict[str, Any]) -> None:
    assert_common_resource_properties(data)
    assert data["payee_type"] in _members(PayeeType)
    assert data["layer"] in _members(BenefitLayer)
    assert data["status"] in _members(BenefitPaymentStatus)
    assert_integer_cents(data["amount_cents"], "amount_cents")


def assert_loss_position_invariants(policy: Dict[str, Any]) -> None:
    """incurred loss is always paid loss plus the reserve of the open set."""
    assert (
        policy["incurred_loss_cents"]
        == policy["paid_loss_cents"] + policy["reserve_cents"]
    ), (
        "incurred_loss_cents must equal paid_loss_cents + reserve_cents, got "
        f"{policy['incurred_loss_cents']} vs "
        f"{policy['paid_loss_cents']} + {policy['reserve_cents']}"
    )
    assert policy["paid_loss_cents"] >= 0
    assert policy["reserve_cents"] >= 0
    assert policy["open_claim_count"] >= 0


def assert_open_claim_cardinality(policy: Dict[str, Any], claims: List[Dict]) -> None:
    """open_claim_count counts exactly the claims in the open adjudication set."""
    open_claims = [
        claim
        for claim in claims
        if claim["adjudication_status"] in OPEN_CLAIM_ADJUDICATION_STATUSES
    ]
    assert policy["open_claim_count"] == len(open_claims), (
        f"open_claim_count {policy['open_claim_count']} does not match the "
        f"{len(open_claims)} claims in the open set"
    )
    assert policy["reserve_cents"] == sum(
        claim["reserve_amount_cents"] for claim in open_claims
    ), "reserve_cents must be the sum of the open set's reserve_amount_cents"


def assert_paid_loss_matches_issued_payments(
    policy: Dict[str, Any], payments: List[Dict]
) -> None:
    """paid_loss_cents is the sum of the ISSUED benefit payments on the policy."""
    issued = sum(
        payment["amount_cents"] for payment in payments if payment["status"] == "ISSUED"
    )
    assert policy["paid_loss_cents"] == issued, (
        f"paid_loss_cents {policy['paid_loss_cents']} does not match the "
        f"{issued} cents of ISSUED benefit payments"
    )
