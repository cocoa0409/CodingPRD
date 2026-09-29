"""Rating cycles: creation with the pinned methodology, scoring, review, publication."""

from flask import request

from db import (
    CORRECTION_WINDOW_DAYS,
    DIMENSIONS,
    d,
    lookup,
    new_row,
    plus_days,
    q2,
    rows,
    store,
    touch,
)
from errors import ApiError
from middleware import route
from response import ok
from routes import listing
from services import calc, cascade, scoring

ALL_ROLES = [
    "MethodologyAdmin",
    "RatingAnalyst",
    "PublishingReviewer",
    "AppealPanelist",
    "OrganizationRep",
    "PublicUser",
]
STAFF_ROLES = [
    "MethodologyAdmin",
    "RatingAnalyst",
    "PublishingReviewer",
    "AppealPanelist",
    "OrganizationRep",
]

CYCLE_STATUSES = [
    "DATA_COLLECTION",
    "SCORED",
    "ORG_REVIEW",
    "CORRECTION_REQUESTED",
    "APPEAL_OPEN",
    "APPEAL_RESOLVED",
    "PUBLISHED",
    "WITHDRAWN",
]
NON_TERMINAL = CYCLE_STATUSES[:6]

CYCLE_BODY = {
    "organization_id": {"type": "string", "required": True, "fk": "Organization"},
    "methodology_version_id": {
        "type": "string",
        "required": True,
        "fk": "MethodologyVersion",
    },
    "fiscal_year": {"type": "int", "required": True, "min": 2000, "max": 2100},
    "period_start": {"type": "datetime", "required": True},
    "period_end": {"type": "datetime", "required": True},
    "assigned_analyst_user_id": {
        "type": "string",
        "required": True,
        "non_blank": True,
    },
    "use_transition_grant": {"type": "bool", "default": False},
}


def _live_grant(organization_id, label):
    """The organization's ACTIVE grant for a superseded label, grace still open."""
    best = None
    for grant in rows("TransitionGrant"):
        if grant["organization_id"] != organization_id:
            continue
        if grant["superseded_version_label"] != label:
            continue
        if grant["status"] != "ACTIVE":
            continue
        if grant["grace_until"] < store.now():
            continue
        if best is None or (grant["created_at"], grant["_seq"]) < (
            best["created_at"],
            best["_seq"],
        ):
            best = grant
    return best


@route("/rating-cycles", "POST", ["RatingAnalyst"], body=CYCLE_BODY)
def create_cycle(ctx):
    body = ctx.body
    if body["period_end"] <= body["period_start"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", "period_end must be strictly after period_start."
        )
    organization = ctx.fk["organization_id"]
    methodology = ctx.fk["methodology_version_id"]
    use_grant = bool(body["use_transition_grant"])

    # check 12 - the pinned methodology must be ADOPTED, or RETIRED under a grant
    retired_pin = False
    if methodology["status"] == "ADOPTED":
        pass
    elif methodology["status"] == "RETIRED" and use_grant:
        retired_pin = True
    else:
        raise ApiError("ERR_METHODOLOGY_NOT_ADOPTED")

    # check 13 - transition grace
    grant = None
    if retired_pin:
        grant = _live_grant(organization["id"], methodology["version_label"])
        if grant is None:
            raise ApiError("ERR_TRANSITION_GRACE_UNAVAILABLE")

    # check 15 - effectivity, waived for a grant-admitted retired pin
    if not retired_pin:
        now = store.now()
        effective_from = methodology["effective_from"]
        effective_until = methodology["effective_until"]
        if effective_from is None or effective_from > now:
            raise ApiError("ERR_METHODOLOGY_NOT_EFFECTIVE")
        if effective_until is not None and now > effective_until:
            raise ApiError("ERR_METHODOLOGY_NOT_EFFECTIVE")

    # check 18 - half-open period overlap against non-WITHDRAWN cycles
    for other in rows("RatingCycle"):
        if other["organization_id"] != organization["id"]:
            continue
        if other["status"] == "WITHDRAWN":
            continue
        if body["period_start"] < other["period_end"] and (
            other["period_start"] < body["period_end"]
        ):
            raise ApiError("ERR_CYCLE_PERIOD_OVERLAP")

    record = new_row(
        "RatingCycle",
        dict(
            organization_id=organization["id"],
            methodology_version_id=methodology["id"],
            fiscal_year=body["fiscal_year"],
            period_start=body["period_start"],
            period_end=body["period_end"],
            status="DATA_COLLECTION",
            assigned_analyst_user_id=body["assigned_analyst_user_id"],
            publishing_reviewer_user_id=None,
            correction_round=0,
            review_opened_at=None,
            correction_deadline_at=None,
            appeal_deadline_at=None,
            published_at=None,
            program_expense_ratio=None,
            fundraising_efficiency=None,
            months_of_reserve=None,
            failed_standard_count=0,
            accountability_penalty_points=0,
            data_completeness_pct=None,
            weighted_sum_provisional=None,
            provisional_composite_score=None,
            provisional_grade=None,
            weighted_sum_final=None,
            final_composite_score=None,
            grade=None,
            standards_penalty_points=None,
            methodology_pin_locked=True,
            withdrawal_reason=None,
        ),
    )
    if grant is not None:
        grant["status"] = "CONSUMED"
        touch(grant)
        # §3.3: transition_grace_until mirrors the grace_until of the
        # organization's ACTIVE grant and is null when there is none, so
        # spending the last live licence clears the organization's deadline.
        cascade.refresh_active_grace(organization)
    return ok(record, 201)


@route("/rating-cycles", "GET", ALL_ROLES, paginated=True)
def list_cycles(ctx):
    args = request.args
    items = rows("RatingCycle")
    organization_id = args.get("organization_id")
    if organization_id:
        items = [r for r in items if r["organization_id"] == organization_id]
    methodology_version_id = args.get("methodology_version_id")
    if methodology_version_id:
        items = [
            r for r in items if r["methodology_version_id"] == methodology_version_id
        ]
    status = args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    fiscal_year = listing.int_arg(args, "fiscal_year")
    if fiscal_year is not None:
        items = [r for r in items if r["fiscal_year"] == fiscal_year]
    return listing.respond(ctx, listing.by_created_at(items))


@route(
    "/rating-cycles/<rating_cycle_id>",
    "GET",
    ALL_ROLES,
    path_params=(("rating_cycle_id", "RatingCycle"),),
)
def get_cycle(ctx):
    return ok(ctx.path["rating_cycle_id"])


@route(
    "/rating-cycles/<rating_cycle_id>/score",
    "POST",
    ["RatingAnalyst"],
    path_params=(("rating_cycle_id", "RatingCycle"),),
)
def score(ctx):
    cycle = ctx.path["rating_cycle_id"]
    # 8 - state
    if cycle["status"] != "DATA_COLLECTION":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    # 11 - assigned analyst
    if ctx.user_id != cycle["assigned_analyst_user_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_ANALYST")
    # 12 - the cycle's governance profile must be EVALUATED
    profile = scoring.profile_for_cycle(cycle)
    if profile is None or profile["evaluation_status"] != "EVALUATED":
        raise ApiError("ERR_GOVERNANCE_NOT_EVALUATED")
    # 30 - filing sufficiency for the cycle's own fiscal year
    if not calc.has_validated_filing(cycle["organization_id"], cycle["fiscal_year"]):
        raise ApiError("ERR_NO_VALIDATED_FILING")

    scoring.score_cycle(cycle)
    cycle["status"] = "SCORED"
    touch(cycle)
    return ok(cycle)


@route(
    "/rating-cycles/<rating_cycle_id>/open-org-review",
    "POST",
    ["RatingAnalyst"],
    path_params=(("rating_cycle_id", "RatingCycle"),),
)
def open_org_review(ctx):
    cycle = ctx.path["rating_cycle_id"]
    if cycle["status"] != "SCORED":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    if ctx.user_id != cycle["assigned_analyst_user_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_ANALYST")
    # no dimension row may be STALE - an org never sees figures known to be stale
    if scoring.has_stale_row(cycle):
        raise ApiError(
            "ERR_CYCLE_STATE_INVALID",
            "A dimension score of this cycle is STALE.",
        )
    now = store.now()
    cycle["review_opened_at"] = now
    cycle["correction_deadline_at"] = plus_days(now, CORRECTION_WINDOW_DAYS)
    cycle["status"] = "ORG_REVIEW"
    touch(cycle)
    return ok(cycle)


PUBLISH_BODY = {
    "publishing_reviewer_note": {"type": "string", "max_len": 2000},
}


@route(
    "/rating-cycles/<rating_cycle_id>/publish",
    "POST",
    ["PublishingReviewer"],
    path_params=(("rating_cycle_id", "RatingCycle"),),
    body=PUBLISH_BODY,
)
def publish_cycle(ctx):
    cycle = ctx.path["rating_cycle_id"]
    # 8 - only ORG_REVIEW or APPEAL_RESOLVED publish
    if cycle["status"] not in ("ORG_REVIEW", "APPEAL_RESOLVED"):
        raise ApiError("ERR_CYCLE_NOT_PUBLISHABLE")
    # 10 - segregation of duties
    if ctx.user_id == cycle["assigned_analyst_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # 31 - completeness gate
    completeness = cycle["data_completeness_pct"]
    if completeness is None or d(completeness) < d("60.00"):
        raise ApiError("ERR_DATA_COMPLETENESS_TOO_LOW")
    # 32 - publishability
    if cascade.open_corrections(cycle):
        raise ApiError("ERR_CYCLE_NOT_PUBLISHABLE")
    if cascade.open_appeals(cycle):
        raise ApiError("ERR_CYCLE_NOT_PUBLISHABLE")
    if scoring.has_stale_row(cycle):
        raise ApiError("ERR_CYCLE_NOT_PUBLISHABLE")
    deadline = cycle["correction_deadline_at"]
    if deadline is None or store.now() < deadline:
        raise ApiError("ERR_CYCLE_NOT_PUBLISHABLE")

    cascade.publish(cycle, ctx.user_id)
    return ok(cycle)


WITHDRAW_BODY = {
    "withdrawal_reason": {
        "type": "string",
        "required": True,
        "min_len": 1,
        "max_len": 500,
        "non_blank": True,
    },
}


@route(
    "/rating-cycles/<rating_cycle_id>/withdraw",
    "POST",
    ["MethodologyAdmin"],
    path_params=(("rating_cycle_id", "RatingCycle"),),
    body=WITHDRAW_BODY,
)
def withdraw_cycle(ctx):
    cycle = ctx.path["rating_cycle_id"]
    if cycle["status"] not in NON_TERMINAL:
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    cycle["withdrawal_reason"] = ctx.body["withdrawal_reason"]
    cycle["status"] = "WITHDRAWN"
    scoring.mark_rows_stale(cycle)
    cascade.cascade_reject_corrections(cycle, "cycle withdrawn")
    cascade.cascade_dismiss_appeals(cycle, "cycle withdrawn")
    touch(cycle)
    return ok(cycle)


@route(
    "/rating-cycles/<rating_cycle_id>/score-breakdown",
    "GET",
    STAFF_ROLES,
    path_params=(("rating_cycle_id", "RatingCycle"),),
)
def score_breakdown(ctx):
    cycle = ctx.path["rating_cycle_id"]
    methodology = scoring.methodology_for(cycle)
    failed = int(cycle["failed_standard_count"] or 0)

    def band_and_penalty(weighted_sum):
        if weighted_sum is None:
            return None, None
        band = calc.band_for(d(weighted_sum))
        return band, q2(calc.BAND_PENALTY_RATE[band] * d(failed))

    provisional_band, provisional_penalty = band_and_penalty(
        cycle["weighted_sum_provisional"]
    )
    final_band, final_penalty = band_and_penalty(cycle["weighted_sum_final"])

    present = {row["dimension"]: row for row in scoring.dimension_rows(cycle)}
    included = [
        dimension
        for dimension in DIMENSIONS
        if dimension in present
        and d(present[dimension]["data_completeness_pct"]) != 0
    ]

    return ok(
        {
            "rating_cycle_id": cycle["id"],
            "methodology_version_label": (
                methodology["version_label"] if methodology else None
            ),
            "program_expense_ratio": cycle["program_expense_ratio"],
            "fundraising_efficiency": cycle["fundraising_efficiency"],
            "months_of_reserve": cycle["months_of_reserve"],
            "data_completeness_pct": cycle["data_completeness_pct"],
            "failed_standard_count": failed,
            "accountability_penalty_points": int(
                cycle["accountability_penalty_points"] or 0
            ),
            "provisional_band": provisional_band,
            "provisional_penalty": provisional_penalty,
            "weighted_sum_provisional": cycle["weighted_sum_provisional"],
            "provisional_composite_score": cycle["provisional_composite_score"],
            "provisional_grade": cycle["provisional_grade"],
            "final_included_dimensions": included,
            "final_band": final_band,
            "final_penalty": final_penalty,
            "weighted_sum_final": cycle["weighted_sum_final"],
            "final_composite_score": cycle["final_composite_score"],
            "grade": cycle["grade"],
        }
    )


@route(
    "/rating-cycles/<rating_cycle_id>/dimension-scores",
    "GET",
    STAFF_ROLES,
    path_params=(("rating_cycle_id", "RatingCycle"),),
    paginated=True,
)
def list_dimension_scores(ctx):
    cycle = ctx.path["rating_cycle_id"]
    args = request.args
    items = scoring.dimension_rows(cycle)
    dimension = args.get("dimension")
    if dimension:
        items = [r for r in items if r["dimension"] == dimension]
    status = args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    return listing.respond(ctx, items)


OVERRIDE_BODY = {
    "overrides": {
        "type": "object_array",
        "required": True,
        "non_empty": True,
        "fields": {
            "dimension_score_id": {"type": "string", "required": True},
            "raw_points": {"type": "int", "required": True, "min": 0},
        },
    },
    "override_reason": {
        "type": "string",
        "required": True,
        "min_len": 1,
        "max_len": 500,
        "non_blank": True,
    },
    "expected_rating_cycle_version": {"type": "int", "required": True},
}


@route(
    "/rating-cycles/<rating_cycle_id>/dimension-overrides",
    "POST",
    ["RatingAnalyst"],
    path_params=(("rating_cycle_id", "RatingCycle"),),
    body=OVERRIDE_BODY,
)
def dimension_overrides(ctx):
    cycle = ctx.path["rating_cycle_id"]
    # 7 - every dimension_score_id resolves to a row of THIS cycle
    resolved = []
    for entry in ctx.body["overrides"]:
        row = lookup("DimensionScore", entry["dimension_score_id"])
        if row is None or row["rating_cycle_id"] != cycle["id"]:
            raise ApiError("ERR_DIMENSION_SCORE_NOT_FOUND")
        resolved.append((row, entry["raw_points"]))
    # raw_points is bounded by the row's own max_points - all or nothing
    for row, points in resolved:
        if points > int(row["max_points"]):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "raw_points may not exceed the dimension's max_points.",
            )
    # 8 - state
    if cycle["status"] != "SCORED":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    # 9 - stale parent version
    if ctx.body["expected_rating_cycle_version"] != cycle["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # 11 - assigned analyst
    if ctx.user_id != cycle["assigned_analyst_user_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_ANALYST")

    for row, points in resolved:
        row["raw_points"] = points
        row["normalized_score"] = calc.normalized(points, int(row["max_points"]))
        row["override_reason"] = ctx.body["override_reason"]
        row["overridden_by_user_id"] = ctx.user_id
        row["status"] = "OVERRIDDEN"
        touch(row)

    scoring.refresh_row_weights(cycle)
    scoring.finalize_scores(cycle, True, True)
    touch(cycle)
    return ok(cycle)
