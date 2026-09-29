"""Related-account links and their adjudication (PRD 3.1)."""

from flask import Blueprint, request

import constants as C
import db
import guards
import middleware as mw
import response
import serializers as ser
import validators as v
from errors import ApiError
from services import notify, posture

bp = Blueprint("links", __name__)


@bp.get("/related-account-links")
@mw.require(C.ROLE_INVESTIGATOR, C.ROLE_OFFICER)
def list_links():
    limit, offset = v.pagination()
    rows = db.sorted_rows(db.RELATED_ACCOUNT_LINKS)
    for field in ("candidate_seller_id", "matched_seller_id", "state"):
        if field in request.args:
            wanted = request.args.get(field)
            rows = [r for r in rows if r.get(field) == wanted]
    page, total = response.paginate(rows, limit, offset)
    return response.many(page, ser.link, limit, offset, total)


@bp.get("/related-account-links/<link_id>")
@mw.require(C.ROLE_INVESTIGATOR, C.ROLE_OFFICER)
def read_link(link_id):
    return response.one(guards.link(link_id), ser.link, 200)


@bp.post("/related-account-links/<link_id>/adjudicate")
@mw.require(C.ROLE_OFFICER)
def adjudicate(link_id):
    link = guards.link(link_id)
    mw.ensure_distinct(link["candidate_seller_id"])

    data = v.body()
    decision = v.req_enum(data, "decision", C.LINK_DECISIONS)
    note = v.opt_str(data, "adjudication_note")

    candidate = db.SELLERS[link["candidate_seller_id"]]
    guards.ensure_not_banned(candidate)

    if link["state"] != "DETECTED":
        raise ApiError("ERR_INVALID_STATE")
    if (decision == "CONFIRMED"
            and link["matched_seller_state_at_detection"] != "BANNED"):
        raise ApiError("ERR_LINK_MATCH_NOT_BANNED")

    db.set_field(link, "state", decision)
    db.set_field(link, "adjudicated_by_user_id", mw.actor())
    db.set_field(link, "adjudication_note", note)

    if decision == "CONFIRMED":
        db.set_field(candidate, "ban_reason", "RELATED_ACCOUNT_CONFIRMED")
        notify.emit(candidate["id"], "ACCOUNT_BANNED", "RELATED_ACCOUNT_LINK",
                    link["id"], decision_rationale=note)
        posture.recompute(candidate)
    else:
        surviving = [
            row for row in db.links_for_candidate(candidate["id"])
            if row["state"] in ("DETECTED", "CONFIRMED")
        ]
        if not surviving:
            db.set_field(candidate, "registration_risk_flag", False)
        posture.recompute(candidate)
    db.mark_dirty(candidate)
    return response.one(link, ser.link, 200)
