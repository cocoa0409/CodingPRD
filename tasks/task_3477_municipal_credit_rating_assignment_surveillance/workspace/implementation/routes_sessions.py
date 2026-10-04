"""Committee sessions (PRD §3.3): schedule (with chair-calendar and
cooling-off rules), open inside the window, close and tally — completion
assigns the Rating."""
from flask import Blueprint, request

import timeutil
from auth import auth, authenticate
from constants import (
    CAUSE_COMMITTEE_ASSIGNMENT,
    COMMITTEE_SIZE,
    EVENT_RATING_ASSIGNED,
    ROLE_COMMITTEE_CHAIR,
    SESSION_COOLING_OFF_HOURS,
)
from envelope import paginate, parse_pagination, success_array, success_object
from errors import (
    ERR_ENGAGEMENT_STATE_INVALID,
    ERR_ESCALATED_REVIEW_BLOCKS_SCHEDULING,
    ERR_INVALID_REQUEST,
    ERR_NO_ACTIVE_CRITERIA,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SESSION_COOLING_OFF,
    ERR_SESSION_NOT_OPENABLE,
    ERR_SESSION_STATE_INVALID,
    ERR_SESSION_WINDOW_OVERLAP,
    ERR_VOTER_POOL_INVALID,
    raise_err,
)
from services_scoring import active_criteria_for, current_scorecard, tally_session
from store import db, new_entity, notify, touch
from validators import (
    body,
    get_engagement,
    get_session,
    present,
    require_datetime,
    require_fields,
)

bp = Blueprint("sessions", __name__)


@bp.route("/muni/engagements/<engagement_id>/committee-sessions", methods=["POST"])
def schedule_session(engagement_id):
    user_id, role = auth([ROLE_COMMITTEE_CHAIR])
    engagement = get_engagement(engagement_id)
    payload = body()

    # Priority 4: required fields, parseable timestamps, end strictly after start.
    require_fields(payload, ["start_at", "end_at", "voter_ids"])
    start_at = require_datetime(payload, "start_at")
    end_at = require_datetime(payload, "end_at")
    if end_at <= start_at:
        raise_err(ERR_INVALID_REQUEST, "end_at must be after start_at")

    # Priority 6: scheduling requires COMMITTEE_READY.
    if engagement["status"] != "COMMITTEE_READY":
        raise_err(ERR_ENGAGEMENT_STATE_INVALID, "engagement is not COMMITTEE_READY")

    # Priority 10(a): the voter pool holds exactly 5 distinct identifiers.
    voter_ids = payload["voter_ids"]
    if (
        not isinstance(voter_ids, list)
        or len(voter_ids) != COMMITTEE_SIZE
        or len(set(voter_ids)) != COMMITTEE_SIZE
    ):
        raise_err(ERR_VOTER_POOL_INVALID, "voter_ids must be exactly 5 distinct identifiers")

    # Scheduling pins the ACTIVE criteria version of the engagement's segment.
    criteria = active_criteria_for(engagement["jurisdiction_code"], engagement["credit_type"])
    if criteria is None:
        raise_err(ERR_NO_ACTIVE_CRITERIA, "no ACTIVE criteria version for this jurisdiction and credit type")

    # Priority 10(j): an ESCALATED review item anywhere in the issuer's
    # portfolio freezes new committee work.
    issuer_rating_ids = [r["id"] for r in db.ratings.values() if r["issuer_id"] == engagement["issuer_id"]]
    if any(
        item["rating_id"] in issuer_rating_ids and item["status"] == "ESCALATED"
        for item in db.review_items.values()
    ):
        raise_err(
            ERR_ESCALATED_REVIEW_BLOCKS_SCHEDULING,
            "an ESCALATED review item blocks scheduling for this issuer",
        )

    # Priority 10(k): chair calendar half-open overlap (adjacency permitted).
    for other in db.sessions.values():
        if other["chair_id"] != user_id or other["status"] not in ("SCHEDULED", "IN_SESSION"):
            continue
        if start_at < other["end_at"] and other["start_at"] < end_at:
            raise_err(ERR_SESSION_WINDOW_OVERLAP, "chair already has a session overlapping this window")

    # Priority 10(k): 24h same-engagement cooling-off; a gap of exactly 24h
    # is allowed.
    prior_ends = [s["end_at"] for s in db.sessions.values() if s["engagement_id"] == engagement["id"]]
    if prior_ends:
        earliest_start = timeutil.add_hours(max(prior_ends), SESSION_COOLING_OFF_HOURS)
        if start_at < earliest_start:
            raise_err(
                ERR_SESSION_COOLING_OFF,
                "session start_at is earlier than 24h after the latest prior session's end_at",
            )

    ent = new_entity()
    ent.update(
        engagement_id=engagement["id"],
        criteria_version_id=criteria["id"],
        chair_id=user_id,
        voter_ids=list(voter_ids),
        appointed_alternate_ids=[],
        recused_voter_ids=[],
        eligible_voter_count=COMMITTEE_SIZE,
        start_at=start_at,
        end_at=end_at,
        status="SCHEDULED",
        outcome_notch=None,
        adjourn_reason=None,
    )
    db.sessions[ent["id"]] = ent
    return success_object(ent, status=201)


@bp.route("/muni/committee-sessions", methods=["GET"])
def list_sessions():
    authenticate()
    items = list(db.sessions.values())
    for field in ("engagement_id", "criteria_version_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [s for s in items if s.get(field) == value]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_array(page, total, limit, offset)


@bp.route("/muni/committee-sessions/<session_id>", methods=["GET"])
def get_one_session(session_id):
    authenticate()
    return success_object(get_session(session_id))


@bp.route("/muni/committee-sessions/<session_id>/open", methods=["POST"])
def open_session(session_id):
    user_id, role = auth([ROLE_COMMITTEE_CHAIR])
    session = get_session(session_id)
    # Priority 5: only the scheduling chair may open.
    if session["chair_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "only the scheduling chair may open this session")
    # Priority 6: state.
    if session["status"] != "SCHEDULED":
        raise_err(ERR_SESSION_STATE_INVALID, "session is not SCHEDULED")
    # Priority 9: the window is [start_at, end_at).
    clock = db.now()
    if not (session["start_at"] <= clock < session["end_at"]):
        raise_err(ERR_SESSION_NOT_OPENABLE, "clock is outside the session window")
    session["status"] = "IN_SESSION"
    touch(session)
    return success_object(session)


@bp.route("/muni/committee-sessions/<session_id>/close", methods=["POST"])
def close_session(session_id):
    user_id, role = auth([ROLE_COMMITTEE_CHAIR])
    session = get_session(session_id)
    # Priority 5: only the scheduling chair may close.
    if session["chair_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "only the scheduling chair may close this session")
    # Priority 6: close from SCHEDULED (cancel unopened) or IN_SESSION (tally).
    if session["status"] not in ("SCHEDULED", "IN_SESSION"):
        raise_err(ERR_SESSION_STATE_INVALID, "session is not SCHEDULED or IN_SESSION")

    if session["status"] == "SCHEDULED":
        # Unopened session adjourns outright with zero votes recorded.
        session["status"] = "ADJOURNED"
        session["adjourn_reason"] = "QUORUM_NOT_MET"
        touch(session)
        return success_object(session)

    engagement = get_engagement(session["engagement_id"])
    scorecard = current_scorecard(engagement["id"])
    if scorecard is None:
        # Unreachable through the API (COMMITTEE_READY implies a scorecard).
        raise_err(ERR_ENGAGEMENT_STATE_INVALID, "engagement has no scorecard")

    new_status, outcome_notch, adjourn_reason = tally_session(session, scorecard["indicative_notch"])
    session["status"] = new_status
    session["outcome_notch"] = outcome_notch
    session["adjourn_reason"] = adjourn_reason
    touch(session)

    if new_status == "COMPLETED":
        _assign_rating(session, engagement, outcome_notch)
    return success_object(session)


def _assign_rating(session, engagement, outcome_notch):
    """Committee completion assigns the rating (PRD §3.3)."""
    clock = db.now()
    rating = new_entity()
    rating.update(
        engagement_id=engagement["id"],
        issuer_id=engagement["issuer_id"],
        criteria_version_id=session["criteria_version_id"],
        credit_type=engagement["credit_type"],
        jurisdiction_code=engagement["jurisdiction_code"],
        notch=outcome_notch,
        outlook=None,
        rationale=None,
        status="ASSIGNED",
        surveillance_posture="CURRENT",
        assigned_at=clock,
        published_at=None,
        withdrawn_at=None,
        withdraw_reason=None,
        notch_at_withdrawal=None,
        review_pending=False,
        notch_history=[
            {"notch": outcome_notch, "changed_at": clock, "cause": CAUSE_COMMITTEE_ASSIGNMENT}
        ],
    )
    db.ratings[rating["id"]] = rating
    if engagement["status"] == "COMMITTEE_READY":
        engagement["status"] = "RATING_ASSIGNED"
        touch(engagement)
    notify(
        engagement["issuer_id"],
        EVENT_RATING_ASSIGNED,
        rating["id"],
        "Rating %s assigned notch %s." % (rating["id"], outcome_notch),
    )
    return rating
