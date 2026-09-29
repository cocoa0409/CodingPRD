"""Mutations, cascades and the shared state-transition machinery."""
from flask import g

import calc
import core
from core import (DELINQUENCY_THRESHOLD_CENTS, DB, RETURN_GRACE_DAYS, new_id,
                  next_seq, now_iso, today_str)


# ---------------------------------------------------------------------------
# Version / updated_at discipline
# ---------------------------------------------------------------------------
def touch(row):
    """Bump version once per request and refresh updated_at."""
    if row is None:
        return
    if not hasattr(g, "touched"):
        g.touched = set()
    key = (row["_kind"], row["id"])
    if key not in g.touched:
        g.touched.add(key)
        row["version"] = row["version"] + 1
    row["updated_at"] = now_iso()


def base_row(kind, event=False):
    row = {
        "_kind": kind,
        "_seq": next_seq(),
        "id": new_id(),
        "created_at": now_iso(),
    }
    if not event:
        row["updated_at"] = now_iso()
        row["version"] = 1
    if not hasattr(g, "touched"):
        g.touched = set()
    g.touched.add((kind, row["id"]))
    return row


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def append_ledger(member, kind, amount_cents, memo=None,
                  damage_claim_id=None, reservation_id=None):
    row = base_row("fee_ledger_entries", event=True)
    row.update({
        "member_id": member["id"],
        "damage_claim_id": damage_claim_id,
        "reservation_id": reservation_id,
        "kind": kind,
        "direction": "DEBIT" if amount_cents > 0 else "CREDIT",
        "amount_cents": amount_cents,
        "balance_after_cents": 0,
        "memo": memo,
    })
    DB["fee_ledger_entries"][row["id"]] = row
    row["balance_after_cents"] = calc.member_outstanding(member["id"])
    return row


def check_delinquency(member):
    """Hops 3-5 of a ledger append: ACTIVE -> DELINQUENT plus unwinding."""
    balance = calc.member_outstanding(member["id"])
    if member["status"] != "ACTIVE" or balance < DELINQUENCY_THRESHOLD_CENTS:
        return
    member["status"] = "DELINQUENT"
    touch(member)
    unwind_member_commitments(member, cancel_waitlisted=True, release_matched=True)


def check_delinquency_recovery(member):
    balance = calc.member_outstanding(member["id"])
    if member["status"] == "DELINQUENT" and balance < DELINQUENCY_THRESHOLD_CENTS:
        member["status"] = "ACTIVE"
        touch(member)


def unwind_member_commitments(member, cancel_waitlisted=True, release_matched=True,
                              bump_member=False, promote=True):
    """Cancel WAITLISTED and release MATCHED reservations; free their units."""
    rows = sorted(calc.reservations_of_member(member["id"]),
                  key=lambda r: (r["created_at"], r["_seq"]))
    freed_units = []
    if cancel_waitlisted:
        for r in rows:
            if r["state"] == "WAITLISTED":
                r["state"] = "CANCELLED"
                touch(r)
    if release_matched:
        for r in rows:
            if r["state"] == "MATCHED":
                unit = DB["rental_units"].get(r["allocated_unit_id"])
                r["state"] = "RELEASED"
                r["allocated_unit_id"] = None
                touch(r)
                if unit is not None and unit["availability_state"] == "RESERVED":
                    unit["availability_state"] = "IN_STOCK"
                    touch(unit)
                    freed_units.append(unit)
    if bump_member:
        touch(member)
    if promote:
        for unit in freed_units:
            promote_for_freed_unit(unit)
    return freed_units


# ---------------------------------------------------------------------------
# Allocation / waitlist
# ---------------------------------------------------------------------------
def allocate(reservation, unit):
    reservation["allocated_unit_id"] = unit["id"]
    reservation["state"] = "MATCHED"
    reservation["matched_at"] = now_iso()
    touch(reservation)
    unit["availability_state"] = "RESERVED"
    touch(unit)


def promote_for_freed_unit(unit):
    """Offer a freed unit to the head of its style/size waitlist."""
    style = DB["styles"].get(unit["style_id"])
    if style is None:
        return None
    head = calc.waitlist_head(style["id"], unit["size"])
    if head is None:
        return None
    member = DB["members"].get(head["member_id"])
    if member is None or member["status"] != "ACTIVE":
        return None
    if not calc.unit_base_eligible(unit, style, head["requested_size"]):
        return None
    if calc.interval_collision(unit["id"], head["requested_start_date"],
                               head["requested_end_date"], head["id"]):
        return None
    allocate(head, unit)
    touch(member)
    return head


def promote_for_style(style):
    """Re-evaluate promotion for every size queued on the style."""
    sizes = []
    for r in DB["reservations"].values():
        if r["state"] == "WAITLISTED" and r["style_id"] == style["id"]:
            if r["requested_size"] not in sizes:
                sizes.append(r["requested_size"])
    promoted = []
    for size in sizes:
        head = calc.waitlist_head(style["id"], size)
        if head is None:
            continue
        member = DB["members"].get(head["member_id"])
        if member is None or member["status"] != "ACTIVE":
            continue
        cands = calc.candidate_units(style, size, head["requested_start_date"],
                                     head["requested_end_date"], head["id"])
        if not cands:
            continue
        unit = calc.rank_candidates(cands)[0]
        allocate(head, unit)
        touch(member)
        promoted.append(head)
    return promoted


def resolve_new_reservation(reservation, member, style, preferred_unit):
    """REQUESTED -> MATCHED or REQUESTED -> WAITLISTED, in the same request."""
    cands = calc.candidate_units(style, reservation["requested_size"],
                                 reservation["requested_start_date"],
                                 reservation["requested_end_date"],
                                 reservation["id"])
    chosen = None
    if preferred_unit is not None:
        chosen = preferred_unit
    elif cands:
        chosen = calc.rank_candidates(cands)[0]
    if chosen is None:
        reservation["state"] = "WAITLISTED"
        touch(reservation)
    else:
        allocate(reservation, chosen)
    touch(member)


# ---------------------------------------------------------------------------
# Reservation closure / revenue
# ---------------------------------------------------------------------------
def close_reservation(reservation, member):
    plan = DB["membership_plans"].get(member["membership_plan_id"])
    reservation["state"] = "CLOSED"
    if plan is not None:
        reservation["revenue_attributed_cents"] = calc.turn_revenue(
            plan, reservation["is_swap"])
    touch(reservation)


# ---------------------------------------------------------------------------
# Retirement
# ---------------------------------------------------------------------------
JOB_DRAIN_STATES = {"RECEIVED", "INSPECTED", "PROCESSING", "READY_FOR_PHOTO",
                    "PHOTOGRAPHED", "CONDEMNED_HOLD"}


def retire_unit(unit, reason):
    """Both declared retirement branches. Returns the style for recomputation."""
    origin = unit["availability_state"]
    unit["availability_state"] = "RETIRED"
    unit["retired_at"] = now_iso()
    unit["retirement_reason"] = reason
    touch(unit)
    style = DB["styles"].get(unit["style_id"])
    if origin == "PROCESSING":
        jobs = sorted(calc.jobs_of_unit(unit["id"]),
                      key=lambda j: (j["created_at"], j["_seq"]))
        for job in jobs:
            was_condemned_hold = job["state"] == "CONDEMNED_HOLD"
            if job["state"] in JOB_DRAIN_STATES:
                if job["state"] != "CONDEMNED_HOLD":
                    job["state"] = "CONDEMNED_HOLD"
                    touch(job)
                if was_condemned_hold:
                    res = DB["reservations"].get(job["reservation_id"])
                    if res is not None and res["state"] == "RETURNED":
                        member = DB["members"].get(res["member_id"])
                        if member is not None:
                            close_reservation(res, member)
    if style is not None:
        promote_for_style(style)
    return style


# ---------------------------------------------------------------------------
# Shipment loss path
# ---------------------------------------------------------------------------
def shipment_loss(shipment):
    unit = None
    res = DB["reservations"].get(shipment["reservation_id"])
    if res is not None:
        unit = DB["rental_units"].get(res["allocated_unit_id"])
    if unit is not None:
        unit["availability_state"] = "RETIRED"
        unit["retirement_reason"] = "LOSS"
        unit["retired_at"] = now_iso()
        unit["condition_state"] = "CONDEMNED"
        touch(unit)
    if res is not None:
        if shipment["direction"] == "OUTBOUND":
            if res["state"] == "SHIPPED":
                res["state"] = "WAITLISTED"
                res["allocated_unit_id"] = None
                res["matched_at"] = None
                touch(res)
        else:
            if res["state"] == "RETURN_INITIATED":
                member = DB["members"].get(res["member_id"])
                res["returned_at"] = None
                res["rental_days"] = None
                res["late_days"] = 0
                res["late_fee_cents"] = 0
                if member is not None:
                    close_reservation(res, member)


# ---------------------------------------------------------------------------
# Warehouse receipt cascade
# ---------------------------------------------------------------------------
def receipt_cascade(shipment):
    res = DB["reservations"].get(shipment["reservation_id"])
    if res is None:
        return
    member = DB["members"].get(res["member_id"])
    received_date = core.now_dt().strftime("%Y-%m-%d")
    # Hop 2 — reservation RETURN_INITIATED -> RETURNED, rental days, late fee
    res["state"] = "RETURNED"
    res["returned_at"] = now_iso()
    if res["delivered_at"]:
        res["rental_days"] = core.date_diff(
            received_date, core.parse_instant(res["delivered_at"]).strftime("%Y-%m-%d"))
    late_days, late_fee = calc.late_return_fee(res, received_date)
    res["late_days"] = late_days
    res["late_fee_cents"] = late_fee
    touch(res)
    if late_fee > 0 and member is not None:
        append_ledger(member, "LATE_FEE", late_fee,
                      memo="Late return fee", reservation_id=res["id"])
        check_delinquency(member)
    # Hop 3 — unit INBOUND -> PROCESSING and a new reverse-logistics job
    unit = DB["rental_units"].get(res["allocated_unit_id"])
    if unit is not None:
        unit["availability_state"] = "PROCESSING"
        unit["last_returned_at"] = now_iso()
        touch(unit)
        job = base_row("reverse_logistics_jobs")
        job.update({
            "rental_unit_id": unit["id"],
            "reservation_id": res["id"],
            "inspecting_technician_id": None,
            "state": "RECEIVED",
            "cleaning_required": False,
            "repair_required": False,
            "cleaning_completed_at": None,
            "repair_completed_at": None,
            "photographed_at": None,
            "repair_attempts": 0,
            "condemned": False,
        })
        DB["reverse_logistics_jobs"][job["id"]] = job


# ---------------------------------------------------------------------------
# Reconditioning join
# ---------------------------------------------------------------------------
def try_join(job, unit):
    if job["state"] != "PROCESSING":
        return
    cleaning_done = (not job["cleaning_required"]) or job["cleaning_completed_at"]
    repair_done = (not job["repair_required"]) or job["repair_completed_at"]
    if cleaning_done and repair_done and not unit["quarantine_hold"]:
        job["state"] = "READY_FOR_PHOTO"
        touch(job)


# ---------------------------------------------------------------------------
# Claim risk persistence
# ---------------------------------------------------------------------------
def persist_lifetime_risk(member):
    risk = calc.damage_risk(member, "LIFETIME")
    member["damage_risk_score"] = risk["damage_risk_score"]
    member["damage_risk_band"] = risk["damage_risk_band"]
