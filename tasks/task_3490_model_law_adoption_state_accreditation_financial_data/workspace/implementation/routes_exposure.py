"""Exposure drafts and member ballots (PRD 3.1)."""

from flask import Blueprint

import calc
from auth import (
    authenticate,
    require_role,
    forbidden,
    ALL_ROLES,
    ROLE_ASSOCIATION_STAFF,
    ROLE_STATE_REGULATOR,
)
from db import store, base_record, touch
from errors import ApiError
from routes_model_acts import get_act_or_404
from serialize import serialize_exposure_draft, serialize_ballot
from util import get_body, req_str, req_enum, req_ts, ok_object, paginate

bp = Blueprint("exposure", __name__)


@bp.post("/naic/exposure-drafts")
def create_exposure_draft():
    principal = authenticate()
    require_role(principal, {ROLE_ASSOCIATION_STAFF})
    body = get_body()
    # Stage 4 (body reference resolution) precedes stage 5 (request shape).
    act = None
    if body.get("model_act_id") is not None:
        if isinstance(body["model_act_id"], str):
            act = store.model_acts.get(body["model_act_id"])
        if act is None:
            raise ApiError("ERR_MODEL_ACT_NOT_FOUND", "model_act_id does not resolve", 404)
    req_str(body, "model_act_id")
    window_start = req_ts(body, "comment_window_start")
    window_end = req_ts(body, "comment_window_end")
    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "comment_window_end must be strictly after comment_window_start",
            400,
        )
    # Stage 6: lifecycle state gate.
    if act["status"] not in ("DRAFTING", "EXPOSURE_OPEN"):
        raise ApiError(
            "ERR_ACT_NOT_OPEN_FOR_EXPOSURE",
            "Act %s is not open for exposure" % act["id"],
            409,
        )
    # Stage 10: minimum window length.
    if window_end - window_start < calc.MIN_COMMENT_WINDOW:
        raise ApiError(
            "ERR_COMMENT_WINDOW_TOO_SHORT",
            "Comment window must span at least 30 days",
            422,
        )
    # Stage 11: half-open [start, end) overlap against all drafts of the act;
    # bare adjacency (new start == existing end) is allowed.
    for d in store.exposure_drafts.values():
        if d["model_act_id"] != act["id"]:
            continue
        if window_start < d["comment_window_end"] and d["comment_window_start"] < window_end:
            raise ApiError(
                "ERR_EXPOSURE_WINDOW_OVERLAP",
                "Comment window intersects another draft of this act",
                409,
            )
    exposure_number = 1 + sum(
        1 for d in store.exposure_drafts.values() if d["model_act_id"] == act["id"]
    )
    rec = base_record()
    rec.update({
        "model_act_id": act["id"],
        "exposure_number": exposure_number,
        "comment_window_start": window_start,
        "comment_window_end": window_end,
        "status": "OPEN",
    })
    store.exposure_drafts[rec["id"]] = rec
    if act["status"] == "DRAFTING":
        act["status"] = "EXPOSURE_OPEN"
    touch(act)
    return ok_object(serialize_exposure_draft(rec), 201)


@bp.get("/naic/model-acts/<act_id>/exposure-drafts")
def list_exposure_drafts(act_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    act = get_act_or_404(act_id)
    drafts = [d for d in store.exposure_drafts.values() if d["model_act_id"] == act["id"]]
    return paginate(drafts, serialize_exposure_draft)


@bp.post("/naic/exposure-drafts/<draft_id>/close")
def close_exposure_draft(draft_id):
    principal = authenticate()
    require_role(principal, {ROLE_ASSOCIATION_STAFF})
    draft = store.exposure_drafts.get(draft_id)
    if draft is None:
        raise ApiError(
            "ERR_EXPOSURE_DRAFT_NOT_FOUND", "Exposure draft not found: %s" % draft_id, 404
        )
    if draft["status"] != "OPEN":
        raise ApiError(
            "ERR_EXPOSURE_DRAFT_NOT_OPEN",
            "Exposure draft %s is not OPEN" % draft_id,
            409,
        )
    if store.clock < draft["comment_window_end"]:
        raise ApiError(
            "ERR_COMMENT_WINDOW_OPEN",
            "Comment window is still open",
            409,
        )
    draft["status"] = "CLOSED"
    touch(draft)
    act = store.model_acts.get(draft["model_act_id"])
    if act is not None and act["status"] == "EXPOSURE_OPEN":
        still_open = any(
            d["model_act_id"] == act["id"] and d["status"] == "OPEN"
            for d in store.exposure_drafts.values()
        )
        if not still_open:
            act["status"] = "BALLOTING"
            touch(act)
    return ok_object(serialize_exposure_draft(draft), 200)


@bp.post("/naic/model-acts/<act_id>/ballots")
def cast_ballot(act_id):
    principal = authenticate()
    require_role(principal, {ROLE_STATE_REGULATOR})
    body = get_body()
    # Stage 2 ownership (body-derived): the supplied state_code must equal the
    # acting regulator's State code.
    supplied = body.get("state_code")
    if supplied is not None and supplied != principal.entity["code"]:
        forbidden("state_code must equal the acting regulator's state code")
    act = get_act_or_404(act_id)
    state_code = req_str(body, "state_code")
    vote = req_enum(body, "vote", {"YEA", "NAY", "ABSTAIN"})
    # PRD 3.1 explicit order: BALLOTING gate, then suspended gate, then dup.
    if act["status"] != "BALLOTING":
        raise ApiError(
            "ERR_ACT_NOT_BALLOTING",
            "Act %s is not in BALLOTING status" % act_id,
            409,
        )
    if principal.entity["accreditation_status"] == "SUSPENDED":
        raise ApiError(
            "ERR_VOTING_STATE_SUSPENDED",
            "SUSPENDED states may not cast ballots",
            422,
        )
    for b in store.ballots.values():
        if (
            b["model_act_id"] == act_id
            and b["state_code"] == state_code
            and b["status"] == "CAST"
        ):
            raise ApiError(
                "ERR_DUPLICATE_BALLOT",
                "State %s already holds a CAST ballot on this act" % state_code,
                409,
            )
    rec = base_record()
    rec.update({
        "model_act_id": act_id,
        "state_code": state_code,
        "vote": vote,
        "status": "CAST",
        "cast_at": store.clock,
    })
    store.ballots[rec["id"]] = rec
    cast = [
        b
        for b in store.ballots.values()
        if b["model_act_id"] == act_id and b["status"] == "CAST"
    ]
    act["votes_cast"] = len(cast)
    act["favorable_votes"] = sum(1 for b in cast if b["vote"] == "YEA")
    touch(act)
    return ok_object(serialize_ballot(rec), 201)


@bp.get("/naic/model-acts/<act_id>/ballots")
def list_ballots(act_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    act = get_act_or_404(act_id)
    ballots = [b for b in store.ballots.values() if b["model_act_id"] == act["id"]]
    return paginate(ballots, serialize_ballot)
