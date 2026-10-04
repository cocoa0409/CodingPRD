"""Investigative groups, completion, and factual reports (PRD 3.3, 3.5).

POST /groups                                             IIC
GET  /groups                                             all roles
GET  /groups/{id}                                        all roles
POST /groups/{id}/complete                               GroupChairman
POST /groups/{id}/factual-reports                        GroupChairman
POST /groups/{id}/factual-reports/{report_id}/verify     IIC
"""

from flask import Blueprint, request

import clock
import db
import domain
from auth import get_context, require_chairman, require_iic, require_roles
from constants import GROUP_SPECIALTIES, REPORT_KINDS, ROLES
from envelope import ok_list, ok_object, paginate, parse_pagination
from errors import api_error
from serializers import group_public
from validate import get_body, req_enum, req_str

bp = Blueprint("groups", __name__)


@bp.route("/groups", methods=["POST"])
def create_group():
    user_id, role = get_context()
    require_roles(role, ("IIC",))
    body = get_body()
    investigation_id = req_str(body, "investigation_id")
    specialty = req_enum(body, "specialty", GROUP_SPECIALTIES)
    chairman_user_id = req_str(body, "chairman_user_id")
    investigation = domain.get_investigation(investigation_id)
    require_iic(user_id, investigation)

    if chairman_user_id == investigation["iic_user_id"]:
        raise api_error(
            "ERR_SOD_IIC_CANNOT_CHAIR",
            "the investigator-in-charge may not chair a group on their own "
            "investigation",
        )

    group = db.add(
        "groups",
        {
            "investigation_id": investigation["id"],
            "specialty": specialty,
            "chairman_user_id": chairman_user_id,
            "status": "ACTIVE",
            "seated_count": 0,
            "factual_reports": [],
        },
    )
    return ok_object(group_public(group), status=201)


@bp.route("/groups", methods=["GET"])
def list_groups():
    _user_id, role = get_context()
    require_roles(role, ROLES)
    limit, offset = parse_pagination(request.args)
    items = db.all_of("groups")
    investigation_id = request.args.get("investigation_id")
    if investigation_id is not None:
        items = [g for g in items if g["investigation_id"] == investigation_id]
    specialty = request.args.get("specialty")
    if specialty is not None:
        items = [g for g in items if g["specialty"] == specialty]
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([group_public(g) for g in page], limit, offset, total)


@bp.route("/groups/<group_id>", methods=["GET"])
def get_group(group_id):
    _user_id, role = get_context()
    require_roles(role, ROLES)
    group = domain.get_group(group_id)
    return ok_object(group_public(group), status=200)


@bp.route("/groups/<group_id>/complete", methods=["POST"])
def complete_group(group_id):
    user_id, role = get_context()
    require_roles(role, ("GroupChairman",))
    group = domain.get_group(group_id)
    require_chairman(user_id, group)

    if group["status"] != "ACTIVE":
        raise api_error(
            "ERR_GROUP_NOT_ACTIVE", "only an ACTIVE group may be completed"
        )
    investigation = domain.get_investigation(group["investigation_id"])
    if investigation["phase"] != "FACTUAL":
        raise api_error(
            "ERR_INVESTIGATION_PHASE_INVALID",
            "a group may only be completed during the FACTUAL phase",
        )
    has_evidence = any(
        report["status"] in ("VERIFIED", "DOCKETED")
        for report in group["factual_reports"]
    )
    if group["seated_count"] < 1 or not has_evidence:
        raise api_error(
            "ERR_GROUP_NOT_COMPLETABLE",
            "group completion requires at least one SEATED seat and at least "
            "one VERIFIED or DOCKETED factual report",
        )

    group["status"] = "COMPLETE"
    domain.recompute_docket_pct(investigation)
    db.touch(group)
    return ok_object(group_public(group), status=200)


@bp.route("/groups/<group_id>/factual-reports", methods=["POST"])
def create_factual_report(group_id):
    user_id, role = get_context()
    require_roles(role, ("GroupChairman",))
    group = domain.get_group(group_id)
    require_chairman(user_id, group)

    body = get_body()
    report_kind = req_enum(body, "report_kind", REPORT_KINDS)
    content = req_str(body, "content")
    recorder_id = body.get("recorder_id")
    if report_kind == "RECORDER_TRANSCRIPT":
        if not isinstance(recorder_id, str) or recorder_id == "":
            raise api_error(
                "ERR_INVALID_REQUEST",
                "recorder_id is required when report_kind is "
                "RECORDER_TRANSCRIPT",
            )
    elif recorder_id is not None:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "recorder_id must be absent unless report_kind is "
            "RECORDER_TRANSCRIPT",
        )
    recorder = None
    if recorder_id is not None:
        recorder = domain.get_recorder(recorder_id)

    if group["status"] != "ACTIVE":
        raise api_error(
            "ERR_GROUP_NOT_ACTIVE",
            "factual reports may only be authored on an ACTIVE group",
        )
    investigation = domain.get_investigation(group["investigation_id"])
    if investigation["phase"] not in ("ON_SCENE", "FACTUAL"):
        raise api_error(
            "ERR_INVESTIGATION_PHASE_INVALID",
            "factual reports may only be authored during ON_SCENE or FACTUAL",
        )

    report = {
        "report_id": db.new_id(),
        "report_kind": report_kind,
        "content": content,
        "recorder_id": recorder["id"] if recorder is not None else None,
        "status": "SUBMITTED",
        "submitted_by_user_id": user_id,
        "submitted_at": clock.get_clock(),
        "verified_at": None,
    }
    group["factual_reports"].append(report)
    db.touch(group)
    return ok_object(group_public(group), status=201)


@bp.route(
    "/groups/<group_id>/factual-reports/<report_id>/verify", methods=["POST"]
)
def verify_factual_report(group_id, report_id):
    user_id, role = get_context()
    require_roles(role, ("IIC",))
    group = domain.get_group(group_id)
    investigation = domain.get_investigation(group["investigation_id"])
    require_iic(user_id, investigation)
    report = domain.find_report(group, report_id)

    if group["status"] != "ACTIVE":
        raise api_error(
            "ERR_GROUP_NOT_ACTIVE",
            "reports may only be verified while the group is ACTIVE",
        )
    if investigation["phase"] != "FACTUAL":
        raise api_error(
            "ERR_INVESTIGATION_PHASE_INVALID",
            "reports may only be verified during the FACTUAL phase",
        )
    if report["status"] != "SUBMITTED":
        raise api_error(
            "ERR_REPORT_STATE_INVALID",
            "only a SUBMITTED report may be verified",
        )
    if report["report_kind"] == "RECORDER_TRANSCRIPT":
        recorder = domain.get_recorder(report["recorder_id"])
        domain.refresh_recorder(recorder)
        if recorder["status"] not in ("READOUT_COMPLETE", "RELEASED"):
            raise api_error(
                "ERR_RECORDER_READOUT_INCOMPLETE",
                "the referenced recorder's readout is not complete",
            )

    report["status"] = "VERIFIED"
    report["verified_at"] = clock.get_clock()
    db.touch(group)
    return ok_object(group_public(group), status=200)
