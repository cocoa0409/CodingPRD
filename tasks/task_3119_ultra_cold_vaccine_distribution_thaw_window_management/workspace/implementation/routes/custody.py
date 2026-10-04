"""Carton thaw window and lifecycle, dose ledger, transfers, reservations."""
from flask import Blueprint

from errors import ApiError
from helpers import h
from middleware import guard
from clockutil import parse_ts, clock, fmt, add_hours, add_minutes, earlier, diff_hours_rounded
from services import derive as D
from services import calc as C
from routes import common as K
from routes.reference import _append_entry, _site_for_carton

bp = Blueprint("custody", __name__)

LEDGER_TYPES = ["RELEASE", "THAW", "TRANSFER_IN", "TRANSFER_OUT", "ADMINISTER",
                "PUNCTURE", "EXPIRE", "WASTE", "DESTROY", "REVERSE"]
LEDGER_STATUSES = ["RECORDED", "RECONCILED"]
TRANSFER_LAPSE_REASONS = ["WINDOW_EXPIRED", "DEST_ADMISSIBILITY_FAILED",
                          "DEST_STANDING_FROZEN", "REFREEZE_FORBIDDEN"]
RESERVATION_STATUSES = ["HELD", "CONFIRMED", "RELEASED", "LAPSED"]
RESOLVE_METHODS = ["RESERVATION_BOUNDARY", "CAPACITY_POOLED"]
TEMP_STATES = ["FROZEN", "THAWED"]
DESTROYABLE = ["ULTRA_COLD", "REFRIGERATED", "THAWED", "PALLET_STAGED"]


def _staged_hop(carton):
    """True when the carton travelled a THAW_AT_HUB staging hop."""
    return carton.get("thawed_at") is not None and \
        carton.get("temperature_state") in ("REFRIGERATED", "THAWED", "PUNCTURED")


# ---------------------------------------------------------------------------
# Carton lifecycle
# ---------------------------------------------------------------------------
@bp.route("/cartons/<cid>/thaw", methods=["POST"])
def thaw_carton(cid):
    guard("POST /vaccine-distribution/cartons/{id}/thaw")
    carton = K.fetch("cartons", cid, "Carton")
    state = carton.get("temperature_state")
    if state == "IN_TRANSIT":
        raise ApiError("ERR_CARTON_IN_TRANSIT")
    if state == "DESTROYED":
        raise ApiError("ERR_CARTON_DESTROYED")
    entries = D.entries_of_carton(carton["id"])
    if any(e.get("entry_type") == "EXPIRE" for e in entries):
        raise ApiError("ERR_CARTON_EXPIRED")
    site = _site_for_carton(carton)
    if site:
        site_rec = h.get("storage_sites", site)
        if site_rec and site_rec.get("inventory_status") in ("RESTRICTED", "FROZEN"):
            raise ApiError("ERR_SITE_RESTRICTED")
    now = clock()
    current = parse_ts(carton.get("current_expires_at"))
    thaw_window = parse_ts(carton.get("thaw_window_expires_at"))
    if (current is not None and current <= now) or (thaw_window is not None and thaw_window <= now):
        raise ApiError("ERR_CARTON_EXPIRED")

    batch = D.batch_of_carton(carton)
    product = D.product_of_batch(batch)
    carton["temperature_state"] = "THAWED"
    carton["thawed_at"] = fmt(now)
    staged = carton.get("_staged_hop", False)
    carton["thaw_window_expires_at"] = fmt(C.thaw_window_expiry(carton, now, staged_hop=staged))
    carton["current_expires_at"] = fmt(
        C.beyond_use_for_carton(carton, thawed_at=now, staged_hop=staged)
    )
    _append_entry(carton, "THAW", 0, fmt(now))
    D.recompute_carton(carton)
    D.recompute_sites_for_carton(carton)
    return K.single(carton)


@bp.route("/cartons/<cid>/puncture", methods=["POST"])
def puncture_carton(cid):
    guard("POST /vaccine-distribution/cartons/{id}/puncture")
    carton = K.fetch("cartons", cid, "Carton")
    state = carton.get("temperature_state")
    entries = D.entries_of_carton(carton["id"])
    if not any(e.get("entry_type") == "ADMINISTER" for e in entries):
        raise ApiError("ERR_CARTON_NOT_IN_USE")
    if state == "PUNCTURED":
        raise ApiError("ERR_ALREADY_PUNCTURED")
    if state not in ("REFRIGERATED", "THAWED"):
        raise ApiError("ERR_INVALID_STATE", "Only a THAWED or REFRIGERATED carton may be punctured.")
    batch = D.batch_of_carton(carton)
    product = D.product_of_batch(batch)
    now = clock()
    if state == "REFRIGERATED":
        current = parse_ts(carton.get("current_expires_at"))
        if current is not None and not (now < current):
            raise ApiError("ERR_CARTON_EXPIRED")
    # From THAWED this is the carton's first puncture, so no earlier puncture
    # limit can tighten the beyond-use date (PRD §3.6).
    puncture_limit = add_hours(now, product.get("punctured_bud_hours", 0))
    carton["temperature_state"] = "PUNCTURED"
    carton["_puncture_at"] = fmt(now)
    existing = carton.get("current_expires_at")
    carton["current_expires_at"] = fmt(
        puncture_limit if state == "THAWED"
        else earlier(parse_ts(existing), puncture_limit)
    )
    _append_entry(carton, "PUNCTURE", 0, fmt(now))
    D.recompute_carton(carton)
    return K.single(carton)


@bp.route("/cartons/<cid>/refreeze", methods=["POST"])
def refreeze_carton(cid):
    guard("POST /vaccine-distribution/cartons/{id}/refreeze")
    carton = K.fetch("cartons", cid, "Carton")
    batch = D.batch_of_carton(carton)
    product = D.product_of_batch(batch)
    if carton.get("temperature_state") != "PALLET_STAGED":
        raise ApiError("ERR_INVALID_STATE", "Only a PALLET_STAGED carton may be refrozen.")
    if product is not None and product.get("refreeze_prohibited"):
        raise ApiError("ERR_REFREEZE_PROHIBITED")
    if not any(x.get("adjudication_status") == "USABLE"
               for x in D.excursions_of_carton(carton["id"])):
        raise ApiError("ERR_EXCURSION_PENDING_REVIEW")
    carton["temperature_state"] = "ULTRA_COLD"
    carton["thawed_at"] = None
    carton["thaw_window_expires_at"] = None
    carton["current_expires_at"] = batch.get("expiry_date") if batch else None
    carton["_puncture_at"] = None
    D.recompute_carton(carton)
    D.recompute_sites_for_carton(carton)
    return K.single(carton)


@bp.route("/cartons/<cid>/advance-logical-state", methods=["POST"])
def advance_logical_state(cid):
    guard("POST /vaccine-distribution/cartons/{id}/advance-logical-state")
    carton = K.fetch("cartons", cid, "Carton")
    data = K.body()
    target = K.as_enum(K.required(data, "target_state"),
                       ["THAWED", "REFRIGERATED", "ULTRA_COLD", "PUNCTURED", "PALLET_STAGED"],
                       "target_state")
    if not any(x.get("adjudication_status") == "USABLE"
               for x in D.excursions_of_carton(carton["id"])):
        raise ApiError("ERR_EXCURSION_PENDING_REVIEW")
    carton["temperature_state"] = target
    carton["thawed_at"] = h.now_iso()
    carton["thaw_window_expires_at"] = fmt(C.thaw_window_expiry(carton, clock()))
    carton["current_expires_at"] = fmt(C.beyond_use_for_carton(carton))
    D.recompute_carton(carton)
    D.recompute_sites_for_carton(carton)
    return K.single(carton)


@bp.route("/cartons/<cid>/destroy", methods=["POST"])
def destroy_carton(cid):
    guard("POST /vaccine-distribution/cartons/{id}/destroy")
    carton = K.fetch("cartons", cid, "Carton")
    data = K.body()
    K.required(data, "reason")
    reservable_states = ["ULTRA_COLD", "REFRIGERATED", "THAWED", "PALLET_STAGED"]
    state = carton.get("temperature_state")
    # DESTROYED is a terminal state of the Carton machine, so a second destruction
    # surfaces through the terminal-state check (PRD §2.9) rather than the
    # operative-state check.
    K.ensure_not_terminal(carton, "cartons", "temperature_state")
    if state == "IN_TRANSIT":
        raise ApiError("ERR_CARTON_IN_TRANSIT")
    if state not in reservable_states:
        raise ApiError("ERR_INVALID_STATE", "This carton state does not admit destruction.")
    excursions = D.excursions_of_carton(carton["id"])
    if any(x.get("review_status") in ("REPORTED", "UNDER_REVIEW") for x in excursions):
        raise ApiError("ERR_PENDING_EXCURSION")
    if not any(x.get("adjudication_status") == "NOT_USABLE" for x in excursions):
        raise ApiError("ERR_EXCURSION_PENDING_REVIEW")
    carton["temperature_state"] = "DESTROYED"
    _append_entry(carton, "DESTROY", -carton.get("remaining_doses", 0), h.now_iso())
    D.recompute_carton(carton)
    D.recompute_sites_for_carton(carton)
    _maybe_deplete_batch(D.batch_of_carton(carton))
    return K.single(carton)


def _maybe_deplete_batch(batch):
    if not batch or batch.get("status") != "ALLOCATED":
        return
    cartons = D.cartons_of_batch(batch["id"])
    if cartons and all(c.get("temperature_state") == "DESTROYED" for c in cartons):
        batch["status"] = "DEPLETED"
        h.touch(batch)


@bp.route("/cartons/<cid>/ledger-entries", methods=["GET"])
def carton_entries(cid):
    guard("GET /vaccine-distribution/cartons/{id}/ledger-entries")
    K.fetch("cartons", cid, "Carton")
    return K.list_response(D.entries_of_carton(cid))


@bp.route("/cartons/<cid>/excursions", methods=["GET"])
def carton_excursions(cid):
    guard("GET /vaccine-distribution/cartons/{id}/excursions")
    K.fetch("cartons", cid, "Carton")
    return K.list_response(D.excursions_of_carton(cid))


@bp.route("/cartons/<cid>/reservations", methods=["GET"])
def carton_reservations(cid):
    guard("GET /vaccine-distribution/cartons/{id}/reservations")
    K.fetch("cartons", cid, "Carton")
    return K.list_response(D.reservations_of_carton(cid))


# ---------------------------------------------------------------------------
# DoseLedgerEntry
# ---------------------------------------------------------------------------
@bp.route("/dose-ledger-entries", methods=["POST"])
def create_entry():
    guard("POST /vaccine-distribution/dose-ledger-entries")
    data = K.body()
    carton = K.fetch("cartons", K.required(data, "carton_id"), "Carton")
    entry_type = K.as_enum(K.required(data, "entry_type"), LEDGER_TYPES, "entry_type")
    quantity = K.as_int(K.required(data, "quantity_doses"), "quantity_doses")
    occurred_at = K.as_ts(K.required(data, "occurred_at"), "occurred_at")
    reverses = K.opt_str(data, "reverses_entry_id")

    if entry_type == "REVERSE":
        if not reverses:
            raise ApiError("ERR_INVALID_REQUEST", "reverses_entry_id is required on a REVERSE entry.")
        target = h.get("dose_ledger_entries", reverses)
        if target is None or target.get("carton_id") != carton["id"]:
            raise ApiError("ERR_INVALID_REQUEST",
                           "reverses_entry_id must name an entry on the same carton.")
        already = [e for e in h.all("dose_ledger_entries")
                   if e.get("entry_type") == "REVERSE" and e.get("reverses_entry_id") == target["id"]]
        if already:
            raise ApiError("ERR_REVERSAL_DRIFT_DETECTED")
        if carton.get("dose_shortfall_doses", 0) > 0:
            has_terminal = any(e.get("entry_type") in ("EXPIRE", "DESTROY")
                               for e in D.entries_of_carton(carton["id"]))
            if not has_terminal:
                raise ApiError("ERR_REVERSAL_DRIFT_DETECTED")
        if abs(quantity) != abs(target.get("quantity_doses", 0)):
            raise ApiError("ERR_INVALID_REQUEST",
                           "A REVERSE entry must carry the negated value it reverses.")
        if target.get("status") == "RECONCILED":
            target["status"] = "RECORDED"
            h.touch(target)
            _reopen_wastage_for(target)
    else:
        if quantity < 0 and abs(quantity) > carton.get("remaining_doses", 0):
            raise ApiError("ERR_DOSE_ACCOUNTABILITY_MISMATCH")

    rec = h.create("dose_ledger_entries", {
        "carton_id": carton["id"],
        "entry_type": entry_type,
        "quantity_doses": quantity,
        "occurred_at": occurred_at,
        "site_id": _site_for_carton(carton),
        "reverses_entry_id": reverses,
        "status": "RECORDED",
    })
    D.recompute_carton(carton)
    site_id = rec.get("site_id")
    if site_id:
        site = h.get("storage_sites", site_id)
        if site:
            D.recompute_site(site)
    return K.created(rec)


def _reopen_wastage_for(entry):
    for report in h.all("wastage_reports"):
        if report.get("dose_accountability_status") == "RECONCILED":
            adj = h.get("excursion_adjudications", report.get("excursion_adjudication_id"))
            if adj and adj.get("temperature_excursion_id"):
                exc = h.get("temperature_excursions", adj["temperature_excursion_id"])
                if exc and exc.get("carton_id") == entry.get("carton_id"):
                    report["dose_accountability_status"] = "OPEN"
                    report["reconciliation_variance_doses"] = \
                        report.get("doses_reported", 0) - report.get("certified_doses", 0)
                    h.touch(report)


@bp.route("/dose-ledger-entries", methods=["GET"])
def list_entries():
    guard("GET /vaccine-distribution/dose-ledger-entries")
    return K.list_response(h.all("dose_ledger_entries"), {
        "carton_id": K.eq("carton_id"),
        "entry_type": K.eq("entry_type"),
        "status": K.eq("status"),
        "reverses_entry_id": K.eq("reverses_entry_id"),
    })


@bp.route("/dose-ledger-entries/<eid>", methods=["GET"])
def get_entry(eid):
    guard("GET /vaccine-distribution/dose-ledger-entries/{id}")
    return K.single(K.fetch("dose_ledger_entries", eid, "Dose ledger entry"))


@bp.route("/dose-ledger-entries/<eid>/reverse", methods=["POST"])
def reverse_entry(eid):
    guard("POST /vaccine-distribution/dose-ledger-entries/{id}/reverse")
    entry = K.fetch("dose_ledger_entries", eid, "Dose ledger entry")
    data = K.body()
    occurred_at = K.as_ts(K.required(data, "occurred_at"), "occurred_at")
    carton = K.fetch("cartons", entry.get("carton_id"), "Carton")
    already = [e for e in h.all("dose_ledger_entries")
               if e.get("entry_type") == "REVERSE" and e.get("reverses_entry_id") == entry["id"]]
    if already:
        raise ApiError("ERR_REVERSAL_DRIFT_DETECTED")
    rec = h.create("dose_ledger_entries", {
        "carton_id": carton["id"],
        "entry_type": "REVERSE",
        "quantity_doses": -entry.get("quantity_doses", 0),
        "occurred_at": occurred_at,
        "site_id": entry.get("site_id"),
        "reverses_entry_id": entry["id"],
        "status": "RECORDED",
    })
    if entry.get("status") == "RECONCILED":
        entry["status"] = "RECORDED"
        h.touch(entry)
        _reopen_wastage_for(entry)
    D.recompute_carton(carton)
    return K.created(rec)


# ---------------------------------------------------------------------------
# SiteTransfer
# ---------------------------------------------------------------------------
def _dest_required_entry_type(carton, site):
    state = carton.get("temperature_state")
    if state in ("ULTRA_COLD", "IN_TRANSIT"):
        return "ULTRA_COLD"
    return "REFRIGERATED"


def _admissibility(site, required, carton):
    if site is None:
        return "NOT_ADMITTED"
    if not site.get("equipment_certified"):
        return "NOT_ADMITTED"
    cap = site.get("storage_capability")
    if required == "ULTRA_COLD":
        return "ADMITTED" if cap == "ULTRA_COLD" else "NOT_ADMITTED"
    return "ADMITTED" if cap in ("ULTRA_COLD", "REFRIGERATED") else "NOT_ADMITTED"


@bp.route("/site-transfers", methods=["POST"])
def create_transfer():
    guard("POST /vaccine-distribution/site-transfers")
    data = K.body()
    from_site = K.fetch("storage_sites", K.required(data, "from_site_id"), "Origin site")
    to_site = K.fetch("storage_sites", K.required(data, "to_site_id"), "Destination site")
    carton = K.fetch("cartons", K.required(data, "carton_id"), "Carton")
    requested_at = K.as_ts(K.required(data, "requested_at"), "requested_at")
    required = _dest_required_entry_type(carton, to_site)
    # PRD 3.7: "on creation it computes hours_remaining_at_request as the thaw-window
    # hours left at that instant" -- the instant being the request, which the server
    # reads from its logical clock.  Taking the difference against the caller-supplied
    # `requested_at` would let a client move the carton's horizon by hand.
    thaw_window = parse_ts(carton.get("thaw_window_expires_at"))
    hours = 0.0
    if thaw_window is not None:
        hours = max(0.0, diff_hours_rounded(thaw_window, clock(), 4))
    rec = h.create("site_transfers", {
        "from_site_id": from_site["id"],
        "to_site_id": to_site["id"],
        "carton_id": carton["id"],
        "requested_at": requested_at,
        "status": "REQUESTED",
        "hours_remaining_at_request": hours,
        "dest_required_entry_type": required,
        "admissibility": _admissibility(to_site, required, carton),
        "reservation_expires_at": None,
        "cumulative_conflict_minutes": 0,
        "freeze_required": bool(to_site.get("reported_entry_type") == "ULTRA_COLD"),
        "lapse_reason": None,
        "_pending_conflict_minutes": 0,
    })
    return K.created(rec)


@bp.route("/site-transfers", methods=["GET"])
def list_transfers():
    guard("GET /vaccine-distribution/site-transfers")
    return K.list_response(h.all("site_transfers"), {
        "from_site_id": K.eq("from_site_id"),
        "to_site_id": K.eq("to_site_id"),
        "carton_id": K.eq("carton_id"),
        "status": K.eq("status"),
    })


@bp.route("/site-transfers/<tid>", methods=["GET"])
def get_transfer(tid):
    guard("GET /vaccine-distribution/site-transfers/{id}")
    return K.single(K.fetch("site_transfers", tid, "Site transfer"))


@bp.route("/site-transfers/<tid>/approve", methods=["POST"])
def approve_transfer(tid):
    guard("POST /vaccine-distribution/site-transfers/{id}/approve")
    tr = K.fetch("site_transfers", tid, "Site transfer")
    if tr.get("status") != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED transfer may be approved.")
    origin = h.get("storage_sites", tr.get("from_site_id"))
    dest = h.get("storage_sites", tr.get("to_site_id"))
    carton = h.get("cartons", tr.get("carton_id"))
    if origin is None or origin.get("inventory_status") != "OPEN":
        raise ApiError("ERR_SITE_RESTRICTED")
    if dest is None or not dest.get("equipment_certified"):
        raise ApiError("ERR_DEST_EQUIPMENT_NOT_CERTIFIED")
    required = _dest_required_entry_type(carton, dest)
    tr["dest_required_entry_type"] = required
    cap = dest.get("storage_capability")
    if required == "ULTRA_COLD" and cap != "ULTRA_COLD":
        raise ApiError("ERR_DEST_CAPABILITY_MISMATCH")
    if required == "REFRIGERATED" and cap not in ("ULTRA_COLD", "REFRIGERATED"):
        raise ApiError("ERR_DEST_CAPABILITY_MISMATCH")
    now = clock()
    current = parse_ts(carton.get("current_expires_at"))
    if current is not None and not (now < current):
        raise ApiError("ERR_CARTON_EXPIRED")
    # A single carton is not a shipper payload, so the presentation's minimum
    # order is never charged against it here (PRD §3.7 takes the shipper-payload
    # shortfall on the dispatch, where a payload actually exists).

    tr["status"] = "APPROVED"
    tr["admissibility"] = "ADMITTED"
    start = parse_ts(tr.get("requested_at"))
    program = h.get("jurisdiction_programs", dest.get("jurisdiction_program_id"))
    end = add_hours(start, program.get("acceptance_window_hours", 0) if program else 0)
    tr["reservation_expires_at"] = fmt(end)

    conflict = C.check_reservation_capacity(dest, required, start, end,
                                           1, "CAPACITY_POOLED")
    tr["_pending_conflict_minutes"] = conflict
    reservation = h.create("carton_storage_reservations", {
        "storage_site_id": dest["id"],
        "carton_id": carton["id"],
        "entry_type": required,
        "temp_state": "FROZEN" if required == "ULTRA_COLD" else "THAWED",
        "reserved_capacity_cartons": 1,
        "start_at": tr.get("requested_at"),
        "end_at": fmt(end),
        "status": "HELD",
        "resolved_conflict_minutes": conflict,
        "_transfer_id": tr["id"],
    })
    h.touch(dest)
    h.touch(tr)
    return K.single(tr)


@bp.route("/site-transfers/<tid>/dispatch", methods=["POST"])
def dispatch_transfer(tid):
    guard("POST /vaccine-distribution/site-transfers/{id}/dispatch")
    tr = K.fetch("site_transfers", tid, "Site transfer")
    if tr.get("status") != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED transfer may be dispatched.")
    if tr.get("admissibility") != "ADMITTED":
        raise ApiError("ERR_TRANSFER_NOT_ADJUDICATED")
    carton = h.get("cartons", tr.get("carton_id"))
    now = clock()
    window = parse_ts(carton.get("thaw_window_expires_at"))
    if window is not None and not (now < window):
        raise ApiError("ERR_THAW_WINDOW_EXPIRED")
    reservation = _reservation_for_transfer(tr["id"])
    if reservation is None or reservation.get("status") not in ("HELD", "CONFIRMED"):
        raise ApiError("ERR_STORAGE_RESERVATION_CONFLICT")
    tr["status"] = "DISPATCHED"
    carton["temperature_state"] = "IN_TRANSIT"
    reservation["status"] = "HELD"
    h.touch(reservation)
    h.touch(carton)
    D.recompute_carton(carton)
    h.touch(tr)
    return K.single(tr)


def _reservation_for_transfer(transfer_id):
    for r in h.all("carton_storage_reservations"):
        if r.get("_transfer_id") == transfer_id:
            return r
    return None


@bp.route("/site-transfers/<tid>/receive", methods=["POST"])
def receive_transfer(tid):
    guard("POST /vaccine-distribution/site-transfers/{id}/receive")
    tr = K.fetch("site_transfers", tid, "Site transfer")
    data = K.body()
    received_at_raw = K.as_ts(K.required(data, "received_at"), "received_at")
    received_at = parse_ts(received_at_raw)
    if tr.get("status") != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", "Only a DISPATCHED transfer may be received.")
    carton = h.get("cartons", tr.get("carton_id"))
    dest = h.get("storage_sites", tr.get("to_site_id"))
    origin = h.get("storage_sites", tr.get("from_site_id"))
    if any(x.get("review_status") in ("REPORTED", "UNDER_REVIEW")
           for x in D.excursions_of_carton(carton["id"])):
        raise ApiError("ERR_PENDING_EXCURSION")

    reservation = _reservation_for_transfer(tr["id"])
    if reservation is not None:
        end = parse_ts(reservation.get("end_at"))
        if end is not None and clock() >= end:
            raise ApiError("ERR_RESERVATION_EXPIRED")

    required = tr.get("dest_required_entry_type")
    destination_report = dest.get("reported_entry_type")
    # PRD §3.7 parks the carton only when the destination's reported_entry_type
    # differs from dest_required_entry_type.  reported_entry_type is the
    # carton-count-weighted mode of the physical cartons the site holds, so the
    # comparison is taken with the arriving carton in place: a destination that
    # owns refrigerated capacity and holds nothing conflicting with the arrival
    # reports REFRIGERATED once the carton is in, and admits it; one whose only
    # cartons are frozen is the restricted destination of PRD §3.5 and parks it.
    if required == "REFRIGERATED" and destination_report != "REFRIGERATED" \
            and D.prospective_entry_type(dest, carton) != "REFRIGERATED":
        # the carton parks instead of being stored
        carton["temperature_state"] = "PALLET_STAGED"
        tr["status"] = "RECEIVED"
        if reservation is not None:
            reservation["status"] = "CONFIRMED"
            h.touch(reservation)
        h.touch(carton)
        D.recompute_carton(carton)
        D.recompute_site(dest)
        raise ApiError("ERR_DEST_RESTRICTED")
    now = clock()
    current = parse_ts(carton.get("current_expires_at"))
    if current is not None and not (now < current):
        raise ApiError("ERR_CARTON_EXPIRED")

    qty = carton.get("remaining_doses", 0)
    _append_entry(carton, "TRANSFER_OUT", -qty, received_at_raw)
    carton["temperature_state"] = "REFRIGERATED"
    h.touch(carton)
    rec_in = h.create("dose_ledger_entries", {
        "carton_id": carton["id"],
        "entry_type": "TRANSFER_IN",
        "quantity_doses": qty,
        "occurred_at": received_at_raw,
        "site_id": dest["id"],
        "reverses_entry_id": None,
        "status": "RECORDED",
    })
    tr["status"] = "RECEIVED"
    if reservation is not None:
        reservation["status"] = "CONFIRMED"
        h.touch(reservation)
    tr["cumulative_conflict_minutes"] = tr.get("_pending_conflict_minutes", 0)
    D.recompute_carton(carton)
    D.recompute_site(dest)
    D.recompute_site(origin)
    D.recompute_sites_for_carton(carton)
    h.touch(tr)
    return K.single(tr)


@bp.route("/site-transfers/<tid>/reject", methods=["POST"])
def reject_transfer(tid):
    guard("POST /vaccine-distribution/site-transfers/{id}/reject")
    tr = K.fetch("site_transfers", tid, "Site transfer")
    data = K.body()
    reason = K.required(data, "reason_code")
    status = tr.get("status")
    if status == "REQUESTED":
        if reason not in TRANSFER_LAPSE_REASONS:
            raise ApiError("ERR_INVALID_REQUEST", "reason_code is not a declared lapse reason.")
        tr["status"] = "REJECTED"
        tr["lapse_reason"] = reason
    elif status == "DISPATCHED":
        expires = parse_ts(tr.get("reservation_expires_at"))
        if expires is not None and clock() < expires:
            raise ApiError("ERR_TRANSFER_RESERVATION_ACTIVE")
        if reason not in ("WINDOW_EXPIRED", "REFREEZE_FORBIDDEN"):
            raise ApiError("ERR_INVALID_REQUEST", "reason_code is not a declared lapse reason.")
        carton = h.get("cartons", tr.get("carton_id"))
        carton["temperature_state"] = "PALLET_STAGED"
        h.touch(carton)
        D.recompute_carton(carton)
        tr["status"] = "REJECTED"
        tr["lapse_reason"] = reason
        reservation = _reservation_for_transfer(tr["id"])
        if reservation is not None:
            reservation["status"] = "LAPSED"
            h.touch(reservation)
    else:
        raise ApiError("ERR_INVALID_STATE", "This transfer cannot be rejected.")
    tr["reservation_expires_at"] = None
    h.touch(tr)
    D.recompute_all_sites()
    return K.single(tr)


@bp.route("/site-transfers/<tid>/cancel", methods=["POST"])
def cancel_transfer(tid):
    guard("POST /vaccine-distribution/site-transfers/{id}/cancel")
    tr = K.fetch("site_transfers", tid, "Site transfer")
    reservation = _reservation_for_transfer(tr["id"])
    # The reservation-CONFIRMED precondition is stated on the APPROVED→CANCELLED
    # transition itself (PRD §3.7: "it is refused with `ERR_INVALID_REQUEST` when the
    # reservation is already `CONFIRMED`"), so it is evaluated before both the
    # operative-state and the terminal-state check -- PRD §2.9 makes the ordering
    # between groups observable.
    if reservation is not None and reservation.get("status") == "CONFIRMED":
        raise ApiError("ERR_INVALID_REQUEST",
                       "A transfer whose reservation is already CONFIRMED cannot be cancelled.")
    if tr.get("status") != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED transfer may be cancelled.")
    K.ensure_not_terminal(tr, "site_transfers")
    tr["status"] = "CANCELLED"
    if reservation is not None:
        reservation["status"] = "RELEASED"
        end = parse_ts(reservation.get("end_at"))
        if end is not None and end <= clock():
            tr["lapse_reason"] = "WINDOW_EXPIRED"
        h.touch(reservation)
    tr["reservation_expires_at"] = None
    h.touch(tr)
    return K.single(tr)


# ---------------------------------------------------------------------------
# CartonStorageReservation
# ---------------------------------------------------------------------------
@bp.route("/carton-storage-reservations", methods=["POST"])
def create_reservation():
    guard("POST /vaccine-distribution/carton-storage-reservations")
    data = K.body()
    site = K.fetch("storage_sites", K.required(data, "storage_site_id"), "Storage site")
    carton = K.fetch("cartons", K.required(data, "carton_id"), "Carton")
    entry_type = K.as_enum(K.required(data, "entry_type"), ["ULTRA_COLD", "REFRIGERATED"],
                           "entry_type")
    temp_state = K.as_enum(K.required(data, "temp_state"), TEMP_STATES, "temp_state")
    qty = K.as_int(K.required(data, "reserved_capacity_cartons"), "reserved_capacity_cartons")
    start_at_raw = K.as_ts(K.required(data, "start_at"), "start_at")
    end_at_raw = K.as_ts(K.required(data, "end_at"), "end_at")
    start_at = parse_ts(start_at_raw)
    end_at = parse_ts(end_at_raw)
    if end_at <= start_at:
        raise ApiError("ERR_INVALID_REQUEST", "end_at must be after start_at.")
    method = K.opt_enum(data, "resolve_method", RESOLVE_METHODS, "RESERVATION_BOUNDARY")

    capacity = C.site_capacity(site, entry_type)
    if entry_type == "ULTRA_COLD" and site.get("storage_capability") == "AMBIENT_ONLY":
        raise ApiError("ERR_DEST_CAPABILITY_MISMATCH")

    conflict = C.check_reservation_capacity(site, entry_type, start_at, end_at, qty, method)
    if method == "RESERVATION_BOUNDARY" and qty > capacity:
        raise ApiError("ERR_SITE_CAPACITY_INSUFFICIENT")

    rec = h.create("carton_storage_reservations", {
        "storage_site_id": site["id"],
        "carton_id": carton["id"],
        "entry_type": entry_type,
        "temp_state": temp_state,
        "reserved_capacity_cartons": qty,
        "start_at": start_at_raw,
        "end_at": end_at_raw,
        "status": "HELD",
        "resolved_conflict_minutes": conflict,
    })
    h.touch(site)
    return K.created(rec)


@bp.route("/carton-storage-reservations", methods=["GET"])
def list_reservations():
    guard("GET /vaccine-distribution/carton-storage-reservations")
    return K.list_response(h.all("carton_storage_reservations"), {
        "storage_site_id": K.eq("storage_site_id"),
        "carton_id": K.eq("carton_id"),
        "entry_type": K.eq("entry_type"),
        "status": K.eq("status"),
    })


@bp.route("/carton-storage-reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    guard("GET /vaccine-distribution/carton-storage-reservations/{id}")
    return K.single(K.fetch("carton_storage_reservations", rid, "Carton storage reservation"))