"""Committee ballots and alternate appointments (PRD §3.3): one vote or
recusal per voter per session, segregation of duties, pool eligibility."""
from flask import Blueprint, request

from auth import auth, authenticate
from constants import (
    COMMITTEE_SIZE,
    NOTCH_SCALE,
    ROLE_COMMITTEE_CHAIR,
    ROLE_COMMITTEE_MEMBER,
)
from envelope import paginate, parse_pagination, success_array, success_object
from errors import (
    ERR_ALTERNATE_NOT_PERMITTED,
    ERR_ANALYST_VOTE_FORBIDDEN,
    ERR_DUPLICATE_COMMITTEE_VOTE,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_RECUSED_VOTER_VOTE_FORBIDDEN,
    ERR_SESSION_STATE_INVALID,
    ERR_VOTE_KIND_AMBIGUOUS,
    ERR_VOTER_NOT_ELIGIBLE,
    raise_err,
)
from store import db, new_entity, touch
from validators import body, get_engagement, get_session, present, require_fields

bp = Blueprint("votes", __name__)


def _eligible_count(session):
    return COMMITTEE_SIZE - len(session["recused_voter_ids"]) + len(session["appointed_alternate_ids"])


@bp.route("/muni/committee-sessions/<session_id>/votes", methods=["POST"])
def cast_vote(session_id):
    user_id, role = auth([ROLE_COMMITTEE_MEMBER])
    session = get_session(session_id)
    payload = body()

    # Priority 4: voter_id required; notch_vote in range when present.
    require_fields(payload, ["voter_id"])
    voter_id = payload["voter_id"]
    has_notch = present(payload, "notch_vote")
    has_recusal = present(payload, "recusal_reason")
    if has_notch and payload["notch_vote"] not in NOTCH_SCALE:
        raise_err(ERR_INVALID_REQUEST, "notch_vote must be one of the seven rating notches")
    if has_recusal and not isinstance(payload["recusal_reason"], str):
        raise_err(ERR_INVALID_REQUEST, "recusal_reason must be text")
    kind = "VOTE" if has_notch else ("RECUSAL" if has_recusal else None)

    # Priority 6: ballots are accepted only while the session is IN_SESSION.
    if session["status"] != "IN_SESSION":
        raise_err(ERR_SESSION_STATE_INVALID, "session is not IN_SESSION")

    engagement = get_engagement(session["engagement_id"])

    # Priority 8: segregation of duties and vote integrity, in scaffold order.
    if voter_id == engagement["assigned_analyst_id"]:
        raise_err(ERR_ANALYST_VOTE_FORBIDDEN, "the assigned analyst may not vote on this engagement")
    if kind == "VOTE" and voter_id in session["recused_voter_ids"]:
        raise_err(ERR_RECUSED_VOTER_VOTE_FORBIDDEN, "a recused voter may not later cast a vote")
    pool = list(session["voter_ids"]) + list(session["appointed_alternate_ids"])
    if voter_id != user_id or voter_id not in pool:
        raise_err(ERR_VOTER_NOT_ELIGIBLE, "voter_id must equal X-User-ID and belong to the session pool")

    # Priority 10(b): exactly one of notch_vote / recusal_reason.
    if has_notch == has_recusal:
        raise_err(ERR_VOTE_KIND_AMBIGUOUS, "supply exactly one of notch_vote or recusal_reason")

    # Priority 10(g): one ballot per voter per session.
    if any(v["session_id"] == session["id"] and v["voter_id"] == voter_id for v in db.votes.values()):
        raise_err(ERR_DUPLICATE_COMMITTEE_VOTE, "voter already has a recorded ballot in this session")

    ent = new_entity(has_version=False)
    ent.update(
        session_id=session["id"],
        voter_id=voter_id,
        kind=kind,
        notch_vote=payload["notch_vote"] if has_notch else None,
        recusal_reason=payload["recusal_reason"] if has_recusal else None,
    )
    db.votes[ent["id"]] = ent
    if kind == "RECUSAL":
        session["recused_voter_ids"].append(voter_id)
        session["eligible_voter_count"] = _eligible_count(session)
    touch(session)
    return success_object(ent, status=201)


@bp.route("/muni/committee-sessions/<session_id>/votes", methods=["GET"])
def list_votes(session_id):
    authenticate()
    session = get_session(session_id)
    items = [v for v in db.votes.values() if v["session_id"] == session["id"]]
    items.sort(key=lambda v: (v["created_at"], v["_seq"]))
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_array(page, total, limit, offset)


@bp.route("/muni/committee-sessions/<session_id>/alternates", methods=["POST"])
def appoint_alternate(session_id):
    user_id, role = auth([ROLE_COMMITTEE_CHAIR])
    session = get_session(session_id)
    payload = body()
    require_fields(payload, ["recused_voter_id", "alternate_voter_id"])
    recused_voter_id = payload["recused_voter_id"]
    alternate_voter_id = payload["alternate_voter_id"]

    # Priority 5: only the scheduling chair appoints alternates.
    if session["chair_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "only the scheduling chair may appoint alternates")

    # Priority 10(h): the seat must be genuinely recused, the alternate must
    # not already sit in the pool or among the recused, the session must not
    # be terminal, and each recused seat takes at most one alternate.
    alternates_for = session.setdefault("_alternate_for", {})
    if session["status"] in ("COMPLETED", "ADJOURNED"):
        raise_err(ERR_ALTERNATE_NOT_PERMITTED, "session is terminal")
    if recused_voter_id not in session["recused_voter_ids"]:
        raise_err(ERR_ALTERNATE_NOT_PERMITTED, "recused_voter_id has no recorded recusal")
    if (
        alternate_voter_id in session["voter_ids"]
        or alternate_voter_id in session["appointed_alternate_ids"]
        or alternate_voter_id in session["recused_voter_ids"]
    ):
        raise_err(ERR_ALTERNATE_NOT_PERMITTED, "alternate already sits in the pool or among the recused")
    if recused_voter_id in alternates_for:
        raise_err(ERR_ALTERNATE_NOT_PERMITTED, "recused seat already filled by an alternate")

    session["appointed_alternate_ids"].append(alternate_voter_id)
    alternates_for[recused_voter_id] = alternate_voter_id
    session["eligible_voter_count"] = _eligible_count(session)
    touch(session)
    return success_object(session)
