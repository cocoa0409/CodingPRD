"""The logical clock, fair editions, stages and the talent roster (PRD sections 2.4, 3.1)."""

import calc
import ledgers
import lookup
import schema
from authz import (
    ROLE_BOX_OFFICE,
    ROLE_FAIR_OPS,
    ROLE_PRODUCTION,
    ROLE_SETTLEMENT,
    ROLE_SPONSORSHIP,
    ROLE_TALENT_AGENT,
    ROLE_TALENT_BUYER,
    resolve_actor,
    roles,
)
from db import db, new_id, parse_ts, public, stamp_new
from errors import ApiError
from flask import Blueprint, g
from response import collection, empty_response, object_response

bp = Blueprint("core", __name__)

ALL = (
    ROLE_TALENT_BUYER,
    ROLE_TALENT_AGENT,
    ROLE_FAIR_OPS,
    ROLE_PRODUCTION,
    ROLE_BOX_OFFICE,
    ROLE_SPONSORSHIP,
    ROLE_SETTLEMENT,
)


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@roles(*ALL)
def set_clock():
    payload = schema.body()
    current_utc = schema.f_ts(payload, "current_utc")
    resolve_actor()
    db.clock = parse_ts(current_utc)
    return empty_response(200)


# ---------------------------------------------------------------------------
# fair editions
# ---------------------------------------------------------------------------

@bp.post("/fair-editions")
@roles(ROLE_FAIR_OPS)
def create_edition():
    payload = schema.body()
    year = schema.f_int(payload, "year", minimum=1900, maximum=2200)
    name = schema.f_str(payload, "name")
    run_start_date = schema.f_date(payload, "run_start_date")
    run_end_date = schema.f_date(payload, "run_end_date")
    gate_admission_price_cents = schema.f_cents(payload, "gate_admission_price_cents")
    talent_budget_cap_cents = schema.f_cents(payload, "talent_budget_cap_cents")
    refund_reserve_cents = schema.f_cents(payload, "refund_reserve_cents")
    max_shows_per_day = schema.f_int(payload, "max_shows_per_day", default=2, minimum=1)
    curfew_utc_time = schema.f_hhmm(payload, "curfew_utc_time", default="23:30")
    strategy_basis = schema.f_enum(
        payload, "strategy_basis", schema.STRATEGY_BASES, default="ATTENDANCE_WEIGHTED"
    )
    if run_start_date > run_end_date:
        schema.bad("run_start_date must fall on or before run_end_date.")
    for existing in db.editions.values():
        if existing.get("year") == year:
            schema.bad("A fair edition already exists for year %s." % year)

    record = {
        "id": new_id(),
        "year": year,
        "name": name,
        "run_start_date": run_start_date,
        "run_end_date": run_end_date,
        "gate_admission_price_cents": gate_admission_price_cents,
        "talent_budget_cap_cents": talent_budget_cap_cents,
        "max_shows_per_day": max_shows_per_day,
        "curfew_utc_time": curfew_utc_time,
        "strategy_basis": strategy_basis,
        "refund_reserve_cents": refund_reserve_cents,
        "committed_guarantee_total_cents": 0,
        "refund_liability_committed_cents": 0,
        "open_stage_count": 0,
    }
    stamp_new(record)
    db.editions[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/fair-editions/<identifier>")
@roles(*ALL)
def read_edition(identifier):
    resolve_actor()
    return object_response(public(lookup.get_edition(identifier)))


@bp.get("/fair-editions")
@roles(ROLE_TALENT_BUYER, ROLE_FAIR_OPS, ROLE_BOX_OFFICE, ROLE_SPONSORSHIP, ROLE_SETTLEMENT)
def list_editions():
    limit, offset = schema.pagination()
    year = schema.q_int("year")
    rows = [e for e in db.editions.values() if year is None or e.get("year") == year]
    return collection(rows, limit, offset, field="created_at", reverse=True)


@bp.get("/fair-editions/<identifier>/buying-strategy-report")
@roles(ROLE_TALENT_BUYER, ROLE_FAIR_OPS)
def buying_strategy_report(identifier):
    edition = lookup.get_edition(identifier)
    shows = []
    artists_by_booking = {}
    for booking in ledgers.bookings_of_edition(edition["id"]):
        if booking.get("booking_status") not in ("ANNOUNCED", "PERFORMED"):
            continue
        shows.append(booking)
        artist = ledgers.artist_of_booking(booking)
        if artist is not None:
            artists_by_booking[booking["id"]] = artist
    show_ids = set(b["id"] for b in shows)
    settlements = [
        s for s in db.settlements.values()
        if s.get("booking_id") in show_ids and s.get("status") == "APPROVED"
    ]
    report = calc.buying_strategy_report(edition, shows, artists_by_booking, settlements)
    return object_response(report, 200)


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------

@bp.post("/stages")
@roles(ROLE_FAIR_OPS)
def create_stage():
    payload = schema.body()
    fair_edition_id = schema.f_str(payload, "fair_edition_id")
    name = schema.f_str(payload, "name")
    reserved_seat_capacity = schema.f_int(payload, "reserved_seat_capacity", minimum=0)
    ga_capacity = schema.f_int(payload, "ga_capacity", minimum=0)
    changeover_buffer_minutes = schema.f_int(
        payload, "changeover_buffer_minutes", default=120, minimum=0
    )
    slot_soft_cap = schema.f_int(payload, "slot_soft_cap", default=3, minimum=1)

    edition = lookup.get_edition(fair_edition_id)
    for existing in db.stages.values():
        if existing.get("fair_edition_id") == edition["id"] and existing.get("name") == name:
            schema.bad("A stage named '%s' already exists in this edition." % name)

    record = {
        "id": new_id(),
        "fair_edition_id": edition["id"],
        "name": name,
        "reserved_seat_capacity": reserved_seat_capacity,
        "ga_capacity": ga_capacity,
        "changeover_buffer_minutes": changeover_buffer_minutes,
        "slot_soft_cap": slot_soft_cap,
        "held_show_count": 0,
        "booking_posture": "OPEN",
    }
    stamp_new(record)
    db.stages[record["id"]] = record
    ledgers.recompute_stage_ledger(record)
    return object_response(public(record), 201)


@bp.get("/stages/<identifier>")
@roles(*ALL)
def read_stage(identifier):
    resolve_actor()
    return object_response(public(lookup.get_stage(identifier)))


@bp.get("/stages")
@roles(ROLE_TALENT_BUYER, ROLE_FAIR_OPS, ROLE_BOX_OFFICE, ROLE_SPONSORSHIP)
def list_stages():
    limit, offset = schema.pagination()
    fair_edition_id = schema.q_str("fair_edition_id")
    booking_posture = schema.q_enum("booking_posture", schema.BOOKING_POSTURES)
    if fair_edition_id is not None:
        lookup.get_edition(fair_edition_id)
    rows = []
    for stage in db.stages.values():
        if fair_edition_id is not None and stage.get("fair_edition_id") != fair_edition_id:
            continue
        if booking_posture is not None and stage.get("booking_posture") != booking_posture:
            continue
        rows.append(stage)
    return collection(rows, limit, offset)


# ---------------------------------------------------------------------------
# talent agents
# ---------------------------------------------------------------------------

@bp.post("/talent-agents")
@roles(ROLE_TALENT_BUYER)
def create_agent():
    payload = schema.body()
    user_id = schema.f_str(payload, "user_id")
    agency_name = schema.f_str(payload, "agency_name")
    contact_email = schema.f_str(payload, "contact_email")
    for existing in db.agents.values():
        if existing.get("user_id") == user_id:
            schema.bad("An agent is already registered for user_id '%s'." % user_id)
    record = {
        "id": new_id(),
        "user_id": user_id,
        "agency_name": agency_name,
        "contact_email": contact_email,
        "roster_artist_count": 0,
    }
    stamp_new(record)
    db.agents[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/talent-agents/<identifier>")
@roles(ROLE_TALENT_BUYER, ROLE_TALENT_AGENT, ROLE_FAIR_OPS, ROLE_SETTLEMENT)
def read_agent(identifier):
    resolve_actor()
    return object_response(public(lookup.get_agent(identifier)))


# ---------------------------------------------------------------------------
# artists
# ---------------------------------------------------------------------------

@bp.post("/artists")
@roles(ROLE_TALENT_BUYER)
def create_artist():
    payload = schema.body()
    agent_id = schema.f_str(payload, "agent_id")
    name = schema.f_str(payload, "name")
    genre = schema.f_enum(payload, "genre", schema.GENRES)
    audience_segment = schema.f_enum(payload, "audience_segment", schema.AUDIENCE_SEGMENTS)
    base_draw_score = schema.f_number(
        payload, "base_draw_score", default=50.00, minimum=0.0, maximum=100.0
    )
    prior_year_paid_attendance = schema.f_int(
        payload, "prior_year_paid_attendance", default=0, minimum=0
    )
    prior_year_net_revenue_cents = schema.f_cents(
        payload, "prior_year_net_revenue_cents", default=0
    )
    agent = lookup.get_agent(agent_id)

    record = {
        "id": new_id(),
        "agent_id": agent["id"],
        "name": name,
        "genre": genre,
        "audience_segment": audience_segment,
        "base_draw_score": float(base_draw_score),
        "prior_year_paid_attendance": prior_year_paid_attendance,
        "prior_year_net_revenue_cents": prior_year_net_revenue_cents,
        "draw_score_next_year": None,
    }
    stamp_new(record)
    db.artists[record["id"]] = record
    ledgers.recompute_agent_roster(agent)
    return object_response(public(record), 201)


@bp.get("/artists/<identifier>")
@roles(ROLE_TALENT_BUYER, ROLE_TALENT_AGENT, ROLE_FAIR_OPS, ROLE_BOX_OFFICE, ROLE_SETTLEMENT)
def read_artist(identifier):
    resolve_actor()
    return object_response(public(lookup.get_artist(identifier)))


@bp.get("/artists")
@roles(ROLE_TALENT_BUYER, ROLE_TALENT_AGENT, ROLE_FAIR_OPS)
def list_artists():
    limit, offset = schema.pagination()
    agent_id = schema.q_str("agent_id")
    genre = schema.q_enum("genre", schema.GENRES)
    audience_segment = schema.q_enum("audience_segment", schema.AUDIENCE_SEGMENTS)
    resolve_actor()
    if agent_id is not None:
        lookup.get_agent(agent_id)
    rows = []
    for artist in db.artists.values():
        if agent_id is not None and artist.get("agent_id") != agent_id:
            continue
        if genre is not None and artist.get("genre") != genre:
            continue
        if audience_segment is not None and artist.get("audience_segment") != audience_segment:
            continue
        rows.append(artist)
    return collection(rows, limit, offset)
