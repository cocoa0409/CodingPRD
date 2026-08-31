from flask import Blueprint, request

import auth
import calcs
import services
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_list, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("controls", __name__)

FREQUENCIES = ("DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "ANNUAL", "ADHOC")
AUTOMATIONS = ("MANUAL", "AUTOMATED")
RISK_RATINGS = ("LOW", "MODERATE", "HIGH")

ACTIONS = ("APPROVE_DESIGN", "START_OBSERVATION")
ACTION_ROLES = {"APPROVE_DESIGN": {"Auditor"}, "START_OBSERVATION": {"ComplianceLead"}}
ACTION_PHASES = {
    "APPROVE_DESIGN": {"SCOPING", "READINESS", "OBSERVATION"},
    "START_OBSERVATION": {"OBSERVATION"},
}


@bp.post("/soc/controls")
def create_control():
    auth.authenticate({"ComplianceLead"})
    body = auth.body()
    engagement = v.fk(body, "engagement_id", "engagements")
    org = v.fk(body, "subservice_organization_id", "subservice_organizations")
    v.req_id(body, "engagement_id")
    control_ref = v.req_str(body, "control_ref", 1, 40)
    title = v.req_str(body, "title", 1, 200)
    frequency = v.req_enum(body, "frequency", FREQUENCIES)
    automation = v.opt_enum(body, "automation", AUTOMATIONS, default="MANUAL")
    risk_rating = v.opt_enum(body, "risk_rating", RISK_RATINGS, default="MODERATE")
    population_size = v.opt_int(body, "population_size", minv=0, default=0)
    org_id = v.opt_id(body, "subservice_organization_id")

    services.require_phase(engagement, {"SCOPING", "READINESS"})

    for row in DB["controls"].values():
        if row["engagement_id"] == engagement["id"] and row["control_ref"] == control_ref:
            raise ApiError("ERR_DUPLICATE_RESOURCE")

    in_scope = org is None or org["method"] == "INCLUSIVE"
    row = store.new_row(
        "controls",
        {
            "engagement_id": engagement["id"],
            "control_ref": control_ref,
            "title": title,
            "frequency": frequency,
            "automation": automation,
            "risk_rating": risk_rating,
            "population_size": population_size,
            "owner_user_id": None,
            "design_status": "DESIGN_DRAFT",
            "operating_status": "NOT_TESTED",
            "in_scope": in_scope,
            "subservice_organization_id": org_id,
            "primary_mapping_count": 0,
            "active_mapping_count": 0,
            "evidence_scheduled_count": 0,
            "evidence_accepted_count": 0,
            "evidence_missed_count": 0,
            "tested_item_count": 0,
            "open_gap_count": 0,
        },
    )
    if org is not None:
        services.refresh_inclusive_control_count(org)
    services.refresh_engagement(engagement)
    return ok(store.public(row), 201)


@bp.get("/soc/controls/<control_id>")
def read_control(control_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("controls", control_id)
    return ok(store.public(row))


@bp.get("/soc/controls")
def list_controls():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("controls")
    for key in ("engagement_id", "subservice_organization_id", "design_status", "operating_status"):
        value = request.args.get(key)
        if value is not None:
            items = [r for r in items if r[key] == value]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)


@bp.post("/soc/controls/<control_id>/assign-owner")
def assign_owner(control_id):
    auth.authenticate({"ComplianceLead"})
    row = store.get_or_404("controls", control_id)
    body = auth.body()
    owner = v.req_str(body, "owner_user_id", 1, 200)
    row["owner_user_id"] = owner
    store.touch(row)
    return ok(store.public(row))


@bp.post("/soc/controls/<control_id>/transitions")
def transition_control(control_id):
    _uid, role = auth.authenticate({"ComplianceLead", "Auditor"})
    body = auth.body()
    auth.check_action_role(role, body.get("action"), ACTION_ROLES)
    row = store.get_or_404("controls", control_id)
    action = v.req_enum(body, "action", ACTIONS)
    v.opt_str(body, "reason", 0, 2000)

    engagement = DB["engagements"][row["engagement_id"]]
    services.require_phase(engagement, ACTION_PHASES[action])

    if action == "APPROVE_DESIGN":
        if row["design_status"] not in ("DESIGN_MAPPED", "DESIGN_DEFICIENT"):
            raise ApiError("ERR_TRANSITION_NOT_ALLOWED")
        if row["design_status"] == "DESIGN_DEFICIENT":
            for gap in DB["gaps"].values():
                if (
                    gap["control_id"] == row["id"]
                    and gap["source"] == "EXCEPTION_CASCADE"
                    and gap["status"] != "VERIFIED"
                ):
                    raise ApiError("ERR_INVALID_STATE")
        if row["primary_mapping_count"] < 1:
            raise ApiError("ERR_INVALID_STATE")
        if row["owner_user_id"] is None:
            raise ApiError("ERR_INVALID_STATE")
        if not row["in_scope"]:
            raise ApiError("ERR_INVALID_STATE")
        if not engagement["boundary_locked"]:
            raise ApiError("ERR_BOUNDARY_NOT_LOCKED")
        row["design_status"] = "DESIGN_APPROVED"
    else:
        if row["operating_status"] != "NOT_TESTED":
            raise ApiError("ERR_TRANSITION_NOT_ALLOWED")
        if row["design_status"] != "DESIGN_APPROVED":
            raise ApiError("ERR_INVALID_STATE")
        if not row["in_scope"]:
            raise ApiError("ERR_INVALID_STATE")
        row["operating_status"] = "IN_OBSERVATION"

    store.touch(row)
    services.refresh_engagement(engagement)
    return ok(store.public(row))


@bp.post("/soc/controls/<control_id>/evidence-calendar")
def evidence_calendar(control_id):
    auth.authenticate({"ComplianceLead"})
    row = store.get_or_404("controls", control_id)
    engagement = DB["engagements"][row["engagement_id"]]
    services.require_phase(engagement, {"SCOPING", "READINESS"})
    if not row["in_scope"] or row["design_status"] == "DESIGN_CARVED_OUT":
        raise ApiError("ERR_CONTROL_OUT_OF_SCOPE")
    if services.evidence_of_control(row["id"]):
        raise ApiError("ERR_CALENDAR_ALREADY_GENERATED")

    created = []
    for index, (start, end) in enumerate(calcs.calendar_periods(engagement, row)):
        created.append(
            store.new_row(
                "evidence_requests",
                {
                    "control_id": row["id"],
                    "period_index": index,
                    "period_start": store.fmt_iso(start),
                    "period_end": store.fmt_iso(end),
                    "due_date": store.fmt_iso(store.add_days(end, calcs.GRACE_DAYS)),
                    "status": "SCHEDULED",
                    "submitted_by_user_id": None,
                    "submitted_at": None,
                    "reviewed_by_user_id": None,
                    "reviewed_at": None,
                    "rejection_round": 0,
                    "artifact_ref": None,
                    "late": False,
                },
            )
        )
    row["evidence_scheduled_count"] = len(created)
    store.touch(row)
    return ok_list([store.public(r) for r in created], 201)
