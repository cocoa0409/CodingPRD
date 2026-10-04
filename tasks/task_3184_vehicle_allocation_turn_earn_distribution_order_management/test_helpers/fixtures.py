"""Composite setup helpers (PRD §3). Each builds preconditions from scratch via
PRD-declared endpoints only; every test runs against a freshly started server."""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_allocation_run_payload,
    create_appeal_payload,
    create_carrier_payload,
    create_commodity_payload,
    create_commodity_restriction_payload,
    create_dealer_payload,
    create_dealer_trade_payload,
    create_incentive_program_payload,
    create_model_line_payload,
    create_order_payload,
    create_region_payload,
    create_shipment_payload,
)
from .test_users import TEST_USERS, make_dealer_headers

ALLOC = TEST_USERS["allocator_headers"]
SCHED = TEST_USERS["scheduler_headers"]
LOGIS = TEST_USERS["logistics_headers"]
COMM = TEST_USERS["commodity_manager_headers"]

_uid_counter = [0]


def _uniq(prefix: str) -> str:
    _uid_counter[0] += 1
    return f"{prefix}-{_uid_counter[0]}"


# ---------------------------------------------------------------------------
# Tier 1/2: catalog + run fixtures
# ---------------------------------------------------------------------------

def create_region(code=None, name=None):
    code = code or _uniq("RG")
    data = get_success_data(api_client.create_region(create_region_payload(code=code, name=name or code), ALLOC))
    return data


def create_dealer(region_id, dealer_code=None, opened_on=None, name=None):
    dealer_code = dealer_code or _uniq("D")
    data = get_success_data(
        api_client.create_dealer(
            create_dealer_payload(region_id, dealer_code=dealer_code, name=name or dealer_code,
                                  opened_on=opened_on or TEST_DEFAULTS["OLD_OPENED_ON"]),
            ALLOC,
        )
    )
    return data


def create_model_line(model_code=None, name=None):
    model_code = model_code or _uniq("ML")
    return get_success_data(api_client.create_model_line(create_model_line_payload(model_code=model_code, name=name or model_code), ALLOC))


def create_commodity(code=None, name=None):
    code = code or _uniq("CM")
    return get_success_data(api_client.create_commodity(create_commodity_payload(code=code, name=name or code), COMM))


def create_restriction(commodity_id, model_line_id, **overrides):
    return get_success_data(
        api_client.create_commodity_restriction(
            create_commodity_restriction_payload(commodity_id, model_line_id, **overrides), COMM
        )
    )


def create_run(model_line_id, **overrides):
    return get_success_data(
        api_client.create_allocation_run(create_allocation_run_payload(model_line_id, **overrides), ALLOC)
    )


def create_published_run(model_line_id, **overrides):
    """Create + publish a run. Returns the PUBLISHED run."""
    run = create_run(model_line_id, **overrides)
    return get_success_data(api_client.publish_allocation_run(run["id"], ALLOC))


def get_dealer_allocation(run_id, dealer_id):
    """Fetch the DealerAllocation row for (run, dealer) via the filtered
    global list (paginated-safe)."""
    resp = api_client.list_dealer_allocations(ALLOC, params={"run_id": run_id, "dealer_id": dealer_id})
    rows = get_success_data(resp)
    assert len(rows) == 1, f"expected exactly one DealerAllocation for ({run_id}, {dealer_id})"
    return rows[0]


def list_run_dealer_allocations(run_id):
    return get_success_data(
        api_client.list_dealer_allocations(ALLOC, params={"run_id": run_id, "limit": 100})
    )


def setup_dealer_run(num_dealers=1, base_units=10, opened_on=None, retail_priority_pct=0, **run_overrides):
    """Region + N dealers + model line + PUBLISHED run.
    Returns dict(region, dealers[list], model_line, run)."""
    region = create_region()
    dealers = [create_dealer(region["id"], opened_on=opened_on) for _ in range(num_dealers)]
    model_line = create_model_line()
    run = create_published_run(model_line["id"], base_units=base_units,
                               retail_priority_pct=retail_priority_pct, **run_overrides)
    return {"region": region, "dealers": dealers, "model_line": model_line, "run": run}


# ---------------------------------------------------------------------------
# Tier 3: order lifecycle fixtures
# ---------------------------------------------------------------------------

def submit_order(dealer_id, model_line_id, run_id, order_kind="STOCK",
                 configuration=None, customer_ref=None):
    """Create an order, re-reading the DealerAllocation version first (§2.6).
    Returns the raw response so callers can inspect accept vs reject."""
    da = get_dealer_allocation(run_id, dealer_id)
    payload = create_order_payload(
        dealer_id, model_line_id, run_id, da["version"],
        order_kind=order_kind,
        configuration=configuration or {"trim": TEST_DEFAULTS["TRIM"], "commodity_codes": []},
    )
    if customer_ref is not None:
        payload["customer_ref"] = customer_ref
    return api_client.create_order(payload, make_dealer_headers(dealer_id))


def create_accepted_order(dealer_id, model_line_id, run_id, **kwargs):
    """Create an order and assert it was ACCEPTED. Returns the order."""
    resp = submit_order(dealer_id, model_line_id, run_id, **kwargs)
    order = get_success_data(resp)
    assert order["state"] == "ACCEPTED", f"order not accepted: {order}"
    return order


def create_scheduled_order(dealer_id, model_line_id, run_id, build_week=None, **kwargs):
    """Accept + schedule. Returns the SCHEDULED order."""
    order = create_accepted_order(dealer_id, model_line_id, run_id, **kwargs)
    return get_success_data(
        api_client.schedule_order(order["id"], {"build_week": build_week or TEST_DEFAULTS["BUILD_WEEK"]}, SCHED)
    )


def create_built_order(dealer_id, model_line_id, run_id, build_week=None, build_mode=None, **kwargs):
    """Accept + schedule + build. Returns the BUILT order."""
    order = create_scheduled_order(dealer_id, model_line_id, run_id, build_week=build_week, **kwargs)
    payload = {}
    if build_mode is not None:
        payload["build_mode"] = build_mode
    return get_success_data(api_client.build_order(order["id"], payload, SCHED))


def create_carrier(code=None, weekly_capacity=5):
    code = code or _uniq("CAR")
    return get_success_data(
        api_client.create_carrier(create_carrier_payload(code=code, weekly_capacity=weekly_capacity), LOGIS)
    )


def create_delivered_order(dealer_id, model_line_id, run_id, build_week=None, **kwargs):
    """Full lifecycle: accept -> schedule -> build -> ship -> pickup -> deliver.
    Returns (order, shipment, carrier)."""
    week = build_week or TEST_DEFAULTS["BUILD_WEEK"]
    order = create_built_order(dealer_id, model_line_id, run_id, build_week=week, **kwargs)
    carrier = create_carrier()
    shipment = get_success_data(
        api_client.create_shipment(create_shipment_payload(order["id"], carrier["id"], pickup_week=week), LOGIS)
    )
    get_success_data(api_client.pickup_shipment(shipment["id"], LOGIS))
    shipment = get_success_data(api_client.deliver_shipment(shipment["id"], LOGIS))
    order = get_success_data(api_client.get_order(order["id"], ALLOC))
    return order, shipment, carrier


def seed_built_order(dealer_id, model_line_id, run_id, scheduled_week="2026-W30", **overrides):
    """Test-driving hook: create an already-BUILT order pinned to a past week (§3.14)."""
    from .factories import seed_order_at_week_payload
    payload = seed_order_at_week_payload(dealer_id, model_line_id, run_id,
                                         scheduled_week=scheduled_week, **overrides)
    return get_success_data(api_client.seed_order_at_week(payload, ALLOC))


def get_dealer_model_line(dealer_id, model_line_id):
    rows = get_success_data(
        api_client.list_dealer_model_lines(ALLOC, params={"dealer_id": dealer_id, "model_line_id": model_line_id})
    )
    assert len(rows) == 1, f"expected one DealerModelLine for ({dealer_id}, {model_line_id})"
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 4: restricted-line fixtures (commodity rationing)
# ---------------------------------------------------------------------------

def setup_restricted_line(install_rate_pct=50, allow_partial_build=True, base_units=4):
    """Dealer + line + PUBLISHED run with an ACTIVE restriction on the line.
    Returns dict(region, dealer, model_line, run, commodity, restriction)."""
    region = create_region()
    dealer = create_dealer(region["id"])
    model_line = create_model_line()
    commodity = create_commodity()
    restriction = create_restriction(
        commodity["id"], model_line["id"],
        install_rate_pct=install_rate_pct, allow_partial_build=allow_partial_build,
    )
    run = create_published_run(model_line["id"], base_units=base_units, retail_priority_pct=0)
    return {
        "region": region, "dealer": dealer, "model_line": model_line,
        "run": run, "commodity": commodity, "restriction": restriction,
    }


def config_with(commodity_codes):
    return {"trim": TEST_DEFAULTS["TRIM"], "commodity_codes": list(commodity_codes)}


# ---------------------------------------------------------------------------
# Tier 5: trades, appeals, programs
# ---------------------------------------------------------------------------

def create_trade(from_dealer, to_dealer, run_id, units=1):
    return get_success_data(
        api_client.create_dealer_trade(
            create_dealer_trade_payload(from_dealer["id"], to_dealer["id"], run_id, units=units),
            make_dealer_headers(from_dealer["id"]),
        )
    )


def create_accepted_trade(from_dealer, to_dealer, run_id, units=1):
    trade = create_trade(from_dealer, to_dealer, run_id, units=units)
    return get_success_data(api_client.accept_dealer_trade(trade["id"], make_dealer_headers(to_dealer["id"])))


def current_run_version(run_id):
    return get_success_data(api_client.get_allocation_run(run_id, ALLOC))["version"]


def execute_trade(trade_id, run_id):
    return api_client.execute_dealer_trade(
        trade_id, {"expected_run_version": current_run_version(run_id)}, ALLOC
    )


def file_appeal(dealer, run_id, appeal_type="MARKET_GAP", requested_units=1):
    return api_client.create_appeal(
        create_appeal_payload(dealer["id"], run_id, appeal_type=appeal_type,
                              requested_units=requested_units),
        make_dealer_headers(dealer["id"]),
    )


def create_volume_bonus_program(model_line_id, tier1_threshold=3, tier1_bonus_cents=500,
                                tier2_threshold=5, tier2_bonus_cents=900, code=None):
    code = code or _uniq("VB")
    return get_success_data(
        api_client.create_incentive_program(
            create_incentive_program_payload(
                model_line_id, code=code, kind="VOLUME_BONUS",
                params={"tier1_threshold": tier1_threshold, "tier1_bonus_cents": tier1_bonus_cents,
                        "tier2_threshold": tier2_threshold, "tier2_bonus_cents": tier2_bonus_cents},
            ),
            ALLOC,
        )
    )


def create_aged_inventory_program(model_line_id, age_threshold_days=45, credit_per_unit_cents=10000,
                                  tier2_age_days=60, tier2_credit_per_unit_cents=25000, code=None,
                                  window_start="2026-09-01T00:00:00Z", window_end="2026-12-01T00:00:00Z"):
    code = code or _uniq("AG")
    return get_success_data(
        api_client.create_incentive_program(
            create_incentive_program_payload(
                model_line_id, code=code, kind="AGED_INVENTORY_CREDIT",
                params={"age_threshold_days": age_threshold_days,
                        "credit_per_unit_cents": credit_per_unit_cents,
                        "tier2_age_days": tier2_age_days,
                        "tier2_credit_per_unit_cents": tier2_credit_per_unit_cents},
                window_start=window_start, window_end=window_end,
            ),
            ALLOC,
        )
    )


def get_accrual(program_id, dealer_id):
    rows = get_success_data(
        api_client.list_program_accruals(program_id, ALLOC, params={"dealer_id": dealer_id})
    )
    assert len(rows) == 1, f"expected one accrual row for dealer {dealer_id}"
    return rows[0]


def lock_all_children(run_id):
    """Lock every child DealerAllocation of a PUBLISHED run."""
    for da in list_run_dealer_allocations(run_id):
        if da["status"] == "OPEN":
            get_success_data(api_client.lock_dealer_allocation(run_id, da["id"], ALLOC))
