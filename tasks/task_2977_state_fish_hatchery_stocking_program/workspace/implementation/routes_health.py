"""Fish health: sampling, results, the treat-and-retest cycle, certification."""

from decimal import Decimal

from flask import Blueprint

import constants as K
import derive
import validators as v
from auth import authorize
from envelope import created, enum_filter, ok, pagination, paginate, str_filter
from errors import ApiError
from serialize import dump
from store import (Tx, base_record, clock, days, fmt_instant, get_or_404, insert,
                   parse_instant, sort_key, values)

bp = Blueprint("health", __name__)

READ_ROLES = (K.PROGRAM_ADMIN, K.HATCHERY_MANAGER, K.VETERINARIAN, K.REGIONAL_BIOLOGIST)


@bp.post("/health-inspections")
def create_health_inspection():
    user_id, role = authorize(K.VETERINARIAN)
    body = v.body()
    lot = get_or_404("rearing_lots", v.req_id(body, "lot_id"))

    inspection_type = v.req_enum(body, "inspection_type", K.INSPECTION_TYPES)
    sample_size = v.req_int(body, "sample_size", minimum=Decimal(30))
    sampled_at = v.req_instant(body, "sampled_at")
    v.not_after_clock("sampled_at", sampled_at, clock())

    for other in derive.inspections_of_lot(lot["id"]):
        if other["status"] in ("SAMPLED", "RETEST_DUE"):
            raise ApiError("ERR_INVALID_STATE",
                           "Another inspection on this lot is still open.")
    if lot["health_status"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED", "This lot is under quarantine.")

    record = base_record()
    record.update({
        "lot_id": lot["id"],
        "inspection_type": inspection_type,
        "sample_size": sample_size,
        "sampled_at": fmt_instant(sampled_at),
        "sampled_by_user_id": user_id,
        "certified_by_user_id": None,
        "result": None,
        "pathogen_code": None,
        "retest_count": 0,
        "escalated_from_retests": False,
        "treatment_code": None,
        "withdrawal_days": None,
        "treatment_completed_at": None,
        "withdrawal_clears_at": None,
        "certified_at": None,
        "certificate_expires_at": None,
        "status": "SAMPLED",
    })
    insert("health_inspections", record)

    tx = Tx()
    # "re-inspecting a lot that was CERTIFIED withdraws its standing certificate
    # outright, immediately, before any result is known"
    lot["health_status"] = "UNDER_INSPECTION"
    lot["certificate_expires_at"] = None
    tx.touch(lot)
    tx.settle()
    return created(dump(record))


@bp.get("/health-inspections/<identifier>")
def get_health_inspection(identifier):
    authorize(*READ_ROLES)
    return ok(dump(get_or_404("health_inspections", identifier)))


@bp.get("/health-inspections")
def list_health_inspections():
    authorize(*READ_ROLES)
    lot_id = str_filter("lot_id")
    status = enum_filter("status", K.INSPECTION_STATUSES)
    inspection_type = enum_filter("inspection_type", K.INSPECTION_TYPES)
    limit, offset = pagination()

    records = values("health_inspections")
    if lot_id is not None:
        records = [r for r in records if r["lot_id"] == lot_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if inspection_type is not None:
        records = [r for r in records if r["inspection_type"] == inspection_type]
    records.sort(key=sort_key)
    return paginate(records, limit, offset, dump)


@bp.post("/health-inspections/<identifier>/record-result")
def record_inspection_result(identifier):
    authorize(K.VETERINARIAN)
    inspection = get_or_404("health_inspections", identifier)
    body = v.body()
    result = v.req_enum(body, "result", K.INSPECTION_RESULTS)
    pathogen_code = v.opt_str(body, "pathogen_code")

    if inspection["status"] not in ("SAMPLED", "RETEST_DUE"):
        raise ApiError("ERR_INVALID_STATE",
                       "This inspection is not awaiting a laboratory result.")
    lot = get_or_404("rearing_lots", inspection["lot_id"])
    if lot["health_status"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED", "This lot is under quarantine.")

    from_retest = inspection["status"] == "RETEST_DUE"
    if from_retest and result == "NEGATIVE" and inspection["withdrawal_clears_at"]:
        if clock() < parse_instant(inspection["withdrawal_clears_at"]):
            raise ApiError("ERR_WITHDRAWAL_PERIOD_ACTIVE",
                           "The drug-withdrawal window has not cleared.")

    tx = Tx()
    inspection["result"] = result
    if pathogen_code is not None:
        inspection["pathogen_code"] = pathogen_code
    tx.touch(inspection)

    reportable = False
    if result == "NEGATIVE":
        inspection["status"] = "PASSED"
    elif result == "POSITIVE_TREATABLE":
        if from_retest and inspection["retest_count"] >= K.MAX_RETESTS:
            # "the third positive escalates the inspection to FAILED_REPORTABLE"
            inspection["status"] = "FAILED_REPORTABLE"
            inspection["escalated_from_retests"] = True
            reportable = True
        else:
            inspection["status"] = "FAILED_TREATABLE"
            lot["health_status"] = "RESTRICTED"
            lot["certificate_expires_at"] = None
            tx.touch(lot)
    else:
        inspection["status"] = "FAILED_REPORTABLE"
        reportable = True

    if reportable:
        derive.quarantine_lot(tx, lot)
    tx.settle()
    return ok(dump(inspection))


@bp.post("/health-inspections/<identifier>/record-treatment")
def record_inspection_treatment(identifier):
    authorize(K.VETERINARIAN)
    inspection = get_or_404("health_inspections", identifier)
    body = v.body()
    treatment_code = v.req_str(body, "treatment_code")
    withdrawal_days = v.req_int(body, "withdrawal_days", minimum=Decimal(0))
    treatment_completed_at = v.req_instant(body, "treatment_completed_at")

    # The one carve-out from the ladder (PRD 2.10).
    if inspection["status"] == "FAILED_REPORTABLE":
        raise ApiError("ERR_PATHOGEN_NOT_TREATABLE",
                       "A reportable pathogen may not be treated out.")
    if inspection["status"] != "FAILED_TREATABLE":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a treatable finding may have a treatment recorded.")

    tx = Tx()
    inspection["treatment_code"] = treatment_code
    inspection["withdrawal_days"] = withdrawal_days
    inspection["treatment_completed_at"] = fmt_instant(treatment_completed_at)
    inspection["withdrawal_clears_at"] = fmt_instant(
        treatment_completed_at + days(withdrawal_days))
    inspection["retest_count"] = inspection["retest_count"] + 1
    inspection["status"] = "RETEST_DUE"
    tx.touch(inspection)
    tx.settle()
    return ok(dump(inspection))


@bp.post("/health-inspections/<identifier>/certify")
def certify_health_inspection(identifier):
    user_id, role = authorize(K.VETERINARIAN)
    inspection = get_or_404("health_inspections", identifier)

    if inspection["status"] != "PASSED":
        raise ApiError("ERR_INVALID_STATE", "Only a PASSED inspection may be certified.")
    lot = get_or_404("rearing_lots", inspection["lot_id"])
    if lot["health_status"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED", "This lot is under quarantine.")
    if user_id == inspection["sampled_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The sampling veterinarian may not sign this certificate.")

    tx = Tx()
    certified_at = clock()
    expires_at = certified_at + days(K.CERT_VALID_DAYS)
    inspection["status"] = "CERTIFIED"
    inspection["certified_by_user_id"] = user_id
    inspection["certified_at"] = fmt_instant(certified_at)
    inspection["certificate_expires_at"] = fmt_instant(expires_at)
    tx.touch(inspection)

    lot["health_status"] = "CERTIFIED"
    lot["certificate_expires_at"] = fmt_instant(expires_at)
    tx.touch(lot)
    tx.settle()
    return ok(dump(inspection))
