"""Request-payload builders, one per write endpoint of PRD s4.

Each builder emits only the fields the PRD declares for that endpoint, with the
PRD's own defaults left out so the server's defaulting behaviour stays visible.
Every cents field is built as a Python ``int`` and therefore serialised as a JSON
integer, per PRD s2.6.
"""

from typing import Any, Dict, Optional

from .constants import CLOCK_DEFAULT_UTC


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is ``None`` so optional fields are truly omitted."""
    return {key: value for key, value in payload.items() if value is not None}


# --- Logical clock (PRD s2.5) -------------------------------------------
def clock_payload(current_utc: str = CLOCK_DEFAULT_UTC) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# --- Collective (PRD s3.1) ---------------------------------------------
def collective_payload(
    institution_ipeds_code: str,
    name: str = "Test Collective",
    institution_name: str = "Test Institution",
    home_state_code: str = "OH",
    association_ruleset: str = "NCAA_2024",
    entity_structure: Optional[str] = None,
    communication_policy: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "name": name,
        "institution_name": institution_name,
        "institution_ipeds_code": institution_ipeds_code,
        "home_state_code": home_state_code,
        "association_ruleset": association_ruleset,
        "entity_structure": entity_structure,
        "communication_policy": communication_policy,
    }
    payload.update(overrides)
    return _prune(payload)


def entity_structure_payload(
    entity_structure: str, expected_collective_version: Optional[int] = None, **overrides
) -> Dict[str, Any]:
    payload = {
        "entity_structure": entity_structure,
        "expected_collective_version": expected_collective_version,
    }
    payload.update(overrides)
    return _prune(payload)


# --- Membership tier (PRD s3.3) ----------------------------------------
def membership_tier_payload(
    tier_code: str,
    annual_dues_cents: int,
    benefit_rank: int,
    tier_name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "tier_code": tier_code,
        "tier_name": tier_name if tier_name is not None else f"{tier_code} Club",
        "annual_dues_cents": int(annual_dues_cents),
        "benefit_rank": int(benefit_rank),
    }
    payload.update(overrides)
    return _prune(payload)


def tier_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return _prune(payload)


# --- Donor member (PRD s3.3) -------------------------------------------
def donor_member_payload(
    collective_id: str,
    membership_tier_id: str,
    display_name: str = "Test Donor",
    email: str = "donor@example.com",
    donor_kind: Optional[str] = None,
    annual_agi_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "collective_id": collective_id,
        "membership_tier_id": membership_tier_id,
        "display_name": display_name,
        "email": email,
        "donor_kind": donor_kind,
        "annual_agi_cents": None if annual_agi_cents is None else int(annual_agi_cents),
    }
    payload.update(overrides)
    return _prune(payload)


def donor_tax_profile_payload(
    donor_kind: Optional[str] = None,
    annual_agi_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "donor_kind": donor_kind,
        "annual_agi_cents": None if annual_agi_cents is None else int(annual_agi_cents),
    }
    payload.update(overrides)
    return _prune(payload)


# --- Commitment (PRD s3.4) --------------------------------------------
def commitment_payload(
    donor_member_id: str,
    kind: str,
    amount_cents: int,
    billing_interval: str,
    expected_donor_member_version: Optional[int] = None,
    installments_total: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "donor_member_id": donor_member_id,
        "kind": kind,
        "amount_cents": int(amount_cents),
        "billing_interval": billing_interval,
        "installments_total": None if installments_total is None else int(installments_total),
        "expected_donor_member_version": expected_donor_member_version,
    }
    payload.update(overrides)
    return _prune(payload)


def commitment_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return _prune(payload)


def commitment_restructure_payload(
    amount_cents: int, installments_total: Optional[int] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "amount_cents": int(amount_cents),
        "installments_total": None if installments_total is None else int(installments_total),
    }
    payload.update(overrides)
    return _prune(payload)


# --- Contribution (PRD s3.5) ------------------------------------------
def contribution_payload(
    donor_member_id: str,
    gross_amount_cents: int,
    source_kind: str = "ONE_TIME_GIFT",
    commitment_id: Optional[str] = None,
    designation: Optional[str] = None,
    processor_outcome: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "donor_member_id": donor_member_id,
        "gross_amount_cents": int(gross_amount_cents),
        "source_kind": source_kind,
        "commitment_id": commitment_id,
        "designation": designation,
        "processor_outcome": processor_outcome,
    }
    payload.update(overrides)
    return _prune(payload)


def settlement_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return _prune(payload)


# --- Billing run (PRD s3.6) -------------------------------------------
def billing_run_payload(run_kind: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"run_kind": run_kind}
    payload.update(overrides)
    return _prune(payload)


# --- Athlete (PRD s3.7) -----------------------------------------------
def athlete_payload(
    collective_id: str,
    portal_user_id: str,
    full_name: str = "Test Athlete",
    sport: str = "FOOTBALL",
    class_year: int = 2028,
    roster_weight: Optional[int] = None,
    tax_person_kind: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "collective_id": collective_id,
        "full_name": full_name,
        "portal_user_id": portal_user_id,
        "sport": sport,
        "class_year": None if class_year is None else int(class_year),
        "roster_weight": None if roster_weight is None else int(roster_weight),
        "tax_person_kind": tax_person_kind,
    }
    payload.update(overrides)
    return _prune(payload)


def eligibility_change_payload(change: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"change": change}
    payload.update(overrides)
    return _prune(payload)


def athlete_tax_profile_payload(
    taxpayer_doc_on_file: str,
    treaty_exempt_claimed: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "taxpayer_doc_on_file": taxpayer_doc_on_file,
        "treaty_exempt_claimed": treaty_exempt_claimed,
    }
    payload.update(overrides)
    return _prune(payload)


# --- Deal contract (PRD s3.8) -----------------------------------------
def deal_contract_payload(
    collective_id: str,
    athlete_id: str,
    total_value_cents: int,
    effective_start_at: str = "2026-08-01T00:00:00Z",
    effective_end_at: str = "2026-12-31T00:00:00Z",
    funding_designation: Optional[str] = None,
    exclusivity_category: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "collective_id": collective_id,
        "athlete_id": athlete_id,
        "total_value_cents": int(total_value_cents),
        "effective_start_at": effective_start_at,
        "effective_end_at": effective_end_at,
        "funding_designation": funding_designation,
        "exclusivity_category": exclusivity_category,
    }
    payload.update(overrides)
    return _prune(payload)


def roster_allocation_payload(
    collective_id: str,
    allocation_batch_code: str,
    sport: str,
    pool_amount_cents: int,
    allocation_mode: str,
    effective_start_at: str,
    effective_end_at: str,
    expected_collective_version: Optional[int] = None,
    funding_designation: Optional[str] = None,
    exclusivity_category: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "collective_id": collective_id,
        "allocation_batch_code": allocation_batch_code,
        "sport": sport,
        "pool_amount_cents": int(pool_amount_cents),
        "allocation_mode": allocation_mode,
        "effective_start_at": effective_start_at,
        "effective_end_at": effective_end_at,
        "expected_collective_version": expected_collective_version,
        "funding_designation": funding_designation,
        "exclusivity_category": exclusivity_category,
    }
    payload.update(overrides)
    return _prune(payload)


def compliance_submission_payload(
    state_law_citation: Optional[str] = None,
    association_rule_citation: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "state_law_citation": state_law_citation,
        "association_rule_citation": association_rule_citation,
    }
    payload.update(overrides)
    return _prune(payload)


def compliance_decision_payload(
    decision: str, reviewer_note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = {"decision": decision, "reviewer_note": reviewer_note}
    payload.update(overrides)
    return _prune(payload)


def termination_payload(termination_reason: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"termination_reason": termination_reason}
    payload.update(overrides)
    return _prune(payload)


# --- Deliverables (PRD s3.9) ------------------------------------------
def deliverable_payload(
    deliverable_kind: str,
    unit_value_cents: int,
    due_at: str,
    required_charity_hours_tenths: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "deliverable_kind": deliverable_kind,
        "unit_value_cents": int(unit_value_cents),
        "due_at": due_at,
        "required_charity_hours_tenths": (
            None
            if required_charity_hours_tenths is None
            else int(required_charity_hours_tenths)
        ),
    }
    payload.update(overrides)
    return _prune(payload)


def evidence_payload(
    evidence_kind: str, reference_label: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {"evidence_kind": evidence_kind, "reference_label": reference_label}
    payload.update(overrides)
    return _prune(payload)


def submission_payload(
    performed_at: str,
    charity_hours_tenths: Optional[int] = None,
    submission_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "performed_at": performed_at,
        "charity_hours_tenths": (
            None if charity_hours_tenths is None else int(charity_hours_tenths)
        ),
        "submission_note": submission_note,
    }
    payload.update(overrides)
    return _prune(payload)


def review_payload(
    decision: str, review_note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = {"decision": decision, "review_note": review_note}
    payload.update(overrides)
    return _prune(payload)


# --- Payment releases (PRD s3.9) --------------------------------------
def payment_release_payload(
    deal_contract_id: str,
    release_kind: str,
    requested_amount_cents: int,
    expected_deal_contract_version: Optional[int] = None,
    deliverable_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "deal_contract_id": deal_contract_id,
        "release_kind": release_kind,
        "requested_amount_cents": int(requested_amount_cents),
        "expected_deal_contract_version": expected_deal_contract_version,
        "deliverable_id": deliverable_id,
    }
    payload.update(overrides)
    return _prune(payload)


def reversal_payload(reversal_reason: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reversal_reason": reversal_reason}
    payload.update(overrides)
    return _prune(payload)


# --- Communication logs (PRD s3.1) ------------------------------------
def communication_log_payload(
    collective_id: str,
    actor_role: str,
    channel: str,
    topic: str,
    athlete_id: Optional[str] = None,
    note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "collective_id": collective_id,
        "actor_role": actor_role,
        "channel": channel,
        "topic": topic,
        "athlete_id": athlete_id,
        "note": note,
    }
    payload.update(overrides)
    return _prune(payload)
