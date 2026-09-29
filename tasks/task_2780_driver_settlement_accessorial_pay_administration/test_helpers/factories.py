"""
Payload factories.

Each factory returns a plain dict ready to be posted. Defaults are chosen so that
a caller can override exactly the field under test and nothing else. Every money
amount is an integer number of cents and is emitted as a JSON integer, never as a
string, because the specification stores money as integer cents.
"""

from typing import Any, Dict

from .types import (
    AccessorialType,
    AdvanceType,
    ComponentType,
    DisputeKind,
    DriverType,
    EscrowReasonCode,
    MileageGuide,
    PerDiemMethod,
    RateUnit,
    RejectReasonCode,
    VoidReasonCode,
)


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the _OMIT sentinel so callers can remove a field."""
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    def __repr__(self):  # pragma: no cover - debugging aid only
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


# ── Pay packages and components ──────────────────────
def pay_package_payload(
    name: str = "Leased Operator Standard",
    driver_type: str = DriverType.LEASED_OPERATOR,
    mileage_guide: str = MileageGuide.PRACTICAL,
    per_diem_method: str = PerDiemMethod.DAY_BASED,
    escrow_required: bool = False,
    escrow_target_cents: Any = _OMIT,
    escrow_monthly_deduction_cents: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "name": name,
        "driver_type": driver_type,
        "mileage_guide": mileage_guide,
        "per_diem_method": per_diem_method,
        "escrow_required": escrow_required,
        "escrow_target_cents": escrow_target_cents,
        "escrow_monthly_deduction_cents": escrow_monthly_deduction_cents,
    }
    payload.update(overrides)
    return _prune(payload)


def escrow_package_payload(
    escrow_target_cents: int = 250000,
    escrow_monthly_deduction_cents: int = 40000,
    **overrides: Any,
) -> Dict[str, Any]:
    """An escrow-bearing package: escrow_required true with both amounts positive."""
    return pay_package_payload(
        escrow_required=True,
        escrow_target_cents=escrow_target_cents,
        escrow_monthly_deduction_cents=escrow_monthly_deduction_cents,
        **overrides,
    )


def component_payload(
    component_type: str = ComponentType.PER_MILE,
    unit: str = RateUnit.MILE,
    rate_value: int = 58,
    sequence: int = 1,
    taxable: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "component_type": component_type,
        "unit": unit,
        "rate_value": rate_value,
        "sequence": sequence,
        "taxable": taxable,
    }
    payload.update(overrides)
    return _prune(payload)


def per_mile_component(rate_value: int = 58, sequence: int = 1, **overrides: Any):
    return component_payload(
        ComponentType.PER_MILE, RateUnit.MILE, rate_value, sequence, **overrides
    )


def revenue_percent_component(rate_value: int = 2500, sequence: int = 2, **overrides: Any):
    return component_payload(
        ComponentType.REVENUE_PERCENT, RateUnit.PERCENT_BPS, rate_value, sequence, **overrides
    )


def hourly_component(rate_value: int = 2400, sequence: int = 3, **overrides: Any):
    return component_payload(
        ComponentType.HOURLY, RateUnit.HOUR, rate_value, sequence, **overrides
    )


def activity_component(rate_value: int = 3000, sequence: int = 4, **overrides: Any):
    return component_payload(
        ComponentType.ACTIVITY, RateUnit.LOAD, rate_value, sequence, **overrides
    )


def revise_payload(expected_pay_package_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_pay_package_version": expected_pay_package_version
    }
    payload.update(overrides)
    return _prune(payload)


# ── Drivers ──────────────────────────────────────────
def driver_payload(
    legal_name: str = "Dale Ruiz",
    driver_type: str = DriverType.LEASED_OPERATOR,
    home_state: Any = _OMIT,
    per_diem_elected: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "legal_name": legal_name,
        "driver_type": driver_type,
        "home_state": home_state,
        "per_diem_elected": per_diem_elected,
    }
    payload.update(overrides)
    return _prune(payload)


def assign_package_payload(pay_package_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"pay_package_id": pay_package_id}
    payload.update(overrides)
    return _prune(payload)


def driver_status_payload(new_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"new_status": new_status}
    payload.update(overrides)
    return _prune(payload)


# ── Escrow ───────────────────────────────────────────
def escrow_deduction_payload(
    amount_cents: int,
    expected_driver_version: int,
    reason_code: str = EscrowReasonCode.TRACTOR_LEASE,
    document_ref: Any = "DOC-ESCROW-1",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "amount_cents": amount_cents,
        "expected_driver_version": expected_driver_version,
        "reason_code": reason_code,
        "document_ref": document_ref,
    }
    payload.update(overrides)
    return _prune(payload)


def escrow_reversal_payload(
    reason_code: str = EscrowReasonCode.DEDUCTION_DISPUTED, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason_code": reason_code}
    payload.update(overrides)
    return _prune(payload)


def escrow_return_payload(
    payment_reference: str = "ACH-ESCROW-RETURN-1", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"payment_reference": payment_reference}
    payload.update(overrides)
    return _prune(payload)


# ── Loads ────────────────────────────────────────────
def load_payload(
    driver_id: str,
    linehaul_revenue_cents: int = 180000,
    practical_miles: int = 780,
    hhg_miles: int = 742,
    origin_zip: Any = _OMIT,
    dest_zip: Any = _OMIT,
    stop_count: Any = _OMIT,
    tarp_required: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "driver_id": driver_id,
        "linehaul_revenue_cents": linehaul_revenue_cents,
        "practical_miles": practical_miles,
        "hhg_miles": hhg_miles,
        "origin_zip": origin_zip,
        "dest_zip": dest_zip,
        "stop_count": stop_count,
        "tarp_required": tarp_required,
    }
    payload.update(overrides)
    return _prune(payload)


def dispatch_payload(dispatched_at: Any = _OMIT, **overrides: Any) -> Dict[str, Any]:
    payload = {"dispatched_at": dispatched_at}
    payload.update(overrides)
    return _prune(payload)


def deliver_payload(
    delivered_at: Any = _OMIT,
    hours_worked_minutes: Any = _OMIT,
    stop_count: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "delivered_at": delivered_at,
        "hours_worked_minutes": hours_worked_minutes,
        "stop_count": stop_count,
    }
    payload.update(overrides)
    return _prune(payload)


# ── Accessorial claims ───────────────────────────────
def accessorial_claim_payload(
    load_id: str,
    driver_id: str,
    accessorial_type: str,
    start_at: str,
    end_at: str,
    document_ref: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "load_id": load_id,
        "driver_id": driver_id,
        "accessorial_type": accessorial_type,
        "start_at": start_at,
        "end_at": end_at,
        "document_ref": document_ref,
    }
    payload.update(overrides)
    return _prune(payload)


def detention_claim_payload(
    load_id: str,
    driver_id: str,
    start_at: str,
    end_at: str,
    document_ref: Any = "DOC-DET-1",
    **overrides: Any,
) -> Dict[str, Any]:
    return accessorial_claim_payload(
        load_id,
        driver_id,
        AccessorialType.DETENTION,
        start_at,
        end_at,
        document_ref,
        **overrides,
    )


def layover_claim_payload(
    load_id: str, driver_id: str, start_at: str, end_at: str, **overrides: Any
) -> Dict[str, Any]:
    return accessorial_claim_payload(
        load_id, driver_id, AccessorialType.LAYOVER, start_at, end_at, **overrides
    )


def claim_document_payload(document_ref: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"document_ref": document_ref}
    payload.update(overrides)
    return _prune(payload)


def claim_reject_payload(
    reject_reason_code: str = RejectReasonCode.OUTSIDE_POLICY, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reject_reason_code": reject_reason_code}
    payload.update(overrides)
    return _prune(payload)


# ── Advances ─────────────────────────────────────────
def advance_payload(
    driver_id: str,
    amount_cents: int,
    advance_type: str = AdvanceType.CASH_ADVANCE,
    installment_cents: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "driver_id": driver_id,
        "amount_cents": amount_cents,
        "advance_type": advance_type,
        "installment_cents": installment_cents,
    }
    payload.update(overrides)
    return _prune(payload)


# ── Settlements ──────────────────────────────────────
def settlement_payload(
    driver_id: str, period_start: str, period_end: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "driver_id": driver_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return _prune(payload)


def apply_corrections_payload(
    expected_settlement_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_settlement_version": expected_settlement_version
    }
    payload.update(overrides)
    return _prune(payload)


def pay_payload(
    payment_reference: str = "ACH-SETTLEMENT-1", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"payment_reference": payment_reference}
    payload.update(overrides)
    return _prune(payload)


def void_payload(
    void_reason_code: str = VoidReasonCode.CLERICAL_ERROR, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"void_reason_code": void_reason_code}
    payload.update(overrides)
    return _prune(payload)


# ── Disputes ─────────────────────────────────────────
def mileage_dispute_payload(
    driver_id: str,
    load_id: str,
    claimed_guide: str,
    claimed_miles: int,
    narrative: str = "Routed miles under-reported on this movement.",
    evidence_doc_ref: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "dispute_kind": DisputeKind.MILEAGE,
        "driver_id": driver_id,
        "load_id": load_id,
        "claimed_guide": claimed_guide,
        "claimed_miles": claimed_miles,
        "narrative": narrative,
        "evidence_doc_ref": evidence_doc_ref,
    }
    payload.update(overrides)
    return _prune(payload)


def pay_dispute_payload(
    driver_id: str,
    settlement_id: str,
    claimed_amount_cents: int,
    disputed_line_type: str,
    narrative: str = "Statement line short-paid against the contract.",
    evidence_doc_ref: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "dispute_kind": DisputeKind.PAY,
        "driver_id": driver_id,
        "settlement_id": settlement_id,
        "claimed_amount_cents": claimed_amount_cents,
        "disputed_line_type": disputed_line_type,
        "narrative": narrative,
        "evidence_doc_ref": evidence_doc_ref,
    }
    payload.update(overrides)
    return _prune(payload)


def resolve_payload(
    outcome: str,
    resolution_note: Any = _OMIT,
    adjustment_cents: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "outcome": outcome,
        "resolution_note": resolution_note,
        "adjustment_cents": adjustment_cents,
    }
    payload.update(overrides)
    return _prune(payload)


def reopen_payload(
    narrative: str = "New routing evidence supplied with the reopen.",
    evidence_doc_ref: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"narrative": narrative, "evidence_doc_ref": evidence_doc_ref}
    payload.update(overrides)
    return _prune(payload)
