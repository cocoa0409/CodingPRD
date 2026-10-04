"""TransferApplication endpoints -- resale, transfer and reallocation
(PRD 3.9, 3.11).

POST /franchise/transfer-applications, GET /franchise/transfer-applications[/{id}]
POST /franchise/transfer-applications/{id}/begin-review|request-revision|revise|approve|reject|close|withdraw
GET /franchise/territory-assignments[/{id}]
"""
from flask import Blueprint

import cascades
import derived
from auth import guard
from config import TRANSFER_KINDS, TRANSFER_OPEN_SET
from errors import ApiError
from fetch import (
    get_agreement,
    get_assignment,
    get_franchisee,
    get_territory,
    get_transfer,
    paged,
    synthesize_assignment,
)
from response import created, ok
from store import common_fields, db, touch
from validate import (
    body,
    opt_id_list,
    opt_money,
    opt_str,
    reject_unknown,
    req_enum,
    req_id,
    req_int,
    req_str,
)
from calculations import transfer_fee
from money import as_number

bp = Blueprint("transfers", __name__)

CREATE_INPUT = [
    "agreement_id", "territory_id", "applicant_franchisee_id", "transfer_kind",
    "purchase_price_cents", "target_territory_ids",
]


def _started_application(application_id):
    application = get_transfer(application_id)
    if application.get("status") in ("CLOSED", "REJECTED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    return application


def _require_status(application, allowed):
    if application.get("status") not in allowed:
        raise ApiError("ERR_INVALID_STATE")


def _submitting_franchisee(application):
    agreement = db.agreements.get(application.get("agreement_id"))
    return (agreement or {}).get("franchisee_id")


def _principal_of(franchisee_id):
    franchisee = db.franchisees.get(franchisee_id)
    return (franchisee or {}).get("principal_name")


@bp.post("/franchise/transfer-applications")
def create_application():
    uid, role = guard(["FranchiseeOperator"])
    b = body()
    reject_unknown(b, CREATE_INPUT)
    agreement_id = req_id(b, "agreement_id")
    territory_id = req_id(b, "territory_id")
    applicant_id = req_id(b, "applicant_franchisee_id")
    transfer_kind = req_enum(b, "transfer_kind", TRANSFER_KINDS)
    purchase_price = req_int(b, "purchase_price_cents", minimum=0)
    target_ids = opt_id_list(b, "target_territory_ids", default=[])

    # Body foreign keys resolve in the order the input list declares them.
    agreement = get_agreement(agreement_id)
    get_territory(territory_id)
    get_franchisee(applicant_id)

    # Ownership precedes the state rung.
    if role == "FranchiseeOperator" and uid != agreement.get("franchisee_id"):
        raise ApiError("ERR_UNAUTHORIZED")
    if agreement.get("lifecycle_status") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    for target_id in target_ids:
        get_territory(target_id)

    conflict = [
        a for a in db.transfer_applications.values()
        if a.get("agreement_id") == agreement_id and a.get("status") in TRANSFER_OPEN_SET
    ]
    if conflict:
        raise ApiError("ERR_TRANSFER_ALREADY_PENDING")

    record = common_fields()
    record.update({
        "_kind": "TransferApplication",
        "agreement_id": agreement_id,
        "territory_id": territory_id,
        "applicant_franchisee_id": applicant_id,
        "transfer_kind": transfer_kind,
        "purchase_price_cents": purchase_price,
        "target_territory_ids": list(target_ids),
        "transfer_fee_cents": 0,
        "reviewer_operator_id": None,
        "approval_operator_id": None,
        "reason": None,
        "status": "SUBMITTED",
    })
    db.transfer_applications[record["id"]] = record

    # The target agreement leaves the live set while the disposition is open.
    agreement["lifecycle_status"] = "TRANSFER_PENDING"
    touch(agreement)
    cascades.recompute_franchisee(db.franchisees.get(agreement.get("franchisee_id")))
    return created(record)


@bp.get("/franchise/transfer-applications/<application_id>")
def read_application(application_id):
    guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    return ok(get_transfer(application_id))


@bp.get("/franchise/transfer-applications")
def list_applications():
    guard(["FranchiseAdmin", "ComplianceAuditor"])
    return paged(
        db.transfer_applications,
        "agreement_id", "applicant_franchisee_id", "territory_id", "status",
    )


@bp.post("/franchise/transfer-applications/<application_id>/begin-review")
def begin_review(application_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["reviewer_operator_id"])
    reviewer = req_str(b, "reviewer_operator_id")
    application = _started_application(application_id)
    _require_status(application, ["SUBMITTED"])
    if reviewer == _principal_of(_submitting_franchisee(application)):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    application["reviewer_operator_id"] = reviewer
    application["status"] = "UNDER_REVIEW"
    touch(application)
    return ok(application)


@bp.post("/franchise/transfer-applications/<application_id>/request-revision")
def request_revision(application_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["reason"])
    reason = req_str(b, "reason")
    application = _started_application(application_id)
    _require_status(application, ["UNDER_REVIEW"])
    application["reason"] = reason
    application["status"] = "REVISION_REQUESTED"
    touch(application)
    return ok(application)


@bp.post("/franchise/transfer-applications/<application_id>/revise")
def revise_application(application_id):
    uid, role = guard(["FranchiseeOperator"])
    b = body()
    reject_unknown(b, ["purchase_price_cents"])
    purchase_price = req_int(b, "purchase_price_cents", minimum=0)
    application = _started_application(application_id)
    _require_status(application, ["REVISION_REQUESTED"])
    if role == "FranchiseeOperator" and uid != _submitting_franchisee(application):
        raise ApiError("ERR_UNAUTHORIZED")
    application["purchase_price_cents"] = purchase_price
    application["reason"] = None
    application["status"] = "UNDER_REVIEW"
    touch(application)
    return ok(application)


@bp.post("/franchise/transfer-applications/<application_id>/approve")
def approve_application(application_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["approval_operator_id"])
    approver = b.get("approval_operator_id")
    application = _started_application(application_id)
    _require_status(application, ["UNDER_REVIEW"])
    if approver is None or not isinstance(approver, str) or not approver:
        raise ApiError("ERR_APPROVER_REQUIRED")
    if approver == application.get("reviewer_operator_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    agreement = get_agreement(application.get("agreement_id"))
    derived.refresh_agreement(agreement)
    if int(agreement.get("open_remediation_count") or 0) != 0:
        raise ApiError("ERR_OPEN_REMEDIATION")
    if agreement.get("standards_status") == "DEFAULT":
        raise ApiError("ERR_STANDARDS_DEFAULTED")

    application["approval_operator_id"] = approver
    application["transfer_fee_cents"] = transfer_fee(application)
    application["status"] = "APPROVED"
    touch(application)
    return ok(application)


@bp.post("/franchise/transfer-applications/<application_id>/reject")
def reject_application(application_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["reason"])
    reason = req_str(b, "reason")
    application = _started_application(application_id)
    _require_status(application, ["UNDER_REVIEW", "TRANSFER_PENDING"])
    application["reason"] = reason
    application["status"] = "REJECTED"
    touch(application)
    _revert_agreement(application)
    return ok(application)


def _revert_agreement(application):
    agreement = db.agreements.get(application.get("agreement_id"))
    if agreement is None:
        return
    if agreement.get("lifecycle_status") in ("TRANSFER_PENDING", "RENEWAL_PENDING"):
        agreement["lifecycle_status"] = "ACTIVE"
        touch(agreement)
    cascades.recompute_franchisee(db.franchisees.get(agreement.get("franchisee_id")))


@bp.post("/franchise/transfer-applications/<application_id>/withdraw")
def withdraw_application(application_id):
    uid, role = guard(["FranchiseeOperator"])
    b = body()
    reject_unknown(b, [])
    application = _started_application(application_id)
    _require_status(application, ["SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED"])
    if role == "FranchiseeOperator" and uid != _submitting_franchisee(application):
        raise ApiError("ERR_UNAUTHORIZED")
    application["status"] = "CLOSED"
    touch(application)
    _revert_agreement(application)
    return ok(application)


@bp.post("/franchise/transfer-applications/<application_id>/close")
def close_application(application_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    application = _started_application(application_id)
    _require_status(application, ["APPROVED"])

    reviewer = application.get("reviewer_operator_id")
    approver = application.get("approval_operator_id")
    if not approver or not reviewer or approver == reviewer:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    agreement = get_agreement(application.get("agreement_id"))
    derived.refresh_agreement(agreement)
    if int(agreement.get("open_remediation_count") or 0) != 0:
        raise ApiError("ERR_OPEN_REMEDIATION")

    outgoing_franchisee_id = agreement.get("franchisee_id")
    territory = get_territory(application.get("territory_id"))
    applicant_id = application.get("applicant_franchisee_id")

    territory["franchisee_id"] = applicant_id
    touch(territory)

    agreement["lifecycle_status"] = "TERMINATED"
    touch(agreement)

    cascades.terminate_transfer_assignments(territory["id"])
    synthesize_assignment(territory["id"], applicant_id, agreement["id"],
                          application.get("transfer_kind"))

    if application.get("transfer_kind") == "TERRITORY_REALLOCATION":
        for target_id in application.get("target_territory_ids") or []:
            target = db.territories.get(target_id)
            if target is None:
                continue
            target["franchisee_id"] = applicant_id
            target["status"] = "AWARDED"
            derived.refresh_territory(target)
            touch(target)

    application["status"] = "CLOSED"
    touch(application)

    cascades.recompute_franchisee(db.franchisees.get(outgoing_franchisee_id))
    cascades.recompute_franchisee(db.franchisees.get(applicant_id))
    return ok(application)


# ---------------------------------------------------------------------------
# TerritoryAssignment reads
# ---------------------------------------------------------------------------
@bp.get("/franchise/territory-assignments/<assignment_id>")
def read_assignment(assignment_id):
    guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    assignment = get_assignment(assignment_id)
    derived.refresh_assignment(assignment)
    return ok(assignment)


@bp.get("/franchise/territory-assignments")
def list_assignments():
    guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    records = list(db.territory_assignments.values())
    for assignment in records:
        derived.refresh_assignment(assignment)
    return paged(
        db.territory_assignments,
        "territory_id", "franchisee_id", "source_agreement_id", "active",
        rows=records,
    )