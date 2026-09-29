"""Partners, partner grants and device lots (PRD 3.8)."""

from flask import Blueprint

import db
import domain
import response
import validation
from db import store, touch
from errors import ApiError
from middleware import endpoint
from services import installations as installation_service

bp = Blueprint("funding", __name__)

GRANT_READ_ROLES = ("ProgramAdmin", "GrantOfficer", "PartnerLiaison")
LOT_READ_ROLES = ("ProgramAdmin", "GrantOfficer", "CrrTechnician")


def load_grant(grant_id):
    grant = store.grants.get(grant_id)
    if grant is None:
        raise ApiError("ERR_GRANT_NOT_FOUND")
    return grant


@bp.post("/crr/partners")
@endpoint("ProgramAdmin")
def create_partner():
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    org_name = validation.req_str(body, "org_name")
    org_type = validation.req_enum(body, "org_type", domain.ORG_TYPES)
    contact_email = validation.req_str(body, "contact_email")
    agreement_signed = validation.opt_bool(body, "agreement_signed", default=False)

    row = db.stamp_new({})
    partner = {
        "id": row["id"],
        "org_name": org_name,
        "org_type": org_type,
        "contact_email": contact_email,
        "agreement_signed": agreement_signed,
        "referral_count": 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "_seq": row["_seq"],
    }
    store.partners[partner["id"]] = partner
    return response.ok_row(partner, 201)


@bp.post("/crr/grants")
@endpoint("GrantOfficer")
def create_grant():
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    partner_id = validation.req_str(body, "partner_id")
    grant_code = validation.req_str(body, "grant_code")
    authorized_cents = validation.req_int(body, "authorized_cents", minimum=1)
    period_start_date = validation.req_date(body, "period_start_date")
    period_end_date = validation.req_date(body, "period_end_date")
    if period_end_date < period_start_date:
        validation.bad("period_end_date must be on or after period_start_date.")
    allowed_device_types = validation.req_str_list(
        body, "allowed_device_types", members=domain.DEVICE_TYPES
    )
    unit_rate_cents_by_type = validation.req_int_map(
        body, "unit_rate_cents_by_type", minimum=1
    )
    reimbursement_basis = validation.req_enum(
        body, "reimbursement_basis", domain.REIMBURSEMENT_BASES
    )
    reimbursement_pct = validation.req_num(
        body, "reimbursement_pct", minimum=0, maximum=100, exclusive_min=True
    )
    indirect_rate_pct = validation.req_num(
        body, "indirect_rate_pct", minimum=0, maximum=50
    )
    match_pct = validation.req_num(body, "match_pct", minimum=0, maximum=50)

    partner = store.partners.get(partner_id)
    if partner is None:
        raise ApiError("ERR_PARTNER_NOT_FOUND")

    for existing in store.grants.values():
        if existing["grant_code"] == grant_code:
            raise ApiError("ERR_GRANT_CODE_TAKEN")

    # PRD 3.8: the rate table must cover every allowed family.
    for device_type in allowed_device_types:
        if device_type not in unit_rate_cents_by_type:
            raise ApiError("ERR_DEVICE_TYPE_NOT_FUNDED")

    row = db.stamp_new({})
    grant = {
        "id": row["id"],
        "partner_id": partner_id,
        "grant_code": grant_code,
        "authorized_cents": authorized_cents,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "allowed_device_types": list(allowed_device_types),
        "unit_rate_cents_by_type": unit_rate_cents_by_type,
        "reimbursement_basis": reimbursement_basis,
        "reimbursement_pct": reimbursement_pct,
        "indirect_rate_pct": indirect_rate_pct,
        "match_pct": match_pct,
        "status": "DRAFT",
        "reserved_cents": 0,
        "committed_cents": 0,
        "available_cents": authorized_cents,
        "reported_grant_share_cents": 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "_seq": row["_seq"],
    }
    store.grants[grant["id"]] = grant
    return response.ok_row(grant, 201)


@bp.get("/crr/grants")
@endpoint(*GRANT_READ_ROLES)
def list_grants():
    limit, offset = validation.pagination()
    rows = db.by_created_at(list(store.grants.values()))
    for name in ("partner_id", "status", "reimbursement_basis"):
        wanted = validation.filter_value(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    page, total = validation.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/crr/grants/<grant_id>")
@endpoint(*GRANT_READ_ROLES)
def get_grant(grant_id):
    return response.ok_row(load_grant(grant_id))


@bp.post("/crr/grants/<grant_id>/activate")
@endpoint("GrantOfficer")
def activate_grant(grant_id):
    grant = load_grant(grant_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)

    if grant["status"] != "DRAFT":
        raise ApiError("ERR_GRANT_NOT_DRAFT")

    # PRD 3.8: no other ACTIVE or CLOSED grant of the same partner may share a
    # device family over an overlapping inclusive period.
    families = set(grant["allowed_device_types"])
    for other in store.grants.values():
        if other["id"] == grant["id"]:
            continue
        if other["partner_id"] != grant["partner_id"]:
            continue
        if other["status"] not in ("ACTIVE", "CLOSED"):
            continue
        if not families.intersection(set(other["allowed_device_types"])):
            continue
        if (
            grant["period_start_date"] <= other["period_end_date"]
            and other["period_start_date"] <= grant["period_end_date"]
        ):
            raise ApiError("ERR_GRANT_PERIOD_OVERLAP")

    grant["status"] = "ACTIVE"
    touch(grant)
    return response.ok_row(grant)


@bp.post("/crr/device-lots")
@endpoint("GrantOfficer")
def create_device_lot():
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    funding_grant_id = validation.req_str(body, "funding_grant_id")
    sku = validation.req_str(body, "sku")
    device_type = validation.req_enum(body, "device_type", domain.DEVICE_TYPES)
    unit_cost_cents = validation.req_int(body, "unit_cost_cents", minimum=1)
    received_qty = validation.req_int(body, "received_qty", minimum=1)
    expiry_date = validation.req_date(body, "expiry_date")

    grant = store.grants.get(funding_grant_id)
    if grant is None:
        raise ApiError("ERR_GRANT_NOT_FOUND")

    if grant["status"] != "ACTIVE":
        raise ApiError("ERR_GRANT_NOT_ACTIVE")

    if device_type not in grant["allowed_device_types"]:
        raise ApiError("ERR_DEVICE_TYPE_NOT_FUNDED")

    row = db.stamp_new({})
    lot = {
        "id": row["id"],
        "funding_grant_id": funding_grant_id,
        "sku": sku,
        "device_type": device_type,
        "unit_cost_cents": unit_cost_cents,
        "received_qty": received_qty,
        "on_hand_qty": received_qty,
        "reserved_qty": 0,
        "consumed_qty": 0,
        "expiry_date": expiry_date,
        "status": "AVAILABLE",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "_seq": row["_seq"],
    }
    store.device_lots[lot["id"]] = lot
    return response.ok_row(lot, 201)


@bp.get("/crr/device-lots")
@endpoint(*LOT_READ_ROLES)
def list_device_lots():
    limit, offset = validation.pagination()
    rows = db.by_created_at(list(store.device_lots.values()))
    for name in ("funding_grant_id", "device_type", "status"):
        wanted = validation.filter_value(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    page, total = validation.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/crr/device-lots/<lot_id>")
@endpoint(*LOT_READ_ROLES)
def get_device_lot(lot_id):
    lot = store.device_lots.get(lot_id)
    if lot is None:
        raise ApiError("ERR_LOT_NOT_FOUND")
    return response.ok_row(lot)
