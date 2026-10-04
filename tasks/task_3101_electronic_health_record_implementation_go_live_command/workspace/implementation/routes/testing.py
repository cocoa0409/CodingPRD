"""Test scenarios and defects (PRD §4.5, §3.5)."""

from decimal import Decimal

from flask import Blueprint

from db import DB, MAX_REOPEN_ATTEMPTS
from errors import (
    ERR_BUILD_ITEM_NOT_FOUND,
    ERR_DEFECT_NOT_FOUND,
    ERR_DEFECT_SEVERITY_NOT_DEFERRABLE,
    ERR_INVALID_STATE,
    ERR_SOD_VIOLATION,
    ERR_TEST_SCENARIO_NOT_FOUND,
    fail,
)
from request_utils import (
    actor,
    body_fields,
    collection,
    enum_member,
    filter_args,
    pagination,
    payload,
    require_role,
)
from response import ok
from services import lookups as L
from services import recompute as R
from services.core import serialize, stamp_created

bp = Blueprint("testing", __name__)

READ_ROLES = ["ImplementationAnalyst", "TestLead", "BuildAnalyst"]
SCENARIO_CLASSES = {"UNIT", "INTEGRATED", "CHARGE_CAPTURE_TO_CLAIM"}
SEVERITIES = {"SEV1", "SEV2", "SEV3", "SEV4"}


def get_item(item_id):
    item = DB.system_build_items.get(item_id)
    if item is None:
        fail(ERR_BUILD_ITEM_NOT_FOUND, "No system build item matches the id.")
    return item


def get_scenario(scenario_id):
    scenario = DB.test_scenarios.get(scenario_id)
    if scenario is None:
        fail(ERR_TEST_SCENARIO_NOT_FOUND, "No test scenario matches the id.")
    return scenario


def get_defect(defect_id):
    defect = DB.test_defects.get(defect_id)
    if defect is None:
        fail(ERR_DEFECT_NOT_FOUND, "No test defect matches the id.")
    return defect


def scenario_view(scenario):
    return serialize("TestScenario", scenario)


def defect_view(defect):
    return serialize("TestDefect", defect)


def _reject_build_item(item):
    if item["status"] == "IN_TESTING":
        item["status"] = "BUILD_REJECTED"
        item["rejection_count"] = int(item["rejection_count"] or 0) + 1
        DB.touch(item, common=True)


# --------------------------------------------------------------------------
# TestScenario
# --------------------------------------------------------------------------
@bp.route("/system-build-items/<item_id>/test-scenarios", methods=["POST"])
def create_scenario(item_id):
    uid, role = actor()
    require_role(role, ["TestLead"])
    item = get_item(item_id)
    data = body_fields(
        [("scenario_class", "enum", True), ("step_count", "int", True)], payload()
    )
    enum_member("scenario_class", data["scenario_class"], SCENARIO_CLASSES)
    if data["step_count"] <= 0:
        fail(ERR_INVALID_REQUEST, "step_count must be a positive integer.")
    scenario = {
        "id": DB.new_id(),
        "system_build_item_id": item["id"],
        "ehr_implementation_id": item["ehr_implementation_id"],
        "scenario_class": data["scenario_class"],
        "step_count": data["step_count"],
        "executed_epoch": None,
        "open_defect_count": 0,
        "status": "DEFINED",
    }
    stamp_created(scenario)
    DB.test_scenarios[scenario["id"]] = scenario
    DB.register_created(scenario)
    R.recompute_program_tree(item["ehr_implementation_id"])
    return ok(scenario_view(scenario), status=201)


@bp.route("/system-build-items/<item_id>/test-scenarios", methods=["GET"])
def list_item_scenarios(item_id):
    uid, role = actor()
    require_role(role, READ_ROLES)
    item = get_item(item_id)
    rows = L.build_item_scenarios(item["id"])
    filters = filter_args(["scenario_class", "status"])
    for key, value in filters.items():
        rows = [s for s in rows if s.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([scenario_view(s) for s in window], pagination=page)


@bp.route("/test-scenarios", methods=["GET"])
def list_scenarios():
    uid, role = actor()
    require_role(role, READ_ROLES)
    rows = list(DB.test_scenarios.values())
    filters = filter_args(
        ["system_build_item_id", "ehr_implementation_id", "scenario_class", "status"]
    )
    for key, value in filters.items():
        rows = [s for s in rows if s.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([scenario_view(s) for s in window], pagination=page)


@bp.route("/test-scenarios/<scenario_id>", methods=["GET"])
def get_scenario_endpoint(scenario_id):
    uid, role = actor()
    require_role(role, READ_ROLES)
    return ok(scenario_view(get_scenario(scenario_id)))


@bp.route("/test-scenarios/<scenario_id>/execute", methods=["POST"])
def execute_scenario(scenario_id):
    uid, role = actor()
    require_role(role, ["TestLead"])
    scenario = get_scenario(scenario_id)
    data = body_fields(
        [("outcome", "enum", True), ("executed_epoch", "int", True)], payload()
    )
    enum_member("outcome", data["outcome"], {"PASS", "FAIL"})
    program = DB.ehr_implementations[scenario["ehr_implementation_id"]]
    if scenario["status"] != "DEFINED":
        fail(ERR_INVALID_STATE, "Executing requires the scenario to be DEFINED.")
    if data["executed_epoch"] != program["current_epoch_index"]:
        fail(
            ERR_INVALID_STATE,
            "The supplied executed_epoch must equal the program's current epoch.",
        )
    scenario["executed_epoch"] = data["executed_epoch"]
    if data["outcome"] == "PASS":
        scenario["status"] = "PASSED"
    else:
        scenario["status"] = "FAILED"
        _reject_build_item(get_item(scenario["system_build_item_id"]))
    DB.touch(scenario, common=True)
    R.recompute_program_tree(program["id"])
    return ok(scenario_view(scenario))


@bp.route("/test-scenarios/<scenario_id>/reset", methods=["POST"])
def reset_scenario(scenario_id):
    uid, role = actor()
    require_role(role, ["TestLead"])
    scenario = get_scenario(scenario_id)
    if scenario["status"] != "FAILED":
        fail(ERR_INVALID_STATE, "Resetting requires the scenario to be FAILED.")
    scenario["status"] = "DEFINED"
    DB.touch(scenario, common=True)
    R.recompute_program_tree(scenario["ehr_implementation_id"])
    return ok(scenario_view(scenario))


@bp.route("/test-scenarios/<scenario_id>/record-defect", methods=["POST"])
def record_defect(scenario_id):
    uid, role = actor()
    require_role(role, ["TestLead"])
    scenario = get_scenario(scenario_id)
    data = body_fields(
        [("defect_code", "string", True), ("severity", "enum", True)], payload()
    )
    enum_member("severity", data["severity"], SEVERITIES)
    defect = {
        "id": DB.new_id(),
        "test_scenario_id": scenario["id"],
        "ehr_implementation_id": scenario["ehr_implementation_id"],
        "defect_code": data["defect_code"],
        "severity": data["severity"],
        "blocks_go_live": False,
        "resolution_epoch": None,
        "attempt_count": 0,
        "aging_hours": 0.0,
        "opened_utc": DB.clock.get(),
        "status": "OPEN",
    }
    stamp_created(defect)
    DB.test_defects[defect["id"]] = defect
    DB.register_created(defect)
    R.recompute_program_tree(defect["ehr_implementation_id"])
    # trigger: a SEV1/SEV2 defect opened against a build item of this department
    scenario = DB.test_scenarios.get(defect["test_scenario_id"])
    item = DB.system_build_items.get(scenario["system_build_item_id"])
    department = DB.departments.get(item["department_id"]) if item else None
    if department is not None:
        R.on_blocking_defect_change(department)
    R.recompute_program_tree(defect["ehr_implementation_id"])
    return ok(defect_view(defect), status=201)


# --------------------------------------------------------------------------
# TestDefect
# --------------------------------------------------------------------------
@bp.route("/test-defects", methods=["GET"])
def list_defects():
    uid, role = actor()
    require_role(role, READ_ROLES)
    rows = list(DB.test_defects.values())
    filters = filter_args(["test_scenario_id", "ehr_implementation_id", "severity", "status"])
    for key, value in filters.items():
        rows = [d for d in rows if d.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([defect_view(d) for d in window], pagination=page)


@bp.route("/test-defects/<defect_id>", methods=["GET"])
def get_defect_endpoint(defect_id):
    uid, role = actor()
    require_role(role, READ_ROLES)
    R.recompute_program_tree(get_defect(defect_id)["ehr_implementation_id"])
    return ok(defect_view(get_defect(defect_id)))


@bp.route("/test-defects/<defect_id>/begin-remediation", methods=["POST"])
def begin_remediation(defect_id):
    uid, role = actor()
    require_role(role, ["BuildAnalyst"])
    defect = get_defect(defect_id)
    if defect["status"] not in ("OPEN", "REOPENED"):
        fail(ERR_INVALID_STATE, "Beginning remediation requires OPEN or REOPENED.")
    defect["status"] = "IN_REMEDIATION"
    DB.touch(defect, common=True)
    R.recompute_program_tree(defect["ehr_implementation_id"])
    return ok(defect_view(defect))


@bp.route("/test-defects/<defect_id>/resolve", methods=["POST"])
def resolve_defect(defect_id):
    uid, role = actor()
    require_role(role, ["BuildAnalyst"])
    defect = get_defect(defect_id)
    if defect["status"] != "IN_REMEDIATION":
        fail(ERR_INVALID_STATE, "Resolving requires the defect to be IN_REMEDIATION.")
    if DB.acted(uid, "go_no_go_approved"):
        fail(
            ERR_SOD_VIOLATION,
            "The acting user approved the go/no-go decision linked to this defect.",
        )
    program = DB.ehr_implementations[defect["ehr_implementation_id"]]
    defect["status"] = "RESOLVED"
    defect["resolution_epoch"] = program["current_epoch_index"]
    defect["blocks_go_live"] = False
    DB.touch(defect, common=True)
    # cascade link 3: clear one CLAIM_DENIED order of the owning facility
    scenario = DB.test_scenarios.get(defect["test_scenario_id"])
    if scenario is not None:
        item = DB.system_build_items.get(scenario["system_build_item_id"])
        if item is not None:
            department = DB.departments.get(item["department_id"])
            if department is not None:
                facility = DB.facilities.get(department["facility_id"])
                if facility is not None:
                    for order in L.facility_orders(facility["id"]):
                        if order["billing_state"] == "CLAIM_DENIED":
                            order["billing_state"] = "CHARGE_POSTED"
                            DB.touch(order, common=True)
                            break
    DB.mark(uid, "resolved_defect:%s" % defect["id"])
    R.recompute_program_tree(defect["ehr_implementation_id"])
    scenario = DB.test_scenarios.get(defect["test_scenario_id"])
    item = DB.system_build_items.get(scenario["system_build_item_id"]) if scenario else None
    department = DB.departments.get(item["department_id"]) if item else None
    if department is not None:
        R.on_blocking_defect_change(department)
    R.recompute_program_tree(defect["ehr_implementation_id"])
    return ok(defect_view(defect))


@bp.route("/test-defects/<defect_id>/defer", methods=["POST"])
def defer_defect(defect_id):
    uid, role = actor()
    require_role(role, ["TestLead"])
    defect = get_defect(defect_id)
    if defect["status"] != "IN_REMEDIATION":
        fail(ERR_INVALID_STATE, "Deferring requires the defect to be IN_REMEDIATION.")
    if defect["severity"] not in ("SEV3", "SEV4"):
        fail(
            ERR_DEFECT_SEVERITY_NOT_DEFERRABLE,
            "Only SEV3 or SEV4 defects may be deferred.",
        )
    defect["status"] = "DEFERRED"
    DB.touch(defect, common=True)
    R.recompute_program_tree(defect["ehr_implementation_id"])
    return ok(defect_view(defect))


@bp.route("/test-defects/<defect_id>/reopen", methods=["POST"])
def reopen_defect(defect_id):
    uid, role = actor()
    require_role(role, ["TestLead"])
    defect = get_defect(defect_id)
    if defect["status"] != "RESOLVED":
        fail(ERR_INVALID_STATE, "Reopening requires the defect to be RESOLVED.")
    program = DB.ehr_implementations[defect["ehr_implementation_id"]]
    if defect["resolution_epoch"] != program["current_epoch_index"]:
        fail(ERR_INVALID_STATE, "Reopening requires the resolution epoch to be current.")
    if int(defect["attempt_count"] or 0) >= MAX_REOPEN_ATTEMPTS:
        fail(ERR_INVALID_STATE, "The defect has reached the maximum reopen attempts.")
    defect["status"] = "REOPENED"
    defect["blocks_go_live"] = True
    defect["attempt_count"] = int(defect["attempt_count"] or 0) + 1
    DB.touch(defect, common=True)
    R.recompute_program_tree(defect["ehr_implementation_id"])
    return ok(defect_view(defect))