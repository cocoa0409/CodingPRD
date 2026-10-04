"""Managing partner contract, buy-in payment, and buyout order routes (PRD §3.3, §3.4)."""

from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    ERR_BUY_IN_OVERPAYMENT,
    ERR_BUY_IN_INCOMPLETE,
    ERR_BUYOUT_ALREADY_OPEN,
    ERR_CONTRACT_NOT_FUNDABLE,
    ERR_CONTRACT_NOT_IN_BUYOUT,
    ERR_CONTRACT_PARTNER_MISMATCH,
    ERR_DEPARTURE_BLOCKED_BY_OPEN_DISPUTE,
    ERR_FUNDING_WINDOW_LAPSED,
    ERR_INVALID_STATE,
    ERR_NOT_MANAGING_PARTNER,
    ERR_OFFSET_EXCEEDS_PAYOUT,
    ERR_RENEWAL_BLOCKED_BY_OPEN_DISPUTE,
    ERR_RESTAURANT_ALREADY_HAS_ACTIVE_CONTRACT,
    ERR_RESTAURANT_NOT_ACTIVE,
    ERR_SUCCESSOR_NOT_ELIGIBLE,
    conflict,
    forbidden,
    invalid_request,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from services import calculations, domain, sweeps
from util import (
    base_entity,
    check_occ,
    get_json_body,
    logical_date,
    logical_dt,
    paginate,
    req_date,
    req_field,
    req_int,
    req_string,
    touch,
)

bp = Blueprint("contracts", __name__)

CONTRACT_READ_ROLES = ("PlatformAdmin", "CorporateController", "OperationsAuditor", "ManagingPartner")


# ---------------- contracts ----------------

@bp.route("/managing-partner-contracts", methods=["POST"])
def create_contract():
    require_roles("CorporateController")
    body = get_json_body()
    partner_id = req_field(body, "partner_id")
    restaurant_id = req_field(body, "restaurant_id")
    # Body FK existence (tier 4).
    domain.ref_partner(partner_id)
    domain.ref_restaurant(restaurant_id)
    # Structural constraints (tier 8).
    term_start = req_date(body, "term_start_date")
    term_end = req_date(body, "term_end_date")
    if term_end <= term_start:
        raise invalid_request("term_end_date must be after term_start_date")
    buy_in = req_int(body, "buy_in_required_cents")
    if buy_in <= 0:
        raise invalid_request("buy_in_required_cents must be > 0")
    c = base_entity()
    c.update({
        "partner_id": partner_id,
        "restaurant_id": restaurant_id,
        "term_start_date": term_start.isoformat(),
        "term_end_date": term_end.isoformat(),
        "buy_in_required_cents": buy_in,
        "buy_in_escrow_cents": 0,
        "capital_account_cents": 0,
        "submitted_at": None,
        "renewed_count": 0,
        "departure_date": None,
        "status": "DRAFT",
    })
    db.contracts[c["id"]] = c
    return success_object(domain.ser_contract(c), 201)


@bp.route("/managing-partner-contracts", methods=["GET"])
def list_contracts():
    require_roles(*CONTRACT_READ_ROLES)
    items = list(db.contracts.values())
    partner_id = request.args.get("partner_id")
    if partner_id is not None:
        items = [c for c in items if c["partner_id"] == partner_id]
    restaurant_id = request.args.get("restaurant_id")
    if restaurant_id is not None:
        items = [c for c in items if c["restaurant_id"] == restaurant_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_contract(c) for c in page], limit, offset, total)


@bp.route("/managing-partner-contracts/<cid>", methods=["GET"])
def get_contract(cid):
    require_roles(*CONTRACT_READ_ROLES)
    return success_object(domain.ser_contract(domain.get_contract(cid)))


@bp.route("/managing-partner-contracts/<cid>/submit", methods=["POST"])
def submit_contract(cid):
    require_roles("CorporateController")
    c = domain.get_contract(cid)
    if c["status"] != "DRAFT":
        raise conflict(ERR_INVALID_STATE, "Contract must be DRAFT to submit")
    # Referential guards, in the PRD's pinned order (§3.3).
    partner = db.partners.get(c["partner_id"])
    if partner is None or partner["role_in_program"] != "MANAGING_PARTNER":
        raise unprocessable(ERR_NOT_MANAGING_PARTNER, "Contract partner must be a MANAGING_PARTNER")
    for other in db.contracts.values():
        if (
            other["id"] != c["id"]
            and other["restaurant_id"] == c["restaurant_id"]
            and other["status"] in domain.CONTRACT_OPEN_STATUSES
        ):
            raise unprocessable(
                ERR_RESTAURANT_ALREADY_HAS_ACTIVE_CONTRACT,
                "Restaurant already has a contract in an open status",
            )
    restaurant = db.restaurants.get(c["restaurant_id"])
    if restaurant is None or restaurant["status"] != "ACTIVE":
        raise unprocessable(ERR_RESTAURANT_NOT_ACTIVE, "Restaurant must be ACTIVE to submit")
    c["status"] = "PENDING_FUNDING"
    c["submitted_at"] = logical_dt()
    touch(c)
    return success_object(domain.ser_contract(c))


@bp.route("/managing-partner-contracts/<cid>/buy-in-payments", methods=["POST"])
def post_buy_in_payment(cid):
    user_id, _ = require_roles("ManagingPartner")
    c = domain.get_contract(cid)
    if c["status"] != "PENDING_FUNDING":
        raise conflict(ERR_INVALID_STATE, "Buy-in payments require contract PENDING_FUNDING")
    if user_id != c["partner_id"]:
        raise forbidden(ERR_CONTRACT_PARTNER_MISMATCH, "Caller is not the contract's partner")
    body = get_json_body()
    amount = req_int(body, "amount_cents")
    if amount <= 0:
        raise invalid_request("amount_cents must be > 0")
    if c["buy_in_escrow_cents"] + amount > c["buy_in_required_cents"]:
        raise unprocessable(ERR_BUY_IN_OVERPAYMENT, "Payment would push escrow above the required buy-in")
    pay = base_entity()
    pay.update({
        "contract_id": c["id"],
        "amount_cents": amount,
        "status": "POSTED",
    })
    db.buy_in_payments[pay["id"]] = pay
    c["buy_in_escrow_cents"] += amount
    touch(c)
    return success_object(domain.ser_buy_in_payment(pay), 201)


@bp.route("/managing-partner-contracts/<cid>/buy-in-payments", methods=["GET"])
def list_buy_in_payments(cid):
    require_roles("PlatformAdmin", "CorporateController", "ManagingPartner")
    c = domain.get_contract(cid)
    items = [p for p in db.buy_in_payments.values() if p["contract_id"] == c["id"]]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_buy_in_payment(p) for p in page], limit, offset, total)


@bp.route("/managing-partner-contracts/<cid>/activate", methods=["POST"])
def activate_contract(cid):
    require_roles("CorporateController")
    c = domain.get_contract(cid)
    if c["status"] != "PENDING_FUNDING":
        raise conflict(ERR_INVALID_STATE, "Contract must be PENDING_FUNDING to activate")
    # State gate fires first (§3.3): zero escrow is not fundable.
    if c["buy_in_escrow_cents"] == 0:
        raise conflict(ERR_CONTRACT_NOT_FUNDABLE, "Contract has zero buy-in escrow")
    # Temporal check (tier 6) before the fiscal check (tier 9).
    if logical_dt() >= c["submitted_at"] + timedelta(days=domain.FUNDING_WINDOW_DAYS):
        raise unprocessable(ERR_FUNDING_WINDOW_LAPSED, "Funding window has lapsed")
    if c["buy_in_escrow_cents"] < c["buy_in_required_cents"]:
        raise unprocessable(ERR_BUY_IN_INCOMPLETE, "Buy-in escrow is below the required amount")
    # Activation: escrow moves wholesale into restaurant capital.
    c["capital_account_cents"] = c["buy_in_escrow_cents"]
    c["buy_in_escrow_cents"] = 0
    c["status"] = "ACTIVE"
    touch(c)
    partner = db.partners.get(c["partner_id"])
    if partner is not None:
        partner["placed_restaurant_id"] = c["restaurant_id"]
        partner["status"] = "PLACED"
        touch(partner)
    return success_object(domain.ser_contract(c))


@bp.route("/managing-partner-contracts/<cid>/offer-renewal", methods=["POST"])
def offer_renewal(cid):
    require_roles("CorporateController")
    c = domain.get_contract(cid)
    if c["status"] != "ACTIVE":
        raise conflict(ERR_INVALID_STATE, "Contract must be ACTIVE to offer renewal")
    if domain.restaurant_has_open_dispute(c["restaurant_id"]):
        raise unprocessable(
            ERR_RENEWAL_BLOCKED_BY_OPEN_DISPUTE,
            "Renewal is blocked by an open dispute on the restaurant's periods",
        )
    c["status"] = "RENEWAL_OFFERED"
    touch(c)
    return success_object(domain.ser_contract(c))


@bp.route("/managing-partner-contracts/<cid>/accept-renewal", methods=["POST"])
def accept_renewal(cid):
    user_id, _ = require_roles("ManagingPartner")
    c = domain.get_contract(cid)
    if c["status"] != "RENEWAL_OFFERED":
        raise conflict(ERR_INVALID_STATE, "Contract must be RENEWAL_OFFERED to accept")
    if user_id != c["partner_id"]:
        raise forbidden(ERR_CONTRACT_PARTNER_MISMATCH, "Caller is not the contract's partner")
    term_end = __import__("datetime").date.fromisoformat(c["term_end_date"])
    try:
        new_end = term_end.replace(year=term_end.year + domain.RENEWAL_EXTENSION_YEARS)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap target years.
        new_end = term_end.replace(year=term_end.year + domain.RENEWAL_EXTENSION_YEARS, day=28)
    c["term_end_date"] = new_end.isoformat()
    c["renewed_count"] += 1
    c["status"] = "ACTIVE"
    touch(c)
    return success_object(domain.ser_contract(c))


@bp.route("/managing-partner-contracts/<cid>/depart", methods=["POST"])
def depart(cid):
    user_id, _ = require_roles("ManagingPartner")
    c = domain.get_contract(cid)
    if c["status"] != "ACTIVE":
        raise conflict(ERR_INVALID_STATE, "Contract must be ACTIVE to depart")
    if user_id != c["partner_id"]:
        raise forbidden(ERR_CONTRACT_PARTNER_MISMATCH, "Caller is not the contract's partner")
    if domain.restaurant_has_open_dispute(c["restaurant_id"]):
        raise unprocessable(
            ERR_DEPARTURE_BLOCKED_BY_OPEN_DISPUTE,
            "Departure is blocked by an open dispute on the restaurant's periods",
        )
    c["departure_date"] = logical_date().isoformat()
    c["status"] = "BUYOUT_PENDING"
    touch(c)
    return success_object(domain.ser_contract(c))


@bp.route("/managing-partner-contracts/<cid>/transfer", methods=["POST"])
def transfer(cid):
    require_roles("CorporateController")
    c = domain.get_contract(cid)
    if c["status"] != "BUYOUT_PENDING":
        raise conflict(ERR_INVALID_STATE, "Contract must be BUYOUT_PENDING to transfer")
    body = get_json_body()
    successor_id = req_field(body, "successor_partner_id")
    successor = domain.ref_partner(successor_id)
    if successor["role_in_program"] != "MANAGING_PARTNER" or successor["status"] != "CERTIFIED":
        raise unprocessable(
            ERR_SUCCESSOR_NOT_ELIGIBLE,
            "Successor must be a CERTIFIED MANAGING_PARTNER",
        )
    open_buyout = any(
        b["contract_id"] == c["id"] and b["status"] in ("DRAFT", "APPROVED")
        for b in db.buyout_orders.values()
    )
    if open_buyout:
        raise unprocessable(ERR_BUYOUT_ALREADY_OPEN, "A buyout order is already open on this contract")
    # Old partner returns to the certified pool; successor is placed.
    old_partner = db.partners.get(c["partner_id"])
    if old_partner is not None and old_partner["status"] == "PLACED":
        old_partner["status"] = "CERTIFIED"
        old_partner["placed_restaurant_id"] = None
        touch(old_partner)
    successor["status"] = "PLACED"
    successor["placed_restaurant_id"] = c["restaurant_id"]
    touch(successor)
    c["status"] = "TRANSFERRED"
    touch(c)
    # Successor gets a fresh DRAFT contract on the same restaurant, term from today.
    start = logical_date()
    try:
        end = start.replace(year=start.year + domain.RENEWAL_EXTENSION_YEARS)
    except ValueError:
        end = start.replace(year=start.year + domain.RENEWAL_EXTENSION_YEARS, day=28)
    new_contract = base_entity()
    new_contract.update({
        "partner_id": successor["id"],
        "restaurant_id": c["restaurant_id"],
        "term_start_date": start.isoformat(),
        "term_end_date": end.isoformat(),
        "buy_in_required_cents": c["buy_in_required_cents"],
        "buy_in_escrow_cents": 0,
        "capital_account_cents": 0,
        "submitted_at": None,
        "renewed_count": 0,
        "departure_date": None,
        "status": "DRAFT",
    })
    db.contracts[new_contract["id"]] = new_contract
    return success_object(domain.ser_contract(c))


@bp.route("/managing-partner-contracts/<cid>/buyout-orders", methods=["POST"])
def create_buyout_order(cid):
    require_roles("CorporateController")
    c = domain.get_contract(cid)
    # State gate (tier 5), then OCC (§2.7).
    if c["status"] != "BUYOUT_PENDING":
        raise conflict(ERR_CONTRACT_NOT_IN_BUYOUT, "Contract is not in BUYOUT_PENDING")
    body = get_json_body()
    check_occ(body, c, "expected_contract_version", "Contract")
    offset = req_int(body, "offset_cents")
    if offset < 0:
        raise invalid_request("offset_cents must be >= 0")
    # Buyout valuation — pinned evaluation order (§3.4).
    capital_return = calculations.capital_return_depreciation(c)
    accrued = calculations.accrued_share(c)
    if offset > capital_return + accrued:
        raise unprocessable(ERR_OFFSET_EXCEEDS_PAYOUT, "offset_cents exceeds capital return plus accrued share")
    b = base_entity()
    b.update({
        "contract_id": c["id"],
        "capital_return_cents": capital_return,
        "accrued_share_cents": accrued,
        "offset_cents": offset,
        "total_payout_cents": capital_return + accrued - offset,
        "status": "DRAFT",
    })
    db.buyout_orders[b["id"]] = b
    touch(c)
    return success_object(domain.ser_buyout(b), 201)


# ---------------- buyout orders ----------------

@bp.route("/buyout-orders", methods=["GET"])
def list_buyout_orders():
    require_roles("PlatformAdmin", "CorporateController")
    items = list(db.buyout_orders.values())
    contract_id = request.args.get("contract_id")
    if contract_id is not None:
        items = [b for b in items if b["contract_id"] == contract_id]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_buyout(b) for b in page], limit, offset, total)


@bp.route("/buyout-orders/<bid>", methods=["GET"])
def get_buyout_order(bid):
    require_roles("PlatformAdmin", "CorporateController", "ManagingPartner")
    return success_object(domain.ser_buyout(domain.get_buyout(bid)))


@bp.route("/buyout-orders/<bid>/approve", methods=["POST"])
def approve_buyout(bid):
    require_roles("CorporateController")
    b = domain.get_buyout(bid)
    if b["status"] != "DRAFT":
        raise conflict(ERR_INVALID_STATE, "Buyout order must be DRAFT to approve")
    contract = db.contracts.get(b["contract_id"])
    if contract is None or contract["status"] != "BUYOUT_PENDING":
        raise conflict(ERR_CONTRACT_NOT_IN_BUYOUT, "Contract is not in BUYOUT_PENDING")
    b["status"] = "APPROVED"
    touch(b)
    return success_object(domain.ser_buyout(b))


@bp.route("/buyout-orders/<bid>/pay", methods=["POST"])
def pay_buyout(bid):
    require_roles("CorporateController")
    b = domain.get_buyout(bid)
    if b["status"] != "APPROVED":
        raise conflict(ERR_INVALID_STATE, "Buyout order must be APPROVED to pay")
    contract = db.contracts.get(b["contract_id"])
    # Depth-3 cascade (§2.8): contract settles, partner withdraws, grants forfeit,
    # swept periods marked paid.
    if contract is not None and contract["status"] == "BUYOUT_PENDING":
        swept = calculations.swept_periods(contract)
        contract["status"] = "SETTLED"
        contract["capital_account_cents"] = 0
        touch(contract)
        partner = db.partners.get(contract["partner_id"])
        if partner is not None and partner["status"] != "WITHDRAWN":
            sweeps.withdraw_partner(partner)
        for period in swept:
            period["partner_share_paid"] = True
            touch(period)
    b["status"] = "PAID"
    touch(b)
    return success_object(domain.ser_buyout(b))
