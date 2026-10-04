"""Advisor endpoints (§1.5; PRD §3.3, §3.8)."""

from flask import Blueprint, request

from db import db
from errors import err
from middleware import body, required, pagination, page
from response import ok, ok_list
from routes._shared import authed
from services import advisors, serialize

bp = Blueprint("advisors", __name__)
WRITE = ["ManagingDirector"]
READ = ["Any"]


@bp.post("/agency/advisors")
@authed(WRITE)
def create(user_id, role):
    data = body()
    required(data, "full_name")
    required(data, "email")
    required(data, "rank")
    row = advisors.create(data)
    return ok(serialize.advisor(row), 201)


@bp.get("/agency/advisors")
@authed(READ)
def list_advisors(user_id, role):
    limit, offset = pagination()
    filters = {
        "district_office_id": request.args.get("district_office_id"),
        "sponsoring_advisor_id": request.args.get("sponsoring_advisor_id"),
        "rank": request.args.get("rank"),
        "contract_status": request.args.get("contract_status"),
    }
    items = [a for a in db.advisors.values()
             if all(value is None or a.get(key) == value for key, value in filters.items())]
    selected = page(items, limit, offset)
    return ok_list([serialize.advisor(a) for a in selected], limit, offset, len(items))


@bp.get("/agency/advisors/<advisor_id>")
@authed(READ)
def get_advisor(user_id, role, advisor_id):
    return ok(serialize.advisor(advisors.get(advisor_id)))


@bp.post("/agency/advisors/<advisor_id>/terminate")
@authed(WRITE)
def terminate(user_id, role, advisor_id):
    row = advisors.get(advisor_id)
    advisors.terminate(row)
    return ok(serialize.advisor(row))


@bp.post("/agency/advisors/<advisor_id>/remediate")
@authed(["DistrictDirector", "ManagingDirector"])
def remediate(user_id, role, advisor_id):
    row = advisors.get(advisor_id)
    advisors.remediate(row)
    return ok(serialize.advisor(row))


@bp.post("/agency/advisors/<advisor_id>/licensing/lock-remediation")
@authed(WRITE)
def lock(user_id, role, advisor_id):
    row = advisors.get(advisor_id)
    advisors.set_licensing_locked(row, True)
    return ok(serialize.advisor(row))


@bp.post("/agency/advisors/<advisor_id>/licensing/unlock-remediation")
@authed(WRITE)
def unlock(user_id, role, advisor_id):
    row = advisors.get(advisor_id)
    advisors.set_licensing_locked(row, False)
    return ok(serialize.advisor(row))


@bp.get("/agency/advisors/<advisor_id>/downline")
@authed(READ)
def downline(user_id, role, advisor_id):
    advisors.get(advisor_id)
    limit, offset = pagination()
    contract_status = request.args.get("contract_status")
    items = [a for a in db.advisors.values()
             if a["sponsoring_advisor_id"] == advisor_id
             and (contract_status is None or a["contract_status"] == contract_status)]
    selected = page(items, limit, offset)
    return ok_list([serialize.advisor(a) for a in selected], limit, offset, len(items))


@bp.get("/agency/advisors/<advisor_id>/product-licenses")
@authed(READ)
def licenses(user_id, role, advisor_id):
    advisors.get(advisor_id)
    limit, offset = pagination()
    status = request.args.get("status")
    product_line = request.args.get("product_line")
    items = [l for l in db.licenses.values()
             if l["advisor_id"] == advisor_id
             and (status is None or l["status"] == status)
             and (product_line is None or l["product_line"] == product_line)]
    selected = page(items, limit, offset)
    return ok_list([serialize.license_(l) for l in selected], limit, offset, len(items))


@bp.get("/agency/advisors/<advisor_id>/securities-registrations")
@authed(READ)
def registrations(user_id, role, advisor_id):
    advisors.get(advisor_id)
    limit, offset = pagination()
    status = request.args.get("status")
    registration_type = request.args.get("registration_type")
    items = [r for r in db.registrations.values()
             if r["advisor_id"] == advisor_id
             and (status is None or r["status"] == status)
             and (registration_type is None or r["registration_type"] == registration_type)]
    selected = page(items, limit, offset)
    return ok_list([serialize.registration(r) for r in selected], limit, offset, len(items))


@bp.get("/agency/advisors/<advisor_id>/carrier-appointments")
@authed(READ)
def appointments(user_id, role, advisor_id):
    advisors.get(advisor_id)
    limit, offset = pagination()
    status = request.args.get("appointment_status")
    items = [a for a in db.appointments.values()
             if a["advisor_id"] == advisor_id
             and (status is None or a["appointment_status"] == status)]
    selected = page(items, limit, offset)
    return ok_list([serialize.appointment(a) for a in selected], limit, offset, len(items))


@bp.get("/agency/advisors/<advisor_id>/employment-contracts")
@authed(READ)
def contracts(user_id, role, advisor_id):
    advisors.get(advisor_id)
    limit, offset = pagination()
    items = [c for c in db.contracts.values() if c["advisor_id"] == advisor_id]
    selected = page(items, limit, offset)
    return ok_list([serialize.contract(c) for c in selected], limit, offset, len(items))


@bp.get("/agency/advisors/<advisor_id>/validation-periods")
@authed(READ)
def periods(user_id, role, advisor_id):
    advisors.get(advisor_id)
    limit, offset = pagination()
    status = request.args.get("status")
    items = [p for p in db.validation_periods.values()
             if p["advisor_id"] == advisor_id
             and (status is None or p["status"] == status)]
    selected = page(items, limit, offset)
    return ok_list([serialize.period(p) for p in selected], limit, offset, len(items))


@bp.get("/agency/advisors/<advisor_id>/persistency-records")
@authed(READ)
def persistency(user_id, role, advisor_id):
    advisors.get(advisor_id)
    limit, offset = pagination()
    status = request.args.get("status")
    measurement_period = request.args.get("measurement_period")
    items = [p for p in db.persistency.values()
             if p["advisor_id"] == advisor_id
             and (status is None or p["status"] == status)
             and (measurement_period is None or p["measurement_period"] == measurement_period)]
    selected = page(items, limit, offset)
    return ok_list([serialize.persistency(p) for p in selected], limit, offset, len(items))


@bp.get("/agency/advisors/<advisor_id>/commission-credits")
@authed(READ)
def credits(user_id, role, advisor_id):
    advisors.get(advisor_id)
    limit, offset = pagination()
    credit_type = request.args.get("credit_type")
    status = request.args.get("status")
    items = [c for c in db.credits.values()
             if c["advisor_id"] == advisor_id
             and (credit_type is None or c["credit_type"] == credit_type)
             and (status is None or c["status"] == status)]
    selected = page(items, limit, offset)
    return ok_list([serialize.credit(c) for c in selected], limit, offset, len(items))


@bp.get("/agency/advisors/<advisor_id>/joint-work-cases")
@authed(READ)
def joint_cases(user_id, role, advisor_id):
    advisors.get(advisor_id)
    limit, offset = pagination()
    status = request.args.get("status")
    items = [c for c in db.joint_cases.values()
             if advisor_id in (c["lead_advisor_id"], c["support_advisor_id"])
             and (status is None or c["status"] == status)]
    selected = page(items, limit, offset)
    return ok_list([serialize.joint(c) for c in selected], limit, offset, len(items))


@bp.get("/agency/advisors/<advisor_id>/orphan-policy-assignments")
@authed(READ)
def orphans(user_id, role, advisor_id):
    advisors.get(advisor_id)
    limit, offset = pagination()
    status = request.args.get("status")
    items = [o for o in db.orphans.values()
             if advisor_id in (o["from_advisor_id"], o["to_advisor_id"])
             and (status is None or o["status"] == status)]
    selected = page(items, limit, offset)
    return ok_list([serialize.orphan(o) for o in selected], limit, offset, len(items))