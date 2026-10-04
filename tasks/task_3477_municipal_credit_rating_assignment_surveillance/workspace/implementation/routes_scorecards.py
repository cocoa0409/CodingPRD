"""Analytical scorecard endpoints (PRD §3.2): OCC-guarded submit/supersede,
the engagement's current scorecard (array of 0 or 1), and the per-criteria
governance listing."""
from flask import Blueprint, request

from auth import auth, authenticate
from constants import ROLE_LEAD_ANALYST
from envelope import paginate, parse_pagination, success_array, success_object
from errors import (
    ERR_ENGAGEMENT_STATE_INVALID,
    ERR_FACTOR_SCORE_OUT_OF_RANGE,
    ERR_NO_ACTIVE_CRITERIA,
    ERR_STALE_ENGAGEMENT_VERSION,
    raise_err,
)
from services_scoring import (
    FACTOR_FIELDS,
    active_criteria_for,
    compute_scorecard,
    current_scorecard,
)
from store import db, new_entity, touch
from validators import (
    body,
    get_criteria_version,
    get_engagement,
    is_int,
    require_fields,
)

bp = Blueprint("scorecards", __name__)

_SCORE_FIELDS = [f for f, _ in FACTOR_FIELDS]


@bp.route("/muni/engagements/<engagement_id>/scorecard", methods=["POST"])
def submit_scorecard(engagement_id):
    user_id, role = auth([ROLE_LEAD_ANALYST])
    engagement = get_engagement(engagement_id)
    payload = body()

    # Priority 4: all six factor scores and the OCC anchor are required fields.
    require_fields(payload, _SCORE_FIELDS + ["expected_engagement_version"])

    # Priority 6: scorecard only from ANALYSIS or COMMITTEE_READY.
    if engagement["status"] not in ("ANALYSIS", "COMMITTEE_READY"):
        raise_err(ERR_ENGAGEMENT_STATE_INVALID, "engagement is not in ANALYSIS or COMMITTEE_READY")

    # Priority 7: OCC on the engagement version.
    if not is_int(payload["expected_engagement_version"]) or payload[
        "expected_engagement_version"
    ] != engagement["version"]:
        raise_err(ERR_STALE_ENGAGEMENT_VERSION, "expected_engagement_version does not match the engagement version")

    # Priority 10(d): every factor score an integer in 1..5.
    scores = {}
    for field in _SCORE_FIELDS:
        value = payload[field]
        if not is_int(value) or value < 1 or value > 5:
            raise_err(ERR_FACTOR_SCORE_OUT_OF_RANGE, "factor scores must be integers in 1..5")
        scores[field] = value

    # Priority 10(i): an ACTIVE criteria version must exist for the segment.
    criteria = active_criteria_for(engagement["jurisdiction_code"], engagement["credit_type"])
    if criteria is None:
        raise_err(ERR_NO_ACTIVE_CRITERIA, "no ACTIVE criteria version for this jurisdiction and credit type")

    computed = compute_scorecard(criteria, scores, engagement["credit_type"])
    ent = new_entity()
    ent.update(
        engagement_id=engagement["id"],
        criteria_version_id=computed["criteria_version_id"],
        weighted_score=computed["weighted_score"],
        anchor_notch=computed["anchor_notch"],
        capped=computed["capped"],
        indicative_notch=computed["indicative_notch"],
        **{f: scores[f] for f in _SCORE_FIELDS},
    )
    db.scorecards[ent["id"]] = ent  # create-with-supersede: latest wins

    engagement["assigned_analyst_id"] = user_id
    if engagement["status"] == "ANALYSIS":
        engagement["status"] = "COMMITTEE_READY"
    touch(engagement)
    return success_object(ent)


@bp.route("/muni/engagements/<engagement_id>/scorecard", methods=["GET"])
def get_engagement_scorecard(engagement_id):
    authenticate()
    engagement = get_engagement(engagement_id)
    current = current_scorecard(engagement["id"])
    items = [current] if current is not None else []
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_array(page, total, limit, offset)


@bp.route("/muni/criteria-versions/<criteria_version_id>/scorecards", methods=["GET"])
def list_criteria_scorecards(criteria_version_id):
    authenticate()
    criteria = get_criteria_version(criteria_version_id)
    items = [s for s in db.scorecards.values() if s["criteria_version_id"] == criteria["id"]]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_array(page, total, limit, offset)
