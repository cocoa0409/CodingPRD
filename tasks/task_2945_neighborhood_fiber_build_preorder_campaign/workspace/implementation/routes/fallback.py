"""Alternative-technology options and offers (PRD 3.2)."""

from flask import Blueprint

import auth
import calc
import cascades
import envelope
import listing
import serialize
import shape
from errors import ApiError
from store import bump, db, insert, must_find, new_row, now, ordered, rows

bp = Blueprint("fallback", __name__)

READ_ROLES = ("ProgramManager", "InstallCoordinator", "Subscriber")


@bp.post("/fallback-options")
def create_option():
    auth.gate(("ProgramManager",))
    data = shape.body()
    campaign = listing.resolve(data, "campaign_id", "campaigns")
    shape.req_id(data, "campaign_id")
    row = new_row(
        {
            "campaign_id": campaign["id"],
            "technology": shape.req_enum(data, "technology", calc.TECHNOLOGIES),
            "min_downstream_mbps": shape.req_int(data, "min_downstream_mbps", 1),
            "monthly_price_cents": shape.req_int(data, "monthly_price_cents", 0),
            "max_serviceable_distance_m": shape.req_int(data, "max_serviceable_distance_m", 0),
            "priority_rank": shape.req_int(data, "priority_rank", 1),
            "supports_mdu": shape.opt_bool(data, "supports_mdu", False),
            "option_status": shape.opt_enum(data, "option_status", calc.OPTION_STATUSES, "ENABLED"),
        }
    )
    insert("fallback_options", row)
    return envelope.created(serialize.fallback_option(row))


@bp.get("/fallback-options/<option_id>")
def read_option(option_id):
    auth.gate(READ_ROLES)
    row = must_find("fallback_options", option_id)
    return envelope.ok(serialize.fallback_option(row))


@bp.get("/fallback-options")
def list_options():
    auth.gate(READ_ROLES)
    items = listing.apply_filters(
        ordered(rows("fallback_options")),
        (
            listing.fk("campaign_id", "campaign_id", "campaigns"),
            listing.enum("option_status", "option_status", calc.OPTION_STATUSES),
            listing.enum("technology", "technology", calc.TECHNOLOGIES),
        ),
    )
    return envelope.list_response(items, serialize.fallback_option)


@bp.get("/fallback-offers/<offer_id>")
def read_offer(offer_id):
    auth.gate(READ_ROLES)
    row = must_find("fallback_offers", offer_id)
    cascades.expire_offer(row)
    return envelope.ok(serialize.fallback_offer(row))


@bp.get("/fallback-offers")
def list_offers():
    auth.gate(READ_ROLES)
    items = ordered(rows("fallback_offers"))
    for row in items:
        cascades.expire_offer(row)
    items = listing.apply_filters(
        items,
        (
            listing.fk("service_address_id", "service_address_id", "service_addresses"),
            listing.fk("fallback_option_id", "fallback_option_id", "fallback_options"),
            listing.fk("account_id", "account_id", "accounts"),
            listing.enum("status", "status", calc.OFFER_STATUSES),
        ),
    )
    return envelope.list_response(items, serialize.fallback_offer)


@bp.post("/fallback-offers/<offer_id>/response")
def respond(offer_id):
    user_id, role = auth.gate(("Subscriber",))
    offer = must_find("fallback_offers", offer_id)
    auth.own(user_id, role, offer["account_id"])
    data = shape.body()
    response = shape.req_enum(data, "response", calc.OFFER_RESPONSES)
    cascades.expire_offer(offer)
    if offer["status"] != "OFFERED":
        raise ApiError(
            "ERR_FALLBACK_OFFER_STATE_INVALID", "this offer is no longer open for a response"
        )
    offer["status"] = "ACCEPTED" if response == "ACCEPT" else "DECLINED"
    offer["responded_at"] = now()
    bump(offer)
    if response == "ACCEPT":
        address = db.service_addresses.get(offer["service_address_id"])
        if address is not None:
            address["active_fallback_technology"] = offer["technology"]
            bump(address)
    return envelope.ok(serialize.fallback_offer(offer))
