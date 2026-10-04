"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Test Borrower",
    "BUSINESS_NAME": "Test Business",
    "TENURE_MONTHS": 24,
    "PRIOR_REPAID": 1,
    "LENDER_NAME": "Test Lender",
    "ORG_NAME": "Test Trust",
    "TRUSTEE_LIMIT": 10_000_000,
    "REQUESTED_AMOUNT": 100_000,
    "TERM_MONTHS": 3,
    "BUSINESS_PURPOSE": "Working capital",
    "ENDORSEMENT_AMOUNT": 25_000,
    "CONTRIBUTION_AMOUNT": 25_000,
    "DEPOSIT_AMOUNT": 500_000,
}

_email_counter = {"n": 0}


def _unique_email(prefix: str) -> str:
    _email_counter["n"] += 1
    return f"{prefix}-{_email_counter['n']}@example.com"


def create_borrower_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "business_name": DEFAULTS["BUSINESS_NAME"],
        "email": _unique_email("borrower"),
        "business_tenure_months": DEFAULTS["TENURE_MONTHS"],
        "prior_repaid_loans_count": DEFAULTS["PRIOR_REPAID"],
    }
    defaults.update(overrides)
    return defaults


def create_lender_payload(**overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["LENDER_NAME"],
        "email": _unique_email("lender"),
    }
    defaults.update(overrides)
    return defaults


def create_trustee_payload(**overrides) -> dict:
    defaults = {
        "org_name": DEFAULTS["ORG_NAME"],
        "endorsement_limit_cents": DEFAULTS["TRUSTEE_LIMIT"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(borrower_id, **overrides) -> dict:
    defaults = {
        "borrower_id": borrower_id,
        "requested_amount_cents": DEFAULTS["REQUESTED_AMOUNT"],
        "term_months": DEFAULTS["TERM_MONTHS"],
        "business_purpose": DEFAULTS["BUSINESS_PURPOSE"],
    }
    defaults.update(overrides)
    return defaults


def create_invite_payload(**overrides) -> dict:
    defaults = {"invitee_email": _unique_email("invitee")}
    defaults.update(overrides)
    return defaults


def create_deposit_payload(**overrides) -> dict:
    defaults = {"amount_cents": DEFAULTS["DEPOSIT_AMOUNT"]}
    defaults.update(overrides)
    return defaults


def create_endorsement_payload(lender_id, **overrides) -> dict:
    defaults = {
        "lender_id": lender_id,
        "amount_cents": DEFAULTS["ENDORSEMENT_AMOUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_contribution_payload(lender_id, **overrides) -> dict:
    defaults = {
        "lender_id": lender_id,
        "amount_cents": DEFAULTS["CONTRIBUTION_AMOUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_trustee_endorsement_payload(application_id, **overrides) -> dict:
    defaults = {
        "loan_application_id": application_id,
        "amount_cents": DEFAULTS["ENDORSEMENT_AMOUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 100}
    defaults.update(overrides)
    return defaults


def create_impact_report_payload(**overrides) -> dict:
    defaults = {
        "months_after_disbursement": 1,
        "revenue_change_pct": 10,
        "jobs_created": 1,
        "narrative": "Progress update",
    }
    defaults.update(overrides)
    return defaults
