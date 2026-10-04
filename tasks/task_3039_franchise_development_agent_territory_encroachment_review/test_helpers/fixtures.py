"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints: the test harness restarts the server before every test, so each
test starts against an empty database. Setup calls use get_success_data() so
failures surface as clear "Setup failed" errors.

Identity threading: DevelopmentAgent and Franchisee are entity-backed roles
(PRD §2.1); ownership-gated calls always use make_*_headers(entity["id"]).
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_development_agent_payload,
    create_fee_statement_payload,
    create_franchisee_payload,
    create_impact_study_payload,
    create_inspection_payload,
    create_promotion_payload,
    create_protest_payload,
    create_remodel_mandate_payload,
    create_site_application_payload,
    create_store_payload,
    create_territory_payload,
    create_training_enrollment_payload,
    create_transfer_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_development_agent_headers,
    make_franchisee_headers,
    make_inspector_headers,
    make_mediator_headers,
)

OPS = TEST_USERS["franchisor_ops_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation helpers
# ---------------------------------------------------------------------------

def create_territory(**overrides) -> dict:
    return get_success_data(api_client.create_territory(create_territory_payload(**overrides), OPS))


def create_agent(**overrides) -> dict:
    return get_success_data(
        api_client.create_development_agent(create_development_agent_payload(**overrides), OPS)
    )


def create_franchisee(**overrides) -> dict:
    return get_success_data(
        api_client.create_franchisee(create_franchisee_payload(**overrides), OPS)
    )


def create_store(territory_id, franchisee_id, **overrides) -> dict:
    """Register a pre-existing store (born OPEN)."""
    return get_success_data(
        api_client.create_store(create_store_payload(territory_id, franchisee_id, **overrides), OPS)
    )


def set_clock(to_iso8601: str):
    get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def get_territory(territory_id) -> dict:
    return get_success_data(api_client.get_territory(territory_id, OPS))


def get_store(store_id) -> dict:
    return get_success_data(api_client.get_store(store_id, OPS))


def get_site_application(app_id) -> dict:
    return get_success_data(api_client.get_site_application(app_id, OPS))


def get_impact_study(study_id) -> dict:
    return get_success_data(api_client.get_impact_study(study_id, OPS))


def get_protest(protest_id) -> dict:
    return get_success_data(api_client.get_protest(protest_id, OPS))


def get_transfer_request(transfer_id) -> dict:
    return get_success_data(api_client.get_transfer_request(transfer_id, OPS))


def get_training_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.get_training_enrollment(enrollment_id, OPS))


def get_remodel_mandate(mandate_id) -> dict:
    return get_success_data(api_client.get_remodel_mandate(mandate_id, OPS))


def get_inspection(inspection_id) -> dict:
    return get_success_data(api_client.get_inspection(inspection_id, OPS))


def get_promotion(promotion_id) -> dict:
    return get_success_data(api_client.get_promotion(promotion_id, OPS))


def get_fee_statement(statement_id) -> dict:
    return get_success_data(api_client.get_fee_statement(statement_id, OPS))


def get_promotion_vote(vote_id) -> dict:
    return get_success_data(api_client.get_promotion_vote(vote_id, OPS))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — territory + agent + franchisee + store
# ---------------------------------------------------------------------------

def setup_assigned_territory(**territory_overrides) -> dict:
    """Territory + ACTIVE agent, assigned. Returns {"territory", "agent"}."""
    territory = create_territory(**territory_overrides)
    agent = create_agent()
    territory = get_success_data(
        api_client.assign_agent(territory["id"], {"agent_id": agent["id"]}, OPS)
    )
    return {"territory": territory, "agent": agent}


def setup_territory_with_stores(store_count=1, agent_assigned=True,
                                sales_cents=1_000_000, **territory_overrides) -> dict:
    """Territory (+ optional assigned agent) + N OPEN stores, each owned by its
    own franchisee. Returns {"territory", "agent", "stores", "owners"}; agent
    is None when agent_assigned is False."""
    territory = create_territory(**territory_overrides)
    agent = None
    if agent_assigned:
        agent = create_agent()
        territory = get_success_data(
            api_client.assign_agent(territory["id"], {"agent_id": agent["id"]}, OPS)
        )
    stores = []
    owners = []
    for i in range(store_count):
        owner = create_franchisee()
        store = create_store(
            territory["id"],
            owner["id"],
            geo_lat=40.0 + 0.1 * i,
            geo_lng=-75.0 - 0.1 * i,
            estimated_weekly_sales_cents=sales_cents,
            actual_avg_weekly_sales_cents=sales_cents,
        )
        stores.append(store)
        owners.append(owner)
    return {"territory": territory, "agent": agent, "stores": stores, "owners": owners}


# ---------------------------------------------------------------------------
# Tier 3: site application lifecycle
# ---------------------------------------------------------------------------

def create_application(territory, agent, applicant_id, **overrides) -> dict:
    """Create a DRAFT site application with the territory's live version as the
    OCC guard. Callers: pass the territory dict you already hold; the helper
    re-reads the version to stay current."""
    fresh = get_territory(territory["id"])
    payload = create_site_application_payload(
        territory["id"], applicant_id, fresh["version"], **overrides
    )
    return get_success_data(
        api_client.create_site_application(payload, make_development_agent_headers(agent["id"]))
    )


def submit_application(app_id, agent_id) -> dict:
    return get_success_data(
        api_client.submit_site_application(app_id, make_development_agent_headers(agent_id))
    )


def setup_submitted_application(**overrides) -> dict:
    """Assigned territory + applicant franchisee + DRAFT application submitted.
    Returns {"territory", "agent", "applicant", "application"} (SUBMITTED)."""
    ctx = setup_assigned_territory()
    applicant = create_franchisee()
    app = create_application(ctx["territory"], ctx["agent"], applicant["id"], **overrides)
    app = submit_application(app["id"], ctx["agent"]["id"])
    ctx.update({"applicant": applicant, "application": app})
    return ctx


def setup_application_in_impact_review(**overrides) -> dict:
    """Submitted application + PROVISIONAL impact study.
    Returns the ctx dict plus "study"; application in IMPACT_REVIEW."""
    ctx = setup_submitted_application(**overrides)
    study = get_success_data(
        api_client.create_impact_study(
            ctx["application"]["id"], create_impact_study_payload(), OPS
        )
    )
    ctx["study"] = study
    ctx["application"] = get_site_application(ctx["application"]["id"])
    return ctx


def setup_approved_application(**overrides) -> dict:
    """Application driven through to APPROVED (FINAL study + approval) with its
    PIPELINE store. Returns ctx plus "study", "application", "pipeline_store"."""
    ctx = setup_application_in_impact_review(**overrides)
    study = get_success_data(api_client.finalize_impact_study(ctx["study"]["id"], OPS))
    app = get_success_data(api_client.approve_site_application(ctx["application"]["id"], OPS))
    pipeline_store = get_store(app["store_id"])
    ctx.update({"study": study, "application": app, "pipeline_store": pipeline_store})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: protests
# ---------------------------------------------------------------------------

def setup_protest_filed(**overrides) -> dict:
    """Approved application + an OPEN protester store (different owner) + a
    FILED protest. Returns ctx plus "protester", "protester_store", "protest"."""
    ctx = setup_approved_application(**overrides)
    protester = create_franchisee()
    protester_store = create_store(ctx["territory"]["id"], protester["id"])
    protest = get_success_data(
        api_client.create_protest(
            create_protest_payload(ctx["application"]["id"], protester_store["id"]),
            make_franchisee_headers(protester["id"]),
        )
    )
    ctx.update({"protester": protester, "protester_store": protester_store, "protest": protest})
    return ctx


def setup_protest_under_review(**overrides) -> dict:
    ctx = setup_protest_filed(**overrides)
    protest = get_success_data(api_client.begin_protest_review(ctx["protest"]["id"], OPS))
    ctx["protest"] = protest
    return ctx


def setup_protest_in_mediation(deadline="2026-09-20T00:00:00Z",
                               mediator_ref="med-1", **overrides) -> dict:
    ctx = setup_protest_under_review(**overrides)
    protest = get_success_data(
        api_client.send_protest_to_mediation(
            ctx["protest"]["id"],
            {"mediator_ref": mediator_ref, "mediation_deadline": deadline},
            OPS,
        )
    )
    ctx["protest"] = protest
    ctx["mediator_ref"] = mediator_ref
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: inspections
# ---------------------------------------------------------------------------

def schedule_inspection(store_id, inspector_ref="insp-1", **overrides) -> dict:
    return get_success_data(
        api_client.create_inspection(
            create_inspection_payload(store_id, inspector_ref, **overrides), OPS
        )
    )


def record_findings(inspection_id, inspector_ref, food=90.0, cleanliness=90.0,
                    operations=90.0, critical_violations=0) -> dict:
    payload = {
        "food_safety_score": food,
        "cleanliness_score": cleanliness,
        "operations_score": operations,
        "critical_violations": critical_violations,
    }
    return get_success_data(
        api_client.record_inspection_findings(
            inspection_id, payload, make_inspector_headers(inspector_ref)
        )
    )


def finalize_inspection(inspection_id) -> dict:
    return get_success_data(api_client.finalize_inspection(inspection_id, OPS))


def drive_store_to_termination_pending(store_id, inspector_ref="insp-1") -> dict:
    """FAIL_CRITICAL cascade: store OPEN -> TERMINATION_PENDING. Returns the
    finalized inspection."""
    insp = schedule_inspection(store_id, inspector_ref=inspector_ref)
    record_findings(insp["id"], inspector_ref, food=50.0, cleanliness=50.0,
                    operations=50.0, critical_violations=3)
    return finalize_inspection(insp["id"])


def terminate_store(store_id) -> dict:
    """Drive a store OPEN -> TERMINATION_PENDING -> TERMINATED. Returns the
    terminated store."""
    drive_store_to_termination_pending(store_id)
    return get_success_data(api_client.terminate_store(store_id, OPS))


# ---------------------------------------------------------------------------
# Tier 3: transfer requests + training
# ---------------------------------------------------------------------------

def create_transfer(store, seller_id, buyer_id, **overrides) -> dict:
    """Create a PENDING transfer request with the store's live version as the
    OCC guard. Returns the request; the store's version is bumped by 1."""
    fresh = get_store(store["id"])
    payload = create_transfer_request_payload(
        store["id"], buyer_id, fresh["version"], **overrides
    )
    return get_success_data(
        api_client.create_transfer_request(payload, make_franchisee_headers(seller_id))
    )


def create_enrollment(franchisee_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_training_enrollment(
            create_training_enrollment_payload(franchisee_id, **overrides), OPS
        )
    )


def setup_transfer_pending(**overrides) -> dict:
    """Territory + OPEN store (seller) + buyer + PENDING transfer request.
    Returns {"territory", "seller", "buyer", "store", "transfer"}."""
    territory = create_territory()
    seller = create_franchisee()
    buyer = create_franchisee()
    store = create_store(territory["id"], seller["id"])
    transfer = create_transfer(store, seller["id"], buyer["id"], **overrides)
    return {"territory": territory, "seller": seller, "buyer": buyer,
            "store": store, "transfer": transfer}


def setup_transfer_in_buyer_training(**overrides) -> dict:
    """PENDING transfer + buyer ENROLLED in TRANSFER_BUYER + advanced to
    BUYER_TRAINING. Returns ctx plus "enrollment"."""
    ctx = setup_transfer_pending(**overrides)
    enrollment = create_enrollment(ctx["buyer"]["id"])
    transfer = get_success_data(
        api_client.advance_transfer_to_training(ctx["transfer"]["id"], OPS)
    )
    ctx.update({"enrollment": enrollment, "transfer": transfer})
    return ctx


def setup_transfer_pending_approval(**overrides) -> dict:
    """BUYER_TRAINING transfer whose buyer completes training -> the request
    lands in PENDING_APPROVAL. Returns ctx plus "enrollment"."""
    ctx = setup_transfer_in_buyer_training(**overrides)
    enrollment = get_success_data(
        api_client.record_training_result(ctx["enrollment"]["id"], {"score": 85}, OPS)
    )
    transfer = get_transfer_request(ctx["transfer"]["id"])
    ctx.update({"enrollment": enrollment, "transfer": transfer})
    return ctx


def setup_transfer_approved(store_opened_on="2016-09-01T00:00:00Z", **overrides) -> dict:
    """Full transfer path through APPROVED: buyer enrollment completed BEFORE
    the advance, so advance-to-training lands directly in PENDING_APPROVAL and
    the approve succeeds. Returns ctx plus "enrollment"."""
    territory = create_territory()
    seller = create_franchisee()
    buyer = create_franchisee()
    store = create_store(territory["id"], seller["id"], opened_on=store_opened_on)
    transfer = create_transfer(store, seller["id"], buyer["id"], **overrides)
    enrollment = create_enrollment(buyer["id"])
    enrollment = get_success_data(
        api_client.record_training_result(enrollment["id"], {"score": 90}, OPS)
    )
    transfer = get_success_data(api_client.advance_transfer_to_training(transfer["id"], OPS))
    transfer = get_success_data(api_client.approve_transfer(transfer["id"], OPS))
    return {"territory": territory, "seller": seller, "buyer": buyer, "store": store,
            "transfer": transfer, "enrollment": enrollment}


# ---------------------------------------------------------------------------
# Tier 3: remodel mandates
# ---------------------------------------------------------------------------

def create_mandate(store_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_remodel_mandate(create_remodel_mandate_payload(store_id, **overrides), OPS)
    )


def schedule_mandate(mandate_id, agent_id, closure_start, closure_end) -> dict:
    return get_success_data(
        api_client.schedule_remodel_mandate(
            mandate_id,
            {"closure_start": closure_start, "closure_end": closure_end},
            make_development_agent_headers(agent_id),
        )
    )


def setup_scheduled_mandate(closure_start="2026-10-01T00:00:00Z",
                            closure_end="2026-10-15T00:00:00Z", **overrides) -> dict:
    """Assigned territory + OPEN store + ISSUED mandate scheduled to a window.
    Returns {"territory", "agent", "owner", "store", "mandate"} (SCHEDULED)."""
    ctx = setup_assigned_territory()
    owner = create_franchisee()
    store = create_store(ctx["territory"]["id"], owner["id"])
    mandate = create_mandate(store["id"], **overrides)
    mandate = schedule_mandate(mandate["id"], ctx["agent"]["id"], closure_start, closure_end)
    ctx.update({"owner": owner, "store": store, "mandate": mandate})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: promotions / votes
# ---------------------------------------------------------------------------

def create_promotion(**overrides) -> dict:
    return get_success_data(api_client.create_promotion(create_promotion_payload(**overrides), OPS))


def setup_promotion_in_voting(**overrides) -> dict:
    """Promotion created and moved PROPOSED -> VOTING (default window covers
    the 2026-09-01 clock). Returns the promotion."""
    promotion = create_promotion(**overrides)
    return get_success_data(api_client.open_promotion_voting(promotion["id"], OPS))


def cast_for_ballots(promotion_id, stores, owners, count=None) -> list:
    """Cast FOR ballots for the first `count` (default: all) stores. Each
    ballot is cast by the owning franchisee. Returns the created votes."""
    votes = []
    pairs = list(zip(stores, owners))
    if count is not None:
        pairs = pairs[:count]
    for store, owner in pairs:
        vote = get_success_data(
            api_client.cast_vote(
                promotion_id,
                {"store_id": store["id"], "ballot": "FOR"},
                make_franchisee_headers(owner["id"]),
            )
        )
        votes.append(vote)
    return votes


def setup_promotion_with_votes(store_count, ballots, **overrides) -> dict:
    """Territory with `store_count` OPEN stores + a VOTING promotion with the
    given ballots. `ballots` is a list like ["FOR", "AGAINST", "ABSTAIN"]
    mapped onto the stores in order. Returns {"territory", "stores", "owners",
    "promotion", "votes"}."""
    ctx = setup_territory_with_stores(store_count=store_count, agent_assigned=False)
    promotion = setup_promotion_in_voting(**overrides)
    votes = []
    for store, owner, ballot in zip(ctx["stores"], ctx["owners"], ballots):
        vote = get_success_data(
            api_client.cast_vote(
                promotion["id"],
                {"store_id": store["id"], "ballot": ballot},
                make_franchisee_headers(owner["id"]),
            )
        )
        votes.append(vote)
    ctx.update({"promotion": promotion, "votes": votes})
    return ctx


def setup_approved_promotion(store_count, ballots, voting_close="2026-09-10T00:00:00Z",
                             **overrides) -> dict:
    """VOTING promotion closed at quorum -> APPROVED with funding computed.
    The clock is moved to `voting_close` to satisfy close-voting."""
    ctx = setup_promotion_with_votes(store_count, ballots, **overrides)
    set_clock(voting_close)
    promotion = get_success_data(api_client.close_promotion_voting(ctx["promotion"]["id"], {}, OPS))
    ctx["promotion"] = promotion
    return ctx


def setup_active_promotion(store_count=1, ballots=None, active_start="2026-10-01T00:00:00Z",
                           **overrides) -> dict:
    """APPROVED promotion activated (clock moved to active_start). Default: one
    store, one FOR ballot. Returns ctx with "promotion" ACTIVE."""
    if ballots is None:
        ballots = ["FOR"] * store_count
    ctx = setup_approved_promotion(store_count, ballots, **overrides)
    set_clock(active_start)
    promotion = get_success_data(api_client.activate_promotion(ctx["promotion"]["id"], OPS))
    ctx["promotion"] = promotion
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: fee statements
# ---------------------------------------------------------------------------

def generate_fee_statement(agent_id, territory_id, **overrides) -> dict:
    return get_success_data(
        api_client.generate_fee_statement(
            create_fee_statement_payload(agent_id, territory_id, **overrides), OPS
        )
    )


def setup_statement_scenario() -> dict:
    """Assigned territory (royalty 0.08) with one OPEN store (1,000,000/wk both
    estimated and actual) and one PIPELINE store via an approved application.
    Returns ctx with "agent", "territory", "open_store", "pipeline_store".

    PRD §3.6: a store born of an approved site application starts in PIPELINE;
    the PRD never names its initial weekly-sales figures, so callers must not
    assume the pipeline store contributes anything to a provisional fee
    estimate."""
    ctx = setup_assigned_territory()
    owner = create_franchisee()
    open_store = create_store(ctx["territory"]["id"], owner["id"])
    applicant = create_franchisee()
    app = create_application(
        ctx["territory"], ctx["agent"], applicant["id"],
        proposed_lat=41.5, proposed_lng=-76.5,
    )
    app = submit_application(app["id"], ctx["agent"]["id"])
    study = get_success_data(
        api_client.create_impact_study(app["id"], create_impact_study_payload(), OPS)
    )
    get_success_data(api_client.finalize_impact_study(study["id"], OPS))
    app = get_success_data(api_client.approve_site_application(app["id"], OPS))
    pipeline_store = get_store(app["store_id"])
    ctx.update({"applicant": applicant, "application": app,
                "open_store": open_store, "pipeline_store": pipeline_store})
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: terminal-state shortcuts
# ---------------------------------------------------------------------------

def setup_agent_under_review(**territory_overrides) -> dict:
    """Assigned territory + agent with one strike (UNDER_REVIEW)."""
    ctx = setup_assigned_territory(**territory_overrides)
    agent = get_success_data(api_client.flag_underperformance(ctx["agent"]["id"], OPS))
    ctx["agent"] = agent
    return ctx


def unique_suffix() -> str:
    return uuid.uuid4().hex[:8]
