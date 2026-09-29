"""The paid post-sale inspection programme (PRD 3.3)."""
from flask import Blueprint

import services as S
import store as C
from authz import authenticate
from envelope import created, obj
from errors import fail
from store import store
from util import add_hours, iso, parse_dt, public
from validators import json_body, req_enum, req_enum_array, req_str

bp = Blueprint("psi", __name__)


def _overlaps(sale_id, start, end):
    """Half-open [requested_at_utc, window_end_utc) intervals of REQUESTED rows."""
    for row in store.rows("inspections"):
        if row["sale_id"] != sale_id or row["status"] != "REQUESTED":
            continue
        other_start = parse_dt(row["requested_at_utc"])
        other_end = parse_dt(row["window_end_utc"])
        if other_start is None or other_end is None:
            continue
        if start < other_end and other_start < end:
            return True
    return False


@bp.route("/arbitration/post-sale-inspections", methods=["POST"])
def buy_inspection():
    role, user_id = authenticate(["BuyerRep"])
    body = json_body()
    sale_id = req_str(body, "sale_id")
    program_tier = req_enum(body, "program_tier", C.PROGRAM_TIERS)
    sale = S.get_sale(sale_id)
    if sale["buyer_id"] != user_id:
        fail("ERR_NOT_SALE_BUYER")
    if sale["settlement_status"] != "UNSETTLED":
        fail("ERR_SALE_ALREADY_SETTLED")
    buyer = S.get_buyer(sale["buyer_id"])
    if buyer["claim_privilege_status"] != "ACTIVE":
        fail("ERR_BUYER_FEE_HOLD")
    start = store.now()
    end = add_hours(start, C.PSI_REQUEST_TTL_HOURS)
    if _overlaps(sale["id"], start, end):
        fail("ERR_PSI_WINDOW_OVERLAP")
    fee = (C.PSI_FEE_PREMIUM_CENTS if program_tier == "PREMIUM"
           else C.PSI_FEE_STANDARD_CENTS)
    row = {
        "sale_id": sale["id"],
        "program_tier": program_tier,
        "requested_at_utc": iso(start),
        "window_end_utc": iso(end),
        "completed_at_utc": None,
        "findings": [],
        "status": "REQUESTED",
        "fee_cents": fee,
    }
    store.insert("inspections", row, mutable=True)
    return created(public(row))


@bp.route("/arbitration/post-sale-inspections/<inspection_id>/complete", methods=["POST"])
def complete_inspection(inspection_id):
    authenticate(["Inspector"])
    body = json_body()
    findings = req_enum_array(body, "findings", C.DEFECT_CLASSES)
    inspection = S.get_inspection(inspection_id)
    if inspection["status"] != "REQUESTED":
        fail("ERR_INVALID_INSPECTION_STATE")
    inspection["status"] = "COMPLETED"
    inspection["completed_at_utc"] = store.now_iso()
    inspection["findings"] = findings
    S.touch(inspection)
    return obj(public(inspection))
