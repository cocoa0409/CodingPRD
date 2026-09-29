"""Offers, the negotiation loop and the acceptance cascade (PRD sections 3.2-3.4)."""

import calc
import ledgers
import lookup
import schema
import scheduling
import spine
from authz import (
    ROLE_FAIR_OPS,
    ROLE_SETTLEMENT,
    ROLE_TALENT_AGENT,
    ROLE_TALENT_BUYER,
    resolve_actor,
    roles,
)
from db import add_hours, db, fmt_ts, new_id, now, now_str, public, stamp_new, touch
from errors import ApiError
from flask import Blueprint, g
from response import collection, object_response

bp = Blueprint("offers", __name__)

READ_ROLES = (ROLE_TALENT_BUYER, ROLE_TALENT_AGENT, ROLE_FAIR_OPS, ROLE_SETTLEMENT)


# ---------------------------------------------------------------------------
# shared gates
# ---------------------------------------------------------------------------

def require_status(offer, allowed):
    if offer.get("status") not in allowed:
        raise ApiError("ERR_INVALID_OFFER_STATE")


def expire_offer(offer):
    """Persist the auto-transition to EXPIRED with its full ledger cascade."""
    offer["status"] = "EXPIRED"
    touch(offer)
    ledgers.recompute_stage_ledger(db.stages.get(offer.get("target_stage_id")))
    ledgers.recompute_edition_committed(db.editions.get(offer.get("fair_edition_id")))


def require_window_open(offer):
    """PRD section 3.3: the expiry check runs after the plain state check."""
    if offer.get("status") not in ("SENT", "COUNTERED"):
        return
    expires_at = offer.get("expires_at_utc")
    if expires_at is None:
        return
    if now_str() >= expires_at:
        expire_offer(offer)
        raise ApiError("ERR_OFFER_EXPIRED")


def require_agent_owns_artist(offer):
    agent = getattr(g, "acting_agent", None)
    artist = db.artists.get(offer.get("artist_id"))
    if agent is None or artist is None or artist.get("agent_id") != agent["id"]:
        raise ApiError("ERR_AGENT_NOT_AUTHORIZED_FOR_ARTIST")


def require_round_room(offer):
    if int(offer.get("round_count", 0)) >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT")


def require_budget(edition, offer_id, amount):
    projected = ledgers.projected_edition_committed(edition, offer_id, amount)
    if projected > int(edition.get("talent_budget_cap_cents", 0)):
        raise ApiError("ERR_TALENT_BUDGET_EXCEEDED")


def append_round(offer, proposed_by, guarantee, split, breakeven, note):
    record = {
        "id": new_id(),
        "offer_id": offer["id"],
        "round_number": int(offer.get("round_count", 0)) + 1,
        "proposed_by": proposed_by,
        "proposed_guarantee_cents": guarantee,
        "proposed_backend_split_pct": split,
        "proposed_breakeven_cents": breakeven,
        "note": note,
        "recorded_at_utc": now_str(),
    }
    stamp_new(record, common=False)
    db.offer_rounds[record["id"]] = record
    ledgers.recompute_offer_round_count(offer)
    return record


# ---------------------------------------------------------------------------
# draft, read, list
# ---------------------------------------------------------------------------

@bp.post("/offers")
@roles(ROLE_TALENT_BUYER)
def create_offer():
    payload = schema.body()
    fair_edition_id = schema.f_str(payload, "fair_edition_id")
    artist_id = schema.f_str(payload, "artist_id")
    target_stage_id = schema.f_str(payload, "target_stage_id")
    deal_type = schema.f_enum(payload, "deal_type", schema.DEAL_TYPES)
    offered_guarantee_cents = schema.f_cents(payload, "offered_guarantee_cents")
    backend_split_pct = schema.f_pct(payload, "backend_split_pct")
    backend_breakeven_cents = schema.f_cents(payload, "backend_breakeven_cents", default=0)
    radius_miles = schema.f_int(payload, "radius_miles", default=150, minimum=0)
    radius_days_before = schema.f_int(payload, "radius_days_before", default=30, minimum=0)
    radius_days_after = schema.f_int(payload, "radius_days_after", default=30, minimum=0)
    target_show_date = schema.f_date(payload, "target_show_date")
    load_in_start_utc = schema.f_ts(payload, "load_in_start_utc")
    load_out_end_utc = schema.f_ts(payload, "load_out_end_utc")
    response_window_hours = schema.f_int(payload, "response_window_hours", default=48, minimum=1)

    edition = lookup.get_edition(fair_edition_id)
    stage = lookup.get_stage(target_stage_id)
    artist = lookup.get_artist(artist_id)

    if not scheduling.date_inside_run(edition, target_show_date):
        raise ApiError("ERR_SHOW_DATE_OUTSIDE_FAIR_RUN")
    if not scheduling.window_is_well_formed(target_show_date, load_in_start_utc, load_out_end_utc):
        raise ApiError("ERR_INVALID_SLOT_WINDOW")

    record = {
        "id": new_id(),
        "fair_edition_id": edition["id"],
        "artist_id": artist["id"],
        "target_stage_id": stage["id"],
        "deal_type": deal_type,
        "offered_guarantee_cents": offered_guarantee_cents,
        "backend_split_pct": backend_split_pct,
        "backend_breakeven_cents": backend_breakeven_cents,
        "radius_miles": radius_miles,
        "radius_days_before": radius_days_before,
        "radius_days_after": radius_days_after,
        "target_show_date": target_show_date,
        "load_in_start_utc": load_in_start_utc,
        "load_out_end_utc": load_out_end_utc,
        "response_window_hours": response_window_hours,
        "radius_waiver_granted": False,
        "status": "DRAFT",
        "round_count": 0,
        "countered_guarantee_cents": None,
        "agreed_guarantee_cents": None,
        "sent_at_utc": None,
        "expires_at_utc": None,
        "created_by_user_id": g.user_id,
    }
    stamp_new(record)
    db.offers[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/offers/<identifier>")
@roles(*READ_ROLES)
def read_offer(identifier):
    resolve_actor()
    return object_response(public(lookup.get_offer(identifier)))


@bp.get("/offers")
@roles(*READ_ROLES)
def list_offers():
    limit, offset = schema.pagination()
    fair_edition_id = schema.q_str("fair_edition_id")
    artist_id = schema.q_str("artist_id")
    target_stage_id = schema.q_str("target_stage_id")
    status = schema.q_enum("status", schema.OFFER_STATUSES)
    resolve_actor()
    if artist_id is not None:
        lookup.get_artist(artist_id)
    rows = []
    for offer in db.offers.values():
        if fair_edition_id is not None and offer.get("fair_edition_id") != fair_edition_id:
            continue
        if artist_id is not None and offer.get("artist_id") != artist_id:
            continue
        if target_stage_id is not None and offer.get("target_stage_id") != target_stage_id:
            continue
        if status is not None and offer.get("status") != status:
            continue
        rows.append(offer)
    return collection(rows, limit, offset)


@bp.get("/offers/<identifier>/rounds")
@roles(*READ_ROLES)
def list_rounds(identifier):
    limit, offset = schema.pagination()
    proposed_by = schema.q_enum("proposed_by", schema.PROPOSED_BY)
    resolve_actor()
    offer = lookup.get_offer(identifier)
    rows = [
        r for r in ledgers.rounds_of_offer(offer["id"])
        if proposed_by is None or r.get("proposed_by") == proposed_by
    ]
    return collection(rows, limit, offset, field="recorded_at_utc")


# ---------------------------------------------------------------------------
# transitions
# ---------------------------------------------------------------------------

@bp.post("/offers/<identifier>/send")
@roles(ROLE_TALENT_BUYER)
def send_offer(identifier):
    offer = lookup.get_offer(identifier)
    require_status(offer, ("DRAFT",))

    edition = db.editions[offer["fair_edition_id"]]
    stage = db.stages[offer["target_stage_id"]]
    artist = db.artists[offer["artist_id"]]
    show_date = offer["target_show_date"]

    if not scheduling.date_inside_run(edition, show_date):
        raise ApiError("ERR_SHOW_DATE_OUTSIDE_FAIR_RUN")
    if not scheduling.window_is_well_formed(
        show_date, offer["load_in_start_utc"], offer["load_out_end_utc"]
    ):
        raise ApiError("ERR_INVALID_SLOT_WINDOW")

    scheduling.check_curfew(edition, show_date, offer["load_out_end_utc"])
    scheduling.check_stage_slot(
        stage,
        offer["load_in_start_utc"],
        offer["load_out_end_utc"],
        exclude_offer_id=offer["id"],
    )
    scheduling.check_radius(artist["id"], show_date, exclude_offer_id=offer["id"])
    scheduling.check_genre_adjacency(
        stage, show_date, artist.get("genre"), exclude_offer_id=offer["id"]
    )
    scheduling.check_day_capacity(edition, show_date, exclude_offer_id=offer["id"])
    require_budget(edition, offer["id"], offer["offered_guarantee_cents"])

    append_round(
        offer,
        "BUYER",
        offer["offered_guarantee_cents"],
        offer["backend_split_pct"],
        offer["backend_breakeven_cents"],
        None,
    )
    offer["status"] = "SENT"
    offer["sent_at_utc"] = now_str()
    offer["expires_at_utc"] = fmt_ts(add_hours(now(), int(offer["response_window_hours"])))
    touch(offer)
    ledgers.recompute_stage_ledger(stage)
    ledgers.recompute_edition_committed(edition)
    return object_response(public(offer), 200)


@bp.post("/offers/<identifier>/counter")
@roles(ROLE_TALENT_AGENT)
def counter_offer(identifier):
    payload = schema.body()
    proposed_guarantee_cents = schema.f_cents(payload, "proposed_guarantee_cents")
    proposed_backend_split_pct = schema.f_pct(payload, "proposed_backend_split_pct")
    proposed_breakeven_cents = schema.f_cents(payload, "proposed_breakeven_cents", default=0)
    grant_radius_waiver = schema.f_bool(payload, "grant_radius_waiver", default=False)
    note = schema.f_str(payload, "note", default=None, allow_blank=True)
    resolve_actor()

    offer = lookup.get_offer(identifier)
    require_status(offer, ("SENT",))
    require_window_open(offer)
    require_agent_owns_artist(offer)
    require_round_room(offer)

    append_round(
        offer,
        "AGENT",
        proposed_guarantee_cents,
        proposed_backend_split_pct,
        proposed_breakeven_cents,
        note,
    )
    offer["status"] = "COUNTERED"
    offer["countered_guarantee_cents"] = proposed_guarantee_cents
    offer["radius_waiver_granted"] = bool(grant_radius_waiver)
    touch(offer)
    return object_response(public(offer), 200)


@bp.post("/offers/<identifier>/revise")
@roles(ROLE_TALENT_BUYER)
def revise_offer(identifier):
    payload = schema.body()
    expected_offer_version = schema.f_int(payload, "expected_offer_version")
    offered_guarantee_cents = schema.f_cents(payload, "offered_guarantee_cents")
    backend_split_pct = schema.f_pct(payload, "backend_split_pct")
    backend_breakeven_cents = schema.f_cents(payload, "backend_breakeven_cents", default=0)
    note = schema.f_str(payload, "note", default=None, allow_blank=True)

    offer = lookup.get_offer(identifier)
    require_status(offer, ("COUNTERED",))
    require_window_open(offer)
    if expected_offer_version != int(offer.get("version", 0)):
        raise ApiError("ERR_STALE_OFFER_VERSION")
    require_round_room(offer)

    edition = db.editions[offer["fair_edition_id"]]
    require_budget(edition, offer["id"], offered_guarantee_cents)

    offer["offered_guarantee_cents"] = offered_guarantee_cents
    offer["backend_split_pct"] = backend_split_pct
    offer["backend_breakeven_cents"] = backend_breakeven_cents
    append_round(
        offer,
        "BUYER",
        offered_guarantee_cents,
        backend_split_pct,
        backend_breakeven_cents,
        note,
    )
    offer["status"] = "SENT"
    offer["countered_guarantee_cents"] = None
    offer["sent_at_utc"] = now_str()
    offer["expires_at_utc"] = fmt_ts(add_hours(now(), int(offer["response_window_hours"])))
    touch(offer)
    ledgers.recompute_edition_committed(edition)
    return object_response(public(offer), 200)


@bp.post("/offers/<identifier>/accept")
@roles(ROLE_TALENT_AGENT)
def accept_offer(identifier):
    resolve_actor()
    offer = lookup.get_offer(identifier)
    require_status(offer, ("SENT",))
    require_window_open(offer)
    require_agent_owns_artist(offer)

    edition = db.editions[offer["fair_edition_id"]]
    require_budget(edition, offer["id"], offer["offered_guarantee_cents"])

    offer["status"] = "ACCEPTED"
    offer["agreed_guarantee_cents"] = offer["offered_guarantee_cents"]
    touch(offer)
    spine.create_booking_from_offer(offer)
    ledgers.recompute_edition_committed(edition)
    ledgers.recompute_stage_ledger(db.stages.get(offer["target_stage_id"]))
    return object_response(public(offer), 200)


@bp.post("/offers/<identifier>/decline")
@roles(ROLE_TALENT_AGENT)
def decline_offer(identifier):
    resolve_actor()
    offer = lookup.get_offer(identifier)
    require_status(offer, ("SENT", "COUNTERED"))
    require_window_open(offer)
    require_agent_owns_artist(offer)

    offer["status"] = "DECLINED"
    touch(offer)
    ledgers.recompute_stage_ledger(db.stages.get(offer["target_stage_id"]))
    ledgers.recompute_edition_committed(db.editions.get(offer["fair_edition_id"]))
    return object_response(public(offer), 200)


@bp.post("/offers/<identifier>/withdraw")
@roles(ROLE_TALENT_BUYER)
def withdraw_offer(identifier):
    offer = lookup.get_offer(identifier)
    require_status(offer, ("DRAFT", "SENT", "COUNTERED"))
    was_held = offer.get("status") in ("SENT", "COUNTERED")

    offer["status"] = "WITHDRAWN"
    touch(offer)
    if was_held:
        ledgers.recompute_stage_ledger(db.stages.get(offer["target_stage_id"]))
        ledgers.recompute_edition_committed(db.editions.get(offer["fair_edition_id"]))
    return object_response(public(offer), 200)
