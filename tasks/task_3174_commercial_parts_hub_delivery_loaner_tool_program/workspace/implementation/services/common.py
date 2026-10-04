"""Shared service helpers: the audit spine, the archive guard, supersession
resolution, fitment matching and inventory line manipulation."""

from timeutil import now_stamp

import db
from errors import ApiError, bad_request

# ---------------------------------------------------------------------------
# debug hook (not part of the contract; lets the harness recover an id)
# ---------------------------------------------------------------------------

_DEBUG = {"enabled": False}


def enable_debug():
    _DEBUG["enabled"] = True


def debug_enabled():
    return _DEBUG["enabled"]


def remember(kind, row_id):
    if not _DEBUG["enabled"]:
        return
    bucket = _DEBUG.setdefault(kind, [])
    if row_id not in bucket:
        bucket.append(row_id)


def remembered(kind):
    return list(_DEBUG.get(kind, []))


def reset_debug():
    for key in list(_DEBUG.keys()):
        if key != "enabled":
            _DEBUG.pop(key, None)


# ---------------------------------------------------------------------------
# audit spine (PRD 2.4)
# ---------------------------------------------------------------------------

def new_resource(fields, common=True):
    """Mint a resource with the common audit spine."""
    row = dict(fields)
    row["id"] = db.new_id()
    if common:
        row["created_at"] = db.stamp()
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    else:
        row["created_at"] = db.stamp()
    return row


def record_audit(row):
    row["updated_at"] = now_stamp()
    row["version"] = row.get("version", 1) + 1
    return row


def slim_resource(fields):
    """Child records carry only id and created_at (PRD 2.4)."""
    row = dict(fields)
    row["id"] = db.new_id()
    row["created_at"] = db.stamp()
    return row


# ---------------------------------------------------------------------------
# archive guard (PRD 3.2 / 3.8)
# ---------------------------------------------------------------------------

OPEN_ORDER_STATES = ("DRAFT", "CONFIRMED", "ALLOCATED", "PICKING", "DISPATCHED")
OPEN_LOAN_STATES = ("REQUESTED", "CHECKED_OUT", "IN_USE", "DUE", "OVERDUE", "RETURNED", "INSPECTED")
OPEN_CORE_STATES = ("INITIATED", "IN_TRANSIT", "INSPECTED")
OPEN_ROUTE_STATES = ("DRAFT", "PLANNED", "DISPATCHED")
OPEN_STOP_STATES = ("PLANNED", "SEQUENCED", "EN_ROUTE", "REJECTED")


def archive_guard(kind, row):
    """A CommercialAccount, Part or Store may not be archived while a
    non-terminal resource references it (ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE)."""
    if kind == "Part":
        part_id = row["id"]
        for order in db.part_orders.values():
            if order.get("status") not in OPEN_ORDER_STATES:
                continue
            for line in order.get("line_items") or []:
                if line.get("part_id") == part_id:
                    raise ApiError("ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE")
                resolved = resolve_current(line.get("part_id"))
                if resolved and resolved.get("id") == part_id:
                    raise ApiError("ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE")
        for loan in db.tool_loans.values():
            if loan.get("status") in ("CLOSED", "FORFEITED"):
                continue
            if loan.get("replacement_part_id") == part_id:
                raise ApiError("ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE")
        for core in db.core_returns.values():
            if core.get("status") in ("CREDITED", "REJECTED"):
                continue
            for line in core.get("line_items") or []:
                if line.get("part_id") == part_id:
                    raise ApiError("ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE")
    elif kind == "Store":
        store_id = row["id"]
        for account in db.accounts.values():
            if account.get("home_store_id") == store_id and not account.get("is_archived"):
                raise ApiError("ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE")
        for part in db.parts.values():
            if part.get("is_archived"):
                continue
        for item in db.inventory_items.values():
            if item.get("store_id") == store_id and item.get("on_hand_units", 0) > 0:
                pass
        for store in db.stores.values():
            if store.get("hub_store_id") == store_id and not store.get("is_archived"):
                raise ApiError("ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE")
        for route in db.service_routes.values():
            if route.get("status") in OPEN_ROUTE_STATES:
                for stop in stops_of(route["id"]):
                    if stop.get("account_id"):
                        account = db.accounts.get(stop["account_id"])
                        if account and account.get("home_store_id") == store_id:
                            raise ApiError("ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE")
    elif kind == "CommercialAccount":
        account_id = row["id"]
        for order in db.part_orders.values():
            if order.get("account_id") == account_id and order.get("status") in OPEN_ORDER_STATES:
                raise ApiError("ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE")
        for loan in db.tool_loans.values():
            if loan.get("account_id") == account_id and loan.get("status") in OPEN_LOAN_STATES:
                raise ApiError("ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE")
        for core in db.core_returns.values():
            if core.get("account_id") == account_id and core.get("status") in OPEN_CORE_STATES:
                raise ApiError("ERR_ARCHIVE_BLOCKED_BY_OPEN_REFERENCE")


# ---------------------------------------------------------------------------
# supersession
# ---------------------------------------------------------------------------

def supersession_chain(part_id, limit=512):
    """Walk superseded_by_part_id forward to the terminal current part."""
    seen = set()
    current = db.parts.get(part_id)
    chain = []
    while current is not None and current.get("superseded_by_part_id"):
        if current["id"] in seen or len(chain) > limit:
            break
        seen.add(current["id"])
        chain.append(current["id"])
        nxt = db.parts.get(current["superseded_by_part_id"])
        if nxt is None:
            break
        current = nxt
    return chain, current


def resolve_current(part_id):
    _, terminal = supersession_chain(part_id)
    return terminal


def supersession_depth(part_id):
    chain, terminal = supersession_chain(part_id)
    if terminal is None or terminal.get("id") == part_id:
        return 0
    return len(chain)


def recompute_depths():
    """Recompute supersession_depth for every part whose forward chain reaches
    a superseded part (PRD 3.2)."""
    for part in db.parts.values():
        depth = supersession_depth(part["id"])
        if part.get("supersession_depth") != depth:
            part["supersession_depth"] = depth
            record_audit(part)


def chain_parts(part_id):
    """The part itself plus every part on its forward supersession chain."""
    chain, terminal = supersession_chain(part_id)
    ids = list(chain)
    if terminal is not None:
        ids.append(terminal["id"])
    if part_id not in ids:
        ids.append(part_id)
    return ids


# ---------------------------------------------------------------------------
# fitment
# ---------------------------------------------------------------------------

def _value_matches(row_value, vehicle_value):
    if row_value is None:
        return True
    text = str(row_value)
    if text == "ANY":
        return True
    return text == str(vehicle_value)


def fits_vehicle(part, vehicle):
    if vehicle is None:
        return True
    for row in db.part_fitments.values():
        if row.get("part_id") != part.get("id"):
            continue
        year = vehicle.get("year")
        if year is not None:
            if row.get("year_from") is not None and year < row["year_from"]:
                continue
            if row.get("year_to") is not None and year > row["year_to"]:
                continue
        if row.get("make") is not None and str(row["make"]) != str(vehicle.get("make")):
            continue
        if row.get("model") is not None and str(row["model"]) != str(vehicle.get("model")):
            continue
        if not _value_matches(row.get("engine_code"), vehicle.get("engine_code")):
            continue
        if not _value_matches(row.get("drive_type"), vehicle.get("drive_type")):
            continue
        return True
    return False


def line_fits(part, vehicle):
    """A line's part fits when it fits directly, or resolves through
    interchange equivalence or the supersession chain to a part that does
    (PRD 3.3)."""
    if vehicle is None:
        return True
    if fits_vehicle(part, vehicle):
        return True
    # supersession: any part on the forward chain
    for chain_id in chain_parts(part["id"]):
        candidate = db.parts.get(chain_id)
        if candidate is not None and fits_vehicle(candidate, vehicle):
            return True
    # interchange equivalence: a part whose list of alternate numbers matches
    # this part's, or which shares an interchange number with a fitting part
    skus = set()
    for row in db.part_interchanges.values():
        if row.get("part_id") == part["id"]:
            skus.add((row.get("interchange_sku"), row.get("interchange_brand")))
    if not skus:
        return False
    for row in db.part_interchanges.values():
        key = (row.get("interchange_sku"), row.get("interchange_brand"))
        if key not in skus:
            continue
        twin = db.parts.get(row.get("part_id"))
        if twin is None or twin.get("id") == part["id"]:
            continue
        if fits_vehicle(twin, vehicle):
            return True
        for chain_id in chain_parts(twin["id"]):
            candidate = db.parts.get(chain_id)
            if candidate is not None and fits_vehicle(candidate, vehicle):
                return True
    return False


def fitment_lookup(vehicle_id, part_id, include_archived):
    results = {}
    vehicles = []
    if vehicle_id:
        vehicle = db.vehicles.get(vehicle_id)
        if vehicle is None:
            raise ApiError("ERR_VEHICLE_NOT_FOUND")
        vehicles = [vehicle]
    else:
        vehicles = list(db.vehicles.values())

    seeds = []
    if part_id:
        seed = db.parts.get(part_id)
        if seed is None:
            raise ApiError("ERR_PART_NOT_FOUND")
        seeds = [seed]
    else:
        seeds = list(db.parts.values())

    for seed in seeds:
        if not include_archived and seed.get("is_archived"):
            continue
        terminal = resolve_current(seed["id"])
        if terminal is None:
            continue
        if not include_archived and terminal.get("is_archived"):
            continue
        if not vehicles:
            results[terminal["id"]] = terminal
            continue
        for vehicle in vehicles:
            if fits_vehicle(terminal, vehicle):
                results[terminal["id"]] = terminal
                break
    return list(results.values())


# ---------------------------------------------------------------------------
# inventory
# ---------------------------------------------------------------------------

def inventory_item_for(store_id, part_id):
    for item in db.inventory_items.values():
        if item.get("store_id") == store_id and item.get("part_id") == part_id:
            return item
    return None


def available_units(store_id, part_id):
    item = inventory_item_for(store_id, part_id)
    if item is None:
        return 0
    return max(0, item.get("on_hand_units", 0) - item.get("reserved_units", 0))


def ensure_inventory(store_id, part_id):
    item = inventory_item_for(store_id, part_id)
    if item is None:
        item = new_resource({
            "store_id": store_id,
            "part_id": part_id,
            "on_hand_units": 0,
            "reserved_units": 0,
        })
        db.inventory_items[item["id"]] = item
    return item


def reserve(item, units):
    item["reserved_units"] = item.get("reserved_units", 0) + units
    record_audit(item)


def release_reservation(item, units):
    item["reserved_units"] = max(0, item.get("reserved_units", 0) - units)
    record_audit(item)


def available_of(item):
    return max(0, item.get("on_hand_units", 0) - item.get("reserved_units", 0))


# ---------------------------------------------------------------------------
# stores
# ---------------------------------------------------------------------------

def stops_of(route_id):
    return [stop for stop in db.route_stops.values() if stop.get("route_id") == route_id]


def orders_of(account_id, statuses=None):
    out = []
    for order in db.part_orders.values():
        if order.get("account_id") != account_id:
            continue
        if statuses is not None and order.get("status") not in statuses:
            continue
        out.append(order)
    return out


def loans_of(account_id, statuses=None, deposit_states=None):
    out = []
    for loan in db.tool_loans.values():
        if loan.get("account_id") != account_id:
            continue
        if statuses is not None and loan.get("status") not in statuses:
            continue
        if deposit_states is not None and loan.get("deposit_state") not in deposit_states:
            continue
        out.append(loan)
    return out


def core_returns_of(account_id, statuses=None):
    out = []
    for core in db.core_returns.values():
        if core.get("account_id") != account_id:
            continue
        if statuses is not None and core.get("status") not in statuses:
            continue
        out.append(core)
    return out


def not_found(error_id):
    raise ApiError(error_id)