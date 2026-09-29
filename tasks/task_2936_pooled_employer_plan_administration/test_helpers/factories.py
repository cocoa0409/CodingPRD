"""
Request payload builders.

Every monetary amount is a JSON number of integer cents, never a string.
Every field the contract declares as a calendar date is built as a bare
``YYYY-MM-DD`` string, and the one field the contract declares as an instant —
the logical clock — is built as a full ISO 8601 UTC instant.  Percentages are
JSON numbers.  Identifiers that the contract declares as digit strings, such as
an EIN or the three-digit plan number, are built as strings.
"""

from typing import Any, Dict, Optional

from . import constants as k


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key whose override is the sentinel ``...``."""
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not ...}


def _defaults(
    defaults: Dict[str, Any], overrides: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Layer a specialised factory's own defaults under a caller's overrides.

    A specialised builder such as ``recordkeeper_payload`` narrows the generic
    builder by fixing a handful of fields, but a caller must still be able to
    override any one of those same fields.  Passing the narrowed defaults as
    explicit keywords alongside ``**overrides`` would raise a TypeError for
    exactly the fields a caller most wants to change, so the two dicts are
    merged first and splatted once.
    """
    merged = dict(defaults)
    merged.update(overrides)
    return merged


# ─── PooledPlanProvider ───────────────────────────────


def plan_provider_payload(**overrides: Any) -> Dict[str, Any]:
    """A pooled plan provider registration intent with a ceiling-level bond."""
    return _merge(
        {
            "legal_name": k.MERIDIAN_LEGAL_NAME,
            "ein": k.MERIDIAN_EIN,
            "fidelity_bond_amount_cents": k.MERIDIAN_BOND_CENTS,
        },
        overrides,
    )


def second_plan_provider_payload(**overrides: Any) -> Dict[str, Any]:
    """A second, unrelated pooled plan provider."""
    return _merge(
        {
            "legal_name": k.WESTVALE_LEGAL_NAME,
            "ein": k.WESTVALE_EIN,
            "fidelity_bond_amount_cents": k.WESTVALE_BOND_CENTS,
        },
        overrides,
    )


def register_provider_payload(**overrides: Any) -> Dict[str, Any]:
    """An approval of a provider's registration."""
    return _merge(
        {"registration_effective_date": k.REGISTRATION_EFFECTIVE_DATE}, overrides
    )


# ─── PlanDocument ─────────────────────────────────────


def plan_document_payload(
    pooled_plan_provider_id: str, **overrides: Any
) -> Dict[str, Any]:
    """The single plan document every adopting employer adopts."""
    return _merge(
        {
            "pooled_plan_provider_id": pooled_plan_provider_id,
            "plan_name": k.PLAN_NAME,
            "plan_number": k.PLAN_NUMBER,
            "plan_year_end_date": k.PLAN_YEAR_END_DATE,
            "base_eligibility_min_age": 21,
            "base_eligibility_service_months": 12,
            "base_vesting_schedule": k.VESTING_CLIFF_3YR,
            "base_match_formula_code": k.MATCH_SAFE_HARBOR_BASIC,
        },
        overrides,
    )


def second_plan_document_payload(
    pooled_plan_provider_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A second plan document of the same sponsor, plan number 002."""
    return plan_document_payload(
        pooled_plan_provider_id,
        **_defaults(
            {
                "plan_name": k.PLAN_NAME_SECOND,
                "plan_number": k.PLAN_NUMBER_SECOND,
            },
            overrides,
        ),
    )


# ─── ServiceProvider ──────────────────────────────────


def service_provider_payload(plan_document_id: str, **overrides: Any) -> Dict[str, Any]:
    """A generic engagement; callers override the type and fee terms."""
    return _merge(
        {
            "plan_document_id": plan_document_id,
            "legal_name": k.RECORDKEEPER_LEGAL_NAME,
            "provider_type": k.PROVIDER_TYPE_RECORDKEEPER,
            "revenue_sharing_bps": k.RECORDKEEPER_BPS,
            "direct_fee_cents_per_participant": k.RECORDKEEPER_FEE_CENTS,
        },
        overrides,
    )


def recordkeeper_payload(plan_document_id: str, **overrides: Any) -> Dict[str, Any]:
    """The plan recordkeeper that reconciles and posts contributions."""
    return service_provider_payload(
        plan_document_id,
        **_defaults(
            {
                "legal_name": k.RECORDKEEPER_LEGAL_NAME,
                "provider_type": k.PROVIDER_TYPE_RECORDKEEPER,
                "revenue_sharing_bps": k.RECORDKEEPER_BPS,
                "direct_fee_cents_per_participant": k.RECORDKEEPER_FEE_CENTS,
            },
            overrides,
        ),
    )


def trustee_payload(plan_document_id: str, **overrides: Any) -> Dict[str, Any]:
    """The plan trustee that holds the trust."""
    return service_provider_payload(
        plan_document_id,
        **_defaults(
            {
                "legal_name": k.TRUSTEE_LEGAL_NAME,
                "provider_type": k.PROVIDER_TYPE_TRUSTEE,
                "revenue_sharing_bps": k.TRUSTEE_BPS,
                "direct_fee_cents_per_participant": k.TRUSTEE_FEE_CENTS,
            },
            overrides,
        ),
    )


def tpa_payload(plan_document_id: str, **overrides: Any) -> Dict[str, Any]:
    """A third party administrator engagement."""
    return service_provider_payload(
        plan_document_id,
        **_defaults(
            {
                "legal_name": k.TPA_LEGAL_NAME,
                "provider_type": k.PROVIDER_TYPE_TPA,
                "revenue_sharing_bps": 0,
                "direct_fee_cents_per_participant": k.TPA_FEE_CENTS,
            },
            overrides,
        ),
    )


def auditor_firm_payload(plan_document_id: str, **overrides: Any) -> Dict[str, Any]:
    """An audit firm engagement."""
    return service_provider_payload(
        plan_document_id,
        **_defaults(
            {
                "legal_name": k.AUDITOR_LEGAL_NAME,
                "provider_type": k.PROVIDER_TYPE_AUDITOR_FIRM,
                "revenue_sharing_bps": 0,
                "direct_fee_cents_per_participant": k.AUDITOR_FEE_CENTS,
            },
            overrides,
        ),
    )


def investment_manager_payload(
    plan_document_id: str, **overrides: Any
) -> Dict[str, Any]:
    """An investment manager engagement."""
    return service_provider_payload(
        plan_document_id,
        **_defaults(
            {
                "legal_name": k.INVESTMENT_MANAGER_LEGAL_NAME,
                "provider_type": k.PROVIDER_TYPE_INVESTMENT_MANAGER,
                "revenue_sharing_bps": k.INVESTMENT_MANAGER_BPS,
                "direct_fee_cents_per_participant": k.INVESTMENT_MANAGER_FEE_CENTS,
            },
            overrides,
        ),
    )


# ─── FiduciaryRoleAllocation ──────────────────────────


def fiduciary_allocation_payload(
    plan_document_id: str,
    service_provider_id: str,
    fiduciary_role: str,
    expected_plan_document_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """A closed-window allocation of a statutory fiduciary function."""
    return _merge(
        {
            "plan_document_id": plan_document_id,
            "service_provider_id": service_provider_id,
            "fiduciary_role": fiduciary_role,
            "effective_from": k.ALLOCATION_EFFECTIVE_FROM,
            "effective_to": k.ALLOCATION_EFFECTIVE_TO,
            "expected_plan_document_version": expected_plan_document_version,
        },
        overrides,
    )


def acknowledge_allocation_payload(
    acknowledgment_statement: str, **overrides: Any
) -> Dict[str, Any]:
    """A provider's written acknowledgment of a fiduciary function."""
    return _merge({"acknowledgment_statement": acknowledgment_statement}, overrides)


# ─── AdoptingEmployer ─────────────────────────────────


def adopting_employer_payload(plan_document_id: str, **overrides: Any) -> Dict[str, Any]:
    """The canonical 13-participant small-plan employer."""
    return _merge(
        {
            "plan_document_id": plan_document_id,
            "legal_name": k.PALISADE_LEGAL_NAME,
            "ein": k.PALISADE_EIN,
            "election_window_close_date": k.ELECTION_WINDOW_CLOSE_DATE,
            "participant_count": 13,
            "hce_count": 3,
            "nhce_count": 10,
            "benefiting_hce_count": 3,
            "benefiting_nhce_count": 9,
            "hce_avg_deferral_pct": 6.0,
            "nhce_avg_deferral_pct": 4.0,
        },
        overrides,
    )


def second_adopting_employer_payload(
    plan_document_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A second 15-participant employer on the same plan."""
    return adopting_employer_payload(
        plan_document_id,
        **_defaults(
            {
                "legal_name": k.QUARRY_LEGAL_NAME,
                "ein": k.QUARRY_EIN,
                "participant_count": 15,
                "hce_count": 4,
                "nhce_count": 11,
                "benefiting_hce_count": 4,
                "benefiting_nhce_count": 11,
                "hce_avg_deferral_pct": 5.0,
                "nhce_avg_deferral_pct": 4.0,
            },
            overrides,
        ),
    )


def census_payload(**overrides: Any) -> Dict[str, Any]:
    """A census restatement for an existing employer."""
    return _merge(
        {
            "participant_count": 13,
            "hce_count": 3,
            "nhce_count": 10,
            "benefiting_hce_count": 3,
            "benefiting_nhce_count": 9,
            "hce_avg_deferral_pct": 6.0,
            "nhce_avg_deferral_pct": 4.0,
        },
        overrides,
    )


# ─── PlanDesignElection ───────────────────────────────


def design_election_payload(
    adopting_employer_id: str,
    expected_adopting_employer_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """An election matching the plan document's base terms exactly."""
    return _merge(
        {
            "adopting_employer_id": adopting_employer_id,
            "eligibility_min_age": 21,
            "eligibility_service_months": 12,
            "vesting_schedule": k.VESTING_CLIFF_3YR,
            "match_formula_code": k.MATCH_SAFE_HARBOR_BASIC,
            "expected_adopting_employer_version": expected_adopting_employer_version,
        },
        overrides,
    )


def tiered_design_election_payload(
    adopting_employer_id: str,
    expected_adopting_employer_version: int,
    match_tier_1_pct: float,
    match_tier_1_limit_pct: float,
    match_tier_2_pct: float,
    match_tier_2_limit_pct: float,
    **overrides: Any,
) -> Dict[str, Any]:
    """A discretionary tiered election carrying all four tier fields."""
    return design_election_payload(
        adopting_employer_id,
        expected_adopting_employer_version,
        **_defaults(
            {
                "match_formula_code": k.MATCH_DISCRETIONARY_TIERED,
                "match_tier_1_pct": match_tier_1_pct,
                "match_tier_1_limit_pct": match_tier_1_limit_pct,
                "match_tier_2_pct": match_tier_2_pct,
                "match_tier_2_limit_pct": match_tier_2_limit_pct,
            },
            overrides,
        ),
    )


def submit_election_payload(
    signatory_name: str = k.PALISADE_SIGNATORY, **overrides: Any
) -> Dict[str, Any]:
    """An election submission carrying the employer's signatory."""
    return _merge({"signatory_name": signatory_name}, overrides)


def return_election_payload(
    return_reason: str, deficiency_code: str, **overrides: Any
) -> Dict[str, Any]:
    """A structured return of a submitted election."""
    return _merge(
        {"return_reason": return_reason, "deficiency_code": deficiency_code}, overrides
    )

# ─── PayrollBatch ─────────────────────────────────────


def payroll_batch_payload(adopting_employer_id: str, **overrides: Any) -> Dict[str, Any]:
    """
    The canonical payroll delivery.

    All four period fields are calendar dates.  The match total agrees with the
    basic safe harbour formula on the canonical compensation, so the batch
    reconciles unless a test deliberately breaks it.
    """
    return _merge(
        {
            "adopting_employer_id": adopting_employer_id,
            "pay_period_start": k.PAY_PERIOD_START,
            "pay_period_end": k.PAY_PERIOD_END,
            "pay_date": k.PAY_DATE,
            "withholding_date": k.WITHHOLDING_DATE,
            "payroll_provider_reference": k.PALISADE_PAYROLL_REFERENCE,
            "total_eligible_compensation_cents": k.CANONICAL_COMPENSATION_CENTS,
            "total_deferral_cents": k.CANONICAL_DEFERRAL_CENTS,
            "total_match_cents": k.CANONICAL_BASIC_MATCH_CENTS,
            "total_loan_repayment_cents": k.CANONICAL_LOAN_REPAYMENT_CENTS,
            "participant_line_count": 13,
        },
        overrides,
    )


def validate_batch_payload(
    reconciliation_note: str = k.RECONCILIATION_NOTE, **overrides: Any
) -> Dict[str, Any]:
    """A recordkeeper's reconciliation of a delivered batch."""
    return _merge({"reconciliation_note": reconciliation_note}, overrides)


# ─── RemittanceDeposit ────────────────────────────────


def remittance_deposit_payload(
    payroll_batch_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A remittance of the canonical batch total, on a timely deposit date."""
    return _merge(
        {
            "payroll_batch_id": payroll_batch_id,
            "deposit_date": k.DEPOSIT_DATE,
            "amount_cents": k.CANONICAL_BATCH_TOTAL_CENTS,
            "deposit_reference": k.DEPOSIT_REFERENCE,
        },
        overrides,
    )


def post_deposit_payload(
    posting_reference: str = k.POSTING_REFERENCE, **overrides: Any
) -> Dict[str, Any]:
    """A recordkeeper's posting of a deposit to the trust."""
    return _merge({"posting_reference": posting_reference}, overrides)


def reverse_deposit_payload(reversal_reason: str, **overrides: Any) -> Dict[str, Any]:
    """A reversal of a posted deposit."""
    return _merge({"reversal_reason": reversal_reason}, overrides)


def compute_correction_payload(
    correction_method: str = k.CORRECTION_IRS_6621_UNDERPAYMENT,
    recovery_date: str = k.RECOVERY_DATE,
    actual_investment_return_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """A late-deposit correction computation under a chosen method."""
    return _merge(
        {
            "correction_method": correction_method,
            "recovery_date": recovery_date,
            "actual_investment_return_cents": actual_investment_return_cents,
        },
        overrides,
    )


def fund_correction_payload(
    form_5330_reference: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """
    An employer's funding of the restoration amount.

    The excise tax return reference is optional, so it is omitted entirely
    unless a caller supplies one.
    """
    payload: Dict[str, Any] = {}
    if form_5330_reference is not None:
        payload["form_5330_reference"] = form_5330_reference
    return _merge(payload, overrides)


# ─── ComplianceTest ───────────────────────────────────


def compliance_test_payload(
    plan_document_id: str,
    test_type: str = k.TEST_TYPE_COVERAGE_410B_RATIO,
    scope: str = k.SCOPE_PLAN_LEVEL,
    plan_year: int = k.PLAN_YEAR,
    adopting_employer_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A scheduled coverage or nondiscrimination test."""
    payload: Dict[str, Any] = {
        "plan_document_id": plan_document_id,
        "test_type": test_type,
        "scope": scope,
        "plan_year": plan_year,
    }
    if adopting_employer_id is not None:
        payload["adopting_employer_id"] = adopting_employer_id
    return _merge(payload, overrides)


def employer_level_test_payload(
    plan_document_id: str,
    adopting_employer_id: str,
    test_type: str = k.TEST_TYPE_COVERAGE_410B_RATIO,
    **overrides: Any,
) -> Dict[str, Any]:
    """A test scoped to a single adopting employer."""
    return compliance_test_payload(
        plan_document_id,
        **_defaults(
            {
                "test_type": test_type,
                "scope": k.SCOPE_EMPLOYER_LEVEL,
                "adopting_employer_id": adopting_employer_id,
            },
            overrides,
        ),
    )


# ─── PlanFiling ───────────────────────────────────────


def plan_filing_payload(
    plan_document_id: str, plan_year: int = k.PLAN_YEAR, **overrides: Any
) -> Dict[str, Any]:
    """An annual return opened for a plan year."""
    return _merge(
        {"plan_document_id": plan_document_id, "plan_year": plan_year}, overrides
    )


def attest_filing_payload(
    audit_firm_service_provider_id: str,
    audit_opinion: str = k.OPINION_UNMODIFIED,
    **overrides: Any,
) -> Dict[str, Any]:
    """An independent auditor's attestation of the plan-level audit."""
    return _merge(
        {
            "audit_firm_service_provider_id": audit_firm_service_provider_id,
            "audit_opinion": audit_opinion,
        },
        overrides,
    )


# ─── ExitTransfer ─────────────────────────────────────


def exit_transfer_payload(adopting_employer_id: str, **overrides: Any) -> Dict[str, Any]:
    """A spin-off request whose blackout window closes before the exit date."""
    return _merge(
        {
            "adopting_employer_id": adopting_employer_id,
            "exit_type": k.EXIT_SPINOFF_TO_SINGLE_PLAN,
            "requested_exit_date": k.REQUESTED_EXIT_DATE,
            "blackout_start_date": k.BLACKOUT_START_DATE,
            "blackout_end_date": k.BLACKOUT_END_DATE,
            "successor_plan_name": k.SUCCESSOR_PLAN_NAME,
        },
        overrides,
    )


def reverse_transfer_payload(reversal_reason: str, **overrides: Any) -> Dict[str, Any]:
    """An unwind of a settled transfer."""
    return _merge({"reversal_reason": reversal_reason}, overrides)


# ─── FeeDisclosure ────────────────────────────────────


def fee_disclosure_payload(plan_document_id: str, **overrides: Any) -> Dict[str, Any]:
    """A fee disclosure for the first half of the plan year."""
    return _merge(
        {
            "plan_document_id": plan_document_id,
            "disclosure_period_start": k.DISCLOSURE_PERIOD_START,
            "disclosure_period_end": k.DISCLOSURE_PERIOD_END,
            "allocation_method": k.ALLOCATION_PER_CAPITA,
            "revenue_sharing_pool_cents": k.REVENUE_SHARING_POOL_CENTS,
        },
        overrides,
    )
