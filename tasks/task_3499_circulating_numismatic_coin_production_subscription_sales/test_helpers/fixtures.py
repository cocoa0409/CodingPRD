"""Composite setup helpers (fixtures).

Every function takes the ApiClient as its first argument and builds its
preconditions from scratch via PRD-declared endpoints (the harness restarts
the server before every test — each test starts against an empty database).
All setup calls go through get_success_data (lenient 2xx), so a broken
precondition surfaces as a clear "Setup step failed" instead of a confusing
assertion failure.

Clock discipline (PRD §2.4): the clock is monotonic. Fixture clock arguments
default to the boot instant 2026-09-01T00:00:00Z and only ever move forward;
when a test drives several set_clock calls, each ts must be >= the previous.
A clock-set is what sweeps the four time-based transition families (program
open, program close, product release, offer expiry) — recipes that care about
ordering call set_clock twice with explicit instants.

Identity threading: Collector and BullionDealer calls use
make_collector_headers / make_bullion_dealer_headers with the real entity id;
opaque roles use the shared TEST_USERS constants.
"""
from datetime import date

from prd_bench_local_runner.testing import get_success_data

from .constants import (
    BOOT_CLOCK_UTC,
    DEFAULT_COPPER_SPOT_CENTS_PER_TONNE,
    DEFAULT_GOLD_SPOT_CENTS_PER_OZ,
)
from .factories import (
    billing_cycle_payload,
    clock_payload,
    create_allocation_payload,
    create_authorized_purchaser_payload,
    create_bullion_issue_payload,
    create_collector_payload,
    create_denomination_payload,
    create_error_coin_case_payload,
    create_fed_order_payload,
    create_metal_lot_payload,
    create_order_payload,
    create_production_run_payload,
    create_program_payload,
    create_product_payload,
    create_subscription_payload,
    create_subscription_product_payload,
    decide_design_payload,
    destroy_payload,
    inspect_payload,
    invoice_payment_payload,
    order_payment_payload,
)
from .test_users import TEST_USERS, make_bullion_dealer_headers, make_collector_headers
from .types import (
    AuthorizedPurchaserTier,
    BullionMetal,
    Commodity,
    DesignDecision,
    InspectionOutcome,
    PaymentOutcome,
    SubscriptionFrequency,
    Vault,
)

ADMIN = TEST_USERS["platform_admin_headers"]
LIAISON = TEST_USERS["fed_liaison_headers"]
PROCUREMENT = TEST_USERS["procurement_officer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]
MANAGER = TEST_USERS["program_manager_headers"]
DIRECTOR = TEST_USERS["mint_director_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# --- Clock -----------------------------------------------------------------------

def set_clock(client, to_iso8601, spot_prices=None):
    """POST /_clock/set_current_utc as PlatformAdmin; returns
    { current_utc, spot_prices }. Call twice when sweep ordering matters.
    spot_prices maps commodity/metal name -> integer cents per unit
    (per troy oz for GOLD/SILVER/PLATINUM, per tonne for COPPER/NICKEL/ZINC)."""
    resp = client.set_clock(clock_payload(to_iso8601, spot_prices), ADMIN)
    return get_success_data(resp)


def add_months(iso_date: str, months: int) -> str:
    """Advance an ISO calendar date (YYYY-MM-DD) by whole months; used for
    next_billing_date expectations (+1 MONTHLY, +3 QUARTERLY)."""
    year, month, day = (int(part) for part in iso_date.split("-"))
    month_index = (year * 12 + (month - 1)) + months
    new_year, new_month0 = divmod(month_index, 12)
    new_month = new_month0 + 1
    # Clamp the day to the target month's length.
    if new_month == 12:
        next_first = date(new_year + 1, 1, 1)
    else:
        next_first = date(new_year, new_month + 1, 1)
    last_day = (next_first.toordinal() - date(new_year, new_month, 1).toordinal())
    return date(new_year, new_month, min(day, last_day)).isoformat()


# --- Circulating side: denominations, lots, fed orders, runs (PRD §3.1-§3.3) ------

def create_denomination(client, **overrides):
    """Create a denomination (201). Default: the canonical QUARTER."""
    resp = client.create_denomination(create_denomination_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_fed_order(client, **overrides):
    """Submit a Federal Reserve order (201, SUBMITTED)."""
    resp = client.create_fed_order(create_fed_order_payload(**overrides), LIAISON)
    return get_success_data(resp)


def create_metal_lot(client, **overrides):
    """Create a procurement lot (201, ORDERED). A current spot price for the
    commodity must already exist — call set_clock with spot_prices first."""
    resp = client.create_metal_lot(create_metal_lot_payload(**overrides), PROCUREMENT)
    return get_success_data(resp)


def receive_metal_lot(client, lot_id):
    """Receive a lot (200, ORDERED -> DELIVERED); credits blank stock."""
    resp = client.receive_metal_lot(lot_id, PROCUREMENT)
    return get_success_data(resp)


def setup_denomination_with_delivered_lot(client, *, clock_ts=BOOT_CLOCK_UTC,
                                          spot_cents=DEFAULT_COPPER_SPOT_CENTS_PER_TONNE,
                                          tonnes=10, hedged=True,
                                          vault=Vault.WEST_POINT.value,
                                          denomination_overrides=None,
                                          lot_overrides=None):
    """Clock+spot, QUARTER denomination, one lot created and DELIVERED.
    Returns (denomination, lot). Default 10t x 176000 blanks/t = 1,760,000
    blanks credited. Note: denominations have no read endpoint; observe stock
    via GET /mint/reports/seigniorage (blanks_on_hand_pieces)."""
    set_clock(client, clock_ts, {Commodity.COPPER.value: spot_cents})
    denomination = create_denomination(client, **(denomination_overrides or {}))
    lot_kwargs = dict(quantity_tonnes=tonnes, vault=vault)
    if not hedged:
        lot_kwargs["locked_unit_price_cents_per_tonne"] = None
    lot_kwargs.update(lot_overrides or {})
    lot = create_metal_lot(client, **lot_kwargs)
    lot = receive_metal_lot(client, lot["id"])
    return denomination, lot


def setup_circulating_base(client, *, quantity_ordered_pieces=50000, **lot_kwargs):
    """Denomination + delivered lot + a SUBMITTED fed order (no runs yet).
    Returns (denomination, lot, fed_order)."""
    denomination, lot = setup_denomination_with_delivered_lot(client, **lot_kwargs)
    fed_order = create_fed_order(client, quantity_ordered_pieces=quantity_ordered_pieces)
    return denomination, lot, fed_order


def create_run(client, fed_order_id, **overrides):
    """Schedule a production run (201, PLANNED); flips the order SUBMITTED ->
    SCHEDULED on the first linked run."""
    resp = client.create_production_run(
        create_production_run_payload(fed_order_id=fed_order_id, **overrides), PLANNER)
    return get_success_data(resp)


def start_run(client, run_id):
    """Start a run (200; PLANNED/REWORK -> STRIKING)."""
    resp = client.start_production_run(run_id, PLANNER)
    return get_success_data(resp)


def inspect_run(client, run_id, outcome=InspectionOutcome.PASS.value, good_pieces=None):
    """Inspect a STRIKING run (200). PASS completes it; FAIL returns REWORK."""
    resp = client.inspect_production_run(run_id, inspect_payload(outcome, good_pieces), INSPECTOR)
    return get_success_data(resp)


def create_started_run(client, fed_order_id, **overrides):
    """Create + start a run. Returns the STRIKING run (fresh version,
    reserved_blanks == planned_quantity)."""
    run = create_run(client, fed_order_id, **overrides)
    return start_run(client, run["id"])


def create_completed_run(client, fed_order_id, *, good_pieces=None, **overrides):
    """Create + start + inspect PASS. good_pieces defaults to the full
    planned_quantity. Returns the COMPLETED run."""
    run = create_started_run(client, fed_order_id, **overrides)
    good = run["reserved_blanks"] if good_pieces is None else good_pieces
    return inspect_run(client, run["id"], InspectionOutcome.PASS.value, good)


def setup_quarantined_case(client, *, error_pieces=200, planned_quantity=10000,
                           good_pieces=9800, reporter_headers=None,
                           description="off-center strikes"):
    """Full circulating chain ending in a QUARANTINED error-coin case whose
    error_pieces (default 200) exactly equals the run's scrapped_pieces.
    reported_by_user_id defaults to qi-1. Returns
    (case, run, fed_order, denomination, lot)."""
    denomination, lot, fed_order = setup_circulating_base(client)
    run = create_completed_run(
        client, fed_order["id"], good_pieces=good_pieces,
        planned_quantity=planned_quantity)
    headers = reporter_headers or INSPECTOR
    resp = client.create_error_coin_case(
        create_error_coin_case_payload(
            production_run_id=run["id"], error_pieces=error_pieces,
            description=description),
        headers)
    case = get_success_data(resp)
    return case, run, fed_order, denomination, lot


def destroy_case(client, case_id, primary_id, secondary_id, headers=None):
    """Certify destruction (200) with two distinct certifier ids, neither the
    reporter. Caller picks the DestructionCertifier headers (default dc-1)."""
    resp = client.destroy_error_coin_case(
        case_id, destroy_payload(primary_id, secondary_id),
        headers or TEST_USERS["destruction_certifier_1_headers"])
    return get_success_data(resp)


# --- Catalog side: products, collectors, orders (PRD §3.6) -------------------------

def create_product(client, **overrides):
    """Create a product (201, SCHEDULED)."""
    resp = client.create_product(create_product_payload(**overrides), MANAGER)
    return get_success_data(resp)


def setup_on_sale_product(client, *, sweep_ts="2026-09-01T00:05:00Z",
                          release_datetime="2026-08-15T00:00:00Z", **overrides):
    """Create a program-less product whose release lies in the past, then sweep
    the clock forward to flip it ON_SALE. Returns the refreshed ON_SALE
    product. sweep_ts must be >= the current clock."""
    product = create_product(client, release_datetime=release_datetime, **overrides)
    set_clock(client, sweep_ts)
    resp = client.get_product(product["id"], MANAGER)
    return get_success_data(resp)


def create_collector(client, **overrides):
    """Register a collector (201; Anonymous is the only caller)."""
    resp = client.create_collector(create_collector_payload(**overrides), ANONYMOUS)
    return get_success_data(resp)


def create_collectors(client, n, *, household_ids=None):
    """Register n collectors. household_ids (list, len >= n) assigns shared
    households; default gives each collector a distinct household."""
    collectors = []
    for i in range(n):
        kwargs = {}
        if household_ids is not None:
            kwargs["household_id"] = household_ids[i]
        collectors.append(create_collector(client, **kwargs))
    return collectors


def place_order(client, product_id, collector, quantity):
    """Place an order (201) as the given collector (identity threaded from the
    entity id). Returns the order."""
    resp = client.create_order(
        create_order_payload(product_id=product_id, quantity=quantity),
        make_collector_headers(collector["id"]))
    return get_success_data(resp)


def pay_order(client, order, collector, amount_cents=None):
    """Pay an order (200) as its owner; amount defaults to exact total_cents."""
    amount = order["total_cents"] if amount_cents is None else amount_cents
    resp = client.pay_order(order["id"], order_payment_payload(amount),
                            make_collector_headers(collector["id"]))
    return get_success_data(resp)


def place_and_pay_order(client, product_id, collector, quantity):
    """Order (ALLOCATED) + pay. Returns the PAID/COMPLETED order."""
    order = place_order(client, product_id, collector, quantity)
    return pay_order(client, order, collector)


def get_order(client, order_id, headers=None):
    resp = client.get_order(order_id, headers or MANAGER)
    return get_success_data(resp)


def get_product(client, product_id, headers=None):
    resp = client.get_product(product_id, headers or MANAGER)
    return get_success_data(resp)


# --- Subscriptions (PRD §3.7) -------------------------------------------------------

def setup_subscription(client, *, units_per_cycle=2,
                       frequency=SubscriptionFrequency.MONTHLY.value,
                       price_cents=None, sweep_ts="2026-09-01T00:05:00Z",
                       product_overrides=None, collector_overrides=None):
    """Subscription-eligible product ON_SALE + collector + ACTIVE subscription.
    Enrollment initializes next_billing_date to the current clock date, so the
    first billing cycle is immediately due. Returns
    (product, collector, subscription)."""
    product_kwargs = dict(product_overrides or {})
    if price_cents is not None:
        product_kwargs["price_cents"] = price_cents
    resp = client.create_product(
        create_subscription_product_payload(**product_kwargs), MANAGER)
    product = get_success_data(resp)
    set_clock(client, sweep_ts)
    resp = client.get_product(product["id"], MANAGER)
    product = get_success_data(resp)
    collector = create_collector(client, **(collector_overrides or {}))
    resp = client.create_subscription(
        create_subscription_payload(
            product_id=product["id"], units_per_cycle=units_per_cycle,
            frequency=frequency),
        make_collector_headers(collector["id"]))
    subscription = get_success_data(resp)
    return product, collector, subscription


def get_subscription(client, subscription_id, headers=None):
    resp = client.get_subscription(subscription_id, headers or ADMIN)
    return get_success_data(resp)


def run_billing_cycle(client, subscription):
    """Run one billing cycle (201 invoice) with a FRESH OCC version taken from
    the supplied subscription dict. Returns (invoice, refreshed_subscription)."""
    resp = client.run_billing_cycle(
        subscription["id"],
        billing_cycle_payload(subscription["version"]), ADMIN)
    invoice = get_success_data(resp)
    return invoice, get_subscription(client, subscription["id"])


def setup_billed_subscription(client, **kwargs):
    """setup_subscription + one billing cycle. Returns
    (product, collector, subscription_refreshed, invoice); the refreshed
    subscription carries the post-cycle version for further OCC calls."""
    product, collector, subscription = setup_subscription(client, **kwargs)
    invoice, subscription = run_billing_cycle(client, subscription)
    return product, collector, subscription, invoice


def pay_invoice(client, invoice, collector, outcome=PaymentOutcome.SUCCEEDED.value):
    """Attempt invoice payment (200) as the subscribing collector (ownership
    gate: X-User-ID == subscription.collector_id)."""
    resp = client.pay_invoice(invoice["id"], invoice_payment_payload(outcome),
                              make_collector_headers(collector["id"]))
    return get_success_data(resp)


def setup_dunning_subscription(client, **kwargs):
    """Billed subscription + one FAILED attempt -> invoice FAILED (attempts 1),
    subscription DUNNING. Returns (product, collector, subscription, invoice)."""
    product, collector, subscription, invoice = setup_billed_subscription(client, **kwargs)
    invoice = pay_invoice(client, invoice, collector, PaymentOutcome.FAILED.value)
    subscription = get_subscription(client, subscription["id"])
    return product, collector, subscription, invoice


def setup_written_off_subscription(client, **kwargs):
    """Three FAILED attempts -> invoice WRITTEN_OFF (attempts 3), subscription
    CANCELLED_NONPAYMENT. Returns (product, collector, subscription, invoice)."""
    product, collector, subscription, invoice = setup_dunning_subscription(client, **kwargs)
    invoice = pay_invoice(client, invoice, collector, PaymentOutcome.FAILED.value)
    invoice = pay_invoice(client, invoice, collector, PaymentOutcome.FAILED.value)
    subscription = get_subscription(client, subscription["id"])
    return product, collector, subscription, invoice


# --- Commemorative programs (PRD §3.5) ----------------------------------------------

def create_program(client, creator_headers=None, **overrides):
    """Create a program (201, DESIGN_REVIEW). created_by_user_id comes from the
    creator's X-User-ID — default pm-1 (pass finance/other headers to vary)."""
    resp = client.create_program(create_program_payload(**overrides),
                                 creator_headers or MANAGER)
    return get_success_data(resp)


def approve_program(client, program_id, decision=DesignDecision.APPROVED.value):
    """MintDirector design decision (200)."""
    resp = client.decide_design(program_id, decide_design_payload(decision), DIRECTOR)
    return get_success_data(resp)


def setup_approved_program(client, **overrides):
    """Program approved into APPROVED_FOR_SALE (clock untouched)."""
    program = create_program(client, **overrides)
    return approve_program(client, program["id"])


def setup_on_sale_program(client, *, window_start="2026-09-15T00:00:00Z", **overrides):
    """Approved program swept to ON_SALE at its sales_window_start (inclusive).
    window_start must be >= the current clock."""
    overrides.setdefault("sales_window_start", window_start)
    program = setup_approved_program(client, **overrides)
    set_clock(client, window_start)
    resp = client.get_program(program["id"], MANAGER)
    return get_success_data(resp)


def setup_sales_closed_program(client, *, window_start="2026-09-15T00:00:00Z",
                               window_end="2026-12-31T00:00:00Z", **overrides):
    """ON_SALE program swept to SALES_CLOSED at its sales_window_end."""
    overrides.setdefault("sales_window_end", window_end)
    program = setup_on_sale_program(client, window_start=window_start, **overrides)
    set_clock(client, window_end)
    resp = client.get_program(program["id"], MANAGER)
    return get_success_data(resp)


def setup_program_with_paid_sales(client, *, units=400, price_cents=5000,
                                  program_overrides=None, product_overrides=None,
                                  window_start="2026-09-15T00:00:00Z",
                                  product_release="2026-09-16T00:00:00Z"):
    """Program ON_SALE + one product sold `units` units to one household, PAID.
    Clock: window_start sweep (program opens), then product_release sweep
    (product opens). Returns (program_refreshed, product, collector, order).
    The refreshed program reflects gross_receipts / surcharge accrual."""
    program = setup_approved_program(client, **(program_overrides or {}))
    product_kwargs = dict(product_overrides or {})
    product_kwargs.setdefault("mintage_limit", units)
    product_kwargs.setdefault("household_order_limit", units)
    product = create_product(client, program_id=program["id"],
                             price_cents=price_cents,
                             release_datetime=product_release,
                             **product_kwargs)
    set_clock(client, window_start)
    set_clock(client, product_release)
    collector = create_collector(client)
    order = place_and_pay_order(client, product["id"], collector, units)
    resp = client.get_program(program["id"], FINANCE)
    return get_success_data(resp), product, collector, order


def disburse_surcharges(client, program_id, headers=None):
    """Disburse surcharges (200) as FinanceOfficer (default fin-1, never the
    default creator pm-1)."""
    resp = client.disburse_surcharges(program_id, headers or FINANCE)
    return get_success_data(resp)


# --- Bullion (PRD §3.8) ---------------------------------------------------------------

def create_authorized_purchaser(client, tier=AuthorizedPurchaserTier.T1.value, **overrides):
    """Register an authorized purchaser (201, APPROVED)."""
    resp = client.create_authorized_purchaser(
        create_authorized_purchaser_payload(tier=tier, **overrides), ADMIN)
    return get_success_data(resp)


def set_ap_status(client, ap_id, to_status):
    """MintDirector set-status transition (200)."""
    resp = client.set_authorized_purchaser_status(ap_id, {"to_status": to_status}, DIRECTOR)
    return get_success_data(resp)


def setup_bullion_issue(client, *, clock_ts=BOOT_CLOCK_UTC,
                        metal=BullionMetal.GOLD.value,
                        spot_cents=DEFAULT_GOLD_SPOT_CENTS_PER_OZ,
                        creator_headers=None, **overrides):
    """Clock + metal spot, then a bullion issue (201, ACTIVE, version 1).
    Returns the issue dict — its `version` is the current OCC observation."""
    set_clock(client, clock_ts, {metal: spot_cents})
    resp = client.create_bullion_issue(
        create_bullion_issue_payload(metal=metal, **overrides),
        creator_headers or MANAGER)
    return get_success_data(resp)


def get_bullion_issue(client, issue_id, headers=None):
    resp = client.get_bullion_issue(issue_id, headers or MANAGER)
    return get_success_data(resp)


def create_allocation_offer(client, issue, ap, quantity_units, offerer_headers=None):
    """Offer an allocation (201, OFFERED) with the OCC field taken from
    issue["version"] — the caller's current observation. Returns
    (allocation, refreshed_issue) so the test always holds the new version."""
    resp = client.create_allocation(
        issue["id"],
        create_allocation_payload(
            authorized_purchaser_id=ap["id"], quantity_units=quantity_units,
            expected_bullion_issue_version=issue["version"]),
        offerer_headers or MANAGER)
    allocation = get_success_data(resp)
    return allocation, get_bullion_issue(client, issue["id"])


def confirm_allocation(client, allocation, ap):
    """Dealer confirm (200) with entity-backed identity (X-User-ID == the
    allocation's authorized_purchaser_id). Returns the CONFIRMED allocation
    carrying total_price_cents."""
    resp = client.confirm_allocation(allocation["id"], make_bullion_dealer_headers(ap["id"]))
    return get_success_data(resp)


def settle_allocation(client, allocation, settler_headers=None):
    """FinanceOfficer settle (200). Default settler fin-1; segregation of
    duties requires settler id != the allocation's offered_by_user_id."""
    resp = client.settle_allocation(allocation["id"], settler_headers or FINANCE)
    return get_success_data(resp)


def setup_confirmed_allocation(client, *, quantity_units=50,
                               tier=AuthorizedPurchaserTier.T1.value,
                               issue_kwargs=None, spot_cents=DEFAULT_GOLD_SPOT_CENTS_PER_OZ,
                               clock_ts=BOOT_CLOCK_UTC):
    """Issue + APPROVED purchaser + offer + dealer confirm. Returns
    (issue, ap, confirmed_allocation, refreshed_issue)."""
    issue = setup_bullion_issue(client, clock_ts=clock_ts, spot_cents=spot_cents,
                                **(issue_kwargs or {}))
    ap = create_authorized_purchaser(client, tier=tier)
    allocation, issue = create_allocation_offer(client, issue, ap, quantity_units)
    allocation = confirm_allocation(client, allocation, ap)
    refreshed = get_bullion_issue(client, issue["id"])
    return issue, ap, allocation, refreshed


def setup_settled_allocation(client, *, settler_headers=None, **kwargs):
    """setup_confirmed_allocation + settle. Returns
    (issue, ap, settled_allocation, refreshed_issue)."""
    issue, ap, allocation, _ = setup_confirmed_allocation(client, **kwargs)
    allocation = settle_allocation(client, allocation, settler_headers)
    refreshed = get_bullion_issue(client, issue["id"])
    return issue, ap, allocation, refreshed
