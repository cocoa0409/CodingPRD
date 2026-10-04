"""Derived-field recomputation and the two system sweeps.

Every derived attribute a client can observe is recomputed on the write that
changes it. A recomputation that moves a value refreshes the owning row's
updated_at and bumps its version exactly as a client write would.
"""

import calc
import clock
import store


# --------------------------------------------------------------------------
# Shops, routes, technicians
# --------------------------------------------------------------------------

def recompute_shop(shop):
    count = 0
    for tech in store.technicians.values():
        if (tech.get("technician_status") == "ACTIVE"
                and tech.get("current_shop_location_id") == shop["id"]):
            count += 1
    store.set_field(shop, "active_technician_count", count)


def recompute_route(route):
    at_risk = 0
    over_pledge = 0
    for position in store.positions.values():
        if position.get("route_id") != route["id"]:
            continue
        cost = position.get("unit_cost_cents", 0)
        reserved = position.get("reserved_qty", 0)
        on_hand = position.get("on_hand_qty", 0)
        at_risk += reserved * cost
        over_pledge += max(0, reserved - on_hand) * cost
    store.set_field(route, "inventory_at_risk_cents", at_risk)
    store.set_field(route, "over_pledge_cents", over_pledge)
    store.set_field(route, "schedule_anchor_utc",
                    clock.fmt_week(clock.route_anchor(route.get("visit_weekday", 1))))


def recompute_technician(technician):
    shop = store.shops.get(technician.get("current_shop_location_id"))
    home = shop.get("route_id") if shop else None
    store.set_field(technician, "home_route_id", home)

    used = 0
    open_count = 0
    for account in store.accounts.values():
        if account.get("technician_id") != technician["id"]:
            continue
        status = account.get("account_status")
        if status in ("ACTIVE", "DELINQUENT", "CHARGED_OFF"):
            open_count += 1
        if account.get("account_kind") == "REVOLVING" and status in ("ACTIVE", "DELINQUENT"):
            used += account.get("current_balance_cents", 0)
    store.set_field(technician, "revolving_used_cents", used)
    store.set_field(technician, "revolving_available_cents",
                    max(0, technician.get("credit_line_limit_cents", 0) - used))
    store.set_field(technician, "open_account_count", open_count)


def recompute_franchisee(franchisee):
    owned_routes = [r for r in store.routes.values()
                    if r.get("franchisee_id") == franchisee["id"]]
    store.set_field(franchisee, "total_route_count", len(owned_routes))
    store.set_field(franchisee, "active_route_count",
                    len([r for r in owned_routes if r.get("route_status") == "IN_SERVICE"]))

    owned_route_ids = {r["id"] for r in owned_routes}
    ceiling = 0
    outstanding = 0
    exposure = 0
    for account in store.accounts.values():
        if account.get("territory_id") not in owned_route_ids:
            continue
        status = account.get("account_status")
        if status in ("ACTIVE", "DELINQUENT"):
            ceiling += account.get("credit_limit_cents", 0)
            outstanding += account.get("current_balance_cents", 0)
        if (account.get("recourse_holder") == "FRANCHISEE"
                and status in ("ACTIVE", "DELINQUENT", "CHARGED_OFF")):
            exposure += account.get("current_balance_cents", 0)
    store.set_field(franchisee, "credit_ceiling_cents", ceiling)
    store.set_field(franchisee, "outstanding_credit_cents", outstanding)
    store.set_field(franchisee, "recourse_exposure_cents", exposure)
    store.set_field(franchisee, "franchisee_capital_at_risk_cents", outstanding - exposure)

    fallback = None
    for shop in store.shops.values():
        if shop.get("route_id") not in owned_route_ids:
            continue
        if shop.get("shop_status") != "ACTIVE":
            continue
        if fallback is None or (shop.get("created_at") or "") < (fallback.get("created_at") or ""):
            fallback = shop
    store.set_field(franchisee, "fallback_shop_location_id",
                    fallback["id"] if fallback else None)
    store.set_field(franchisee, "can_resell_territory",
                    franchisee.get("training_status") == "CERTIFIED")


def recompute_franchisee_of_route(route):
    franchisee = store.franchisees.get(route.get("franchisee_id"))
    if franchisee:
        recompute_franchisee(franchisee)


# --------------------------------------------------------------------------
# Accounts and their dependants
# --------------------------------------------------------------------------

def account_charges(account_id):
    return [c for c in store.charges.values() if c.get("account_id") == account_id]


def account_payments(account_id):
    return [p for p in store.payments.values() if p.get("account_id") == account_id]


def recompute_account(account):
    charges = account_charges(account["id"])
    accrued = sum(c.get("charge_amount_cents", 0) - c.get("collection_applied_cents", 0)
                  for c in charges)
    principal = account.get("principal_balance_cents", 0)
    store.set_field(account, "accrued_finance_charge_cents", accrued)
    store.set_field(account, "current_balance_cents", principal + accrued)
    store.set_field(account, "credit_available_cents",
                    max(0, account.get("credit_limit_cents", 0) - (principal + accrued)))
    store.set_field(account, "is_lease_program", account.get("account_kind") == "LEASE")
    store.set_field(account, "is_revolving_program", account.get("account_kind") == "REVOLVING")

    payments = account_payments(account["id"])
    store.set_field(account, "missed_payment_count",
                    len([p for p in payments if p.get("payment_status") == "MISSED"]))
    booked = [p for p in payments if p.get("payment_status") == "BOOKED"]
    if booked:
        earliest = min(booked, key=lambda p: p.get("expected_week_start") or "")
        due_weekday = _weekday_of(earliest.get("expected_week_start"))
    else:
        due_weekday = account.get("payment_due_weekday")
    store.set_field(account, "next_due_weekday", due_weekday)
    collected = [p for p in payments if p.get("payment_status") == "COLLECTED"]
    if collected:
        latest = max(collected, key=lambda p: p.get("expected_week_start") or "")
        store.set_field(account, "last_payment_week_start", latest.get("expected_week_start"))
    else:
        store.set_field(account, "last_payment_week_start", None)

    if account.get("account_kind") == "LEASE":
        installment = calc.lease_amortization(principal, account.get("term_months", 0),
                                              account.get("account_status"))
    else:
        installment = 0
    store.set_field(account, "installment_due_cents", installment)
    store.set_field(account, "minimum_payment_due_cents", calc.minimum_payment_due(
        account.get("current_balance_cents", 0), account.get("account_status"),
        account.get("account_kind") == "LEASE", installment))


def _weekday_of(iso_text):
    if not iso_text:
        return None
    parsed = clock.parse_utc(iso_text)
    return parsed.weekday() + 1


def recompute_account_dependants(account):
    technician = store.technicians.get(account.get("technician_id"))
    if technician:
        recompute_technician(technician)
    route = store.routes.get(account.get("territory_id"))
    if route:
        recompute_franchisee_of_route(route)


def recompute_all_accounts():
    for account in store.accounts.values():
        recompute_account(account)


# --------------------------------------------------------------------------
# Sales orders and warranty claims
# --------------------------------------------------------------------------

def approved_claim_allocations(order_id):
    return [c.get("principal_allocated_cents", 0) for c in store.claims.values()
            if c.get("order_id") == order_id and c.get("claim_status") == "APPROVED"]


def recompute_order(order):
    lines = order.get("lines", [])
    store.set_field(order, "line_count", len(lines))
    gross = calc.order_gross_total(lines, order.get("mix_profile"))
    store.set_field(order, "gross_total_cents", gross)
    settled = order.get("order_status") == "SETTLED"
    financed = calc.order_financing_variant(
        order, gross, approved_claim_allocations(order["id"]), settled)
    store.set_field(order, "financed_principal_cents", financed)


def claim_amounts(claim):
    """(replacement_charge_cents, warranty_credit_amount_cents) for a claim."""
    order = store.sales_orders.get(claim.get("order_id"))
    if order is None:
        return 0, 0
    lines = order.get("lines", [])
    index = claim.get("line_index", -1)
    if index < 0 or index >= len(lines):
        return 0, 0
    line = lines[index]
    product = store.products.get(line.get("product_id"))
    if product is None:
        return 0, 0
    warranty_months = (line.get("warranty_terms") or {}).get("months", 0)
    elapsed = clock.months_between(
        clock.parse_utc(order.get("sale_iso_week")) if order.get("sale_iso_week") else None,
        clock.current_week_start())
    replacement = calc.warranty_charges(line, product, elapsed, warranty_months)
    credit = calc.warranty_credit_amount(line, product, claim.get("claim_kind"),
                                         claim.get("claim_status"))
    return replacement, credit


def recompute_claim(claim):
    replacement, credit = claim_amounts(claim)
    store.set_field(claim, "replacement_charge_cents", replacement)
    store.set_field(claim, "warranty_credit_amount_cents", credit)


# --------------------------------------------------------------------------
# System sweeps — evaluated on every request
# --------------------------------------------------------------------------

def accrue_account(account):
    """One charge for the current week when the clock has moved past the last."""
    if account.get("account_status") == "CLOSED":
        return
    current_week = clock.current_week_start()
    charges = account_charges(account["id"])
    if charges:
        baseline = max(clock.parse_utc(c["accrual_iso_week"]) for c in charges)
    else:
        baseline = clock.week_start(clock.parse_utc(account["created_at"]))
    if current_week <= baseline:
        return
    opening = account.get("principal_balance_cents", 0)
    if account.get("use_final_basis"):
        settled = sum(p.get("charge_applied_cents", 0) for p in account_payments(account["id"])
                      if p.get("payment_status") == "COLLECTED"
                      and p.get("effective_iso_week") == clock.fmt_week(current_week))
        basis = opening - settled
    else:
        basis = opening
    seq = len([c for c in charges if c.get("accrual_iso_week") == clock.fmt_week(current_week)]) + 1
    store.create(store.charges,
                 account_id=account["id"],
                 accrual_iso_week=clock.fmt_week(current_week),
                 accrual_seq=seq,
                 opening_balance_cents=opening,
                 charge_amount_cents=calc.finance_charge_amount(basis),
                 collection_applied_cents=0,
                 charge_status="OPEN",
                 charge_resolved_iso_week=None)
    recompute_account(account)


def run_sweeps():
    """Charge-off sweep plus the weekly accrual, evaluated on every request."""
    current_week = clock.current_week_start()
    for account in list(store.accounts.values()):
        accrue_account(account)
        status = account.get("account_status")
        if status not in ("ACTIVE", "DELINQUENT"):
            continue
        changed_week = clock.week_start(clock.parse_utc(account["account_status_changed_at"]))
        if not calc.charge_off_due(changed_week, current_week):
            continue
        if status == "ACTIVE" and account.get("missed_payment_count", 0) < 3:
            continue
        store.set_field(account, "account_status", "CHARGED_OFF")
        account["account_status_changed_at"] = clock.fmt_week(clock.now())
        store.stamp(account)
        recompute_account(account)
        recompute_account_dependants(account)
