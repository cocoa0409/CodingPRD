"""Payload factories — one per request body, input fields only.

Defaults are drawn from the canonical world used across the design recipes:
a POPULATION-basis settlement of 100,000,000 cents total with a
10,000,000-cent restitution reserve and three injunctive terms.
"""
from .constants import (
    CANONICAL_INJUNCTIVE_TERMS,
    CANONICAL_RESERVE_CENTS,
    CANONICAL_TOTAL_CENTS,
    CLOCK_DEFAULT,
)


def create_state_office_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "population": 100,
        "harm_measure_cents": 50,
        "appropriation_rule": "PREAPPROPRIATED",
    }
    defaults.update(overrides)
    return defaults


def patch_state_office_payload(expected_state_office_version, **overrides) -> dict:
    defaults = {"expected_state_office_version": expected_state_office_version}
    defaults.update(overrides)
    return defaults


def create_investigation_payload(**overrides) -> dict:
    defaults = {
        "title": "Pricing probe",
        "target_name": "Acme Corp",
        "summary": "Coordinated probe",
    }
    defaults.update(overrides)
    return defaults


def advance_payload(to_phase, **overrides) -> dict:
    defaults = {"to_phase": to_phase}
    defaults.update(overrides)
    return defaults


def create_participation_payload(state_office_id, **overrides) -> dict:
    defaults = {"state_office_id": state_office_id}
    defaults.update(overrides)
    return defaults


def execute_cia_payload(**overrides) -> dict:
    defaults = {"confidentiality_tier": "STANDARD"}
    defaults.update(overrides)
    return defaults


def create_demand_payload(**overrides) -> dict:
    defaults = {"scope_text": "Pricing documents"}
    defaults.update(overrides)
    return defaults


def create_response_payload(demand_ids, **overrides) -> dict:
    defaults = {
        "demand_ids": list(demand_ids),
        "coverage_summary": "Consolidated production",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(**overrides) -> dict:
    defaults = {
        "monetary_total_cents": CANONICAL_TOTAL_CENTS,
        "restitution_reserve_cents": CANONICAL_RESERVE_CENTS,
        "allocation_basis": "POPULATION",
        "injunctive_terms": list(CANONICAL_INJUNCTIVE_TERMS),
    }
    defaults.update(overrides)
    return defaults


def counter_settlement_payload(expected_settlement_version, **overrides) -> dict:
    defaults = {"expected_settlement_version": expected_settlement_version}
    defaults.update(overrides)
    return defaults


def revise_settlement_payload(expected_settlement_version, **overrides) -> dict:
    defaults = {"expected_settlement_version": expected_settlement_version}
    defaults.update(overrides)
    return defaults


def sign_on_payload(decision="SIGNED", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def deposit_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(**overrides) -> dict:
    defaults = {"amount_cents": 1000, "use_code": "PROGRAM"}
    defaults.update(overrides)
    return defaults


def create_claimant_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "contact_ref": "ref-k1",
        "claimed_loss_cents": 6000000,
    }
    defaults.update(overrides)
    return defaults


def validate_claimant_payload(decision="VALIDATED", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_finding_payload(term_index=0, outcome="COMPLIANT", **overrides) -> dict:
    defaults = {"term_index": term_index, "outcome": outcome}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601=CLOCK_DEFAULT, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
