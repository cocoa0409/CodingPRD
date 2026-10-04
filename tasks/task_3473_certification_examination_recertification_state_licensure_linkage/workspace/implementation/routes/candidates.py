"""Candidates (PRD §3.2): header-exempt self-registration + live hold flag."""

from flask import Blueprint

from db import STORE, base_entity, disciplinary_hold, serialize
from envelope import ok_object
from errors import raise_err
from middleware import ALL_AUTHENTICATED_ROLES, authn, body, req_str

bp = Blueprint("candidates", __name__)


def candidate_json(c):
    out = serialize(c)
    out["disciplinary_hold"] = disciplinary_hold(c["id"])
    return out


@bp.post("/registry/candidates")
def register_candidate():
    # The single header-exempt endpoint (Anonymous role).
    b = body()
    full_name = req_str(b, "full_name")
    email = req_str(b, "email")
    e = base_entity()
    e.update({
        "full_name": full_name,
        "email": email,
        "status": "REGISTERED",
    })
    STORE.candidates[e["id"]] = e
    return ok_object(candidate_json(e), 201)


@bp.get("/registry/candidates/<cid>")
def get_candidate(cid):
    authn(ALL_AUTHENTICATED_ROLES)
    c = STORE.candidates.get(cid)
    if not c:
        raise_err("ERR_NOT_FOUND", "Candidate %s does not exist" % cid)
    return ok_object(candidate_json(c), 200)
