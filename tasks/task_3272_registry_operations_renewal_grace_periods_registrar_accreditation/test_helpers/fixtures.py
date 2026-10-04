"""Composite setup helpers — multi-step preconditions built from PRD endpoints.

Every fixture builds state from scratch via the public API; the harness
restarts the server before every test, so each test begins with an empty
database and the logical clock at 2026-09-01T00:00:00Z (PRD §2.5).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_domain_payload,
    create_registrar_payload,
)
from .test_users import (
    make_admin_headers,
    make_finance_headers,
    make_operator_headers,
)

DEFAULT_EFFECTIVE_ON = "2027-03-01T00:00:00Z"


def set_clock(to_iso8601: str):
    """Advance the logical clock as RegistryAdmin. Returns response data."""
    resp = api_client.set_clock(to_iso8601, make_admin_headers())
    return get_success_data(resp)


def create_schedule(effective_on: str = DEFAULT_EFFECTIVE_ON, **overrides):
    """Announce a price schedule as RegistryAdmin. Returns schedule data."""
    payload = {
        "create_fee_cents": 700,
        "renew_fee_cents": 850,
        "restore_fee_cents": 12000,
        "transfer_fee_cents": 700,
        "effective_on": effective_on,
    }
    payload.update(overrides)
    resp = api_client.create_price_schedule(payload, make_admin_headers())
    return get_success_data(resp)


def create_pending_registrar(**overrides):
    """Create a PENDING_TESTS registrar applicant. Returns registrar data."""
    resp = api_client.create_registrar(
        create_registrar_payload(**overrides), make_admin_headers())
    return get_success_data(resp, expected_status=201)


def create_active_registrar(**overrides):
    """Create + accredit a registrar. Returns accredited registrar data."""
    registrar = create_pending_registrar(**overrides)
    resp = api_client.accredit_registrar(registrar["id"], make_admin_headers())
    return get_success_data(resp)


def operator_headers_for(registrar_id: str) -> dict:
    return make_operator_headers(registrar_id)


def create_domain_for(registrar_id: str, name: str, years: int = 1,
                      premium: bool = None):
    """Register a domain under an ACTIVE registrar. Returns domain data."""
    payload = create_domain_payload(name=name, registrar_id=registrar_id,
                                    years=years)
    if premium is not None:
        payload["premium"] = premium
    resp = api_client.create_domain(payload, make_operator_headers(registrar_id))
    return get_success_data(resp, expected_status=201)


def setup_active_registrar(clock: str = "2027-04-01T00:00:00Z",
                           schedule_effective_on: str = DEFAULT_EFFECTIVE_ON,
                           **registrar_overrides):
    """Schedule announced at the epoch (satisfying the 180-day notice),
    then clock advanced + accredited registrar.

    Returns (registrar, schedule).
    """
    schedule = create_schedule(effective_on=schedule_effective_on)
    set_clock(clock)
    registrar = create_active_registrar(**registrar_overrides)
    return registrar, schedule


def setup_active_domain(clock: str = "2027-04-01T00:00:00Z",
                        name: str = "fixture-domain",
                        years: int = 1, premium: bool = None,
                        **registrar_overrides):
    """Active registrar + one ACTIVE domain.

    Returns (registrar, schedule, domain).
    """
    registrar, schedule = setup_active_registrar(clock=clock,
                                                 **registrar_overrides)
    domain = create_domain_for(registrar["id"], name, years=years,
                               premium=premium)
    return registrar, schedule, domain


def setup_two_registrars_with_domain(clock: str = "2027-03-01T00:00:00Z",
                                     domain_clock: str = None,
                                     name: str = "xfer-domain",
                                     years: int = 1):
    """Registrars A (loser) and B (gainer) ACTIVE, plus a domain sponsored
    by A. Returns (reg_a, reg_b, schedule, domain).

    The domain is created at `clock` unless domain_clock overrides it; the
    60-day transfer window opens at domain.created_at + 60 days.
    """
    schedule = create_schedule(effective_on=DEFAULT_EFFECTIVE_ON)
    set_clock(clock)
    reg_a = create_active_registrar(legal_name="Fixture Registrar A")
    reg_b = create_active_registrar(legal_name="Fixture Registrar B")
    if domain_clock is not None:
        set_clock(domain_clock)
    domain = create_domain_for(reg_a["id"], name, years=years)
    return reg_a, reg_b, schedule, domain


def request_transfer(domain_id: str, gaining_registrar_id: str):
    """Gaining registrar requests a transfer. Returns transfer data
    (including the plaintext auth_code, present only in this response)."""
    resp = api_client.create_transfer(
        {"domain_id": domain_id, "to_registrar_id": gaining_registrar_id},
        make_operator_headers(gaining_registrar_id),
    )
    return get_success_data(resp, expected_status=201)


def setup_requested_transfer(clock: str = "2027-03-01T00:00:00Z",
                             request_clock: str = "2027-05-08T00:00:00Z",
                             name: str = "xfer-domain"):
    """Domain by A, then a REQUESTED transfer A -> B at request_clock.

    Returns (reg_a, reg_b, domain, transfer).
    """
    reg_a, reg_b, _schedule, domain = setup_two_registrars_with_domain(
        clock=clock, name=name)
    set_clock(request_clock)
    transfer = request_transfer(domain["id"], reg_b["id"])
    return reg_a, reg_b, domain, transfer


def setup_completed_transfer(clock: str = "2027-03-01T00:00:00Z",
                             request_clock: str = "2027-05-08T00:00:00Z",
                             name: str = "xfer-domain"):
    """A -> B transfer requested, acked, and completed.

    Returns (reg_a, reg_b, domain, transfer).
    """
    reg_a, reg_b, domain, transfer = setup_requested_transfer(
        clock=clock, request_clock=request_clock, name=name)
    resp = api_client.ack_transfer(
        transfer["id"], transfer["auth_code"],
        make_operator_headers(reg_a["id"]))
    get_success_data(resp)
    resp = api_client.complete_transfer(
        transfer["id"], make_operator_headers(reg_b["id"]))
    transfer = get_success_data(resp)
    return reg_a, reg_b, domain, transfer


def setup_disputed_transfer(**kwargs):
    """Completed transfer then disputed by the losing registrar.

    Returns (reg_a, reg_b, domain, transfer).
    """
    reg_a, reg_b, domain, transfer = setup_completed_transfer(**kwargs)
    resp = api_client.dispute_transfer(
        transfer["id"], "fixture dispute", make_operator_headers(reg_a["id"]))
    transfer = get_success_data(resp)
    return reg_a, reg_b, domain, transfer


def find_invoice(domain_id=None, registrar_id=None, kind=None):
    """Fetch a single invoice by filters; fails loudly unless exactly one."""
    rows = list_invoices(domain_id=domain_id, registrar_id=registrar_id,
                         kind=kind)
    assert len(rows) == 1, f"expected exactly 1 invoice, got {len(rows)}"
    return rows[0]


def list_invoices(domain_id=None, registrar_id=None, kind=None):
    params = {}
    if domain_id is not None:
        params["domain_id"] = domain_id
    if registrar_id is not None:
        params["registrar_id"] = registrar_id
    if kind is not None:
        params["kind"] = kind
    resp = api_client.list_invoices(make_finance_headers(), params=params)
    rows, _meta = validate_paginated(resp)
    return rows


def registrar_ledger(registrar_id: str):
    """All ledger entries for a registrar."""
    resp = api_client.list_registrar_ledger(
        registrar_id, make_finance_headers())
    rows, _meta = validate_paginated(resp)
    return rows


def ledger_sum(registrar_id: str) -> int:
    return sum(entry["amount_cents"] for entry in registrar_ledger(registrar_id))


def get_domain(domain_id: str):
    resp = api_client.get_domain(domain_id, make_admin_headers())
    return get_success_data(resp)


def get_registrar(registrar_id: str):
    resp = api_client.get_registrar(registrar_id, make_admin_headers())
    return get_success_data(resp)


def get_transfer(transfer_id: str):
    resp = api_client.get_transfer(transfer_id, make_admin_headers())
    return get_success_data(resp)
