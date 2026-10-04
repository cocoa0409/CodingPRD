"""Every calculation rule from PRD section 3 (scaffold section 1.3).

Rounding discipline (PRD section 2.6): half-up is never used.  Each rounding
step is either a ceiling or a floor to a whole unit, and each rule below states
which one it uses.  All money is integer cents; no float ever touches a
monetary value.
"""

from datetime import timedelta

from store import store, clock, to_date, add_days, add_years

# --- constants (scaffold section 1.3 `constants`) ----------------------------
LINE_SURCHARGE_CENTS = 25000
LABOR_RATE_CENTS_PER_BUILD_HOUR = 45000
CHANGE_FEE_PER_ENDORSEMENT_CENTS = 15000
FEE_CAP_PCT_OF_UNROUNDED = 8
LOCK_HORIZON_DAYS = 120
FORECAST_WHEELSET_CASTING_UPLIFT_PCT = 110
FORECAST_COATING_UPLIFT_PCT = 104
FORECAST_COATING_LEAD_TIME_DAYS = 60

RETAINED_CAR_EQUITY_BPS = 700
EQUITY_BPS_CEILING = 900

UTILIZATION_CREDIT_PCT = 12
MILES_PER_UTILIZATION_POINT = 100

MILEAGE_OVERAGE_RATE_CENTS = 12
DAYS_PER_ALLOWANCE_BLOCK = 30

CONDITION_PARTS_CENTS = {"A": 0, "B": 200000, "C": 400000, "D": 600000}
LESSEE_PARTS_SHARE_PCT = 1
LESSEE_PARTS_SHARE_PCT_CEILING = 5

RETROFIT_ALLOWANCE_CENTS = 2500000
RETROFIT_SHOP_DAY_RATE_CENTS = 185000
DAILY_DEPRECIATION_CENTS = 2500

GATED_COMPONENT_CLASSES = ("WHEELSET", "CASTING")

LIVE_FLEET_STATES = ("HELD", "ASSIGNED", "UNDER_REPAIR")
OPEN_ASSIGNMENT_STATES = ("COMPLETED", "REASSIGNED")


def ceil_div(a, b):
    """Integer ceiling division for non-negative operands."""
    if b <= 0:
        return 0
    return -((-int(a)) // int(b))


def ceil_cents(numerator, denominator):
    return ceil_div(numerator, denominator)


def floor_cents(numerator, denominator):
    return int(numerator) // int(denominator)


# --- lookups -----------------------------------------------------------------
def car_type_of(car):
    return store.get("car_types", car.get("car_type_id"))


def component_of(row):
    return store.get("components", row.get("component_id"))


def bom_rows_for(car_type_id):
    rows = [r for r in store.all("bom_rows") if r["car_type_id"] == car_type_id]
    return store.sorted_rows(rows)


def endorsements_of_order(order_id, statuses=None):
    rows = [e for e in store.all("endorsements") if e["production_order_id"] == order_id]
    if statuses is not None:
        rows = [e for e in rows if e["status"] in statuses]
    return store.sorted_rows(rows)


def substitution_for_row(order_id, component_id):
    """The APPROVED/APPLIED endorsement standing in for this requirement row."""
    matches = [e for e in endorsements_of_order(order_id, ("APPROVED", "APPLIED"))
               if e["original_component_id"] == component_id]
    return matches[-1] if matches else None


def effective_qty(order, row):
    sub = substitution_for_row(order["id"], row["component_id"])
    if sub is not None:
        return int(sub["substitute_qty_per_car"])
    return int(row["qty_per_car"])


# --- order_price_quote -------------------------------------------------------
def _row_unit_cost(order, row, sub=None):
    """Committed basis cost, with the forecast variant's two uplift substitutions.

    When an APPROVED or APPLIED endorsement stands in for this row, PRD section
    3.3 requires the re-quote to be computed "with the endorsed substitute
    standing in for the original component", so the substitute's own cost is
    the one that prices the line.
    """
    comp = component_of(row)
    if sub is not None:
        substitute = store.get("components", sub["substitute_component_id"])
        if substitute is not None:
            comp = substitute
    cost = int(comp["unit_cost_cents"])
    if order["status"] != "DRAFT":
        return cost
    horizon = (clock.date - to_date(order["order_date"])).days
    if horizon > LOCK_HORIZON_DAYS and comp["component_class"] in GATED_COMPONENT_CLASSES:
        # locked contract price has lapsed
        return ceil_div(cost * FORECAST_WHEELSET_CASTING_UPLIFT_PCT, 100)
    if comp["component_class"] == "COATING" and int(comp["lead_time_days"]) > FORECAST_COATING_LEAD_TIME_DAYS:
        return ceil_div(cost * FORECAST_COATING_UPLIFT_PCT, 100)
    return cost


def order_price_quote(order):
    """unit_price_cents per PRD section 3.1.

    Per-line ceiling to the next whole dollar first, summation second, the cap
    and fee third, and no further rounding after the final addition.
    """
    rows = bom_rows_for(order["car_type_id"])
    # part_number ASC, tie-broken by the row's created_at ASC
    rows = sorted(rows, key=lambda r: (
        component_of(r)["part_number"] if component_of(r) else "",
        r.get("created_at", ""), r.get("_seq", 0)))

    subtotal = 0
    for row in rows:
        sub = substitution_for_row(order["id"], row["component_id"])
        qty = int(sub["substitute_qty_per_car"]) if sub is not None \
            else int(row["qty_per_car"])
        cost = _row_unit_cost(order, row, sub)
        line = ceil_div(qty * cost + LINE_SURCHARGE_CENTS, 100) * 100
        subtotal += line

    car_type = car_type_of(order)
    labor = int(car_type["build_hours"]) * LABOR_RATE_CENTS_PER_BUILD_HOUR if car_type else 0
    unrounded = subtotal + labor

    fee_cap = floor_cents(unrounded * FEE_CAP_PCT_OF_UNROUNDED, 100)
    raw_fee = CHANGE_FEE_PER_ENDORSEMENT_CENTS * len(
        endorsements_of_order(order["id"], ("APPROVED", "APPLIED")))
    change_fee = min(raw_fee, fee_cap)
    return unrounded + change_fee


# --- production_feasibility_gate --------------------------------------------
def production_feasibility_gate(order):
    """(feasible, worst_lead) over WHEELSET/CASTING rows only."""
    horizon = (to_date(order["required_delivery_date"]) - to_date(order["order_date"])).days
    worst = 0
    for row in bom_rows_for(order["car_type_id"]):
        comp = component_of(row)
        if comp is None or comp["component_class"] not in GATED_COMPONENT_CLASSES:
            continue
        lead = ceil_div(int(comp["lead_time_days"]), int(row["qty_per_car"]))
        worst = max(worst, lead)
    return horizon >= worst, worst


# --- component_allocation ----------------------------------------------------
def component_allocation(component):
    """reserved_qty = reservation term + retrofit term; shortfall derived from it.

    on_hand_qty is authoritative and read first; reserved_qty is re-derived from
    scratch, never incrementally patched.
    """
    on_hand = int(component["on_hand_qty"])

    reservations = 0
    for row in store.all("bom_rows"):
        if row["component_id"] != component["id"]:
            continue
        qty = sum(int(o["quantity"]) for o in store.all("production_orders")
                  if o["car_type_id"] == row["car_type_id"] and o["status"] == "RELEASED")
        reservations += int(row["qty_per_car"]) * qty

    retrofit_holds = 0
    for wo in store.all("retrofit_work_orders"):
        if wo["status"] != "IN_PROGRESS":
            continue
        program = store.get("retrofit_programs", wo["retrofit_program_id"])
        if program is not None and program.get("required_component_id") == component["id"]:
            retrofit_holds += int(wo["component_qty_consumed"])

    reserved = reservations + retrofit_holds
    shortfall = reserved - on_hand if reserved > on_hand else 0
    return reserved, shortfall


def recompute_component(component):
    reserved, shortfall = component_allocation(component)
    component["reserved_qty"] = reserved
    component["shortfall_qty"] = shortfall
    return component


def recompute_all_components():
    for comp in store.all("components"):
        recompute_component(comp)


# --- lease_fleet_capital_allocation -----------------------------------------
def retained_cars_for_order(order_id):
    return [c for c in store.all("fleet_cars")
            if c.get("production_order_id") == order_id and c["status"] in LIVE_FLEET_STATES]


def capital_allocation_for_order(order):
    """The capital figure written to the named contract's capital_allocation_cents.

    PRD section 3.4: "The capital figure is the size of that set multiplied by
    the order's unit_price_cents."  The lessor equity derived from that capital
    is a separate quantity that the API does not expose as a field.
    """
    return len(retained_cars_for_order(order["id"])) * int(order["unit_price_cents"])


# --- assignment_per_diem_accrual --------------------------------------------
def _lessee_of_contract(contract):
    return store.get("lessees", contract["lessee_id"]) if contract else None


def utilization_credit(assignment, gross):
    """The 12-percent credit, granted only at or above the lessee's threshold."""
    util_pct = int(assignment["mileage_used"]) // MILES_PER_UTILIZATION_POINT
    contract = store.get("lease_contracts", assignment.get("lease_contract_id"))
    lessee = _lessee_of_contract(contract)
    if lessee is not None and int(lessee["utilization_threshold_pct"]) <= util_pct:
        return floor_cents(gross * UTILIZATION_CREDIT_PCT, 100)
    return 0


def per_diem_accrued_open(assignment, end_override=None):
    """current_open variant: the window ends at end_date when closed, else now."""
    start = to_date(assignment["start_date"])
    if end_override is not None:
        end = to_date(end_override)
    elif assignment["status"] in OPEN_ASSIGNMENT_STATES:
        end = to_date(assignment["end_date"])
    else:
        end = clock.date
    days = (end - start).days
    if days < 0:
        days = 0
    gross = days * int(assignment["per_diem_rate_cents"])
    return gross - utilization_credit(assignment, gross)


def _clip(start, end, lo, hi):
    """Clip a half-open interval to [lo, hi); returns whole days, floored at 0."""
    s = max(start, lo)
    e = min(end, hi)
    return max(0, (e - s).days)


def per_diem_accrued_restated(assignment):
    """restated_chronological: walk the car's placements, clip, sum once."""
    car_id = assignment["lease_fleet_car_id"]
    siblings = store.sorted_rows(
        [a for a in store.all("car_assignments") if a["lease_fleet_car_id"] == car_id])
    contract = store.get("lease_contracts", assignment.get("lease_contract_id"))
    now = clock.date
    window_lo = now - timedelta(days=365)
    total_days = 0
    for a in siblings:
        start = to_date(a["start_date"])
        if a["status"] in OPEN_ASSIGNMENT_STATES:
            end = to_date(a["end_date"])
        else:
            end = now
        lo, hi = window_lo, now
        if contract is not None:
            lo = max(lo, to_date(contract["term_start_date"]))
            hi = min(hi, to_date(contract["term_end_date"]))
        total_days += _clip(start, end, lo, hi)
    gross = total_days * int(assignment["per_diem_rate_cents"])
    # PRD 3.6: "The placement's per_diem_accrued_cents is the gross accrual
    # minus the credit" -- the credit term applies to either basis.
    return gross - utilization_credit(assignment, gross)


def recompute_assignment_accrual(assignment, end_override=None, restated=False):
    if restated:
        assignment["per_diem_accrued_cents"] = per_diem_accrued_restated(assignment)
    else:
        assignment["per_diem_accrued_cents"] = per_diem_accrued_open(assignment, end_override)
    return assignment["per_diem_accrued_cents"]


# --- mileage_true_up_settlement ---------------------------------------------
def mileage_true_up(assignment):
    """Overage charge in cents; zero overage produces exactly zero."""
    days = (to_date(assignment["end_date"]) - to_date(assignment["start_date"])).days
    blocks = ceil_div(days, DAYS_PER_ALLOWANCE_BLOCK)
    included = blocks * int(assignment["mileage_allowance"])
    contract = store.get("lease_contracts", assignment.get("lease_contract_id"))
    if contract is not None and contract["lease_type"] == "NET":
        term_days = (to_date(contract["term_end_date"]) - to_date(contract["term_start_date"])).days
        if term_days < days:
            # term_trailing: allowance granted once for the whole term
            included = int(assignment["mileage_allowance"])
    overage = int(assignment["mileage_used"]) - included
    if overage < 0:
        overage = 0
    return overage * MILEAGE_OVERAGE_RATE_CENTS


# --- maintenance_burden_allocation ------------------------------------------
def maintenance_split(parts_cents, contract):
    """(lessor_share, lessee_share); the cap applies inside the min()."""
    total = int(parts_cents)
    if contract is not None and contract["liability_bearer"] == "LESSOR":
        lessor = total
    else:
        pct = min(LESSEE_PARTS_SHARE_PCT, LESSEE_PARTS_SHARE_PCT_CEILING)
        lessor = floor_cents(total * pct, 100)
    return lessor, total - lessor


# --- sale_gain_loss ----------------------------------------------------------
def sale_book_value(car, sale_date):
    age_days = (to_date(sale_date) - to_date(car["built_date"])).days
    return int(car["acquisition_cost_cents"]) - age_days * DAILY_DEPRECIATION_CENTS


def sale_gain_loss(car, sale_price_cents, writeback_liability_cents, sale_date):
    """(net_book_value_cents, gain_loss_cents); no rounding step applies."""
    book = sale_book_value(car, sale_date)
    gain = int(sale_price_cents) - book - int(writeback_liability_cents)
    return book, gain


# --- fleet_capital_reconciliation -------------------------------------------
def disposal_proceeds_net():
    total = sum(int(s["sale_price_cents"]) for s in store.all("fleet_sales")
                if s["status"] == "SETTLED")
    return total if total > 0 else 0


def fleet_nbv_cents():
    total = 0
    for car in store.all("fleet_cars"):
        if car["status"] not in LIVE_FLEET_STATES:
            continue
        age_days = (clock.date - to_date(car["built_date"])).days
        value = int(car["acquisition_cost_cents"]) - age_days * DAILY_DEPRECIATION_CENTS
        if value < 0:
            value = 0
        total += value
    return total  # each car already floored; the sum is a whole number of cents


def oldest_basis_cents():
    return int(store.ledger["committed_capital_cents"]) - disposal_proceeds_net()


def drift_cents():
    return oldest_basis_cents() - fleet_nbv_cents()


def recompute_ledger_nbv():
    store.ledger["fleet_nbv_cents"] = fleet_nbv_cents()
    return store.ledger["fleet_nbv_cents"]


# --- retrofit_program_cost_allocation ---------------------------------------
def program_cost(program):
    """scheduled_estimate while PLANNED/IN_PROGRESS, completed_actual once COMPLETED."""
    if program["status"] == "COMPLETED":
        counted = ("COMPLETED",)
    else:
        counted = ("SCHEDULED", "IN_PROGRESS", "COMPLETED")
    required = store.get("components", program.get("required_component_id"))
    unit_cost = int(required["unit_cost_cents"]) if required is not None else 0
    total = 0
    for wo in store.all("retrofit_work_orders"):
        if wo["retrofit_program_id"] != program["id"] or wo["status"] not in counted:
            continue
        total += int(wo["shop_days"]) * RETROFIT_SHOP_DAY_RATE_CENTS
        if required is not None:
            total += int(wo["component_qty_consumed"]) * unit_cost
    return total


def recompute_program_cost(program):
    program["program_cost_cents"] = program_cost(program)
    return program["program_cost_cents"]


# --- lessee_balance_reconciliation ------------------------------------------
def order_lessee_id(order):
    """The lessee an order is written for: the named one, else its contract's."""
    if order.get("lessee_id"):
        return order["lessee_id"]
    contract = store.get("lease_contracts", order.get("_lease_contract_id"))
    return contract["lessee_id"] if contract is not None else None


def lessee_components(lessee_id):
    """(settled_charges, credits_applied) for one lessee, from scratch."""
    charges = 0

    # settled returns of this lessee's placements
    for ret in store.all("car_returns"):
        if ret["settlement_status"] != "SETTLED":
            continue
        assignment = store.get("car_assignments", ret["car_assignment_id"])
        contract = store.get("lease_contracts", assignment["lease_contract_id"]) if assignment else None
        if contract is not None and contract["lessee_id"] == lessee_id:
            charges += int(ret["mileage_overage_cents"])

    # completed SOLD orders of this lessee
    for order in store.all("production_orders"):
        if order_lessee_id(order) == lessee_id and order["status"] == "COMPLETED" \
                and order["disposition"] == "SOLD":
            charges += int(order["unit_price_cents"]) * int(order["quantity"])

    # settled sales of this lessee's cars
    for sale in store.all("fleet_sales"):
        if sale["status"] == "SETTLED" and sale.get("lessee_id") == lessee_id:
            charges += int(sale["writeback_liability_cents"])

    credits = 0
    for order in store.all("production_orders"):
        if order["disposition"] != "RETAINED" or order_lessee_id(order) != lessee_id:
            continue
        retained = len([c for c in store.all("fleet_cars")
                        if c.get("production_order_id") == order["id"]])
        credits += int(order["unit_price_cents"]) * retained

    return charges, credits


def lessee_outstanding(lessee_id):
    charges, credits = lessee_components(lessee_id)
    outstanding = charges - credits
    return (outstanding if outstanding > 0 else 0), charges, credits


def recompute_lessee_balance(lessee):
    outstanding, _, _ = lessee_outstanding(lessee["id"])
    lessee["outstanding_balance_cents"] = outstanding
    return outstanding


# --- scrape_or_retrofit_decision --------------------------------------------
def scrape_or_retrofit_decision(car, program, work_order=None):
    """SCRAP / RETROFIT / RETAIN per PRD section 3.8 (life end test is inclusive)."""
    if clock.date > to_date(car["regulatory_life_end_date"]):
        return "SCRAP"
    required = store.get("components", program.get("required_component_id"))
    retrofit_cost = int(program["required_shop_days_per_car"]) * RETROFIT_SHOP_DAY_RATE_CENTS
    if required is not None and work_order is not None:
        retrofit_cost += int(required["unit_cost_cents"]) * int(work_order["component_qty_consumed"])
    if retrofit_cost > RETROFIT_ALLOWANCE_CENTS:
        return "SCRAP"
    if car.get("retrofit_required"):
        return "RETROFIT"
    return "RETAIN"


# --- regulatory life / car derived fields -----------------------------------
def regulatory_life_end(car):
    car_type = car_type_of(car)
    if car_type is None:
        return None
    return add_years(car["built_date"], car_type["regulatory_life_years"]).isoformat()


def car_is_enrolled(car):
    """True while a covering program is IN_PROGRESS with an unexpired deadline."""
    now = clock.date
    covered = {row["retrofit_program_id"] for row in store.all("program_car_types")
               if row["car_type_id"] == car["car_type_id"]}
    for pid in covered:
        program = store.get("retrofit_programs", pid)
        if program is None or program["status"] != "IN_PROGRESS":
            continue
        if to_date(program["compliance_deadline_date"]) >= now:
            return True
    return False


def recompute_car_derived(car):
    car["regulatory_life_end_date"] = regulatory_life_end(car)
    car["retrofit_required"] = car_is_enrolled(car)
    car["accumulated_mileage"] = sum(
        int(a["mileage_used"]) for a in store.all("car_assignments")
        if a["lease_fleet_car_id"] == car["id"])
    return car


def refresh_enrolled_flags():
    for car in store.all("fleet_cars"):
        car["retrofit_required"] = car_is_enrolled(car)
