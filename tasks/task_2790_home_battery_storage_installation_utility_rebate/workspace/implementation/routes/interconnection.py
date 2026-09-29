"""Interconnection applications: filing, submission, utility review and PTO."""

from flask import Blueprint, request

import shape
import store
from common import EXPORT_MODES, dec, kw
from envelope import collection, created, ok
from errors import ApiError, invalid
from routes.systems import permit_of
from security import guard, path_ref, ref

bp = Blueprint("interconnection", __name__)

READ_ROLES = (
    "CertifiedInstaller",
    "Homeowner",
    "UtilityInterconnectionReviewer",
    "AuthorityHavingJurisdiction",
    "RebateAdministrator",
)


def _app_state_error(application, action):
    return ApiError(
        "ERR_APPLICATION_STATE_INVALID",
        "An application in %s cannot be %s." % (application["status"], action),
    )


def _export_consistency(export_mode, requested_export_kw):
    if export_mode == "NON_EXPORT" and dec(requested_export_kw) != 0:
        raise invalid("'requested_export_kw' must be 0 for the NON_EXPORT mode.")


@bp.route("/interconnection-applications", methods=["POST"])
@guard("CertifiedInstaller")
def create_application(actor):
    payload = shape.body()
    system_id = payload.fk("battery_system_id")
    system = ref("battery_system", system_id)
    export_mode = payload.enum("export_mode", EXPORT_MODES)
    requested_export_kw = payload.number("requested_export_kw")
    _export_consistency(export_mode, requested_export_kw)

    for existing in store.rows("applications"):
        if existing["battery_system_id"] == system["id"] and existing["status"] != "DENIED":
            raise ApiError(
                "ERR_DUPLICATE_APPLICATION",
                "The system already carries a live interconnection application.",
            )

    record = store.insert(
        "applications",
        {
            "battery_system_id": system_id,
            "export_mode": export_mode,
            "requested_export_kw": kw(requested_export_kw),
            "approved_export_kw": None,
            "status": "DRAFT",
            "supplemental_round_count": 0,
            "reviewed_by_user_id": None,
            "pto_granted_by_user_id": None,
            "pto_granted_at": None,
        },
    )
    return created(store.view(record))


@bp.route("/interconnection-applications/<application_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_application(actor, application_id):
    record = path_ref(actor, "application", application_id)
    return ok(store.view(record))


@bp.route("/interconnection-applications", methods=["GET"])
@guard(*READ_ROLES)
def list_applications(actor):
    records = store.where(
        "applications",
        battery_system_id=request.args.get("battery_system_id"),
        status=request.args.get("status"),
        export_mode=request.args.get("export_mode"),
    )
    return collection(records)


@bp.route("/interconnection-applications/<application_id>/submit", methods=["POST"])
@guard("CertifiedInstaller")
def submit_application(actor, application_id):
    application = path_ref(actor, "application", application_id)
    payload = shape.body()
    export_mode = payload.enum(
        "export_mode", EXPORT_MODES, required=False, default=application["export_mode"]
    )
    requested_export_kw = payload.number(
        "requested_export_kw", required=False, default=application["requested_export_kw"]
    )
    _export_consistency(export_mode, requested_export_kw)

    if application["status"] not in ("DRAFT", "SUPPLEMENTAL_REVIEW"):
        raise _app_state_error(application, "submitted")

    system = store.get("battery_systems", application["battery_system_id"])
    if application["status"] == "DRAFT":
        if system is None or system["build_status"] not in (
            "DESIGN_LOCKED",
            "INSTALLED",
            "COMMISSIONED",
        ):
            raise ApiError(
                "ERR_SYSTEM_BUILD_STATE_INVALID",
                "The bank has nothing stable for the utility to review.",
            )
    if system is not None and system["grid_status"] == "DENIED":
        raise ApiError(
            "ERR_SYSTEM_GRID_STATE_INVALID",
            "The utility denial is final for this bank.",
        )

    application["export_mode"] = export_mode
    application["requested_export_kw"] = kw(requested_export_kw)
    application["status"] = "SUBMITTED"
    store.touch(application)

    if system is not None and system["grid_status"] != "APPLICATION_SUBMITTED":
        system["grid_status"] = "APPLICATION_SUBMITTED"
        store.touch(system)
    return ok(store.view(application))


@bp.route("/interconnection-applications/<application_id>/review", methods=["POST"])
@guard("UtilityInterconnectionReviewer")
def review_application(actor, application_id):
    application = path_ref(actor, "application", application_id)
    payload = shape.body()
    decision = payload.enum(
        "decision", ("APPROVE_TO_INSTALL", "REQUEST_SUPPLEMENTAL", "DENY")
    )
    approved_export_kw = payload.number("approved_export_kw", required=False)

    if application["status"] != "SUBMITTED":
        raise _app_state_error(application, "reviewed")

    system = store.get("battery_systems", application["battery_system_id"])
    if decision == "APPROVE_TO_INSTALL":
        _export_consistency(application["export_mode"], application["requested_export_kw"])
        limit = (
            approved_export_kw
            if approved_export_kw is not None
            else application["requested_export_kw"]
        )
        application["status"] = "APPROVED_TO_INSTALL"
        application["approved_export_kw"] = kw(limit)
        application["reviewed_by_user_id"] = actor.user_id
        store.touch(application)
        if system is not None:
            system["grid_status"] = "APPROVED_TO_INSTALL"
            store.touch(system)
    elif decision == "REQUEST_SUPPLEMENTAL":
        application["status"] = "SUPPLEMENTAL_REVIEW"
        application["supplemental_round_count"] += 1
        store.touch(application)
    else:
        application["status"] = "DENIED"
        store.touch(application)
        if system is not None:
            system["grid_status"] = "DENIED"
            store.touch(system)
    return ok(store.view(application))


@bp.route("/interconnection-applications/<application_id>/grant-pto", methods=["POST"])
@guard("UtilityInterconnectionReviewer")
def grant_pto(actor, application_id):
    application = path_ref(actor, "application", application_id)
    if application["status"] != "APPROVED_TO_INSTALL":
        raise _app_state_error(application, "granted permission to operate")

    system = store.get("battery_systems", application["battery_system_id"])
    if system is None or system["build_status"] != "COMMISSIONED":
        raise ApiError(
            "ERR_SYSTEM_BUILD_STATE_INVALID",
            "The bank must be commissioned before permission to operate.",
        )
    if application["reviewed_by_user_id"] is not None and (
        actor.user_id == application["reviewed_by_user_id"]
    ):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The approving reviewer may not grant permission to operate.",
        )
    permit = permit_of(system)
    if permit["status"] != "INSPECTION_PASSED":
        raise ApiError(
            "ERR_PERMIT_NOT_PASSED", "The permit inspection has not passed."
        )

    application["status"] = "PTO_GRANTED"
    application["pto_granted_by_user_id"] = actor.user_id
    application["pto_granted_at"] = store.now()
    store.touch(application)
    system["grid_status"] = "PTO_GRANTED"
    store.touch(system)
    return ok(store.view(application))
