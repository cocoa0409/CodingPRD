"""Account routes (PRD §4, §3.14)."""

from flask import Blueprint

import middleware as mw
from response import ok, created
from services import accounts as svc
from db import STORE, ordered, paginate

bp = Blueprint("accounts", __name__)


def register(app):
    app.register_blueprint(bp)


@bp.get("/car-share/accounts")
def list_accounts():
    mw.authenticate(("UniversityAccountAdmin", "FleetAdmin", "Anonymous"))
    limit, offset = mw.pagination()
    rows, meta = svc.list_accounts(mw.query("type"), mw.query("primary_member_id"),
                                   limit, offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.post("/car-share/accounts")
def create_account():
    mw.authenticate(("Anonymous", "UniversityAccountAdmin"))
    data = mw.body()
    account = svc.create(data, mw)
    return created(svc.serialize(account))


@bp.get("/car-share/accounts/<account_id>")
def get_account(account_id):
    mw.authenticate(("UniversityAccountAdmin", "FleetAdmin", "Anonymous"))
    account = svc.get(account_id)
    return ok(svc.serialize(account))


@bp.get("/car-share/accounts/<account_id>/memberships")
def account_memberships(account_id):
    mw.authenticate(("UniversityAccountAdmin", "FleetAdmin"))
    limit, offset = mw.pagination()
    rows, meta = svc.account_memberships(account_id, limit, offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.get("/car-share/accounts/<account_id>/members")
def account_members(account_id):
    mw.authenticate(("UniversityAccountAdmin", "FleetAdmin"))
    rows = svc.account_members(account_id)
    return ok([svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})


@bp.get("/car-share/tier-restore-entitlements")
def list_entitlements():
    mw.authenticate(("PodOperator", "UniversityAccountAdmin"))
    from services import memberships as m_svc
    limit, offset = mw.pagination()
    rows, meta = m_svc.list_entitlements(mw.query("membership_id"),
                                         mw.query("restore_status"), limit, offset)
    return ok([m_svc.serialize(r) for r in rows], response_type="array", pagination=meta)