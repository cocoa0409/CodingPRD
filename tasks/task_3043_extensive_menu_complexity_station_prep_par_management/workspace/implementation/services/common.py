from datetime import datetime, timezone

from db import db, now_iso, format_iso, parse_iso, clock_now
from errors import ApiError, err_invalid_request, err_not_found

STATION_TYPES = ["GRILL", "SAUTE", "FRY", "BAKERY", "COLD"]
BATCH_UNITS = ["OZ", "EA", "ML"]
MODIFICATION_POLICIES = ["ALLOWED", "LIMITED", "FORBIDDEN"]
CHEESECAKE_TYPES = ["ORIGINAL", "CHOCOLATE", "STRAWBERRY", "SEASONAL"]
WASTE_REASONS = ["OVER_PREP", "EXPIRED", "QUALITY", "SPILLAGE"]
GENERATION_VARIANTS = ["OPTIMISTIC", "CONSERVATIVE"]

BATCH_TERMINAL = {"DEPLETED", "EXPIRED", "WASTED", "CANCELLED"}
ASSIGNMENT_NON_TERMINAL = {"SCHEDULED", "CONFIRMED"}


def touch(entity):
    """Refresh updated_at and bump version on any mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def new_entity():
    ts = now_iso()
    return {"created_at": ts, "updated_at": ts, "version": 1}


# ---------------- request field validation helpers ----------------

def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")


def check_str(body, field, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return None
    if not isinstance(v, str):
        raise err_invalid_request(f"Field {field} must be a string")
    return v


def check_int(body, field, required=True, min_value=None, allow_zero=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"Field {field} must be an integer")
    if min_value is not None and v < min_value:
        raise err_invalid_request(f"Field {field} must be >= {min_value}")
    if not allow_zero and v == 0:
        raise err_invalid_request(f"Field {field} must be > 0")
    return v


def check_enum(body, field, values, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return default
    v = body[field]
    if not isinstance(v, str) or v not in values:
        raise err_invalid_request(f"Field {field} must be one of {values}")
    return v


def check_array(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return default
    v = body[field]
    if not isinstance(v, list):
        raise err_invalid_request(f"Field {field} must be an array")
    return v


def check_datetime(body, field, required=True):
    v = check_str(body, field, required=required)
    if v is None:
        return None
    try:
        return parse_iso(v)
    except (ValueError, TypeError):
        raise err_invalid_request(f"Field {field} must be a valid ISO8601 datetime")


def parse_datetime_value(v, field):
    try:
        return parse_iso(v)
    except (ValueError, TypeError):
        raise err_invalid_request(f"Field {field} must be a valid ISO8601 datetime")


# ---------------- FK resolution ----------------

COLLECTIONS = {
    "restaurant": ("restaurants",),
    "menu_revision": ("menu_revisions",),
    "recipe": ("recipes",),
    "prep_item": ("prep_items",),
    "station": ("stations",),
    "station_par": ("station_pars",),
    "cook": ("cooks",),
    "demand_forecast": ("demand_forecasts",),
    "prep_list": ("prep_lists",),
    "prep_batch": ("prep_batches",),
    "shift_assignment": ("shift_assignments",),
    "bakery_order": ("bakery_orders",),
    "waste_entry": ("waste_entries",),
    "service_ticket": ("service_tickets",),
}


def resolve(kind, entity_id):
    if not isinstance(entity_id, str):
        raise err_not_found(kind)
    coll = getattr(db, COLLECTIONS[kind][0])
    ent = coll.get(entity_id)
    if ent is None:
        raise err_not_found(kind)
    return ent


def get_or_404_path(kind, entity_id):
    return resolve(kind, entity_id)


# ---------------- shared domain helpers ----------------

def rack_load(station_id):
    total = 0
    for b in db.prep_batches.values():
        if b["station_id"] == station_id and b["status"] in ("PLANNED", "PREPPED"):
            total += b["quantity"] - b["consumed_quantity"] - b["wasted_quantity"]
    return total


def recompute_par_health(station_id):
    """Recompute a station's par_health; mutates station (touch on change)."""
    station = db.stations.get(station_id)
    if station is None:
        return
    severity = {"CRITICAL": 0, "BELOW_PAR": 1, "OK": 2}
    worst = "OK"
    for par in db.station_pars.values():
        if par["station_id"] != station_id or par["status"] != "ACTIVE":
            continue
        on_hand = 0
        for b in db.prep_batches.values():
            if (
                b["station_id"] == station_id
                and b["prep_item_id"] == par["prep_item_id"]
                and b["status"] in ("PLANNED", "PREPPED")
            ):
                on_hand += b["quantity"] - b["consumed_quantity"] - b["wasted_quantity"]
        pq = par["par_quantity"]
        if on_hand < 0.25 * pq:
            cand = "CRITICAL"
        elif on_hand < pq:
            cand = "BELOW_PAR"
        else:
            cand = "OK"
        if severity[cand] < severity[worst]:
            worst = cand
    if station["par_health"] != worst:
        station["par_health"] = worst
        touch(station)


def finalize_batch_terminal(batch, new_status):
    """Transition a batch to a terminal state and run the shared cascade."""
    batch["status"] = new_status
    touch(batch)
    recompute_par_health(batch["station_id"])
    maybe_complete_prep_list(batch["prep_list_id"])
    # Waste entries on this batch flip to ATTRIBUTED
    for w in db.waste_entries.values():
        if w["prep_batch_id"] == batch["id"] and w["status"] == "RECORDED":
            w["status"] = "ATTRIBUTED"
            touch(w)


def maybe_complete_prep_list(prep_list_id):
    pl = db.prep_lists.get(prep_list_id)
    if pl is None or pl["status"] != "IN_PROGRESS":
        return
    batches = [b for b in db.prep_batches.values() if b["prep_list_id"] == prep_list_id]
    if batches and all(b["status"] in BATCH_TERMINAL for b in batches):
        pl["status"] = "COMPLETED"
        touch(pl)


def cancel_planned_batch(batch):
    """System cancellation of a PLANNED batch (regenerate / retire / publish)."""
    batch["status"] = "CANCELLED"
    touch(batch)
    recompute_par_health(batch["station_id"])
    maybe_complete_prep_list(batch["prep_list_id"])


def suspend_pars_and_cancel_batches(prep_item_ids):
    """For retired prep items: ACTIVE pars -> SUSPENDED; PLANNED batches at
    stations whose par was just suspended -> CANCELLED."""
    suspended = []
    for par in db.station_pars.values():
        if par["status"] == "ACTIVE" and par["prep_item_id"] in prep_item_ids:
            par["status"] = "SUSPENDED"
            touch(par)
            suspended.append(par)
    for par in suspended:
        for b in db.prep_batches.values():
            if (
                b["status"] == "PLANNED"
                and b["station_id"] == par["station_id"]
                and b["prep_item_id"] == par["prep_item_id"]
            ):
                cancel_planned_batch(b)
        recompute_par_health(par["station_id"])


def active_recipe_item_ids(restaurant_id):
    """Prep item ids referenced by ACTIVE recipes whose revision belongs to this restaurant."""
    rev_ids = {
        r["id"] for r in db.menu_revisions.values() if r["restaurant_id"] == restaurant_id
    }
    referenced = set()
    for rec in db.recipes.values():
        if rec["menu_revision_id"] in rev_ids and rec["status"] == "ACTIVE":
            for c in rec.get("components", []):
                referenced.add(c["prep_item_id"])
    return referenced


def retire_prep_item(item):
    """Retire an ACTIVE prep item and run the cascade."""
    item["status"] = "RETIRED"
    touch(item)
    suspend_pars_and_cancel_batches({item["id"]})


def list_paginated(collection, filters, args):
    """filters: list of (query_param, record_field)."""
    items = list(collection.values())
    for qp, rf in filters:
        if qp in args and args.get(qp) is not None:
            items = [i for i in items if i.get(rf) == args.get(qp)]
    items.sort(key=lambda i: (i["created_at"], i.get("_seq", 0)))
    total = len(items)
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    page = items[offset:offset + limit]
    return page, limit, offset, total
