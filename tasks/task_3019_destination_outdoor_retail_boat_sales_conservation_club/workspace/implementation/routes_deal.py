"""Boat dealership, title work, service department and loading dock routes."""
from core import DB, err, get, find, find_one, create_row, touch, iso, norm_now
import calc
from calc import _parse_iso
import services as S
from services import (Shape, require_store, require_row, ensure_belongs, page,
                      pagination_args, softly)
from app import route, ok, ok_list, created


# ---------------------------------------------------------------------------
# BoatUnit
# ---------------------------------------------------------------------------
@route("POST", "/stores/{store_id}/boat-units", ["DealDeskClerk", "StoreManager"])
def boat_unit_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    stock_no = shape.str(body, "stock_no", required=True)
    model_name = shape.str(body, "model_name", required=True)
    unit_price_cents = shape.int(body, "unit_price_cents", required=True, minimum=0)
    unit_condition = shape.enum(body, "unit_condition", ("NEW", "USED", "DEMO"))
    hull_id_no = shape.str(body, "hull_id_no", required=True)
    motor_price_cents = shape.int(body, "motor_price_cents", minimum=0)
    trailer_price_cents = shape.int(body, "trailer_price_cents", minimum=0)
    prior_title_no = shape.str(body, "prior_title_no")
    shape.raise_now()

    if find_one("boat_units", lambda u: u.get("store_id") == store["id"]
                and u.get("stock_no") == stock_no):
        err("ERR_DUPLICATE_STOCK_NO")
    if find_one("boat_units", lambda u: u.get("store_id") == store["id"]
                and u.get("hull_id_no") == hull_id_no):
        err("ERR_DUPLICATE_HIN")

    row = create_row("boat_units", {
        "store_id": store["id"],
        "stock_no": stock_no,
        "model_name": model_name,
        "unit_price_cents": unit_price_cents,
        "motor_price_cents": 0 if motor_price_cents is None else motor_price_cents,
        "trailer_price_cents": 0 if trailer_price_cents is None else trailer_price_cents,
        "unit_condition": unit_condition,
        "prior_title_no": prior_title_no,
        "hull_id_no": hull_id_no,
        "status": "AVAILABLE",
    })
    return created(row)


@route("GET", "/stores/boat-units/{boat_unit_id}",
       ["DealDeskClerk", "StoreManager", "PlatformAdmin", "Member"])
def boat_unit_read(ctx):
    return ok(require_row("boat_units", ctx.p("boat_unit_id")))


@route("GET", "/stores/boat-units", ["DealDeskClerk", "StoreManager", "PlatformAdmin"])
def boat_unit_list(ctx):
    rows = list(DB.tables["boat_units"].values())
    for key in ("store_id", "status", "unit_condition"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("PATCH", "/stores/boat-units/{boat_unit_id}", ["DealDeskClerk", "StoreManager"])
def boat_unit_patch(ctx):
    unit = require_row("boat_units", ctx.p("boat_unit_id"))
    body = ctx.body
    shape = Shape()
    model_name = shape.str(body, "model_name")
    unit_price_cents = shape.int(body, "unit_price_cents", minimum=0)
    motor_price_cents = shape.int(body, "motor_price_cents", minimum=0)
    trailer_price_cents = shape.int(body, "trailer_price_cents", minimum=0)
    shape.raise_now()
    if model_name is not None:
        unit["model_name"] = model_name
    if unit_price_cents is not None:
        unit["unit_price_cents"] = unit_price_cents
    if motor_price_cents is not None:
        unit["motor_price_cents"] = motor_price_cents
    if trailer_price_cents is not None:
        unit["trailer_price_cents"] = trailer_price_cents
    touch(unit)
    for deal in DB.tables["boat_deals"].values():
        if deal.get("boat_unit_id") == unit["id"]:
            calc.recompute_deal_money(deal)
    return ok(unit)


# ---------------------------------------------------------------------------
# TradeInAppraisal
# ---------------------------------------------------------------------------
@route("POST", "/stores/{store_id}/appraisals", ["DealDeskClerk"])
def appraisal_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    member_id = shape.str(body, "member_id", required=True)
    boat_unit_id = shape.str(body, "boat_unit_id", required=True)
    offer_amount_cents = shape.int(body, "offer_amount_cents", required=True, minimum=0)
    shape.raise_now()
    member = require_row("members", member_id)
    unit = require_row("boat_units", boat_unit_id)
    ensure_belongs("boat_units", unit, store["id"])
    row = create_row("appraisals", {
        "store_id": store["id"],
        "member_id": member["id"],
        "boat_unit_id": unit["id"],
        "offer_amount_cents": offer_amount_cents,
        "accepted_credit_cents": 0,
        "appraised_at_utc": iso(norm_now()),
        "status": "PENDING",
    })
    return created(row)


@route("GET", "/stores/appraisals/{appraisal_id}",
       ["DealDeskClerk", "StoreManager", "PlatformAdmin"])
def appraisal_read(ctx):
    return ok(require_row("appraisals", ctx.p("appraisal_id")))


@route("GET", "/stores/appraisals", ["DealDeskClerk", "StoreManager", "PlatformAdmin"])
def appraisal_list(ctx):
    rows = list(DB.tables["appraisals"].values())
    for key in ("boat_unit_id", "member_id", "store_id", "status"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("GET", "/stores/appraisals/{appraisal_id}/boat-deals",
       ["DealDeskClerk", "StoreManager", "PlatformAdmin"])
def appraisal_deals(ctx):
    ap = require_row("appraisals", ctx.p("appraisal_id"))
    rows = [d for d in DB.tables["boat_deals"].values() if d.get("trade_in_appraisal_id") == ap["id"]]
    stage = ctx.args.get("deal_stage")
    if stage:
        rows = [r for r in rows if r.get("deal_stage") == stage]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("PUT", "/stores/trade-in-appraisals/{appraisal_id}",
       ["DealDeskClerk", "StoreManager"])
def appraisal_put(ctx):
    ap = require_row("appraisals", ctx.p("appraisal_id"))
    body = ctx.body
    if "appraised_at_utc" in body and body.get("appraised_at_utc") is not None:
        err("ERR_TYPE_IMMUTABLE")
    if ap.get("status") not in ("PENDING",):
        err("ERR_INVALID_STATE")
    shape = Shape()
    offer = shape.int(body, "offer_amount_cents", minimum=0)
    shape.raise_now()
    if offer is not None:
        ap["offer_amount_cents"] = offer
    touch(ap)
    return ok(ap)


@route("POST", "/stores/appraisals/{appraisal_id}/accept", ["DealDeskClerk"])
def appraisal_accept(ctx):
    ap = require_row("appraisals", ctx.p("appraisal_id"))
    if ap.get("status") in ("DECLINED", "SUPERSEDED"):
        err("ERR_ALREADY_TERMINAL")
    if ap.get("status") != "PENDING":
        err("ERR_INVALID_STATE")
    member = require_row("members", ap.get("member_id"))
    unit = require_row("boat_units", ap.get("boat_unit_id"))
    ap["accepted_credit_cents"] = calc.trade_in_credit(ap, unit=unit, member=member)
    ap["status"] = "ACCEPTED"
    touch(ap)
    for other in DB.tables["appraisals"].values():
        if other["id"] == ap["id"] or other.get("boat_unit_id") != ap["boat_unit_id"]:
            continue
        if other.get("status") == "ACCEPTED":
            other["status"] = "SUPERSEDED"
            touch(other)
    return ok(ap)


@route("POST", "/stores/appraisals/{appraisal_id}/decline", ["DealDeskClerk"])
def appraisal_decline(ctx):
    ap = require_row("appraisals", ctx.p("appraisal_id"))
    if ap.get("status") in ("DECLINED", "SUPERSEDED"):
        err("ERR_ALREADY_TERMINAL")
    if ap.get("status") != "PENDING":
        err("ERR_INVALID_STATE")
    ap["decline_reason"] = ctx.body.get("decline_reason")
    ap["status"] = "DECLINED"
    touch(ap)
    return ok(ap)


# ---------------------------------------------------------------------------
# TitleFiling
# ---------------------------------------------------------------------------
FILING_KINDS = ("BOAT_TITLE", "MOTOR_TITLE", "TRAILER_REGISTRATION", "LIEN_RELEASE")


def _check_filing_rules(store, unit, filing_kind, state_code):
    if state_code != store.get("state_code"):
        err("ERR_TITLE_STATE_MISMATCH")
    if filing_kind == "LIEN_RELEASE" and not unit.get("prior_title_no"):
        err("ERR_TITLE_STATE_MISMATCH")


@route("POST", "/stores/{store_id}/title-filings", ["TitleClerk", "DealDeskClerk"])
def filing_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    boat_unit_id = shape.str(body, "boat_unit_id", required=True)
    filing_kind = shape.enum(body, "filing_kind", FILING_KINDS)
    state_code = shape.str(body, "state_code", required=True)
    shape.raise_now()
    unit = require_row("boat_units", boat_unit_id)
    ensure_belongs("boat_units", unit, store["id"])
    _check_filing_rules(store, unit, filing_kind, state_code)
    row = create_row("title_filings", {
        "store_id": store["id"],
        "boat_unit_id": unit["id"],
        "filing_kind": filing_kind,
        "state_code": state_code,
        "agency_reference": None,
        "filed_at_utc": None,
        "acknowledged_at_utc": None,
        "status": "DRAFT",
    })
    return created(row)


@route("GET", "/stores/title-filings/{filing_id}",
       ["TitleClerk", "DealDeskClerk", "StoreManager", "PlatformAdmin"])
def filing_read(ctx):
    return ok(require_row("title_filings", ctx.p("filing_id")))


@route("GET", "/stores/title-filings",
       ["TitleClerk", "DealDeskClerk", "StoreManager", "PlatformAdmin"])
def filing_list(ctx):
    rows = list(DB.tables["title_filings"].values())
    for key in ("boat_unit_id", "store_id", "state_code", "status"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("POST", "/stores/title-filings/{filing_id}/submit", ["TitleClerk"])
def filing_submit(ctx):
    filing = require_row("title_filings", ctx.p("filing_id"))
    if filing.get("status") in ("ISSUED", "REJECTED"):
        err("ERR_ALREADY_TERMINAL")
    if filing.get("status") != "DRAFT":
        err("ERR_INVALID_STATE")
    filing["status"] = "SUBMITTED"
    filing["filed_at_utc"] = iso(norm_now())
    touch(filing)
    return ok(filing)


@route("POST", "/stores/title-filings/{filing_id}/issue", ["TitleClerk", "AgencyOperator"])
def filing_issue(ctx):
    filing = require_row("title_filings", ctx.p("filing_id"))
    store = get("stores", filing.get("store_id"))
    unit = get("boat_units", filing.get("boat_unit_id"))
    if store is not None and unit is not None:
        _check_filing_rules(store, unit, filing.get("filing_kind"),
                            filing.get("state_code"))
    if filing.get("status") in ("ISSUED", "REJECTED"):
        err("ERR_ALREADY_TERMINAL")
    if filing.get("status") != "SUBMITTED":
        err("ERR_INVALID_STATE")
    filing["agency_reference"] = ctx.body.get("agency_reference")
    filing["status"] = "ISSUED"
    filing["acknowledged_at_utc"] = iso(norm_now())
    touch(filing)
    _deal_title_issued(filing)
    return ok(filing)


def _deal_title_issued(filing):
    if filing.get("filing_kind") != "BOAT_TITLE":
        return
    deal = find_one("boat_deals", lambda d: d.get("title_filing_id") == filing["id"])
    if deal is None:
        return
    deal["title_status"] = "ISSUED"
    touch(deal)
    S.deal_rigging_complete(deal)


@route("POST", "/stores/title-filings/{filing_id}/reject", ["AgencyOperator"])
def filing_reject(ctx):
    filing = require_row("title_filings", ctx.p("filing_id"))
    if filing.get("status") == "REJECTED":
        err("ERR_ALREADY_TERMINAL")
    if filing.get("status") not in ("SUBMITTED", "ISSUED"):
        err("ERR_INVALID_STATE")
    filing["rejection_reason"] = ctx.body.get("rejection_reason")
    filing["status"] = "REJECTED"
    touch(filing)
    S.apply_deal_title_rejection(filing)
    return ok(filing)


# ---------------------------------------------------------------------------
# BoatDeal
# ---------------------------------------------------------------------------
def _deal_or_404(deal_id):
    return require_row("boat_deals", deal_id)


@route("POST", "/stores/{store_id}/boat-deals", ["DealDeskClerk"])
def deal_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    member_id = shape.str(body, "member_id", required=True)
    boat_unit_id = shape.str(body, "boat_unit_id", required=True)
    trade_in_appraisal_id = shape.str(body, "trade_in_appraisal_id")
    deposit_cents = shape.int(body, "deposit_cents", minimum=0)
    shape.raise_now()
    member = require_row("members", member_id)
    unit = require_row("boat_units", boat_unit_id)
    ensure_belongs("boat_units", unit, store["id"])
    if trade_in_appraisal_id is not None:
        require_row("appraisals", trade_in_appraisal_id)

    member_card = member.get("club_card_status")
    row = create_row("boat_deals", {
        "store_id": store["id"],
        "member_id": member["id"],
        "boat_unit_id": unit["id"],
        "trade_in_appraisal_id": trade_in_appraisal_id,
        "deal_stage": "QUOTED",
        "funding_status": "UNFUNDED",
        "title_status": "NOT_STARTED",
        "title_filing_id": None,
        "rigging_status": "NOT_STARTED",
        "contract_price_cents": 0,
        "total_fee_cents": 0,
        "balance_due_cents": 0,
        "deposit_cents": 0 if deposit_cents is None else deposit_cents,
        "funded_amount_cents": 0,
        "points_awarded": 0,
        "settlement_variance_cents": 0,
        "_contract_card_active": member_card == "ACTIVE",
    })
    calc.recompute_deal_money(row, bump=False)
    return created(row)


@route("GET", "/stores/boat-deals/{deal_id}",
       ["DealDeskClerk", "FinanceAdmin", "StoreManager", "PlatformAdmin", "Member"])
def deal_read(ctx):
    deal = _deal_or_404(ctx.p("deal_id"))
    S.maybe_auto_deliver(deal)
    return ok(deal)


@route("GET", "/stores/boat-deals",
       ["DealDeskClerk", "FinanceAdmin", "StoreManager", "PlatformAdmin"])
def deal_list(ctx):
    rows = list(DB.tables["boat_deals"].values())
    for key in ("store_id", "member_id", "boat_unit_id", "trade_in_appraisal_id", "deal_stage"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


def _occ(deal, body):
    expected = body.get("expected_deal_version")
    if expected is None:
        return
    if not isinstance(expected, int) or isinstance(expected, bool):
        err("ERR_INVALID_REQUEST", "expected_deal_version must be an integer.")
    if expected != int(deal.get("version", 0)):
        err("ERR_STALE_VERSION")


@route("POST", "/stores/boat-deals/{deal_id}/contract", ["DealDeskClerk"])
def deal_contract(ctx):
    deal = _deal_or_404(ctx.p("deal_id"))
    S.maybe_auto_deliver(deal)
    _occ(deal, ctx.body)
    if deal.get("deal_stage") == "SETTLED":
        err("ERR_ALREADY_TERMINAL")
    if deal.get("deal_stage") != "QUOTED":
        err("ERR_INVALID_STATE")
    store = require_store(deal.get("store_id"))
    unit = require_row("boat_units", deal.get("boat_unit_id"))
    if unit.get("status") != "AVAILABLE":
        err("ERR_INVALID_STATE", "The hull is not available.")
    appr_id = deal.get("trade_in_appraisal_id")
    if appr_id:
        ap = require_row("appraisals", appr_id)
        if ap.get("status") != "ACCEPTED":
            err("ERR_INVALID_STATE", "The trade-in appraisal is not accepted.")
        if ap.get("member_id") != deal.get("member_id"):
            err("ERR_INVALID_STATE", "The appraisal belongs to another member.")
    member = require_row("members", deal.get("member_id"))
    if member.get("club_card_status") not in ("ACTIVE", "SUSPENDED", "NONE"):
        err("ERR_INVALID_STATE", "The member's club card status blocks contracting.")
    if calc.refresh_posture(store) == "FROZEN":
        err("ERR_POSTURE_FROZEN")

    deal["_contract_card_active"] = member.get("club_card_status") == "ACTIVE"

    unit["status"] = "DEAL_PENDING"
    touch(unit)
    deal["deal_stage"] = "CONTRACTED"

    filing = create_row("title_filings", {
        "store_id": store["id"],
        "boat_unit_id": unit["id"],
        "filing_kind": "BOAT_TITLE",
        "state_code": store.get("state_code"),
        "agency_reference": None,
        "filed_at_utc": None,
        "acknowledged_at_utc": None,
        "status": "DRAFT",
    })
    deal["title_filing_id"] = filing["id"]
    deal["title_status"] = "FILED"

    calc.recompute_deal_money(deal, bump=False)
    touch(deal)
    touch(store)
    return ok(deal)


@route("POST", "/stores/boat-deals/{deal_id}/funding", ["FinanceAdmin"])
def deal_funding(ctx):
    deal = _deal_or_404(ctx.p("deal_id"))
    S.maybe_auto_deliver(deal)
    _occ(deal, ctx.body)
    shape = Shape()
    amount = shape.int(ctx.body, "amount_cents", required=True, minimum=0)
    shape.raise_now()
    if deal.get("deal_stage") == "SETTLED":
        err("ERR_ALREADY_TERMINAL")
    if deal.get("deal_stage") not in ("CONTRACTED", "DELIVERED"):
        err("ERR_INVALID_STATE")
    balance = int(deal.get("balance_due_cents", 0) or 0)
    funding_status = deal.get("funding_status")
    if funding_status == "FUNDED":
        err("ERR_INVALID_STATE", "The deal is already funded.")
    if funding_status == "REFUNDED":
        err("ERR_INVALID_STATE", "A refunded deal cannot be re-funded.")
    if amount < balance:
        err("ERR_FUNDING_SHORTFALL")
    if funding_status == "UNFUNDED":
        # UNFUNDED -> FUNDED in one step: the recorded amount is the whole
        # obligation, so the balance is recomputed down to zero.
        deal["funding_status"] = "FUNDED"
        deal["funded_amount_cents"] = amount
        calc.recompute_deal_money(deal, bump=False)
        deal["balance_due_cents"] = 0
        touch(deal)
        S.deal_rigging_complete(deal)
        return ok(deal)
    # PENDING -> FUNDED: the balance is recomputed from the recorded amount.
    deal["funding_status"] = "FUNDED"
    deal["funded_amount_cents"] = amount
    calc.recompute_deal_money(deal, bump=False)
    touch(deal)
    S.deal_rigging_complete(deal)
    return ok(deal)


@route("POST", "/stores/boat-deals/{deal_id}/refund", ["FinanceAdmin"])
def deal_refund(ctx):
    deal = _deal_or_404(ctx.p("deal_id"))
    S.maybe_auto_deliver(deal)
    _occ(deal, ctx.body)
    # Refund is a funding-dimension act, so it is the funding state that the
    # transition table gates; a SETTLED deal keeps its FUNDED dimension and is
    # simply outside the state the transition declares.
    if deal.get("funding_status") != "FUNDED":
        err("ERR_INVALID_STATE")
    if deal.get("deal_stage") == "SETTLED":
        err("ERR_INVALID_STATE")
    deal["funding_status"] = "REFUNDED"
    deal["funded_amount_cents"] = 0
    calc.recompute_deal_money(deal, bump=False)
    touch(deal)
    S.deal_auto_revert(deal)
    return ok(deal)


@route("POST", "/stores/boat-deals/{deal_id}/settle", ["FinanceAdmin"])
def deal_settle(ctx):
    deal = _deal_or_404(ctx.p("deal_id"))
    S.maybe_auto_deliver(deal)
    _occ(deal, ctx.body)
    if deal.get("deal_stage") == "SETTLED":
        err("ERR_ALREADY_TERMINAL")
    if deal.get("deal_stage") != "DELIVERED":
        err("ERR_INVALID_STATE")
    if int(deal.get("balance_due_cents", 0) or 0) > 0:
        err("ERR_BALANCE_OUTSTANDING")
    member = require_row("members", deal.get("member_id"))
    previous_tier = member.get("club_tier")
    points = calc.deal_points_award(deal)
    deal["deal_stage"] = "SETTLED"
    deal["points_awarded"] = points
    calc.recompute_deal_money(deal, bump=False)
    touch(deal)
    S.post_point_event(deal.get("store_id"), member, "AWARD", points, deal["id"])
    S.maybe_attach_pending_club_card(member, previous_tier)
    store = get("stores", deal.get("store_id"))
    if store is not None:
        touch(store)
    return ok(deal)


@route("GET", "/stores/{store_id}/boat-deals/{deal_id}/service-orders",
       ["ServiceWriter", "DealDeskClerk", "StoreManager", "PlatformAdmin"])
def deal_service_orders(ctx):
    store = require_store(ctx.p("store_id"))
    deal = require_row("boat_deals", ctx.p("deal_id"))
    ensure_belongs("boat_deals", deal, store["id"])
    rows = [o for o in DB.tables["service_orders"].values()
            if o.get("deal_id") == deal["id"] or o.get("boat_deal_id") == deal["id"]]
    status = ctx.args.get("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


# ---------------------------------------------------------------------------
# ServiceOrder
# ---------------------------------------------------------------------------
ORDER_KINDS = ("RIGGING", "OVERSIZE_LOADING", "TAXIDERMY", "OUTFITTING", "POND_MAINTENANCE")


@route("POST", "/stores/{store_id}/service-orders", ["ServiceWriter", "ServiceTechnician"])
def service_order_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    boat_unit_id = shape.str(body, "boat_unit_id")
    order_kind = shape.enum(body, "order_kind", ORDER_KINDS)
    promised_lead_days = shape.int(body, "promised_lead_days", required=True, minimum=0)
    deal_id = shape.str(body, "deal_id")
    boat_deal_id = shape.str(body, "boat_deal_id")
    shape.raise_now()
    if boat_unit_id is not None:
        unit = require_row("boat_units", boat_unit_id)
        ensure_belongs("boat_units", unit, store["id"])
    linked_deal = deal_id if deal_id is not None else boat_deal_id
    if linked_deal is not None:
        require_row("boat_deals", linked_deal)

    if order_kind == "RIGGING" and linked_deal is not None:
        open_order = find_one("service_orders", lambda o: o.get("deal_id") == linked_deal
                              and o.get("order_kind") == "RIGGING"
                              and o.get("status") not in ("DELIVERED", "CANCELLED"))
        if open_order is not None:
            err("ERR_RIGGING_ALREADY_OPEN")

    row = create_row("service_orders", {
        "store_id": store["id"],
        "boat_unit_id": boat_unit_id,
        "deal_id": linked_deal,
        "boat_deal_id": boat_deal_id if boat_deal_id is not None else linked_deal,
        "order_kind": order_kind,
        "promised_lead_days": promised_lead_days,
        "started_at_utc": None,
        "completed_at_utc": None,
        "actual_lead_days": 0,
        "is_late": False,
        "status": "INTAKE",
    })
    return created(row)


@route("GET", "/stores/service-orders/{order_id}",
       ["ServiceWriter", "ServiceTechnician", "StoreManager", "PlatformAdmin"])
def service_order_read(ctx):
    return ok(require_row("service_orders", ctx.p("order_id")))


@route("GET", "/stores/service-orders",
       ["ServiceWriter", "ServiceTechnician", "StoreManager", "PlatformAdmin"])
def service_order_list(ctx):
    rows = list(DB.tables["service_orders"].values())
    for key in ("boat_unit_id", "boat_deal_id", "deal_id", "store_id", "order_kind", "status"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("POST", "/stores/service-orders/{order_id}/schedule",
       ["ServiceTechnician", "ServiceWriter"])
def service_order_schedule(ctx):
    order = require_row("service_orders", ctx.p("order_id"))
    if order.get("status") in ("DELIVERED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL")
    if order.get("status") != "INTAKE":
        err("ERR_INVALID_STATE")
    for ful in DB.tables["order_fulfillments"].values():
        if ful.get("pre_service_order_id") != order["id"]:
            continue
        if ful.get("status") != "READY_FOR_RELEASE":
            err("ERR_FULFILLMENT_BLOCKED")
    if order.get("order_kind") == "RIGGING":
        clash = find_one("service_orders", lambda o: o["id"] != order["id"]
                         and o.get("boat_unit_id") == order.get("boat_unit_id")
                         and o.get("order_kind") == "RIGGING"
                         and o.get("status") == "IN_PROGRESS")
        if clash is not None:
            err("ERR_FULFILLMENT_BLOCKED", "Another rigging order is already in progress.")
    order["status"] = "SCHEDULED"
    touch(order)
    if order.get("order_kind") == "RIGGING" and order.get("deal_id"):
        deal = get("boat_deals", order.get("deal_id"))
        if deal is not None and deal.get("rigging_status") == "NOT_STARTED":
            deal["rigging_status"] = "SCHEDULED"
            touch(deal)
    return ok(order)


@route("POST", "/stores/service-orders/{order_id}/start", ["ServiceTechnician"])
def service_order_start(ctx):
    order = require_row("service_orders", ctx.p("order_id"))
    if order.get("status") in ("DELIVERED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL")
    if order.get("status") != "SCHEDULED":
        err("ERR_INVALID_STATE")
    store = require_store(order.get("store_id"))
    if calc.refresh_posture(store) == "FROZEN":
        err("ERR_POSTURE_FROZEN")
    order["status"] = "IN_PROGRESS"
    order["started_at_utc"] = iso(norm_now())
    touch(order)
    return ok(order)


@route("POST", "/stores/service-orders/{order_id}/complete", ["ServiceTechnician"])
def service_order_complete(ctx):
    order = require_row("service_orders", ctx.p("order_id"))
    if order.get("status") in ("DELIVERED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL")
    if order.get("status") != "IN_PROGRESS":
        err("ERR_INVALID_STATE")
    order["completed_at_utc"] = iso(norm_now())
    order["status"] = "COMPLETED"
    calc.lead_time_actual(order, endpoint=_parse_iso(order["completed_at_utc"]), bump=False)
    touch(order)
    return ok(order)


@route("POST", "/stores/service-orders/{order_id}/deliver",
       ["ServiceTechnician", "PlatformAdmin"])
def service_order_deliver(ctx):
    order = require_row("service_orders", ctx.p("order_id"))
    if order.get("status") in ("DELIVERED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL")
    if order.get("status") != "COMPLETED":
        err("ERR_INVALID_STATE")
    if order.get("order_kind") == "OVERSIZE_LOADING":
        # PRD §3.6: "the check-in is what lets the bay's linked OVERSIZE_LOADING
        # work order move from SCHEDULED to IN_PROGRESS", so a load that was
        # never checked in cannot be handed over.
        booking = find_one("bay_bookings", lambda b: b.get("service_order_id") == order["id"])
        if booking is not None and booking.get("status") not in ("CHECKED_IN", "COMPLETED"):
            err("ERR_INVALID_STATE", "The linked bay booking is not checked in.")
    order["status"] = "DELIVERED"
    touch(order)
    if order.get("order_kind") == "RIGGING" and order.get("deal_id"):
        deal = get("boat_deals", order.get("deal_id"))
        if deal is not None and deal.get("rigging_status") != "COMPLETE":
            deal["rigging_status"] = "COMPLETE"
            touch(deal)
            S.deal_rigging_complete(deal)
    return ok(order)


@route("POST", "/stores/service-orders/{order_id}/cancel",
       ["ServiceWriter", "PlatformAdmin"])
def service_order_cancel(ctx):
    order = require_row("service_orders", ctx.p("order_id"))
    if order.get("status") in ("DELIVERED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL")
    if order.get("status") not in ("INTAKE", "SCHEDULED"):
        err("ERR_INVALID_STATE")
    order["status"] = "CANCELLED"
    touch(order)
    intake = find_one("service_intakes", lambda i: i.get("service_order_id") == order["id"])
    if intake is not None and int(intake.get("deposit_cents", 0) or 0) > 0:
        member = get("members", intake.get("member_id"))
        if member is not None:
            S.post_point_event(order.get("store_id"), member, "ADJUST",
                               int(intake.get("deposit_cents", 0)) // 10)
    return ok(order)


# ---------------------------------------------------------------------------
# ServiceIntake
# ---------------------------------------------------------------------------
INTAKE_KINDS = ("TAXIDERMY", "OUTFITTING", "BOAT_SERVICE")


@route("POST", "/stores/{store_id}/service-intakes", ["ServiceWriter"])
def intake_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    member_id = shape.str(body, "member_id", required=True)
    service_order_id = shape.str(body, "service_order_id", required=True)
    intake_kind = shape.enum(body, "intake_kind", INTAKE_KINDS)
    specimen_quantity = shape.int(body, "specimen_quantity", required=True, minimum=0)
    quoted_lead_days = shape.int(body, "quoted_lead_days", required=True, minimum=0)
    deposit_cents = shape.int(body, "deposit_cents", minimum=0)
    species_code = shape.str(body, "species_code")
    permit_sale_id = shape.str(body, "permit_sale_id")
    shape.raise_now()
    member = require_row("members", member_id)
    order = require_row("service_orders", service_order_id)
    ensure_belongs("service_orders", order, store["id"])
    if permit_sale_id is not None:
        require_row("permit_sales", permit_sale_id)

    row = create_row("service_intakes", {
        "store_id": store["id"],
        "member_id": member["id"],
        "service_order_id": order["id"],
        "intake_kind": intake_kind,
        "species_code": species_code,
        "permit_sale_id": permit_sale_id,
        "specimen_quantity": specimen_quantity,
        "deposit_cents": 0 if deposit_cents is None else deposit_cents,
        "quoted_lead_days": quoted_lead_days,
        "project_charge_cents": 0,
        "status": "INTAKE_QUOTED",
    })
    _permit_gate(row, row.get("permit_sale_id"), permit_kind=intake_kind)
    row["project_charge_cents"] = calc.intake_project_charge(row, "INTAKE_QUOTED")
    return created(row)


def _permit_gate(row, permit_sale_id, permit_kind):
    """p11 lawful-take permit rule for TAXIDERMY intakes."""
    if row.get("intake_kind") == "TAXIDERMY":
        sale = get("permit_sales", permit_sale_id) if permit_sale_id else None
        if sale is None:
            err("ERR_PERMIT_VERIFICATION_REQUIRED")
        if sale.get("permit_type") not in ("HUNTING", "ARCHERY_RANGE"):
            err("ERR_PERMIT_VERIFICATION_REQUIRED")
        if sale.get("status") not in ("ISSUED", "REMITTED"):
            err("ERR_PERMIT_VERIFICATION_REQUIRED")
    else:
        if permit_sale_id is not None:
            err("ERR_PERMIT_VERIFICATION_REQUIRED")


@route("GET", "/stores/service-intakes/{intake_id}",
       ["ServiceWriter", "ServiceTechnician", "StoreManager", "PlatformAdmin", "Member"])
def intake_read(ctx):
    return ok(require_row("service_intakes", ctx.p("intake_id")))


@route("GET", "/stores/service-intakes",
       ["ServiceWriter", "ServiceTechnician", "StoreManager", "PlatformAdmin"])
def intake_list(ctx):
    rows = list(DB.tables["service_intakes"].values())
    for key in ("service_order_id", "permit_sale_id", "member_id", "store_id", "status"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("PUT", "/stores/{store_id}/service-intakes/{intake_id}", ["ServiceWriter"])
def intake_put(ctx):
    store = require_store(ctx.p("store_id"))
    intake = require_row("service_intakes", ctx.p("intake_id"))
    ensure_belongs("service_intakes", intake, store["id"])
    body = ctx.body
    if "specimen_quantity" in body and body.get("specimen_quantity") is not None:
        rank = calc.INTAKE_STAGE_ORDER.index(intake.get("status"))
        if rank >= calc.INTAKE_STAGE_ORDER.index("MATERIALS_ORDERED"):
            err("ERR_TYPE_IMMUTABLE")
    shape = Shape()
    species_code = shape.str(body, "species_code")
    specimen_quantity = shape.int(body, "specimen_quantity", minimum=0)
    quoted_lead_days = shape.int(body, "quoted_lead_days", minimum=0)
    shape.raise_now()
    if species_code is not None:
        intake["species_code"] = species_code
    if specimen_quantity is not None:
        intake["specimen_quantity"] = specimen_quantity
    if quoted_lead_days is not None:
        intake["quoted_lead_days"] = quoted_lead_days
    touch(intake)
    return ok(intake)


@route("POST", "/stores/service-intakes/{intake_id}/verify-permit", ["ServiceWriter"])
def intake_verify_permit(ctx):
    intake = require_row("service_intakes", ctx.p("intake_id"))
    if intake.get("status") in ("RELEASED", "ABANDONED"):
        err("ERR_ALREADY_TERMINAL")
    if intake.get("status") != "INTAKE_QUOTED":
        err("ERR_INVALID_STATE")
    _permit_gate(intake, intake.get("permit_sale_id"), permit_kind=intake.get("intake_kind"))
    intake["status"] = "PERMIT_VERIFIED"
    intake["project_charge_cents"] = calc.intake_project_charge(intake, "PERMIT_VERIFIED")
    touch(intake)
    order = get("service_orders", intake.get("service_order_id"))
    if order is not None and int(intake["project_charge_cents"]) > 0:
        calc.lead_time_actual(order)
    return ok(intake)


@route("POST", "/stores/service-intakes/{intake_id}/order-materials", ["ServiceWriter"])
def intake_order_materials(ctx):
    intake = require_row("service_intakes", ctx.p("intake_id"))
    if intake.get("status") in ("RELEASED", "ABANDONED"):
        err("ERR_ALREADY_TERMINAL")
    if intake.get("status") != "PERMIT_VERIFIED":
        err("ERR_INVALID_STATE")
    if int(intake.get("deposit_cents", 0) or 0) < 5000:
        err("ERR_OUTSTANDING_DEPOSIT_REQUIRED")
    intake["status"] = "MATERIALS_ORDERED"
    intake["project_charge_cents"] = calc.intake_project_charge(intake, "MATERIALS_ORDERED")
    touch(intake)
    return ok(intake)


@route("POST", "/stores/service-intakes/{intake_id}/begin-curing", ["ServiceTechnician"])
def intake_begin_curing(ctx):
    intake = require_row("service_intakes", ctx.p("intake_id"))
    if intake.get("status") in ("RELEASED", "ABANDONED"):
        err("ERR_ALREADY_TERMINAL")
    if intake.get("status") != "MATERIALS_ORDERED":
        err("ERR_INVALID_STATE")
    if intake.get("intake_kind") == "TAXIDERMY" and int(intake.get("specimen_quantity", 0) or 0) > 20:
        err("ERR_INVALID_REQUEST", "Too many specimens for curing.")
    intake["status"] = "CURING"
    intake["project_charge_cents"] = calc.intake_project_charge(intake, "CURING")
    touch(intake)
    order = get("service_orders", intake.get("service_order_id"))
    if order is not None:
        order["promised_lead_days"] = int(intake.get("quoted_lead_days", 0) or 0) + calc.CURING_EXTRA_LEAD_DAYS
        touch(order)
    return ok(intake)


@route("POST", "/stores/service-intakes/{intake_id}/mark-ready", ["ServiceTechnician"])
def intake_mark_ready(ctx):
    intake = require_row("service_intakes", ctx.p("intake_id"))
    if intake.get("status") in ("RELEASED", "ABANDONED"):
        err("ERR_ALREADY_TERMINAL")
    if intake.get("status") != "CURING":
        err("ERR_INVALID_STATE")
    intake["status"] = "READY_FOR_PICKUP"
    intake["project_charge_cents"] = calc.intake_project_charge(intake, "READY_FOR_PICKUP")
    touch(intake)
    order = get("service_orders", intake.get("service_order_id"))
    if order is not None:
        order["status"] = "COMPLETED"
        order["completed_at_utc"] = iso(norm_now())
        calc.lead_time_actual(order, endpoint=_parse_iso(order["completed_at_utc"]), bump=False)
        touch(order)
    return ok(intake)


@route("POST", "/stores/service-intakes/{intake_id}/release", ["ServiceWriter"])
def intake_release(ctx):
    intake = require_row("service_intakes", ctx.p("intake_id"))
    if intake.get("status") in ("RELEASED", "ABANDONED"):
        err("ERR_ALREADY_TERMINAL")
    if intake.get("status") != "READY_FOR_PICKUP":
        err("ERR_INVALID_STATE")
    order = require_row("service_orders", intake.get("service_order_id"))
    if order.get("status") != "COMPLETED":
        err("ERR_INVALID_STATE", "The linked work order is not completed.")
    intake["status"] = "RELEASED"
    touch(intake)
    return ok(intake)


@route("GET", "/stores/permit-sales/{sale_id}/service-intakes",
       ["ServiceWriter", "PermitClerk", "StoreManager", "PlatformAdmin"])
def permit_sale_intakes(ctx):
    sale = require_row("permit_sales", ctx.p("sale_id"))
    rows = [i for i in DB.tables["service_intakes"].values() if i.get("permit_sale_id") == sale["id"]]
    status = ctx.args.get("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


# ---------------------------------------------------------------------------
# LoadingBayBooking
# ---------------------------------------------------------------------------
@route("POST", "/stores/{store_id}/bay-bookings", ["ReceivingManager", "StoreManager"])
def bay_booking_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    bay_no = shape.int(body, "bay_no", required=True, minimum=0)
    member_id = shape.str(body, "member_id", required=True)
    service_order_id = shape.str(body, "service_order_id", required=True)
    booked_start = shape.dt(body, "booked_start_utc", required=True)
    booked_end = shape.dt(body, "booked_end_utc", required=True)
    shape.raise_now()
    if bay_no < 1 or bay_no > int(store.get("load_bays_total", 0) or 0):
        err("ERR_BAY_NOT_FOUND")
    member = require_row("members", member_id)
    order = require_row("service_orders", service_order_id)
    ensure_belongs("service_orders", order, store["id"])
    if booked_end is None or booked_start is None or booked_end <= booked_start:
        err("ERR_INVALID_SLOT_WINDOW")
    _bay_conflict(store, bay_no, booked_start, booked_end)
    row = create_row("bay_bookings", {
        "store_id": store["id"],
        "bay_no": bay_no,
        "member_id": member["id"],
        "service_order_id": order["id"],
        "booked_start_utc": iso(booked_start),
        "booked_end_utc": iso(booked_end),
        "status": "RESERVED",
    })
    return created(row)


def _bay_conflict(store, bay_no, start, end, exclude=None):
    from datetime import timedelta
    buffered_start = start - timedelta(minutes=15)
    buffered_end = end + timedelta(minutes=15)
    for b in DB.tables["bay_bookings"].values():
        if exclude is not None and b["id"] == exclude:
            continue
        if b.get("store_id") != store["id"] or b.get("bay_no") != bay_no:
            continue
        if b.get("status") == "CANCELLED":
            continue
        b_start = _parse_iso(b.get("booked_start_utc"))
        b_end = _parse_iso(b.get("booked_end_utc"))
        if b_start is None or b_end is None:
            continue
        if S.overlapping(buffered_start, buffered_end, b_start, b_end):
            err("ERR_BAY_BOOKING_CONFLICT")


@route("GET", "/stores/bay-bookings/{booking_id}",
       ["ReceivingManager", "StoreManager", "PlatformAdmin"])
def bay_booking_read(ctx):
    return ok(require_row("bay_bookings", ctx.p("booking_id")))


@route("GET", "/stores/bay-bookings", ["ReceivingManager", "StoreManager", "PlatformAdmin"])
def bay_booking_list(ctx):
    rows = list(DB.tables["bay_bookings"].values())
    for key in ("store_id", "member_id", "service_order_id", "status"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if str(r.get(key)) == value]
    bay_no = ctx.args.get("bay_no")
    if bay_no:
        rows = [r for r in rows if str(r.get("bay_no")) == bay_no]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("GET", "/stores/{store_id}/load-bays/{bay_no}/bookings",
       ["ReceivingManager", "StoreManager", "PlatformAdmin"])
def load_bay_bookings(ctx):
    store = require_store(ctx.p("store_id"))
    try:
        bay_no = int(ctx.p("bay_no"))
    except (TypeError, ValueError):
        err("ERR_RESOURCE_NOT_FOUND")
    rows = [b for b in DB.tables["bay_bookings"].values()
            if b.get("store_id") == store["id"] and b.get("bay_no") == bay_no]
    status = ctx.args.get("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("POST", "/stores/bay-bookings/{booking_id}/check-in", ["ReceivingManager"])
def bay_booking_check_in(ctx):
    booking = require_row("bay_bookings", ctx.p("booking_id"))
    if booking.get("status") in ("COMPLETED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL")
    if booking.get("status") != "RESERVED":
        err("ERR_INVALID_STATE")
    booking["status"] = "CHECKED_IN"
    touch(booking)
    order = get("service_orders", booking.get("service_order_id"))
    if order is not None and order.get("order_kind") == "OVERSIZE_LOADING" \
            and order.get("status") == "SCHEDULED":
        order["status"] = "IN_PROGRESS"
        order["started_at_utc"] = iso(norm_now())
        touch(order)
    return ok(booking)


@route("POST", "/stores/bay-bookings/{booking_id}/cancel",
       ["ReceivingManager", "PlatformAdmin"])
def bay_booking_cancel(ctx):
    booking = require_row("bay_bookings", ctx.p("booking_id"))
    if booking.get("status") in ("COMPLETED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL")
    booking["status"] = "CANCELLED"
    touch(booking)
    return ok(booking)


# ---------------------------------------------------------------------------
# OrderFulfillment
# ---------------------------------------------------------------------------
FULFILLMENT_KINDS = ("OVERSIZE_CARRYOUT", "BOAT_DELIVERY_ORIENTATION")


@route("POST", "/stores/{store_id}/order-fulfillments", ["ReceivingManager"])
def fulfillment_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    member_id = shape.str(body, "member_id", required=True)
    order_kind = shape.enum(body, "order_kind", FULFILLMENT_KINDS)
    pre_service_order_id = shape.str(body, "pre_service_order_id", required=True)
    booking_id = shape.str(body, "booking_id", required=True)
    waiver_id = shape.str(body, "waiver_id")
    expected_booking_version = shape.int(body, "expected_booking_version")
    shape.raise_now()
    member = require_row("members", member_id)
    order = require_row("service_orders", pre_service_order_id)
    ensure_belongs("service_orders", order, store["id"])
    booking = require_row("bay_bookings", booking_id)
    ensure_belongs("bay_bookings", booking, store["id"])
    if waiver_id is not None:
        require_row("waivers", waiver_id)

    if expected_booking_version is not None \
            and expected_booking_version != int(booking.get("version", 0)):
        err("ERR_STALE_VERSION")

    row = create_row("order_fulfillments", {
        "store_id": store["id"],
        "member_id": member["id"],
        "order_kind": order_kind,
        "pre_service_order_id": order["id"],
        "booking_id": booking["id"],
        "waiver_id": waiver_id,
        "rm_cross_check_code": None,
        "fulfilled_at_utc": None,
        "status": "READY_FOR_RELEASE",
    })
    touch(booking)
    return created(row)


@route("GET", "/stores/order-fulfillments/{fulfillment_id}",
       ["ReceivingManager", "StoreManager", "PlatformAdmin", "Member"])
def fulfillment_read(ctx):
    return ok(require_row("order_fulfillments", ctx.p("fulfillment_id")))


@route("GET", "/stores/order-fulfillments",
       ["ReceivingManager", "StoreManager", "PlatformAdmin"])
def fulfillment_list(ctx):
    rows = list(DB.tables["order_fulfillments"].values())
    for key in ("pre_service_order_id", "booking_id", "member_id", "waiver_id",
                "store_id", "status"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("POST", "/stores/order-fulfillments/{fulfillment_id}/release", ["ReceivingManager"])
def fulfillment_release(ctx):
    ful = require_row("order_fulfillments", ctx.p("fulfillment_id"))
    if ful.get("status") in ("RELEASED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL")
    if ful.get("status") != "READY_FOR_RELEASE":
        err("ERR_INVALID_STATE")
    body = ctx.body

    order = require_row("service_orders", ful.get("pre_service_order_id"))
    if order.get("status") != "DELIVERED":
        err("ERR_FULFILLMENT_BLOCKED")

    if ful.get("order_kind") == "BOAT_DELIVERY_ORIENTATION":
        waiver = get("waivers", ful.get("waiver_id")) if ful.get("waiver_id") else None
        if waiver is None or waiver.get("activity_scope") != "BOAT_DELIVERY_ORIENTATION" \
                or waiver.get("member_id") != ful.get("member_id"):
            err("ERR_WAIVER_REQUIRED")
        expires = _parse_iso(waiver.get("expires_on"))
        if waiver.get("status") != "SIGNED" or expires is None or expires <= calc.now():
            err("ERR_WAIVER_EXPIRED")

    if ful.get("order_kind") == "OVERSIZE_CARRYOUT":
        booking = require_row("bay_bookings", ful.get("booking_id"))
        if booking.get("status") not in ("CHECKED_IN", "COMPLETED"):
            err("ERR_INVALID_STATE", "The bay booking is not checked in.")

    code = body.get("rm_cross_check_code")
    if not isinstance(code, str) or code == "" or code == ful.get("member_id"):
        err("ERR_RECEIVING_CROSS_CHECK_REQUIRED")

    ful["rm_cross_check_code"] = code
    ful["status"] = "RELEASED"
    ful["fulfilled_at_utc"] = iso(norm_now())
    touch(ful)
    booking = get("bay_bookings", ful.get("booking_id"))
    if booking is not None and booking.get("status") == "CHECKED_IN":
        order2 = get("service_orders", booking.get("service_order_id"))
        if order2 is not None and order2.get("status") == "DELIVERED":
            booking["status"] = "COMPLETED"
            touch(booking)
    return ok(ful)


@route("POST", "/stores/order-fulfillments/{fulfillment_id}/cancel",
       ["ReceivingManager", "PlatformAdmin"])
def fulfillment_cancel(ctx):
    ful = require_row("order_fulfillments", ctx.p("fulfillment_id"))
    if ful.get("status") in ("RELEASED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL")
    if ful.get("status") != "READY_FOR_RELEASE":
        err("ERR_INVALID_STATE")
    ful["status"] = "CANCELLED"
    touch(ful)
    booking = get("bay_bookings", ful.get("booking_id"))
    if booking is not None and booking.get("status") in ("RESERVED", "CHECKED_IN"):
        booking["status"] = "CANCELLED"
        touch(booking)
    return ok(ful)