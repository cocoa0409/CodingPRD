"""Request-payload factories.

Every factory returns a plain dict that is valid against the PRD's payload
shape, and accepts keyword overrides so a test can perturb exactly one field.

Conventions honoured here:
  * money is an integer count of cents, never a string and never a float;
  * dates are `YYYY-MM-DD` strings; instants are full ISO-8601 UTC instants
    with three fractional digits and a trailing `Z`;
  * `None` passed explicitly for an optional field means "send JSON null";
    the sentinel `OMIT` means "leave the key out of the payload entirely".
"""

from typing import Any, Dict, List, Optional, Sequence

from .constants import (
    ADMIN_CONTACT_EMAIL,
    ADMIN_LEGAL_NAME,
    AppliedTo,
    BenefitCategory,
    BenefitSide,
    CapClosureOutcome,
    CapDecisionOutcome,
    COVERED_PARTICIPANT_COUNT,
    DEFAULT_CONTRACTUAL_PRODUCTION_DAYS,
    DeterminationOutcome,
    FundingArrangement,
    LIABILITY_CAP_CENTS,
    LimitationType,
    NetworkTier,
    NqtlType,
    PLAN_NAME,
    PLAN_YEAR_LABEL,
    RemedyType,
    ReviewOutcome,
    StringencyFinding,
    SubmissionType,
    TestBasis,
    AdjudicationOutcome,
)


class _Omit:
    """Sentinel meaning: leave this key out of the emitted payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


OMIT = _Omit()


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if not isinstance(v, _Omit)}


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    base.update(overrides)
    return _clean(base)


# ─── Administrator ────────────────────────────────────────────────────────────


def administrator_payload(
    legal_name: str = ADMIN_LEGAL_NAME,
    contact_email: str = ADMIN_CONTACT_EMAIL,
    contractual_production_days: Any = DEFAULT_CONTRACTUAL_PRODUCTION_DAYS,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": legal_name,
            "contact_email": contact_email,
            "contractual_production_days": contractual_production_days,
        },
        overrides,
    )


# ─── Plan year ────────────────────────────────────────────────────────────────


def plan_year_payload(
    administrator_id: str,
    plan_name: str = PLAN_NAME,
    plan_year_label: str = PLAN_YEAR_LABEL,
    funding_arrangement: str = FundingArrangement.SELF_FUNDED,
    covered_participant_count: Any = COVERED_PARTICIPANT_COUNT,
    remediation_liability_cap_cents: Any = LIABILITY_CAP_CENTS,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "plan_name": plan_name,
            "plan_year_label": plan_year_label,
            "administrator_id": administrator_id,
            "funding_arrangement": funding_arrangement,
            "covered_participant_count": covered_participant_count,
            "remediation_liability_cap_cents": remediation_liability_cap_cents,
        },
        overrides,
    )


# ─── Benefit classification ───────────────────────────────────────────────────


def classification_payload(
    benefit_category: str = BenefitCategory.OUTPATIENT,
    network_tier: str = NetworkTier.IN_NETWORK,
    sub_classification: Any = OMIT,
    measurement_period_start: str = "2026-01-01",
    measurement_period_end: str = "2026-06-30",
    mh_su_benefits_covered: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "benefit_category": benefit_category,
            "network_tier": network_tier,
            "sub_classification": sub_classification,
            "measurement_period_start": measurement_period_start,
            "measurement_period_end": measurement_period_end,
            "mh_su_benefits_covered": mh_su_benefits_covered,
        },
        overrides,
    )


# ─── Treatment limitation ─────────────────────────────────────────────────────


def treatment_limitation_payload(
    limitation_type: str = LimitationType.COPAY,
    benefit_side: str = BenefitSide.MEDICAL_SURGICAL,
    level_value: Any = 30,
    projected_plan_payments_cents: Any = 5000000,
    projected_claims_count: Any = 400,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "limitation_type": limitation_type,
            "benefit_side": benefit_side,
            "level_value": level_value,
            "projected_plan_payments_cents": projected_plan_payments_cents,
            "projected_claims_count": projected_claims_count,
        },
        overrides,
    )


def ms_limitation(
    level_value: int,
    payments_cents: int,
    claims_count: int,
    limitation_type: str = LimitationType.COPAY,
) -> Dict[str, Any]:
    """A MEDICAL_SURGICAL baseline row — the test population side."""
    return treatment_limitation_payload(
        limitation_type=limitation_type,
        benefit_side=BenefitSide.MEDICAL_SURGICAL,
        level_value=level_value,
        projected_plan_payments_cents=payments_cents,
        projected_claims_count=claims_count,
    )


def mh_limitation(
    level_value: int,
    payments_cents: int,
    claims_count: int,
    limitation_type: str = LimitationType.COPAY,
) -> Dict[str, Any]:
    """A MENTAL_HEALTH_SUD row — the side under test."""
    return treatment_limitation_payload(
        limitation_type=limitation_type,
        benefit_side=BenefitSide.MENTAL_HEALTH_SUD,
        level_value=level_value,
        projected_plan_payments_cents=payments_cents,
        projected_claims_count=claims_count,
    )


# ─── Parity test ──────────────────────────────────────────────────────────────


def parity_test_payload(
    limitation_type: str = LimitationType.COPAY,
    basis: str = TestBasis.PLAN_PAYMENTS,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"limitation_type": limitation_type, "basis": basis}, overrides)


# ─── NQTL item ────────────────────────────────────────────────────────────────


def nqtl_item_payload(
    plan_year_id: str,
    classification_id: str,
    nqtl_type: str = NqtlType.PRIOR_AUTHORIZATION,
    applied_to: str = AppliedTo.MENTAL_HEALTH_SUD_ONLY,
    description: str = "Prior authorisation required for all behavioural health admissions.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "plan_year_id": plan_year_id,
            "classification_id": classification_id,
            "nqtl_type": nqtl_type,
            "applied_to": applied_to,
            "description": description,
        },
        overrides,
    )


# ─── Comparative analysis ─────────────────────────────────────────────────────


def analysis_payload(
    nqtl_item_id: str,
    expected_nqtl_item_version: Any,
    factor_count: Any = 2,
    evidentiary_standard_count: Any = 1,
    stringency_written_finding: str = StringencyFinding.COMPARABLE,
    stringency_operation_finding: str = StringencyFinding.MORE_STRINGENT_MH,
    supersedes_analysis_id: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "nqtl_item_id": nqtl_item_id,
            "factor_count": factor_count,
            "evidentiary_standard_count": evidentiary_standard_count,
            "stringency_written_finding": stringency_written_finding,
            "stringency_operation_finding": stringency_operation_finding,
            "expected_nqtl_item_version": expected_nqtl_item_version,
            "supersedes_analysis_id": supersedes_analysis_id,
        },
        overrides,
    )


def review_payload(
    outcome: str = ReviewOutcome.CERTIFIED,
    review_note: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"outcome": outcome, "review_note": review_note}, overrides)


# ─── Determination ────────────────────────────────────────────────────────────


def determination_payload(
    outcome: str,
    expected_plan_year_version: Any,
    rationale: str = "Recorded from the recomputed stringency-in-operation evidence.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "outcome": outcome,
            "rationale": rationale,
            "expected_plan_year_version": expected_plan_year_version,
        },
        overrides,
    )


def compliant_determination_payload(expected_plan_year_version: Any, **overrides: Any) -> Dict[str, Any]:
    return determination_payload(
        DeterminationOutcome.COMPLIANT, expected_plan_year_version, **overrides
    )


def violation_determination_payload(expected_plan_year_version: Any, **overrides: Any) -> Dict[str, Any]:
    return determination_payload(
        DeterminationOutcome.VIOLATION, expected_plan_year_version, **overrides
    )


# ─── Vendor data request ──────────────────────────────────────────────────────


def vendor_request_payload(
    administrator_id: str,
    plan_year_id: str,
    requested_item_count: Any = 1,
    requested_submission_types: Optional[Sequence[str]] = None,
    nqtl_item_id: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    types: Any = (
        list(requested_submission_types)
        if requested_submission_types is not None
        else [SubmissionType.DENIAL_RATES]
    )
    return _merge(
        {
            "administrator_id": administrator_id,
            "plan_year_id": plan_year_id,
            "nqtl_item_id": nqtl_item_id,
            "requested_item_count": requested_item_count,
            "requested_submission_types": types,
        },
        overrides,
    )


# ─── Data submission ──────────────────────────────────────────────────────────


def denial_rate_submission_payload(
    classification_id: str,
    mh_denials: Any = 137,
    mh_adjudicated_claims: Any = 1919,
    ms_denials: Any = 71,
    ms_adjudicated_claims: Any = 1913,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "classification_id": classification_id,
            "submission_type": SubmissionType.DENIAL_RATES,
            "mh_denials": mh_denials,
            "mh_adjudicated_claims": mh_adjudicated_claims,
            "ms_denials": ms_denials,
            "ms_adjudicated_claims": ms_adjudicated_claims,
        },
        overrides,
    )


def network_composition_submission_payload(
    classification_id: str,
    mh_in_network_provider_pct: Any = 0.30,
    ms_in_network_provider_pct: Any = 0.58,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "classification_id": classification_id,
            "submission_type": SubmissionType.NETWORK_COMPOSITION,
            "mh_in_network_provider_pct": mh_in_network_provider_pct,
            "ms_in_network_provider_pct": ms_in_network_provider_pct,
        },
        overrides,
    )


def reimbursement_benchmark_submission_payload(
    classification_id: str,
    benchmark_note: Any = "Benchmarked against the regional commercial fee schedule.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "classification_id": classification_id,
            "submission_type": SubmissionType.REIMBURSEMENT_BENCHMARK,
            "benchmark_note": benchmark_note,
        },
        overrides,
    )


# ─── Corrective action plan ───────────────────────────────────────────────────


def cap_payload(
    nqtl_item_id: str,
    remedy_type: str = RemedyType.PROCESS_CHANGE,
    affected_claims_count: Any = 880,
    average_claim_cents: Any = 3125,
    target_completion_date: str = "2026-12-31",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "nqtl_item_id": nqtl_item_id,
            "remedy_type": remedy_type,
            "affected_claims_count": affected_claims_count,
            "average_claim_cents": average_claim_cents,
            "target_completion_date": target_completion_date,
        },
        overrides,
    )


def cap_decision_payload(
    outcome: str = CapDecisionOutcome.APPROVED,
    decision_note: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"outcome": outcome, "decision_note": decision_note}, overrides)


def cap_closure_payload(
    outcome: str = CapClosureOutcome.COMPLETED,
    closure_note: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"outcome": outcome, "closure_note": closure_note}, overrides)


# ─── Regulator request ────────────────────────────────────────────────────────


def regulator_request_payload(
    plan_year_id: str,
    requested_nqtl_types: Optional[Sequence[str]] = None,
    request_reference: str = "DOL-EBSA-2026-0417",
    **overrides: Any,
) -> Dict[str, Any]:
    types: Any = (
        list(requested_nqtl_types)
        if requested_nqtl_types is not None
        else [NqtlType.PRIOR_AUTHORIZATION]
    )
    return _merge(
        {
            "plan_year_id": plan_year_id,
            "requested_nqtl_types": types,
            "request_reference": request_reference,
        },
        overrides,
    )


def respond_payload(response_note: Any = OMIT, **overrides: Any) -> Dict[str, Any]:
    return _merge({"response_note": response_note}, overrides)


def adjudicate_payload(
    outcome: str = AdjudicationOutcome.ACCEPTED,
    adjudication_note: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"outcome": outcome, "adjudication_note": adjudication_note}, overrides)


# ─── Logical clock ────────────────────────────────────────────────────────────


def clock_payload(current_utc: Any, **overrides: Any) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


# ─── Convenience limitation sets ──────────────────────────────────────────────


def limitation_set(*rows: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Group treatment-limitation payloads so a fixture can post them in order."""
    return list(rows)
