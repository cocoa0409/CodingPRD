"""Methodology versions, public comments and transition grants."""

from datetime import timedelta
from decimal import Decimal

from flask import request

from db import (
    METHODOLOGY_BUFFER_DAYS,
    TRANSITION_GRANT_DELTA,
    d,
    lookup,
    new_row,
    plus_days,
    q2,
    q4,
    rows,
    store,
    touch,
)
from errors import ApiError
from middleware import route, validate_field
from response import ok
from routes import listing
from services import calc, cascade, scoring

WEIGHT_FIELDS = [
    "weight_financial_health",
    "weight_accountability",
    "weight_transparency",
    "weight_impact",
]

READ_ROLES = [
    "MethodologyAdmin",
    "RatingAnalyst",
    "PublishingReviewer",
    "OrganizationRep",
    "PublicUser",
]
ALL_ROLES = READ_ROLES + ["AppealPanelist"]

WEIGHT_SPEC = {"type": "number", "required": True, "scale": 4}

DRAFT_BODY = {
    "version_label": {"type": "string", "required": True, "min_len": 1, "max_len": 32},
    "weight_financial_health": WEIGHT_SPEC,
    "weight_accountability": WEIGHT_SPEC,
    "weight_transparency": WEIGHT_SPEC,
    "weight_impact": WEIGHT_SPEC,
    "dimension_floor_score": {
        "type": "number",
        "min": "0.00",
        "max": "100.00",
        "scale": 2,
        "default": Decimal("40.00"),
    },
    "comment_period_days": {"type": "int", "min": 7, "max": 120, "default": 30},
    "transition_period_days": {"type": "int", "min": 0, "max": 365, "default": 90},
    "supersedes_version_id": {"type": "string"},
    "revision_note": {"type": "string"},
}


def _check_weights(values):
    total = Decimal(0)
    for field in WEIGHT_FIELDS:
        weight = q4(values[field])
        if weight <= 0:
            raise ApiError("ERR_WEIGHTS_NOT_NORMALIZED")
        total += weight
    if total != Decimal("1.0000"):
        raise ApiError("ERR_WEIGHTS_NOT_NORMALIZED")


@route("/methodology-versions", "POST", ["MethodologyAdmin"], body=DRAFT_BODY)
def create_methodology(ctx):
    # check 19 - weight normalisation
    _check_weights(ctx.body)
    # check 21 - unique version label
    for existing in rows("MethodologyVersion"):
        if existing["version_label"] == ctx.body["version_label"]:
            raise ApiError("ERR_DUPLICATE_VERSION_LABEL")
    record = new_row(
        "MethodologyVersion",
        dict(
            version_label=ctx.body["version_label"],
            status="DRAFT",
            supersedes_version_id=ctx.body["supersedes_version_id"],
            weight_financial_health=q4(ctx.body["weight_financial_health"]),
            weight_accountability=q4(ctx.body["weight_accountability"]),
            weight_transparency=q4(ctx.body["weight_transparency"]),
            weight_impact=q4(ctx.body["weight_impact"]),
            dimension_floor_score=q2(ctx.body["dimension_floor_score"]),
            comment_period_days=ctx.body["comment_period_days"],
            transition_period_days=ctx.body["transition_period_days"],
            comment_open_at=None,
            comment_closed_at=None,
            comment_deadline_at=None,
            adopted_at=None,
            retired_at=None,
            effective_from=None,
            effective_until=None,
            revision_note=ctx.body["revision_note"],
            comment_count=0,
            unresolved_comment_count=0,
        ),
    )
    return ok(record, 201)


@route("/methodology-versions", "GET", READ_ROLES, paginated=True)
def list_methodologies(ctx):
    items = rows("MethodologyVersion")
    status = request.args.get("status")
    supersedes = request.args.get("supersedes_version_id")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if supersedes is not None:
        items = [m for m in items if m["supersedes_version_id"] == supersedes]
    return listing.respond(ctx, listing.by_created_at(items))


@route(
    "/methodology-versions/<methodology_version_id>",
    "GET",
    ALL_ROLES,
    path_params=[("methodology_version_id", "MethodologyVersion")],
)
def get_methodology(ctx):
    return ok(ctx.path["methodology_version_id"])


def refresh_comment_counts(version):
    comments = [
        c for c in rows("PublicComment") if c["methodology_version_id"] == version["id"]
    ]
    version["comment_count"] = len(comments)
    version["unresolved_comment_count"] = sum(
        1 for c in comments if c["status"] == "SUBMITTED"
    )


@route(
    "/methodology-versions/<methodology_version_id>/open-comment",
    "POST",
    ["MethodologyAdmin"],
    path_params=[("methodology_version_id", "MethodologyVersion")],
)
def open_comment(ctx):
    version = ctx.path["methodology_version_id"]
    if version["status"] != "DRAFT":
        raise ApiError("ERR_METHODOLOGY_STATE_INVALID")
    version["status"] = "COMMENT_OPEN"
    version["comment_open_at"] = store.now()
    version["comment_deadline_at"] = plus_days(
        version["comment_open_at"], version["comment_period_days"]
    )
    touch(version)
    return ok(version)


@route(
    "/methodology-versions/<methodology_version_id>/close-comment",
    "POST",
    ["MethodologyAdmin"],
    path_params=[("methodology_version_id", "MethodologyVersion")],
)
def close_comment(ctx):
    version = ctx.path["methodology_version_id"]
    if version["status"] != "COMMENT_OPEN":
        raise ApiError("ERR_METHODOLOGY_STATE_INVALID")
    version["status"] = "COMMENT_CLOSED"
    version["comment_closed_at"] = store.now()
    refresh_comment_counts(version)
    touch(version)
    return ok(version)


RETURN_BODY = {
    "revision_note": {"type": "string", "required": True, "min_len": 1},
    "weight_financial_health": {"type": "number", "scale": 4},
    "weight_accountability": {"type": "number", "scale": 4},
    "weight_transparency": {"type": "number", "scale": 4},
    "weight_impact": {"type": "number", "scale": 4},
    "dimension_floor_score": {"type": "number", "min": "0.00", "max": "100.00", "scale": 2},
}


@route(
    "/methodology-versions/<methodology_version_id>/return-to-draft",
    "POST",
    ["MethodologyAdmin"],
    path_params=[("methodology_version_id", "MethodologyVersion")],
    body=RETURN_BODY,
)
def return_to_draft(ctx):
    version = ctx.path["methodology_version_id"]
    supplied = [f for f in WEIGHT_FIELDS if ctx.body.get(f) is not None]
    if supplied and len(supplied) != 4:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Weights are all-or-nothing: supply all four or none.",
        )
    if version["status"] != "COMMENT_CLOSED":
        raise ApiError("ERR_METHODOLOGY_STATE_INVALID")
    if supplied:
        _check_weights(ctx.body)
        for field in WEIGHT_FIELDS:
            version[field] = q4(ctx.body[field])
    if ctx.body.get("dimension_floor_score") is not None:
        version["dimension_floor_score"] = q2(ctx.body["dimension_floor_score"])
    version["revision_note"] = ctx.body["revision_note"]
    version["status"] = "DRAFT"
    version["comment_open_at"] = None
    version["comment_deadline_at"] = None
    version["comment_closed_at"] = None
    touch(version)
    return ok(version)


ADOPT_BODY = {
    "effective_from": {"type": "datetime", "required": True},
    "effective_until": {"type": "datetime"},
}


def _window_conflict(version, effective_from, effective_until):
    if effective_from < plus_days(store.now(), METHODOLOGY_BUFFER_DAYS):
        return True
    if effective_until is not None and effective_until <= effective_from:
        return True
    exempt = version.get("supersedes_version_id")
    for other in rows("MethodologyVersion"):
        if other["id"] == version["id"] or other["status"] != "ADOPTED":
            continue
        if exempt is not None and other["id"] == exempt:
            continue
        if other["effective_until"] is None:
            # open-ended predecessors are never overlapped by a successor
            continue
        other_from = other["effective_from"]
        if other_from is None:
            continue
        if effective_from <= other["effective_until"] and (
            effective_until is None or effective_until >= other_from
        ):
            return True
    return False


@route(
    "/methodology-versions/<methodology_version_id>/adopt",
    "POST",
    ["MethodologyAdmin"],
    path_params=[("methodology_version_id", "MethodologyVersion")],
    body=ADOPT_BODY,
)
def adopt(ctx):
    version = ctx.path["methodology_version_id"]
    if version["status"] != "COMMENT_CLOSED":
        raise ApiError("ERR_METHODOLOGY_STATE_INVALID")
    effective_from = ctx.body["effective_from"]
    effective_until = ctx.body["effective_until"]
    # check 17 precedes check 24 in the ladder
    if _window_conflict(version, effective_from, effective_until):
        raise ApiError("ERR_METHODOLOGY_WINDOW_CONFLICT")
    if int(version["unresolved_comment_count"] or 0) != 0:
        raise ApiError("ERR_UNRESOLVED_COMMENTS")

    now = store.now()
    # hop 1
    version["status"] = "ADOPTED"
    version["adopted_at"] = now
    version["effective_from"] = effective_from
    version["effective_until"] = effective_until
    touch(version)

    retiring = None
    predecessor = lookup("MethodologyVersion", version.get("supersedes_version_id"))
    if predecessor is not None and predecessor["status"] == "ADOPTED":
        predecessor["status"] = "RETIRED"
        predecessor["retired_at"] = now
        predecessor["effective_until"] = effective_from
        touch(predecessor)
        retiring = predecessor

    # hop 2 - the impact projection, caused by hop one's retirement
    if retiring is not None:
        weights = calc.declared_weights(version)
        floor = d(version["dimension_floor_score"])
        weight_changed = any(
            q4(version[field]) != q4(retiring[field]) for field in WEIGHT_FIELDS
        )
        grace_until = plus_days(now, version["transition_period_days"])
        for organization in rows("Organization"):
            if int(organization["published_cycle_count"] or 0) < 1:
                continue
            history = cascade.publication_rows_for(organization["id"])
            if not history:
                continue
            record = history[-1]
            cycle = lookup("RatingCycle", record["rating_cycle_id"])
            if cycle is None:
                continue
            projected = calc.composite(
                weights,
                floor,
                scoring.dimension_rows(cycle),
                int(cycle["failed_standard_count"] or 0),
                cycle["data_completeness_pct"],
                "final",
            )
            if organization["latest_published_score"] is None:
                continue
            delta = q2(
                d(projected["composite"]) - d(organization["latest_published_score"])
            )
            if delta > TRANSITION_GRANT_DELTA:
                continue
            grant = new_row(
                "TransitionGrant",
                dict(
                    organization_id=organization["id"],
                    methodology_version_id=version["id"],
                    superseded_version_label=retiring["version_label"],
                    status="ACTIVE",
                    grace_until=grace_until,
                    trigger_reason=(
                        "WEIGHT_CHANGE" if weight_changed else "THRESHOLD_TIGHTENED"
                    ),
                    projected_score_delta=delta,
                ),
            )
            # hop 3 - propagate the grace
            existing = organization["transition_grace_until"]
            organization["transition_grace_until"] = (
                grant["grace_until"]
                if existing is None or grant["grace_until"] > existing
                else existing
            )
            touch(organization)
            for cycle_row in rows("RatingCycle"):
                if (
                    cycle_row["organization_id"] == organization["id"]
                    and cycle_row["status"] not in ("PUBLISHED", "WITHDRAWN")
                ):
                    cycle_row["methodology_pin_locked"] = True
    return ok(version)


# ---------------------------------------------------------------- comments

COMMENT_BODY = {
    "methodology_version_id": {
        "type": "string",
        "required": True,
        "fk": "MethodologyVersion",
    },
    "commenter_kind": {
        "type": "enum",
        "required": True,
        "values": ["DONOR", "RATED_ORGANIZATION", "PUBLIC"],
    },
    "body": {"type": "string", "required": True, "min_len": 1, "max_len": 2000, "non_blank": True},
}


@route(
    "/methodology-versions/<id>/public-comments",
    "GET",
    ["MethodologyAdmin", "RatingAnalyst", "OrganizationRep", "PublicUser"],
    path_params=[("id", "MethodologyVersion")],
    paginated=True,
)
def list_version_comments(ctx):
    version = ctx.path["id"]
    items = [
        c for c in rows("PublicComment") if c["methodology_version_id"] == version["id"]
    ]
    status = request.args.get("status")
    kind = request.args.get("commenter_kind")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if kind is not None:
        items = [c for c in items if c["commenter_kind"] == kind]
    return listing.respond(ctx, listing.by_created_at(items))


@route(
    "/public-comments",
    "POST",
    ["PublicUser", "OrganizationRep"],
    body=COMMENT_BODY,
)
def create_comment(ctx):
    version = ctx.fk["methodology_version_id"]
    # check 23 - the comment period must be open, deadline inclusive
    if version["status"] != "COMMENT_OPEN":
        raise ApiError("ERR_COMMENT_PERIOD_CLOSED")
    deadline = version["comment_deadline_at"]
    if deadline is None or store.now() > deadline:
        raise ApiError("ERR_COMMENT_PERIOD_CLOSED")
    record = new_row(
        "PublicComment",
        dict(
            methodology_version_id=version["id"],
            commenter_kind=ctx.body["commenter_kind"],
            commenter_user_id=ctx.user_id,
            body=ctx.body["body"],
            status="SUBMITTED",
            disposition_note=None,
        ),
    )
    refresh_comment_counts(version)
    touch(version)
    return ok(record, 201)


DISPOSE_BODY = {
    "disposition": {
        "type": "enum",
        "required": True,
        "values": ["INCORPORATED", "DECLINED"],
    },
    "disposition_note": {"type": "string"},
}


@route(
    "/public-comments/<public_comment_id>/dispose",
    "POST",
    ["MethodologyAdmin"],
    path_params=[("public_comment_id", "PublicComment")],
    body=DISPOSE_BODY,
)
def dispose_comment(ctx):
    comment = ctx.path["public_comment_id"]
    comment["status"] = ctx.body["disposition"]
    comment["disposition_note"] = ctx.body["disposition_note"]
    touch(comment)
    version = lookup("MethodologyVersion", comment["methodology_version_id"])
    if version is not None:
        refresh_comment_counts(version)
        touch(version)
    return ok(comment)


# ---------------------------------------------------------------- grants


@route(
    "/transition-grants",
    "GET",
    ["MethodologyAdmin", "RatingAnalyst", "OrganizationRep"],
    paginated=True,
)
def list_grants(ctx):
    items = rows("TransitionGrant")
    organization_id = request.args.get("organization_id")
    version_id = request.args.get("methodology_version_id")
    status = request.args.get("status")
    if organization_id is not None:
        items = [g for g in items if g["organization_id"] == organization_id]
    if version_id is not None:
        items = [g for g in items if g["methodology_version_id"] == version_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    return listing.respond(ctx, listing.by_created_at(items))


@route(
    "/transition-grants/<transition_grant_id>",
    "GET",
    ["MethodologyAdmin", "RatingAnalyst", "OrganizationRep"],
    path_params=[("transition_grant_id", "TransitionGrant")],
)
def get_grant(ctx):
    return ok(ctx.path["transition_grant_id"])
