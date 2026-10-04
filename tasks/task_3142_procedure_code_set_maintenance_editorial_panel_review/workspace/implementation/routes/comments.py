"""Public comments on posted changes."""

from flask import Blueprint, request

import auth
import parsers as P
import resolvers as R
import store
from clock import logical_now
from errors import ERR_INVALID_STATE, ERR_UNAUTHORIZED, ApiError
from response import object_response
from routes.common import guard, list_response, one

bp = Blueprint("comments", __name__)

FILERS = (auth.CHANGE_APPLICANT, auth.LICENSEE)
READERS = (auth.EDITORIAL_STAFF, auth.EDITORIAL_PANEL_CHAIR)
COMMENTER_TYPES = (
    "SPECIALTY_SOCIETY", "PAYER", "MANUFACTURER", "HIT_VENDOR", "INDIVIDUAL",
)


@bp.post("/public-comments")
@guard(FILERS)
def file_comment(actor):
    data = P.body()
    change = R.code_change(P.text_or_none(data.get("change_id")) or "")
    commenter = R.applicant(P.text_or_none(data.get("commenter_id")) or "")

    comment = store.create(store.public_comments, {
        "change_id": change["id"],
        "commenter_id": commenter["id"],
        "commenter_type": P.text(data.get("commenter_type")),
        "citation_submitted": P.boolean(data.get("citation_submitted"), False),
        "body": P.text(data.get("body")),
        "posted_at": logical_now(),
        "withdrawn_at": None,
    })
    return object_response(one(comment), 201)


@bp.get("/public-comments")
@guard(READERS)
def list_comments(actor):
    rows = store.sorted_rows(store.public_comments)
    args = request.args
    for field in ("change_id", "commenter_id"):
        wanted = args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    citation = args.get("citation_submitted")
    if citation not in (None, ""):
        wanted = P.boolean(citation)
        rows = [r for r in rows if bool(r.get("citation_submitted")) == wanted]
    return list_response(rows)


@bp.get("/public-comments/<comment_id>")
@guard(READERS)
def read_comment(actor, comment_id):
    return object_response(one(R.public_comment(comment_id)))


@bp.post("/public-comments/<comment_id>/withdrawals")
@guard((auth.CHANGE_APPLICANT,))
def withdraw_comment(actor, comment_id):
    comment = R.public_comment(comment_id)
    if comment.get("commenter_id") != actor.user_id:
        raise ApiError(ERR_UNAUTHORIZED, "only the filing applicant may withdraw the comment")
    if comment.get("withdrawn_at") is not None:
        raise ApiError(ERR_INVALID_STATE, "the comment has already been withdrawn")

    # Withdrawal requires a reason and stamps withdrawn_at rather than deleting.
    reason = P.body().get("reason")
    if reason in (None, ""):
        raise ApiError(ERR_INVALID_STATE, "a withdrawal must supply a reason")
    comment["withdrawal_reason"] = P.text(reason)
    comment["withdrawn_at"] = logical_now()
    store.bump(comment)
    return object_response(one(comment), 200)