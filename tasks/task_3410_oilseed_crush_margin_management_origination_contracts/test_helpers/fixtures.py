"""Composite setup helpers (fixtures) for the Oilseed Crush Origination tests.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints — the test harness restarts the server (empty database) before each
test, and the logical clock starts at exactly 2026-09-01T00:00:00Z
(PRD §2.5). Setup calls use get_success_data() so a setup failure surfaces as
a clear "Setup failed" error rather than an assertion failure.

Identity threading: Farmer and CommercialBuyer are entity-backed roles
(PRD §2.1); ownership-gated calls use make_farmer_headers(farmer["id"]) /
make_commercial_buyer_headers(buyer["id"]), never the shared TEST_USERS
fallback. Hedge flows pass explicit operator user ids ("trader-77", "rm-1")
because segregation of duties (PRD §3.7) keys on the recorded user id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BUYER_SUSPEND_CLAIM_THRESHOLD,
    LOGICAL_CLOCK_START,
)
from .factories import (
    CANONICAL_BEAN_PRICE_CENTS,
    CANONICAL_MEAL_PRICE_CENTS,
    CANONICAL_OIL_PRICE_CENTS,
    FUTURES_MONTH_DEC,
    FUTURES_MONTH_NOV,
    create_board_position_payload,
    create_buyer_payload,
    create_cash_contract_payload,
    create_basis_contract_payload,
    create_crush_plant_payload,
    create_crush_run_payload,
    create_deferred_contract_payload,
    create_delivery_ticket_payload,
    create_farmer_payload,
    create_freight_lane_payload,
    create_market_quote_payload,
    create_program_payload,
    create_sales_contract_payload,
    create_sales_delivery_payload,
    create_schedule_payload,
    schedule_crush_run_payload,
    set_clock_payload,
    transition_crush_run_payload,
)
from .test_users import (
    CRUSH_TRADER_USER_ID,
    RISK_MANAGER_USER_ID,
    TEST_USERS,
    make_crush_trader_headers,
    make_risk_manager_headers,
)

# Shared opaque-role header handles used inside fixtures.
ADMIN = TEST_USERS["platform_admin_headers"]
MERCH = TEST_USERS["origination_merchandiser_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
SCHEDULER = TEST_USERS["plant_scheduler_headers"]
PRODUCT_MERCH = TEST_USERS["product_merchandiser_headers"]
AUDITOR = TEST_USERS["sustainability_auditor_headers"]


def _fail(fixture_name, response):
    raise AssertionError(
        f"Setup failed in {fixture_name}: HTTP {response.status_code} — {response.text}"
    )


def _ok(fixture_name, response):
    try:
        return get_success_data(response)
    except AssertionError:
        _fail(fixture_name, response)


# =============================================================================
# Tier 0 — logical clock (PRD §2.5 / §3.9)
# =============================================================================

def set_clock(to_iso8601=LOGICAL_CLOCK_START, headers=None):
    """Advance the logical clock and run the deadline sweep synchronously.
    Returns {"current_utc": ...}. Only PlatformAdmin may call this."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), headers or ADMIN)
    return _ok("set_clock", resp)


def reset_clock(headers=None):
    """Pin the clock back to the PRD startup value 2026-09-01T00:00:00Z."""
    return set_clock(LOGICAL_CLOCK_START, headers=headers)


# =============================================================================
# Tier 1 — reference data and counterparties
# =============================================================================

def create_published_schedule(headers=None, **payload_overrides):
    """Create a discount schedule in DRAFT and publish it (terminal).
    Returns the PUBLISHED schedule."""
    hdrs = headers or ADMIN
    resp = api_client.create_quality_discount_schedule(
        create_schedule_payload(**payload_overrides), hdrs
    )
    schedule = _ok("create_published_schedule.create", resp)
    resp = api_client.publish_quality_discount_schedule(schedule["id"], hdrs)
    return _ok("create_published_schedule.publish", resp)


def create_draft_schedule(headers=None, **payload_overrides):
    """Create a schedule and leave it in DRAFT (for ERR_SCHEDULE_NOT_PUBLISHED
    and publish-transition tests)."""
    resp = api_client.create_quality_discount_schedule(
        create_schedule_payload(**payload_overrides), headers or ADMIN
    )
    return _ok("create_draft_schedule", resp)


def create_active_program(headers=None, **payload_overrides):
    resp = api_client.create_sustainability_program(
        create_program_payload(**payload_overrides), headers or ADMIN
    )
    return _ok("create_active_program", resp)


def close_program(program_id, headers=None):
    resp = api_client.close_sustainability_program(program_id, headers or AUDITOR)
    return _ok("close_program", resp)


def create_farmer(headers=None, **payload_overrides):
    resp = api_client.create_farmer(create_farmer_payload(**payload_overrides),
                                    headers or ADMIN)
    return _ok("create_farmer", resp)


def create_buyer(headers=None, **payload_overrides):
    resp = api_client.create_buyer(create_buyer_payload(**payload_overrides),
                                   headers or ADMIN)
    return _ok("create_buyer", resp)


def create_crush_plant(headers=None, **payload_overrides):
    """Register a plant. Pass status="MAINTENANCE" to register a site directly
    in maintenance (PRD §3.1)."""
    resp = api_client.create_crush_plant(create_crush_plant_payload(**payload_overrides),
                                         headers or ADMIN)
    return _ok("create_crush_plant", resp)


def create_elevator(schedule_id, headers=None, **payload_overrides):
    from .factories import create_elevator_payload
    resp = api_client.create_elevator(
        create_elevator_payload(schedule_id, **payload_overrides), headers or ADMIN
    )
    return _ok("create_elevator", resp)


# ------------------------------------------------------------- market quotes

def post_market_quote(commodity, quote_month, price_cents,
                      quote_date=LOGICAL_CLOCK_START, headers=None, **overrides):
    resp = api_client.create_market_quote(
        create_market_quote_payload(commodity, quote_month, price_cents,
                                    quote_date, **overrides),
        headers or ADMIN,
    )
    return _ok("post_market_quote", resp)


def post_bean_quote(quote_month, price_cents, quote_date=LOGICAL_CLOCK_START,
                    headers=None):
    return post_market_quote("BEAN", quote_month, price_cents, quote_date,
                             headers=headers)


def post_crush_quote_set(futures_month=FUTURES_MONTH_NOV,
                         bean=CANONICAL_BEAN_PRICE_CENTS,
                         oil=CANONICAL_OIL_PRICE_CENTS,
                         meal=CANONICAL_MEAL_PRICE_CENTS,
                         quote_date=LOGICAL_CLOCK_START, headers=None):
    """Post the BEAN/OIL/MEAL triple one futures month needs for crush-margin
    and board-crush math (PRD §3.6/§3.7). Returns {"BEAN":..., "OIL":..., "MEAL":...}."""
    return {
        "BEAN": post_market_quote("BEAN", futures_month, bean, quote_date, headers=headers),
        "OIL": post_market_quote("OIL", futures_month, oil, quote_date, headers=headers),
        "MEAL": post_market_quote("MEAL", futures_month, meal, quote_date, headers=headers),
    }


# =============================================================================
# Tier 2 — site composites
# =============================================================================

def setup_site(storage_capacity_bushels=100000, schedule_overrides=None,
               elevator_overrides=None):
    """Published discount schedule + elevator pinned to it for its lifetime
    (PRD §3.1). Returns {"schedule": ..., "elevator": ...}."""
    schedule = create_published_schedule(**(schedule_overrides or {}))
    elevator = create_elevator(
        schedule["id"],
        storage_capacity_bushels=storage_capacity_bushels,
        **(elevator_overrides or {}),
    )
    return {"schedule": schedule, "elevator": elevator}


def setup_origination_site(storage_capacity_bushels=100000, with_program=False,
                           program_overrides=None, farmer_overrides=None,
                           schedule_overrides=None, elevator_overrides=None):
    """Schedule + elevator + farmer (+ optional ACTIVE sustainability program).
    Returns {"schedule", "elevator", "farmer", "program"} (program None when
    with_program is False)."""
    site = setup_site(storage_capacity_bushels, schedule_overrides, elevator_overrides)
    farmer = create_farmer(**(farmer_overrides or {}))
    program = (
        create_active_program(**(program_overrides or {})) if with_program else None
    )
    return {
        "schedule": site["schedule"],
        "elevator": site["elevator"],
        "farmer": farmer,
        "program": program,
    }


# =============================================================================
# Tier 2 — origination contracts
# =============================================================================

def create_cash_contract(farmer_id, elevator_id, quantity_bushels=100,
                         cash_price_cents_per_bushel=1000, program_id=None,
                         headers=None, **overrides):
    """CASH contract: born pricing_status PRICED with one seeded election of
    quantity_bushels at cash_price_cents_per_bushel (PRD §3.2)."""
    payload = create_cash_contract_payload(
        farmer_id, elevator_id,
        quantity_bushels=quantity_bushels,
        cash_price_cents_per_bushel=cash_price_cents_per_bushel,
        **overrides,
    )
    if program_id is not None:
        payload["program_id"] = program_id
    resp = api_client.create_origination_contract(payload, headers or MERCH)
    return _ok("create_cash_contract", resp)


def create_basis_contract(farmer_id, elevator_id, quantity_bushels=100,
                          basis_cents_per_bushel=-25,
                          futures_month=FUTURES_MONTH_DEC, program_id=None,
                          headers=None, **overrides):
    payload = create_basis_contract_payload(
        farmer_id, elevator_id,
        quantity_bushels=quantity_bushels,
        basis_cents_per_bushel=basis_cents_per_bushel,
        futures_month=futures_month,
        **overrides,
    )
    if program_id is not None:
        payload["program_id"] = program_id
    resp = api_client.create_origination_contract(payload, headers or MERCH)
    return _ok("create_basis_contract", resp)


def create_deferred_contract(farmer_id, elevator_id, quantity_bushels=100,
                             futures_month=FUTURES_MONTH_DEC,
                             pricing_deadline="2026-12-15T00:00:00Z",
                             storage_rate_cents_per_bushel_day=1,
                             program_id=None, headers=None, **overrides):
    payload = create_deferred_contract_payload(
        farmer_id, elevator_id,
        quantity_bushels=quantity_bushels,
        futures_month=futures_month,
        pricing_deadline=pricing_deadline,
        storage_rate_cents_per_bushel_day=storage_rate_cents_per_bushel_day,
        **overrides,
    )
    if program_id is not None:
        payload["program_id"] = program_id
    resp = api_client.create_origination_contract(payload, headers or MERCH)
    return _ok("create_deferred_contract", resp)


def read_contract(contract_id, headers=None):
    resp = api_client.get_origination_contract(contract_id, headers or MERCH)
    return _ok("read_contract", resp)


# =============================================================================
# Tier 2 — delivery tickets and the apply cascade (PRD §3.3)
# =============================================================================

def create_ticket(contract_id, gross_bushels=100, moisture_pct=13.0,
                  damage_pct=0, foreign_material_pct=0, headers=None, **overrides):
    """Create a scale ticket in RECEIVED against a contract."""
    resp = api_client.create_delivery_ticket(
        create_delivery_ticket_payload(
            contract_id,
            gross_bushels=gross_bushels,
            moisture_pct=moisture_pct,
            damage_pct=damage_pct,
            foreign_material_pct=foreign_material_pct,
            **overrides,
        ),
        headers or MERCH,
    )
    return _ok("create_ticket", resp)


def apply_ticket(ticket_id, headers=None):
    """Grade and apply (or moisture-reject) a RECEIVED ticket. Returns the
    post-apply ticket."""
    resp = api_client.apply_delivery_ticket(ticket_id, headers or MERCH)
    return _ok("apply_ticket", resp)


def create_and_apply_ticket(contract_id, gross_bushels=100, moisture_pct=13.0,
                            damage_pct=0, foreign_material_pct=0, headers=None,
                            **overrides):
    """Create a ticket and apply it in one step. Returns the applied ticket."""
    ticket = create_ticket(contract_id, gross_bushels, moisture_pct, damage_pct,
                           foreign_material_pct, headers=headers, **overrides)
    return apply_ticket(ticket["id"], headers=headers)


# =============================================================================
# Tier 3 — pricing elections and settlement (PRD §3.4)
# =============================================================================

def elect_price(contract_id, bushels, headers=None):
    """Read the contract's current version and post a pricing election with
    the correct OCC token. Returns the updated contract. For a Farmer caller
    pass headers=make_farmer_headers(farmer_id)."""
    hdrs = headers or MERCH
    contract = read_contract(contract_id, headers=hdrs)
    resp = api_client.create_pricing_election(
        contract_id,
        {"bushels": bushels, "expected_contract_version": contract["version"]},
        hdrs,
    )
    return _ok("elect_price", resp)


def price_contract_in_full(contract_id, headers=None):
    """Elect every remaining unpriced bushel in a single election, moving
    pricing to PRICED."""
    contract = read_contract(contract_id, headers=headers or MERCH)
    remaining = contract["quantity_bushels"] - contract["priced_bushels"]
    return elect_price(contract_id, remaining, headers=headers)


def settle_contract(contract_id, headers=None):
    resp = api_client.settle_origination_contract(contract_id, headers or MERCH)
    return _ok("settle_contract", resp)


# =============================================================================
# Tier 3/4 — contract lifecycle composites
# =============================================================================

def setup_delivered_cash_contract(quantity_bushels=100,
                                  cash_price_cents_per_bushel=1000,
                                  storage_capacity_bushels=100000,
                                  program_id=None):
    """Site + farmer + CASH contract with one clean ticket exactly filling it:
    fulfillment OPEN -> DELIVERED in one hop, pricing born PRICED.
    Returns {"site", "contract", "ticket"}; contract is refreshed post-apply."""
    site = setup_origination_site(storage_capacity_bushels=storage_capacity_bushels)
    contract = create_cash_contract(
        site["farmer"]["id"], site["elevator"]["id"],
        quantity_bushels=quantity_bushels,
        cash_price_cents_per_bushel=cash_price_cents_per_bushel,
        program_id=program_id,
    )
    ticket = create_and_apply_ticket(contract["id"], gross_bushels=quantity_bushels)
    return {
        "site": site,
        "contract": read_contract(contract["id"]),
        "ticket": ticket,
    }


def setup_settled_cash_contract(quantity_bushels=100,
                                cash_price_cents_per_bushel=1000):
    """Full lifecycle: DELIVERED + PRICED -> settle -> SETTLED (PRD §3.4).
    Returns {"site", "contract", "ticket"}; contract is SETTLED."""
    base = setup_delivered_cash_contract(quantity_bushels, cash_price_cents_per_bushel)
    settled = settle_contract(base["contract"]["id"])
    return {"site": base["site"], "contract": settled, "ticket": base["ticket"]}


def setup_deferred_contract_delivered_unpriced(
        quantity_bushels=1000, delivered_bushels=None,
        storage_rate_cents_per_bushel_day=2,
        pricing_deadline="2026-12-15T00:00:00Z",
        futures_month=FUTURES_MONTH_DEC,
        bean_price_cents=1200,
        bean_quote_date=LOGICAL_CLOCK_START,
        apply_clock=None):
    """DEFERRED contract with delivered-but-unpriced bushels in the accrual
    pool (PRD §3.4). Optionally advances the clock to apply_clock before the
    ticket apply so the accrual anchors at a chosen date. The BEAN futures
    quote for futures_month is posted at bean_quote_date when bean_price_cents
    is not None. Returns {"site", "contract", "ticket", "quote"}."""
    site = setup_origination_site()
    quote = None
    if bean_price_cents is not None:
        quote = post_bean_quote(futures_month, bean_price_cents, bean_quote_date)
    contract = create_deferred_contract(
        site["farmer"]["id"], site["elevator"]["id"],
        quantity_bushels=quantity_bushels,
        futures_month=futures_month,
        pricing_deadline=pricing_deadline,
        storage_rate_cents_per_bushel_day=storage_rate_cents_per_bushel_day,
    )
    if apply_clock is not None:
        set_clock(apply_clock)
    gross = delivered_bushels if delivered_bushels is not None else quantity_bushels
    ticket = create_and_apply_ticket(contract["id"], gross_bushels=gross)
    return {
        "site": site,
        "contract": read_contract(contract["id"]),
        "ticket": ticket,
        "quote": quote,
    }


def setup_settled_deferred_contract(quantity_bushels=1000,
                                    storage_rate_cents_per_bushel_day=2,
                                    pricing_deadline="2026-12-15T00:00:00Z",
                                    futures_month=FUTURES_MONTH_DEC,
                                    bean_price_cents=1200,
                                    election_price_cents=1250,
                                    apply_clock="2026-09-10T00:00:00Z",
                                    election_clock="2026-09-20T00:00:00Z"):
    """Full DEFERRED lifecycle: deliver the full quantity at apply_clock, then
    re-quote and price in full at election_clock, then settle.
    Returns {"site", "contract", "ticket"}; contract is SETTLED."""
    base = setup_deferred_contract_delivered_unpriced(
        quantity_bushels=quantity_bushels,
        storage_rate_cents_per_bushel_day=storage_rate_cents_per_bushel_day,
        pricing_deadline=pricing_deadline,
        futures_month=futures_month,
        bean_price_cents=bean_price_cents,
        apply_clock=apply_clock,
    )
    set_clock(election_clock)
    if election_price_cents is not None:
        post_bean_quote(futures_month, election_price_cents, election_clock)
    price_contract_in_full(base["contract"]["id"])
    settled = settle_contract(base["contract"]["id"])
    return {"site": base["site"], "contract": settled, "ticket": base["ticket"]}


# =============================================================================
# Tier 2 — freight lanes, routing, shipments (PRD §3.5)
# =============================================================================

def create_truck_lane(origin_elevator_id, destination_plant_id, headers=None,
                      **overrides):
    resp = api_client.create_freight_lane(
        create_freight_lane_payload(origin_elevator_id, destination_plant_id,
                                    mode="TRUCK", **overrides),
        headers or LOGISTICS,
    )
    return _ok("create_truck_lane", resp)


def create_rail_lane(origin_elevator_id, destination_plant_id, headers=None,
                     **overrides):
    resp = api_client.create_freight_lane(
        create_freight_lane_payload(origin_elevator_id, destination_plant_id,
                                    mode="RAIL", **overrides),
        headers or LOGISTICS,
    )
    return _ok("create_rail_lane", resp)


def create_barge_lane(origin_elevator_id, destination_plant_id, transit_days=5,
                      daily_capacity_bushels=1, headers=None, **overrides):
    """BARGE lane: daily_capacity_bushels is ignored for barges (interval
    occupancy governs, PRD §3.5) — the default of 1 proves that."""
    resp = api_client.create_freight_lane(
        create_freight_lane_payload(
            origin_elevator_id, destination_plant_id,
            mode="BARGE", transit_days=transit_days,
            daily_capacity_bushels=daily_capacity_bushels, **overrides,
        ),
        headers or LOGISTICS,
    )
    return _ok("create_barge_lane", resp)


def book_shipment(lane_id, bushels, departure_date="2026-09-10T00:00:00Z",
                  certified_program_id=None, headers=None, **overrides):
    from .factories import create_shipment_payload
    payload = create_shipment_payload(lane_id, bushels,
                                      departure_date=departure_date, **overrides)
    if certified_program_id is not None:
        payload["certified_program_id"] = certified_program_id
    resp = api_client.create_shipment(payload, headers or LOGISTICS)
    return _ok("book_shipment", resp)


def read_shipment(shipment_id, headers=None):
    resp = api_client.get_shipment(shipment_id, headers or LOGISTICS)
    return _ok("read_shipment", resp)


def deliver_shipment_now(shipment_id, headers=None):
    """POST deliver without touching the clock — the caller must already have
    advanced the clock to >= arrival_date (PRD §3.5 ERR_SHIPMENT_NOT_ARRIVED)."""
    resp = api_client.deliver_shipment(shipment_id, headers or LOGISTICS)
    return _ok("deliver_shipment_now", resp)


def deliver_shipment_after_arrival(shipment_id, headers=None):
    """Advance the logical clock to the shipment's arrival_date, then deliver.
    NB: the advance runs the deadline sweep (PRD §3.9) — tests with live
    DEFERRED contracts / sales windows / hedge positions should drive the
    clock themselves and use deliver_shipment_now instead."""
    shipment = read_shipment(shipment_id, headers=headers)
    set_clock(shipment["arrival_date"])
    return deliver_shipment_now(shipment_id, headers=headers)


def cancel_shipment(shipment_id, headers=None):
    resp = api_client.cancel_shipment(shipment_id, headers or LOGISTICS)
    return _ok("cancel_shipment", resp)


# =============================================================================
# Tier 2/4 — elevator storage composites
# =============================================================================

def setup_elevator_with_stored_bushels(bushels, certified=False,
                                       storage_capacity_bushels=100000,
                                       program_overrides=None):
    """Site (+ optional program) with a contract whose full quantity is
    applied via one clean ticket, leaving `bushels` stored at the elevator.
    Returns {"site", "contract", "ticket"}; site["program"] holds the program
    when certified=True."""
    site = setup_origination_site(
        storage_capacity_bushels=storage_capacity_bushels,
        with_program=certified,
        program_overrides=program_overrides,
    )
    program_id = site["program"]["id"] if certified else None
    contract = create_cash_contract(
        site["farmer"]["id"], site["elevator"]["id"],
        quantity_bushels=bushels, program_id=program_id,
    )
    ticket = create_and_apply_ticket(contract["id"], gross_bushels=bushels)
    return {"site": site, "contract": read_contract(contract["id"]), "ticket": ticket}


def setup_elevator_with_mixed_lots(certified_bushels=3000, conventional_bushels=2000,
                                   storage_capacity_bushels=100000):
    """One certified lot and one conventional lot at the same elevator
    (chain-of-custody scenarios, PRD §3.5). Returns {"site", "certified",
    "conventional"} where each value is {"contract", "ticket"}."""
    site = setup_origination_site(
        storage_capacity_bushels=storage_capacity_bushels, with_program=True
    )
    cert_contract = create_cash_contract(
        site["farmer"]["id"], site["elevator"]["id"],
        quantity_bushels=certified_bushels, program_id=site["program"]["id"],
    )
    cert_ticket = create_and_apply_ticket(cert_contract["id"],
                                          gross_bushels=certified_bushels)
    plain_contract = create_cash_contract(
        site["farmer"]["id"], site["elevator"]["id"],
        quantity_bushels=conventional_bushels,
    )
    plain_ticket = create_and_apply_ticket(plain_contract["id"],
                                           gross_bushels=conventional_bushels)
    return {
        "site": site,
        "certified": {"contract": cert_contract, "ticket": cert_ticket},
        "conventional": {"contract": plain_contract, "ticket": plain_ticket},
    }


# =============================================================================
# Tier 4 — plant bean inventory (ticket apply -> storage lot -> lane -> ship ->
# deliver credits CrushPlant.bean_inventory_bushels, PRD §3.5)
# =============================================================================

def setup_plant_with_bean_inventory(bushels=10000, storage_capacity_bushels=100000,
                                    lane_overrides=None):
    """Full chain crediting a plant's bean inventory: site + CASH contract +
    clean ticket applied + TRUCK lane + shipment + clock to arrival + deliver.
    Returns {"site", "plant", "contract", "lane", "shipment"}."""
    site = setup_origination_site(storage_capacity_bushels=storage_capacity_bushels)
    plant = create_crush_plant()
    contract = create_cash_contract(
        site["farmer"]["id"], site["elevator"]["id"], quantity_bushels=bushels
    )
    create_and_apply_ticket(contract["id"], gross_bushels=bushels)
    lane = create_truck_lane(site["elevator"]["id"], plant["id"],
                             **(lane_overrides or {}))
    shipment = book_shipment(lane["id"], bushels,
                             departure_date="2026-09-02T00:00:00Z")
    delivered = deliver_shipment_after_arrival(shipment["id"])
    return {
        "site": site,
        "plant": plant,
        "contract": contract,
        "lane": lane,
        "shipment": delivered,
    }


# =============================================================================
# Tier 2/3 — crush runs (PRD §3.6)
# =============================================================================

def create_crush_run(plant_id, run_date="2026-09-10T00:00:00Z",
                     planned_bushels=1000, futures_month=FUTURES_MONTH_NOV,
                     headers=None, **overrides):
    """Plan a run; creation computes the PLANNED margin from as-of quotes.
    run_date may be in the past — only scheduling rejects that (PRD §3.6)."""
    resp = api_client.create_crush_run(
        create_crush_run_payload(plant_id, run_date=run_date,
                                 planned_bushels=planned_bushels,
                                 futures_month=futures_month, **overrides),
        headers or SCHEDULER,
    )
    return _ok("create_crush_run", resp)


def read_crush_run(run_id, headers=None):
    resp = api_client.get_crush_run(run_id, headers or SCHEDULER)
    return _ok("read_crush_run", resp)


def schedule_run(run_id, expected_run_version=None, headers=None):
    """Schedule a PLANNED run; reads the current version when the caller does
    not pin an OCC token."""
    hdrs = headers or SCHEDULER
    if expected_run_version is None:
        expected_run_version = read_crush_run(run_id, headers=hdrs)["version"]
    resp = api_client.schedule_crush_run(
        run_id, schedule_crush_run_payload(expected_run_version), hdrs
    )
    return _ok("schedule_run", resp)


def transition_run(run_id, to_status, headers=None):
    """Drive a run lifecycle transition: PLANNED (revert), RUNNING, COMPLETE,
    or CANCELLED."""
    resp = api_client.transition_crush_run(
        run_id, transition_crush_run_payload(to_status), headers or SCHEDULER
    )
    return _ok("transition_run", resp)


def setup_scheduled_run(plant_id=None, run_date="2026-09-10T00:00:00Z",
                        planned_bushels=1000, futures_month=FUTURES_MONTH_NOV,
                        plant_overrides=None):
    """Plant (created when plant_id is None) + canonical quote triple + run
    scheduled onto run_date. Returns {"plant", "run", "quotes"}."""
    plant = create_crush_plant(**(plant_overrides or {})) if plant_id is None else None
    pid = plant_id or plant["id"]
    quotes = post_crush_quote_set(futures_month)
    run = create_crush_run(pid, run_date=run_date, planned_bushels=planned_bushels,
                           futures_month=futures_month)
    scheduled = schedule_run(run["id"], expected_run_version=run["version"])
    return {"plant": plant, "run": scheduled, "quotes": quotes}


def setup_running_run(planned_bushels=1000, run_date="2026-09-10T00:00:00Z",
                      futures_month=FUTURES_MONTH_NOV):
    """Plant holding enough bean inventory + run driven SCHEDULED -> RUNNING
    (consumes plant inventory, PRD §3.6). Returns {"plant", "run", "base"}."""
    base = setup_plant_with_bean_inventory(bushels=planned_bushels)
    quotes = post_crush_quote_set(futures_month)
    run = create_crush_run(base["plant"]["id"], run_date=run_date,
                           planned_bushels=planned_bushels,
                           futures_month=futures_month)
    schedule_run(run["id"], expected_run_version=run["version"])
    running = transition_run(run["id"], "RUNNING")
    return {"plant": base["plant"], "run": running, "base": base,
            "quotes": quotes}


# =============================================================================
# Tier 2/3 — board crush positions and segregation of duties (PRD §3.7)
# =============================================================================

def enter_board_position(trader_user_id=CRUSH_TRADER_USER_ID,
                         futures_month=FUTURES_MONTH_NOV, bean_lots_long=2,
                         oil_lots_short=2, meal_lots_short=2,
                         expiry_date="2026-11-13T00:00:00Z", **overrides):
    """Enter a hedge as CrushTrader with an explicit operator id (the id is
    recorded as entered_by_user_id). Requires the quote triple to be on file."""
    resp = api_client.create_board_crush_position(
        create_board_position_payload(
            futures_month=futures_month, bean_lots_long=bean_lots_long,
            oil_lots_short=oil_lots_short, meal_lots_short=meal_lots_short,
            expiry_date=expiry_date, **overrides,
        ),
        make_crush_trader_headers(trader_user_id),
    )
    return _ok("enter_board_position", resp)


def confirm_board_position(position_id, risk_manager_user_id=RISK_MANAGER_USER_ID):
    """Confirm an ENTERED position as RiskManager. The confirmer's user id
    must differ from entered_by_user_id (ERR_SEGREGATION_OF_DUTIES)."""
    resp = api_client.confirm_board_crush_position(
        position_id, make_risk_manager_headers(risk_manager_user_id)
    )
    return _ok("confirm_board_position", resp)


def offset_board_position(position_id, trader_user_id=CRUSH_TRADER_USER_ID):
    resp = api_client.offset_board_crush_position(
        position_id, make_crush_trader_headers(trader_user_id)
    )
    return _ok("offset_board_position", resp)


def setup_board_position_entered(trader_user_id=CRUSH_TRADER_USER_ID,
                                 futures_month=FUTURES_MONTH_NOV, **overrides):
    """Canonical quote triple + one ENTERED position. Returns
    {"position", "quotes"}."""
    quotes = post_crush_quote_set(futures_month)
    position = enter_board_position(trader_user_id=trader_user_id,
                                    futures_month=futures_month, **overrides)
    return {"position": position, "quotes": quotes}


def setup_board_position_confirmed(trader_user_id=CRUSH_TRADER_USER_ID,
                                   risk_manager_user_id=RISK_MANAGER_USER_ID,
                                   futures_month=FUTURES_MONTH_NOV, **overrides):
    """ENTERED -> CONFIRMED with two distinct operators (segregation of
    duties). Returns {"position", "quotes"}."""
    base = setup_board_position_entered(trader_user_id, futures_month, **overrides)
    confirmed = confirm_board_position(base["position"]["id"], risk_manager_user_id)
    return {"position": confirmed, "quotes": base["quotes"]}


# =============================================================================
# Tier 2/3/5 — product sales contracts, deliveries, defaults (PRD §3.8/§3.9)
# =============================================================================

def create_sales_contract(buyer_id, plant_id, product="SOY_OIL", headers=None,
                          **overrides):
    resp = api_client.create_product_sales_contract(
        create_sales_contract_payload(buyer_id, plant_id, product=product,
                                      **overrides),
        headers or PRODUCT_MERCH,
    )
    return _ok("create_sales_contract", resp)


def read_sales_contract(contract_id, headers=None):
    resp = api_client.get_product_sales_contract(contract_id,
                                                 headers or PRODUCT_MERCH)
    return _ok("read_sales_contract", resp)


def record_delivery(contract_id, delivery_date, quantity_lbs, product="SOY_OIL",
                    actual_protein_pct=None, actual_ffa_pct=None, headers=None,
                    **overrides):
    """Record a delivery against a sales contract (returns 201 — each call
    appends an immutable entry to the delivery log, PRD §3.8/§4)."""
    payload = create_sales_delivery_payload(
        delivery_date, quantity_lbs, product=product, **overrides
    )
    if actual_protein_pct is not None:
        payload["actual_protein_pct"] = actual_protein_pct
    if actual_ffa_pct is not None:
        payload["actual_ffa_pct"] = actual_ffa_pct
    resp = api_client.deliver_product_sales_contract(contract_id, payload,
                                                     headers or PRODUCT_MERCH)
    return _ok("record_delivery", resp)


def read_buyer(buyer_id, headers=None):
    resp = api_client.get_buyer(buyer_id, headers or PRODUCT_MERCH)
    return _ok("read_buyer", resp)


def setup_sales_scenario(product="SOY_OIL", buyer_overrides=None,
                         plant_overrides=None, **contract_overrides):
    """Buyer + plant + one sales contract. Returns {"buyer", "plant",
    "contract"}."""
    buyer = create_buyer(**(buyer_overrides or {}))
    plant = create_crush_plant(**(plant_overrides or {}))
    contract = create_sales_contract(buyer["id"], plant["id"], product=product,
                                     **contract_overrides)
    return {"buyer": buyer, "plant": plant, "contract": contract}


def setup_defaulted_sales_contract(quantity_lbs=1000, price_cents_per_lb=20,
                                   product="SOY_OIL",
                                   window_start="2026-09-15T00:00:00Z",
                                   window_end="2026-09-30T00:00:00Z",
                                   sweep_to="2026-10-01T00:00:00Z"):
    """Sales contract left undelivered past its window, then the clock sweep
    defaults it (PRD §3.9 phase two). Returns {"buyer", "plant", "contract"}
    with the contract refreshed post-sweep (status DEFAULTED)."""
    base = setup_sales_scenario(
        product=product,
        quantity_lbs=quantity_lbs,
        price_cents_per_lb=price_cents_per_lb,
        delivery_window_start=window_start,
        delivery_window_end=window_end,
    )
    set_clock(sweep_to)
    return {
        "buyer": read_buyer(base["buyer"]["id"]),
        "plant": base["plant"],
        "contract": read_sales_contract(base["contract"]["id"]),
    }


def setup_suspended_buyer(num_contracts=BUYER_SUSPEND_CLAIM_THRESHOLD,
                          quantity_lbs=1000, price_cents_per_lb=20,
                          window_start="2026-09-15T00:00:00Z",
                          window_end="2026-09-30T00:00:00Z",
                          sweep_to="2026-10-01T00:00:00Z"):
    """Buyer driven to SUSPENDED: `num_contracts` undelivered sales contracts
    default in one sweep, crossing the three-open-claims threshold
    (PRD §3.9). Returns {"buyer", "plant", "contracts"}; buyer is refreshed
    post-sweep with status SUSPENDED."""
    buyer = create_buyer()
    plant = create_crush_plant()
    contracts = [
        create_sales_contract(
            buyer["id"], plant["id"],
            quantity_lbs=quantity_lbs, price_cents_per_lb=price_cents_per_lb,
            delivery_window_start=window_start, delivery_window_end=window_end,
        )
        for _ in range(num_contracts)
    ]
    set_clock(sweep_to)
    return {
        "buyer": read_buyer(buyer["id"]),
        "plant": plant,
        "contracts": [read_sales_contract(c["id"]) for c in contracts],
    }


__all__ = [
    "set_clock",
    "reset_clock",
    "create_published_schedule",
    "create_draft_schedule",
    "create_active_program",
    "close_program",
    "create_farmer",
    "create_buyer",
    "create_crush_plant",
    "create_elevator",
    "post_market_quote",
    "post_bean_quote",
    "post_crush_quote_set",
    "setup_site",
    "setup_origination_site",
    "create_cash_contract",
    "create_basis_contract",
    "create_deferred_contract",
    "read_contract",
    "create_ticket",
    "apply_ticket",
    "create_and_apply_ticket",
    "elect_price",
    "price_contract_in_full",
    "settle_contract",
    "setup_delivered_cash_contract",
    "setup_settled_cash_contract",
    "setup_deferred_contract_delivered_unpriced",
    "setup_settled_deferred_contract",
    "create_truck_lane",
    "create_rail_lane",
    "create_barge_lane",
    "book_shipment",
    "read_shipment",
    "deliver_shipment_now",
    "deliver_shipment_after_arrival",
    "cancel_shipment",
    "setup_elevator_with_stored_bushels",
    "setup_elevator_with_mixed_lots",
    "setup_plant_with_bean_inventory",
    "create_crush_run",
    "read_crush_run",
    "schedule_run",
    "transition_run",
    "setup_scheduled_run",
    "setup_running_run",
    "enter_board_position",
    "confirm_board_position",
    "offset_board_position",
    "setup_board_position_entered",
    "setup_board_position_confirmed",
    "create_sales_contract",
    "read_sales_contract",
    "record_delivery",
    "read_buyer",
    "setup_sales_scenario",
    "setup_defaulted_sales_contract",
    "setup_suspended_buyer",
]
