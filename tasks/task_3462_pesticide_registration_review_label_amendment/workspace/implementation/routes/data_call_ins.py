"""Data call-ins (PRD 3.7): issuance, obligation ledger, responses."""
from flask import Blueprint

import clock
import constants
from auth import require_auth, require_role
from db import new_row, store, touch
from envelope import ok
from errors import err
from services.dci import compute_ledger, reconcile_after_change
from validate import (
    as_datetime,
    as_list,
    as_str,
    parse_body,
    reject_unknown,
)

bp = Blueprint("data_call_ins", __name__)


def get_dci_or_404(dci_id):
    dci = store["dcis"].get(dci_id)
    if dci is None:
        err("ERR_NOT_FOUND", "Data call-in %s does not exist." % dci_id)
    return dci


def _with_ledger(dci):
    row = dict(dci)
    row.update(compute_ledger(dci))
    return row


@bp.post("/data-call-ins")
def create_dci():
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRATION_REVIEWER])
    data = parse_body()
    reject_unknown(data, ["review_case_id", "required_study_types", "response_deadline"])
    review_case_id = as_str(data, "review_case_id", required=True)
    required_study_types = as_list(data, "required_study_types", required=True)
    if not required_study_types:
        err("ERR_INVALID_REQUEST", "required_study_types must be a non-empty array.")
    for study_type in required_study_types:
        if study_type not in constants.STUDY_TYPES:
            err(
                "ERR_INVALID_REQUEST",
                "required_study_types entries must be study types; got %r." % study_type,
            )
    response_deadline = as_datetime(data, "response_deadline", required=True)

    case = store["review_cases"].get(review_case_id)
    if case is None:
        err("ERR_NOT_FOUND", "Registration review case %s does not exist." % review_case_id)

    # Stage 7: the case must be OPEN or UNDER_REVIEW.
    if case["status"] not in ("OPEN", "UNDER_REVIEW"):
        err("ERR_CASE_NOT_OPEN", "The case is not OPEN or UNDER_REVIEW.")

    # The deadline must be strictly in the future.
    if response_deadline <= clock.now():
        err("ERR_INVALID_REQUEST", "response_deadline must be strictly after the logical clock.")

    # De-duplicate preserving order; the ledger partitions these as sets.
    seen = set()
    required = []
    for study_type in required_study_types:
        if study_type not in seen:
            seen.add(study_type)
            required.append(study_type)

    row = new_row()
    row.update(
        {
            "review_case_id": review_case_id,
            "required_study_types": required,
            "response_deadline": response_deadline,
            "status": "ISSUED",
            "issued_at": clock.now(),
            "responded_at": None,
        }
    )
    store["dcis"][row["id"]] = row

    case["status"] = "DCI_PENDING"
    touch(case)
    return ok(_with_ledger(row), status=201)


@bp.get("/data-call-ins/<dci_id>")
def get_dci(dci_id):
    require_auth()
    return ok(_with_ledger(get_dci_or_404(dci_id)))


@bp.post("/data-call-ins/<dci_id>/respond")
def respond_dci(dci_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRANT_REPRESENTATIVE])
    data = parse_body()
    reject_unknown(data, ["study_submission_ids"])
    study_submission_ids = as_list(data, "study_submission_ids", required=True)
    for sid in study_submission_ids:
        if not isinstance(sid, str):
            err("ERR_INVALID_REQUEST", "study_submission_ids must be an array of strings.")

    dci = get_dci_or_404(dci_id)
    case = store["review_cases"][dci["review_case_id"]]
    product = store["products"][case["product_id"]]

    # Stage 5: only the owning registrant may respond.
    if product["registrant_ref"] != caller["user_id"]:
        err("ERR_NOT_RESOURCE_OWNER", "The data call-in belongs to another registrant's product.")

    # Stage 7: only a SATISFIED call-in refuses further response.
    if dci["status"] == "SATISFIED":
        err("ERR_DCI_NOT_RESPONDABLE", "The data call-in is already SATISFIED.")

    # Every id must exist and already bear this call-in's data_call_in_id on
    # the caller's product — any mismatch fails ERR_STUDY_PARENT_MISMATCH.
    for sid in study_submission_ids:
        study = store["studies"].get(sid)
        if study is None or study.get("data_call_in_id") != dci_id:
            err(
                "ERR_STUDY_PARENT_MISMATCH",
                "Every study id must exist and be linked to this data call-in.",
            )

    dci["responded_at"] = clock.now()
    dci["status"] = "RESPONDED"
    touch(dci)
    reconcile_after_change(dci)
    return ok(_with_ledger(dci))
