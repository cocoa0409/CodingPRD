"""Composite setup helpers.

Most interesting claims in this platform need the system walked several calls
deep — a guide edition, an obligor, a community whose operator agreement is
executed, a registered unit, a certified valuation, a priced and approved loan,
proved coverage and a recorded instrument — before the behaviour under test can
even be reached.  These helpers encapsulate those walks so tests carry
assertions only.

Every helper uses the lenient ``get_success_data`` validator, so a broken
precondition surfaces as a setup failure rather than as a confusing assertion.
Identity is threaded explicitly: a CommunityOperator call always carries the
acting community's own ``id`` as ``X-User-ID``.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import TEST_DEFAULTS
from .test_users import (
    LOAN_APPROVER_USER_ID,
    RECOVERY_CERTIFIER_USER_ID,
    TEST_USERS,
    VALUATION_CERTIFIER_USER_ID,
    make_community_operator_headers,
    make_credit_analyst_headers,
    make_recovery_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["credit_analyst_headers"]
CLOSER = TEST_USERS["closing_agent_headers"]
SERVICER = TEST_USERS["servicer_headers"]
RECOVERY = TEST_USERS["recovery_manager_headers"]


# ─── Tier 0: single-step primitives ───────────────────

def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the server-wide logical UTC clock forward to ``current_utc``."""
    return get_success_data(api.set_clock(current_utc, ADMIN))


def publish_guide(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_book_value_guide(f.book_value_guide_payload(**overrides), ADMIN))


def register_borrower(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_borrower(f.borrower_payload(**overrides), ADMIN))


def register_community(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_community(f.community_payload(**overrides), ADMIN))


def propose_agreement(api: ApiClient, community_id: str) -> Dict[str, Any]:
    """PlatformAdmin proposes the operator agreement; the community moves to PENDING."""
    return get_success_data(api.operator_agreement(community_id, "PROPOSE", ADMIN))


def execute_agreement(api: ApiClient, community_id: str) -> Dict[str, Any]:
    """The CommunityOperator executes its own agreement — X-User-ID is the community id."""
    return get_success_data(
        api.operator_agreement(
            community_id, "EXECUTE", make_community_operator_headers(community_id)
        )
    )


def terminate_agreement(api: ApiClient, community_id: str) -> Dict[str, Any]:
    return get_success_data(api.operator_agreement(community_id, "TERMINATE", ADMIN))


def register_community_with_executed_agreement(api: ApiClient, **overrides) -> Dict[str, Any]:
    """Register a community and walk its agreement NONE -> PENDING -> EXECUTED."""
    community = register_community(api, **overrides)
    propose_agreement(api, community["id"])
    return execute_agreement(api, community["id"])


def register_community_with_pending_agreement(api: ApiClient, **overrides) -> Dict[str, Any]:
    community = register_community(api, **overrides)
    return propose_agreement(api, community["id"])


def register_community_unit(api: ApiClient, community_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_unit(f.community_unit_payload(community_id, **overrides), CLOSER)
    )


def register_private_land_unit(
    api: ApiClient, land_owner_borrower_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_unit(
            f.private_land_unit_payload(land_owner_borrower_id, **overrides), CLOSER
        )
    )


def record_land_documents(api: ApiClient, unit_id: str) -> Dict[str, Any]:
    """Record both the DEED and the AFFIXATION_AFFIDAVIT; returns the unit after the second."""
    get_success_data(api.record_land_document(unit_id, "DEED", CLOSER))
    return get_success_data(api.record_land_document(unit_id, "AFFIXATION_AFFIDAVIT", CLOSER))


def read_unit(api: ApiClient, unit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_unit(unit_id, ADMIN))


def read_loan(api: ApiClient, loan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_loan(loan_id, SERVICER))


def read_borrower(api: ApiClient, borrower_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_borrower(borrower_id, ADMIN))


def read_community(api: ApiClient, community_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_community(community_id, ADMIN))


def read_valuation(api: ApiClient, valuation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_valuation(valuation_id, ANALYST))


def read_filing(api: ApiClient, filing_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_lien_filing(filing_id, CLOSER))


def read_policy(api: ApiClient, policy_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_insurance_policy(policy_id, SERVICER))


def read_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_recovery_case(case_id, RECOVERY))


def read_payment(api: ApiClient, payment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_payment(payment_id, SERVICER))


# ─── Tier 1: valuation state progression ──────────────

def create_valuation(
    api: ApiClient,
    unit_id: str,
    guide_id: str,
    expected_unit_version: int,
    variant: str = "ORIGINATION",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_valuation(
            f.valuation_payload(unit_id, guide_id, expected_unit_version, variant),
            headers or ANALYST,
        )
    )


def certify_valuation(
    api: ApiClient,
    valuation_id: str,
    certifier_user_id: str = VALUATION_CERTIFIER_USER_ID,
    role: str = "CreditAnalyst",
) -> Dict[str, Any]:
    """Freeze a draft valuation, stamping ``certified_by_user_id`` with the actor."""
    headers = (
        make_credit_analyst_headers(certifier_user_id)
        if role == "CreditAnalyst"
        else make_recovery_manager_headers(certifier_user_id)
    )
    return get_success_data(api.certify_valuation(valuation_id, headers))


def create_certified_valuation(
    api: ApiClient,
    unit_id: str,
    guide_id: str,
    variant: str = "ORIGINATION",
    expected_unit_version: Optional[int] = None,
    certifier_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a valuation and certify it in one step.

    When ``expected_unit_version`` is omitted the unit is re-read first, which is
    what a client must do anyway because creating a valuation increments the
    unit's own version.
    """
    if expected_unit_version is None:
        expected_unit_version = read_unit(api, unit_id)["version"]
    role = "CreditAnalyst" if variant == "ORIGINATION" else "RecoveryManager"
    creator = ANALYST if variant == "ORIGINATION" else RECOVERY
    certifier = certifier_user_id or (
        VALUATION_CERTIFIER_USER_ID if variant == "ORIGINATION" else RECOVERY_CERTIFIER_USER_ID
    )
    valuation = create_valuation(
        api, unit_id, guide_id, expected_unit_version, variant, creator
    )
    return certify_valuation(api, valuation["id"], certifier, role)


# ─── Tier 2: loan origination progression ─────────────

def open_loan(
    api: ApiClient,
    borrower_id: str,
    unit_id: str,
    origination_valuation_id: str,
    principal_cents: int = TEST_DEFAULTS["PRINCIPAL_CENTS"],
    requested_term_months: int = TEST_DEFAULTS["REQUESTED_TERM_MONTHS"],
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_loan(
            f.loan_payload(
                borrower_id,
                unit_id,
                origination_valuation_id,
                principal_cents,
                requested_term_months,
                **overrides,
            ),
            ANALYST,
        )
    )


def price_loan(api: ApiClient, loan_id: str) -> Dict[str, Any]:
    """Submit for underwriting, which computes ltv_bps, apr_bps and term_months."""
    return get_success_data(api.submit_underwriting(loan_id, ANALYST))


def approve_loan(
    api: ApiClient, loan_id: str, approver_user_id: str = LOAN_APPROVER_USER_ID
) -> Dict[str, Any]:
    """Credit-approve the loan under an operator identity distinct from the certifier."""
    return get_success_data(
        api.approve_loan(loan_id, make_credit_analyst_headers(approver_user_id))
    )


def record_policy(
    api: ApiClient,
    loan_id: str,
    dwelling_coverage_cents: int = 5200000,
    expected_loan_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Record a borrower-provided hazard policy, re-reading the loan version first."""
    if expected_loan_version is None:
        expected_loan_version = read_loan(api, loan_id)["version"]
    payload = f.insurance_policy_payload(
        loan_id, expected_loan_version, dwelling_coverage_cents, **overrides
    )
    return get_success_data(api.create_insurance_policy(payload, headers or CLOSER))


def tender_filing(api: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_lien_filing(payload, CLOSER))


def record_filing_outcome(
    api: ApiClient,
    filing_id: str,
    outcome: str = "RECORDED",
    agency_reference: Optional[str] = None,
    rejection_code: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.agency_response(
            filing_id,
            f.agency_response_payload(outcome, agency_reference, rejection_code),
            ADMIN,
        )
    )


def perfect_with_title_lien(api: ApiClient, loan_id: str) -> Dict[str, Any]:
    """Tender a TITLE_LIEN and have the agency record it; the loan reaches PERFECTED."""
    filing = tender_filing(api, f.title_lien_payload(loan_id))
    return record_filing_outcome(api, filing["id"])


def perfect_with_deed_of_trust(api: ApiClient, loan_id: str) -> Dict[str, Any]:
    """Tender a LAND_HOME_DEED_OF_TRUST and have the county record it."""
    filing = tender_filing(api, f.deed_of_trust_payload(loan_id))
    return record_filing_outcome(api, filing["id"], agency_reference=f.unique_agency_reference("GA-DT-2026"))


def fund_loan(
    api: ApiClient,
    loan_id: str,
    first_due_date: str = TEST_DEFAULTS["FIRST_DUE_DATE"],
    escrow_target_cents: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"first_due_date": first_due_date}
    if escrow_target_cents is not None:
        payload["escrow_target_cents"] = escrow_target_cents
    return get_success_data(api.fund_loan(loan_id, payload, CLOSER))


def run_servicing_assessment(api: ApiClient, loan_id: str) -> Dict[str, Any]:
    return get_success_data(api.servicing_assessment(loan_id, SERVICER))


def post_payment(
    api: ApiClient, loan_id: str, amount_cents: int, payment_kind: str = "SCHEDULED"
) -> Dict[str, Any]:
    return get_success_data(
        api.create_payment(loan_id, f.payment_payload(amount_cents, payment_kind), SERVICER)
    )


def reverse_payment(
    api: ApiClient, payment_id: str, reversal_reason: str = "ACH_RETURN_R01"
) -> Dict[str, Any]:
    return get_success_data(
        api.reverse_payment(payment_id, SERVICER, {"reversal_reason": reversal_reason})
    )


def report_lot_rent(
    api: ApiClient,
    loan_id: str,
    community_id: str,
    months_delinquent: int,
    lot_rent_state: str = "DELINQUENT",
) -> Dict[str, Any]:
    """The CommunityOperator reports lot-rent standing on a loan in its own park."""
    return get_success_data(
        api.lot_rent_report(
            loan_id,
            f.lot_rent_report_payload(months_delinquent, lot_rent_state),
            make_community_operator_headers(community_id),
        )
    )


def convert_classification(api: ApiClient, unit_id: str, action: str) -> Dict[str, Any]:
    return get_success_data(api.convert_classification(unit_id, action, CLOSER))


def complete_conversion(api: ApiClient, unit_id: str) -> Dict[str, Any]:
    """Walk a private-land unit PERSONAL_PROPERTY -> CONVERSION_PENDING -> REAL_PROPERTY."""
    convert_classification(api, unit_id, "INITIATE")
    return convert_classification(api, unit_id, "COMPLETE")


# ─── Tier 3: collateral scenarios ─────────────────────

def setup_community_collateral(
    api: ApiClient,
    clock: Optional[str] = None,
    agreement: str = "EXECUTED",
    guide_overrides: Optional[Dict[str, Any]] = None,
    borrower_overrides: Optional[Dict[str, Any]] = None,
    community_overrides: Optional[Dict[str, Any]] = None,
    unit_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Guide + obligor + community (agreement walked to ``agreement``) + a unit on a lot.

    ``agreement`` is one of ``NONE``, ``PENDING``, ``EXECUTED`` or
    ``TERMINATED`` and decides the location adjustment a valuation of this unit
    will attract.
    """
    if clock:
        set_clock(api, clock)
    guide = publish_guide(api, **(guide_overrides or {}))
    borrower = register_borrower(api, **(borrower_overrides or {}))
    community = register_community(api, **(community_overrides or {}))
    if agreement in ("PENDING", "EXECUTED", "TERMINATED"):
        community = propose_agreement(api, community["id"])
    if agreement in ("EXECUTED", "TERMINATED"):
        community = execute_agreement(api, community["id"])
    if agreement == "TERMINATED":
        community = terminate_agreement(api, community["id"])
    unit = register_community_unit(api, community["id"], **(unit_overrides or {}))
    return {
        "guide": guide,
        "borrower": borrower,
        "community": community,
        "unit": unit,
    }


def setup_private_land_collateral(
    api: ApiClient,
    clock: Optional[str] = None,
    guide_overrides: Optional[Dict[str, Any]] = None,
    borrower_overrides: Optional[Dict[str, Any]] = None,
    unit_overrides: Optional[Dict[str, Any]] = None,
    record_documents: bool = True,
) -> Dict[str, Any]:
    """Guide + obligor + a unit on land the obligor owns, with both land documents."""
    if clock:
        set_clock(api, clock)
    guide = publish_guide(api, **(guide_overrides or {}))
    borrower = register_borrower(
        api, **(borrower_overrides or {"full_name": "Marcus Bell", "credit_score": 728,
                                      "monthly_income_cents": 610000, "state_code": "GA"})
    )
    unit = register_private_land_unit(api, borrower["id"], **(unit_overrides or {}))
    if record_documents:
        unit = record_land_documents(api, unit["id"])
    return {"guide": guide, "borrower": borrower, "community": None, "unit": unit}


# ─── Tier 4: loan lifecycle shortcuts ─────────────────

def setup_approved_loan(
    api: ApiClient,
    scenario: Dict[str, Any],
    principal_cents: int = TEST_DEFAULTS["PRINCIPAL_CENTS"],
    requested_term_months: int = TEST_DEFAULTS["REQUESTED_TERM_MONTHS"],
    certifier_user_id: str = VALUATION_CERTIFIER_USER_ID,
    approver_user_id: str = LOAN_APPROVER_USER_ID,
    loan_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Certify an ORIGINATION valuation, open the application, price it and approve it."""
    valuation = create_certified_valuation(
        api,
        scenario["unit"]["id"],
        scenario["guide"]["id"],
        "ORIGINATION",
        certifier_user_id=certifier_user_id,
    )
    loan = open_loan(
        api,
        scenario["borrower"]["id"],
        scenario["unit"]["id"],
        valuation["id"],
        principal_cents,
        requested_term_months,
        **(loan_overrides or {}),
    )
    price_loan(api, loan["id"])
    loan = approve_loan(api, loan["id"], approver_user_id)
    scenario = dict(scenario)
    scenario["valuation"] = valuation
    scenario["loan"] = loan
    return scenario


def setup_funded_loan(
    api: ApiClient,
    scenario: Dict[str, Any],
    dwelling_coverage_cents: int = 5200000,
    filing_type: str = "TITLE_LIEN",
    first_due_date: str = TEST_DEFAULTS["FIRST_DUE_DATE"],
    escrow_target_cents: Optional[int] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Prove coverage, perfect the lien and fund an already-approved loan."""
    loan_id = scenario["loan"]["id"]
    policy = record_policy(
        api, loan_id, dwelling_coverage_cents, **(policy_overrides or {})
    )
    if filing_type == "TITLE_LIEN":
        filing = perfect_with_title_lien(api, loan_id)
    else:
        filing = perfect_with_deed_of_trust(api, loan_id)
    loan = fund_loan(api, loan_id, first_due_date, escrow_target_cents)
    scenario = dict(scenario)
    scenario["policy"] = policy
    scenario["filing"] = filing
    scenario["loan"] = loan
    return scenario


def setup_funded_community_loan(
    api: ApiClient,
    clock: Optional[str] = None,
    principal_cents: int = TEST_DEFAULTS["PRINCIPAL_CENTS"],
    requested_term_months: int = TEST_DEFAULTS["REQUESTED_TERM_MONTHS"],
    dwelling_coverage_cents: int = 5200000,
    first_due_date: str = TEST_DEFAULTS["FIRST_DUE_DATE"],
    escrow_target_cents: Optional[int] = None,
    agreement: str = "EXECUTED",
    community_overrides: Optional[Dict[str, Any]] = None,
    unit_overrides: Optional[Dict[str, Any]] = None,
    borrower_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The canonical chattel loan: a piered MULTI_WIDE on an executed community lot,
    priced, approved, insured, perfected by title lien and funded."""
    scenario = setup_community_collateral(
        api,
        clock=clock,
        agreement=agreement,
        community_overrides=community_overrides,
        unit_overrides=unit_overrides,
        borrower_overrides=borrower_overrides,
    )
    scenario = setup_approved_loan(
        api,
        scenario,
        principal_cents=principal_cents,
        requested_term_months=requested_term_months,
    )
    return setup_funded_loan(
        api,
        scenario,
        dwelling_coverage_cents=dwelling_coverage_cents,
        filing_type="TITLE_LIEN",
        first_due_date=first_due_date,
        escrow_target_cents=escrow_target_cents,
    )


def setup_funded_private_land_loan(
    api: ApiClient,
    clock: Optional[str] = None,
    principal_cents: int = TEST_DEFAULTS["PRINCIPAL_CENTS"],
    requested_term_months: int = TEST_DEFAULTS["REQUESTED_TERM_MONTHS"],
    dwelling_coverage_cents: int = 6800000,
    first_due_date: str = TEST_DEFAULTS["FIRST_DUE_DATE"],
    escrow_target_cents: Optional[int] = None,
    unit_overrides: Optional[Dict[str, Any]] = None,
    borrower_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A private-land loan on a permanently founded MULTI_WIDE, funded on a title lien."""
    scenario = setup_private_land_collateral(
        api,
        clock=clock,
        unit_overrides=unit_overrides,
        borrower_overrides=borrower_overrides,
    )
    scenario = setup_approved_loan(
        api,
        scenario,
        principal_cents=principal_cents,
        requested_term_months=requested_term_months,
    )
    return setup_funded_loan(
        api,
        scenario,
        dwelling_coverage_cents=dwelling_coverage_cents,
        filing_type="TITLE_LIEN",
        first_due_date=first_due_date,
        escrow_target_cents=escrow_target_cents,
    )


# ─── Tier 5: delinquency, default and recovery ────────

def setup_delinquent_community_loan(
    api: ApiClient,
    assessment_clock: str = "2026-10-31T00:00:00Z",
    **kwargs,
) -> Dict[str, Any]:
    """Fund a community chattel loan, then walk the clock so one assessment
    finds the loan past the 30-day delinquency threshold."""
    scenario = setup_funded_community_loan(api, clock="2026-08-01T00:00:00Z", **kwargs)
    set_clock(api, assessment_clock)
    scenario["loan"] = run_servicing_assessment(api, scenario["loan"]["id"])
    return scenario


def setup_defaulted_community_loan(
    api: ApiClient,
    assessment_clock: str = "2026-10-31T00:00:00Z",
    **kwargs,
) -> Dict[str, Any]:
    """Declare default on a delinquent chattel loan, opening a REPOSSESSION case."""
    scenario = setup_delinquent_community_loan(
        api, assessment_clock=assessment_clock, **kwargs
    )
    case = get_success_data(api.declare_default(scenario["loan"]["id"], RECOVERY))
    scenario["case"] = case
    scenario["loan"] = read_loan(api, scenario["loan"]["id"])
    return scenario


def setup_defaulted_real_property_loan(
    api: ApiClient,
    assessment_clock: str = "2026-12-01T00:00:00Z",
    **kwargs,
) -> Dict[str, Any]:
    """Fund a private-land loan, convert the unit to real property, then default it
    onto the FORECLOSURE arm."""
    scenario = setup_funded_private_land_loan(api, clock="2026-08-01T00:00:00Z", **kwargs)
    scenario["unit"] = complete_conversion(api, scenario["unit"]["id"])
    set_clock(api, assessment_clock)
    scenario["loan"] = run_servicing_assessment(api, scenario["loan"]["id"])
    case = get_success_data(api.declare_default(scenario["loan"]["id"], RECOVERY))
    scenario["case"] = case
    scenario["loan"] = read_loan(api, scenario["loan"]["id"])
    return scenario


def issue_notice(
    api: ApiClient, case_id: str, notice_reference: str = "RTC-2026-0001"
) -> Dict[str, Any]:
    return get_success_data(
        api.issue_notice(case_id, {"notice_reference": notice_reference}, RECOVERY)
    )


def obtain_possession(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.obtain_possession(case_id, RECOVERY))


def begin_refurbishment(
    api: ApiClient, case_id: str, recovery_valuation_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.begin_refurbishment(
            case_id, {"recovery_valuation_id": recovery_valuation_id}, RECOVERY
        )
    )


def record_refurbishment_cost(
    api: ApiClient, case_id: str, category: str, cost_cents: int, cost_class: str
) -> Dict[str, Any]:
    return get_success_data(
        api.record_refurbishment_cost(
            case_id, f.refurbishment_cost_payload(category, cost_cents, cost_class), RECOVERY
        )
    )


def list_for_resale(api: ApiClient, case_id: str, asking_price_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api.list_for_resale(case_id, {"asking_price_cents": asking_price_cents}, RECOVERY)
    )


def finalize_sale(
    api: ApiClient,
    case_id: str,
    resale_price_cents: int,
    resale_loan_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"resale_price_cents": resale_price_cents}
    if resale_loan_id is not None:
        payload["resale_loan_id"] = resale_loan_id
    return get_success_data(api.finalize_sale(case_id, payload, RECOVERY))


def setup_case_at_possession(
    api: ApiClient,
    possession_clock: str = "2026-11-15T00:00:00Z",
    notice_reference: str = "RTC-2026-0455",
    **kwargs,
) -> Dict[str, Any]:
    """Repossession arm walked to POSSESSION_OBTAINED: default, notice, then the
    clock moved past the ten-day right-to-cure deadline."""
    scenario = setup_defaulted_community_loan(api, **kwargs)
    scenario["case"] = issue_notice(api, scenario["case"]["id"], notice_reference)
    set_clock(api, possession_clock)
    scenario["case"] = obtain_possession(api, scenario["case"]["id"])
    scenario["loan"] = read_loan(api, scenario["loan"]["id"])
    scenario["unit"] = read_unit(api, scenario["unit"]["id"])
    return scenario


def setup_case_at_remarketing(
    api: ApiClient,
    asking_price_cents: int = 5400000,
    refurbishment_lines: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Repossession arm walked to REMARKETING with a certified RECOVERY_LIQUIDATION
    valuation attached and any requested refurbishment lines recorded."""
    scenario = setup_case_at_possession(api, **kwargs)
    recovery_valuation = create_certified_valuation(
        api,
        scenario["unit"]["id"],
        scenario["guide"]["id"],
        "RECOVERY_LIQUIDATION",
        certifier_user_id=RECOVERY_CERTIFIER_USER_ID,
    )
    scenario["recovery_valuation"] = recovery_valuation
    scenario["case"] = begin_refurbishment(
        api, scenario["case"]["id"], recovery_valuation["id"]
    )
    for line in refurbishment_lines or []:
        scenario["case"] = record_refurbishment_cost(
            api,
            scenario["case"]["id"],
            line["category"],
            line["cost_cents"],
            line["cost_class"],
        )
    scenario["case"] = list_for_resale(api, scenario["case"]["id"], asking_price_cents)
    return scenario
