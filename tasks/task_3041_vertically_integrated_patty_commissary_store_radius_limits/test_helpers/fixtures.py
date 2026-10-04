"""Composite setup helpers.

Most PRD rules can only be observed deep inside a multi-entity precondition:
an order-pricing rule needs an OPEN store with delivered inventory, which in
turn needs a manager assigned before approval, which needs a candidate
promoted to SHIFT_LEAD through the posting process, and so on.  These helpers
build those preconditions from an empty database using only PRD section 4
endpoints.

The logical clock starts at the fixed startup default 2026-09-01T00:00:00Z
(PRD section 2.4), a Tuesday; helpers pin it explicitly so tests never depend
on the caller having left it alone.

Two PRD section 3.7 constraints shape the promotion helpers:

- A promote call needs at least 180 days of tenure and at least 2 SCHEDULED
  shifts whose ``shift_start`` is at or after the current clock time.  The
  helpers hire with a 2024 ``hired_date`` (well past tenure) and schedule two
  far-future shifts (October 2026) once per promotion campaign, reusing them
  for every promote call.
- A store's derived ``staffing_posture`` gates shift creation: posture
  CRITICAL blocks it, and coverage is checked FIRST — the coverage ratio is
  today's SCHEDULED shifts divided by the active crew, which is zero while
  the clock sits outside every shift window.  The helpers therefore move the
  logical clock into a shift window (so coverage is 1.0, not CRITICAL) before
  creating shifts, and restore the caller's clock position afterwards.  Once
  a store has an active MANAGER in its crew, posture is at worst STRAINED
  (a MANAGER satisfies the minimum-leads rule), which only blocks scheduling
  during OPENING_SURGE — and these helpers never schedule during a surge.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import CLOCK_START
from .factories import (
    create_associate_payload,
    create_batch_payload,
    create_beef_delivery_payload,
    create_commissary_payload,
    create_menu_item_payload,
    create_production_run_payload,
    create_route_payload,
    create_shift_payload,
    create_store_payload,
    create_supplier_payload,
    create_truck_payload,
)
from .test_users import (
    auditor_headers,
    hr_closer_headers,
    hr_poster_headers,
    make_associate_headers,
    make_store_manager_headers,
    planner_headers,
    real_estate_headers,
    scd_headers,
)

_api = ApiClient()

# Far-future shift windows used to satisfy the promotion gate's requirement
# of at least 2 SCHEDULED shifts starting at or after the clock (PRD section
# 3.7).  Mid-window positions of these shifts are also where the clock is
# parked while a promotion campaign runs, so the store's coverage ratio is
# 1.0 and its posture is not CRITICAL at shift-creation time.
_FUTURE_SHIFT_A = ("2026-10-01T16:00:00Z", "2026-10-02T00:00:00Z")
_FUTURE_SHIFT_A_CLOCK = "2026-10-01T18:00:00Z"
_FUTURE_SHIFT_B = ("2026-10-02T16:00:00Z", "2026-10-03T00:00:00Z")
_FUTURE_SHIFT_B_CLOCK = "2026-10-02T18:00:00Z"

# Reference dates: deliveries/batches land on 2026-09-02 (Wednesday), a day
# the default delivery-days mask serves.
DELIVERY_DATE = "2026-09-02T00:00:00Z"
RUN_DATE = "2026-09-01T00:00:00Z"


def set_clock(current_utc: str = CLOCK_START):
    """Pin the logical clock (a SupplyChainDirector capability, PRD section
    2.4)."""
    resp = _api.set_clock(current_utc, scd_headers())
    return get_success_data(resp)


def create_approved_supplier(audit_frequency_days: int = 30,
                             scheduled_date: str = CLOCK_START) -> dict:
    """Register a supplier and move it PROBATION -> APPROVED via a recorded
    PASS audit (PRD section 3.1).  Returns the supplier row."""
    sup = get_success_data(_api.create_supplier(
        create_supplier_payload(audit_frequency_days=audit_frequency_days),
        scd_headers()))
    aud = get_success_data(_api.create_audit(
        sup["id"], {"scheduled_date": scheduled_date}, auditor_headers()))
    get_success_data(_api.record_audit(
        sup["id"], aud["id"], {"result": "PASS"}, auditor_headers()))
    return get_success_data(_api.get_supplier(sup["id"], scd_headers()))


def create_operational_commissary(audit_frequency_days: int = 30,
                                  **commissary_overrides) -> dict:
    """APPROVED supplier + commissary walked PLANNING -> BUILDING ->
    OPERATIONAL (PRD section 3.2).  Returns ``{"supplier": ..., "commissary":
    ...}`` where the commissary row reflects the activation."""
    supplier = create_approved_supplier(audit_frequency_days=audit_frequency_days)
    com = get_success_data(_api.create_commissary(
        create_commissary_payload(supplier["id"], **commissary_overrides),
        scd_headers()))
    get_success_data(_api.begin_build(com["id"], scd_headers()))
    com = get_success_data(_api.activate_commissary(com["id"], scd_headers()))
    return {"supplier": supplier, "commissary": com}


def create_site_store(commissary: dict, **store_overrides) -> dict:
    """Propose a store site against an OPERATIONAL commissary, using the
    commissary's current version as ``expected_commissary_version`` (PRD
    section 2.7).  Callers that mutate the commissary afterwards must re-read
    it before creating another store."""
    fresh = get_success_data(_api.get_commissary(commissary["id"], scd_headers()))
    return get_success_data(_api.create_store(
        create_store_payload(
            commissary["id"],
            expected_commissary_version=fresh["version"],
            **store_overrides),
        real_estate_headers()))


def hire_associate(store_id: str, **overrides) -> dict:
    return get_success_data(_api.create_associate(
        create_associate_payload(store_id, **overrides), hr_poster_headers()))


def _schedule_promotion_shifts(associate_id: str, store_id: str,
                               window, clock_inside_window: str):
    """Create one SCHEDULED shift for the promotion gate.  The clock is moved
    inside the window first so the store's coverage ratio is non-zero (the
    coverage check runs before the manager check in the posture rule, PRD
    section 3.7)."""
    set_clock(clock_inside_window)
    get_success_data(_api.create_shift(
        store_id,
        create_shift_payload(associate_id, window[0], window[1]),
        hr_poster_headers()))


def promote_to_shift_lead(associate_id: str, store_id: str) -> dict:
    """Walk an associate LEVEL_1 -> SHIFT_LEAD (six promote calls), leaving
    the logical clock parked inside the last future shift window.  Callers
    MUST restore the clock with :func:`set_clock` when they are done."""
    _schedule_promotion_shifts(
        associate_id, store_id, _FUTURE_SHIFT_A, _FUTURE_SHIFT_A_CLOCK)
    _schedule_promotion_shifts(
        associate_id, store_id, _FUTURE_SHIFT_B, _FUTURE_SHIFT_B_CLOCK)
    assoc = get_success_data(_api.get_associate(associate_id, hr_poster_headers()))
    for _ in range(6):
        assoc = get_success_data(_api.promote_associate(
            associate_id, hr_poster_headers()))
    return assoc


def promote_to_manager_via_posting(associate_id: str, store_id: str) -> dict:
    """Assign a SHIFT_LEAD candidate as the store's MANAGER through the
    internal posting process (PRD section 3.7): the posting is created by one
    HRDirector identity and closed by a different one (segregation of
    duties).  The candidate's home store moves to the posting's store."""
    posting = get_success_data(_api.create_manager_posting(
        {"store_id": store_id}, hr_poster_headers()))
    app = get_success_data(_api.create_manager_application(
        posting["id"], {"candidate_associate_id": associate_id},
        make_associate_headers(associate_id)))
    get_success_data(_api.close_manager_posting(
        posting["id"], {"candidate_application_id": app["id"]},
        hr_closer_headers()))
    return get_success_data(_api.get_associate(associate_id, hr_poster_headers()))


def create_open_store_with_manager(**commissary_overrides) -> dict:
    """OPERATIONAL commissary + store walked SITE_REVIEW -> APPROVED -> OPEN
    with a MANAGER associate assigned (approval requires a non-null manager
    reference at MANAGER level, PRD section 3.4).  The logical clock is
    restored to the startup default on return.  Returns ``{"supplier",
    "commissary", "store" (the OPEN row), "manager"}``."""
    set_clock(CLOCK_START)
    env = create_operational_commissary(**commissary_overrides)
    store = create_site_store(env["commissary"])
    mgr = hire_associate(store["id"])
    mgr = promote_to_shift_lead(mgr["id"], store["id"])
    mgr = promote_to_manager_via_posting(mgr["id"], store["id"])
    set_clock(CLOCK_START)
    get_success_data(_api.approve_store(store["id"], real_estate_headers()))
    store = get_success_data(_api.open_store(store["id"], real_estate_headers()))
    return {
        "supplier": env["supplier"],
        "commissary": env["commissary"],
        "store": store,
        "manager": mgr,
    }


def _fresh_store_version(store_id: str) -> int:
    return get_success_data(_api.get_store(store_id, planner_headers()))["version"]


def deliver_inventory(store: dict, commissary: dict, delivery_date: str,
                      patty_count: int, bun_count: int, produce_units: int,
                      run_date: str = RUN_DATE,
                      truck_cooler_cases: int = 500) -> dict:
    """Credit the store's on-hand ledger (PRD sections 3.5/3.6): plan a batch,
    plan + complete a covering production run, run a route DRAFT ->
    FINALIZED, then load and deliver the batch.  Returns the DELIVERED batch
    plus the run/truck/route ids."""
    batch = get_success_data(_api.create_batch(
        create_batch_payload(
            store["id"], _fresh_store_version(store["id"]), delivery_date,
            patty_count=patty_count, bun_count=bun_count,
            produce_units=produce_units),
        planner_headers()))
    run = get_success_data(_api.create_production_run(
        commissary["id"],
        create_production_run_payload(
            patties_planned=patty_count, buns_planned=bun_count,
            produce_units_planned=produce_units, run_date=run_date),
        planner_headers()))
    get_success_data(_api.complete_production_run(run["id"], planner_headers()))
    truck = get_success_data(_api.create_truck(
        commissary["id"],
        create_truck_payload(cooler_capacity_cases=truck_cooler_cases),
        planner_headers()))
    route = get_success_data(_api.create_route(
        create_route_payload(commissary["id"], truck["id"], delivery_date,
                             [store["id"]]),
        planner_headers()))
    get_success_data(_api.load_batch(
        batch["id"], {"production_run_id": run["id"], "route_id": route["id"]},
        planner_headers()))
    get_success_data(_api.finalize_route(route["id"], planner_headers()))
    batch = get_success_data(_api.deliver_batch(batch["id"], planner_headers()))
    return {
        "batch": batch,
        "run_id": run["id"],
        "truck_id": truck["id"],
        "route_id": route["id"],
    }


def create_stocked_open_store(patty_count: int = 100, bun_count: int = 60,
                              produce_units: int = 60,
                              delivery_date: str = DELIVERY_DATE,
                              menu_item: dict = None,
                              **commissary_overrides) -> dict:
    """OPEN store with a manager and a delivered inventory batch.  Returns the
    :func:`create_open_store_with_manager` dict plus ``item`` (a created menu
    item) and ``delivery`` (the :func:`deliver_inventory` result)."""
    env = create_open_store_with_manager(**commissary_overrides)
    item = get_success_data(_api.create_menu_item(
        create_menu_item_payload(**(menu_item or {})), scd_headers()))
    delivery = deliver_inventory(
        env["store"], env["commissary"], delivery_date,
        patty_count, bun_count, produce_units)
    env["item"] = item
    env["delivery"] = delivery
    return env


def receive_beef(commissary: dict, supplier: dict, raw_beef_lbs: float,
                 transit_temp_celsius: float = 2.0) -> dict:
    """Schedule, ship, and confirm a beef delivery, crediting the commissary's
    raw-beef ledger (PRD section 3.3).  Returns the RECEIVED delivery."""
    bd = get_success_data(_api.create_beef_delivery(
        create_beef_delivery_payload(
            commissary["id"], supplier["id"], raw_beef_lbs=raw_beef_lbs,
            transit_temp_celsius=transit_temp_celsius),
        planner_headers()))
    get_success_data(_api.ship_beef_delivery(bd["id"], planner_headers()))
    return get_success_data(_api.confirm_receiving(bd["id"], planner_headers()))


def manager_headers_for(env: dict):
    """StoreManager headers for the env's manager — entity-backed identity
    (PRD section 2.1): X-User-ID must be the manager associate's id."""
    return make_store_manager_headers(env["manager"]["id"])


def associate_headers_for(associate: dict):
    """Associate headers for a specific associate row (entity-backed
    identity, PRD section 2.1)."""
    return make_associate_headers(associate["id"])
