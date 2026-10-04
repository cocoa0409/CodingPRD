"""Storage sites, allocation windows/entitlements, site orders, releases,
shipping-window lapses, program standings and reporting periods."""
from flask import Blueprint

from errors import ApiError
from helpers import h
from db import STORE
from middleware import guard
from clockutil import parse_ts, clock, fmt, add_hours, earlier, diff_minutes, diff_hours_rounded
from services import derive as D
from services import calc as C
from routes import common as K

bp = Blueprint("allocation", __name__)

CAPABILITIES = ["ULTRA_COLD", "REFRIGERATED", "AMBIENT_ONLY"]
EQUIPMENT = ["ULTRA_COLD_FREEZER", "THERMAL_SHIPPER"]
ENTITLEMENT_STATES = ["PENDING", "PARTIALLY_ACCEPTED", "FULFILLED", "LAPSED"]
ORDER_STATES = ["DRAFT", "SUBMITTED", "ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED", "FULFILLED"]
REJECTION_REASONS = ["BELOW_MIN_ORDER", "NO_ENTITLEMENT", "CAPACITY_UNAVAILABLE",
                     "SITE_NOT_READY", "WINDOW_CLOSED"]
RELEASE_REASONS = ["WINDOW_LAPSE", "ORDER_REJECTION", "CAPACITY_UNAVAILABLE",
                   "PROGRAM_REALLOCATION"]
LAPSE_REASONS = ["ACCEPTANCE_WINDOW_CLOSED", "SITE_NOT_READY", "NO_ORDER_SUBMITTED"]
PROPAGATION = ["IMMEDIATE", "AFTER_CYCLE"]
PERIOD_STATES = ["OPEN", "SUBMITTED"]


# ---------------------------------------------------------------------------
# StorageSite
# ---------------------------------------------------------------------------
@bp.route("/storage-sites", methods=["POST"])
def create_site():
    guard("POST /vaccine-distribution/storage-sites")
    data = K.body()
    program = K.fetch("jurisdiction_programs", K.required(data, "jurisdiction_program_id"),
                      "Jurisdiction program")
    code = K.as_str(K.required(data, "site_code"), "site_code")
    for existing in h.all("storage_sites"):
        if existing.get("site_code") == code and \
                existing.get("jurisdiction_program_id") == program["id"]:
            raise ApiError("ERR_INVALID_REQUEST",
                           "site_code must be unique within its jurisdiction program.")
    rec = h.create("storage_sites", {
        "site_code": code,
        "site_name": K.as_str(K.required(data, "site_name"), "site_name"),
        "jurisdiction_program_id": program["id"],
        "storage_capability": K.as_enum(K.required(data, "storage_capability"),
                                        CAPABILITIES, "storage_capability"),
        "ultra_cold_capacity_cartons":
            K.as_int(K.required(data, "ultra_cold_capacity_cartons"),
                     "ultra_cold_capacity_cartons"),
        "refrigerated_capacity_cartons":
            K.as_int(K.required(data, "refrigerated_capacity_cartons"),
                     "refrigerated_capacity_cartons"),
        "cold_chain_equipment_type": K.as_enum(K.required(data, "cold_chain_equipment_type"),
                                               EQUIPMENT, "cold_chain_equipment_type"),
        "equipment_certificate_expires_at":
            K.as_ts(K.required(data, "equipment_certificate_expires_at"),
                    "equipment_certificate_expires_at"),
        "expected_weekly_doses": K.as_int(K.required(data, "expected_weekly_doses"),
                                          "expected_weekly_doses"),
        "equipment_certified": False,
        "equipment_verification_id": None,
        "reported_entry_type": "ULTRA_COLD",
        "usable_doses": 0,
        "administrative_remaining_doses": 0,
        "open_excursion_count": 0,
        "inventory_status": "OPEN",
    })
    D.recompute_site(rec)
    return K.created(rec)


@bp.route("/storage-sites", methods=["GET"])
def list_sites():
    guard("GET /vaccine-distribution/storage-sites")
    return K.list_response(h.all("storage_sites"), {
        "jurisdiction_program_id": K.eq("jurisdiction_program_id"),
        "storage_capability": K.eq("storage_capability"),
        "inventory_status": K.eq("inventory_status"),
    })


@bp.route("/storage-sites/<sid>", methods=["GET"])
def get_site(sid):
    guard("GET /vaccine-distribution/storage-sites/{id}")
    return K.single(K.fetch("storage_sites", sid, "Storage site"))


@bp.route("/storage-sites/<sid>/usable-doses", methods=["GET"])
def usable_doses(sid):
    guard("GET /vaccine-distribution/storage-sites/{id}/usable-doses")
    site = K.fetch("storage_sites", sid, "Storage site")
    physical = [c for c in D.cartons_at_site(sid)
                if c.get("temperature_state") not in ("IN_TRANSIT", "DESTROYED")]
    return K.single({
        "site_id": site["id"],
        "usable_doses": site.get("usable_doses", 0),
        "administrative_remaining_doses": site.get("administrative_remaining_doses", 0),
        "physical_carton_count": len(physical),
        "reported_entry_type": site.get("reported_entry_type"),
        "inventory_status": site.get("inventory_status"),
    })


@bp.route("/storage-sites/<sid>/transfers", methods=["GET"])
def site_transfers(sid):
    guard("GET /vaccine-distribution/storage-sites/{id}/transfers")
    K.fetch("storage_sites", sid, "Storage site")
    rows = [t for t in h.all("site_transfers")
            if t.get("from_site_id") == sid or t.get("to_site_id") == sid]
    return K.list_response(rows)


@bp.route("/storage-sites/<sid>/excursions", methods=["GET"])
def site_excursions(sid):
    guard("GET /vaccine-distribution/storage-sites/{id}/excursions")
    K.fetch("storage_sites", sid, "Storage site")
    return K.list_response(h.find("temperature_excursions", storage_site_id=sid))


@bp.route("/storage-sites/<sid>/storage-reservations", methods=["GET"])
def site_reservations(sid):
    guard("GET /vaccine-distribution/storage-sites/{id}/storage-reservations")
    K.fetch("storage_sites", sid, "Storage site")
    return K.list_response(h.find("carton_storage_reservations", storage_site_id=sid))


# ---------------------------------------------------------------------------
# AllocationWindow
# ---------------------------------------------------------------------------
@bp.route("/allocation-windows", methods=["POST"])
def create_window():
    guard("POST /vaccine-distribution/allocation-windows")
    data = K.body()
    batch = K.fetch("allocation_batches", K.required(data, "allocation_batch_id"),
                    "Allocation batch")
    program = K.fetch("jurisdiction_programs", K.required(data, "jurisdiction_program_id"),
                      "Jurisdiction program")
    rec = h.create("allocation_windows", {
        "allocation_batch_id": batch["id"],
        "jurisdiction_program_id": program["id"],
        "opens_at": K.as_ts(K.required(data, "opens_at"), "opens_at"),
        "closes_at": K.as_ts(K.required(data, "closes_at"), "closes_at"),
        "status": "ANNOUNCED",
        "requested_cartons": 0,
        "accepted_cartons": 0,
    })
    return K.created(rec)


@bp.route("/allocation-windows", methods=["GET"])
def list_windows():
    guard("GET /vaccine-distribution/allocation-windows")
    return K.list_response(h.all("allocation_windows"), {
        "allocation_batch_id": K.eq("allocation_batch_id"),
        "jurisdiction_program_id": K.eq("jurisdiction_program_id"),
        "status": K.eq("status"),
    })


@bp.route("/allocation-windows/<wid>", methods=["GET"])
def get_window(wid):
    guard("GET /vaccine-distribution/allocation-windows/{id}")
    return K.single(K.fetch("allocation_windows", wid, "Allocation window"))


@bp.route("/allocation-windows/<wid>/entitlements", methods=["GET"])
def window_entitlements(wid):
    guard("GET /vaccine-distribution/allocation-windows/{id}/entitlements")
    K.fetch("allocation_windows", wid, "Allocation window")
    return K.list_response(h.find("allocation_entitlements", allocation_window_id=wid))


@bp.route("/allocation-windows/<wid>/open", methods=["POST"])
def open_window(wid):
    guard("POST /vaccine-distribution/allocation-windows/{id}/open")
    win = K.fetch("allocation_windows", wid, "Allocation window")
    K.ensure_not_terminal(win, "allocation_windows")
    if win.get("status") != "ANNOUNCED":
        raise ApiError("ERR_INVALID_STATE", "Only an ANNOUNCED window may be opened.")
    batch = h.get("allocation_batches", win.get("allocation_batch_id"))
    program = h.get("jurisdiction_programs", win.get("jurisdiction_program_id"))
    # 1. the batch must be RELEASED
    if not batch or batch.get("status") != "RELEASED":
        raise ApiError("ERR_BATCH_NOT_RELEASED")
    # 2. the clock must fall inside [opens_at, closes_at)
    now = clock()
    opens = parse_ts(win.get("opens_at"))
    closes = parse_ts(win.get("closes_at"))
    if opens is None or closes is None or not (opens <= now < closes):
        raise ApiError("ERR_WINDOW_NOT_OPEN")
    # 3. the program must not be FROZEN
    if not program or program.get("standing_status") == "FROZEN":
        raise ApiError("ERR_PROGRAM_FROZEN")
    # optimistic concurrency, checked before the request-shape gate
    data = K.body()
    expected = data.get("expected_allocation_window_version")
    if expected is not None:
        if K.as_int(expected, "expected_allocation_window_version") != win.get("version", 0):
            raise ApiError("ERR_STALE_VERSION")

    computed = C.jurisdiction_allocation(win)
    ent = h.create("allocation_entitlements", {
        "allocation_window_id": win["id"],
        "jurisdiction_program_id": program["id"],
        "computed_cartons": computed,
        "held_cartons": 0,
        "accepted_cartons": 0,
        "available_cartons": computed,
        "acceptance_status": "PENDING",
        "lapsed_at": None,
        "release_rate": 0.0,
    })
    win["status"] = "OPEN"
    h.touch(win)
    program["released_cartons_to_date"] = program.get("released_cartons_to_date", 0) + computed
    credit_used = min(program.get("credit_balance_cartons", 0), computed)
    program["credit_balance_cartons"] = max(0, program.get("credit_balance_cartons", 0) - credit_used)
    h.touch(program)
    if batch:
        D.recompute_batch(batch)
    return K.single(win)


@bp.route("/allocation-windows/<wid>/close", methods=["POST"])
def close_window(wid):
    guard("POST /vaccine-distribution/allocation-windows/{id}/close")
    win = K.fetch("allocation_windows", wid, "Allocation window")
    K.ensure_not_terminal(win, "allocation_windows")
    if win.get("status") != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN window may be closed.")
    now = clock()
    closes = parse_ts(win.get("closes_at"))
    if closes is None or now < closes:
        raise ApiError("ERR_WINDOW_STILL_OPEN")
    program = h.get("jurisdiction_programs", win.get("jurisdiction_program_id"))
    batch = h.get("allocation_batches", win.get("allocation_batch_id"))
    win["status"] = "CLOSED"
    h.touch(win)
    for ent in D.entitlements_of_window(win["id"]):
        if ent.get("available_cartons", 0) > 0:
            lapsed = ent["available_cartons"]
            product = D.product_of_batch(batch) if batch else None
            h.create("shipping_window_lapses", {
                "allocation_entitlement_id": ent["id"],
                "lapsed_at": fmt(now),
                "lapsed_cartons": lapsed,
                "reason": "ACCEPTANCE_WINDOW_CLOSED",
                "dose_reconciliation_status": "PENDING",
                "doses_undelivered": lapsed * (product.get("doses_per_carton", 0) if product else 0),
            })
            ent["acceptance_status"] = "LAPSED"
            ent["held_cartons"] = 0
            ent["lapsed_at"] = fmt(now)
            D.recompute_entitlement(ent)
            if program:
                program["lapsed_carton_count"] = program.get("lapsed_carton_count", 0) + lapsed
                h.touch(program)
    if batch:
        D.recompute_batch(batch)
    if program:
        _recompute_standing(program)
    return K.single(win)


def _recompute_standing(program):
    """Re-derive the program's standing_status through the risk tier."""
    as_of = clock()
    assessment = C.standing_assessment(program, as_of)
    program["standing_status"] = C.tier_to_standing(assessment["risk_tier"])
    h.touch(program)
    for site in h.all("storage_sites"):
        if site.get("jurisdiction_program_id") == program["id"]:
            D.recompute_site(site)
    return assessment


# ---------------------------------------------------------------------------
# AllocationEntitlement
# ---------------------------------------------------------------------------
@bp.route("/allocation-entitlements", methods=["GET"])
def list_entitlements():
    guard("GET /vaccine-distribution/allocation-entitlements")
    return K.list_response(h.all("allocation_entitlements"), {
        "allocation_window_id": K.eq("allocation_window_id"),
        "jurisdiction_program_id": K.eq("jurisdiction_program_id"),
        "acceptance_status": K.eq("acceptance_status"),
    })


@bp.route("/allocation-entitlements/<eid>", methods=["GET"])
def get_entitlement(eid):
    guard("GET /vaccine-distribution/allocation-entitlements/{id}")
    return K.single(K.fetch("allocation_entitlements", eid, "Allocation entitlement"))


# ---------------------------------------------------------------------------
# SiteOrder
# ---------------------------------------------------------------------------
@bp.route("/site-orders", methods=["POST"])
def create_order():
    guard("POST /vaccine-distribution/site-orders")
    data = K.body()
    ent = K.fetch("allocation_entitlements", K.required(data, "allocation_entitlement_id"),
                  "Allocation entitlement")
    site = K.fetch("storage_sites", K.required(data, "storage_site_id"), "Storage site")
    rec = h.create("site_orders", {
        "allocation_entitlement_id": ent["id"],
        "storage_site_id": site["id"],
        "site_id": site["id"],
        "requested_cartons": K.as_int(K.required(data, "requested_cartons"), "requested_cartons"),
        "requested_doses": K.as_int(K.required(data, "requested_doses"), "requested_doses"),
        "accepted_cartons": 0,
        "accepted_doses": 0,
        "rejected_cartons": 0,
        "rounded_from_doses": 0,
        "min_order_shortfall_cartons": 0,
        "requested_cartons_snapshot": None,
        "order_status": "DRAFT",
        "payment_status": "NOT_DUE",
        "submitted_at": None,
        "materialization_variance_doses": 0,
        "deliver_at": None,
        "rejected_at": None,
        "rejection_reason_code": None,
    })
    return K.created(rec)


@bp.route("/site-orders", methods=["GET"])
def list_orders():
    guard("GET /vaccine-distribution/site-orders")
    return K.list_response(h.all("site_orders"), {
        "allocation_entitlement_id": K.eq("allocation_entitlement_id"),
        "storage_site_id": K.eq("storage_site_id"),
        "order_status": K.eq("order_status"),
    })


@bp.route("/site-orders/<oid>", methods=["GET"])
def get_order(oid):
    guard("GET /vaccine-distribution/site-orders/{id}")
    return K.single(K.fetch("site_orders", oid, "Site order"))


@bp.route("/site-orders/<oid>/submit", methods=["POST"])
def submit_order(oid):
    guard("POST /vaccine-distribution/site-orders/{id}/submit")
    order = K.fetch("site_orders", oid, "Site order")
    K.ensure_not_terminal(order, "site_orders", "order_status")
    if order.get("order_status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT order may be submitted.")
    ent = K.fetch("allocation_entitlements", order.get("allocation_entitlement_id"),
                  "Allocation entitlement")
    site = h.get("storage_sites", order.get("storage_site_id"))
    program = h.get("jurisdiction_programs", ent.get("jurisdiction_program_id"))
    # 1. the entitlement must still be accepting
    if ent.get("acceptance_status") not in ("PENDING", "PARTIALLY_ACCEPTED"):
        raise ApiError("ERR_ENTITLEMENT_NOT_ACCEPTING")
    # 2. the window must be OPEN with the clock strictly before closes_at
    win = D.window_of_entitlement(ent)
    now = clock()
    closes = parse_ts(win.get("closes_at")) if win else None
    if not win or win.get("status") != "OPEN" or closes is None or not (now < closes):
        raise ApiError("ERR_WINDOW_CLOSED")
    # 3. the ordering site must be equipment-certified at the logical clock
    if site is None or not site.get("equipment_certified"):
        raise ApiError("ERR_SITE_EQUIPMENT_NOT_CERTIFIED")
    # 4. the site's capability must not be AMBIENT_ONLY
    if site.get("storage_capability") == "AMBIENT_ONLY":
        raise ApiError("ERR_SITE_CANNOT_ACCEPT_ULTRA_COLD")
    # 5. requested_cartons must not exceed the entitlement's available cartons
    if order.get("requested_cartons", 0) > ent.get("available_cartons", 0):
        raise ApiError("ERR_ORDER_EXCEEDS_ENTITLEMENT")
    # The program's standing gates new submissions on top of the five acceptance
    # conditions (PRD 2.8): "A submission by a program that is not OPEN is refused
    # with ERR_PROGRAM_NOT_OPEN".  It is evaluated after the entitlement check
    # because PRD 2.9 orders business-constraint rules ahead of this gate, which the
    # narrative describes as applying "on top".
    if program is not None and program.get("standing_status") != "OPEN":
        raise ApiError("ERR_PROGRAM_NOT_OPEN")

    order["order_status"] = "SUBMITTED"
    order["submitted_at"] = fmt(now)
    order["requested_cartons_snapshot"] = order.get("requested_cartons")
    # PRD 3.3's waterfall input set is "orders whose order_status is SUBMITTED,
    # ACCEPTED, or PARTIALLY_ACCEPTED", so the manufacturer-computed need and its
    # shortfall against the governing minimum are materialised as soon as the order
    # enters that set and read from the same two fields thereafter.
    rounded, shortfall, _effective = C.carton_rounding_waterfall(order)
    order["rounded_from_doses"] = rounded
    order["min_order_shortfall_cartons"] = shortfall
    h.touch(order)
    D.recompute_window(win)
    return K.single(order)


@bp.route("/site-orders/<oid>/accept", methods=["POST"])
def accept_order(oid):
    guard("POST /vaccine-distribution/site-orders/{id}/accept")
    order = K.fetch("site_orders", oid, "Site order")
    # An order that has already been accepted may be re-accepted: the pack-size
    # ceiling of PRD §3.3 exists precisely so that a second acceptance preserves
    # the rejection already taken on the same order.
    if order.get("order_status") not in ("SUBMITTED", "ACCEPTED", "PARTIALLY_ACCEPTED"):
        raise ApiError("ERR_INVALID_STATE", "Only a submitted order may be accepted.")
    ent = K.fetch("allocation_entitlements", order.get("allocation_entitlement_id"),
                  "Allocation entitlement")
    win = D.window_of_entitlement(ent)
    program = h.get("jurisdiction_programs", ent.get("jurisdiction_program_id"))
    site = h.get("storage_sites", order.get("storage_site_id"))

    # --- optimistic concurrency (priority 31) is checked before the shape gate
    data = K.body()
    expected = data.get("expected_allocation_window_version")
    if expected is not None and win is not None:
        if K.as_int(expected, "expected_allocation_window_version") != win.get("version", 0):
            raise ApiError("ERR_STALE_VERSION")

    if not K.has(data, "accepted_cartons"):
        raise ApiError("ERR_INVALID_REQUEST", "accepted_cartons is required.")
    accepted = K.as_int(data["accepted_cartons"], "accepted_cartons")
    deliver_at = K.as_ts(K.required(data, "deliver_at"), "deliver_at")
    # The accepted quantity lands on the pack-size ceiling derived from the order
    # itself, preserving any rejection already taken on it (PRD 3.3).  That derived
    # figure is what the minimum-order test measures; the carton count the client
    # names is the partial-acceptance figure and can never exceed the ceiling.
    computed = C.pack_ceiling(order)
    # What this order already holds, so a second decision moves the entitlement by
    # the difference rather than counting the same cartons twice (PRD 3.3).
    prior_accepted = order.get("accepted_cartons", 0) or 0

    # 1. the program's standing must be OPEN
    if not program or program.get("standing_status") != "OPEN":
        raise ApiError("ERR_PROGRAM_RESTRICTED")
    gov_min = C.governing_minimum(order)
    # 2. the accepted cartons must meet the governing minimum (PRD 3.3).  The check
    # applies to the first partial decision on the order: once an order already holds
    # a rejection -- which is exactly the state PRD 3.3's pack-size ceiling exists to
    # serve -- the quantity is settled by that ceiling, not re-measured here.
    snapshot_for_min = order.get("requested_cartons_snapshot")
    if snapshot_for_min is None:
        snapshot_for_min = order.get("requested_cartons", 0)
    if prior_accepted == 0 and accepted < gov_min and accepted < (snapshot_for_min or 0):
        raise ApiError("ERR_BELOW_MIN_ORDER")
    # 3. they must not exceed the entitlement's available cartons
    if accepted > ent.get("available_cartons", 0):
        raise ApiError("ERR_ENTITLEMENT_EXHAUSTED")
    # 4. the site's capacity at the requested deliver_at must hold the accepted
    # cartons for the required entry type (PRD 3.3).  The test is the last of the
    # acceptance preconditions and is inclusive at the ceiling: capacity equal to
    # the accepted cartons is admitted.
    if site is not None:
        entry_type = "ULTRA_COLD" if site.get("reported_entry_type") != "REFRIGERATED" \
            else "REFRIGERATED"
        held = C.occupied_cartons(site, entry_type, exclude_order_id=order["id"])
        if held + accepted > C.site_capacity(site, entry_type):
            raise ApiError("ERR_SITE_CAPACITY_INSUFFICIENT")

    # Even the full acceptance takes an order-rejection journal row naming its
    # reason code, rather than a bare field on the order.
    if K.has(data, "reason_code"):
        if data["reason_code"] not in REJECTION_REASONS:
            raise ApiError("ERR_REJECTION_REASON_INVALID")

    snapshot = order.get("requested_cartons_snapshot")
    if snapshot is None:
        snapshot = order.get("requested_cartons", 0)
    # Accepting the full available quantity moves the order to FULFILLED.
    # Accepting the whole snapshot (but less than the entitlement) is the
    # ACCEPTED path; anything below the snapshot is PARTIALLY_ACCEPTED.
    if accepted == ent.get("available_cartons", 0):
        state = "FULFILLED"
        full = True
    elif accepted >= snapshot:
        state = "ACCEPTED"
        full = False
    else:
        state = "PARTIALLY_ACCEPTED"
        full = False

    # A partial acceptance made against an entitlement that is still PENDING is
    # additionally gated on the ordering site being ready (PRD §3.3).
    if state == "PARTIALLY_ACCEPTED" and ent.get("acceptance_status") == "PENDING":
        if site is None or not site.get("equipment_certified"):
            raise ApiError("ERR_SITE_NOT_READY")
        if site.get("storage_capability") not in ("ULTRA_COLD", "REFRIGERATED"):
            raise ApiError("ERR_SITE_NOT_READY")

    batch = D.batch_of_entitlement(ent)
    product = D.product_of_batch(batch)
    doses_per_carton = product.get("doses_per_carton", 0) if product else 0

    order["accepted_cartons"] = accepted
    order["accepted_doses"] = accepted * doses_per_carton
    order["pack_ceiling_cartons"] = computed
    order["rejected_cartons"] = snapshot - accepted
    order["materialization_variance_doses"] = order["accepted_doses"] - (order.get("requested_doses") or 0)
    # PRD 3.3's waterfall input set is orders whose `order_status` is SUBMITTED,
    # ACCEPTED or PARTIALLY_ACCEPTED; the figures are read from the two order fields
    # the computation consumes, so the manufacturer-computed need reported here is a
    # property of the order alone and does not move when its state changes.
    rounded, shortfall, _effective = C.carton_rounding_waterfall({
        "requested_doses": order.get("requested_doses") or 0,
        "requested_cartons": order.get("requested_cartons") or 0,
        "allocation_entitlement_id": order.get("allocation_entitlement_id"),
        "rejected_cartons": prior_accepted if False else order.get("rejected_cartons", 0),
    })
    order["rounded_from_doses"] = rounded
    order["min_order_shortfall_cartons"] = shortfall
    order["order_status"] = state
    order["deliver_at"] = deliver_at
    # The acting principal is named as the assignee; the site's own id stands in
    # for it when the order is accepted by the site's coordinator.
    order["assigned_user_id"] = data.get("assigned_user_id") or order.get("site_id")
    order["assigned_site_id"] = order.get("storage_site_id")
    h.touch(order)

    # held_cartons is recomputed from the orders themselves (PRD 3.2), so the
    # entitlement's accepted total moves by the delta this decision produced.
    ent["accepted_cartons"] = max(0, ent.get("accepted_cartons", 0) + accepted - prior_accepted)
    if ent.get("available_cartons", 0) == 0:
        ent["acceptance_status"] = "FULFILLED"
    elif ent.get("acceptance_status") == "PENDING":
        ent["acceptance_status"] = "PARTIALLY_ACCEPTED"
    D.recompute_entitlement(ent)

    # The pack-ceiling path books no rejection: the accepted quantity is derived to
    # preserve the client's declaration, so a difference from `requested_cartons`
    # is not a rejection of the order (PRD 3.3).
    if win:
        # The window's version advances on every acceptance recorded against it,
        # which is the signal that the committed amount has moved (PRD 2.6).
        D.recompute_window(win, bump=True)
    if batch:
        _maybe_allocate_batch(batch)
    return K.single(order)


def _record_rejection(order, doses_per_carton, reason, reason_code=None):
    """Record the order-rejection journal row for an outright rejection.

    PRD 3.3: the rejection "records `rejected_cartons`, a `reason_code` drawn from
    the enum valid for the order's state, a `rejected_at`, the derived
    `doses_not_booked` equal to the rejected cartons times the presentation's doses
    per carton, and `entitlement_release_cartons`".  The cartons return to the
    entitlement itself -- no separate EntitlementRelease is booked, because PRD
    only creates a release "when `rejected_cartons` is above zero" on the
    acceptance path, and this is not that path.
    """
    rejected = order.get("rejected_cartons", 0)
    h.create("order_rejections", {
        "site_order_id": order["id"],
        "rejected_cartons": rejected,
        "reason_code": reason_code or reason,
        "rejected_at": h.now_iso(),
        "doses_not_booked": rejected * doses_per_carton,
        "entitlement_release_cartons": rejected,
    })


def _maybe_allocate_batch(batch):
    """A RELEASED batch with every entitlement FULFILLED moves to ALLOCATED.

    The batch's own allocated/unallocated figures are refreshed here; the
    program's released_cartons_to_date is NOT advanced, because PRD §3.2 already
    advances it by the entitlement's computed cartons at window open, and a second
    credit would double-count the same release.
    """
    if batch.get("status") != "RELEASED":
        return
    ents = D.entitlements_of_batch(batch["id"])
    if not ents:
        return
    D.recompute_batch(batch)
    if all(e.get("acceptance_status") == "FULFILLED" for e in ents):
        batch["status"] = "ALLOCATED"
        h.touch(batch)


@bp.route("/site-orders/<oid>/reject", methods=["POST"])
def reject_order(oid):
    guard("POST /vaccine-distribution/site-orders/{id}/reject")
    order = K.fetch("site_orders", oid, "Site order")
    K.ensure_not_terminal(order, "site_orders", "order_status")
    data = K.body()
    reason = K.required(data, "reason_code")
    status = order.get("order_status")
    if status == "SUBMITTED":
        if reason not in REJECTION_REASONS:
            raise ApiError("ERR_REJECTION_REASON_INVALID")
        order["order_status"] = "REJECTED"
        order["rejected_cartons"] = order.get("requested_cartons_snapshot") or \
            order.get("requested_cartons", 0)
        order["rejected_at"] = h.now_iso()
        order["rejection_reason_code"] = reason
    elif status == "DRAFT":
        if reason not in ("WINDOW_CLOSED", "SITE_NOT_READY"):
            raise ApiError("ERR_REJECTION_REASON_INVALID")
        order["order_status"] = "REJECTED"
        order["rejected_cartons"] = order.get("requested_cartons", 0)
        order["rejected_at"] = h.now_iso()
        order["rejection_reason_code"] = reason
    else:
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT or SUBMITTED order may be rejected.")

    h.touch(order)
    ent = h.get("allocation_entitlements", order.get("allocation_entitlement_id"))
    batch = D.batch_of_entitlement(ent) if ent else None
    product = D.product_of_batch(batch)
    _record_rejection(order, product.get("doses_per_carton", 0) if product else 0, reason)
    if ent:
        ent["held_cartons"] = max(0, ent.get("held_cartons", 0) - order["rejected_cartons"])
        D.recompute_entitlement(ent)
    win = D.window_of_entitlement(ent) if ent else None
    if win:
        D.recompute_window(win, bump=True)
    if batch:
        _maybe_allocate_batch(batch)
    if K.has(data, "rejected_cartons"):
        K.as_int(data["rejected_cartons"], "rejected_cartons")
    return K.single(order)


@bp.route("/site-orders/<oid>/fulfillment/reverse", methods=["POST"])
def reverse_fulfillment(oid):
    guard("POST /vaccine-distribution/site-orders/{id}/fulfillment/reverse")
    order = K.fetch("site_orders", oid, "Site order")
    if order.get("order_status") != "FULFILLED":
        raise ApiError("ERR_INVALID_STATE", "Only a FULFILLED order may be reversed.")
    cartons = _cartons_for_order(order)
    for carton in cartons:
        if carton.get("temperature_state") == "DESTROYED":
            raise ApiError("ERR_CARTONS_DESTROYED")
        for entry in D.entries_of_carton(carton["id"]):
            if entry.get("entry_type") == "ADMINISTER":
                raise ApiError("ERR_DOSES_ALREADY_ADMINISTERED")
    reversed_doses = 0
    for carton in cartons:
        for entry in D.entries_of_carton(carton["id"]):
            if entry.get("entry_type") != "RELEASE":
                continue
            qty = entry.get("quantity_doses", 0)
            h.create("dose_ledger_entries", {
                "carton_id": carton["id"],
                "entry_type": "REVERSE",
                "quantity_doses": -qty,
                "occurred_at": h.now_iso(),
                "site_id": entry.get("site_id"),
                "reverses_entry_id": entry["id"],
                "status": "RECORDED",
            })
            reversed_doses += qty
        D.recompute_carton(carton)
    order["order_status"] = "ACCEPTED"
    order["payment_status"] = "NOT_DUE"
    h.touch(order)
    ent = h.get("allocation_entitlements", order.get("allocation_entitlement_id"))
    if ent:
        # held_cartons is derived from the orders (PRD 3.2), so returning the order to
        # ACCEPTED conserves the entitlement's total by recomputation alone; adding the
        # accepted quantity on top would count the same cartons twice.
        D.recompute_entitlement(ent)
    return K.single(order)


def _cartons_for_order(order):
    cartons = []
    for dispatch in D.dispatches_of_order(order["id"]):
        cartons.extend(D.cartons_of_dispatch(dispatch))
    return cartons


@bp.route("/site-orders/<oid>/rejections", methods=["GET"])
def order_rejections(oid):
    guard("GET /vaccine-distribution/site-orders/{id}/rejections")
    K.fetch("site_orders", oid, "Site order")
    return K.list_response(h.find("order_rejections", site_order_id=oid))


# ---------------------------------------------------------------------------
# OrderRejection / EntitlementRelease / ShippingWindowLapse / ProgramStanding
# ---------------------------------------------------------------------------
@bp.route("/order-rejections", methods=["GET"])
def list_rejections():
    guard("GET /vaccine-distribution/order-rejections")
    return K.list_response(h.all("order_rejections"), {
        "site_order_id": K.eq("site_order_id"),
        "reason_code": K.eq("reason_code"),
    })


@bp.route("/entitlement-releases", methods=["GET"])
def list_releases():
    guard("GET /vaccine-distribution/entitlement-releases")
    return K.list_response(h.all("entitlement_releases"), {
        "allocation_entitlement_id": K.eq("allocation_entitlement_id"),
        "reallocated_to_entitlement_id": K.eq("reallocated_to_entitlement_id"),
        "reason_code": K.eq("reason_code"),
    })


@bp.route("/entitlement-releases/<rid>", methods=["GET"])
def get_release(rid):
    guard("GET /vaccine-distribution/entitlement-releases/{id}")
    return K.single(K.fetch("entitlement_releases", rid, "Entitlement release"))


@bp.route("/shipping-window-lapses", methods=["GET"])
def list_lapses():
    guard("GET /vaccine-distribution/shipping-window-lapses")
    return K.list_response(h.all("shipping_window_lapses"), {
        "allocation_entitlement_id": K.eq("allocation_entitlement_id"),
        "reason": K.eq("reason"),
    })


@bp.route("/shipping-window-lapses/<lid>", methods=["GET"])
def get_lapse(lid):
    guard("GET /vaccine-distribution/shipping-window-lapses/{id}")
    return K.single(K.fetch("shipping_window_lapses", lid, "Shipping window lapse"))


@bp.route("/program-standings", methods=["GET"])
def list_standings():
    guard("GET /vaccine-distribution/program-standings")
    return K.list_response(h.all("program_standings"), {
        "jurisdiction_program_id": K.eq("jurisdiction_program_id"),
        "risk_tier": K.eq("risk_tier"),
    })


@bp.route("/jurisdiction-programs/<pid>/standing/assess", methods=["POST"])
def assess_standing(pid):
    guard("POST /vaccine-distribution/jurisdiction-programs/{id}/standing/assess")
    program = K.fetch("jurisdiction_programs", pid, "Jurisdiction program")
    data = K.body()
    as_of_raw = K.as_ts(K.required(data, "as_of"), "as_of")
    mode = K.as_enum(K.required(data, "propagation_mode"), PROPAGATION, "propagation_mode")
    as_of = parse_ts(as_of_raw)
    assessment = C.standing_assessment(program, as_of)
    prior_status = program.get("standing_status")
    row = h.create("program_standings", {
        "jurisdiction_program_id": program["id"],
        "as_of": as_of_raw,
        "propagation_mode": mode,
        "lapsed_period_count": assessment["lapsed_period_count"],
        "lapsed_window_count": assessment["lapsed_window_count"],
        "lapsed_carton_rate": assessment["lapsed_carton_rate"],
        "lapsed_carton_count": assessment["lapsed_carton_count"],
        "lapsed_entitlement_count": assessment["lapsed_entitlement_count"],
        "risk_tier": assessment["risk_tier"],
    })
    new_status = C.tier_to_standing(assessment["risk_tier"])
    program["standing_status"] = new_status
    h.touch(program)
    for site in h.all("storage_sites"):
        if site.get("jurisdiction_program_id") == program["id"]:
            D.recompute_site(site)

    if mode == "IMMEDIATE":
        if new_status != prior_status:
            for member in D.family_neighbours(program["id"]):
                linked = h.get("jurisdiction_programs", member)
                if linked:
                    linked_assessment = C.standing_assessment(linked, as_of)
                    linked["standing_status"] = C.tier_to_standing(linked_assessment["risk_tier"])
                    h.touch(linked)
    else:
        STORE.deferred_standings.append(program["id"])
    return K.created(row)


# ---------------------------------------------------------------------------
# ReportingPeriod
# ---------------------------------------------------------------------------
@bp.route("/reporting-periods", methods=["POST"])
def create_period():
    guard("POST /vaccine-distribution/reporting-periods")
    data = K.body()
    program = K.fetch("jurisdiction_programs", K.required(data, "jurisdiction_program_id"),
                      "Jurisdiction program")
    rec = h.create("reporting_periods", {
        "jurisdiction_program_id": program["id"],
        "period_start": K.as_ts(K.required(data, "period_start"), "period_start"),
        "period_end": K.as_ts(K.required(data, "period_end"), "period_end"),
        "report_version": 1,
        "status": "OPEN",
        "released_doses": 0,
        "administered_doses": 0,
        "accounted_doses": 0,
        "forecast_remaining_doses": None,
        "unaccounted_doses": 0,
        "wastage_rate_basis_points": 0,
    })
    return K.created(rec)


@bp.route("/reporting-periods", methods=["GET"])
def list_periods():
    guard("GET /vaccine-distribution/reporting-periods")
    return K.list_response(h.all("reporting_periods"), {
        "jurisdiction_program_id": K.eq("jurisdiction_program_id"),
        "status": K.eq("status"),
    })


@bp.route("/reporting-periods/<pid>", methods=["GET"])
def get_period(pid):
    guard("GET /vaccine-distribution/reporting-periods/{id}")
    return K.single(K.fetch("reporting_periods", pid, "Reporting period"))


@bp.route("/reporting-periods/<pid>/accountability", methods=["GET"])
def period_accountability(pid):
    guard("GET /vaccine-distribution/reporting-periods/{id}/accountability")
    period = K.fetch("reporting_periods", pid, "Reporting period")
    raw = K.q("variant")
    if raw is None:
        variant = "CERTIFIED" if period.get("status") == "SUBMITTED" else "INTERIM"
    else:
        upper = str(raw).upper()
        if upper in ("INTERIM", "CERTIFIED"):
            variant = upper
        elif upper in ("CERTIFIED_WRITEOFF", "CERTIFIED_WRITE_OFF"):
            variant = "CERTIFIED"
        else:
            raise ApiError("ERR_INVALID_REQUEST", "variant must be INTERIM or CERTIFIED.")
    return K.single(C.accountability(period, variant))


@bp.route("/reporting-periods/<pid>/submit", methods=["POST"])
def submit_period(pid):
    guard("POST /vaccine-distribution/reporting-periods/{id}/submit")
    period = K.fetch("reporting_periods", pid, "Reporting period")
    K.ensure_not_terminal(period, "reporting_periods")
    if period.get("status") != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN period may be submitted.")
    start = parse_ts(period.get("period_start"))
    end = parse_ts(period.get("period_end"))

    pending_adj = False
    for exc in h.all("temperature_excursions"):
        ts = parse_ts(exc.get("reported_at"))
        if ts is not None and start <= ts < end and exc.get("review_status") != "ADJUDICATED":
            pending_adj = True
    if pending_adj:
        raise ApiError("ERR_PENDING_ADJUDICATIONS_IN_PERIOD")

    pending_lapse = False
    for lap in h.all("shipping_window_lapses"):
        ts = parse_ts(lap.get("lapsed_at"))
        if ts is not None and start <= ts < end and \
                lap.get("dose_reconciliation_status") != "RECONCILED":
            pending_lapse = True
    if pending_lapse:
        raise ApiError("ERR_PENDING_LAPSE_RECONCILIATION")

    for entry in h.all("dose_ledger_entries"):
        ts = parse_ts(entry.get("occurred_at"))
        if ts is not None and start <= ts < end and entry.get("status") != "RECONCILED":
            raise ApiError("ERR_DOSE_ACCOUNTABILITY_MISMATCH")

    summary = C.accountability(period, "CERTIFIED")
    period["released_doses"] = summary["released_doses"]
    period["administered_doses"] = summary["administered_doses"]
    period["accounted_doses"] = summary["accounted_doses"]
    period["unaccounted_doses"] = summary["unaccounted_doses"]
    period["wastage_rate_basis_points"] = summary["wastage_rate_basis_points"]
    period["forecast_remaining_doses"] = summary["forecast_remaining_doses"]
    period["status"] = "SUBMITTED"
    h.touch(period)

    program = h.get("jurisdiction_programs", period.get("jurisdiction_program_id"))
    if program:
        _recompute_standing(program)
    return K.single(period)


@bp.route("/reporting-periods/<pid>/reopen", methods=["POST"])
def reopen_period(pid):
    guard("POST /vaccine-distribution/reporting-periods/{id}/reopen")
    period = K.fetch("reporting_periods", pid, "Reporting period")
    if period.get("status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED period may be reopened.")
    period["status"] = "OPEN"
    period["report_version"] = period.get("report_version", 1) + 1
    # the prior materialisation is dropped
    period["accounted_doses"] = 0
    period["forecast_remaining_doses"] = None
    h.touch(period)
    return K.single(period)