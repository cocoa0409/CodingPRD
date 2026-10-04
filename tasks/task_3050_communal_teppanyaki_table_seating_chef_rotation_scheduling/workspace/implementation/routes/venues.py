"""Venue endpoints plus the venue-scoped operations."""
from decimal import Decimal

from flask import Blueprint

import calculations as calc
import constants as C
import db
import helpers as h
import services as svc
from middleware import authenticate, guard
from response import ok

bp = Blueprint("venues", __name__)

READ_ROLES = C.ROLES


@bp.route("/service-floor/venues", methods=["POST"])
def create_venue():
    # The only endpoint besides the clock that does not require auth headers.
    body = h.payload()
    venue = db.add("venues", db.new_row(
        venue_name=h.as_string(body, "venue_name"),
        city_code=h.as_string(body, "city_code"),
        ventilation_zone=h.as_string(body, "ventilation_zone", enum=C.ZONES),
        status="ACTIVE",
        occupancy_freeze=False,
        hood_filter_life_index=0,
        filter_service_threshold_index=h.as_int(
            body, "filter_service_threshold_index", required=False,
            default=C.FILTER_SERVICE_THRESHOLD_DEFAULT),
        ops_epoch=0,
        shortfall_turn_debt_minutes=0,
        protein_cost_cents=0,
        restaurant_charge_cents=0,
    ))
    return ok(db.public(venue), 201)


@bp.route("/service-floor/venues", methods=["GET"])
def list_venues():
    guard(READ_ROLES)
    rows = h.filter_rows(db.all_of("venues"), city_code=h.q("city_code"))
    data, page_meta = h.list_response(rows)
    return ok(data, 200, page_meta)


@bp.route("/service-floor/venues/<venue_id>", methods=["GET"])
def get_venue(venue_id):
    guard(READ_ROLES)
    venue = svc.venue_or_404(venue_id)
    return ok(db.public(venue), 200)


@bp.route("/service-floor/venues/<venue_id>/run_ops", methods=["POST"])
def run_ops(venue_id):
    guard(["FloorManager"])
    venue = svc.venue_or_404(venue_id)
    return ok(db.public(svc.run_ops(venue)), 200)


@bp.route("/service-floor/venues/<venue_id>/cost-report", methods=["GET"])
def cost_report(venue_id):
    guard(READ_ROLES)
    venue = svc.venue_or_404(venue_id)
    tables = [t for t in db.all_of("tables") if t.get("venue_id") == venue["id"]]
    count = calc.billable_guest_count(tables)
    cost = calc.venue_cost_report(tables, db.DB["tiers"])
    return ok({"venue_cost_cents": cost, "billable_guest_count": count}, 200)


@bp.route("/service-floor/venues/<venue_id>/protein-cost-report", methods=["GET"])
def protein_cost_report(venue_id):
    guard(READ_ROLES)
    venue = svc.venue_or_404(venue_id)
    tickets = [t for t in db.all_of("protein_tickets")
               if t.get("venue_id") == venue["id"] and t.get("status") == "POSTED"]
    cost = sum(int(t.get("cost_cents", 0)) for t in tickets)
    variance = sum(t.get("variance_grams", 0) for t in tickets)
    allowance = int(calc.round_half_up(
        Decimal(str(C.PROTEIN_GRAM_COST_CONTROL_PCT)) * Decimal(cost), 0))
    return ok({"protein_cost_cents": cost,
               "control_allowance_cents": allowance,
               "variance_grams_total": variance}, 200)


@bp.route("/service-floor/venues/<venue_id>/tiers/<tier_id>/retire", methods=["POST"])
def retire_tier(venue_id, tier_id):
    guard(["PlatformAdmin"])
    svc.venue_or_404(venue_id)
    tier = svc.tier_or_404(tier_id)
    tier = db.touch(tier, status="RETIRED")
    return ok(db.public(tier), 200)


@bp.route("/service-floor/venues/<venue_id>/tables/<table_id>/maintenance-release",
          methods=["POST"])
def maintenance_release(venue_id, table_id):
    guard(["FloorManager"])
    venue = svc.venue_or_404(venue_id)
    table = svc.table_or_404(table_id)
    body = h.payload()
    expected = h.as_int(body, "expected_venue_version", required=False)
    if expected is not None and expected != venue.get("version"):
        from errors import fail
        fail("ERR_STALE_VERSION")
    table = svc.release_table_from_maintenance(venue, table)
    return ok(db.public(table), 200)