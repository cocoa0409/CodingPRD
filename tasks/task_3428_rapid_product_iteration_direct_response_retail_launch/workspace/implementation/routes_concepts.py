"""ProductLead domain: product concepts, research insights, the advance ladder,
prototype rounds, and round completion."""

from decimal import Decimal

from flask import Blueprint

from auth import ALL_ROLES, require_roles
from constants import CONSTANTS
from errors import ApiError
from serializers import ser_concept, ser_round
from services import (get_or_404, posture_gate, req_fk, season_of_category,
                      season_of_concept)
from state import DB, base_fields, bump, now, touch
from util import (body, by_creation, fmt_iso, momentum_score, ok_object,
                  opt_string, paginate, req_dt, req_int, req_string)

bp = Blueprint("concepts", __name__)

LEAD = ("ProductLead",)

_TERMINAL_FOR_ADVANCE = ("ENGINEERING_LOCKED", "LAUNCH_KILLED")


def _concept_rounds(concept_id):
    return [r for r in by_creation(DB.rounds.values()) if r["concept_id"] == concept_id]


@bp.post("/concepts")
def create_concept():
    require_roles(LEAD)
    data = body()
    cat = req_fk(data, "category_id", DB.categories, "ERR_CATEGORY_NOT_FOUND")
    title = req_string(data, "title")
    posture_gate(season_of_category(cat))
    c = base_fields()
    c.update({
        "category_id": cat["id"],
        "title": title,
        "status": "IDENTIFIED",
        "research_insights": [],
        "rounds_used": 0,
        "killed_reason": None,
        "cycle_base": 0,  # internal: rounds existing when the current cycle began
    })
    DB.concepts[c["id"]] = c
    return ok_object(ser_concept(c), 201)


@bp.get("/concepts/<cid>")
def get_concept(cid):
    require_roles(ALL_ROLES)
    return ok_object(ser_concept(get_or_404(DB.concepts, cid, "ERR_CONCEPT_NOT_FOUND")))


@bp.get("/concepts")
def list_concepts():
    require_roles(ALL_ROLES)
    from flask import request
    items = by_creation(DB.concepts.values())
    category_id = request.args.get("category_id")
    status = request.args.get("status")
    if category_id is not None:
        items = [c for c in items if c["category_id"] == category_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate([ser_concept(c) for c in items])


@bp.post("/concepts/<cid>/insights")
def append_insight(cid):
    require_roles(LEAD)
    c = get_or_404(DB.concepts, cid, "ERR_CONCEPT_NOT_FOUND")
    posture_gate(season_of_concept(c))
    data = body()
    points = req_int(data, "points", min_v=1, max_v=100)
    observed_dt = req_dt(data, "observed_at")
    c["research_insights"].append({"points": points, "observed_dt": observed_dt})
    bump(c)
    # PRD §4: appending to a resource's collection returns 200 OK with the
    # updated resource (only creation of the twelve resources returns 201)
    return ok_object(ser_concept(c), 200)


@bp.post("/concepts/<cid>/advance")
def advance_concept(cid):
    require_roles(LEAD)
    c = get_or_404(DB.concepts, cid, "ERR_CONCEPT_NOT_FOUND")
    posture_gate(season_of_concept(c))
    status = c["status"]
    if status in _TERMINAL_FOR_ADVANCE:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "no advance transition exists from %s" % status)
    if status == "IDENTIFIED":
        if not c["research_insights"]:
            raise ApiError("ERR_NO_RESEARCH_INSIGHTS", 422,
                           "at least one research insight is required")
        c["status"] = "RESEARCHING"
    elif status == "RESEARCHING":
        momentum = momentum_score(c["research_insights"], now())
        if momentum < Decimal(CONSTANTS["RESEARCH_SCORE_MIN"]):
            raise ApiError("ERR_RESEARCH_SCORE_TOO_LOW", 422,
                           "research_momentum %s is below the lock threshold"
                           % momentum)
        c["status"] = "CONCEPT_LOCKED"
    elif status == "CONCEPT_LOCKED":
        c["status"] = "PROTOTYPE_CYCLING"
        c["cycle_base"] = len(_concept_rounds(c["id"]))
    else:  # PROTOTYPE_CYCLING
        passed = any(
            r["round_number"] > c["cycle_base"]
            and r["status"] == "SCORED"
            and r["score"] >= CONSTANTS["ROUND_PASS_SCORE"]
            for r in _concept_rounds(c["id"])
        )
        if not passed:
            raise ApiError("ERR_ROUND_NOT_PASSED", 422,
                           "no SCORED round at or above the pass threshold in the current cycle")
        c["status"] = "ENGINEERING_LOCKED"
    bump(c)
    return ok_object(ser_concept(c))


@bp.post("/concepts/<cid>/rounds")
def open_round(cid):
    require_roles(LEAD)
    c = get_or_404(DB.concepts, cid, "ERR_CONCEPT_NOT_FOUND")
    posture_gate(season_of_concept(c))
    if c["status"] != "PROTOTYPE_CYCLING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "rounds can only be opened while PROTOTYPE_CYCLING")
    if any(r["status"] == "OPEN" for r in _concept_rounds(c["id"])):
        raise ApiError("ERR_ROUND_ALREADY_OPEN", 409,
                       "another round of this concept is still OPEN")
    r = base_fields()
    ts = fmt_iso(now())
    r.update({
        "concept_id": c["id"],
        "round_number": len(_concept_rounds(c["id"])) + 1,
        "status": "OPEN",
        "opened_at": ts,
        "opened_dt": now(),
        "score": None,
        "feedback": None,
    })
    DB.rounds[r["id"]] = r
    return ok_object(ser_round(r), 201)


@bp.get("/concepts/<cid>/rounds")
def list_rounds(cid):
    require_roles(ALL_ROLES)
    get_or_404(DB.concepts, cid, "ERR_CONCEPT_NOT_FOUND")
    # round_number is a 1-based sequence by creation order, so creation sort == it
    return paginate([ser_round(r) for r in _concept_rounds(cid)])


@bp.post("/prototype-rounds/<rid>/complete")
def complete_round(rid):
    require_roles(LEAD)
    r = get_or_404(DB.rounds, rid, "ERR_ROUND_NOT_FOUND")
    concept = get_or_404(DB.concepts, r["concept_id"], "ERR_CONCEPT_NOT_FOUND")
    posture_gate(season_of_concept(concept))
    if r["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "only an OPEN round can be completed")
    data = body()
    score = req_int(data, "score", min_v=0, max_v=100)
    feedback = opt_string(data, "feedback")
    r["status"] = "SCORED"
    r["score"] = score
    r["feedback"] = feedback
    touch(r)  # scaffold lists no PrototypeRound version bump on complete
    # budget: every completion consumes one round of budget unconditionally
    # (PRD §3.2 "incrementing the concept's rounds_used by one"); the revert
    # is scoped to PROTOTYPE_CYCLING ("the concept reverts from
    # PROTOTYPE_CYCLING to RESEARCHING"). No version bump on the concept —
    # round completion is not in the §2.5 version-bump enumeration.
    concept["rounds_used"] += 1
    if (concept["status"] == "PROTOTYPE_CYCLING"
            and score < CONSTANTS["ROUND_PASS_SCORE"]
            and concept["rounds_used"] >= CONSTANTS["MAX_ROUNDS_PER_CYCLE"]):
        concept["rounds_used"] = 0
        concept["status"] = "RESEARCHING"
    touch(concept)
    return ok_object(ser_round(r))
