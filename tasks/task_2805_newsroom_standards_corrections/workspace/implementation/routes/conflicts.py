"""Conflict disclosures, outside work and standards training."""

from flask import Blueprint

import calc
import serialize as ser
from auth import auth, require_ownership
from envelope import respond_object
from errors import ApiError
from helpers import activity_or_404, disclosure_or_404
from store import base_record, db, now, ordered, touch
from validation import (ACTIVITY_TYPES, DECISIONS, DISCLOSURE_TYPES, MODULE_CODES,
                        REVIEW_OUTCOMES, b, dt, e, read_raw_body, resolve_body_ids,
                        s, str_array, validate_body)

bp = Blueprint("conflicts", __name__)

DISCLOSURE_SPEC = {
    "journalist_id": s(required=True),
    "disclosure_type": e(DISCLOSURE_TYPES, required=True),
    "subject_entity_name": s(required=True, min_len=1, max_len=160),
    "description": s(required=True, min_len=1, max_len=4000),
}

DISCLOSURE_REVIEW_SPEC = {
    "review_outcome": e(REVIEW_OUTCOMES, required=True),
    "restricted_beats": str_array(),
}

ACTIVITY_SPEC = {
    "journalist_id": s(required=True),
    "activity_type": e(ACTIVITY_TYPES, required=True),
    "compensated": b(required=True),
    "starts_on": dt(required=True),
    "ends_on": dt(required=True),
    "related_beat": s(required=True, min_len=1, max_len=80),
    "host_organization": s(required=True, min_len=1, max_len=160),
}

ACTIVITY_DECIDE_SPEC = {
    "decision": e(DECISIONS, required=True),
    "decision_note": s(min_len=0, max_len=4000),
}

TRAINING_SPEC = {
    "journalist_id": s(required=True),
    "module_code": e(MODULE_CODES, required=True),
    "case_study_reference": s(min_len=1, max_len=200),
}

DISCLOSURE_STATUS = {
    "ACKNOWLEDGE": "ACKNOWLEDGED",
    "IMPOSE_RESTRICTION": "RESTRICTION_IMPOSED",
    "REJECT": "REJECTED",
}


# ---------------------------------------------------------------------------
# Conflict disclosures
# ---------------------------------------------------------------------------


@bp.route("/conflict-disclosures", methods=["POST"])
def create_disclosure():
    actor = auth(["Reporter"])
    raw = read_raw_body()
    # Step 4: a reporter files their own disclosure.
    proposed = raw.get("journalist_id")
    if isinstance(proposed, str):
        require_ownership(actor, proposed)
    resolved = resolve_body_ids(raw, ["journalist_id"])
    body = validate_body(raw, DISCLOSURE_SPEC)
    disclosure = base_record()
    disclosure.update({
        "journalist_id": resolved["journalist_id"]["id"],
        "disclosure_type": body["disclosure_type"],
        "subject_entity_name": body["subject_entity_name"],
        "description": body["description"],
        "status": "SUBMITTED",
        "restricted_beats": [],
        "reviewed_by_user_id": None,
        "reviewed_at": None,
    })
    db.disclosures[disclosure["id"]] = disclosure
    return respond_object(ser.disclosure_out(disclosure), 201)


@bp.route("/conflict-disclosures/<disclosure_id>/review", methods=["POST"])
def review_disclosure(disclosure_id):
    actor = auth(["StandardsEditor", "ExecutiveEditor"])
    disclosure = disclosure_or_404(disclosure_id)
    body = validate_body(read_raw_body(), DISCLOSURE_REVIEW_SPEC)
    outcome = body["review_outcome"]
    beats = body["restricted_beats"]
    if outcome == "IMPOSE_RESTRICTION" and not beats:
        raise ApiError("ERR_INVALID_REQUEST",
                       "restricted_beats must be present and non-empty for "
                       "IMPOSE_RESTRICTION.")
    if disclosure["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "The disclosure has already been reviewed.")

    disclosure["status"] = DISCLOSURE_STATUS[outcome]
    disclosure["reviewed_by_user_id"] = actor.user_id
    disclosure["reviewed_at"] = now()
    if outcome == "IMPOSE_RESTRICTION":
        # Duplicates in the supplied labels are collapsed by the union below.
        stored = []
        for beat in beats:
            if beat not in stored:
                stored.append(beat)
        disclosure["restricted_beats"] = stored
    touch(disclosure)

    journalist = db.journalists.get(disclosure["journalist_id"])
    if journalist is not None and calc.recompute_restricted_beats(journalist):
        touch(journalist)
    return respond_object(ser.disclosure_out(disclosure))


@bp.route("/conflict-disclosures/<disclosure_id>", methods=["GET"])
def read_disclosure(disclosure_id):
    auth(["Reporter", "StandardsEditor", "ExecutiveEditor", "PublicEditor"])
    return respond_object(ser.disclosure_out(disclosure_or_404(disclosure_id)))


# ---------------------------------------------------------------------------
# Outside activity
# ---------------------------------------------------------------------------


@bp.route("/outside-activity-requests", methods=["POST"])
def create_activity():
    actor = auth(["Reporter"])
    raw = read_raw_body()
    # Step 4: a reporter asks in their own name.
    proposed = raw.get("journalist_id")
    if isinstance(proposed, str):
        require_ownership(actor, proposed)
    resolved = resolve_body_ids(raw, ["journalist_id"])
    body = validate_body(raw, ACTIVITY_SPEC)
    if body["ends_on"] <= body["starts_on"]:
        raise ApiError("ERR_INVALID_INTERVAL",
                       "ends_on must be strictly after starts_on.")
    activity = base_record()
    activity.update({
        "journalist_id": resolved["journalist_id"]["id"],
        "activity_type": body["activity_type"],
        "compensated": body["compensated"],
        "starts_on": body["starts_on"],
        "ends_on": body["ends_on"],
        "related_beat": body["related_beat"],
        "host_organization": body["host_organization"],
        "status": "REQUESTED",
        "decided_by_user_id": None,
        "decided_at": None,
        "revocation_reason": None,
    })
    db.activities[activity["id"]] = activity
    return respond_object(ser.activity_out(activity), 201)


@bp.route("/outside-activity-requests/<request_id>/decide", methods=["POST"])
def decide_activity(request_id):
    actor = auth(["StandardsEditor", "ExecutiveEditor"])
    activity = activity_or_404(request_id)
    body = validate_body(read_raw_body(), ACTIVITY_DECIDE_SPEC)
    if activity["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a REQUESTED activity may be decided.")

    if body["decision"] == "APPROVE":
        # A denial performs none of these three checks.
        journalist = db.journalists.get(activity["journalist_id"])
        pending = any(d["journalist_id"] == activity["journalist_id"]
                      and d["status"] == "SUBMITTED"
                      for d in db.disclosures.values())
        if pending:
            raise ApiError("ERR_COI_DISCLOSURE_PENDING",
                           "An unreviewed conflict disclosure blocks all outside work.")
        if journalist is not None and activity["related_beat"] in journalist["restricted_beats"]:
            raise ApiError("ERR_ACTIVITY_BEAT_RESTRICTED",
                           "The activity's beat is restricted for this journalist.")
        for other in ordered(list(db.activities.values())):
            if other["id"] == activity["id"] or other["status"] != "APPROVED":
                continue
            if other["journalist_id"] != activity["journalist_id"]:
                continue
            # Half-open windows: touching endpoints are admissible.
            if (activity["starts_on"] < other["ends_on"]
                    and other["starts_on"] < activity["ends_on"]):
                raise ApiError("ERR_OUTSIDE_ACTIVITY_OVERLAP",
                               "The window overlaps an already approved activity.")
        activity["status"] = "APPROVED"
    else:
        activity["status"] = "DENIED"
    activity["decided_by_user_id"] = actor.user_id
    activity["decided_at"] = now()
    touch(activity)
    return respond_object(ser.activity_out(activity))


@bp.route("/outside-activity-requests/<request_id>", methods=["GET"])
def read_activity(request_id):
    auth(["Reporter", "StandardsEditor", "ExecutiveEditor", "PublicEditor"])
    return respond_object(ser.activity_out(activity_or_404(request_id)))


# ---------------------------------------------------------------------------
# Standards training
# ---------------------------------------------------------------------------


@bp.route("/training-records", methods=["POST"])
def create_training_record():
    actor = auth(["Reporter", "StandardsEditor", "ExecutiveEditor"])
    raw = read_raw_body()
    # Step 4: a reporter may only file their own training.
    proposed = raw.get("journalist_id")
    if isinstance(proposed, str):
        require_ownership(actor, proposed)
    resolved = resolve_body_ids(raw, ["journalist_id"])
    body = validate_body(raw, TRAINING_SPEC)
    journalist = resolved["journalist_id"]
    for other in db.training_records.values():
        if (other["journalist_id"] == journalist["id"]
                and other["module_code"] == body["module_code"]):
            raise ApiError("ERR_DUPLICATE_TRAINING_MODULE",
                           "This journalist has already filed that module.")

    # Append-only: no updated_at, no version.
    record = base_record(with_version=False)
    record.update({
        "journalist_id": journalist["id"],
        "module_code": body["module_code"],
        "case_study_reference": body["case_study_reference"],
        "completed_at": now(),
    })
    db.training_records[record["id"]] = record

    if calc.recompute_journalist_training(journalist):
        touch(journalist)
    newsroom = db.newsrooms.get(journalist["newsroom_id"])
    if newsroom is not None and calc.recompute_compliance_index(newsroom):
        touch(newsroom)
    return respond_object(ser.training_out(record), 201)
