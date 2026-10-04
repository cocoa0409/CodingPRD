"""DataAcquisitionAgreement endpoints."""

from flask import Blueprint

from db import db
from errors import (
    err_not_found,
    err_invalid_request,
    err_invalid_state,
    err_stale_version,
    err_agreement_not_active,
)
from middleware import require_role, ALL_ROLES
from response import success_object
from routes.suppliers import check_window_overlap
from services.cascades import suspend_agreement_cascade, resume_agreement_cascade
from services.common import body_json, require_fields, check_int_opt, check_date_opt, touch

bp = Blueprint("agreements", __name__)


def _get_agreement(aid):
    ag = db.agreements.get(aid)
    if ag is None:
        raise err_not_found("Agreement not found")
    return ag


@bp.route("/data-acquisition-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    require_role(ALL_ROLES)
    return success_object(_get_agreement(aid))


@bp.route("/data-acquisition-agreements/<aid>/activate", methods=["POST"])
def activate_agreement(aid):
    require_role(["DataAcquisitionManager"])
    ag = _get_agreement(aid)
    if ag["status"] != "DRAFT":
        raise err_invalid_state("Agreement must be DRAFT to activate")
    if db.suppliers[ag["supplier_id"]]["status"] != "ACTIVE":
        raise err_agreement_not_active("Supplier must be ACTIVE to activate agreement")
    ag["status"] = "ACTIVE"
    touch(ag)
    return success_object(ag)


@bp.route("/data-acquisition-agreements/<aid>/suspend", methods=["POST"])
def suspend_agreement(aid):
    require_role(["DataAcquisitionManager"])
    ag = _get_agreement(aid)
    if ag["status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE to suspend")
    ag["status"] = "SUSPENDED"
    touch(ag)
    suspend_agreement_cascade(ag)
    return success_object(ag)


@bp.route("/data-acquisition-agreements/<aid>/resume", methods=["POST"])
def resume_agreement(aid):
    require_role(["DataAcquisitionManager"])
    ag = _get_agreement(aid)
    if ag["status"] != "SUSPENDED":
        raise err_invalid_state("Agreement must be SUSPENDED to resume")
    if db.suppliers[ag["supplier_id"]]["status"] != "ACTIVE":
        raise err_agreement_not_active("Supplier must be ACTIVE to resume agreement")
    ag["status"] = "ACTIVE"
    touch(ag)
    resume_agreement_cascade(ag)
    return success_object(ag)


@bp.route("/data-acquisition-agreements/<aid>/terminate", methods=["POST"])
def terminate_agreement(aid):
    require_role(["DataAcquisitionManager"])
    ag = _get_agreement(aid)
    if ag["status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
        raise err_invalid_state("Agreement cannot be terminated from its current state")
    was_active = ag["status"] == "ACTIVE"
    ag["status"] = "TERMINATED"
    touch(ag)
    if was_active:
        suspend_agreement_cascade(ag)
    return success_object(ag)


@bp.route("/data-acquisition-agreements/<aid>/amendments", methods=["POST"])
def amend_agreement(aid):
    require_role(["DataAcquisitionManager"])
    ag = _get_agreement(aid)
    data = body_json()
    require_fields(data, ["expected_agreement_version"])
    new_budget = check_int_opt(data, "royalty_budget_cents", min_v=0)
    new_end = check_date_opt(data, "exclusivity_end_date")
    if data["expected_agreement_version"] != ag["version"]:
        raise err_stale_version()
    if new_end is not None:
        check_window_overlap(
            ag["supplier_id"], ag["data_domain"], ag["exclusivity_start_date"], new_end,
            exclude_id=ag["id"],
        )
    if new_budget is not None:
        ag["royalty_budget_cents"] = new_budget
    if new_end is not None:
        ag["exclusivity_end_date"] = new_end
    ag["amendment_count"] += 1
    touch(ag)
    return success_object(ag)
