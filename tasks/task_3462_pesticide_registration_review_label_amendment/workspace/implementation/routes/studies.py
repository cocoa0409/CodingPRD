"""Study submissions (PRD 3.3): exactly one parent, conditional residue fields,
assessor decisions driving the DCI obligation ledger."""
from flask import Blueprint, request

import clock
import constants
from auth import require_auth, require_role
from db import new_row, store, touch
from envelope import ok, ok_list
from errors import err
from services.dci import reconcile_after_change
from validate import (
    as_enum,
    as_num,
    as_str,
    paginate,
    parse_body,
    reject_unknown,
)

bp = Blueprint("studies", __name__)


def get_study_or_404(study_id):
    study = store["studies"].get(study_id)
    if study is None:
        err("ERR_NOT_FOUND", "Study submission %s does not exist." % study_id)
    return study


def _product_of_study(study):
    if study.get("application_id"):
        application = store["applications"][study["application_id"]]
        return store["products"][application["product_id"]]
    dci = store["dcis"][study["data_call_in_id"]]
    case = store["review_cases"][dci["review_case_id"]]
    return store["products"][case["product_id"]]


@bp.post("/study-submissions")
def create_study():
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRANT_REPRESENTATIVE])
    data = parse_body()
    reject_unknown(
        data,
        [
            "application_id",
            "data_call_in_id",
            "study_type",
            "guideline_reference",
            "commodity_code",
            "field_trial_residue_ppm",
        ],
    )
    application_id = as_str(data, "application_id", required=False)
    data_call_in_id = as_str(data, "data_call_in_id", required=False)
    # Study parent XOR: exactly one of application_id / data_call_in_id.
    if (application_id is None) == (data_call_in_id is None):
        err(
            "ERR_INVALID_REQUEST",
            "Exactly one of application_id and data_call_in_id must be supplied.",
        )
    study_type = as_enum(data, "study_type", constants.STUDY_TYPES, required=True)
    guideline_reference = as_str(data, "guideline_reference", required=True)
    commodity_code = as_str(data, "commodity_code", required=False)
    residue = as_num(
        data, "field_trial_residue_ppm", required=False, minimum=0
    )
    # commodity_code + field_trial_residue_ppm exactly when RESIDUE_CHEMISTRY.
    if study_type == "RESIDUE_CHEMISTRY":
        if commodity_code is None or residue is None:
            err(
                "ERR_INVALID_REQUEST",
                "commodity_code and field_trial_residue_ppm are required for RESIDUE_CHEMISTRY.",
            )
    else:
        if commodity_code is not None or residue is not None:
            err(
                "ERR_INVALID_REQUEST",
                "commodity_code and field_trial_residue_ppm are only allowed for RESIDUE_CHEMISTRY.",
            )

    # Stage 4: parent existence.
    application = None
    dci = None
    if application_id is not None:
        application = store["applications"].get(application_id)
        if application is None:
            err("ERR_APPLICATION_NOT_FOUND", "Application %s does not exist." % application_id)
        product = store["products"][application["product_id"]]
    else:
        dci = store["dcis"].get(data_call_in_id)
        if dci is None:
            err("ERR_NOT_FOUND", "Data call-in %s does not exist." % data_call_in_id)
        case = store["review_cases"][dci["review_case_id"]]
        product = store["products"][case["product_id"]]

    # Stage 5/10: the parent must belong to a product the caller owns.
    if product["registrant_ref"] != caller["user_id"]:
        err(
            "ERR_STUDY_PARENT_MISMATCH",
            "The study's parent does not belong to a product of the acting registrant.",
        )

    # Stage 7: application-parent studies only while the application is open.
    if application is not None and application["status"] not in (
        "DRAFT",
        "IN_REVIEW",
        "DATA_DEFICIENCY",
    ):
        err(
            "ERR_APPLICATION_ALREADY_DECIDED",
            "Studies cannot be filed against a decided application.",
        )

    # Stage 10: commodity must be known to the dietary model.
    if commodity_code is not None and commodity_code not in constants.CONSUMPTION_G_DAY:
        err("ERR_UNKNOWN_COMMODITY", "Unknown commodity_code %s." % commodity_code)

    row = new_row()
    row.update(
        {
            "application_id": application_id,
            "data_call_in_id": data_call_in_id,
            "study_type": study_type,
            "guideline_reference": guideline_reference,
            "commodity_code": commodity_code,
            "field_trial_residue_ppm": residue,
            "status": "RECEIVED",
            "submitted_by_ref": caller["user_id"],
            "decided_by_ref": None,
            "decided_at": None,
        }
    )
    store["studies"][row["id"]] = row
    return ok(row, status=201)


@bp.get("/study-submissions")
def list_studies():
    require_auth()
    rows = list(store["studies"].values())
    for key in ("application_id", "data_call_in_id", "study_type", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.get("/study-submissions/<study_id>")
def get_study(study_id):
    require_auth()
    return ok(get_study_or_404(study_id))


@bp.post("/study-submissions/<study_id>/review-decisions")
def decide_study(study_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_RISK_ASSESSOR])
    data = parse_body()
    reject_unknown(data, ["decision", "decision_notes"])
    decision = as_enum(data, "decision", ["ACCEPT", "REJECT"], required=True)
    if "decision_notes" in data and data["decision_notes"] is not None:
        as_str(data, "decision_notes")

    study = get_study_or_404(study_id)
    if study["status"] != "RECEIVED":
        err("ERR_STUDY_NOT_DECIDABLE", "The study is not RECEIVED.")

    now = clock.now()
    study["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    study["decided_by_ref"] = caller["user_id"]
    study["decided_at"] = now
    touch(study)

    dci_id = study.get("data_call_in_id")
    if dci_id:
        dci = store["dcis"][dci_id]
        if decision == "ACCEPT":
            reconcile_after_change(dci)
        elif dci["status"] == "RESPONDED":
            dci["status"] = "DEFICIENT"
            touch(dci)
    return ok(study)
