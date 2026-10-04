"""Special exhibitions (PRD 3.2): create, read, list, open-sale, close.

The close cascade flips every still-PURCHASED ticket to REFUNDED; fund
receipts are computed from ticket states at read time, so each flip debits
the revenue fund's computed receipts automatically (cascade link 2).
"""

from flask import Blueprint

import db
import serializers
import util
from envelope import listing, success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("exhibitions", __name__)

EXHIBITION_READ_ROLES = ["PlatformAdmin", "VisitorServices", "ExhibitionManager", "Member", "Public"]


@bp.post("/campus/museums/<mid>/exhibitions")
def create_exhibition(mid):
    _uid, role = auth()
    require_role(role, ["ExhibitionManager"])
    museum = get_or_404("museums", mid, "Museum")  # (3) path existence
    b = util.body()
    # (4) body FK existence: revenue_fund_id, when provided, must exist
    revenue_fund_id = b.get("revenue_fund_id")
    fund = None
    if revenue_fund_id is not None:
        fund = get_or_404("funds", revenue_fund_id, "FundAccount")
    # (9) request shape
    title = util.req_str(b, "title")
    fee_cents = util.req_int(b, "fee_cents", minimum=0)
    daily_ticket_quota = util.req_int(b, "daily_ticket_quota", minimum=1)
    presale_raw, presale_dt = util.req_datetime(b, "member_presale_opens_at")
    public_raw, public_dt = util.req_datetime(b, "public_sale_opens_at")
    if not public_dt > presale_dt:
        fail(
            "ERR_INVALID_REQUEST",
            "public_sale_opens_at must be strictly after member_presale_opens_at",
        )
    if revenue_fund_id is None:
        fail("ERR_INVALID_REQUEST", "Missing required field: revenue_fund_id")
    # Ticket revenue is trust money: the revenue fund must be TRUST.
    if fund["fund_type"] != "TRUST":
        fail("ERR_NOT_TRUST_FUND", "Exhibition revenue_fund_id must reference a TRUST fund")
    e = db.new_entity(
        {
            "museum_id": museum["id"],
            "revenue_fund_id": revenue_fund_id,
            "title": title,
            "fee_cents": fee_cents,
            "daily_ticket_quota": daily_ticket_quota,
            "member_presale_opens_at": presale_raw,
            "public_sale_opens_at": public_raw,
            "status": "DRAFT",
            "_presale_dt": presale_dt,
            "_public_dt": public_dt,
        }
    )
    db.STORE["exhibitions"][e["id"]] = e
    return success(serializers.special_exhibition(e), 201)


@bp.get("/campus/exhibitions")
def list_exhibitions():
    _uid, role = auth()
    require_role(role, EXHIBITION_READ_ROLES)
    limit, offset = util.pagination()
    f_museum = util.request.args.get("museum_id")
    f_fund = util.request.args.get("revenue_fund_id")
    rows = []
    for e in db.all_sorted("exhibitions"):
        if f_museum is not None and e["museum_id"] != f_museum:
            continue
        if f_fund is not None and e["revenue_fund_id"] != f_fund:
            continue
        rows.append(e)
    page = rows[offset : offset + limit]
    return listing([serializers.special_exhibition(e) for e in page], limit, offset, len(rows))


@bp.get("/campus/exhibitions/<eid>")
def get_exhibition(eid):
    _uid, role = auth()
    require_role(role, EXHIBITION_READ_ROLES)
    e = get_or_404("exhibitions", eid, "SpecialExhibition")
    return success(serializers.special_exhibition(e))


@bp.post("/campus/exhibitions/<eid>/open-sale")
def open_sale(eid):
    _uid, role = auth()
    require_role(role, ["ExhibitionManager"])
    e = get_or_404("exhibitions", eid, "SpecialExhibition")
    if e["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT exhibition can be opened for sale")
    e["status"] = "ON_SALE"
    db.touch(e)
    return success(serializers.special_exhibition(e))


@bp.post("/campus/exhibitions/<eid>/close")
def close_exhibition(eid):
    _uid, role = auth()
    require_role(role, ["ExhibitionManager"])
    e = get_or_404("exhibitions", eid, "SpecialExhibition")
    if e["status"] != "ON_SALE":
        fail("ERR_INVALID_STATE", "Only an ON_SALE exhibition can be closed")
    e["status"] = "CLOSED"
    # Cascade link 1: every PURCHASED ticket flips to REFUNDED. Cascade link 2
    # (revenue-fund receipts debited per refund) follows because receipts are
    # computed from live ticket states.
    for t in db.STORE["tickets"].values():
        if t["exhibition_id"] == e["id"] and t["status"] == "PURCHASED":
            t["status"] = "REFUNDED"
            db.touch(t)
    db.touch(e)
    return success(serializers.special_exhibition(e))
