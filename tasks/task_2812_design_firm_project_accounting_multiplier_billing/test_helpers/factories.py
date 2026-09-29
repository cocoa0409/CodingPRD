"""
Request payload factories for the design-firm project accounting API.

Every factory returns a plain dict whose keys are the PRD's own field names and
whose money and ratio values are JSON **numbers**, never strings: PRD §2.5 says
monetary figures are carried at exactly 2 decimal places and ratios at exactly 4,
and a quoted "100.00" is a value of the wrong JSON type, which §2.5 rejects with
ERR_INVALID_REQUEST.

Optional fields are omitted unless supplied, because several PRD rules turn on
absence rather than on a null: ``effective_to`` omitted leaves a labour rate
window open-ended (§3.2), ``lump_sum_fee`` must be omitted on a
PERCENT_OF_CONTRACT phase and ``fee_percent`` on a LUMP_SUM one (§3.1), and
``invoice_id`` must be omitted on an UNBILLED_LABOR_WIP write-off (§3.8).

The two canonical client profiles are the private practice client and the public
agency client, because ``is_public_agency`` switches four separate rules:
statutory expense exclusion, the consultant markup cap, the certification gate
on invoicing and the certified multiplier ceiling on new multipliers.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CATEGORY_ENTERTAINMENT,
    CATEGORY_PRINTING,
    CONTRACT_TIME_AND_MATERIALS,
    FEE_BASIS_LUMP_SUM,
    FEE_BASIS_PERCENT_OF_CONTRACT,
    METHOD_EFFORT_BASED,
    ROLE_CODE_PROJECT_ARCHITECT,
    TARGET_INVOICE_RECEIVABLE,
    TARGET_UNBILLED_LABOR_WIP,
)
from .test_users import PROJECT_MANAGER_USER_ID

JsonDict = Dict[str, Any]


def _drop_unset(payload: JsonDict) -> JsonDict:
    """Remove keys whose value is the sentinel ``_UNSET``."""
    return {key: val for key, val in payload.items() if val is not _UNSET}


class _Unset:
    def __repr__(self) -> str:  # pragma: no cover
        return "<unset>"


_UNSET = _Unset()


# ─── Logical clock (PRD §2.6) ─────────────────────────────────────────


def clock_payload(to_iso8601: str) -> JsonDict:
    """The single field the clock move takes."""
    return {"to_iso8601": to_iso8601}


# ─── Client (PRD §3.1) ────────────────────────────────────────────────


def private_client_payload(**overrides: Any) -> JsonDict:
    """
    A private practice client: not a public agency, 5% retainage, 10% expense
    markup, ENTERTAINMENT contractually refused, receipts required at 75.00.
    """
    payload: JsonDict = {
        "name": "Northside Development",
        "is_public_agency": False,
        "retainage_pct": 0.0500,
        "expense_markup_pct": 0.1000,
        "disallowed_categories": [CATEGORY_ENTERTAINMENT],
        "receipt_required_above": 75.00,
        "review_cycle_days": 30,
    }
    payload.update(overrides)
    return payload


def public_client_payload(**overrides: Any) -> JsonDict:
    """
    A public agency client: statutory unallowable-cost rules apply, the
    consultant markup is capped and invoicing is gated on certification.
    """
    payload: JsonDict = {
        "name": "State Transit Authority",
        "is_public_agency": True,
        "retainage_pct": 0.0500,
        "expense_markup_pct": 0.0500,
        "disallowed_categories": [],
        "receipt_required_above": 75.00,
        "review_cycle_days": 45,
    }
    payload.update(overrides)
    return payload


def client_payload(
    name: str = "Northside Development",
    is_public_agency: bool = False,
    retainage_pct: float = 0.0500,
    expense_markup_pct: float = 0.1000,
    disallowed_categories: Optional[List[str]] = None,
    receipt_required_above: float = 75.00,
    review_cycle_days: int = 30,
    **overrides: Any,
) -> JsonDict:
    """Fully explicit client payload for range and shape probes."""
    payload: JsonDict = {
        "name": name,
        "is_public_agency": is_public_agency,
        "retainage_pct": retainage_pct,
        "expense_markup_pct": expense_markup_pct,
        "disallowed_categories": (
            [] if disallowed_categories is None else list(disallowed_categories)
        ),
        "receipt_required_above": receipt_required_above,
        "review_cycle_days": review_cycle_days,
    }
    payload.update(overrides)
    return payload


# ─── Project (PRD §3.1) ───────────────────────────────────────────────


def project_payload(
    client_id: str,
    name: str = "Riverside Library",
    contract_type: str = CONTRACT_TIME_AND_MATERIALS,
    contract_amount: float = 800000.00,
    project_manager_user_id: str = PROJECT_MANAGER_USER_ID,
    percent_complete_method: str = METHOD_EFFORT_BASED,
    target_multiplier: float = 3.0000,
    wip_alert_threshold: Any = _UNSET,
    **overrides: Any,
) -> JsonDict:
    """
    A project payload. ``wip_alert_threshold`` is omitted unless supplied so the
    50000.00 default of PRD §2.11 is exercised by default.
    """
    payload: JsonDict = {
        "client_id": client_id,
        "name": name,
        "contract_type": contract_type,
        "contract_amount": contract_amount,
        "project_manager_user_id": project_manager_user_id,
        "percent_complete_method": percent_complete_method,
        "target_multiplier": target_multiplier,
        "wip_alert_threshold": wip_alert_threshold,
    }
    payload.update(overrides)
    return _drop_unset(payload)


def lock_period_payload(locked_through_date: str) -> JsonDict:
    return {"locked_through_date": locked_through_date}


# ─── Phase (PRD §3.1) ─────────────────────────────────────────────────


def lump_sum_phase_payload(
    project_id: str,
    wbs_code: str = "02-DD",
    lump_sum_fee: float = 200000.00,
    budget_labor_cost: float = 60000.00,
    consultant_budget: float = 0.00,
    parent_phase_id: Any = _UNSET,
    **overrides: Any,
) -> JsonDict:
    """A LUMP_SUM phase: ``fee_percent`` must be omitted (PRD §3.1)."""
    payload: JsonDict = {
        "project_id": project_id,
        "wbs_code": wbs_code,
        "fee_basis": FEE_BASIS_LUMP_SUM,
        "lump_sum_fee": lump_sum_fee,
        "budget_labor_cost": budget_labor_cost,
        "consultant_budget": consultant_budget,
        "parent_phase_id": parent_phase_id,
    }
    payload.update(overrides)
    return _drop_unset(payload)


def percent_phase_payload(
    project_id: str,
    wbs_code: str = "01-SD",
    fee_percent: float = 0.2500,
    budget_labor_cost: float = 50000.00,
    consultant_budget: float = 0.00,
    parent_phase_id: Any = _UNSET,
    **overrides: Any,
) -> JsonDict:
    """A PERCENT_OF_CONTRACT phase: ``lump_sum_fee`` must be omitted (PRD §3.1)."""
    payload: JsonDict = {
        "project_id": project_id,
        "wbs_code": wbs_code,
        "fee_basis": FEE_BASIS_PERCENT_OF_CONTRACT,
        "fee_percent": fee_percent,
        "budget_labor_cost": budget_labor_cost,
        "consultant_budget": consultant_budget,
        "parent_phase_id": parent_phase_id,
    }
    payload.update(overrides)
    return _drop_unset(payload)


def assess_payload(assessed_percent_complete: float) -> JsonDict:
    return {"assessed_percent_complete": assessed_percent_complete}


# ─── Labour rate (PRD §3.2) ───────────────────────────────────────────


def labor_rate_payload(
    role_code: str = ROLE_CODE_PROJECT_ARCHITECT,
    raw_cost_rate: float = 62.50,
    effective_from: str = "2026-01-01",
    effective_to: Any = _UNSET,
    **overrides: Any,
) -> JsonDict:
    """
    A labour rate window. ``effective_to`` is omitted unless supplied, which
    leaves the half-open window open-ended (PRD §3.2).
    """
    payload: JsonDict = {
        "role_code": role_code,
        "raw_cost_rate": raw_cost_rate,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    payload.update(overrides)
    return _drop_unset(payload)


# ─── Billing multiplier (PRD §3.2, §2.7) ──────────────────────────────


def multiplier_payload(
    project_id: str,
    expected_project_version: int,
    multiplier: float = 3.0500,
    effective_from: str = "2026-01-01",
    effective_to: Any = _UNSET,
    **overrides: Any,
) -> JsonDict:
    """
    A billing multiplier. ``expected_project_version`` is non-optional here
    because PRD §2.7 makes multiplier creation optimistically concurrent.
    """
    payload: JsonDict = {
        "project_id": project_id,
        "multiplier": multiplier,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return _drop_unset(payload)


# ─── Time entry (PRD §3.3) ────────────────────────────────────────────


def time_entry_payload(
    project_id: str,
    phase_id: str,
    role_code: str = ROLE_CODE_PROJECT_ARCHITECT,
    work_date: str = "2026-05-11",
    hours: float = 7.35,
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {
        "project_id": project_id,
        "phase_id": phase_id,
        "role_code": role_code,
        "work_date": work_date,
        "hours": hours,
    }
    payload.update(overrides)
    return payload


# ─── Expense (PRD §3.4) ───────────────────────────────────────────────


def expense_payload(
    project_id: str,
    phase_id: str,
    category: str = CATEGORY_PRINTING,
    amount: float = 74.99,
    incurred_on: str = "2026-05-13",
    receipt_attached: bool = False,
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {
        "project_id": project_id,
        "phase_id": phase_id,
        "category": category,
        "amount": amount,
        "incurred_on": incurred_on,
        "receipt_attached": receipt_attached,
    }
    payload.update(overrides)
    return payload


def expense_review_payload(decision: str, justification: str) -> JsonDict:
    return {"decision": decision, "justification": justification}


# ─── Consultant subcontract (PRD §3.5) ────────────────────────────────


def subcontract_payload(
    project_id: str,
    phase_id: str,
    consultant_name: str = "Halcyon MEP",
    committed_amount: float = 20000.00,
    pay_when_paid: bool = False,
    commitment_start: str = "2026-04-01",
    commitment_end: str = "2026-12-31",
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {
        "project_id": project_id,
        "phase_id": phase_id,
        "consultant_name": consultant_name,
        "committed_amount": committed_amount,
        "pay_when_paid": pay_when_paid,
        "commitment_start": commitment_start,
        "commitment_end": commitment_end,
    }
    payload.update(overrides)
    return payload


# ─── Consultant payable (PRD §3.5) ────────────────────────────────────


def consultant_invoice_payload(
    subcontract_id: str,
    amount: float = 20000.00,
    invoice_date: str = "2026-05-20",
    backup_attached: bool = True,
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {
        "subcontract_id": subcontract_id,
        "amount": amount,
        "invoice_date": invoice_date,
        "backup_attached": backup_attached,
    }
    payload.update(overrides)
    return payload


def reject_payload(reason: str) -> JsonDict:
    return {"reason": reason}


# ─── Client invoice (PRD §3.7) ────────────────────────────────────────


def invoice_payload(
    project_id: str,
    expected_project_version: int,
    period_end: str = "2026-05-31",
    **overrides: Any,
) -> JsonDict:
    """
    Invoice preparation. ``expected_project_version`` is non-optional because
    PRD §2.7 makes the sweep optimistically concurrent on the project.
    """
    payload: JsonDict = {
        "project_id": project_id,
        "period_end": period_end,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def invoice_review_payload(decision: str, comment: Any = _UNSET) -> JsonDict:
    """The client's decision; ``comment`` is optional (PRD §3.7)."""
    return _drop_unset({"decision": decision, "comment": comment})


def record_payment_payload(received_on: str) -> JsonDict:
    return {"received_on": received_on}


def void_payload(reason: str) -> JsonDict:
    return {"reason": reason}


# ─── Write-off (PRD §3.8) ─────────────────────────────────────────────


def labor_write_off_payload(
    project_id: str,
    amount: float,
    reason: str = "Stale charge on a cancelled study",
    **overrides: Any,
) -> JsonDict:
    """
    An UNBILLED_LABOR_WIP write-off. ``invoice_id`` is deliberately absent:
    PRD §3.8 requires it to be omitted for this target type.
    """
    payload: JsonDict = {
        "project_id": project_id,
        "target_type": TARGET_UNBILLED_LABOR_WIP,
        "amount": amount,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def receivable_write_off_payload(
    project_id: str,
    invoice_id: str,
    amount: float,
    reason: str = "Client entered receivership; receivable uncollectible",
    **overrides: Any,
) -> JsonDict:
    """An INVOICE_RECEIVABLE write-off, which names the receivable (PRD §3.8)."""
    payload: JsonDict = {
        "project_id": project_id,
        "target_type": TARGET_INVOICE_RECEIVABLE,
        "invoice_id": invoice_id,
        "amount": amount,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


# ─── Overhead rate certification (PRD §3.9) ───────────────────────────


def certification_payload(
    fiscal_year: int = 2026,
    ytd_months: int = 6,
    direct_labor_base: float = 1200000.00,
    indirect_cost_pool: float = 1980000.00,
    unallowable_costs: float = 90000.00,
    **overrides: Any,
) -> JsonDict:
    """
    The canonical certification figures of PRD §3.9: they yield a provisional
    rate of 1.6500, a final rate of 1.5750 and a ceiling of 2.8325.
    """
    payload: JsonDict = {
        "fiscal_year": fiscal_year,
        "ytd_months": ytd_months,
        "direct_labor_base": direct_labor_base,
        "indirect_cost_pool": indirect_cost_pool,
        "unallowable_costs": unallowable_costs,
    }
    payload.update(overrides)
    return payload


def findings_payload(findings: str) -> JsonDict:
    return {"findings": findings}
