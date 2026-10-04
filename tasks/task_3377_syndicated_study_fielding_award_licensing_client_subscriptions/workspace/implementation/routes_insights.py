"""Client insights (diagnostics / benchmarking), the press kit, and the
test-driving logical clock endpoint."""
from flask import Blueprint, g

from db import clock, store
from envelope import ok_object
from errors import fail
from middleware import require
from records import ser_award
from services import (
    accepted_responses,
    active_mv,
    brand_results_of,
    factor_scores,
    factors_of,
    find_active_subscription,
    find_brand_result,
)
from timeutil import iso
from validation import Body

bp = Blueprint("insights", __name__, url_prefix="/research")


def _published_study(sid):
    study = store.studies.get(sid)
    if study is None:
        fail("ERR_NOT_FOUND", "Study not found")
    if study["status"] != "PUBLISHED":
        fail("ERR_RESULTS_NOT_PUBLISHED", "Insights require a PUBLISHED study")
    return study


@bp.get("/studies/<sid>/diagnostics")
@require("ClientUser")
def diagnostics(sid):
    study = _published_study(sid)
    sub = find_active_subscription(g.user_id, sid)
    if sub is None:
        fail("ERR_SUBSCRIPTION_REQUIRED", "An ACTIVE in-window subscription is required")
    client = store.clients.get(g.user_id)
    brand_id = client["brand_id"] if client is not None else None
    if not brand_id:
        fail("ERR_NOT_FOUND", "Client record carries no brand_id")
    br = find_brand_result(sid, brand_id)
    if br is None:
        fail("ERR_NOT_FOUND", "No BrandResult exists for the client's brand in this study")
    mv = active_mv(study)
    factors = factors_of(mv["id"]) if mv is not None else []
    rs = accepted_responses(sid, brand_id)
    fs = (
        [{"factor_code": f["code"], "score": s} for f, s in factor_scores(rs, factors)]
        if rs else []
    )
    return ok_object({
        "study_id": sid,
        "brand_id": brand_id,
        "eligible": br["eligible"],
        "accepted_n": br["accepted_n"],
        "final_index": br["final_index"],
        "rank_position": br["rank_position"],
        "significance_group": br["significance_group"],
        "factor_scores": fs,
    })


@bp.get("/studies/<sid>/benchmarking")
@require("ClientUser")
def benchmarking(sid):
    study = _published_study(sid)
    sub = find_active_subscription(g.user_id, sid)
    if sub is None:
        fail("ERR_SUBSCRIPTION_REQUIRED", "An ACTIVE in-window subscription is required")
    if sub["tier"] != "BENCHMARK":
        fail("ERR_TIER_INSUFFICIENT", "Benchmarking requires subscription tier BENCHMARK")
    mv = active_mv(study)
    elig = [br for br in brand_results_of(sid) if br["eligible"]]

    def rank_key(br):
        b = store.brands.get(br["brand_id"])
        brand_k = (b["created_at"], b["_seq"]) if b is not None else (study["created_at"], 0)
        return (br["rank_position"], -br["final_index"], brand_k)

    elig.sort(key=rank_key)
    rankings = [
        {
            "brand_id": br["brand_id"],
            "final_index": br["final_index"],
            "rank_position": br["rank_position"],
            "significance_group": br["significance_group"],
            "accepted_n": br["accepted_n"],
        }
        for br in elig
    ]
    # year-over-year comparability (pinned methodology's declared change class)
    yoy_comparable = False
    yoy_delta = None
    client = store.clients.get(g.user_id)
    brand_id = client["brand_id"] if client is not None else None
    prior = None
    if study["prior_study_id"]:
        prior = store.studies.get(study["prior_study_id"])
    if (
        prior is not None
        and prior["status"] == "PUBLISHED"
        and mv is not None
        and mv["change_class"] != "BREAK"
        and brand_id
    ):
        cur_br = find_brand_result(sid, brand_id)
        prior_br = find_brand_result(prior["id"], brand_id)
        if (
            cur_br is not None and cur_br["final_index"] is not None
            and prior_br is not None and prior_br["final_index"] is not None
        ):
            yoy_comparable = True
            yoy_delta = cur_br["final_index"] - prior_br["final_index"]
    return ok_object({
        "study_id": sid,
        "change_class": mv["change_class"] if mv is not None else None,
        "yoy_comparable": yoy_comparable,
        "yoy_delta": yoy_delta,
        "rankings": rankings,
    })


@bp.get("/studies/<sid>/press-kit")
@require("PressUser", "StudyAdmin")
def press_kit(sid):
    study = store.studies.get(sid)
    if study is None:
        fail("ERR_NOT_FOUND", "Study not found")
    embargo_status = "EMBARGOED" if clock.now() < study["embargo_lift_at"] else "LIFTED"
    awards = sorted(
        (a for a in store.awards.values() if a["study_id"] == sid),
        key=lambda a: (a["created_at"], a["_seq"]),
    )
    return ok_object({
        "study_id": sid,
        "name": study["name"],
        "embargo_lift_at": iso(study["embargo_lift_at"]),
        "embargo_status": embargo_status,
        "published_at": iso(study["published_at"]),
        "awards": [ser_award(a) for a in awards],
    })


@bp.post("/_clock/set_current_utc")
@require("StudyAdmin")
def set_clock():
    b = Body()
    dt = b.dt_("to_iso8601")
    b.finalize()
    clock.set(dt)
    return ok_object({"current_utc": iso(clock.now())}, 200)
