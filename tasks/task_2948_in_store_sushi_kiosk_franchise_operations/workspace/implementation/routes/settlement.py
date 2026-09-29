"""Register feeds, reconciliation and the revenue-share settlement -- PRD 3.8."""

from flask import Blueprint

import db
from core import LOCK, iso_instant
from errors import ApiError
from middleware import (ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER, authorize,
                        bad, body, current_user_id, req_date, req_instant,
                        req_int, req_str, strictly_ordered)
from response import created, ok
from routes.base import (agreement_or_404, feed_or_404, fk_lookup, filters,
                         paginate, statement_or_404, store_or_404)
from services import calc, domain

bp = Blueprint("settlement", __name__)

LIVE_FEED_STATES = ("SUBMITTED", "RECONCILED")


def _parse_lines(payload):
    """Register lines: [{pack_lot_id, units_sold, was_markdown}]. May be empty."""
    raw = payload.get("lines")
    if raw is None:
        bad("lines", "is required.")
    if not isinstance(raw, list):
        bad("lines", "must be an array.")
    out = []
    for index, item in enumerate(raw):
        label = "lines[%d]" % index
        if not isinstance(item, dict):
            bad(label, "must be an object.")
        pack_lot_id = item.get("pack_lot_id")
        if not isinstance(pack_lot_id, str) or not pack_lot_id.strip():
            bad(label + ".pack_lot_id", "must be a non-empty string.")
        units_sold = item.get("units_sold")
        if isinstance(units_sold, bool) or not isinstance(units_sold, int):
            bad(label + ".units_sold", "must be an integer.")
        if units_sold < 0:
            bad(label + ".units_sold", "must be greater than or equal to 0.")
        was_markdown = item.get("was_markdown")
        if not isinstance(was_markdown, bool):
            bad(label + ".was_markdown", "must be a boolean.")
        out.append({
            "pack_lot_id": pack_lot_id,
            "units_sold": units_sold,
            "was_markdown": was_markdown,
        })
    return out


# ==========================================================================
# POS sales feeds
# ==========================================================================


@bp.post("/pos-sales-feeds")
def submit_feed():
    actor = authorize(ROLE_HOST_STORE_MANAGER)
    payload = body()
    if payload.get("host_store_id") != actor.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    store = fk_lookup(payload, "host_store_id", store_or_404)
    req_str(payload, "host_store_id")
    business_date = req_date(payload, "business_date")
    gross = req_int(payload, "gross_sales_cents", minimum=0)
    markdown = req_int(payload, "markdown_sales_cents", minimum=0)
    full_price_units = req_int(payload, "full_price_units", minimum=0)
    markdown_units = req_int(payload, "markdown_units", minimum=0)
    lines = _parse_lines(payload)
    if markdown > gross:
        bad("markdown_sales_cents", "must not exceed gross_sales_cents.")

    with LOCK:
        # PRD 2.2: "A store whose integration is anything other than `CONNECTED`
        # cannot have a sales feed accepted -- the attempt is refused with
        # `ERR_POS_NOT_CONNECTED`".
        if store["pos_integration_status"] != "CONNECTED":
            raise ApiError("ERR_POS_NOT_CONNECTED")
        for feed in db.pos_sales_feeds.values():
            if (feed["host_store_id"] == store["id"]
                    and feed["business_date"] == business_date
                    and feed["status"] in LIVE_FEED_STATES):
                raise ApiError("ERR_DUPLICATE_FEED_FOR_DATE")
        row = db.new_row(db.pos_sales_feeds, {
            "host_store_id": store["id"],
            "business_date": business_date,
            "gross_sales_cents": gross,
            "markdown_sales_cents": markdown,
            "full_price_units": full_price_units,
            "markdown_units": markdown_units,
            "lines": lines,
            "status": "SUBMITTED",
            "reconciled_unit_total": 0,
            "rejection_reason": None,
        })
    return created(db.public(row))


@bp.get("/pos-sales-feeds/<feed_id>")
def get_feed(feed_id):
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER)
    feed = feed_or_404(feed_id)
    if actor.is_manager and feed["host_store_id"] != actor.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    return ok(db.public(feed))


@bp.get("/pos-sales-feeds")
def list_feeds():
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER)
    rows = list(db.pos_sales_feeds.values())
    if actor.is_manager:
        rows = [f for f in rows if f["host_store_id"] == actor.user_id]
    rows = filters(rows, {
        "host_store_id": "host_store_id",
        "business_date": "business_date",
        "status": "status",
    })
    return paginate(rows)


@bp.post("/pos-sales-feeds/<feed_id>/reconcile")
def reconcile_feed(feed_id):
    authorize(ROLE_FRANCHISOR_OPS)
    feed = feed_or_404(feed_id)
    with LOCK:
        if feed["status"] != "SUBMITTED":
            raise ApiError("ERR_POS_FEED_INVALID_STATE")
        store = db.host_stores.get(feed["host_store_id"])
        if store is None or store["pos_integration_status"] != "CONNECTED":
            raise ApiError("ERR_POS_NOT_CONNECTED")

        # Referential coherence (rung 10) for every line before any cardinality
        # check (rung 11), and no mutation until both passes are clean.
        resolved = []
        for line in feed["lines"]:
            lot = db.pack_lots.get(line["pack_lot_id"])
            if lot is None:
                raise ApiError("ERR_PRODUCTION_RECORD_NOT_FOUND")
            kiosk = domain.kiosk_of_pack_lot(lot)
            lot_store = domain.store_of_kiosk(kiosk) if kiosk is not None else None
            if lot_store is None or lot_store["id"] != store["id"]:
                raise ApiError("ERR_CROSS_KIOSK_REFERENCE")
            resolved.append((line, lot))

        wanted = {}
        for line, lot in resolved:
            wanted[lot["id"]] = wanted.get(lot["id"], 0) + line["units_sold"]
        for lot_id, units in wanted.items():
            if units > db.pack_lots[lot_id]["unsold_count"]:
                raise ApiError("ERR_PACK_CAP_EXCEEDED")

        total = 0
        for line, lot in resolved:
            units = line["units_sold"]
            total += units
            if units == 0:
                continue
            lot["sold_count"] += units
            lot["unsold_count"] -= units
            if lot["unsold_count"] == 0:
                lot["status"] = "SOLD_OUT"
            db.touch(lot)
        feed["status"] = "RECONCILED"
        feed["reconciled_unit_total"] = total
        db.touch(feed)
    return ok(db.public(feed))


@bp.post("/pos-sales-feeds/<feed_id>/reject")
def reject_feed(feed_id):
    authorize(ROLE_FRANCHISOR_OPS)
    feed = feed_or_404(feed_id)
    payload = body()
    reason = req_str(payload, "rejection_reason")
    with LOCK:
        if feed["status"] != "SUBMITTED":
            raise ApiError("ERR_POS_FEED_INVALID_STATE")
        feed["status"] = "REJECTED"
        feed["rejection_reason"] = reason
        db.touch(feed)
    return ok(db.public(feed))


# ==========================================================================
# Settlement statements
# ==========================================================================


OPEN_STATEMENT_STATES = ("DRAFT", "ISSUED", "ACKNOWLEDGED", "DISPUTED")


def _statement_agreement(statement):
    return db.license_agreements.get(statement["license_agreement_id"])


def _scope_statement(actor, statement):
    if not actor.is_manager:
        return
    agreement = _statement_agreement(statement)
    if agreement is None or agreement["host_store_id"] != actor.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")


def _periods_overlap(start_a, end_a, start_b, end_b):
    """Closed intervals: a shared endpoint date is an overlap."""
    return start_a <= end_b and start_b <= end_a


@bp.post("/settlement-statements")
def draft_statement():
    authorize(ROLE_FRANCHISOR_OPS)
    payload = body()
    agreement = fk_lookup(payload, "license_agreement_id", agreement_or_404)
    req_str(payload, "license_agreement_id")
    period_start = req_date(payload, "period_start")
    period_end = req_date(payload, "period_end")
    expected_version = req_int(payload, "expected_license_agreement_version")
    strictly_ordered("period_start", period_start, "period_end", period_end)

    with LOCK:
        if expected_version != agreement["version"]:
            raise ApiError("ERR_STALE_LICENSE_VERSION")

        superseded_id = None
        siblings = db.ordered([s for s in db.settlement_statements.values()
                               if s["license_agreement_id"] == agreement["id"]])
        for prior in siblings:
            if prior["status"] == "VOID":
                continue
            same_period = (prior["period_start"] == period_start
                           and prior["period_end"] == period_end)
            if prior["status"] == "DRAFT" and same_period:
                continue
            if _periods_overlap(period_start, period_end,
                                prior["period_start"], prior["period_end"]):
                raise ApiError("ERR_SETTLEMENT_PERIOD_OVERLAP")
        for prior in siblings:
            if (prior["status"] == "DRAFT"
                    and prior["period_start"] == period_start
                    and prior["period_end"] == period_end):
                prior["status"] = "VOID"
                prior["void_reason"] = "SUPERSEDED"
                db.touch(prior)
                superseded_id = prior["id"]

        row = db.new_row(db.settlement_statements, {
            "license_agreement_id": agreement["id"],
            "period_start": period_start,
            "period_end": period_end,
            "status": "DRAFT",
            "gross_sales_cents": 0,
            "markdown_sales_cents": 0,
            "settlement_base_cents": 0,
            "binding_share_cents": 0,
            "advisory_share_cents": 0,
            "variance_cents": 0,
            "space_shortfall_credit_cents": 0,
            "period_discard_value_cents": 0,
            "discard_credit_cents": 0,
            "net_due_cents": 0,
            "binding_variant": agreement["revenue_share_model"],
            "revision_round": 1,
            "created_by_user_id": current_user_id(),
            "issued_by_user_id": None,
            "superseded_statement_id": superseded_id,
            "dispute_reason": None,
            "revision_note": None,
            "void_reason": None,
            "paid_amount_cents": None,
            "paid_at": None,
        })
        row.update(domain.compute_statement_money(row, agreement))
        db.touch(agreement)
        domain.refresh_lifetime_accrual(agreement)
    return created(db.public(row))


@bp.get("/settlement-statements/<statement_id>")
def get_statement(statement_id):
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER)
    statement = statement_or_404(statement_id)
    _scope_statement(actor, statement)
    return ok(db.public(statement))


@bp.get("/settlement-statements")
def list_statements():
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER)
    rows = list(db.settlement_statements.values())
    if actor.is_manager:
        rows = [s for s in rows
                if (_statement_agreement(s) or {}).get("host_store_id")
                == actor.user_id]
    rows = filters(rows, {
        "license_agreement_id": "license_agreement_id",
        "status": "status",
        "superseded_statement_id": "superseded_statement_id",
    })
    return paginate(rows)


@bp.post("/settlement-statements/<statement_id>/issue")
def issue_statement(statement_id):
    authorize(ROLE_FRANCHISOR_OPS)
    statement = statement_or_404(statement_id)
    with LOCK:
        # State beats fiscal (PRD 2.6).
        if statement["status"] != "DRAFT":
            raise ApiError("ERR_SETTLEMENT_INVALID_STATE")
        agreement = _statement_agreement(statement)
        feeds = domain.reconciled_feeds(agreement["host_store_id"],
                                        statement["period_start"],
                                        statement["period_end"])
        if not feeds:
            raise ApiError("ERR_NO_SETTLEABLE_SALES")
        if current_user_id() == statement["created_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        statement["status"] = "ISSUED"
        statement["issued_by_user_id"] = current_user_id()
        db.touch(statement)
        domain.refresh_lifetime_accrual(agreement)
    return ok(db.public(statement))


@bp.post("/settlement-statements/<statement_id>/acknowledge")
def acknowledge_statement(statement_id):
    actor = authorize(ROLE_HOST_STORE_MANAGER)
    statement = statement_or_404(statement_id)
    _scope_statement(actor, statement)
    with LOCK:
        if statement["status"] != "ISSUED":
            raise ApiError("ERR_SETTLEMENT_INVALID_STATE")
        statement["status"] = "ACKNOWLEDGED"
        db.touch(statement)
        domain.refresh_lifetime_accrual(_statement_agreement(statement))
    return ok(db.public(statement))


@bp.post("/settlement-statements/<statement_id>/dispute")
def dispute_statement(statement_id):
    actor = authorize(ROLE_HOST_STORE_MANAGER)
    statement = statement_or_404(statement_id)
    _scope_statement(actor, statement)
    payload = body()
    reason = req_str(payload, "dispute_reason")
    with LOCK:
        if statement["status"] != "ISSUED":
            raise ApiError("ERR_SETTLEMENT_INVALID_STATE")
        statement["status"] = "DISPUTED"
        statement["dispute_reason"] = reason
        db.touch(statement)
        domain.refresh_lifetime_accrual(_statement_agreement(statement))
    return ok(db.public(statement))


@bp.post("/settlement-statements/<statement_id>/revise")
def revise_statement(statement_id):
    authorize(ROLE_FRANCHISOR_OPS)
    statement = statement_or_404(statement_id)
    payload = body()
    note = req_str(payload, "revision_note")
    with LOCK:
        if statement["status"] != "DISPUTED":
            raise ApiError("ERR_SETTLEMENT_INVALID_STATE")
        if statement["revision_round"] >= calc.MAX_REVISION_ROUND:
            raise ApiError("ERR_CORRECTIVE_ROUNDS_EXHAUSTED")
        agreement = _statement_agreement(statement)
        changes = {
            "status": "DRAFT",
            "revision_round": statement["revision_round"] + 1,
            "revision_note": note,
            "issued_by_user_id": None,
        }
        changes.update(domain.compute_statement_money(statement, agreement))
        db.apply_changes(statement, changes)
        domain.refresh_lifetime_accrual(agreement)
    return ok(db.public(statement))


@bp.post("/settlement-statements/<statement_id>/pay")
def pay_statement(statement_id):
    actor = authorize(ROLE_HOST_STORE_MANAGER)
    statement = statement_or_404(statement_id)
    _scope_statement(actor, statement)
    payload = body()
    amount = req_int(payload, "paid_amount_cents", minimum=0)
    paid_at = req_instant(payload, "paid_at")
    with LOCK:
        if statement["status"] != "ACKNOWLEDGED":
            raise ApiError("ERR_SETTLEMENT_INVALID_STATE")
        if amount != statement["net_due_cents"]:
            raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")
        statement["status"] = "PAID"
        statement["paid_amount_cents"] = amount
        statement["paid_at"] = iso_instant(paid_at)
        db.touch(statement)
        domain.refresh_lifetime_accrual(_statement_agreement(statement))
    return ok(db.public(statement))


@bp.post("/settlement-statements/<statement_id>/void")
def void_statement(statement_id):
    authorize(ROLE_FRANCHISOR_OPS)
    statement = statement_or_404(statement_id)
    payload = body()
    reason = req_str(payload, "void_reason")
    with LOCK:
        if statement["status"] not in OPEN_STATEMENT_STATES:
            raise ApiError("ERR_SETTLEMENT_INVALID_STATE")
        statement["status"] = "VOID"
        statement["void_reason"] = reason
        db.touch(statement)
        domain.refresh_lifetime_accrual(_statement_agreement(statement))
    return ok(db.public(statement))
