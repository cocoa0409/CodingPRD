"""Payload factories — one per writable resource, input fields only."""
import itertools

from .constants import DEFAULT_CLOSING_DATE, DEFAULT_EFFECTIVE_FROM, DEFAULT_LOAN_AMOUNT_CENTS

_org_seq = itertools.count(1000000)
_name_seq = itertools.count(1)


def next_org_id() -> str:
    """Seven-digit organizational identifier, unique per process."""
    return str(next(_org_seq))


def create_member_payload(**overrides) -> dict:
    n = next(_name_seq)
    defaults = {
        "legal_name": f"Member Org {n}",
        "org_id": next_org_id(),
        "org_id_type": "TAX_ID",
        "member_type": "SERVICER",
    }
    defaults.update(overrides)
    return defaults


def create_signer_payload(**overrides) -> dict:
    n = next(_name_seq)
    defaults = {
        "full_name": f"Signer {n}",
        "email": f"signer{n}@example.com",
        "effective_from": DEFAULT_EFFECTIVE_FROM,
        "role_scope": "ALL",
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(**overrides) -> dict:
    defaults = {
        "loan_amount_cents": DEFAULT_LOAN_AMOUNT_CENTS,
        "property_state": "TX",
        "closing_date": DEFAULT_CLOSING_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(loan_id, to_member_id, expected_loan_version, **overrides) -> dict:
    n = next(_name_seq)
    defaults = {
        "loan_id": loan_id,
        "to_member_id": to_member_id,
        "transfer_type": "SERVICING",
        "effective_date": DEFAULT_CLOSING_DATE,
        "idempotency_key": f"idem-{n}",
        "expected_loan_version": expected_loan_version,
    }
    defaults.update(overrides)
    return defaults


def create_qa_review_payload(member_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-06-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(loan_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "field_name": "CLOSING_DATE",
        "expected_value": "2026-01-05",
        "actual_value": "2026-01-06",
        "severity": "MINOR",
    }
    defaults.update(overrides)
    return defaults


def create_annual_report_payload(report_year=2026, **overrides) -> dict:
    defaults = {"report_year": report_year}
    defaults.update(overrides)
    return defaults


def create_sor_run_payload(records=None, **overrides) -> dict:
    defaults = {"records": [] if records is None else records}
    defaults.update(overrides)
    return defaults


def sor_record(min_value, servicer_org_id, investor_org_id) -> dict:
    return {
        "min": min_value,
        "servicer_org_id": servicer_org_id,
        "investor_org_id": investor_org_id,
    }


def terminate_member_payload(effective_date, expected_member_version) -> dict:
    return {
        "effective_date": effective_date,
        "expected_member_version": expected_member_version,
    }
