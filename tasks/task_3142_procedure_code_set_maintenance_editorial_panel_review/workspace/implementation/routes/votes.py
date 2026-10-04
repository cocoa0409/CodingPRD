"""Editorial ballots and the seat-weighted meeting tallies."""

from flask import Blueprint, request

import auth
import parsers as P
import resolvers as R
import store
from clock import logical_now
from errors import ERR_DUPLICATE_VOTE, ERR_INVALID_STATE, ApiError
from response import object_response
from routes.common import guard, list_response, one
from services import votes as VT

bp = Blueprint("votes", __name__)

CHAIR = (auth.EDITORIAL_PANEL_CHAIR,)
READERS = (auth.EDITORIAL_STAFF, auth.EDITORIAL_PANEL_CHAIR)

VOTE_POSITIONS = ("YES", "NO", "ABSTAIN")


@bp.post("/editorial-votes")
@guard(CHAIR)
def cast_vote(actor):
    data = P.body()
    change = R.code_change(P.text_or_none(data.get("change_id")) or "")
    meeting = R.meeting(P.text_or_none(data.get("meeting_id")) or "")
    society = R.society(P.text_or_none(data.get("society_id")) or "")
    position = P.text(data.get("vote"))
    if position not in VOTE_POSITIONS:
        raise ApiError(ERR_INVALID_STATE, "an unsupported ballot position")

    # Only a seated society may cast the single ballot it is entitled to on a
    # given change at a given meeting; a prior ballot is superseded rather than
    # accumulated, and an attempt that does not supersede is rejected.
    prior = None
    for vote in store.editorial_votes.values():
        if vote.get("change_id") != change["id"]:
            continue
        if vote.get("meeting_id") != meeting["id"]:
            continue
        if vote.get("society_id") != society["id"]:
            continue
        if prior is None or _later(vote, prior):
            prior = vote

    if prior is not None and not _supersedes(prior, meeting):
        raise ApiError(ERR_DUPLICATE_VOTE,
                       "the society has already cast the ballot it is entitled to")

    recorded = store.create(store.editorial_votes, {
        "change_id": change["id"],
        "meeting_id": meeting["id"],
        "society_id": society["id"],
        "vote": position,
        "votes_carried": VT.votes_carried_for(society, bool(meeting.get("citation_mode"))),
        "cast_at": logical_now(),
    })
    VT.panel_weighted_vote_tally(meeting)
    store.bump(meeting)
    return object_response(one(recorded), 201)


def _later(candidate, incumbent):
    """(cast_at, created_at, insertion sequence) ascending ordering; the greater
    row is the later ballot and supersedes the other.  The insertion sequence is
    needed because the logical clock is frozen, so a superseding ballot can
    share both of its timestamps with the ballot it replaces."""
    return (candidate.get("cast_at"), candidate.get("created_at"),
            candidate.get("_seq", 0)) > (incumbent.get("cast_at"),
                                         incumbent.get("created_at"),
                                         incumbent.get("_seq", 0))


def _supersedes(prior, meeting):
    """A later ballot supersedes an earlier one only while the meeting can
    still take ballots; once the meeting is closed or recessed its ballots
    stand and a further attempt is a duplicate."""
    return meeting.get("meeting_status") in ("SCHEDULED", "PUBLIC_COMMENT_OPEN", "OPEN")


@bp.get("/editorial-votes")
@guard(READERS)
def list_votes(actor):
    rows = store.sorted_rows(store.editorial_votes)
    for field in ("change_id", "meeting_id", "society_id", "vote"):
        wanted = request.args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    return list_response(rows)


@bp.get("/editorial-votes/<vote_id>")
@guard(READERS)
def read_vote(actor, vote_id):
    return object_response(one(R.vote(vote_id)))