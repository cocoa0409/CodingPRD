"""Exclusive set launches: the queue waterfall, the ceilings, and the reclass."""

from db import PRIORITY_CLASS_RANK, db, grant_batch_counter
from services.core import recompute_soft_hold, touch


def wave_units(member_id, launch_id):
    """Units this member already holds for the launch, excluding voided/expired rows."""
    return sum(q["requested_units"] for q in db().launch_queues.values()
               if q["member_id"] == member_id
               and q["launch_id"] == launch_id
               and q["status"] not in ("VOIDED", "EXPIRED"))


def eligible_rows(launch, restrict_ids=None, stage=None):
    """launch_grant_allocation: the eligible pool, in priority-class then sequence order."""
    stage = stage or launch["stage"]
    rows = []
    for queue in db().launch_queues.values():
        if queue["launch_id"] != launch["id"] or queue["status"] != "WAITING":
            continue
        member = db().members.get(queue["member_id"])
        if member is None or member["stage"] != "ACTIVE":
            continue
        if queue["priority_class"] == "VIP_EARLY":
            if stage not in ("VIP_EARLY", "STAGED_OPEN"):
                continue
        else:
            if stage != "STAGED_OPEN":
                continue
        if restrict_ids is not None and queue["id"] not in restrict_ids:
            continue
        rows.append(queue)
    rows.sort(key=lambda q: (PRIORITY_CLASS_RANK[q["priority_class"]], q["sequence"]))
    return rows


def run_grant_batch(launch, restrict_ids=None, stage=None):
    """Walk the ordered population once; the waterfall stops at the first row that does not fit."""
    batch_index = grant_batch_counter(launch["id"]).next()

    remaining = launch["exclusive_set_units_remaining"]
    cumulative = 0
    granted = []
    for queue in eligible_rows(launch, restrict_ids, stage):
        units = queue["requested_units"]
        if cumulative + units <= remaining:
            queue["status"] = "GRANTED"
            queue["granted_units"] = units
            queue["batch_index"] = batch_index
            touch(queue)
            cumulative += units
            granted.append(queue)
        else:
            break

    launch["exclusive_set_units_remaining"] = remaining - cumulative
    recompute_soft_hold(launch)
    touch(launch)   # the grant batch is one of only two writes that advance the launch version

    if launch["exclusive_set_units_remaining"] == 0 and launch["stage"] == "STAGED_OPEN":
        close_launch(launch)
    return granted


def close_launch(launch):
    """STAGED_OPEN -> CLOSED expires every queue row of the launch still waiting."""
    launch["stage"] = "CLOSED"
    for queue in db().launch_queues.values():
        if queue["launch_id"] == launch["id"] and queue["status"] == "WAITING":
            queue["status"] = "EXPIRED"
            touch(queue)
    recompute_soft_hold(launch)
    return launch


def reopen_launch_if_stocked(launch):
    """The compensating half: stock returning while CLOSED makes the launch sellable again."""
    if launch["stage"] == "CLOSED" and launch["exclusive_set_units_remaining"] > 0:
        launch["stage"] = "STAGED_OPEN"
    return launch


def reclass_waiting_rows(member):
    """launch_queue_priority_reclass -- only WAITING rows, sequence untouched."""
    changed = []
    for queue in db().launch_queues.values():
        if queue["member_id"] == member["id"] and queue["status"] == "WAITING":
            queue["priority_class"] = "VIP_EARLY"
            touch(queue)
            changed.append(queue)
    return changed