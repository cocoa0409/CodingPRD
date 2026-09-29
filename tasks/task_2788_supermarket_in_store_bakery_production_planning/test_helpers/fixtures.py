"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because each test runs against an empty database.  Setup calls
go through the lenient ``get_success_data`` validator so a broken preamble
surfaces as a clear setup failure rather than an obscure assertion.

The logical clock is always pinned first (PRD §2.11), so no helper depends on
where a previous call left it.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_TEST_CLOCK, TEST_DEFAULTS
from .factories import (
    cancel_ingredient_order_payload,
    close_bake_day_payload,
    complete_run_payload,
    create_bake_day_payload,
    create_cake_base_product_payload,
    create_cake_order_payload,
    create_department_payload,
    create_flour_payload,
    create_ingredient_order_payload,
    create_oven_payload,
    create_pickup_slot_payload,
    create_product_payload,
    create_production_run_payload,
    create_scratch_product_payload,
    create_second_department_payload,
    create_sugar_payload,
    create_thaw_filler_product_payload,
    create_waste_record_payload,
    forecast_line_payload,
    generate_plan_payload,
    ingredient_order_line,
    oven_status_payload,
    recipe_line,
    void_waste_record_payload,
)
from .test_users import (
    BAKER_ONE_USER_ID,
    BAKER_TWO_USER_ID,
    TEST_USERS,
    make_baker_headers,
    make_department_manager_headers,
)

REGIONAL_ADMIN = TEST_USERS["regional_admin_headers"]
BAKER = TEST_USERS["baker_headers"]
SECOND_BAKER = TEST_USERS["second_baker_headers"]
DECORATOR = TEST_USERS["decorator_headers"]
CAKE_DESK = TEST_USERS["cake_desk_headers"]

# The canonical bake day used across the suite: a Wednesday, whose forecast
# therefore takes no day-of-week uplift, with a 04:00Z–20:00Z oven shift.
SHIFT_START = TEST_DEFAULTS["OVEN_SHIFT_START_UTC"]
SHIFT_END = TEST_DEFAULTS["OVEN_SHIFT_END_UTC"]


# --- primitives -------------------------------------------------------------

def set_clock(instant=DEFAULT_TEST_CLOCK, headers=REGIONAL_ADMIN):
    """Move the server's logical clock to ``instant``."""
    return get_success_data(api_client.set_clock(instant, headers))


def provision_department(**overrides):
    """Register a bakery department. Returns the created department."""
    return get_success_data(
        api_client.create_department(create_department_payload(**overrides), REGIONAL_ADMIN)
    )


def provision_second_department(**overrides):
    """Register a second, unrelated department (for cross-scope tests)."""
    return get_success_data(
        api_client.create_department(
            create_second_department_payload(**overrides), REGIONAL_ADMIN
        )
    )


def provision_ingredient(payload):
    return get_success_data(api_client.create_ingredient(payload, REGIONAL_ADMIN))


def provision_flour(department_id, on_hand_units=2000, **overrides):
    return provision_ingredient(
        create_flour_payload(department_id, on_hand_units=on_hand_units, **overrides)
    )


def provision_sugar(department_id, on_hand_units=500, **overrides):
    return provision_ingredient(
        create_sugar_payload(department_id, on_hand_units=on_hand_units, **overrides)
    )


def provision_product(payload):
    return get_success_data(api_client.create_product(payload, REGIONAL_ADMIN))


def provision_oven(payload):
    return get_success_data(api_client.create_oven(payload, REGIONAL_ADMIN))


def open_bake_day(department, **overrides):
    """Open a bake day owned by ``department``. Returns the DRAFT bake day."""
    headers = make_department_manager_headers(department["id"])
    return get_success_data(
        api_client.create_bake_day(
            create_bake_day_payload(department["id"], **overrides), headers
        )
    )


def add_forecast_line(bake_day, department, product_id, daypart="MORNING", forecasted_units=40):
    """Append one forecast line. Returns the whole updated bake day."""
    headers = make_department_manager_headers(department["id"])
    return get_success_data(
        api_client.append_forecast_line(
            bake_day["id"],
            forecast_line_payload(product_id, daypart, forecasted_units),
            headers,
        )
    )


def run_plan_generation(bake_day, department, expected_version=None):
    """Generate the plan using the bake day's current version. Returns the day."""
    headers = make_department_manager_headers(department["id"])
    version = bake_day["version"] if expected_version is None else expected_version
    return get_success_data(
        api_client.generate_plan(
            bake_day["id"], generate_plan_payload(version), headers
        )
    )


def read_bake_day(bake_day_id, headers=REGIONAL_ADMIN):
    return get_success_data(api_client.get_bake_day(bake_day_id, headers))


def read_run(run_id, headers=REGIONAL_ADMIN):
    return get_success_data(api_client.get_production_run(run_id, headers))


def read_department(department_id, headers=REGIONAL_ADMIN):
    return get_success_data(api_client.get_department(department_id, headers))


def read_ingredient(ingredient_id, headers=REGIONAL_ADMIN):
    return get_success_data(api_client.get_ingredient(ingredient_id, headers))


def read_oven(oven_id, headers=REGIONAL_ADMIN):
    return get_success_data(api_client.get_oven(oven_id, headers))


def read_pickup_slot(slot_id, headers=REGIONAL_ADMIN):
    return get_success_data(api_client.get_pickup_slot(slot_id, headers))


def read_cake_order(order_id, headers=REGIONAL_ADMIN):
    return get_success_data(api_client.get_cake_order(order_id, headers))


def read_ingredient_order(order_id, headers=REGIONAL_ADMIN):
    return get_success_data(api_client.get_ingredient_order(order_id, headers))


def read_waste_record(record_id, headers=REGIONAL_ADMIN):
    return get_success_data(api_client.get_waste_record(record_id, headers))


# --- Tier 2: reference data hierarchy --------------------------------------

def setup_reference_data(
    clock=DEFAULT_TEST_CLOCK,
    flour_on_hand=2000,
    sugar_on_hand=500,
    include_sugar=True,
    include_scratch=True,
    include_cake_base=True,
    include_oven=True,
    oven_payload=None,
    department_overrides=None,
):
    """A department with its ingredients, catalogue and one oven.

    Returns a dict carrying ``department``, ``manager`` headers, ``flour``,
    ``sugar``, the ``filler`` thaw-and-serve product, the par-baked
    ``croissant`` (30 flour units a rack), the scratch ``roll`` (25 flour units
    a rack), the ``cake_base`` and ``oven``.
    """
    set_clock(clock)
    department = provision_department(**(department_overrides or {}))
    manager = make_department_manager_headers(department["id"])

    flour = provision_flour(department["id"], on_hand_units=flour_on_hand)
    sugar = (
        provision_sugar(department["id"], on_hand_units=sugar_on_hand)
        if include_sugar
        else None
    )

    filler = provision_product(create_thaw_filler_product_payload(department["id"]))
    croissant = provision_product(
        create_product_payload(
            department["id"], recipe_lines=[recipe_line(flour["id"], 30)]
        )
    )
    roll = (
        provision_product(
            create_scratch_product_payload(
                department["id"], recipe_lines=[recipe_line(flour["id"], 25)]
            )
        )
        if include_scratch
        else None
    )
    cake_base = (
        provision_product(create_cake_base_product_payload(department["id"]))
        if include_cake_base
        else None
    )

    oven = None
    if include_oven:
        oven = provision_oven(oven_payload or create_oven_payload(department["id"]))

    return {
        "clock": clock,
        "department": department,
        "manager": manager,
        "flour": flour,
        "sugar": sugar,
        "filler": filler,
        "croissant": croissant,
        "roll": roll,
        "cake_base": cake_base,
        "oven": oven,
    }


def setup_planned_day(bake_day_overrides=None, **reference_kwargs):
    """Reference data plus a bake day driven all the way to ``PLANNED``.

    The plan is made non-empty with a single one-unit forecast line on the
    zero-labor thaw-and-serve filler, so the day reaches ``PLANNED`` while
    contributing 0.00 planned labor and exactly 1 planned unit.  The returned
    dict adds ``bake_day`` (freshly read, ``PLANNED``) and ``filler_run``.
    """
    setup = setup_reference_data(**reference_kwargs)
    bake_day = open_bake_day(setup["department"], **(bake_day_overrides or {}))
    bake_day = add_forecast_line(
        bake_day, setup["department"], setup["filler"]["id"], "MORNING", 1
    )
    bake_day = run_plan_generation(bake_day, setup["department"])
    runs, _ = _list_runs(bake_day["id"])
    filler_run = next(
        (r for r in runs if r["product_id"] == setup["filler"]["id"]), None
    )
    setup["bake_day"] = bake_day
    setup["filler_run"] = filler_run
    return setup


def setup_draft_day(bake_day_overrides=None, **reference_kwargs):
    """Reference data plus a bake day left in ``DRAFT`` with no forecast."""
    setup = setup_reference_data(**reference_kwargs)
    setup["bake_day"] = open_bake_day(
        setup["department"], **(bake_day_overrides or {})
    )
    return setup


def _list_runs(bake_day_id, params=None, headers=REGIONAL_ADMIN):
    query = {"bake_day_id": bake_day_id}
    query.update(params or {})
    response = api_client.list_production_runs(headers, params=query)
    body = response.json()
    return body["data"], body["meta"]


def list_runs_for_day(bake_day_id, **filters):
    """List the runs of a bake day. Returns ``(rows, meta)``."""
    return _list_runs(bake_day_id, filters)


# --- Tier 3: production run lifecycle shortcuts -----------------------------

def schedule_run(
    bake_day,
    product_id,
    rack_count=2,
    oven_id=None,
    deck_index=None,
    bake_start_utc=None,
    proof_start_utc=None,
    headers=BAKER,
):
    """Schedule one run by hand. Returns the created run."""
    payload = create_production_run_payload(
        bake_day["id"],
        product_id,
        rack_count=rack_count,
        oven_id=oven_id,
        deck_index=deck_index,
        proof_start_utc=proof_start_utc,
        bake_start_utc=bake_start_utc,
    )
    return get_success_data(api_client.create_production_run(payload, headers))


def schedule_par_baked_run(
    setup,
    rack_count=2,
    deck_index=0,
    bake_start_utc=SHIFT_START,
    oven=None,
    headers=BAKER,
):
    """A par-baked croissant batch: 20 bake + 15 cool minutes, no proof."""
    oven = oven or setup["oven"]
    return schedule_run(
        setup["bake_day"],
        setup["croissant"]["id"],
        rack_count=rack_count,
        oven_id=oven["id"],
        deck_index=deck_index,
        bake_start_utc=bake_start_utc,
        headers=headers,
    )


def schedule_scratch_run(
    setup,
    rack_count=4,
    deck_index=0,
    bake_start_utc="2026-08-12T04:45:00Z",
    proof_start_utc=SHIFT_START,
    oven=None,
    headers=BAKER,
):
    """A scratch dinner-roll batch: 45 proof + 30 bake + 20 cool minutes."""
    oven = oven or setup["oven"]
    return schedule_run(
        setup["bake_day"],
        setup["roll"]["id"],
        rack_count=rack_count,
        oven_id=oven["id"],
        deck_index=deck_index,
        bake_start_utc=bake_start_utc,
        proof_start_utc=proof_start_utc,
        headers=headers,
    )


def drive_run_to_baking(run, production_method, headers=BAKER):
    """Walk a scheduled run up to ``BAKING`` along its method's path."""
    if production_method == "SCRATCH":
        get_success_data(api_client.start_proof(run["id"], headers))
    return get_success_data(api_client.start_bake(run["id"], headers))


def complete_run(run, actual_units, actual_labor_minutes=None, headers=BAKER):
    """Complete a run with the given yield. Returns the completed run."""
    return get_success_data(
        api_client.complete_run(
            run["id"],
            complete_run_payload(actual_units, actual_labor_minutes),
            headers,
        )
    )


def drive_run_to_completed(
    run, production_method, actual_units, actual_labor_minutes=None, headers=BAKER
):
    """Walk a scheduled run all the way to ``COMPLETED``."""
    if production_method != "THAW_AND_SERVE":
        drive_run_to_baking(run, production_method, headers=headers)
    return complete_run(
        run, actual_units, actual_labor_minutes=actual_labor_minutes, headers=headers
    )


def create_completed_par_baked_run(
    setup,
    rack_count=2,
    actual_units=None,
    actual_labor_minutes=None,
    deck_index=0,
    bake_start_utc=SHIFT_START,
    oven=None,
    headers=BAKER,
):
    """Schedule, bake and complete a croissant batch in one call.

    With the default two racks the batch plans 80 units, 27.00 planned labor
    minutes and 600 cents of ingredient cost, and completing it at full yield
    settles a unit cost basis of 8 cents.
    """
    run = schedule_par_baked_run(
        setup,
        rack_count=rack_count,
        deck_index=deck_index,
        bake_start_utc=bake_start_utc,
        oven=oven,
        headers=headers,
    )
    yielded = run["planned_units"] if actual_units is None else actual_units
    return drive_run_to_completed(
        run,
        "PAR_BAKED",
        yielded,
        actual_labor_minutes=actual_labor_minutes,
        headers=headers,
    )


def create_completed_scratch_run(
    setup,
    rack_count=4,
    actual_units=None,
    actual_labor_minutes=None,
    deck_index=0,
    bake_start_utc="2026-08-12T04:45:00Z",
    proof_start_utc=SHIFT_START,
    oven=None,
    headers=BAKER,
):
    """Schedule, proof, bake and complete a scratch dinner-roll batch."""
    run = schedule_scratch_run(
        setup,
        rack_count=rack_count,
        deck_index=deck_index,
        bake_start_utc=bake_start_utc,
        proof_start_utc=proof_start_utc,
        oven=oven,
        headers=headers,
    )
    yielded = run["planned_units"] if actual_units is None else actual_units
    return drive_run_to_completed(
        run,
        "SCRATCH",
        yielded,
        actual_labor_minutes=actual_labor_minutes,
        headers=headers,
    )


# --- Tier 4: waste, shrink and markdown targeting ---------------------------

def attest_waste(run_id, units, disposition_reason="DAMAGED", headers=SECOND_BAKER):
    """Attest waste against a completed run.

    The default attesting identity is the second baker, because the operator who
    completed the run may not write it off.
    """
    return get_success_data(
        api_client.create_waste_record(
            create_waste_record_payload(run_id, units, disposition_reason), headers
        )
    )


def void_waste(record_id, department, void_reason="Mis-attested batch"):
    manager = make_department_manager_headers(department["id"])
    return get_success_data(
        api_client.void_waste_record(
            record_id, void_waste_record_payload(void_reason), manager
        )
    )


def setup_completed_run_with_waste(
    waste_units=10,
    rack_count=2,
    actual_units=None,
    disposition_reason="DAMAGED",
    shrink_budget_pct=None,
    **planned_day_kwargs,
):
    """A completed croissant batch with waste already attested against it.

    Returns the ``setup_planned_day`` dict plus ``run`` (re-read after the
    attestation), ``waste_record`` and the refreshed ``bake_day``.
    """
    if shrink_budget_pct is not None:
        overrides = dict(planned_day_kwargs.pop("department_overrides", None) or {})
        overrides["shrink_budget_pct"] = shrink_budget_pct
        planned_day_kwargs["department_overrides"] = overrides
    setup = setup_planned_day(**planned_day_kwargs)
    run = create_completed_par_baked_run(
        setup, rack_count=rack_count, actual_units=actual_units
    )
    record = attest_waste(run["id"], waste_units, disposition_reason)
    setup["run"] = read_run(run["id"])
    setup["waste_record"] = record
    setup["bake_day"] = read_bake_day(setup["bake_day"]["id"])
    return setup


def lock_day(bake_day, department):
    """Lock the plan. Returns the ``LOCKED`` bake day."""
    manager = make_department_manager_headers(department["id"])
    return get_success_data(api_client.lock_plan(bake_day["id"], manager))


def close_day(bake_day, department, donate_remaining=None):
    """Close the day. Returns the ``CLOSED`` bake day."""
    manager = make_department_manager_headers(department["id"])
    return get_success_data(
        api_client.close_bake_day(
            bake_day["id"], close_bake_day_payload(donate_remaining), manager
        )
    )


def lock_and_close_day(bake_day, department, donate_remaining=None):
    locked = lock_day(bake_day, department)
    return close_day(locked, department, donate_remaining=donate_remaining)


# --- Tier 4: purchasing ------------------------------------------------------

def raise_ingredient_order(
    department, lines, expected_version=None, target_bake_day_id=None
):
    """Raise a manual ingredient order under the department's current version."""
    manager = make_department_manager_headers(department["id"])
    version = (
        read_department(department["id"])["version"]
        if expected_version is None
        else expected_version
    )
    payload = create_ingredient_order_payload(
        department["id"], version, lines, target_bake_day_id=target_bake_day_id
    )
    return get_success_data(api_client.create_ingredient_order(payload, manager))


def order_line(ingredient_id, required_units):
    return ingredient_order_line(ingredient_id, required_units)


def submit_order(order_id, department):
    manager = make_department_manager_headers(department["id"])
    return get_success_data(api_client.submit_ingredient_order(order_id, manager))


def cancel_order(order_id, department, cancel_reason="Supplier out of stock"):
    manager = make_department_manager_headers(department["id"])
    return get_success_data(
        api_client.cancel_ingredient_order(
            order_id, cancel_ingredient_order_payload(cancel_reason), manager
        )
    )


def setup_submitted_ingredient_order(
    flour_units=100, sugar_units=75, clock=DEFAULT_TEST_CLOCK, **reference_kwargs
):
    """Reference data plus one SUBMITTED two-line ingredient order.

    Returns the reference dict plus ``ingredient_order`` (as submitted).
    """
    reference_kwargs.setdefault("clock", clock)
    setup = setup_reference_data(**reference_kwargs)
    lines = [
        order_line(setup["flour"]["id"], flour_units),
        order_line(setup["sugar"]["id"], sugar_units),
    ]
    order = raise_ingredient_order(setup["department"], lines)
    setup["ingredient_order"] = submit_order(order["id"], setup["department"])
    return setup


def list_ingredient_orders_for_department(department_id, **filters):
    params = {"department_id": department_id}
    params.update(filters)
    response = api_client.list_ingredient_orders(REGIONAL_ADMIN, params=params)
    body = response.json()
    return body["data"], body["meta"]


# --- Tier 5: pickup windows and the custom cake lane ------------------------

def open_pickup_slot(
    bake_day,
    slot_start_utc="2026-08-12T14:00:00Z",
    slot_end_utc="2026-08-12T16:00:00Z",
    decorator_capacity_units=10,
    headers=CAKE_DESK,
):
    """Open a half-open decorator window on the bake day."""
    return get_success_data(
        api_client.create_pickup_slot(
            create_pickup_slot_payload(
                bake_day["id"],
                slot_start_utc=slot_start_utc,
                slot_end_utc=slot_end_utc,
                decorator_capacity_units=decorator_capacity_units,
            ),
            headers,
        )
    )


def take_cake_order(
    bake_day,
    pickup_slot,
    product_id,
    decoration_complexity="STANDARD",
    tier_count=2,
    headers=CAKE_DESK,
    **overrides,
):
    """Take a custom cake order in ``INTAKE`` against the window."""
    payload = create_cake_order_payload(
        bake_day["id"],
        pickup_slot["id"],
        product_id,
        decoration_complexity=decoration_complexity,
        tier_count=tier_count,
        **overrides,
    )
    return get_success_data(api_client.create_cake_order(payload, headers))


def confirm_cake_order(order_id, headers=CAKE_DESK):
    return get_success_data(api_client.confirm_cake_order(order_id, headers))


def start_cake_decoration(order_id, headers=DECORATOR):
    return get_success_data(api_client.start_decoration(order_id, headers))


def mark_cake_ready(order_id, headers=DECORATOR):
    return get_success_data(api_client.cake_order_ready(order_id, headers))


def pick_up_cake(order_id, headers=CAKE_DESK):
    return get_success_data(api_client.pickup_cake_order(order_id, headers))


def setup_confirmed_cake_order(
    decoration_complexity="STANDARD",
    tier_count=2,
    decorator_capacity_units=10,
    slot_start_utc="2026-08-12T14:00:00Z",
    slot_end_utc="2026-08-12T16:00:00Z",
    **planned_day_kwargs,
):
    """A planned day with an open window and one CONFIRMED cake order.

    With the default standard complexity over two tiers the order carries 8
    decoration units and a 180-minute lead, so its deadline is 11:00Z on the
    business date and the window reserves 8 of its 10 units.
    """
    setup = setup_planned_day(**planned_day_kwargs)
    slot = open_pickup_slot(
        setup["bake_day"],
        slot_start_utc=slot_start_utc,
        slot_end_utc=slot_end_utc,
        decorator_capacity_units=decorator_capacity_units,
    )
    order = take_cake_order(
        setup["bake_day"],
        slot,
        setup["cake_base"]["id"],
        decoration_complexity=decoration_complexity,
        tier_count=tier_count,
    )
    setup["pickup_slot"] = read_pickup_slot(slot["id"])
    setup["cake_order"] = confirm_cake_order(order["id"])
    setup["pickup_slot"] = read_pickup_slot(slot["id"])
    return setup


def setup_cake_order_in_decoration(**kwargs):
    """A planned day with one cake order already pulled into decoration."""
    setup = setup_confirmed_cake_order(**kwargs)
    setup["cake_order"] = start_cake_decoration(setup["cake_order"]["id"])
    return setup


# --- oven service state ------------------------------------------------------

def set_oven_status(oven_id, department, oven_status, status_reason=None):
    manager = make_department_manager_headers(department["id"])
    return get_success_data(
        api_client.set_oven_status(
            oven_id, oven_status_payload(oven_status, status_reason), manager
        )
    )
