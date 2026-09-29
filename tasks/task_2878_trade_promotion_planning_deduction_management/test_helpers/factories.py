"""
Request-payload factories.

Each factory returns only the *input* fields the PRD declares for that write —
server-minted and derived fields are never sent, because unknown fields are
rejected outright. Money is emitted as a JSON number with two decimal places,
rates as a number with at most three, unit counts as integers, calendar fields
as ISO dates and `received_at` as a full ISO 8601 UTC instant.
"""

import itertools
from typing import Any, Dict

from .constants import (
    MONDAY_AUG_03,
    MONDAY_AUG_10,
    MONDAY_AUG_31,
    MONDAY_JUL_06,
    MONDAY_SEP_28,
    instant,
)
from .types import (
    AccrualMethod,
    BaselineMethod,
    Channel,
    CoversTacticType,
    DeductionValidationPolicy,
    DisputeReasonCode,
    DocClass,
    DocType,
    EventType,
    FactSource,
    FactType,
    RetailerResponse,
    TacticType,
)

_counter = itertools.count(1)


def _seq() -> int:
    """Monotonic counter making generated names and references unique."""
    return next(_counter)


DEFAULTS: Dict[str, Any] = {
    "program_name": "FY2026 National Trade Fund",
    "program_fiscal_year": 2026,
    "program_total_budget_amount": 1000000.00,
    "brand_name": "Aurora Sparkling Water 12pk",
    "brand_list_price_per_case": 24.00,
    "brand_cogs_per_case": 14.00,
    "brand_baseline_units_per_week": 500,
    "customer_name": "Northlake Grocers",
    "allocation_planned_amount": 100000.00,
    "allocation_baseline_units": 5000,
    "allocation_planned_incremental_units": 20000,
    "promotion_name": "August Sparkling Water Feature",
    "promotion_window_start": MONDAY_AUG_03,
    "promotion_window_end": MONDAY_AUG_31,
    "tactic_planned_units": 2000,
    "tactic_rate_per_case": 1.250,
    "tactic_fixed_fee": 4000.00,
    "document_received_at": instant(MONDAY_AUG_10, hour=9, minute=30),
    "volume_fact_units": 2000,
    "deduction_claimed_amount": 3000.00,
    "deduction_date": "2026-09-15",
    "dispute_disputed_amount": 500.00,
    "audit_scope_start": MONDAY_JUL_06,
    "audit_scope_end": MONDAY_SEP_28,
    "audit_finding_code": "MISSING_SIGNED_LOI",
    "audit_recovery_amount": 1200.00,
}


# ─── Program, brand and customer ──────────────────────

def create_program_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for opening an annual trade program."""
    payload: Dict[str, Any] = {
        "name": f"{DEFAULTS['program_name']} {_seq()}",
        "fiscal_year": DEFAULTS["program_fiscal_year"],
        "total_budget_amount": DEFAULTS["program_total_budget_amount"],
        "accrual_method_default": AccrualMethod.SHIPMENT.value,
    }
    payload.update(overrides)
    return payload


def create_brand_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    """Body for registering a brand under a trade program."""
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "name": f"{DEFAULTS['brand_name']} {_seq()}",
        "list_price_per_case": DEFAULTS["brand_list_price_per_case"],
        "cogs_per_case": DEFAULTS["brand_cogs_per_case"],
        "baseline_units_per_week": DEFAULTS["brand_baseline_units_per_week"],
    }
    payload.update(overrides)
    return payload


def create_customer_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    """Body for registering a retail customer under a trade program."""
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "name": f"{DEFAULTS['customer_name']} {_seq()}",
        "channel": Channel.GROCERY.value,
        "deduction_validation_policy": DeductionValidationPolicy.EVIDENCE_BASED.value,
    }
    payload.update(overrides)
    return payload


def credit_hold_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for placing a customer on manual credit hold."""
    payload: Dict[str, Any] = {"reason": "Remittance shortfall under review"}
    payload.update(overrides)
    return payload


# ─── Budget allocation ────────────────────────────────

def create_allocation_payload(
    program_id: str, customer_id: str, brand_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Body for earmarking part of the program envelope."""
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "customer_id": customer_id,
        "brand_id": brand_id,
        "event_type": EventType.SEASONAL.value,
        "planned_amount": DEFAULTS["allocation_planned_amount"],
        "baseline_units": DEFAULTS["allocation_baseline_units"],
        "planned_incremental_units": DEFAULTS["allocation_planned_incremental_units"],
    }
    payload.update(overrides)
    return payload


# ─── Promotion and tactic lines ───────────────────────

def create_promotion_payload(
    allocation_id: str, expected_allocation_version: int, **overrides: Any
) -> Dict[str, Any]:
    """
    Body for planning a promotion.

    Neither `customer_id` nor `brand_id` is sent: both are copied from the
    funding allocation and are rejected as unknown fields if supplied.
    """
    payload: Dict[str, Any] = {
        "allocation_id": allocation_id,
        "name": f"{DEFAULTS['promotion_name']} {_seq()}",
        "window_start": DEFAULTS["promotion_window_start"],
        "window_end": DEFAULTS["promotion_window_end"],
        "expected_allocation_version": expected_allocation_version,
    }
    payload.update(overrides)
    return payload


def create_tpr_tactic_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for a `TPR` line: carries `rate_per_case` and omits `fixed_fee`."""
    payload: Dict[str, Any] = {
        "tactic_type": TacticType.TPR.value,
        "planned_units": DEFAULTS["tactic_planned_units"],
        "rate_per_case": DEFAULTS["tactic_rate_per_case"],
        "window_start": DEFAULTS["promotion_window_start"],
        "window_end": DEFAULTS["promotion_window_end"],
    }
    payload.update(overrides)
    return payload


def create_display_tactic_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for a `DISPLAY` line: carries `fixed_fee` and omits `rate_per_case`."""
    payload: Dict[str, Any] = {
        "tactic_type": TacticType.DISPLAY.value,
        "planned_units": DEFAULTS["tactic_planned_units"],
        "fixed_fee": DEFAULTS["tactic_fixed_fee"],
        "window_start": DEFAULTS["promotion_window_start"],
        "window_end": DEFAULTS["promotion_window_end"],
    }
    payload.update(overrides)
    return payload


def create_feature_tactic_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for a `FEATURE` line: carries `fixed_fee` and omits `rate_per_case`."""
    payload: Dict[str, Any] = {
        "tactic_type": TacticType.FEATURE.value,
        "planned_units": DEFAULTS["tactic_planned_units"],
        "fixed_fee": DEFAULTS["tactic_fixed_fee"],
        "window_start": DEFAULTS["promotion_window_start"],
        "window_end": DEFAULTS["promotion_window_end"],
    }
    payload.update(overrides)
    return payload


def create_tactic_payload(tactic_type: str, **overrides: Any) -> Dict[str, Any]:
    """Body for a tactic line of the requested type, with the right money field."""
    if tactic_type == TacticType.TPR.value:
        return create_tpr_tactic_payload(**overrides)
    if tactic_type == TacticType.DISPLAY.value:
        return create_display_tactic_payload(**overrides)
    return create_feature_tactic_payload(**overrides)


def patch_tactic_payload(expected_promotion_version: int, **overrides: Any) -> Dict[str, Any]:
    """Body for rate maintenance on a `PLANNED` line of a `DRAFT` promotion."""
    payload: Dict[str, Any] = {
        "expected_promotion_version": expected_promotion_version,
    }
    payload.update(overrides)
    return payload


def cancel_tactic_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for cancelling a `PLANNED` tactic line."""
    payload: Dict[str, Any] = {"cancel_reason": "Retailer pulled the placement"}
    payload.update(overrides)
    return payload


def request_changes_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for the rework branch out of `SUBMITTED`."""
    payload: Dict[str, Any] = {"change_notes": "Reduce the display fee and resubmit"}
    payload.update(overrides)
    return payload


def withdraw_promotion_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for withdrawing an `APPROVED` promotion."""
    payload: Dict[str, Any] = {"withdraw_reason": "Retailer cancelled the event"}
    payload.update(overrides)
    return payload


# ─── Retailer documents ───────────────────────────────

def create_commitment_document_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for a `COMMITMENT` document; `units_verified` must stay 0."""
    payload: Dict[str, Any] = {
        "doc_class": DocClass.COMMITMENT.value,
        "doc_type": DocType.SIGNED_LOI.value,
        "covers_tactic_type": CoversTacticType.ALL.value,
        "received_at": DEFAULTS["document_received_at"],
    }
    payload.update(overrides)
    return payload


def create_evidence_document_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for an `EVIDENCE` document carrying substantiated cases."""
    payload: Dict[str, Any] = {
        "doc_class": DocClass.EVIDENCE.value,
        "doc_type": DocType.SCAN_DATA.value,
        "covers_tactic_type": CoversTacticType.ALL.value,
        "received_at": DEFAULTS["document_received_at"],
        "units_verified": 1800,
    }
    payload.update(overrides)
    return payload


# ─── Volume facts and accruals ────────────────────────

def create_volume_fact_payload(
    customer_id: str, brand_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Body for one week of shipment or consumption volume."""
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "brand_id": brand_id,
        "fact_type": FactType.SHIPMENT.value,
        "period_start": MONDAY_AUG_03,
        "units": DEFAULTS["volume_fact_units"],
        "source": FactSource.EDI_856.value,
    }
    payload.update(overrides)
    return payload


def create_accrual_payload(period_start: str = MONDAY_AUG_03, **overrides: Any) -> Dict[str, Any]:
    """Body for posting the accrual of one week."""
    payload: Dict[str, Any] = {"period_start": period_start}
    payload.update(overrides)
    return payload


def reverse_accrual_payload(amount: float, **overrides: Any) -> Dict[str, Any]:
    """Body for the compensating entry of a posted accrual."""
    payload: Dict[str, Any] = {
        "amount": amount,
        "reversal_reason": "Fact restatement received from the retailer",
    }
    payload.update(overrides)
    return payload


# ─── Deductions ───────────────────────────────────────

def create_deduction_payload(customer_id: str, **overrides: Any) -> Dict[str, Any]:
    """Body for booking a retailer chargeback."""
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "claim_reference": f"CB-{_seq():05d}",
        "claimed_amount": DEFAULTS["deduction_claimed_amount"],
        "deduction_date": DEFAULTS["deduction_date"],
    }
    payload.update(overrides)
    return payload


def match_deduction_payload(promotion_id: str, **overrides: Any) -> Dict[str, Any]:
    """Body for matching a `RECEIVED` claim to a promotion agreement."""
    payload: Dict[str, Any] = {"promotion_id": promotion_id}
    payload.update(overrides)
    return payload


def validate_deduction_payload(expected_promotion_version: int, **overrides: Any) -> Dict[str, Any]:
    """Body for valuing a `MATCHED` claim."""
    payload: Dict[str, Any] = {
        "expected_promotion_version": expected_promotion_version,
    }
    payload.update(overrides)
    return payload


# ─── Disputes ─────────────────────────────────────────

def create_dispute_payload(disputed_amount: float, **overrides: Any) -> Dict[str, Any]:
    """Body for opening a dispute over an invalid claim."""
    payload: Dict[str, Any] = {
        "reason_code": DisputeReasonCode.NO_EVIDENCE.value,
        "disputed_amount": disputed_amount,
    }
    payload.update(overrides)
    return payload


def send_to_retailer_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for sending an `OPEN` dispute to the retailer."""
    payload: Dict[str, Any] = {"packet_notes": "Deduction packet with rate sheet attached"}
    payload.update(overrides)
    return payload


def retailer_respond_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for the retailer's answer through the portal."""
    payload: Dict[str, Any] = {"retailer_response": RetailerResponse.REFUSE.value}
    payload.update(overrides)
    return payload


def record_recovery_payload(recovered_amount: float, **overrides: Any) -> Dict[str, Any]:
    """Body for recording cash recovered from the retailer."""
    payload: Dict[str, Any] = {"recovered_amount": recovered_amount}
    payload.update(overrides)
    return payload


def write_off_payload(write_off_amount: float, **overrides: Any) -> Dict[str, Any]:
    """Body for abandoning an uncollectible dispute."""
    payload: Dict[str, Any] = {
        "write_off_amount": write_off_amount,
        "write_off_reason": "Retailer refused and the amount is uncollectible",
    }
    payload.update(overrides)
    return payload


# ─── Post-event analysis and compliance audits ────────

def analyze_promotion_payload(
    baseline_method: str = BaselineMethod.TRAILING.value, **overrides: Any
) -> Dict[str, Any]:
    """Body for the post-event analysis of an `ENDED` promotion."""
    payload: Dict[str, Any] = {"baseline_method": baseline_method}
    payload.update(overrides)
    return payload


def create_compliance_audit_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for opening a contract-compliance audit over a scope window."""
    payload: Dict[str, Any] = {
        "scope_start": DEFAULTS["audit_scope_start"],
        "scope_end": DEFAULTS["audit_scope_end"],
    }
    payload.update(overrides)
    return payload


def record_audit_finding_payload(
    recovery_amount: float = DEFAULTS["audit_recovery_amount"], **overrides: Any
) -> Dict[str, Any]:
    """Body for recording one audit finding with its recovery claim."""
    payload: Dict[str, Any] = {
        "finding_code": DEFAULTS["audit_finding_code"],
        "recovery_amount": recovery_amount,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(current_utc: str) -> Dict[str, Any]:
    """Body for the test-driving logical clock capability."""
    return {"current_utc": current_utc}
