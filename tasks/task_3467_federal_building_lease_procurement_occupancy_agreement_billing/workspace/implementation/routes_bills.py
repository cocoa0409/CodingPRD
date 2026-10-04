"""RentBill generation, listing, and payment (PRD section 3.5)."""
from flask import Blueprint, request

from calc import bill_components
from dates import parse_date, parse_month
from envelope import success
from errors import ApiError
from middleware import (ALL_ROLES, agency_scope, body, is_int, paginate,
                        require_auth)
from store import DB, bump, make_entity, now_str, pub, sorted_items

bp = Blueprint("bills", __name__)


def _recompute_receivable(oa):
    bills = [x for x in DB["bills"].values() if x["oa_id"] == oa["id"]]
    oa["receivable_outstanding_cents"] = (
        sum(x["total_cents"] for x in bills) - sum(x["amount_paid_cents"] for x in bills))


@bp.route("/leasing/occupancy-agreements/<oid>/bills", methods=["POST"])
def generate_bill(oid):
    require_auth(["GSAPropertyManager"])
    oa = DB["oas"].get(oid)
    if not oa:
        raise ApiError("ERR_NOT_FOUND", 404, "OccupancyAgreement not found")
    b = body()
    # priority 5: billing_month shape
    bm = b.get("billing_month")
    if parse_month(bm) is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "billing_month must be in YYYY-MM form")
    # priority 7: OA must be ACTIVE
    if oa["status"] != "ACTIVE":
        raise ApiError("ERR_OA_NOT_ACTIVE", 409, "Bills may only be generated for an ACTIVE occupancy agreement")
    by, bmm = parse_month(bm)
    lease = DB["leases"].get(oa["lease_id"]) if oa.get("lease_id") else None
    # priority 9: billing window [commencement month (leased), OA end month]
    if lease is not None:
        comm = parse_date(lease["commencement_date"])
        if (by, bmm) < (comm.year, comm.month):
            raise ApiError("ERR_BILL_MONTH_OUT_OF_TERM", 422,
                           "billing_month precedes the lease's commencement month")
    oa_end = parse_date(oa["end_date"])
    if (by, bmm) > (oa_end.year, oa_end.month):
        raise ApiError("ERR_BILL_MONTH_OUT_OF_TERM", 422, "billing_month is after the OA's end month")
    # priority 11: one bill per (OA, billing_month)
    for bill in DB["bills"].values():
        if bill["oa_id"] == oid and bill["billing_month"] == bm:
            raise ApiError("ERR_BILL_ALREADY_EXISTS", 409, "A bill already exists for this OA and billing_month")
    alterations = [a for a in DB["alterations"].values() if a["oa_id"] == oid]
    comp = bill_components(oa, lease, bm, alterations)
    touched = comp.pop("_touched")
    for a in touched:
        bump(a)
    oa["pending_service_credit_cents"] -= comp["service_credit_applied_cents"]
    e = make_entity()
    e.update({
        "oa_id": oid,
        "billing_month": bm,
        **comp,
        "amount_paid_cents": 0,
        "payments": [],
        "status": "ISSUED",
    })
    DB["bills"][e["id"]] = e
    _recompute_receivable(oa)
    bump(oa)
    return success(pub(e), 201)


@bp.route("/leasing/occupancy-agreements/<oid>/bills", methods=["GET"])
def list_bills(oid):
    require_auth(ALL_ROLES)
    if oid not in DB["oas"]:
        raise ApiError("ERR_NOT_FOUND", 404, "OccupancyAgreement not found")
    items = [x for x in DB["bills"].values() if x["oa_id"] == oid]
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, pagination = paginate(sorted_items(items))
    return success([pub(x) for x in page], 200, pagination)


@bp.route("/leasing/rent-bills/<bid>/pay", methods=["POST"])
def pay_bill(bid):
    uid, role = require_auth(["AgencyManager"])
    bill = DB["bills"].get(bid)
    if not bill:
        raise ApiError("ERR_NOT_FOUND", 404, "RentBill not found")
    oa = DB["oas"][bill["oa_id"]]
    # priority 3: agency scope against the bill's OA
    agency_scope(uid, role, oa["agency_id"])
    b = body()
    # priority 5: shape
    if not is_int(b.get("amount_cents")):
        raise ApiError("ERR_INVALID_REQUEST", 400, "amount_cents is required and must be an integer")
    amt = b["amount_cents"]
    # priority 6: state
    if bill["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only an ISSUED or PARTIALLY_PAID bill can be paid")
    # priority 12: fiscal gate
    remaining = bill["total_cents"] - bill["amount_paid_cents"]
    if amt <= 0 or amt > remaining:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", 422,
                       "amount_cents must be > 0 and no more than the remaining balance")
    bill["payments"].append({"paid_at": now_str(), "amount_cents": amt, "payer_user_id": uid})
    if amt == remaining:
        bill["amount_paid_cents"] = bill["total_cents"]
        bill["status"] = "PAID"
    else:
        bill["amount_paid_cents"] += amt
        bill["status"] = "PARTIALLY_PAID"
    bump(bill)
    _recompute_receivable(oa)
    bump(oa)
    return success(pub(bill))
