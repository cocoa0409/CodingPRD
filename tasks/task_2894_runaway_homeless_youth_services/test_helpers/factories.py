"""Payload factories — one per write operation, input fields only.

Money is always an integer count of cents and every rate is an integer count of
basis points. Instants are ISO 8601 UTC timestamps with three fractional digits;
a youth's `date_of_birth` is a bare calendar date.
"""

from typing import Optional

from .constants import TEST_DEFAULTS
from .types import (
    AttemptChannel,
    EngagementStage,
    EnrollmentType,
    ExitDestination,
    ExitReason,
    LifeSkillsModule,
    MediationOutcome,
    ProgramType,
    ProposalCategory,
    SafetyAssessmentResult,
    SavingsEntryType,
    ScreeningStatus,
    VoteStance,
)


def emergency_shelter_payload(**overrides) -> dict:
    """A licensed `EMERGENCY_SHELTER` program."""
    payload = {
        "name": TEST_DEFAULTS["PROGRAM_NAME"],
        "program_type": ProgramType.EMERGENCY_SHELTER.value,
        "licensed_bed_capacity": TEST_DEFAULTS["BED_CAPACITY"],
        "min_age_years": TEST_DEFAULTS["MIN_AGE_YEARS"],
        "max_age_years": TEST_DEFAULTS["MAX_AGE_YEARS"],
        "max_stay_nights": TEST_DEFAULTS["MAX_STAY_NIGHTS"],
        "max_placement_days": TEST_DEFAULTS["MAX_PLACEMENT_DAYS"],
        "savings_match_rate_bp": TEST_DEFAULTS["SAVINGS_MATCH_RATE_BP"],
        "required_savings_rate_bp": TEST_DEFAULTS["REQUIRED_SAVINGS_RATE_BP"],
    }
    payload.update(overrides)
    return payload


def transitional_living_payload(**overrides) -> dict:
    """A licensed `TRANSITIONAL_LIVING` program."""
    payload = emergency_shelter_payload(
        name=TEST_DEFAULTS["TLP_PROGRAM_NAME"],
        program_type=ProgramType.TRANSITIONAL_LIVING.value,
        min_age_years=TEST_DEFAULTS["TLP_MIN_AGE_YEARS"],
        max_age_years=TEST_DEFAULTS["TLP_MAX_AGE_YEARS"],
    )
    payload.update(overrides)
    return payload


def youth_payload(**overrides) -> dict:
    """A youth intake. `unaccompanied` is optional and is omitted by default."""
    payload = {
        "legal_first_name": TEST_DEFAULTS["FIRST_NAME"],
        "legal_last_name": TEST_DEFAULTS["LAST_NAME"],
        "date_of_birth": TEST_DEFAULTS["DATE_OF_BIRTH"],
    }
    payload.update(overrides)
    return payload


def outreach_contact_payload(**overrides) -> dict:
    """A street-outreach encounter."""
    payload = {
        "engagement_stage": EngagementStage.FIRST_CONTACT.value,
        "basic_needs_provided": [],
        "indicator_flags": [],
    }
    payload.update(overrides)
    return payload


def safety_screening_payload(**overrides) -> dict:
    """A trafficking and exploitation safety screening."""
    payload = {"indicator_codes": []}
    payload.update(overrides)
    return payload


def screening_disposition_payload(
    disposition: str = ScreeningStatus.CLEARED.value,
    specialized_response_code: Optional[str] = None,
    **overrides,
) -> dict:
    """A screening disposition. `specialized_response_code` is optional and
    defaults to `NONE` on the server when omitted."""
    payload = {"disposition": disposition}
    if specialized_response_code is not None:
        payload["specialized_response_code"] = specialized_response_code
    payload.update(overrides)
    return payload


def admission_payload(
    youth_id: str,
    program_id: str,
    planned_discharge_at: str,
    waitlist_opt_out: Optional[bool] = None,
    **overrides,
) -> dict:
    """An emergency shelter admission request."""
    payload = {
        "youth_id": youth_id,
        "program_id": program_id,
        "planned_discharge_at": planned_discharge_at,
    }
    if waitlist_opt_out is not None:
        payload["waitlist_opt_out"] = waitlist_opt_out
    payload.update(overrides)
    return payload


def extend_payload(new_planned_discharge_at: str, **overrides) -> dict:
    payload = {"new_planned_discharge_at": new_planned_discharge_at}
    payload.update(overrides)
    return payload


def discharge_payload(
    exit_destination: str = ExitDestination.FAMILY_REUNIFIED.value, **overrides
) -> dict:
    payload = {"exit_destination": exit_destination}
    payload.update(overrides)
    return payload


def notification_attempt_payload(
    attempt_channel: str = AttemptChannel.PHONE.value, **overrides
) -> dict:
    payload = {"attempt_channel": attempt_channel}
    payload.update(overrides)
    return payload


def notification_resolve_payload(
    outcome: str = "CONTACTED", waiver_reason: Optional[str] = None, **overrides
) -> dict:
    payload = {"outcome": outcome}
    if waiver_reason is not None:
        payload["waiver_reason"] = waiver_reason
    payload.update(overrides)
    return payload


def reunification_case_payload(
    youth_id: str, expected_youth_version: int, **overrides
) -> dict:
    """Opening a case carries the client's last observed youth `version`."""
    payload = {
        "youth_id": youth_id,
        "guardian_household_label": TEST_DEFAULTS["HOUSEHOLD_LABEL"],
        "expected_youth_version": expected_youth_version,
    }
    payload.update(overrides)
    return payload


def mediation_session_payload(
    scheduled_start_at: str, scheduled_end_at: str, **overrides
) -> dict:
    payload = {
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    payload.update(overrides)
    return payload


def mediation_outcome_payload(
    outcome: str = MediationOutcome.PROGRESS.value, **overrides
) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def home_assessment_payload(
    safety_assessment_result: str = SafetyAssessmentResult.SAFE.value, **overrides
) -> dict:
    payload = {"safety_assessment_result": safety_assessment_result}
    payload.update(overrides)
    return payload


def decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def aftercare_contact_payload(contact_note: Optional[str] = None, **overrides) -> dict:
    """`contact_note` is optional."""
    payload = {}
    if contact_note is not None:
        payload["contact_note"] = contact_note
    payload.update(overrides)
    return payload


def tlp_placement_payload(
    youth_id: str,
    program_id: str,
    documented_monthly_income_cents: Optional[int] = None,
    **overrides,
) -> dict:
    """A transitional living placement. The income figure is optional and
    defaults to 0 when omitted."""
    payload = {"youth_id": youth_id, "program_id": program_id}
    if documented_monthly_income_cents is not None:
        payload["documented_monthly_income_cents"] = int(documented_monthly_income_cents)
    payload.update(overrides)
    return payload


def savings_entry_payload(
    entry_type: str,
    amount_cents: int,
    expected_placement_version: int,
    source_note: Optional[str] = None,
    **overrides,
) -> dict:
    """A savings ledger posting. `amount_cents` is an integer magnitude of at
    least 1 and `expected_placement_version` is mandatory."""
    payload = {
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "expected_placement_version": int(expected_placement_version),
    }
    if source_note is not None:
        payload["source_note"] = source_note
    payload.update(overrides)
    return payload


def deposit_payload(amount_cents: int, expected_placement_version: int, **overrides) -> dict:
    return savings_entry_payload(
        SavingsEntryType.DEPOSIT.value, amount_cents, expected_placement_version, **overrides
    )


def withdrawal_payload(amount_cents: int, expected_placement_version: int, **overrides) -> dict:
    return savings_entry_payload(
        SavingsEntryType.WITHDRAWAL.value, amount_cents, expected_placement_version, **overrides
    )


def reversal_payload(amount_cents: int, expected_placement_version: int, **overrides) -> dict:
    return savings_entry_payload(
        SavingsEntryType.REVERSAL.value, amount_cents, expected_placement_version, **overrides
    )


def life_skills_completion_payload(
    credit_hours: int, module_code: str = LifeSkillsModule.BUDGETING.value, **overrides
) -> dict:
    payload = {"module_code": module_code, "credit_hours": int(credit_hours)}
    payload.update(overrides)
    return payload


def tlp_exit_payload(
    exit_reason: str = ExitReason.YOUTH_INITIATED.value, **overrides
) -> dict:
    payload = {"exit_reason": exit_reason}
    payload.update(overrides)
    return payload


def education_enrollment_payload(**overrides) -> dict:
    payload = {
        "school_name": TEST_DEFAULTS["SCHOOL_NAME"],
        "enrollment_type": EnrollmentType.PUBLIC_K12.value,
    }
    payload.update(overrides)
    return payload


def governance_proposal_payload(voting_closes_at: str, **overrides) -> dict:
    payload = {
        "title": TEST_DEFAULTS["PROPOSAL_TITLE"],
        "category": ProposalCategory.HOUSE_RULES.value,
        "voting_closes_at": voting_closes_at,
    }
    payload.update(overrides)
    return payload


def governance_vote_payload(stance: str = VoteStance.SUPPORT.value, **overrides) -> dict:
    payload = {"stance": stance}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
