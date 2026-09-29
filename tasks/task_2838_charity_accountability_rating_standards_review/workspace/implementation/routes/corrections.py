"""Correction requests: the organization's dispute channel during review."""

from flask import request

from db import (
    APPEAL_WINDOW_DAYS,
    MAX_CORRECTION_ROUNDS,
    SOURCE_KINDS,
    lookup,
    new_row,
    plus_days,
    rows,
    store,
    touch,
)
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

TARGET_KINDS = ["FILING_FINANCIAL", "GOVERNANCE_DISCLOSURE"]


def lookup_cycle(correction):
    return lookup("RatingCycle", correction["rating_cycle_id"])

# the input fields of a filing record and of a governance profile
CORRECTABLE_FIELDS = set(cascade.FILING_COPY_FIELDS) | set(cascade.GOVERNANCE_FIELDS)

CORRECTION_BODY = {
    "rating_cycle_id": {"type": "string", "required": True, "fk": "RatingCycle"},
    "target_kind": {"type": "enum", "required": True, "values": TARGET_KINDS},
    "target_field_name": {
        "type": "string",
        "required": True,
        "min_len": 1,
        "max_len": 100,
        "non_blank": True,
    },
    "proposed_value": {
        "type": "string",
        "required": True,
        "min_len": 1,
        "max_len": 500,
        "non_blank": True,
    },
    "narrative": {
        "type": "string",
        "required": True,
        "min_len": 1,
        "max_len": 2000,
        "non_blank": True,
    },
    "target_fiscal_year": {"type": "int", "min": 2000, "max": 2100},
    "target_source_kind": {"type": "enum", "values": SOURCE_KINDS},
}


@route(
    "/correction-requests",
    "POST",
    ["OrganizationRep"],
    body=CORRECTION_BODY,
    owner=owner_from_body_cycle,
)
def create_correction(ctx):
    body = ctx.body
    if body["target_field_name"] not in CORRECTABLE_FIELDS:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "target_field_name must name an input field of a filing record or a"
            " governance profile.",
        )
    if body["target_kind"] == "FILING_FINANCIAL":
        if body["target_fiscal_year"] is None or body["target_source_kind"] is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "target_fiscal_year and target_source_kind are required for a"
                " FILING_FINANCIAL target.",
            )
        fiscal_year = body["target_fiscal_year"]
        source_kind = body["target_source_kind"]
    else:
        fiscal_year = None
        source_kind = None

    cycle = ctx.fk["rating_cycle_id"]
    # 8 - the cycle must be in ORG_REVIEW
    if cycle["status"] != "ORG_REVIEW":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    # 25 - correction round limit
    if int(cycle["correction_round"] or 0) >= MAX_CORRECTION_ROUNDS:
        raise ApiError("ERR_CORRECTION_ROUND_LIMIT")

    record = new_row(
        "CorrectionRequest",
        dict(
            rating_cycle_id=cycle["id"],
            submitted_by_org_user_id=ctx.user_id,
            round_number=int(cycle["correction_round"] or 0) + 1,
            target_kind=body["target_kind"],
            target_fiscal_year=fiscal_year,
            target_source_kind=source_kind,
            target_field_name=body["target_field_name"],
            proposed_value=body["proposed_value"],
            narrative=body["narrative"],
            status="SUBMITTED",
            claimed_by_user_id=None,
            decided_by_user_id=None,
            decision_note=None,
            decided_at=None,
        ),
    )
    # correction_deadline_at is deliberately retained across this transition
    cycle["status"] = "CORRECTION_REQUESTED"
    touch(cycle)
    return ok(record, 201)


@route("/correction-requests", "GET", READ_ROLES, paginated=True)
def list_corrections(ctx):
    args = request.args
    items = rows("CorrectionRequest")
    rating_cycle_id = args.get("rating_cycle_id")
    if rating_cycle_id:
        items = [r for r in items if r["rating_cycle_id"] == rating_cycle_id]
    status = args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    return listing.respond(ctx, listing.by_created_at(items))


@route(
    "/correction-requests/<correction_request_id>",
    "GET",
    READ_ROLES,
    path_params=(("correction_request_id", "CorrectionRequest"),),
)
def get_correction(ctx):
    return ok(ctx.path["correction_request_id"])


@route(
    "/correction-requests/<correction_request_id>/claim",
    "POST",
    ["RatingAnalyst"],
    path_params=(("correction_request_id", "CorrectionRequest"),),
)
def claim_correction(ctx):
    correction = ctx.path["correction_request_id"]
    cycle = lookup_cycle(correction)
    if correction["status"] != "SUBMITTED":
        raise ApiError("ERR_CORRECTION_STATE_INVALID")
    if cycle is None or ctx.user_id != cycle["assigned_analyst_user_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_ANALYST")
    correction["status"] = "UNDER_ANALYST_REVIEW"
    correction["claimed_by_user_id"] = ctx.user_id
    touch(correction)
    return ok(correction)


DECIDE_BODY = {
    "decision": {"type": "enum", "required": True, "values": ["ACCEPT", "REJECT"]},
    "decision_note": {"type": "string", "max_len": 2000},
}


@route(
    "/correction-requests/<correction_request_id>/decide",
    "POST",
    ["RatingAnalyst"],
    path_params=(("correction_request_id", "CorrectionRequest"),),
    body=DECIDE_BODY,
)
def decide_correction(ctx):
    correction = ctx.path["correction_request_id"]
    cycle = lookup_cycle(correction)
    decision = ctx.body["decision"]
    # 8 - state of the request itself
    if correction["status"] != "UNDER_ANALYST_REVIEW":
        raise ApiError("ERR_CORRECTION_STATE_INVALID")
    # 8 - a rejection needs every other correction of the cycle already decided
    if decision == "REJECT" and cycle is not None:
        for other in cascade.open_corrections(cycle):
            if other["id"] != correction["id"]:
                raise ApiError(
                    "ERR_CORRECTION_STATE_INVALID",
                    "Another correction of this cycle is still open.",
                )
    # 11 - assigned analyst
    if cycle is None or ctx.user_id != cycle["assigned_analyst_user_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_ANALYST")
    # 25 - the acceptance is what the round limit forbids
    if decision == "ACCEPT":
        if int(cycle["correction_round"] or 0) >= MAX_CORRECTION_ROUNDS:
            raise ApiError("ERR_CORRECTION_ROUND_LIMIT")

    correction["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    correction["decided_by_user_id"] = ctx.user_id
    correction["decision_note"] = ctx.body["decision_note"]
    correction["decided_at"] = store.now()
    touch(correction)

    if decision == "ACCEPT":
        cascade.accept_and_rewind(cycle, correction)
    else:
        cycle["status"] = "ORG_REVIEW"
        cycle["appeal_deadline_at"] = plus_days(store.now(), APPEAL_WINDOW_DAYS)
        touch(cycle)
    return ok(correction)
