"""Exhibition tickets (PRD 3.2): purchase with presale/member pricing/quota,
read, list, refund, redeem."""

from flask import Blueprint

import calc
import db
import serializers
import util
from envelope import listing, success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("tickets", __name__)

TICKET_READ_ROLES = ["PlatformAdmin", "VisitorServices", "ExhibitionManager", "Member", "Public"]
TICKET_LIST_ROLES = ["PlatformAdmin", "VisitorServices", "ExhibitionManager"]


@bp.post("/campus/exhibitions/<eid>/tickets")
def purchase_ticket(eid):
    uid, role = auth()
    require_role(role, ["Public", "Member"])
    b = util.body()
    # (2) ownership: a Member caller purchases only with member_id == own id.
    member_id = b.get("member_id")
    if role == "Member" and member_id != uid:
        fail(
            "ERR_UNAUTHORIZED_ROLE",
            "Member callers may purchase only with their own member_id",
        )
    ex = get_or_404("exhibitions", eid, "SpecialExhibition")  # (3) path existence
    # (4) body FK existence
    member = None
    if member_id is not None:
        member = get_or_404("members", member_id, "Member")
    # (9) request shape
    buyer_name = util.req_str(b, "buyer_name")
    visit_date = util.req_date(b, "visit_date")
    # (13) closure dates on the hosting museum
    museum = db.STORE["museums"].get(ex["museum_id"])
    if museum is not None and visit_date in museum["closed_dates"]:
        fail("ERR_MUSEUM_CLOSED_ON_DATE", "Museum is closed on the requested visit date")
    # (14) sale windows (half-open at the opening instants)
    now = db.now_dt()
    if ex["status"] != "ON_SALE":
        fail("ERR_SALE_NOT_OPEN", "Exhibition is not on sale")
    if now < ex["_presale_dt"]:
        fail("ERR_SALE_NOT_OPEN", "Sale has not opened yet")
    if member is not None and calc.member_status(member) == "LAPSED":
        fail("ERR_MEMBER_LAPSED", "The named member is lapsed")
    if now < ex["_public_dt"] and member is None:
        fail("ERR_PRESALE_MEMBER_ONLY", "Only member purchases are allowed during presale")
    # (16) daily ticket quota: PURCHASED + REDEEMED count against it
    sold = sum(
        1
        for t in db.STORE["tickets"].values()
        if t["exhibition_id"] == ex["id"]
        and t["visit_date"] == visit_date
        and t["status"] in ("PURCHASED", "REDEEMED")
    )
    if sold >= ex["daily_ticket_quota"]:
        fail("ERR_TICKET_QUOTA_EXHAUSTED", "The daily ticket quota is exhausted")
    price = calc.member_unit_price(ex["fee_cents"], member is not None)
    t = db.new_entity(
        {
            "exhibition_id": ex["id"],
            "member_id": member_id,
            "buyer_name": buyer_name,
            "visit_date": visit_date,
            "price_paid_cents": price,
            "status": "PURCHASED",
        }
    )
    db.STORE["tickets"][t["id"]] = t
    return success(serializers.exhibition_ticket(t), 201)


@bp.get("/campus/tickets")
def list_tickets():
    _uid, role = auth()
    require_role(role, TICKET_LIST_ROLES)
    limit, offset = util.pagination()
    f_ex = util.request.args.get("exhibition_id")
    f_member = util.request.args.get("member_id")
    rows = []
    for t in db.all_sorted("tickets"):
        if f_ex is not None and t["exhibition_id"] != f_ex:
            continue
        if f_member is not None and t["member_id"] != f_member:
            continue
        rows.append(t)
    page = rows[offset : offset + limit]
    return listing([serializers.exhibition_ticket(t) for t in page], limit, offset, len(rows))


@bp.get("/campus/tickets/<tid>")
def get_ticket(tid):
    _uid, role = auth()
    require_role(role, TICKET_READ_ROLES)
    t = get_or_404("tickets", tid, "ExhibitionTicket")
    return success(serializers.exhibition_ticket(t))


@bp.post("/campus/tickets/<tid>/refund")
def refund_ticket(tid):
    _uid, role = auth()
    require_role(role, ["VisitorServices"])
    t = get_or_404("tickets", tid, "ExhibitionTicket")
    if t["status"] != "PURCHASED":
        fail("ERR_INVALID_STATE", "Only a PURCHASED ticket can be refunded")
    # (15) manual refund only while the current logical date <= visit_date
    if db.today_str() > t["visit_date"]:
        fail("ERR_REFUND_WINDOW_CLOSED", "The refund window closed after the visit date")
    t["status"] = "REFUNDED"
    db.touch(t)
    return success(serializers.exhibition_ticket(t))


@bp.post("/campus/tickets/<tid>/redeem")
def redeem_ticket(tid):
    _uid, role = auth()
    require_role(role, ["SecurityScreener"])
    t = get_or_404("tickets", tid, "ExhibitionTicket")
    if t["status"] != "PURCHASED":
        fail("ERR_INVALID_STATE", "Only a PURCHASED ticket can be redeemed")
    # Redemption requires the exhibition still ON_SALE (unreachable in
    # practice: closing an exhibition refunds all PURCHASED tickets).
    ex = db.STORE["exhibitions"].get(t["exhibition_id"])
    if ex is None or ex["status"] != "ON_SALE":
        fail("ERR_INVALID_STATE", "The exhibition is not on sale")
    # (15) redemption happens exactly on the ticket's visit date
    if db.today_str() != t["visit_date"]:
        fail("ERR_VISIT_DATE_MISMATCH", "Tickets redeem only on their visit date")
    t["status"] = "REDEEMED"
    db.touch(t)
    return success(serializers.exhibition_ticket(t))
