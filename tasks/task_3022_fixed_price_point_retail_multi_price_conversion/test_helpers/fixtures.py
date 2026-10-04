"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API,
because the harness restarts the server before each test and each test starts
against an empty database. Setup calls use the lenient validator so a broken
precondition surfaces as a clear "setup failed" message rather than as a
confusing assertion failure in the test body.
"""

from itertools import count

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import CLOCK_START
from .test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    BUYER_HEADERS,
    DCO_HEADERS,
    IMPORT_HEADERS,
    PLANNER_HEADERS,
    SOM_HEADERS,
)

# ─── unique-key bookkeeping ───────────────────────────────────────────────────
# Every unique key is minted from a fresh counter so a test can create as many
# rows of a kind as it needs without colliding with itself.

_sku_seq = count(900000)
_store_seq = count(9000)
_container_seq = count(900)
_vendor_seq = count(900)
_formulation_seq = count(900)

DEFAULT_SEASON_CODE = "HARVEST_2026"
DEFAULT_WINDOW_OPENS = CLOCK_START
DEFAULT_WINDOW_CLOSES = "2026-11-30T00:00:00Z"


def next_sku() -> str:
    return str(next(_sku_seq))


def next_store_number() -> str:
    return str(next(_store_seq))


def next_container_number() -> str:
    return f"MSCU{next(_container_seq)}"


def next_vendor_name() -> str:
    return f"Vendor {next(_vendor_seq)}"


def next_formulation_code() -> str:
    return f"FORM-{next(_formulation_seq)}"


# ─── Tier 1: clock, price points, vendors, stores ────────────────────────────

def set_clock(to_iso8601=CLOCK_START):
    """Pin the logical clock (the server's startup default is the same instant)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN_HEADERS))


def create_price_point(shelf_price_cents=125, target_landed_cost_ratio=0.90, label=None, activate=True):
    """Register a price point and, by default, move it to ACTIVE so it is issuable."""
    label = label or f"PP-{shelf_price_cents}"
    pp = get_success_data(api_client.create_price_point(
        factories.create_price_point_payload(
            label=label,
            shelf_price_cents=shelf_price_cents,
            target_landed_cost_ratio=target_landed_cost_ratio,
        ),
        BUYER_HEADERS,
    ), 201)
    if activate:
        pp = get_success_data(api_client.activate_price_point(pp["id"], BUYER_HEADERS))
    return pp


def create_draft_price_point(shelf_price_cents=300, target_landed_cost_ratio=0.40, label=None):
    """Register a price point and leave it DRAFT, so it is not yet issuable."""
    return get_success_data(api_client.create_price_point(
        factories.create_price_point_payload(
            label=label or f"DRAFT-{shelf_price_cents}",
            shelf_price_cents=shelf_price_cents,
            target_landed_cost_ratio=target_landed_cost_ratio,
        ),
        BUYER_HEADERS,
    ), 201)


def create_vendor(vendor_name=None, country_of_origin="CN", import_flag=True):
    """Register a vendor."""
    return get_success_data(api_client.create_vendor(
        factories.create_vendor_payload(
            vendor_name=vendor_name or next_vendor_name(),
            country_of_origin=country_of_origin,
            import_flag=import_flag,
        ),
        BUYER_HEADERS,
    ), 201)


def create_store(store_number=None, shelf_facing_capacity_sqft=400.0):
    """Register a store with its shelf facing capacity."""
    return get_success_data(api_client.create_store(
        factories.create_store_payload(
            store_number=store_number or next_store_number(),
            shelf_facing_capacity_sqft=shelf_facing_capacity_sqft,
        ),
        SOM_HEADERS,
    ), 201)


# ─── Tier 2: items in each lifecycle position ────────────────────────────────

def create_item(sourcing_vendor_id, sku=None, **overrides):
    """Denominate an item."""
    sku = sku or next_sku()
    return get_success_data(api_client.create_item(
        factories.create_item_payload(sku, sourcing_vendor_id, **overrides),
        BUYER_HEADERS,
    ), 201)


def price_assign_item(item_id, price_point_id):
    """Fix an item to a shelf price point."""
    return get_success_data(api_client.assign_item_price_point(item_id, price_point_id, BUYER_HEADERS))


def apply_landed_cost(item_id, method="VENDOR_PRICE_CHANGE", applied_amount_cents=0,
                      container_id=None, headers=None):
    """Apply a landed cost and return the raw response (the caller reads the item back)."""
    return api_client.apply_landed_cost(
        item_id,
        factories.landed_cost_payload(method=method, applied_amount_cents=applied_amount_cents,
                                      container_id=container_id),
        headers or BUYER_HEADERS,
    )


def activate_item(item_id):
    return get_success_data(api_client.activate_item(item_id, BUYER_HEADERS))


def create_price_assigned_item(price_point_id, sourcing_vendor_id, sku=None, **overrides):
    """An item sitting at a shelf price point with no cost row yet."""
    item = create_item(sourcing_vendor_id, sku=sku, **overrides)
    return price_assign_item(item["id"], price_point_id)


def create_active_item(price_point_id, sourcing_vendor_id, sku=None, **overrides):
    """An item cleared to sell: priced, a cost row applied at its base cost, then activated."""
    item = create_price_assigned_item(price_point_id, sourcing_vendor_id, sku=sku, **overrides)
    # The landed-cost call answers with a LandedCostHistory row, not an Item, so the
    # item must be re-read to keep the Item's id for the activation call.
    get_success_data(apply_landed_cost(
        item["id"], applied_amount_cents=item["base_landed_cost_cents"]))
    return activate_item(item["id"])


def create_item_in_state(price_point_id, sourcing_vendor_id, target_state, sku=None, **overrides):
    """Walk an item from DENOMINATED to the requested lifecycle state.

    Supported targets: DENOMINATED, PRICE_ASSIGNED, COST_PENDING, DELETE_REVIEW, ACTIVE.
    A cost-carrying target takes a vendor price change at the item's base landed cost,
    which leaves the unit margin non-negative whenever the base cost fits the retail.
    """
    item = create_item(sourcing_vendor_id, sku=sku, **overrides)
    if target_state == "DENOMINATED":
        return item

    item = price_assign_item(item["id"], price_point_id)
    if target_state == "PRICE_ASSIGNED":
        return item

    # apply_landed_cost answers with a LandedCostHistory row; keep the Item object.
    get_success_data(apply_landed_cost(
        item["id"], applied_amount_cents=item["base_landed_cost_cents"]))
    if target_state in ("COST_PENDING", "DELETE_REVIEW"):
        return get_success_data(api_client.get_item(item["id"], ANALYST_HEADERS))

    if target_state == "ACTIVE":
        return activate_item(item["id"])

    raise ValueError(f"unsupported target state {target_state!r}")


def create_item_in_delete_review(price_point_id, sourcing_vendor_id, sku=None, **overrides):
    """An item whose landed cost outruns its retail, so it queues for deletion review."""
    overrides.setdefault("unit_retail_cents", 125)
    overrides.setdefault("base_landed_cost_cents", 128)
    overrides.setdefault("variable_store_cost_cents", 4)
    item = create_item(sourcing_vendor_id, sku=sku, **overrides)
    item = price_assign_item(item["id"], price_point_id)
    # The landed-cost call answers with a LandedCostHistory row, not an Item.
    get_success_data(apply_landed_cost(
        item["id"], applied_amount_cents=item["base_landed_cost_cents"]))
    item = get_success_data(api_client.get_item(item["id"], ANALYST_HEADERS))
    assert item["status"] == "DELETE_REVIEW", (
        f"setup failed: expected DELETE_REVIEW, got {item['status']}"
    )
    return item


# ─── Tier 3: containers through to RECEIVED ──────────────────────────────────

def create_booked_container(vendor_id, total_freight_cents=0, container_number=None):
    """Book a container and leave it in BOOKED."""
    return get_success_data(api_client.create_container(
        factories.create_container_payload(
            vendor_id,
            container_number=container_number or next_container_number(),
            total_freight_cents=total_freight_cents,
        ),
        IMPORT_HEADERS,
    ), 201)


def container_in_transit(container_id):
    return get_success_data(api_client.container_depart(container_id, IMPORT_HEADERS))


def create_container_at_port(vendor_id, total_freight_cents=0, container_number=None, on_hold=False):
    """Book a container and walk it to AT_PORT, optionally placing it on customs hold."""
    container = create_booked_container(vendor_id, total_freight_cents, container_number)
    get_success_data(api_client.container_depart(container["id"], IMPORT_HEADERS))
    container = get_success_data(api_client.container_arrive(container["id"], IMPORT_HEADERS))
    if on_hold:
        container = get_success_data(api_client.container_customs_hold(container["id"], IMPORT_HEADERS))
    return container


def create_received_container(vendor_id, total_freight_cents=0, container_number=None):
    """Book a container and walk it all the way to RECEIVED.

    PRD §3.6 makes arrival set `customs_cleared` true, so a container is
    receipt-eligible straight from `AT_PORT`. The customs-release revert edge is
    only legal on a container that is currently on hold (`CUSTOMS_HOLD`), so the
    fixture places the container on hold first and then releases it — exercising
    the revert edge rather than calling it out of state.
    """
    container = get_success_data(api_client.create_container(
        factories.create_container_payload(
            vendor_id,
            container_number=container_number or next_container_number(),
            total_freight_cents=total_freight_cents,
        ),
        IMPORT_HEADERS,
    ), 201)
    get_success_data(api_client.container_depart(container["id"], IMPORT_HEADERS))
    get_success_data(api_client.container_arrive(container["id"], IMPORT_HEADERS))
    get_success_data(api_client.container_customs_hold(container["id"], IMPORT_HEADERS))
    get_success_data(api_client.container_customs_release(container["id"], IMPORT_HEADERS))
    return get_success_data(api_client.container_receive(container["id"], IMPORT_HEADERS))


def container_customs_release(container_id):
    return get_success_data(api_client.container_customs_release(container_id, IMPORT_HEADERS))


def container_receive(container_id):
    return get_success_data(api_client.container_receive(container_id, IMPORT_HEADERS))


def allocate(container_id, store_id, item_id, sequence=1, requested_units=40):
    """Create one allocation line."""
    return get_success_data(api_client.create_allocation_line(
        factories.create_allocation_line_payload(
            container_id, store_id, item_id, sequence=sequence, requested_units=requested_units),
        DCO_HEADERS,
    ), 201)


def release_line(line_id, release_units):
    return get_success_data(api_client.release_allocation_line(line_id, release_units, DCO_HEADERS))


def short_line(line_id):
    return get_success_data(api_client.short_allocation_line(line_id, DCO_HEADERS))


def build_received_container(vendor_id, store_id, item_specs, total_freight_cents=0, container_number=None):
    """One RECEIVED container plus one allocation line per spec.

    Each spec is a dict carrying ``item_id``, an optional ``sequence`` (defaults to its
    1-based position) and an optional ``requested_units`` (defaults to 40).
    """
    container = create_received_container(
        vendor_id, total_freight_cents=total_freight_cents, container_number=container_number)
    lines = []
    for index, spec in enumerate(item_specs, start=1):
        lines.append(allocate(
            container["id"],
            store_id,
            spec["item_id"],
            sequence=spec.get("sequence", index),
            requested_units=spec.get("requested_units", 40),
        ))
    return container, lines


# ─── Tier 4: exclusive pack programs ─────────────────────────────────────────

def create_pack_program(vendor_id, price_point_id, quoted_landed_cost_cents=100,
                        formulation_code=None, **overrides):
    return get_success_data(api_client.create_pack_program(
        factories.create_pack_program_payload(
            vendor_id, price_point_id,
            quoted_landed_cost_cents=quoted_landed_cost_cents,
            formulation_code=formulation_code or next_formulation_code(),
            **overrides,
        ),
        BUYER_HEADERS,
    ), 201)


def advance_pack_program(program_id, status="ACTIVE", quoted_landed_cost_cents=None):
    """Advance a program's status, optionally re-quoting its landed cost on the same call."""
    payload = {"status": status}
    if quoted_landed_cost_cents is not None:
        payload["quoted_landed_cost_cents"] = quoted_landed_cost_cents
    return api_client.patch_pack_program(program_id, payload, BUYER_HEADERS)


def create_active_pack_program(vendor_id, price_point_id, quoted_landed_cost_cents=0, **overrides):
    """Open a program and advance it to ACTIVE at a quote that clears the ceiling."""
    program = create_pack_program(
        vendor_id, price_point_id, quoted_landed_cost_cents=0, **overrides)
    return get_success_data(advance_pack_program(
        program["id"], quoted_landed_cost_cents=quoted_landed_cost_cents))


# ─── Tier 5: the reset calendar ──────────────────────────────────────────────

def create_draft_season_window(season_code=DEFAULT_SEASON_CODE, opens_on="2026-10-01T00:00:00Z",
                               closes_on="2026-10-31T00:00:00Z"):
    return get_success_data(api_client.create_season_window(
        factories.create_season_window_payload(
            season_code=season_code, opens_on=opens_on, closes_on=closes_on),
        PLANNER_HEADERS,
    ), 201)


def create_open_season_window(season_code=DEFAULT_SEASON_CODE, opens_on=None, closes_on=None):
    """Define a window and publish it. At the default clock the window reads OPEN."""
    window = create_draft_season_window(
        season_code=season_code,
        opens_on=opens_on or DEFAULT_WINDOW_OPENS,
        closes_on=closes_on or DEFAULT_WINDOW_CLOSES,
    )
    return get_success_data(api_client.schedule_season_window(window["id"], PLANNER_HEADERS))


def plan_reset(store_id, price_point_id, season_window_id, aisle_code="A11",
               starts_at="2026-09-02T00:00:00Z", ends_at="2026-09-08T00:00:00Z",
               allocated_shelf_sqft=50.0, seasonal_changeover=True):
    return api_client.create_aisle_reset(
        factories.create_aisle_reset_payload(
            store_id, price_point_id, season_window_id,
            aisle_code=aisle_code, starts_at=starts_at, ends_at=ends_at,
            allocated_shelf_sqft=allocated_shelf_sqft, seasonal_changeover=seasonal_changeover,
        ),
        PLANNER_HEADERS,
    )


def plan_reset_ok(*args, **kwargs):
    """Plan an aisle reset and unwrap the created row (positional- and keyword-friendly)."""
    return get_success_data(plan_reset(*args, **kwargs), 201)


def begin_reset(reset_id):
    return api_client.begin_aisle_reset(reset_id, PLANNER_HEADERS)


def execute_reset(reset_id):
    return api_client.execute_aisle_reset(reset_id, PLANNER_HEADERS)


def abandon_reset(reset_id):
    return api_client.abandon_aisle_reset(reset_id, SOM_HEADERS)


def create_executed_reset(**kwargs):
    """Plan, begin and execute one aisle changeover."""
    reset = plan_reset_ok(**kwargs)
    get_success_data(begin_reset(reset["id"]))
    return get_success_data(execute_reset(reset["id"]))


# ─── conversion lifecycle ────────────────────────────────────────────────────

def begin_conversion(store_id, to_price_point_id):
    return api_client.begin_conversion(store_id, to_price_point_id, SOM_HEADERS)


def open_conversion_project(store_id, from_price_point_id, to_price_point_id,
                            expected_store_version=None):
    if expected_store_version is None:
        store = get_success_data(api_client.get_store(store_id, ANALYST_HEADERS))
        expected_store_version = store["version"]
    return api_client.create_conversion_project(
        factories.create_conversion_project_payload(
            store_id, from_price_point_id, to_price_point_id, expected_store_version),
        SOM_HEADERS,
    )


def start_conversion_project(project_id):
    return api_client.start_conversion_project(project_id, SOM_HEADERS)


def complete_conversion(store_id, conversion_id):
    return api_client.complete_conversion(store_id, conversion_id, SOM_HEADERS)


def rollback_conversion(store_id, conversion_id):
    return api_client.rollback_conversion(store_id, conversion_id, SOM_HEADERS)


def file_conversion_artifact(store_id, conversion_id, artifact):
    return api_client.file_conversion_artifact(store_id, conversion_id, artifact, SOM_HEADERS)


def store_bound_to_point_count(price_point_id):
    """How many stores currently bind ``conversion_price_point_id`` to a price point."""
    response = api_client.list_stores(
        ANALYST_HEADERS, params={"conversion_price_point_id": price_point_id})
    return len(get_success_data(response))


def conversion_in_progress(store_id, from_price_point_id, to_price_point_id):
    """A store CONVERTING toward ``to_price_point_id`` with a started project.

    The project's source is ``from_price_point_id`` and its destination is
    ``to_price_point_id``; the two must differ, because a project whose
    destination equals its source is refused as malformed (PRD §3.8).

    Returns a dict carrying the store (mid-change), the project id and the version
    the store held when the project was opened.
    """
    begin = get_success_data(begin_conversion(store_id, to_price_point_id))
    project = get_success_data(open_conversion_project(
        store_id, from_price_point_id, to_price_point_id,
        expected_store_version=begin["version"]))
    project = get_success_data(start_conversion_project(project["id"]))
    return {
        "store": begin,
        "version_at_begin": begin["version"],
        "project": project,
        "conversion_id": project["id"],
    }


# ─── multi-entity scenario helpers ───────────────────────────────────────────

def seed_reference_data():
    """Pin the clock for a test that only needs the baseline time."""
    set_clock()
    return {
        "clock_start": CLOCK_START,
        "five_days_before_window_close": "2026-09-15T00:00:00Z",
        "day_before_existing_reset_ends": "2026-09-19T00:00:00Z",
    }


def setup_price_point_and_vendor(shelf_price_cents=125, target_landed_cost_ratio=0.90):
    """The most common two-line preamble: an ACTIVE price point and an import vendor."""
    return create_price_point(shelf_price_cents, target_landed_cost_ratio), create_vendor()


def setup_priced_items(price_point_id, vendor_id, specs):
    """Price-assign a batch of items at one price point.

    ``specs`` is a list of dicts of ``create_item`` overrides; each spec may carry a ``sku``.
    Returns the list of items.
    """
    items = []
    for spec in specs:
        spec = dict(spec)
        sku = spec.pop("sku", None)
        item = create_item(vendor_id, sku=sku, **spec)
        items.append(price_assign_item(item["id"], price_point_id))
    return items


def setup_shelf_waterfall_scenario(broken_case_item_kwargs, fitting_item_kwargs,
                                   price_point_id, vendor_id, store_id,
                                   total_freight_cents=1260, requests=(150, 150),
                                   fitting_price_point_id=None):
    """Two ACTIVE items on one RECEIVED container: one broken-case, one fitting the shelf.

    ``fitting_price_point_id`` lets the fitting item rest on a second price point of
    the same shelf price. Two distinct price points are required whenever an ACTIVE
    exclusive pack cures every item on its own price point: if both items shared one
    point the single pack would cover both, and a negative-contribution item could
    never be queued for deletion review (PRD §3.4's three-field cure join).

    Returns a dict with the container, the two items and their two lines.
    """
    broken = create_active_item(price_point_id, vendor_id, **broken_case_item_kwargs)
    fitting = create_active_item(
        fitting_price_point_id or price_point_id, vendor_id, **fitting_item_kwargs)
    container, lines = build_received_container(
        vendor_id, store_id,
        [
            {"item_id": broken["id"], "sequence": 1, "requested_units": requests[0]},
            {"item_id": fitting["id"], "sequence": 2, "requested_units": requests[1]},
        ],
        total_freight_cents=total_freight_cents,
    )
    return {
        "container": container,
        "broken_item": broken,
        "fitting_item": fitting,
        "broken_line": lines[0],
        "fitting_line": lines[1],
    }