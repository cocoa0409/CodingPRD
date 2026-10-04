"""States and state adoptions (PRD 3.2)."""

from decimal import Decimal

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
from db import store, base_record, touch, state_by_code
from errors import ApiError
from serialize import serialize_state, serialize_adoption
from util import get_body, req_str, req_enum, req_int, req_ts, ok_object, paginate

bp = Blueprint("states", __name__)


def get_state_or_404(state_id):
    st = store.states.get(state_id)
    if st is None:
        raise ApiError("ERR_STATE_NOT_FOUND", "State not found: %s" % state_id, 404)
    return st


@bp.post("/naic/states")
def create_state():
    principal = authenticate()
    require_role(principal, {ROLE_ASSOCIATION_STAFF})
    body = get_body()
    code = req_str(body, "code")
    name = req_str(body, "name")
    # PRD 2.7 declares state code unique but assigns no catalogue error id;
    # enforced here as a shape-level rejection.
    if state_by_code(code) is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "State code already registered: %s" % code, 400
        )
    rec = base_record()
    rec.update({
        "code": code,
        "name": name,
        "accreditation_status": "ACCREDITED",
        "consecutive_fail_count": 0,
        "core_act_coverage_pct": Decimal("100.0"),
    })
    store.states[rec["id"]] = rec
    return ok_object(serialize_state(rec), 201)


@bp.get("/naic/states/<state_id>")
def read_state(state_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    return ok_object(serialize_state(get_state_or_404(state_id)), 200)


@bp.post("/naic/adoptions")
def create_adoption():
    principal = authenticate()
    require_role(principal, {ROLE_STATE_REGULATOR})
    body = get_body()
    # Stage 2 ownership (body-derived).
    supplied = body.get("state_code")
    if supplied is not None and supplied != principal.entity["code"]:
        forbidden("state_code must equal the acting regulator's state code")
    # Stage 4 body reference resolution.
    act = None
    if body.get("model_act_id") is not None:
        if isinstance(body["model_act_id"], str):
            act = store.model_acts.get(body["model_act_id"])
        if act is None:
            raise ApiError("ERR_MODEL_ACT_NOT_FOUND", "model_act_id does not resolve", 404)
    # Stage 5 shape.
    req_str(body, "model_act_id")
    state_code = req_str(body, "state_code")
    adopted_citation = req_str(body, "adopted_citation")
    enacted_on = req_ts(body, "enacted_on")
    expected_state_version = req_int(body, "expected_state_version")
    state = principal.entity
    # Stage 6 state gate.
    if act["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_ACT_NOT_PUBLISHED",
            "Act %s is not PUBLISHED" % act["id"],
            422,
        )
    # Stage 7 OCC.
    if expected_state_version != state["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_state_version does not match the state's current version",
            412,
        )
    # Stage 9 duplicate guard.
    for ad in store.adoptions.values():
        if (
            ad["state_code"] == state_code
            and ad["model_act_id"] == act["id"]
            and ad["status"] == "PENDING_CERTIFICATION"
        ):
            raise ApiError(
                "ERR_DUPLICATE_ADOPTION",
                "State %s already holds a PENDING_CERTIFICATION adoption for this act"
                % state_code,
                409,
            )
    # Supersession happens at successor CREATION time (adjudicated at PRD time).
    superseded = False
    for ad in store.adoptions.values():
        if (
            ad["state_code"] == state_code
            and ad["model_act_id"] == act["id"]
            and ad["status"] in ("CERTIFIED_SIMILAR", "CERTIFIED_VARIED")
        ):
            ad["status"] = "SUPERSEDED"
            touch(ad)
            superseded = True
    rec = base_record()
    rec.update({
        "model_act_id": act["id"],
        "state_code": state_code,
        "adopted_citation": adopted_citation,
        "enacted_on": enacted_on,
        "status": "PENDING_CERTIFICATION",
    })
    store.adoptions[rec["id"]] = rec
    # The state's version increments by exactly one for the recording.
    touch(state)
    if superseded:
        calc.recompute_coverage(state)
    return ok_object(serialize_adoption(rec), 201)


@bp.get("/naic/model-acts/<act_id>/adoptions")
def list_act_adoptions(act_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    act = store.model_acts.get(act_id)
    if act is None:
        raise ApiError("ERR_MODEL_ACT_NOT_FOUND", "Model act not found: %s" % act_id, 404)
    ads = [a for a in store.adoptions.values() if a["model_act_id"] == act["id"]]
    return paginate(ads, serialize_adoption)


@bp.post("/naic/adoptions/<adoption_id>/certify")
def certify_adoption(adoption_id):
    principal = authenticate()
    require_role(principal, {ROLE_ASSOCIATION_STAFF})
    adoption = store.adoptions.get(adoption_id)
    if adoption is None:
        raise ApiError(
            "ERR_ADOPTION_NOT_FOUND", "Adoption not found: %s" % adoption_id, 404
        )
    body = get_body()
    variation_class = req_enum(
        body,
        "variation_class",
        {"SUBSTANTIALLY_SIMILAR", "SUBSTANTIVE_VARIATIONS", "NOT_SIMILAR"},
    )
    if adoption["status"] != "PENDING_CERTIFICATION":
        raise ApiError(
            "ERR_ADOPTION_NOT_PENDING",
            "Adoption %s is not PENDING_CERTIFICATION" % adoption_id,
            409,
        )
    adoption["status"] = {
        "SUBSTANTIALLY_SIMILAR": "CERTIFIED_SIMILAR",
        "SUBSTANTIVE_VARIATIONS": "CERTIFIED_VARIED",
        "NOT_SIMILAR": "REJECTED_NOT_SIMILAR",
    }[variation_class]
    touch(adoption)
    # All three branches recompute the adopting state's coverage.
    state = state_by_code(adoption["state_code"])
    if state is not None:
        calc.recompute_coverage(state)
    return ok_object(serialize_adoption(adoption), 200)
