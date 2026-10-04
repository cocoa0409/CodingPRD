# Shortage allocation runs (PRD 3.6): awards computed and frozen at creation
# (calc_allocation_awards), applied at publish.
from flask import Blueprint

import derive
from auth import require_roles
from envelope import success
from errors import ApiError, ERR_INVALID_STATE
from lookups import get_allocation_run
from serialize import allocation_run_public
from store import store
from validate import as_str, check_unknown_fields, get_body, require_fields

bp = Blueprint("allocation", __name__)

_CREATE_ALLOWED = {"period_label"}


def _compute_awards():
    """calc_allocation_awards: one frozen entry per eligible line (0-award
    entries included). Parts processed in part_number ASC order."""
    eligible = []
    for line in store.order_lines.values():
        order = store.orders.get(line["order_id"])
        if order is None or order["status"] != "BACKORDERED":
            continue
        if line["quantity"] - line["awarded_units"] > 0:
            eligible.append(line)
    parts = {}
    for line in eligible:
        parts.setdefault(line["part_id"], store.parts[line["part_id"]])
    ordered_parts = sorted(parts.values(), key=lambda p: p["part_number"])

    awards = []
    for part in ordered_parts:
        available = part["on_hand_units"] - derive.part_reserved_units(part["id"])
        part_lines = [l for l in eligible if l["part_id"] == part["id"]]

        def sort_key(line):
            order = store.orders[line["order_id"]]
            # score DESC, order.created_at ASC, line.created_at ASC; lines of
            # the same order fall back to creation sequence (== lines-array
            # position, since the clock is fixed within a creation request).
            return (-derive.priority_score(line), order["created_at"], order["seq"], line["seq"])

        part_lines.sort(key=sort_key)
        for rank, line in enumerate(part_lines, start=1):
            remaining = line["quantity"] - line["awarded_units"]
            award = min(remaining, available)
            if award < 0:
                award = 0
            available -= award
            awards.append({
                "order_line_id": line["id"],
                "awarded_units": award,
                "priority_score": derive.priority_score(line),
                "rank": rank,
            })
    return awards


@bp.post("/allocation-runs")
def create_allocation_run():
    require_roles("SupplyPlanner")
    body = get_body(required=True)
    require_fields(body, ["period_label"])
    check_unknown_fields(body, _CREATE_ALLOWED)
    period_label = as_str(body["period_label"], "period_label")
    shortage_part_ids = [
        p["id"] for p in store.parts.values()
        if derive.coverage_and_posture(p)[1] == "SHORTAGE"
    ]
    shortage_part_ids.sort(key=lambda pid: store.parts[pid]["part_number"])
    run = {
        "period_label": period_label,
        "status": "DRAFT",
        "shortage_part_ids": shortage_part_ids,
        "awards": _compute_awards(),
    }
    run.update(store.stamp())
    store.allocation_runs[run["id"]] = run
    return success(allocation_run_public(run), 201)


@bp.post("/allocation-runs/<run_id>/publish")
def publish_allocation_run(run_id):
    require_roles("SupplyPlanner")
    run = get_allocation_run(run_id)
    body = get_body(required=False)
    check_unknown_fields(body, set())
    if run["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT allocation run can be published")
    touched_orders = set()
    for entry in run["awards"]:
        line = store.order_lines.get(entry["order_line_id"])
        if line is None:
            continue
        line["awarded_units"] += entry["awarded_units"]
        line["allocation_run_id"] = run["id"]
        line["allocation_rank"] = entry["rank"]
        line["allocation_priority_score"] = entry["priority_score"]
        store.touch(line)
        touched_orders.add(line["order_id"])
    for order_id in touched_orders:
        order = store.orders[order_id]
        if order["status"] != "BACKORDERED":
            continue
        lines = derive.order_lines_of(order["id"])
        if all(l["awarded_units"] == l["quantity"] for l in lines):
            order["status"] = "ALLOCATED"
            store.touch(order)
    run["status"] = "PUBLISHED"
    store.touch(run)
    return success(allocation_run_public(run))
