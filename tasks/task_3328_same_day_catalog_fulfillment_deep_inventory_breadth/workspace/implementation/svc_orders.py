"""CatalogOrder domain: creation, release cycle, allocation, picking,
cutoff certification, freight, returns and damage claims.

Validation precedence follows PRD section 2.9 exactly: authentication and
authorization live in auth.py, this module owns priorities 3..16 and always
evaluates them in the pinned order (existence -> ownership -> terminal ->
state -> stale version -> posture -> suspension -> curation -> candidate ->
delivery window -> promise date -> part number -> inbound capacity).
"""

from datetime import timedelta

from calculations import (RESTOCK_CAP_UNITS, damage_value_cents,
                          damaged_unit_ratio_breach, derived_line_subtotal,
                          freight_charge_two_variant,
                          order_total_cents_factor_first,
                          order_total_two_variant, restock_cap_allocation,
                          select_dc, small_line_fee_total_and_allocate)
from common import (body_json, invalid_request, out_iso, parse_optional_datetime,
                    require, require_int, require_str)
from db import created_key
from errors import ApiError, not_found

SERVICE_LEVELS = ("GROUND", "TWO_DAY", "OVERNIGHT")
LINE_STATUSES = ("PENDING", "ALLOCATED", "PICKED", "SHORT", "RESTOCKED", "RETURNED")
ORDER_STATUSES = ("DRAFT", "RELEASED", "CANCELLED")
FULFILLMENT_STATUSES = ("AWAITING_RELEASE", "ALLOCATED", "PICKED", "SHIPPED", "RETURNED")


# --------------------------------------------------------------- lookups

def get_order(store, order_id):
    record = store.orders.get(order_id)
    if record is None:
        raise not_found("ERR_ORDER_NOT_FOUND", "No order exists for id '%s'." % order_id)
    return record


def get_line(store, order, line_id):
    record = store.order_lines.get(line_id)
    if record is None or record.get("order_id") != order["id"]:
        raise not_found("ERR_LINE_NOT_FOUND",
                        "No line exists for id '%s' on order '%s'." % (line_id, order["id"]))
    return record


def get_account(store, account_id):
    record = store.accounts.get(account_id)
    if record is None:
        raise not_found("ERR_INVALID_REQUEST", "No customer account exists for id '%s'." % account_id)
    return record


def create_account(store, body):
    from svc_dc import REGIONS
    account_name = require_str(body, "account_name")
    delivery_zone = require_str(body, "delivery_zone")
    home_region = require_str(body, "home_region")
    if home_region not in REGIONS:
        raise invalid_request("Field 'home_region' must be one of %s." % " | ".join(REGIONS))
    record = {
        "account_name": account_name,
        "delivery_zone": delivery_zone,
        "home_region": home_region,
        "open_claim_count": 0,
    }
    store.stamp(record)
    store.accounts[record["id"]] = record
    return record


def account_matches(account, args):
    home_region = args.get("home_region")
    if home_region and account.get("home_region") != home_region:
        return False
    return True


def get_return(store, return_id):
    record = store.return_authorizations.get(return_id)
    if record is None:
        raise not_found("ERR_RETURN_NOT_FOUND", "No return authorization exists for id '%s'." % return_id)
    return record


def get_claim(store, claim_id):
    record = store.damage_claims.get(claim_id)
    if record is None:
        raise not_found("ERR_CLAIM_NOT_FOUND", "No damage claim exists for id '%s'." % claim_id)
    return record


def lines_of(store, order_id):
    rows = [line for line in store.order_lines.values() if line.get("order_id") == order_id]
    return sorted(rows, key=created_key)


def shipment_of(store, order_id):
    rows = [s for s in store.shipments.values() if s.get("order_id") == order_id]
    rows.sort(key=created_key)
    return rows[0] if rows else None


def _clinical_order_lines(store, order_id):
    return [line for line in store.order_lines.values() if line.get("order_id") == order_id]


# ------------------------------------------------------------ state guards

def _ownership(order, user_id):
    """Priority 4: the calling CustomerAccount must own the order."""
    if order.get("account_id") != user_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP",
                       "The calling account does not own order '%s'." % order["id"], 403)


def _not_terminal(record, terminal, message):
    """Priority 5."""
    if record.get("order_status") in terminal:
        raise ApiError("ERR_ALREADY_TERMINAL", message, 409)


def _require_state(condition, message):
    """Priority 6."""
    if not condition:
        raise ApiError("ERR_INVALID_STATE", message, 409)


def _stale_version(order, body):
    """Priority 7: expected_order_version is mandatory on the two protected writes."""
    supplied = require(body, "expected_order_version")
    if isinstance(supplied, bool) or not isinstance(supplied, int):
        if isinstance(supplied, str) and supplied.lstrip("-").isdigit():
            supplied = int(supplied)
        else:
            raise invalid_request("Field 'expected_order_version' must be an integer.")
    if supplied != order.get("version"):
        raise ApiError("ERR_STALE_VERSION",
                       "expected_order_version %s does not match the order's version %s."
                       % (supplied, order.get("version")), 412)


# -------------------------------------------------------- stock / counters

def _stock_row(store, item_id, dc_id):
    for row in store.stock_rows.values():
        if row.get("item_id") == item_id and row.get("dc_id") == dc_id:
            return row
    return None


def refresh_line_count(order, store):
    """order_line_count_guard."""
    order["line_count"] = len(_clinical_order_lines(store, order["id"]))
    return order["line_count"]


def _account_open_claims(store, account):
    if account is None:
        return
    count = 0
    for claim in store.damage_claims.values():
        if claim.get("claim_status") in ("RESOLVED", "REJECTED", "VOIDED"):
            continue
        order = store.orders.get(claim.get("order_id"))
        if order is not None and order.get("account_id") == account["id"]:
            count += 1
    account["open_claim_count"] = count


def _order_open_claims(store, order):
    count = 0
    for claim in store.damage_claims.values():
        if claim.get("order_id") != order["id"]:
            continue
        if claim.get("claim_status") in ("RESOLVED", "REJECTED", "VOIDED"):
            continue
        count += 1
    order["damage_claim_count"] = count
    return count


def _item_suspended(item):
    return item.get("catalog_status") == "SUSPENDED"


def recompute_dc_posture(store, dc):
    if dc is None:
        return
    from svc_dc import refresh_posture
    refresh_posture(dc, store)


# ------------------------------------------------- delivery-window helpers

def _parse_hhmmss(value):
    try:
        hh, mm, ss = (int(part) for part in str(value).split(":"))
    except (ValueError, TypeError):
        return None
    return hh, mm, ss


def _cutoff_instant(local_dt, local_cutoff_time):
    parts = _parse_hhmmss(local_cutoff_time)
    if parts is None:
        return None
    hh, mm, ss = parts
    return local_dt.replace(hour=hh, minute=mm, second=ss, microsecond=0)


def _promise_instant(value):
    """A bare date is anchored at 23:59:59 of that local day."""
    if len(value.strip()) == 10:
        try:
            base = parse_optional_datetime(value + "T23:59:59", "promised_delivery_by")
        except Exception:
            return None
        return base
    return parse_optional_datetime(value, "promised_delivery_by")


def candidate_centers(store, lines, account):
    """The dc_allocation_selector candidate set, using requested quantity."""
    selected, candidates = select_dc(None, lines, account, store)
    return candidates


def check_delivery_window(store, lines, account, promise_dt, candidates=None):
    """Priority 12: ERR_CUTOFF_WINDOW_PASSED.

    The committed deadline must not fall on or before a candidate centre's
    local cutoff, judged by local weekday first and local wall-clock time
    second.
    """
    if promise_dt is None:
        return
    if candidates is None:
        candidates = candidate_centers(store, lines, account)
    from db import local_datetime
    for dc in candidates:
        offset = dc.get("utc_offset_minutes", 0) or 0
        local = local_datetime(store.current_utc, offset)
        weekday = local.weekday()
        cutoff = _cutoff_instant(local, dc.get("local_cutoff_time", "00:00:00"))
        if cutoff is None:
            continue
        if weekday >= 5 and cutoff.weekday() < 5:
            cutoff += timedelta(days=1)
        if promise_dt <= cutoff:
            raise ApiError(
                "ERR_CUTOFF_WINDOW_PASSED",
                "The committed delivery deadline falls on or before the local cutoff of "
                "distribution center '%s'." % dc.get("code"), 422)


def _commit_minutes(dc, store):
    from db import local_datetime
    offset = dc.get("utc_offset_minutes", 0) or 0
    local = local_datetime(store.current_utc, offset)
    cutoff = _cutoff_instant(local, dc.get("local_cutoff_time", "00:00:00"))
    if cutoff is None:
        return 0
    minutes = int((cutoff - local).total_seconds()) // 60
    return minutes if minutes > 0 else 0


# ----------------------------------------------------------- order create

def create_order(store, user_id, body):
    account_id = require_str(body, "account_id")
    account = get_account(store, account_id)

    # Priority 4 - ownership.
    if account_id != user_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP",
                       "The calling account does not own account '%s'." % account_id, 403)

    raw_lines = require(body, "lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise invalid_request("Field 'lines' must be a non-empty array.")

    items = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise invalid_request("Every entry of 'lines' must be an object.")
        item_id = require_str(entry, "item_id")
        item = store.catalog_items.get(item_id)
        if item is None:
            raise not_found("ERR_ITEM_NOT_FOUND", "No catalog item exists for id '%s'." % item_id)
        quantity = require_int(entry, "quantity", 1)
        items.append((item, quantity))

    # Priority 10 - curation gate.
    for item, _qty in items:
        if item.get("curation_review_state") != "APPROVED":
            raise ApiError("ERR_CURATION_NOT_APPROVED",
                           "Item '%s' has not been approved by curation." % item.get("sku"), 409)

    promise_raw = body.get("promised_delivery_by")
    promise_dt = _promise_instant(promise_raw) if isinstance(promise_raw, str) else None
    probes = [{"item_id": item["id"], "quantity": qty} for item, qty in items]

    # Priority 12 - delivery window.
    check_delivery_window(store, probes, account, promise_dt)

    order = {
        "account_id": account_id,
        "order_status": "DRAFT",
        "fulfillment_status": "AWAITING_RELEASE",
        "line_count": 0,
        "total_small_line_fee_cents": 0,
        "order_total_cents": 0,
        "allocated_dc_id": None,
        "same_day_committed": False,
        "commit_minutes_before_cutoff": 0,
        "damage_claim_count": 0,
        "freight_charge_cents": 0,
        "promised_delivery_by": promise_dt,
    }
    store.stamp(order)
    store.orders[order["id"]] = order

    for item, quantity in items:
        line = {
            "order_id": order["id"],
            "item_id": item["id"],
            "quantity": quantity,
            "allocated_dc_id": None,
            "allocated_units": 0,
            "is_small_line": quantity <= (item.get("curation_bundle_size", 0) or 0),
            # SCAFFOLD CatalogOrderLine: line_subtotal_cents = allocated_units *
            # item.unit_price_cents, so it is 0 until the line is allocated and it
            # returns to 0 when a cancel resets allocated_units.
            "line_subtotal_cents": 0,
            "allocated_small_line_fee_cents": 0,
            "line_total_cents": 0,
            "line_status": "PENDING",
            "returned_units": 0,
            "restocked_units": 0,
            "damaged_units": 0,
            "return_friction_units": 0,
        }
        store.stamp(line)
        store.order_lines[line["id"]] = line

    refresh_line_count(order, store)
    # "Creating an order runs the pricing calculations of section 3.5 immediately."
    order_total_cents_factor_first(order, lines_of(store, order["id"]), store)
    return order


# ------------------------------------------------------------- release etc.

def release_order(store, order):
    _not_terminal(order, ("CANCELLED", "RETURNED"),
                  "Order '%s' is already in a terminal state." % order["id"])
    _require_state(order.get("order_status") == "DRAFT",
                   "Order '%s' is not in DRAFT and cannot be released." % order["id"])
    for line in lines_of(store, order["id"]):
        item = store.catalog_items.get(line.get("item_id")) or {}
        if item.get("curation_review_state") != "APPROVED":
            raise ApiError("ERR_CURATION_NOT_APPROVED",
                           "Item '%s' has not been approved by curation." % item.get("sku"), 409)
    order["order_status"] = "RELEASED"
    store.touch(order)
    return order


def allocate_order(store, order, body):
    _not_terminal(order, ("CANCELLED", "RETURNED"),
                  "Order '%s' is already in a terminal state." % order["id"])
    _require_state(order.get("order_status") == "RELEASED"
                   and order.get("fulfillment_status") == "AWAITING_RELEASE",
                   "Order '%s' is not in RELEASED / AWAITING_RELEASE and cannot be allocated."
                   % order["id"])
    _stale_version(order, body)

    from db import local_datetime
    lines = lines_of(store, order["id"])
    account = get_account(store, order["account_id"])

    # Priority 12 - delivery window is re-checked before the selector runs.
    check_delivery_window(store, lines, account, order.get("promised_delivery_by"))

    # Priority 11 - the selector owns the empty-candidate rejection.
    selected, candidates = select_dc(order, lines, account, store)
    if selected is None:
        raise ApiError("ERR_NO_ELIGIBLE_DC",
                       "No distribution center satisfies the allocation selector for order '%s'."
                       % order["id"], 409)

    total_units = sum(line.get("quantity", 0) for line in lines)
    capacity = selected.get("inbound_capacity_units", 0) or 0
    reserved = selected.get("inbound_reserved_units", 0) or 0

    # Priority 15 - inbound capacity.
    if reserved + total_units > capacity:
        raise ApiError("ERR_INBOUND_CAPACITY_EXCEEDED",
                       "Allocation would push distribution center '%s' past its inbound capacity."
                       % selected.get("code"), 409)

    any_ahead = False
    for dc in candidates:
        if not dc.get("cutoff_passed"):
            any_ahead = True
            break

    order["allocated_dc_id"] = selected["id"]
    order["same_day_committed"] = any_ahead
    order["commit_minutes_before_cutoff"] = _commit_minutes(selected, store)
    # PRD 3.4: allocation moves the order to RELEASED / ALLOCATED.
    order["fulfillment_status"] = "ALLOCATED"

    for line in lines:
        line["allocated_dc_id"] = selected["id"]
        line["allocated_units"] = line.get("quantity", 0)
        line["line_status"] = "ALLOCATED"
        line["line_subtotal_cents"] = derived_line_subtotal(line, store)
        store.touch(line)

    for line in lines:
        row = _stock_row(store, line.get("item_id"), selected["id"])
        if row is not None:
            row["reserved_units"] = (row.get("reserved_units", 0) or 0) + line.get("allocated_units", 0)
            row["available_units"] = (row.get("on_hand_units", 0) or 0) - (row.get("reserved_units", 0) or 0)
            store.touch(row)

    selected["inbound_reserved_units"] = reserved + total_units
    recompute_dc_posture(store, selected)
    store.touch(selected)

    small_line_fee_total_and_allocate(order, lines, store)   # pricing pass 1
    # PRD 3.4: allocation runs the order-total calculation too. Before the cutoff is
    # certified that is the own-precision variant, so the order total is the
    # discounted material base plus the flat 3% per-line fee sum.
    order_total_cents_factor_first(order, lines, store)
    refresh_line_count(order, store)                          # line-count guard
    store.touch(order)
    return order


def cancel_order(store, order):
    _not_terminal(order, ("CANCELLED", "RETURNED"),
                  "Order '%s' is already in a terminal state." % order["id"])

    status = order.get("order_status")
    fulfillment = order.get("fulfillment_status")

    if status == "DRAFT":
        pass
    elif status == "RELEASED" and fulfillment == "AWAITING_RELEASE":
        pass
    elif status == "RELEASED" and fulfillment == "ALLOCATED":
        lines = lines_of(store, order["id"])
        released_by_dc = {}
        for line in lines:
            if line.get("line_status") != "ALLOCATED":
                continue
            dc_id = line.get("allocated_dc_id")
            units = line.get("allocated_units", 0) or 0
            row = _stock_row(store, line.get("item_id"), dc_id)
            if row is not None:
                row["reserved_units"] = max(0, (row.get("reserved_units", 0) or 0) - units)
                row["available_units"] = (row.get("on_hand_units", 0) or 0) - row["reserved_units"]
                store.touch(row)
            released_by_dc[dc_id] = released_by_dc.get(dc_id, 0) + units
        for dc_id, units in released_by_dc.items():
            dc = store.distribution_centers.get(dc_id)
            if dc is not None:
                dc["inbound_reserved_units"] = max(0, (dc.get("inbound_reserved_units", 0) or 0) - units)
                recompute_dc_posture(store, dc)
                store.touch(dc)
        for line in lines:
            line["line_status"] = "PENDING"
            line["allocated_units"] = 0
            line["allocated_dc_id"] = None
            line["line_subtotal_cents"] = 0
            line["line_total_cents"] = 0
            line["allocated_small_line_fee_cents"] = 0
            store.touch(line)
        order["fulfillment_status"] = "AWAITING_RELEASE"
    else:
        _require_state(False, "Order '%s' is not in a state that permits cancellation." % order["id"])

    order["order_status"] = "CANCELLED"
    small_line_fee_total_and_allocate(order, lines_of(store, order["id"]), store)
    # The cancel reset every line's allocated_units to 0, so the material subtotals
    # fall to 0 and the order-total calculation must be re-run rather than left
    # standing at its pre-cancel figure.
    order_total_cents_factor_first(order, lines_of(store, order["id"]), store)
    store.touch(order)
    return order


# ------------------------------------------------------------------ picks

def start_pick(store, order, line, body):
    _not_terminal(order, ("CANCELLED", "RETURNED"),
                  "Order '%s' is already in a terminal state." % order["id"])

    task = _task_for_line(store, line["id"])
    if task is not None and task.get("pick_status") == "SHORT_CLOSED":
        # Re-pick after a damaged pick was written off.
        claim = _open_claim_for_line(store, line["id"])
        _require_state(order.get("fulfillment_status") == "ALLOCATED"
                       and claim is not None and claim.get("claim_status") == "OPEN",
                       "Pick task '%s' cannot be reopened in the order's current state." % task["id"])
        requested_units = require_int(body, "requested_units", 1)
        dc = store.distribution_centers.get(line.get("allocated_dc_id"))
        if dc is not None and dc.get("operations_posture") == "LOCKDOWN":
            raise ApiError("ERR_DC_LOCKDOWN",
                           "Distribution center '%s' is in LOCKDOWN." % dc.get("code"), 409)
        task["requested_units"] = requested_units
        task["picked_units"] = 0
        task["shortage_units"] = 0
        task["pick_status"] = "PICKING"
        line["line_status"] = "ALLOCATED"
        store.touch(line)
        store.touch(task)
        store.touch(order)
        return task

    _require_state(order.get("fulfillment_status") == "ALLOCATED",
                   "Order '%s' is not ALLOCATED and cannot be picked." % order["id"])
    _require_state(task is None or task.get("pick_status") == "QUEUED",
                   "Pick task for line '%s' is not QUEUED." % line["id"])

    dc = store.distribution_centers.get(line.get("allocated_dc_id"))
    if dc is not None and dc.get("operations_posture") == "LOCKDOWN":
        raise ApiError("ERR_DC_LOCKDOWN",
                       "Distribution center '%s' is in LOCKDOWN." % dc.get("code"), 409)

    requested_units = require_int(body, "requested_units", 1)
    _require_state(line.get("line_status") == "ALLOCATED",
                   "Line '%s' is not ALLOCATED and cannot be picked." % line["id"])

    task = {
        "order_id": order["id"],
        "line_id": line["id"],
        "dc_id": line.get("allocated_dc_id"),
        "requested_units": requested_units,
        "picked_units": 0,
        "shortage_units": 0,
        "shortage_disposition": "NONE",
        "pick_status": "PICKING",
    }
    store.stamp(task)
    store.pick_tasks[task["id"]] = task
    return task


def _task_for_line(store, line_id):
    rows = [t for t in store.pick_tasks.values() if t.get("line_id") == line_id]
    rows.sort(key=created_key)
    return rows[0] if rows else None


def _open_claim_for_line(store, line_id):
    rows = [c for c in store.damage_claims.values()
            if c.get("line_id") == line_id and c.get("claim_status") == "OPEN"]
    rows.sort(key=created_key)
    return rows[0] if rows else None


def complete_pick(store, order, line, body):
    _not_terminal(order, ("CANCELLED", "RETURNED"),
                  "Order '%s' is already in a terminal state." % order["id"])

    task = _task_for_line(store, line["id"])
    _require_state(task is not None and task.get("pick_status") == "PICKING",
                   "Pick task for line '%s' is not PICKING." % line["id"])

    actual_units = require_int(body, "actual_units", 0)
    requested = task.get("requested_units", 0)

    task["picked_units"] = actual_units
    task["shortage_units"] = max(0, requested - actual_units)
    task["pick_status"] = "PICKED" if task["shortage_units"] == 0 else "SHORT_CLOSED"
    store.touch(task)

    dc_id = line.get("allocated_dc_id")
    row = _stock_row(store, line.get("item_id"), dc_id)
    if row is not None:
        row["on_hand_units"] = max(0, (row.get("on_hand_units", 0) or 0) - actual_units)
        # The units just pulled have physically left the shelf, so the reservation
        # that was holding them is consumed with them — otherwise they would be
        # counted as reserved after they are gone and available_units would read
        # short by the picked quantity. A shortfall's unfilled remainder stays
        # reserved, because the line still holds those units.
        row["reserved_units"] = max(0, (row.get("reserved_units", 0) or 0) - actual_units)
        row["available_units"] = row["on_hand_units"] - row["reserved_units"]
        store.touch(row)

    item = store.catalog_items.get(line.get("item_id")) or {}

    if task["shortage_units"] == 0:
        line["line_status"] = "PICKED"
    else:
        line["line_status"] = "SHORT"
        line["allocated_small_line_fee_cents"] = 0
    store.touch(line)

    if task["shortage_units"] > 0:
        _apply_shortage_disposition(store, order, line, task, item)
        if item.get("long_tail") is not True:
            _open_damage_claim(store, order, line, task["shortage_units"], item, "PICK_SHORTAGE")

    if all(l.get("line_status") in ("PICKED", "SHORT") for l in lines_of(store, order["id"])):
        order["fulfillment_status"] = "PICKED"
        # The STAGED shipment is minted when the order first reaches PICKED, which is
        # the point at which both cutoff-certification preconditions (fulfillment_status
        # PICKED, shipment STAGED) become satisfiable together.
        if shipment_of(store, order["id"]) is None:
            shipment = {
                "order_id": order["id"],
                "dc_id": order.get("allocated_dc_id"),
                "shipment_status": "STAGED",
                "cutoff_sequence_index": None,
                "service_level": "GROUND",
                "billable_weight_kg": None,
                "freight_rate_cents": None,
                "freight_surcharge_cents": None,
                "freight_charge_cents": None,
                "promised_delivery_by": order.get("promised_delivery_by"),
            }
            store.stamp(shipment)
            store.shipments[shipment["id"]] = shipment

    # Both pricing passes are recomputed on every pick completion (PRD 3.6).
    small_line_fee_total_and_allocate(order, lines_of(store, order["id"]), store)
    shipment = shipment_of(store, order["id"])
    if shipment is not None and shipment.get("shipment_status") == "CUTOFF_CONFIRMED":
        order_total_two_variant_tiered(order, lines_of(store, order["id"]), store)
    else:
        order_total_cents_factor_first(order, lines_of(store, order["id"]), store)

    store.touch(order)
    if dc_id:
        dc = store.distribution_centers.get(dc_id)
        if dc is not None:
            store.touch(dc)
    return task


def _apply_shortage_disposition(store, order, line, task, item):
    if item.get("long_tail") is not True:
        task["shortage_disposition"] = "NONE"
        store.touch(task)
        return
    for other in lines_of(store, order["id"]):
        if other["id"] == line["id"]:
            continue
        if (other.get("shortage_units", 0) or 0) <= 0:
            continue
        other_task = _task_for_line(store, other["id"])
        if other_task is None or (other_task.get("shortage_units", 0) or 0) <= 0:
            continue
        other_item = store.catalog_items.get(other.get("item_id")) or {}
        if other_item.get("long_tail") is not True:
            task["shortage_disposition"] = "NONE"
            store.touch(task)
            return
    task["shortage_disposition"] = "MADE_TO_ORDER"
    store.touch(task)


def _open_damage_claim(store, order, line, claim_units, item, disposition):
    claim = {
        "order_id": order["id"],
        "line_id": line["id"],
        "claim_units": claim_units,
        "damage_value_cents": damage_value_cents(claim_units, item.get("unit_price_cents", 0) or 0),
        "claim_status": "OPEN",
        "disposition": disposition,
    }
    store.stamp(claim)
    store.damage_claims[claim["id"]] = claim
    order["damage_claim_count"] = _order_open_claims(store, order)
    account = store.accounts.get(order.get("account_id"))
    _account_open_claims(store, account)
    return claim


# ------------------------------------------------------- cutoff / freight

def confirm_cutoff(store, order, body):
    _not_terminal(order, ("CANCELLED", "RETURNED"),
                  "Order '%s' is already in a terminal state." % order["id"])
    _require_state(order.get("fulfillment_status") == "PICKED",
                   "Order '%s' is not PICKED and cannot have its cutoff confirmed." % order["id"])

    shipment = shipment_of(store, order["id"])
    _require_state(shipment is not None and shipment.get("shipment_status") == "STAGED",
                   "The order's shipment is not STAGED and cannot be certified.")

    _stale_version(order, body)

    service_level = require_str(body, "service_level")
    if service_level not in SERVICE_LEVELS:
        raise invalid_request("Field 'service_level' must be one of %s." % " | ".join(SERVICE_LEVELS))

    account = get_account(store, order["account_id"])
    allocated_dc = store.distribution_centers.get(order.get("allocated_dc_id"))

    # Priority 11 - candidate membership.
    lines = lines_of(store, order["id"])
    candidates = candidate_centers(store, lines, account)
    if allocated_dc is None or allocated_dc["id"] not in {dc["id"] for dc in candidates}:
        raise ApiError("ERR_DC_NOT_CANDIDATE",
                       "The order's allocated distribution center is not a candidate.", 409)

    promise_raw = body.get("promised_delivery_by")
    promise_dt = _promise_instant(promise_raw) if isinstance(promise_raw, str) else None

    # Priority 13 - promise date.
    if promise_dt is not None:
        from db import local_datetime
        local = local_datetime(store.current_utc, allocated_dc.get("utc_offset_minutes", 0) or 0)
        if promise_dt < local:
            raise ApiError("ERR_PROMISE_DATE_IN_PAST",
                           "promised_delivery_by lies in the past relative to the centre's "
                           "local clock.", 422)
        shipment["promised_delivery_by"] = promise_dt

    shipment["shipment_status"] = "CUTOFF_CONFIRMED"
    shipment["service_level"] = service_level
    shipment["cutoff_sequence_index"] = allocated_dc.get("cutoff_sequence_index", 0) or 0
    order["fulfillment_status"] = "SHIPPED"

    freight_charge_two_variant(shipment, order, lines, account, allocated_dc, store,
                               variant="cutoff_certified")
    # Re-price the order through the handling-pool variant of the order total.
    order_total_two_variant_tiered(order, lines, store)

    store.touch(shipment)
    store.touch(order)
    return shipment


def order_total_two_variant_tiered(order, lines, store):
    return order_total_two_variant(order, lines, store, fee_tiered=True)


def dispatch_shipment(store, shipment):
    status = shipment.get("shipment_status")
    if status == "DISPATCHED":
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "Shipment '%s' has already been dispatched." % shipment["id"], 409)
    _require_state(status == "CUTOFF_CONFIRMED",
                   "Shipment '%s' is not CUTOFF_CONFIRMED and cannot be dispatched." % shipment["id"])
    shipment["shipment_status"] = "DISPATCHED"
    store.touch(shipment)
    return shipment


# ----------------------------------------------------------------- returns

def create_return(store, user_id, role, body):
    order_id = require_str(body, "order_id")
    order = get_order(store, order_id)

    # Priority 4 - ownership guards return-authorization creation for accounts.
    if role == "CustomerAccount" and order.get("account_id") != user_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP",
                       "The calling account does not own order '%s'." % order_id, 403)

    raw_lines = require(body, "lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise invalid_request("Field 'lines' must be a non-empty array.")

    claims = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise invalid_request("Every entry of 'lines' must be an object.")
        line_id = require_str(entry, "line_id")
        line = get_line(store, order, line_id)
        units = require_int(entry, "requested_return_units", 0)
        claims.append((line, units))

    authorization = {
        "order_id": order["id"],
        "dc_id": order.get("allocated_dc_id"),
        "return_status": "DRAFT",
        "restock_units": 0,
        "damaged_units": 0,
        "removed_manufacturer_part_numbers": {},
    }
    store.stamp(authorization)
    store.return_authorizations[authorization["id"]] = authorization

    for line, units in claims:
        record = {
            "return_id": authorization["id"],
            "line_id": line["id"],
            "requested_return_units": units,
            "restock_units": 0,
            "damaged_units": 0,
        }
        store.stamp(record)
        store.return_lines[record["id"]] = record
    return authorization


def return_lines_of(store, return_id):
    rows = [r for r in store.return_lines.values() if r.get("return_id") == return_id]
    return sorted(rows, key=created_key)


def approve_return(store, authorization):
    status = authorization.get("return_status")
    if status in ("RECEIVED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "Return authorization '%s' is already terminal." % authorization["id"], 409)
    _require_state(status in ("APPROVED", "DRAFT"),
                   "Return authorization '%s' is not in a state that permits approval."
                   % authorization["id"])

    lines = return_lines_of(store, authorization["id"])
    for record in lines:
        line = store.order_lines.get(record.get("line_id"))
        delivered = 0 if line is None else max(line.get("quantity", 0),
                                              _max_returned_units(store, line["id"]))
        if (record.get("requested_return_units", 0) or 0) > delivered:
            raise ApiError("ERR_INVALID_STATE",
                           "Return line '%s' claims more units than were delivered." % record["id"], 409)

    lines = restock_cap_allocation(lines, store)
    authorization["restock_units"] = sum(r.get("restock_units", 0) or 0 for r in lines)
    authorization["damaged_units"] = sum(r.get("damaged_units", 0) or 0 for r in lines)
    authorization["return_status"] = "APPROVED"
    for record in lines:
        store.touch(record)
    store.touch(authorization)
    return authorization


def _max_returned_units(store, line_id):
    total = 0
    for record in store.return_lines.values():
        if record.get("line_id") != line_id:
            continue
        authorization = store.return_authorizations.get(record.get("return_id")) or {}
        if authorization.get("return_status") == "CANCELLED":
            continue
        total += record.get("requested_return_units", 0) or 0
    return total


def cancel_return(store, authorization):
    status = authorization.get("return_status")
    if status in ("RECEIVED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "Return authorization '%s' is already terminal." % authorization["id"], 409)
    _require_state(status == "DRAFT",
                   "Return authorization '%s' is not DRAFT and cannot be cancelled."
                   % authorization["id"])
    authorization["return_status"] = "CANCELLED"
    store.touch(authorization)
    return authorization


def receive_return(store, authorization, body):
    status = authorization.get("return_status")
    if status in ("RECEIVED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "Return authorization '%s' is already terminal." % authorization["id"], 409)
    _require_state(status == "APPROVED",
                   "Return authorization '%s' is not APPROVED and cannot be received."
                   % authorization["id"])

    order = store.orders.get(authorization.get("order_id"))
    lines = return_lines_of(store, authorization["id"])

    # Priority 14 - every claimed unit must carry a removed part number.
    _check_part_numbers(authorization, lines, body)

    account = store.accounts.get(order.get("account_id")) if order else None
    dc = store.distribution_centers.get(authorization.get("dc_id"))

    damaged_lines = []
    # Stage B walks the same ratio waterfall the approval used (PRD section 3.9):
    # 0.80 of the authorized units on the highest-subtotal line, stepping down by
    # 0.30 per line and floored at the restock cap — NOT a flat min(units, cap).
    restock_cap_allocation(lines, store)
    for record in lines:
        line = store.order_lines.get(record.get("line_id"))
        if line is None:
            continue
        authorized = record.get("requested_return_units", 0) or 0
        item = store.catalog_items.get(line.get("item_id")) or {}

        # Stage A - line return record.
        line["returned_units"] = (line.get("returned_units", 0) or 0) + authorized
        line["line_status"] = "RETURNED"

        # Stage B - restock assessment (ratio waterfall written just above).
        restocked = record.get("restock_units", 0) or 0
        line["restocked_units"] = restocked
        line["damaged_units"] = (line.get("damaged_units", 0) or 0) + (authorized - restocked)
        line["return_friction_units"] = (authorized - restocked)
        store.touch(record)

        # Stage C - stock restore (damaged material never re-enters availability).
        row = _stock_row(store, line.get("item_id"), authorization.get("dc_id"))
        if row is not None:
            row["on_hand_units"] = (row.get("on_hand_units", 0) or 0) + restocked
            row["available_units"] = row["on_hand_units"] - (row.get("reserved_units", 0) or 0)
            store.touch(row)
        if dc is not None and dc.get("operations_posture") == "LOCKDOWN":
            recompute_dc_posture(store, dc)

        # Stage D - damage path.
        if authorized - restocked > 0:
            damaged_lines.append(line)
            _open_damage_claim(store, order, line, authorized - restocked, item, "PENDING")

        # Stage E - supplier breach for long-tail material.
        if item.get("long_tail") is True:
            supplier = _supplier_for_item(store, item["id"], authorization.get("dc_id"))
            if supplier is not None:
                supplier["commitment_breach_count"] = (supplier.get("commitment_breach_count", 0) or 0) + 1
                supplier["performance_rating_units"] = 100 - 10 * supplier["commitment_breach_count"]
                store.touch(supplier)

        # Stage F - catalogue suspension.
        if damaged_unit_ratio_breach(line, store):
            item["catalog_status"] = "SUSPENDED"
            store.touch(item)

        store.touch(line)

    # Stage G - fresh authorization: sibling APPROVED returns become CANCELLED.
    for other in store.return_authorizations.values():
        if other["id"] == authorization["id"]:
            continue
        if other.get("order_id") != authorization.get("order_id"):
            continue
        if other.get("return_status") == "APPROVED":
            other["return_status"] = "CANCELLED"
            store.touch(other)

    authorization["return_status"] = "RECEIVED"
    store.touch(authorization)

    if order is not None:
        _order_open_claims(store, order)
        order["fulfillment_status"] = "RETURNED"
        store.touch(order)
    _account_open_claims(store, account)
    return authorization


def _check_part_numbers(authorization, lines, body):
    provided = body.get("removed_manufacturer_part_numbers")
    stored = authorization.get("removed_manufacturer_part_numbers") or {}
    if isinstance(provided, dict):
        merged = dict(stored)
        merged.update({str(k): v for k, v in provided.items()})
        authorization["removed_manufacturer_part_numbers"] = merged
        stored = merged
    elif isinstance(provided, list):
        merged = dict(stored)
        for entry in provided:
            if isinstance(entry, dict) and "line_id" in entry:
                merged[str(entry["line_id"])] = entry.get("removed_manufacturer_part_number")
        authorization["removed_manufacturer_part_numbers"] = merged
        stored = merged

    missing = []
    for record in lines:
        if (record.get("requested_return_units", 0) or 0) <= 0:
            continue
        value = stored.get(str(record.get("line_id")))
        if not value:
            missing.append(record.get("line_id"))
    if missing:
        raise ApiError("ERR_RETURN_PART_NUMBER_REQUIRED",
                       "Every claimed return unit must carry a removed_manufacturer_part_number.",
                       422)


def _supplier_for_item(store, item_id, dc_id=None):
    """The supplier behind a long-tail item.

    Preferred link is an availability report filed against the item; failing that,
    the supplier contracted to stock the receiving center, which is the only other
    association a Supplier carries (its `home_dc_id` names the center its long-tail
    commitment stocks).
    """
    reports = [r for r in store.supplier_availability_reports.values()
               if r.get("item_id") == item_id]
    reports.sort(key=created_key)
    if reports:
        return store.suppliers.get(reports[0].get("supplier_id"))
    if dc_id is not None:
        candidates = [s for s in store.suppliers.values()
                      if s.get("home_dc_id") == dc_id
                      and s.get("long_tail_authorized") is True]
        candidates.sort(key=created_key)
        if candidates:
            return candidates[0]
    return None


# ----------------------------------------------------------- damage claims

def resume_claim(store, claim):
    status = claim.get("claim_status")
    if status in ("RESOLVED", "REJECTED", "VOIDED"):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "Damage claim '%s' is already terminal." % claim["id"], 409)
    _require_state(status == "OPEN",
                   "Damage claim '%s' is not OPEN and cannot be resumed." % claim["id"])

    line = store.order_lines.get(claim.get("line_id"))
    item = store.catalog_items.get(line.get("item_id")) if line else None

    # Priority 9 - resumed item suspension.
    if item is not None and item.get("catalog_status") == "SUSPENDED":
        raise ApiError("ERR_ITEM_SUSPENDED",
                       "Item '%s' is suspended; fulfillment cannot be resumed." % item.get("sku"), 409)

    claim["claim_status"] = "RESUMED"
    claim["disposition"] = "PENDING"
    order = store.orders.get(claim.get("order_id"))
    if order is not None:
        order["fulfillment_status"] = "ALLOCATED"
        store.touch(order)
    if line is not None:
        line["line_status"] = "ALLOCATED"
        store.touch(line)
    store.touch(claim)
    return claim


def _close_claim(store, claim, status, disposition):
    current = claim.get("claim_status")
    if current in ("RESOLVED", "REJECTED", "VOIDED"):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "Damage claim '%s' is already terminal." % claim["id"], 409)
    _require_state(current == "OPEN" if status == "REJECTED" else current == "RESUMED",
                   "Damage claim '%s' is not in a state that permits this operation." % claim["id"])
    claim["claim_status"] = status
    if disposition is not None:
        claim["disposition"] = disposition
    store.touch(claim)
    order = store.orders.get(claim.get("order_id"))
    account = store.accounts.get(order.get("account_id")) if order else None
    if order is not None:
        _order_open_claims(store, order)
    _account_open_claims(store, account)
    return claim


def resolve_claim(store, claim):
    return _close_claim(store, claim, "RESOLVED", "ZERO_CHARGE_RESHIP")


def reject_claim(store, claim):
    return _close_claim(store, claim, "REJECTED", "REPLACE_FROM_STOCK")


def void_claim(store, claim):
    return _close_claim(store, claim, "VOIDED", None)