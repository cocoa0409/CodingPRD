"""Engineering reviews of critical lifts."""
from flask import Blueprint

import calc
import derive
from core import fail, new_record, ordered, respond_list, respond_object, store, touch
from guards import Body, auth, body, fk, must_exist, pagination, paginate, q_enum, q_str

bp = Blueprint("reviews", __name__)

REVIEW_STATUSES = ["UNDER_REVIEW", "CHANGES_REQUESTED", "STAMPED", "REJECTED", "SUPERSEDED"]
DECISION_ACTIONS = ["REQUEST_CHANGES", "STAMP", "REJECT"]


@bp.post("/engineering-reviews")
def create_review():
    auth(["Engineer"])
    b = Body(body())
    lift_plan_id = b.string("lift_plan_id")
    author_personnel_id = b.string("author_personnel_id")
    analysis_notes = b.string("analysis_notes", allow_empty=True)
    fk("lift_plans", lift_plan_id)
    author = fk("personnel", author_personnel_id)
    if author["role_type"] != "ENGINEER":
        fail("ERR_PERSONNEL_ROLE_MISMATCH", "author_personnel_id must name an ENGINEER.")
    rec = new_record({
        "lift_plan_id": lift_plan_id,
        "author_personnel_id": author_personnel_id,
        "stamped_by_personnel_id": None,
        "analysis_notes": analysis_notes,
        "revision_round": 1,
        "change_request_note": None,
        "decision_note": None,
        "final_bearing_pressure_psf": 0,
        "final_mat_count": 0,
        "status": "UNDER_REVIEW",
    })
    store.engineering_reviews[rec["id"]] = rec
    return respond_object(derive.review_json(rec), 201)


@bp.get("/engineering-reviews/<rid>")
def read_review(rid):
    auth(["Dispatcher", "LiftDirector", "Engineer", "SafetyManager"])
    rec = must_exist("engineering_reviews", rid)
    return respond_object(derive.review_json(rec))


@bp.get("/engineering-reviews")
def list_reviews():
    auth(["Dispatcher", "LiftDirector", "Engineer", "SafetyManager"])
    limit, offset = pagination()
    lift_plan_id = q_str("lift_plan_id")
    author_personnel_id = q_str("author_personnel_id")
    stamped_by_personnel_id = q_str("stamped_by_personnel_id")
    status = q_enum("status", REVIEW_STATUSES)
    rows = ordered(store.engineering_reviews)
    if lift_plan_id:
        rows = [r for r in rows if r["lift_plan_id"] == lift_plan_id]
    if author_personnel_id:
        rows = [r for r in rows if r["author_personnel_id"] == author_personnel_id]
    if stamped_by_personnel_id:
        rows = [r for r in rows if r["stamped_by_personnel_id"] == stamped_by_personnel_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    items, limit, offset, total = paginate(rows, limit, offset, derive.review_json)
    return respond_list(items, limit, offset, total)


@bp.post("/engineering-reviews/<rid>/decision")
def review_decision(rid):
    user_id, _role = auth(["Engineer"])
    review = must_exist("engineering_reviews", rid)
    b = Body(body())
    action = b.enum("action", DECISION_ACTIONS)
    note = b.string("note", required=False, default=None, allow_empty=True)

    if user_id == review["author_personnel_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "An engineer may not decide on a review they authored.")

    if review["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_REVIEW_STATE", "Only an UNDER_REVIEW analysis may be decided upon.")

    plan = store.lift_plans.get(review["lift_plan_id"])
    if action == "STAMP":
        if plan is None or plan["plan_status"] != "PENDING_ENGINEERING":
            fail("ERR_PLAN_NOT_PENDING_ENGINEERING",
                 "A review may only be stamped while its plan awaits engineering.")

    if action == "REQUEST_CHANGES":
        review["status"] = "CHANGES_REQUESTED"
        review["change_request_note"] = note
    elif action == "REJECT":
        review["status"] = "REJECTED"
        review["decision_note"] = note
    else:
        review["status"] = "STAMPED"
        review["stamped_by_personnel_id"] = user_id
        review["decision_note"] = note
        crane = store.cranes.get(plan["crane_id"]) if plan["crane_id"] else None
        site = store.sites.get(plan["site_id"])
        if crane is not None and site is not None:
            figures = calc.ground_bearing(plan["total_load_lb"], crane, site, "FINAL_ENGINEERED")
            review["final_bearing_pressure_psf"] = figures["bearing_pressure_psf"]
            review["final_mat_count"] = figures["mat_count"]
            plan.update(figures)
        plan["plan_status"] = "APPROVED"
        touch(plan)

    touch(review)
    return respond_object(derive.review_json(review))


@bp.post("/engineering-reviews/<rid>/resubmit")
def review_resubmit(rid):
    user_id, _role = auth(["Engineer"])
    review = must_exist("engineering_reviews", rid)
    b = Body(body())
    analysis_notes = b.string("analysis_notes", allow_empty=True)

    if user_id != review["author_personnel_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "Only the author may resubmit an analysis.")

    if review["status"] != "CHANGES_REQUESTED":
        fail("ERR_INVALID_REVIEW_STATE",
             "Only an analysis with changes requested may be resubmitted.")

    if review["revision_round"] >= 3:
        review["status"] = "REJECTED"
        review["decision_note"] = "revision limit exceeded"
        touch(review)
        fail("ERR_REVISION_LIMIT_EXCEEDED",
             "The analysis has exhausted its three revision rounds.")

    review["status"] = "UNDER_REVIEW"
    review["revision_round"] += 1
    review["analysis_notes"] = analysis_notes
    touch(review)
    return respond_object(derive.review_json(review))
