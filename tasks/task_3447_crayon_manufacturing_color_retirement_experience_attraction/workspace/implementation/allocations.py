"""Retail allocations and the seasonal waterfall decisions (PRD section 3.5)."""
from calculations import (
    recompute_spec, rerun_waterfall, spec_boxes_available, spec_lots,
)
from constants import (
    ROLE_ALLOCATION_PLANNER, ROLE_PLATFORM_ADMIN, SEASON_END, SEASON_START,
)
from envelope import ok
from errors import ApiError
from store import STORE, parse_dt
from validation import (
    auth, body, get_or_404, new_entity, req_dt, req_enum, req_int, req_str,
    require_role, touch,
)


def serialize_allocation(a):
    return {
        "id": a["id"],
        "assortment_spec_id": a["assortment_spec_id"],
        "retailer_name": a["retailer_name"],
        "priority_tier": a["priority_tier"],
        "requested_boxes": a["requested_boxes"],
        "requested_ship_date": a["requested_ship_date"],
        "allocated_boxes_provisional": a["allocated_boxes_provisional"],
        "allocated_boxes_final": a["allocated_boxes_final"],
        "status": a["status"],
        "request_seq": a["request_seq"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def create_allocation():
    _, role = auth()
    require_role(role, {ROLE_ALLOCATION_PLANNER})
    data = body()
    spec_id = req_str(data, "assortment_spec_id")
    retailer_name = req_str(data, "retailer_name")
    tier = req_enum(data, "priority_tier", ("PLATINUM", "GOLD", "STANDARD"))
    requested_boxes = req_int(data, "requested_boxes")
    ship_raw, ship = req_dt(data, "requested_ship_date")
    expected_version = req_int(data, "expected_assortment_spec_version")
    if requested_boxes < 1:
        raise ApiError("ERR_INVALID_REQUEST", "requested_boxes must be >= 1")
    spec = get_or_404(STORE.specs, spec_id)
    # Optimistic concurrency (stage 5).
    if expected_version != spec["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # Temporal (stage 8): the season window, inclusive at both ends.
    if not (parse_dt(SEASON_START) <= ship <= parse_dt(SEASON_END)):
        raise ApiError("ERR_SEASON_WINDOW")
    alloc = new_entity({
        "assortment_spec_id": spec_id,
        "retailer_name": retailer_name,
        "priority_tier": tier,
        "requested_boxes": requested_boxes,
        "requested_ship_date": ship_raw,
        "allocated_boxes_provisional": 0,
        "allocated_boxes_final": None,
        "status": "REQUESTED",
        "request_seq": STORE.next_scoped(STORE.request_seq, spec_id),
    })
    STORE.allocations[alloc["id"]] = alloc
    # Provisional waterfall share computed immediately (covers this allocation).
    # The spec's version advances by exactly 1 in this request: the waterfall's
    # recompute supplies the bump when boxes_reserved changed; otherwise the
    # creation itself bumps it so the next stale writer is rejected (OCC rule).
    version_before = spec["version"]
    rerun_waterfall(spec)
    if spec["version"] == version_before:
        touch(spec)
    return ok(serialize_allocation(alloc), status=201)


def get_allocation(alloc_id):
    _, role = auth()
    require_role(role, {ROLE_PLATFORM_ADMIN, ROLE_ALLOCATION_PLANNER})
    alloc = get_or_404(STORE.allocations, alloc_id)
    return ok(serialize_allocation(alloc))


def _deduct_lots_fifo(spec_id, amount):
    """COMMIT deduction: on_hand -> committed over AVAILABLE/DEPLETED lots, FIFO."""
    remaining = amount
    for lot in spec_lots(spec_id):
        if remaining <= 0:
            break
        if lot["status"] not in ("AVAILABLE", "DEPLETED"):
            continue
        take = min(remaining, lot["boxes_on_hand"])
        if take <= 0:
            continue
        lot["boxes_on_hand"] -= take
        lot["boxes_committed"] += take
        if lot["boxes_on_hand"] == 0:
            lot["status"] = "DEPLETED"
        touch(lot)
        remaining -= take


def _ship_lots_fifo(spec_id, amount):
    """FULFILL: committed -> shipped over the spec's lots, FIFO."""
    remaining = amount
    for lot in spec_lots(spec_id):
        if remaining <= 0:
            break
        give = min(remaining, lot["boxes_committed"])
        if give <= 0:
            continue
        lot["boxes_committed"] -= give
        lot["boxes_shipped"] += give
        touch(lot)
        remaining -= give


def _return_lots_fifo(spec_id, amount):
    """RELEASE from COMMITTED: committed -> on_hand, FIFO; DEPLETED lots reopen."""
    remaining = amount
    for lot in spec_lots(spec_id):
        if remaining <= 0:
            break
        give = min(remaining, lot["boxes_committed"])
        if give <= 0:
            continue
        lot["boxes_committed"] -= give
        lot["boxes_on_hand"] += give
        if lot["status"] == "DEPLETED" and lot["boxes_on_hand"] > 0:
            lot["status"] = "AVAILABLE"
        touch(lot)
        remaining -= give


def allocation_decision(alloc_id):
    _, role = auth()
    require_role(role, {ROLE_ALLOCATION_PLANNER})
    data = body()
    action = req_enum(data, "action", ("COMMIT", "FULFILL", "RELEASE"))
    alloc = get_or_404(STORE.allocations, alloc_id)
    spec = STORE.specs[alloc["assortment_spec_id"]]
    if action == "COMMIT":
        if alloc["status"] != "REQUESTED":
            raise ApiError("ERR_ALLOCATION_STATE")
        # FINAL share: physical on-hand only, projections excluded.
        final = min(alloc["requested_boxes"], spec_boxes_available(spec["id"]))
        if final <= 0:
            raise ApiError("ERR_INSUFFICIENT_INVENTORY")
        alloc["allocated_boxes_final"] = final
        alloc["status"] = "COMMITTED"
        touch(alloc)
        _deduct_lots_fifo(spec["id"], final)
        recompute_spec(spec)
        rerun_waterfall(spec)
    elif action == "FULFILL":
        if alloc["status"] != "COMMITTED":
            raise ApiError("ERR_ALLOCATION_STATE")
        _ship_lots_fifo(spec["id"], alloc["allocated_boxes_final"])
        alloc["status"] = "FULFILLED"
        touch(alloc)
        recompute_spec(spec)
        rerun_waterfall(spec)
    else:  # RELEASE
        if alloc["status"] == "REQUESTED":
            alloc["status"] = "RELEASED"
            touch(alloc)
            recompute_spec(spec)
            rerun_waterfall(spec)
        elif alloc["status"] == "COMMITTED":
            _return_lots_fifo(spec["id"], alloc["allocated_boxes_final"])
            alloc["status"] = "RELEASED"
            touch(alloc)
            recompute_spec(spec)
            rerun_waterfall(spec)
        else:
            raise ApiError("ERR_ALLOCATION_STATE")
    return ok(serialize_allocation(alloc))


def register(app):
    app.add_url_rule("/crayon-works/retail-allocations",
                     view_func=create_allocation, methods=["POST"])
    app.add_url_rule("/crayon-works/retail-allocations/<alloc_id>",
                     view_func=get_allocation, methods=["GET"])
    app.add_url_rule("/crayon-works/retail-allocations/<alloc_id>/decision",
                     view_func=allocation_decision, methods=["POST"])
