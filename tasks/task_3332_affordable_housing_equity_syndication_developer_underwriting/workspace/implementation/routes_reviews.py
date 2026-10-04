"""Portfolio reviews: opening, scoring and resolving compliance findings."""

from flask import Blueprint, request

import calc
import clock
import errors
import response
import state
import store
import validate

bp = Blueprint("reviews", __name__)

READ_REVIEWS = ("AssetManager", "ComplianceOfficer", "Investor", "PlatformAdmin")
WRITE_REVIEWS = ("AssetManager", "ComplianceOfficer")

OUTCOMES = ("COMPLIANT", "WATCH", "ESCALATED", "NONCOMPLIANT", "CURED")
OFFICER_ONLY = ("ESCALATED", "NONCOMPLIANT")
RESERVE_TARGET_CENTS = 50000000
BAND_COMPLIANT = 70
BAND_ESCALATED = 85


@bp.get("/projects/<project_id>/reviews")
def list_reviews(project_id):
    role, user_id = validate.authenticate(request)
    validate.require_role(role, READ_REVIEWS)
    project = validate.get_project(project_id)
    if role == "Investor" and not validate.investor_holds_fund(user_id, project["fund_id"]):
        errors.fail(errors.ERR_FORBIDDEN_SCOPE,
                    "An Investor may read only projects of funds it subscribes to.")
    index = request.args.get("review_period_index")
    filters = {"project_id": project_id, "status": request.args.get("status")}
    rows = store.listing(store.reviews, filters)
    if index is not None:
        try:
            rows = [r for r in rows if int(r["review_period_index"]) == int(index)]
        except (TypeError, ValueError):
            rows = []
    limit, offset = response.pagination_args(request)
    window, meta = response.paginate(rows, limit, offset)
    return response.array([store.public(r) for r in window], 200, meta)


@bp.post("/projects/<project_id>/reviews")
def create_review(project_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, WRITE_REVIEWS)
    payload = validate.body(request)
    index = validate.non_negative(validate.as_int(payload, "review_period_index"),
                                  "review_period_index")
    period_end = validate.as_datetime(payload, "review_period_end")
    occupancy = validate.as_number(payload, "occupancy_pct")
    dscr_observed = validate.as_number(payload, "dscr_observed")
    reserve = validate.non_negative(validate.as_int(payload, "reserve_balance_cents"),
                                    "reserve_balance_cents")
    validate.non_negative(occupancy, "occupancy_pct")
    validate.non_negative(dscr_observed, "dscr_observed")

    project = validate.get_project(project_id)
    for existing in state.reviews_of_project(project_id):
        if int(existing["review_period_index"]) == index:
            errors.fail(errors.ERR_DUPLICATE_REVIEW_PERIOD,
                        "A review already exists for this period index.")

    review = store.create(store.reviews, {
        "project_id": project["id"],
        "review_period_index": index,
        "review_period_end": period_end,
        "occupancy_pct": occupancy,
        "dscr_observed": dscr_observed,
        "reserve_balance_cents": reserve,
        "corrected_reserve_balance_cents": None,
        "risk_score": 0,
        "status": "PENDING",
        "escalated_at": None,
    })
    review["risk_score"] = calc.watch_list_risk_score(review, project)
    store.touch(review)
    return response.ok(store.public(review), 201)


@bp.post("/reviews/<review_id>/resolve")
def resolve_review(review_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, WRITE_REVIEWS)
    payload = validate.body(request)
    outcome = payload.get("outcome")
    if outcome is not None:
        validate.in_enum(outcome, OUTCOMES, "outcome")

    review = validate.get_review(review_id)
    project = validate.get_project(review["project_id"])
    fund = validate.get_fund(project["fund_id"])
    status = review["status"]

    if status in ("COMPLIANT", "CURED"):
        errors.fail(errors.ERR_REVIEW_NOT_ESCALATED,
                    "The review has no transition out of its current state.")

    # Re-derive the score: the clock-dependent terms may have moved.
    review["risk_score"] = calc.watch_list_risk_score(review, project)
    score = int(review["risk_score"])

    if outcome is None:
        if status not in ("PENDING", "WATCH"):
            errors.fail(errors.ERR_REVIEW_NOT_ESCALATED,
                        "No implied outcome exists for the review's current state.")
        if score < BAND_COMPLIANT:
            target = "COMPLIANT"
        elif score < BAND_ESCALATED:
            target = "WATCH"
        else:
            target = "ESCALATED"
        if target in OFFICER_ONLY and role != "ComplianceOfficer":
            errors.fail(errors.ERR_FORBIDDEN,
                        "Only a ComplianceOfficer may record an escalation.")
    else:
        if outcome in OFFICER_ONLY and role != "ComplianceOfficer":
            errors.fail(errors.ERR_FORBIDDEN,
                        "Only a ComplianceOfficer may record this outcome.")
        if outcome == "NONCOMPLIANT":
            if status != "ESCALATED":
                errors.fail(errors.ERR_REVIEW_NOT_ESCALATED,
                            "A noncompliance finding requires an escalated review.")
            if clock.now() < clock._parse(review["review_period_end"]):
                errors.fail(errors.ERR_REVIEW_PERIOD_OPEN,
                            "The reviewed period has not closed yet.")
        elif outcome == "CURED":
            if status != "NONCOMPLIANT":
                errors.fail(errors.ERR_REVIEW_NOT_ESCALATED,
                            "Only a noncompliant review may be cured.")
            corrected = validate.as_int(payload, "corrected_reserve_balance_cents")
            validate.non_negative(corrected, "corrected_reserve_balance_cents")
            if corrected < RESERVE_TARGET_CENTS:
                errors.fail(errors.ERR_INVALID_REQUEST,
                            "corrected_reserve_balance_cents must reach the reserve target.")
            review["corrected_reserve_balance_cents"] = corrected
        else:
            if status not in ("PENDING", "WATCH"):
                errors.fail(errors.ERR_REVIEW_NOT_ESCALATED,
                            "The review cannot move to that outcome from its current state.")
            if outcome == "ESCALATED" and score < BAND_ESCALATED:
                errors.fail(errors.ERR_REVIEW_NOT_ESCALATED,
                            "An escalation requires a risk score of 85 or above.")
        target = outcome

    review["status"] = target
    if target == "ESCALATED":
        review["escalated_at"] = clock.now_str()
    store.touch(review)

    if target == "ESCALATED":
        state.distress_project(project["id"])
    # PRD 3.7: "A `DISTRESSED` project returns to `COMPLIANCE_PERIOD` once none
    # of its reviews remains `ESCALATED`".  That condition is reached both by a
    # cure and by an escalated review taking the noncompliance finding, so the
    # heal is evaluated after every resolve (it is a no-op while any review is
    # still ESCALATED).
    state.heal_project(project["id"])
    state.recompute_project(project["id"])
    state.recompute_fund(fund["id"])
    state.recompute_developer(project["developer_id"])
    return response.ok(store.public(review), 200)
