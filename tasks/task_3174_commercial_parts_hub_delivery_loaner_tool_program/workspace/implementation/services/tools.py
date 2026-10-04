"""The tool crib: the ToolCatalog band machine and the ToolLoan lifecycle
(PRD 3.6 and SCAFFOLD 1.2 ToolCatalog / ToolLoan)."""

from datetime import timedelta

import db
from errors import ApiError, bad_request
from middleware import iso_field, optional, require_fields, string_field
from money import round_half_up, to_decimal
from services import calc, common, ledger

CONDITIONS = ("GOOD", "WORN", "BROKEN", "LOST")
OUT_STATES = ("IN_USE", "DUE", "OVERDUE")
OPEN_LOAN_STATES = ("CHECKED_OUT", "IN_USE", "DUE", "OVERDUE")
TOOL_ON_LOAN_STATES = ("CHECKED_OUT", "IN_USE", "DUE", "OVERDUE")


# ---------------------------------------------------------------------------
# ToolCatalog
# ---------------------------------------------------------------------------

def create_tool(body):
    # PRD 3.6 states the replacement part explicitly: "If every candidate set at
    # every level is empty, the loan's replacement_part_id stays null, no
    # replacement is offered" -- so a catalogue entry may open with no
    # replacement part, seeded from nothing until a wear-band advance or a worn
    # return selects one.
    require_fields(body, ["tool_sku", "tool_name", "deposit_amount_cents",
                          "replacement_unit_cost_cents"])
    replacement_part_id = body.get("replacement_part_id")
    if replacement_part_id is not None:
        replacement_part_id = str(replacement_part_id)
        if db.parts.get(replacement_part_id) is None:
            raise ApiError("ERR_PART_NOT_FOUND")
    tool = common.new_resource({
        "tool_sku": string_field(body, "tool_sku", required=True),
        "tool_name": string_field(body, "tool_name", required=True),
        "deposit_amount_cents": _int(body, "deposit_amount_cents"),
        "replacement_part_id": replacement_part_id,
        "replacement_unit_cost_cents": _int(body, "replacement_unit_cost_cents"),
        "wear_accumulated": 0,
        "wear_band": "LEVEL_1",
        "wear_multiplier_rate": 1.00,
        "wear_forfeiture_rate": 0.00,
        "wear_grace_period_hours": 48,
    })
    db.tool_catalog[tool["id"]] = tool
    calc.pin_wear_band(tool)
    common.remember("tool_catalog", tool["id"])
    return tool


def _int(body, field, default=None):
    if field not in body or body.get(field) is None:
        if default is None:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
        return default
    try:
        return int(body[field])
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % field)


def _number(body, field, default=None):
    if field not in body or body.get(field) is None:
        if default is None:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
        return default
    try:
        return float(body[field])
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a number." % field)


def account_home_store_for_tool(tool):
    """The store used by the selector's stock condition.  A catalogue-level
    re-selection has no single owning account, so a loan on the tool supplies
    the store when one is open."""
    for loan in db.tool_loans.values():
        if loan.get("tool_catalog_id") != tool["id"]:
            continue
        if loan.get("status") in ("CLOSED", "FORFEITED"):
            continue
        account = db.accounts.get(loan.get("account_id"))
        if account is not None:
            return account.get("home_store_id")
    for loan in db.tool_loans.values():
        if loan.get("tool_catalog_id") != tool["id"]:
            continue
        account = db.accounts.get(loan.get("account_id"))
        if account is not None:
            return account.get("home_store_id")
    return None


def advance_wear_band(tool):
    """Raise the band only when a threshold has actually been crossed, then run
    the advance's side effects (PRD 3.6)."""
    advanced = calc.pin_wear_band(tool)
    if not advanced:
        common.record_audit(tool)
        return False
    calc.apply_wear_band_side_effects(tool, account_home_store_for_tool(tool))
    common.record_audit(tool)
    return True


def adjust_wear(tool, body):
    delta = _number(body, "wear_delta_units")
    current = float(tool.get("wear_accumulated") or 0)
    tool["wear_accumulated"] = max(0.0, current + delta)
    # PRD 3.6: "The band is then recomputed from the new accumulation, and it is
    # raised only when a band threshold has actually been crossed".  A correction
    # that lowers the accumulation therefore also lowers the band when the new
    # figure no longer reaches the band's threshold -- the recompute is what
    # "raised only when crossed" qualifies, not a ratchet in the other
    # direction.  Nothing below LEVEL_1 is reachable because the accumulation
    # itself floors at zero.
    recomputed = calc.literal_wear_band(tool["wear_accumulated"])
    tool["wear_band"] = recomputed
    multiplier, forfeiture, grace = calc.wear_values(recomputed)
    tool["wear_multiplier_rate"] = multiplier
    tool["wear_forfeiture_rate"] = forfeiture
    tool["wear_grace_period_hours"] = grace
    calc.apply_wear_band_side_effects(tool, account_home_store_for_tool(tool))
    common.record_audit(tool)
    return tool


def reset_wear(tool, body=None):
    if tool.get("wear_band") not in ("LEVEL_2", "LEVEL_3", "LEVEL_4", "LEVEL_5"):
        raise ApiError("ERR_INVALID_TOOL_WEAR_BAND")
    tool["wear_accumulated"] = 0
    tool["wear_band"] = "LEVEL_1"
    multiplier, forfeiture, grace = calc.wear_values("LEVEL_1")
    tool["wear_multiplier_rate"] = multiplier
    tool["wear_forfeiture_rate"] = forfeiture
    tool["wear_grace_period_hours"] = grace
    common.record_audit(tool)
    return tool


def add_tool_fitment(tool, body):
    require_fields(body, ["part_id", "placement", "depth_index"])
    part = db.parts.get(str(body["part_id"]))
    if part is None:
        raise ApiError("ERR_PART_NOT_FOUND")
    placement = string_field(body, "placement", required=True)
    if placement not in ("FRONT", "REAR_LEFT", "REAR_RIGHT", "OTHER"):
        bad_request("placement must be FRONT, REAR_LEFT, REAR_RIGHT or OTHER.")
    fitment = common.slim_resource({
        "tool_catalog_id": tool["id"],
        "part_id": part["id"],
        "placement": placement,
        "depth_index": _int(body, "depth_index"),
    })
    db.tool_fitments[fitment["id"]] = fitment
    return fitment


# ---------------------------------------------------------------------------
# ToolLoan
# ---------------------------------------------------------------------------

def create_loan(body):
    require_fields(body, ["account_id", "tool_catalog_id", "deposit_amount_cents"])
    account = db.accounts.get(str(body["account_id"]))
    if account is None:
        raise ApiError("ERR_COMMERCIAL_ACCOUNT_NOT_FOUND")
    tool = db.tool_catalog.get(str(body["tool_catalog_id"]))
    if tool is None:
        raise ApiError("ERR_TOOL_CATALOG_NOT_FOUND")
    loaned_order_id = optional(body, "loaned_order_id")
    if loaned_order_id is not None:
        if db.part_orders.get(str(loaned_order_id)) is None:
            raise ApiError("ERR_PART_ORDER_NOT_FOUND")
        loaned_order_id = str(loaned_order_id)

    loan = common.new_resource({
        "account_id": account["id"],
        "tool_catalog_id": tool["id"],
        "loaned_order_id": loaned_order_id,
        "deposit_amount_cents": _int(body, "deposit_amount_cents"),
        "deposit_state": "UNCHARGED",
        "loaned_at": None,
        "due_at": None,
        "returned_at": None,
        "overdue_days": 0,
        "return_condition": None,
        "deposit_forfeited_cents": 0,
        "replacement_part_id": None,
        "wear_intensity": 0,
        "damage_multiplier": 1.00,
        "forfeiture_rate": 0.00,
        "status": "REQUESTED",
    })
    db.tool_loans[loan["id"]] = loan
    if loaned_order_id:
        order = db.part_orders.get(loaned_order_id)
        if order is not None:
            order["refundable_deposit_cents"] = calc.refundable_deposit_for(order, account["id"])
            common.record_audit(order)
    ledger.recompute_account(account)
    common.remember("tool_loans", loan["id"])
    return loan


def checkout_loan(loan, body):
    account = db.accounts.get(loan["account_id"])
    tool = db.tool_catalog.get(loan["tool_catalog_id"])
    if loan.get("status") != "REQUESTED":
        raise ApiError("ERR_LOAN_NOT_REQUESTED")
    if account is None or account.get("account_posture") != "OPEN":
        raise ApiError("ERR_ACCOUNT_NOT_OPEN")

    accepted = body.get("accepted_deposit_cents")
    amount = loan.get("deposit_amount_cents") or 0
    if accepted is not None:
        try:
            amount = int(accepted)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "accepted_deposit_cents must be an integer.")
    minimum = (tool or {}).get("deposit_amount_cents") or 0
    if amount < minimum:
        raise ApiError("ERR_DEPOSIT_BELOW_MINIMUM")
    if ledger.credit_exposure(account) + amount > (account.get("credit_limit_cents") or 0):
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")
    for other in db.tool_loans.values():
        if other["id"] == loan["id"]:
            continue
        if tool is None or other.get("tool_catalog_id") != tool["id"]:
            continue
        if other.get("account_id") != account["id"]:
            continue
        if other.get("status") in TOOL_ON_LOAN_STATES:
            raise ApiError("ERR_TOOL_ALREADY_ON_LOAN")

    _check_account_version(body, account)

    loan["deposit_amount_cents"] = amount
    loan["deposit_state"] = "HELD"
    loan["loaned_at"] = db.clock_iso()
    loan["status"] = "CHECKED_OUT"
    account["petty_cash_cents"] = (account.get("petty_cash_cents") or 0) + amount
    _refresh_attached_order(loan, account)
    common.record_audit(loan)
    ledger.recompute_account(account)
    return loan


def _refresh_attached_order(loan, account):
    order_id = loan.get("loaned_order_id")
    if not order_id:
        return
    order = db.part_orders.get(order_id)
    if order is None:
        return
    order["refundable_deposit_cents"] = calc.refundable_deposit_for(order, account["id"])
    common.record_audit(order)


def _check_account_version(body, account):
    expected = optional(body, "expected_account_version")
    if expected is None:
        return
    try:
        value = int(expected)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "expected_account_version must be an integer.")
    if value != (account.get("version") or 0):
        raise ApiError("ERR_STALE_ACCOUNT_VERSION")


def update_loan(loan, body):
    account = db.accounts.get(loan["account_id"])
    tool = db.tool_catalog.get(loan["tool_catalog_id"])
    if loan.get("status") != "CHECKED_OUT":
        raise ApiError("ERR_LOAN_NOT_CHECKED_OUT")
    try:
        new_amount = int(body.get("deposit_amount_cents"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "deposit_amount_cents must be an integer.")
    minimum = (tool or {}).get("deposit_amount_cents") or 0
    if new_amount < minimum:
        raise ApiError("ERR_DEPOSIT_BELOW_MINIMUM")
    _check_account_version(body, account)

    previous = loan.get("deposit_amount_cents") or 0
    loan["deposit_amount_cents"] = new_amount
    account["petty_cash_cents"] = (account.get("petty_cash_cents") or 0) + (new_amount - previous)
    _refresh_attached_order(loan, account)
    common.record_audit(loan)
    ledger.recompute_account(account)
    return loan


def specsification_on_wear(loan):
    """The second CHECKED_OUT self-transition: a wear-band respecification
    refreshes the loan's replacement part and leaves it CHECKED_OUT."""
    if loan.get("status") != "CHECKED_OUT":
        raise ApiError("ERR_LOAN_NOT_CHECKED_OUT")
    tool = db.tool_catalog.get(loan.get("tool_catalog_id"))
    if tool is None:
        raise ApiError("ERR_TOOL_CATALOG_NOT_FOUND")
    if calc.band_index(tool.get("wear_band")) < calc.band_index("LEVEL_2"):
        raise ApiError("ERR_INSUFFICIENT_TOOL_WEAR")
    account = db.accounts.get(loan.get("account_id"))
    selected = calc.select_replacement(tool["id"], (account or {}).get("home_store_id"),
                                       tool.get("replacement_part_id"))
    tool["replacement_part_id"] = selected
    loan["replacement_part_id"] = selected
    common.record_audit(tool)
    common.record_audit(loan)
    return loan


# ---------------------------------------------------------------------------
# the clock-driven transitions
# ---------------------------------------------------------------------------

def apply_clock_transitions(loan):
    """Advance the loan along the system transitions whose trigger is the
    logical clock (SCAFFOLD 1.2 ToolLoan)."""
    account = db.accounts.get(loan["account_id"])
    status = loan.get("status")
    if status == "CHECKED_OUT":
        loaned_at = calc._parse(loan.get("loaned_at"))
        # PRD 3.6: "Once the logical clock is strictly after the loan's
        # `loaned_at`, an unconditional system transition sets the loan's
        # `due_at` to the logical clock advanced by exactly 14 days and moves
        # the loan to `IN_USE`. From there the clock drives two further
        # transitions."  Both are strictly-after comparisons against the clock:
        # `loaned_at` is stamped from that same clock, so a checkout observed
        # at its own instant is not yet out in the field, and the 24-hour
        # ahead-of-due transition therefore tests against `due_at` itself
        # (PRD: "once the logical clock ... has reached or passed `due_at`
        # minus 24 hours").
        if loaned_at is not None and db.clock() > loaned_at:
            loan["due_at"] = calc._fmt(db.clock() + timedelta(days=14))
            loan["status"] = "IN_USE"
            common.record_audit(loan)
            status = "IN_USE"
    if status == "IN_USE":
        due_at = calc._parse(loan.get("due_at"))
        if due_at is not None and db.clock() >= due_at - timedelta(hours=24):
            if account is not None and ledger.credit_exposure(account) > (account.get("credit_limit_cents") or 0):
                raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")
            loan["status"] = "DUE"
            common.record_audit(loan)
            status = "DUE"
    if status == "DUE":
        due_at = calc._parse(loan.get("due_at"))
        if due_at is not None and db.clock() > due_at:
            if account is not None and ledger.credit_exposure(account) > (account.get("credit_limit_cents") or 0):
                raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")
            loan["status"] = "OVERDUE"
            loan["overdue_days"] = max(0, int((db.clock() - due_at).total_seconds() // 86400))
            common.record_audit(loan)
    if loan.get("status") != "OVERDUE":
        loan["overdue_days"] = 0
    return loan


def settle_loan(loan):
    """Run the clock-driven transitions before any action endpoint reads a
    loan's status."""
    try:
        apply_clock_transitions(loan)
    except ApiError:
        pass
    return loan


def return_loan(loan, body):
    settle_loan(loan)
    if loan.get("status") not in OUT_STATES:
        raise ApiError("ERR_LOAN_NOT_OUT")
    loan["status"] = "RETURNED"
    loan["returned_at"] = db.clock_iso()
    common.record_audit(loan)
    return loan


def inspect_loan(loan, body):
    account = db.accounts.get(loan["account_id"])
    tool = db.tool_catalog.get(loan["tool_catalog_id"])
    if loan.get("status") != "RETURNED":
        raise ApiError("ERR_LOAN_NOT_RETURNED")
    condition = string_field(body, "return_condition", required=True)
    if condition not in CONDITIONS:
        raise ApiError("ERR_INVALID_RETURN_CONDITION")
    if not _return_desk_exists(account):
        raise ApiError("ERR_RETURN_DESK_STOP_MISSING")
    # PRD 3.6: the return-desk requirement exists so the crib can reconcile the
    # tool against the work that prompted it; the loan's own `loaned_order_id`
    # must therefore still be a live order, not one that has been voided out
    # from under it.  ERR_RETURN_DESK_STOP_MISSING carries both branches.
    linked_order_id = loan.get("loaned_order_id")
    if linked_order_id:
        linked = db.part_orders.get(linked_order_id)
        if linked is None or linked.get("status") == "VOID":
            raise ApiError("ERR_RETURN_DESK_STOP_MISSING")

    intensity, multiplier, rate = calc.condition_readings(tool, condition)
    loan["return_condition"] = condition
    loan["wear_intensity"] = intensity
    loan["damage_multiplier"] = multiplier

    if condition == "WORN":
        selected = calc.select_replacement(tool["id"], account.get("home_store_id"),
                                           tool.get("replacement_part_id"))
        if selected is None:
            loan["replacement_part_id"] = None
            rate = to_decimal("1.00")
        else:
            loan["replacement_part_id"] = selected
    elif condition == "LOST":
        loan["replacement_part_id"] = tool.get("replacement_part_id")

    loan["forfeiture_rate"] = _fmt_rate(rate)
    deposit = loan.get("deposit_amount_cents") or 0
    forfeited = round_half_up(to_decimal(deposit) * rate)
    loan["deposit_forfeited_cents"] = forfeited
    refundable = deposit - forfeited
    if refundable > deposit:
        raise ApiError("ERR_DEPOSIT_AMOUNT_EXCEEDS_CHARGE")

    if condition in ("WORN", "BROKEN"):
        tool["wear_accumulated"] = float(tool.get("wear_accumulated") or 0) + 0.4
        advance_wear_band(tool)

    loan["status"] = "INSPECTED"
    common.record_audit(loan)
    ledger.recompute_account(account)
    return loan


def _fmt_rate(rate):
    """A rate is a number, not a formatted string (SCAFFOLD 1.2 ToolLoan).

    All four severity bands are exact hundredths, so the quantized decimal
    converts back to the float the contract describes without loss.
    """
    return float(to_decimal(rate).quantize(to_decimal("0.01")))


def _return_desk_exists(account):
    for stop in db.route_stops.values():
        if stop.get("account_id") != account["id"]:
            continue
        if stop.get("stop_kind") != "RETURN_DESK":
            continue
        route = db.service_routes.get(stop.get("route_id"))
        if route is None:
            continue
        if route.get("status") == "CANCELLED":
            continue
        return True
    return False


def close_loan(loan, body):
    account = db.accounts.get(loan["account_id"])
    if loan.get("status") != "INSPECTED":
        raise ApiError("ERR_LOAN_NOT_INSPECTED")
    if loan.get("return_condition") not in ("GOOD", "WORN"):
        raise ApiError("ERR_LOAN_NOT_CLOSABLE")
    if loan.get("deposit_state") != "HELD":
        raise ApiError("ERR_DEPOSIT_NOT_HELD")
    # PRD 3.6: "a shop with no return-desk stop on a live route cannot have its
    # tool inspected at all" -- closing draws the same precondition, so a route
    # cancelled out from under the loan takes the close with it.
    if not _return_desk_exists(account):
        raise ApiError("ERR_RETURN_DESK_STOP_MISSING")

    deposit = loan.get("deposit_amount_cents") or 0
    forfeited = loan.get("deposit_forfeited_cents") or 0
    loan["deposit_state"] = "REFUNDED"
    account["petty_cash_cents"] = (account.get("petty_cash_cents") or 0) - (deposit - forfeited)
    loan["status"] = "CLOSED"
    common.record_audit(loan)
    ledger.recompute_account(account)
    return loan


def forfeit_loan(loan, body):
    account = db.accounts.get(loan["account_id"])
    if loan.get("status") != "INSPECTED":
        raise ApiError("ERR_LOAN_NOT_INSPECTED")
    if loan.get("deposit_state") != "HELD":
        raise ApiError("ERR_DEPOSIT_NOT_HELD")
    if not _return_desk_exists(account):
        raise ApiError("ERR_RETURN_DESK_STOP_MISSING")

    ledger.recompute_account(account, derive_posture=False)
    deposit = loan.get("deposit_amount_cents") or 0
    loan["deposit_forfeited_cents"] = deposit
    if (account.get("receivable_balance_cents") or 0) > 0:
        # The held cash pays the debt down: the deposit leaves petty cash and the
        # receivable drops by the same amount, so no cash and no receivable leaks
        # out of the account (PRD 3.6, PRD 2.11).
        loan["deposit_state"] = "APPLIED_TO_BALANCE"
        account["petty_cash_cents"] = (account.get("petty_cash_cents") or 0) - deposit
        account["deposits_applied_to_balance_cents"] = (
            account.get("deposits_applied_to_balance_cents") or 0) + deposit
    else:
        loan["deposit_state"] = "FORFEITED"
        account["petty_cash_cents"] = (account.get("petty_cash_cents") or 0) - deposit
    loan["status"] = "FORFEITED"
    common.record_audit(loan)
    ledger.recompute_account(account)
    return loan