"""Payload factories — one per resource, input fields only (per PRD §3)."""


def create_jurisdiction_payload(**overrides) -> dict:
    defaults = {
        "code": "FED-941",
        "name": "IRS Form 941",
        "deposit_frequency": "SEMIWEEKLY",
        "penalty_tier1_rate": 0.02,
        "penalty_tier2_rate": 0.05,
        "penalty_tier3_rate": 0.10,
        "underpayment_threshold_cents": 250000,
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Client Co",
        "ein": "00-0000001",
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(**overrides) -> dict:
    defaults = {
        "jurisdiction_id": None,
        "agency_account_number": "EFTPS-0001",
        "poa_document_ref": "POA-0001",
    }
    defaults.update(overrides)
    return defaults


def create_payroll_run_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "pay_date": "2026-09-04T00:00:00Z",
        "period_start": "2026-08-22T00:00:00Z",
        "period_end": "2026-09-04T00:00:00Z",
        "gross_pay_cents": 1000000,
        "total_tax_cents": 200000,
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(**overrides) -> dict:
    defaults = {
        "jurisdiction_id": None,
        "amount_cents": 100000,
        "expected_payroll_run_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "jurisdiction_id": None,
        "period": "2026-Q3",
        "expected_client_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(**overrides) -> dict:
    defaults = {
        "return_id": None,
        "reason": "Correction after agency review",
        "adjusted_liability_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "jurisdiction_id": None,
        "return_id": None,
        "notice_type": "BALANCE_DUE",
        "claimed_amount_cents": 50000,
        "received_at": "2026-10-10T00:00:00Z",
        "response_due_at": "2026-11-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_wage_statement_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "tax_year": 2026,
        "employee_ref": "E-1",
        "wages_cents": 1000000,
        "withheld_cents": 200000,
    }
    defaults.update(overrides)
    return defaults
