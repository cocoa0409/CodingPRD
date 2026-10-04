"""Venues, events, licenses, zones, screen assignments, forecast, pricing quote."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
from errors import invalid_request
from util import (success, list_response, auth, body, require, req_int,
                  req_str, parse_dt, now_ts, zip_miles, bump, LEAGUES,
                  EVENT_KINDS)
import services
from util import serialize, serialize_list

bp = Blueprint("core", __name__)

ALL = ["PlatformAdmin", "VenueManager", "Host", "Server", "Scheduler"]


def get_venue_or_404(venue_id):
    v = db.venues.get(venue_id)
    if v is None:
        raise errors.not_found()
    return v


def get_event_or_404(event_id):
    e = db.events.get(event_id)
    if e is None:
        raise errors.event_not_found()
    return e


def get_license_or_404(license_id):
    lic = db.licenses.get(license_id)
    if lic is None:
        raise errors.not_found()
    return lic


def get_zone_or_404(zone_id):
    z = db.zones.get(zone_id)
    if z is None:
        raise errors.not_found()
    return z


# ---------------------------------------------------------------- venues

@bp.post("/api/venues")
def create_venue():
    auth(["PlatformAdmin"])
    data = body()
    name = req_str(data, "name")
    market_zip = req_str(data, "market_zip")
    capacity = req_int(data, "capacity_seats", minimum=0)
    wing_cost = req_int(data, "wing_cost_cents_per_lb", minimum=0)
    ts = now_ts()
    venue = {
        "id": services.new_id(), "name": name, "market_zip": market_zip,
        "capacity_seats": capacity, "wing_cost_cents_per_lb": wing_cost,
        "volatility_score": services.volatility_score(wing_cost),
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.venues[venue["id"]] = venue
    return success(serialize(venue), code=201)


@bp.get("/api/venues/<venue_id>")
def get_venue(venue_id):
    auth(ALL)
    return success(serialize(get_venue_or_404(venue_id)))


@bp.patch("/api/venues/<venue_id>/wing-cost")
def update_wing_cost(venue_id):
    auth(["VenueManager"])
    venue = get_venue_or_404(venue_id)
    data = body()
    wing_cost = req_int(data, "wing_cost_cents_per_lb", minimum=0)
    venue["wing_cost_cents_per_lb"] = wing_cost
    venue["volatility_score"] = services.volatility_score(wing_cost)
    bump(venue)
    return success(serialize(venue))


@bp.get("/api/venues/<venue_id>/forecasts/wing-prep")
def wing_prep_forecast(venue_id):
    auth(["VenueManager", "Scheduler"])
    venue = get_venue_or_404(venue_id)
    date_str = request.args.get("date")
    if not date_str:
        raise invalid_request("date query parameter is required")
    date = parse_dt(date_str, "date")
    mode = request.args.get("mode", "group_day")

    # 48h window [date 14:00 UTC, date+2 14:00 UTC)
    win_start = date.replace(hour=14, minute=0, second=0, microsecond=0)
    win_end = win_start + timedelta(days=2)

    base_events = [e for e in db.events.values()
                   if e["kind"] == "BASE" and e["status"] == "INGESTED"
                   and win_start <= e["scheduled_start"] < win_end]
    base_att = sum(e["expected_attendance"] for e in base_events)

    overlay_att = 0
    for ov in db.events.values():
        if ov["kind"] != "OVERLAY" or ov["status"] != "INGESTED":
            continue
        if ov.get("lift_pct") is None:
            continue
        # Must temporally overlap at least one BASE event in the window
        overlapping = [b for b in base_events
                       if ov["scheduled_start"] < b["scheduled_end"]
                       and b["scheduled_start"] < ov["scheduled_end"]]
        if not overlapping:
            continue
        overlapping.sort(key=lambda b: (-b["expected_attendance"],
                                        b["scheduled_start"]))
        overlay_att += overlapping[0]["expected_attendance"] * ov["lift_pct"]

    gross = base_att + overlay_att
    dine_in = math.floor(gross * 0.70)
    wing_eaters = math.floor(dine_in * 0.40)
    required_pieces = wing_eaters * 15
    shortage_risk = venue["volatility_score"] > 0.25

    # Group-day classification over the weekend window of the requested week:
    # Friday 18:00 UTC to Sunday 18:00 UTC.
    days_since_friday = (date.weekday() - 4) % 7
    friday = (date - timedelta(days=days_since_friday)).replace(
        hour=18, minute=0, second=0, microsecond=0)
    wk_end = friday + timedelta(days=2)
    leagues = sorted({e["league"] for e in db.events.values()
                      if e["kind"] == "BASE" and e["status"] == "INGESTED"
                      and friday <= e["scheduled_start"] < wk_end})
    weights = {"FF_NFL": 0.5, "FF_NBA": 0.4, "MLB": 0.3, "NHL": 0.3,
               "NCAA": 0.2, "MMA": 0.3, "BOXING": 0.3, "ENTERTAINMENT": 0.1}
    score = sum(weights.get(lg, 0.0) for lg in leagues)
    group_day = score >= 2.0

    return success({
        "required_pieces": int(required_pieces),
        "shortage_risk": shortage_risk,
        "base_attendance": int(base_att),
        "overlay_attendance": int(overlay_att),
        "group_day": group_day,
        "matched_leagues": leagues,
    })


@bp.post("/api/venues/<venue_id>/wing-pricing/quote")
def wing_price_quote(venue_id):
    auth(["Server", "VenueManager"])
    venue = get_venue_or_404(venue_id)
    data = body()
    guest_id = require(data, "guest_id")
    guest = db.guests.get(guest_id)
    if guest is None:
        raise errors.guest_not_found()
    wing_kind = require(data, "wing_kind")
    if wing_kind not in ("TRADITIONAL", "BONELESS"):
        raise invalid_request("wing_kind must be TRADITIONAL or BONELESS")
    pieces = require(data, "pieces")
    if isinstance(pieces, bool) or not isinstance(pieces, int):
        raise invalid_request("pieces must be an integer")
    if pieces < 0:
        raise errors.quantity_invalid("pieces must be non-negative")
    event_date = parse_dt(require(data, "event_date"), "event_date")

    promo = services.find_promo(wing_kind, event_date)
    if promo is not None:
        base_unit = Decimal(promo["promo_price_cents_per_10"]) / Decimal(10)
        promo_applied = True
    else:
        base_unit = Decimal(150)
        promo_applied = False

    qty_mult = Decimal("0.95") if pieces >= 50 else Decimal("1.0")
    quantity_tier_applied = pieces >= 50

    last_30d = services.pieces_for_guest_last_30d(guest_id, venue_id, db.now())
    surcharge = Decimal("1.10") if last_30d > 5000 else Decimal("1.0")
    surcharge_applied = last_30d > 5000

    quote = (base_unit * pieces * qty_mult * surcharge).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)

    return success({
        "quote_cents": int(quote),
        "promo_applied": promo_applied,
        "quantity_tier_applied": quantity_tier_applied,
        "surcharge_applied": surcharge_applied,
    })


# ---------------------------------------------------------------- events

@bp.post("/api/events")
def create_event():
    auth(["Scheduler"])
    data = body()
    kind = require(data, "kind")
    if kind not in EVENT_KINDS:
        raise invalid_request("kind must be BASE, OVERLAY, or PPV")
    league = require(data, "league")
    if league not in LEAGUES:
        raise invalid_request("invalid league")
    title = req_str(data, "title")
    home_market_zip = req_str(data, "home_market_zip")
    expected_attendance = req_int(data, "expected_attendance", minimum=0)
    scheduled_start = parse_dt(require(data, "scheduled_start"), "scheduled_start")
    scheduled_end = parse_dt(require(data, "scheduled_end"), "scheduled_end")
    lift_pct = data.get("lift_pct")
    if kind != "OVERLAY":
        lift_pct = None

    if scheduled_end <= scheduled_start:
        raise errors.event_window_conflict("scheduled_end must be after scheduled_start")
    if kind == "OVERLAY":
        overlaps = any(
            b["kind"] == "BASE" and b["status"] == "INGESTED"
            and scheduled_start < b["scheduled_end"]
            and b["scheduled_start"] < scheduled_end
            for b in db.events.values())
        if not overlaps:
            raise errors.event_window_conflict(
                "OVERLAY event must overlap at least one BASE event")

    ts = now_ts()
    event = {
        "id": services.new_id(), "kind": kind, "league": league, "title": title,
        "home_market_zip": home_market_zip,
        "expected_attendance": expected_attendance,
        "lift_pct": lift_pct, "status": "INGESTED",
        "scheduled_start": scheduled_start, "scheduled_end": scheduled_end,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.events[event["id"]] = event
    return success(serialize(event), code=201)


@bp.get("/api/events")
def list_events():
    auth(ALL)
    league = request.args.get("league")
    kind = request.args.get("kind")
    status = request.args.get("status")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    items = sorted(db.events.values(), key=lambda e: e["created_at"])
    if league is not None:
        items = [e for e in items if e["league"] == league]
    if kind is not None:
        items = [e for e in items if e["kind"] == kind]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if date_from is not None:
        df = parse_dt(date_from, "date_from")
        items = [e for e in items if e["scheduled_start"] >= df]
    if date_to is not None:
        dt_ = parse_dt(date_to, "date_to")
        items = [e for e in items if e["scheduled_start"] <= dt_]
    return list_response(serialize_list(items))


@bp.get("/api/events/<event_id>")
def get_event(event_id):
    auth(ALL)
    return success(serialize(get_event_or_404(event_id)))


@bp.post("/api/events/<event_id>/cancel")
def cancel_event(event_id):
    auth(["Scheduler"])
    event = get_event_or_404(event_id)
    if event["status"] != "INGESTED":
        raise errors.invalid_state("Event is not INGESTED")
    event["status"] = "CANCELLED"
    bump(event)
    # Remove screen assignments referencing this event
    for a in list(db.screen_assignments.values()):
        if a["event_id"] == event_id:
            del db.screen_assignments[a["id"]]
    services.recompute_all_zones()
    return success(serialize(event))


@bp.get("/api/events/<event_id>/zones")
def event_zones(event_id):
    auth(ALL)
    get_event_or_404(event_id)
    items = sorted([z for z in db.zones.values()
                    if z.get("primary_event_id") == event_id],
                   key=lambda z: z["created_at"])
    return list_response(serialize_list(items))


@bp.get("/api/events/<event_id>/screen-assignments")
def event_screen_assignments(event_id):
    auth(ALL)
    get_event_or_404(event_id)
    items = sorted([a for a in db.screen_assignments.values()
                    if a["event_id"] == event_id],
                   key=lambda a: a["created_at"])
    return list_response(serialize_list(items))


@bp.get("/api/events/<event_id>/checks")
def event_checks(event_id):
    auth(["PlatformAdmin", "VenueManager", "Server"])
    get_event_or_404(event_id)
    items = sorted([c for c in db.checks.values()
                    if c.get("event_id") == event_id],
                   key=lambda c: c["created_at"])
    return list_response(serialize_list(items))


@bp.get("/api/events/<event_id>/ppv-events")
def event_ppv_events(event_id):
    auth(["PlatformAdmin", "VenueManager", "Server"])
    get_event_or_404(event_id)
    items = sorted([p for p in db.ppv_events.values()
                    if p["event_id"] == event_id],
                   key=lambda p: p["created_at"])
    return list_response(serialize_list(items))


# ---------------------------------------------------------------- licenses

@bp.post("/api/venues/<venue_id>/licenses")
def create_license(venue_id):
    auth(["VenueManager"])
    venue = get_venue_or_404(venue_id)
    data = body()
    league = require(data, "league")
    if league not in LEAGUES:
        raise invalid_request("invalid league")
    radius = data.get("blackout_radius_miles")
    if radius is not None and (isinstance(radius, bool) or not isinstance(radius, int)):
        raise invalid_request("blackout_radius_miles must be an integer")
    fee = req_int(data, "fee_per_head_cents", minimum=0)
    ts = now_ts()
    lic = {
        "id": services.new_id(), "venue_id": venue["id"], "league": league,
        "blackout_radius_miles": radius, "fee_per_head_cents": fee,
        "status": "PENDING",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.licenses[lic["id"]] = lic
    return success(serialize(lic), code=201)


@bp.get("/api/venues/<venue_id>/licenses")
def list_venue_licenses(venue_id):
    auth(["PlatformAdmin", "VenueManager", "Scheduler"])
    get_venue_or_404(venue_id)
    items = sorted([l for l in db.licenses.values() if l["venue_id"] == venue_id],
                   key=lambda l: l["created_at"])
    league = request.args.get("league")
    status = request.args.get("status")
    if league is not None:
        items = [l for l in items if l["league"] == league]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_response(serialize_list(items))


@bp.get("/api/licenses")
def list_licenses():
    auth(["PlatformAdmin", "VenueManager", "Scheduler"])
    items = sorted(db.licenses.values(), key=lambda l: l["created_at"])
    venue_id = request.args.get("venue_id")
    league = request.args.get("league")
    status = request.args.get("status")
    if venue_id is not None:
        items = [l for l in items if l["venue_id"] == venue_id]
    if league is not None:
        items = [l for l in items if l["league"] == league]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_response(serialize_list(items))


@bp.get("/api/licenses/<license_id>")
def get_license(license_id):
    auth(["PlatformAdmin", "VenueManager", "Scheduler"])
    return success(serialize(get_license_or_404(license_id)))


@bp.post("/api/licenses/<license_id>/activate")
def activate_license(license_id):
    role = auth(["VenueManager", "PlatformAdmin"])
    lic = get_license_or_404(license_id)
    if lic["status"] == "PENDING":
        # Requires no other ACTIVE license for same (venue_id, league)
        for other in db.licenses.values():
            if other["id"] != lic["id"] and other["venue_id"] == lic["venue_id"] \
                    and other["league"] == lic["league"] and other["status"] == "ACTIVE":
                raise errors.invalid_state(
                    "Another ACTIVE license exists for this venue and league")
        if role != "VenueManager":
            raise errors.forbidden()
    elif lic["status"] == "SUSPENDED":
        if role != "PlatformAdmin":
            raise errors.forbidden()
    else:
        raise errors.invalid_state("License cannot be activated from this state")
    lic["status"] = "ACTIVE"
    bump(lic)
    venue = db.venues.get(lic["venue_id"])
    if venue is not None:
        bump(venue)
    services.recompute_all_zones()
    return success(serialize(lic))


@bp.post("/api/licenses/<license_id>/suspend")
def suspend_license(license_id):
    auth(["PlatformAdmin"])
    lic = get_license_or_404(license_id)
    if lic["status"] != "ACTIVE":
        raise errors.invalid_state("License is not ACTIVE")
    lic["status"] = "SUSPENDED"
    bump(lic)
    services.recompute_all_zones()
    return success(serialize(lic))


@bp.post("/api/licenses/<license_id>/terminate")
def terminate_license(license_id):
    auth(["VenueManager"])
    lic = get_license_or_404(license_id)
    if lic["status"] not in ("PENDING", "ACTIVE", "SUSPENDED"):
        raise errors.invalid_state("License cannot be terminated from this state")
    lic["status"] = "TERMINATED"
    bump(lic)
    # Drop zone assignments showing events of this league at this venue
    league_events = {e["id"] for e in db.events.values()
                     if e["league"] == lic["league"]}
    venue_zone_ids = {z["id"] for z in db.zones.values()
                      if z["venue_id"] == lic["venue_id"]}
    for a in list(db.screen_assignments.values()):
        if a["zone_id"] in venue_zone_ids and a["event_id"] in league_events:
            del db.screen_assignments[a["id"]]
    services.recompute_all_zones()
    return success(serialize(lic))


# ---------------------------------------------------------------- zones

@bp.post("/api/venues/<venue_id>/zones")
def create_zone(venue_id):
    auth(["VenueManager"])
    venue = get_venue_or_404(venue_id)
    data = body()
    name = req_str(data, "name")
    screen_ids = require(data, "screen_ids")
    if not isinstance(screen_ids, list) or not all(isinstance(s, str) for s in screen_ids):
        raise invalid_request("screen_ids must be an array of strings")
    ts = now_ts()
    zone = {
        "id": services.new_id(), "venue_id": venue["id"], "name": name,
        "screen_ids": screen_ids, "primary_event_id": None, "posture": "OPEN",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.zones[zone["id"]] = zone
    return success(serialize(zone), code=201)


@bp.get("/api/venues/<venue_id>/zones")
def list_venue_zones(venue_id):
    auth(ALL)
    get_venue_or_404(venue_id)
    items = sorted([z for z in db.zones.values() if z["venue_id"] == venue_id],
                   key=lambda z: z["created_at"])
    return list_response(serialize_list(items))


@bp.get("/api/zones")
def list_zones():
    auth(ALL)
    items = sorted(db.zones.values(), key=lambda z: z["created_at"])
    venue_id = request.args.get("venue_id")
    primary_event_id = request.args.get("primary_event_id")
    if venue_id is not None:
        items = [z for z in items if z["venue_id"] == venue_id]
    if primary_event_id is not None:
        items = [z for z in items if z.get("primary_event_id") == primary_event_id]
    return list_response(serialize_list(items))


@bp.get("/api/zones/<zone_id>")
def get_zone(zone_id):
    auth(ALL)
    return success(serialize(get_zone_or_404(zone_id)))


# ---------------------------------------------------------------- screen assignments

@bp.post("/api/zones/<zone_id>/screen-assignments")
def create_screen_assignment(zone_id):
    auth(["VenueManager", "Host"])
    zone = get_zone_or_404(zone_id)
    venue = db.venues[zone["venue_id"]]
    data = body()
    event_id = require(data, "event_id")
    event = get_event_or_404(event_id)
    screen_id = require(data, "screen_id")
    audio_enabled = data.get("audio_enabled", False)
    if not isinstance(audio_enabled, bool):
        raise invalid_request("audio_enabled must be a boolean")

    # State conflict first (PRD §2.9 priority 4): the screen is already
    # showing a live assignment in this zone.
    for a in db.screen_assignments.values():
        if a["zone_id"] == zone_id and a["screen_id"] == screen_id:
            raise errors.invalid_state("Screen already has a live assignment")
    # Blackout safety (PRD §2.9 priority 5)
    if services.blackout_active_for(event, venue):
        raise errors.blackout_window_active()
    # License must be ACTIVE for the event's league (PRD §2.9 priority 6)
    lic = services.find_license(venue["id"], event["league"])
    if lic is None or lic["status"] != "ACTIVE":
        raise errors.license_not_active()
    # screen_id must belong to zone
    if screen_id not in zone["screen_ids"]:
        raise invalid_request("screen_id does not belong to this zone")

    assignment = {
        "id": services.new_id(), "zone_id": zone_id, "event_id": event_id,
        "screen_id": screen_id, "audio_enabled": audio_enabled,
        "created_at": now_ts(),
    }
    db.screen_assignments[assignment["id"]] = assignment
    services.recompute_zone(zone)
    return success(serialize(assignment), code=201)


@bp.delete("/api/zones/<zone_id>/screen-assignments/<assignment_id>")
def delete_screen_assignment(zone_id, assignment_id):
    auth(["VenueManager", "Host"])
    zone = get_zone_or_404(zone_id)
    a = db.screen_assignments.get(assignment_id)
    if a is None or a["zone_id"] != zone_id:
        raise errors.not_found()
    del db.screen_assignments[assignment_id]
    services.recompute_zone(zone)
    return "", 204


@bp.get("/api/zones/<zone_id>/screen-assignments")
def list_zone_assignments(zone_id):
    auth(ALL)
    get_zone_or_404(zone_id)
    items = sorted([a for a in db.screen_assignments.values()
                    if a["zone_id"] == zone_id],
                   key=lambda a: a["created_at"])
    return list_response(serialize_list(items))


@bp.get("/api/screen-assignments/<assignment_id>")
def get_screen_assignment(assignment_id):
    auth(ALL)
    a = db.screen_assignments.get(assignment_id)
    if a is None:
        raise errors.not_found()
    return success(serialize(a))
