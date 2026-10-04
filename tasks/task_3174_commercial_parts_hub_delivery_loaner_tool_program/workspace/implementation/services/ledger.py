"""The revolving credit ledger, the account posture state machine and the
cascading void (PRD 2.5, 2.6, 3.8 and SCAFFOLD 1.2 CommercialAccount)."""

from datetime import timedelta

import db
from errors import ApiError
from money import to_decimal
from services import calc, common


# ---------------------------------------------------------------------------
# derived account figures
# ---------------------------------------------------------------------------

def credit_exposure(account):
    """sum over open orders of parts_subtotal_cents + sum over HELD loan
    deposits.  DELIVERED, RETURNED and VOID orders contribute 0."""
    total = 0
    for order in db.part_orders.values():
        if order.get("account_id") != account["id"]:
            continue
        if order.get("status") not in ("DRAFT", "CONFIRMED", "ALLOCATED", "PICKING", "DISPATCHED"):
            continue
        total += order.get("parts_subtotal_cents") or 0
    for loan in db.tool_loans.values():
        if loan.get("account_id") != account["id"]:
            continue
        if loan.get("deposit_state") != "HELD":
            continue
        total += loan.get("deposit_amount_cents") or 0
    return total


def deposit_liability(account):
    total = 0
    for loan in db.tool_loans.values():
        if loan.get("account_id") != account["id"]:
            continue
        if loan.get("deposit_state") != "HELD":
            continue
        total += (loan.get("deposit_amount_cents") or 0) - (loan.get("deposit_forfeited_cents") or 0)
    return total


def captured_cents(order):
    """The amount an order has moved onto the receivable.

    PRD 2.6: "Orders in `DELIVERED`, `RETURNED` or `VOID` contribute nothing
    [to credit exposure]: they have left the provisional exposure pool and moved
    onto the receivable."  The movement happens at delivery (PRD 3.4: "The
    account's `receivable_balance_cents` is recomputed over its non-`VOID`
    orders ... and the order moves to `DELIVERED`"), so an order that has not
    been delivered is still provisional and has no invoice yet.
    """
    if order.get("delivered_at") is None and order.get("status") not in (
            "DELIVERED", "RETURNED"):
        return 0
    return order.get("parts_subtotal_cents") or 0


def receivable_balance(account):
    """The sum of `captured_cents` over the account's non-`VOID` invoices, less
    any held deposit already applied against that debt.

    PRD 3.6: "When the account's `receivable_balance_cents` is above zero, the
    deposit is applied against that debt: `deposit_state` moves to
    `APPLIED_TO_BALANCE` and `receivable_balance_cents` is reduced by the deposit
    amount."  The reduction is an offset carried on the account rather than a
    rewrite of any invoice, so the figure survives every later recompute and no
    formula that reads net terms has to special-case it.
    """
    total = 0
    for order in db.part_orders.values():
        if order.get("account_id") != account["id"]:
            continue
        if order.get("status") == "VOID":
            continue
        total += captured_cents(order)
    total -= account.get("deposits_applied_to_balance_cents") or 0
    return max(0, total)


def recompute_account(account, derive_posture=True):
    """Recompute every derived figure and refresh the audit spine."""
    account["credit_exposure_cents"] = credit_exposure(account)
    account["deposit_liability_cents"] = deposit_liability(account)
    account["receivable_balance_cents"] = receivable_balance(account)
    account["next_cutoff_at"] = next_cutoff(account)
    if derive_posture:
        account["account_posture"] = calc.derive_account_posture(account)
    common.record_audit(account)
    return account


def sync_posture(account):
    """Refresh the stored account_posture from the derivation without treating
    the refresh as a client mutation: a read must not bump the audit spine, or
    the optimistic-concurrency guard would reject every write that follows a
    read (PRD 2.4, 2.6)."""
    if account is None:
        return account
    derived = calc.derive_account_posture(account)
    if account.get("account_posture") != derived:
        account["account_posture"] = derived
    return account


def next_cutoff(account):
    """The next delivery cutoff instant for this account's schedule."""
    store = db.stores.get(account.get("home_store_id"))
    if store is None:
        return None
    hour = store.get("cutoff_hour_local")
    if hour is None:
        hour = 15
    now = db.clock()
    candidate = now.replace(hour=int(hour), minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    from timeutil import format_iso
    return format_iso(candidate)


def sales_rep_active_count(rep):
    """Non-archived accounts whose home_store_id is assigned to this rep on the
    current coverage date (PRD 3.1)."""
    now = db.clock()
    count = 0
    for account in db.accounts.values():
        if account.get("is_archived"):
            continue
        if not coverage_covers(rep["id"], account["id"], now):
            continue
        count += 1
    return count


def coverage_covers(rep_id, account_id, at_instant):
    """A coverage window spans the instant when the logical clock is at or after
    its effective_from and strictly before its effective_to, so a row that has
    never been explicitly expired still covers the instant once the clock
    reaches it (PRD 3.1)."""
    for coverage in db.rep_coverages.values():
        if coverage.get("rep_id") != rep_id or coverage.get("account_id") != account_id:
            continue
        start = calc._parse(coverage.get("effective_from"))
        end = calc._parse(coverage.get("effective_to"))
        if coverage.get("coverage_posture") == "EXPIRED":
            continue
        if start is not None and at_instant < start:
            continue
        if end is not None and at_instant >= end:
            continue
        return True
    return False


def refresh_all_rep_counts():
    """Re-derive every rep's count, including the lazily drifting posture of
    each coverage window (PRD 3.1)."""
    for coverage in db.rep_coverages.values():
        if coverage.get("coverage_posture") == "EXPIRED":
            continue
        now = db.clock()
        start = calc._parse(coverage.get("effective_from"))
        end = calc._parse(coverage.get("effective_to"))
        if start is not None and now < start:
            derived = "SCHEDULED"
        elif end is not None and now >= end:
            derived = "EXPIRED"
        else:
            derived = "ACTIVE"
        if coverage.get("coverage_posture") != derived:
            coverage["coverage_posture"] = derived
            common.record_audit(coverage)
    for rep in db.sales_reps.values():
        count = sales_rep_active_count(rep)
        if rep.get("active_account_count") != count:
            rep["active_account_count"] = count
            common.record_audit(rep)


def refresh_rep_counts(*rep_ids):
    seen = set()
    for rep_id in rep_ids:
        rep = db.sales_reps.get(rep_id)
        if rep is None or rep_id in seen:
            continue
        seen.add(rep_id)
        rep["active_account_count"] = sales_rep_active_count(rep)
        common.record_audit(rep)


# ---------------------------------------------------------------------------
# account posture state machine
# ---------------------------------------------------------------------------

def require_posture(account, required):
    if account.get("account_posture") != required:
        raise ApiError("ERR_INVALID_ACCOUNT_POSTURE")


def hold_account(account):
    """POST /commercial/commercial-accounts/{accountId}/hold.

    The hold exists to stop a shop that has already overrun: it requires the
    account to be OPEN and the exposure to exceed the limit.  It is also the
    entry point for credit suspension evaluation.
    """
    posture = account.get("account_posture")
    if posture == "CLOSED":
        raise ApiError("ERR_INVALID_ACCOUNT_POSTURE")
    recompute_account(account, derive_posture=False)
    if account["credit_exposure_cents"] > (account.get("credit_limit_cents") or 0):
        _cascading_void(account)
        account["account_posture"] = "ON_HOLD"
        recompute_account(account, derive_posture=False)
        return account
    if posture == "ON_HOLD":
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")
    if posture not in ("OPEN", "CREDIT_SUSPENDED"):
        raise ApiError("ERR_INVALID_ACCOUNT_POSTURE")
    derived = calc.derive_account_posture(account)
    if derived == "CREDIT_SUSPENDED":
        account["account_posture"] = "CREDIT_SUSPENDED"
    else:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")
    recompute_account(account, derive_posture=False)
    return account


def release_account(account):
    """ON_HOLD -> OPEN, refused with ERR_CREDIT_LIMIT_STILL_EXCEEDED while the
    exposure still exceeds the ceiling."""
    require_posture(account, "ON_HOLD")
    recompute_account(account, derive_posture=False)
    if account["credit_exposure_cents"] > (account.get("credit_limit_cents") or 0):
        raise ApiError("ERR_CREDIT_LIMIT_STILL_EXCEEDED")
    account["account_posture"] = "OPEN"
    recompute_account(account, derive_posture=False)
    return account


def restore_account(account):
    """CREDIT_SUSPENDED -> OPEN under the same exposure gate."""
    require_posture(account, "CREDIT_SUSPENDED")
    recompute_account(account, derive_posture=False)
    if account["credit_exposure_cents"] > (account.get("credit_limit_cents") or 0):
        raise ApiError("ERR_CREDIT_LIMIT_STILL_EXCEEDED")
    account["account_posture"] = "OPEN"
    recompute_account(account, derive_posture=False)
    return account


CLOSABLE_POSTURES = ("OPEN", "ON_HOLD", "CREDIT_SUSPENDED")


def close_account(account):
    """The terminal act, guarded on four fronts with the PRD's precedence:
    open orders, then open loans, then open core returns, then the receivable."""
    if account.get("account_posture") not in CLOSABLE_POSTURES:
        raise ApiError("ERR_INVALID_ACCOUNT_POSTURE")
    for order in db.part_orders.values():
        if order.get("account_id") == account["id"] and order.get("status") in common.OPEN_ORDER_STATES:
            raise ApiError("ERR_OPEN_ORDERS_EXIST")
    for loan in db.tool_loans.values():
        if loan.get("account_id") == account["id"] and loan.get("status") in common.OPEN_LOAN_STATES:
            raise ApiError("ERR_OPEN_LOANS_EXIST")
    for core in db.core_returns.values():
        if core.get("account_id") == account["id"] and core.get("status") in common.OPEN_CORE_STATES:
            raise ApiError("ERR_OPEN_CORE_RETURNS_EXIST")
    recompute_account(account, derive_posture=False)
    if account["receivable_balance_cents"] != 0:
        raise ApiError("ERR_RECEIVABLE_BALANCE_OUTSTANDING")
    account["account_posture"] = "CLOSED"
    recompute_account(account, derive_posture=False)
    return account


# ---------------------------------------------------------------------------
# the cascading void (PRD 2.5)
# ---------------------------------------------------------------------------

def _cascading_void(account):
    route_ids = set()
    for order in list(db.part_orders.values()):
        if order.get("account_id") != account["id"]:
            continue
        if order.get("status") not in ("DRAFT", "CONFIRMED", "ALLOCATED", "PICKING", "DISPATCHED"):
            continue
        _void_order(order, account, cascade=False)
        route_id = order.get("service_route_id")
        if route_id:
            route_ids.add(route_id)
            for stop in common.stops_of(route_id):
                if order["id"] in (stop.get("order_ids") or []):
                    stop["status"] = "REJECTED"
                    common.record_audit(stop)
    for route_id in route_ids:
        route = db.service_routes.get(route_id)
        if route is not None:
            calc.derive_route_geometry(route)
    recompute_account(account, derive_posture=False)
    return account


def _void_order(order, account, cascade=True):
    """Release the order's reservations and move it to VOID."""
    if order.get("status") == "DRAFT":
        order["status"] = "VOID"
        common.record_audit(order)
        return order
    source = _source_stores(order)
    for index, line in enumerate(order.get("line_items") or []):
        quantity = line.get("quantity") or 0
        store_id = source[index] if index < len(source) else None
        if store_id is None:
            continue
        item = common.inventory_item_for(store_id, line.get("part_id"))
        if item is not None:
            common.release_reservation(item, quantity)
        store = db.stores.get(store_id)
        if store is not None:
            store["committed_units_today"] = max(
                0, (store.get("committed_units_today") or 0) - quantity)
            common.record_audit(store)
    order["reserved_unit_count"] = 0
    order["refundable_deposit_consumed_cents"] = 0
    order["status"] = "VOID"

    # PRD 2.5: "For each voided order that carried a non-null `service_route_id`,
    # the `RouteStop` it was dropped at is moved to `REJECTED` and every later
    # stop on that `ServiceRoute` is re-derived -- `stop_sequence`,
    # `projected_arrival_at`, `projected_departure_at`, and `lateness_minutes`
    # are recomputed."
    if cascade:
        _cascade_void_to_route(order)
    common.record_audit(order)
    return order


def _cascade_void_to_route(order):
    from services import routing

    route_id = order.get("service_route_id")
    if not route_id:
        return
    route = db.service_routes.get(route_id)
    if route is None:
        return
    for stop in common.stops_of(route_id):
        if order["id"] not in (stop.get("order_ids") or []):
            continue
        stop["status"] = "REJECTED"
        stop["order_ids"] = [oid for oid in (stop.get("order_ids") or [])
                             if oid != order["id"]]
        common.record_audit(stop)
        calc.derive_route_geometry(route)
        common.record_audit(route)
        break
    order["service_route_id"] = None


def _source_stores(order):
    per_line = order.get("line_source_store_ids") or []
    fallback = order.get("source_store_id")
    out = []
    for index in range(len(order.get("line_items") or [])):
        if index < len(per_line) and per_line[index]:
            out.append(per_line[index])
        else:
            out.append(fallback)
    return out


def void_order(order, account):
    """The public void transition, enforcing the state and role gates."""
    status = order.get("status")
    if status in ("DRAFT", "CONFIRMED"):
        _void_order(order, account)
        recompute_account(account)
        return order
    if status in ("ALLOCATED", "PICKING"):
        _void_order(order, account)
        recompute_account(account)
        return order
    raise ApiError("ERR_ORDER_NOT_VOIDABLE")


def prepare_confirmed_void(order, account):
    """Release reservations on a CONFIRMED order before a void."""
    return _void_order(order, account)