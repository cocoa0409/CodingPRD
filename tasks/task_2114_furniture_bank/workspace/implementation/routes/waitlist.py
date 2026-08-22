"""The unmet-need waitlist and the board report (PRD 3.6)."""

from flask import Blueprint, request

from auth import authenticate, resolve
from db import db, serialize
from envelope import object_response
from routes._common import filtered, respond_list
from services.report import unmet_need_report
from validation import pagination_params

bp = Blueprint("waitlist", __name__)


@bp.route("/waitlist-entries/<entry_id>", methods=["GET"])
def get_waitlist_entry(entry_id):
    authenticate(["PlatformAdmin", "CaseManager", "WarehouseLead"])
    entry = resolve("waitlist_entry", entry_id)
    return object_response(serialize(entry))


@bp.route("/waitlist-entries", methods=["GET"])
def list_waitlist_entries():
    authenticate(["PlatformAdmin", "CaseManager", "WarehouseLead"])
    limit, offset = pagination_params()
    rows = filtered(list(db.waitlist_entries.values()), {
        "voucher_line_id": "voucher_line_id",
        "client_id": "client_id",
        "status": "status",
        "category": "category",
        "county": "county",
    })
    return respond_list(rows, limit, offset)


@bp.route("/reports/unmet-need", methods=["GET"])
def report_unmet_need():
    authenticate(["PlatformAdmin", "CaseManager"])
    county = request.args.get("county")
    category = request.args.get("category")
    return object_response(unmet_need_report(county, category))
