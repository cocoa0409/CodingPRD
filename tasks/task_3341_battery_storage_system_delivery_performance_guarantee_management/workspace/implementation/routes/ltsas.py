"""ServiceAgreement (LTSA) routes with lazy expiry cascade."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles, ALL_ROLES
from pagination import paginate
from response import success_object, success_list, iso_utc
from services import compute_credit_pool
from util import new_id, stamp_new, touch, parse_iso, req_nonneg_int, req_bool

bp = Blueprint("ltsas", __name__)


def serialize_sa(s):
    return dict(s)


def lazy_expire(sa):
    """If end_date has passed and the LTSA is ACTIVE/SUSPENDED, flip to EXPIRED
    and cascade-cancel ORDERED/SHIPPED orders, restoring drawn credit."""
    if sa["status"] not in ("ACTIVE", "SUSPENDED"):
        return
    now = store.clock()
    end = parse_iso(sa["end_date"], "end_date")
    if now > end:
        sa["status"] = "EXPIRED"
        for o in store.orders.values():
            if o["service_agreement_id"] == sa["id"] and o["status"] in ("ORDERED", "SHIPPED"):
                o["status"] = "CANCELLED"
                if o.get("covered_by_credit"):
                    sa["credit_drawn_cents"] -= o["part_cost_cents"]
                touch(o)
        touch(sa)


def get_sa_or_404(sid):
    sa = store.service_agreements.get(sid)
    if sa is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceAgreement not found")
    lazy_expire(sa)
    return sa


@bp.route("/service-agreements", methods=["POST"])
@require_roles({"ServiceManager"})
def create_sa():
    body = request.get_json(silent=True) or {}
    project_id = body.get("project_id")
    if not isinstance(project_id, str) or project_id not in store.projects:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "project_id does not reference an existing Project")
    fee = req_nonneg_int(body, "annual_fee_cents")
    cm = req_bool(body, "covers_monitoring")
    cmt = req_bool(body, "covers_maintenance")
    csp = req_bool(body, "covers_spare_parts")
    csu = req_bool(body, "covers_software_updates")
    sd_raw = body.get("start_date")
    ed_raw = body.get("end_date")
    sd = parse_iso(sd_raw, "start_date")
    ed = parse_iso(ed_raw, "end_date")
    if ed <= sd:
        raise ApiError("ERR_INVALID_REQUEST", 400, "end_date must be strictly after start_date")
    sa = {
        "id": new_id(),
        "project_id": project_id,
        "annual_fee_cents": fee,
        "covers_monitoring": cm,
        "covers_maintenance": cmt,
        "covers_spare_parts": csp,
        "covers_software_updates": csu,
        "start_date": sd_raw,
        "end_date": ed_raw,
        "activated_at": None,
        "credit_pool_cents": 0,
        "credit_drawn_cents": 0,
        "status": "DRAFT",
    }
    stamp_new(sa)
    store.service_agreements[sa["id"]] = sa
    return success_object(serialize_sa(sa), 201)


@bp.route("/service-agreements", methods=["GET"])
@require_roles(set(ALL_ROLES))
def list_sas():
    # reads may trigger lazy expiry
    for sa in store.service_agreements.values():
        lazy_expire(sa)
    project_id = request.args.get("project_id")
    items = [s for s in store.service_agreements.values()
             if project_id is None or s["project_id"] == project_id]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_sa(s) for s in page], limit, offset, total)


@bp.route("/service-agreements/<sid>", methods=["GET"])
@require_roles(set(ALL_ROLES))
def get_sa(sid):
    return success_object(serialize_sa(get_sa_or_404(sid)))


@bp.route("/service-agreements/<sid>/activate", methods=["POST"])
@require_roles({"ServiceManager"})
def activate_sa(sid):
    sa = get_sa_or_404(sid)
    if sa["status"] != "DRAFT":
        raise ApiError("ERR_LTSA_NOT_DRAFT", 409, "LTSA activate requires DRAFT")
    now = store.clock()
    sd = parse_iso(sa["start_date"], "start_date")
    ed = parse_iso(sa["end_date"], "end_date")
    if not (sd <= now <= ed):
        raise ApiError("ERR_LTSA_NOT_IN_TERM", 409,
                       "Activation requires the logical clock within [start_date, end_date]")
    sa["status"] = "ACTIVE"
    sa["activated_at"] = iso_utc(now)
    sa["credit_pool_cents"] = compute_credit_pool(sa["annual_fee_cents"])
    touch(sa)
    return success_object(serialize_sa(sa))


@bp.route("/service-agreements/<sid>/suspend", methods=["POST"])
@require_roles({"ServiceManager"})
def suspend_sa(sid):
    sa = get_sa_or_404(sid)
    if sa["status"] != "ACTIVE":
        raise ApiError("ERR_LTSA_NOT_ACTIVE", 409, "LTSA suspend requires ACTIVE")
    sa["status"] = "SUSPENDED"
    touch(sa)
    return success_object(serialize_sa(sa))


@bp.route("/service-agreements/<sid>/reactivate", methods=["POST"])
@require_roles({"ServiceManager"})
def reactivate_sa(sid):
    sa = get_sa_or_404(sid)
    if sa["status"] != "SUSPENDED":
        raise ApiError("ERR_LTSA_NOT_SUSPENDED", 409, "LTSA reactivate requires SUSPENDED")
    now = store.clock()
    ed = parse_iso(sa["end_date"], "end_date")
    if now > ed:
        raise ApiError("ERR_LTSA_NOT_IN_TERM", 409,
                       "Reactivation requires the logical clock at or before end_date")
    sa["status"] = "ACTIVE"
    touch(sa)
    return success_object(serialize_sa(sa))
