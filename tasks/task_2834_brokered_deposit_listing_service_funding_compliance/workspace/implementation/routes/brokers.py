from flask import Blueprint

import calc
import cascades
import db
import middleware as mw
import response
from errors import ApiError

bp = Blueprint("brokers", __name__)

BROKER_TYPES = ("DEPOSIT_BROKER", "LISTING_SERVICE", "DEPOSIT_PLACEMENT_NETWORK", "AFFILIATE")
FEE_STRUCTURES = ("FLAT_FEE", "BASIS_POINT_FEE", "VOLUME_TIERED", "PER_ACCOUNT_FEE")
DILIGENCE_ACTIONS = ("START_DILIGENCE", "ISSUE_RFI", "RESUME_DILIGENCE", "APPROVE",
                     "REJECT", "SUSPEND", "TERMINATE")

READ_ROLES = ("SystemAdmin", "FundingDeskOfficer", "ComplianceReviewer",
              "TreasuryController", "Examiner")
READ_ROLES_REP = READ_ROLES + ("BrokerRepresentative",)


def find_broker(broker_id):
    record = db.brokers.get(broker_id)
    if record is None:
        raise ApiError("ERR_BROKER_NOT_FOUND")
    return record


def find_agreement(agreement_id):
    record = db.broker_agreements.get(agreement_id)
    if record is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND")
    return record


@bp.post("/brokers")
def create_broker():
    mw.auth("SystemAdmin", "FundingDeskOfficer")
    data = mw.body()
    record = {
        "legal_name": mw.req_str(data, "legal_name"),
        "broker_type": mw.req_enum(data, "broker_type", BROKER_TYPES),
        "has_placement_discretion": mw.req_bool(data, "has_placement_discretion"),
        "fee_structure": mw.req_enum(data, "fee_structure", FEE_STRUCTURES),
        "fee_bps": mw.opt_int(data, "fee_bps", 0, minimum=0),
        "fee_flat_cents": mw.opt_int(data, "fee_flat_cents", 0, minimum=0),
        "diligence_status": "NOT_STARTED",
        "approved_agreement_count": 0,
    }
    db.stamp_new(record)
    db.brokers[record["id"]] = record
    return response.created(db.public(record))


@bp.get("/brokers/<broker_id>")
def read_broker(broker_id):
    user_id, role = mw.auth(*READ_ROLES_REP)
    if role == "BrokerRepresentative" and user_id != broker_id:
        raise ApiError("ERR_UNAUTHORIZED")
    return response.ok(db.public(find_broker(broker_id)))


@bp.get("/brokers")
def list_brokers():
    mw.auth(*READ_ROLES)
    limit, offset = mw.page()
    rows = list(db.brokers.values())
    broker_type = mw.q("broker_type")
    if broker_type is not None:
        rows = [r for r in rows if r["broker_type"] == broker_type]
    diligence_status = mw.q("diligence_status") or mw.q("registration_status")
    if diligence_status is not None:
        rows = [r for r in rows if r["diligence_status"] == diligence_status]
    rows.sort(key=lambda r: (r["created_at"], r["legal_name"], r["_seq"]))
    return response.listing(db.public_list(rows), limit, offset)


@bp.post("/brokers/<broker_id>/agreements")
def create_agreement(broker_id):
    user_id, _role = mw.auth("SystemAdmin", "FundingDeskOfficer")
    find_broker(broker_id)
    data = mw.body()
    agreement_ref = mw.req_str(data, "agreement_ref")
    record = {
        "broker_id": broker_id,
        "agreement_ref": agreement_ref,
        "status": "DRAFT",
        "fee_structure": mw.req_enum(data, "fee_structure", FEE_STRUCTURES),
        "fee_bps": mw.opt_int(data, "fee_bps", 0, minimum=0),
        "fee_flat_cents": mw.opt_int(data, "fee_flat_cents", 0, minimum=0),
        "termination_notice_days": mw.req_int(data, "termination_notice_days", minimum=0),
        "effective_date": mw.req_date(data, "effective_date"),
        "aml_program_score": mw.req_int(data, "aml_program_score", minimum=0, maximum=100),
        "financial_condition_score": mw.req_int(data, "financial_condition_score",
                                               minimum=0, maximum=100),
        "insurance_coverage_score": mw.req_int(data, "insurance_coverage_score",
                                              minimum=0, maximum=100),
        "recordkeeping_score": mw.req_int(data, "recordkeeping_score",
                                         minimum=0, maximum=100),
        "diligence_score": 0,
        "rfi_round_count": 0,
        "accrued_fee_cents": 0,
        "prepared_by_user_id": user_id,
        "reviewed_by_user_id": None,
    }
    for existing in db.broker_agreements.values():
        if existing["broker_id"] == broker_id and existing["agreement_ref"] == agreement_ref:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "agreement_ref is already used by this counterparty.")
    db.stamp_new(record)
    db.broker_agreements[record["id"]] = record
    return response.created(db.public(record))


@bp.get("/brokers/<broker_id>/agreements")
def list_agreements(broker_id):
    user_id, role = mw.auth(*READ_ROLES_REP)
    if role == "BrokerRepresentative" and user_id != broker_id:
        raise ApiError("ERR_UNAUTHORIZED")
    find_broker(broker_id)
    limit, offset = mw.page()
    rows = [r for r in db.broker_agreements.values() if r["broker_id"] == broker_id]
    status = mw.q("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.listing(db.public_list(db.by_created(rows)), limit, offset)


@bp.get("/broker-agreements/<agreement_id>")
def read_agreement(agreement_id):
    user_id, role = mw.auth(*READ_ROLES_REP)
    agreement = find_agreement(agreement_id)
    if role == "BrokerRepresentative" and user_id != agreement["broker_id"]:
        raise ApiError("ERR_UNAUTHORIZED")
    return response.ok(db.public(agreement))


@bp.get("/broker-agreements/<agreement_id>/fee-summary")
def fee_summary(agreement_id):
    user_id, role = mw.auth("SystemAdmin", "FundingDeskOfficer", "TreasuryController",
                            "Examiner", "BrokerRepresentative")
    agreement = find_agreement(agreement_id)
    if role == "BrokerRepresentative" and user_id != agreement["broker_id"]:
        raise ApiError("ERR_UNAUTHORIZED")
    lines, fees, total = calc.fee_lines(agreement)
    return response.ok({
        "agreement_id": agreement["id"],
        "fee_structure": agreement["fee_structure"],
        "line_count": len(lines),
        "accrued_fee_cents": total,
        "line_fee_cents": fees,
        "line_placement_ids": [p["id"] for p in lines],
    })


def _set_broker_status(broker, status, delta=0):
    changed = False
    if broker["diligence_status"] != status:
        broker["diligence_status"] = status
        changed = True
    if delta:
        broker["approved_agreement_count"] = max(
            0, broker["approved_agreement_count"] + delta)
        changed = True
    if changed:
        db.bump(broker)


@bp.post("/broker-agreements/<agreement_id>/diligence-actions")
def diligence_action(agreement_id):
    user_id, _role = mw.auth("SystemAdmin", "FundingDeskOfficer", "ComplianceReviewer")
    agreement = find_agreement(agreement_id)
    data = mw.body()
    action = mw.req_enum(data, "action", DILIGENCE_ACTIONS)
    mw.opt_str(data, "note")
    status = agreement["status"]
    broker = db.brokers.get(agreement["broker_id"])

    if action == "START_DILIGENCE":
        if status != "DRAFT":
            raise ApiError("ERR_AGREEMENT_STATE_INVALID")
        agreement["status"] = "UNDER_DILIGENCE"
        agreement["diligence_score"] = calc.diligence_score(agreement)
        agreement["reviewed_by_user_id"] = user_id
        db.bump(agreement)
        _set_broker_status(broker, "IN_DILIGENCE")

    elif action == "ISSUE_RFI":
        if status != "UNDER_DILIGENCE":
            raise ApiError("ERR_AGREEMENT_STATE_INVALID")
        if agreement["rfi_round_count"] >= calc.MAX_RFI_ROUNDS:
            raise ApiError("ERR_REVIEW_ROUND_LIMIT")
        agreement["status"] = "RFI_ISSUED"
        agreement["rfi_round_count"] += 1
        agreement["reviewed_by_user_id"] = user_id
        db.bump(agreement)

    elif action == "RESUME_DILIGENCE":
        if status not in ("RFI_ISSUED", "SUSPENDED"):
            raise ApiError("ERR_AGREEMENT_STATE_INVALID")
        agreement["status"] = "UNDER_DILIGENCE"
        agreement["diligence_score"] = calc.diligence_score(agreement)
        db.bump(agreement)
        if status == "SUSPENDED":
            _set_broker_status(broker, "IN_DILIGENCE")

    elif action == "APPROVE":
        if status != "UNDER_DILIGENCE":
            raise ApiError("ERR_AGREEMENT_STATE_INVALID")
        if user_id == agreement["prepared_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        score = agreement["diligence_score"]
        if agreement["aml_program_score"] < calc.AML_FLOOR \
                or score < calc.DILIGENCE_CONDITIONAL_MIN:
            raise ApiError("ERR_DILIGENCE_SCORE_INSUFFICIENT")
        target = "APPROVED" if score >= calc.DILIGENCE_APPROVE_MIN else "CONDITIONAL"
        agreement["status"] = target
        db.bump(agreement)
        _set_broker_status(broker, target, delta=1)

    elif action == "REJECT":
        if status != "UNDER_DILIGENCE":
            raise ApiError("ERR_AGREEMENT_STATE_INVALID")
        if user_id == agreement["prepared_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        agreement["status"] = "REJECTED"
        db.bump(agreement)
        _set_broker_status(broker, "REJECTED")

    elif action == "SUSPEND":
        if status not in ("APPROVED", "CONDITIONAL"):
            raise ApiError("ERR_AGREEMENT_STATE_INVALID")
        agreement["status"] = "SUSPENDED"
        db.bump(agreement)
        _set_broker_status(broker, "SUSPENDED", delta=-1)
        cascades.suspend_programs_for_agreement(agreement)

    else:  # TERMINATE
        if status != "SUSPENDED":
            raise ApiError("ERR_AGREEMENT_STATE_INVALID")
        agreement["status"] = "TERMINATED"
        db.bump(agreement)
        cascades.close_programs_for_agreement(agreement)

    return response.ok(db.public(agreement))
