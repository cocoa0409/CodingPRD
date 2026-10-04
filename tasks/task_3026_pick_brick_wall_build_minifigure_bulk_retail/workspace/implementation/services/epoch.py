"""run_epoch: the three ordered wave_reconcile passes (PRD §3.8)."""

from db import (
    EMPTY_BACKFILL_PCT,
    NO_SHOW_RESTRICT_COUNT,
    db,
    launch_arrival,
    now,
)
from services.core import (
    apply_freeze_consequences,
    recompute_remaining,
    recompute_soft_hold,
    recompute_store,
    rh,
    rh1,
    touch,
)
from services.events import (
    children_of,
    recompute_event_counts,
    promote_off_waitlist,
)
from services.launch import reopen_launch_if_stocked
from services.wall import recompute_shrinkage


# ---------------------------------------------------------------------------
# Round 1 -- repair the wall and open the schedule.
# ---------------------------------------------------------------------------
def round_one(store):
    recompute_store(store)

    for bin_record in [b for b in db().wall_bins.values() if b["store_id"] == store["id"]]:
        if bin_record["status"] != "EMPTY":
            continue
        element = db().elements.get(bin_record["element_id"])
        if element is None or element["status"] not in ("ACTIVE", "CATALOG"):
            continue
        bin_record["bin_mass_grams"] = rh(
            float(bin_record["bin_capacity_grams"]) * float(EMPTY_BACKFILL_PCT))
        bin_record["status"] = "OPEN"
        bin_record["fill_pct"] = rh1(bin_record["bin_mass_grams"] * 100.0
                                     / bin_record["bin_capacity_grams"])
        bin_record["last_restock_index"] = store["last_event_run_index"]
        touch(bin_record)

    # A surplus restock requisition names an element when it sits in a bin that
    # has been retired off the wall -- that is what brings an archived design back.
    for element in db().elements.values():
        if element["status"] != "RETIRED_TO_ARCHIVE":
            continue
        if _requisitioned(element["id"]):
            element["status"] = "CATALOG"
            element["sourcing_mode"] = "SURPLUS"
            touch(element)

    current = now()
    for launch in db().theme_launches.values():
        if launch["stage"] == "SCHEDULED" and current >= launch["vip_early_access_utc"]:
            launch["stage"] = "VIP_EARLY"
        if launch["stage"] == "VIP_EARLY" and current >= launch["release_utc"]:
            launch["stage"] = "STAGED_OPEN"


    for event in db().store_events.values():
        if event["store_id"] != store["id"] or event["stage"] != "SCHEDULED":
            continue
        if store["stage"] == "FROZEN":
            continue
        if current >= event["start_utc"]:
            event["stage"] = "OPEN"
            touch(event)

    recompute_store(store)
    apply_freeze_consequences(store)


def _requisitioned(element_id):
    return any(b["element_id"] == element_id and b["status"] == "RETIRED"
               for b in db().wall_bins.values())


# ---------------------------------------------------------------------------
# Round 2 -- time-limited claims, against fences snapped before anything moves.
# ---------------------------------------------------------------------------
def round_two(store):
    current = now()
    events = [e for e in db().store_events.values() if e["store_id"] == store["id"]]

    snapshots = {event["id"]: event["waitlist_epoch"] for event in events}

    for event in events:
        if event["stage"] == "OPEN" and current >= event["end_utc"]:
            event["stage"] = "CLOSED"
            touch(event)
        if event["stage"] in ("CLOSED", "COMPLETED"):
            for reservation in children_of(event):
                if (reservation["status"] == "REGISTERED"
                        and reservation["checked_in_at_utc"] is None):
                    reservation["status"] = "EXPIRED"
                    touch(reservation)

    for event in events:
        if event["stage"] != "CLOSED":
            recompute_event_counts(event)
            continue
        fence = snapshots[event["id"]]
        pool = [r for r in children_of(event)
                if r["status"] == "WAITLISTED" and r["wait_mark"] <= fence]
        promote_off_waitlist(event, pool, event["registered_count"])
        # Every promoted row that never checks in is recorded as not admitted.
        for reservation in children_of(event):
            if reservation["status"] == "PROMOTED" and reservation["checked_in_at_utc"] is None:
                reservation["status"] = "NOT_ADMITTED"
                touch(reservation)
        event["waitlist_epoch"] += 1
        recompute_event_counts(event)
        touch(event)

    # Replacement prospects past their resolution window expire with zero points.
    for record in db().replacement_requests.values():
        if record["store_id"] != store["id"] or record["stage"] != "PROSPECT":
            continue
        if current >= record["window_expires_utc"]:
            record["stage"] = "EXPIRED"
            record["earned_points"] = 0
            touch(record)

    # Stale queue rows: a launch that closed expires its waiting rows, and a
    # member who is no longer ACTIVE cannot hold a waiting slot.
    for queue in db().launch_queues.values():
        if queue["store_id"] != store["id"] or queue["status"] != "WAITING":
            continue
        launch = db().theme_launches.get(queue["launch_id"])
        member = db().members.get(queue["member_id"])
        if launch is None or member is None:
            continue
        if launch["stage"] == "CLOSED" or member["stage"] != "ACTIVE":
            queue["status"] = "EXPIRED"
            touch(queue)
            recompute_soft_hold(launch)

    for launch in db().theme_launches.values():
        recompute_remaining(launch)
        recompute_soft_hold(launch)


# ---------------------------------------------------------------------------
# Round 3 -- settle and repair.
# ---------------------------------------------------------------------------
def round_three(store):
    # 1. Rollback refunds: a granted or purchased row whose cup was voided
    #    unwinds.  The voided set is collected before any order is closed, so a
    #    void that the same pass goes on to close still refunds its units.
    voided_launches = {}
    for order in db().fusion_orders.values():
        if order.get("_voided") and order.get("exclusive_launch_id"):
            voided_launches[(order["member_id"], order["exclusive_launch_id"])] = order["id"]

    # 2. Orders close once their inspection has reached a terminal stage.
    for order in db().fusion_orders.values():
        if order["store_id"] != store["id"]:
            continue
        inspections = [i for i in db().exit_inspections.values()
                       if i["fusion_order_id"] == order["id"]]
        if order["status"] == "SETTLED" and any(i["stage"] == "COMPLETED" for i in inspections):
            order["status"] = "CLOSED"
            touch(order)
        elif order["status"] == "VOID" and not any(i["stage"] == "SCHEDULED" for i in inspections):
            order["status"] = "CLOSED"
            touch(order)

    for queue in db().launch_queues.values():
        if queue["store_id"] != store["id"]:
            continue
        if queue["status"] not in ("GRANTED", "PURCHASED"):
            continue
        if (queue["member_id"], queue["launch_id"]) not in voided_launches:
            continue
        launch = db().theme_launches.get(queue["launch_id"])
        # The refund returns the granted units to the pool, so the row must stop
        # holding them at the same moment (PRD §3.4: "its granted units are
        # returned to the launch's remaining allocation"; the row is then
        # requeued "with granted_units reset to zero").
        held = queue.get("granted_units", 0)
        queue["status"] = "PURCHASED_ROLLBACK"
        queue["granted_units"] = 0
        touch(queue)
        if launch is not None:
            launch["exclusive_set_units_remaining"] += held
            recompute_soft_hold(launch)

    # 3. A rolled-back row rejoins the queue when its launch is still sellable;
    #    the refund that lifts a closed launch above zero reopens it.
    for queue in db().launch_queues.values():
        if queue["status"] != "PURCHASED_ROLLBACK":
            continue
        launch = db().theme_launches.get(queue["launch_id"])
        if launch is None:
            continue
        recompute_remaining(launch)
        reopen_launch_if_stocked(launch)
        if launch["stage"] == "CLOSED":
            continue
        queue["status"] = "WAITING"
        queue["sequence"] = launch_arrival(queue["launch_id"]).next()
        queue["granted_units"] = 0
        touch(queue)
        recompute_soft_hold(launch)

    for launch in db().theme_launches.values():
        recompute_remaining(launch)
        reopen_launch_if_stocked(launch)
        recompute_soft_hold(launch)

    # 4. Event slots with no live child complete; their stragglers are not admitted.
    for event in db().store_events.values():
        if event["store_id"] != store["id"] or event["stage"] != "CLOSED":
            continue
        children = children_of(event)
        if any(r["status"] in ("REGISTERED", "WAITLISTED", "PROMOTED") for r in children):
            continue
        event["stage"] = "COMPLETED"
        touch(event)
        for reservation in children:
            if reservation["status"] == "WAITLISTED":
                reservation["status"] = "NOT_ADMITTED"
                touch(reservation)
        recompute_event_counts(event)

    # 5. Restricted members return to ACTIVE when the sanction has lapsed.
    frozen = store["stage"] == "FROZEN"
    for member in db().members.values():
        if member["home_store_id"] != store["id"] or member["stage"] != "RESTRICTED":
            continue
        if not frozen and member["passed_mb_reservations"] < NO_SHOW_RESTRICT_COUNT:
            member["stage"] = "ACTIVE"
            touch(member)

    # 6. A return-to-bin correction recorded against a sealed build retires it.
    consumed = []
    for build_id in db().pending_corrections:
        build = db().minifigure_builds.get(build_id)
        if build is None:
            consumed.append(build_id)
            continue
        if build["store_id"] == store["id"] and build["status"] == "SEALED":
            build["status"] = "RETURNED"
            touch(build)
            consumed.append(build_id)
    db().pending_corrections = [b for b in db().pending_corrections if b not in consumed]

    recompute_store(store)
    recompute_shrinkage(store)


def run_epoch(store):
    """Advance last_event_run_index and drive the three ordered passes."""
    store["last_event_run_index"] += 1
    round_one(store)
    round_two(store)
    round_three(store)
    recompute_store(store)
    apply_freeze_consequences(store)
    touch(store)
    return store