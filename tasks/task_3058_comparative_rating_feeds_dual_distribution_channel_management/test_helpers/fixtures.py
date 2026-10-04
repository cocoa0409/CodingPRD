"""Composite setup helpers for the comparative-rating dual-channel domain.

Every helper builds its preconditions from scratch against a freshly restarted
server (the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z until set).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_agent_payload,
    create_appointment_payload,
    create_bonus_pool_payload,
    create_bundle_placement_payload,
    create_claim_payload,
    create_commission_schedule_payload,
    create_commission_statement_payload,
    create_consumer_payload,
    create_feed_publication_payload,
    create_portfolio_review_payload,
    create_product_payload,
    create_quote_payload,
    create_rater_payload,
)
from .test_users import (
    TEST_USERS,
    make_agent_headers,
    make_consumer_headers,
)

ADMIN = TEST_USERS["carrier_admin_headers"]
RM = TEST_USERS["rating_manager_headers"]
UR = TEST_USERS["underwriting_reviewer_headers"]
UR2 = TEST_USERS["underwriting_reviewer_2_headers"]
ANON = TEST_USERS["anonymous_headers"]
SYS = TEST_USERS["system_headers"]


# ---------------------------------------------------------------------------
# Tier 1: basic entity setup
# ---------------------------------------------------------------------------

def set_clock(to_iso8601="2026-01-01T00:00:00Z"):
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def create_active_product(**overrides):
    """Create a product and activate it. Returns the ACTIVE product."""
    product = get_success_data(api.create_product(create_product_payload(**overrides), RM))
    return get_success_data(api.activate_product(product["id"], RM))


def create_rater(**overrides):
    return get_success_data(api.create_rater(create_rater_payload(**overrides), RM))


def create_feed_publication(rater_id, product_id, expected_rater_version=None, **overrides):
    """Create a DRAFT feed publication, reading the rater's current version
    when expected_rater_version is not supplied."""
    if expected_rater_version is None:
        expected_rater_version = get_success_data(api.get_rater(rater_id, RM))["version"]
    payload = create_feed_publication_payload(
        product_id, expected_rater_version, **overrides
    )
    return get_success_data(api.create_feed_publication(rater_id, payload, RM))


def publish_feed(publication_id):
    return get_success_data(api.publish_feed_publication(publication_id, RM))


def create_published_feed(rater_id, product_id, **overrides):
    """Create and publish a feed publication. Returns the PUBLISHED publication."""
    pub = create_feed_publication(rater_id, product_id, **overrides)
    return publish_feed(pub["id"])


def create_agent(**overrides):
    return get_success_data(api.create_agent(create_agent_payload(**overrides), ADMIN))


def create_appointment(agent_id, **overrides):
    payload = create_appointment_payload(**overrides)
    return get_success_data(api.create_appointment(agent_id, payload, UR))


def create_appointed_agent(state_code="TX", line_of_business="AUTO",
                           appointment_start="2026-01-01T00:00:00Z", **agent_overrides):
    """Create an agent with one ACTIVE appointment and appoint it.
    Returns the APPOINTED agent (re-read so version reflects the appoint)."""
    agent = create_agent(**agent_overrides)
    create_appointment(
        agent["id"], state_code=state_code, line_of_business=line_of_business,
        effective_start=appointment_start,
    )
    get_success_data(api.appoint_agent(agent["id"], UR))
    return get_success_data(api.get_agent(agent["id"], ADMIN))


def create_schedule(agent_id, tiers=None, contingent_bonus_eligible=False,
                    effective_start="2026-01-01T00:00:00Z", **overrides):
    """Create a CommissionSchedule, reading the agent's current version for the
    OCC field. Returns the ACTIVE schedule."""
    current_version = get_success_data(api.get_agent(agent_id, ADMIN))["version"]
    payload = create_commission_schedule_payload(
        current_version,
        tiers=tiers or [{"up_to_cents": None, "rate_pct": 0.10}],
        contingent_bonus_eligible=contingent_bonus_eligible,
        effective_start=effective_start,
        **overrides,
    )
    return get_success_data(api.create_commission_schedule(agent_id, payload, ADMIN))


def create_consumer(**overrides):
    return get_success_data(api.create_consumer(create_consumer_payload(**overrides), ANON))


# ---------------------------------------------------------------------------
# Tier 2: quote funnel helpers
# ---------------------------------------------------------------------------

def create_direct_quote(consumer, product_id, coverages=None, telematics_opt_in=False,
                        bundled_home_intended=False, **overrides):
    payload = create_quote_payload(
        consumer["id"], product_id,
        coverages=coverages or [{"coverage_code": "LIABILITY", "tier": "BASIC"}],
        telematics_opt_in=telematics_opt_in,
        bundled_home_intended=bundled_home_intended,
        **overrides,
    )
    return get_success_data(
        api.create_quote(payload, make_consumer_headers(consumer["id"]))
    )


def create_agent_quote(consumer, agent, product_id, coverages=None,
                       telematics_opt_in=False, bundled_home_intended=False, **overrides):
    payload = create_quote_payload(
        consumer["id"], product_id, channel="AGENT", agent_id=agent["id"],
        coverages=coverages or [{"coverage_code": "LIABILITY", "tier": "BASIC"}],
        telematics_opt_in=telematics_opt_in,
        bundled_home_intended=bundled_home_intended,
        **overrides,
    )
    return get_success_data(api.create_quote(payload, make_agent_headers(agent["id"])))


def submit_direct_quote(consumer, quote_id):
    return get_success_data(
        api.submit_quote(quote_id, make_consumer_headers(consumer["id"]))
    )


def submit_agent_quote(agent, quote_id):
    return get_success_data(api.submit_quote(quote_id, make_agent_headers(agent["id"])))


def bind_direct_quote(consumer, quote_id):
    """Bind a QUOTED direct quote; returns the created Policy."""
    return get_success_data(api.bind_quote(quote_id, make_consumer_headers(consumer["id"])))


def bind_agent_quote(agent, quote_id):
    """Bind an AGENT_QUOTED quote; returns the created Policy."""
    return get_success_data(api.bind_quote(quote_id, make_agent_headers(agent["id"])))


def bind_agent_policy_via_referral(consumer, agent, product_id, coverages=None,
                                   telematics_opt_in=False,
                                   bundled_home_intended=False, **overrides):
    """Bind a policy in the AGENT channel via the PRD §3.3 referral loop.

    PRD §3.3 pins agent-side bind to `AGENT_QUOTED`, and the only declared
    route to `AGENT_QUOTED` is consumer referral (`QUOTED → REFERRED_TO_AGENT`
    on a DIRECT quote, flipping channel to AGENT) followed by the named
    agent's `agent-quote` (`REFERRED_TO_AGENT → AGENT_QUOTED`), then bind. The
    agent leg recomputes the premium with agent-channel factors and pins the
    covering publication.
    """
    payload = create_quote_payload(
        consumer["id"], product_id,
        coverages=coverages or [{"coverage_code": "LIABILITY", "tier": "BASIC"}],
        telematics_opt_in=telematics_opt_in,
        bundled_home_intended=bundled_home_intended,
        **overrides,
    )
    quote = get_success_data(
        api.create_quote(payload, make_consumer_headers(consumer["id"]))
    )
    submit_direct_quote(consumer, quote["id"])
    get_success_data(
        api.refer_quote_to_agent(
            quote["id"], {"agent_id": agent["id"]}, make_consumer_headers(consumer["id"])
        )
    )
    agent_headers = make_agent_headers(agent["id"])
    get_success_data(api.agent_quote(quote["id"], agent_headers))
    policy = get_success_data(api.bind_quote(quote["id"], agent_headers))
    return {"quote": quote, "policy": policy}


def get_policy_enrollment(policy_id):
    """Return the (single) telematics enrollment of a policy."""
    data, _meta = _list_enrollments(policy_id)
    assert len(data) == 1, f"expected exactly one enrollment, got {len(data)}"
    return data[0]


def _list_enrollments(policy_id):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api.list_policy_telematics_enrollments(policy_id, SYS)
    return validate_paginated(resp)


# ---------------------------------------------------------------------------
# Tier 3: full setup composites
# ---------------------------------------------------------------------------

def setup_product_with_feed(product_overrides=None, feed_start="2026-01-01T00:00:00Z",
                            feed_end="2027-01-01T00:00:00Z"):
    """Active product + rater + PUBLISHED feed covering the window.
    Returns dict(product, rater, feed)."""
    product = create_active_product(**(product_overrides or {}))
    rater = create_rater()
    feed = create_published_feed(
        rater["id"], product["id"],
        effective_start=feed_start, effective_end=feed_end,
    )
    return {"product": product, "rater": rater, "feed": feed}


def setup_bound_direct_policy(consumer=None, telematics_opt_in=False, coverages=None,
                              product_overrides=None):
    """Active DIRECT-capable product + consumer + submitted + bound direct quote.
    Returns dict(product, consumer, quote, policy)."""
    product = create_active_product(**(product_overrides or {}))
    consumer = consumer or create_consumer()
    quote = create_direct_quote(
        consumer, product["id"], coverages=coverages,
        telematics_opt_in=telematics_opt_in,
    )
    submit_direct_quote(consumer, quote["id"])
    policy = bind_direct_quote(consumer, quote["id"])
    return {"product": product, "consumer": consumer, "quote": quote, "policy": policy}


def setup_bound_agent_policy(agent=None, consumer=None, telematics_opt_in=False,
                             bundled_home_intended=False, coverages=None,
                             product_overrides=None, with_feed=True):
    """Active product (+published feed) + appointed agent + consumer + a policy
    bound in the AGENT channel via the PRD §3.3 referral loop (direct quote →
    refer → agent-quote → bind). Returns dict(product, rater, feed, agent,
    consumer, quote, policy)."""
    ctx = {}
    if with_feed:
        ctx = setup_product_with_feed(product_overrides=product_overrides)
        product = ctx["product"]
    else:
        product = create_active_product(**(product_overrides or {}))
        ctx = {"product": product}
    agent = agent or create_appointed_agent()
    consumer = consumer or create_consumer()
    bound = bind_agent_policy_via_referral(
        consumer, agent, product["id"], coverages=coverages,
        telematics_opt_in=telematics_opt_in,
        bundled_home_intended=bundled_home_intended,
    )
    ctx.update({"agent": agent, "consumer": consumer,
                "quote": bound["quote"], "policy": bound["policy"]})
    return ctx


def setup_participating_enrollment(policy_id, actor_headers):
    """Fetch the enrollment of a policy and activate the device.
    Returns the PARTICIPATING enrollment."""
    enrollment = get_policy_enrollment(policy_id)
    return get_success_data(
        api.activate_telematics_device(enrollment["id"], actor_headers)
    )


def setup_paid_statement(agent_id, period_start="2026-01-01T00:00:00Z",
                         period_end="2026-02-01T00:00:00Z"):
    """Generate a statement, finalize it, pay it. Returns the PAID statement."""
    stmt = get_success_data(
        api.create_commission_statement(
            agent_id,
            create_commission_statement_payload(
                period_start=period_start, period_end=period_end
            ),
            ADMIN,
        )
    )
    get_success_data(api.finalize_commission_statement(stmt["id"], ADMIN))
    return get_success_data(api.pay_commission_statement(stmt["id"], ADMIN))


def setup_open_review_with_findings(agent_id, opened_by_headers=None):
    """Open a portfolio review and issue findings. Returns the FINDINGS_ISSUED
    review."""
    opener = opened_by_headers or UR
    review = get_success_data(
        api.create_portfolio_review(
            agent_id, create_portfolio_review_payload(), opener
        )
    )
    return get_success_data(
        api.issue_findings(review["id"], {"findings": "above appetite"}, opener)
    )


def setup_placed_bundle(agent=None, consumer=None, total_commission_cents=36500):
    """Bound agent policy on a bundle-eligible product + placement created and
    placed. Returns dict from setup_bound_agent_policy plus placement."""
    ctx = setup_bound_agent_policy(
        agent=agent, consumer=consumer,
        product_overrides={"bundle_eligible": True},
        bundled_home_intended=True,
    )
    agent = ctx["agent"]
    placement = get_success_data(
        api.create_bundle_placement(
            ctx["policy"]["id"],
            create_bundle_placement_payload(
                total_commission_cents=total_commission_cents
            ),
            make_agent_headers(agent["id"]),
        )
    )
    placement = get_success_data(
        api.place_bundle_placement(placement["id"], make_agent_headers(agent["id"]))
    )
    ctx["placement"] = placement
    return ctx


def report_claim(policy_id, **overrides):
    return get_success_data(api.create_claim(policy_id, create_claim_payload(**overrides), ADMIN))


def create_bonus_pool(**overrides):
    return get_success_data(api.create_bonus_pool(create_bonus_pool_payload(**overrides), ADMIN))
