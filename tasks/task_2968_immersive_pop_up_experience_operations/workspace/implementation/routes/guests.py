"""GuestAccount — loyalty, accommodation profile and the no-show strike ladder
(PRD §3.6)."""

from flask import Blueprint

from db import db, new_row, public, touch
from errors import ApiError  # noqa: F401
from middleware import EP, GSA, GUEST, roles
from response import object_response
from services import derive
from services.validate import Body, fail

bp = Blueprint("guests", __name__)

LOYALTY_TIERS = ("VISITOR", "MEMBER", "PATRON")
ACCOMMODATIONS = ("QUIET_ROUTE", "WHEELCHAIR", "ASL_INTERPRETER", "LOW_STIM_HOURS")


@bp.post("/guest-accounts")
@roles(GSA)
def open_account():
    body = Body(require_body=True)
    email = body.string("email", min_len=5, max_len=160)
    if email.count("@") != 1:
        fail("Field 'email' must contain exactly one '@'.")
    display_name = body.string("display_name", min_len=1, max_len=80)
    tier = body.enum("loyalty_tier", LOYALTY_TIERS, required=False,
                     default="VISITOR")
    profile = body.enum_array("accommodation_profile", ACCOMMODATIONS,
                              required=False, default=[])

    # rung 6 — uniqueness, compared case-insensitively
    for peer in db.guests.values():
        if peer["email"].lower() == email.lower():
            raise ApiError("ERR_DUPLICATE_GUEST_EMAIL")

    row = new_row()
    row.update({
        "email": email,
        "display_name": display_name,
        "loyalty_tier": tier,
        "accommodation_profile": profile,
        "experience_credit_cents": 0,
        "no_show_strikes": 0,
        "visit_count": 0,
        "status": "ACTIVE",
    })
    db.guests[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/guest-accounts/<guest_id>")
@roles(GSA, EP, GUEST)
def read_account(guest_id):
    return object_response(public(derive.guest(guest_id)))


@bp.patch("/guest-accounts/<guest_id>")
@roles(GSA)
def update_account(guest_id):
    guest_row = derive.guest(guest_id)
    body = Body()
    if body.has("loyalty_tier"):
        guest_row["loyalty_tier"] = body.enum("loyalty_tier", LOYALTY_TIERS)
    if body.has("display_name"):
        guest_row["display_name"] = body.string("display_name", min_len=1,
                                                max_len=80)
    if body.has("accommodation_profile"):
        guest_row["accommodation_profile"] = body.enum_array(
            "accommodation_profile", ACCOMMODATIONS)
    # already-priced orders are never repriced by a tier change
    touch(guest_row)
    return object_response(public(guest_row))


@bp.post("/guest-accounts/<guest_id>/reinstate")
@roles(GSA)
def reinstate_account(guest_id):
    guest_row = derive.guest(guest_id)
    body = Body()
    body.string("note", required=False, default=None, min_len=1, max_len=500)
    # The catalogue declares no ERR_GUEST_INVALID_STATE, so an account that is
    # not RESTRICTED falls back to the generic request-shape refusal.
    if guest_row["status"] != "RESTRICTED":
        fail("Only a RESTRICTED guest account can be reinstated.")
    guest_row["status"] = "ACTIVE"
    guest_row["no_show_strikes"] = 0
    touch(guest_row)
    return object_response(public(guest_row))
