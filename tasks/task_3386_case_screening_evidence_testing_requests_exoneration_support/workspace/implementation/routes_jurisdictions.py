"""Jurisdiction registry endpoints."""

from flask import Blueprint

import db
from auth import STAFF_ROLES, require_roles
from envelope import ok
from errors import (
    ERR_DUPLICATE_STATE_CODE,
    ERR_INVALID_REQUEST,
    ERR_JURISDICTION_NOT_FOUND,
    raise_err,
)
from validation import (
    body_json,
    opt_int,
    opt_nullable_int,
    paged_list,
    reject_unknown,
    req_bool,
    req_str,
)

bp = Blueprint("jurisdictions", __name__)

_FIELDS = (
    "state_code",
    "name",
    "has_post_conviction_dna_statute",
    "post_conviction_deadline_years",
    "clemency_available",
    "compensation_statute_exists",
    "compensation_cap_cents",
    "actual_innocence_enhancement_pct",
)


@bp.post("/jurisdictions")
def create_jurisdiction():
    require_roles("PlatformAdmin")
    body = body_json()
    reject_unknown(body, set(_FIELDS))
    state_code = req_str(body, "state_code")
    name = req_str(body, "name")
    dna_statute = req_bool(body, "has_post_conviction_dna_statute")
    clemency_available = req_bool(body, "clemency_available")
    compensation_statute_exists = req_bool(body, "compensation_statute_exists")
    deadline_years = opt_nullable_int(body, "post_conviction_deadline_years", minimum=1)
    cap_cents = opt_nullable_int(body, "compensation_cap_cents", minimum=0)
    enhancement_pct = opt_int(body, "actual_innocence_enhancement_pct", minimum=0, maximum=100)
    if enhancement_pct is None:
        enhancement_pct = 0
    if not (len(state_code) == 2 and state_code.isalpha() and state_code.isupper()):
        raise_err(ERR_INVALID_REQUEST,
                  "Field 'state_code' must be a two-letter uppercase code")
    # priority 8(g): duplicate state_code
    if any(j["state_code"] == state_code for j in db.jurisdictions.values()):
        raise_err(ERR_DUPLICATE_STATE_CODE,
                  "A jurisdiction with state_code %s already exists" % state_code)
    jur = db.new_entity()
    jur.update({
        "state_code": state_code,
        "name": name,
        "has_post_conviction_dna_statute": dna_statute,
        "post_conviction_deadline_years": deadline_years,
        "clemency_available": clemency_available,
        "compensation_statute_exists": compensation_statute_exists,
        "compensation_cap_cents": cap_cents,
        "actual_innocence_enhancement_pct": enhancement_pct,
    })
    db.jurisdictions[jur["id"]] = jur
    return ok(jur, 201)


@bp.get("/jurisdictions/<jid>")
def get_jurisdiction(jid):
    require_roles(*STAFF_ROLES, "Client")
    jur = db.lookup(db.jurisdictions, jid, ERR_JURISDICTION_NOT_FOUND)
    return ok(jur)


@bp.get("/jurisdictions/<jid>/policy-initiatives")
def list_jurisdiction_policy_initiatives(jid):
    require_roles(*STAFF_ROLES)
    db.lookup(db.jurisdictions, jid, ERR_JURISDICTION_NOT_FOUND)
    items = [p for p in db.policy_initiatives.values() if p["jurisdiction_id"] == jid]
    return paged_list(items, {})
