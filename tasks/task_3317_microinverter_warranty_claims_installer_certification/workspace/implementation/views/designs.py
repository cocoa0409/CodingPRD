"""Design project routes and the DC/AC approval gate (PRD 3.2)."""

import db
import shapes
from approval import as_int, as_nonempty_str_optional, as_str, body
from auth import ROLE_INSTALLER, ROLE_PLATFORM_ADMIN, get_design_project, require
from errors import fail
from respond import ok, ok_list, paginate
from services import common



def create_design_project():
    data = body()
    installer_id = as_str(data, "installer_id")
    site_address = as_str(data, "site_address")
    site_postal_code = as_str(data, "site_postal_code")
    module_count = as_int(data, "module_count", minimum=1)
    dc_capacity_watts = as_int(data, "dc_capacity_watts", minimum=1)

    installer = db.DB.installers.get(installer_id)
    if installer is None:
        fail("ERR_RESOURCE_NOT_FOUND", "installer %s does not exist" % installer_id)

    # Certification first, then level -- the two checks run in that order.
    common.require_active_certification(installer)
    if installer.get("certification_level") not in ("GOLD", "PLATINUM"):
        fail("ERR_DESIGN_TOOL_NOT_ENABLED")

    ac_watts = common.dec(module_count) * common.dec(common.MICRO_AC_WATTS)
    dc_ac_ratio = common.ratio4(common.dec(dc_capacity_watts) / ac_watts)

    project = {
        "id": common.new_id(),
        "created_at": common.now_iso(),
        "updated_at": common.now_iso(),
        "version": 1,
        "installer_id": installer_id,
        "site_address": site_address,
        "site_postal_code": site_postal_code,
        "module_count": module_count,
        "dc_capacity_watts": dc_capacity_watts,
        "dc_ac_ratio": dc_ac_ratio,
        "status": "DRAFT",
        "rejection_reason": None,
    }
    db.DB.design_projects[project["id"]] = project
    common.recompute_installer(installer)
    return ok(shapes.design_project(project), 201)


def list_design_projects():
    from flask import request

    installer_id = request.args.get("installer_id")
    status = request.args.get("status")
    rows = list(db.DB.design_projects.values())
    if installer_id:
        rows = [p for p in rows if p.get("installer_id") == installer_id]
    if status:
        rows = [p for p in rows if p.get("status") == status]
    rows = db.by_created_at(rows)
    window, meta = paginate(rows, request.args)
    return ok_list([shapes.design_project(p) for p in window], pagination=meta)


def read_design_project(project_id):
    project = get_design_project(project_id)
    return ok(shapes.design_project(project))


def submit_design_project(project_id):
    project = get_design_project(project_id)
    if project.get("status") != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT design can be submitted")
    common.set_many(project, {"status": "SUBMITTED"})
    return ok(shapes.design_project(project))


def approve_design_project(project_id):
    project = get_design_project(project_id)
    if project.get("status") != "SUBMITTED":
        fail("ERR_INVALID_STATE", "only a SUBMITTED design can be approved")
    if common.dec(project.get("dc_ac_ratio")) > common.MAX_DC_AC_RATIO:
        fail("ERR_DC_AC_RATIO_EXCEEDED")
    common.set_many(project, {"status": "APPROVED", "rejection_reason": None})
    installer = db.DB.installers.get(project.get("installer_id"))
    if installer is not None:
        common.recompute_installer(installer)
    return ok(shapes.design_project(project))


def reject_design_project(project_id):
    data = body()
    rejection_reason = as_nonempty_str_optional(data, "rejection_reason")
    if rejection_reason is None:
        fail("ERR_INVALID_REQUEST_BODY", "missing required field `rejection_reason`")
    project = get_design_project(project_id)
    if project.get("status") != "SUBMITTED":
        fail("ERR_INVALID_STATE", "only a SUBMITTED design can be rejected")
    common.set_many(project, {"status": "REJECTED", "rejection_reason": rejection_reason})
    return ok(shapes.design_project(project))


def register(app):
    app.add_url_rule("/warranty/design-projects", "create_design_project",
                     require(ROLE_INSTALLER)(create_design_project), methods=["POST"])
    app.add_url_rule("/warranty/design-projects", "list_design_projects",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER)(list_design_projects),
                     methods=["GET"])
    app.add_url_rule("/warranty/design-projects/<project_id>", "read_design_project",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER)(read_design_project),
                     methods=["GET"])
    app.add_url_rule("/warranty/design-projects/<project_id>/submit", "submit_design_project",
                     require(ROLE_INSTALLER)(submit_design_project), methods=["POST"])
    app.add_url_rule("/warranty/design-projects/<project_id>/approve", "approve_design_project",
                     require(ROLE_PLATFORM_ADMIN)(approve_design_project), methods=["POST"])
    app.add_url_rule("/warranty/design-projects/<project_id>/reject", "reject_design_project",
                     require(ROLE_PLATFORM_ADMIN)(reject_design_project), methods=["POST"])