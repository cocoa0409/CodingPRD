"""Composite setup helpers for multi-step test prerequisites.

Every helper here builds its preconditions from an empty database using only
declared endpoints, because the harness restarts the server before each test.

Setup steps use get_success_data() (lenient validator) so a broken prerequisite
surfaces as a clear "Setup failed" message rather than a confusing assertion
failure inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_2026_09_02,
    LOGICAL_CLOCK_START,
)
from .factories import (
    create_element_payload,
    create_fusion_order_payload,
    create_launch_queue_payload,
    create_member_payload,
    create_replacement_request_payload,
    create_reservation_payload,
    create_store_event_payload,
    create_store_payload,
    create_theme_launch_payload,
    create_wall_bin_payload,
)
from .test_users import TEST_USERS, make_member_headers


def _fail(step: str, response):
    body = ""
    try:
        body = response.json()
    except Exception:
        body = response.text
    raise AssertionError(f"Setup failed at {step}: HTTP {response.status_code} {body}")


def _ok(response, step: str) -> dict:
    if not (200 <= response.status_code < 300):
        _fail(step, response)
    return get_success_data(response)


# ─── Primitives ───────────────────────────────────────

def set_clock(to_iso8601: str, headers=None) -> dict:
    """Move the logical clock. The server never reads wall-clock time."""
    headers = headers or TEST_USERS["admin_headers"]
    return _ok(api_client.set_clock(to_iso8601, headers), "set_clock")


def reset_clock(headers=None) -> dict:
    return set_clock(LOGICAL_CLOCK_START, headers)


def open_store(**overrides) -> dict:
    """Open a store. Returns the created Store."""
    res = api_client.create_store(create_store_payload(**overrides),
                                  TEST_USERS["admin_headers"])
    return _ok(res, "create_store")


def add_element(**overrides) -> dict:
    """Register an element design. Returns the created Element."""
    res = api_client.create_element(create_element_payload(**overrides),
                                    TEST_USERS["admin_headers"])
    return _ok(res, "create_element")


def add_member(store_id: str, **overrides) -> dict:
    """Create a loyalty member homed at store_id. Returns the Member."""
    res = api_client.create_member(create_member_payload(store_id, **overrides),
                                   TEST_USERS["admin_headers"])
    return _ok(res, "create_member")


def load_bin(store_id: str, element_id: str, **overrides) -> dict:
    """Load a wall bin. Returns the created WallBin."""
    res = api_client.create_wall_bin(
        create_wall_bin_payload(store_id, element_id, **overrides),
        TEST_USERS["associate_headers"])
    return _ok(res, "create_wall_bin")


def open_cup(store_id: str, member_id: str, **overrides) -> dict:
    """Open a Pick-a-Brick cup. Returns the created FusionOrder."""
    res = api_client.create_fusion_order(
        create_fusion_order_payload(store_id, member_id, **overrides),
        TEST_USERS["associate_headers"])
    return _ok(res, "create_fusion_order")


def draw_from_bin(order_id: str, wall_bin_id: str, allocation_grams: int) -> dict:
    """Record one bin draw against a cup. Returns the updated FusionOrder."""
    payload = {"wall_bin_id": wall_bin_id, "allocation_grams": allocation_grams}
    res = api_client.create_allocation(order_id, payload,
                                       TEST_USERS["associate_headers"])
    return _ok(res, "create_allocation")


def reissue_element(element_id: str) -> dict:
    res = api_client.reissue_element(element_id, TEST_USERS["associate_headers"])
    return _ok(res, "reissue_element")


def restock_bin(bin_id: str, add_grams: int) -> dict:
    res = api_client.restock_wall_bin(bin_id, {"add_grams": add_grams},
                                      TEST_USERS["associate_headers"])
    return _ok(res, "restock_wall_bin")


# ─── Tier 1: State progression ────────────────────────

def advance_clock_and_run_epoch(store_id: str, to_iso8601: str) -> dict:
    """Set the clock, run one epoch pass, and return the updated Store.

    Wave-driven transitions only fire on the checkpoint, never per request.
    """
    set_clock(to_iso8601)
    res = api_client.run_epoch(store_id, TEST_USERS["admin_headers"])
    return _ok(res, "run_epoch")


def run_epoch(store_id: str) -> dict:
    res = api_client.run_epoch(store_id, TEST_USERS["admin_headers"])
    return _ok(res, "run_epoch")


def open_and_open_store(**overrides) -> dict:
    """Clock at its starting instant, then a store. The common preamble."""
    reset_clock()
    return open_store(**overrides)


def checkout(order_id: str, order_version: int, member_id: str, **overrides) -> dict:
    """Settle a cup as its owning member. Returns the settled FusionOrder."""
    payload = {"expected_fusion_order_version": order_version}
    payload.update(overrides)
    res = api_client.checkout_fusion_order(order_id, payload,
                                           make_member_headers(member_id))
    return _ok(res, "checkout_fusion_order")


def void_order(order_id: str, order_version: int, member_id: str) -> dict:
    """Void a cup as its owning member. Returns the voided FusionOrder."""
    payload = {"expected_fusion_order_version": order_version}
    res = api_client.void_fusion_order(order_id, payload,
                                       make_member_headers(member_id))
    return _ok(res, "void_fusion_order")


def inspect_order(order_id: str, order_version: int, **overrides) -> dict:
    """Record an exit-tunnel inspection. Returns the created ExitInspection."""
    payload = {
        "fusion_order_id": order_id,
        "outcome": "CLEAR",
        "checklist_result": "COMPLETED",
        "reviewed_by_user_id": "assoc-77",
        "expected_fusion_order_version": order_version,
    }
    payload.update(overrides)
    res = api_client.create_exit_inspection(payload, TEST_USERS["associate_headers"])
    return _ok(res, "create_exit_inspection")


def suspend_member(member_id: str, reason_code: str = "POLICY_REVIEW") -> dict:
    res = api_client.suspend_member(member_id, {"reason_code": reason_code},
                                    TEST_USERS["associate_headers"])
    return _ok(res, "suspend_member")


def reinstate_member(member_id: str) -> dict:
    res = api_client.reinstate_member(member_id, TEST_USERS["associate_headers"])
    return _ok(res, "reinstate_member")


def post_ledger(member_id: str, entry_kind: str, points_delta: int, reason: str) -> dict:
    payload = {
        "member_id": member_id,
        "entry_kind": entry_kind,
        "points_delta": points_delta,
        "reason": reason,
    }
    res = api_client.create_ledger_entry(payload, TEST_USERS["admin_headers"])
    return _ok(res, "create_ledger_entry")


# ─── Tier 2: Entity hierarchy ─────────────────────────

def setup_store_with_wall(store_overrides=None, element_overrides=None,
                          bin_overrides=None, member_overrides=None,
                          with_member=True):
    """Clock, store, one element, and one loaded bin.

    Returns (store, element, member, bin); member is None when with_member is
    False. Default bin mass 600 g on a 1000 g capacity, inside the default
    2000 g store wall so the store reads TRADING.
    """
    reset_clock()
    store = open_store(**(store_overrides or {}))
    element = add_element(**(element_overrides or {}))
    member = add_member(store["id"], **(member_overrides or {})) if with_member else None
    if bin_overrides is not None and "skip_bin" in bin_overrides:
        bin_overrides = {k: v for k, v in bin_overrides.items() if k != "skip_bin"}
        return store, element, member, None
    defaults = {"bin_capacity_grams": 1000, "bin_mass_grams": 600}
    defaults.update(bin_overrides or {})
    bin_row = load_bin(store["id"], element["id"], **defaults)
    return store, element, member, bin_row


def setup_cup_ready_to_checkout(store_overrides=None, element_overrides=None,
                                bin_overrides=None, cup_overrides=None,
                                draw_grams=None):
    """A PENDING cup with one recorded draw, ready to be settled.

    Returns (store, element, member, bin, order).
    """
    store, element, member, bin_row = setup_store_with_wall(
        store_overrides=store_overrides,
        element_overrides=element_overrides,
        bin_overrides=bin_overrides,
    )
    cup_defaults = {"cup_size": "LARGE", "pricing_model": "CUP_FILL",
                    "declared_mass_grams": 400}
    cup_defaults.update(cup_overrides or {})
    order = open_cup(store["id"], member["id"], **cup_defaults)
    grams = draw_grams if draw_grams is not None else cup_defaults["declared_mass_grams"]
    if grams:
        order = draw_from_bin(order["id"], bin_row["id"], grams)
    return store, element, member, bin_row, order


def setup_checked_out_cup(store_overrides=None, element_overrides=None,
                          bin_overrides=None, cup_overrides=None,
                          draw_grams=None):
    """A SETTLED cup. Returns (store, element, member, bin, settled_order)."""
    store, element, member, bin_row, order = setup_cup_ready_to_checkout(
        store_overrides=store_overrides,
        element_overrides=element_overrides,
        bin_overrides=bin_overrides,
        cup_overrides=cup_overrides,
        draw_grams=draw_grams,
    )
    settled = checkout(order["id"], order["version"], member["id"])
    return store, element, member, bin_row, settled


def setup_element_in_archive(element_overrides=None, store_overrides=None):
    """An element retired into the archive, with no bin holding it.

    Returns (store, element) with element.status RETIRED_TO_ARCHIVE.
    """
    reset_clock()
    store = open_store(**(store_overrides or {}))
    element = add_element(**(element_overrides or {}))
    res = api_client.retire_element(
        element["id"], {"expected_element_version": element["version"]},
        TEST_USERS["associate_headers"])
    return store, _ok(res, "retire_element")


def setup_store_event_with_reservations(capacity_units=1, seats_each=1,
                                        registrations=1, event_overrides=None,
                                        store_overrides=None,
                                        member_overrides=None):
    """An event slot plus one member per registration.

    Returns (store, event, [(member, reservation), ...]). The first
    `capacity_units` seats worth of registrations fit; the rest waitlist.
    """
    reset_clock()
    store = open_store(**(store_overrides or {}))
    event_defaults = {
        "capacity_units": capacity_units,
        "days_from_default_clock": 1,
        "duration_hours": 2,
    }
    event_defaults.update(event_overrides or {})
    res = api_client.create_store_event(
        create_store_event_payload(store["id"], **event_defaults),
        TEST_USERS["associate_headers"])
    event = _ok(res, "create_store_event")

    pairs = []
    for _ in range(registrations):
        member = add_member(store["id"], **(member_overrides or {}))
        rres = api_client.create_reservation(
            create_reservation_payload(event["id"], member["id"], seats=seats_each),
            TEST_USERS["associate_headers"])
        pairs.append((member, _ok(rres, "create_reservation")))
    return store, event, pairs
def settle_cup_with_inspection(order: dict, member_id: str, **checkout_overrides) -> dict:
    """Record the exit-tunnel inspection and settle the cup.

    Stores whose checklist_required flag is true refuse settlement until the
    linked inspection has reached COMPLETED.
    """
    inspect_order(order["id"], order["version"])
    settled = checkout(order["id"], order["version"], member_id,
                       **checkout_overrides)
    return settled


def settle_cup_with_inspection_and_void(store_id, member_id, cup_overrides=None,
                                        draw_grams=None, store_overrides=None):
    """A cup settled through an inspection, ready to be voided.

    Returns (store, member, bin, settled_order).
    """
    store, _element, member, bin_row, order = setup_cup_ready_to_checkout(
        store_overrides=store_overrides, cup_overrides=cup_overrides,
        draw_grams=draw_grams)
    settled = settle_cup_with_inspection(order, member["id"])
    return store, member, bin_row, settled


# ─── Launches and the queue waterfall ─────────────────

def schedule_launch(**overrides) -> dict:
    res = api_client.create_theme_launch(create_theme_launch_payload(**overrides),
                                         TEST_USERS["admin_headers"])
    return _ok(res, "create_theme_launch")


def join_queue(member_id: str, launch_id: str, **overrides) -> dict:
    res = api_client.create_launch_queue(
        create_launch_queue_payload(member_id, launch_id, **overrides),
        TEST_USERS["associate_headers"])
    return _ok(res, "create_launch_queue")


def open_launch_after_epoch(store_id: str, launch_overrides=None):
    """A launch pushed to STAGED_OPEN by one epoch pass on the release instant.

    Returns (launch_after_epoch, launch_version_before_epoch). The pre-epoch
    version is what a caller who read the launch before the pass would hold.
    """
    launch = schedule_launch(**(launch_overrides or {"days_from_default_clock": 1,
                                                     "vip_early_days_before_release": 0}))
    version_before = launch["version"]
    advance_clock_and_run_epoch(store_id, CLOCK_2026_09_02)
    return launch, version_before


def setup_launch_with_queue_rows(store_overrides=None, element_overrides=None,
                                 launch_overrides=None, queue_specs=None,
                                 release_utc=None):
    """An OPEN launch with one WAITING queue row per member.

    queue_specs is a list of dicts merged into each member's queue join, so one
    spec builds one member + one row. The epoch pass is run so the launch
    reaches STAGED_OPEN unless release_utc is falsy.

    Returns (store, launch, [(member, queue_row), ...]).
    """
    store, element, _member, _bin = setup_store_with_wall(
        store_overrides=store_overrides,
        element_overrides=element_overrides,
        with_member=False,
    )
    ldefaults = {"allocated_exclusive_units": 4, "per_customer_limit": 2,
                 "days_from_default_clock": 1, "vip_early_days_before_release": 0}
    ldefaults.update(launch_overrides or {})
    launch = schedule_launch(**ldefaults)
    if release_utc is not False:
        advance_clock_and_run_epoch(store["id"], release_utc or CLOCK_2026_09_02)

    pairs = []
    for spec in (queue_specs or [{}]):
        member = add_member(store["id"])
        row = join_queue(member["id"], launch["id"], **spec)
        pairs.append((member, row))
    return store, launch, pairs


# ─── Replacements ─────────────────────────────────────

def file_replacement(store_id: str, member_id: str, element_id: str,
                     member_version: int, **overrides) -> dict:
    res = api_client.create_replacement_request(
        create_replacement_request_payload(store_id, member_id, element_id,
                                           member_version, **overrides),
        TEST_USERS["associate_headers"])
    return _ok(res, "create_replacement_request")


def setup_surplus_element(store_id: str, element_overrides=None):
    """An element loaded on the wall and then retired into surplus sourcing.

    Returns the element with status RETIRED_TO_ARCHIVE and sourcing_mode
    SURPLUS. RETIRED bins do not count as on the wall.

    Retirement is refused while any bin still holds mass of the element, so the
    surplus element's own bin must read zero. A separate ballast bin keeps the
    store's engine mass above zero, because PRD §2.5 freezes a store whose
    engine mass is exactly zero and a frozen store admits no replacement filing.
    """
    element = add_element(**(element_overrides or {}))
    load_bin(store_id, element["id"], bin_mass_grams=0,
             bin_capacity_grams=1000, bin_label=f"SB-{element['element_code']}")
    res = api_client.retire_element(
        element["id"], {"expected_element_version": element["version"]},
        TEST_USERS["associate_headers"])
    retired = _ok(res, "retire_element")

    ballast = add_element(element_name="Ballast Brick")
    load_bin(store_id, ballast["id"], bin_mass_grams=600,
             bin_capacity_grams=1000,
             bin_label=f"BL-{ballast['element_code']}")
    return retired


def setup_prospect_request(quantity_missing=1, element_overrides=None,
                           window_days=30, store_overrides=None,
                           member_overrides=None):
    """Clock, store, surplus-sourced element, member and one PROSPECT request.

    Returns (store, element, member, request, member_version_at_creation).
    """
    reset_clock()
    store = open_store(**(store_overrides or {}))
    element = setup_surplus_element(store["id"], element_overrides)
    member = add_member(store["id"], **(member_overrides or {}))
    request = file_replacement(store["id"], member["id"], element["id"],
                               member["version"],
                               quantity_missing=quantity_missing,
                               window_days=window_days)
    return store, element, member, request, member["version"]


# ─── Minifigure builds ────────────────────────────────

def open_build(store_id: str, member_id: str) -> dict:
    res = api_client.create_minifigure_build(
        {"store_id": store_id, "member_id": member_id},
        TEST_USERS["associate_headers"])
    return _ok(res, "create_minifigure_build")


def set_components(build_id: str, member_id: str, **slots) -> dict:
    res = api_client.set_build_components(build_id, dict(slots),
                                          make_member_headers(member_id))
    return _ok(res, "set_build_components")


def seal_build(build_id: str, build_version: int, member_id: str) -> dict:
    res = api_client.seal_build(build_id, {"expected_build_version": build_version},
                                make_member_headers(member_id))
    return _ok(res, "seal_build")


def setup_four_component_bins(store_overrides=None):
    """A store with four component elements each loaded in its own stocked bin.

    Returns (store, member, {"torso": el, "head": el, "legs": el, "accessory": el},
    {"torso": bin, "head": bin, "legs": bin, "accessory": bin}).
    """
    reset_clock()
    store = open_store(**(store_overrides or {}))
    specs = {
        "torso": ("3100", "Torso Town", 20),
        "head": ("3101", "Head Classic", 10),
        "legs": ("3102", "Legs Blue", 12),
        "accessory": ("3103", "Accessory Cap", 6),
    }
    elements = {}
    bins = {}
    for slot, (code, name, cost) in specs.items():
        elements[slot] = add_element(element_code=code, element_name=name,
                                     cost_basis_cents=cost)
        bins[slot] = load_bin(store["id"], elements[slot]["id"],
                              bin_label=f"P-{slot}", bin_capacity_grams=2000,
                              bin_mass_grams=600)
    member = add_member(store["id"])
    return store, member, elements, bins


def setup_late_waitlisted_reservation(store_overrides=None,
                                      event_overrides=None,
                                      member_overrides=None):
    """Event at 2026-09-02 with one REGISTERED reservation, then a late join.

    The first epoch pass on 2026-09-02T03:00:00Z closes the slot and promotes
    nothing beyond the fence; a further join lands WAITLISTED with a wait_mark
    the first wave's fence cannot reach.

    Returns (store, event, [(member, reservation), ...]) including the late join.
    """
    reset_clock()
    store = open_store(**(store_overrides or {}))
    edefaults = {"capacity_units": 1, "days_from_default_clock": 1,
                 "duration_hours": 2}
    edefaults.update(event_overrides or {})
    res = api_client.create_store_event(
        create_store_event_payload(store["id"], **edefaults),
        TEST_USERS["associate_headers"])
    event = _ok(res, "create_store_event")

    pairs = []
    first = add_member(store["id"], **(member_overrides or {}))
    rres = api_client.create_reservation(
        create_reservation_payload(event["id"], first["id"]),
        TEST_USERS["associate_headers"])
    pairs.append((first, _ok(rres, "create_reservation")))

    advance_clock_and_run_epoch(store["id"], "2026-09-02T03:00:00Z")

    late = add_member(store["id"])
    lres = api_client.create_reservation(
        create_reservation_payload(event["id"], late["id"]),
        TEST_USERS["associate_headers"])
    pairs.append((late, _ok(lres, "create_reservation")))
    return store, event, pairs