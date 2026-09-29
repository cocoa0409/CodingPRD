"""Governance profiles, the eight standards, waivers and revocations."""

from flask import request

from db import STANDARD_CODES, lookup, new_row, rows, store, touch
from errors import ApiError
from middleware import route
from response import ok
from routes import listing
from services import calc, scoring

READ_ROLES = [
    "MethodologyAdmin",
    "RatingAnalyst",
    "PublishingReviewer",
    "AppealPanelist",
    "OrganizationRep",
]

PROFILE_BODY = {
    "rating_cycle_id": {"type": "string", "required": True, "fk": "RatingCycle"},
    "board_member_count": {"type": "int", "required": True, "min": 0, "max": 100},
    "independent_board_member_count": {"type": "int", "required": True, "min": 0},
    "conflict_of_interest_policy_on_file": {"type": "bool", "required": True},
    "coi_policy_reviewed_at": {"type": "datetime"},
    "board_meetings_last_year": {"type": "int", "required": True, "min": 0, "max": 52},
    "audit_committee_exists": {"type": "bool", "required": True},
    "whistleblower_policy": {"type": "bool", "required": True},
    "ceo_compensation_reviewed": {"type": "bool", "required": True},
    "impact_report_on_file": {"type": "bool", "required": True},
    "outcome_measures_count": {"type": "int", "required": True, "min": 0, "max": 50},
    "third_party_evaluation_on_file": {"type": "bool", "required": True},
}


@route("/governance-profiles", "POST", ["RatingAnalyst"], body=PROFILE_BODY)
def create_profile(ctx):
    if ctx.body["independent_board_member_count"] > ctx.body["board_member_count"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "independent_board_member_count may not exceed board_member_count.",
        )
    cycle = ctx.fk["rating_cycle_id"]
    # check 22 - at most one profile per cycle
    for existing in rows("GovernanceProfile"):
        if existing["rating_cycle_id"] == cycle["id"]:
            raise ApiError("ERR_DUPLICATE_GOVERNANCE_PROFILE")
    payload = {
        field: ctx.body[field]
        for field in PROFILE_BODY
        if field != "rating_cycle_id"
    }
    record = new_row(
        "GovernanceProfile",
        dict(
            rating_cycle_id=cycle["id"],
            independence_ratio=None,
            evaluation_status="PENDING",
            evaluated_at=None,
            standards_met_count=0,
            standards_not_met_count=0,
            standards_waived_count=0,
            standards_not_applicable_count=0,
            **payload
        ),
    )
    return ok(record, 201)


@route("/governance-profiles", "GET", READ_ROLES, paginated=True)
def list_profiles(ctx):
    items = rows("GovernanceProfile")
    cycle_id = request.args.get("rating_cycle_id")
    status = request.args.get("evaluation_status")
    if cycle_id is not None:
        items = [p for p in items if p["rating_cycle_id"] == cycle_id]
    if status is not None:
        items = [p for p in items if p["evaluation_status"] == status]
    return listing.respond(ctx, listing.by_created_at(items))


@route(
    "/governance-profiles/<governance_profile_id>",
    "GET",
    READ_ROLES,
    path_params=[("governance_profile_id", "GovernanceProfile")],
)
def get_profile(ctx):
    return ok(ctx.path["governance_profile_id"])


@route(
    "/governance-profiles/<governance_profile_id>/evaluate",
    "POST",
    ["RatingAnalyst"],
    path_params=[("governance_profile_id", "GovernanceProfile")],
)
def evaluate_profile(ctx):
    profile = ctx.path["governance_profile_id"]
    if profile["evaluation_status"] != "PENDING":
        raise ApiError("ERR_GOVERNANCE_STATE_INVALID")
    cycle = lookup("RatingCycle", profile["rating_cycle_id"])
    if cycle is None or cycle["status"] != "DATA_COLLECTION":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    organization = lookup("Organization", cycle["organization_id"])

    ratio, results = calc.standards_evaluation(profile, organization["org_type"])
    profile["independence_ratio"] = ratio
    for code, result, observed, required in results:
        new_row(
            "StandardEvaluation",
            dict(
                governance_profile_id=profile["id"],
                standard_code=code,
                result=result,
                observed_value=observed,
                required_value=required,
                waiver_reason=None,
                waived_by_user_id=None,
                evaluated_at=store.now(),
            ),
        )
    scoring.refresh_profile_counts(profile)
    profile["evaluation_status"] = "EVALUATED"
    profile["evaluated_at"] = store.now()
    touch(profile)
    cycle["failed_standard_count"] = profile["standards_not_met_count"]
    touch(cycle)
    return ok(profile)


@route(
    "/governance-profiles/<id>/standard-evaluations",
    "GET",
    READ_ROLES,
    path_params=[("id", "GovernanceProfile")],
    paginated=True,
)
def list_standard_evaluations(ctx):
    profile = ctx.path["id"]
    items = [
        s
        for s in rows("StandardEvaluation")
        if s["governance_profile_id"] == profile["id"]
    ]
    code = request.args.get("standard_code")
    result = request.args.get("result")
    if code is not None:
        items = [s for s in items if s["standard_code"] == code]
    if result is not None:
        items = [s for s in items if s["result"] == result]
    items.sort(key=lambda s: (s["standard_code"], s["_seq"]))
    return listing.respond(ctx, items)


@route(
    "/standard-evaluations/<standard_evaluation_id>",
    "GET",
    READ_ROLES,
    path_params=[("standard_evaluation_id", "StandardEvaluation")],
)
def get_standard_evaluation(ctx):
    return ok(ctx.path["standard_evaluation_id"])


WAIVE_BODY = {"waiver_reason": {"type": "string", "required": True, "min_len": 1}}
REVOKE_BODY = {"revocation_note": {"type": "string"}}


def _standard_context(row):
    profile = lookup("GovernanceProfile", row["governance_profile_id"])
    cycle = (
        lookup("RatingCycle", profile["rating_cycle_id"]) if profile is not None else None
    )
    return profile, cycle


@route(
    "/standard-evaluations/<standard_evaluation_id>/waive",
    "POST",
    ["MethodologyAdmin"],
    path_params=[("standard_evaluation_id", "StandardEvaluation")],
    body=WAIVE_BODY,
)
def waive_standard(ctx):
    row = ctx.path["standard_evaluation_id"]
    if row["result"] != "NOT_MET":
        raise ApiError("ERR_STANDARD_STATE_INVALID")
    profile, cycle = _standard_context(row)
    if cycle is None or cycle["status"] in ("PUBLISHED", "WITHDRAWN"):
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    row["result"] = "WAIVED"
    row["waiver_reason"] = ctx.body["waiver_reason"]
    row["waived_by_user_id"] = ctx.user_id
    touch(row)

    scoring.refresh_profile_counts(profile)
    touch(profile)
    cycle["failed_standard_count"] = profile["standards_not_met_count"]
    touch(cycle)
    if scoring.recompute_accountability_row(cycle):
        scoring.finalize_scores(cycle, True, True)
    return ok(row)


@route(
    "/standard-evaluations/<standard_evaluation_id>/revoke-waiver",
    "POST",
    ["MethodologyAdmin"],
    path_params=[("standard_evaluation_id", "StandardEvaluation")],
    body=REVOKE_BODY,
)
def revoke_waiver(ctx):
    row = ctx.path["standard_evaluation_id"]
    if row["result"] != "WAIVED":
        raise ApiError("ERR_STANDARD_STATE_INVALID")
    profile, cycle = _standard_context(row)
    if cycle is None or cycle["status"] in ("PUBLISHED", "WITHDRAWN"):
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    row["result"] = "NOT_MET"
    row["waiver_reason"] = None
    row["waived_by_user_id"] = None
    touch(row)

    scoring.refresh_profile_counts(profile)
    touch(profile)
    cycle["failed_standard_count"] = profile["standards_not_met_count"]
    touch(cycle)
    if scoring.recompute_accountability_row(cycle):
        scoring.finalize_scores(cycle, True, True)
    return ok(row)
