"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because the harness restarts the server and wipes the database
before each individual test. Setup calls use the lenient `get_success_data`
validator so a broken precondition surfaces as a clear "Setup failed" message
rather than a confusing assertion failure deep inside the test body.

Ownership-gated calls thread the live entity id through the entity-backed role
builders (`make_listing_agent_headers`, `make_associate_agent_headers`).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_LOGICAL_CLOCK,
    TEST_DEFAULTS,
    TOUR_CONFIRM_CLOCK,
)
from .factories import (
    agent_payload,
    client_payload,
    clock_payload,
    listing_agreement_payload,
    referral_payload,
    region_payload,
    survey_payload,
    tour_payload,
)
from .test_users import (
    OPERATIONS_COORDINATOR,
    PLATFORM_ADMIN,
    TRANSACTION_COORDINATOR,
    make_associate_agent_headers,
    make_listing_agent_headers,
)

api = api_client


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def set_clock(current_utc: str = DEFAULT_LOGICAL_CLOCK):
    get_success_data(api.set_current_utc(current_utc, PLATFORM_ADMIN))


def create_region(**overrides) -> dict:
    return get_success_data(api.create_region(region_payload(**overrides), PLATFORM_ADMIN))


def create_lead_agent(region_id: str, **overrides) -> dict:
    overrides.setdefault("region_id", region_id)
    overrides.setdefault("agent_kind", "LEAD")
    return get_success_data(api.create_agent(agent_payload(**overrides), PLATFORM_ADMIN))


def create_associate_agent(region_id: str, **overrides) -> dict:
    overrides.setdefault("region_id", region_id)
    overrides.setdefault("agent_kind", "ASSOCIATE")
    overrides.setdefault("base_salary_cents", TEST_DEFAULTS["ASSOCIATE_BASE_SALARY_CENTS"])
    return get_success_data(api.create_agent(agent_payload(**overrides), PLATFORM_ADMIN))


def create_client(**overrides) -> dict:
    return get_success_data(api.create_client(client_payload(**overrides), OPERATIONS_COORDINATOR))


def assign_client(client_id: str) -> dict:
    return get_success_data(api.assign_agent(client_id, {}, OPERATIONS_COORDINATOR))


def open_transaction(client_id: str) -> dict:
    return get_success_data(api.open_transaction(client_id, {}, TRANSACTION_COORDINATOR))


def advance_to_review(transaction_id: str, contract_price_cents: int) -> dict:
    return get_success_data(api.set_coordination(
        transaction_id,
        {"coordination_status": "REVIEW", "contract_price_cents": contract_price_cents},
        TRANSACTION_COORDINATOR,
    ))


def close_transaction(transaction_id: str) -> dict:
    return get_success_data(api.close_transaction(transaction_id, TRANSACTION_COORDINATOR))


def create_survey(transaction_id: str, agent_id: str, score=None) -> dict:
    payload = {"agent_id": agent_id}
    if score is not None:
        payload["score"] = score
    return get_success_data(api.create_survey(transaction_id, payload, TRANSACTION_COORDINATOR))


def region_version(region_id: str) -> int:
    return get_success_data(api.get_region(region_id, PLATFORM_ADMIN))["version"]


def agent_version(agent_id: str) -> int:
    return get_success_data(api.get_agent(agent_id, PLATFORM_ADMIN))["version"]


def create_referral(client_id: str, region_id: str, **overrides) -> dict:
    overrides.setdefault("expected_region_version", region_version(region_id))
    return get_success_data(api.create_referral(referral_payload(client_id, **overrides), OPERATIONS_COORDINATOR))


def reconcile_referral(referral_id: str, contract_price_cents: int) -> dict:
    return get_success_data(api.reconcile_referral(
        referral_id, {"contract_price_cents": contract_price_cents}, TRANSACTION_COORDINATOR,
    ))


def create_listing(client_id: str, lead_agent_id: str, region_id: str, **overrides) -> dict:
    overrides.setdefault("expected_region_version", region_version(region_id))
    payload = listing_agreement_payload(client_id, overrides.pop("expected_region_version"), **overrides)
    return get_success_data(api.create_listing_agreement(payload, make_listing_agent_headers(lead_agent_id)))


def publish_listing(agreement_id: str, lead_agent_id: str) -> dict:
    return get_success_data(api.publish_listing(agreement_id, make_listing_agent_headers(lead_agent_id)))


def schedule_tour(client_id: str, scheduled_at: str, **overrides) -> dict:
    return get_success_data(api.create_tour(tour_payload(client_id, scheduled_at, **overrides), OPERATIONS_COORDINATOR))


def confirm_tour(tour_id: str, associate_agent_id: str) -> dict:
    return get_success_data(api.confirm_tour(tour_id, make_associate_agent_headers(associate_agent_id)))


def complete_tour(tour_id: str, associate_agent_id: str, feedback_rating: int, **overrides) -> dict:
    payload = {"feedback_rating": feedback_rating}
    payload.update(overrides)
    return get_success_data(api.complete_tour(tour_id, payload, make_associate_agent_headers(associate_agent_id)))


# ---------------------------------------------------------------------------
# Tier 1 — State progression
# ---------------------------------------------------------------------------

def create_basic_region_and_agent(**region_overrides):
    """Region + one LEAD agent inside it. Returns (region, lead_agent)."""
    set_clock()
    region = create_region(**region_overrides)
    lead = create_lead_agent(region["id"])
    return region, lead


def create_assigned_client(region: dict, lead: dict, **client_overrides) -> dict:
    """Client registered then assigned to `lead`. Returns the assigned client."""
    client = create_client(
        service_area_code=region["service_area_codes"][0],
        **client_overrides,
    )
    return assign_client(client["id"])


def create_agent_in_state(lead_agent_id: str, target_status: str, region_id: str) -> dict:
    """Walk an agent's employment status to `target_status` (ACTIVE / ON_LEAVE)."""
    if target_status == "ACTIVE":
        return get_success_data(api.get_agent(lead_agent_id, PLATFORM_ADMIN))
    payload = {"new_status": target_status, "expected_agent_version": agent_version(lead_agent_id)}
    return get_success_data(api.set_agent_status(lead_agent_id, payload, PLATFORM_ADMIN))


# ---------------------------------------------------------------------------
# Tier 2 — Entity hierarchy
# ---------------------------------------------------------------------------

def setup_region_with_lead():
    """Region + LEAD agent + ASSOCIATE agent. Returns (region, lead, associate)."""
    set_clock()
    region = create_region()
    lead = create_lead_agent(region["id"], full_name="Ada Lead")
    associate = create_associate_agent(region["id"], full_name="Ann Associate")
    return region, lead, associate


def setup_assigned_client_with_transaction(**region_overrides):
    """Region + lead + assigned client + an open transaction.

    Returns (region, lead, client, transaction).
    """
    set_clock()
    region = create_region(**region_overrides)
    lead = create_lead_agent(region["id"])
    client = create_assigned_client(region, lead)
    tx = open_transaction(client["id"])
    return region, lead, client, tx


# ---------------------------------------------------------------------------
# Tier 3 — Full lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_closed_transaction(
    region: dict,
    lead: dict,
    contract_price_cents: int = 80_000_000,
    **client_overrides,
):
    """Client assigned to `lead` whose transaction has run through to CLOSED.

    Returns (client, transaction).
    """
    client = create_assigned_client(region, lead, **client_overrides)
    tx = open_transaction(client["id"])
    advance_to_review(tx["id"], contract_price_cents)
    closed = close_transaction(tx["id"])
    return client, closed


def create_responded_survey_for_lead(region: dict, lead: dict, score: int = 5) -> dict:
    """Close a transaction for `lead` and create a RESPONDED survey scored `score`."""
    _client, tx = create_closed_transaction(region, lead)
    return create_survey(tx["id"], lead["id"], score=score)


def setup_lead_with_closed_transactions(region: dict, lead: dict, count: int = 3, score: int = 5):
    """Give `lead` `count` CLOSED transactions, each with a RESPONDED survey."""
    for i in range(count):
        create_responded_survey_for_lead(
            region, lead, score=score,
        )
    return get_success_data(api.get_agent(lead["id"], PLATFORM_ADMIN))


def setup_lead_with_one_close_and_one_cancel(region: dict, lead: dict):
    """One CLOSED and one CANCELLED transaction for the same lead agent.

    Returns (agent, closed_transaction, cancelled_transaction).
    """
    close_client, closed_tx = create_closed_transaction(region, lead)
    cancel_client = create_assigned_client(region, lead, full_name="Cancels")
    cancel_tx = open_transaction(cancel_client["id"])
    get_success_data(api.cancel_transaction(cancel_tx["id"], TRANSACTION_COORDINATOR))
    return get_success_data(api.get_agent(lead["id"], PLATFORM_ADMIN)), closed_tx, cancel_tx


# ---------------------------------------------------------------------------
# Tier 4 — Accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_region_with_agents_and_clients(
    target_client_ratio: float,
    agent_count: int,
    client_count: int,
    assign_clients: bool = False,
    **region_overrides,
):
    """Build a region with a known agent count and client pipeline.

    Returns (region, agents, clients). Used by occupancy-band boundary tests:
    the pipeline count over agent_count * target_client_ratio is what the test
    targets, so both inputs are caller-controlled.
    """
    set_clock()
    region = create_region(target_client_ratio=target_client_ratio, **region_overrides)
    codes = region["service_area_codes"]
    agents = [
        create_lead_agent(region["id"], full_name=f"Lead {i}", home_zip=codes[i % len(codes)])
        for i in range(agent_count)
    ]
    clients = [
        create_client(full_name=f"Pipeline {i}", service_area_code=codes[i % len(codes)])
        for i in range(client_count)
    ]
    if assign_clients:
        for client in clients:
            assign_client(client["id"])
    return region, agents, clients


def setup_lead_with_open_clients(
    target_client_ratio: float,
    client_count: int,
    **region_overrides,
):
    """Region + one lead agent carrying exactly `client_count` assigned clients.

    Returns (region, lead, clients). Drives the per-agent capacity-posture edges
    against the region's target ratio.
    """
    set_clock()
    region = create_region(target_client_ratio=target_client_ratio, **region_overrides)
    lead = create_lead_agent(region["id"])
    clients = []
    for i in range(client_count):
        clients.append(create_assigned_client(region, lead, full_name=f"Client {i}"))
    return region, lead, clients


def setup_lead_with_open_transaction_at_review(target_client_ratio: float = 1.0, **region_overrides):
    """Region + lead + one assigned client whose transaction sits at REVIEW.

    Returns (region, lead, client, transaction).
    """
    set_clock()
    region = create_region(target_client_ratio=target_client_ratio, **region_overrides)
    lead = create_lead_agent(region["id"])
    client = create_assigned_client(region, lead)
    tx = open_transaction(client["id"])
    advance_to_review(tx["id"], 80_000_000)
    return region, lead, client, tx


def setup_lead_with_confirmed_tour(target_client_ratio: float = 2.0):
    """Region + lead + associate + assigned client + a tour confirmed inside its window.

    Returns (region, lead, associate, client, tour).
    """
    set_clock()
    region = create_region(target_client_ratio=target_client_ratio)
    lead = create_lead_agent(region["id"], full_name="Ada Lead")
    associate = create_associate_agent(region["id"], full_name="Ann Associate")
    client = create_assigned_client(region, lead)
    tour = schedule_tour(
        client["id"],
        scheduled_at=TEST_DEFAULTS.get("TOUR_SCHEDULED_AT", "2026-09-02T10:00:00Z"),
        associate_agent_id=associate["id"],
    )
    set_clock(TOUR_CONFIRM_CLOCK)
    confirmed = confirm_tour(tour["id"], associate["id"])
    return region, lead, associate, client, confirmed


# ---------------------------------------------------------------------------
# Tier 5 — Finalization / terminal state
# ---------------------------------------------------------------------------

def setup_seller_with_listing(region: dict, lead: dict, publish: bool = False, **listing_overrides):
    """SELL client assigned to `lead`, carrying a listing agreement.

    Returns (client, listing_agreement).
    """
    seller = create_assigned_client(region, lead, full_name="Sara Seller", need_kind="SELL")
    listing = create_listing(seller["id"], lead["id"], region["id"], **listing_overrides)
    if publish:
        listing = publish_listing(listing["id"], lead["id"])
    return seller, listing


def setup_referred_client(region: dict, **referral_overrides):
    """Client routed to a partner brokerage. Returns (client, referral)."""
    client = create_client(service_area_code=region["service_area_codes"][0])
    referral = create_referral(client["id"], region["id"], **referral_overrides)
    return client, referral


def setup_referred_client_computed(region: dict, contract_price_cents: int = 100_000_000, **referral_overrides):
    """Referred client whose referral has been reconciled to COMPUTED."""
    client, referral = setup_referred_client(region, **referral_overrides)
    computed = reconcile_referral(referral["id"], contract_price_cents)
    return client, computed


def setup_client_with_prior_closed_then_reopened(region: dict, lead: dict, contract_price_cents: int = 75_000_000):
    """Client whose first transaction closed, then whose second transaction is opened.

    Returns (client, first_transaction, second_transaction).
    """
    client = create_assigned_client(region, lead, full_name="Repeat Buyer")
    tx1 = open_transaction(client["id"])
    advance_to_review(tx1["id"], contract_price_cents)
    close_transaction(tx1["id"])
    tx2 = open_transaction(client["id"])
    return client, tx1, tx2


def setup_region_with_agent_and_audits(region_id: str, limit: int = 100):
    """Read a region's audit stream."""
    return get_success_data(api.list_region_activity_audits(region_id, PLATFORM_ADMIN, params={"limit": limit}))