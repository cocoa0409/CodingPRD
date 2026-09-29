"""Section 3.2 - trials, stakeholder feedback and the endorsement score."""

from flask import Blueprint, request

import auth
import calc
import envelope
import services
import shape
import store
from errors import ApiError

bp = Blueprint("trials", __name__)


def _window_conflict(product_id, member_id, start_date, end_date):
    """A conflict exists when the new start falls strictly before the existing
    end advanced by the cooldown buffer, and the existing start falls strictly
    before the new end. Every existing status counts, terminal ones included."""
    for trial in store.trials.values():
        if trial["product_id"] != product_id or trial["member_id"] != member_id:
            continue
        buffered_end = calc.add_days(trial["end_date"], calc.TRIAL_COOLDOWN_DAYS)
        if start_date < buffered_end and trial["start_date"] < end_date:
            return True
    return False


@bp.post("/erm/products/<product_id>/trials")
def create_trial(product_id):
    auth.require_roles(auth.ROLE_MEMBER_LIBRARIAN)
    product = auth.get_product(product_id)
    data = shape.body()
    member = None
    if shape.present(data, "member_id"):
        member = auth.get_member(data["member_id"])
        auth.require_member_scope(data["member_id"])
    member_id = shape.req_string(data, "member_id")
    start_date = shape.req_date(data, "start_date")
    end_date = shape.req_date(data, "end_date")
    criteria = shape.req_criteria(data)

    if member["standing"] != "IN_GOOD_STANDING":
        raise ApiError("ERR_MEMBER_OVER_COMMITTED")
    if _window_conflict(product["id"], member_id, start_date, end_date):
        raise ApiError("ERR_TRIAL_WINDOW_CONFLICT")

    row = store.new_row({
        "product_id": product["id"],
        "member_id": member_id,
        "start_date": start_date,
        "end_date": end_date,
        "criteria": criteria,
        "status": "DRAFT",
        "provisional_score": None,
        "final_score": None,
        "feedback_count": 0,
        "distinct_stakeholder_group_count": 0,
        "quorum_penalty_applied": False,
    })
    store.trials[row["id"]] = row
    return envelope.object_response(store.serialize(row), 201)


@bp.get("/erm/trials/<trial_id>")
def read_trial(trial_id):
    auth.require_roles(*auth.ALL_ROLES)
    row = auth.get_trial(trial_id)
    return envelope.object_response(store.serialize(row))


@bp.get("/erm/trials")
def list_trials():
    auth.require_roles(
        auth.ROLE_CONSORTIUM_ADMIN, auth.ROLE_MEMBER_LIBRARIAN, auth.ROLE_LICENSE_NEGOTIATOR
    )
    rows = list(store.trials.values())
    for field in ("product_id", "member_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return envelope.paged(rows)


@bp.post("/erm/trials/<trial_id>/open")
def open_trial(trial_id):
    auth.require_roles(auth.ROLE_MEMBER_LIBRARIAN)
    trial = auth.get_trial(trial_id)
    auth.require_member_scope(trial["member_id"])
    if trial["status"] != "DRAFT":
        raise ApiError("ERR_TRIAL_INVALID_STATE")
    member = store.members[trial["member_id"]]
    if member["standing"] != "IN_GOOD_STANDING":
        raise ApiError("ERR_MEMBER_OVER_COMMITTED")
    if not store.clock_date() < trial["end_date"]:
        raise ApiError(
            "ERR_TRIAL_INVALID_STATE",
            "The trial window has already closed; the clock date is not before end_date.",
        )
    store.mutate(trial, {"status": "ACTIVE"})
    return envelope.object_response(store.serialize(trial))


@bp.post("/erm/trials/<trial_id>/close")
def close_trial(trial_id):
    auth.require_roles(auth.ROLE_MEMBER_LIBRARIAN)
    trial = auth.get_trial(trial_id)
    auth.require_member_scope(trial["member_id"])
    if trial["status"] != "ACTIVE":
        raise ApiError("ERR_TRIAL_INVALID_STATE")
    score, _penalty = calc.trial_endorsement_score(trial, "provisional_at_close")
    count, groups = services.trial_counters(trial["id"])
    store.mutate(trial, {
        "provisional_score": float(score),
        "status": "CLOSED",
        "feedback_count": count,
        "distinct_stakeholder_group_count": groups,
    })
    return envelope.object_response(store.serialize(trial))


@bp.post("/erm/trials/<trial_id>/evaluate")
def evaluate_trial(trial_id):
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    trial = auth.get_trial(trial_id)
    if trial["status"] != "CLOSED":
        raise ApiError("ERR_TRIAL_INVALID_STATE")
    if trial["feedback_count"] < calc.MIN_FEEDBACK_ROWS:
        raise ApiError("ERR_INSUFFICIENT_FEEDBACK")
    score, penalty_applied = calc.trial_endorsement_score(trial, "final_at_evaluation")
    status = "ENDORSED" if score >= calc.ENDORSEMENT_THRESHOLD else "DECLINED"
    store.mutate(trial, {
        "final_score": float(score),
        "quorum_penalty_applied": penalty_applied,
        "status": status,
    })
    return envelope.object_response(store.serialize(trial))


@bp.post("/erm/trials/<trial_id>/feedback")
def create_feedback(trial_id):
    auth.require_roles(auth.ROLE_MEMBER_LIBRARIAN)
    trial = auth.get_trial(trial_id)
    auth.require_member_scope(trial["member_id"])
    data = shape.body()
    stakeholder_group = shape.req_enum(data, "stakeholder_group", shape.STAKEHOLDER_GROUPS)
    criterion_code = shape.req_string(data, "criterion_code")
    score = shape.req_int(data, "score", minimum=0, maximum=100)
    comment = shape.opt_string(data, "comment", None)

    if trial["status"] not in ("ACTIVE", "CLOSED"):
        raise ApiError("ERR_TRIAL_INVALID_STATE")
    if criterion_code not in [c["code"] for c in trial["criteria"]]:
        raise ApiError("ERR_UNKNOWN_CRITERION")

    row = store.new_row({
        "trial_id": trial["id"],
        "stakeholder_group": stakeholder_group,
        "criterion_code": criterion_code,
        "score": score,
        "submitted_during_status": trial["status"],
        "submitted_by_user_id": auth.user_id(),
        "comment": comment,
    }, versioned=False)
    store.feedback_entries[row["id"]] = row

    count, groups = services.trial_counters(trial["id"])
    store.mutate(trial, {
        "feedback_count": count,
        "distinct_stakeholder_group_count": groups,
    })
    return envelope.object_response(store.serialize(row), 201)


@bp.get("/erm/trials/<trial_id>/feedback")
def list_feedback(trial_id):
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN, auth.ROLE_MEMBER_LIBRARIAN)
    trial = auth.get_trial(trial_id)
    rows = [r for r in store.feedback_entries.values() if r["trial_id"] == trial["id"]]
    return envelope.paged(rows)
