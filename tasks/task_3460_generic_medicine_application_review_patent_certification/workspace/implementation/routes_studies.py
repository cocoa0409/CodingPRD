"""Bioequivalence studies (PRD 3.3): per-study round-first adequacy."""
from flask import Blueprint, request

from auth import ALL_ROLES, auth, own_application, require_role
from domain import be_is_adequate
from envelope import sort_default, success_list, success_object
from errors import fail
from serialize import study
from state import STORE, create_entity, get
from validate import body, req_enum, req_number, req_str

bp = Blueprint("studies", __name__)


@bp.post("/generic-drug-review/applications/<app_id>/bioequivalence-studies")
def create_study(app_id):
    uid, role = auth()
    require_role(role, ["ApplicantSponsor"])
    app = get("applications", app_id)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    own_application(uid, app)
    b = body()
    fields = {
        "study_type": req_enum(b, "study_type", ("FASTING", "FED")),
        "analyte": req_str(b, "analyte"),
        "auc_ratio_pct": req_number(b, "auc_ratio_pct"),
        "auc_ci_low_pct": req_number(b, "auc_ci_low_pct"),
        "auc_ci_high_pct": req_number(b, "auc_ci_high_pct"),
        "cmax_ratio_pct": req_number(b, "cmax_ratio_pct"),
        "cmax_ci_low_pct": req_number(b, "cmax_ci_low_pct"),
        "cmax_ci_high_pct": req_number(b, "cmax_ci_high_pct"),
    }
    if app["status"] not in ("DRAFT", "RECEIVED"):
        fail("ERR_INVALID_STATE",
             "Studies may be submitted only while DRAFT or RECEIVED")
    # The server alone computes is_adequate; any client-supplied verdict is
    # ignored. Status is fixed at creation and never changes.
    adequate = be_is_adequate(fields)
    ent = create_entity("studies", dict(fields, **{
        "application_id": app_id,
        "is_adequate": adequate,
        "status": "ACCEPTED" if adequate else "DEFICIENT",
    }))
    return success_object(study(ent), 201)


@bp.get("/generic-drug-review/applications/<app_id>/bioequivalence-studies")
def list_studies(app_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    if get("applications", app_id) is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    items = [s for s in STORE["studies"].values()
             if s["application_id"] == app_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return success_list([study(s) for s in sort_default(items)])
