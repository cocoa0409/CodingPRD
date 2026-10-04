"""Core returns, the deposit waterfall and warranty registrations
(PRD 3.7)."""

from datetime import timedelta

import db
from errors import ApiError, bad_request
from middleware import require_fields, string_field
from services import calc, common, ledger


def _int(body, field, required=False, default=None):
    if not isinstance(body, dict) or field not in body or body.get(field) is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
        return default
    try:
        return int(body[field])
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % field)


def _lines(body):
    if not isinstance(body, dict) or body.get("line_items") is None:
        raise ApiError("ERR_INVALID_REQUEST", "line_items is required.")
    raw = body["line_items"]
    if not isinstance(raw, list):
        raise ApiError("ERR_INVALID_REQUEST", "line_items must be an array.")
    out = []
    for entry in raw:
        if not isinstance(entry, dict) or entry.get("part_id") is None:
            raise ApiError("ERR_INVALID_REQUEST", "Each core line needs a part_id.")
        out.append({
            "part_id": str(entry["part_id"]),
            "quantity": _int(entry, "quantity", required=True),
        })
    return out


# ---------------------------------------------------------------------------
# opening a core return
# ---------------------------------------------------------------------------

def open_core_return(order, account, auto=False, lines=None):
    """A CoreReturn is created in INITIATED against the order and the account,
    with core_subtotal_cents computed from the core lines."""
    if lines is None:
        lines = [{"part_id": line.get("part_id"), "quantity": line.get("quantity") or 0}
                 for line in order.get("line_items") or []]
    core = common.new_resource({
        "order_id": order["id"],
        "account_id": account["id"],
        "line_items": lines,
        "core_subtotal_cents": calc.core_subtotal_of(lines),
        "restocking_fee_cents": 0,
        "warranty_covered": False,
        "credit_amount_cents": 0,
        "status": "INITIATED",
    })
    db.core_returns[core["id"]] = core
    common.remember("core_returns", core["id"])
    return core


def create_core_return(body):
    require_fields(body, ["order_id", "line_items"])
    order = db.part_orders.get(str(body["order_id"]))
    if order is None:
        raise ApiError("ERR_PART_ORDER_NOT_FOUND")
    account = db.accounts.get(order.get("account_id"))
    if account is None:
        raise ApiError("ERR_COMMERCIAL_ACCOUNT_NOT_FOUND")
    lines = _lines(body)
    _check_return_window(order, account)
    _check_lines_exist(lines)
    return open_core_return(order, account, lines=lines)


def _check_lines_exist(lines):
    for line in lines:
        if calc.resolved_line_part(line) is None:
            raise ApiError("ERR_PART_NOT_FOUND")


def _check_return_window(order, account):
    delivered = calc._parse(order.get("delivered_at"))
    if delivered is None:
        return
    terms = account.get("credit_terms_days") or 0
    window_end = delivered + timedelta(days=terms + 30)
    if db.clock() > window_end:
        raise ApiError("ERR_RETURN_WINDOW_CLOSED")


# ---------------------------------------------------------------------------
# transitions
# ---------------------------------------------------------------------------

def transit_core(core, body=None):
    if core.get("status") != "INITIATED":
        raise ApiError("ERR_CORE_RETURN_NOT_INITIATED")
    core["status"] = "IN_TRANSIT"
    common.record_audit(core)
    return core


def inspect_core(core, body=None):
    order = db.part_orders.get(core.get("order_id"))
    if core.get("status") != "IN_TRANSIT":
        raise ApiError("ERR_CORE_RETURN_NOT_IN_TRANSIT")
    if order is None:
        raise ApiError("ERR_PART_ORDER_NOT_FOUND")

    # priority 14 -- a core line may not exceed the quantity on the order
    _check_line_quantities(core, order)
    # priority 21 -- a credit claimed as warranty-covered must rest on a live
    # registration; an expired warranty removes the fee waiver rather than
    # blocking the credit, so this only fires on an explicit claim
    _check_warranty_claim(core, body)

    core["core_subtotal_cents"] = calc.core_subtotal_of(core.get("line_items") or [])
    covered = calc.warranty_covered_for(core, db.clock())
    core["warranty_covered"] = covered
    readings = calc.core_credit(core, order, db.clock())
    core["restocking_fee_cents"] = readings["restocking_fee_cents"]
    core["credit_amount_cents"] = readings["credit_amount_cents"]

    # priority 27, deliberately last among the core-return rules
    if core.get("warranty_covered") and (core.get("restocking_fee_cents") or 0) != 0:
        raise ApiError("ERR_RESTOCKING_FEE_MISAPPLIED")

    core["status"] = "INSPECTED"
    common.record_audit(core)
    account = db.accounts.get(core["account_id"])
    if account is not None:
        ledger.recompute_account(account)
    return core


def _check_line_quantities(core, order):
    purchased = {}
    for line in order.get("line_items") or []:
        part = calc.resolved_line_part(line)
        if part is None:
            continue
        key = part["id"]
        purchased[key] = purchased.get(key, 0) + (line.get("quantity") or 0)
        for chain_id in common.chain_parts(part["id"]):
            purchased.setdefault(chain_id, 0)
            purchased[chain_id] += line.get("quantity") or 0
    for line in core.get("line_items") or []:
        part = common.resolve_current(line.get("part_id"))
        if part is None:
            raise ApiError("ERR_PART_NOT_FOUND")
        if (line.get("quantity") or 0) > purchased.get(part["id"], 0):
            raise ApiError("ERR_CORE_QUANTITY_EXCEEDS_PURCHASE")


def _check_warranty_claim(core, body):
    if not isinstance(body, dict):
        return
    claimed = body.get("warranty_covered")
    if claimed is None:
        return
    flag = claimed if isinstance(claimed, bool) else str(claimed).lower() in ("true", "1", "yes")
    if not flag:
        return
    if not calc.warranty_covered_for(core, db.clock()):
        raise ApiError("ERR_WARRANTY_EXPIRED")


def credit_core(core, body=None):
    if core.get("status") != "INSPECTED":
        raise ApiError("ERR_CORE_RETURN_NOT_INSPECTED")
    account = db.accounts.get(core.get("account_id"))
    if account is not None and account.get("account_posture") == "CLOSED":
        raise ApiError("ERR_ACCOUNT_CLOSED")
    if account is not None:
        account["petty_cash_cents"] = (account.get("petty_cash_cents") or 0) + \
            (core.get("credit_amount_cents") or 0)
        order = db.part_orders.get(core.get("order_id"))
        if order is not None:
            order["refundable_deposit_consumed_cents"] = \
                (order.get("refundable_deposit_consumed_cents") or 0) + \
                _refundable_portion(core, order)
            common.record_audit(order)
    core["status"] = "CREDITED"
    common.record_audit(core)
    if account is not None:
        ledger.recompute_account(account)
    return core


def _refundable_portion(core, order):
    """The payout drawn against the order's waterfall headroom, in ascending
    core-line index order (PRD 3.7)."""
    headroom = (order.get("refundable_deposit_cents") or 0) - \
        (order.get("refundable_deposit_consumed_cents") or 0)
    core_subtotal = core.get("core_subtotal_cents") or 0
    from money import round_half_up, to_decimal
    requested = round_half_up(to_decimal(core_subtotal) * to_decimal(calc.REFUNDABLE_RATE))
    return max(0, min(requested, headroom))


def reject_core(core, body=None):
    if core.get("status") not in ("INITIATED", "IN_TRANSIT"):
        raise ApiError("ERR_CORE_RETURN_NOT_REJECTABLE")
    core["status"] = "REJECTED"
    common.record_audit(core)
    return core


# ---------------------------------------------------------------------------
# warranty registrations
# ---------------------------------------------------------------------------

def create_warranty(body):
    require_fields(body, ["account_id", "part_id", "purchased_at", "warranty_expires_at"])
    account = db.accounts.get(str(body["account_id"]))
    if account is None:
        raise ApiError("ERR_COMMERCIAL_ACCOUNT_NOT_FOUND")
    part = db.parts.get(str(body["part_id"]))
    if part is None:
        raise ApiError("ERR_PART_NOT_FOUND")
    purchase_order_id = body.get("purchase_order_id")
    if purchase_order_id is not None:
        if db.part_orders.get(str(purchase_order_id)) is None:
            raise ApiError("ERR_PART_ORDER_NOT_FOUND")
        purchase_order_id = str(purchase_order_id)
    purchased_at = calc._parse(body.get("purchased_at"))
    expires_at = calc._parse(body.get("warranty_expires_at"))
    if purchased_at is None or expires_at is None:
        bad_request("purchased_at and warranty_expires_at must be ISO 8601 instants.")
    if expires_at <= purchased_at:
        bad_request("warranty_expires_at must be strictly after purchased_at.")

    claim_reference = body.get("claim_reference")
    record = common.slim_resource({
        "account_id": account["id"],
        "part_id": part["id"],
        "purchase_order_id": purchase_order_id,
        "purchased_at": calc._fmt(purchased_at),
        "warranty_expires_at": calc._fmt(expires_at),
        "claim_reference": claim_reference,
    })
    db.warranty_registrations[record["id"]] = record
    common.remember("warranty_registrations", record["id"])
    return record