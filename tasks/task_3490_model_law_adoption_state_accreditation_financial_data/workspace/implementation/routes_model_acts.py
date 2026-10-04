"""Model act registry: create, read, close-ballot, publish (PRD 3.1-3.2)."""

from flask import Blueprint

import calc
from auth import authenticate, require_role, ALL_ROLES, ROLE_ASSOCIATION_STAFF
from db import store, base_record, touch
from errors import ApiError
from serialize import serialize_model_act
from util import get_body, req_str, req_enum, opt_bool, ok_object

bp = Blueprint("model_acts", __name__)


def get_act_or_404(act_id):
    act = store.model_acts.get(act_id)
    if act is None:
        raise ApiError("ERR_MODEL_ACT_NOT_FOUND", "Model act not found: %s" % act_id, 404)
    return act


@bp.post("/naic/model-acts")
def create_model_act():
    principal = authenticate()
    require_role(principal, {ROLE_ASSOCIATION_STAFF})
    body = get_body()
    model_code = req_str(body, "model_code")
    version_label = req_str(body, "version_label")
    title = req_str(body, "title")
    act_type = req_enum(body, "act_type", {"MODEL_LAW", "MODEL_REGULATION"})
    committee_name = req_str(body, "committee_name")
    is_core = opt_bool(body, "is_core", False)
    for a in store.model_acts.values():
        if a["model_code"] == model_code and a["version_label"] == version_label:
            raise ApiError(
                "ERR_DUPLICATE_MODEL_ACT",
                "A model act already exists for (%s, %s)" % (model_code, version_label),
                409,
            )
    rec = base_record()
    rec.update({
        "model_code": model_code,
        "version_label": version_label,
        "title": title,
        "act_type": act_type,
        "committee_name": committee_name,
        "is_core": is_core,
        "status": "DRAFTING",
        "published_at": None,
        "votes_cast": 0,
        "favorable_votes": 0,
    })
    store.model_acts[rec["id"]] = rec
    return ok_object(serialize_model_act(rec), 201)


@bp.get("/naic/model-acts/<act_id>")
def read_model_act(act_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    return ok_object(serialize_model_act(get_act_or_404(act_id)), 200)


@bp.post("/naic/model-acts/<act_id>/close-ballot")
def close_ballot(act_id):
    principal = authenticate()
    require_role(principal, {ROLE_ASSOCIATION_STAFF})
    act = get_act_or_404(act_id)
    if act["status"] != "BALLOTING":
        raise ApiError(
            "ERR_ACT_NOT_BALLOTING",
            "Act %s is not in BALLOTING status" % act_id,
            409,
        )
    eligible = sum(
        1
        for s in store.states.values()
        if s["accreditation_status"] in ("ACCREDITED", "PROBATION")
    )
    cast = [
        b
        for b in store.ballots.values()
        if b["model_act_id"] == act_id and b["status"] == "CAST"
    ]
    votes_cast = len(cast)
    favorable = sum(1 for b in cast if b["vote"] == "YEA")
    if calc.ballot_passes(eligible, votes_cast, favorable):
        act["votes_cast"] = votes_cast
        act["favorable_votes"] = favorable
        act["status"] = "ADOPTED"
    else:
        # Revision loop: every CAST ballot cascades to VOID; counters reset.
        for b in cast:
            b["status"] = "VOID"
            touch(b)
        act["votes_cast"] = 0
        act["favorable_votes"] = 0
        act["status"] = "DRAFTING"
    touch(act)
    return ok_object(serialize_model_act(act), 200)


@bp.post("/naic/model-acts/<act_id>/publish")
def publish_model_act(act_id):
    principal = authenticate()
    require_role(principal, {ROLE_ASSOCIATION_STAFF})
    act = get_act_or_404(act_id)
    if act["status"] != "ADOPTED":
        raise ApiError(
            "ERR_ACT_NOT_ADOPTED",
            "Act %s is not in ADOPTED status" % act_id,
            409,
        )
    act["published_at"] = store.clock
    act["status"] = "PUBLISHED"
    touch(act)

    # Hop 1: prior PUBLISHED act of the same model_code becomes SUPERSEDED.
    superseded_acts = [
        a
        for a in store.model_acts.values()
        if a["id"] != act_id
        and a["model_code"] == act["model_code"]
        and a["status"] == "PUBLISHED"
    ]
    affected_state_codes = set()
    for old in superseded_acts:
        old["status"] = "SUPERSEDED"
        touch(old)
        # Hop 2: adoptions of the superseded act (except REJECTED_NOT_SIMILAR).
        for ad in store.adoptions.values():
            if ad["model_act_id"] == old["id"] and ad["status"] in (
                "PENDING_CERTIFICATION",
                "CERTIFIED_SIMILAR",
                "CERTIFIED_VARIED",
            ):
                ad["status"] = "SUPERSEDED"
                touch(ad)
                affected_state_codes.add(ad["state_code"])

    # Hop 3: recompute coverage for every state whose adoption was superseded.
    affected_states = []
    for code in affected_state_codes:
        st = None
        for s in store.states.values():
            if s["code"] == code:
                st = s
                break
        if st is not None:
            calc.recompute_coverage(st)
            affected_states.append(st)

    # Hop 4: ACCREDITED states that fell below MIN_COVERAGE_PCT get an
    # AUTO_COVERAGE review (null team_lead_id, period [now, now+180d], 0/1).
    for st in affected_states:
        if (
            st["accreditation_status"] == "ACCREDITED"
            and st["core_act_coverage_pct"] < calc.MIN_COVERAGE_PCT
        ):
            calc.auto_create_coverage_review(st)

    return ok_object(serialize_model_act(act), 200)
