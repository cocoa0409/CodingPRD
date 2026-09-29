"""Appeals: the organization's challenge to a rejected correction."""

from flask import request

from db import MAX_CORRECTION_ROUNDS, lookup, new_row, rows, store, touch
from errors import ApiError
from middleware import owner_from_body_cycle, route
from response import ok
from routes import listing
from services import cascade

READ_ROLES = [
    "MethodologyAdmin",
    "RatingAnalyst",
    "PublishingReviewer",
    "AppealPanelist",
    "OrganizationRep",
]

LIVE_APPEAL_STATES = ("FILED", "PANEL_ASSIGNED", "GRANTED", "DENIED")

APPEAL_BODY = {
    "rating_cycle_id": {"type": "string", "required": True, "fk": "RatingCycle"},
    "correction_request_id": {
        "type": "string",
        "required": True,
        "fk": "CorrectionRequest",
    },
    "grounds": {
        "type": "string",
        "required": True,
        "min_len": 1,
        "max_len": 2000,
        "non_blank": True,
    },
}


@route(
    "/appeals",
    "POST",
    ["OrganizationRep"],
    body=APPEAL_BODY,
    owner=owner_from_body_cycle,
)
def create_appeal(ctx):
    cycle = ctx.fk["rating_cycle_id"]
    correction = ctx.fk["correction_request_id"]
    # 8 - the cycle must be in ORG_REVIEW
    if cycle["status"] != "ORG_REVIEW":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    # 12 - only a REJECTED correction can be contested
    if correction["status"] != "REJECTED":
        raise ApiError("ERR_CORRECTION_NOT_REJECTED")
    # 16 - strictly before the cycle's appeal deadline
    deadline = cycle["appeal_deadline_at"]
    if deadline is None or not store.now() < deadline:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")
    # 26 - only a DISMISSED appeal leaves room for another
    for other in rows("Appeal"):
        if (
            other["rating_cycle_id"] == cycle["id"]
            and other["status"] in LIVE_APPEAL_STATES
        ):
            raise ApiError("ERR_APPEAL_ALREADY_FILED")

    record = new_row(
        "Appeal",
        dict(
            rating_cycle_id=cycle["id"],
            correction_request_id=correction["id"],
            filed_by_org_user_id=ctx.user_id,
            grounds=ctx.body["grounds"],
            status="FILED",
            panel_member_user_ids=[],
            filed_at=store.now(),
            deadline_at=deadline,
            decided_by_user_id=None,
            decided_at=None,
            decision_note=None,
        ),
    )
    cycle["status"] = "APPEAL_OPEN"
    touch(cycle)
    return ok(record, 201)


@route("/appeals", "GET", READ_ROLES, paginated=True)
def list_appeals(ctx):
    args = request.args
    items = rows("Appeal")
    rating_cycle_id = args.get("rating_cycle_id")
    if rating_cycle_id:
        items = [r for r in items if r["rating_cycle_id"] == rating_cycle_id]
    correction_request_id = args.get("correction_request_id")
    if correction_request_id:
        items = [
            r for r in items if r["correction_request_id"] == correction_request_id
        ]
    status = args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    return listing.respond(ctx, listing.by_created_at(items))


@route(
    "/appeals/<appeal_id>",
    "GET",
    READ_ROLES,
    path_params=(("appeal_id", "Appeal"),),
)
def get_appeal(ctx):
    return ok(ctx.path["appeal_id"])


PANEL_BODY = {
    "panel_member_user_ids": {
        "type": "array",
        "required": True,
        "item": {"type": "string", "non_blank": True},
    },
}


@route(
    "/appeals/<appeal_id>/assign-panel",
    "POST",
    ["MethodologyAdmin"],
    path_params=(("appeal_id", "Appeal"),),
    body=PANEL_BODY,
)
def assign_panel(ctx):
    appeal = ctx.path["appeal_id"]
    cycle = lookup("RatingCycle", appeal["rating_cycle_id"])
    # 8 - state
    if appeal["status"] != "FILED":
        raise ApiError("ERR_APPEAL_STATE_INVALID")
    # 10 - the seating admin may not be the cycle's analyst
    if cycle is not None and ctx.user_id == cycle["assigned_analyst_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # 27 - exactly three distinct ids, excluding analyst and publishing reviewer
    members = ctx.body["panel_member_user_ids"]
    if len(members) != 3 or len(set(members)) != 3:
        raise ApiError("ERR_PANEL_COMPOSITION_INVALID")
    if cycle is not None:
        barred = {
            cycle["assigned_analyst_user_id"],
            cycle["publishing_reviewer_user_id"],
        }
        for member in members:
            if member in barred:
                raise ApiError("ERR_PANEL_COMPOSITION_INVALID")

    appeal["panel_member_user_ids"] = list(members)
    appeal["status"] = "PANEL_ASSIGNED"
    touch(appeal)
    return ok(appeal)


APPEAL_DECIDE_BODY = {
    "decision": {
        "type": "enum",
        "required": True,
        "values": ["GRANT", "DENY", "DISMISS"],
    },
    "decision_note": {"type": "string", "max_len": 2000},
}


@route(
    "/appeals/<appeal_id>/decide",
    "POST",
    ["AppealPanelist"],
    path_params=(("appeal_id", "Appeal"),),
    body=APPEAL_DECIDE_BODY,
)
def decide_appeal(ctx):
    appeal = ctx.path["appeal_id"]
    cycle = lookup("RatingCycle", appeal["rating_cycle_id"])
    decision = ctx.body["decision"]
    # 8 - state
    if appeal["status"] != "PANEL_ASSIGNED":
        raise ApiError("ERR_APPEAL_STATE_INVALID")
    # only a seated panelist may decide
    if ctx.user_id not in (appeal["panel_member_user_ids"] or []):
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    # 25 - a grant rewinds the cycle, so the round limit binds
    if decision == "GRANT":
        if cycle is None or int(cycle["correction_round"] or 0) >= (
            MAX_CORRECTION_ROUNDS
        ):
            raise ApiError("ERR_CORRECTION_ROUND_LIMIT")

    now = store.now()
    appeal["decided_by_user_id"] = ctx.user_id
    appeal["decided_at"] = now
    appeal["decision_note"] = ctx.body["decision_note"]
    if decision == "GRANT":
        appeal["status"] = "GRANTED"
    elif decision == "DENY":
        appeal["status"] = "DENIED"
    else:
        appeal["status"] = "DISMISSED"
    touch(appeal)

    if decision == "GRANT":
        correction = lookup("CorrectionRequest", appeal["correction_request_id"])
        if correction is not None:
            correction["status"] = "ACCEPTED"
            correction["decided_by_user_id"] = ctx.user_id
            correction["decided_at"] = now
            touch(correction)
            cascade.accept_and_rewind(cycle, correction)
    else:
        cycle["status"] = "APPEAL_RESOLVED"
        touch(cycle)
    return ok(appeal)
