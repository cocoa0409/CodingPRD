"""Receipt endpoints: ring, edit, attach, reconcile, dispute, resolve, settle.

Validation order follows SCAFFOLD Table 4 literally.  The adjacencies the
scaffold calls out as load-bearing are honoured verbatim:
  * POST /receipts evaluates priority 8 (suspended gate) BEFORE priority 9
    (unknown item), so a ticket that both names an unknown item and lands on a
    suspended day reports ERR_STORE_DAY_GATE_SUSPENDED.
"""

from flask import Blueprint, request

import calculations as calc
import db
import middleware as mw
import response as resp
import serializers as ser
from errors import ApiError

bp = Blueprint("receipts", __name__)

RECEIPT_READ_ROLES = ["PlatformAdmin", "BoutiqueManager", "RetailLead", "RetailCashier", "Cashier"]
RECEIPT_WRITE_ROLES = ["RetailLead", "RetailCashier"]
TENDERS = {"CASH", "CARD", "GIFT_CARD", "SPLIT"}
LINE_KINDS = {"RETAIL", "SEASONAL_DECOR", "NOSTALGIA", "GIFT_CARD"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _resolve_day_and_location(data):
    location_id = mw.required(data, "location_id")
    location_rec = db.get_or_404(db.locations, location_id, "ERR_LOCATION_NOT_FOUND")
    store_day_id = mw.required(data, "store_day_id")
    day = db.get_or_404(db.store_days, store_day_id, "ERR_STORE_DAY_NOT_FOUND")
    return location_rec, day


def _gate_check(day):
    """Priority 8: a SUSPENDED gate refuses this write."""
    if day.get("conversion_gate") == "SUSPENDED":
        raise ApiError("ERR_STORE_DAY_GATE_SUSPENDED")


def _day_open_check(day):
    """Priority 7: a store-day-scoped write against a closed day is a state error.

    PRD 2.10: "once `day_status` has reached `CLOSED` the day is terminal ... and a
    store-day-scoped mutation against a closed day is rejected as an invalid state,
    reported with `ERR_STORE_DAY_CLOSED` (HTTP 409)".  The rule is the priority-7
    state row, so it is evaluated before the priority-8 gate and the priority-9
    item-existence row (PRD 2.12).
    """
    if day.get("day_status") != "OPEN":
        raise ApiError("ERR_STORE_DAY_CLOSED")


def _parse_lines(raw_lines):
    lines = []
    for index, raw in enumerate(raw_lines):
        if not isinstance(raw, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each receipt line must be an object.")
        item_id = raw.get("item_id")
        if not item_id:
            raise ApiError("ERR_INVALID_REQUEST", "Each receipt line requires an item_id.")
        quantity = raw.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            raise ApiError("ERR_INVALID_REQUEST", "Each receipt line requires a positive quantity.")
        unit_price = raw.get("unit_price_cents")
        if unit_price is None or not isinstance(unit_price, int) or isinstance(unit_price, bool) \
                or unit_price < 0:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Each receipt line requires a non-negative unit_price_cents.")
        discount = raw.get("discount_pct", 0)
        line_kind = raw.get("line_kind")
        if line_kind not in LINE_KINDS:
            raise ApiError("ERR_INVALID_REQUEST", "line_kind is not a declared line kind.")
        lines.append({
            "item_id": item_id,
            "quantity": quantity,
            "unit_price_cents": unit_price,
            "discount_pct": discount,
            "line_kind": line_kind,
        })
    return lines


def _check_lines(lines):
    """Priority 9: every item id referenced by the request must exist."""
    for line in lines:
        db.get_or_404(db.items, line["item_id"], "ERR_ITEM_NOT_FOUND")


def _check_gift_card(lines, payment_method):
    """Priority 11: at most one GIFT_CARD line, and only under GIFT_CARD tender."""
    gift_lines = [ln for ln in lines if ln.get("line_kind") == "GIFT_CARD"]
    if len(gift_lines) > 1:
        raise ApiError("ERR_GIFT_CARD_LINE_MISMATCH")
    if gift_lines and payment_method != "GIFT_CARD":
        raise ApiError("ERR_GIFT_CARD_LINE_MISMATCH")


def _receipt_number_conflict(location_id, day, receipt_number, exclude_id=None):
    """Priority 10: unique within (location_id, business_date)."""
    business_date = day.get("business_date")
    for rec in db.receipts.values():
        if exclude_id is not None and rec["id"] == exclude_id:
            continue
        if rec.get("location_id") != location_id or rec.get("receipt_number") != receipt_number:
            continue
        other_day = db.store_days.get(rec.get("store_day_id"))
        if other_day is not None and other_day.get("business_date") == business_date:
            raise ApiError("ERR_RECEIPT_DUPLICATE")


def _check_attachment(day, check):
    """Priority 12: the check must belong to the receipt's own store day."""
    if check is None:
        return
    if check.get("store_day_id") != day["id"]:
        raise ApiError("ERR_CHECK_STORE_DAY_MISMATCH")


def _max_check_ceiling(day, receipt_retail_cents, check):
    """Priority 16: the combined check total must stay under the brand ceiling."""
    if check is None:
        return
    brand_rec = calc.brand_of_store_day(day)
    if brand_rec is None:
        return
    other_receipts = [r.get("provisional_retail_cents", 0) or 0
                      for r in db.receipts.values()
                      if r.get("guest_check_id") == check["id"]
                      and r.get("status") in calc.RECEIPT_SALES_STATUSES]
    projected = (check.get("restaurant_subtotal_cents", 0)
                 + sum(other_receipts) + receipt_retail_cents
                 + (check.get("tip_cents", 0) or 0))
    fee = calc.compute_service_fee(projected - (check.get("tip_cents", 0) or 0))
    if projected + fee > brand_rec.get("max_check_total_cents", 50000):
        raise ApiError("ERR_CHECK_TOTAL_EXCEEDED")


def _refresh_allocated_share(rec):
    """Under ALLOCATED the restaurant share is derived inside the ticket.

    PRD 3.2: "the restaurant share is the check's total_cents multiplied by
    restaurant_subtotal_cents and divided by the sum of restaurant_subtotal_cents
    and retail_subtotal_cents, rounded half-up to a whole cent ... That derived
    restaurant figure is what a receipt carries in restaurant_share_cents".
    """
    if rec.get("restaurant_share_basis") != "ALLOCATED":
        return rec
    check = db.guest_checks.get(rec.get("guest_check_id")) if rec.get("guest_check_id") else None
    if check is None:
        return rec
    restaurant = check.get("restaurant_subtotal_cents", 0) or 0
    retail = check.get("retail_subtotal_cents", 0) or 0
    rec["restaurant_share_cents"] = calc.allocated_restaurant_share(
        check.get("total_cents", 0), restaurant, retail)
    return rec


def _refresh_day(day, touch=True):
    calc.recompute_store_day_retail_metrics(day)
    calc.recompute_conversion_index(day)
    if touch:
        db.touch(day)


# ---------------------------------------------------------------------------
# POST /receipts
# ---------------------------------------------------------------------------

@bp.post("/retail-ops/receipts")
def create_receipt():
    ctx = mw.context()
    mw.require_role(ctx, RECEIPT_WRITE_ROLES)
    data = mw.body()

    # Priority 3 — location and store day both resolve through the path.
    location_rec, day = _resolve_day_and_location(data)

    # Priority 7 — state.  Ringing is a store-day-scoped write, so a closed day is
    # refused here, ahead of the priority-8 gate and the priority-9 item row.
    _day_open_check(day)

    # Priority 8 — the suspended gate refuses this retail-side write.
    _gate_check(day)

    # Priority 9 — item references.
    lines = _parse_lines(mw.required(data, "lines", list))
    _check_lines(lines)

    # Priority 10 — receipt_number uniqueness.
    receipt_number = mw.required(data, "receipt_number")
    _receipt_number_conflict(location_rec["id"], day, receipt_number)

    payment_method = mw.required(data, "payment_method")
    if payment_method not in TENDERS:
        raise ApiError("ERR_INVALID_REQUEST", "payment_method is not a declared tender.")

    # Priority 11 — gift-card line rule.
    _check_gift_card(lines, payment_method)

    # Priority 12 — check/store-day agreement.
    check = None
    check_id = mw.optional(data, "guest_check_id", None)
    if check_id:
        check = db.get_or_404(db.guest_checks, check_id, "ERR_CHECK_NOT_FOUND")
        _check_attachment(day, check)

    # Priority 16 — the combined-check ceiling.
    provisional = calc.provisional_retail_revenue({"guest_check_id": check_id, "lines": lines})
    _max_check_ceiling(day, provisional, check)

    # OCC on the parent check (PRD 2.6) — the attach is version-pinned and the
    # expected version is non-optional whenever a check is named.
    if check is not None:
        expected = mw.optional(data, "expected_guest_check_version", None, int)
        if expected is None or expected != check.get("version"):
            raise ApiError("ERR_STALE_VERSION")
        if check.get("check_status") in {"FINALIZED", "VOIDED"}:
            raise ApiError("ERR_CHECK_ALREADY_FINALIZED")

    rec = db.new_record({
        "location_id": location_rec["id"],
        "store_day_id": day["id"],
        "guest_check_id": check_id,
        "receipt_number": receipt_number,
        "lines": lines,
        "restaurant_share_cents": mw.optional(data, "restaurant_share_cents", 0, int),
        "restaurant_share_basis": mw.optional(data, "restaurant_share_basis", "CHECK_TOTAL"),
        "payment_method": payment_method,
        "status": "DRAFT",
        "provisional_retail_cents": 0,
        "recognized_retail_cents": 0,
        "recognition_delta_cents": 0,
        "reconciliation_posted_at": None,
        "reversal_posted_at": None,
        "reconciled_at": None,
        "settled_at": None,
        "closed_at": None,
    })
    rec["provisional_retail_cents"] = calc.provisional_retail_revenue(rec)
    db.receipts[rec["id"]] = rec

    if check is not None:
        # The check's totals must be settled before an ALLOCATED share can be
        # derived from them.
        calc.recompute_check(check)
        _refresh_allocated_share(rec)
        calc.recompute_check_tip_fields(check)
        db.touch(check)

    calc.recompute_store_day_transaction_count(day)
    _refresh_day(day)
    db.touch(location_rec)
    return resp.ok(ser.receipt(rec), 201)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@bp.get("/retail-ops/receipts")
def list_receipts():
    ctx = mw.context()
    mw.require_role(ctx, RECEIPT_READ_ROLES)
    records = resp.order_records([r for r in db.receipts.values() if mw.matches(r, {
        "location_id": mw.query_str("location_id"),
        "store_day_id": mw.query_str("store_day_id"),
        "guest_check_id": mw.query_str("guest_check_id"),
        "status": mw.query_str("status"),
        "payment_method": mw.query_str("payment_method"),
    })])
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.receipt(r) for r in page], pagination=pagination)


@bp.get("/retail-ops/receipts/<receipt_id>")
def get_receipt(receipt_id):
    ctx = mw.context()
    mw.require_role(ctx, RECEIPT_READ_ROLES)
    rec = db.get_or_404(db.receipts, receipt_id, "ERR_RECEIPT_NOT_FOUND")
    return resp.ok(ser.receipt(rec))


# ---------------------------------------------------------------------------
# PUT /receipts/{id}
# ---------------------------------------------------------------------------

@bp.put("/retail-ops/receipts/<receipt_id>")
def edit_receipt(receipt_id):
    ctx = mw.context()
    mw.require_role(ctx, RECEIPT_WRITE_ROLES)
    rec = db.get_or_404(db.receipts, receipt_id, "ERR_RECEIPT_NOT_FOUND")
    data = mw.body()

    day = db.store_days.get(rec.get("store_day_id"))
    if rec.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    if day is not None:
        _gate_check(day)

    if "lines" in data and data["lines"] is not None:
        lines = _parse_lines(data["lines"])
        _check_lines(lines)
        rec["lines"] = lines
    if "restaurant_share_cents" in data and data["restaurant_share_cents"] is not None:
        rec["restaurant_share_cents"] = mw.coerce(
            data["restaurant_share_cents"], "restaurant_share_cents", int)
    if "restaurant_share_basis" in data and data["restaurant_share_basis"] is not None:
        basis = data["restaurant_share_basis"]
        if basis not in {"CHECK_TOTAL", "ALLOCATED"}:
            raise ApiError("ERR_INVALID_REQUEST", "restaurant_share_basis is not a declared basis.")
        rec["restaurant_share_basis"] = basis
    if "payment_method" in data and data["payment_method"] is not None:
        tender = data["payment_method"]
        if tender not in TENDERS:
            raise ApiError("ERR_INVALID_REQUEST", "payment_method is not a declared tender.")
        rec["payment_method"] = tender

    _check_gift_card(rec.get("lines") or [], rec.get("payment_method"))

    check = db.guest_checks.get(rec.get("guest_check_id")) if rec.get("guest_check_id") else None
    if check is not None and day is not None:
        _check_attachment(day, check)

    rec["provisional_retail_cents"] = calc.provisional_retail_revenue(rec)

    # Priority 16 also guards editing an existing ticket against a check.
    if check is not None and day is not None:
        _max_check_ceiling(day, rec["provisional_retail_cents"], check)

    db.touch(rec)

    if check is not None:
        calc.recompute_check(check)
        calc.recompute_check_tip_fields(check)
        _refresh_allocated_share(rec)
        db.touch(check)

    if day is not None:
        _refresh_day(day)
    return resp.ok(ser.receipt(rec))


# ---------------------------------------------------------------------------
# POST /receipts/{id}/attach-check
# ---------------------------------------------------------------------------

@bp.post("/retail-ops/receipts/<receipt_id>/attach-check")
def attach_check(receipt_id):
    ctx = mw.context()
    mw.require_role(ctx, ["RetailLead", "Cashier"])
    rec = db.get_or_404(db.receipts, receipt_id, "ERR_RECEIPT_NOT_FOUND")
    data = mw.body()

    check_id = mw.required(data, "guest_check_id")
    check = db.get_or_404(db.guest_checks, check_id, "ERR_CHECK_NOT_FOUND")

    day = db.store_days.get(check.get("store_day_id"))
    if day is not None:
        _gate_check(day)

    expected = mw.required(data, "expected_guest_check_version", int)
    if expected != check.get("version"):
        raise ApiError("ERR_STALE_VERSION")

    if check.get("check_status") in {"FINALIZED", "VOIDED"}:
        raise ApiError("ERR_CHECK_ALREADY_FINALIZED")
    if rec.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    rec["guest_check_id"] = check["id"]
    rec["store_day_id"] = check.get("store_day_id")
    rec["provisional_retail_cents"] = calc.provisional_retail_revenue(rec)
    db.touch(rec)

    calc.recompute_check(check)
    _refresh_allocated_share(rec)
    calc.recompute_check_tip_fields(check)
    db.touch(check)

    if day is not None:
        _refresh_day(day)
    return resp.ok(ser.receipt(rec))


# ---------------------------------------------------------------------------
# lifecycle actions
# ---------------------------------------------------------------------------

@bp.post("/retail-ops/receipts/<receipt_id>/reconcile")
def reconcile_receipt(receipt_id):
    ctx = mw.context()
    mw.require_role(ctx, ["RetailLead"])
    rec = db.get_or_404(db.receipts, receipt_id, "ERR_RECEIPT_NOT_FOUND")

    day = db.store_days.get(rec.get("store_day_id"))
    brand_rec = calc.brand_of_store_day(day) if day is not None else None

    # Priority 5 — the fiscal period must still be open.
    if brand_rec is not None and brand_rec.get("fiscal_period_status") != "OPEN":
        raise ApiError("ERR_FISCAL_PERIOD_CLOSED")

    # Priority 7 — state-machine membership.
    if rec.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    check = db.guest_checks.get(rec.get("guest_check_id")) if rec.get("guest_check_id") else None
    if check is not None and check.get("check_status") == "VOIDED":
        raise ApiError("ERR_INVALID_STATE")

    if day is not None:
        _gate_check(day)

    calc.post_recognition(rec, brand_rec)
    rec["reconciliation_posted_at"] = db.fmt_ts(db.now())
    rec["reconciled_at"] = db.fmt_ts(db.now())
    rec["status"] = "RECONCILED"
    db.touch(rec)

    if brand_rec is not None:
        calc.recompute_brand_revenue(brand_rec)
        db.touch(brand_rec)

    if day is not None:
        _refresh_day(day)
    return resp.ok(ser.receipt(rec))


@bp.post("/retail-ops/receipts/<receipt_id>/dispute")
def dispute_receipt(receipt_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.receipts, receipt_id, "ERR_RECEIPT_NOT_FOUND")

    day = db.store_days.get(rec.get("store_day_id"))
    brand_rec = calc.brand_of_store_day(day) if day is not None else None
    grace = brand_rec.get("open_receipt_grace_hours", 24) if brand_rec else 24

    status = rec.get("status")
    if status not in {"RECONCILED", "SETTLED"}:
        raise ApiError("ERR_INVALID_STATE")

    if status == "RECONCILED":
        # PRD 3.4: within the brand's grace window, measured from reconciled_at.
        if rec.get("reconciled_at") is None:
            raise ApiError("ERR_INVALID_STATE")
        deadline = db.plus_hours(db.parse_ts(rec["reconciled_at"], "reconciled_at"), grace)
        if db.now() > deadline:
            raise ApiError("ERR_STORE_DAY_CLOSED" if day and day.get("day_status") == "CLOSED"
                           else "ERR_INVALID_STATE")
    else:
        # PRD 3.4: a settled ticket's day must still be OPEN.
        if day is None or day.get("day_status") != "OPEN":
            raise ApiError("ERR_STORE_DAY_CLOSED" if day and day.get("day_status") == "CLOSED"
                           else "ERR_INVALID_STATE")

    if day is not None:
        _gate_check(day)

    rec["status"] = "DISPUTED"
    rec["reversal_posted_at"] = db.fmt_ts(db.now())
    db.touch(rec)

    if brand_rec is not None:
        calc.recompute_brand_revenue(brand_rec)
        db.touch(brand_rec)

    if day is not None:
        calc.recompute_store_day_transaction_count(day)
        _refresh_day(day)
    return resp.ok(ser.receipt(rec))


@bp.post("/retail-ops/receipts/<receipt_id>/resolve")
def resolve_receipt(receipt_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.receipts, receipt_id, "ERR_RECEIPT_NOT_FOUND")

    if rec.get("status") != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE")

    day = db.store_days.get(rec.get("store_day_id"))
    brand_rec = calc.brand_of_store_day(day) if day is not None else None
    grace = brand_rec.get("open_receipt_grace_hours", 24) if brand_rec else 24

    # PRD 3.4: the clock is re-checked at resolution time, not merely at dispute.
    if rec.get("reconciled_at") is None:
        raise ApiError("ERR_INVALID_STATE")
    deadline = db.plus_hours(db.parse_ts(rec["reconciled_at"], "reconciled_at"), grace)
    if db.now() > deadline:
        raise ApiError("ERR_INVALID_STATE")

    if day is not None:
        _gate_check(day)

    rec["status"] = "RECONCILED"
    rec["reversal_posted_at"] = None
    calc.post_recognition(rec, brand_rec)
    db.touch(rec)

    if brand_rec is not None:
        calc.recompute_brand_revenue(brand_rec)
        db.touch(brand_rec)

    if day is not None:
        calc.recompute_store_day_transaction_count(day)
        _refresh_day(day)
    return resp.ok(ser.receipt(rec))


@bp.post("/retail-ops/receipts/<receipt_id>/settle")
def settle_receipt(receipt_id):
    ctx = mw.context()
    mw.require_role(ctx, ["RetailLead"])
    rec = db.get_or_404(db.receipts, receipt_id, "ERR_RECEIPT_NOT_FOUND")
    data = mw.body()

    if rec.get("status") != "RECONCILED":
        raise ApiError("ERR_INVALID_STATE")

    if rec.get("reconciled_at") is None or db.now() < db.parse_ts(rec["reconciled_at"], "reconciled_at"):
        raise ApiError("ERR_INVALID_STATE")

    day = db.store_days.get(rec.get("store_day_id"))
    if day is not None:
        _gate_check(day)

    tender = mw.optional(data, "payment_method", None)
    if tender is not None:
        if tender not in TENDERS:
            raise ApiError("ERR_INVALID_REQUEST", "payment_method is not a declared tender.")
        rec["payment_method"] = tender

    rec["status"] = "SETTLED"
    rec["settled_at"] = db.fmt_ts(db.now())
    db.touch(rec)

    if day is not None:
        _refresh_day(day)
    return resp.ok(ser.receipt(rec))