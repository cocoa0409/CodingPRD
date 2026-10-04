"""HTTP layer: every declared endpoint, its RBAC list and its side effects.

All routes are mounted under the ``/prefab`` prefix.  The two reference-data
registration routes that the scaffold's role matrix does not enumerate
(assemblies, and the roster-summary read) are implemented but carry no role
restriction, so the declared matrix is never contradicted.
"""

from flask import Blueprint, request

from core import (ApiError, DB, build_envelope, CLOCK, fail, list_response,
                  object_response, require, serialize, empty_response)
import calculations
import compliance
import components as component_service
import labor
import models as model_service
import orders as order_service
import procurement
import projects as project_service
import revisions as revision_service

bp = Blueprint("prefab", __name__)

READ_ALL = ["PlatformAdmin", "ProjectManager", "ModelCoordinator", "ShopForeman",
            "LogisticsCoordinator", "ProcurementLead", "GeneralForeman", "InstallForeman"]


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_PREFAB_TRANSITION", "a JSON object body is required")
    return data


def merged_args():
    out = dict(request.args)
    return out


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------

@bp.route("/projects", methods=["POST"])
def create_project():
    require(["PlatformAdmin"])
    project = project_service.create_project(body())
    return object_response(project, 201)


@bp.route("/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    require(READ_ALL)
    project = project_service.require_project(project_id)
    project_service.refresh_project(project)
    return object_response(project, 200)


@bp.route("/projects/<project_id>/posture/recompute", methods=["POST"])
def recompute_posture(project_id):
    require(["PlatformAdmin"])
    project = project_service.require_project(project_id)
    project_service.recompute_posture(project)
    return object_response(project, 200)


# --------------------------------------------------------------------------
# Model versions / takeoff lines / racks
# --------------------------------------------------------------------------

@bp.route("/model-versions", methods=["POST"])
def create_model_version():
    require(["ModelCoordinator"])
    record = model_service.create_model_version(body())
    return object_response(record, 201)


@bp.route("/model-versions", methods=["GET"])
def list_model_versions():
    require(["PlatformAdmin", "ProjectManager", "ModelCoordinator", "ShopForeman"])
    return list_response(model_service.filter_model_versions(merged_args()))


@bp.route("/model-versions/<model_version_id>", methods=["GET"])
def get_model_version(model_version_id):
    require(["PlatformAdmin", "ProjectManager", "ModelCoordinator", "ShopForeman"])
    record = model_service.require_model_version(model_version_id)
    return object_response(record, 200)


@bp.route("/model-versions/<model_version_id>/coordinate", methods=["POST"])
def coordinate_model_version(model_version_id):
    require(["ModelCoordinator"])
    record = model_service.require_model_version(model_version_id)
    model_service.coordinate_model_version(record)
    return object_response(record, 200)


@bp.route("/takeoff-lines", methods=["POST"])
def create_takeoff_line():
    require(["ModelCoordinator"])
    model_version = model_service.require_model_version(body().get("model_version_id"))
    if model_version.get("status") not in ("DRAFT", "COORDINATED"):
        fail("ERR_INVALID_PREFAB_TRANSITION")
    record = model_service.create_takeoff_line(body())
    return object_response(record, 201)


@bp.route("/takeoff-lines", methods=["GET"])
def list_takeoff_lines():
    require(["PlatformAdmin", "ProjectManager", "ModelCoordinator", "ShopForeman"])
    records = model_service.filter_takeoff_lines(merged_args())
    for line in records:
        line["crafted_hours"] = calculations.conduit_craft_hours(line)
    return list_response(records)


@bp.route("/racks", methods=["POST"])
def create_rack():
    require(["ModelCoordinator"])
    record = model_service.create_rack(body())
    return object_response(record, 201)


@bp.route("/racks", methods=["GET"])
def list_racks():
    require(["PlatformAdmin", "ProjectManager", "ModelCoordinator", "ShopForeman", "InstallForeman"])
    return list_response(model_service.filter_racks(merged_args()))


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------

@bp.route("/assemblies", methods=["POST"])
def create_assembly():
    record = model_service.create_assembly(body())
    return object_response(record, 201)


@bp.route("/assemblies", methods=["GET"])
def list_assemblies():
    return list_response(DB.all("assemblies"))


@bp.route("/trade-contract-rates", methods=["POST"])
def create_trade_contract_rate():
    require(["PlatformAdmin"])
    record = labor.create_trade_contract_rate(body())
    return object_response(record, 201)


@bp.route("/trade-contract-rates", methods=["GET"])
def list_trade_contract_rates():
    return list_response(labor.filter_rates(merged_args()))


@bp.route("/workers", methods=["POST"])
def create_worker():
    require(["GeneralForeman"])
    record = labor.create_worker(body())
    return object_response(record, 201)


@bp.route("/workers", methods=["GET"])
def list_workers():
    return list_response(DB.all("workers"))


@bp.route("/workers/<worker_id>/roster-summary", methods=["GET"])
def worker_roster_summary(worker_id):
    worker = DB.find("workers", worker_id)
    if worker is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    calculations.apprentice_upgrade_projection(worker)
    return object_response(worker, 200)


# --------------------------------------------------------------------------
# Trade activities / crew days / compliance ledger
# --------------------------------------------------------------------------

@bp.route("/trade-activities", methods=["POST"])
def create_trade_activity():
    require(["GeneralForeman"])
    record = labor.create_trade_activity(body())
    return object_response(record, 201)


@bp.route("/trade-activities", methods=["GET"])
def list_trade_activities():
    require(["PlatformAdmin", "ProjectManager", "GeneralForeman", "InstallForeman"])
    return list_response(labor.filter_activities(merged_args()))


@bp.route("/trade-activities/<activity_id>/status", methods=["PATCH"])
def patch_trade_activity(activity_id):
    require(["GeneralForeman"])
    activity = labor.require_activity(activity_id)
    labor.set_activity_status(activity, body().get("status"))
    return object_response(activity, 200)


@bp.route("/crew-days", methods=["POST"])
def create_crew_day():
    require(["GeneralForeman"])
    record = labor.create_crew_day(body())
    return object_response(record, 201)


@bp.route("/crew-days", methods=["GET"])
def list_crew_days():
    require(["PlatformAdmin", "ProjectManager", "GeneralForeman", "ShopForeman"])
    return list_response(labor.filter_crew_days(merged_args()))


@bp.route("/crew-days/<crew_day_id>/acknowledge", methods=["POST"])
def acknowledge_crew_day(crew_day_id):
    require(["GeneralForeman"])
    crew_day = DB.find("crew_days", crew_day_id)
    if crew_day is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    labor.acknowledge_crew_day(crew_day, body())
    return object_response(crew_day, 200)


@bp.route("/compliance-ledger", methods=["GET"])
def list_compliance_ledger():
    require(["PlatformAdmin", "ProjectManager", "GeneralForeman"])
    return list_response(labor.filter_ledger(merged_args()))


# --------------------------------------------------------------------------
# Prefab orders
# --------------------------------------------------------------------------

@bp.route("/prefab-orders", methods=["POST"])
def create_prefab_order():
    require(["ProjectManager"])
    record = order_service.create_prefab_order(body())
    return object_response(record, 201)


@bp.route("/prefab-orders", methods=["GET"])
def list_prefab_orders():
    require(["PlatformAdmin", "ProjectManager", "ModelCoordinator", "ShopForeman", "LogisticsCoordinator"])
    return list_response(order_service.filter_orders(merged_args()))


@bp.route("/prefab-orders/<order_id>", methods=["GET"])
def get_prefab_order(order_id):
    require(["PlatformAdmin", "ProjectManager", "ModelCoordinator", "ShopForeman", "LogisticsCoordinator"])
    order = order_service.require_order(order_id)
    return object_response(order, 200)


@bp.route("/prefab-orders/<order_id>/release", methods=["POST"])
def release_prefab_order(order_id):
    require(["ProjectManager"])
    order = order_service.require_order(order_id)
    order_service.release_order(order, body())
    return object_response(order, 200)


@bp.route("/prefab-orders/<order_id>/fabrication-status", methods=["PATCH"])
def patch_fabrication_status(order_id):
    require(["ShopForeman"])
    order = order_service.require_order(order_id)
    order_service.set_fabrication_status(order, body())
    return object_response(order, 200)


@bp.route("/prefab-orders/<order_id>/ressue", methods=["POST"])
def ressue_prefab_order(order_id):
    require(["ProjectManager"])
    order = order_service.require_order(order_id)
    order_service.ressue_order(order)
    return object_response(order, 200)


@bp.route("/prefab-orders/<order_id>/cancel", methods=["POST"])
def cancel_prefab_order(order_id):
    require(["ProjectManager"])
    order = order_service.require_order(order_id)
    order_service.cancel_order(order)
    return object_response(order, 200)


@bp.route("/prefab-orders/<order_id>/delivery-status", methods=["PATCH"])
def patch_delivery_status(order_id):
    require(["LogisticsCoordinator"])
    order = order_service.require_order(order_id)
    order_service.set_delivery_status(order, body())
    return object_response(order, 200)


# --------------------------------------------------------------------------
# Prefab components
# --------------------------------------------------------------------------

@bp.route("/prefab-components", methods=["POST"])
def create_prefab_component():
    require(["ShopForeman"])
    record = component_service.create_component(body())
    return object_response(record, 201)


@bp.route("/prefab-components", methods=["GET"])
def list_prefab_components():
    require(["PlatformAdmin", "ProjectManager", "ShopForeman", "InstallForeman", "LogisticsCoordinator"])
    return list_response(component_service.filter_components(merged_args()))


@bp.route("/prefab-components/<component_id>", methods=["GET"])
def get_prefab_component(component_id):
    require(["PlatformAdmin", "ProjectManager", "ShopForeman", "InstallForeman", "LogisticsCoordinator"])
    component = component_service.require_component(component_id)
    return object_response(component, 200)


@bp.route("/prefab-components/<component_id>/fabricate", methods=["POST"])
def fabricate_prefab_component(component_id):
    require(["ShopForeman"])
    component = component_service.require_component(component_id)
    component_service.fabricate_component(component)
    return object_response(component, 200)


@bp.route("/prefab-components/<component_id>/install-status", methods=["PATCH"])
def patch_install_status(component_id):
    require(["InstallForeman"])
    component = component_service.require_component(component_id)
    component_service.set_install_status(component, body())
    return object_response(component, 200)


# --------------------------------------------------------------------------
# Revisions / rework jobs
# --------------------------------------------------------------------------

@bp.route("/revisions", methods=["POST"])
def create_revision():
    require(["ProjectManager"])
    record = revision_service.create_revision(body())
    return object_response(record, 201)


@bp.route("/revisions", methods=["GET"])
def list_revisions():
    require(["PlatformAdmin", "ProjectManager", "ModelCoordinator", "ShopForeman", "ProcurementLead"])
    records = revision_service.filter_revisions(merged_args())
    for revision in records:
        revision_service.revision_derived(revision, DB.find("projects", revision.get("project_id")))
    return list_response(records)


@bp.route("/revisions/<revision_id>/submit", methods=["POST"])
def submit_revision(revision_id):
    require(["ProjectManager"])
    revision = DB.find("revisions", revision_id)
    if revision is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    revision_service.submit_revision(revision, body())
    return object_response(revision, 200)


@bp.route("/revisions/<revision_id>/approve", methods=["POST"])
def approve_revision(revision_id):
    require(["ProjectManager"])
    revision = DB.find("revisions", revision_id)
    if revision is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    revision_service.approve_revision(revision, body())
    return object_response(revision, 200)


@bp.route("/rework-jobs/<job_id>/status", methods=["PATCH"])
def patch_rework_status(job_id):
    require(["ShopForeman", "ProjectManager"])
    job = revision_service.require_rework_job(job_id)
    revision_service.set_rework_status(job, body())
    return object_response(job, 200)


@bp.route("/rework-jobs", methods=["GET"])
def list_rework_jobs():
    require(["PlatformAdmin", "ProjectManager", "ShopForeman"])
    return list_response(revision_service.filter_rework_jobs(merged_args()))


# --------------------------------------------------------------------------
# Material releases / clock
# --------------------------------------------------------------------------

@bp.route("/material-releases", methods=["POST"])
def create_material_release():
    require(["ProcurementLead"])
    record = procurement.create_material_release(body())
    return object_response(record, 201)


@bp.route("/material-releases", methods=["GET"])
def list_material_releases():
    require(["PlatformAdmin", "ProjectManager", "ProcurementLead", "LogisticsCoordinator"])
    records = procurement.filter_releases(merged_args())
    for release in records:
        procurement.refresh_release_values(release)
    return list_response(records)


@bp.route("/material-releases/<release_id>", methods=["GET"])
def get_material_release(release_id):
    require(["PlatformAdmin", "ProjectManager", "ProcurementLead", "LogisticsCoordinator"])
    release = procurement.require_release(release_id)
    procurement.refresh_release_values(release)
    return object_response(release, 200)


@bp.route("/material-releases/<release_id>/declare", methods=["POST"])
def declare_material_release(release_id):
    require(["ProcurementLead"])
    release = procurement.require_release(release_id)
    procurement.declare_release(release, body())
    return object_response(release, 200)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require(["PlatformAdmin"])
    payload = body()
    CLOCK.set(payload.get("to_iso8601"))
    return empty_response()


@bp.route("/_clock", methods=["GET"])
def get_clock():
    return object_response({"current_utc": CLOCK.now_iso()}, 200)


@bp.route("/_clock/clear", methods=["POST"])
def clear_state():
    DB.reset()
    CLOCK.set("2026-09-01T00:00:00Z")
    return empty_response()