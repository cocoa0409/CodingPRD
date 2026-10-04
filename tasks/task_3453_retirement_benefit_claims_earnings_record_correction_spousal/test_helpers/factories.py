"""Payload factories — one per creatable entity, input fields only (PRD §3)."""

DEFAULTS = {
    "WORKER_FULL_NAME": "Test Worker",
    "WORKER_BIRTH_YEAR": 1964,
    "WORKER_BIRTH_MONTH": 6,
    "EMPLOYER_NAME": "Acme Corp",
    "EVIDENCE_TYPE": "WAGE_STATEMENT",
    "ENTITLEMENT_MONTH": "2026-06",
    "MARRIAGE_DATE": "2000-01-01",
    "OVERPAYMENT_REASON": "REPORTING_ERROR",
    "PAYEE_NAME": "Pat Payee",
    "DETERMINATION_BASIS": "physician letter: cannot manage funds",
}


def create_worker_payload(**overrides) -> dict:
    """Worker intake: full_name, birth_year, birth_month; optional pension fields
    (PRD §3.1). Pension fields are omitted entirely unless overridden."""
    defaults = {
        "full_name": DEFAULTS["WORKER_FULL_NAME"],
        "birth_year": DEFAULTS["WORKER_BIRTH_YEAR"],
        "birth_month": DEFAULTS["WORKER_BIRTH_MONTH"],
    }
    defaults.update(overrides)
    return defaults


def create_wage_report_payload(worker_id, tax_year, amount_cents, **overrides) -> dict:
    """Wage report: worker_id, employer_name, tax_year, amount_cents; optional
    covered_employment defaults server-side to true (PRD §3.1)."""
    defaults = {
        "worker_id": worker_id,
        "employer_name": DEFAULTS["EMPLOYER_NAME"],
        "tax_year": tax_year,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_correction_request_payload(worker_id, tax_year, claimed_earnings_cents, **overrides) -> dict:
    """Correction request: worker_id, tax_year, claimed_earnings_cents,
    evidence_type (PRD §3.2)."""
    defaults = {
        "worker_id": worker_id,
        "tax_year": tax_year,
        "claimed_earnings_cents": claimed_earnings_cents,
        "evidence_type": DEFAULTS["EVIDENCE_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_relationship_payload(worker_id, spouse_worker_id, relationship_type,
                                marriage_date, **overrides) -> dict:
    """Relationship assertion: covered worker_id, spouse_worker_id,
    relationship_type, marriage_date; divorce_date only when overridden
    (PRD §3.3)."""
    defaults = {
        "worker_id": worker_id,
        "spouse_worker_id": spouse_worker_id,
        "relationship_type": relationship_type,
        "marriage_date": marriage_date,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(worker_id, claim_type, entitlement_month, **overrides) -> dict:
    """Claim filing: worker_id, claim_type, entitlement_month; relationship_id
    only via override (required for auxiliary types, forbidden for RETIREMENT —
    PRD §3.4)."""
    defaults = {
        "worker_id": worker_id,
        "claim_type": claim_type,
        "entitlement_month": entitlement_month,
    }
    defaults.update(overrides)
    return defaults


def create_overpayment_case_payload(claim_id, amount_cents, period_start_month,
                                    period_end_month, **overrides) -> dict:
    """Overpayment case: claim_id, amount_cents, period bounds, reason (PRD §3.8)."""
    defaults = {
        "claim_id": claim_id,
        "amount_cents": amount_cents,
        "period_start_month": period_start_month,
        "period_end_month": period_end_month,
        "reason": DEFAULTS["OVERPAYMENT_REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_payee_case_payload(claim_id, **overrides) -> dict:
    """Payee determination: claim_id, payee_name, determination_basis (PRD §3.9)."""
    defaults = {
        "claim_id": claim_id,
        "payee_name": DEFAULTS["PAYEE_NAME"],
        "determination_basis": DEFAULTS["DETERMINATION_BASIS"],
    }
    defaults.update(overrides)
    return defaults
