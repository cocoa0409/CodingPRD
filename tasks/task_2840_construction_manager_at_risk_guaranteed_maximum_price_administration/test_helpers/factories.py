"""Request-payload builders for the CMAR guaranteed-maximum-price API.

Each builder produces the payload one endpoint accepts, with sensible defaults
that satisfy every field-level rule, and accepts keyword overrides so a test can
vary exactly the one field it is exercising. Money, ratios, quantities and unit
rates are always emitted as JSON *numbers*, never as strings, because that is
what the field definitions describe.
"""

from decimal import Decimal
from itertools import count
from typing import Any, Dict, Optional

from .constants import (
    CLOCK_START,
    SOLICITATION_CLOSE,
    STD_CONSTRUCTION_CONTINGENCY,
    STD_COST_OF_WORK,
    STD_GENERAL_CONDITIONS,
    STD_OWNER_CONTINGENCY,
)
from .types import Numeric, Payload

_SEQUENCE = count(1)


def next_sequence() -> int:
    """A process-unique counter, used to keep generated labels distinguishable."""
    return next(_SEQUENCE)


def num(value: Optional[Numeric]) -> Optional[float]:
    """Render a decimal quantity as the JSON number the API expects."""
    if value is None:
        return None
    if isinstance(value, bool):  # pragma: no cover - guards a programming error
        raise TypeError("boolean is not a numeric field value")
    if isinstance(value, int):
        return value
    return float(Decimal(str(value)))


def _compact(payload: Dict[str, Any]) -> Payload:
    """Drop keys whose value is ``None`` so optional fields are truly omitted."""
    return {key: value for key, value in payload.items() if value is not None}


def _finish(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Payload:
    """Apply overrides after compaction so a test may force a null or extra key."""
    result = _compact(payload)
    result.update(overrides)
    return result


# --- logical clock ---------------------------------------------------------


def clock_payload(current_utc: str = CLOCK_START, **overrides: Any) -> Payload:
    return _finish({"current_utc": current_utc}, overrides)


# --- projects --------------------------------------------------------------


def project_payload(
    name: Optional[str] = None,
    owner_org: str = "Harborview County Owner Authority",
    cm_fee_pct: Numeric = Decimal("0.04"),
    insurance_rate: Numeric = Decimal("0.01"),
    precon_fee_amount: Optional[Numeric] = None,
    **overrides: Any,
) -> Payload:
    """A CMAR project registration with its two contractual rates."""
    return _finish(
        {
            "name": name or f"Harborview Program Project {next_sequence()}",
            "owner_org": owner_org,
            "cm_fee_pct": num(cm_fee_pct),
            "insurance_rate": num(insurance_rate),
            "precon_fee_amount": num(precon_fee_amount),
        },
        overrides,
    )


def audit_request_payload(
    audit_scope_note: Optional[str] = None, **overrides: Any
) -> Payload:
    return _finish({"audit_scope_note": audit_scope_note}, overrides)


def audit_action_payload(
    action: str = "CLOSE",
    adjustment_amount: Optional[Numeric] = None,
    adjustment_note: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    return _finish(
        {
            "action": action,
            "adjustment_amount": num(adjustment_amount),
            "adjustment_note": adjustment_note,
        },
        overrides,
    )


def shared_savings_payload(
    basis: str = "PRE_AUDIT_PROVISIONAL", execute: bool = False, **overrides: Any
) -> Payload:
    return _finish({"basis": basis, "execute": execute}, overrides)


# --- progressive estimates -------------------------------------------------


def estimate_payload(
    project_id: str,
    expected_project_version: int,
    milestone_code: str = "SD",
    submitted_cost_of_work: Numeric = STD_COST_OF_WORK,
    prior_estimate_id: Optional[str] = None,
    justification_note: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    """A progressive estimate priced at one design milestone."""
    return _finish(
        {
            "project_id": project_id,
            "milestone_code": milestone_code,
            "submitted_cost_of_work": num(submitted_cost_of_work),
            "expected_project_version": expected_project_version,
            "prior_estimate_id": prior_estimate_id,
            "justification_note": justification_note,
        },
        overrides,
    )


def estimate_submit_payload(
    justification_note: Optional[str] = None, **overrides: Any
) -> Payload:
    return _finish({"justification_note": justification_note}, overrides)


def estimate_reconcile_payload(
    decision: str = "ACCEPT",
    reconciliation_note: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    return _finish(
        {"decision": decision, "reconciliation_note": reconciliation_note}, overrides
    )


# --- guaranteed-maximum-price proposals ------------------------------------


def gmp_proposal_payload(
    project_id: str,
    based_on_estimate_id: str,
    expected_project_version: int,
    cost_of_work_total: Numeric = STD_COST_OF_WORK,
    general_conditions_total: Numeric = STD_GENERAL_CONDITIONS,
    owner_contingency_amount: Numeric = STD_OWNER_CONTINGENCY,
    construction_contingency_amount: Numeric = STD_CONSTRUCTION_CONTINGENCY,
    **overrides: Any,
) -> Payload:
    """A base proposal carrying the four money components the build-up prices."""
    return _finish(
        {
            "project_id": project_id,
            "based_on_estimate_id": based_on_estimate_id,
            "cost_of_work_total": num(cost_of_work_total),
            "general_conditions_total": num(general_conditions_total),
            "owner_contingency_amount": num(owner_contingency_amount),
            "construction_contingency_amount": num(construction_contingency_amount),
            "expected_project_version": expected_project_version,
        },
        overrides,
    )


def proposal_submit_payload(cover_note: Optional[str] = None, **overrides: Any) -> Payload:
    return _finish({"cover_note": cover_note}, overrides)


def proposal_decision_payload(
    decision: str = "EXECUTE",
    owner_decision_note: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    return _finish(
        {"decision": decision, "owner_decision_note": owner_decision_note}, overrides
    )


# --- qualification log -----------------------------------------------------


def qualification_item_payload(
    gmp_proposal_id: str,
    item_type: str = "ASSUMPTION",
    text: str = "Unit masonry priced from the 60% construction documents.",
    **overrides: Any,
) -> Payload:
    """A non-allowance qualification entry; the allowance ledger fields stay absent."""
    return _finish(
        {"gmp_proposal_id": gmp_proposal_id, "item_type": item_type, "text": text},
        overrides,
    )


def allowance_item_payload(
    gmp_proposal_id: str,
    allowance_amount: Numeric = Decimal("75000.00"),
    allocated_units: Numeric = Decimal("1500.00"),
    unit_of_measure: str = "SF",
    text: str = "Decorative stone veneer allowance carried at the exhibit rate.",
    **overrides: Any,
) -> Payload:
    """An allowance entry carrying dollars, a quantity and its unit label."""
    return _finish(
        {
            "gmp_proposal_id": gmp_proposal_id,
            "item_type": "ALLOWANCE",
            "text": text,
            "allowance_amount": num(allowance_amount),
            "allocated_units": num(allocated_units),
            "unit_of_measure": unit_of_measure,
        },
        overrides,
    )


def allowance_reconcile_payload(
    units: Numeric,
    actual_unit_cost: Numeric,
    overrun_authorized: Optional[bool] = None,
    **overrides: Any,
) -> Payload:
    return _finish(
        {
            "action": "RECONCILE",
            "units": num(units),
            "actual_unit_cost": num(actual_unit_cost),
            "overrun_authorized": overrun_authorized,
        },
        overrides,
    )


def allowance_reverse_payload(**overrides: Any) -> Payload:
    return _finish({"action": "REVERSE"}, overrides)


# --- work packages ---------------------------------------------------------


def work_package_payload(
    project_id: str,
    trade_division: Optional[str] = None,
    budget_amount: Numeric = Decimal("500000.00"),
    self_perform_intent: Optional[bool] = None,
    **overrides: Any,
) -> Payload:
    """A budgeted trade package carried inside the cost of work."""
    return _finish(
        {
            "project_id": project_id,
            "trade_division": trade_division or f"03-CONCRETE-{next_sequence()}",
            "budget_amount": num(budget_amount),
            "self_perform_intent": self_perform_intent,
        },
        overrides,
    )


def solicit_payload(
    solicitation_opens_at: str = CLOCK_START,
    solicitation_closes_at: str = SOLICITATION_CLOSE,
    **overrides: Any,
) -> Payload:
    return _finish(
        {
            "solicitation_opens_at": solicitation_opens_at,
            "solicitation_closes_at": solicitation_closes_at,
        },
        overrides,
    )


def transparency_payload(
    target_status: str = "DISCLOSED",
    disclosure_note: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    return _finish(
        {"target_status": target_status, "disclosure_note": disclosure_note}, overrides
    )


def award_payload(
    bid_id: str, award_note: Optional[str] = None, **overrides: Any
) -> Payload:
    return _finish({"bid_id": bid_id, "award_note": award_note}, overrides)


# --- sealed bids -----------------------------------------------------------


def open_book_breakdown(
    labor: Numeric,
    material: Numeric,
    equipment: Numeric,
    overhead: Numeric,
    profit: Numeric,
) -> Payload:
    """The five-component open-book cost breakdown."""
    return {
        "labor": num(labor),
        "material": num(material),
        "equipment": num(equipment),
        "overhead": num(overhead),
        "profit": num(profit),
    }


def breakdown_summing_to(base_bid_amount: Numeric) -> Payload:
    """A breakdown whose five components sum exactly to ``base_bid_amount``."""
    total = Decimal(str(base_bid_amount))
    labor = (total / 2).quantize(Decimal("0.01"))
    material = (total / 4).quantize(Decimal("0.01"))
    equipment = (total / 10).quantize(Decimal("0.01"))
    overhead = (total / 20).quantize(Decimal("0.01"))
    profit = total - labor - material - equipment - overhead
    return open_book_breakdown(labor, material, equipment, overhead, profit)


def self_perform_bid_payload(
    work_package_id: str,
    base_bid_amount: Numeric = Decimal("460000.00"),
    bidder_name: str = "CM Self-Perform Concrete Division",
    open_book_cost_breakdown: Optional[Payload] = None,
    **overrides: Any,
) -> Payload:
    """A sealed bid from the construction manager's own forces."""
    breakdown = (
        open_book_cost_breakdown
        if open_book_cost_breakdown is not None
        else breakdown_summing_to(base_bid_amount)
    )
    return _finish(
        {
            "work_package_id": work_package_id,
            "bidder_type": "CM_SELF_PERFORM",
            "bidder_name": bidder_name,
            "base_bid_amount": num(base_bid_amount),
            "open_book_cost_breakdown": breakdown,
        },
        overrides,
    )


def third_party_bid_payload(
    work_package_id: str,
    base_bid_amount: Numeric = Decimal("460000.00"),
    bidder_name: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    """A sealed bid from the open market, whose breakdown must be null."""
    payload = {
        "work_package_id": work_package_id,
        "bidder_type": "THIRD_PARTY",
        "bidder_name": bidder_name or f"Open Market Trade Contractor {next_sequence()}",
        "base_bid_amount": num(base_bid_amount),
        "open_book_cost_breakdown": None,
    }
    payload.update(overrides)
    return payload


def open_bid_payload(open_note: Optional[str] = None, **overrides: Any) -> Payload:
    return _finish({"open_note": open_note}, overrides)


# --- subcontracts ----------------------------------------------------------


def subcontract_payload(
    work_package_id: str,
    awarded_bid_id: str,
    expected_work_package_version: int,
    contract_amount: Numeric = Decimal("460000.00"),
    performance_start: str = "2026-09-01T00:00:00Z",
    performance_end: str = "2026-11-30T00:00:00Z",
    subcontractor_name: Optional[str] = None,
    bond_required: Optional[bool] = None,
    bond_amount: Optional[Numeric] = None,
    **overrides: Any,
) -> Payload:
    """A subcontract executed against an awarded package and its winning bid."""
    return _finish(
        {
            "work_package_id": work_package_id,
            "awarded_bid_id": awarded_bid_id,
            "subcontractor_name": subcontractor_name
            or f"Trade Subcontractor {next_sequence()}",
            "contract_amount": num(contract_amount),
            "performance_start": performance_start,
            "performance_end": performance_end,
            "bond_required": bond_required,
            "bond_amount": num(bond_amount),
            "expected_work_package_version": expected_work_package_version,
        },
        overrides,
    )


def progress_payment_payload(payment_amount: Numeric, **overrides: Any) -> Payload:
    return _finish({"payment_amount": num(payment_amount)}, overrides)


def status_action_payload(
    action: str,
    default_reason: Optional[str] = None,
    cure_note: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    return _finish(
        {"action": action, "default_reason": default_reason, "cure_note": cure_note},
        overrides,
    )


def bond_claim_payload(
    action: str,
    claim_amount: Optional[Numeric] = None,
    recovered_amount: Optional[Numeric] = None,
    denial_reason: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    return _finish(
        {
            "action": action,
            "claim_amount": num(claim_amount),
            "recovered_amount": num(recovered_amount),
            "denial_reason": denial_reason,
        },
        overrides,
    )


# --- change events ---------------------------------------------------------


def change_event_payload(
    project_id: str,
    estimated_amount: Numeric = Decimal("30000.00"),
    origin: str = "FIELD_CONDITION",
    description: Optional[str] = None,
    qualification_item_id: Optional[str] = None,
    source_subcontract_id: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    """A logged cost impact awaiting its cost-responsibility determination."""
    return _finish(
        {
            "project_id": project_id,
            "description": description
            or f"Unforeseen field condition at grid line {next_sequence()}.",
            "estimated_amount": num(estimated_amount),
            "origin": origin,
            "qualification_item_id": qualification_item_id,
            "source_subcontract_id": source_subcontract_id,
        },
        overrides,
    )


def change_event_submit_payload(
    submit_note: Optional[str] = None, **overrides: Any
) -> Payload:
    return _finish({"submit_note": submit_note}, overrides)


def change_event_review_payload(
    action: str, review_note: Optional[str] = None, **overrides: Any
) -> Payload:
    return _finish({"action": action, "review_note": review_note}, overrides)


def classify_payload(
    classification: str, classification_note: Optional[str] = None, **overrides: Any
) -> Payload:
    return _finish(
        {"classification": classification, "classification_note": classification_note},
        overrides,
    )


# --- contingency draws -----------------------------------------------------


def draw_approve_payload(
    approve: bool = True, approval_note: Optional[str] = None, **overrides: Any
) -> Payload:
    return _finish({"approve": approve, "approval_note": approval_note}, overrides)


def draw_post_payload(post_note: Optional[str] = None, **overrides: Any) -> Payload:
    return _finish({"post_note": post_note}, overrides)


def draw_void_payload(
    void_reason: str = "Owner directive withdrawn before the work was released.",
    **overrides: Any,
) -> Payload:
    return _finish({"void_reason": void_reason}, overrides)


# --- monthly cost reports --------------------------------------------------


def cost_report_payload(
    project_id: str,
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-09-01T00:00:00Z",
    **overrides: Any,
) -> Payload:
    """A monthly report over the half-open period [period_start, period_end)."""
    return _finish(
        {
            "project_id": project_id,
            "period_start": period_start,
            "period_end": period_end,
        },
        overrides,
    )


def cost_line_payload(
    quantity: Numeric = Decimal("100.0000"),
    unit_rate: Numeric = Decimal("200.0000"),
    markup_pct: Numeric = Decimal("0.0000"),
    cost_code: Optional[str] = None,
    work_package_id: Optional[str] = None,
    qualification_item_id: Optional[str] = None,
    disputed: Optional[bool] = None,
    **overrides: Any,
) -> Payload:
    """An open-book cost line, extended and rounded before it enters any total."""
    return _finish(
        {
            "cost_code": cost_code or f"03-3000-{next_sequence()}",
            "quantity": num(quantity),
            "unit_rate": num(unit_rate),
            "markup_pct": num(markup_pct),
            "work_package_id": work_package_id,
            "qualification_item_id": qualification_item_id,
            "disputed": disputed,
        },
        overrides,
    )


def cost_report_reconcile_payload(
    decision: str = "RECONCILE",
    reconciliation_note: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    return _finish(
        {"decision": decision, "reconciliation_note": reconciliation_note}, overrides
    )


def release_hold_payload(release_note: Optional[str] = None, **overrides: Any) -> Payload:
    return _finish({"release_note": release_note}, overrides)
