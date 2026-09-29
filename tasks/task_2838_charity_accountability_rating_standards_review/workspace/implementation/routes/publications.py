"""The immutable publication ledger."""

from flask import request

from db import rows
from middleware import route
from response import ok
from routes import listing

ALL_ROLES = [
    "MethodologyAdmin",
    "RatingAnalyst",
    "PublishingReviewer",
    "AppealPanelist",
    "OrganizationRep",
    "PublicUser",
]


@route("/publication-records", "GET", ALL_ROLES, paginated=True)
def list_publication_records(ctx):
    args = request.args
    items = rows("PublicationRecord")
    organization_id = args.get("organization_id")
    if organization_id:
        items = [r for r in items if r["organization_id"] == organization_id]
    rating_cycle_id = args.get("rating_cycle_id")
    if rating_cycle_id:
        items = [r for r in items if r["rating_cycle_id"] == rating_cycle_id]
    items = sorted(items, key=lambda r: (r["sequence_number"], r["_seq"]))
    return listing.respond(ctx, items)


@route(
    "/publication-records/<publication_record_id>",
    "GET",
    ALL_ROLES,
    path_params=(("publication_record_id", "PublicationRecord"),),
)
def get_publication_record(ctx):
    return ok(ctx.path["publication_record_id"])
