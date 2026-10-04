"""Composite setup helpers for the managing-partner-equity API tests.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, and uses get_success_data() so a setup failure surfaces as a clear
"Setup failed" assertion rather than a confusing validate error.

Identity threading: ManagingPartner and MarketPartner are entity-backed roles;
every ownership-gated call here is made with make_managing_partner_headers(
partner["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_partner_payload,
    create_market_group_payload,
    create_restaurant_payload,
    create_contract_payload,
    create_profit_period_payload,
    create_line_item_payload,
    create_yield_standard_payload,
    create_meat_cut_batch_payload,
    create_award_program_payload,
    create_agreement_payload,
)
from .test_users import TEST_USERS, make_managing_partner_headers

ADMIN = TEST_USERS["platform_admin_headers"]
HR = TEST_USERS["hr_recruiter_headers"]
CONTROLLER = TEST_USERS["corporate_controller_headers"]
AUDITOR = TEST_USERS["operations_auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------

def set_clock(current_utc: str):
    """Advance the logical clock (fires every time-based sweep)."""
    return get_success_data(api_client.set_clock(current_utc, ADMIN))


def create_partner(role_in_program="MANAGING_PARTNER", **overrides):
    payload = create_partner_payload(role_in_program=role_in_program, **overrides)
    return get_success_data(api_client.create_partner(payload, HR))


def create_active_restaurant(market_group_id=None, **overrides):
    payload = create_restaurant_payload(**overrides)
    if market_group_id is not None:
        payload["market_group_id"] = market_group_id
    restaurant = get_success_data(api_client.create_restaurant(payload, ADMIN))
    return get_success_data(api_client.activate_restaurant(restaurant["id"], ADMIN))


def create_active_market_group_with_restaurants(num_restaurants=1, **overrides):
    """ACTIVE market group with num_restaurants ACTIVE restaurants assigned.
    Returns (group, [restaurant, ...])."""
    group = get_success_data(
        api_client.create_market_group(create_market_group_payload(**overrides), ADMIN)
    )
    restaurants = [
        create_active_restaurant(market_group_id=group["id"]) for _ in range(num_restaurants)
    ]
    group = get_success_data(api_client.activate_market_group(group["id"], ADMIN))
    return group, restaurants


# ---------------------------------------------------------------------------
# Tier 1/2: contract lifecycle
# ---------------------------------------------------------------------------

def create_draft_contract(partner_id, restaurant_id, **overrides):
    payload = create_contract_payload(
        partner_id=partner_id, restaurant_id=restaurant_id, **overrides
    )
    return get_success_data(api_client.create_contract(payload, CONTROLLER))


def submit_contract(contract_id):
    return get_success_data(api_client.submit_contract(contract_id, CONTROLLER))


def fund_contract(contract_id, partner_id, amount_cents):
    return get_success_data(
        api_client.post_buy_in_payment(
            contract_id,
            {"amount_cents": amount_cents},
            make_managing_partner_headers(partner_id),
        )
    )


def setup_active_contract(
    term_start_date="2027-01-01",
    term_end_date="2032-01-01",
    buy_in_required_cents=2500000,
    restaurant_id=None,
    market_group_id=None,
    partner_id=None,
):
    """ACTIVE contract on an ACTIVE restaurant with the buy-in fully funded.

    Returns dict(partner, restaurant, contract)."""
    partner = (
        get_success_data(api_client.get_partner(partner_id, HR))
        if partner_id
        else create_partner()
    )
    restaurant = (
        get_success_data(api_client.get_restaurant(restaurant_id, ADMIN))
        if restaurant_id
        else create_active_restaurant(market_group_id=market_group_id)
    )
    contract = create_draft_contract(
        partner["id"],
        restaurant["id"],
        term_start_date=term_start_date,
        term_end_date=term_end_date,
        buy_in_required_cents=buy_in_required_cents,
    )
    submit_contract(contract["id"])
    fund_contract(contract["id"], partner["id"], buy_in_required_cents)
    contract = get_success_data(api_client.activate_contract(contract["id"], CONTROLLER))
    return {"partner": partner, "restaurant": restaurant, "contract": contract}


# ---------------------------------------------------------------------------
# Tier 2: profit periods / line items
# ---------------------------------------------------------------------------

def create_open_period(restaurant_id, period_start_date, period_end_date):
    payload = create_profit_period_payload(
        restaurant_id=restaurant_id,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
    )
    return get_success_data(api_client.create_profit_period(payload, AUDITOR))


def current_period_version(period_id):
    return get_success_data(api_client.get_profit_period(period_id, AUDITOR))["version"]


def post_line_item(period_id, category, amount_cents, entry_status="FINALIZED"):
    """Post a line item carrying the period's current version (OCC)."""
    payload = create_line_item_payload(
        category=category,
        amount_cents=amount_cents,
        entry_status=entry_status,
        expected_profit_period_version=current_period_version(period_id),
    )
    return get_success_data(api_client.post_line_item(period_id, payload, AUDITOR))


def compute_period(period_id):
    """Run the provisional compute with the current period version (OCC)."""
    payload = {"expected_profit_period_version": current_period_version(period_id)}
    return get_success_data(api_client.compute_period(period_id, payload, AUDITOR))


def finalize_period(period_id):
    return get_success_data(api_client.finalize_period(period_id, CONTROLLER))


def setup_finalized_period(
    line_items,
    restaurant_id=None,
    period_start_date="2027-04-01",
    period_end_date="2027-05-01",
    clock_at="2027-04-15T00:00:00Z",
    setup=None,
):
    """ACTIVE contract + OPEN period + line items + compute + finalize.

    line_items: list of (category, amount_cents) posted as FINALIZED.
    The default clock instant sits INSIDE the period window because PRD §3.5
    rejects posting once the logical clock's date has passed period_end_date
    (ERR_PERIOD_CLOSED_FOR_ENTRIES). Callers that need the clock elsewhere
    afterwards set it explicitly after this helper returns.
    Returns dict(setup..., period)."""
    if setup is None:
        setup = setup_active_contract(restaurant_id=restaurant_id)
    period = create_open_period(
        setup["restaurant"]["id"], period_start_date, period_end_date
    )
    set_clock(clock_at)
    for category, amount_cents in line_items:
        post_line_item(period["id"], category, amount_cents, "FINALIZED")
    compute_period(period["id"])
    period = finalize_period(period["id"])
    setup["period"] = period
    return setup


def setup_dispute_under_review(setup=None, claim_text="Profit figure contested", **kwargs):
    """Finalized period + an open dispute (auto UNDER_REVIEW) filed by the
    managing partner. Returns dict(setup..., dispute)."""
    if setup is None:
        setup = setup_finalized_period(**kwargs)
    dispute = get_success_data(
        api_client.create_dispute_case(
            {"period_id": setup["period"]["id"], "claim_text": claim_text},
            make_managing_partner_headers(setup["partner"]["id"]),
        )
    )
    setup["dispute"] = dispute
    return setup


# ---------------------------------------------------------------------------
# Tier 3: meat cutting
# ---------------------------------------------------------------------------

def create_yield_standard(cut_code="SIR_8", **overrides):
    payload = create_yield_standard_payload(cut_code=cut_code, **overrides)
    return get_success_data(api_client.create_yield_standard(payload, CONTROLLER))


def create_meat_cut_batch(restaurant_id, profit_period_id, cut_code, sub_primal_weight_lbs):
    payload = create_meat_cut_batch_payload(
        restaurant_id=restaurant_id,
        profit_period_id=profit_period_id,
        cut_code=cut_code,
        sub_primal_weight_lbs=sub_primal_weight_lbs,
    )
    return get_success_data(api_client.create_meat_cut_batch(payload, AUDITOR))


def audit_batch(batch_id, actual_yield_lbs):
    return get_success_data(
        api_client.audit_meat_cut_batch(batch_id, {"actual_yield_lbs": actual_yield_lbs}, AUDITOR)
    )


# ---------------------------------------------------------------------------
# Tier 3: market partner agreements
# ---------------------------------------------------------------------------

def create_and_activate_agreement(
    market_group_id,
    partner_id=None,
    coverage_start_date="2027-01-01",
    coverage_end_date="2027-12-31",
    override_pct=5,
    basis="PER_RESTAURANT_POSITIVE",
):
    partner = (
        get_success_data(api_client.get_partner(partner_id, HR))
        if partner_id
        else create_partner(role_in_program="MARKET_PARTNER")
    )
    agreement = get_success_data(
        api_client.create_agreement(
            create_agreement_payload(
                partner_id=partner["id"],
                market_group_id=market_group_id,
                coverage_start_date=coverage_start_date,
                coverage_end_date=coverage_end_date,
                override_pct=override_pct,
                basis=basis,
            ),
            CONTROLLER,
        )
    )
    agreement = get_success_data(api_client.activate_agreement(agreement["id"], CONTROLLER))
    return partner, agreement


# ---------------------------------------------------------------------------
# Tier 4: awards
# ---------------------------------------------------------------------------

def create_stock_program(
    stock_units_pool=1000,
    performance_period_start_date="2027-01-01",
    performance_period_end_date="2027-12-31",
    program_type="STOCK_GRANT",
    **overrides,
):
    payload = create_award_program_payload(
        program_type=program_type,
        performance_period_start_date=performance_period_start_date,
        performance_period_end_date=performance_period_end_date,
        stock_units_pool=stock_units_pool,
        **overrides,
    )
    return get_success_data(api_client.create_award_program(payload, CONTROLLER))


def grant_award(program_id, partner_id, source_period_id):
    return get_success_data(
        api_client.create_award_grant(
            program_id,
            {"partner_id": partner_id, "source_period_id": source_period_id},
            CONTROLLER,
        )
    )


# ---------------------------------------------------------------------------
# Tier 5: departure / buyout
# ---------------------------------------------------------------------------

def setup_buyout_pending_contract(setup=None, clock_at="2028-06-01T00:00:00Z", **kwargs):
    """ACTIVE contract whose partner has departed (BUYOUT_PENDING)."""
    if setup is None:
        setup = setup_active_contract(**kwargs)
    set_clock(clock_at)
    contract = get_success_data(
        api_client.depart_contract(
            setup["contract"]["id"],
            make_managing_partner_headers(setup["partner"]["id"]),
        )
    )
    setup["contract"] = contract
    return setup


def create_priced_buyout(setup, offset_cents=0):
    """Create a DRAFT BuyoutOrder against a BUYOUT_PENDING contract (OCC)."""
    contract = get_success_data(
        api_client.get_contract(setup["contract"]["id"], CONTROLLER)
    )
    order = get_success_data(
        api_client.create_buyout_order(
            contract["id"],
            {"offset_cents": offset_cents, "expected_contract_version": contract["version"]},
            CONTROLLER,
        )
    )
    return order
