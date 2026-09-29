"""Payload factories for every write endpoint.

Each factory returns a fresh dict whose defaults satisfy the PRD's shape rules,
then applies `overrides` last so a test can pin one field or delete one with
`overrides={"field": None}` handled explicitly by the caller. Overrides are
merged with dict.update rather than passed as keyword arguments, so a test may
override any field, including one the factory sets by default, without a
duplicate-argument collision.

Money is always an integer number of cents and basis points are always plain
integers (PRD 2.6). The date-only fields birth_date, hire_date,
retirement_date, medicare_part_b_effective_date, esrd_entitlement_date,
event_date and service_date carry no time component; every other temporal field
is a full ISO 8601 UTC instant.
"""
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Shared plan-year vocabulary. These are the values the fixtures build the
# standard 2027 plan year from.
# --------------------------------------------------------------------------- #
PLAN_YEAR_2027 = 2027
OPEN_ENROLLMENT_START = "2026-10-15T00:00:00Z"
OPEN_ENROLLMENT_END = "2026-11-15T00:00:00Z"
COVERAGE_START = "2027-01-01T00:00:00Z"
HRA_CREDIT_PRE_MEDICARE_CENTS = 185000
HRA_CREDIT_MEDICARE_CENTS = 209500
CARRYOVER_CAP_PCT = 0.5
DISCOUNT_RATE_BPS = 500
ASSUMED_ANNUAL_SUBSIDY_CENTS = 240000
ASSUMED_PAYMENT_YEARS = 20
PREMIUM_GRACE_PERIOD_DAYS = 31
REINSTATEMENT_WINDOW_DAYS = 60
NOTICE_LEAD_DAYS = 60

# Plan option premiums used across the suite.
PRE65_CORE_PREMIUM_CENTS = 74500
MED_WRAP_PREMIUM_CENTS = 32900


def _merge(base: Dict[str, Any], overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = dict(base)
    if overrides:
        payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Clock and ops
# --------------------------------------------------------------------------- #
def clock_payload(to_iso8601: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _merge({"to_iso8601": to_iso8601}, overrides)


# --------------------------------------------------------------------------- #
# PlanYear
# --------------------------------------------------------------------------- #
def plan_year_payload(
    year: int = PLAN_YEAR_2027,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A plan year whose annual election window is [2026-10-15, 2026-11-15) and
    whose coverage starts 2027-01-01."""
    return _merge(
        {
            "year": year,
            "open_enrollment_start": OPEN_ENROLLMENT_START,
            "open_enrollment_end": OPEN_ENROLLMENT_END,
            "coverage_start": COVERAGE_START,
            "hra_credit_pre_medicare_cents": HRA_CREDIT_PRE_MEDICARE_CENTS,
            "hra_credit_medicare_cents": HRA_CREDIT_MEDICARE_CENTS,
            "carryover_cap_pct": CARRYOVER_CAP_PCT,
            "discount_rate_bps": DISCOUNT_RATE_BPS,
            "assumed_annual_subsidy_cents": ASSUMED_ANNUAL_SUBSIDY_CENTS,
            "assumed_payment_years": ASSUMED_PAYMENT_YEARS,
            "premium_grace_period_days": PREMIUM_GRACE_PERIOD_DAYS,
            "reinstatement_window_days": REINSTATEMENT_WINDOW_DAYS,
            "notice_lead_days": NOTICE_LEAD_DAYS,
        },
        overrides,
    )


def plan_year_status_payload(to_status: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _merge({"to_status": to_status}, overrides)


def liability_valuation_payload(method: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _merge({"method": method}, overrides)


# --------------------------------------------------------------------------- #
# Retiree
# --------------------------------------------------------------------------- #
def retiree_payload(
    full_name: str = "Rosa Alvarez",
    birth_date: str = "1963-06-01",
    hire_date: str = "1990-06-01",
    retirement_date: str = "2026-12-31",
    credited_service_months: int = 150,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A pre-Medicare retiree. hire_date 1990-06-01 falls before 1993-01-01, so
    the grandfather group derives as GRANDFATHERED_A. The optional Medicare
    attributes are left out so their PRD defaults apply."""
    return _merge(
        {
            "full_name": full_name,
            "birth_date": birth_date,
            "hire_date": hire_date,
            "retirement_date": retirement_date,
            "credited_service_months": credited_service_months,
        },
        overrides,
    )


def retiree_r1_payload(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """R1 Rosa Alvarez: retires 2026-12-31 at completed age 63 with 150 credited
    months, so service_years is 12 and eligibility_points is exactly 75."""
    return retiree_payload(overrides=overrides)


def retiree_r2_payload(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """R2 Walter Nkemelu: hired 1988-09-01, so GRANDFATHERED_A, and already
    enrolled in Medicare Part B from 2023-04-01."""
    return retiree_payload(
        full_name="Walter Nkemelu",
        birth_date="1958-03-01",
        hire_date="1988-09-01",
        retirement_date="2023-03-31",
        credited_service_months=402,
        overrides=_merge(
            {
                "medicare_status": "MEDICARE_ENROLLED",
                "medicare_part_b_effective_date": "2023-04-01",
            },
            overrides,
        ),
    )


def retiree_r3_payload(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """R3 Priya Raghunathan: identical to R1 except for 143 credited months, so
    service_years is 11 and eligibility_points is 74 - one point short."""
    return retiree_payload(
        full_name="Priya Raghunathan",
        birth_date="1963-06-01",
        hire_date="1990-06-01",
        retirement_date="2026-12-31",
        credited_service_months=143,
        overrides=overrides,
    )


def retiree_r4_payload(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """R4 Bertrand Okonkwo: a second pre-Medicare retiree with long service, used
    where a test needs a second enrollment that must stay untouched."""
    return retiree_payload(
        full_name="Bertrand Okonkwo",
        birth_date="1961-01-01",
        hire_date="1990-06-01",
        retirement_date="2026-12-31",
        credited_service_months=402,
        overrides=overrides,
    )


def retiree_r5_payload(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """R5 Ingrid Sorenson: hired 1998-04-01, so TRANSITION_B, retiring at
    completed age 64 with 344 credited months, which is 28 service years."""
    return retiree_payload(
        full_name="Ingrid Sorenson",
        birth_date="1962-04-01",
        hire_date="1998-04-01",
        retirement_date="2026-12-31",
        credited_service_months=344,
        overrides=overrides,
    )


def retiree_r6_payload(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """R6 Tomas Ferreira: hired 2008-04-01, so STANDARD_C, the same completed age
    64 as R5 but with 224 credited months, which is 18 service years."""
    return retiree_payload(
        full_name="Tomas Ferreira",
        birth_date="1962-04-01",
        hire_date="2008-04-01",
        retirement_date="2026-12-31",
        credited_service_months=224,
        overrides=overrides,
    )


def retiree_patch_payload(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """PATCH bodies carry only the Medicare and other-coverage attributes."""
    return _merge({}, overrides)


# --------------------------------------------------------------------------- #
# PlanOption
# --------------------------------------------------------------------------- #
def plan_option_payload(
    plan_year_id: str,
    plan_code: str = "PRE65-CORE",
    coverage_class: str = "PRE_MEDICARE_GROUP",
    monthly_premium_cents: int = PRE65_CORE_PREMIUM_CENTS,
    requires_medicare_part_b: bool = False,
    allowed_grandfather_groups: Optional[List[str]] = None,
    subsidy_vehicle: str = "NONE",
    rx_gross_value_bps: int = 0,
    rx_net_value_bps: int = 0,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return _merge(
        {
            "plan_year_id": plan_year_id,
            "plan_code": plan_code,
            "coverage_class": coverage_class,
            "monthly_premium_cents": monthly_premium_cents,
            "requires_medicare_part_b": requires_medicare_part_b,
            "allowed_grandfather_groups": list(
                allowed_grandfather_groups
                if allowed_grandfather_groups is not None
                else ["GRANDFATHERED_A", "TRANSITION_B", "STANDARD_C"]
            ),
            "subsidy_vehicle": subsidy_vehicle,
            "rx_gross_value_bps": rx_gross_value_bps,
            "rx_net_value_bps": rx_net_value_bps,
        },
        overrides,
    )


def pre65_core_payload(plan_year_id: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """PRE65-CORE: a pre-Medicare group option with no prescription subsidy."""
    return plan_option_payload(plan_year_id, overrides=overrides)


def med_wrap_payload(plan_year_id: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """MED-WRAP: a Medicare group wrap option funded through EGWP, so it needs a
    Part B effective date and an actuarial attestation."""
    return plan_option_payload(
        plan_year_id,
        plan_code="MED-WRAP",
        coverage_class="MEDICARE_GROUP_WRAP",
        monthly_premium_cents=MED_WRAP_PREMIUM_CENTS,
        requires_medicare_part_b=True,
        allowed_grandfather_groups=["GRANDFATHERED_A", "TRANSITION_B"],
        subsidy_vehicle="EGWP",
        rx_gross_value_bps=10500,
        rx_net_value_bps=7800,
        overrides=overrides,
    )


def exch_hra_payload(plan_year_id: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """EXCH-HRA: an individual-exchange HRA option with a zero premium."""
    return plan_option_payload(
        plan_year_id,
        plan_code="EXCH-HRA",
        coverage_class="INDIVIDUAL_EXCHANGE_HRA",
        monthly_premium_cents=0,
        overrides=overrides,
    )


def attest_payload(
    rx_gross_value_bps: int = 10500,
    rx_net_value_bps: int = 7800,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return _merge(
        {
            "rx_gross_value_bps": rx_gross_value_bps,
            "rx_net_value_bps": rx_net_value_bps,
        },
        overrides,
    )


def subsidy_certification_payload(decision: str = "CERTIFY", overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def change_notice_payload(
    change_type: str = "PREMIUM_INCREASE",
    effective_date: str = "2026-12-19T00:00:00Z",
    new_monthly_premium_cents: Optional[int] = 79900,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "change_type": change_type,
        "effective_date": effective_date,
    }
    if new_monthly_premium_cents is not None:
        base["new_monthly_premium_cents"] = new_monthly_premium_cents
    return _merge(base, overrides)


# --------------------------------------------------------------------------- #
# EligibilityDetermination
# --------------------------------------------------------------------------- #
def determination_payload(
    retiree_id: str,
    plan_year_id: str,
    expected_retiree_version: int,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return _merge(
        {
            "retiree_id": retiree_id,
            "plan_year_id": plan_year_id,
            "expected_retiree_version": expected_retiree_version,
        },
        overrides,
    )


def appeal_payload(appeal_reason: str = "Service credit recount requested", overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _merge({"appeal_reason": appeal_reason}, overrides)


def appeal_decision_payload(decision: str = "UPHOLD", overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# --------------------------------------------------------------------------- #
# ElectionEvent
# --------------------------------------------------------------------------- #
def election_event_payload(
    retiree_id: str,
    plan_year_id: str,
    requested_plan_option_id: str,
    event_type: str = "ANNUAL_OPEN",
    event_date: str = "2026-10-20",
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """event_date is a date-only field (PRD 2.6)."""
    return _merge(
        {
            "retiree_id": retiree_id,
            "plan_year_id": plan_year_id,
            "requested_plan_option_id": requested_plan_option_id,
            "event_type": event_type,
            "event_date": event_date,
        },
        overrides,
    )


def election_decision_payload(
    decision: str = "APPROVE",
    denial_reason_code: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"decision": decision}
    if denial_reason_code is not None:
        base["denial_reason_code"] = denial_reason_code
    return _merge(base, overrides)


# --------------------------------------------------------------------------- #
# Enrollment
# --------------------------------------------------------------------------- #
def terminate_payload(
    termination_reason: str = "RETIREE_VOLUNTARY_WITHDRAWAL",
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return _merge({"termination_reason": termination_reason}, overrides)


# --------------------------------------------------------------------------- #
# HraAccount
# --------------------------------------------------------------------------- #
def hra_account_payload(
    retiree_id: str,
    plan_year_id: str,
    covered_months: int = 12,
    prior_year_account_id: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "retiree_id": retiree_id,
        "plan_year_id": plan_year_id,
        "covered_months": covered_months,
    }
    if prior_year_account_id is not None:
        base["prior_year_account_id"] = prior_year_account_id
    return _merge(base, overrides)


# --------------------------------------------------------------------------- #
# ReimbursementClaim
# --------------------------------------------------------------------------- #
def claim_payload(
    hra_account_id: str,
    expected_hra_account_version: int,
    expense_category: str = "QUALIFIED_MEDICAL",
    service_date: str = "2027-03-15",
    submitted_cents: int = 30000,
    documentation_reference: Optional[str] = "DOC-2027-0315",
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """service_date is a date-only field; submitted_cents is integer cents."""
    base: Dict[str, Any] = {
        "hra_account_id": hra_account_id,
        "expense_category": expense_category,
        "service_date": service_date,
        "submitted_cents": submitted_cents,
        "expected_hra_account_version": expected_hra_account_version,
    }
    if documentation_reference is not None:
        base["documentation_reference"] = documentation_reference
    return _merge(base, overrides)


def substantiation_payload(
    documentation_reference: str = "DOC-RESUBMIT-0001",
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return _merge({"documentation_reference": documentation_reference}, overrides)


def claim_review_payload(
    decision: str = "APPROVE",
    denial_reason_code: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"decision": decision}
    if denial_reason_code is not None:
        base["denial_reason_code"] = denial_reason_code
    return _merge(base, overrides)


def claim_settlement_payload(action: str = "PAY", overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# --------------------------------------------------------------------------- #
# PremiumInvoice
# --------------------------------------------------------------------------- #
def invoice_payload(
    enrollment_id: str,
    billing_period_start: str = "2027-01-01T00:00:00Z",
    billing_period_end: str = "2027-01-31T00:00:00Z",
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Billing periods are closed on both endpoints, so consecutive periods must
    not share an endpoint instant."""
    return _merge(
        {
            "enrollment_id": enrollment_id,
            "billing_period_start": billing_period_start,
            "billing_period_end": billing_period_end,
        },
        overrides,
    )


def payment_payload(amount_cents: int, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _merge({"amount_cents": amount_cents}, overrides)


__all__ = [
    "PLAN_YEAR_2027",
    "OPEN_ENROLLMENT_START",
    "OPEN_ENROLLMENT_END",
    "COVERAGE_START",
    "HRA_CREDIT_PRE_MEDICARE_CENTS",
    "HRA_CREDIT_MEDICARE_CENTS",
    "CARRYOVER_CAP_PCT",
    "DISCOUNT_RATE_BPS",
    "ASSUMED_ANNUAL_SUBSIDY_CENTS",
    "ASSUMED_PAYMENT_YEARS",
    "PREMIUM_GRACE_PERIOD_DAYS",
    "REINSTATEMENT_WINDOW_DAYS",
    "NOTICE_LEAD_DAYS",
    "PRE65_CORE_PREMIUM_CENTS",
    "MED_WRAP_PREMIUM_CENTS",
    "clock_payload",
    "plan_year_payload",
    "plan_year_status_payload",
    "liability_valuation_payload",
    "retiree_payload",
    "retiree_r1_payload",
    "retiree_r2_payload",
    "retiree_r3_payload",
    "retiree_r4_payload",
    "retiree_patch_payload",
    "plan_option_payload",
    "pre65_core_payload",
    "med_wrap_payload",
    "exch_hra_payload",
    "attest_payload",
    "subsidy_certification_payload",
    "change_notice_payload",
    "determination_payload",
    "appeal_payload",
    "appeal_decision_payload",
    "election_event_payload",
    "election_decision_payload",
    "terminate_payload",
    "hra_account_payload",
    "claim_payload",
    "substantiation_payload",
    "claim_review_payload",
    "claim_settlement_payload",
    "invoice_payload",
    "payment_payload",
]
