"""Editorial panel meetings, their docket, dimensions and weighted tallies."""

from datetime import timedelta

from flask import Blueprint, request

import auth
import parsers as P
import resolvers as R
import store
from clock import logical_now
from errors import (
    ERR_APPROVAL_PERCENT_TOO_LOW,
    ERR_CHANGE_NOT_READY_FOR_PANEL,
    ERR_COMMENT_PERIOD_TOO_SHORT,
    ERR_FREQUENT_FAMILY_EXEMPLAR_REQUIRED,
    ERR_INVALID_STATE,
    ERR_MEETING_NOT_OPEN,
    ERR_MEETING_SLOT_OCCUPIED,
    ERR_NO_QUORUM,
    ApiError,
)
from money import dec
from response import object_response
from routes.common import guard, list_response, one
from services import cycles as CY
from services import votes as VT

bp = Blueprint("meetings", __name__)

STAFF = (auth.EDITORIAL_STAFF,)
CHAIR = (auth.EDITORIAL_PANEL_CHAIR,)
READERS = (auth.EDITORIAL_STAFF, auth.EDITORIAL_PANEL_CHAIR, auth.COMMITTEE_REVIEWER)

MIN_SITTING_HOURS = 8
OPEN_STATUSES = ("SCHEDULED", "PUBLIC_COMMENT_OPEN")
# February, April, August, October and December admit only frequent-family
# exemplars, so a TIER_IV change may not be docketed there.
FREQUENT_FAMILY_MONTHS = ("FEBRUARY", "APRIL", "AUGUST", "OCTOBER", "DECEMBER")
OUTSIDE_CAST_LIMIT = dec("1")


@bp.post("/meetings")
@guard(STAFF)
def schedule_meeting(actor):
    data = P.body()
    code = P.text(data.get("meeting_code"))
    for existing in store.meetings.values():
        if existing.get("meeting_code") == code:
            raise ApiError(ERR_INVALID_STATE, "meeting_code must be unique across meetings")

    starts_at = P.dt(data.get("starts_at"))
    ends_at = P.dt(data.get("ends_at"))
    if starts_at is None or ends_at is None or ends_at < starts_at + timedelta(hours=MIN_SITTING_HOURS):
        raise ApiError(ERR_INVALID_STATE,
                       "the scheduled closing must be at least 8 hours after the opening")

    meeting = store.create(store.meetings, {
        "meeting_code": code,
        "meeting_month": P.text(data.get("meeting_month")),
        "meeting_status": "SCHEDULED",
        "agenda_status": "UNSET",
        "quorum_present": False,
        "citation_mode": P.boolean(data.get("citation_mode"), False),
        "starts_at": starts_at,
        "ends_at": ends_at,
        "public_comment_open_at": None,
        "public_comment_close_at": None,
        "weighted_yes": 0.0,
        "weighted_no": 0.0,
        "weighted_abstain": 0.0,
        "conducted_at": None,
    })
    return object_response(one(meeting), 201)


@bp.get("/meetings")
@guard(READERS)
def list_meetings(actor):
    rows = store.sorted_rows(store.meetings)
    for field in ("meeting_status", "meeting_month"):
        wanted = request.args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    return list_response(rows)


@bp.get("/meetings/<meeting_id>")
@guard(READERS)
def read_meeting(actor, meeting_id):
    meeting = R.meeting(meeting_id)
    VT.recompute_quorum(meeting)
    return object_response(one(meeting))


@bp.post("/meetings/<meeting_id>/agenda")
@guard(STAFF)
def set_agenda(actor, meeting_id):
    meeting = R.meeting(meeting_id)
    data = P.body()
    change_ids = P.id_list(data.get("change_ids"))
    if not change_ids:
        raise ApiError(ERR_INVALID_STATE, "the agenda must carry at least one change")

    # Guard 1: the meeting must admit docketing.
    if meeting.get("meeting_status") not in OPEN_STATUSES:
        raise ApiError(ERR_MEETING_NOT_OPEN, "meeting does not admit docketing")

    # Resolve every named change left to right before mutating anything.
    changes = [R.code_change(change_id) for change_id in change_ids]

    month = meeting.get("meeting_month")
    for change in changes:
        # Guard 2: the month's frequency allowance.
        if change.get("clinical_evidence_tier") == "TIER_IV" and month in FREQUENT_FAMILY_MONTHS:
            raise ApiError(ERR_FREQUENT_FAMILY_EXEMPLAR_REQUIRED,
                           "a TIER_IV change may not be docketed at a %s meeting" % month)
        # Guard 3: the docket slot.
        existing_slot = change.get("meeting_id")
        if existing_slot and existing_slot != meeting["id"]:
            raise ApiError(ERR_MEETING_SLOT_OCCUPIED,
                           "change already carries an open docket slot")
        if change.get("administrative_review_status") not in (
            "UNDER_ADMIN_REVIEW", "ADMIN_COMPLETE"
        ):
            raise ApiError(ERR_INVALID_STATE,
                           "administrative screening does not admit docketing")

    for change in changes:
        if change.get("review_status") != "AGENDA_SET":
            change["review_status"] = "AGENDA_SET"
        change["meeting_id"] = meeting["id"]
        store.bump(change)

    meeting["agenda_status"] = "SET"
    VT.recompute_quorum(meeting)
    store.bump(meeting)
    return object_response(one(meeting), 200)


@bp.post("/meetings/<meeting_id>/comment-windows")
@guard(STAFF)
def open_comment_window(actor, meeting_id):
    meeting = R.meeting(meeting_id)
    data = P.body()
    open_at = P.dt(data.get("public_comment_open_at"))
    close_at = P.dt(data.get("public_comment_close_at"))

    if meeting.get("meeting_status") != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "the comment window has already been opened")
    if not CY.window_acceptable(open_at, close_at):
        raise ApiError(ERR_COMMENT_PERIOD_TOO_SHORT,
                       "the meeting comment window must span at least 30 whole days")

    meeting["public_comment_open_at"] = open_at
    meeting["public_comment_close_at"] = close_at
    meeting["meeting_status"] = "PUBLIC_COMMENT_OPEN"
    for change in _docketed_in_status(meeting["id"], "ADMIN_REVIEW"):
        change["posting_state"] = "COMMENT_OPEN"
        store.bump(change)
    store.bump(meeting)
    return object_response(one(meeting), 200)


@bp.post("/meetings/<meeting_id>/comment-closures")
@guard(STAFF)
def close_comment_window(actor, meeting_id):
    meeting = R.meeting(meeting_id)
    if meeting.get("meeting_status") != "PUBLIC_COMMENT_OPEN":
        raise ApiError(ERR_INVALID_STATE, "the meeting comment window is not open")
    close_at = meeting.get("public_comment_close_at")
    if close_at is None or logical_now() < close_at:
        raise ApiError(ERR_INVALID_STATE,
                       "the logical clock has not reached the comment close instant")

    meeting["meeting_status"] = "OPEN"
    for change in _docketed_in_status(meeting["id"], "ADMIN_REVIEW"):
        change["posting_state"] = "POSTED"
        store.bump(change)
    VT.recompute_quorum(meeting)
    store.bump(meeting)
    return object_response(one(meeting), 200)


@bp.post("/meetings/<meeting_id>/comment-window-reversals")
@guard(STAFF)
def reverse_comment_window(actor, meeting_id):
    meeting = R.meeting(meeting_id)
    if meeting.get("meeting_status") != "PUBLIC_COMMENT_OPEN":
        raise ApiError(ERR_INVALID_STATE, "the meeting comment window is not open")
    docketed = {c.get("id") for c in store.code_changes.values()
                if c.get("meeting_id") == meeting["id"]}
    for comment in store.public_comments.values():
        if comment.get("change_id") in docketed:
            raise ApiError(ERR_INVALID_STATE,
                           "a comment has been filed, so the window cannot be reversed")

    meeting["meeting_status"] = "SCHEDULED"
    meeting["public_comment_open_at"] = None
    meeting["public_comment_close_at"] = None
    store.bump(meeting)
    return object_response(one(meeting), 200)


@bp.post("/meetings/<meeting_id>/openings")
@guard(CHAIR)
def open_meeting(actor, meeting_id):
    meeting = R.meeting(meeting_id)
    if meeting.get("agenda_status") != "SET":
        raise ApiError(ERR_INVALID_STATE, "the agenda is not set")
    if meeting.get("meeting_status") not in OPEN_STATUSES:
        raise ApiError(ERR_INVALID_STATE, "the meeting cannot be opened from its current state")

    advancing = [c for c in store.code_changes.values()
                 if c.get("meeting_id") == meeting["id"] and c.get("review_status") == "AGENDA_SET"]
    advancing.sort(key=lambda c: (c.get("created_at"), c.get("_seq", 0)))

    for change in advancing:
        # The interested-party conflict is evaluated before the state check.
        if _commenter_counts_toward_quorum(meeting, change):
            raise ApiError(ERR_CHANGE_NOT_READY_FOR_PANEL,
                           "a public comment on this change names a party counting toward quorum")
        if change.get("administrative_review_status") not in (
            "UNDER_ADMIN_REVIEW", "ADMIN_COMPLETE"
        ):
            raise ApiError(ERR_INVALID_STATE,
                           "administrative screening does not admit panel review")

    meeting["meeting_status"] = "OPEN"
    for change in advancing:
        change["review_status"] = "PANEL_REVIEW"
        store.bump(change)
    VT.recompute_quorum(meeting)
    store.bump(meeting)
    return object_response(one(meeting), 200)


@bp.post("/meetings/<meeting_id>/recesses")
@guard(CHAIR)
def recess_meeting(actor, meeting_id):
    meeting = R.meeting(meeting_id)
    if meeting.get("meeting_status") != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "only an open meeting may be recessed")
    if meeting.get("agenda_status") != "SET":
        raise ApiError(ERR_INVALID_STATE, "the agenda is not set")

    meeting["meeting_status"] = "RECESSED"
    # conducted_at is deliberately left empty by a recess.
    VT.panel_weighted_vote_tally(meeting)
    VT.recompute_quorum(meeting)
    store.bump(meeting)
    return object_response(one(meeting), 200)


@bp.post("/meetings/<meeting_id>/reopenings")
@guard(CHAIR)
def reopen_meeting(actor, meeting_id):
    meeting = R.meeting(meeting_id)
    if meeting.get("meeting_status") != "RECESSED":
        raise ApiError(ERR_INVALID_STATE, "only a recessed meeting may be reopened")
    if meeting.get("agenda_status") != "ADDENDUM_OPEN":
        raise ApiError(ERR_INVALID_STATE, "the addendum agenda is not open")

    meeting["meeting_status"] = "OPEN"
    VT.recompute_quorum(meeting)
    store.bump(meeting)
    return object_response(one(meeting), 200)


@bp.post("/meetings/<meeting_id>/addenda")
@guard(STAFF)
def open_addendum(actor, meeting_id):
    meeting = R.meeting(meeting_id)
    data = P.body()
    if meeting.get("meeting_status") not in ("OPEN", "RECESSED"):
        raise ApiError(ERR_INVALID_STATE, "the meeting is not convened")
    cycle = CY.cycle_for_meeting(meeting["id"])
    deadline = CY.addendum_deadline_for_cycle(cycle)
    if deadline is None or logical_now() > deadline:
        raise ApiError(ERR_INVALID_STATE,
                       "the addendum close of the cycle naming this meeting has passed")

    meeting["agenda_status"] = "ADDENDUM_OPEN"
    meeting["addendum_note"] = P.text_or_none(data.get("addendum_note"))
    VT.recompute_quorum(meeting)
    store.bump(meeting)
    return object_response(one(meeting), 200)


@bp.post("/meetings/<meeting_id>/addendum-closures")
@guard(STAFF)
def close_addendum(actor, meeting_id):
    meeting = R.meeting(meeting_id)
    if meeting.get("meeting_status") not in ("OPEN", "RECESSED"):
        raise ApiError(ERR_INVALID_STATE, "the meeting is not convened")
    if meeting.get("agenda_status") != "ADDENDUM_OPEN":
        raise ApiError(ERR_INVALID_STATE, "the addendum agenda is not open")

    meeting["agenda_status"] = "SET"
    store.bump(meeting)
    return object_response(one(meeting), 200)


@bp.post("/meetings/<meeting_id>/closures")
@guard(CHAIR)
def close_meeting(actor, meeting_id):
    meeting = R.meeting(meeting_id)
    status = meeting.get("meeting_status")

    if status == "OPEN":
        # The outside-cast limit guards closing the meeting as well.
        share = VT.outside_cast_share(meeting)
        if share is not None and dec(share) > OUTSIDE_CAST_LIMIT:
            raise ApiError(ERR_APPROVAL_PERCENT_TOO_LOW,
                           "more than one percent of the weighted yes vote was cast from outside "
                           "the seated societies")
        VT.recompute_quorum(meeting)
        if not bool(meeting.get("quorum_present")):
            raise ApiError(ERR_NO_QUORUM, "the meeting has no quorum")
        determined = any(
            c.get("meeting_id") == meeting["id"] and c.get("review_status") == "DETERMINED"
            for c in store.code_changes.values()
        )
        if not determined:
            raise ApiError(ERR_INVALID_STATE,
                           "no docketed change has reached a determination")
    elif status == "RECESSED":
        if meeting.get("agenda_status") != "SET":
            raise ApiError(ERR_INVALID_STATE, "the agenda is not set")
    else:
        raise ApiError(ERR_INVALID_STATE, "the meeting cannot be closed from its current state")

    meeting["conducted_at"] = logical_now()
    meeting["meeting_status"] = "CLOSED"
    VT.panel_weighted_vote_tally(meeting)
    VT.recompute_quorum(meeting)
    store.bump(meeting)
    return object_response(one(meeting), 200)


@bp.get("/meetings/<meeting_id>/votes")
@guard((auth.EDITORIAL_STAFF, auth.EDITORIAL_PANEL_CHAIR))
def list_meeting_votes(actor, meeting_id):
    meeting = R.meeting(meeting_id)
    rows = [v for v in store.sorted_rows(store.editorial_votes)
            if v.get("meeting_id") == meeting["id"]]
    return list_response(rows)


# --- helpers ---------------------------------------------------------------

def _docketed_in_status(meeting_id, review_status):
    rows = [c for c in store.code_changes.values()
            if c.get("meeting_id") == meeting_id and c.get("review_status") == review_status]
    rows.sort(key=lambda c: (c.get("created_at"), c.get("_seq", 0)))
    return rows


def _commenter_counts_toward_quorum(meeting, change):
    """A public comment on the change names an interested party that is also
    one of the seats counting toward the meeting's quorum."""
    seated = VT.meeting_society_seats(meeting["id"])
    if not seated:
        return False
    for comment in store.public_comments.values():
        if comment.get("change_id") != change["id"]:
            continue
        if comment.get("withdrawn_at") is not None:
            continue
        commenter = store.applicants.get(comment.get("commenter_id"))
        if commenter is None:
            continue
        if commenter.get("society_id") in seated:
            return True
    return False