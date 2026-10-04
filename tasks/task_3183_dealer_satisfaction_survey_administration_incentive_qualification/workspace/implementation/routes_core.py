"""Routes: clock, regions, dealers, departments, advisors, customers."""

from flask import Blueprint, request

import clock
import db
import errors
import helpers
import services
from middleware import require_roles
from response import (
    parse_pagination,
    success_list,
    success_object,
)

bp = Blueprint("core", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def _require(data, *fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise errors.invalid_request(f"Missing required field: {f}")
    return data


def _sorted(records):
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))


# ------------------------------------------------------------------- clock


@bp.post("/survey/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock(user_id, role):
    data = _require(_body(), "current_utc")
    try:
        dt = clock.parse_iso(data["current_utc"])
    except (ValueError, TypeError):
        raise errors.invalid_request("current_utc must be an ISO8601 timestamp")
    clock.set_now(dt)
    services.evaluate_overdue_plans()
    return success_object({"current_utc": clock.iso(dt)})


# ----------------------------------------------------------------- regions


@bp.post("/survey/regions")
@require_roles("PlatformAdmin")
def create_region(user_id, role):
    data = _require(_body(), "code", "name")
    if not isinstance(data["code"], str) or not isinstance(data["name"], str):
        raise errors.invalid_request("code and name must be strings")
    for r in db.regions.values():
        if r["code"] == data["code"]:
            raise errors.validation("Region code must be unique")
    rec = helpers.make_record()
    rec.update({"code": data["code"], "name": data["name"]})
    db.regions[rec["id"]] = rec
    return success_object(helpers.ser_region(rec), 201)


@bp.get("/survey/regions/<rid>")
@require_roles("PlatformAdmin", "RegionalManager", "ComplianceAuditor", "FieldConsultant")
def get_region(user_id, role, rid):
    rec = db.regions.get(rid)
    if rec is None:
        raise errors.not_found("Region not found")
    return success_object(helpers.ser_region(rec))


# ----------------------------------------------------------------- dealers


@bp.post("/survey/dealers")
@require_roles("PlatformAdmin")
def create_dealer(user_id, role):
    data = _require(_body(), "region_id", "name", "dealer_code")
    if data["region_id"] not in db.regions:
        raise errors.not_found("Region not found")
    for d in db.dealers.values():
        if d["dealer_code"] == data["dealer_code"]:
            raise errors.validation("dealer_code must be unique")
    rec = helpers.make_record()
    rec.update(
        {
            "region_id": data["region_id"],
            "name": data["name"],
            "dealer_code": data["dealer_code"],
            "posture": "GOOD_STANDING",
            "current_score_adjusted": None,
            "current_response_rate": None,
            "confirmed_flag_count": 0,
        }
    )
    db.dealers[rec["id"]] = rec
    return success_object(helpers.ser_dealer(rec), 201)


@bp.get("/survey/dealers/<did>")
@require_roles(
    "PlatformAdmin",
    "RegionalManager",
    "ComplianceAuditor",
    "FieldConsultant",
    "DealerPrincipal",
)
def get_dealer(user_id, role, did):
    rec = db.dealers.get(did)
    if rec is None:
        raise errors.not_found("Dealer not found")
    return success_object(helpers.ser_dealer(rec))


@bp.get("/survey/dealers")
@require_roles("PlatformAdmin", "RegionalManager", "ComplianceAuditor", "FieldConsultant")
def list_dealers(user_id, role):
    limit, offset = parse_pagination(request.args)
    region_id = request.args.get("region_id")
    items = list(db.dealers.values())
    if region_id is not None:
        items = [d for d in items if d["region_id"] == region_id]
    items = _sorted(items)
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([helpers.ser_dealer(d) for d in page], limit, offset, total)


@bp.get("/survey/dealers/<did>/score-history")
@require_roles(
    "PlatformAdmin",
    "RegionalManager",
    "ComplianceAuditor",
    "FieldConsultant",
    "DealerPrincipal",
)
def dealer_score_history(user_id, role, did):
    dealer = db.dealers.get(did)
    if dealer is None:
        raise errors.not_found("Dealer not found")
    out = []
    for wave in db.waves.values():
        if wave["status"] not in ("CLOSED", "FINALIZED"):
            continue
        raw, _adjusted, _rate = services.compute_dealer_wave_numbers(did, wave)
        if raw is None:
            continue
        qs = db.question_sets.get(wave["question_set_id"])
        factor = services.D(qs["comparability_factor"]) if qs else services.D(1)
        normalized = services.round2(raw * factor)
        out.append(
            {
                "wave_id": wave["id"],
                "raw_score": helpers.num(raw),
                "normalized_score": helpers.num(normalized),
            }
        )
    out.sort(
        key=lambda e: db.waves[e["wave_id"]]["closed_at"] or db.waves[e["wave_id"]]["created_at"]
    )
    limit, offset = parse_pagination(request.args)
    total = len(out)
    page = out[offset : offset + limit]
    return success_list(page, limit, offset, total)


# ------------------------------------------------------------- departments


@bp.post("/survey/departments")
@require_roles("PlatformAdmin")
def create_department(user_id, role):
    data = _require(_body(), "dealer_id", "kind", "name")
    if data["dealer_id"] not in db.dealers:
        raise errors.not_found("Dealer not found")
    if data["kind"] not in ("SALES", "SERVICE"):
        raise errors.invalid_request("kind must be SALES or SERVICE")
    for dep in db.departments.values():
        if dep["dealer_id"] == data["dealer_id"] and dep["kind"] == data["kind"]:
            raise errors.validation("One department per (dealer_id, kind)")
    rec = helpers.make_record()
    rec.update(
        {"dealer_id": data["dealer_id"], "kind": data["kind"], "name": data["name"]}
    )
    db.departments[rec["id"]] = rec
    return success_object(helpers.ser_department(rec), 201)


@bp.get("/survey/departments/<dep_id>")
@require_roles(
    "PlatformAdmin",
    "RegionalManager",
    "ComplianceAuditor",
    "FieldConsultant",
    "DealerPrincipal",
)
def get_department(user_id, role, dep_id):
    rec = db.departments.get(dep_id)
    if rec is None:
        raise errors.not_found("Department not found")
    return success_object(helpers.ser_department(rec))


@bp.get("/survey/dealers/<did>/departments")
@require_roles(
    "PlatformAdmin",
    "RegionalManager",
    "ComplianceAuditor",
    "FieldConsultant",
    "DealerPrincipal",
)
def list_departments(user_id, role, did):
    if did not in db.dealers:
        raise errors.not_found("Dealer not found")
    limit, offset = parse_pagination(request.args)
    items = _sorted([d for d in db.departments.values() if d["dealer_id"] == did])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([helpers.ser_department(d) for d in page], limit, offset, total)


# ---------------------------------------------------------------- advisors


@bp.post("/survey/advisors")
@require_roles("PlatformAdmin")
def create_advisor(user_id, role):
    data = _require(_body(), "department_id", "name", "employee_ref")
    if data["department_id"] not in db.departments:
        raise errors.not_found("Department not found")
    for a in db.advisors.values():
        if (
            a["department_id"] == data["department_id"]
            and a["employee_ref"] == data["employee_ref"]
        ):
            raise errors.validation("employee_ref must be unique within department")
    rec = helpers.make_record()
    rec.update(
        {
            "department_id": data["department_id"],
            "name": data["name"],
            "employee_ref": data["employee_ref"],
        }
    )
    db.advisors[rec["id"]] = rec
    return success_object(helpers.ser_advisor(rec), 201)


@bp.get("/survey/advisors/<aid>")
@require_roles(
    "PlatformAdmin",
    "RegionalManager",
    "ComplianceAuditor",
    "FieldConsultant",
    "DealerPrincipal",
)
def get_advisor(user_id, role, aid):
    rec = db.advisors.get(aid)
    if rec is None:
        raise errors.not_found("Advisor not found")
    return success_object(helpers.ser_advisor(rec))


@bp.get("/survey/departments/<dep_id>/advisors")
@require_roles(
    "PlatformAdmin",
    "RegionalManager",
    "ComplianceAuditor",
    "FieldConsultant",
    "DealerPrincipal",
)
def list_advisors(user_id, role, dep_id):
    if dep_id not in db.departments:
        raise errors.not_found("Department not found")
    limit, offset = parse_pagination(request.args)
    items = _sorted(
        [a for a in db.advisors.values() if a["department_id"] == dep_id]
    )
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([helpers.ser_advisor(a) for a in page], limit, offset, total)


# --------------------------------------------------------------- customers


@bp.post("/survey/customers")
@require_roles("PlatformAdmin")
def create_customer(user_id, role):
    data = _require(_body(), "full_name", "email", "phone")
    email = data["email"]
    phone = data["phone"]
    if not isinstance(email, str) or "@" not in email:
        raise errors.invalid_request("email must contain '@'")
    if (
        not isinstance(phone, str)
        or not phone.isdigit()
        or not (10 <= len(phone) <= 15)
    ):
        raise errors.invalid_request("phone must be digits only, 10-15 chars")
    dnc = data.get("do_not_contact", False)
    if not isinstance(dnc, bool):
        raise errors.invalid_request("do_not_contact must be a boolean")
    rec = helpers.make_record()
    rec.update(
        {
            "full_name": data["full_name"],
            "email": email,
            "phone": phone,
            "do_not_contact": dnc,
        }
    )
    db.customers[rec["id"]] = rec
    return success_object(helpers.ser_customer(rec), 201)


@bp.get("/survey/customers/<cid>")
@require_roles("PlatformAdmin", "ComplianceAuditor")
def get_customer(user_id, role, cid):
    rec = db.customers.get(cid)
    if rec is None:
        raise errors.not_found("Customer not found")
    return success_object(helpers.ser_customer(rec))
