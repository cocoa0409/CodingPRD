"""Technician, training course, and course completion endpoints."""
from flask import Blueprint, request

import calc
from db import db, serialize
from util import (ApiError, bump, get_json, iso_ms, now_logical, ok, paginate,
                  parse_dt, sort_by_created, new_common)
from routes.shops import require_roles, get_shop_or_404

bp = Blueprint("technicians", __name__)

ROLES_READ = {"NetworkAdmin", "NetworkAuditor", "ShopManager"}
TECH_ROLES = {"STRUCTURAL", "NON_STRUCTURAL", "ESTIMATOR", "REFINISH", "ADAS_SPECIALIST"}
OPEN_ORDER_STATUSES = {"ESTIMATE", "APPROVED", "IN_REPAIR", "QC", "REWORK", "CALIBRATION"}


def get_technician_or_404(tech_id):
    tech = db.technicians.get(tech_id)
    if not tech:
        raise ApiError("ERR_NOT_FOUND", 404, "Technician not found")
    return tech


def get_course_or_404(course_id):
    course = db.courses.get(course_id)
    if not course:
        raise ApiError("ERR_NOT_FOUND", 404, "Training course not found")
    return course


def _check_shop_ownership(shop_id):
    if request.headers.get("X-User-Role") == "ShopManager" \
            and request.headers.get("X-User-ID") != shop_id:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "ShopManager may only manage their own shop")


@bp.post("/network/shops/<shop_id>/technicians")
def create_technician(shop_id):
    require_roles("ShopManager")
    _check_shop_ownership(shop_id)
    shop = get_shop_or_404(shop_id)
    body = get_json()
    full_name = body.get("full_name")
    tech_role = body.get("tech_role")
    if not isinstance(full_name, str) or not full_name:
        raise ApiError("ERR_INVALID_REQUEST", 400, "full_name is required")
    if tech_role not in TECH_ROLES:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"tech_role must be one of {sorted(TECH_ROLES)}")
    tech = new_common()
    tech.update({
        "shop_id": shop["id"],
        "full_name": full_name,
        "tech_role": tech_role,
        "status": "PROVISIONAL",
        "curriculum_progress_pct": 0.0,
    })
    db.technicians[tech["id"]] = tech
    calc.recompute_technician(tech)
    return ok(serialize(tech), 201)


@bp.get("/network/shops/<shop_id>/technicians")
def list_shop_technicians(shop_id):
    require_roles(*ROLES_READ)
    get_shop_or_404(shop_id)
    status = request.args.get("status")
    tech_role = request.args.get("tech_role")
    items = [t for t in db.technicians.values() if t["shop_id"] == shop_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if tech_role is not None:
        items = [t for t in items if t["tech_role"] == tech_role]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(t) for t in page], 200, meta)


@bp.get("/network/technicians/<tech_id>")
def get_technician(tech_id):
    require_roles(*ROLES_READ)
    return ok(serialize(get_technician_or_404(tech_id)))


@bp.post("/network/technicians/<tech_id>/deactivate")
def deactivate_technician(tech_id):
    require_roles("ShopManager")
    tech = get_technician_or_404(tech_id)
    _check_shop_ownership(tech["shop_id"])
    if tech["status"] not in ("PROVISIONAL", "CURRENT"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only PROVISIONAL or CURRENT technicians can be deactivated")
    if any(o["assigned_technician_id"] == tech["id"]
           and o["status"] in OPEN_ORDER_STATUSES
           for o in db.repair_orders.values()):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Technician is assigned to an open repair order")
    tech["status"] = "INACTIVE"
    bump(tech)
    shop = db.shops.get(tech["shop_id"])
    if shop:
        calc.recompute_shop_score(shop)
    return ok(serialize(tech))


# ---------------------------------------------------------------------------
# Training courses
# ---------------------------------------------------------------------------
@bp.post("/network/training-courses")
def create_course():
    require_roles("NetworkAdmin")
    body = get_json()
    code = body.get("course_code")
    title = body.get("title")
    roles = body.get("required_for_roles")
    validity = body.get("validity_months")
    credits = body.get("credit_hours")
    active = body.get("active", True)
    if not isinstance(code, str) or not code:
        raise ApiError("ERR_INVALID_REQUEST", 400, "course_code is required")
    if not isinstance(title, str) or not title:
        raise ApiError("ERR_INVALID_REQUEST", 400, "title is required")
    if not isinstance(roles, list) or any(r not in TECH_ROLES for r in roles):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "required_for_roles must be an array of tech_role values")
    if not isinstance(validity, int) or isinstance(validity, bool) or validity < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "validity_months must be >= 1")
    if not isinstance(credits, int) or isinstance(credits, bool) or credits < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "credit_hours must be >= 0")
    if not isinstance(active, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "active must be a boolean")
    course = new_common()
    course.update({
        "course_code": code,
        "title": title,
        "required_for_roles": roles,
        "validity_months": validity,
        "credit_hours": credits,
        "active": active,
    })
    db.courses[course["id"]] = course
    return ok(serialize(course), 201)


@bp.get("/network/training-courses")
def list_courses():
    require_roles(*ROLES_READ)
    active = request.args.get("active")
    items = list(db.courses.values())
    if active is not None:
        want = active.lower() == "true"
        items = [c for c in items if c["active"] == want]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(c) for c in page], 200, meta)


@bp.get("/network/training-courses/<course_id>")
def get_course(course_id):
    require_roles(*ROLES_READ)
    return ok(serialize(get_course_or_404(course_id)))


# ---------------------------------------------------------------------------
# Course completions
# ---------------------------------------------------------------------------
@bp.post("/network/technicians/<tech_id>/course-completions")
def create_completion(tech_id):
    require_roles("ShopManager", "NetworkAdmin")
    tech = get_technician_or_404(tech_id)
    _check_shop_ownership(tech["shop_id"])
    body = get_json()
    course_id = body.get("course_id")
    completed_at = body.get("completed_at")
    proof_uri = body.get("proof_uri")
    if not isinstance(course_id, str) or course_id not in db.courses:
        raise ApiError("ERR_NOT_FOUND", 404, "Training course not found")
    course = db.courses[course_id]
    if not course.get("active"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Course is not active; new completions are not allowed")
    completed = parse_dt(completed_at, "completed_at")
    if not isinstance(proof_uri, str) or not proof_uri:
        raise ApiError("ERR_INVALID_REQUEST", 400, "proof_uri is required")
    cc = new_common()
    cc.update({
        "technician_id": tech["id"],
        "course_id": course["id"],
        "completed_at": iso_ms(completed),
        "proof_uri": proof_uri,
        "status": "CURRENT",
    })
    db.completions[cc["id"]] = cc
    calc.recompute_technician(tech)
    return ok(serialize(cc), 201)


def _completion_current(cc):
    course = db.courses.get(cc["course_id"])
    if not course:
        return cc["status"] == "CURRENT"
    expiry = calc.add_months(parse_dt(cc["completed_at"], "completed_at"),
                             course["validity_months"])
    return expiry > now_logical()


@bp.get("/network/technicians/<tech_id>/course-completions")
def list_technician_completions(tech_id):
    require_roles(*ROLES_READ)
    get_technician_or_404(tech_id)
    status = request.args.get("status")
    items = [c for c in db.completions.values() if c["technician_id"] == tech_id]
    if status is not None:
        if status == "CURRENT":
            items = [c for c in items
                     if (c["status"] == "CURRENT" and _completion_current(c))]
        elif status == "EXPIRED":
            items = [c for c in items
                     if c["status"] == "EXPIRED"
                     or (c["status"] == "CURRENT" and not _completion_current(c))]
        else:
            items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(c) for c in page], 200, meta)


@bp.get("/network/training-courses/<course_id>/completions")
def list_course_completions(course_id):
    require_roles(*ROLES_READ)
    get_course_or_404(course_id)
    status = request.args.get("status")
    items = [c for c in db.completions.values() if c["course_id"] == course_id]
    if status is not None:
        if status == "CURRENT":
            items = [c for c in items
                     if (c["status"] == "CURRENT" and _completion_current(c))]
        elif status == "EXPIRED":
            items = [c for c in items
                     if c["status"] == "EXPIRED"
                     or (c["status"] == "CURRENT" and not _completion_current(c))]
        else:
            items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(c) for c in page], 200, meta)


@bp.get("/network/technicians/<tech_id>/repair-orders")
def list_technician_orders(tech_id):
    require_roles(*ROLES_READ)
    get_technician_or_404(tech_id)
    status = request.args.get("status")
    items = [o for o in db.repair_orders.values()
             if o["assigned_technician_id"] == tech_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(o) for o in page], 200, meta)


@bp.get("/network/technicians/<tech_id>/procedure-steps")
def list_technician_steps(tech_id):
    require_roles(*ROLES_READ)
    get_technician_or_404(tech_id)
    step_type = request.args.get("step_type")
    items = [s for s in db.procedure_steps.values()
             if s["performed_by_technician_id"] == tech_id]
    if step_type is not None:
        items = [s for s in items if s["step_type"] == step_type]
    items = sorted(items, key=lambda s: (s.get("sequence_index", 0), s.get("_seq", 0)))
    page, meta = paginate(items)
    return ok([serialize(s) for s in page], 200, meta)
