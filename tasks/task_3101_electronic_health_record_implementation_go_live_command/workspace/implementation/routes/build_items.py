"""System build item endpoints (PRD §4.3, §3.3)."""

from decimal import Decimal

from flask import Blueprint

from db import DB, MAX_REJECTIONS
from errors import (
    ERR_BUILD_ITEM_NOT_FOUND,
    ERR_CUSTOMIZATION_LIMIT_EXCEEDED,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_POSTURE_BLOCKS_OPERATION,
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
from services import calculations as C
from services import lookups as L
from services import recompute as R
from services.core import serialize, stamp_created

bp = Blueprint("build_items", __name__)

READ_ROLES = [
    "ImplementationDirector",
    "ImplementationAnalyst",
    "BuildAnalyst",
    "TestLead",
]

CLASSIFICATIONS = {"FOUNDATION_ADOPTED", "FOUNDATION_ADAPTED", "LOCAL_CUSTOM"}


def get_department(department_id):
    department = DB.departments.get(department_id)
    if department is None:
        fail(ERR_DEPARTMENT_NOT_FOUND, "No department matches the id.")
    return department


def get_item(item_id):
    item = DB.system_build_items.get(item_id)
    if item is None:
        fail(ERR_BUILD_ITEM_NOT_FOUND, "No system build item matches the id.")
    return item


def view(item):
    return serialize("SystemBuildItem", item)


def _score(item):
    """Compute and publish the item's customization risk.

    PRD §3.3: "The customization score is computed once, on completion of the
    build". The score is a pure function of the item's own recorded
    classification, depth and field list, so a read of the resource publishes
    the same figure completion publishes.
    """
    item["customization_risk_points"] = float(
        C.build_customization_risk(
            item["build_classification"],
            item["customization_depth"],
            item["local_custom_fields"],
        )
    )
    return item


def _customization_ceiling(item):
    """PRD §2.12: "a `LOCAL_CUSTOM` build item whose `customization_risk_points`
    exceeds 40.00 is not admissible to advance either out of build or out of
    validation without a remediation record"."""
    if item["build_classification"] != "LOCAL_CUSTOM":
        return
    if Decimal(str(item["customization_risk_points"] or 0)) > Decimal("40.00"):
        fail(
            ERR_CUSTOMIZATION_LIMIT_EXCEEDED,
            "A LOCAL_CUSTOM build item above 40.00 risk points may not advance.",
        )


@bp.route("/departments/<department_id>/system-build-items", methods=["POST"])
def create_build_item(department_id):
    uid, role = actor()
    require_role(role, ["BuildAnalyst"])
    department = get_department(department_id)
    data = body_fields(
        [
            ("application_code", "string", True),
            ("build_classification", "enum", True),
            ("customization_depth", "int", True),
            ("local_custom_fields", "array", True),
        ],
        payload(),
    )
    enum_member("build_classification", data["build_classification"], CLASSIFICATIONS)
    if data["customization_depth"] < 0:
        fail(ERR_INVALID_REQUEST, "customization_depth must be a non-negative integer.")
    item = {
        "id": DB.new_id(),
        "department_id": department["id"],
        "ehr_implementation_id": department["ehr_implementation_id"],
        "application_code": data["application_code"],
        "build_classification": data["build_classification"],
        "customization_depth": data["customization_depth"],
        "local_custom_fields": data["local_custom_fields"],
        "customization_risk_points": 0.0,
        "test_cycles_passed": 0,
        "open_defect_count": 0,
        "rejection_count": 0,
        "status": "DRAFT",
    }
    stamp_created(item)
    _score(item)
    DB.system_build_items[item["id"]] = item
    DB.register_created(item)
    return ok(view(item), status=201)


@bp.route("/departments/<department_id>/system-build-items", methods=["GET"])
def list_department_items(department_id):
    uid, role = actor()
    require_role(role, READ_ROLES)
    department = get_department(department_id)
    rows = L.department_build_items(department["id"])
    filters = filter_args(["status"])
    if "status" in filters:
        rows = [i for i in rows if i["status"] == filters["status"]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([view(_score(i)) for i in window], pagination=page)


@bp.route("/system-build-items", methods=["GET"])
def list_build_items():
    uid, role = actor()
    require_role(role, READ_ROLES)
    rows = list(DB.system_build_items.values())
    filters = filter_args(["department_id", "ehr_implementation_id", "status"])
    for key in ("department_id", "ehr_implementation_id", "status"):
        if key in filters:
            rows = [i for i in rows if i[key] == filters[key]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([view(_score(i)) for i in window], pagination=page)


@bp.route("/system-build-items/<item_id>", methods=["GET"])
def get_build_item(item_id):
    uid, role = actor()
    require_role(role, READ_ROLES)
    item = get_item(item_id)
    _score(item)
    R.recompute_program_tree(item["ehr_implementation_id"])
    return ok(view(item))


def _transition(item_id, allowed_from, mutate):
    uid, role = actor()
    require_role(role, ["BuildAnalyst"])
    item = get_item(item_id)
    R.recompute_program_tree(item["ehr_implementation_id"])
    if item["status"] not in allowed_from:
        fail(
            ERR_INVALID_STATE,
            "The build item is in status %s; this operation requires %s."
            % (item["status"], " or ".join(allowed_from)),
        )
    mutate(uid, item)
    DB.touch(item, common=True)
    R.recompute_program_tree(item["ehr_implementation_id"])
    return ok(view(item))


@bp.route("/system-build-items/<item_id>/start-build", methods=["POST"])
def start_item_build(item_id):
    def mutate(uid, item):
        program = DB.ehr_implementations[item["ehr_implementation_id"]]
        _customization_ceiling(item)
        if program["readiness_posture"] != "OPEN":
            fail(
                ERR_POSTURE_BLOCKS_OPERATION,
                "Beginning build work requires the program readiness posture to be OPEN.",
            )
        item["status"] = "IN_BUILD"

    return _transition(item_id, ["DRAFT"], mutate)


@bp.route("/system-build-items/<item_id>/complete-build", methods=["POST"])
def complete_item_build(item_id):
    def mutate(uid, item):
        _score(item)
        _customization_ceiling(item)
        item["status"] = "BUILD_COMPLETE"

    return _transition(item_id, ["IN_BUILD"], mutate)


def _require_test_lead(entity_id, allowed_from, mutate):
    uid, role = actor()
    require_role(role, ["TestLead"])
    item = get_item(entity_id)
    R.recompute_program_tree(item["ehr_implementation_id"])
    if item["status"] not in allowed_from:
        fail(
            ERR_INVALID_STATE,
            "The build item is in status %s; this operation requires %s."
            % (item["status"], " or ".join(allowed_from)),
        )
    mutate(uid, item)
    DB.touch(item, common=True)
    R.recompute_program_tree(item["ehr_implementation_id"])
    return ok(view(item))


@bp.route("/system-build-items/<item_id>/start-testing", methods=["POST"])
def start_testing(item_id):
    def mutate(uid, item):
        item["status"] = "IN_TESTING"

    return _require_test_lead(item_id, ["BUILD_COMPLETE"], mutate)


@bp.route("/system-build-items/<item_id>/complete-validation", methods=["POST"])
def complete_validation(item_id):
    def mutate(uid, item):
        _customization_ceiling(item)
        if int(item["test_cycles_passed"] or 0) < 1:
            fail(
                ERR_INVALID_STATE,
                "At least one test scenario must have passed in the current epoch.",
            )
        if int(item["open_defect_count"] or 0) != 0:
            fail(ERR_INVALID_STATE, "The build item must have no open defects.")
        item["status"] = "VALIDATION_COMPLETE"

    return _require_test_lead(item_id, ["IN_TESTING"], mutate)


@bp.route("/system-build-items/<item_id>/rework", methods=["POST"])
def rework_item(item_id):
    def mutate(uid, item):
        if int(item["rejection_count"] or 0) > MAX_REJECTIONS:
            fail(
                ERR_INVALID_STATE,
                "The build item has exceeded the maximum rejection count and must be reset.",
            )
        item["status"] = "IN_BUILD"

    return _transition(item_id, ["BUILD_REJECTED"], mutate)


@bp.route("/system-build-items/<item_id>/reset-to-draft", methods=["POST"])
def reset_to_draft(item_id):
    def mutate(uid, item):
        if int(item["rejection_count"] or 0) <= MAX_REJECTIONS:
            fail(
                ERR_INVALID_STATE,
                "Resetting to DRAFT requires the rejection count to exceed 3.",
            )
        item["status"] = "DRAFT"
        item["rejection_count"] = 0
        item["test_cycles_passed"] = 0
        item["open_defect_count"] = 0
        _score(item)

    return _transition(item_id, ["BUILD_REJECTED"], mutate)