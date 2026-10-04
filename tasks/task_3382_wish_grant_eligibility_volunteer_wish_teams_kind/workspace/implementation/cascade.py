"""Shared cascade helpers: line release, offer quantity bookkeeping,
plan supersede, team disband, and the wish ready gate."""

from db import STORE, touch


def plans_of_wish(wish_id):
    return [p for p in STORE["plans"].values() if p["wish_id"] == wish_id]


def lines_of_plan(plan_id):
    return [l for l in STORE["lines"].values() if l["plan_id"] == plan_id]


def offer_release(offer, qty):
    """Return units to an offer; reopen FULLY_RESERVED -> AVAILABLE."""
    offer["quantity_reserved"] -= qty
    if offer["status"] == "FULLY_RESERVED" and (
        offer["quantity_total"] - offer["quantity_reserved"]
    ) > 0:
        offer["status"] = "AVAILABLE"
    touch(offer)


def release_line(line):
    offer = STORE["offers"].get(line["donation_offer_id"])
    line["status"] = "RELEASED"
    touch(line)
    if offer is not None:
        offer_release(offer, line["quantity"])


def consume_offer(offer, qty):
    """Consumption at grant completion: reserved and total shrink together,
    leaving quantity_available unchanged; DEPLETED when total hits 0."""
    offer["quantity_reserved"] -= qty
    offer["quantity_total"] -= qty
    if offer["quantity_total"] == 0:
        offer["status"] = "DEPLETED"
    touch(offer)


def supersede_open_plans(wish_id):
    """Replacement plan creation: DRAFT/PENDING_APPROVAL -> SUPERSEDED,
    releasing their RESERVED lines back to the offers."""
    for p in plans_of_wish(wish_id):
        if p["status"] in ("DRAFT", "PENDING_APPROVAL"):
            p["status"] = "SUPERSEDED"
            touch(p)
            for l in lines_of_plan(p["id"]):
                if l["status"] == "RESERVED":
                    release_line(l)


def disband_active_team(wish_id):
    """Team replacement: ACTIVE team -> DISBANDED; its SCHEDULED visits
    -> CANCELLED."""
    for t in STORE["teams"].values():
        if t["wish_id"] == wish_id and t["status"] == "ACTIVE":
            t["status"] = "DISBANDED"
            touch(t)
            for v in STORE["visits"].values():
                if v["wish_team_id"] == t["id"] and v["status"] == "SCHEDULED":
                    v["status"] = "CANCELLED"
                    touch(v)


def approved_plan_of_wish(wish_id):
    for p in plans_of_wish(wish_id):
        if p["status"] == "APPROVED":
            return p
    return None


def ready_gate_satisfied(wish):
    """calculations.wish_ready_gate, evaluated while wish is PLAN_APPROVED."""
    t = wish["wish_type"]
    if t == "TRAVEL":
        return any(
            c["wish_id"] == wish["id"] and c["status"] in ("CLEARED", "CONDITIONAL")
            for c in STORE["clearances"].values()
        )
    if t == "RECEIVE_ITEM":
        plan = approved_plan_of_wish(wish["id"])
        if plan is None:
            return False
        return all(
            l["status"] == "COMMITTED" for l in lines_of_plan(plan["id"])
        )
    if t in ("MEET_PERSON", "BE_SOMETHING"):
        return approved_plan_of_wish(wish["id"]) is not None
    return False
