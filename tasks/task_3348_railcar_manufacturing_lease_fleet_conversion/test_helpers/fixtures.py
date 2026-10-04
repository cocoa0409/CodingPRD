"""Composite setup helpers — the multi-step preambles tests need before asserting.

Most claims in this API require the system to be in a specific state that takes
five to twenty calls to reach: a retained order must be catalogued, sourced,
reserved, released, scheduled and completed before a fleet car exists at all.
These helpers encapsulate those sequences so tests can assert rather than plumb.

Conventions
-----------
* Every helper returns a plain ``dict`` ("world") whose keys are named after the
  domain objects it produced, so callers read ``world["order"]["id"]`` rather
  than unpacking an anonymous tuple.
* Every helper accepts keyword overrides for the values a test needs to control
  (dates, quantities, rates, caps) and supplies sensible defaults for the rest.
* Setup steps use ``get_success_data()`` so a broken precondition raises a clear
  "Setup failed at <step>" error instead of a confusing assertion failure.
* Every helper sets the logical clock before it writes anything dated, because
  the API never reads wall-clock time.
* Each test runs against a freshly restarted server with an empty database, so
  helpers build their preconditions from scratch and never rely on prior state.
"""

from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START_DATE,
    CLOCK_START_ISO,
    DEFAULT_PAGE_LIMIT,
    TEST_DEFAULTS as D,
)
from .factories import (
    changeover_payload,
    complete_production_order_payload,
    create_car_assignment_payload,
    create_car_return_payload,
    create_car_type_component_requirement_payload,
    create_car_type_payload,
    create_component_payload,
    create_component_purchase_order_payload,
    create_component_receipt_payload,
    create_lease_contract_payload,
    create_lease_fleet_sale_payload,
    create_lessee_payload,
    create_production_order_payload,
    create_retrofit_program_car_type_payload,
    create_retrofit_program_payload,
    create_retrofit_work_order_payload,
    create_substitution_endorsement_payload,
    days_between,
    draft_lease_amendment_payload,
    iso_date,
    patch_substitution_endorsement_payload,
    ratify_lease_amendment_payload,
    reassign_car_assignment_payload,
    release_production_order_payload,
    scrap_lease_fleet_car_payload,
    shift_date,
    suspend_car_assignment_payload,
    terminate_lease_contract_payload,
)
from .test_users import TEST_USERS, make_lessee_headers

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
PLANNER_2 = TEST_USERS["production_planner_2_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
LEASE_2 = TEST_USERS["lease_administrator_2_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]


# ─── Low-level helpers ────────────────────────────────

def _data(response, step: str) -> dict:
    """Lenient 2xx unwrap that names the failing setup step."""
    try:
        return get_success_data(response)
    except AssertionError as exc:  # pragma: no cover - setup guard
        raise AssertionError(f"Setup failed at {step}: {exc}") from exc


def _list(response, step: str) -> list:
    """Unwrap a list payload, asserting the array envelope."""
    data = _data(response, step)
    assert isinstance(data, list), (
        f"Setup failed at {step}: expected an array payload, got {type(data).__name__}"
    )
    return data


def set_clock(to_iso8601: str = CLOCK_START_ISO):
    """Pin the logical clock. Every dated rule is evaluated against it."""
    return _data(
        api_client.set_current_utc(to_iso8601, ADMIN), f"set clock to {to_iso8601}"
    )


def advance_clock_to(to_iso8601: str):
    """Move the logical clock forward to a specific instant."""
    return set_clock(to_iso8601)


def _first_car_for_order(order_id: str) -> dict:
    """The first fleet car produced by an order (results are creation-ordered)."""
    cars = _list(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": order_id, "limit": DEFAULT_PAGE_LIMIT}
        ),
        f"list fleet cars for order {order_id}",
    )
    assert cars, f"Setup failed: order {order_id} produced no fleet cars"
    return cars[0]


def _all_cars_for_order(order_id: str) -> list:
    return _list(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": order_id, "limit": DEFAULT_PAGE_LIMIT}
        ),
        f"list fleet cars for order {order_id}",
    )


# ─── Tier 2: catalogue and commercial preamble ────────

def setup_catalogue(
    model_code: str = None,
    car_class: str = None,
    build_hours: int = None,
    regulatory_life_years: int = None,
    line_count_family: str = None,
    wheelset_part_number: str = None,
    casting_part_number: str = None,
    coating_part_number: str = None,
    wheelset_unit_cost_cents: int = None,
    casting_unit_cost_cents: int = None,
    coating_unit_cost_cents: int = None,
    wheelset_qty_per_car: int = None,
    casting_qty_per_car: int = None,
    coating_qty_per_car: int = None,
    lead_time_days: int = None,
    wheelset_lead_time_days: int = None,
    casting_lead_time_days: int = None,
    coating_lead_time_days: int = None,
    on_hand_qty: int = None,
    wheelset_overrides: Optional[dict] = None,
    casting_overrides: Optional[dict] = None,
    coating_overrides: Optional[dict] = None,
    car_type_overrides: Optional[dict] = None,
    include_coating: bool = True,
    include_casting: bool = True,
    include_bom: bool = True,
    set_clock_first: bool = True,
):
    """Clock + one car type + a wheelset/casting/coating catalogue + BOM rows.

    Returns a world with ``car_type``, ``wheelset``, ``casting``, ``coating``
    (``None`` when ``include_coating`` is false) and ``bom`` (a list of rows).

    ``include_casting`` is the sibling switch for car types whose recipes name a
    one-row WHEELSET bill of materials; it suppresses both the casting component
    and its bill-of-material row.

    The per-component ``*_overrides`` dicts are merged into that component's
    registration body, which is how a caller pins an exact stock position or
    lead time for a boundary test.
    """
    if set_clock_first:
        set_clock(CLOCK_START_ISO)

    lead = lead_time_days if lead_time_days is not None else D["COMPONENT_LEAD_TIME_DAYS"]
    stock = on_hand_qty if on_hand_qty is not None else D["COMPONENT_ON_HAND_QTY"]

    car_type = _data(
        api_client.create_car_type(
            create_car_type_payload(
                model_code=model_code,
                car_class=car_class,
                build_hours=build_hours,
                regulatory_life_years=regulatory_life_years,
                line_count_family=line_count_family,
                **(car_type_overrides or {}),
            ),
            PLANNER,
        ),
        "create car type",
    )

    # Default part numbers are keyed off the model code so that a test which
    # builds two catalogues in one scenario does not collide on the declared
    # uniqueness rule for `part_number` (PRD 2.11, sixteenth).
    code = model_code or D["CAR_TYPE_MODEL_CODE"]

    wheelset = _data(
        api_client.create_component(
            create_component_payload(
                part_number=wheelset_part_number or f"WS-{code}",
                component_class="WHEELSET",
                unit_cost_cents=(
                    wheelset_unit_cost_cents
                    if wheelset_unit_cost_cents is not None
                    else D["COMPONENT_WHEELSET_UNIT_COST_CENTS"]
                ),
                lead_time_days=(
                    wheelset_lead_time_days
                    if wheelset_lead_time_days is not None
                    else lead
                ),
                **{"on_hand_qty": stock, **(wheelset_overrides or {})},
            ),
            SUPPLY,
        ),
        "create wheelset component",
    )
    casting = None
    if include_casting:
        casting = _data(
            api_client.create_component(
                create_component_payload(
                    part_number=casting_part_number or f"CS-{code}",
                    component_class="CASTING",
                    unit_cost_cents=(
                        casting_unit_cost_cents
                        if casting_unit_cost_cents is not None
                        else D["COMPONENT_CASTING_UNIT_COST_CENTS"]
                    ),
                    lead_time_days=(
                        casting_lead_time_days
                        if casting_lead_time_days is not None
                        else lead
                    ),
                    **{"on_hand_qty": stock, **(casting_overrides or {})},
                ),
                SUPPLY,
            ),
            "create casting component",
        )

    coating = None
    if include_coating:
        coating = _data(
            api_client.create_component(
                create_component_payload(
                    part_number=coating_part_number or f"CT-{code}",
                    component_class="COATING",
                    unit_cost_cents=(
                        coating_unit_cost_cents
                        if coating_unit_cost_cents is not None
                        else D["COMPONENT_COATING_UNIT_COST_CENTS"]
                    ),
                    lead_time_days=(
                        coating_lead_time_days
                        if coating_lead_time_days is not None
                        else lead
                    ),
                    **{"on_hand_qty": stock, **(coating_overrides or {})},
                ),
                SUPPLY,
            ),
            "create coating component",
        )

    bom: List[dict] = []
    if include_bom:
        rows = [(wheelset, wheelset_qty_per_car, D["BOM_WHEELSET_QTY_PER_CAR"])]
        if casting is not None:
            rows.append((casting, casting_qty_per_car, D["BOM_CASTING_QTY_PER_CAR"]))
        if coating is not None:
            rows.append((coating, coating_qty_per_car, D["BOM_COATING_QTY_PER_CAR"]))
        for component, qty, default_qty in rows:
            bom.append(
                _data(
                    api_client.create_car_type_component_requirement(
                        create_car_type_component_requirement_payload(
                            car_type_id=car_type["id"],
                            component_id=component["id"],
                            qty_per_car=qty if qty is not None else default_qty,
                        ),
                        PLANNER,
                    ),
                    f"add bill-of-material row for {component['part_number']}",
                )
            )

    return {
        "car_type": car_type,
        "wheelset": wheelset,
        "casting": casting,
        "coating": coating,
        "components": [c for c in (wheelset, casting, coating) if c is not None],
        "bom": bom,
    }


def create_lessee_and_contract(
    legal_name: str = None,
    credit_tier: str = None,
    utilization_threshold_pct: int = None,
    credit_ceiling_cents: int = None,
    lease_type: str = None,
    per_diem_rate_cents: int = None,
    liability_bearer: str = None,
    term_start_date: str = None,
    term_end_date: str = None,
    fleet_car_cap: int = None,
    activate: bool = True,
    set_clock_first: bool = False,
):
    """Register a lessee and write a contract for it, optionally activating it.

    Returns ``{"lessee": ..., "contract": ...}``.
    """
    if set_clock_first:
        set_clock(CLOCK_START_ISO)

    lessee = _data(
        api_client.create_lessee(
            create_lessee_payload(
                legal_name=legal_name,
                credit_tier=credit_tier,
                utilization_threshold_pct=utilization_threshold_pct,
                credit_ceiling_cents=credit_ceiling_cents,
            ),
            LEASE,
        ),
        "create lessee",
    )
    contract = _data(
        api_client.create_lease_contract(
            create_lease_contract_payload(
                lessee_id=lessee["id"],
                lease_type=lease_type,
                per_diem_rate_cents=per_diem_rate_cents,
                liability_bearer=liability_bearer,
                term_start_date=term_start_date,
                term_end_date=term_end_date,
                fleet_car_cap=fleet_car_cap,
            ),
            LEASE,
        ),
        "create lease contract",
    )
    if activate:
        contract = _data(
            api_client.activate_lease_contract(contract["id"], LEASE),
            "activate lease contract",
        )
    return {"lessee": lessee, "contract": contract}


def setup_catalogue_with_contract(
    include_coating: bool = True,
    fleet_car_cap: int = None,
    per_diem_rate_cents: int = None,
    liability_bearer: str = None,
    lease_type: str = None,
    credit_ceiling_cents: int = None,
    legal_name: str = None,
    **catalogue_kwargs,
):
    """The most common preamble: catalogue plus an ACTIVE contract."""
    world = setup_catalogue(include_coating=include_coating, **catalogue_kwargs)
    world.update(
        create_lessee_and_contract(
            legal_name=legal_name,
            credit_ceiling_cents=credit_ceiling_cents,
            lease_type=lease_type,
            per_diem_rate_cents=per_diem_rate_cents,
            liability_bearer=liability_bearer,
            fleet_car_cap=fleet_car_cap,
            activate=True,
        )
    )
    return world


# ─── Purchasing path ──────────────────────────────────

def receive_component_stock(
    component: dict,
    qty: int,
    order_date: str = None,
    receipt_date: Optional[str] = None,
    confirm: bool = True,
    apply_receipt: bool = True,
):
    """Raise, confirm and receive a purchase order so stock lands on hand.

    The expected receipt date is derived as the order date plus the component's
    supplier lead time, which is the derivation the PRD prescribes when the date
    is not negotiated.
    """
    order_date = order_date or CLOCK_START_DATE
    lead = component.get("lead_time_days", D["COMPONENT_LEAD_TIME_DAYS"])
    expected = shift_date(order_date, lead)
    purchase_order = _data(
        api_client.create_component_purchase_order(
            create_component_purchase_order_payload(
                component_id=component["id"],
                qty_ordered=qty,
                unit_cost_cents=component["unit_cost_cents"],
                order_date=order_date,
                expected_receipt_date=expected,
            ),
            SUPPLY,
        ),
        "create component purchase order",
    )
    if confirm:
        purchase_order = _data(
            api_client.confirm_component_purchase_order(purchase_order["id"], SUPPLY),
            "confirm component purchase order",
        )
    receipt = None
    if apply_receipt:
        receipt = _data(
            api_client.create_component_receipt(
                create_component_receipt_payload(
                    component_purchase_order_id=purchase_order["id"],
                    component_id=component["id"],
                    qty_received=qty,
                    receipt_date=receipt_date or expected,
                ),
                SUPPLY,
            ),
            "book component receipt",
        )
        receipt = _data(
            api_client.receive_component_receipt(receipt["id"], SUPPLY),
            "apply component receipt",
        )
    return {
        "purchase_order": purchase_order,
        "receipt": receipt,
        "expected_receipt_date": expected,
    }


def ensure_coating_supply(
    coating: dict, qty: int, required_delivery_date: str, order_date: str = None
):
    """Confirm a coating purchase order that covers an order's delivery window.

    Release requires every coating row to have a purchase order in CONFIRMED or
    RECEIVED status whose expected receipt date is on or before the order's
    required delivery date.
    """
    order_date = order_date or CLOCK_START_DATE
    expected = shift_date(order_date, coating.get("lead_time_days", 10))
    if expected > required_delivery_date:
        # Pull the order date back so the derived receipt date still lands
        # inside the delivery window.
        order_date = shift_date(required_delivery_date, -coating.get("lead_time_days", 10))
        expected = shift_date(order_date, coating.get("lead_time_days", 10))
    purchase_order = _data(
        api_client.create_component_purchase_order(
            create_component_purchase_order_payload(
                component_id=coating["id"],
                qty_ordered=qty,
                unit_cost_cents=coating["unit_cost_cents"],
                order_date=order_date,
                expected_receipt_date=expected,
            ),
            SUPPLY,
        ),
        "create coating purchase order",
    )
    purchase_order = _data(
        api_client.confirm_component_purchase_order(purchase_order["id"], SUPPLY),
        "confirm coating purchase order",
    )
    return {"purchase_order": purchase_order, "expected_receipt_date": expected}


# ─── Tier 1/3: production order lifecycle ─────────────

def worst_gated_lead_days(catalogue: dict) -> int:
    """The worst gated component lead time: ceil(lead_time_days / qty_per_car)."""
    from .constants import GATED_COMPONENT_CLASSES

    by_id = {c["id"]: c for c in catalogue["components"]}
    worst = 0
    for row in catalogue["bom"]:
        component = by_id.get(row["component_id"])
        if component is None:
            continue
        if component["component_class"] in GATED_COMPONENT_CLASSES:
            derived = -(-component["lead_time_days"] // row["qty_per_car"])
            worst = max(worst, derived)
    return worst


def feasible_delivery_date(
    catalogue: dict, order_date: str = None, slack_days: int = 60
) -> str:
    """A delivery date comfortably clear of the worst gated lead time."""
    order_date = order_date or CLOCK_START_DATE
    return shift_date(order_date, worst_gated_lead_days(catalogue) + slack_days)


def create_order(
    catalogue: dict,
    quantity: int = None,
    disposition: str = None,
    priority_rank: int = None,
    order_date: str = None,
    required_delivery_date: str = None,
    unit_price_cents: Optional[int] = None,
    lessee_id: Optional[str] = None,
    planned_shop_days: Optional[int] = None,
    **overrides,
) -> dict:
    """Take a production order against the catalogue's car type."""
    car_type = catalogue["car_type"]
    quantity = quantity if quantity is not None else D["ORDER_QUANTITY"]
    order_date = order_date or CLOCK_START_DATE
    if required_delivery_date is None:
        required_delivery_date = feasible_delivery_date(catalogue, order_date)
    if planned_shop_days is None:
        planned_shop_days = car_type["build_hours"] * quantity
    return _data(
        api_client.create_production_order(
            create_production_order_payload(
                car_type_id=car_type["id"],
                quantity=quantity,
                planned_shop_days=planned_shop_days,
                disposition=disposition,
                priority_rank=priority_rank,
                order_date=order_date,
                required_delivery_date=required_delivery_date,
                unit_price_cents=unit_price_cents,
                lessee_id=lessee_id,
                **overrides,
            ),
            PLANNER,
        ),
        "create production order",
    )


def reserve_order(order_id: str, headers=None) -> dict:
    """Commit stock to a draft order and re-quote it."""
    return _data(
        api_client.reserve_components(order_id, headers or PLANNER),
        f"reserve components for order {order_id}",
    )


def release_order(
    order_id: str, lease_contract_id: Optional[str] = None, headers=None
) -> dict:
    """Release a component-reserved order to the backlog."""
    return _data(
        api_client.release_production_order(
            order_id,
            headers or PLANNER,
            release_production_order_payload(lease_contract_id=lease_contract_id),
        ),
        f"release order {order_id}",
    )


def start_production(
    order_id: str,
    line: str,
    window_start: str = None,
    window_days: int = None,
    headers=None,
) -> dict:
    """Schedule a line changeover and move the head-of-backlog order into production."""
    window_start = window_start or shift_date(CLOCK_START_DATE, 4)
    if window_days is None:
        order = _data(
            api_client.get_production_order(order_id, ADMIN), "read order for window"
        )
        window_days = order["planned_shop_days"]
    return _data(
        api_client.changeover_production_line(
            line,
            changeover_payload(
                production_order_id=order_id,
                scheduled_start_date=window_start,
                scheduled_end_date=shift_date(window_start, window_days),
            ),
            headers or PLANNER,
        ),
        f"changeover line {line} for order {order_id}",
    )


def complete_order(
    order_id: str,
    completed_qty: Optional[int] = None,
    completion_date: Optional[str] = None,
    lessee_id: Optional[str] = None,
    headers=None,
) -> dict:
    """Complete the remaining cars of an in-production order."""
    if completed_qty is None:
        order = _data(
            api_client.get_production_order(order_id, ADMIN), "read order for completion"
        )
        completed_qty = order["quantity"] - order["completed_qty"]
    return _data(
        api_client.complete_production_order(
            order_id,
            complete_production_order_payload(
                completed_qty=completed_qty,
                completion_date=completion_date,
                lessee_id=lessee_id,
            ),
            headers or PLANNER,
        ),
        f"complete order {order_id}",
    )


def setup_order_in_state(
    target_status: str,
    catalogue: dict = None,
    quantity: int = None,
    disposition: str = None,
    priority_rank: int = None,
    order_date: str = None,
    required_delivery_date: str = None,
    lessee_id: Optional[str] = None,
    lease_contract_id: Optional[str] = None,
    line: Optional[str] = None,
    changeover_start: str = None,
    completion_date: Optional[str] = None,
    coating_qty: Optional[int] = None,
    **order_kwargs,
):
    """Walk the production order state machine to ``target_status``.

    Legal targets are ``DRAFT``, ``COMPONENT_RESERVED``, ``RELEASED``,
    ``IN_PRODUCTION``, ``COMPLETED`` and ``CANCELLED``.
    """
    catalogue = catalogue or setup_catalogue()
    line = line or catalogue["car_type"]["line_count_family"]
    world = {"catalogue": catalogue}

    order = create_order(
        catalogue,
        quantity=quantity,
        disposition=disposition,
        priority_rank=priority_rank,
        order_date=order_date,
        required_delivery_date=required_delivery_date,
        lessee_id=lessee_id,
        **order_kwargs,
    )
    world["order"] = order
    if target_status == "DRAFT":
        return world

    if target_status == "CANCELLED":
        world["order"] = _data(
            api_client.cancel_production_order(order["id"], PLANNER),
            f"cancel order {order['id']}",
        )
        return world

    order = reserve_order(order["id"])
    world["order"] = order
    if target_status == "COMPONENT_RESERVED":
        return world

    # Release needs a coating purchase order covering the delivery window.
    coating = catalogue.get("coating")
    if coating is not None and coating_qty is not None:
        ensure_coating_supply(
            coating,
            coating_qty,
            order["required_delivery_date"],
            order_date=order["order_date"],
        )
    elif coating is not None:
        ensure_coating_supply(
            coating,
            order["quantity"],
            order["required_delivery_date"],
            order_date=order["order_date"],
        )

    order = release_order(order["id"], lease_contract_id=lease_contract_id)
    world["order"] = order
    if target_status == "RELEASED":
        return world

    order = start_production(
        order["id"], line, window_start=changeover_start, headers=PLANNER
    )
    world["order"] = order
    if target_status == "IN_PRODUCTION":
        return world

    order = complete_order(
        order["id"], completion_date=completion_date, lessee_id=lessee_id
    )
    world["order"] = order
    return world


def setup_released_order(catalogue: dict = None, **kwargs):
    """Catalogue + contract (optional) + an order walked to RELEASED."""
    catalogue = catalogue or setup_catalogue()
    kwargs.setdefault("lease_contract_id", None)
    return setup_order_in_state("RELEASED", catalogue=catalogue, **kwargs)


def setup_in_production_order(catalogue: dict = None, **kwargs):
    """Catalogue + an order walked to IN_PRODUCTION."""
    catalogue = catalogue or setup_catalogue()
    return setup_order_in_state("IN_PRODUCTION", catalogue=catalogue, **kwargs)


# ─── Tier 5: fleet cars from retained orders ──────────

def setup_retained_order_with_fleet_cars(
    car_count: int = 1,
    catalogue: dict = None,
    contract: dict = None,
    lessee: dict = None,
    line: Optional[str] = None,
    order_date: str = None,
    changeover_start: str = None,
    completion_date: Optional[str] = None,
    priority_rank: int = 1,
    build_contract: bool = True,
    fleet_car_cap: int = None,
    per_diem_rate_cents: int = None,
    liability_bearer: str = None,
    lease_type: str = None,
    credit_ceiling_cents: int = None,
    legal_name: str = None,
    **order_kwargs,
):
    """Complete a RETAINED order so that ``car_count`` fleet cars exist in HELD.

    Returns a world with ``catalogue``, ``lessee``, ``contract``, ``order``,
    ``cars`` (creation-ordered) and ``car`` (the first one).
    """
    catalogue = catalogue or setup_catalogue()
    world = {"catalogue": catalogue}
    if build_contract and contract is None:
        world.update(
            create_lessee_and_contract(
                legal_name=legal_name,
                fleet_car_cap=fleet_car_cap,
                per_diem_rate_cents=per_diem_rate_cents,
                liability_bearer=liability_bearer,
                lease_type=lease_type,
                credit_ceiling_cents=credit_ceiling_cents,
            )
        )
    else:
        world["lessee"] = lessee
        world["contract"] = contract

    contract_id = world["contract"]["id"] if world.get("contract") else None
    order = create_order(
        catalogue,
        quantity=car_count,
        disposition="RETAINED",
        priority_rank=priority_rank,
        order_date=order_date,
        **order_kwargs,
    )
    world["order"] = order
    order = reserve_order(order["id"])
    coating = catalogue.get("coating")
    if coating is not None:
        ensure_coating_supply(
            coating, order["quantity"], order["required_delivery_date"],
            order_date=order["order_date"],
        )
    order = release_order(order["id"], lease_contract_id=contract_id)
    world["order"] = order
    line = line or catalogue["car_type"]["line_count_family"]
    order = start_production(
        order["id"], line, window_start=changeover_start, headers=PLANNER
    )
    world["order"] = order
    completion_date = completion_date or order.get("required_delivery_date")
    if completion_date is None or completion_date > order["required_delivery_date"]:
        completion_date = order["required_delivery_date"]
    order = complete_order(order["id"], completion_date=completion_date)
    world["order"] = order

    cars = _all_cars_for_order(order["id"])
    world["cars"] = cars
    world["car"] = cars[0] if cars else None
    return world


def setup_fleet_cars(
    car_count: int = 1, catalogue: dict = None, **kwargs
):
    """Alias for a retained completion producing ``car_count`` HELD cars."""
    return setup_retained_order_with_fleet_cars(
        car_count=car_count, catalogue=catalogue, **kwargs
    )


# ─── Placements ───────────────────────────────────────

def create_assignment(
    car: dict,
    contract: dict,
    lessee: dict,
    start_date: str = None,
    end_date: str = None,
    mileage_allowance: int = None,
    headers=None,
) -> dict:
    """Place a free car with a lessee under an active contract."""
    return _data(
        api_client.create_car_assignment(
            create_car_assignment_payload(
                lease_fleet_car_id=car["id"],
                lease_contract_id=contract["id"],
                lessee_id=lessee["id"],
                start_date=start_date,
                end_date=end_date,
                mileage_allowance=mileage_allowance,
            ),
            headers or LEASE,
        ),
        f"create placement for car {car['id']}",
    )


def setup_assigned_car(
    catalogue: dict = None,
    start_date: str = None,
    end_date: str = None,
    assignment_days: int = None,
    mileage_allowance: int = None,
    per_diem_rate_cents: int = None,
    liability_bearer: str = None,
    lease_type: str = None,
    fleet_car_cap: int = None,
    credit_ceiling_cents: int = None,
    legal_name: str = None,
    car_count: int = 1,
    **order_kwargs,
):
    """A HELD fleet car placed with a lessee under an ACTIVE contract.

    Returns a world with ``catalogue``, ``lessee``, ``contract``, ``order``,
    ``car``, ``cars`` and ``assignment``.

    When the window is not supplied it opens on the car's build date — a car
    cannot be placed before it exists — and runs for ``assignment_days``
    (thirty by default).  The end date is exclusive.
    """
    world = setup_retained_order_with_fleet_cars(
        car_count=car_count,
        catalogue=catalogue,
        per_diem_rate_cents=per_diem_rate_cents,
        liability_bearer=liability_bearer,
        lease_type=lease_type,
        fleet_car_cap=fleet_car_cap,
        credit_ceiling_cents=credit_ceiling_cents,
        legal_name=legal_name,
        **order_kwargs,
    )
    if start_date is None:
        start_date = max(CLOCK_START_DATE, world["car"]["built_date"])
    if end_date is None:
        end_date = shift_date(start_date, assignment_days or 30)
    world["assignment_start_date"] = start_date
    world["assignment_end_date"] = end_date
    world["assignment"] = create_assignment(
        world["car"],
        world["contract"],
        world["lessee"],
        start_date=start_date,
        end_date=end_date,
        mileage_allowance=mileage_allowance,
    )
    world["car"] = _data(
        api_client.get_lease_fleet_car(world["car"]["id"], ADMIN), "read placed car"
    )
    return world


def suspend_assignment(assignment_id: str, suspend_date: Optional[str] = None) -> dict:
    return _data(
        api_client.suspend_car_assignment(
            assignment_id, LEASE, suspend_car_assignment_payload(suspend_date)
        ),
        f"suspend placement {assignment_id}",
    )


def resume_assignment(assignment_id: str) -> dict:
    return _data(
        api_client.resume_car_assignment(assignment_id, LEASE),
        f"resume placement {assignment_id}",
    )


def reassign_assignment(
    assignment_id: str, target_car_id: str, effective_date: Optional[str] = None
) -> dict:
    return _data(
        api_client.reassign_car_assignment(
            assignment_id,
            reassign_car_assignment_payload(target_car_id, effective_date),
            LEASE,
        ),
        f"reassign placement {assignment_id}",
    )


# ─── Returns and the repair queue ─────────────────────

def create_return(
    car: dict,
    assignment: dict,
    return_date: str = None,
    mileage_since_last: int = 0,
    condition_grade: str = "A",
    headers=None,
) -> dict:
    """Record a car coming back off a placement."""
    return_date = return_date or assignment["end_date"]
    return _data(
        api_client.create_car_return(
            create_car_return_payload(
                lease_fleet_car_id=car["id"],
                car_assignment_id=assignment["id"],
                return_date=return_date,
                mileage_since_last=mileage_since_last,
                condition_grade=condition_grade,
            ),
            headers or LEASE,
        ),
        f"record return for placement {assignment['id']}",
    )


def settle_return(return_id: str) -> dict:
    return _data(
        api_client.settle_car_return(return_id, PORTFOLIO),
        f"settle return {return_id}",
    )


def setup_car_in_repair(
    catalogue: dict = None,
    start_date: str = None,
    end_date: str = None,
    mileage_allowance: int = None,
    mileage_since_last: int = 0,
    condition_grade: str = "A",
    per_diem_rate_cents: int = None,
    liability_bearer: str = None,
    lease_type: str = None,
    car_count: int = 1,
    **order_kwargs,
):
    """A car that has been placed and returned, now sitting in UNDER_REPAIR.

    Returns the assigned-car world plus ``car_return`` and the refreshed ``car``.
    """
    world = setup_assigned_car(
        catalogue=catalogue,
        start_date=start_date,
        end_date=end_date,
        mileage_allowance=mileage_allowance,
        per_diem_rate_cents=per_diem_rate_cents,
        liability_bearer=liability_bearer,
        lease_type=lease_type,
        car_count=car_count,
        **order_kwargs,
    )
    world["car_return"] = create_return(
        world["car"],
        world["assignment"],
        mileage_since_last=mileage_since_last,
        condition_grade=condition_grade,
    )
    world["assignment"] = _data(
        api_client.get_car_assignment(world["assignment"]["id"], ADMIN),
        "read closed placement",
    )
    world["car"] = _data(
        api_client.get_lease_fleet_car(world["car"]["id"], ADMIN), "read repaired car"
    )
    return world


def setup_returned_car_ready_to_settle(
    catalogue: dict = None, **kwargs
):
    """A car in UNDER_REPAIR with one PENDING return awaiting settlement."""
    return setup_car_in_repair(catalogue=catalogue, **kwargs)


def setup_car_back_in_fleet(
    catalogue: dict = None, settle: bool = True, **kwargs
):
    """A returned car walked all the way back to HELD.

    Settles the return and then closes the repair queue.
    """
    world = setup_car_in_repair(catalogue=catalogue, **kwargs)
    if settle:
        world["car_return"] = settle_return(world["car_return"]["id"])
    world["car"] = _data(
        api_client.settle_fleet_car_returns(world["car"]["id"], PLANNER),
        "release car from the repair queue",
    )
    return world


# ─── Secondary-market sales ───────────────────────────

def book_value_cents(car: dict, sale_date: str) -> int:
    """Acquisition cost less daily depreciation over the car's age in days."""
    from .constants import DAILY_DEPRECIATION_CENTS

    age_days = days_between(car["built_date"], sale_date)
    return car["acquisition_cost_cents"] - age_days * DAILY_DEPRECIATION_CENTS


def gain_over_book_cents(car: dict, sale_date: str, sale_price_cents: int) -> int:
    """The sale price less the car's depreciated book value."""
    return sale_price_cents - book_value_cents(car, sale_date)


def create_sale(
    car: dict,
    sale_price_cents: Optional[int] = None,
    sale_date: Optional[str] = None,
    writeback_liability_cents: int = 0,
    buyer_name: str = None,
    lease_contract_id: Optional[str] = None,
    net_book_value_cents: Optional[int] = None,
    lessee_id: Optional[str] = None,
    headers=None,
) -> dict:
    """Sell a HELD fleet car on the secondary market.

    When the price is not supplied it is derived so the settlement balances:
    the car's book value plus the writeback liability plus a margin.

    When the date is not supplied the car is sold on its build date, which
    keeps the depreciation age non-negative.
    """
    sale_date = sale_date or max(CLOCK_START_DATE, car["built_date"])
    if sale_price_cents is None:
        sale_price_cents = (
            book_value_cents(car, sale_date) + writeback_liability_cents + 100000
        )
    return _data(
        api_client.create_lease_fleet_sale(
            create_lease_fleet_sale_payload(
                lease_fleet_car_id=car["id"],
                buyer_name=buyer_name,
                sale_price_cents=sale_price_cents,
                sale_date=sale_date,
                writeback_liability_cents=writeback_liability_cents,
                lease_contract_id=lease_contract_id,
                net_book_value_cents=net_book_value_cents,
                lessee_id=lessee_id,
            ),
            headers or PORTFOLIO,
        ),
        f"create sale for car {car['id']}",
    )


def settle_sale(sale_id: str) -> dict:
    return _data(
        api_client.settle_lease_fleet_sale(sale_id, PORTFOLIO), f"settle sale {sale_id}"
    )


def void_sale(sale_id: str, reason: Optional[str] = None) -> dict:
    payload = {"reason": reason} if reason is not None else None
    return _data(
        api_client.void_lease_fleet_sale(sale_id, PORTFOLIO, payload),
        f"void sale {sale_id}",
    )


def setup_sold_car(
    catalogue: dict = None,
    sale_price_cents: Optional[int] = None,
    sale_date: Optional[str] = None,
    writeback_liability_cents: int = 0,
    settle: bool = False,
    **kwargs,
):
    """A HELD fleet car sold on the secondary market, optionally settled."""
    world = setup_retained_order_with_fleet_cars(catalogue=catalogue, **kwargs)
    world["sale"] = create_sale(
        world["car"],
        sale_price_cents=sale_price_cents,
        sale_date=sale_date,
        writeback_liability_cents=writeback_liability_cents,
    )
    if settle:
        world["sale"] = settle_sale(world["sale"]["id"])
    world["car"] = _data(
        api_client.get_lease_fleet_car(world["car"]["id"], ADMIN), "read sold car"
    )
    return world


# ─── Retrofit mandates ────────────────────────────────

def create_retrofit_program(
    catalogue: dict,
    mandate_code: str = None,
    compliance_deadline_date: str = None,
    required_shop_days_per_car: int = None,
    required_component_id: Optional[str] = None,
    cover_car_types: bool = True,
    description: str = None,
):
    """Open a mandate program and optionally cover the catalogue's car type."""
    program = _data(
        api_client.create_retrofit_program(
            create_retrofit_program_payload(
                mandate_code=mandate_code,
                description=description,
                compliance_deadline_date=compliance_deadline_date,
                required_shop_days_per_car=required_shop_days_per_car,
                required_component_id=required_component_id,
            ),
            RETROFIT,
        ),
        "create retrofit program",
    )
    coverage = None
    if cover_car_types:
        coverage = _data(
            api_client.create_retrofit_program_car_type(
                create_retrofit_program_car_type_payload(
                    retrofit_program_id=program["id"],
                    car_type_id=catalogue["car_type"]["id"],
                ),
                RETROFIT,
            ),
            "cover car type under retrofit program",
        )
    return {"program": program, "coverage": coverage}


def create_work_order(
    program: dict,
    car: dict,
    shop_line: str = None,
    scheduled_start_date: str = None,
    scheduled_end_date: str = None,
    component_qty_consumed: int = 1,
    headers=None,
) -> dict:
    """Schedule retrofit shop work on a shop line for a covered car."""
    shop_days = program.get("required_shop_days_per_car", 1)
    scheduled_start_date = scheduled_start_date or shift_date(CLOCK_START_DATE, 30)
    if scheduled_end_date is None:
        scheduled_end_date = shift_date(scheduled_start_date, shop_days)
    return _data(
        api_client.create_retrofit_work_order(
            create_retrofit_work_order_payload(
                retrofit_program_id=program["id"],
                lease_fleet_car_id=car["id"],
                shop_line=shop_line,
                scheduled_start_date=scheduled_start_date,
                scheduled_end_date=scheduled_end_date,
                component_qty_consumed=component_qty_consumed,
            ),
            headers or PLANNER,
        ),
        f"create retrofit work order for car {car['id']}",
    )


def setup_retrofit_program_with_car(
    catalogue: dict = None,
    required_shop_days_per_car: int = None,
    compliance_deadline_date: str = None,
    required_component_id: Optional[str] = None,
    start_program: bool = False,
    work_order_start: Optional[str] = None,
    shop_line: str = None,
    component_qty_consumed: int = 1,
    **car_kwargs,
):
    """A fleet car plus a mandate program that covers its car type.

    Returns the fleet-car world extended with ``program``, ``coverage`` and,
    when ``work_order_start`` is supplied, ``work_order``.
    """
    world = setup_retained_order_with_fleet_cars(catalogue=catalogue, **car_kwargs)
    world.update(
        create_retrofit_program(
            world["catalogue"],
            compliance_deadline_date=compliance_deadline_date,
            required_shop_days_per_car=required_shop_days_per_car,
            required_component_id=required_component_id,
        )
    )
    if start_program:
        world["program"] = _data(
            api_client.start_retrofit_program(world["program"]["id"], RETROFIT),
            "start retrofit program",
        )
    if work_order_start is not None:
        world["work_order"] = create_work_order(
            world["program"],
            world["car"],
            shop_line=shop_line,
            scheduled_start_date=work_order_start,
            component_qty_consumed=component_qty_consumed,
        )
        world["car"] = _data(
            api_client.get_lease_fleet_car(world["car"]["id"], ADMIN),
            "read car under retrofit",
        )
    return world


def setup_work_order_in_state(
    target_status: str, catalogue: dict = None, **kwargs
):
    """Walk a retrofit work order to SCHEDULED, IN_PROGRESS, COMPLETED or CANCELLED."""
    world = setup_retrofit_program_with_car(
        catalogue=catalogue, work_order_start=shift_date(CLOCK_START_DATE, 30), **kwargs
    )
    if target_status == "SCHEDULED":
        return world
    if target_status == "CANCELLED":
        world["work_order"] = _data(
            api_client.cancel_retrofit_work_order(world["work_order"]["id"], PLANNER),
            "cancel retrofit work order",
        )
        return world
    world["work_order"] = _data(
        api_client.start_retrofit_work_order(world["work_order"]["id"], PLANNER),
        "start retrofit work order",
    )
    if target_status == "IN_PROGRESS":
        return world
    world["work_order"] = _data(
        api_client.complete_retrofit_work_order(world["work_order"]["id"], PLANNER),
        "complete retrofit work order",
    )
    world["car"] = _data(
        api_client.get_lease_fleet_car(world["car"]["id"], ADMIN),
        "read car after retrofit completion",
    )
    return world


# ─── Substitution endorsements ────────────────────────

def create_endorsement(
    order: dict,
    original_component: dict,
    substitute_component: dict,
    substitute_qty_per_car: Optional[int] = None,
    decides_material: bool = False,
    expected_production_order_version: Optional[int] = None,
    headers=None,
) -> dict:
    """Raise an endorsement, defaulting the version precondition to the order's.

    The expected version is the order's current ``version``, which is the
    serialization point that stops a stale writer from superseding an
    endorsement it never saw.
    """
    if expected_production_order_version is None:
        order = _data(
            api_client.get_production_order(order["id"], ADMIN),
            "read order for endorsement version",
        )
        expected_production_order_version = order["version"]
    return _data(
        api_client.create_substitution_endorsement(
            create_substitution_endorsement_payload(
                production_order_id=order["id"],
                original_component_id=original_component["id"],
                substitute_component_id=substitute_component["id"],
                substitute_qty_per_car=substitute_qty_per_car,
                decides_material=decides_material,
                expected_production_order_version=expected_production_order_version,
            ),
            headers or PLANNER,
        ),
        f"create substitution endorsement on order {order['id']}",
    )


def approve_endorsement(endorsement_id: str, headers=None) -> dict:
    """Approve as a second person — never the operator that created it."""
    return _data(
        api_client.approve_substitution_endorsement(
            endorsement_id, headers or LEASE
        ),
        f"approve endorsement {endorsement_id}",
    )


def reject_endorsement(endorsement_id: str, headers=None) -> dict:
    return _data(
        api_client.patch_substitution_endorsement(
            endorsement_id,
            patch_substitution_endorsement_payload(status="REJECTED"),
            headers or LEASE,
        ),
        f"reject endorsement {endorsement_id}",
    )


def return_endorsement_to_pending(endorsement_id: str, headers=None) -> dict:
    return _data(
        api_client.patch_substitution_endorsement(
            endorsement_id,
            patch_substitution_endorsement_payload(status="PENDING"),
            headers or PLANNER,
        ),
        f"return endorsement {endorsement_id} to pending",
    )


def setup_order_with_endorsement(
    catalogue: dict = None,
    substitute_part_number: str = "WS-SUB",
    substitute_unit_cost_cents: int = None,
    substitute_on_hand_qty: int = 1000,
    substitute_qty_per_car: int = 4,
    decides_material: bool = False,
    quantity: int = 1,
    original_component_key: str = "wheelset",
    approve: bool = False,
    **order_kwargs,
):
    """A DRAFT order carrying one PENDING (or APPROVED) substitution endorsement."""
    catalogue = catalogue or setup_catalogue()
    substitute = _data(
        api_client.create_component(
            create_component_payload(
                part_number=substitute_part_number,
                component_class=catalogue[original_component_key]["component_class"],
                unit_cost_cents=(
                    substitute_unit_cost_cents
                    if substitute_unit_cost_cents is not None
                    else catalogue[original_component_key]["unit_cost_cents"]
                ),
                lead_time_days=catalogue[original_component_key]["lead_time_days"],
                on_hand_qty=substitute_on_hand_qty,
            ),
            SUPPLY,
        ),
        "create substitute component",
    )
    order = create_order(catalogue, quantity=quantity, **order_kwargs)
    endorsement = create_endorsement(
        order,
        catalogue[original_component_key],
        substitute,
        substitute_qty_per_car=substitute_qty_per_car,
        decides_material=decides_material,
    )
    world = {
        "catalogue": catalogue,
        "substitute": substitute,
        "order": order,
        "endorsement": endorsement,
    }
    if approve:
        world["endorsement"] = approve_endorsement(endorsement["id"])
    return world


# ─── Tier 4: threshold and boundary targeting ─────────

def required_stock(quantity: int, qty_per_car: int) -> int:
    """The on-hand quantity a covered bill-of-material row demands for an order."""
    return qty_per_car * quantity


def setup_order_at_stock_boundary(
    quantity: int = 10,
    wheelset_qty_per_car: int = 4,
    casting_qty_per_car: int = 2,
    wheelset_stock_delta: int = 0,
    casting_stock_delta: int = 0,
    disposition: str = "SOLD",
    **order_kwargs,
):
    """A DRAFT order whose covered stock sits exactly at (or beside) the requirement.

    ``*_stock_delta`` of 0 puts on-hand exactly at the requirement, which is the
    passing side of the shortage test; -1 puts it one unit short.
    """
    catalogue = setup_catalogue(
        wheelset_qty_per_car=wheelset_qty_per_car,
        casting_qty_per_car=casting_qty_per_car,
        wheelset_overrides={
            "on_hand_qty": required_stock(quantity, wheelset_qty_per_car)
            + wheelset_stock_delta
        },
        casting_overrides={
            "on_hand_qty": required_stock(quantity, casting_qty_per_car)
            + casting_stock_delta
        },
        coating_overrides={"on_hand_qty": 1_000_000},
    )
    order = create_order(
        catalogue, quantity=quantity, disposition=disposition, **order_kwargs
    )
    return {"catalogue": catalogue, "order": order}


def setup_order_at_lead_time_boundary(
    horizon_days: int,
    quantity: int = 1,
    lead_time_days: int = 10,
    qty_per_car: int = 1,
    **order_kwargs,
):
    """A car type with one gated row whose derived lead time is known.

    With ``qty_per_car`` 1 the derived lead time is the component's lead time,
    so ``horizon_days`` can be set to the worst lead (passes) or one day short.
    """
    catalogue = setup_catalogue(
        wheelset_qty_per_car=qty_per_car,
        casting_qty_per_car=1,
        include_coating=False,
        wheelset_overrides={"lead_time_days": lead_time_days},
        casting_overrides={"lead_time_days": 1},
    )
    order_date = order_kwargs.pop("order_date", None) or CLOCK_START_DATE
    order = create_order(
        catalogue,
        quantity=quantity,
        order_date=order_date,
        required_delivery_date=shift_date(order_date, horizon_days),
        **order_kwargs,
    )
    return {"catalogue": catalogue, "order": order, "horizon_days": horizon_days}


def projected_mileage_charge_cents(
    days_in_placement: int, mileage_allowance: int, mileage_used: int
) -> int:
    """The monthly_prorated true-up: per-30-day block allowance, then 12c/mile."""
    from .constants import DAYS_PER_ALLOWANCE_BLOCK, MILEAGE_OVERAGE_RATE_CENTS

    blocks = -(-days_in_placement // DAYS_PER_ALLOWANCE_BLOCK)
    included_miles = blocks * mileage_allowance
    overage_miles = max(0, mileage_used - included_miles)
    return overage_miles * MILEAGE_OVERAGE_RATE_CENTS


def setup_placement_for_true_up(
    days_in_placement: int = 30,
    mileage_allowance: int = 1000,
    mileage_since_last: int = 0,
    start_date: Optional[str] = None,
    condition_grade: str = "A",
    per_diem_rate_cents: int = None,
    liability_bearer: str = None,
    lease_type: str = None,
    credit_ceiling_cents: int = None,
    car_count: int = 1,
    catalogue: dict = None,
    **order_kwargs,
):
    """A placed car whose return is ready to record with a controlled mileage.

    The placement's window width is ``days_in_placement``, which fixes the
    allowance blocks; ``mileage_since_last`` fixes the miles run, and therefore
    both the per-diem utilization credit and the mileage true-up.
    """
    world = setup_assigned_car(
        catalogue=catalogue,
        start_date=start_date,
        assignment_days=days_in_placement,
        mileage_allowance=mileage_allowance,
        per_diem_rate_cents=per_diem_rate_cents,
        liability_bearer=liability_bearer,
        lease_type=lease_type,
        credit_ceiling_cents=credit_ceiling_cents,
        car_count=car_count,
        **order_kwargs,
    )
    start_date = world["assignment_start_date"]
    end_date = world["assignment_end_date"]
    world["start_date"] = start_date
    world["end_date"] = end_date
    world["days_in_placement"] = days_in_placement
    world["expected_mileage_charge_cents"] = projected_mileage_charge_cents(
        days_in_placement, mileage_allowance, mileage_since_last
    )
    world["car_return"] = create_return(
        world["car"],
        world["assignment"],
        return_date=end_date,
        mileage_since_last=mileage_since_last,
        condition_grade=condition_grade,
    )
    world["assignment"] = _data(
        api_client.get_car_assignment(world["assignment"]["id"], ADMIN),
        "read closed placement after true-up",
    )
    world["car"] = _data(
        api_client.get_lease_fleet_car(world["car"]["id"], ADMIN),
        "read car after true-up",
    )
    return world


def setup_return_at_credit_boundary(
    days_in_placement: int = 30,
    mileage_allowance: int = 1000,
    mileage_since_last: int = 1500,
    ceiling_delta: int = 0,
    **kwargs,
):
    """A placement whose projected mileage charge sits exactly at the ceiling.

    The lessee is registered with a credit ceiling equal to the projected charge
    plus ``ceiling_delta``, and the balance is still zero, so a delta of 0 is the
    passing side of the ceiling test and a negative delta the failing side.
    """
    charge = projected_mileage_charge_cents(
        days_in_placement, mileage_allowance, mileage_since_last
    )
    world = setup_placement_for_true_up(
        days_in_placement=days_in_placement,
        mileage_allowance=mileage_allowance,
        mileage_since_last=mileage_since_last,
        credit_ceiling_cents=charge + ceiling_delta,
        **kwargs,
    )
    world["projected_charge_cents"] = charge
    world["credit_ceiling_cents"] = charge + ceiling_delta
    return world


def setup_fleet_at_cap_boundary(
    live_cars: int = 0,
    added_cars: int = 1,
    cap_delta: int = 0,
    catalogue: dict = None,
    **kwargs,
):
    """A contract whose cap sits exactly at the live fleet plus the cars to add.

    ``cap_delta`` of 0 is the passing side; -1 makes the next retained order
    breach the cap.
    """
    catalogue = catalogue or setup_catalogue()
    cap = live_cars + added_cars + cap_delta
    world = {"catalogue": catalogue, "fleet_car_cap": cap}
    if live_cars:
        first = setup_retained_order_with_fleet_cars(
            car_count=live_cars, catalogue=catalogue, fleet_car_cap=cap, **kwargs
        )
        world.update({k: v for k, v in first.items() if k != "catalogue"})
    else:
        world.update(
            create_lessee_and_contract(fleet_car_cap=cap)
        )
    world["added_cars"] = added_cars
    world["next_order"] = create_order(
        catalogue,
        quantity=added_cars,
        disposition="RETAINED",
        priority_rank=5,
    )
    return world


# ─── Pagination and listing helpers ───────────────────

def create_many_orders(catalogue: dict, count: int, **kwargs) -> list:
    """Create ``count`` draft orders, each with a distinct priority rank."""
    orders = []
    for index in range(count):
        orders.append(
            create_order(
                catalogue,
                quantity=1,
                priority_rank=index + 1,
                **kwargs,
            )
        )
    return orders


def list_all_pages(list_call, headers, page_size: int = DEFAULT_PAGE_LIMIT,
                   max_pages: int = 50, **params):
    """Walk a list endpoint page by page, returning every record seen."""
    collected, offset, pages = [], 0, 0
    while pages < max_pages:
        query = dict(params)
        query["limit"] = page_size
        query["offset"] = offset
        page = _list(list_call(headers, query), f"list page at offset {offset}")
        collected.extend(page)
        pages += 1
        if len(page) < page_size:
            break
        offset += page_size
    return collected


__all__ = [
    # clock
    "set_clock", "advance_clock_to",
    # catalogue and commercial preamble
    "setup_catalogue", "create_lessee_and_contract", "setup_catalogue_with_contract",
    "receive_component_stock", "ensure_coating_supply",
    "worst_gated_lead_days", "feasible_delivery_date",
    # production order lifecycle
    "create_order", "reserve_order", "release_order", "start_production",
    "complete_order", "setup_order_in_state", "setup_released_order",
    "setup_in_production_order",
    # fleet cars
    "setup_retained_order_with_fleet_cars", "setup_fleet_cars",
    # placements and returns
    "create_assignment", "setup_assigned_car", "suspend_assignment",
    "resume_assignment", "reassign_assignment", "create_return", "settle_return",
    "setup_car_in_repair", "setup_returned_car_ready_to_settle",
    "setup_car_back_in_fleet",
    # sales
    "book_value_cents", "gain_over_book_cents", "create_sale", "settle_sale",
    "void_sale", "setup_sold_car",
    # retrofit
    "create_retrofit_program", "create_work_order", "setup_retrofit_program_with_car",
    "setup_work_order_in_state",
    # endorsements
    "create_endorsement", "approve_endorsement", "reject_endorsement",
    "return_endorsement_to_pending", "setup_order_with_endorsement",
    # boundary targeting
    "required_stock", "setup_order_at_stock_boundary",
    "setup_order_at_lead_time_boundary", "projected_mileage_charge_cents",
    "setup_placement_for_true_up", "setup_return_at_credit_boundary",
    "setup_fleet_at_cap_boundary",
    # listing
    "create_many_orders", "list_all_pages",
]
