"""Carbon reduction projects and the certification waterfall."""
import derive
import guards
import serialize
from envelope import ok, ok_list
from errors import fail
from routes import bp
from shape import enum_param, page, pagination, require_auth, str_param, take
from store import db, new_row, touch
from util import D, rhu

PROJECT_TYPES = ["CARBON_CAPTURE", "COMBINED_HEAT_POWER", "CORN_OIL_EXTRACTION",
                 "LOW_TILL_FEEDSTOCK", "PROCESS_HEAT_ELECTRIFICATION"]
TIERS = ["FULL", "PROVISIONAL"]
PROJECT_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED_FOR_REVISION", "CERTIFIED")

PROJECT_SPEC = {
    "project_code": {"type": "string", "required": True},
    "project_name": {"type": "string", "required": True},
    "project_type": {"type": "enum", "required": True, "values": PROJECT_TYPES},
    "claimed_reduction_g_per_mj": {"type": "dec", "required": True, "gt": 0,
                                   "places": 1},
    "certification_tier": {"type": "enum", "required": True, "values": TIERS},
    "capital_cost_cents": {"type": "int", "ge": 0},
    "predecessor_project_id": {"type": "string"},
}
SUBMIT_SPEC = {"verification_body": {"type": "string", "required": True}}
REVIEW_SPEC = {
    "determination": {"type": "enum", "required": True, "values": ["RETURN", "CERTIFY"]},
    "verified_reduction_g_per_mj": {"type": "dec", "gt": 0, "places": 1},
    "review_note": {"type": "string"},
}


@bp.route("/carbon-projects", methods=["POST"])
def create_project():
    require_auth(["ComplianceOfficer"])
    body = take(PROJECT_SPEC)
    predecessor = None
    if body["predecessor_project_id"] is not None:
        predecessor = guards.get_project(body["predecessor_project_id"])
    guards.unique(db.projects, "project_code", body["project_code"])
    project = new_row({
        "project_code": body["project_code"],
        "project_name": body["project_name"],
        "project_type": body["project_type"],
        "claimed_reduction_g_per_mj": rhu(body["claimed_reduction_g_per_mj"], 1),
        "capital_cost_cents": body["capital_cost_cents"],
        "predecessor_project_id": predecessor["id"] if predecessor else None,
        "verification_status": "DRAFT",
        "certification_tier": body["certification_tier"],
        "verification_body": None,
        "verified_reduction_g_per_mj": None,
        "credited_reduction_g_per_mj": None,
        "submitted_at": None,
        "reviewed_at": None,
        "certified_at": None,
        "revision_count": 0,
        "review_note": None,
        "submitted_by_user_id": None,
    })
    db.projects[project["id"]] = project
    return ok(serialize.project_out(project), 201)


@bp.route("/carbon-projects/<project_id>", methods=["GET"])
def get_project(project_id):
    require_auth(["PlantManager", "ComplianceOfficer", "RiskManager"])
    project = guards.get_project(project_id)
    return ok(serialize.project_out(project))


@bp.route("/carbon-projects", methods=["GET"])
def list_projects():
    require_auth(["PlantManager", "ComplianceOfficer", "RiskManager"])
    predecessor_id = str_param("predecessor_project_id")
    status = enum_param("verification_status", PROJECT_STATUSES)
    tier = enum_param("certification_tier", TIERS)
    limit, offset = pagination()
    if predecessor_id is not None:
        guards.get_project(predecessor_id)
    rows = list(db.projects.values())
    if predecessor_id is not None:
        rows = [r for r in rows if r["predecessor_project_id"] == predecessor_id]
    if status is not None:
        rows = [r for r in rows if r["verification_status"] == status]
    if tier is not None:
        rows = [r for r in rows if r["certification_tier"] == tier]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    window = page(rows, limit, offset)
    return ok_list([serialize.project_out(r) for r in window],
                   limit, offset, len(rows))


@bp.route("/carbon-projects/<project_id>/submit", methods=["POST"])
def submit_project(project_id):
    user_id, _role = require_auth(["ComplianceOfficer"])
    body = take(SUBMIT_SPEC)
    project = guards.get_project(project_id)
    if project["verification_status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        fail("ERR_INVALID_PROJECT_STATE",
             "Project is %s and may not be submitted" % project["verification_status"])
    if int(project["revision_count"]) > 2:
        fail("ERR_REVISION_LIMIT_REACHED",
             "Project has exhausted its two permitted revisions")
    if project["predecessor_project_id"] is not None:
        predecessor = db.projects.get(project["predecessor_project_id"])
        if predecessor is None or predecessor["verification_status"] != "CERTIFIED":
            fail("ERR_PREDECESSOR_NOT_CERTIFIED",
                 "The predecessor project has not been certified")
    project["verification_status"] = "SUBMITTED"
    project["verification_body"] = body["verification_body"]
    project["submitted_at"] = db.clock
    project["submitted_by_user_id"] = user_id
    touch(project)
    return ok(serialize.project_out(project))


@bp.route("/carbon-projects/<project_id>/review", methods=["POST"])
def review_project(project_id):
    # PRD 2.1: the project segregation of duties is enforced purely by the role
    # split (submit is ComplianceOfficer-only, review is PlantManager-only), so
    # no X-User-ID comparison is made here.
    require_auth(["PlantManager"])
    body = take(REVIEW_SPEC)
    project = guards.get_project(project_id)
    if project["verification_status"] != "SUBMITTED":
        fail("ERR_INVALID_PROJECT_STATE",
             "Project is %s and may not be reviewed" % project["verification_status"])
    if body["determination"] == "RETURN":
        if int(project["revision_count"]) >= 2:
            fail("ERR_REVISION_LIMIT_REACHED",
                 "Project has already been returned twice")
        project["verification_status"] = "RETURNED_FOR_REVISION"
        project["revision_count"] = int(project["revision_count"]) + 1
        project["review_note"] = body["review_note"]
        project["reviewed_at"] = db.clock
        touch(project)
        return ok(serialize.project_out(project))
    verified = body["verified_reduction_g_per_mj"]
    if verified is None:
        verified = project["claimed_reduction_g_per_mj"]
    verified = rhu(verified, 1)
    if D(verified) <= 0:
        fail("ERR_VALIDATION", "verified_reduction_g_per_mj must be greater than zero")
    project["verification_status"] = "CERTIFIED"
    project["verified_reduction_g_per_mj"] = verified
    project["review_note"] = body["review_note"]
    project["reviewed_at"] = db.clock
    project["certified_at"] = db.clock
    touch(project)
    derive.recompute_credited(skip_bump_id=project["id"])
    return ok(serialize.project_out(project))
