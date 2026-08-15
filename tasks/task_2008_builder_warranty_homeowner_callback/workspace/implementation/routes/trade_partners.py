"""Trade partner registration and fetch (PRD 3.1)."""
from flask import Blueprint

from db import db, new_entity
from errors import raise_error, ERR_TRADE_PARTNER_NOT_FOUND
from middleware import get_caller, require_role
from response import success_object
from util import serialize
from validate import get_body, opt_int, req_enum, req_str

bp = Blueprint("trade_partners", __name__)

TRADES = {"PLUMBING", "ELECTRICAL", "HVAC", "DRYWALL", "FLOORING", "GENERAL"}


@bp.post("/trade-partners")
def create_trade_partner():
    _uid, role = get_caller()
    require_role(role, {"WarrantyManager"})
    body = get_body()
    company_name = req_str(body, "company_name")
    trade = req_enum(body, "trade", TRADES)
    contact_email = req_str(body, "contact_email")
    daily_capacity_minutes = opt_int(body, "daily_capacity_minutes", default=480, positive=True)
    partner = new_entity()
    partner.update({
        "company_name": company_name,
        "trade": trade,
        "contact_email": contact_email,
        "daily_capacity_minutes": daily_capacity_minutes,
        "outstanding_chargeback_cents": 0,
        "open_work_order_count": 0,
    })
    db["trade_partners"][partner["id"]] = partner
    return success_object(serialize(partner), 201)


@bp.get("/trade-partners/<rid>")
def fetch_trade_partner(rid):
    _uid, role = get_caller()
    require_role(role, {"WarrantyManager", "WarrantyRep", "TradePartner", "FinanceAdmin"})
    partner = db["trade_partners"].get(rid)
    if partner is None:
        raise_error(ERR_TRADE_PARTNER_NOT_FOUND, f"trade partner id does not resolve: {rid}")
    return success_object(serialize(partner))
