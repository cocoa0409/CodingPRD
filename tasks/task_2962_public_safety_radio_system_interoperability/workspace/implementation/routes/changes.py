"""Programming change requests: submission, board review and fleet deployment."""
from flask import Blueprint

import common
import compute
import db
import enums
import response
import serialize
import validate
from errors import ApiError
from validate import CHANGE_CONTROL_BOARD, FLEET_ENGINEER

bp = Blueprint("changes", __name__, url_prefix=common.PREFIX)

TERMINAL = ("DEPLOYED", "REJECTED")


@bp.post("/change-requests")
def create_change_request():
    validate.authenticate([FLEET_ENGINEER])
    body = validate.get_body()
    template = validate.req_fk(body, "template_id", "templates")
    agency = validate.req_fk(body, "target_agency_id", "agencies")
    title = validate.req_str(body, "title", 1, 120)
    row = db.base_row({
        "template_id": template["id"],
        "target_agency_id": agency["id"],
        "title": title,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
        "revision_count": 0,
        "review_comment": None,
        "pinned_template_version": None,
        "pinned_template_record_version": None,
        "target_unit_count": 0,
        "deployed_unit_count": 0,
        "failed_unit_count": 0,
        "deployment_started_at": None,
        "deployed_at": None,
    })
    db.store.change_requests[row["id"]] = row
    return response.ok(serialize.change_request(row), 201)


@bp.get("/change-requests")
def list_change_requests():
    validate.authenticate(common.ANY_ROLE)
    filters = (
        ("template_id", validate.filter_str("template_id")),
        ("target_agency_id", validate.filter_str("target_agency_id")),
        ("status", validate.filter_enum("status", enums.CHANGE_REQUEST_STATUSES)),
    )
    return common.list_endpoint("change_requests", serialize.change_request, filters)


@bp.get("/change-requests/<change_request_id>")
def read_change_request(change_request_id):
    validate.authenticate(common.ANY_ROLE)
    change = validate.lookup("change_requests", change_request_id)
    return response.ok(serialize.change_request(change))


@bp.post("/change-requests/<change_request_id>/submit")
def submit_change_request(change_request_id):
    actor = validate.authenticate([FLEET_ENGINEER])
    change = validate.lookup("change_requests", change_request_id)
    if change["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if change["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if change["status"] == "CHANGES_REQUESTED":
        if change["revision_count"] >= compute.REVISION_LIMIT:
            raise ApiError("ERR_REVISION_LIMIT_EXCEEDED")
        change["revision_count"] += 1
    change["status"] = "SUBMITTED"
    change["submitted_by_user_id"] = actor.user_id
    db.touch(change)
    return response.ok(serialize.change_request(change))


@bp.post("/change-requests/<change_request_id>/review-decision")
def review_change_request(change_request_id):
    actor = validate.authenticate([CHANGE_CONTROL_BOARD])
    change = validate.lookup("change_requests", change_request_id)
    body = validate.get_body()
    decision = validate.req_enum(body, "decision", enums.REVIEW_DECISIONS)
    comment = validate.opt_str(body, "review_comment")
    if change["submitted_by_user_id"] is not None and actor.user_id == change["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if change["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if change["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if decision == "APPROVE":
        template = db.store.templates.get(change["template_id"])
        if template is None or template["status"] != "PUBLISHED":
            raise ApiError("ERR_TEMPLATE_NOT_PUBLISHED")
        target_units = 0
        for unit in db.store.units.values():
            if unit["agency_id"] == change["target_agency_id"] and \
                    unit["provision_status"] in compute.BILLABLE_STATUSES:
                target_units += 1
        change["status"] = "APPROVED"
        change["pinned_template_version"] = template["template_version"]
        change["pinned_template_record_version"] = template["version"]
        change["target_unit_count"] = target_units
    elif decision == "REQUEST_CHANGES":
        change["status"] = "CHANGES_REQUESTED"
        change["review_comment"] = comment
    else:
        change["status"] = "REJECTED"
        change["review_comment"] = comment
    change["reviewed_by_user_id"] = actor.user_id
    db.touch(change)
    return response.ok(serialize.change_request(change))


@bp.post("/change-requests/<change_request_id>/deploy")
def deploy_change_request(change_request_id):
    validate.authenticate([FLEET_ENGINEER])
    change = validate.lookup("change_requests", change_request_id)
    if change["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if change["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    template = db.store.templates.get(change["template_id"])
    agency = db.store.agencies.get(change["target_agency_id"])
    if template["encryption_required"]:
        for talkgroup in db.store.talkgroups.values():
            if talkgroup["owner_agency_id"] != change["target_agency_id"]:
                continue
            if talkgroup["status"] not in compute.LIVE_TALKGROUP_STATUSES:
                continue
            site = db.store.sites.get(talkgroup["home_site_id"])
            if site is None or site["coverage_class"] not in ("MISSION_CRITICAL", "GENERAL"):
                raise ApiError("ERR_COVERAGE_CLASS_INSUFFICIENT")
    if template["version"] != change["pinned_template_record_version"]:
        raise ApiError("ERR_TEMPLATE_VERSION_STALE")
    if agency is not None and agency["billing_status"] == "SUSPENDED_FROM_VOTING":
        raise ApiError("ERR_AGENCY_VOTING_SUSPENDED")
    change["status"] = "DEPLOYING"
    change["deployment_started_at"] = db.now()
    deployed = 0
    failed = 0
    for unit in db.sort_rows(compute.agency_units(change["target_agency_id"])):
        if unit["provision_status"] == "ASSIGNED":
            compute.apply_fields(unit, template_id=change["template_id"])
            deployed += 1
        elif unit["provision_status"] == "SUSPENDED":
            failed += 1
    change["deployed_unit_count"] = deployed
    change["failed_unit_count"] = failed
    db.touch(change)
    compute.recompute_template_deployed_count(template)
    if deployed + failed == change["target_unit_count"]:
        change["status"] = "DEPLOYED"
        change["deployed_at"] = db.now()
        db.touch(change)
    return response.ok(serialize.change_request(change))
