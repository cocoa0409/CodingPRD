"""RestrictedUseFile endpoints: create, list (role-filtered), submit-review,
review-decision."""
from flask import Blueprint

import store
from calc import MAX_DISCLOSURE_RISK, disclosure_risk
from errors import raise_err
from serialize import ruf_out
from services import study_has_published_report
from util import new_entity, ok_list, ok_obj, paginate, sort_created, touch
from validation import (ROLE_AGENCY_OFFICER, ROLE_DATA_MANAGER,
                        ROLE_EXTERNAL_RESEARCHER, STAFF_ROLES, authenticate,
                        authorize, check_schema, get_json_body)

bp = Blueprint("restricted_use_files", __name__)


def get_ruf_or_404(file_id):
    ruf = store.restricted_use_files.get(file_id)
    if ruf is None:
        raise_err("ERR_NOT_FOUND", "Restricted-use file not found")
    return ruf


@bp.post("/evaluation/studies/<study_id>/restricted-use-files")
def create_ruf(study_id):
    uid, role = authenticate()
    authorize(role, [ROLE_DATA_MANAGER])
    study = store.studies.get(study_id)
    if study is None:
        raise_err("ERR_NOT_FOUND", "Study not found")
    body = get_json_body()
    check_schema(body, {
        "title": ("str", True),
        "cell_counts": ("arr_int", True),
        "sensitivity_weights": ("arr_num", True),
    })
    counts = body["cell_counts"]
    weights = body["sensitivity_weights"]
    if not counts:
        raise_err("ERR_INVALID_REQUEST", "cell_counts must be non-empty")
    if any(c < 1 for c in counts):
        raise_err("ERR_INVALID_REQUEST",
                  "Every cell count must be an integer >= 1")
    if len(counts) != len(weights):
        raise_err("ERR_INVALID_REQUEST",
                  "sensitivity_weights must have the same length as "
                  "cell_counts")
    if any(not 0 < w <= 1 for w in weights):
        raise_err("ERR_INVALID_REQUEST",
                  "Every sensitivity weight must be in (0, 1]")
    if study["status"] in ("TERMINATED", "COMPLETED"):
        raise_err("ERR_STUDY_INVALID_STATE",
                  "A terminated or completed study accepts no new files")
    if not study_has_published_report(study_id):
        raise_err("ERR_NO_PUBLISHED_REPORT",
                  "The study has no PUBLISHED report yet")
    ruf = new_entity({
        "study_id": study_id,
        "title": body["title"],
        "cell_counts": counts,
        "sensitivity_weights": weights,
        "suppressed_cell_count": None,
        "max_risk": None,
        "mean_risk": None,
        "prepared_by_id": uid,
        "status": "DRAFT",
    })
    store.restricted_use_files[ruf["id"]] = ruf
    return ok_obj(ruf_out(ruf), 201)


@bp.get("/evaluation/studies/<study_id>/restricted-use-files")
def list_rufs(study_id):
    _uid, role = authenticate()
    authorize(role, list(STAFF_ROLES) + [ROLE_EXTERNAL_RESEARCHER])
    if study_id not in store.studies:
        raise_err("ERR_NOT_FOUND", "Study not found")
    items = [f for f in store.restricted_use_files.values()
             if f["study_id"] == study_id]
    if role == ROLE_EXTERNAL_RESEARCHER:
        items = [f for f in items if f["status"] == "RELEASED"]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([ruf_out(f) for f in page], limit, offset, total)


@bp.post("/evaluation/restricted-use-files/<file_id>/submit-review")
def submit_ruf_review(file_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_DATA_MANAGER])
    ruf = get_ruf_or_404(file_id)
    body = get_json_body()
    check_schema(body, {})
    if ruf["status"] not in ("DRAFT", "RISK_REJECTED"):
        raise_err("ERR_RUF_INVALID_STATE",
                  "Only a DRAFT or RISK_REJECTED file can be submitted for "
                  "review")
    suppressed, max_risk, mean_risk = disclosure_risk(
        ruf["cell_counts"], ruf["sensitivity_weights"])
    ruf["suppressed_cell_count"] = suppressed
    ruf["max_risk"] = max_risk
    ruf["mean_risk"] = mean_risk
    ruf["status"] = "DISCLOSURE_REVIEW"
    touch(ruf)
    return ok_obj(ruf_out(ruf))


@bp.post("/evaluation/restricted-use-files/<file_id>/review-decision")
def ruf_review_decision(file_id):
    uid, role = authenticate()
    authorize(role, [ROLE_AGENCY_OFFICER])
    ruf = get_ruf_or_404(file_id)
    body = get_json_body()
    check_schema(body, {"decision": ("enum:APPROVE|REJECT", True)})
    if ruf["status"] != "DISCLOSURE_REVIEW":
        raise_err("ERR_RUF_INVALID_STATE",
                  "Only a file in DISCLOSURE_REVIEW can receive a decision")
    if uid == ruf["prepared_by_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "The decider must differ from the preparer")
    if body["decision"] == "APPROVE":
        if ruf["max_risk"] > MAX_DISCLOSURE_RISK:
            raise_err("ERR_DISCLOSURE_RISK_TOO_HIGH",
                      "max_risk exceeds the release gate")
        ruf["status"] = "RELEASED"
    else:
        ruf["status"] = "RISK_REJECTED"
    touch(ruf)
    return ok_obj(ruf_out(ruf))
