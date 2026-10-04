"""DomesticContentReport endpoints (PRD 3.6): create (OCC-guarded) and list."""
from flask import Blueprint, request

import cascade
import constants
import serializers
from errors import ApiError
from middleware import require_roles
from response import ok_obj, list_response
from state import DB, sorted_items
from validation import body, req_enum, req_int
from routes_runs import get_run

bp = Blueprint("reports", __name__)


@bp.post("/footwear/production-runs/<rid>/content-reports")
@require_roles("ProductionPlanner")
def create_content_report(rid, _uid, _role):
    run = get_run(rid)
    # Family 5 (schema): variant and the non-optional OCC field.
    b = body()
    variant = req_enum(b, "variant", constants.REPORT_VARIANTS)
    expected = req_int(b, "expected_run_version")
    # Family 6 (state): CERTIFIED requires COMPLETED; PROVISIONAL is allowed in
    # any state other than CANCELLED.
    if variant == "CERTIFIED" and run["status"] != "COMPLETED":
        raise ApiError("ERR_RUN_NOT_COMPLETED", "a CERTIFIED report requires a COMPLETED run")
    if variant == "PROVISIONAL" and run["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", "cannot report on a CANCELLED run")
    # Family 12 (OCC) is the final gate.
    if expected != run["version"]:
        raise ApiError(
            "ERR_STALE_RUN_VERSION",
            "expected_run_version does not match the run's current version",
        )
    rep = cascade.create_report_record(run, variant)
    return ok_obj(serializers.pub(rep), 201)


@bp.get("/footwear/production-runs/<rid>/content-reports")
@require_roles(*constants.ALL_ROLES)
def list_content_reports(rid, _uid, _role):
    run = get_run(rid)
    items = [r for r in sorted_items(DB["reports"]) if r["run_id"] == run["id"]]
    variant = request.args.get("variant")
    status = request.args.get("status")
    if variant is not None:
        items = [r for r in items if r["variant"] == variant]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response([serializers.pub(r) for r in items])
