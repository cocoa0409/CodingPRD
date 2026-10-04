"""Membership routes (PRD §4, §3.3, §3.4)."""

from flask import Blueprint

import middleware as mw
from response import ok, created
from services import memberships as svc

bp = Blueprint("memberships", __name__)


def register(app):
    app.register_blueprint(bp)


@bp.get("/car-share/memberships")
def list_memberships():
    mw.authenticate(("UniversityAccountAdmin", "FleetAdmin"))
    limit, offset = mw.pagination()
    rows, meta = svc.list_memberships(mw.query("member_id"), mw.query("account_id"),
                                      mw.query("status"), limit, offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.post("/car-share/memberships")
def create_membership():
    mw.authenticate(("UniversityAccountAdmin",))
    data = mw.body()
    row = svc.create(data, mw)
    return created(svc.serialize(row))


@bp.get("/car-share/memberships/<membership_id>")
def get_membership(membership_id):
    identity, role = mw.authenticate(("Member", "PodOperator", "UniversityAccountAdmin",
                                      "FleetAdmin"))
    row = svc.get(membership_id)
    mw.require_owner(identity, role, row["member_id"])
    return ok(svc.serialize(row))


@bp.get("/car-share/memberships/<membership_id>/tier-restore-entitlements")
def membership_entitlements(membership_id):
    identity, role = mw.authenticate(("Member", "PodOperator", "UniversityAccountAdmin"))
    row = svc.get(membership_id)
    mw.require_owner(identity, role, row["member_id"])
    limit, offset = mw.pagination()
    rows, meta = svc.list_entitlements(membership_id=membership_id, limit=limit, offset=offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.post("/car-share/memberships/<membership_id>/tier-restore-entitlements")
def create_entitlement(membership_id):
    mw.authenticate(("UniversityAccountAdmin", "PodOperator"))
    data = mw.body()
    row = svc.create_entitlement(membership_id, data, mw)
    return created(svc.serialize(row))


@bp.post("/car-share/memberships/<membership_id>/suspend")
def suspend(membership_id):
    mw.authenticate(("PodOperator",))
    row = svc.suspend(membership_id)
    return ok(svc.serialize(row))


@bp.post("/car-share/memberships/<membership_id>/reinstate")
def reinstate(membership_id):
    mw.authenticate(("PodOperator",))
    row = svc.reinstate(membership_id)
    return ok(svc.serialize(row))


@bp.post("/car-share/memberships/<membership_id>/thaw")
def thaw(membership_id):
    mw.authenticate(("PodOperator",))
    row = svc.thaw(membership_id)
    return ok(svc.serialize(row))


@bp.post("/car-share/memberships/<membership_id>/close")
def close(membership_id):
    identity, role = mw.authenticate(("UniversityAccountAdmin",))
    row = svc.get(membership_id)
    mw.require_account_owner(identity, role, row["account_id"])
    row = svc.close(membership_id)
    return ok(svc.serialize(row))