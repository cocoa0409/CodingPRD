"""Partner and reciprocity-agreement endpoints (PRD 3.2)."""
from flask import Blueprint

from db import base_row, db, touch
from errors import ApiError
from middleware import (ACCOUNTANT, ACQUISITIONS, ADMIN, ILL_STAFF, PARTNER_AGENT,
                        auth, get_agreement, get_partner, own_partner_id)
from response import ok_row
from routes.common import filter_eq, list_response
from services import calc
from validate import (bad, body, opt_bool, opt_enum, opt_int, q_enum, q_str,
                      raw_id, req_bool, req_enum, req_instant, req_int, req_str)

bp = Blueprint("partners", __name__)

PARTNER_STATUSES = ("ACTIVE", "SUSPENDED", "WITHDRAWN")
FEE_WAIVER_MODES = ("NONE", "FULL", "CAPPED")
SETTLEMENT_MODES = ("GROSS", "NET")
AGREEMENT_STATUSES = ("ACTIVE", "SUPERSEDED", "EXPIRED")


@bp.route("/ill/partners", methods=["POST"])
def create_partner():
    auth(ADMIN)
    data = body()
    code = req_str(data, "code", 2, 16)
    name = req_str(data, "name")
    consortium_code = req_str(data, "consortium_code")
    base_fee = req_int(data, "base_lending_fee_cents", 0)
    turnaround = req_int(data, "avg_turnaround_days", 0)
    ships_physical = req_bool(data, "ships_physical")
    supplies_electronic = req_bool(data, "supplies_electronic")
    allows_renewals = req_bool(data, "allows_renewals")
    loan_period_days = req_int(data, "loan_period_days", 1, 120)
    max_renewals = req_int(data, "max_renewals", 0)
    status = opt_enum(data, "status", PARTNER_STATUSES, "ACTIVE")
    for existing in db.partners.values():
        if existing["code"] == code:
            bad("Field 'code' must be unique across all partner rows.")
    row = base_row()
    row.update({
        "code": code,
        "name": name,
        "consortium_code": consortium_code,
        "base_lending_fee_cents": base_fee,
        "avg_turnaround_days": turnaround,
        "ships_physical": ships_physical,
        "supplies_electronic": supplies_electronic,
        "allows_renewals": allows_renewals,
        "loan_period_days": loan_period_days,
        "max_renewals": max_renewals,
        "status": status,
        "borrowed_from_count": 0,
        "lent_to_count": 0,
        "net_borrow_imbalance_items": 0,
        "borrow_payable_cents": 0,
        "lend_receivable_cents": 0,
    })
    db.partners[row["id"]] = row
    return ok_row(row, 201)


@bp.route("/ill/partners/<partner_id>", methods=["PATCH"])
def patch_partner(partner_id):
    auth(ADMIN)
    partner = get_partner(partner_id)
    data = body()
    status = opt_enum(data, "status", PARTNER_STATUSES)
    base_fee = opt_int(data, "base_lending_fee_cents", None, 0)
    turnaround = opt_int(data, "avg_turnaround_days", None, 0)
    ships_physical = opt_bool(data, "ships_physical")
    supplies_electronic = opt_bool(data, "supplies_electronic")
    allows_renewals = opt_bool(data, "allows_renewals")
    loan_period_days = opt_int(data, "loan_period_days", None, 1, 120)
    max_renewals = opt_int(data, "max_renewals", None, 0)
    for field, value in (("status", status),
                         ("base_lending_fee_cents", base_fee),
                         ("avg_turnaround_days", turnaround),
                         ("ships_physical", ships_physical),
                         ("supplies_electronic", supplies_electronic),
                         ("allows_renewals", allows_renewals),
                         ("loan_period_days", loan_period_days),
                         ("max_renewals", max_renewals)):
        if value is not None:
            partner[field] = value
    touch(partner)
    return ok_row(partner)


@bp.route("/ill/partners/<partner_id>", methods=["GET"])
def get_one_partner(partner_id):
    user_id, role = auth(PARTNER_AGENT, ILL_STAFF, ACQUISITIONS, ACCOUNTANT, ADMIN)
    own_partner_id(partner_id, user_id, role)
    partner = get_partner(partner_id)
    return ok_row(partner)


@bp.route("/ill/partners", methods=["GET"])
def list_partners():
    auth(ILL_STAFF, ACCOUNTANT, ADMIN)
    rows = list(db.partners.values())
    rows = filter_eq(rows, "status", q_enum("status", PARTNER_STATUSES))
    rows = filter_eq(rows, "consortium_code", q_str("consortium_code"))
    return list_response(rows)


@bp.route("/ill/partners/<partner_id>/rota-entries", methods=["GET"])
def list_partner_entries(partner_id):
    user_id, role = auth(PARTNER_AGENT, ILL_STAFF, ADMIN)
    own_partner_id(partner_id, user_id, role)
    get_partner(partner_id)
    rows = [r for r in db.rota_entries.values() if r["partner_id"] == partner_id]
    rows = filter_eq(rows, "status", q_enum("status", ("ACTIVE", "SUPERSEDED")))
    return list_response(rows)


@bp.route("/ill/reciprocity-agreements", methods=["POST"])
def create_agreement():
    auth(ADMIN)
    data = body()
    # rung 32: body foreign keys, in declared field order
    partner_ref = raw_id(data, "partner_id")
    if partner_ref is not None and partner_ref not in db.partners:
        raise ApiError("ERR_PARTNER_NOT_FOUND")
    supersedes_ref = raw_id(data, "supersedes_agreement_id")
    if supersedes_ref is not None and supersedes_ref not in db.agreements:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND")
    # rung 35: shape
    partner_id = req_str(data, "partner_id")
    expected_version = req_int(data, "expected_partner_version", 0)
    fee_waiver_mode = req_enum(data, "fee_waiver_mode", FEE_WAIVER_MODES)
    settlement_mode = req_enum(data, "settlement_mode", SETTLEMENT_MODES)
    guarantee_days = req_int(data, "turnaround_guarantee_days", 0)
    effective_from = req_instant(data, "effective_from")
    effective_to = req_instant(data, "effective_to")
    capped_waiver = opt_int(data, "capped_waiver_cents", 0, 0)
    tolerance = opt_int(data, "balance_tolerance_items", 3, 0)
    if effective_to <= effective_from:
        bad("Field 'effective_to' must be strictly later than 'effective_from'.")
    partner = db.partners[partner_id]
    superseded = db.agreements[supersedes_ref] if supersedes_ref else None
    # rung 47: the superseded agreement must still be ACTIVE
    if superseded is not None and superseded["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    # rung 48: optimistic concurrency on the parent partner
    if expected_version != partner["version"]:
        raise ApiError("ERR_STALE_PARTNER_VERSION")
    # rung 63: window overlap, with the superseded row already excluded
    for other in db.agreements.values():
        if other["partner_id"] != partner_id or other["status"] != "ACTIVE":
            continue
        if superseded is not None and other["id"] == superseded["id"]:
            continue
        if calc.windows_overlap(effective_from, effective_to,
                                other["effective_from"], other["effective_to"]):
            raise ApiError("ERR_AGREEMENT_WINDOW_OVERLAP")
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        touch(superseded)
    row = base_row()
    row.update({
        "partner_id": partner_id,
        "supersedes_agreement_id": supersedes_ref,
        "fee_waiver_mode": fee_waiver_mode,
        "capped_waiver_cents": capped_waiver,
        "balance_tolerance_items": tolerance,
        "settlement_mode": settlement_mode,
        "turnaround_guarantee_days": guarantee_days,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "ACTIVE",
    })
    db.agreements[row["id"]] = row
    touch(partner)
    return ok_row(row, 201)


@bp.route("/ill/reciprocity-agreements/<agreement_id>", methods=["GET"])
def get_one_agreement(agreement_id):
    auth(PARTNER_AGENT, ILL_STAFF, ACCOUNTANT, ADMIN)
    return ok_row(get_agreement(agreement_id))


@bp.route("/ill/reciprocity-agreements", methods=["GET"])
def list_agreements():
    auth(PARTNER_AGENT, ILL_STAFF, ACCOUNTANT, ADMIN)
    rows = list(db.agreements.values())
    rows = filter_eq(rows, "partner_id", q_str("partner_id"))
    rows = filter_eq(rows, "supersedes_agreement_id", q_str("supersedes_agreement_id"))
    rows = filter_eq(rows, "status", q_enum("status", AGREEMENT_STATUSES))
    return list_response(rows)
