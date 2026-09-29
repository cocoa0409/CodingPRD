"""
Request-payload builders for the Child Support Enforcement API.

Every factory returns a plain dict carrying the PRD's required fields with
valid defaults, and accepts keyword overrides so a test can vary exactly the
one field it is about. Money is always an integer number of cents — never a
decimal and never a string.
"""

import itertools
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import (
    CLOCK_START,
    HOME_STATE_CODE,
)

# ---------------------------------------------------------------------------
# Unique-value sequences
# ---------------------------------------------------------------------------

_fein_counter = itertools.count(1)
_name_counter = itertools.count(1)
_ssn_counter = itertools.count(1000)


def next_fein() -> str:
    """A fresh FEIN in the two-digit, hyphen, seven-digit form."""
    n = next(_fein_counter)
    return f"{41 + (n % 50):02d}-{1000000 + n:07d}"


def next_ssn_last4() -> str:
    """A fresh four-digit ``ssn_last4``."""
    return f"{next(_ssn_counter) % 10000:04d}"


def next_name(prefix: str = "Party") -> str:
    """A fresh human-readable name between 1 and 120 characters."""
    return f"{prefix} {next(_name_counter):04d}"


# ---------------------------------------------------------------------------
# Date and instant arithmetic used to build payloads
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def format_instant(moment: datetime) -> str:
    """Render an instant as an ISO 8601 UTC string with three fractional digits."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def format_instant_seconds(moment: datetime) -> str:
    """Render an instant as an ISO 8601 UTC string with whole seconds."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_instant(value: str, *, days: int = 0, hours: int = 0, seconds: int = 0) -> str:
    """Return ``value`` moved by the given offset, rendered with whole seconds."""
    moved = parse_instant(value) + timedelta(days=days, hours=hours, seconds=seconds)
    return format_instant_seconds(moved)


def parse_date(value: str) -> date:
    """Parse an ISO calendar date in year-month-day form."""
    return date.fromisoformat(value)


def shift_date(value: str, *, days: int = 0) -> str:
    """Return the calendar date ``value`` moved by ``days``."""
    return (parse_date(value) + timedelta(days=days)).isoformat()


def add_months(value: str, months: int) -> str:
    """Return the calendar date ``value`` moved by whole months, clamping the day."""
    base = parse_date(value)
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    day = min(base.day, _days_in_month(year, month))
    return date(year, month, day).isoformat()


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def month_end(value: str) -> str:
    """Return the last calendar date of the month containing ``value``."""
    d = parse_date(value)
    return date(d.year, d.month, _days_in_month(d.year, d.month)).isoformat()


def instant_at_midnight(value: str) -> str:
    """Render a calendar date as the UTC instant at its start of day."""
    return f"{value}T00:00:00Z"


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def clock_payload(to_iso8601: str = CLOCK_START, **overrides: Any) -> Dict[str, Any]:
    """Body for setting the logical clock."""
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------


def participant_payload(
    role_type: str = "NONCUSTODIAL_PARTY", **overrides: Any
) -> Dict[str, Any]:
    """Body for registering a participant."""
    payload: Dict[str, Any] = {
        "role_type": role_type,
        "full_name": next_name("Party"),
        "ssn_last4": next_ssn_last4(),
        "residence_state_code": HOME_STATE_CODE,
    }
    payload.update(overrides)
    return payload


def custodial_party_payload(
    monthly_gross_income_cents: Optional[int] = 200000,
    income_verification_source: str = "VERIFIED_WAGE_RECORD",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for registering the custodial party with a verified income figure."""
    payload = participant_payload(
        role_type="CUSTODIAL_PARTY",
        full_name=next_name("Custodial"),
    )
    if monthly_gross_income_cents is not None:
        payload["monthly_gross_income_cents"] = monthly_gross_income_cents
        payload["income_verification_source"] = income_verification_source
    payload.update(overrides)
    return payload


def noncustodial_party_payload(
    monthly_gross_income_cents: Optional[int] = 300000,
    income_verification_source: str = "VERIFIED_WAGE_RECORD",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for registering the obligor with a verified income figure."""
    payload = participant_payload(
        role_type="NONCUSTODIAL_PARTY",
        full_name=next_name("Obligor"),
        employer_name="Northline Manufacturing",
        supports_second_family=False,
        has_valid_drivers_license=True,
    )
    if monthly_gross_income_cents is not None:
        payload["monthly_gross_income_cents"] = monthly_gross_income_cents
        payload["income_verification_source"] = income_verification_source
    payload.update(overrides)
    return payload


def income_patch_payload(
    monthly_gross_income_cents: int = 400000,
    income_verification_source: str = "VERIFIED_WAGE_RECORD",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for recording a new income figure and its provenance."""
    payload: Dict[str, Any] = {
        "monthly_gross_income_cents": monthly_gross_income_cents,
        "income_verification_source": income_verification_source,
    }
    payload.update(overrides)
    return payload


def locate_result_payload(locate_outcome: str = "LOCATED", **overrides: Any) -> Dict[str, Any]:
    """Body for recording the outcome of locate services."""
    payload: Dict[str, Any] = {"locate_outcome": locate_outcome}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def case_payload(
    custodial_party_id: str,
    noncustodial_party_id: str,
    case_type: str = "DIRECT_APPLICATION",
    child_count: int = 2,
    tanf_assistance: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for opening a IV-D case."""
    payload: Dict[str, Any] = {
        "case_type": case_type,
        "custodial_party_id": custodial_party_id,
        "noncustodial_party_id": noncustodial_party_id,
        "child_count": child_count,
        "tanf_assistance": tanf_assistance,
    }
    payload.update(overrides)
    return payload


def assistance_case_payload(
    custodial_party_id: str, noncustodial_party_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Body for opening a public-assistance case whose arrears are assigned."""
    return case_payload(
        custodial_party_id,
        noncustodial_party_id,
        case_type="PA_REFERRAL",
        tanf_assistance=True,
        **overrides,
    )


def locate_referral_payload(
    locate_source: str = "FEDERAL_PLS", **overrides: Any
) -> Dict[str, Any]:
    """Body for referring the obligor to locate services."""
    payload: Dict[str, Any] = {"locate_source": locate_source}
    payload.update(overrides)
    return payload


def closure_payload(closed_reason: str = "CP_REQUEST", **overrides: Any) -> Dict[str, Any]:
    """Body for closing a case."""
    payload: Dict[str, Any] = {"closed_reason": closed_reason}
    payload.update(overrides)
    return payload


def accrual_run_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for posting an accrual run; the run takes no inputs of its own."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Paternity
# ---------------------------------------------------------------------------


def paternity_action_payload(
    method: str = "PRESUMED_MARITAL", **overrides: Any
) -> Dict[str, Any]:
    """Body for opening the single paternity action of a case."""
    payload: Dict[str, Any] = {"method": method}
    payload.update(overrides)
    return payload


def acknowledgment_payload(
    signed_by_participant_id: str, notary_verified: bool = True, **overrides: Any
) -> Dict[str, Any]:
    """Body for recording a notarised voluntary acknowledgment of parentage."""
    payload: Dict[str, Any] = {
        "notary_verified": notary_verified,
        "signed_by_participant_id": signed_by_participant_id,
    }
    payload.update(overrides)
    return payload


def rescission_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for rescinding a signed acknowledgment."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def genetic_test_order_payload(
    collection_appointment_at: str, **overrides: Any
) -> Dict[str, Any]:
    """Body for ordering genetic testing and scheduling specimen collection."""
    payload: Dict[str, Any] = {"collection_appointment_at": collection_appointment_at}
    payload.update(overrides)
    return payload


def specimen_collection_payload(
    chain_of_custody_ok: bool = True, **overrides: Any
) -> Dict[str, Any]:
    """Body for recording a specimen collection attempt."""
    payload: Dict[str, Any] = {"chain_of_custody_ok": chain_of_custody_ok}
    payload.update(overrides)
    return payload


def genetic_result_payload(
    genetic_probability_pct: float = 99.5, **overrides: Any
) -> Dict[str, Any]:
    """Body for recording the probability of parentage."""
    payload: Dict[str, Any] = {"genetic_probability_pct": genetic_probability_pct}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Support orders
# ---------------------------------------------------------------------------


def order_payload(
    order_type: str = "CURRENT_SUPPORT",
    effective_date: str = "2026-08-01",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for drafting a support order."""
    payload: Dict[str, Any] = {
        "order_type": order_type,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def guideline_calculation_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for running the guideline worksheet; the run takes no inputs."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def deviation_request_payload(
    deviation_requested_cents: int,
    deviation_reason: str = "HARDSHIP",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for requesting a deviation from the guideline amount."""
    payload: Dict[str, Any] = {
        "deviation_requested_cents": deviation_requested_cents,
        "deviation_reason": deviation_reason,
    }
    payload.update(overrides)
    return payload


def deviation_findings_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    """Body for the attorney's decision on a requested deviation."""
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def entry_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for entering an order at the guideline amount."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def vacatur_payload(vacate_reason: str = "CLERICAL_ERROR", **overrides: Any) -> Dict[str, Any]:
    """Body for vacating an order."""
    payload: Dict[str, Any] = {"vacate_reason": vacate_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Employers and withholding
# ---------------------------------------------------------------------------


def employer_payload(
    state_code: str = HOME_STATE_CODE,
    pay_frequency: str = "MONTHLY",
    remittance_fee_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for registering an employer."""
    payload: Dict[str, Any] = {
        "legal_name": next_name("Employer"),
        "fein": next_fein(),
        "state_code": state_code,
        "pay_frequency": pay_frequency,
        "remittance_fee_cents": remittance_fee_cents,
    }
    payload.update(overrides)
    return payload


def withholding_order_payload(
    employer_id: str,
    expected_order_version: int,
    reported_disposable_income_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for issuing an income withholding order."""
    payload: Dict[str, Any] = {
        "employer_id": employer_id,
        "expected_order_version": expected_order_version,
    }
    if reported_disposable_income_cents is not None:
        payload["reported_disposable_income_cents"] = reported_disposable_income_cents
    payload.update(overrides)
    return payload


def service_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for recording service of the withholding order on the employer."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def amendment_payload(
    reported_disposable_income_cents: int, **overrides: Any
) -> Dict[str, Any]:
    """Body for amending the reported disposable income."""
    payload: Dict[str, Any] = {
        "reported_disposable_income_cents": reported_disposable_income_cents
    }
    payload.update(overrides)
    return payload


def remittance_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    """Body for an employer's withheld remittance."""
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def lapse_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for recording a missed remittance period."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def iwo_termination_payload(
    terminated_reason: str = "EMPLOYMENT_ENDED", **overrides: Any
) -> Dict[str, Any]:
    """Body for terminating a withholding order."""
    payload: Dict[str, Any] = {"terminated_reason": terminated_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Charges and payments
# ---------------------------------------------------------------------------


def charge_payload(
    charge_type: str = "CURRENT_SUPPORT",
    period_start_date: str = "2026-08-01",
    period_end_date: str = "2026-09-01",
    due_date: str = "2026-08-01",
    amount_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for posting an obligation charge against an entered order."""
    payload: Dict[str, Any] = {
        "charge_type": charge_type,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "due_date": due_date,
    }
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    payload.update(overrides)
    return payload


def monthly_charge_payload(
    month_start: str,
    charge_type: str = "CURRENT_SUPPORT",
    due_day: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Body for a charge covering exactly one calendar month from ``month_start``.

    ``due_day`` places the due date inside that month, since the due date is the
    anchor from which per-charge statutory interest is measured. An explicit
    ``due_date`` override wins over ``due_day``.
    """
    due_date = overrides.pop("due_date", None) or "%s%02d" % (month_start[:8], due_day)
    return charge_payload(
        charge_type=charge_type,
        period_start_date=month_start,
        period_end_date=add_months(month_start, 1),
        due_date=due_date,
        **overrides,
    )


def voidance_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for voiding an unpaid charge."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def payment_payload(
    amount_cents: int, source: str = "DIRECT_PAY", **overrides: Any
) -> Dict[str, Any]:
    """Body for posting a non-withholding collection."""
    payload: Dict[str, Any] = {"source": source, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def installment_payment_payload(
    amount_cents: int, compromise_offer_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Body for a compromise installment payment referencing its offer."""
    return payment_payload(
        amount_cents,
        source="COMPROMISE_INSTALLMENT",
        compromise_offer_id=compromise_offer_id,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Modification review
# ---------------------------------------------------------------------------


def modification_review_payload(
    trigger_type: str = "PARTY_REQUEST", **overrides: Any
) -> Dict[str, Any]:
    """Body for opening a modification review on an entered order."""
    payload: Dict[str, Any] = {"trigger_type": trigger_type}
    payload.update(overrides)
    return payload


def screening_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for screening a review against the substantial-change test."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def review_information_payload(
    participant_id: str,
    monthly_gross_income_cents: int,
    income_verification_source: str = "VERIFIED_WAGE_RECORD",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for supplying the income information a screening asked for."""
    payload: Dict[str, Any] = {
        "participant_id": participant_id,
        "monthly_gross_income_cents": monthly_gross_income_cents,
        "income_verification_source": income_verification_source,
    }
    payload.update(overrides)
    return payload


def proposed_order_payload(effective_date: str, **overrides: Any) -> Dict[str, Any]:
    """Body for creating the successor order of a review."""
    payload: Dict[str, Any] = {"effective_date": effective_date}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


def enforcement_action_payload(
    action_type: str = "LICENSE_SUSPENSION", **overrides: Any
) -> Dict[str, Any]:
    """Body for proposing an enforcement remedy."""
    payload: Dict[str, Any] = {"action_type": action_type}
    payload.update(overrides)
    return payload


def notice_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for sending the pre-deprivation notice."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def contest_payload(
    contest_grounds: str = "MISTAKE_OF_FACT", **overrides: Any
) -> Dict[str, Any]:
    """Body for the obligor's contest of a proposed remedy."""
    payload: Dict[str, Any] = {"contest_grounds": contest_grounds}
    payload.update(overrides)
    return payload


def review_decision_payload(
    review_decision: str = "UPHOLD", **overrides: Any
) -> Dict[str, Any]:
    """Body for the attorney's decision on a contested action."""
    payload: Dict[str, Any] = {"review_decision": review_decision}
    payload.update(overrides)
    return payload


def activation_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for activating an uncontested remedy."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def release_payload(
    release_reason: str = "PLAN_COMPLIANT", **overrides: Any
) -> Dict[str, Any]:
    """Body for releasing an active remedy."""
    payload: Dict[str, Any] = {"release_reason": release_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Interstate referrals
# ---------------------------------------------------------------------------


def interstate_referral_payload(
    direction: str = "INITIATING",
    other_state_code: str = "TX",
    child_home_state_code: str = HOME_STATE_CODE,
    transmittal_type: str = "ENFORCEMENT",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for drafting a UIFSA transmittal."""
    payload: Dict[str, Any] = {
        "direction": direction,
        "other_state_code": other_state_code,
        "child_home_state_code": child_home_state_code,
        "transmittal_type": transmittal_type,
    }
    payload.update(overrides)
    return payload


def transmittal_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for transmitting an initiating referral."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def registration_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for registering a referral and determining the controlling order."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def referral_return_payload(
    returned_reason: str = "NO_JURISDICTION", **overrides: Any
) -> Dict[str, Any]:
    """Body for returning a transmittal unworked."""
    payload: Dict[str, Any] = {"returned_reason": returned_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Compromise offers
# ---------------------------------------------------------------------------


def compromise_offer_payload(
    expected_case_version: int, installment_count: int = 3, **overrides: Any
) -> Dict[str, Any]:
    """Body for building an arrears compromise offer."""
    payload: Dict[str, Any] = {
        "installment_count": installment_count,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def offer_acceptance_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for the obligor's acceptance of a compromise offer."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def default_declaration_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for declaring a compromise plan in default."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload
