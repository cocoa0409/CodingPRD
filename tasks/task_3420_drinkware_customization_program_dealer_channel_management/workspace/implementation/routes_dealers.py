"""Dealer registration, reads, and standing transitions (suspend / reinstate /
terminate) with the allocation-forfeiture and application-rejection cascades."""
from flask import Blueprint, request

from auth import context, forbidden, require_roles
from calc import dealer_infraction_points, forfeit_allocations_for_dealer
from constants import (
    DEFAULT_CREDIT_LIMIT_CENTS, PROBATION_THRESHOLD, SUSPEND_THRESHOLD,
)
from envelope import (
    get_body, new_entity, opt_enum, opt_int, req_enum, req_int, req_number,
    req_str, sort_created, success, success_list, touch,
)
from errors import fail
from serialize import ser_dealer
from store import DB

bp = Blueprint("dealers", __name__)

TIERS = ("STANDARD", "PREMIER")


def load_dealer(dealer_id):
    d = DB.dealers.get(dealer_id)
    if d is None:
        fail("ERR_DEALER_NOT_FOUND", "no dealer with id %s" % dealer_id)
    return d


@bp.post("/drinkware/dealers")
def create_dealer():
    _, role = context()
    require_roles(role, ["PlatformAdmin"])
    body = get_body()
    legal_name = req_str(body, "legal_name")
    storefront_address = req_str(body, "storefront_address")
    region_code = req_str(body, "region_code")
    tier = opt_enum(body, "tier", TIERS) or "STANDARD"
    credit_limit = opt_int(body, "credit_limit_cents", minimum=0)
    if credit_limit is None:
        credit_limit = DEFAULT_CREDIT_LIMIT_CENTS
    sell_through = req_number(body, "sell_through_pct", minimum=0, maximum=100)
    tenure = req_int(body, "tenure_years", minimum=0)
    dealer = new_entity({
        "legal_name": legal_name,
        "storefront_address": storefront_address,
        "region_code": region_code,
        "tier": tier,
        "credit_limit_cents": credit_limit,
        "sell_through_pct": sell_through,
        "tenure_years": tenure,
        "status": "PENDING",
        "storefront_verified": False,
        "brand_presentation_score": 0,
    })
    DB.dealers[dealer["id"]] = dealer
    return success(ser_dealer(dealer), 201)


@bp.get("/drinkware/dealers/<dealer_id>")
def get_dealer(dealer_id):
    uid, role = context()
    require_roles(role, ["PlatformAdmin", "ChannelManager", "Dealer", "WarrantyAgent"])
    dealer = load_dealer(dealer_id)
    if role == "Dealer" and dealer["id"] != uid:
        forbidden("Dealer role may read only its own record")
    return success(ser_dealer(dealer))


@bp.get("/drinkware/dealers")
def list_dealers():
    _, role = context()
    require_roles(role, ["PlatformAdmin", "ChannelManager", "WarrantyAgent"])
    status = request.args.get("status")
    tier = request.args.get("tier")
    items = sort_created(list(DB.dealers.values()))
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if tier is not None:
        items = [d for d in items if d["tier"] == tier]
    return success_list([ser_dealer(d) for d in items])


@bp.post("/drinkware/dealers/<dealer_id>/suspend")
def suspend_dealer(dealer_id):
    _, role = context()
    require_roles(role, ["ChannelManager"])
    dealer = load_dealer(dealer_id)
    body = get_body()
    req_str(body, "reason")
    if dealer["status"] not in ("AUTHORIZED", "PROBATION"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an AUTHORIZED or PROBATION dealer can be suspended")
    dealer["status"] = "SUSPENDED"
    forfeit_allocations_for_dealer(dealer["id"], "DEALER_SUSPENDED")
    touch(dealer)
    return success(ser_dealer(dealer))


@bp.post("/drinkware/dealers/<dealer_id>/reinstate")
def reinstate_dealer(dealer_id):
    _, role = context()
    require_roles(role, ["ChannelManager"])
    dealer = load_dealer(dealer_id)
    get_body()
    if dealer["status"] not in ("SUSPENDED", "PROBATION"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a SUSPENDED or PROBATION dealer can be reinstated")
    points = dealer_infraction_points(dealer["id"])
    # The landing state is derived from live points, never caller-chosen.
    if points < PROBATION_THRESHOLD:
        dealer["status"] = "AUTHORIZED"
    elif points < SUSPEND_THRESHOLD and dealer["status"] == "SUSPENDED":
        dealer["status"] = "PROBATION"
    else:
        fail("ERR_INVALID_STATE_TRANSITION",
             "live infraction points do not permit reinstatement")
    touch(dealer)
    return success(ser_dealer(dealer))


@bp.post("/drinkware/dealers/<dealer_id>/terminate")
def terminate_dealer(dealer_id):
    _, role = context()
    require_roles(role, ["ChannelManager"])
    dealer = load_dealer(dealer_id)
    body = get_body()
    req_str(body, "reason")
    if dealer["status"] not in ("PENDING", "AUTHORIZED", "PROBATION", "SUSPENDED"):
        fail("ERR_INVALID_STATE_TRANSITION", "dealer is already TERMINATED")
    dealer["status"] = "TERMINATED"
    forfeit_allocations_for_dealer(dealer["id"], "DEALER_TERMINATED")
    for app in DB.applications.values():
        if app["dealer_id"] == dealer["id"] and app["status"] in ("SUBMITTED", "VETTING"):
            app["status"] = "REJECTED"
            app["decision_reason"] = "dealer terminated"
            touch(app)
    touch(dealer)
    return success(ser_dealer(dealer))
