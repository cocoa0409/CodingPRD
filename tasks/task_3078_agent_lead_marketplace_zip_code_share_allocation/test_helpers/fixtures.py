"""Composite setup helpers for the agent lead marketplace domain.

Every helper builds its preconditions from scratch against a freshly restarted
server (the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z per PRD §2.4).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import TEST_DEFAULTS
from .factories import (
    create_agent_payload,
    create_brokerage_payload,
    create_credit_claim_payload,
    create_dispute_payload,
    create_lead_payload,
    create_listing_payload,
    create_live_connection_payload,
    create_market_payload,
    create_payment_payload,
    create_record_payload,
    create_share_order_payload,
    create_team_account_payload,
    create_team_membership_payload,
)
from .test_users import TEST_USERS, make_agent_headers, make_brokerage_user_headers

OPS = TEST_USERS["marketplace_ops_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

CLOCK_START = TEST_DEFAULTS["CLOCK_START"]


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------

def set_clock(current_utc=CLOCK_START):
    return get_success_data(api.set_clock(current_utc, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: basic entities
# ---------------------------------------------------------------------------

def create_market(**overrides):
    return get_success_data(api.create_market(create_market_payload(**overrides), ADMIN))


def create_brokerage(**overrides):
    return get_success_data(api.create_brokerage(create_brokerage_payload(**overrides), ADMIN))


def create_agent(brokerage_id, **overrides):
    return get_success_data(api.create_agent(create_agent_payload(brokerage_id, **overrides), ADMIN))


def get_market(market_id):
    return get_success_data(api.get_market(market_id, ADMIN))


def get_agent(agent_id):
    return get_success_data(api.get_agent(agent_id, ADMIN))


def get_share_order(order_id):
    return get_success_data(api.get_share_order(order_id, ADMIN))


def get_lead(lead_id):
    return get_success_data(api.get_lead(lead_id, ADMIN))


def get_assignment(assignment_id):
    return get_success_data(api.get_assignment(assignment_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: share order lifecycle
# ---------------------------------------------------------------------------

def create_share_order(market_id, buyer_agent_id, **overrides):
    """Create a PENDING_PAYMENT order as the buyer agent (ownership-gated)."""
    payload = create_share_order_payload(market_id, buyer_agent_id, **overrides)
    return get_success_data(api.create_share_order(payload, make_agent_headers(buyer_agent_id)))


def activate_share_order(order, outcome="SUCCEEDED"):
    """Capture the activation deposit for a PENDING_PAYMENT order.

    Re-reads the market right before capture so expected_market_version always
    matches the current Market.version (OCC, PRD §2.7). Returns the recorded
    Payment."""
    market = get_market(order["market_id"])
    payload = create_payment_payload(
        order["deposit_cents"], market["version"], outcome=outcome
    )
    return get_success_data(
        api.capture_payment(order["id"], payload, make_agent_headers(order["buyer_agent_id"]))
    )


def create_active_share_order(market_id, buyer_agent_id, **overrides):
    """Create an order and activate it. Returns the ACTIVE order (re-read)."""
    order = create_share_order(market_id, buyer_agent_id, **overrides)
    activate_share_order(order)
    return get_share_order(order["id"])


# ---------------------------------------------------------------------------
# Tier 3: market + brokerage + agent + active order (the workhorse)
# ---------------------------------------------------------------------------

def setup_market_with_active_order(
    zip_code=None,
    state_code="OR",
    base_lead_price_cents=TEST_DEFAULTS["BASE_LEAD_PRICE_CENTS"],
    share_bps=6000,
    duration_days=30,
    participation_agreement=None,
    num_filler_agents=0,
):
    """Market + brokerage + buyer agent with one ACTIVE order.

    Returns (market, brokerage, buyer_agent, order). Filler agents (same
    license state, no orders) are returned nowhere but can be listed."""
    market_kwargs = {"state_code": state_code, "base_lead_price_cents": base_lead_price_cents}
    if zip_code is not None:
        market_kwargs["zip_code"] = zip_code
    if participation_agreement is not None:
        market_kwargs["participation_agreement"] = participation_agreement
    market = create_market(**market_kwargs)
    brokerage = create_brokerage(primary_state=state_code)
    agent = create_agent(brokerage["id"], license_state=state_code)
    for _ in range(num_filler_agents):
        create_agent(brokerage["id"], license_state=state_code)
    order = create_active_share_order(
        market["id"], agent["id"], share_bps=share_bps, duration_days=duration_days
    )
    market = get_market(market["id"])
    return market, brokerage, agent, order


def create_active_listing(market_id, brokerage_id, listing_agent_id, **overrides):
    """Create a listing and approve it. PRD §3.1/§3.4: a new listing lands in
    PENDING_REVIEW and is not routable for lead intake until approved; lead intake
    requires the listing to be ACTIVE (not WITHDRAWN / not under review)."""
    listing = create_listing(market_id, brokerage_id, listing_agent_id, **overrides)
    return get_success_data(
        api.review_listing(listing["id"], {"outcome": "APPROVE"}, OPS)
    )


# ---------------------------------------------------------------------------
# Tier 4: lead intake, offer, acceptance
# ---------------------------------------------------------------------------

def create_routed_lead(market_id, consumer_key, listing=None):
    """Ingest a lead and return (lead, open_assignment).

    PRD §3.4: intake requires the `listing_id` of the listing the consumer
    inquired about and the `listing_agent_id` recorded at intake. Pass an
    ACTIVE listing created via `create_active_listing` (or any listing dict
    carrying `id` and `listing_agent_id`)."""
    lead = get_success_data(
        api.create_lead(
            create_lead_payload(
                market_id,
                listing["id"],
                listing["listing_agent_id"],
                consumer_key=consumer_key,
            ),
            OPS,
        )
    )
    assignments = get_success_data(api.list_lead_assignments(lead["id"], OPS))
    return lead, assignments[0]


def accept_lead_offer(lead, assignment, agent_id):
    """Accept the open offer as one of its candidates. Returns the accept response data."""
    fresh_lead = get_lead(lead["id"])
    return get_success_data(
        api.accept_assignment(
            assignment["id"],
            {"expected_lead_version": fresh_lead["version"]},
            make_agent_headers(agent_id),
        )
    )


def setup_assigned_lead(
    zip_code=None,
    state_code="OR",
    share_bps=6000,
    duration_days=30,
    consumer_key="consumer-1@example.com",
    **market_kwargs,
):
    """Full chain: market + brokerage + agent + ACTIVE order + listing + lead +
    accepted offer.

    Returns (market, brokerage, agent, order, lead, assignment, listing)."""
    market, brokerage, agent, order = setup_market_with_active_order(
        zip_code=zip_code, state_code=state_code, share_bps=share_bps,
        duration_days=duration_days, **market_kwargs,
    )
    listing = create_active_listing(market["id"], brokerage["id"], agent["id"])
    lead, assignment = create_routed_lead(market["id"], consumer_key, listing)
    accept_lead_offer(lead, assignment, agent["id"])
    return market, brokerage, agent, order, get_lead(lead["id"]), assignment, listing


# ---------------------------------------------------------------------------
# Tier 5: teams
# ---------------------------------------------------------------------------

def setup_team_with_order(
    zip_code=None,
    state_code="OR",
    share_bps=6000,
    duration_days=30,
    member_weights=(2, 1),
    include_lead_membership=True,
    base_lead_price_cents=TEST_DEFAULTS["BASE_LEAD_PRICE_CENTS"],
):
    """Market + brokerage + team lead + members + team account + ACTIVE team order.

    Returns (market, brokerage, lead_agent, member_agents, team, memberships, order,
    listing). When include_lead_membership is true (the default), the team lead is
    added as a member with weight 1 first — its earlier created_at wins allocation
    ties per PRD §3.6 — and member_weights are added after. The listing is an
    ACTIVE listing whose listing agent is the team lead."""
    market = create_market(state_code=state_code, base_lead_price_cents=base_lead_price_cents,
                           **({"zip_code": zip_code} if zip_code else {}))
    brokerage = create_brokerage(primary_state=state_code)
    lead_agent = create_agent(brokerage["id"], license_state=state_code)
    member_agents = [create_agent(brokerage["id"], license_state=state_code) for _ in member_weights]
    team = get_success_data(
        api.create_team_account(
            create_team_account_payload(lead_agent["id"], market["id"]),
            make_agent_headers(lead_agent["id"]),
        )
    )
    memberships = []
    if include_lead_membership:
        memberships.append(
            get_success_data(
                api.create_team_membership(
                    create_team_membership_payload(team["id"], lead_agent["id"], allocation_weight=1),
                    make_agent_headers(lead_agent["id"]),
                )
            )
        )
    for idx, (member, weight) in enumerate(zip(member_agents, member_weights)):
        # Distinct created_at per membership so the PRD §3.6 tie-break
        # ("created_at ascending") is deterministic under the frozen clock.
        set_clock(f"2026-09-01T00:00:{idx + 1:02d}Z")
        memberships.append(
            get_success_data(
                api.create_team_membership(
                    create_team_membership_payload(team["id"], member["id"], allocation_weight=weight),
                    make_agent_headers(lead_agent["id"]),
                )
            )
        )
    set_clock(CLOCK_START)
    order = create_active_share_order(
        market["id"], lead_agent["id"], share_bps=share_bps,
        duration_days=duration_days, team_id=team["id"],
    )
    listing = create_active_listing(market["id"], brokerage["id"], lead_agent["id"])
    return market, brokerage, lead_agent, member_agents, team, memberships, order, listing


# ---------------------------------------------------------------------------
# Tier 6: claims / listings / disputes shortcuts
# ---------------------------------------------------------------------------

def create_claim(lead_id, claimant_agent_id, claim_type="INVALID", reason="test"):
    return get_success_data(
        api.create_credit_claim(
            create_credit_claim_payload(lead_id, claim_type=claim_type, reason=reason),
            make_agent_headers(claimant_agent_id),
        )
    )


def create_listing(market_id, brokerage_id, listing_agent_id, source_feed="MLS", **overrides):
    return get_success_data(
        api.create_listing(
            create_listing_payload(
                market_id, brokerage_id, listing_agent_id, source_feed=source_feed, **overrides
            ),
            make_brokerage_user_headers(brokerage_id),
        )
    )


def create_dispute(brokerage_id, **overrides):
    return get_success_data(
        api.create_dispute(
            create_dispute_payload(brokerage_id, **overrides),
            make_brokerage_user_headers(brokerage_id),
        )
    )
