"""Payload factories: one per entity, input fields only.

Defaults are drawn from the PRD's stated defaults for optional input fields
(PRD sections 3.1, 3.3, 3.4, 3.6, 3.7).
"""


def create_homeowner_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Household",
        "email": "test.household@example.com",
        "credit_score": 700,
        "household_income_cents": 30_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(homeowner_id: str, **overrides) -> dict:
    defaults = {
        "homeowner_id": homeowner_id,
        "address": "1 Test Way",
        "kind": "DEPARTING",
        "appraised_value_cents": 70_000_000,
        "mortgage_payoff_cents": 30_000_000,
        "condition_grade": "B",
    }
    defaults.update(overrides)
    return defaults


def create_qualification_payload(homeowner_id: str, departing_property_id: str,
                                 new_property_id: str, **overrides) -> dict:
    defaults = {
        "homeowner_id": homeowner_id,
        "departing_property_id": departing_property_id,
        "new_property_id": new_property_id,
        "target_purchase_price_cents": 30_000_000,
        "variant_used": "CONSERVATIVE",
    }
    defaults.update(overrides)
    return defaults


def create_bridge_program_payload(homeowner_id: str, qualification_id: str,
                                  new_property_id: str, departing_property_id: str,
                                  **overrides) -> dict:
    defaults = {
        "homeowner_id": homeowner_id,
        "qualification_id": qualification_id,
        "new_property_id": new_property_id,
        "departing_property_id": departing_property_id,
        "projected_carry_months": 4,
    }
    defaults.update(overrides)
    return defaults


def create_fund_payload(expected_bridge_program_version: int, **overrides) -> dict:
    defaults = {
        "expected_bridge_program_version": expected_bridge_program_version,
        "interest_rate_bps": 800,
    }
    defaults.update(overrides)
    return defaults


def create_interim_loan_payload(bridge_program_id: str, **overrides) -> dict:
    defaults = {
        "bridge_program_id": bridge_program_id,
        "principal_cents": 30_000_000,
        "interest_rate_bps": 800,
    }
    defaults.update(overrides)
    return defaults


def create_bridge_advance_payload(bridge_program_id: str, interim_loan_id: str,
                                  **overrides) -> dict:
    defaults = {
        "bridge_program_id": bridge_program_id,
        "interim_loan_id": interim_loan_id,
        "purpose": "DOWN_PAYMENT",
        "amount_cents": 8_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_carrying_cost_payload(bridge_program_id: str, **overrides) -> dict:
    defaults = {
        "bridge_program_id": bridge_program_id,
        "kind": "DEPARTING_TAX",
        "amount_cents": 500_000,
        "due_date": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_repair_advance_payload(property_id: str, bridge_program_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "bridge_program_id": bridge_program_id,
        "scope": "Pre-listing repair scope",
        "approved_amount_cents": 3_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_backup_offer_payload(departing_property_id: str, bridge_program_id: str,
                                **overrides) -> dict:
    defaults = {
        "departing_property_id": departing_property_id,
        "bridge_program_id": bridge_program_id,
        "offer_price_cents": 44_000_000,
        "window_days": 30,
        "window_start": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(departing_property_id: str, bridge_program_id: str,
                           **overrides) -> dict:
    defaults = {
        "departing_property_id": departing_property_id,
        "bridge_program_id": bridge_program_id,
        "list_price_cents": 44_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Agent",
        "brokerage_name": "Test Brokerage",
        "license_number": "LIC-TEST-1",
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(agent_id: str, bridge_program_id: str, **overrides) -> dict:
    defaults = {
        "agent_id": agent_id,
        "bridge_program_id": bridge_program_id,
        "role_scope": "DEPARTING_SIDE",
    }
    defaults.update(overrides)
    return defaults


def create_coordination_task_payload(bridge_program_id: str, referral_id: str,
                                     **overrides) -> dict:
    defaults = {
        "bridge_program_id": bridge_program_id,
        "referral_id": referral_id,
        "task_kind": "PHOTOGRAPHY",
        "due_date": "2026-09-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(bridge_program_id: str, **overrides) -> dict:
    defaults = {
        "bridge_program_id": bridge_program_id,
        "source_kind": "RESALE",
        "amount_cents": 3_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_repayment_payload(expected_interim_loan_version: int, **overrides) -> dict:
    defaults = {
        "amount_cents": 1_000_000,
        "expected_interim_loan_version": expected_interim_loan_version,
    }
    defaults.update(overrides)
    return defaults