"""Color catalog, vote campaigns, and consumer ballots (PRD section 3.1)."""
from decimal import Decimal

from flask import request

from constants import OPS_ROLES, ROLE_CONSUMER, ROLE_PLATFORM_ADMIN, VOTE_WEIGHTS
from envelope import ok, paginate
from errors import ApiError
from store import STORE, parse_dt
from validation import (
    apply_filters, auth, body, get_or_404, new_entity, opt_bool, opt_int,
    pagination_params, req_dt, req_enum, req_str, require_role, touch,
)

VOTER_SEGMENTS = ("KIDS", "PARENTS", "EDUCATORS", "COLLECTORS")
VOTE_CHOICES = ("YES", "NO")


def serialize_color(color):
    return {
        "id": color["id"],
        "name": color["name"],
        "hex_code": color["hex_code"],
        "is_core_curriculum": color["is_core_curriculum"],
        "status": color["status"],
        "introduced_on": color["introduced_on"],
        "retired_on": color["retired_on"],
        "archive_after_date": color["archive_after_date"],
        "created_at": color["created_at"],
        "updated_at": color["updated_at"],
        "version": color["version"],
    }


def serialize_campaign(c):
    return {
        "id": c["id"],
        "color_id": c["color_id"],
        "kind": c["kind"],
        "opens_on": c["opens_on"],
        "closes_on": c["closes_on"],
        "status": c["status"],
        "votes_yes_weighted": float(c["votes_yes_weighted"]),
        "votes_total_weighted": float(c["votes_total_weighted"]),
        "turnout_count": c["turnout_count"],
        "outcome": c["outcome"],
        "tallied_at": c["tallied_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def create_color():
    _, role = auth()
    require_role(role, {ROLE_PLATFORM_ADMIN})
    data = body()
    name = req_str(data, "name")
    hex_code = req_str(data, "hex_code")
    is_core = opt_bool(data, "is_core_curriculum", False)
    color = new_entity({
        "name": name,
        "hex_code": hex_code,
        "is_core_curriculum": is_core,
        "status": "PROPOSED",
        "introduced_on": None,
        "retired_on": None,
        "archive_after_date": None,
    })
    STORE.colors[color["id"]] = color
    return ok(serialize_color(color), status=201)


def get_color(color_id):
    _, role = auth()
    require_role(role, OPS_ROLES)
    color = get_or_404(STORE.colors, color_id)
    return ok(serialize_color(color))


def create_vote_campaign(color_id):
    _, role = auth()
    require_role(role, {ROLE_PLATFORM_ADMIN})
    data = body()
    kind = req_enum(data, "kind", ("INTRODUCTION", "RETIREMENT"))
    opens_raw, opens = req_dt(data, "opens_on")
    closes_raw, closes = req_dt(data, "closes_on")
    color = get_or_404(STORE.colors, color_id)
    # State gate (stage 6): INTRODUCTION needs PROPOSED, RETIREMENT needs ACTIVE.
    if kind == "INTRODUCTION" and color["status"] != "PROPOSED":
        raise ApiError("ERR_COLOR_NOT_ACTIVE")
    if kind == "RETIREMENT" and color["status"] != "ACTIVE":
        raise ApiError("ERR_COLOR_NOT_ACTIVE")
    # Temporal (stage 8): closes_on strictly after opens_on.
    if closes <= opens:
        raise ApiError("ERR_DATE_ORDER")
    # Structural (stage 9): closed-interval overlap with the color's campaigns.
    for existing in STORE.campaigns.values():
        if existing["color_id"] != color_id:
            continue
        ex_opens = parse_dt(existing["opens_on"])
        ex_closes = parse_dt(existing["closes_on"])
        if opens <= ex_closes and ex_opens <= closes:
            raise ApiError("ERR_CAMPAIGN_WINDOW_CONFLICT")
    campaign = new_entity({
        "color_id": color_id,
        "kind": kind,
        "opens_on": opens_raw,
        "closes_on": closes_raw,
        "status": "SCHEDULED",
        "votes_yes_weighted": Decimal("0"),
        "votes_total_weighted": Decimal("0"),
        "turnout_count": 0,
        "outcome": None,
        "tallied_at": None,
    })
    STORE.campaigns[campaign["id"]] = campaign
    color["status"] = "IN_VOTE" if kind == "INTRODUCTION" else "RETIRE_VOTE"
    touch(color)
    return ok(serialize_campaign(campaign), status=201)


def list_vote_campaigns(color_id):
    _, role = auth()
    require_role(role, OPS_ROLES)
    get_or_404(STORE.colors, color_id)
    limit, offset = pagination_params()
    items = [c for c in STORE.campaigns.values() if c["color_id"] == color_id]
    items = apply_filters(items, [
        ("kind", request.args.get("kind")),
        ("status", request.args.get("status")),
    ])
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, meta = paginate(items, limit, offset)
    return ok([serialize_campaign(c) for c in page], response_type="array", pagination=meta)


def list_color_formulas(color_id):
    from formulas_safety import serialize_formula
    _, role = auth()
    require_role(role, OPS_ROLES)
    get_or_404(STORE.colors, color_id)
    limit, offset = pagination_params()
    items = [f for f in STORE.formulas.values() if f["color_id"] == color_id]
    items = apply_filters(items, [("status", request.args.get("status"))])
    items.sort(key=lambda f: (f["created_at"], f["_seq"]))
    page, meta = paginate(items, limit, offset)
    return ok([serialize_formula(f) for f in page], response_type="array", pagination=meta)


def cast_vote():
    _, role = auth()
    require_role(role, {ROLE_CONSUMER})
    data = body()
    campaign_id = req_str(data, "campaign_id")
    segment = req_str(data, "voter_segment")
    choice = req_str(data, "choice")
    count = opt_int(data, "count", 1)
    campaign = get_or_404(STORE.campaigns, campaign_id)
    # State gate (stage 6).
    if campaign["status"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN")
    # Payload validity (stage 9): unknown segment/choice or count < 1.
    if segment not in VOTER_SEGMENTS or choice not in VOTE_CHOICES or count < 1:
        raise ApiError("ERR_VOTE_INVALID")
    weight = VOTE_WEIGHTS[campaign["kind"]][segment]
    campaign["votes_total_weighted"] += weight * count
    if choice == "YES":
        campaign["votes_yes_weighted"] += weight * count
    campaign["turnout_count"] += count
    touch(campaign)
    return ok({
        "accepted": True,
        "campaign_id": campaign_id,
        "weight_applied": float(weight),
    })


def register(app):
    app.add_url_rule("/crayon-works/colors", view_func=create_color, methods=["POST"])
    app.add_url_rule("/crayon-works/colors/<color_id>", view_func=get_color, methods=["GET"])
    app.add_url_rule("/crayon-works/colors/<color_id>/vote-campaigns",
                     view_func=create_vote_campaign, methods=["POST"])
    app.add_url_rule("/crayon-works/colors/<color_id>/vote-campaigns",
                     view_func=list_vote_campaigns, methods=["GET"])
    app.add_url_rule("/crayon-works/colors/<color_id>/formulas",
                     view_func=list_color_formulas, methods=["GET"])
    app.add_url_rule("/crayon-works/votes", view_func=cast_vote, methods=["POST"])
