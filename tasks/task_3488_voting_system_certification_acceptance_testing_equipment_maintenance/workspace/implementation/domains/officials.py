"""ElectionOfficial endpoints (PRD 3.1) plus the two per-official reads.

badge_no is unique within the official's jurisdiction (ERR_DUPLICATE_BADGE).
Officials are ACTIVE on creation; PlatformAdmin toggles ACTIVE <-> INACTIVE.
"""
from flask import Blueprint

from auth import auth_context, peek_to_state, require_role, require_transition_actor
from envelope import apply_filters, list_page, ok_object
from errors import err_invalid_state, err_not_found, raise_err
from store import db
from util import stamp_new, touch
from validation import body_json, no_extra, req_enum, req_str

bp = Blueprint("officials", __name__)

OFFICIAL_STATES = {"ACTIVE", "INACTIVE"}
OFFICIAL_ACTORS = {"ACTIVE": {"PlatformAdmin"}, "INACTIVE": {"PlatformAdmin"}}


@bp.post("/evote/jurisdictions/<jurisdiction_id>/officials")
def create_official(jurisdiction_id):
    _, role = auth_context()
    require_role(role, {"PlatformAdmin"})
    jurisdiction = db.jurisdictions.get(jurisdiction_id)
    if jurisdiction is None:
        err_not_found("jurisdiction not found")
    body = body_json()
    no_extra(body, {"full_name", "badge_no"})
    full_name = req_str(body, "full_name")
    badge_no = req_str(body, "badge_no")
    for official in db.election_officials.values():
        if official["jurisdiction_id"] == jurisdiction_id and official["badge_no"] == badge_no:
            raise_err("ERR_DUPLICATE_BADGE", 409, "badge_no already used within this jurisdiction")
    rec = stamp_new({})
    rec.update({
        "jurisdiction_id": jurisdiction_id,
        "full_name": full_name,
        "badge_no": badge_no,
        "status": "ACTIVE",
    })
    db.election_officials[rec["id"]] = rec
    return ok_object(rec, 201)


def get_official_or_404(official_id):
    official = db.election_officials.get(official_id)
    if official is None:
        err_not_found("election official not found")
    return official


@bp.get("/evote/officials")
def list_officials():
    auth_context()
    items = apply_filters(list(db.election_officials.values()), {"jurisdiction_id", "status"})
    return list_page(items)


@bp.get("/evote/officials/<official_id>")
def get_official(official_id):
    auth_context()
    return ok_object(get_official_or_404(official_id), 200)


@bp.post("/evote/officials/<official_id>/transitions")
def official_transition(official_id):
    _, role = auth_context()
    require_role(role, {"PlatformAdmin"})
    ts = peek_to_state()
    require_transition_actor(role, ts, OFFICIAL_ACTORS)
    official = get_official_or_404(official_id)
    body = body_json()
    no_extra(body, {"to_state"})
    to_state = req_enum(body, "to_state", OFFICIAL_STATES)
    legal = {"ACTIVE": {"INACTIVE"}, "INACTIVE": {"ACTIVE"}}
    if official["status"] not in legal[to_state]:
        err_invalid_state("official cannot transition from %s to %s" % (official["status"], to_state))
    official["status"] = to_state
    touch(official)
    return ok_object(official, 200)


@bp.get("/evote/officials/<official_id>/la-tests")
def official_la_tests(official_id):
    auth_context()
    get_official_or_404(official_id)
    items = [
        t for t in db.logic_accuracy_tests.values()
        if t["conducted_by"] == official_id or t["certified_by"] == official_id
    ]
    items = apply_filters(items, {"status", "result"})
    return list_page(items)


@bp.get("/evote/officials/<official_id>/custody-transfers")
def official_custody_transfers(official_id):
    auth_context()
    get_official_or_404(official_id)
    items = [
        t for t in db.custody_transfers.values()
        if t["from_official_id"] == official_id or t["to_official_id"] == official_id
    ]
    return list_page(items)
