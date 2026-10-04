"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import DEFAULT_SCHEDULE_FEES, TEST_DEFAULTS

_iana_counter = itertools.count(50000)
_hostname_counter = itertools.count(1)
_case_counter = itertools.count(1)


def _next_iana() -> int:
    return next(_iana_counter)


def _next_hostname() -> str:
    return f"ns-auto-{next(_hostname_counter)}.example"


def _next_case_reference() -> str:
    return f"CASE-AUTO-{next(_case_counter):05d}"


def create_registrar_payload(**overrides) -> dict:
    defaults = {
        "iana_number": _next_iana(),
        "legal_name": "Test Registrar LLC",
        "application_fee_cents": TEST_DEFAULTS["APPLICATION_FEE_CENTS"],
        "annual_fee_cents": TEST_DEFAULTS["ANNUAL_FEE_CENTS"],
        "escrow_deposit_cents": TEST_DEFAULTS["ESCROW_DEPOSIT_CENTS"],
        "technical_test_score": TEST_DEFAULTS["TECHNICAL_TEST_SCORE"],
        "financial_statement_verified": True,
    }
    defaults.update(overrides)
    return defaults


def create_price_schedule_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_SCHEDULE_FEES)
    defaults["effective_on"] = "2027-03-01T00:00:00Z"
    defaults.update(overrides)
    return defaults


def create_domain_payload(**overrides) -> dict:
    defaults = {
        "name": f"domain-{next(_hostname_counter)}",
        "registrar_id": "placeholder-registrar-id",
        "years": 1,
    }
    defaults.update(overrides)
    return defaults


def create_nameserver_payload(**overrides) -> dict:
    defaults = {
        "hostname": _next_hostname(),
        "ip_addresses": ["192.0.2.1"],
        "capacity_qps": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(**overrides) -> dict:
    defaults = {
        "domain_id": "placeholder-domain-id",
        "to_registrar_id": "placeholder-registrar-id",
    }
    defaults.update(overrides)
    return defaults


def create_abuse_report_payload(**overrides) -> dict:
    defaults = {
        "domain_id": "placeholder-domain-id",
        "reporter_contact": "reporter@example.com",
        "category": "SPAM",
        "detail": "abuse report detail",
    }
    defaults.update(overrides)
    return defaults


def create_court_order_payload(**overrides) -> dict:
    defaults = {
        "case_reference": _next_case_reference(),
        "domain_id": "placeholder-domain-id",
        "action": "SUSPEND",
        "effective_immediately": True,
    }
    defaults.update(overrides)
    return defaults
