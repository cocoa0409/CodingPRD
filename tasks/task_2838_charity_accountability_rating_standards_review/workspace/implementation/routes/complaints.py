"""Complaints: intake, triage, investigation findings and the accountability cascade."""

from flask import request

from db import (
    INVESTIGATION_DAYS,
    lookup,
    new_row,
    plus_days,
    rows,
    store,
    touch,
)
from errors import ApiError
from middleware import route
from response import ok
from routes import listing
from services import calc, cascade, scoring

READ_ROLES = [
    "MethodologyAdmin",
    "RatingAnalyst",
    "PublishingReviewer",
    "AppealPanelist",
    "OrganizationRep",
]

COMPLAINANT_KINDS = ["DONOR", "BENEFICIARY", "EMPLOYEE", "ANONYMOUS"]
CATEGORIES = [
    "MISUSE_OF_FUNDS",
    "GOVERNANCE",
    "SOLICITATION_PRACTICE",
    "TRANSPARENCY",
    "OTHER",
]
RESCORE_NOTE = "cycle re-scored after substantiated complaint"
REVIEW_TRACK = ("ORG_REVIEW", "CORRECTION_REQUESTED", "APPEAL_OPEN")

COMPLAINT_BODY = {
    "organization_id": {"type": "string", "required": True, "fk": "Organization"},
    "complainant_kind": {
        "type": "enum",
        "required": True,
        "values": COMPLAINANT_KINDS,
    },
    "category": {"type": "enum", "required": True, "values": CATEGORIES},
    "narrative": {
        "type": "string",
        "required": True,
        "min_len": 1,
        "max_len": 4000,
        "non_blank": True,
    },
    "corroborating_document_count": {
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 50,
    },
}


@route(
    "/complaints",
    "POST",
    ["PublicUser", "OrganizationRep"],
    body=COMPLAINT_BODY,
)
def create_complaint(ctx):
    organization = ctx.fk["organization_id"]
    record = new_row(
        "Complaint",
        dict(
            organization_id=organization["id"],
            penalized_rating_cycle_id=None,
            complainant_kind=ctx.body["complainant_kind"],
            complainant_user_id=ctx.user_id,
            category=ctx.body["category"],
            narrative=ctx.body["narrative"],
            corroborating_document_count=ctx.body["corroborating_document_count"],
            status="INTAKE",
            credibility_score=None,
            credibility_variant=None,
            severity_tier=None,
            investigation_due_at=None,
            penalty_points_applied=0,
            triage_note=None,
            finding_note=None,
            referred_to=None,
            reversal_reason=None,
            resolved_at=None,
        ),
    )
    return ok(record, 201)


@route("/complaints", "GET", READ_ROLES, paginated=True)
def list_complaints(ctx):
    args = request.args
    items = rows("Complaint")
    organization_id = args.get("organization_id")
    if organization_id:
        items = [r for r in items if r["organization_id"] == organization_id]
    penalized = args.get("penalized_rating_cycle_id")
    if penalized:
        items = [r for r in items if r["penalized_rating_cycle_id"] == penalized]
    status = args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    category = args.get("category")
    if category:
        items = [r for r in items if r["category"] == category]
    return listing.respond(ctx, listing.by_created_at(items))


@route(
    "/complaints/<complaint_id>",
    "GET",
    READ_ROLES,
    path_params=(("complaint_id", "Complaint"),),
)
def get_complaint(ctx):
    return ok(ctx.path["complaint_id"])


TRIAGE_BODY = {
    "disposition": {
        "type": "enum",
        "required": True,
        "values": ["INVESTIGATE", "CLOSE_NO_ACTION", "REFER_OUT"],
    },
    "triage_note": {"type": "string", "max_len": 2000},
    "referred_to": {"type": "string", "max_len": 200, "non_blank": True},
}


@route(
    "/complaints/<complaint_id>/triage",
    "POST",
    ["RatingAnalyst"],
    path_params=(("complaint_id", "Complaint"),),
    body=TRIAGE_BODY,
)
def triage(ctx):
    complaint = ctx.path["complaint_id"]
    disposition = ctx.body["disposition"]
    # 5 - referred_to is required for a referral
    if disposition == "REFER_OUT" and not ctx.body["referred_to"]:
        raise ApiError("ERR_INVALID_REQUEST", "referred_to is required for REFER_OUT.")
    # 8 - state
    if complaint["status"] != "INTAKE":
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")

    now = store.now()
    complaint["triage_note"] = ctx.body["triage_note"]
    if disposition == "INVESTIGATE":
        score = calc.credibility_score(complaint, "intake")
        complaint["credibility_score"] = score
        complaint["credibility_variant"] = "INTAKE"
        complaint["severity_tier"] = calc.severity_tier(score)
        complaint["investigation_due_at"] = plus_days(now, INVESTIGATION_DAYS)
        complaint["status"] = "INVESTIGATING"
    elif disposition == "CLOSE_NO_ACTION":
        complaint["resolved_at"] = now
        complaint["status"] = "CLOSED_NO_ACTION"
    else:
        score = calc.credibility_score(complaint, "intake")
        complaint["credibility_score"] = score
        complaint["credibility_variant"] = "INTAKE"
        complaint["severity_tier"] = calc.severity_tier(score)
        complaint["referred_to"] = ctx.body["referred_to"]
        complaint["resolved_at"] = now
        complaint["status"] = "REFERRED_OUT"
    touch(complaint)
    return ok(complaint)


RESOLVE_BODY = {
    "finding": {
        "type": "enum",
        "required": True,
        "values": ["SUBSTANTIATED", "UNSUBSTANTIATED"],
    },
    "penalty_points": {"type": "int"},
    "finding_note": {"type": "string", "max_len": 2000},
}


def _accountability_base(cycle):
    profile = scoring.profile_for_cycle(cycle)
    if profile is None:
        return None
    return calc.accountability_base_points(profile)


@route(
    "/complaints/<complaint_id>/resolve",
    "POST",
    ["RatingAnalyst"],
    path_params=(("complaint_id", "Complaint"),),
    body=RESOLVE_BODY,
)
def resolve(ctx):
    complaint = ctx.path["complaint_id"]
    finding = ctx.body["finding"]
    points = ctx.body["penalty_points"]
    # 8 - state
    if complaint["status"] != "INVESTIGATING":
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")

    # the investigated score is recomputed before the ceiling is applied
    score = calc.credibility_score(complaint, "investigated", finding)
    tier = calc.severity_tier(score)

    # 28 - penalty range
    if finding == "SUBSTANTIATED":
        if points is None or points < 1 or points > 15:
            raise ApiError("ERR_PENALTY_POINTS_RANGE")
        if points > calc.SEVERITY_CAP[tier]:
            raise ApiError("ERR_PENALTY_POINTS_RANGE")
    else:
        if points is not None and points != 0:
            raise ApiError("ERR_PENALTY_POINTS_RANGE")

    now = store.now()
    complaint["credibility_score"] = score
    complaint["credibility_variant"] = "INVESTIGATED"
    complaint["severity_tier"] = tier
    complaint["finding_note"] = ctx.body["finding_note"]
    complaint["resolved_at"] = now

    if finding == "UNSUBSTANTIATED":
        complaint["status"] = "UNSUBSTANTIATED"
        touch(complaint)
        return ok(complaint)

    # hop 1 - the finding itself, plus the choice of victim
    complaint["status"] = "SUBSTANTIATED"
    complaint["penalty_points_applied"] = points
    target = calc.penalty_target_cycle(complaint["organization_id"])
    complaint["penalized_rating_cycle_id"] = target["id"] if target else None
    touch(complaint)

    organization = lookup("Organization", complaint["organization_id"])
    if organization is not None:
        cascade.refresh_substantiated_count(organization)
        touch(organization)

    if target is None:
        return ok(complaint)

    # hop 2 - the ACCOUNTABILITY row absorbs the penalty and goes stale
    row = scoring.dimension_row(target, "ACCOUNTABILITY")
    if row is not None:
        row["penalty_points"] = int(row["penalty_points"] or 0) + points
        base = _accountability_base(target)
        if base is not None:
            row["raw_points"] = max(0, base - int(row["penalty_points"]))
        else:
            row["raw_points"] = max(0, int(row["raw_points"] or 0) - points)
        row["normalized_score"] = calc.normalized(
            row["raw_points"], int(row["max_points"])
        )
        if row["status"] in ("COMPUTED", "OVERRIDDEN"):
            row["status"] = "STALE"
        touch(row)

    # hop 3 - the cycle recomputes its provisional family only
    target["accountability_penalty_points"] = scoring.accountability_penalty_total(
        target
    )
    scoring.refresh_row_weights(target)
    scoring.finalize_scores(target, True, False)
    departed = target["status"] in REVIEW_TRACK
    if departed:
        target["status"] = "SCORED"
        cascade.clear_review_track(target)
    touch(target)

    # hop 4 - the review track is tidied up
    if departed:
        cascade.cascade_dismiss_appeals(target, RESCORE_NOTE)
        cascade.cascade_reject_corrections(target, RESCORE_NOTE)
    return ok(complaint)


REVERSAL_BODY = {
    "reversal_reason": {
        "type": "string",
        "required": True,
        "min_len": 1,
        "max_len": 500,
        "non_blank": True,
    },
}


@route(
    "/complaints/<complaint_id>/reverse-finding",
    "POST",
    ["MethodologyAdmin"],
    path_params=(("complaint_id", "Complaint"),),
    body=REVERSAL_BODY,
)
def reverse_finding(ctx):
    complaint = ctx.path["complaint_id"]
    # 8 - the complaint itself, then the penalised cycle
    if complaint["status"] != "SUBSTANTIATED":
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")
    cycle = lookup("RatingCycle", complaint["penalized_rating_cycle_id"])
    if cycle is not None and cycle["status"] in ("PUBLISHED", "WITHDRAWN"):
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    reversed_points = int(complaint["penalty_points_applied"] or 0)
    complaint["status"] = "INVESTIGATING"
    complaint["reversal_reason"] = ctx.body["reversal_reason"]
    complaint["penalty_points_applied"] = 0
    complaint["resolved_at"] = None
    complaint["penalized_rating_cycle_id"] = None
    touch(complaint)

    organization = lookup("Organization", complaint["organization_id"])
    if organization is not None:
        cascade.refresh_substantiated_count(organization)
        touch(organization)

    if cycle is None:
        return ok(complaint)

    row = scoring.dimension_row(cycle, "ACCOUNTABILITY")
    if row is not None:
        row["penalty_points"] = max(0, int(row["penalty_points"] or 0) - reversed_points)
        base = _accountability_base(cycle)
        if base is not None:
            row["raw_points"] = max(0, base - int(row["penalty_points"]))
        else:
            row["raw_points"] = int(row["raw_points"] or 0) + reversed_points
        row["normalized_score"] = calc.normalized(
            row["raw_points"], int(row["max_points"])
        )
        if row["status"] == "STALE":
            row["status"] = "COMPUTED"
        touch(row)

    cycle["accountability_penalty_points"] = scoring.accountability_penalty_total(cycle)
    scoring.refresh_row_weights(cycle)
    scoring.finalize_scores(cycle, True, False)
    touch(cycle)
    return ok(complaint)
