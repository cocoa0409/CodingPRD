"""Shared helpers: rounding, record lifecycle, lookups, and store posture."""

from decimal import Decimal, ROUND_HALF_UP

from db import (
    ENGINE_RESTRICTED_FRACTION,
    SUSPENDED_MEMBER_FREEZE_COUNT,
    db,
    format_iso,
    now,
)
from errors import fail

# Queue-row statuses that hold units of a launch allocation.
UNIT_HOLDING = ("GRANTED", "PURCHASED", "PURCHASED_ROLLBACK", "EXPIRED", "NO_SHOW")


# ---------------------------------------------------------------------------
# Rounding -- halves always move away from zero toward the larger magnitude.
# ---------------------------------------------------------------------------
def rh(value):
    """Round half up to an integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rh1(value):
    """Round half up to one decimal place (used for fill_pct)."""
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------
def new_record(fields):
    """Mint a resource: id, created_at, updated_at and version are system-managed."""
    record = dict(fields)
    record["id"] = db().new_id()
    stamp = format_iso(now())
    record["created_at"] = stamp
    record["updated_at"] = stamp
    record["version"] = 1
    return record


def touch(record):
    """Advance version and updated_at -- every mutation, derived ones included."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = format_iso(now())
    return record


def log_record(fields):
    """Append-only resources (FusionAllocation, LoyaltyLedger) carry no version."""
    record = dict(fields)
    record["id"] = db().new_id()
    record["created_at"] = format_iso(now())
    return record


# ---------------------------------------------------------------------------
# Lookups -- the existence rung (priority 3), resolved left to right.
# ---------------------------------------------------------------------------
def get_store(store_id):
    record = db().stores.get(store_id)
    if record is None:
        fail("ERR_NOT_FOUND", "No store exists with id %s." % store_id)
    return record


def get_member(member_id):
    record = db().members.get(member_id)
    if record is None:
        fail("ERR_NOT_FOUND", "No member exists with id %s." % member_id)
    return record


def get_element(element_id):
    record = db().elements.get(element_id)
    if record is None:
        fail("ERR_NOT_FOUND", "No element exists with id %s." % element_id)
    return record


def get_launch(launch_id):
    record = db().theme_launches.get(launch_id)
    if record is None:
        fail("ERR_NOT_FOUND", "No theme launch exists with id %s." % launch_id)
    return record


def get_queue(queue_id):
    record = db().launch_queues.get(queue_id)
    if record is None:
        fail("ERR_NOT_FOUND", "No launch queue row exists with id %s." % queue_id)
    return record


def get_bin(bin_id):
    record = db().wall_bins.get(bin_id)
    if record is None:
        fail("ERR_NOT_FOUND", "No wall bin exists with id %s." % bin_id)
    return record


def get_order(order_id):
    record = db().fusion_orders.get(order_id)
    if record is None:
        fail("ERR_NOT_FOUND", "No fusion order exists with id %s." % order_id)
    return record


def get_build(build_id):
    record = db().minifigure_builds.get(build_id)
    if record is None:
        fail("ERR_NOT_FOUND", "No minifigure build exists with id %s." % build_id)
    return record


def get_event(event_id):
    record = db().store_events.get(event_id)
    if record is None:
        fail("ERR_NOT_FOUND", "No store event exists with id %s." % event_id)
    return record


def get_reservation(reservation_id):
    record = db().mini_build_reservations.get(reservation_id)
    if record is None:
        fail("ERR_NOT_FOUND", "No reservation exists with id %s." % reservation_id)
    return record


def get_request(request_id):
    record = db().replacement_requests.get(request_id)
    if record is None:
        fail("ERR_NOT_FOUND", "No replacement request exists with id %s." % request_id)
    return record


def get_inspection(inspection_id):
    record = db().exit_inspections.get(inspection_id)
    if record is None:
        fail("ERR_NOT_FOUND", "No exit inspection exists with id %s." % inspection_id)
    return record


# ---------------------------------------------------------------------------
# Derived collections
# ---------------------------------------------------------------------------
def bins_of_store(store_id):
    return [b for b in db().wall_bins.values() if b["store_id"] == store_id]


def live_bins(store_id):
    return [b for b in bins_of_store(store_id)
            if b["status"] in ("OPEN", "LOW", "EMPTY")]


def bin_engine_mass(store_id):
    return sum(b["bin_mass_grams"] for b in live_bins(store_id))


def suspended_member_count(store_id):
    return len([m for m in db().members.values()
                if m["home_store_id"] == store_id and m["stage"] == "SUSPENDED"])


def recompute_store(store):
    """wall_engine_mass_and_posture: stage is a pure function of the two inputs."""
    store["bin_engine_mass_grams"] = bin_engine_mass(store["id"])
    suspended = suspended_member_count(store["id"])
    mass = store["bin_engine_mass_grams"]
    if mass <= 0 or suspended >= SUSPENDED_MEMBER_FREEZE_COUNT:
        new_stage = "FROZEN"
    elif (Decimal(mass)
          < Decimal(store["wall_bin_capacity_grams"]) * Decimal(str(ENGINE_RESTRICTED_FRACTION))):
        new_stage = "RESTRICTED"
    else:
        new_stage = "TRADING"
    store["stage"] = new_stage
    return store


def apply_freeze_consequences(store):
    """Freezing a store voids its queue rows and closes its event slots."""
    if store["stage"] != "FROZEN":
        return
    for queue in db().launch_queues.values():
        if queue["store_id"] != store["id"]:
            continue
        if queue["status"] == "WAITING":
            queue["status"] = "VOIDED"
            touch(queue)
        elif queue["status"] == "GRANTED":
            release_queue_units(queue)
    for event in db().store_events.values():
        if event["store_id"] == store["id"] and event["stage"] in ("SCHEDULED", "OPEN"):
            event["stage"] = "CLOSED"
            touch(event)


def release_queue_units(queue):
    """GRANTED -> VOIDED, handing the granted units back to the launch."""
    launch = db().theme_launches.get(queue["launch_id"])
    held = queue.get("granted_units", 0)
    queue["status"] = "VOIDED"
    queue["granted_units"] = 0
    touch(queue)
    if launch is not None:
        if held:
            launch["exclusive_set_units_remaining"] += held
        recompute_soft_hold(launch)
        reevaluate_launch_grants(launch)
    return queue


def recompute_soft_hold(launch):
    launch["soft_hold_units"] = sum(
        q["requested_units"] for q in db().launch_queues.values()
        if q["launch_id"] == launch["id"] and q["status"] in ("WAITING", "GRANTED"))
    return launch


def recompute_remaining(launch):
    """remaining = allocation minus the units committed to non-voided rows.

    The counter is maintained incrementally on every grant, purchase and
    release; this is the reconciliation used by the epoch passes.
    """
    held = sum(q.get("granted_units", 0) for q in db().launch_queues.values()
               if q["launch_id"] == launch["id"] and q["status"] in UNIT_HOLDING)
    launch["exclusive_set_units_remaining"] = launch["allocated_exclusive_units"] - held
    return launch


def reevaluate_launch_grants(launch):
    """A release re-evaluates the grant batch for this launch.

    Re-evaluation is admitted at VIP_EARLY as well as STAGED_OPEN: the release
    of units means the launch's held total has fallen below what it still has
    to sell, so the batch runs again under the launch's current stage.
    """
    from services.launch import run_grant_batch
    if launch["stage"] not in ("VIP_EARLY", "STAGED_OPEN"):
        return []
    if launch["soft_hold_units"] >= launch["exclusive_set_units_remaining"]:
        return []
    return run_grant_batch(launch)