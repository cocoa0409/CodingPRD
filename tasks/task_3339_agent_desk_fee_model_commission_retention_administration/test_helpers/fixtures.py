"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so each fixture builds its preconditions from scratch using
only PRD-declared endpoints. All setup calls use the lenient get_success_data
validator so failures surface as clear 'Setup failed' errors.

Identity threading: the Agent role is entity-backed (PRD §2.1), so every
ownership-gated call uses make_agent_headers(agent["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import FIXTURE, REVIEW_LADDER
from .factories import (
    create_agent_payload, create_cda_payload, create_fee_assignment_payload,
    create_fee_schedule_payload, create_offer_payload, create_office_payload,
    create_referral_agreement_payload,
    generate_invoices_payload,
)
from .test_users import TEST_USERS, make_agent_headers

ADMIN = TEST_USERS["platform_admin_headers"]
OWNER = TEST_USERS["franchisee_owner_headers"]
BOR = TEST_USERS["broker_of_record_headers"]
MB = TEST_USERS["managing_broker_headers"]
TA = TEST_USERS["trust_accountant_headers"]
CA = TEST_USERS["compliance_auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: primitive building blocks
# ---------------------------------------------------------------------------

def set_clock(ts: str) -> None:
    resp = api_client.set_clock(ts, ADMIN)
    get_success_data(resp)


def create_office(**overrides) -> dict:
    resp = api_client.create_office(create_office_payload(**overrides), OWNER)
    return get_success_data(resp)


def create_second_office(**overrides) -> dict:
    defaults = {
        "office_name": FIXTURE["OFFICE2_NAME"],
        "market_code": FIXTURE["OFFICE2_MARKET"],
        "recruiting_target_agents": FIXTURE["OFFICE2_TARGET"],
    }
    defaults.update(overrides)
    resp = api_client.create_office(defaults, OWNER)
    return get_success_data(resp)


def create_schedule(**overrides) -> dict:
    resp = api_client.create_fee_schedule(create_fee_schedule_payload(**overrides), BOR)
    return get_success_data(resp)


def create_agent(office_id, **overrides) -> dict:
    resp = api_client.create_agent(office_id, create_agent_payload(**overrides), MB)
    return get_success_data(resp)


def propose_assignment(agent, schedule, **overrides) -> dict:
    """Propose an assignment with a fresh expected_agent_version (OCC field,
    PRD §2.7). Returns the PROPOSED assignment."""
    current = get_success_data(api_client.get_agent(agent["id"], MB))
    payload = create_fee_assignment_payload(
        schedule["id"], current["version"], **overrides)
    resp = api_client.create_fee_assignment(agent["id"], payload, MB)
    return get_success_data(resp)


def accept_assignment(assignment, agent) -> dict:
    resp = api_client.accept_fee_assignment(
        assignment["id"], make_agent_headers(agent["id"]))
    return get_success_data(resp)


def propose_and_accept_assignment(agent, schedule, **overrides) -> dict:
    assignment = propose_assignment(agent, schedule, **overrides)
    return accept_assignment(assignment, agent)


def create_active_agent(office_id, schedule, name=FIXTURE["ALICE_NAME"],
                        email=FIXTURE["ALICE_EMAIL"],
                        license_number=FIXTURE["ALICE_LICENSE"],
                        **assignment_overrides) -> dict:
    """Create an agent, propose + accept the fee assignment, and return the
    refreshed (ACTIVE) agent record."""
    agent = create_agent(office_id, full_name=name, email=email,
                         license_number=license_number)
    propose_and_accept_assignment(agent, schedule, **assignment_overrides)
    return get_success_data(api_client.get_agent(agent["id"], MB))


# ---------------------------------------------------------------------------
# Tier 2: office + schedule + agents
# ---------------------------------------------------------------------------

def setup_office_with_schedule(clock="2026-09-10T00:00:00Z"):
    """Clock set, one Denver office, one 95/5 schedule. Returns (office, schedule)."""
    set_clock(clock)
    office = create_office()
    schedule = create_schedule()
    return office, schedule


def setup_office_with_active_agent(clock="2026-09-10T00:00:00Z"):
    """Office + schedule + ACTIVE Alice. Returns (office, schedule, alice)."""
    office, schedule = setup_office_with_schedule(clock)
    alice = create_active_agent(office["id"], schedule)
    return office, schedule, alice


def setup_office_with_two_active_agents(clock="2026-09-01T00:00:00Z"):
    """Office + schedule + ACTIVE Alice + ACTIVE Bob."""
    office, schedule = setup_office_with_schedule(clock)
    alice = create_active_agent(office["id"], schedule)
    bob = create_active_agent(office["id"], schedule, name=FIXTURE["BOB_NAME"],
                              email=FIXTURE["BOB_EMAIL"],
                              license_number=FIXTURE["BOB_LICENSE"])
    return office, schedule, alice, bob


# ---------------------------------------------------------------------------
# Tier 3: offers, transactions, CDAs
# ---------------------------------------------------------------------------

def create_offer(office_id, caller_agent, **overrides) -> dict:
    resp = api_client.create_offer(
        office_id, create_offer_payload(**overrides),
        make_agent_headers(caller_agent["id"]))
    return get_success_data(resp)


def create_transaction_via_offer(office_id, agent, **offer_overrides):
    """Offer -> accept -> the acceptance-born transaction (UNDER_CONTRACT).

    PRD §3.5: "Acceptance is the offer's terminal fork. When an offer in
    `OFFERED` is accepted by the agent, two things happen in the same request:
    the offer moves to `ACCEPTED`, and a `Transaction` is created against the
    same office, born directly in `UNDER_CONTRACT` status". The born
    transaction is located via the `offer_id` list filter (PRD §3.5:
    "Transactions are listed with `office_id`, `status`, `selling_agent_id`,
    `listing_agent_id`, and `offer_id` filters").

    Returns (offer, transaction) with the transaction in UNDER_CONTRACT."""
    offer = create_offer(office_id, agent, **offer_overrides)
    # PRD §3.5: gross_commission_cents is the acceptance-time input.
    get_success_data(api_client.accept_offer(
        offer["id"], make_agent_headers(agent["id"]),
        {"gross_commission_cents": FIXTURE["TXN_GCI_CENTS"]}))
    from prd_bench_local_runner.testing import validate_paginated
    rows, _m = validate_paginated(api_client.list_transactions(
        MB, params={"offer_id": offer["id"]}))
    txn = next(r for r in rows if r["status"] == "UNDER_CONTRACT")
    return offer, txn


def create_transaction_under_contract(office_id, agent, **offer_overrides):
    """(offer, transaction) with the transaction in UNDER_CONTRACT.

    The canonical chain from the PRD §3.5 acceptance path: the offer is
    created and accepted, and the acceptance-born transaction lands directly
    in UNDER_CONTRACT."""
    return create_transaction_via_offer(office_id, agent, **offer_overrides)


def create_cda(txn_id) -> dict:
    resp = api_client.create_cda(txn_id, create_cda_payload(), MB)
    return get_success_data(resp)


def approve_cda_fully(cda_id) -> dict:
    """Walk the three-rung ladder: rung 0 ComplianceAuditor, rung 1
    TrustAccountant, rung 2 ManagingBroker (PRD §3.6). Returns APPROVED CDA."""
    get_success_data(api_client.review_cda(cda_id, {"verdict": "APPROVE"}, CA))
    get_success_data(api_client.review_cda(cda_id, {"verdict": "APPROVE"}, TA))
    return get_success_data(api_client.review_cda(cda_id, {"verdict": "APPROVE"}, MB))


def setup_pending_close_transaction(clock="2026-09-10T00:00:00Z",
                                    listing="L-100"):
    """Full chain: office + schedule + ACTIVE Alice + offer + UNDER_CONTRACT
    transaction + fully-approved CDA + request-close.

    Returns a dict with keys: office, schedule, alice, offer, txn, cda.
    The transaction is in PENDING_CLOSE."""
    office, schedule, alice = setup_office_with_active_agent(clock)
    offer, txn = create_transaction_under_contract(
        office["id"], alice, listing_reference=listing)
    cda = create_cda(txn["id"])
    approve_cda_fully(cda["id"])
    txn = get_success_data(
        api_client.request_close(txn["id"], make_agent_headers(alice["id"])))
    return {"office": office, "schedule": schedule, "alice": alice,
            "offer": offer, "txn": txn, "cda": cda}


# ---------------------------------------------------------------------------
# Tier 4: billing
# ---------------------------------------------------------------------------

def generate_september_invoices(office_id, billing_month=FIXTURE["BILLING_MONTH"]):
    """Run the monthly billing run; returns the list of generated invoices."""
    resp = api_client.generate_invoices(
        office_id, generate_invoices_payload(billing_month), MB)
    return get_success_data(resp)


def list_invoice_rows(headers=None, **params):
    from prd_bench_local_runner.testing import validate_paginated
    rows, _meta = validate_paginated(
        api_client.list_invoices(headers or TA, params=params))
    return rows


def list_agent_invoice_rows(agent_id, headers=None):
    from prd_bench_local_runner.testing import validate_paginated
    rows, _meta = validate_paginated(
        api_client.list_invoices(headers or TA, params={"agent_id": agent_id}))
    return rows


# ---------------------------------------------------------------------------
# Tier 5: termination flows
# ---------------------------------------------------------------------------

def terminate_agent(agent, clock_date) -> dict:
    """Set the clock to clock_date and have the agent initiate termination."""
    set_clock(clock_date)
    resp = api_client.terminate_agent(agent["id"], make_agent_headers(agent["id"]))
    return get_success_data(resp)


def complete_termination(agent, clock_date) -> dict:
    """Set the clock to clock_date and complete the termination."""
    set_clock(clock_date)
    resp = api_client.complete_termination(agent["id"], MB)
    return get_success_data(resp)


def terminate_and_complete(agent, terminate_date, complete_date) -> dict:
    terminate_agent(agent, terminate_date)
    return complete_termination(agent, complete_date)
