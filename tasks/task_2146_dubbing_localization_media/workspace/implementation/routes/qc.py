"""Quality reviews and retake items, including the four-link regression cascade."""
from flask import Blueprint, g, request

import calc
from auth import ALL_ROLES, auth
from domain import (get_assignment, get_mix_job, get_order, get_retake_item, get_review,
                    newest_mix_job, newest_payment, order_adaptation, order_spec,
                    rows_where)
from errors import ApiError
from responses import created, ok, paged
from store import db, new_row, serialize, touch
from validate import body, v_array, v_enum, v_int, v_string

bp = Blueprint("qc", __name__)

DEFECT_CATEGORIES = ("LIPSYNC", "PERFORMANCE", "AUDIO", "TRANSLATION")


@bp.post("/quality-reviews")
@auth("NativeReviewer")
def create_review():
    data = body()
    order = get_order(data.get("order_id"))            # rung 7, declaration order
    job = get_mix_job(data.get("mix_job_id"))
    if job["order_id"] != order["id"]:                 # rung 20
        raise ApiError("ERR_CROSS_ORDER_REFERENCE")

    row = new_row({
        "order_id": order["id"],
        "mix_job_id": job["id"],
        "status": "PENDING",
        "round_number": 1,
        "reviewer_user_id": None,
        "sampled_loop_count": 0,
        "defect_count": 0,
        "pass_rate": None,
        "decision": None,
    })
    db.reviews[row["id"]] = row
    return created(serialize(row))


@bp.get("/quality-reviews/<review_id>")
@auth(*ALL_ROLES)
def read_review(review_id):
    return ok(serialize(get_review(review_id)))


@bp.get("/quality-reviews")
@auth(*ALL_ROLES)
def list_reviews():
    rows = list(db.reviews.values())
    for key in ("order_id", "mix_job_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paged(rows, serialize)


@bp.post("/quality-reviews/<review_id>/start")
@auth("NativeReviewer")
def start_review(review_id):
    review = get_review(review_id)
    data = body()
    sampled = v_int(data, "sampled_loop_count", minimum=0)         # rung 8
    order = db.orders[review["order_id"]]

    if review["status"] not in ("PENDING", "FAILED_RETAKE"):       # rung 11
        raise ApiError("ERR_INVALID_STATE")
    if order["status"] != "QC":
        raise ApiError("ERR_INVALID_STATE")

    adaptation = order_adaptation(order["id"])                     # rung 14
    if (adaptation is not None and adaptation["reviewed_by_user_id"] is not None
            and g.user_id == adaptation["reviewed_by_user_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if sampled < 1:                                                # rung 31
        raise ApiError("ERR_EMPTY_QC_SAMPLE")

    re_entry = review["status"] == "FAILED_RETAKE"
    if re_entry:                                                   # rung 34
        for item in rows_where(db.retake_items, quality_review_id=review["id"]):
            if item["status"] not in ("RECORDED", "WAIVED"):
                raise ApiError("ERR_OPEN_RETAKES")
        review["round_number"] = review["round_number"] + 1

    review["sampled_loop_count"] = sampled
    review["reviewer_user_id"] = g.user_id
    review["status"] = "IN_REVIEW"
    touch(review)
    return ok(serialize(review))


@bp.post("/quality-reviews/<review_id>/decide")
@auth("NativeReviewer")
def decide_review(review_id):
    review = get_review(review_id)                                 # rung 6
    if g.user_id != review["reviewer_user_id"]:                    # rung 5
        raise ApiError("ERR_REVIEWER_MISMATCH")

    data = body()
    raw_defects = data.get("defects")
    if isinstance(raw_defects, list):                              # rung 7
        for entry in raw_defects:
            if isinstance(entry, dict) and isinstance(entry.get("casting_assignment_id"), str):
                get_assignment(entry.get("casting_assignment_id"))

    decision = v_enum(data, "decision", ("PASS", "FAIL"))          # rung 8
    defect_count = v_int(data, "defect_count", minimum=0)
    defects = v_array(data, "defects", required=False, default=[], member_type=dict)
    for entry in defects:
        v_string(entry, "casting_assignment_id")
        v_string(entry, "loop_ref")
        v_enum(entry, "defect_category", DEFECT_CATEGORIES)
        v_int(entry, "estimated_minutes", required=False, default=0, minimum=0)

    order = db.orders[review["order_id"]]
    if review["status"] != "IN_REVIEW":                            # rung 11
        raise ApiError("ERR_INVALID_STATE")

    pass_rate = calc.qc_pass_rate(defect_count, review["sampled_loop_count"])
    spec = order_spec(order)

    if decision == "PASS":                                         # rung 32
        if calc.dec(pass_rate) < calc.dec(spec["qc_pass_threshold"]):
            raise ApiError("ERR_QC_BELOW_THRESHOLD")
    else:
        if len(defects) == 0:
            raise ApiError("ERR_QC_BELOW_THRESHOLD")
        if order["retake_cycles"] >= calc.MAX_RETAKE_CYCLES:       # rung 35
            raise ApiError("ERR_RETAKE_LIMIT_EXCEEDED")

    review["defect_count"] = defect_count
    review["pass_rate"] = pass_rate
    review["decision"] = decision
    review["status"] = "PASSED" if decision == "PASS" else "FAILED_RETAKE"
    touch(review)

    if decision == "FAIL":
        _regression_cascade(review, order, defects)
    return ok(serialize(review))


def _regression_cascade(review, order, defects):
    # link 1: one RetakeItem per defect entry, each OPEN
    for entry in defects:
        item = new_row({
            "quality_review_id": review["id"],
            "casting_assignment_id": entry["casting_assignment_id"],
            "loop_ref": entry["loop_ref"],
            "defect_category": entry["defect_category"],
            "estimated_minutes": entry.get("estimated_minutes", 0) or 0,
            "status": "OPEN",
        })
        db.retake_items[item["id"]] = item

    # link 2: newest MixJob CONFORMED -> STEM_CHECKED
    job = newest_mix_job(order["id"])
    if job is not None and job["status"] == "CONFORMED":
        job["mix_round"] = job["mix_round"] + 1
        job["conformance_index"] = None
        job["status"] = "STEM_CHECKED"
        touch(job)

    # link 3: order QC -> RECORDING, retake_cycles + 1
    if order["status"] == "QC":
        order["status"] = "RECORDING"
        order["retake_cycles"] = order["retake_cycles"] + 1
        touch(order)

    # link 4: every assignment named by an OPEN retake item of this review
    seen = []
    for item in rows_where(db.retake_items, quality_review_id=review["id"], status="OPEN"):
        if item["casting_assignment_id"] in seen:
            continue
        seen.append(item["casting_assignment_id"])
        assignment = db.assignments.get(item["casting_assignment_id"])
        if assignment is None:
            continue
        changed = False
        if assignment["casting_status"] == "RECORDED":
            assignment["casting_status"] = "CONFIRMED"
            changed = True
        if assignment["payment_status"] == "ACCRUED":
            void_cents = 0
            for session in db.sessions.values():
                if (session["casting_assignment_id"] == assignment["id"]
                        and session["status"] == "COMPLETED" and not session["is_retake"]):
                    void_cents += session["session_cost_cents"]
            payment = newest_payment(assignment["id"])
            if payment is not None and payment["status"] == "ACCRUED":
                payment["status"] = "VOIDED"
                touch(payment)
            assignment["payment_status"] = "VOIDED"
            changed = True
            if void_cents:
                order["committed_cents"] = order["committed_cents"] - void_cents
                order["released_cents"] = order["released_cents"] + void_cents
        if changed:
            touch(assignment)


# --------------------------------------------------------------------------
# Retake items
# --------------------------------------------------------------------------
@bp.get("/retake-items/<retake_item_id>")
@auth(*ALL_ROLES)
def read_retake_item(retake_item_id):
    return ok(serialize(get_retake_item(retake_item_id)))


@bp.get("/retake-items")
@auth(*ALL_ROLES)
def list_retake_items():
    rows = list(db.retake_items.values())
    for key in ("quality_review_id", "casting_assignment_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paged(rows, serialize)


@bp.post("/retake-items/<retake_item_id>/waive")
@auth("NativeReviewer")
def waive_retake_item(retake_item_id):
    item = get_retake_item(retake_item_id)
    if item["status"] != "OPEN":                                   # rung 11
        raise ApiError("ERR_INVALID_STATE")
    review = db.reviews.get(item["quality_review_id"])
    if review is None or g.user_id != review["reviewer_user_id"]:
        raise ApiError("ERR_REVIEWER_MISMATCH")
    if item["defect_category"] == "LIPSYNC":                       # rung 33
        raise ApiError("ERR_RETAKE_NOT_WAIVABLE")
    item["status"] = "WAIVED"
    touch(item)
    return ok(serialize(item))
