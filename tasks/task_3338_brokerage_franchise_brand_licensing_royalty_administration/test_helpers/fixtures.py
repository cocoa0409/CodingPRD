"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared endpoints —
the server restarts (empty database) before each test. Setup calls use the
lenient get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_brand_payload,
    create_brokerage_payload,
    create_conversion_plan_payload,
    create_council_payload,
    create_default_case_payload,
    create_gci_report_payload,
    create_market_payload,
    create_proposal_payload,
)
from .test_users import TEST_USERS, make_franchisee_admin_headers

OPS = TEST_USERS["franchisor_ops_headers"]
AUDITOR = TEST_USERS["brand_auditor_headers"]


# --- Tier 1: single-resource creation ---

def create_brand(**overrides) -> dict:
    return get_success_data(api_client.create_brand(create_brand_payload(**overrides), OPS))


def create_market(**overrides) -> dict:
    return get_success_data(api_client.create_market(create_market_payload(**overrides), OPS))


def create_brokerage(market_id: str = None, **overrides) -> dict:
    if market_id is None:
        market_id = create_market()["id"]
    return get_success_data(
        api_client.create_brokerage(create_brokerage_payload(market_id, **overrides), OPS)
    )


# --- Tier 2: agreement lifecycle ---

def setup_draft_agreement(**terms) -> dict:
    """Brand + Market + Brokerage + DRAFT FranchiseAgreement.

    Returns a ctx dict: brand, market, brokerage, agreement.
    """
    brand = create_brand(**{k[7:]: v for k, v in terms.items() if k.startswith("brand__")})
    market = create_market(**{k[8:]: v for k, v in terms.items() if k.startswith("market__")})
    brokerage = create_brokerage(
        market["id"],
        **{k[11:]: v for k, v in terms.items() if k.startswith("brokerage__")},
    )
    agreement_terms = {
        k: v for k, v in terms.items() if "__" not in k
    }
    agreement = get_success_data(
        api_client.create_agreement(
            create_agreement_payload(brokerage["id"], brand["id"], market["id"], **agreement_terms),
            OPS,
        )
    )
    return {"brand": brand, "market": market, "brokerage": brokerage, "agreement": agreement}


def setup_agreement_with_plan(num_milestones: int = 1, milestones=None, **terms) -> dict:
    """DRAFT agreement + ConversionPlan (milestones NOT completed)."""
    ctx = setup_draft_agreement(**terms)
    payload_milestones = milestones if milestones is not None else [
        {"name": f"m{i}", "target_date": "2027-01-01T00:00:00Z", "sequence": i}
        for i in range(1, num_milestones + 1)
    ]
    plan = get_success_data(
        api_client.create_conversion_plan(
            ctx["agreement"]["id"], create_conversion_plan_payload(milestones=payload_milestones), OPS
        )
    )
    ctx["plan"] = plan
    return ctx


def setup_active_agreement(num_milestones: int = 1, **terms) -> dict:
    """DRAFT agreement + ready ConversionPlan + activation.

    Returns ctx with brand, market, brokerage, agreement (ACTIVE), plan.
    """
    ctx = setup_agreement_with_plan(num_milestones=num_milestones, **terms)
    plan_id = ctx["plan"]["id"]
    milestones = ctx["plan"]["milestones"]
    for ms in milestones:
        get_success_data(
            api_client.complete_milestone(plan_id, {"sequence": ms["sequence"]}, OPS)
        )
    agreement_id = ctx["agreement"]["id"]
    activated = get_success_data(
        api_client.activate_agreement(
            agreement_id,
            {"expected_agreement_version": ctx["agreement"]["version"]},
            OPS,
        )
    )
    ctx["agreement"] = activated
    return ctx


def submit_gci_report(agreement_id: str, period_month: str, gci_cents: int) -> dict:
    return get_success_data(
        api_client.create_gci_report(
            agreement_id,
            create_gci_report_payload(period_month=period_month, gci_cents=gci_cents),
            OPS,
        )
    )


def assess_period(agreement_id: str, period_month: str) -> dict:
    return get_success_data(
        api_client.assess_royalty_period(agreement_id, {"period_month": period_month}, OPS)
    )


def setup_assessed_period(period_month: str, gci_cents: int, **terms) -> dict:
    """ACTIVE agreement + GCI report + assessed RoyaltyPeriod for one month."""
    ctx = setup_active_agreement(**terms)
    submit_gci_report(ctx["agreement"]["id"], period_month, gci_cents)
    ctx["period"] = assess_period(ctx["agreement"]["id"], period_month)
    return ctx


# --- Tier 3: default / suspension / termination flows ---

def open_default(agreement_id: str, reason_code: str = "PAYMENT") -> dict:
    return get_success_data(
        api_client.create_default_case(
            agreement_id, create_default_case_payload(reason_code=reason_code), OPS
        )
    )


def setup_suspended_agreement(**terms) -> dict:
    """ACTIVE agreement + one OPEN default + suspended. Adds 'default' to ctx."""
    ctx = setup_active_agreement(**terms)
    ctx["default"] = open_default(ctx["agreement"]["id"])
    ctx["agreement"] = get_success_data(api_client.suspend_agreement(ctx["agreement"]["id"], OPS))
    return ctx


def setup_deidentifying_agreement(**terms) -> dict:
    """Agreement terminated for cause -> DEIDENTIFYING with five PENDING tasks.

    Adds 'default' (ESCALATED) and 'tasks' (list of 5 task dicts) to ctx.
    """
    ctx = setup_active_agreement(**terms)
    ctx["default"] = open_default(ctx["agreement"]["id"])
    get_success_data(api_client.escalate_default_case(ctx["default"]["id"], OPS))
    ctx["agreement"] = get_success_data(
        api_client.terminate_agreement(ctx["agreement"]["id"], OPS)
    )
    rows, _m = validate_paginated(
        api_client.list_deidentification_tasks(ctx["agreement"]["id"], OPS)
    )
    ctx["tasks"] = rows
    return ctx


def setup_closed_agreement(**terms) -> dict:
    """DEIDENTIFYING agreement walked to CLOSED: default resolved, all tasks verified.

    Adds 'tasks' to ctx; brokerage is TERMINATED after closure if this was its
    only agreement.
    """
    ctx = setup_deidentifying_agreement(**terms)
    get_success_data(api_client.resolve_default_case(ctx["default"]["id"], OPS))
    admin = make_franchisee_admin_headers(ctx["brokerage"]["id"])
    for task in ctx["tasks"]:
        get_success_data(api_client.complete_deidentification_task(task["id"], admin))
        get_success_data(api_client.verify_deidentification_task(task["id"], OPS))
    ctx["agreement"] = get_success_data(api_client.get_agreement(ctx["agreement"]["id"], OPS))
    return ctx


# --- Tier 4: council / proposal flows ---

def setup_brand_with_seated_brokerages(brand_code: str, count: int, **terms) -> dict:
    """One brand plus `count` brokerages each holding an ACTIVE agreement in its
    own market. Returns {'brand', 'markets', 'brokerages', 'agreements'}."""
    brand = create_brand(brand_code=brand_code)
    markets, brokerages, agreements = [], [], []
    for _ in range(count):
        market = create_market()
        brokerage = create_brokerage(market["id"])
        agreement = get_success_data(
            api_client.create_agreement(
                create_agreement_payload(brokerage["id"], brand["id"], market["id"], **terms),
                OPS,
            )
        )
        plan = get_success_data(
            api_client.create_conversion_plan(
                agreement["id"], create_conversion_plan_payload(), OPS
            )
        )
        get_success_data(
            api_client.complete_milestone(
                plan["id"], {"sequence": plan["milestones"][0]["sequence"]}, OPS
            )
        )
        agreement = get_success_data(
            api_client.activate_agreement(
                agreement["id"], {"expected_agreement_version": agreement["version"]}, OPS
            )
        )
        markets.append(market)
        brokerages.append(brokerage)
        agreements.append(agreement)
    return {"brand": brand, "markets": markets, "brokerages": brokerages, "agreements": agreements}


def setup_submitted_proposal(seat_count: int = 3, amount_cents: int = 1_000, **terms) -> dict:
    """Brand + `seat_count` seated brokerages + council + SUBMITTED proposal.

    Returns {'brand', 'brokerages', 'agreements', 'council', 'proposal'}.
    """
    ctx = setup_brand_with_seated_brokerages(create_brand_payload()["brand_code"], seat_count, **terms)
    council = get_success_data(
        api_client.create_advisory_council(
            create_council_payload(
                ctx["brand"]["id"], [b["id"] for b in ctx["brokerages"]]
            ),
            OPS,
        )
    )
    proposal = get_success_data(
        api_client.create_ad_fund_proposal(
            create_proposal_payload(ctx["brand"]["id"], council["id"], amount_cents=amount_cents),
            OPS,
        )
    )
    proposal = get_success_data(api_client.submit_ad_fund_proposal(proposal["id"], OPS))
    ctx["council"] = council
    ctx["proposal"] = proposal
    return ctx


def cast_votes(proposal_id: str, brokerage_ids, vote: str) -> list:
    """Cast the same vote from several seated members; returns response data list."""
    results = []
    for bid in brokerage_ids:
        results.append(
            get_success_data(
                api_client.cast_vote(proposal_id, {"vote": vote}, make_franchisee_admin_headers(bid))
            )
        )
    return results
