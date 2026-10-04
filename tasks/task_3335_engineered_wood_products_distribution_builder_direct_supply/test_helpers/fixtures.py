"""Composite setup helpers — multi-step preconditions built from PRD-declared
endpoints only. Fixtures use get_success_data() so setup failures surface as
clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START_ISO,
    DELIVERY_WINDOW_END,
    DELIVERY_WINDOW_START,
    DEFAULT_CREDIT_LIMIT_CENTS,
    DEFAULT_JOB_CAP_CENTS,
    SHIFT_WINDOW_END,
    SHIFT_WINDOW_START,
)
from .factories import (
    create_accept_takeoff_payload,
    create_branch_payload,
    create_builder_payload,
    create_capacity_week_payload,
    create_delivery_payload,
    create_inventory_lot_payload,
    create_job_payload,
    create_order_line,
    create_price_index_entry_payload,
    create_product_payload,
    create_sales_order_payload,
    create_submit_design_payload,
    create_takeoff_request_payload,
    create_truck_shift_payload,
)
from .test_users import TEST_USERS, make_builder_contact_headers

OPS = TEST_USERS["ops_admin_headers"]
MILL = TEST_USERS["mill_planner_headers"]
BRANCH_MGR = TEST_USERS["branch_manager_headers"]
CREDIT = TEST_USERS["credit_manager_headers"]
ACCT = TEST_USERS["account_manager_headers"]
FLEET = TEST_USERS["fleet_coordinator_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_START_ISO):
    """Advance the server logical clock. Setup call."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, OPS)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Basic entities
# ---------------------------------------------------------------------------

def create_product(**overrides):
    resp = api_client.create_product(create_product_payload(**overrides), OPS)
    return get_success_data(resp)


def create_branch(**overrides):
    resp = api_client.create_branch(create_branch_payload(**overrides), OPS)
    return get_success_data(resp)


def create_builder(legal_name="Treeline Builders", lien_rights_state_code="ID"):
    resp = api_client.create_builder(
        create_builder_payload(
            legal_name=legal_name, lien_rights_state_code=lien_rights_state_code
        ),
        CREDIT,
    )
    return get_success_data(resp)


def approve_builder(builder_id, credit_limit_cents=DEFAULT_CREDIT_LIMIT_CENTS):
    resp = api_client.credit_review(
        builder_id,
        {"decision": "APPROVE", "credit_limit_cents": credit_limit_cents},
        CREDIT,
    )
    return get_success_data(resp)


def create_active_builder(credit_limit_cents=DEFAULT_CREDIT_LIMIT_CENTS,
                          legal_name="Treeline Builders",
                          lien_rights_state_code="ID"):
    """Create a builder and approve it to ACTIVE. Returns the builder dict."""
    builder = create_builder(legal_name, lien_rights_state_code)
    return approve_builder(builder["id"], credit_limit_cents)


def create_job(builder_id, **overrides):
    resp = api_client.create_job(
        builder_id, create_job_payload(**overrides), ACCT
    )
    return get_success_data(resp)


def create_price_index_entry(**overrides):
    resp = api_client.create_price_index_entry(
        create_price_index_entry_payload(**overrides), OPS
    )
    return get_success_data(resp)


def receive_lot(branch_id, product_id, qty_received_mbf,
                unit_cost_cents_per_mbf):
    resp = api_client.receive_inventory_lot(
        branch_id,
        create_inventory_lot_payload(
            product_id,
            qty_received_mbf=qty_received_mbf,
            unit_cost_cents_per_mbf=unit_cost_cents_per_mbf,
        ),
        BRANCH_MGR,
    )
    return get_success_data(resp)


def get_builder(builder_id):
    return get_success_data(api_client.get_builder(builder_id, ACCT))


def get_builder_exposure(builder_id):
    return get_success_data(api_client.get_builder_exposure(builder_id, CREDIT))


def builder_version(builder_id):
    return get_builder(builder_id)["version"]


def get_order(order_id):
    return get_success_data(api_client.get_sales_order(order_id, ACCT))


def get_lot(lot_id):
    return get_success_data(api_client.get_inventory_lot(lot_id, OPS))


def get_job(job_id):
    return get_success_data(api_client.get_job(job_id, OPS))


def get_delivery(delivery_id):
    return get_success_data(api_client.get_delivery(delivery_id, OPS))


def get_shift(shift_id):
    return get_success_data(api_client.get_truck_shift(shift_id, OPS))


def get_takeoff(takeoff_id):
    return get_success_data(api_client.get_takeoff_request(takeoff_id, OPS))


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def create_order(job_id, branch_id, builder_id, qty_mbf=10,
                 unit_price_cents=100000, price_basis="FIXED",
                 product_id=None, code_report_reference=None):
    """Create a DRAFT direct order with one line, threading the builder's
    current version for the optimistic-concurrency field."""
    overrides = {}
    if code_report_reference is not None:
        overrides["code_report_reference"] = code_report_reference
    payload = create_sales_order_payload(
        branch_id,
        builder_version(builder_id),
        lines=[
            create_order_line(
                product_id,
                qty_mbf=qty_mbf,
                price_basis=price_basis,
                fixed_unit_price_cents_per_mbf=unit_price_cents,
            )
        ],
        **overrides,
    )
    resp = api_client.create_sales_order(job_id, payload, ACCT)
    return get_success_data(resp)


def confirm_order(order_id):
    resp = api_client.confirm_sales_order(order_id, ACCT)
    return get_success_data(resp)


def cancel_order(order_id):
    resp = api_client.cancel_sales_order(order_id, ACCT)
    return get_success_data(resp)


def setup_builder_with_job(credit_limit_cents=DEFAULT_CREDIT_LIMIT_CENTS,
                           job_exposure_cap_cents=DEFAULT_JOB_CAP_CENTS,
                           **job_overrides):
    """ACTIVE builder + job. Returns (builder, job)."""
    builder = create_active_builder(credit_limit_cents)
    job = create_job(
        builder["id"], job_exposure_cap_cents=job_exposure_cap_cents,
        **job_overrides,
    )
    return builder, job


def setup_order_confirmed(product=None, branch=None, lot_qty=100,
                          lot_cost=40000,
                          credit_limit_cents=DEFAULT_CREDIT_LIMIT_CENTS,
                          job_exposure_cap_cents=DEFAULT_JOB_CAP_CENTS,
                          order_qty=10, unit_price_cents=100000,
                          price_basis="FIXED", **job_overrides):
    """Stocked branch + ACTIVE builder + job + CONFIRMED order.
    Returns dict with keys: product, branch, lot, builder, job, order."""
    product = product or create_product()
    branch = branch or create_branch()
    lot = receive_lot(branch["id"], product["id"], lot_qty, lot_cost)
    builder, job = setup_builder_with_job(
        credit_limit_cents, job_exposure_cap_cents, **job_overrides
    )
    order = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=order_qty, unit_price_cents=unit_price_cents,
        price_basis=price_basis, product_id=product["id"],
    )
    order = confirm_order(order["id"])
    return {
        "product": product,
        "branch": branch,
        "lot": lot,
        "builder": builder,
        "job": job,
        "order": order,
    }


# ---------------------------------------------------------------------------
# Deliveries / shifts
# ---------------------------------------------------------------------------

def create_truck_shift(**overrides):
    resp = api_client.create_truck_shift(create_truck_shift_payload(**overrides), OPS)
    return get_success_data(resp)


def request_delivery(order_id, boom_required=False,
                     window_start=DELIVERY_WINDOW_START,
                     window_end=DELIVERY_WINDOW_END):
    resp = api_client.create_delivery(
        order_id,
        create_delivery_payload(
            boom_required=boom_required,
            window_start=window_start,
            window_end=window_end,
        ),
        ACCT,
    )
    return get_success_data(resp)


def schedule_delivery(delivery_id, shift_id):
    resp = api_client.schedule_delivery(delivery_id, {"truck_shift_id": shift_id}, FLEET)
    return get_success_data(resp)


def complete_delivery(delivery_id, outcome):
    resp = api_client.complete_delivery(delivery_id, {"outcome": outcome}, FLEET)
    return get_success_data(resp)


def setup_scheduled_delivery(clock_at_completion=None, **scenario_overrides):
    """CONFIRMED order + delivery SCHEDULED on a boom-capable shift.
    Returns the setup dict extended with delivery and shift."""
    scenario = setup_order_confirmed(**scenario_overrides)
    delivery = request_delivery(scenario["order"]["id"])
    shift = create_truck_shift()
    delivery = schedule_delivery(delivery["id"], shift["id"])
    if clock_at_completion:
        set_clock(clock_at_completion)
    scenario["delivery"] = delivery
    scenario["shift"] = shift
    return scenario


def setup_delivered_order(clock_at_completion="2026-09-10T13:00:00Z",
                          **scenario_overrides):
    """CONFIRMED order driven to DELIVERED via a completed delivery.
    Returns the setup dict extended with delivery and shift (final states)."""
    scenario = setup_scheduled_delivery(**scenario_overrides)
    set_clock(clock_at_completion)
    delivery = complete_delivery(scenario["delivery"]["id"], "COMPLETED")
    scenario["delivery"] = delivery
    scenario["order"] = get_order(scenario["order"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Take-offs
# ---------------------------------------------------------------------------

def create_takeoff(job_id, builder_id, **overrides):
    resp = api_client.create_takeoff_request(
        job_id,
        create_takeoff_request_payload(**overrides),
        make_builder_contact_headers(builder_id),
    )
    return get_success_data(resp)


def submit_design(takeoff_id, **overrides):
    resp = api_client.submit_design(
        takeoff_id, create_submit_design_payload(**overrides), ACCT
    )
    return get_success_data(resp)


def setup_quoted_takeoff(quoted_total_cents=800000, design_ref="DSN-A",
                         includes_floor_system_design=True,
                         credit_limit_cents=DEFAULT_CREDIT_LIMIT_CENTS):
    """Branch + ACTIVE builder + job + takeoff in QUOTED.
    Returns dict with keys: branch, builder, job, takeoff."""
    branch = create_branch()
    builder, job = setup_builder_with_job(credit_limit_cents)
    takeoff = create_takeoff(
        job["id"], builder["id"],
        includes_floor_system_design=includes_floor_system_design,
    )
    takeoff = submit_design(
        takeoff["id"], design_package_reference=design_ref,
        quoted_total_cents=quoted_total_cents,
    )
    return {
        "branch": branch,
        "builder": builder,
        "job": job,
        "takeoff": takeoff,
    }


def accept_takeoff(takeoff_id, builder_id, branch_id):
    resp = api_client.accept_takeoff(
        takeoff_id,
        create_accept_takeoff_payload(branch_id),
        make_builder_contact_headers(builder_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Capacity weeks
# ---------------------------------------------------------------------------

def create_capacity_week(**overrides):
    resp = api_client.create_capacity_week(
        create_capacity_week_payload(**overrides), MILL
    )
    return get_success_data(resp)


def allocate_week(week_id, internal, market, expected_version):
    resp = api_client.allocate_capacity_week(
        week_id,
        {
            "internal_alloc_mbf": internal,
            "market_alloc_mbf": market,
            "expected_capacity_week_version": expected_version,
        },
        MILL,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Liens
# ---------------------------------------------------------------------------

def file_lien(job_id):
    resp = api_client.create_lien_filing(job_id, CREDIT)
    return get_success_data(resp)
