"""Utility connections, permit submittals, correction items."""
from datetime import date, timedelta

from flask import Blueprint, request

from common import (
    ALL_ROLES, DB, authorize, body_json, clock_date, fail, get_correction, get_project,
    get_submittal, get_utility, listing, new_row, ok, ser, touch, v_array, v_bool, v_enum,
    v_int, v_str,
)
import calc
import services

bp = Blueprint("permit", __name__)

SERVICE_TYPES = ("WATER", "SEWER", "ELECTRIC")
DISCIPLINES = ("STRUCTURAL", "ENERGY", "FIRE", "PLANNING", "UTILITY")
SEVERITIES = ("BLOCKING", "ADVISORY")


# ---------------------------------------------------------------------------
# Utility connections
# ---------------------------------------------------------------------------
@bp.post("/adu-projects/<pid>/utility-connections")
@authorize("DesignLead")
def create_utility(pid):
    project = get_project(pid)
    body = body_json()
    service_type = v_enum(body, "service_type", SERVICE_TYPES)

    for uc in services.project_utilities(project["id"]):
        if uc["service_type"] == service_type:
            fail("ERR_DUPLICATE_UTILITY_SERVICE",
                 "Project already carries a %s connection." % service_type)

    row = new_row()
    row.update(
        adu_project_id=project["id"],
        service_type=service_type,
        status="PENDING_DECISION",
        decision=None,
        separation_score=0,
        separation_cost_cents=0,
        override_decision=None,
        energized_on_date=None,
    )
    DB.utilities[row["id"]] = row
    return ok(ser(row), 201)


@bp.get("/adu-projects/<pid>/utility-connections")
@authorize(*ALL_ROLES)
def list_utilities(pid):
    get_project(pid)
    rows = [u for u in DB.utilities.values() if u["adu_project_id"] == pid]
    service_type = request.args.get("service_type")
    if service_type:
        rows = [r for r in rows if r["service_type"] == service_type]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows)


@bp.post("/utility-connections/<uid>/decide")
@authorize("DesignLead")
def decide_utility(uid):
    uc = get_utility(uid)
    body = body_json()
    override_decision = v_enum(body, "override_decision", ("SEPARATE", "SHARED"),
                               required=False, default=None)

    if uc["status"] != "PENDING_DECISION":
        fail("ERR_UTILITY_STATE_INVALID", "Connection has already been decided.")

    project = DB.projects[uc["adu_project_id"]]
    if project["approved_pathway"] is None:
        fail("ERR_PATHWAY_NOT_SELECTED", "Project has no approved pathway.")

    prop = DB.properties[project["property_id"]]
    jur = DB.jurisdictions[prop["jurisdiction_id"]]
    score, decision, cost = calc.utility_separation_decision(
        project, prop, jur, override_decision
    )

    uc["separation_score"] = score
    uc["decision"] = decision
    uc["separation_cost_cents"] = cost
    uc["override_decision"] = override_decision
    uc["status"] = "SEPARATE_APPROVED" if decision == "SEPARATE" else "SHARED_APPROVED"
    touch(uc)
    return ok(ser(uc))


@bp.post("/utility-connections/<uid>/energize")
@authorize("ProjectManager")
def energize_utility(uid):
    uc = get_utility(uid)
    if uc["status"] not in ("SEPARATE_APPROVED", "SHARED_APPROVED"):
        fail("ERR_UTILITY_STATE_INVALID", "Connection cannot be energized from %s."
             % uc["status"])

    latest = services.latest_submittal(uc["adu_project_id"])
    if latest is None or latest["status"] != "APPROVED":
        fail("ERR_PERMIT_NOT_APPROVED", "The project's newest permit submittal is not APPROVED.")

    uc["status"] = "ENERGIZED"
    uc["energized_on_date"] = clock_date()
    touch(uc)
    return ok(ser(uc))


# ---------------------------------------------------------------------------
# Permit submittals
# ---------------------------------------------------------------------------
@bp.post("/adu-projects/<pid>/permit-submittals")
@authorize("DesignLead")
def create_submittal(pid):
    project = get_project(pid)
    body = body_json()
    design_sheet_count = v_int(body, "design_sheet_count", minimum=1)
    title24_compliant = v_bool(body, "title24_compliant")

    prop = DB.properties[project["property_id"]]
    jur = DB.jurisdictions[prop["jurisdiction_id"]]
    fees = calc.permit_fee_schedule(project, prop, jur)

    row = new_row()
    row.update(
        adu_project_id=project["id"],
        design_sheet_count=design_sheet_count,
        title24_compliant=title24_compliant,
        design_revision=1,
        status="PREPARED",
        cycle_number=0,
        submitted_on_date=None,
        correction_deadline_date=None,
        approved_on_date=None,
    )
    row.update(fees)
    DB.submittals[row["id"]] = row
    return ok(ser(row), 201)


@bp.get("/adu-projects/<pid>/permit-submittals")
@authorize(*ALL_ROLES)
def list_submittals(pid):
    get_project(pid)
    rows = [s for s in DB.submittals.values() if s["adu_project_id"] == pid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows)


@bp.get("/permit-submittals/<sid>")
@authorize(*ALL_ROLES)
def read_submittal(sid):
    return ok(ser(get_submittal(sid)))


@bp.post("/permit-submittals/<sid>/submit")
@authorize("DesignLead")
def submit_submittal(sid):
    sub = get_submittal(sid)
    project = DB.projects[sub["adu_project_id"]]

    if sub["status"] != "PREPARED":
        fail("ERR_SUBMITTAL_STATE_INVALID", "Submittal is not PREPARED.")
    if project["status"] not in ("FEASIBILITY_CLEARED", "PERMITTED", "UNDER_CONSTRUCTION"):
        fail("ERR_PROJECT_PHASE_INVALID", "Project cannot file a submittal from %s."
             % project["status"])
    for uc in services.project_utilities(project["id"]):
        if uc["status"] == "PENDING_DECISION":
            fail("ERR_UTILITY_DECISION_PENDING", "A utility connection is still pending.")
    if not sub["title24_compliant"]:
        fail("ERR_TITLE24_MISSING", "Package lacks a passing Title 24 report.")

    sub["status"] = "UNDER_PLAN_CHECK"
    sub["cycle_number"] = 1
    sub["submitted_on_date"] = clock_date()
    touch(sub)

    project["status"] = "PERMITTING"
    touch(project)
    return ok(ser(sub))


@bp.post("/permit-submittals/<sid>/plan-check-result")
@authorize("PlanChecker")
def plan_check_result(sid):
    sub = get_submittal(sid)
    body = body_json()
    outcome = v_enum(body, "outcome", ("APPROVED", "CORRECTIONS_REQUIRED"))

    raw_items = body.get("correction_items")
    if raw_items is not None:
        if not isinstance(raw_items, list):
            fail("ERR_VALIDATION", "correction_items must be an array.")
        for item in raw_items:
            if not isinstance(item, dict):
                fail("ERR_VALIDATION", "correction_items elements must be objects.")
            v_enum(item, "discipline", DISCIPLINES)
            v_enum(item, "severity", SEVERITIES)
            v_str(item, "description")

    if sub["status"] != "UNDER_PLAN_CHECK":
        fail("ERR_SUBMITTAL_STATE_INVALID", "Submittal is not UNDER_PLAN_CHECK.")

    project = DB.projects[sub["adu_project_id"]]

    if outcome == "APPROVED":
        for item in services.submittal_corrections(sub["id"]):
            if item["severity"] == "BLOCKING" and item["status"] == "OPEN":
                fail("ERR_BLOCKING_CORRECTIONS_OPEN", "A BLOCKING correction is still OPEN.")
        sub["status"] = "APPROVED"
        sub["approved_on_date"] = clock_date()
        touch(sub)

        if project["status"] == "PERMITTING":
            project["status"] = "PERMITTED"
        project["total_permit_fee_cents"] = sub["total_permit_fee_cents"]
        touch(project)
        return ok(ser(sub))

    # outcome == CORRECTIONS_REQUIRED
    if raw_items is None or len(raw_items) == 0:
        fail("ERR_NO_CORRECTIONS_ON_RECORD", "A corrections letter must carry corrections.")

    for item in raw_items:
        row = new_row()
        row.update(
            permit_submittal_id=sub["id"],
            discipline=item["discipline"],
            severity=item["severity"],
            description=item["description"],
            status="OPEN",
            resolved_on_date=None,
        )
        DB.corrections[row["id"]] = row

    prop = DB.properties[project["property_id"]]
    jur = DB.jurisdictions[prop["jurisdiction_id"]]
    deadline = date.fromisoformat(clock_date()) + timedelta(days=jur["correction_response_days"])

    sub["status"] = "CORRECTIONS_REQUIRED"
    sub["correction_deadline_date"] = deadline.isoformat()
    touch(sub)

    if project["status"] == "PERMITTING":
        project["status"] = "DESIGN_REVISION"
        touch(project)
        services.block_scheduled_phases(project)
    return ok(ser(sub))


@bp.post("/permit-submittals/<sid>/resubmit")
@authorize("DesignLead")
def resubmit_submittal(sid):
    sub = get_submittal(sid)
    if sub["status"] != "CORRECTIONS_REQUIRED":
        fail("ERR_SUBMITTAL_STATE_INVALID", "Submittal is not in CORRECTIONS_REQUIRED.")

    deadline = sub.get("correction_deadline_date")
    if deadline is not None and date.fromisoformat(clock_date()) > date.fromisoformat(deadline):
        sub["status"] = "EXPIRED"
        sub["correction_deadline_date"] = None
        touch(sub)
        fail("ERR_CORRECTION_WINDOW_EXPIRED", "The correction window has lapsed.")

    for item in services.submittal_corrections(sub["id"]):
        if item["severity"] == "BLOCKING" and item["status"] == "OPEN":
            fail("ERR_BLOCKING_CORRECTIONS_OPEN", "A BLOCKING correction is still OPEN.")

    sub["status"] = "UNDER_PLAN_CHECK"
    sub["cycle_number"] = sub["cycle_number"] + 1
    sub["design_revision"] = sub["design_revision"] + 1
    sub["correction_deadline_date"] = None
    touch(sub)

    project = DB.projects[sub["adu_project_id"]]
    if project["status"] == "DESIGN_REVISION":
        project["status"] = "PERMITTING"
        touch(project)
    return ok(ser(sub))


@bp.get("/permit-submittals/<sid>/correction-items")
@authorize(*ALL_ROLES)
def list_corrections(sid):
    get_submittal(sid)
    rows = [c for c in DB.corrections.values() if c["permit_submittal_id"] == sid]
    severity = request.args.get("severity")
    if severity:
        rows = [r for r in rows if r["severity"] == severity]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows)


@bp.post("/correction-items/<cid>/resolve")
@authorize("DesignLead")
def resolve_correction(cid):
    item = get_correction(cid)
    if item["status"] != "OPEN":
        fail("ERR_CORRECTION_ITEM_STATE_INVALID", "Correction item is already RESOLVED.")
    sub = DB.submittals[item["permit_submittal_id"]]
    if sub["status"] != "CORRECTIONS_REQUIRED":
        fail("ERR_SUBMITTAL_STATE_INVALID", "Parent submittal is not in CORRECTIONS_REQUIRED.")

    item["status"] = "RESOLVED"
    item["resolved_on_date"] = clock_date()
    touch(item)
    return ok(ser(item))
