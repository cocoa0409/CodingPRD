"""Members (PRD 3.2): registration and read with computed standing.

expires_on = join date (logical date at creation) + membership_term_months
calendar months. member_status is derived from the logical clock on every
read and every member-linked purchase: ACTIVE through expires_on inclusive,
LAPSED from the day after.
"""

from flask import Blueprint

import db
import serializers
import util
from envelope import success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("members", __name__)

MEMBER_READ_ROLES = ["PlatformAdmin", "VisitorServices", "ExhibitionManager", "Member"]


@bp.post("/campus/members")
def create_member():
    _uid, role = auth()
    require_role(role, ["Public", "VisitorServices"])
    b = util.body()
    full_name = util.req_str(b, "full_name")
    email = util.req_str(b, "email")
    term = util.req_int(b, "membership_term_months", minimum=1)
    for m in db.STORE["members"].values():
        if m["email"] == email:
            fail("ERR_INVALID_REQUEST", "email must be unique")
    expires_on = util.add_months(db.today(), term)
    m = db.new_entity(
        {
            "full_name": full_name,
            "email": email,
            "membership_term_months": term,
            "expires_on": expires_on.isoformat(),
        }
    )
    db.STORE["members"][m["id"]] = m
    return success(serializers.member(m), 201)


@bp.get("/campus/members/<mid>")
def get_member(mid):
    uid, role = auth()
    require_role(role, MEMBER_READ_ROLES)
    m = get_or_404("members", mid, "Member")
    # Member identity is entity-backed: a Member caller reads only themself.
    if role == "Member" and m["id"] != uid:
        fail("ERR_UNAUTHORIZED_ROLE", "Member callers may read only their own record")
    return success(serializers.member(m))
