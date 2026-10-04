"""Composite setup helpers.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints (the server is restarted with an empty database before each test).
Setup calls use the lenient get_success_data validator so failures surface as
clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DESIGN_WIN_START_DATE,
    EOL_NOTICE_DATE,
    EOL_LAST_ORDER_DATE,
    EOL_LAST_SHIP_DATE,
    POOL_PERIOD_END,
    POOL_PERIOD_START,
    PRICING_EFFECTIVE_FROM,
)
from .factories import (
    create_allocation_run_payload,
    create_capacity_pool_payload,
    create_customer_payload,
    create_design_win_payload,
    create_eol_notice_payload,
    create_lifetime_buy_payload,
    create_order_payload,
    create_part_payload,
    create_pricing_schedule_payload,
    create_reference_design_payload,
    create_site_qualification_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["supply_planner_headers"]
CHANNEL = TEST_USERS["channel_manager_headers"]
QUALITY = TEST_USERS["quality_engineer_headers"]
FIELD = TEST_USERS["field_engineer_headers"]


# --- Tier 1: single-entity creators -------------------------------------------

def make_part(**overrides) -> dict:
    """Create a catalog part (201). Returns the Part."""
    return get_success_data(api_client.create_part(create_part_payload(**overrides), PLANNER))


def make_customer(**overrides) -> dict:
    """Register a direct customer (201). Returns the Customer."""
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), CHANNEL)
    )


def make_capacity_pool(
    site_name="DFAB",
    process_technology="ANALOG_BIPOLAR",
    period_start=POOL_PERIOD_START,
    period_end=POOL_PERIOD_END,
    total_units=10000,
) -> dict:
    """Create a capacity pool (201); OPEN at the default clock for the default window."""
    payload = create_capacity_pool_payload(
        site_name=site_name,
        process_technology=process_technology,
        period_start=period_start,
        period_end=period_end,
        total_units=total_units,
    )
    return get_success_data(api_client.create_capacity_pool(payload, PLANNER))


def record_receipt(part_id, pool_id, units) -> dict:
    """Record a production receipt (201). Returns the updated Part."""
    return get_success_data(
        api_client.create_receipt(
            part_id, {"capacity_pool_id": pool_id, "units": units}, PLANNER
        )
    )


def publish_price(part_id, unit_price_cents=100, effective_from=PRICING_EFFECTIVE_FROM,
                  tiers=None) -> dict:
    """Publish a pricing schedule for a part with a fresh OCC version (201)."""
    part = get_success_data(api_client.get_part(part_id, PLANNER))
    payload = create_pricing_schedule_payload(
        part_id,
        expected_part_version=part["version"],
        effective_from=effective_from,
        tiers=tiers,
        unit_price_cents=unit_price_cents,
    )
    return get_success_data(api_client.create_pricing_schedule(payload, CHANNEL))


def make_order(customer_id, lines) -> dict:
    """Create a DRAFT order owned by the given customer (201)."""
    payload = create_order_payload(customer_id, lines)
    return get_success_data(
        api_client.create_order(payload, make_customer_headers(customer_id))
    )


def submit_order(order_id, customer_id) -> dict:
    """Submit a DRAFT order as its owning customer (200). Returns the order."""
    return get_success_data(
        api_client.submit_order(order_id, make_customer_headers(customer_id))
    )


def set_clock(to_iso8601) -> dict:
    """Advance the logical clock (PlatformAdmin only). Returns {current_utc}."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def get_order_lines(order_id) -> list:
    """List an order's lines as SupplyPlanner (200)."""
    data = get_success_data(
        api_client.list_order_lines(PLANNER, params={"order_id": order_id})
    )
    return data


def get_part(part_id) -> dict:
    return get_success_data(api_client.get_part(part_id, PLANNER))


def get_customer(customer_id) -> dict:
    return get_success_data(api_client.get_customer(customer_id, CHANNEL))


def get_inventory_position(part_id) -> dict:
    return get_success_data(api_client.get_inventory_position(part_id, PLANNER))


def get_pool(pool_id) -> dict:
    return get_success_data(api_client.get_capacity_pool(pool_id, PLANNER))


# --- Tier 2: common composite preambles ---------------------------------------

def make_stocked_priced_part(
    part_number,
    on_hand=0,
    unit_price_cents=100,
    demand_rate=None,
    buffer_multiple=None,
    site_name="DFAB",
    process_technology="ANALOG_BIPOLAR",
    pool_total_units=10000,
    effective_from=PRICING_EFFECTIVE_FROM,
    package_family="PDIP",
    description="Precision analog part",
):
    """Part + OPEN capacity pool + receipt + published single-tier schedule.

    Returns (part_after_pricing, pool). Posture reflects demand/stock inputs.
    """
    overrides = {
        "part_number": part_number,
        "process_technology": process_technology,
        "package_family": package_family,
        "description": description,
    }
    if demand_rate is not None:
        overrides["demand_rate_units_per_week"] = demand_rate
    if buffer_multiple is not None:
        overrides["buffer_multiple"] = buffer_multiple
    part = make_part(**overrides)
    pool = make_capacity_pool(
        site_name=site_name,
        process_technology=process_technology,
        total_units=pool_total_units,
    )
    if on_hand:
        part = record_receipt(part["id"], pool["id"], on_hand)
    publish_price(
        part["id"], unit_price_cents=unit_price_cents, effective_from=effective_from
    )
    return get_part(part["id"]), pool


def make_eol_notice(part_id, notice_date=EOL_NOTICE_DATE,
                    last_order_date=EOL_LAST_ORDER_DATE,
                    last_ship_date=EOL_LAST_SHIP_DATE,
                    reason="End of life program") -> dict:
    """Issue an EOL notice for a part (201); drives the part to EOL_ANNOUNCED."""
    payload = create_eol_notice_payload(
        notice_date=notice_date,
        last_order_date=last_order_date,
        last_ship_date=last_ship_date,
        reason=reason,
    )
    return get_success_data(api_client.create_eol_notice(part_id, payload, PLANNER))


def make_active_design_win(part, customer, expected_lifetime_revenue_cents=1_000_000,
                           annual_volume_units=5200,
                           start_date=DESIGN_WIN_START_DATE, title=None):
    """Published reference design + activated design win. Returns (rd, win)."""
    rd = get_success_data(
        api_client.create_reference_design(
            create_reference_design_payload(
                title=title, featured_part_number=part["part_number"]
            ),
            FIELD,
        )
    )
    get_success_data(api_client.publish_reference_design(rd["id"], FIELD))
    win = get_success_data(
        api_client.create_design_win(
            create_design_win_payload(
                reference_design_id=rd["id"],
                customer_id=customer["id"],
                part_id=part["id"],
                expected_lifetime_revenue_cents=expected_lifetime_revenue_cents,
                annual_volume_units=annual_volume_units,
                start_date=start_date,
            ),
            FIELD,
        )
    )
    win = get_success_data(api_client.activate_design_win(win["id"], FIELD))
    return rd, win


def qualify_site(site_name, segment="AUTOMOTIVE") -> dict:
    """Open a site qualification and drive it REQUESTED -> IN_REVIEW -> QUALIFIED."""
    qual = get_success_data(
        api_client.create_site_qualification(
            create_site_qualification_payload(site_name=site_name, segment=segment),
            QUALITY,
        )
    )
    get_success_data(
        api_client.transition_site_qualification(
            qual["id"], {"to_state": "IN_REVIEW"}, QUALITY
        )
    )
    return get_success_data(
        api_client.transition_site_qualification(
            qual["id"], {"to_state": "QUALIFIED"}, QUALITY
        )
    )


def make_ltb_ready_part(part_number, demand_rate=40, on_hand=3000,
                        unit_price_cents=150):
    """EOL_ANNOUNCED part with stock and pricing, ready for lifetime buys.

    Returns (part, pool, notice). LTB minimum quantity is demand_rate * 52.
    """
    part, pool = make_stocked_priced_part(
        part_number,
        on_hand=on_hand,
        unit_price_cents=unit_price_cents,
        demand_rate=demand_rate,
    )
    notice = make_eol_notice(part["id"])
    return get_part(part["id"]), pool, notice


def place_lifetime_buy(notice, part_id, customer_id, quantity) -> dict:
    """Place a lifetime buy as the owning customer (201)."""
    payload = create_lifetime_buy_payload(notice["id"], part_id, customer_id, quantity)
    return get_success_data(
        api_client.create_lifetime_buy(payload, make_customer_headers(customer_id))
    )


def make_allocation_run(period_label="2026-W40") -> dict:
    """Create an allocation run (201, DRAFT with frozen awards)."""
    return get_success_data(
        api_client.create_allocation_run(
            create_allocation_run_payload(period_label), PLANNER
        )
    )
