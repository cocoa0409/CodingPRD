"""Money helpers and derived-field recomputation.

Money is carried in integer cents; rates are carried to two decimal places of a
cent (four for commodity blends).  Every figure is rounded half up at the point
of computation, and where a figure is assembled from several components each
component is rounded on its own before the components are summed.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

import constants as C
import store


# --- numeric helpers ---------------------------------------------------------
def D(x):
    if isinstance(x, Decimal):
        return x
    if x is None:
        return Decimal(0)
    if isinstance(x, bool):
        return Decimal(1 if x else 0)
    return Decimal(str(x))


def r2(x):
    """Round a cents figure to a whole cent, half up."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def r2f(x):
    """Round a rate to two decimal places of its own unit, half up."""
    return float(D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def r4f(x):
    """Round a commodity blend to four decimal places, half up."""
    return float(D(x).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def floor_int(x):
    """Truncate toward zero."""
    return int(D(x).to_integral_value(rounding=ROUND_FLOOR))


# --- fuel pricing ------------------------------------------------------------
def effective_commodity_rate(delivery, site=None, frozen=False):
    """composite_hedged_index_price.

    The two products are computed first, then summed, then rounded once to four
    decimal places.  A FIXED_PRICE_BLEND delivery forces the index leg to zero
    and the hedged fraction to one.

    The index leg follows the delivery's basis (PRD 3.3): a delivery still in
    DELIVERY_SCHEDULED or DELIVERY_IN_TRANSIT reads the site's current gas
    index, so the same delivery prices differently before and after it is
    receipted; a confirmed or settled delivery reads the index rate captured
    with it.
    """
    hedged = D(delivery.get("hedged_fraction") or 0)
    fixed = D(delivery.get("fixed_price_cents_per_therm") or 0)
    if delivery.get("sourcing_mode") == "FIXED_PRICE_BLEND":
        hedged = Decimal(1)
        index_leg = Decimal(0)
    elif not frozen and site is not None \
            and delivery.get("lifecycle_state") in ("DELIVERY_SCHEDULED", "DELIVERY_IN_TRANSIT"):
        index_leg = D(site.get("gas_commodity_rate_cents_per_therm") or 0)
    else:
        index_leg = D(delivery.get("index_rate_cents_per_therm") or 0)
    return r4f(hedged * fixed + (Decimal(1) - hedged) * index_leg)


def site_index_leg(site, ppa):
    """The index leg a contract reads: the site's declared index while the
    contract is a draft, and the site's most recent confirmed delivery once the
    contract is live."""
    if ppa.get("state") == "PPA_DRAFT":
        return D(site.get("gas_commodity_rate_cents_per_therm") or 0)
    return D(site.get("current_avoided_fuel_cost_cents_per_therm") or 0)


def contract_index_ceiling(site):
    return r2f(D(site.get("gas_commodity_rate_cents_per_therm") or 0) * D(C.INDEX_CEILING_MULTIPLE))


def index_basis(site):
    ceiling = contract_index_ceiling(site)
    gas = D(site.get("gas_commodity_rate_cents_per_therm") or 0)
    return r2f(min(gas, D(ceiling)))


def effective_fuel_adder(ppa):
    return r2f(min(D(ppa.get("fuel_adder_cents_per_therm") or 0), D(C.HARD_CAP_CENTS_PER_THERM)))


def escalated_rate_at(ppa, instant):
    """The whole-year escalation ladder read at an arbitrary instant."""
    entered = store.parse_dt(ppa["state_entered_at"])
    years = floor_int(max(0, (instant - entered).total_seconds()) / (365 * 86400))
    return r2f(D(ppa.get("tariff_base_cents_per_kwh") or 0) * (1 + D(ppa.get("escalator_pct") or 0)) ** years)


def current_escalated_rate(ppa):
    return escalated_rate_at(ppa, store.clock())


def purchase_price(ppa):
    """The operator's purchase basis, amortised across the committed term.

    Neither document pins a value for `purchase_price_cents_per_kwh`; the
    reading taken here is the contract's own energy rate spread over its term,
    which makes the derived `fixed_purchase_cents` (term * annual * purchase
    price / 12) exactly one month of energy at the contracted annual output --
    a fixed leg of the same order as the variable leg rather than a figure that
    would swamp the settlement credit ceiling on its own.
    """
    term = D(ppa.get("term_years") or 0)
    if term <= 0:
        return r2f(ppa.get("effective_tariff_cents_per_kwh") or 0)
    return r2f(D(ppa.get("effective_tariff_cents_per_kwh") or 0) / term)


def availability_penalty_rate(site):
    return r2f(D(site.get("grid_tariff_rate_cents_per_kwh") or 0) * D(C.AVAILABILITY_PENALTY_MULTIPLE))


def availability_shortfall_kwh(ppa, site, hourly=False):
    if hourly:
        raw = D(ppa.get("contracted_kw") or 0) * 8760 * (1 - D(ppa.get("guaranteed_availability_pct") or 0))
    else:
        raw = (1 - D(ppa.get("guaranteed_availability_pct") or 0)) * D(site.get("expected_annual_site_load_kwh") or 0)
    return float(max(Decimal(0), raw))


# --- settlement line pools ---------------------------------------------------
def live_cap_side_pool(ppa):
    rows = [a for a in store.ppa_accruals(ppa["id"])
            if a.get("accrual_type") in ("CHARGE_ACCRUAL", "OUTPUT_GUARANTEE_ACCRUAL")
            and a.get("lifecycle_state") == "ACCRUAL_OPEN"]
    return sum(int(a.get("signed_amount_cents") or 0) for a in store.by_created(rows))


def live_resource_side_pool(ppa):
    rows = [a for a in store.ppa_accruals(ppa["id"])
            if a.get("accrual_type") == "CAPACITY_ACCRUAL"
            and a.get("lifecycle_state") == "ACCRUAL_OPEN"]
    return sum(int(a.get("signed_amount_cents") or 0) for a in store.by_created(rows))


def output_guarantee_reserve(ppa):
    actual = 0.0
    now = store.clock()
    for line in store.ppa_lines(ppa["id"]):
        if line.get("status") != "SETTLEMENT_APPLIED":
            continue
        start = store.parse_dt(line["period_start"])
        if 0 <= (now - start).total_seconds() <= 365 * 86400:
            actual += float(line.get("metered_kwh") or 0)
    shortfall = max(0.0, float(ppa.get("contracted_annual_kwh") or 0) - actual)
    return r2(D(shortfall) * D(ppa.get("effective_tariff_cents_per_kwh") or 0))


def capacity_reserve_credits(ppa):
    credits = 0
    for allowance in store.ppa_allowances(ppa["id"]):
        if allowance.get("allowance_kind") != "CAPACITY_ALLOWANCE":
            continue
        if allowance.get("lifecycle_state") == "ALLOWANCE_APPLIED" \
                and allowance.get("applied_direction") == "ALLOWANCE_APPLIED_AS_TIME":
            credits += int(allowance.get("applied_amount_cents") or 0)
    for accrual in store.ppa_accruals(ppa["id"]):
        if accrual.get("accrual_type") == "TRUEUP_ACCRUAL":
            credits += int(accrual.get("amount_cents") or 0)
    return credits


def capacity_guarantee_reserve(ppa):
    pre = int(ppa.get("capacity_reserve_pre_cents") or 0)
    if ppa.get("state") == "PPA_DRAFT":
        return pre
    return pre - capacity_reserve_credits(ppa)


def contract_days_used(ppa):
    """Days already settled on the contract, used by the leftover rebate."""
    days = 0
    for line in store.ppa_lines(ppa["id"]):
        if line.get("status") != "SETTLEMENT_APPLIED":
            continue
        days += max(0, store.days_between(store.parse_dt(line["period_start"]),
                                          store.parse_dt(line["period_end"])))
    return days


# --- contract-level recomputation -------------------------------------------
def recompute_ppa(ppa):
    """Refresh the contract's derived fields.  Callers own the version bump."""
    site = store.get_site(ppa.get("site_id"))
    if site is None:
        return ppa
    ppa["effective_tariff_cents_per_kwh"] = current_escalated_rate(ppa)
    ppa["purchase_price_cents_per_kwh"] = purchase_price(ppa)
    ppa["availability_penalty_cents_per_kwh"] = availability_penalty_rate(site)
    ppa["effective_fuel_adder_cents_per_therm"] = effective_fuel_adder(ppa)
    ppa["contract_index_ceiling_cents_per_therm"] = contract_index_ceiling(site)
    ppa["index_basis_cents_per_therm"] = index_basis(site)
    ppa["annual_customer_cost_cents"] = r2(
        D(ppa.get("contracted_annual_kwh") or 0) * D(ppa.get("effective_tariff_cents_per_kwh") or 0))
    settled_kwh = sum(float(ln.get("metered_kwh") or 0) for ln in store.ppa_lines(ppa["id"])
                      if ln.get("status") == "SETTLEMENT_APPLIED")
    ppa["lifetime_settled_kwh"] = round(settled_kwh, 2)
    replayed = sum(int(a.get("signed_amount_cents") or 0) for a in store.ppa_accruals(ppa["id"])
                   if a.get("lifecycle_state") == "ACCRUAL_RECONCILED")
    applied = sum(int(ln.get("net_charge_cents") or 0) for ln in store.ppa_lines(ppa["id"])
                  if ln.get("status") == "SETTLEMENT_APPLIED")
    ppa["lifetime_settled_cents"] = applied + replayed
    ppa["committed_kwh_remaining"] = round(
        float(ppa.get("term_years") or 0) * float(ppa.get("contracted_annual_kwh") or 0) - settled_kwh, 2)
    applied_lines = [ln for ln in store.by_created(store.ppa_lines(ppa["id"]))
                     if ln.get("status") == "SETTLEMENT_APPLIED"]
    ppa["realized_guarantee_credit_cents"] = int(applied_lines[-1].get("output_guarantee_credit_cents") or 0) \
        if applied_lines else 0
    ppa["output_guarantee_reserve_cents"] = output_guarantee_reserve(ppa)
    ppa["capacity_guarantee_reserve_cents"] = capacity_guarantee_reserve(ppa)
    ppa["capacity_reserve_credits_cents"] = capacity_reserve_credits(ppa)
    ppa["loss_floor_cents"] = int(ppa.get("loss_floor_cents") or 0)
    ppa["exit_fee_cents"] = r2(site_exit_capacity(site)
                               * D(site.get("interconnect_exit_fee_cents_per_kw") or 0))
    return ppa


def site_contracted_capacity(site):
    """Sum of contracted_kw over the site's draft, active and suspended PPAs."""
    return sum(int(p.get("contracted_kw") or 0) for p in store.site_ppas(site["id"])
               if p.get("state") in ("PPA_DRAFT", "PPA_ACTIVE", "PPA_SUSPENDED"))


def site_exit_capacity(site):
    """Sum of contracted_kw over every contract at the site.

    The exit-fee basis counts capacity once per contract and keeps counting it
    after a contract leaves the draft/active/suspended set: a terminated
    contract leaves its equipment behind (PRD 3.8).
    """
    return sum(int(p.get("contracted_kw") or 0) for p in store.site_ppas(site["id"]))


def committed_feedstock_therms(site):
    total = Decimal(0)
    for ppa in store.site_ppas(site["id"]):
        if ppa.get("state") not in ("PPA_DRAFT", "PPA_ACTIVE", "PPA_SUSPENDED"):
            continue
        efficiency = D(ppa.get("contracted_efficiency_kwh_per_therm") or 0)
        if efficiency <= 0:
            continue
        total += (D(ppa.get("term_years") or 0) * 365 * D(ppa.get("contracted_kwh") or 0)) / efficiency
    return float(total)


def contracted_purchase_cents(site):
    total = 0
    for ppa in store.site_ppas(site["id"]):
        if ppa.get("state") not in ("PPA_DRAFT", "PPA_ACTIVE", "PPA_SUSPENDED"):
            continue
        total += r2(D(ppa.get("purchase_price_cents_per_kwh") or 0) * D(ppa.get("contracted_kw") or 0))
    return total


def site_clearance_used(site):
    total = Decimal(0)
    for plan in store.site_plans(site["id"]):
        if plan.get("lifecycle_state") in ("SERVICE_ACTIVE", "SERVICE_MAINTENANCE_WINDOW_OPEN"):
            total += D(plan.get("radius_buffer_m") or 0)
    return float(total)


def current_avoided_fuel_cost(site):
    confirmed = [d for d in store.site_deliveries(site["id"])
                 if d.get("lifecycle_state") in ("DELIVERY_CONFIRMED", "DELIVERY_SETTLED")]
    if not confirmed:
        return 0.0
    latest = store.by_created(confirmed)[-1]
    ceiling = D(site.get("gas_commodity_rate_cents_per_therm") or 0) * D(C.SOURCED_INDEX_CEILING_MULTIPLE)
    return r4f(min(D(latest.get("effective_commodity_rate_cents_per_therm") or 0), ceiling))


def recompute_site(site):
    site["active_ppa_count"] = sum(1 for p in store.site_ppas(site["id"])
                                   if p.get("state") in ("PPA_ACTIVE", "PPA_SUSPENDED"))
    site["total_contracted_kw"] = site_contracted_capacity(site)
    site["committed_feedstock_therms"] = round(committed_feedstock_therms(site), 4)
    site["contracted_purchase_cents"] = contracted_purchase_cents(site)
    site["clearance_zone_used"] = round(site_clearance_used(site), 4)
    site["current_avoided_fuel_cost_cents_per_therm"] = current_avoided_fuel_cost(site)
    applied = [ln for ln in store.settlement_lines.values()
               if ln.get("status") == "SETTLEMENT_APPLIED"
               and (store.get_ppa(ln["ppa_id"]) or {}).get("site_id") == site["id"]]
    site["lifetime_customer_billable_cents"] = sum(int(ln.get("net_charge_cents") or 0) for ln in applied)
    site["lifetime_availability_credit_cents"] = sum(int(ln.get("availability_credit_cents") or 0)
                                                     for ln in applied)
    site["lifetime_settled_kwh"] = round(sum(float(ln.get("metered_kwh") or 0) for ln in applied), 2)
    site["lifetime_settle_reconcile_count"] = sum(
        1 for a in store.accruals.values()
        if a.get("site_id") == site["id"] and a.get("lifecycle_state") == "ACCRUAL_RECONCILED")
    site["initial_fuel_inventory_therms"] = float(site.get("initial_fuel_inventory_therms") or 0)
    site["draw_position_therms"] = float(site.get("draw_position_therms") or 0)
    site["reserved_capacity_hold_count"] = int(site.get("reserved_capacity_hold_count") or 0)
    return site


def exposure_hold_pct(customer):
    tier = customer.get("credit_tier")
    if tier == "CREDIT_SUBSTANDARD":
        return 0.40
    if tier == "CREDIT_STANDARD":
        return 0.15
    return 0.0


def recompute_customer(customer):
    owned = store.customer_ppas(customer["id"])
    applied = [ln for ln in store.settlement_lines.values()
               if ln.get("status") == "SETTLEMENT_APPLIED"
               and (store.get_ppa(ln["ppa_id"]) or {}).get("customer_id") == customer["id"]]
    customer["outstanding_balance_cents"] = sum(int(ln.get("net_charge_cents") or 0) for ln in applied)
    settled = Decimal(0)
    for line in applied:
        ppa = store.get_ppa(line["ppa_id"]) or {}
        settled += D(line.get("metered_kwh") or 0) * D(ppa.get("effective_tariff_cents_per_kwh") or 0)
    customer["lifetime_settled_cents"] = r2(settled)
    guarantee = sum(int(ln.get("output_guarantee_credit_cents") or 0) for ln in applied)
    for accrual in store.accruals.values():
        if accrual.get("accrual_type") != "OUTPUT_GUARANTEE_ACCRUAL":
            continue
        ppa = store.get_ppa(accrual.get("ppa_id")) or {}
        if ppa.get("customer_id") == customer["id"] and accrual.get("applied_allowance_id"):
            guarantee += int(accrual.get("amount_cents") or 0)
    customer["lifetime_output_guarantee_credit_cents"] = guarantee
    customer["lifetime_availability_credit_cents"] = sum(int(ln.get("availability_credit_cents") or 0)
                                                         for ln in applied)
    customer["active_ppa_count"] = sum(1 for p in owned if p.get("state") in ("PPA_ACTIVE", "PPA_SUSPENDED"))
    customer["earned_customer_tokens"] = sum(
        int(p.get("customer_earned_ppa_tokens") or 0) + int(p.get("customer_earned_output_tokens") or 0)
        for p in owned)
    customer["spent_customer_tokens"] = sum(
        int(p.get("customer_spent_ppa_tokens") or 0) + int(p.get("customer_spent_output_tokens") or 0)
        for p in owned)
    customer["exposure_hold_pct"] = exposure_hold_pct(customer)
    open_accruals = sum(1 for a in store.accruals.values()
                        if a.get("lifecycle_state") == "ACCRUAL_OPEN"
                        and (store.get_ppa(a.get("ppa_id")) or {}).get("customer_id") == customer["id"])
    customer["reconcile_cadence_slots"] = customer["active_ppa_count"] - open_accruals
    customer["hold_armed"] = bool(customer.get("hold_armed"))
    return customer


def recompute_all(site=None, customer=None, ppa=None):
    if ppa is not None:
        recompute_ppa(ppa)
    if site is not None:
        recompute_site(site)
    if customer is not None:
        recompute_customer(customer)
