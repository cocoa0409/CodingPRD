"""Payload factories — one per creatable resource, input fields only.

Conventions:
- Every factory takes keyword arguments and returns a plain dict payload.
- Optional fields are OMITTED from the payload unless the caller supplies them
  (pass the value explicitly; the _UNSET sentinel controls omission).
- DEFAULT_* dates are the canonical scenario dates used across the test
  design: the FOA receipt deadline (2026-12-01) sits after the logical
  clock's 2026-09-01 start so submissions succeed, and the default award
  start (2027-01-01) and transfer effective date (2027-07-01) are on or
  after the clock as the PRD requires for those fields. They are convenience
  defaults, not PRD-pinned constants; every test may override them.
- unique_* helpers mint per-process-unique names/numbers so several entities
  can coexist inside one test without colliding on uniqueness rules.
"""
import itertools

from .constants import JIT_BASE_ITEMS

_UNSET = object()

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def unique_name(prefix: str = "Entity") -> str:
    """Per-process-unique display name, e.g. 'Institution 17'."""
    return f"{prefix} {_next()}"


def unique_pa_number() -> str:
    """Per-process-unique announcement number, e.g. 'PA-26-90017'."""
    return f"PA-26-{90000 + _next()}"


def unique_email(prefix: str = "pi") -> str:
    return f"{prefix}{_next()}@example.edu"


# --- Canonical scenario dates (defaults; overridable per call) --------------
DEFAULT_OPEN_DATE = "2026-08-01T00:00:00Z"
DEFAULT_RECEIPT_DEADLINE = "2026-12-01T00:00:00Z"
DEFAULT_MEETING_DATE = "2027-03-01T00:00:00Z"
DEFAULT_AWARD_START_DATE = "2027-01-01T00:00:00Z"
DEFAULT_TRANSFER_EFFECTIVE_DATE = "2027-07-01T00:00:00Z"


# --- Clock ------------------------------------------------------------------

def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


# --- FundingOpportunity ------------------------------------------------------

def create_funding_opportunity_payload(
    pa_number=_UNSET,
    title=_UNSET,
    activity_code="R01",
    research_strategy_page_limit=12,
    min_direct_cents_per_year=1_000_000,
    max_direct_cents_per_year=25_000_000,
    max_years=5,
    open_date=DEFAULT_OPEN_DATE,
    receipt_deadline=DEFAULT_RECEIPT_DEADLINE,
    **overrides,
) -> dict:
    payload = {
        "pa_number": unique_pa_number() if pa_number is _UNSET else pa_number,
        "title": unique_name("FOA") if title is _UNSET else title,
        "activity_code": activity_code,
        "research_strategy_page_limit": research_strategy_page_limit,
        "min_direct_cents_per_year": min_direct_cents_per_year,
        "max_direct_cents_per_year": max_direct_cents_per_year,
        "max_years": max_years,
        "open_date": open_date,
        "receipt_deadline": receipt_deadline,
    }
    payload.update(overrides)
    return payload


# --- Institute ----------------------------------------------------------------

def create_institute_payload(
    name=_UNSET,
    appropriation_cents=100_000_000,
    reserve_cents=0,
    indirect_cost_rate=0.5,
    select_pay_cap_pct=0.10,
    select_pay_extension_percentile=5.0,
    **overrides,
) -> dict:
    payload = {
        "name": unique_name("Institute") if name is _UNSET else name,
        "appropriation_cents": appropriation_cents,
        "reserve_cents": reserve_cents,
        "indirect_cost_rate": indirect_cost_rate,
        "select_pay_cap_pct": select_pay_cap_pct,
        "select_pay_extension_percentile": select_pay_extension_percentile,
    }
    payload.update(overrides)
    return payload


# --- Institution --------------------------------------------------------------

def create_institution_payload(
    name=_UNSET,
    human_subjects_certification_expiry=_UNSET,
    animal_welfare_assurance_expiry=_UNSET,
    **overrides,
) -> dict:
    payload = {"name": unique_name("Institution") if name is _UNSET else name}
    if human_subjects_certification_expiry is not _UNSET:
        payload["human_subjects_certification_expiry"] = human_subjects_certification_expiry
    if animal_welfare_assurance_expiry is not _UNSET:
        payload["animal_welfare_assurance_expiry"] = animal_welfare_assurance_expiry
    payload.update(overrides)
    return payload


# --- Applicant -----------------------------------------------------------------

def create_applicant_payload(
    full_name=_UNSET,
    email=_UNSET,
    career_stage="ESTABLISHED_INVESTIGATOR",
    **overrides,
) -> dict:
    payload = {
        "full_name": unique_name("PI") if full_name is _UNSET else full_name,
        "email": unique_email() if email is _UNSET else email,
        "career_stage": career_stage,
    }
    payload.update(overrides)
    return payload


# --- Application ---------------------------------------------------------------

def create_application_payload(
    foa_id,
    institution_id,
    title=_UNSET,
    research_strategy_page_count=5,
    direct_cents_per_year=_UNSET,
    requested_years=_UNSET,
    human_subjects_involved=_UNSET,
    vertebrate_animals_involved=_UNSET,
    requested_study_section_id=_UNSET,
    requested_institute_id=_UNSET,
    excluded_reviewer_ids=_UNSET,
    **overrides,
) -> dict:
    if direct_cents_per_year is _UNSET:
        if requested_years is _UNSET:
            direct_cents_per_year = [20_000_000]
            requested_years = 1
        else:
            direct_cents_per_year = [20_000_000] * requested_years
    elif requested_years is _UNSET:
        requested_years = len(direct_cents_per_year)
    payload = {
        "foa_id": foa_id,
        "institution_id": institution_id,
        "title": unique_name("Application") if title is _UNSET else title,
        "research_strategy_page_count": research_strategy_page_count,
        "direct_cents_per_year": list(direct_cents_per_year),
        "requested_years": requested_years,
    }
    if human_subjects_involved is not _UNSET:
        payload["human_subjects_involved"] = human_subjects_involved
    if vertebrate_animals_involved is not _UNSET:
        payload["vertebrate_animals_involved"] = vertebrate_animals_involved
    if requested_study_section_id is not _UNSET:
        payload["requested_study_section_id"] = requested_study_section_id
    if requested_institute_id is not _UNSET:
        payload["requested_institute_id"] = requested_institute_id
    if excluded_reviewer_ids is not _UNSET:
        payload["excluded_reviewer_ids"] = list(excluded_reviewer_ids)
    payload.update(overrides)
    return payload


# --- StudySection ---------------------------------------------------------------

def create_study_section_payload(
    name=_UNSET,
    meeting_date=DEFAULT_MEETING_DATE,
    application_quota=10,
    **overrides,
) -> dict:
    payload = {
        "name": unique_name("Section") if name is _UNSET else name,
        "meeting_date": meeting_date,
        "application_quota": application_quota,
    }
    payload.update(overrides)
    return payload


# --- Reviewer -------------------------------------------------------------------

def create_reviewer_payload(
    institution_id,
    full_name=_UNSET,
    expertise_keywords=_UNSET,
    **overrides,
) -> dict:
    payload = {
        "full_name": unique_name("Reviewer") if full_name is _UNSET else full_name,
        "institution_id": institution_id,
        "expertise_keywords": ["neuro"] if expertise_keywords is _UNSET else list(expertise_keywords),
    }
    payload.update(overrides)
    return payload


def reviewer_respond_payload(decision="ACCEPT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def declare_conflict_payload(application_id, **overrides) -> dict:
    payload = {"application_id": application_id}
    payload.update(overrides)
    return payload


# --- Assignment -----------------------------------------------------------------

def create_assignment_payload(application_id, reviewer_id, role="PRIMARY", **overrides) -> dict:
    payload = {"application_id": application_id, "reviewer_id": reviewer_id, "role": role}
    payload.update(overrides)
    return payload


def assignment_respond_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def critique_payload(
    overall_impact_score=3,
    significance_score=None,
    innovation_score=None,
    approach_score=None,
    investigator_score=None,
    environment_score=None,
    **overrides,
) -> dict:
    """Six criterion scores; each criterion defaults to the overall value."""
    payload = {
        "significance_score": overall_impact_score if significance_score is None else significance_score,
        "innovation_score": overall_impact_score if innovation_score is None else innovation_score,
        "approach_score": overall_impact_score if approach_score is None else approach_score,
        "investigator_score": overall_impact_score if investigator_score is None else investigator_score,
        "environment_score": overall_impact_score if environment_score is None else environment_score,
        "overall_impact_score": overall_impact_score,
    }
    payload.update(overrides)
    return payload


# --- CouncilReview --------------------------------------------------------------

def council_review_payload(
    application_id,
    recommendation,
    priority_alignment_score=_UNSET,
    portfolio_balance_note=_UNSET,
    **overrides,
) -> dict:
    payload = {"application_id": application_id, "recommendation": recommendation}
    if priority_alignment_score is not _UNSET:
        payload["priority_alignment_score"] = priority_alignment_score
    if portfolio_balance_note is not _UNSET:
        payload["portfolio_balance_note"] = portfolio_balance_note
    payload.update(overrides)
    return payload


# --- Referral / payline / select pay --------------------------------------------

def referral_payload(
    study_section_id,
    institute_id,
    expected_application_version,
    override_assignment_request=_UNSET,
    **overrides,
) -> dict:
    payload = {
        "study_section_id": study_section_id,
        "institute_id": institute_id,
        "expected_application_version": expected_application_version,
    }
    if override_assignment_request is not _UNSET:
        payload["override_assignment_request"] = override_assignment_request
    payload.update(overrides)
    return payload


def payline_decision_payload(base_payline_percentile, expected_institute_version, **overrides) -> dict:
    payload = {
        "base_payline_percentile": base_payline_percentile,
        "expected_institute_version": expected_institute_version,
    }
    payload.update(overrides)
    return payload


def select_pay_payload(rationale=_UNSET, **overrides) -> dict:
    payload = {}
    if rationale is not _UNSET:
        payload["rationale"] = rationale
    payload.update(overrides)
    return payload


# --- JitRequest -----------------------------------------------------------------

def jit_submit_items_payload(items_submitted=_UNSET, **overrides) -> dict:
    payload = {
        "items_submitted": list(JIT_BASE_ITEMS) if items_submitted is _UNSET else list(items_submitted)
    }
    payload.update(overrides)
    return payload


def jit_adjudicate_payload(decision, budget_cut_pct=_UNSET, return_reason=_UNSET, **overrides) -> dict:
    payload = {"decision": decision}
    if budget_cut_pct is not _UNSET:
        payload["budget_cut_pct"] = budget_cut_pct
    if return_reason is not _UNSET:
        payload["return_reason"] = return_reason
    payload.update(overrides)
    return payload


# --- Award / ProgressReport ------------------------------------------------------

def award_payload(start_date=DEFAULT_AWARD_START_DATE, **overrides) -> dict:
    payload = {"start_date": start_date}
    payload.update(overrides)
    return payload


def progress_report_payload(period_year, actual_expenditure_cents, publications_count=0, **overrides) -> dict:
    payload = {
        "period_year": period_year,
        "actual_expenditure_cents": actual_expenditure_cents,
        "publications_count": publications_count,
    }
    payload.update(overrides)
    return payload


# --- AwardModification -----------------------------------------------------------

def award_modification_payload(
    type,
    amount_cents=_UNSET,
    from_period=_UNSET,
    new_end_date=_UNSET,
    reason=_UNSET,
    **overrides,
) -> dict:
    payload = {"type": type}
    if amount_cents is not _UNSET:
        payload["amount_cents"] = amount_cents
    if from_period is not _UNSET:
        payload["from_period"] = from_period
    if new_end_date is not _UNSET:
        payload["new_end_date"] = new_end_date
    if reason is not _UNSET:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def modification_adjudicate_payload(decision, denial_reason=_UNSET, **overrides) -> dict:
    payload = {"decision": decision}
    if denial_reason is not _UNSET:
        payload["denial_reason"] = denial_reason
    payload.update(overrides)
    return payload


# --- TransferRequest --------------------------------------------------------------

def transfer_request_payload(
    to_institution_id,
    effective_date=DEFAULT_TRANSFER_EFFECTIVE_DATE,
    **overrides,
) -> dict:
    payload = {"to_institution_id": to_institution_id, "effective_date": effective_date}
    payload.update(overrides)
    return payload


def transfer_decide_payload(decision, decline_reason=_UNSET, **overrides) -> dict:
    payload = {"decision": decision}
    if decline_reason is not _UNSET:
        payload["decline_reason"] = decline_reason
    payload.update(overrides)
    return payload
