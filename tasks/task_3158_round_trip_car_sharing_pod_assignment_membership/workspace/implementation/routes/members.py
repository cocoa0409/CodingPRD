"""Member lifecycle routes (PRD §4)."""

from flask import Blueprint, request

import middleware as mw
from response import ok, created
from services import members as svc

bp = Blueprint("members", __name__)


def register(app):
    app.register_blueprint(bp)


@bp.post("/car-share/member-registrations")
def register_member():
    mw.authenticate(("Anonymous", "Member", "PodOperator", "UniversityAccountAdmin",
                     "FleetAdmin", "PlatformAdmin"))
    data = mw.body()
    member = svc.register(data, mw)
    return created(svc.serialize(member))


@bp.get("/car-share/members")
def list_members():
    mw.authenticate(("PodOperator", "UniversityAccountAdmin", "FleetAdmin"))
    limit, offset = mw.pagination()
    rows, meta = svc.list_members(mw.query("application_status"), mw.query("kind"),
                                  limit, offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.get("/car-share/members/<member_id>")
def get_member(member_id):
    identity, role = mw.authenticate(("Member", "PodOperator", "UniversityAccountAdmin",
                                      "FleetAdmin"))
    member = svc.get(member_id)
    mw.require_owner(identity, role, member["id"])
    return ok(svc.serialize(member))


@bp.post("/car-share/members/<member_id>/driving-record-reports")
def submit_report(member_id):
    identity, role = mw.authenticate(("Member",))
    data = mw.body()
    report = svc.submit_driving_record(member_id, data, mw, identity, role)
    return created(svc._public(report) if hasattr(svc, "_public") else
                   {k: v for k, v in report.items() if not k.startswith("_")})


@bp.post("/car-share/driving-record-reports/<report_id>/decision")
def record_decision(report_id):
    mw.authenticate(("PodOperator",))
    data = mw.body()
    report = svc.record_report_decision(report_id, data, mw)
    return ok({k: v for k, v in report.items() if not k.startswith("_")})


@bp.post("/car-share/members/<member_id>/application-decision")
def application_decision(member_id):
    mw.authenticate(("PodOperator",))
    data = mw.body()
    member = svc.application_decision(member_id, data, mw)
    return ok(svc.serialize(member))


@bp.post("/car-share/members/<member_id>/reopen-application")
def reopen_application(member_id):
    mw.authenticate(("PodOperator",))
    member = svc.reopen_application(member_id)
    return ok(svc.serialize(member))


@bp.post("/car-share/members/<member_id>/wallet-adjustments")
def wallet_adjustment(member_id):
    mw.authenticate(("PodOperator",))
    data = mw.body()
    member = svc.wallet_adjustment(member_id, data, mw)
    return ok(svc.serialize(member))


@bp.get("/car-share/members/<member_id>/memberships")
def member_memberships(member_id):
    identity, role = mw.authenticate(("Member", "PodOperator", "UniversityAccountAdmin",
                                      "FleetAdmin"))
    from services import memberships as m_svc
    from services import lookup
    lookup.member(member_id)
    mw.require_owner(identity, role, member_id)
    limit, offset = mw.pagination()
    rows, meta = m_svc.list_memberships(member_id=member_id, limit=limit, offset=offset)
    return ok([m_svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.get("/car-share/members/<member_id>/driving-record-reports")
def member_reports(member_id):
    identity, role = mw.authenticate(("Member", "PodOperator", "FleetAdmin"))
    from services import lookup
    from db import ordered
    from db import STORE
    lookup.member(member_id)
    mw.require_owner(identity, role, member_id)
    rows = ordered([r for r in STORE.driving_reports.values() if r.get("member_id") == member_id])
    return ok([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
              response_type="array", pagination={"limit": 10, "offset": 0,
                                                 "total_count": len(rows), "has_more": False})


@bp.get("/car-share/members/<member_id>/access-events")
def member_access_events(member_id):
    identity, role = mw.authenticate(("Member", "PodOperator"))
    from services import access as a_svc
    mw.require_owner(identity, role, member_id)
    rows = a_svc.access_events_for_member(member_id)
    return ok([a_svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})


@bp.get("/car-share/members/<member_id>/community-signals")
def member_signals(member_id):
    identity, role = mw.authenticate(("Member", "PodOperator", "FleetAdmin"))
    from services import fuel as f_svc
    mw.require_owner(identity, role, member_id)
    rows = f_svc.signals_for_member(member_id)
    return ok([f_svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})


@bp.get("/car-share/members/<member_id>/incidents")
def member_incidents(member_id):
    identity, role = mw.authenticate(("Member", "PodOperator", "FleetAdmin"))
    from services import incidents as i_svc
    mw.require_owner(identity, role, member_id)
    rows = i_svc.incidents_for_member(member_id)
    return ok([i_svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})


@bp.get("/car-share/members/<member_id>/tier-restore-entitlements")
def member_entitlements(member_id):
    identity, role = mw.authenticate(("Member", "PodOperator", "UniversityAccountAdmin"))
    from services import memberships as m_svc
    from services import lookup
    lookup.member(member_id)
    mw.require_owner(identity, role, member_id)
    rows = m_svc.entitlements_for_member(member_id)
    return ok([m_svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})