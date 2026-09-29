"""Fundraising pledge collection, refund and the allocation waterfall (PRD section 3.6)."""

from flask import Blueprint

import calc
import validate as v
from auth import authenticate
from envelope import object_response
from errors import ApiError
from store import parse_date, public, store

bp = Blueprint("pledges", __name__)

PLEDGE_READ_ROLES = [
    "ManufacturerAdmin",
    "ComplianceOfficer",
    "DesignConsultant",
    "ClientRepresentative",
]
UNCOLLECTABLE_DESIGN_STATUSES = ("CANCELLED", "AUDITED")
COMMITTED_DESIGN_STATUSES = ("ORDERED", "INSTALLED", "AUDITED")


@bp.route("/playground/pledges/<pledge_id>", methods=["GET"])
def get_pledge(pledge_id):
    authenticate(PLEDGE_READ_ROLES)
    return object_response(public(store.require("pledge", pledge_id)))


@bp.route("/playground/pledges/<pledge_id>/collect", methods=["POST"])
def collect_pledge(pledge_id):
    authenticate(["ClientRepresentative"])
    pledge = store.require("pledge", pledge_id)
    project = store.require("project", pledge["project_id"])

    if pledge["status"] != "PLEDGED":
        raise ApiError("ERR_PLEDGE_INVALID_STATE")
    if store.clock.today() > parse_date(project["fundraising_deadline"]):
        raise ApiError("ERR_FUNDRAISING_DEADLINE_PASSED")
    if project["design_status"] in UNCOLLECTABLE_DESIGN_STATUSES:
        raise ApiError("ERR_PROJECT_NOT_FUNDABLE")

    pledge["status"] = "COLLECTED"
    store.touch(pledge)
    calc.recompute_fundraising(project)
    store.touch(project)
    return object_response(public(pledge))


@bp.route("/playground/pledges/<pledge_id>/refund", methods=["POST"])
def refund_pledge(pledge_id):
    authenticate(["ClientRepresentative"])
    pledge = store.require("pledge", pledge_id)
    project = store.require("project", pledge["project_id"])

    if pledge["status"] not in ("PLEDGED", "COLLECTED"):
        raise ApiError("ERR_PLEDGE_INVALID_STATE")
    if project["design_status"] in COMMITTED_DESIGN_STATUSES:
        raise ApiError("ERR_FUNDS_ALREADY_COMMITTED")

    was_collected = pledge["status"] == "COLLECTED"
    pledge["status"] = "REFUNDED"
    store.touch(pledge)
    if was_collected:
        # A merely PLEDGED pledge never entered the project's money, so only a
        # collected pledge's refund touches the project row.
        calc.recompute_fundraising(project)
        store.touch(project)
    return object_response(public(pledge))
