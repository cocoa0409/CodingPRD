"""Temporal semantics: interval edges, deferred sweeps and idle returns.

Each test places the logical clock exactly at the edge the rule describes, so
an implementation with the wrong edge convention is caught rather than one
with a merely wrong interval length.
"""

from test_helpers import (
    ADMIN,
    ANALYST,
    ASSOCIATE,
    AFTERCARE,
    LOGICAL_CLOCK_START,
    MANAGER,
    api_client,
    day_offset,
    get_success_data,
    reset_clock,
    setup_bundle,
    setup_customer,
    setup_diamond,
    setup_purchase,
    setup_registration,
    setup_store,
    setup_active_registration,
    setup_plan_environment,
    setup_vendor_shop,
    validate_success,
)


def test_the_store_hold_window_closes_inclusively_at_its_right_edge(
        api, customer_service_headers):
    """PRD §2.16: "`store_hold_days` (default 30, the days a completed repair is held before it is abandoned)"
    PRD §2.7: "Turnaround is measured in whole calendar days from the intake instant, and the datetime arithmetic is inclusive of the accepted instant."

    Design: Difficulty/resource_temporal_overlap/store_hold_slot_adjacency_is_inclusive
    """
    customer, store, diamond, registration, repair = _repair_completed_with_deadline()
    assert repair["pickup_deadline_at"] == "2026-10-31T00:00:00.000Z", (
        "a repair delivered on 2026-10-01 is held through 2026-10-31"
    )
    store_after = get_success_data(api.get_store(store["id"], customer_service_headers))
    assert store_after["store_hold_days"] == 30
    assert repair["repair_status"] == "COMPLETED"

    reset_clock("2026-10-31T00:00:00Z")
    report = validate_success(api.abandon_repairs_overdue(customer_service_headers), 200)
    assert report["abandoned_count"] == 1, (
        "the hold interval is closed inclusive at its right edge, so the sweep fires exactly there"
    )
    swept = get_success_data(api.get_repair(repair["id"], customer_service_headers))
    assert swept["repair_status"] == "ABANDONED"
    stone = get_success_data(api.get_diamond(diamond["id"], customer_service_headers))
    assert stone["custody_status"] == "IN_VAULT", "constructive custody returns to the store"


def test_the_sweep_abandons_the_repair_once_the_deadline_has_passed(
        api, customer_service_headers):
    """PRD §3.4: "Repairs no one collects are swept by a `CustomerService` operator. A repair in `COMPLETED` whose `pickup_deadline_at` is strictly before the current instant becomes `ABANDONED`, the store takes constructive custody of the stone with a `custody_status` of `IN_VAULT`"
    PRD §3.4: "The sweep reports `abandoned_count` and `abandoned_repair_ids`."

    Design: Difficulty/resource_temporal_overlap/store_hold_slot_adjacency_is_inclusive
    """
    customer, store, diamond, registration, repair = _repair_completed_with_deadline()
    reset_clock("2026-11-01T00:00:00Z")
    report = validate_success(api.abandon_repairs_overdue(customer_service_headers), 200)
    assert report["abandoned_count"] == 1, (
        "past the closing instant the completed repair is swept"
    )
    assert report["abandoned_repair_ids"], "the sweep names the repairs it abandoned"

    swept = get_success_data(api.get_repair(repair["id"], customer_service_headers))
    assert swept["repair_status"] == "ABANDONED"
    stone = get_success_data(api.get_diamond(diamond["id"], customer_service_headers))
    assert stone["custody_status"] == "IN_VAULT"


def test_the_sweep_is_a_no_op_before_the_deadline_is_reached(api, customer_service_headers):
    """PRD §3.4: "A repair in `COMPLETED` whose `pickup_deadline_at` is strictly before the current instant becomes `ABANDONED`"
    PRD §2.16: "Every temporal comparison in §3 — validity windows, simplicity windows, cure deadlines, pickup deadlines, overhaul overdue counts — is evaluated against this logical instant, not against the host clock."

    Design: Difficulty/resource_temporal_overlap/store_hold_slot_adjacency_is_inclusive
    """
    customer, store, diamond, registration, repair = _repair_completed_with_deadline()
    reset_clock("2026-10-30T00:00:00Z")
    report = validate_success(api.abandon_repairs_overdue(customer_service_headers), 200)
    assert report["abandoned_count"] == 0, (
        "the repair is still inside its hold window"
    )
    still_held = get_success_data(api.get_repair(repair["id"], customer_service_headers))
    assert still_held["repair_status"] == "COMPLETED"
    stone = get_success_data(api.get_diamond(diamond["id"], customer_service_headers))
    assert stone["custody_status"] == "IN_CASE"


def test_routing_stamps_the_promise_from_the_shop_base_turnaround(api, store_manager_headers):
    """PRD §2.7: "The shop's `base_turnaround_days` fixes `promised_delivery_at` as the accepted instant plus that many days — the `QUOTED_TURNAROUND` reading."
    PRD §2.7: "a `SETTING` failure that is not a rush routes to `JEWELCRAFT`; with a base turnaround of 7 days the promise lands at the accepted instant plus 7 days"

    Design: Difficulty/resource_temporal_overlap/bench_shop_transient_overbooking_allowed_against_parallel_capacity
    """
    customer, store, diamond, registration, repair = _routed_repair_environment()
    routed = get_success_data(api.get_repair(repair["id"], store_manager_headers))
    assert routed["vendor_shop_code"] == "JEWELCRAFT"
    assert routed["repair_status"] == "ROUTED"
    assert routed["promised_delivery_at"] == day_offset(routed["accepted_at"], 7)


def test_routing_is_refused_when_the_named_shop_is_absent(api, store_manager_headers):
    """PRD §2.7: "The bench shop must exist in the shop directory with `vendor_status` of `ACTIVE`; otherwise routing is refused with `ERR_VENDOR_MISSING` (HTTP 422)"
    PRD §3.4: "Routing requires the repair to be in `INTAKE` and the shop named by the routing rule to exist with a `vendor_status` of `ACTIVE`"

    Design: Difficulty/resource_temporal_overlap/bench_shop_transient_overbooking_allowed_against_parallel_capacity
    """
    from test_helpers import setup_repair
    customer, store, diamond, bundle, purchase, registration = setup_active_registration()
    repair = setup_repair(customer, store, diamond, registration, failure_class="SETTING")
    response = api.route_repair(repair["id"], store_manager_headers)
    assert response.status_code == 422
    assert response.json()["data"]["error_id"] == "ERR_VENDOR_MISSING"
    untouched = get_success_data(api.get_repair(repair["id"], store_manager_headers))
    assert untouched["repair_status"] == "INTAKE"
    assert untouched["vendor_shop_code"] is None


def test_routing_keys_the_shop_off_the_failure_class(api, store_manager_headers):
    """PRD §2.7: "When the repair is not a rush, `vendor_shop_code` comes from a fixed routing table (`ROUTE_TABLE`): `STONE_LOSS` routes to `MALCA`, `SETTING` and `PRONG` route to `JEWELCRAFT`, and `RESIZE` and `OTHER` route to `MASTERMELT`."
    PRD §2.7: "When `vendor_is_rush` is true, the routing is the constant `RUSH_SHOP_CODE` — `CONRUSH` — irrespective of failure class."

    Design: Difficulty/resource_temporal_overlap/bench_shop_transient_overbooking_allowed_against_parallel_capacity
    """
    from test_helpers import setup_repair
    customer, store, diamond, bundle, purchase, registration = setup_active_registration()
    setup_vendor_shop(shop_code="JEWELCRAFT")
    setup_vendor_shop(shop_code="MASTERMELT", shop_name="Mastermelt Bench",
                      base_turnaround_days=5)
    resize_repair = setup_repair(customer, store, diamond, registration,
                                 failure_class="RESIZE", declared_parts_cents=20_000,
                                 declared_labor_cents=9_000,
                                 declared_loss_liability_cents=0)
    routed = validate_success(api.route_repair(resize_repair["id"], store_manager_headers), 200)
    assert routed["vendor_shop_code"] == "MASTERMELT", (
        "RESIZE routes through the ROUTE_TABLE to MASTERMELT"
    )


def test_a_rush_routing_ignores_the_failure_class_table(api, store_manager_headers):
    """PRD §2.7: "The bench shop must exist in the shop directory with `vendor_status` of `ACTIVE`; otherwise routing is refused with `ERR_VENDOR_MISSING` (HTTP 422), and a rush routing additionally requires the rush shop to hold a signed alliance agreement"
    PRD §2.7: "When `vendor_is_rush` is true, the routing is the constant `RUSH_SHOP_CODE` — `CONRUSH` — irrespective of failure class."

    Design: Difficulty/resource_temporal_overlap/bench_shop_transient_overbooking_allowed_against_parallel_capacity
    """
    from test_helpers import setup_repair
    customer, store, diamond, bundle, purchase, registration = setup_active_registration()
    setup_vendor_shop(shop_code="JEWELCRAFT")
    rush_repair = setup_repair(customer, store, diamond, registration,
                               failure_class="SETTING", vendor_is_rush=True)
    get_success_data(api.create_vendor_shop({
        "shop_code": "CONRUSH", "shop_name": "Con Rush Bench", "base_turnaround_days": 2,
    }, ADMIN), 201)
    routed = validate_success(api.route_repair(rush_repair["id"], store_manager_headers), 200)
    assert routed["vendor_shop_code"] == "CONRUSH"


def test_capitalization_is_a_deferred_action_that_only_fires_past_the_window(
        api, credit_analyst_headers):
    """PRD §3.2: "Capitalization is the event the promo clock is designed around, and it belongs to a `CreditAnalyst` running a scheduled sweep. Any plan still `ACCRUING` when the current instant is strictly after `simplicity_expires_at` has its deferred interest converted into principal."
    PRD §3.2: "The sweep reports `capitalized_count` and `capitalized_plan_ids`."

    Design: Difficulty/resource_temporal_overlap/bench_shop_transient_overbooking_allowed_against_parallel_capacity
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment()
    reset_clock("2027-08-31T00:00:00Z")
    before = validate_success(api.capitalize_plans_due(credit_analyst_headers), 200)
    assert before["capitalized_count"] == 0
    still_accruing = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    assert still_accruing["plan_status"] == "ACCRUING"

    reset_clock("2027-09-02T00:00:00Z")
    after = validate_success(api.capitalize_plans_due(credit_analyst_headers), 200)
    assert after["capitalized_count"] == 1
    capitalized = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    assert capitalized["plan_status"] == "CAPITALIZED"


def test_reinstating_a_store_returns_it_to_active(
        api, chain_admin_headers, store_manager_headers):
    """PRD §3.4: "A store in `ACTIVE` is suspended by a chain-level administrator when its `open_repair_liability_cents` has outrun its `available_credit_capacity_cents`"
    PRD §3.4: "A suspended store returns to `ACTIVE` once its liability is back inside its capacity. Every one of these transitions increments the store's `version`."

    Design: Difficulty/resource_temporal_overlap/bench_shop_transient_overbooking_allowed_against_parallel_capacity
    """
    from test_helpers import setup_store_over_capacity, setup_vendor_shop
    customer, store, diamond, registration, repair = setup_store_over_capacity()
    active = get_success_data(api.get_store(store["id"], chain_admin_headers))
    assert active["store_status"] == "ACTIVE", "the fixture store starts ACTIVE"
    assert active["open_repair_liability_cents"] > active["available_credit_capacity_cents"], (
        "PRD §3.4 suspends only once the liability has outrun the capacity"
    )

    suspended = validate_success(api.suspend_store(store["id"], chain_admin_headers), 200)
    assert suspended["store_status"] == "SUSPENDED"

    # PRD §3.4: "A suspended store returns to `ACTIVE` once its liability is
    # back inside its capacity." A verified loss leaves the open-liability set,
    # so the liability drains back under the capacity.
    setup_vendor_shop(shop_code="MASTERMELT", shop_name="Mastermelt",
                      base_turnaround_days=5)
    get_success_data(api.route_repair(repair["id"], store_manager_headers))
    get_success_data(api.arrive_repair_at_vendor(repair["id"], store_manager_headers))
    get_success_data(api.submit_repair_for_qc(repair["id"], store_manager_headers))
    get_success_data(api.declare_repair_loss(repair["id"], store_manager_headers))

    drained = get_success_data(api.get_store(store["id"], chain_admin_headers))
    assert drained["open_repair_liability_cents"] <= drained["available_credit_capacity_cents"]

    reinstated = validate_success(api.reinstate_store(store["id"], chain_admin_headers), 200)
    assert reinstated["store_status"] == "ACTIVE"
    assert reinstated["version"] > active["version"], (
        "each transition increments the store's version"
    )


def _repair_completed_with_deadline():
    """A repair delivered at 2026-10-01 so its 30-day hold closes at 2026-10-31."""
    from test_helpers import create_repair_in_qc_review
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, diamond, registration, repair = create_repair_in_qc_review()
    reset_clock("2026-10-01T00:00:00Z")
    repair = get_success_data(api_client.verify_repair(repair["id"], MANAGER))
    return customer, store, diamond, registration, repair


def _routed_repair_environment():
    """A setting-class repair routed to JEWELCRAFT at a base turnaround of 7 days."""
    from test_helpers import setup_repair
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, diamond, bundle, purchase, registration = setup_active_registration()
    setup_vendor_shop(shop_code="JEWELCRAFT", base_turnaround_days=7)
    repair = setup_repair(customer, store, diamond, registration, failure_class="SETTING")
    routed = get_success_data(api_client.route_repair(repair["id"], MANAGER))
    return customer, store, diamond, registration, routed