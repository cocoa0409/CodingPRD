"""Voluntary disclosure agreements for past exposure."""
from flask import Blueprint

from calc import (adjust_obligations, compute_vda_exposure, filings_of_registration,
                  group_of_registration, vdas_of_entity, FULL_EXPOSURE_YEARS,
                  VDA_MAX_LOOKBACK_YEARS, VDA_SHIELD_MONTHS)
from errors import ApiError, invalid
from models import (find_legal_entity, find_registration, find_vda, ser_vda)
from routes_reg import guard_not_withdrawn
from store import db
from util import add_months, money, opt_num, req_enum, req_int, req_num, req_str, D, ZERO
from web import (ANY_ROLE, body_json, bump, created, endpoint, mark_dirty, new_record,
                 ok, paginate, query_str, sort_created)

bp = Blueprint("vda", __name__)

EXPOSURE_VARIANTS = ("LOOKBACK_LIMITED", "FULL_EXPOSURE")
LIVE_VDA_STATUSES = ("DRAFT", "SUBMITTED", "EXECUTED")


@bp.route("/salt/registrations/<rid>/vda-agreements", methods=["POST"])
@endpoint(["TaxManager"])
def create_vda(rid):
    reg = find_registration(rid)
    body = body_json()

    raw_entity = body.get("legal_entity_id")
    entity = find_legal_entity(raw_entity) if raw_entity is not None else None
    if entity is None:
        raise invalid("'legal_entity_id' is required")

    anchor_tax_year = req_int(body, "anchor_tax_year")
    lookback_years = req_int(body, "lookback_years", minv=1)
    exposure_variant = req_enum(body, "exposure_variant", EXPOSURE_VARIANTS)
    estimated_exposure_tax = req_num(body, "estimated_exposure_tax", minv=0)

    guard_not_withdrawn(reg)

    if entity["group_id"] != reg["group_id"]:
        raise ApiError("ERR_ENTITY_NOT_IN_GROUP",
                       "The named member entity does not belong to this registration's group.")
    if anchor_tax_year < lookback_years:
        raise ApiError("ERR_ACTIVITY_YEAR_MISMATCH",
                       "anchor_tax_year must be at least as large as lookback_years.")

    effective = lookback_years if exposure_variant == "LOOKBACK_LIMITED" else FULL_EXPOSURE_YEARS
    start_year = anchor_tax_year - effective + 1
    end_year = anchor_tax_year

    for other in vdas_of_entity(entity["id"]):
        if other["status"] not in LIVE_VDA_STATUSES:
            continue
        if (start_year - 2) < (other["lookback_end_year"] + 1) and \
                other["lookback_start_year"] < (end_year + 3):
            raise ApiError("ERR_VDA_WINDOW_OVERLAP",
                           "The proposed disclosure window overlaps a live disclosure for this "
                           "member entity.")

    if exposure_variant == "LOOKBACK_LIMITED" and lookback_years > VDA_MAX_LOOKBACK_YEARS:
        raise ApiError("ERR_VDA_EXPOSURE_MISMATCH",
                       "A lookback-limited disclosure may not exceed %d years."
                       % VDA_MAX_LOOKBACK_YEARS)

    vda = new_record()
    vda.update({
        "registration_id": reg["id"],
        "legal_entity_id": entity["id"],
        "anchor_tax_year": anchor_tax_year,
        "lookback_years": lookback_years,
        "exposure_variant": exposure_variant,
        "estimated_exposure_tax": estimated_exposure_tax,
        "effective_lookback_years": 0,
        "lookback_start_year": 0,
        "lookback_end_year": 0,
        "computed_exposure_tax": money(ZERO),
        "waived_penalty_amount": money(ZERO),
        "negotiated_tax": None,
        "negotiated_interest": money(ZERO),
        "settlement_total": money(ZERO),
        "status": "DRAFT",
        "executed_on_date": None,
        "shield_expires_at": None,
    })
    compute_vda_exposure(vda)
    db.vdas[vda["id"]] = vda
    return created(ser_vda(vda))


@bp.route("/salt/vda-agreements/<vid>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_vda(vid):
    return ok(ser_vda(find_vda(vid)))


@bp.route("/salt/vda-agreements", methods=["GET"])
@endpoint(ANY_ROLE)
def list_vdas():
    registration_id = query_str("registration_id")
    legal_entity_id = query_str("legal_entity_id")
    status = query_str("status")
    rows = list(db.vdas.values())
    if registration_id is not None:
        rows = [v for v in rows if v["registration_id"] == registration_id]
    if legal_entity_id is not None:
        rows = [v for v in rows if v["legal_entity_id"] == legal_entity_id]
    if status is not None:
        rows = [v for v in rows if v["status"] == status]
    return paginate(sort_created(rows), ser_vda)


@bp.route("/salt/vda-agreements/<vid>/submit", methods=["POST"])
@endpoint(["TaxManager"])
def submit_vda(vid):
    vda = find_vda(vid)
    if vda["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_VDA_STATE", "Only a DRAFT disclosure may be submitted.")
    vda["status"] = "SUBMITTED"
    bump(vda)
    return ok(ser_vda(vda))


@bp.route("/salt/vda-agreements/<vid>/execute", methods=["POST"])
@endpoint(["TaxManager"])
def execute_vda(vid):
    vda = find_vda(vid)
    body = body_json()
    negotiated_tax = opt_num(body, "negotiated_tax", None, minv=0)
    negotiated_interest = opt_num(body, "negotiated_interest", None, minv=0)

    if vda["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_VDA_STATE", "Only a SUBMITTED disclosure may be executed.")

    reg = db.registrations[vda["registration_id"]]
    for filing in filings_of_registration(reg):
        if (filing["preparation_status"] in ("FILED", "AMENDED")
                and vda["lookback_start_year"] <= filing["tax_year"] <= vda["lookback_end_year"]):
            raise ApiError("ERR_VDA_YEAR_ALREADY_FILED",
                           "A return covering a year inside the lookback window has already been "
                           "filed.")

    tax = negotiated_tax if negotiated_tax is not None else D(vda["computed_exposure_tax"])
    interest = negotiated_interest if negotiated_interest is not None else ZERO
    vda["negotiated_tax"] = money(tax)
    vda["negotiated_interest"] = money(interest)
    vda["settlement_total"] = money(D(tax) + D(interest))
    vda["status"] = "EXECUTED"
    vda["executed_on_date"] = db.clock
    vda["shield_expires_at"] = add_months(db.clock, VDA_SHIELD_MONTHS)

    entity = db.legal_entities.get(vda["legal_entity_id"])
    if entity is not None:
        entity["vda_shield_until"] = vda["shield_expires_at"]
        mark_dirty(entity)

    reg["nexus_status"] = "VOLUNTARY"
    if reg["registration_status"] == "REGISTRATION_REQUIRED":
        reg["registration_status"] = "REGISTERED"
        reg["state_account_number"] = "VDA-" + vda["id"]
        reg["registered_on_date"] = db.clock
        adjust_obligations(group_of_registration(reg), -1)
    bump(reg)
    bump(vda)
    return ok(ser_vda(vda))


@bp.route("/salt/vda-agreements/<vid>/withdraw", methods=["POST"])
@endpoint(["TaxManager"])
def withdraw_vda(vid):
    vda = find_vda(vid)
    body = body_json()
    req_str(body, "reason")

    if vda["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_INVALID_VDA_STATE",
                       "Only a drafted or submitted disclosure may be withdrawn.")

    vda["status"] = "WITHDRAWN"
    bump(vda)
    return ok(ser_vda(vda))
