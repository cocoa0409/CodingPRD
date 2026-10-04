"""Carton families, the logical clock and the deferred-action cycle."""
from flask import Blueprint

from errors import ApiError
from helpers import h
from db import STORE
from middleware import guard
from clockutil import parse_ts, clock, fmt, set_clock
from services import derive as D
from services import calc as C
from routes import common as K
from routes.reference import _append_entry

bp = Blueprint("ops", __name__)

EXPIRABLE_STATES = ["REFRIGERATED", "THAWED", "PUNCTURED", "ULTRA_COLD", "PALLET_STAGED"]


# ---------------------------------------------------------------------------
# CartonFamily
# ---------------------------------------------------------------------------
@bp.route("/carton-families", methods=["POST"])
def create_family():
    guard("POST /vaccine-distribution/carton-families")
    data = K.body()
    site = K.fetch("storage_sites", K.required(data, "site_id"), "Storage site")
    member = K.fetch("storage_sites", K.required(data, "member_site_id"), "Member site")
    linked_at = K.as_ts(K.required(data, "linked_at"), "linked_at")
    rec = h.create("carton_families", {
        "site_id": site["id"],
        "member_site_id": member["id"],
        "linked_at": linked_at,
        "shared_dose_count": 0,
    })
    # PRD 3.9: the call links "one site, site_id, to another, member_site_id, as TWO
    # MEMBERS OF ONE excursion-sharing family" -- one membership row, and the link is
    # read symmetrically (family_neighbours consults both endpoints), so no second
    # row is minted.
    D.recompute_site(site)
    D.recompute_site(member)
    for row in h.all("carton_families"):
        root = row.get("site_id")
        row["shared_dose_count"] = sum(
            (h.get("storage_sites", m) or {}).get("usable_doses", 0)
            for m in D.family_closure(root)
        )
        h.touch(row)
    return K.created(rec)


@bp.route("/carton-families", methods=["GET"])
def list_families():
    guard("GET /vaccine-distribution/carton-families")
    # A membership links two sites, so the site filter matches either endpoint.
    return K.list_response(h.all("carton_families"), {
        "site_id": K.either_site("site_id", "member_site_id"),
        "member_site_id": K.eq("member_site_id"),
    })


@bp.route("/carton-families/<fid>", methods=["GET"])
def get_family(fid):
    guard("GET /vaccine-distribution/carton-families/{id}")
    return K.single(K.fetch("carton_families", fid, "Carton family membership"))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    guard("POST /vaccine-distribution/_clock/set_current_utc")
    data = K.body()
    raw = K.required(data, "current_utc")
    target = K.as_ts(raw, "current_utc")
    set_clock(target)
    _sweep_expiry()
    return K.single({"current_utc": raw})


def _sweep_expiry():
    """Advancing the clock is never merely a number change (PRD §2.4).

    Every carton whose current_expires_at is at or before the new instant advances
    to EXPIRED and has administrative_expired recomputed as part of the same
    operation.
    """
    now = clock()
    for carton in h.all("cartons"):
        state = carton.get("temperature_state")
        if state in ("DESTROYED", "EXPIRED"):
            continue
        limit = parse_ts(carton.get("current_expires_at"))
        if limit is None or limit > now:
            continue
        if state not in EXPIRABLE_STATES:
            continue
        carton["temperature_state"] = "EXPIRED"
        carton["expired_at"] = fmt(limit)
        # Expiry appends an EXPIRE entry for the negated remaining doses; the
        # carton is physically present but carries no live doses thereafter.  The
        # expiry stamps themselves are left in place, because the carton and
        # transfer gates read them to decide that the window has passed.
        _append_entry(carton, "EXPIRE", -carton.get("remaining_doses", 0), h.now_iso())
        carton["remaining_doses"] = 0
        carton["administrative_remaining_doses"] = 0
        carton["cumulative_released_doses"] = 0
        D.recompute_carton(carton)
        carton["administrative_expired"] = True
    _sweep_batches(now)
    for site in h.all("storage_sites"):
        D.recompute_site(site)


def _sweep_batches(now):
    for batch in h.all("allocation_batches"):
        expiry = parse_ts(batch.get("expiry_date"))
        if expiry is None or now < expiry:
            continue
        status = batch.get("status")
        if status == "DRAFT" and batch.get("unallocated_cartons", 0) > 0:
            batch["status"] = "EXPIRED"
            h.touch(batch)
        elif status == "RELEASED":
            if batch.get("unallocated_cartons", 0) > 0:
                batch["status"] = "EXPIRED"
                for carton in D.cartons_of_batch(batch["id"]):
                    if carton.get("temperature_state") == "DESTROYED":
                        continue
                    carton["temperature_state"] = "DESTROYED"
                    _append_entry(carton, "DESTROY", 0, h.now_iso())
                    D.recompute_carton(carton)
                batch["unallocated_cartons"] = 0
                h.touch(batch)
        elif status == "ALLOCATED":
            batch["status"] = "EXPIRED"
            for carton in D.cartons_of_batch(batch["id"]):
                if carton.get("temperature_state") == "DESTROYED":
                    continue
                carton["temperature_state"] = "DESTROYED"
                _append_entry(carton, "DESTROY", 0, h.now_iso())
                D.recompute_carton(carton)
            h.touch(batch)
    return


def _sweep_reservations(now):
    """Advancing the clock lapses every elapsed HELD reservation (PRD §3.7).

    A reservation whose transfer never advanced past APPROVED is lapsed here
    too, so the reservation machine never reports an elapsed interval as HELD.
    """
    for reservation in h.all("carton_storage_reservations"):
        if reservation.get("status") != "HELD":
            continue
        end = parse_ts(reservation.get("end_at"))
        if end is not None and now >= end:
            reservation["status"] = "LAPSED"
            h.touch(reservation)
            transfer = h.get("site_transfers", reservation.get("_transfer_id"))
            if transfer and transfer.get("status") in ("REQUESTED", "APPROVED"):
                transfer["status"] = "REJECTED"
                transfer["lapse_reason"] = "WINDOW_EXPIRED"
                h.touch(transfer)


# ---------------------------------------------------------------------------
# Deferred-action cycle
# ---------------------------------------------------------------------------
@bp.route("/_ops/run-cycle", methods=["POST"])
def run_cycle():
    guard("POST /vaccine-distribution/_ops/run-cycle")
    now = clock()
    lapsed_reservations = 0
    lapsed_windows = 0

    # PRD 2.11: the cycle "lapses every HELD reservation whose end_at is at or before
    # the logical clock".  The associated transfer follows it into REJECTED when it
    # is still in flight (PRD 3.7), but the lapse itself is unconditional.
    for reservation in h.all("carton_storage_reservations"):
        if reservation.get("status") != "HELD":
            continue
        end = parse_ts(reservation.get("end_at"))
        if end is None or end > now:
            continue
        reservation["status"] = "LAPSED"
        h.touch(reservation)
        lapsed_reservations += 1
        transfer = h.get("site_transfers", reservation.get("_transfer_id"))
        if transfer is not None and transfer.get("status") in ("REQUESTED", "APPROVED"):
            transfer["status"] = "REJECTED"
            transfer["lapse_reason"] = "WINDOW_EXPIRED"
            h.touch(transfer)

    from routes.allocation import close_window
    for win in list(h.all("allocation_windows")):
        if win.get("status") != "OPEN":
            continue
        closes = parse_ts(win.get("closes_at"))
        if closes is None or now < closes:
            continue
        _close_window_side_effects(win, now)
        lapsed_windows += 1

    deferred = len(STORE.deferred_standings)
    for program_id in list(STORE.deferred_standings):
        program = h.get("jurisdiction_programs", program_id)
        if program:
            assessment = C.standing_assessment(program, now)
            program["standing_status"] = C.tier_to_standing(assessment["risk_tier"])
            h.touch(program)
            for site in h.all("storage_sites"):
                if site.get("jurisdiction_program_id") == program["id"]:
                    D.recompute_site(site)
    STORE.deferred_standings = []

    return K.single({
        "lapsed_reservation_count": lapsed_reservations,
        "lapsed_window_count": lapsed_windows,
        "deferred_standing_count": deferred,
    })


def _close_window_side_effects(win, now):
    win["status"] = "CLOSED"
    h.touch(win)
    program = h.get("jurisdiction_programs", win.get("jurisdiction_program_id"))
    batch = h.get("allocation_batches", win.get("allocation_batch_id"))
    for ent in D.entitlements_of_window(win["id"]):
        if ent.get("available_cartons", 0) <= 0:
            continue
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
        assessment = C.standing_assessment(program, now)
        program["standing_status"] = C.tier_to_standing(assessment["risk_tier"])
        h.touch(program)