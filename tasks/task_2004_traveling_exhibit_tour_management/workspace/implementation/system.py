"""System-performed transitions and cross-entity cascades (PRD §2.9, §3).

Every cascaded resource gets its own updated_at refresh and version bump.
"""

from datetime import timedelta

import db
import calc


# --- lookups -------------------------------------------------------------------

def stops_of_tour(tour_id):
    return [s for s in db.stops.values() if s["tour_id"] == tour_id]


def crates_of_tour(tour_id):
    return [c for c in db.crates.values() if c["tour_id"] == tour_id]


def shipments_of_tour(tour_id):
    return [s for s in db.shipments.values() if s["tour_id"] == tour_id]


def contracts_of_stop(stop_id):
    return [c for c in db.contracts.values() if c["tour_stop_id"] == stop_id]


def contracts_of_tour(tour_id):
    stop_ids = {s["id"] for s in stops_of_tour(tour_id)}
    return [c for c in db.contracts.values() if c["tour_stop_id"] in stop_ids]


def kits_of_stop(stop_id):
    return [k for k in db.kits.values() if k["tour_stop_id"] == stop_id]


def certs_of_tour(tour_id):
    return [c for c in db.certs.values() if c["tour_id"] == tour_id]


def claims_of_shipment(shipment_id):
    return [c for c in db.claims.values() if c["shipment_id"] == shipment_id]


def reports_of_shipment(shipment_id):
    return [r for r in db.reports.values() if r["shipment_id"] == shipment_id]


def live_contract(stop_id):
    """The one non-terminal contract on a stop, if any (latest created)."""
    live = [c for c in contracts_of_stop(stop_id) if c["status"] != "FINALIZED"]
    live.sort(key=lambda c: c["created_at"])
    return live[-1] if live else None


def live_kit(stop_id):
    """Latest non-RETIRED marketing kit on a stop, if any."""
    live = [k for k in kits_of_stop(stop_id) if k["status"] != "RETIRED"]
    live.sort(key=lambda k: k["created_at"])
    return live[-1] if live else None


# --- tour ledger ------------------------------------------------------------------

def recompute_billed(tour):
    total = sum(c["final_fee_cents"] or 0
                for c in contracts_of_tour(tour["id"])
                if c["status"] == "FINALIZED")
    tour["total_billed_cents"] = total
    db.touch(tour)


def finalize_contract(contract, final_fee_cents):
    contract["final_fee_cents"] = final_fee_cents
    contract["status"] = "FINALIZED"
    db.touch(contract)
    tour = db.tours.get(_tour_of_stop(contract["tour_stop_id"]))
    if tour is not None:
        recompute_billed(tour)


def _tour_of_stop(stop_id):
    stop = db.stops.get(stop_id)
    return stop["tour_id"] if stop else None


# --- fee computation helpers -------------------------------------------------------

def venue_of_stop(stop):
    return db.venues.get(stop["venue_id"])


def compute_provisional(contract, stop):
    venue = venue_of_stop(stop)
    return calc.participation_fee(contract["base_fee_cents"],
                                  contract["sponsorship_credit_cents"],
                                  venue["local_sponsorship_cap_cents"],
                                  stop["projected_attendance"])


def compute_final(contract, stop):
    venue = venue_of_stop(stop)
    return calc.participation_fee(contract["base_fee_cents"],
                                  contract["sponsorship_credit_cents"],
                                  venue["local_sponsorship_cap_cents"],
                                  stop["actual_attendance"])


# --- certificate clock sweep (PRD §2.4) ---------------------------------------------

def clock_set(to_dt):
    db.CLOCK["now"] = to_dt
    for cert in db.certs.values():
        if cert["status"] == "ISSUED" and db.parse_dt(cert["effective_from"]) <= to_dt:
            cert["status"] = "ACTIVE"
            db.touch(cert)
    for cert in db.certs.values():
        if cert["status"] == "ACTIVE" and db.parse_dt(cert["effective_to"]) <= to_dt:
            cert["status"] = "EXPIRED"
            db.touch(cert)


# --- stop cancellation cascade (PRD §3.8) ---------------------------------------------

def _retire_kits(stop_id):
    for kit in kits_of_stop(stop_id):
        if kit["status"] in ("PLANNED", "PRODUCED"):
            kit["status"] = "RETIRED"
            db.touch(kit)


def _void_certs(stop_id):
    for cert in db.certs.values():
        if cert["tour_stop_id"] == stop_id and cert["status"] in ("ISSUED", "ACTIVE"):
            cert["status"] = "VOID"
            db.touch(cert)


def cancel_stop(stop):
    """TENTATIVE cancel is free (final fee 0); CONTRACTED cancel exacts the
    FINAL_CANCEL penalty. Both retire live kits and void live certificates."""
    if stop["status"] == "TENTATIVE":
        contract = live_contract(stop["id"])
        if contract is not None:
            finalize_contract(contract, 0)
    elif stop["status"] == "CONTRACTED":
        contract = live_contract(stop["id"])
        if contract is not None:
            provisional = contract["provisional_fee_cents"]
            finalize_contract(contract, calc.cancel_penalty_fee(provisional or 0))
        _retire_kits(stop["id"])
        _void_certs(stop["id"])
    stop["status"] = "CANCELLED"
    db.touch(stop)


# --- stop close: finalization + refurbishment trigger (PRD §3.8, §3.9) -----------------

def close_stop_effects(stop, tour):
    contract = live_contract(stop["id"])
    if contract is not None and contract["status"] == "SIGNED":
        finalize_contract(contract, compute_final(contract, stop))
    maybe_enter_refurbishment(stop, tour)


def maybe_enter_refurbishment(closed_stop, tour):
    if tour["status"] != "ON_TOUR":
        return
    # The closed stop must be the latest CLOSED stop by teardown_end.
    closed = [s for s in stops_of_tour(tour["id"]) if s["status"] == "CLOSED"]
    if not closed:
        return
    latest = max(closed, key=lambda s: (db.parse_dt(s["teardown_end"]),
                                        s["created_at"]))
    if latest["id"] != closed_stop["id"]:
        return
    # Next stop in route order after the closed one.
    closed_key = (db.parse_dt(closed_stop["install_start"]), closed_stop["created_at"])
    successors = [s for s in stops_of_tour(tour["id"])
                  if s["id"] != closed_stop["id"]
                  and (db.parse_dt(s["install_start"]), s["created_at"]) > closed_key]
    if not successors:
        return
    successors.sort(key=lambda s: (db.parse_dt(s["install_start"]), s["created_at"]))
    nxt = successors[0]
    if nxt["status"] not in ("TENTATIVE", "CONTRACTED"):
        return
    gap = db.parse_dt(nxt["install_start"]) - db.parse_dt(closed_stop["teardown_end"])
    if gap <= timedelta(days=tour["refurbishment_gap_days"]):
        return  # strictly more than the gap is required
    tour["status"] = "IN_REFURBISHMENT"
    db.touch(tour)
    for crate in crates_of_tour(tour["id"]):
        if crate["location_status"] == "AT_VENUE" \
                and crate["current_stop_id"] == closed_stop["id"]:
            crate["location_status"] = "IN_REFURBISHMENT"
            db.touch(crate)


# --- tour retirement cascade (PRD §3.9) -------------------------------------------------

def retire_tour(tour):
    from_refurbishment = tour["status"] == "IN_REFURBISHMENT"
    for stop in stops_of_tour(tour["id"]):
        if stop["status"] == "TENTATIVE":
            stop["status"] = "CANCELLED"
            db.touch(stop)
    # Every non-terminal contract is finalized with its provisional figure
    # deemed final; a contract never sent (provisional null) finalizes at 0.
    for contract in contracts_of_tour(tour["id"]):
        if contract["status"] != "FINALIZED":
            final = contract["provisional_fee_cents"]
            finalize_contract(contract, final if final is not None else 0)
    for stop in stops_of_tour(tour["id"]):
        _retire_kits(stop["id"])
    for cert in certs_of_tour(tour["id"]):
        if cert["status"] in ("ISSUED", "ACTIVE"):
            cert["status"] = "VOID"
            db.touch(cert)
    if from_refurbishment:
        for crate in crates_of_tour(tour["id"]):
            if crate["location_status"] == "IN_REFURBISHMENT":
                crate["location_status"] = "AT_ORIGIN"
                crate["current_stop_id"] = None
                db.touch(crate)
    tour["status"] = "RETIRED"
    db.touch(tour)


# --- shipment damage-hold release (PRD §3.6, §3.7) ----------------------------------------

OPEN_CLAIM_STATES = ("FILED", "UNDER_REVIEW", "APPROVED")


def maybe_release_damage_hold(shipment):
    if shipment["status"] != "DAMAGE_HOLD":
        return
    if any(c["status"] in OPEN_CLAIM_STATES
           for c in claims_of_shipment(shipment["id"])):
        return
    shipment["status"] = "RECEIVED"
    db.touch(shipment)
