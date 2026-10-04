"""Party endpoints."""
from flask import Blueprint

import constants as C
import db
import helpers as h
import services as svc
from middleware import guard
from response import ok

bp = Blueprint("parties", __name__)

READ_ROLES = C.ROLES


@bp.route("/service-floor/parties", methods=["POST"])
def create_party():
    guard(["Host"])
    body = h.payload()
    venue = svc.venue_or_404(h.as_string(body, "venue_id"))
    party = db.add("parties", db.new_row(
        venue_id=venue["id"],
        lead_guest_name=h.as_string(body, "lead_guest_name"),
        contact_phone=h.as_string(body, "contact_phone"),
        loyalty_tier=h.as_string(body, "loyalty_tier", required=False,
                                 default="NONE", enum=C.LOYALTY_TIERS),
        no_show_count=0,
        loyalty_credit_cents=0,
        status="ACTIVE",
    ))
    return ok(db.public(party), 201)


@bp.route("/service-floor/parties", methods=["GET"])
def list_parties():
    guard(READ_ROLES)
    rows = h.filter_rows(db.all_of("parties"), venue_id=h.q("venue_id"))
    data, page_meta = h.list_response(rows)
    return ok(data, 200, page_meta)


@bp.route("/service-floor/parties/<party_id>", methods=["GET"])
def get_party(party_id):
    guard(READ_ROLES)
    party = svc.party_or_404(party_id)
    return ok(db.public(party), 200)