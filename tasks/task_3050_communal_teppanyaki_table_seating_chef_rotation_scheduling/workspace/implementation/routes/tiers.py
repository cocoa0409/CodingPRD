"""TableTier endpoints."""
from flask import Blueprint

import constants as C
import db
import helpers as h
import services as svc
from middleware import guard
from response import ok

bp = Blueprint("tiers", __name__)

READ_ROLES = C.ROLES


@bp.route("/service-floor/tiers", methods=["POST"])
def create_tier():
    guard(["PlatformAdmin"])
    body = h.payload()
    venue_id = h.as_string(body, "venue_id")
    venue = svc.venue_or_404(venue_id)
    tier = db.add("tiers", db.new_row(
        venue_id=venue["id"],
        tier_code=h.as_string(body, "tier_code", enum=C.TIER_CODES),
        seat_capacity=h.as_int(body, "seat_capacity", minimum=1),
        over_capacity_ratio=h.as_number(body, "over_capacity_ratio", required=False,
                                        default=1.25),
        base_rate_per_guest_cents=h.as_int(body, "base_rate_per_guest_cents", minimum=0),
        minimum_bill_cents=h.as_int(body, "minimum_bill_cents", minimum=0),
        protein_gram_standard=h.as_int(body, "protein_gram_standard", minimum=0),
        chef_show_minutes=h.as_int(body, "chef_show_minutes", minimum=0),
        turn_time_standard_minutes=h.as_int(body, "turn_time_standard_minutes", minimum=0),
        turn_time_celebration_minutes=h.as_int(body, "turn_time_celebration_minutes",
                                               minimum=0),
        status="ACTIVE",
    ))
    return ok(db.public(tier), 201)


@bp.route("/service-floor/tiers", methods=["GET"])
def list_tiers():
    guard(READ_ROLES)
    rows = h.filter_rows(db.all_of("tiers"), venue_id=h.q("venue_id"),
                         tier_code=h.q("tier_code"))
    data, page_meta = h.list_response(rows)
    return ok(data, 200, page_meta)


@bp.route("/service-floor/tiers/<tier_id>", methods=["GET"])
def get_tier(tier_id):
    guard(READ_ROLES)
    tier = svc.tier_or_404(tier_id)
    return ok(db.public(tier), 200)