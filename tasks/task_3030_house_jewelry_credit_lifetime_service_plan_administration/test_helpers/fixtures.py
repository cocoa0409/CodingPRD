"""Composite setup helpers for multi-step test prerequisites.

Every helper uses ``get_success_data`` so a broken precondition surfaces as a
clear "Setup failed" error rather than a confusing assertion failure. All
setup is rebuilt from scratch: the harness restarts the server before each
test, so nothing is carried over between tests.
"""

from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ALL_STATES_KEY,
    DEFAULT_BUNDLE,
    DEFAULT_TX_REGULATION,
    LOGICAL_CLOCK_START,
    PROMO_CODE_TERMS,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["chain_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
ANALYST = TEST_USERS["credit_analyst_headers"]
ASSOCIATE = TEST_USERS["sales_associate_headers"]
AFTERCARE = TEST_USERS["customer_service_headers"]


# ---------------------------------------------------------------------------
# Tier 1: State progression
# ---------------------------------------------------------------------------


def reset_clock(to_iso8601: str = LOGICAL_CLOCK_START):
    """Move the logical clock. Every deadline rule reads this instant."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def setup_store(state_code: str = "TX", activate: bool = True,
                credit_capacity_cents: int = 5_000_000, **overrides):
    """Open a store, optionally activating it. Returns the store row.

    PRD §3.4 makes activation conditional on a resolvable risk-registry row
    ("A store in `OPEN` moves to `ACTIVE` on activation, which requires at
    least one registry row available on its state code or the global
    fallback."), so an activating call must supply a prerequisite row unless
    the caller has declared one of its own. A state-scoped row is registered
    first when the state is absent, and a chain-wide fallback row (keyed by
    the `all_states_key` sentinel) covers the states that deliberately have
    no state row.
    """
    payload = {
        "store_code": "0142",
        "name": "Highland Village",
        "state_code": state_code,
        "credit_capacity_cents": credit_capacity_cents,
    }
    payload.update(overrides)
    store = get_success_data(api_client.create_store(payload, ADMIN), 201)
    if activate:
        rows = get_success_data(api_client.list_registry_rows(ADMIN))
        known = {row["registry_key"] for row in rows}
        if state_code not in known and ALL_STATES_KEY not in known:
            setup_registry_row(registry_key=state_code, credit_tier="TIER_3",
                               base_limit_cents=2_000_000, min_down_payment_pct=0.10,
                               min_ticket_cents=200_000)
        store = get_success_data(api_client.activate_store(store["id"], ADMIN))
    return store


def setup_customer(state_code: str = "TX", **overrides):
    """Create a customer file. Returns the customer row."""
    payload = {
        "full_name": "Nina Ortiz",
        "email": overrides.pop("email", "nina.ortiz@example.com"),
        "state_code": state_code,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_customer(payload, ASSOCIATE), 201)


def setup_registry_row(registry_key: str = "TX", credit_tier: str = "TIER_3",
                       base_limit_cents: int = 2_000_000,
                       min_down_payment_pct: float = 0.10,
                       min_ticket_cents: int = 200_000, **overrides):
    payload = {
        "registry_key": registry_key,
        "credit_tier": credit_tier,
        "base_limit_cents": base_limit_cents,
        "min_down_payment_pct": min_down_payment_pct,
        "registry_type": "STATE" if registry_key != "*" else "GLOBAL",
        "min_ticket_cents": min_ticket_cents,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_registry_row(payload, ADMIN), 201)


def setup_regulation(**overrides):
    payload = dict(DEFAULT_TX_REGULATION)
    payload.update(overrides)
    return get_success_data(api_client.create_regulation(payload, ADMIN), 201)


def setup_bundle(**overrides):
    payload = dict(DEFAULT_BUNDLE)
    payload.update(overrides)
    return get_success_data(api_client.create_bundle(payload, ADMIN), 201)


def setup_vendor_shop(shop_code: str = "JEWELCRAFT", shop_name: str = "Jewelcraft Bench",
                      base_turnaround_days: int = 7, rush_surcharge_cents: int = 4_000,
                      **overrides):
    payload = {
        "shop_code": shop_code,
        "shop_name": shop_name,
        "base_turnaround_days": base_turnaround_days,
        "rush_surcharge_cents": rush_surcharge_cents,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_vendor_shop(payload, ADMIN), 201)


def setup_diamond(stone_code: Optional[str] = None, **overrides):
    payload = {"stone_code": stone_code or "ST-0001", "stone_kind": "NATURAL", "carat": 0.90}
    payload.update(overrides)
    return get_success_data(api_client.create_diamond(payload, ASSOCIATE), 201)


def setup_diamond_in_custody(stone_kind: str = "NATURAL", carat: float = 0.90, **overrides):
    payload = {
        "stone_code": overrides.pop("stone_code", "ST-0002"),
        "stone_kind": stone_kind,
        "carat": carat,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_diamond(payload, ASSOCIATE), 201)


def setup_approved_customer(store=None, state_code: str = "TX",
                            requested_limit_cents: int = 1_000_000,
                            base_limit_cents: int = 2_000_000,
                            min_down_payment_pct: float = 0.10,
                            requested_purchase_amount_cents: int = 450_018,
                            down_payment_cents: int = 45_002):
    """Customer opened to OPEN/TIER_3 by an approved application.

    Returns (customer, store, application).
    """
    if store is None:
        store = setup_store(state_code=state_code)
    setup_regulation(state_code=state_code)
    setup_registry_row(registry_key=state_code, credit_tier="TIER_3",
                       base_limit_cents=base_limit_cents,
                       min_down_payment_pct=min_down_payment_pct)
    customer = setup_customer(state_code=state_code)
    application = create_application(customer, store,
                                     requested_limit_cents=requested_limit_cents,
                                     requested_purchase_amount_cents=requested_purchase_amount_cents,
                                     down_payment_cents=down_payment_cents)
    application = get_success_data(
        api_client.decide_credit_application(application["id"],
                                             {"decision": "APPROVE_FULL"}, ANALYST)
    )
    customer = get_success_data(api_client.get_customer(customer["id"], AFTERCARE))
    return customer, store, application


def setup_credit_environment(state_code: str = "TX"):
    """Store + regulation + registry row + customer. Returns (store, customer)."""
    store = setup_store(state_code=state_code)
    setup_regulation(state_code=state_code)
    setup_registry_row(registry_key=state_code, credit_tier="TIER_3",
                       base_limit_cents=2_000_000, min_down_payment_pct=0.10)
    customer = setup_customer(state_code=state_code)
    return store, customer


def setup_tier1_environment(state_code: str = "TX", base_limit_cents: int = 400_000,
                            min_down_payment_pct: float = 0.20):
    """Store + regulation + TIER_1 row + customer. Returns (store, customer)."""
    store = setup_store(state_code=state_code)
    setup_regulation(state_code=state_code)
    setup_registry_row(registry_key=state_code, credit_tier="TIER_1",
                       base_limit_cents=base_limit_cents,
                       min_down_payment_pct=min_down_payment_pct,
                       min_ticket_cents=200_000)
    customer = setup_customer(state_code=state_code)
    return store, customer


def create_application(customer, store, requested_limit_cents: int = 300_000,
                       requested_purchase_amount_cents: int = 300_000,
                       down_payment_cents: int = 30_000, **overrides):
    payload = {
        "customer_id": customer["id"],
        "store_id": store["id"],
        "requested_limit_cents": requested_limit_cents,
        "requested_purchase_amount_cents": requested_purchase_amount_cents,
        "down_payment_cents": down_payment_cents,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_credit_application(payload, ASSOCIATE), 201)


def create_addressed_application(customer, store, decision: str = "APPROVE_FULL",
                                 requested_limit_cents: int = 300_000,
                                 requested_purchase_amount_cents: int = 300_000,
                                 down_payment_cents: int = 30_000, **overrides):
    """Application that has already received a decision."""
    application = create_application(
        customer, store,
        requested_limit_cents=requested_limit_cents,
        requested_purchase_amount_cents=requested_purchase_amount_cents,
        down_payment_cents=down_payment_cents, **overrides,
    )
    return get_success_data(
        api_client.decide_credit_application(application["id"], {"decision": decision}, ANALYST)
    )


def open_customer(customer, store, requested_limit_cents: int = 2_000_000,
                  requested_purchase_amount_cents: int = 450_018,
                  down_payment_cents: int = 45_002, **overrides):
    """Drive a freshly created customer file to `account_status` `OPEN`.

    PRD §3.1: a newly created customer carries `account_status` of `NO_FILE`,
    and PRD §3.3 / §3.5 make an open account the posture prerequisite for
    carrying a new registration or completing a purchase. Fixtures that need
    an obligation-bearing customer must therefore open the file first with an
    approved application, rather than asserting on a posture the PRD forbids.

    PRD §2.6 makes the governing regulation row a prerequisite of the credit
    decision itself, and PRD §2.4 makes a resolvable registry row a
    prerequisite of the approval, so both are supplied here when the caller
    has not already done so.
    """
    state_code = customer["state_code"]
    _ensure_regulation(state_code)
    rows = get_success_data(api_client.list_registry_rows(ADMIN))
    if not any(row["registry_key"] == state_code for row in rows):
        setup_registry_row(registry_key=state_code, credit_tier="TIER_3",
                           base_limit_cents=2_000_000, min_down_payment_pct=0.10,
                           min_ticket_cents=200_000)
    application = create_addressed_application(
        customer, store, decision="APPROVE_FULL",
        requested_limit_cents=requested_limit_cents,
        requested_purchase_amount_cents=requested_purchase_amount_cents,
        down_payment_cents=down_payment_cents, **overrides)
    opened = get_success_data(api_client.get_customer(customer["id"], AFTERCARE))
    return opened, application


def _ensure_regulation(state_code: str = "TX"):
    """Register the governing regulation row for a state when none exists."""
    from .constants import DEFAULT_TX_REGULATION
    rows = get_success_data(api_client.list_regulations(ADMIN))
    if any(row["state_code"] == state_code for row in rows):
        return None
    payload = dict(DEFAULT_TX_REGULATION)
    payload["state_code"] = state_code
    return get_success_data(api_client.create_regulation(payload, ADMIN), 201)


# ---------------------------------------------------------------------------
# Tier 2: Entity hierarchy
# ---------------------------------------------------------------------------


def setup_purchase(customer, store, base_price_cents: int = 450_018,
                   diamond=None, **overrides):
    payload = {
        "customer_id": customer["id"],
        "store_id": store["id"],
        "base_price_cents": base_price_cents,
    }
    if diamond is not None:
        payload["diamond_id"] = diamond["id"]
    payload.update(overrides)
    return get_success_data(api_client.create_purchase(payload, ASSOCIATE), 201)


def setup_completed_purchase(customer, store, base_price_cents: int = 450_018,
                             diamond=None, **overrides):
    """Purchase walked all the way to COMPLETED."""
    purchase = setup_purchase(customer, store, base_price_cents=base_price_cents,
                              diamond=diamond, **overrides)
    return get_success_data(api_client.complete_purchase(purchase["id"], ASSOCIATE))


def setup_registration(customer, store, purchase, diamond, bundle,
                       plan_term_months: int = 24, **overrides):
    payload = {
        "customer_id": customer["id"],
        "purchase_id": purchase["id"],
        "diamond_id": diamond["id"],
        "store_id": store["id"],
        "bundle_id": bundle["id"],
        "plan_term_months": plan_term_months,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_registration(payload, MANAGER), 201)


def setup_active_registration(visit_at: str = "2026-09-10T00:00:00Z", **overrides):
    """Full graph through to a registration in ACTIVE coverage.

    Returns (customer, store, diamond, bundle, purchase, registration).
    """
    reset_clock(LOGICAL_CLOCK_START)
    setup_regulation()
    store = setup_store(**overrides.pop("store", {}))
    customer = setup_customer()
    customer, _ = open_customer(customer, store)
    bundle = setup_bundle(**overrides.pop("bundle", {}))
    diamond = setup_diamond(**overrides.pop("diamond", {}))
    purchase = setup_completed_purchase(customer, store, base_price_cents=450_018,
                                        diamond=diamond)
    registration = setup_registration(customer, store, purchase, diamond, bundle,
                                      **overrides.pop("registration", {}))
    registration = get_success_data(
        api_client.log_inspection_exam(registration["id"],
                                       {"visit_at": visit_at, "result": "CLAIMED"}, MANAGER)
    )
    return customer, store, diamond, bundle, purchase, registration


def setup_plan_environment(plan_code: str = "PROMO_12_6M",
                           base_price_cents: int = 450_000,
                           requested_limit_cents: int = 1_000_000,
                           bundle_id: Optional[str] = None):
    """Open customer + store + purchase + promotional plan.

    Returns (customer, store, purchase, plan).
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, _ = setup_approved_customer(
        requested_limit_cents=requested_limit_cents,
        requested_purchase_amount_cents=base_price_cents,
        down_payment_cents=base_price_cents // 10,
    )
    diamond = setup_diamond()
    purchase_payload = {
        "customer_id": customer["id"],
        "store_id": store["id"],
        "base_price_cents": base_price_cents,
        "diamond_id": diamond["id"],
    }
    if bundle_id is not None:
        purchase_payload["bundle_id"] = bundle_id
    purchase = get_success_data(api_client.create_purchase(purchase_payload, ASSOCIATE), 201)
    purchase = get_success_data(api_client.get_purchase(purchase["id"], ASSOCIATE))
    plan = get_success_data(api_client.create_promotional_plan({
        "customer_id": customer["id"],
        "purchase_id": purchase["id"],
        "plan_code": plan_code,
        "expected_purchase_version": purchase["version"],
    }, ASSOCIATE), 201)
    return customer, store, purchase, plan


# ---------------------------------------------------------------------------
# Tier 3: Full lifecycle shortcuts
# ---------------------------------------------------------------------------


def setup_repair(customer, store, diamond, registration, **overrides):
    payload = {
        "customer_id": customer["id"],
        "store_id": store["id"],
        "diamond_id": diamond["id"],
        "registration_id": registration["id"],
        "failure_class": "SETTING",
        "declared_parts_cents": 40_000,
        "declared_labor_cents": 15_000,
        "declared_loss_liability_cents": 5_000,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_repair(payload, MANAGER), 201)


def create_repair_in_qc_review(**overrides):
    """Registration ACTIVE + shop + routed repair sitting in QC_REVIEW.

    Returns (customer, store, diamond, registration, repair).
    """
    shop_code = overrides.pop("shop_code", "JEWELCRAFT")
    failure_class = overrides.pop("failure_class", "SETTING")
    customer, store, diamond, bundle, purchase, registration = setup_active_registration(
        **overrides.pop("active", {})
    )
    # PRD §2.7 needs the routing table's target shop in the directory; register
    # the requested shop, plus MALCA when it is not already the requested one
    # (a duplicate shop_code is a 409 per PRD §3.4).
    if shop_code != "MALCA":
        setup_vendor_shop(shop_code=shop_code)
        setup_vendor_shop(shop_code="MALCA", shop_name="Malca Stone Bench",
                          base_turnaround_days=12, rush_surcharge_cents=6_000)
    else:
        setup_vendor_shop(shop_code="MALCA", shop_name="Malca Stone Bench",
                          base_turnaround_days=12, rush_surcharge_cents=6_000)
    repair = setup_repair(customer, store, diamond, registration,
                          failure_class=failure_class,
                          **overrides.pop("repair", {}))
    get_success_data(api_client.route_repair(repair["id"], MANAGER))
    get_success_data(api_client.arrive_repair_at_vendor(repair["id"], MANAGER))
    repair = get_success_data(api_client.submit_repair_for_qc(repair["id"], MANAGER))
    return customer, store, diamond, registration, repair


def setup_repair_completed(**overrides):
    """Repair walked through QC_REVIEW to COMPLETED.

    Returns (customer, store, diamond, registration, repair).
    """
    customer, store, diamond, registration, repair = create_repair_in_qc_review(**overrides)
    repair = get_success_data(api_client.verify_repair(repair["id"], MANAGER))
    return customer, store, diamond, registration, repair


def setup_repair_routed(**overrides):
    """Registration ACTIVE + shop + repair sitting in ROUTED.

    Returns (customer, store, diamond, registration, repair).
    """
    shop_code = overrides.pop("shop_code", "JEWELCRAFT")
    customer, store, diamond, bundle, purchase, registration = setup_active_registration(
        **overrides.pop("active", {})
    )
    setup_vendor_shop(shop_code=shop_code)
    repair = setup_repair(customer, store, diamond, registration,
                          **overrides.pop("repair", {}))
    repair = get_success_data(api_client.route_repair(repair["id"], MANAGER))
    return customer, store, diamond, registration, repair


def setup_completed_repair_with_registered_graph(**overrides):
    """Alias kept explicit for readability at call sites."""
    return setup_repair_completed(**overrides)


def setup_registration_awaiting_lapse(sweep_instant: str = "2027-06-15T00:00:00Z",
                                      **overrides):
    """A registration the reminder sweep has parked in `REMINDER_ISSUED`.

    PRD §3.3 lapses only a registration sitting in `PENDING_INSPECTION` or
    `REMINDER_ISSUED`, and the reminder sweep is what moves a registration into
    `REMINDER_ISSUED` once its due instant comes within the 14-day lead. This
    helper walks that half of the cycle from an unclaimed registration —
    `PENDING_INSPECTION` -> `REMINDER_ISSUED`, spawning the cycle's one
    scheduled visit — and leaves the clock at the sweep instant so a following
    lapse sweep fires.

    Returns (customer, store, diamond, registration).
    """
    customer, store, diamond, bundle, purchase, registration = setup_pending_registration(
        **overrides.pop("pending", {}))
    current = get_success_data(api_client.get_registration(registration["id"], MANAGER))
    reset_clock(current["inspection_due_at"])
    get_success_data(api_client.run_inspection_reminders(MANAGER))
    reset_clock(sweep_instant)
    registration = get_success_data(api_client.get_registration(registration["id"], MANAGER))
    return customer, store, diamond, registration


def setup_lapsed_registration(customer=None, store=None, diamond=None,
                              bundle=None, purchase=None, registration=None, **overrides):
    """A registration whose cure deadline has passed and been swept to LAPSED.

    Returns (customer, store, diamond, registration).
    """
    if registration is None:
        customer, store, diamond, registration = setup_registration_awaiting_lapse(**overrides)
    else:
        reset_clock(overrides.pop("sweep_instant", "2027-06-15T00:00:00Z"))
    get_success_data(api_client.lapse_registrations_due(ANALYST))
    registration = get_success_data(api_client.get_registration(registration["id"], MANAGER))
    return customer, store, diamond, registration


def setup_pending_registration(**overrides):
    """Registration in PENDING_INSPECTION with nothing claimed yet.

    Returns (customer, store, diamond, bundle, purchase, registration).
    """
    reset_clock(LOGICAL_CLOCK_START)
    setup_regulation()
    store = setup_store()
    customer = setup_customer()
    customer, _ = open_customer(customer, store)
    bundle = setup_bundle()
    diamond = setup_diamond()
    purchase = setup_completed_purchase(customer, store, base_price_cents=450_018,
                                        diamond=diamond)
    registration = setup_registration(customer, store, purchase, diamond, bundle)
    return customer, store, diamond, bundle, purchase, registration


def setup_trade_up_graph(new_base_price_cents: int = 900_100,
                         origin_base_price_cents: int = 450_018,
                         additional_credit_cents: Optional[int] = None,
                         with_bundle: bool = False):
    """Origin purchase + new trade-up purchase naming it.

    Returns (customer, store, origin, new_purchase, origin_diamond, new_diamond).
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, _ = setup_approved_customer(
        requested_limit_cents=1_500_000,
        requested_purchase_amount_cents=new_base_price_cents,
        down_payment_cents=new_base_price_cents // 10,
    )
    origin_diamond = setup_diamond(stone_code="ST-0001")
    new_diamond = setup_diamond(stone_code="ST-0002", carat=1.25,
                                origin_registry="KIMBERLEY-TX-9911")
    origin = setup_purchase(customer, store, base_price_cents=origin_base_price_cents,
                            diamond=origin_diamond)
    origin = get_success_data(api_client.complete_purchase(origin["id"], ASSOCIATE))
    if additional_credit_cents is not None:
        get_success_data(api_client.stamp_trade_up_credit(
            origin["id"], {"additional_credit_cents": additional_credit_cents}, AFTERCARE
        ))
    payload = {
        "customer_id": customer["id"],
        "store_id": store["id"],
        "base_price_cents": new_base_price_cents,
        "diamond_id": new_diamond["id"],
        "origin_purchase_id": origin["id"],
    }
    if with_bundle:
        bundle = setup_bundle(bundle_code="BUNDLE_180_TA")
        payload["bundle_id"] = bundle["id"]
    new_purchase = get_success_data(api_client.create_purchase(payload, ASSOCIATE), 201)
    return customer, store, origin, new_purchase, origin_diamond, new_diamond


def setup_design_order(estimate_amount_cents: int = 250_000,
                       deposit_pct: float = 0.40, revisions: int = 0,
                       approve: bool = False, in_production: bool = False):
    """Customer + store + custom commission walked to the requested stage."""
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store()
    customer = setup_customer()
    customer, _ = open_customer(customer, store)
    order = get_success_data(api_client.create_custom_design_order({
        "customer_id": customer["id"],
        "store_id": store["id"],
        "estimate_amount_cents": estimate_amount_cents,
        "deposit_pct": deposit_pct,
    }, ASSOCIATE), 201)
    for _ in range(revisions):
        get_success_data(api_client.request_cad_revision(
            order["id"], make_customer_headers(customer["id"])))
    if approve:
        get_success_data(api_client.approve_cad(
            order["id"], make_customer_headers(customer["id"])))
    if in_production:
        get_success_data(api_client.start_design_production(order["id"], MANAGER))
    order = get_success_data(api_client.get_custom_design_order(order["id"], MANAGER))
    return customer, store, order


def setup_defaulted_plan_and_registration():
    """Customer with a DEFAULTED plan, a PENDING application and a lapsed registration.

    Returns a dict of the graph nodes used by the cascade assertions.
    """
    reset_clock(LOGICAL_CLOCK_START)
    setup_regulation()
    store = setup_store()
    setup_registry_row(registry_key="TX", credit_tier="TIER_3",
                       base_limit_cents=2_000_000, min_down_payment_pct=0.10)
    customer = setup_customer()
    application = create_addressed_application(
        customer, store, decision="APPROVE_FULL",
        requested_limit_cents=1_000_000,
        requested_purchase_amount_cents=450_018, down_payment_cents=45_002)
    customer = get_success_data(api_client.get_customer(customer["id"], AFTERCARE))
    diamond = setup_diamond(stone_code="ST-0021")
    bundle = setup_bundle()
    purchase = setup_purchase(customer, store, base_price_cents=450_018, diamond=diamond)
    purchase = get_success_data(api_client.get_purchase(purchase["id"], ASSOCIATE))
    plan = get_success_data(api_client.create_promotional_plan({
        "customer_id": customer["id"],
        "purchase_id": purchase["id"],
        "plan_code": "PROMO_12_6M",
        "expected_purchase_version": purchase["version"],
    }, ASSOCIATE), 201)
    registration = setup_registration(customer, store, purchase, diamond, bundle)
    get_success_data(api_client.create_ledger_entry({
        "plan_id": plan["id"],
        "entry_kind": "INSTALLMENT",
        "direction": "DECREASE",
        "amount_cents": 112_500,
        "adjustment_cents": -112_500,
        "reference_bucket": "PROMOTIONAL",
        "expected_plan_version": get_success_data(
            api_client.get_promotional_plan(plan["id"], MANAGER))["version"],
    }, AFTERCARE), 201)
    application2 = create_application(
        customer, store, requested_limit_cents=800_000,
        requested_purchase_amount_cents=700_000, down_payment_cents=70_000)
    # PRD §3.7 hop four lapses the registrations the customer holds in
    # `PENDING_INSPECTION`, so the registration is left there rather than being
    # advanced by a reminder sweep. PRD §3.7 also requires the instant to be
    # strictly more than 90 days past `simplicity_expires_at`; a plan created on
    # 2026-09-01 with a 12-month window closes on 2027-09-01, so the sweep runs
    # on a later instant.
    reset_clock("2027-12-15T00:00:00Z")
    get_success_data(api_client.default_plans_due(ANALYST))
    return {
        "customer": customer,
        "store": store,
        "plan": plan,
        "registration": registration,
        "application2": application2,
        "diamond": diamond,
        "purchase": purchase,
    }


# ---------------------------------------------------------------------------
# Tier 4: Accumulation / threshold targeting
# ---------------------------------------------------------------------------


def setup_with_origin_credit(new_base_price_cents: int = 900_100,
                             origin_base_price_cents: int = 450_018,
                             origin_trade_up_credit_cents: int = 10_050):
    """Trade-up console whose origin already carries a bonus-bearing credit.

    Returns (customer, store, origin, new_purchase).
    """
    customer, store, origin, new_purchase, _, _ = setup_trade_up_graph(
        new_base_price_cents=new_base_price_cents,
        origin_base_price_cents=origin_base_price_cents,
        additional_credit_cents=origin_trade_up_credit_cents,
    )
    return customer, store, origin, new_purchase


def setup_store_over_capacity(credit_capacity_cents: int = 1_100,
                              first_parts_cents: int = 15_000,
                              first_labor_cents: int = 0,
                              first_failure_class: str = "OTHER"):
    """An `ACTIVE` store whose open repair liability has outrun its capacity.

    PRD §3.4 suspends a store only "when its `open_repair_liability_cents` has
    outrun its `available_credit_capacity_cents`", so a fixture that wants to
    exercise the suspend/reinstate cycle must first book a repair whose pinned
    liability exceeds the store's remaining capacity.

    Returns (customer, store, diamond, registration, first_repair).
    """
    customer, store, diamond, registration, first_repair = setup_store_near_capacity(
        credit_capacity_cents=credit_capacity_cents,
        first_parts_cents=first_parts_cents,
        first_labor_cents=first_labor_cents,
        first_failure_class=first_failure_class)
    store = get_success_data(api_client.get_store(store["id"], MANAGER))
    return customer, store, diamond, registration, first_repair


def setup_store_near_capacity(credit_capacity_cents: int = 20_000,
                              first_parts_cents: int = 15_000,
                              first_labor_cents: int = 0,
                              first_failure_class: str = "OTHER"):
    """Store whose remaining credit capacity is already partly consumed.

    Returns (customer, store, diamond, registration, first_repair).
    """
    reset_clock(LOGICAL_CLOCK_START)
    setup_regulation()
    store = setup_store(credit_capacity_cents=credit_capacity_cents)
    customer = setup_customer()
    customer, _ = open_customer(customer, store)
    bundle = setup_bundle()
    diamond = setup_diamond()
    purchase = setup_completed_purchase(customer, store, base_price_cents=400_000,
                                        diamond=diamond)
    registration = setup_registration(customer, store, purchase, diamond, bundle)
    registration = get_success_data(api_client.log_inspection_exam(
        registration["id"], {"visit_at": "2026-09-10T00:00:00Z", "result": "CLAIMED"}, MANAGER))
    first_repair = get_success_data(api_client.create_repair({
        "customer_id": customer["id"],
        "store_id": store["id"],
        "diamond_id": diamond["id"],
        "registration_id": registration["id"],
        "failure_class": first_failure_class,
        "declared_parts_cents": first_parts_cents,
        "declared_labor_cents": first_labor_cents,
    }, MANAGER), 201)
    return customer, store, diamond, registration, first_repair


def setup_registration_at_day_offset(day_offset: int, interval_days: int = 180,
                                     cure_days: int = 30,
                                     registered_at: str = "2026-03-05T00:00:00Z"):
    """A registration whose clock has been advanced `day_offset` whole days.

    Returns (customer, store, registration) with the clock left at the target.
    """
    reset_clock(registered_at)
    setup_regulation()
    store = setup_store()
    customer = setup_customer()
    customer, _ = open_customer(customer, store)
    bundle = setup_bundle(inspection_interval_days=interval_days,
                          inspection_cure_days=cure_days)
    diamond = setup_diamond()
    purchase = setup_completed_purchase(customer, store, base_price_cents=400_000,
                                        diamond=diamond)
    registration = setup_registration(customer, store, purchase, diamond, bundle)
    advanced = _add_days(registered_at, day_offset)
    reset_clock(advanced)
    return customer, store, registration


def setup_plan_with_accrual(elapsed_days: int = 120, principal_cents: int = 450_000,
                            plan_code: str = "PROMO_12_6M",
                            created_at: str = "2026-09-01T00:00:00Z"):
    """Plan whose deferral accrual has run `elapsed_days` whole days.

    Returns (customer, store, purchase, plan) with the clock at the target instant.
    """
    reset_clock(created_at)
    customer, store, purchase, plan = setup_plan_environment(
        plan_code=plan_code, base_price_cents=principal_cents)
    reset_clock(_add_days(created_at, elapsed_days))
    plan = get_success_data(api_client.get_promotional_plan(plan["id"], AFTERCARE))
    return customer, store, purchase, plan


def setup_plan_at_simplicity_offset(day_offset: int, plan_code: str = "PROMO_12_6M",
                                    principal_cents: int = 450_000):
    """Plan whose clock sits `day_offset` days past its created instant.

    Returns (customer, store, purchase, plan).
    """
    return setup_plan_with_accrual(elapsed_days=day_offset,
                                   principal_cents=principal_cents,
                                   plan_code=plan_code)


def _add_days(iso: str, days: int) -> str:
    """Advance an ISO instant by whole days, preserving the UTC form.

    PRD §2.12 fixes the wire format at exactly three fractional digits, so the
    rendered instant carries milliseconds and compares byte-for-byte with a
    server-returned deadline.
    """
    import datetime as _dt
    text = iso.replace("Z", "+00:00")
    instant = _dt.datetime.fromisoformat(text)
    moved = instant + _dt.timedelta(days=days)
    return moved.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def day_offset(iso: str, days: int) -> str:
    """Public alias for date arithmetic used by boundary tests."""
    return _add_days(iso, days)


# ---------------------------------------------------------------------------
# Tier 5: Finalization / terminal state
# ---------------------------------------------------------------------------


def setup_customer_ready_to_close():
    """Customer with zero balance and no live obligations.

    Returns (customer, store).
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, _ = setup_approved_customer(
        requested_purchase_amount_cents=450_018, down_payment_cents=45_002)
    return customer, store


def setup_customer_with_live_registration():
    """Customer carrying a registration in PENDING_INSPECTION.

    Returns (customer, store, registration).
    """
    customer, store, diamond, bundle, purchase, registration = setup_pending_registration()
    return customer, store, registration


def setup_customer_with_completed_repair():
    """Customer carrying a COMPLETED repair (an active obligation).

    Returns (customer, store, repair).
    """
    customer, store, diamond, registration, repair = setup_repair_completed()
    return customer, store, repair


def setup_suspended_customer():
    """Customer suspended by a defaulted plan.

    Returns (customer, store, plan).
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment()
    reset_clock("2027-10-15T00:00:00Z")
    get_success_data(api_client.default_plans_due(ANALYST))
    customer = get_success_data(api_client.get_customer(customer["id"], ANALYST))
    plan = get_success_data(api_client.get_promotional_plan(plan["id"], ANALYST))
    return customer, store, plan


def setup_terminal_registration_and_shop():
    """A repair already declared a verified loss, plus its shop directory.

    Returns (customer, store, diamond, registration, repair).
    """
    customer, store, diamond, registration, repair = create_repair_in_qc_review(
        shop_code="MALCA", failure_class="STONE_LOSS")
    repair = get_success_data(api_client.declare_repair_loss(repair["id"], MANAGER))
    return customer, store, diamond, registration, repair


__all__ = [
    "ADMIN", "MANAGER", "ANALYST", "ASSOCIATE", "AFTERCARE",
    "reset_clock",
    "setup_store", "setup_customer", "setup_registry_row", "setup_regulation",
    "setup_bundle", "setup_vendor_shop", "setup_diamond", "setup_diamond_in_custody",
    "setup_approved_customer", "setup_credit_environment", "setup_tier1_environment",
    "create_application", "create_addressed_application", "open_customer",
    "_ensure_regulation",
    "setup_purchase", "setup_completed_purchase", "setup_registration",
    "setup_active_registration", "setup_plan_environment",
    "setup_repair", "create_repair_in_qc_review", "setup_repair_completed",
    "setup_repair_routed", "setup_lapsed_registration", "setup_registration_awaiting_lapse", "setup_pending_registration",
    "setup_trade_up_graph", "setup_design_order",
    "setup_defaulted_plan_and_registration",
    "setup_with_origin_credit", "setup_store_near_capacity", "setup_store_over_capacity",
    "setup_registration_at_day_offset", "setup_plan_with_accrual",
    "setup_plan_at_simplicity_offset", "day_offset",
    "setup_customer_ready_to_close", "setup_customer_with_live_registration",
    "setup_customer_with_completed_repair", "setup_suspended_customer",
    "setup_terminal_registration_and_shop",
]