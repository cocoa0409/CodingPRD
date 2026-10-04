"""Composite setup helpers for the Ocean Billing API test suite.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so the
database is always empty at test start). Setup calls use get_success_data()
so failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_payload,
    create_contract_payload,
    create_terminal_payload,
    create_holiday_payload,
    create_slot_payload,
    create_return_location_payload,
    create_container_payload,
    set_hold_payload,
    gate_out_payload,
    create_dispute_payload,
    create_evidence_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_rep_headers,
)

CM = TEST_USERS["contract_manager_headers"]
TO = TEST_USERS["terminal_operator_headers"]
EC = TEST_USERS["equipment_controller_headers"]
BA = TEST_USERS["billing_agent_headers"]
SUP = TEST_USERS["credit_supervisor_headers"]
DIR = TEST_USERS["credit_director_headers"]


def set_clock(to_iso8601, headers=None):
    """Advance the logical clock; returns the response payload."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, headers or TO)
    )


def create_account(**overrides):
    """Register a fresh ACTIVE customer account."""
    return get_success_data(api_client.create_customer_account(create_account_payload(**overrides), CM))


def create_contract(account_id, **overrides):
    """Create a DRAFT service contract under the account."""
    return get_success_data(
        api_client.create_service_contract(account_id, create_contract_payload(**overrides), CM)
    )


def create_active_contract(account_id, **overrides):
    """Create a contract and activate it (logical clock must be inside its window)."""
    contract = create_contract(account_id, **overrides)
    activated = get_success_data(api_client.activate_service_contract(contract["id"], CM))
    return activated


def create_terminal(**overrides):
    """Register a terminal (defaults: Pacific/Honolulu, capacity 5, weekends closed)."""
    return get_success_data(api_client.create_terminal(create_terminal_payload(**overrides), TO))


def create_terminal_with_labor_day(**overrides):
    """Terminal plus the 2026-09-07 Labor Day holiday used by the test calendar."""
    terminal = create_terminal(**overrides)
    get_success_data(api_client.create_terminal_holiday(terminal["id"], create_holiday_payload(), TO))
    return terminal


def create_return_location(terminal_id, **overrides):
    return get_success_data(
        api_client.create_return_location(
            create_return_location_payload(terminal_id, **overrides), EC
        )
    )


def create_slot(terminal_id, **overrides):
    return get_success_data(
        api_client.create_appointment_slot(terminal_id, create_slot_payload(**overrides), TO)
    )


def setup_account_with_active_contract(contract_overrides=None, account_overrides=None):
    """Tier 2: ACTIVE account + ACTIVE contract. Returns (account, contract)."""
    account = create_account(**(account_overrides or {}))
    contract = create_active_contract(account["id"], **(contract_overrides or {}))
    return account, contract


def setup_terminal_stack(with_holiday=True, location_overrides=None, terminal_overrides=None):
    """Tier 2: terminal (+ optional Labor Day holiday) + one OPEN DRY40 return location.

    Returns (terminal, location).
    """
    if with_holiday:
        terminal = create_terminal_with_labor_day(**(terminal_overrides or {}))
    else:
        terminal = create_terminal(**(terminal_overrides or {}))
    location = create_return_location(terminal["id"], **(location_overrides or {}))
    return terminal, location


def register_container(account, contract, terminal, **overrides):
    """Register a discharged container pinned to the contract. Returns container."""
    return get_success_data(
        api_client.create_container(
            create_container_payload(account["id"], contract["id"], terminal["id"], **overrides),
            TO,
        )
    )


def create_available_container(account, contract, terminal, **overrides):
    """Tier 1/3: register + mark-available. Returns the AVAILABLE container."""
    container = register_container(account, contract, terminal, **overrides)
    return get_success_data(api_client.mark_container_available(container["id"], TO))


def gate_out(container_id, clock_ts=None, **overrides):
    """Advance the clock (if given) and gate the container out with slot_override."""
    if clock_ts:
        set_clock(clock_ts)
    return get_success_data(api_client.gate_out_container(container_id, gate_out_payload(**overrides), TO))


def return_empty(container_id, clock_ts=None):
    """Advance the clock (if given) and accept the empty return."""
    if clock_ts:
        set_clock(clock_ts)
    return get_success_data(api_client.return_empty_container(container_id, EC))


def setup_empty_returned_container(
    contract_overrides=None,
    container_overrides=None,
    gate_out_clock="2026-09-04T12:00:00Z",
    return_clock=None,
    account_overrides=None,
    location_overrides=None,
    with_holiday=True,
):
    """Tier 3: full physical flow through EMPTY_RETURNED.

    Returns dict with account, contract, terminal, location, container.
    """
    account, contract = setup_account_with_active_contract(
        contract_overrides=contract_overrides, account_overrides=account_overrides
    )
    terminal, location = setup_terminal_stack(
        with_holiday=with_holiday, location_overrides=location_overrides
    )
    container = create_available_container(account, contract, terminal, **(container_overrides or {}))
    container = gate_out(container["id"], clock_ts=gate_out_clock)
    container = return_empty(container["id"], clock_ts=return_clock)
    return {
        "account": account,
        "contract": contract,
        "terminal": terminal,
        "location": location,
        "container": container,
    }


def setup_issued_invoice(**kwargs):
    """Tier 3/5: EMPTY_RETURNED container + issued invoice.

    Accepts the same kwargs as setup_empty_returned_container plus
    issue_clock (logical clock at issuance). Returns dict including 'invoice'.
    """
    issue_clock = kwargs.pop("issue_clock", None)
    ctx = setup_empty_returned_container(**kwargs)
    if issue_clock:
        set_clock(issue_clock)
    invoice = get_success_data(api_client.issue_invoice(ctx["container"]["id"], BA))
    ctx["invoice"] = invoice
    return ctx


def file_dispute(invoice, account, contested_amount_cents, **overrides):
    """CustomerRep of the owning account files a dispute (identity threaded)."""
    return get_success_data(
        api_client.create_dispute(
            invoice["id"],
            create_dispute_payload(contested_amount_cents, **overrides),
            make_customer_rep_headers(account["id"]),
        )
    )


def attach_evidence(dispute, account=None, actor_headers=None, **overrides):
    """Attach evidence to a dispute. Defaults to the owning CustomerRep."""
    if actor_headers is None:
        actor_headers = make_customer_rep_headers(account["id"])
    return get_success_data(
        api_client.attach_evidence(dispute["id"], create_evidence_payload(**overrides), actor_headers)
    )


def setup_dispute_under_review(
    dispute_reason="OTHER",
    contested_amount_cents=10000,
    with_evidence=False,
    invoice_kwargs=None,
    dispute_overrides=None,
):
    """Tier 5: issued invoice + dispute moved to UNDER_REVIEW.

    Returns dict with account/contract/terminal/location/container/invoice/dispute.
    For evidence-driven reasons pass with_evidence=True to satisfy the
    start-review evidence requirement.
    """
    ctx = setup_issued_invoice(**(invoice_kwargs or {}))
    overrides = {"dispute_reason": dispute_reason}
    overrides.update(dispute_overrides or {})
    dispute = file_dispute(ctx["invoice"], ctx["account"], contested_amount_cents, **overrides)
    if with_evidence:
        attach_evidence(dispute, ctx["account"])
    dispute = get_success_data(api_client.start_dispute_review(dispute["id"], BA))
    ctx["dispute"] = dispute
    return ctx


def get_invoice(invoice_id, headers=None):
    return get_success_data(api_client.get_invoice(invoice_id, headers or BA))


def get_account(account_id, headers=None):
    return get_success_data(api_client.get_customer_account(account_id, headers or BA))


def get_dispute(dispute_id, headers=None):
    return get_success_data(api_client.get_dispute(dispute_id, headers or BA))


def get_container(container_id, headers=None):
    return get_success_data(api_client.get_container(container_id, headers or TO))


def get_slot(slot_id, headers=None):
    return get_success_data(api_client.get_appointment_slot(slot_id, headers or TO))
