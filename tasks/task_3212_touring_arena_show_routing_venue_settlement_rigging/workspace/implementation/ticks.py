"""Lazy clock-driven transitions and cascade side effects."""

from clock import now
from db import db, touch
import helpers as H


def recompute_tour_counters(tour):
    gross = 0
    for e in db.engagements.values():
        if e["tour_id"] == tour["id"] and e["status"] == "SETTLED":
            sid = db.settlements_by_eng.get(e["id"])
            if sid:
                gross += db.settlements[sid]["gross_ticket_cents"]
    due = 0
    for e in db.engagements.values():
        if e["tour_id"] == tour["id"] and e["status"] == "SETTLED":
            sid = db.settlements_by_eng.get(e["id"])
            if sid:
                due += db.settlements[sid]["venue_share_cents"]
    open_count = 0
    for e in db.engagements.values():
        if e["tour_id"] == tour["id"] and e["status"] in H.OPEN_ENGAGEMENT_STATUSES:
            open_count += 1
    tour["total_gross_cents"] = gross
    tour["total_settlement_due_cents"] = due
    tour["open_engagement_count"] = open_count


def tick_tour(tour):
    if tour["status"] == "ROUTING":
        confirmed = [e for e in db.engagements.values()
                     if e["tour_id"] == tour["id"] and e["status"] == "CONFIRMED"]
        if confirmed:
            earliest = min(e["load_in_at"] for e in confirmed)
            if now() >= earliest:
                tour["status"] = "ON_ROAD"
                touch(tour)
    if tour["status"] == "ON_ROAD":
        engs = [e for e in db.engagements.values() if e["tour_id"] == tour["id"]]
        non_cancelled = [e for e in engs if e["status"] != "CANCELLED"]
        if (non_cancelled
                and all(e["status"] == "SETTLED" for e in non_cancelled)
                and all(e["status"] in ("SETTLED", "CANCELLED") for e in engs)):
            tour["status"] = "WRAP"
            touch(tour)
            recompute_tour_counters(tour)


def _cancel_engagement(e, reason=None):
    """Shared cascade for HOLD->CANCELLED and CONFIRMED->CANCELLED (time gates
    checked by callers)."""
    e["status"] = "CANCELLED"
    if reason:
        e["cancel_reason"] = reason
    touch(e)
    avail = db.date_avails.get(e["date_avail_id"])
    if avail is not None and avail["status"] in ("HELD", "BOOKED"):
        if avail.get("held_for_engagement_id") == e["id"]:
            avail["status"] = "OPEN"
            avail["held_for_engagement_id"] = None
            touch(avail)
    for p in db.rigging_plans.values():
        if p["engagement_id"] == e["id"] and p["status"] in H.PLAN_NONTERMINAL:
            p["status"] = "SUPERSEDED"
            touch(p)
    if e.get("_cancel_from") == "CONFIRMED":
        labor_states = ("DRAFT", "POSTED", "FILLED")
    else:
        labor_states = ("DRAFT", "POSTED")
    for c in db.labor_calls.values():
        if c["engagement_id"] == e["id"] and c["status"] in labor_states:
            c["status"] = "CANCELLED"
            touch(c)
    for m in db.truck_moves.values():
        if m["engagement_id"] == e["id"] and m["status"] in ("SCHEDULED", "DISPATCHED"):
            m["status"] = "CANCELLED"
            touch(m)
    tour = db.tours.get(e["tour_id"])
    if tour is not None:
        recompute_tour_counters(tour)


def cancel_engagement(e, reason=None, from_status=None):
    e["_cancel_from"] = from_status or e["status"]
    try:
        _cancel_engagement(e, reason)
    finally:
        e.pop("_cancel_from", None)


def tick_engagement(e):
    ts = now()
    if e["status"] == "HOLD":
        if ts >= e["hold_expires_at"]:
            cancel_engagement(e, reason="HOLD_EXPIRED", from_status="HOLD")
            return
    if e["status"] == "CONFIRMED" and ts >= e["load_in_at"]:
        e["status"] = "IN_LOAD"
        touch(e)
    if e["status"] == "SHOW_READY" and ts >= e["first_show_at"]:
        e["status"] = "IN_PERFORMANCE"
        touch(e)
    tour = db.tours.get(e["tour_id"])
    if tour is not None:
        tick_tour(tour)


def tick_license(l):
    if l["status"] == "ACTIVE" and now() >= l["ends_on"]:
        l["status"] = "EXPIRED"
        touch(l)


def tick_all():
    for e in list(db.engagements.values()):
        tick_engagement(e)
    for l in list(db.license_agreements.values()):
        tick_license(l)
    for t in list(db.tours.values()):
        tick_tour(t)
