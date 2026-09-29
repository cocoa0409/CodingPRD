"""Organization registry, rating trend and the organization's filing ledger."""

from flask import request

from db import ORG_TYPES, SOURCE_KINDS, new_row, rows
from errors import ApiError
from middleware import owner_from_path, route
from response import ok, ok_object_paginated
from routes import listing
from services import cascade

ALL_ROLES = [
    "MethodologyAdmin",
    "RatingAnalyst",
    "PublishingReviewer",
    "AppealPanelist",
    "OrganizationRep",
    "PublicUser",
]

ORG_BODY = {
    "legal_name": {"type": "string", "required": True, "min_len": 1, "max_len": 200, "non_blank": True},
    "ein": {"type": "string", "required": True, "pattern": r"^\d{9}$"},
    "org_type": {"type": "enum", "required": True, "values": ORG_TYPES},
    "fiscal_year_end_month": {"type": "int", "required": True, "min": 1, "max": 12},
    "contact_email": {"type": "string", "required": True, "min_len": 1, "contains": "@"},
}


@route("/organizations", "POST", ["MethodologyAdmin"], body=ORG_BODY)
def create_organization(ctx):
    # check 20 - duplicate EIN
    for existing in rows("Organization"):
        if existing["ein"] == ctx.body["ein"]:
            raise ApiError("ERR_DUPLICATE_EIN")
    record = new_row(
        "Organization",
        dict(
            legal_name=ctx.body["legal_name"],
            ein=ctx.body["ein"],
            org_type=ctx.body["org_type"],
            fiscal_year_end_month=ctx.body["fiscal_year_end_month"],
            contact_email=ctx.body["contact_email"],
            latest_published_score=None,
            latest_published_grade=None,
            published_cycle_count=0,
            trend_direction="NOT_APPLICABLE",
            transition_grace_until=None,
            substantiated_complaint_count=0,
        ),
    )
    return ok(record, 201)


@route(
    "/organizations",
    "GET",
    ["MethodologyAdmin", "RatingAnalyst", "PublishingReviewer", "PublicUser"],
    paginated=True,
)
def list_organizations(ctx):
    items = rows("Organization")
    org_type = request.args.get("org_type")
    trend = request.args.get("trend_direction")
    if org_type is not None:
        items = [o for o in items if o["org_type"] == org_type]
    if trend is not None:
        items = [o for o in items if o["trend_direction"] == trend]
    return listing.respond(ctx, listing.by_created_at(items))


@route(
    "/organizations/<organization_id>",
    "GET",
    ALL_ROLES,
    path_params=[("organization_id", "Organization")],
)
def get_organization(ctx):
    return ok(ctx.path["organization_id"])


@route(
    "/organizations/<organization_id>/rating-trend",
    "GET",
    [
        "MethodologyAdmin",
        "RatingAnalyst",
        "PublishingReviewer",
        "OrganizationRep",
        "PublicUser",
    ],
    path_params=[("organization_id", "Organization")],
    paginated=True,
    owner=owner_from_path("organization_id"),
)
def rating_trend(ctx):
    organization = ctx.path["organization_id"]
    history = cascade.publication_rows_for(organization["id"])
    history.reverse()  # newest-first, the donor-facing display order
    total = len(history)
    window = history[ctx.offset: ctx.offset + ctx.limit]
    data = {
        "organization_id": organization["id"],
        "latest_published_score": organization["latest_published_score"],
        "latest_published_grade": organization["latest_published_grade"],
        "published_cycle_count": organization["published_cycle_count"],
        "trend_direction": organization["trend_direction"],
        "points": window,
    }
    return ok_object_paginated(data, ctx.limit, ctx.offset, total, len(window))


@route(
    "/organizations/<id>/filing-records",
    "GET",
    ["MethodologyAdmin", "RatingAnalyst", "OrganizationRep"],
    path_params=[("id", "Organization")],
    paginated=True,
    owner=owner_from_path("id"),
)
def organization_filings(ctx):
    organization = ctx.path["id"]
    items = [
        f for f in rows("FilingRecord") if f["organization_id"] == organization["id"]
    ]
    fiscal_year = listing.int_arg(request.args, "fiscal_year")
    source_kind = request.args.get("source_kind")
    status = request.args.get("status")
    if fiscal_year is not None:
        items = [f for f in items if f["fiscal_year"] == fiscal_year]
    if source_kind is not None:
        items = [f for f in items if f["source_kind"] == source_kind]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items.sort(
        key=lambda f: (-f["fiscal_year"], f["source_precedence"], f["created_at"], f["_seq"])
    )
    return listing.respond(ctx, items)
