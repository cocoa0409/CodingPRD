"""Partner routes (PRD §3.1)."""

from flask import Blueprint, request

import db
from errors import conflict, invalid_request, unprocessable
from errors import ERR_INVALID_STATE, ERR_TRAINING_TENURE_INSUFFICIENT
from middleware import require_roles, ALL_ROLES
from response import success_list, success_object
from services import domain
from util import (
    base_entity,
    get_json_body,
    logical_dt,
    paginate,
    req_string,
    touch,
)

bp = Blueprint("partners", __name__)


@bp.route("/partners", methods=["POST"])
def create_partner():
    require_roles("HRRecruiter")
    body = get_json_body()
    full_name = req_string(body, "full_name")
    email = req_string(body, "email")
    role_in_program = req_string(body, "role_in_program")
    if role_in_program not in ("MANAGING_PARTNER", "MARKET_PARTNER"):
        raise invalid_request("role_in_program must be MANAGING_PARTNER or MARKET_PARTNER")
    p = base_entity()
    p.update({
        "full_name": full_name,
        "email": email,
        "role_in_program": role_in_program,
        "status": "CANDIDATE",
        "training_started_at": None,
        "certified_at": None,
        "placed_restaurant_id": None,
    })
    db.partners[p["id"]] = p
    return success_object(domain.ser_partner(p), 201)


@bp.route("/partners", methods=["GET"])
def list_partners():
    require_roles(*ALL_ROLES)
    items = list(db.partners.values())
    role_in_program = request.args.get("role_in_program")
    if role_in_program is not None:
        items = [p for p in items if p["role_in_program"] == role_in_program]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    placed = request.args.get("placed_restaurant_id")
    if placed is not None:
        items = [p for p in items if p.get("placed_restaurant_id") == placed]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_partner(p) for p in page], limit, offset, total)


@bp.route("/partners/<pid>", methods=["GET"])
def get_partner(pid):
    require_roles(*ALL_ROLES)
    return success_object(domain.ser_partner(domain.get_partner(pid)))


@bp.route("/partners/<pid>/start-training", methods=["POST"])
def start_training(pid):
    require_roles("HRRecruiter")
    p = domain.get_partner(pid)
    if p["status"] != "CANDIDATE":
        raise conflict(ERR_INVALID_STATE, "Partner must be CANDIDATE to start training")
    p["status"] = "IN_TRAINING"
    p["training_started_at"] = logical_dt()
    touch(p)
    return success_object(domain.ser_partner(p))


@bp.route("/partners/<pid>/certify", methods=["POST"])
def certify(pid):
    require_roles("HRRecruiter")
    p = domain.get_partner(pid)
    if p["status"] not in ("IN_TRAINING", "TRAINING_EXTENDED"):
        raise conflict(ERR_INVALID_STATE, "Partner must be IN_TRAINING or TRAINING_EXTENDED to certify")
    # Temporal check (tier 6): tenure gate.
    if domain.training_weeks_accrued(p) < domain.MIN_TRAINING_WEEKS:
        raise unprocessable(
            ERR_TRAINING_TENURE_INSUFFICIENT,
            "Certification requires at least %d accrued training weeks" % domain.MIN_TRAINING_WEEKS,
        )
    p["status"] = "CERTIFIED"
    p["certified_at"] = logical_dt()
    touch(p)
    return success_object(domain.ser_partner(p))


@bp.route("/partners/<pid>/withdraw", methods=["POST"])
def withdraw(pid):
    require_roles("HRRecruiter")
    p = domain.get_partner(pid)
    if p["status"] not in ("CANDIDATE", "IN_TRAINING", "TRAINING_EXTENDED", "CERTIFIED"):
        raise conflict(ERR_INVALID_STATE, "Partner in status %s cannot be withdrawn directly" % p["status"])
    from services import sweeps

    sweeps.withdraw_partner(p)
    return success_object(domain.ser_partner(p))
