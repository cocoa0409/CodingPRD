"""Dispatches, cold chain shippers, logger readings, equipment verifications."""
from flask import Blueprint

from errors import ApiError
from helpers import h
from middleware import guard
from clockutil import (parse_ts, clock, fmt, add_hours, add_minutes, diff_minutes,
                         weekday_name, earlier)
from services import derive as D
from services import calc as C
from routes import common as K
from routes.reference import _append_entry

bp = Blueprint("supply", __name__)

ENTRY_ROUTES = ["DIRECT_ULTRA_COLD", "THAW_AT_HUB"]
SHIPPER_STATUSES = ["PREPARING", "SEALED", "IN_TRANSIT", "RECEIVED", "RELEASED", "HELD"]
HOLD_REASONS = ["MISSING_LOGGER", "INSUFFICIENT_DRY_ICE", "LATE_PACKING", "LATE_READING"]
READING_SOURCES = ["LOGGER", "MANUAL"]
VERIFICATION_EQUIPMENT = ["ULTRA_COLD_FREEZER", "THERMAL_SHIPPER", "DATA_LOGGER"]
VERIFICATION_OUTCOMES = ["PASSED", "FAILED"]

TRANSIT_HOURS = 24
LOGGER_READING_GRACE_MINUTES = 120


# ---------------------------------------------------------------------------
# SiteEquipmentVerification
# ---------------------------------------------------------------------------
@bp.route("/site-equipment-verifications", methods=["POST"])
def create_verification():
    guard("POST /vaccine-distribution/site-equipment-verifications")
    data = K.body()
    site = K.fetch("storage_sites", K.required(data, "storage_site_id"), "Storage site")
    rec = h.create("site_equipment_verifications", {
        "storage_site_id": site["id"],
        "equipment_type": K.as_enum(K.required(data, "equipment_type"),
                                    VERIFICATION_EQUIPMENT, "equipment_type"),
        "certificate_number": K.as_str(K.required(data, "certificate_number"), "certificate_number"),
        "certificate_expires_at": K.as_ts(K.required(data, "certificate_expires_at"),
                                          "certificate_expires_at"),
        "verified_at": K.as_ts(K.required(data, "verified_at"), "verified_at"),
        "outcome": K.as_enum(K.required(data, "outcome"), VERIFICATION_OUTCOMES, "outcome"),
        "status": "RECORDED",
        "invalidated_at": None,
    })
    # A new verification invalidates every earlier RECORDED verification on the
    # same site whose equipment_type is ULTRA_COLD_FREEZER (PRD §2.8).
    if rec["equipment_type"] == "ULTRA_COLD_FREEZER":
        for other in h.all("site_equipment_verifications"):
            if other["id"] == rec["id"]:
                continue
            if other.get("storage_site_id") != site["id"]:
                continue
            if other.get("equipment_type") != "ULTRA_COLD_FREEZER":
                continue
            if other.get("status") == "RECORDED":
                other["status"] = "INVALIDATED"
                other["invalidated_at"] = h.now_iso()
                h.touch(other)
    D.recompute_site(site)
    return K.created(rec)


@bp.route("/site-equipment-verifications", methods=["GET"])
def list_verifications():
    guard("GET /vaccine-distribution/site-equipment-verifications")
    return K.list_response(h.all("site_equipment_verifications"), {
        "storage_site_id": K.eq("storage_site_id"),
        "status": K.eq("status"),
        "equipment_type": K.eq("equipment_type"),
    })


@bp.route("/site-equipment-verifications/<vid>", methods=["GET"])
def get_verification(vid):
    guard("GET /vaccine-distribution/site-equipment-verifications/{id}")
    return K.single(K.fetch("site_equipment_verifications", vid, "Equipment verification"))


@bp.route("/storage-sites/<sid>/equipment-verifications", methods=["GET"])
def list_site_verifications(sid):
    guard("GET /vaccine-distribution/storage-sites/{id}/equipment-verifications")
    K.fetch("storage_sites", sid, "Storage site")
    return K.list_response(h.find("site_equipment_verifications", storage_site_id=sid))


# ---------------------------------------------------------------------------
# DispatchOrder
# ---------------------------------------------------------------------------
def _select_staging_site(order_site_id):
    """Eligibility filter + ranking (PRD §3.4)."""
    candidates = []
    for member in D.family_neighbours(order_site_id):
        site = h.get("storage_sites", member)
        if site is None or site["id"] == order_site_id:
            continue
        if site.get("storage_capability") != "ULTRA_COLD":
            continue
        if not site.get("equipment_certified"):
            continue
        if site.get("inventory_status") == "FROZEN":
            continue
        candidates.append(site)
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s.get("expected_weekly_doses", 0), s.get("created_at", "")))
    return candidates[0]


@bp.route("/dispatches", methods=["POST"])
def create_dispatch():
    guard("POST /vaccine-distribution/dispatches")
    data = K.body()
    order = K.fetch("site_orders", K.required(data, "site_order_id"), "Site order")
    site = K.fetch("storage_sites", K.required(data, "storage_site_id"), "Storage site")
    route = K.as_enum(K.required(data, "entry_route"), ENTRY_ROUTES, "entry_route")
    staging = None
    if route == "THAW_AT_HUB":
        staging = _select_staging_site(order.get("storage_site_id") or site["id"])
        # PRD 3.4: "An empty candidate set is refused with ERR_NO_ELIGIBLE_SITE."
        if staging is None:
            raise ApiError("ERR_NO_ELIGIBLE_SITE")
    rec = h.create("dispatch_orders", {
        "site_order_id": order["id"],
        "storage_site_id": site["id"],
        "entry_route": route,
        "staging_site_id": staging["id"] if staging else None,
        "freeze_required": False,
        "dispatched_at": None,
        "eta_at": None,
        "status": "DRAFT",
        "carton_count": 0,
        "route_cartons": 0,
        "min_order_shortfall_cartons": 0,
    })
    D.recompute_dispatch(rec)
    return K.created(rec)


@bp.route("/dispatches", methods=["GET"])
def list_dispatches():
    guard("GET /vaccine-distribution/dispatches")
    return K.list_response(h.all("dispatch_orders"), {
        "site_order_id": K.eq("site_order_id"),
        "storage_site_id": K.eq("storage_site_id"),
        "status": K.eq("status"),
    })


@bp.route("/dispatches/<did>", methods=["GET"])
def get_dispatch(did):
    guard("GET /vaccine-distribution/dispatches/{id}")
    return K.single(K.fetch("dispatch_orders", did, "Dispatch"))


@bp.route("/site-orders/<oid>/dispatches", methods=["GET"])
def list_order_dispatches(oid):
    guard("GET /vaccine-distribution/site-orders/{id}/dispatches")
    K.fetch("site_orders", oid, "Site order")
    return K.list_response(h.find("dispatch_orders", site_order_id=oid))


@bp.route("/dispatches/<did>/shippers", methods=["GET"])
def list_dispatch_shippers(did):
    guard("GET /vaccine-distribution/dispatches/{id}/shippers")
    K.fetch("dispatch_orders", did, "Dispatch")
    return K.list_response(h.find("cold_chain_shippers", dispatch_order_id=did))


@bp.route("/dispatches/<did>/cartons", methods=["GET"])
def list_dispatch_cartons(did):
    guard("GET /vaccine-distribution/dispatches/{id}/cartons")
    dispatch = K.fetch("dispatch_orders", did, "Dispatch")
    return K.list_response(D.cartons_of_dispatch(dispatch))


def _unexpired_passed_verification(site_id, equipment_type=None):
    now = clock()
    for v in h.all("site_equipment_verifications"):
        if v.get("storage_site_id") != site_id:
            continue
        if v.get("status") != "RECORDED" or v.get("outcome") != "PASSED":
            continue
        if equipment_type and v.get("equipment_type") != equipment_type:
            continue
        exp = parse_ts(v.get("certificate_expires_at"))
        if exp is None:
            continue
        if exp > now:
            return v
    return None


@bp.route("/dispatches/<did>/pack", methods=["POST"])
def pack_dispatch(did):
    guard("POST /vaccine-distribution/dispatches/{id}/pack")
    dispatch = K.fetch("dispatch_orders", did, "Dispatch")
    K.ensure_not_terminal(dispatch, "dispatch_orders")
    if dispatch.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT dispatch may be packed.")
    order = h.get("site_orders", dispatch.get("site_order_id"))
    site = h.get("storage_sites", dispatch.get("storage_site_id"))
    # 1. the order must be ACCEPTED or PARTIALLY_ACCEPTED
    if not order or order.get("order_status") not in ("ACCEPTED", "PARTIALLY_ACCEPTED"):
        raise ApiError("ERR_ORDER_NOT_ACCEPTED")
    # 2. the destination must be equipment-certified at the logical clock
    if site is None or not site.get("equipment_certified"):
        raise ApiError("ERR_SITE_EQUIPMENT_NOT_CERTIFIED")
    # 3. THAW_AT_HUB needs an ultra-cold staging site that is itself certified
    if dispatch.get("entry_route") == "THAW_AT_HUB":
        staging_id = dispatch.get("staging_site_id")
        if not staging_id:
            raise ApiError("ERR_NO_HUB_AVAILABLE")
        staging = h.get("storage_sites", staging_id)
        if staging is None or staging.get("storage_capability") != "ULTRA_COLD":
            raise ApiError("ERR_NO_HUB_AVAILABLE")
        if not _unexpired_passed_verification(staging_id):
            raise ApiError("ERR_HUB_NOT_CERTIFIED")

    dispatch["status"] = "PACKED"
    destination = h.get("storage_sites", dispatch.get("storage_site_id"))
    dispatch["freeze_required"] = bool(
        destination and destination.get("reported_entry_type") == "ULTRA_COLD"
    )
    h.touch(dispatch)
    D.recompute_dispatch(dispatch)
    return K.single(dispatch)


def _inside_shipping_schedule(program):
    now = clock()
    days = program.get("shipping_days") or []
    cutoff = program.get("shipping_cutoff_utc") or "23:59:59"
    if weekday_name(now) not in days:
        return False
    try:
        hh, mm, ss = [int(x) for x in str(cutoff).split(":")]
    except ValueError:
        return True
    cutoff_seconds = hh * 3600 + mm * 60 + ss
    now_seconds = now.hour * 3600 + now.minute * 60 + now.second
    return now_seconds <= cutoff_seconds


@bp.route("/dispatches/<did>/dispatch", methods=["POST"])
def dispatch_order(did):
    guard("POST /vaccine-distribution/dispatches/{id}/dispatch")
    dispatch = K.fetch("dispatch_orders", did, "Dispatch")
    if dispatch.get("status") != "PACKED":
        raise ApiError("ERR_INVALID_STATE", "Only a PACKED dispatch may be dispatched.")
    order = h.get("site_orders", dispatch.get("site_order_id"))
    shippers = D.shippers_of_dispatch(dispatch["id"])
    # 1. the shipper must be sealed
    if not shippers or all(s.get("packing_status") != "SEALED" for s in shippers):
        raise ApiError("ERR_SHIPPER_NOT_SEALED")
    shipper = next(s for s in shippers if s.get("packing_status") == "SEALED")
    # 2. a logger reading at or after packing_completed_at must exist
    completed = parse_ts(shipper.get("packing_completed_at"))
    readings = [r for r in h.all("logger_readings")
                if r.get("cold_chain_shipper_id") == shipper["id"]]
    if not any(completed is not None and parse_ts(r.get("recorded_at")) is not None
               and parse_ts(r["recorded_at"]) >= completed for r in readings):
        raise ApiError("ERR_LOGGER_READING_MISSING")
    # 3. the logical clock must sit inside the program's shipping schedule
    ent = D.entitlement_of(order) if order else None
    batch = D.batch_of_entitlement(ent) if ent else None
    program = D.program_of_batch(batch)
    if program is not None and not _inside_shipping_schedule(program):
        raise ApiError("ERR_OUTSIDE_SHIPPING_SCHEDULE")
    # 4. the order must still be accepted and not disputed
    if not order or order.get("order_status") not in ("ACCEPTED", "PARTIALLY_ACCEPTED"):
        raise ApiError("ERR_ORDER_NOT_ACCEPTED")
    if order.get("payment_status") not in ("NOT_DUE", "DUE"):
        raise ApiError("ERR_PAYMENT_HOLD")

    now = clock()
    dispatch["status"] = "IN_TRANSIT"
    dispatch["dispatched_at"] = fmt(now)
    dispatch["eta_at"] = fmt(add_hours(now, TRANSIT_HOURS))
    for carton in D.cartons_of_dispatch(dispatch):
        carton["temperature_state"] = "IN_TRANSIT"
        _append_entry(carton, "RELEASE", carton.get("remaining_doses", 0), fmt(now))
        D.recompute_carton(carton)
    shipper["packing_status"] = "IN_TRANSIT"
    h.touch(shipper)
    h.touch(dispatch)
    K.recompute_all_sites()
    return K.single(dispatch)


def _reading_within_grace(shipper_id, instant, grace_minutes=LOGGER_READING_GRACE_MINUTES):
    target = parse_ts(instant)
    for r in h.all("logger_readings"):
        if r.get("cold_chain_shipper_id") != shipper_id:
            continue
        rec = parse_ts(r.get("recorded_at"))
        if rec is None:
            continue
        if abs((rec - target).total_seconds()) <= grace_minutes * 60:
            return r
    return None


@bp.route("/dispatches/<did>/deliver", methods=["POST"])
def deliver_dispatch(did):
    guard("POST /vaccine-distribution/dispatches/{id}/deliver")
    dispatch = K.fetch("dispatch_orders", did, "Dispatch")
    data = K.body()
    arrived_at_raw = K.as_ts(K.required(data, "arrived_at"), "arrived_at")
    arrived_at = parse_ts(arrived_at_raw)
    if dispatch.get("status") != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_TRANSIT dispatch may be delivered.")

    site = h.get("storage_sites", dispatch.get("storage_site_id"))
    order = h.get("site_orders", dispatch.get("site_order_id"))
    shippers = D.shippers_of_dispatch(dispatch["id"])

    # A delivery attempted while the shipper has not been released by a cold
    # chain reviewer is refused (PRD §3.5).
    for ship in shippers:
        if ship.get("packing_status") == "HELD":
            raise ApiError("ERR_SHIPPER_NOT_RELEASED")

    # The destination must hold a PASSED verification at the arrival instant.
    now = clock()
    passed = False
    for v in h.all("site_equipment_verifications"):
        if v.get("storage_site_id") != (site["id"] if site else None):
            continue
        if v.get("outcome") != "PASSED":
            continue
        exp = parse_ts(v.get("certificate_expires_at"))
        if exp is not None and exp > arrived_at:
            passed = True
            break
    if not passed:
        raise ApiError("ERR_DEST_CERT_EXPIRED_AT_DOCK")

    route = dispatch.get("entry_route")
    product = None
    if order:
        ent = D.entitlement_of(order)
        batch = D.batch_of_entitlement(ent) if ent else None
        product = D.product_of_batch(batch)

    cartons = D.cartons_of_dispatch(dispatch)
    destination = h.get("storage_sites", dispatch.get("storage_site_id"))
    ultra_cold_capacity = destination.get("ultra_cold_capacity_cartons", 0) if destination else 0
    already_ultra_cold = 0
    if destination:
        already_ultra_cold = len([
            c for c in D.cartons_at_site(destination["id"])
            if c.get("temperature_state") in ("ULTRA_COLD", "IN_TRANSIT")
            and c["id"] not in {x["id"] for x in cartons}
        ])

    staged_count = 0
    for carton in cartons:
        if route == "THAW_AT_HUB":
            carton["temperature_state"] = "REFRIGERATED"
            if carton.get("thawed_at") is None:
                carton["thawed_at"] = arrived_at_raw
            if product is not None:
                thawed = parse_ts(carton.get("thawed_at"))
                carton["current_expires_at"] = fmt(earlier(
                    parse_ts(D.batch_of_carton(carton).get("expiry_date")),
                    add_hours(thawed, product.get("refrigerated_shelf_life_hours", 0)),
                    add_hours(thawed, product.get("thaw_stability_hours", 0)),
                ))
            carton["thaw_window_expires_at"] = fmt(
                C.thaw_window_expiry(carton, carton.get("thawed_at"), staged_hop=True)
            )
        else:
            if carton.get("thawed_at") is not None:
                raise ApiError("ERR_REFREEZE_FORBIDDEN")
            if destination is not None and destination.get("reported_entry_type") == "ULTRA_COLD" \
                    and (already_ultra_cold + len(cartons)) > ultra_cold_capacity:
                carton["temperature_state"] = "PALLET_STAGED"
                staged_count += 1
                _park_with_excursion(carton, destination, arrived_at_raw)
            else:
                carton["temperature_state"] = "ULTRA_COLD"
        D.recompute_carton(carton)

    dispatch["status"] = "DELIVERED"
    h.touch(dispatch)
    if destination:
        D.recompute_site(destination)
    if order:
        order["order_status"] = "FULFILLED"
        order["payment_status"] = "DUE"
        h.touch(order)
        ent = D.entitlement_of(order)
        if ent:
            D.recompute_entitlement(ent)
            batch = D.batch_of_entitlement(ent)
            if batch:
                D.recompute_batch(batch)

    for ship in shippers:
        if ship.get("packing_status") == "IN_TRANSIT":
            if _reading_within_grace(ship["id"], arrived_at_raw):
                ship["packing_status"] = "RECEIVED"
                h.touch(ship)
    D.recompute_dispatch(dispatch)
    if staged_count:
        raise ApiError("ERR_SITE_CAPACITY_INSUFFICIENT")
    return K.single(dispatch)


def _park_with_excursion(carton, site, instant):
    """Park a carton and report an excursion against it (PRD §3.5)."""
    site["open_excursion_count"] = site.get("open_excursion_count", 0) + 1
    existing = [x for x in h.all("temperature_excursions")
                if x.get("carton_id") == carton["id"]
                and x.get("review_status") in ("REPORTED", "UNDER_REVIEW")]
    if existing:
        return
    product = D.product_of_carton(carton)
    h.create("temperature_excursions", {
        "carton_id": carton["id"],
        "storage_site_id": site["id"],
        "first_breach_at": instant,
        "last_breach_at": instant,
        "min_temperature_c": product.get("ultra_cold_max_c", -60) if product else -60,
        "reported_at": instant,
        "review_status": "REPORTED",
        "adjudication_status": "PENDING",
        "adjudicated_at": None,
        "min_duration_minutes": 0,
        "dosing_hours_remaining_at_breach": 0.0,
        "exceeds_cumulative_cap": False,
        "dose_impact_category": "NONE",
        "dose_impact_factor": 0.0,
        "quarantine_status": "OPEN",
        "current_resolution_trace_id": None,
        "_ready_at_first_phase": 0,
    })
    h.touch(carton)


def _dock_inspection_failed(dispatch, order):
    """True when the dock inspection actually failed (PRD §3.5).

    PRD names two legitimate bases: "the destination's equipment certificate expired
    at arrival, or a pack hold was raised in transit".  A return leg whose order is
    already under a dock dispute is the same shipment being refused a second time,
    so the basis carries with it.
    """
    site = h.get("storage_sites", dispatch.get("storage_site_id"))
    arrived = parse_ts(dispatch.get("eta_at")) or clock()
    for v in h.all("site_equipment_verifications"):
        if v.get("storage_site_id") != (site["id"] if site else None):
            continue
        if v.get("outcome") != "PASSED":
            continue
        exp = parse_ts(v.get("certificate_expires_at"))
        if exp is not None and exp <= arrived:
            return True
    for ship in D.shippers_of_dispatch(dispatch["id"]):
        if ship.get("packing_status") == "HELD":
            return True
    if order is not None and order.get("payment_status") == "DISPUTED":
        return True
    return False


@bp.route("/dispatches/<did>/reject-at-dock", methods=["POST"])
def reject_at_dock(did):
    guard("POST /vaccine-distribution/dispatches/{id}/reject-at-dock")
    dispatch = K.fetch("dispatch_orders", did, "Dispatch")
    data = K.body()
    K.required(data, "reason_code")
    if dispatch.get("status") != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_TRANSIT dispatch may be refused at the dock.")
    order = h.get("site_orders", dispatch.get("site_order_id"))
    if not _dock_inspection_failed(dispatch, order):
        raise ApiError("ERR_DOCK_REJECTION_REQUIRED")
    dispatch["status"] = "REJECTED_AT_DOCK"
    dispatch["reason_code"] = data["reason_code"]
    h.touch(dispatch)
    order = h.get("site_orders", dispatch.get("site_order_id"))
    if order:
        order["payment_status"] = "DISPUTED"
        h.touch(order)
    D.recompute_dispatch(dispatch)
    return K.single(dispatch)


# ---------------------------------------------------------------------------
# ColdChainShipper
# ---------------------------------------------------------------------------
@bp.route("/shippers", methods=["POST"])
def create_shipper():
    guard("POST /vaccine-distribution/shippers")
    data = K.body()
    dispatch = K.fetch("dispatch_orders", K.required(data, "dispatch_order_id"), "Dispatch")
    serial = K.as_str(K.required(data, "shipper_serial"), "shipper_serial")
    for existing in h.all("cold_chain_shippers"):
        if existing.get("shipper_serial") == serial:
            raise ApiError("ERR_INVALID_REQUEST", "shipper_serial must be unique.")
    rec = h.create("cold_chain_shippers", {
        "dispatch_order_id": dispatch["id"],
        "shipper_serial": serial,
        "dry_ice_kg": K.as_num(K.required(data, "dry_ice_kg"), "dry_ice_kg"),
        "packing_started_at": K.as_ts(K.required(data, "packing_started_at"), "packing_started_at"),
        "packing_completed_at": None,
        "logger_serial": K.opt_str(data, "logger_serial"),
        "packing_status": "PREPARING",
        "hold_reason": None,
        "payload_locked_at": None,
        "required_dry_ice_kg": 0,
        "dry_ice_deficit_kg": 0,
        "punctured_ice_slots": 0,
    })
    return K.created(rec)


@bp.route("/shippers", methods=["GET"])
def list_shippers():
    guard("GET /vaccine-distribution/shippers")
    return K.list_response(h.all("cold_chain_shippers"), {
        "dispatch_order_id": K.eq("dispatch_order_id"),
        "packing_status": K.eq("packing_status"),
    })


@bp.route("/shippers/<sid>", methods=["GET"])
def get_shipper(sid):
    guard("GET /vaccine-distribution/shippers/{id}")
    return K.single(K.fetch("cold_chain_shippers", sid, "Cold chain shipper"))


@bp.route("/shippers/<sid>/cartons", methods=["GET"])
def list_shipper_cartons(sid):
    guard("GET /vaccine-distribution/shippers/{id}/cartons")
    K.fetch("cold_chain_shippers", sid, "Cold chain shipper")
    return K.list_response(h.find("cartons", cold_chain_shipper_id=sid))


@bp.route("/shippers/<sid>/attach-carton", methods=["POST"])
def attach_carton(sid):
    guard("POST /vaccine-distribution/shippers/{id}/attach-carton")
    shipper = K.fetch("cold_chain_shippers", sid, "Cold chain shipper")
    data = K.body()
    carton = K.fetch("cartons", K.required(data, "carton_id"), "Carton")
    if shipper.get("packing_status") != "PREPARING":
        raise ApiError("ERR_INVALID_STATE", "Cartons may only be attached while preparing.")
    if shipper.get("payload_locked_at") and carton.get("cold_chain_shipper_id") != shipper["id"] \
            and False:
        raise ApiError("ERR_INVALID_STATE", "The payload is locked.")
    carton["cold_chain_shipper_id"] = shipper["id"]
    h.touch(carton)
    if shipper.get("payload_locked_at") is None:
        shipper["payload_locked_at"] = h.now_iso()
    D.recompute_shipper(shipper)
    return K.single(shipper)


@bp.route("/shippers/<sid>/seal", methods=["POST"])
def seal_shipper(sid):
    guard("POST /vaccine-distribution/shippers/{id}/seal")
    shipper = K.fetch("cold_chain_shippers", sid, "Cold chain shipper")
    data = K.body()
    if shipper.get("packing_status") != "PREPARING":
        raise ApiError("ERR_INVALID_STATE", "Only a PREPARING shipper may be sealed.")
    # The optimistic concurrency check runs against the stored version before any
    # recomputation touches it.
    expected = data.get("expected_shipper_version")
    if expected is not None:
        if K.as_int(expected, "expected_shipper_version") != shipper.get("version", 0):
            raise ApiError("ERR_STALE_VERSION")
    D.recompute_shipper(shipper)
    # Three packing preconditions gate the seal; when any fails the transition is
    # refused with ERR_SHIPPER_HOLD and packing_status stays PREPARING.
    failures = []
    if (shipper.get("dry_ice_kg") or 0) < shipper.get("required_dry_ice_kg", 0):
        failures.append("ERR_DRY_ICE_INSUFFICIENT")
    if not shipper.get("logger_serial"):
        failures.append("ERR_LOGGER_MISSING")
    started = parse_ts(shipper.get("packing_started_at"))
    completed = clock()
    if started is not None and (completed - started).total_seconds() / 3600.0 > 48:
        failures.append("ERR_PACKING_EXCEEDED")
    if failures:
        raise ApiError("ERR_SHIPPER_HOLD",
                       "Packing precondition failed: %s" % ", ".join(failures))
    shipper["packing_status"] = "SEALED"
    shipper["packing_completed_at"] = fmt(completed)
    # The derived recomputation above already refreshed updated_at and advanced
    # version by one; PRD 2.5 counts the seal as a single modification.
    return K.single(shipper)


@bp.route("/shippers/<sid>/hold", methods=["POST"])
def hold_shipper(sid):
    guard("POST /vaccine-distribution/shippers/{id}/hold")
    shipper = K.fetch("cold_chain_shippers", sid, "Cold chain shipper")
    data = K.body()
    if not K.has(data, "hold_reason"):
        raise ApiError("ERR_INVALID_REQUEST", "hold_reason is required.")
    reason = data["hold_reason"]
    if reason not in HOLD_REASONS:
        raise ApiError("ERR_REJECTION_REASON_INVALID")
    if shipper.get("packing_status") != "RECEIVED":
        raise ApiError("ERR_INVALID_REQUEST", "Only a RECEIVED shipper may be held.")
    shipper["packing_status"] = "HELD"
    shipper["hold_reason"] = reason
    h.touch(shipper)
    return K.single(shipper)


@bp.route("/shippers/<sid>/release", methods=["POST"])
def release_shipper(sid):
    guard("POST /vaccine-distribution/shippers/{id}/release")
    shipper = K.fetch("cold_chain_shippers", sid, "Cold chain shipper")
    status = shipper.get("packing_status")
    if status not in ("RECEIVED", "HELD"):
        raise ApiError("ERR_INVALID_STATE", "Only a RECEIVED or HELD shipper may be released.")
    cartons = D.cartons_of_shipper(shipper["id"])
    if status == "RECEIVED":
        if shipper.get("hold_reason"):
            raise ApiError("ERR_HOLD_NOT_CLEARED")
        pending = False
        for carton in cartons:
            for exc in D.excursions_of_carton(carton["id"]):
                if exc.get("adjudication_status") == "PENDING":
                    pending = True
        if pending:
            raise ApiError("ERR_PENDING_EXCURSION")
        product = None
        for carton in cartons:
            product = D.product_of_carton(carton)
            if product:
                break
        if product is not None:
            total = 0
            for carton in cartons:
                for exc in D.excursions_of_carton(carton["id"]):
                    total += exc.get("min_duration_minutes", 0) or 0
            if total > product.get("excursion_max_cumulative_minutes", 0):
                raise ApiError("ERR_EXCURSION_EXCEEDS_CAP")
    else:
        if shipper.get("hold_reason"):
            raise ApiError("ERR_HOLD_NOT_CLEARED")
    shipper["packing_status"] = "RELEASED"
    shipper["hold_reason"] = None
    h.touch(shipper)
    site = h.get("storage_sites", _destination_of_dispatch(shipper))
    if site:
        D.recompute_site(site)
    return K.single(shipper)


def _destination_of_dispatch(shipper):
    dispatch = h.get("dispatch_orders", shipper.get("dispatch_order_id"))
    return dispatch.get("storage_site_id") if dispatch else None


# ---------------------------------------------------------------------------
# TemperatureLoggerReading
# ---------------------------------------------------------------------------
@bp.route("/logger-readings", methods=["POST"])
def create_reading():
    guard("POST /vaccine-distribution/logger-readings")
    data = K.body()
    shipper = K.fetch("cold_chain_shippers", K.required(data, "cold_chain_shipper_id"),
                      "Cold chain shipper")
    recorded_at = K.as_ts(K.required(data, "recorded_at"), "recorded_at")
    temperature = K.as_num(K.required(data, "temperature_c"), "temperature_c")
    source = K.as_enum(K.required(data, "source"), READING_SOURCES, "source")
    product = _product_for_shipper(shipper)
    band_low = product.get("ultra_cold_min_c", -90) if product else -90
    band_high = product.get("ultra_cold_max_c", -60) if product else -60
    breach = 0
    if temperature < band_low or temperature > band_high:
        breach = 15
    rec = h.create("logger_readings", {
        "cold_chain_shipper_id": shipper["id"],
        "recorded_at": recorded_at,
        "temperature_c": temperature,
        "source": source,
        "breach_minutes": breach,
    })
    h.touch(shipper)
    return K.created(rec)


def _product_for_shipper(shipper):
    dispatch = h.get("dispatch_orders", shipper.get("dispatch_order_id"))
    if not dispatch:
        return None
    order = h.get("site_orders", dispatch.get("site_order_id"))
    if not order:
        return None
    ent = D.entitlement_of(order)
    batch = D.batch_of_entitlement(ent) if ent else None
    return D.product_of_batch(batch)


@bp.route("/logger-readings", methods=["GET"])
def list_readings():
    guard("GET /vaccine-distribution/logger-readings")
    return K.list_response(h.all("logger_readings"), {
        "cold_chain_shipper_id": K.eq("cold_chain_shipper_id"),
        "source": K.eq("source"),
    })


@bp.route("/logger-readings/<rid>", methods=["GET"])
def get_reading(rid):
    guard("GET /vaccine-distribution/logger-readings/{id}")
    return K.single(K.fetch("logger_readings", rid, "Logger reading"))