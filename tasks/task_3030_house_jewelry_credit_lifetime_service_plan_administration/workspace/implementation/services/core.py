"""Entity builders, derived-field reconciliation and every calculation rule."""

from datetime import timedelta
from decimal import Decimal

from constants import (
    APPRAISAL_MULTIPLIER_DEFAULT, APPRAISAL_MULTIPLIER_UNREPAIRABLE,
    BREACH_COMPENSATION_PCT, DAYS_PER_YEAR,
    DEFERRAL_TIERS, FULL_BREACH_PCT, HIGH_BALANCE_THRESHOLD_CENTS, LAB_GROWN_FACTOR,
    MAJOR_BREACH_PCT, MATERIAL_RECOVERY_CENTS, MIN_BASE_PCT_HIGH, MIN_BASE_PCT_LOW,
    MIN_FLOOR_CENTS, MONTHS_PER_QUARTER, PARTIAL_BREACH_PCT, REMINDER_LEAD_DAYS,
    ROUTE_TABLE, RUSH_SHOP_CODE, STREAK_COMPONENT_CAP, TIER_BOUNDARY_HIGH_CENTS,
    TIER_BOUNDARY_MID_CENTS, TIER_FEE_PCT_HIGH, TIER_FEE_PCT_LOW, TIER_FEE_PCT_MID,
    TRADE_UP_BONUS_PCT, TRADE_UP_CREDIT_CAP_MULTIPLIER, TRADE_UP_CREDIT_PCT,
    UTIL_VIOLATION_BPS, UTIL_WATCH_BPS, WARRANTY_RESERVE_PCT, half_up,
)
from db import DB, NO_VERSION, days_between, iso, parse_dt
from response import ApiError, Err, not_found

# ---------------------------------------------------------------------------
# row primitives
# ---------------------------------------------------------------------------

def new_row(collection, **fields):
    now = DB.now()
    row = {"id": DB.new_id(), "created_at": iso(now)}
    if collection not in NO_VERSION:
        row["updated_at"] = iso(now)
        row["version"] = 1
    row.update(fields)
    DB.add(collection, row)
    return row


def touch(row):
    """A cascade mutates a parent exactly like a direct request does."""
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = iso(DB.now())
    return row


def fetch(collection, ident, label="resource"):
    row = DB.get(collection, ident)
    if row is None:
        raise not_found("The %s does not exist." % label)
    return row


def fetch_chain(pairs):
    """Resolve foreign keys left to right; the first miss is the error."""
    out = []
    for collection, ident, label in pairs:
        out.append(fetch(collection, ident, label))
    return out


def bundle_of(registration):
    return DB.get("bundles", registration.get("bundle_id"))


def regulation_for_state(state_code):
    for row in DB.all("regulations"):
        if row["state_code"] == state_code:
            return row
    return None


def store_of(store_id):
    return DB.get("stores", store_id)


def customer_plans(customer_id, statuses=None):
    out = []
    for plan in DB.all("promotional_plans"):
        if plan["customer_id"] != customer_id:
            continue
        if statuses is None or plan["plan_status"] in statuses:
            out.append(plan)
    return out


def ledger_entries_of(plan_id):
    rows = [e for e in DB.all("ledger") if e["plan_id"] == plan_id]
    rows.sort(key=lambda e: (e["recorded_at"], e["entry_sequence"]))
    return rows


def plan_ledger_delta(plan_id):
    plus = 0
    minus = 0
    for entry in DB.all("ledger"):
        if entry["plan_id"] != plan_id:
            continue
        if entry["direction"] == "INCREASE":
            plus += entry["amount_cents"]
        else:
            minus += entry["amount_cents"]
    return plus, minus


def has_defaulted_plan(customer_id):
    return bool(customer_plans(customer_id, {"DEFAULTED"}))


# ---------------------------------------------------------------------------
# promo_interest_accrual / payoff_ledger_projection
# ---------------------------------------------------------------------------

def promo_interest_accrual(plan):
    """Forward-looking accrual: only ACCRUING plans accrue (PROVISIONAL_ACCRUING)."""
    if plan["plan_status"] != "ACCRUING":
        return 0
    start = parse_dt(plan.get("created_at"))
    if start is None:
        return 0
    elapsed = days_between(DB.now(), start)
    if elapsed < 0:
        elapsed = 0
    raw = (Decimal(plan["principal_cents"]) * Decimal(str(plan["promotional_apr_pct"]))
           / Decimal(100) * Decimal(elapsed) / Decimal(DAYS_PER_YEAR))
    return half_up(raw)


def final_settlement(plan):
    """principal + deferred interest while ACCRUING; principal once CAPITALIZED."""
    if plan["plan_status"] == "CAPITALIZED":
        return plan["principal_cents"]
    if plan["plan_status"] == "ACCRUING":
        return plan["principal_cents"] + promo_interest_accrual(plan)
    return 0


def recompute_plan_derived(plan):
    plan["deferred_interest_accrued_cents"] = promo_interest_accrual(plan)
    plan["final_settlement_amount_cents"] = final_settlement(plan)
    return plan


def append_ledger_entry(plan, kind, direction, amount, adjustment, reference_bucket=None):
    """Append one immutable ledger row, taking the next per-plan sequence."""
    sequence = 0
    for entry in DB.all("ledger"):
        if entry["plan_id"] == plan["id"]:
            sequence = max(sequence, entry["entry_sequence"])
    row = new_row(
        "ledger",
        plan_id=plan["id"],
        entry_kind=kind,
        adjustment_cents=adjustment,
        amount_cents=amount,
        reference_bucket=reference_bucket,
        direction=direction,
        entry_sequence=sequence + 1,
        projected_total_cents=0,
        recorded_at=iso(DB.now()),
    )
    row["projected_total_cents"] = payoff_ledger_projection(plan)
    return row


def payoff_ledger_projection(plan):
    """Base reading plus the PROMOTIONAL reference-bucket reading.

    The base reading is artifact-independent: every decrease lowers it.  The
    reference reading only lets entries that reference the PROMOTIONAL bucket
    move the figure -- a payment booked to CUSTOM_DESIGN or RETAIL leaves the
    promotional payoff figure untouched (§3.2 worked reference).
    """
    entries = ledger_entries_of(plan["id"])
    plus, minus = plan_ledger_delta(plan["id"])
    base_total = plan["principal_cents"] + promo_interest_accrual(plan) + plus - minus
    binding = [e for e in entries if e.get("reference_bucket") == "PROMOTIONAL"]
    if not binding:
        return base_total
    bound_decreases = sum(e["amount_cents"] for e in binding if e["direction"] == "DECREASE")
    return plan["principal_cents"] + promo_interest_accrual(plan) + plus - bound_decreases


# ---------------------------------------------------------------------------
# customer credit posture
# ---------------------------------------------------------------------------

def outstanding_balance(customer):
    plans = customer_plans(customer["id"])
    plan_ids = {plan["id"] for plan in plans}
    total = 0
    for entry in DB.all("ledger"):
        if entry["plan_id"] in plan_ids:
            total += entry["adjustment_cents"]
    for plan in plans:
        if plan["plan_status"] != "PAID":
            total += plan["installment_amount_cents"]
    return total


def revolving_utilization_bps(customer):
    limit = customer.get("standalone_credit_limit_cents") or 0
    balance = customer.get("outstanding_balance_cents") or 0
    if limit <= 0:
        return 0
    return half_up(Decimal(balance) * Decimal(10000) / Decimal(limit))


def credit_tier_from_plan_mix_and_inspection_streak(customer):
    active = len(customer_plans(customer["id"], {"ACCRUING"}))
    defaulted = len(customer_plans(customer["id"], {"DEFAULTED"}))
    util = revolving_utilization_bps(customer)
    if util >= UTIL_VIOLATION_BPS:
        band = 2
    elif util >= UTIL_WATCH_BPS:
        band = 1
    else:
        band = 0
    streak = min(STREAK_COMPONENT_CAP, customer.get("lost_inspection_streak") or 0)
    raw = 2 * band + active + streak
    if defaulted > 0:
        return "NO_FILE"
    if raw >= 3:
        return "TIER_1"
    if raw == 2:
        return "TIER_2"
    return "TIER_3"


def recompute_customer(customer, tier=True):
    customer["lifetime_purchase_cents"] = sum(
        p["base_price_cents"] for p in DB.all("purchases")
        if p["customer_id"] == customer["id"]
        and p["purchase_status"] in ("COMPLETED", "TRADE_UP_APPLIED"))
    customer["outstanding_balance_cents"] = outstanding_balance(customer)
    customer["revolving_utilization_bps"] = revolving_utilization_bps(customer)
    if tier:
        customer["credit_tier"] = credit_tier_from_plan_mix_and_inspection_streak(customer)
    return customer


def recompute_tier(customer):
    """The tier-only recomputation a cascade's final hop runs.

    The utilization figure a hop has just pinned (the suspend pin of 10000) is
    not disturbed by re-running the tier rule on its own.
    """
    customer["credit_tier"] = credit_tier_from_plan_mix_and_inspection_streak(customer)
    return customer


def latest_approved_application(customer_id):
    matches = [a for a in DB.all("credit_applications")
               if a["customer_id"] == customer_id and a["decision_status"] == "APPROVED"]
    if not matches:
        return None
    matches.sort(key=lambda a: (a["created_at"], a["id"]))
    return matches[-1]


def registry_limit_for_customer(customer):
    application = latest_approved_application(customer["id"])
    if application is None or not application.get("decision_rule_id"):
        return 0
    row = DB.get("registry", application["decision_rule_id"])
    return row["base_limit_cents"] if row else 0


# ---------------------------------------------------------------------------
# store reconciliation
# ---------------------------------------------------------------------------

OPEN_LIABILITY_STATES = ("INTAKE", "ROUTED", "IN_REPAIR", "QC_REVIEW")
ABSORBED_STATES = ("INTAKE", "ROUTED", "IN_REPAIR", "QC_REVIEW", "COMPLETED")
OPEN_INSPECTION_STATES = ("PENDING_INSPECTION", "REMINDER_ISSUED")
CLOSE_BLOCKING_REPAIR_STATES = ("INTAKE", "ROUTED", "IN_REPAIR", "QC_REVIEW", "COMPLETED")
CLOSE_BLOCKING_REGISTRATION_STATES = ("PENDING_INSPECTION", "REMINDER_ISSUED",
                                      "GRACE_PERIOD", "RENEWED")


def recompute_store(store):
    repairs = [r for r in DB.all("repairs") if r["store_id"] == store["id"]]
    store["open_repair_liability_cents"] = sum(
        r["loss_liability_cents"] for r in repairs
        if r["repair_status"] in OPEN_LIABILITY_STATES)
    store["store_absorbed_total_cents"] = sum(
        r["store_absorbed_cents"] for r in repairs
        if r["repair_status"] in ABSORBED_STATES)
    registrations = [g for g in DB.all("registrations") if g["store_id"] == store["id"]]
    store["open_inspection_count"] = sum(
        1 for g in registrations if g["coverage_status"] in OPEN_INSPECTION_STATES)

    balances = 0
    touched_customers = {r["customer_id"] for r in repairs}
    for purchase in DB.all("purchases"):
        if purchase["store_id"] == store["id"]:
            touched_customers.add(purchase["customer_id"])
    for customer_id in touched_customers:
        customer = DB.get("customers", customer_id)
        if customer is None:
            continue
        customer["outstanding_balance_cents"] = outstanding_balance(customer)
        balances += max(0, customer["outstanding_balance_cents"])

    available = ((store.get("credit_capacity_cents") or 0)
                 - store["store_absorbed_total_cents"] - balances)
    store["available_credit_capacity_cents"] = max(0, available)
    return store


def recompute_stores_of_customer(customer_id):
    store_ids = {p["store_id"] for p in DB.all("purchases")
                 if p["customer_id"] == customer_id}
    for store_id in store_ids:
        store = DB.get("stores", store_id)
        if store is not None:
            recompute_store(store)


def recompute_vendor_shop(shop_code):
    for shop in DB.all("vendor_shops"):
        if shop["shop_code"] == shop_code:
            shop["open_repair_count"] = sum(
                1 for r in DB.all("repairs")
                if r.get("vendor_shop_code") == shop_code
                and r["repair_status"] in ("ROUTED", "IN_REPAIR", "QC_REVIEW"))
            return shop
    return None


# ---------------------------------------------------------------------------
# credit_limit_registry_pricing
# ---------------------------------------------------------------------------

def policy_tier_for(requested_limit_cents, declared_annual_income_cents):
    if requested_limit_cents >= 1000000:
        tier = "TIER_3"
    elif requested_limit_cents >= 500000:
        tier = "TIER_2"
    else:
        tier = "TIER_1"
    if declared_annual_income_cents is not None and declared_annual_income_cents < 2500000:
        tier = "TIER_1"
    return tier


def select_registry_row(state_code, tier, requested_limit_cents):
    candidates = [row for row in DB.all("registry")
                  if row["credit_tier"] == tier
                  and row["min_ticket_cents"] <= requested_limit_cents]
    state_rows = [row for row in candidates if row["registry_key"] == state_code]
    pool = state_rows or [row for row in candidates
                          if row["registry_key"] == row["all_states_key"]]
    if not pool:
        return None
    pool.sort(key=lambda r: (r["min_ticket_cents"], r["created_at"]))
    return pool[-1]


# ---------------------------------------------------------------------------
# promo_plan_tiering
# ---------------------------------------------------------------------------

def plan_terms_for(plan_code):
    if plan_code == "PROMO_12_6M":
        return 26.99, 6, 12, 1200
    if plan_code == "PROMO_18_6M":
        return 27.99, 6, 18, 1500
    return 28.99, 12, 24, 1600


def marginal_deferral_bps(simplicity_months):
    """The fee is built tier by tier; inside one code tier this is its headline rate."""
    bps = DEFERRAL_TIERS[0][1]
    for boundary, rate in DEFERRAL_TIERS:
        if simplicity_months >= boundary:
            bps = rate
    return bps


def merchant_deferral_fee(principal_cents, simplicity_months):
    bps = marginal_deferral_bps(simplicity_months)
    return half_up(Decimal(principal_cents) * Decimal(bps) / Decimal(10000))


def purchase_protection_fee(purchase):
    bundle_id = purchase.get("bundle_id")
    if not bundle_id:
        return 0
    bundle = DB.get("bundles", bundle_id)
    return bundle["lifetime_plan_fee_cents"] if bundle else 0


def installment_quarter(principal_cents, simplicity_months):
    quarters = simplicity_months // MONTHS_PER_QUARTER
    if quarters <= 0:
        return principal_cents
    return half_up(Decimal(principal_cents) / Decimal(quarters))


# ---------------------------------------------------------------------------
# repair_loss_liability
# ---------------------------------------------------------------------------

def repair_liability(declared_parts_cents, declared_labor_cents,
                     declared_loss_liability_cents, bundle, plan_is_valid):
    """NET_RESERVE posture: the reserve is taken on parts before the limit."""
    limit_labor = bundle["stone_limit_labor_cents"]
    limit_parts = bundle["stone_limit_parts_cents"]
    reserve = half_up(Decimal(declared_parts_cents) * Decimal(str(WARRANTY_RESERVE_PCT)))
    covered = declared_parts_cents - reserve
    insurance_labor = min(declared_labor_cents, max(0, limit_labor - covered))
    liability = (max(0, covered + declared_labor_cents - limit_labor)
                 + reserve + declared_loss_liability_cents)
    insurance_parts = min(covered, limit_parts)
    customer_parts = declared_parts_cents - insurance_parts
    customer_labor = max(0, declared_labor_cents - insurance_labor)
    if not plan_is_valid:
        customer_parts += insurance_parts
        insurance_parts = 0
    return {
        "reserve_cents": reserve,
        "loss_liability_cents": liability,
        "store_absorbed_cents": liability,
        "insurance_parts_cents": insurance_parts,
        "customer_parts_cents": customer_parts,
        "customer_labor_cents": customer_labor,
    }


# ---------------------------------------------------------------------------
# vendor_routing_and_turnaround / turnaround_breach_compensation
# ---------------------------------------------------------------------------

def vendor_routing_rule(failure_class, vendor_is_rush):
    return RUSH_SHOP_CODE if vendor_is_rush else ROUTE_TABLE[failure_class]


def vendor_shop_by_code(shop_code):
    for shop in DB.all("vendor_shops"):
        if shop["shop_code"] == shop_code:
            return shop
    return None


def turnaround_days_for(shop_code):
    shop = vendor_shop_by_code(shop_code)
    return shop["base_turnaround_days"] if shop else 0


def applied_extension_days(repair_id):
    return sum(h["extension_days"] for h in DB.all("holds")
               if h["repair_id"] == repair_id and h["deadline_adjusted"])


def promised_delivery_instant(repair):
    """QUOTED when no hold applied, ADJUSTED once one has been."""
    accepted = parse_dt(repair.get("accepted_at"))
    if accepted is None:
        return None
    base = turnaround_days_for(repair.get("vendor_shop_code"))
    return accepted + timedelta(days=base + applied_extension_days(repair["id"]))


def breach_compensation(repair, store, delivered_at=None):
    promised = parse_dt(repair.get("promised_delivery_at"))
    if promised is None:
        return 0
    instant = delivered_at or DB.now()
    overdue = max(0, days_between(instant, promised))
    if overdue < 1:
        cents = 0
    elif overdue <= 5:
        cents = half_up(Decimal(repair["loss_liability_cents"]) * Decimal(str(PARTIAL_BREACH_PCT)))
    elif overdue <= 15:
        cents = half_up(Decimal(repair["loss_liability_cents"]) * Decimal(str(MAJOR_BREACH_PCT)))
    else:
        cents = half_up(Decimal(repair["loss_liability_cents"]) * Decimal(str(FULL_BREACH_PCT)))
    recompute_store(store)
    return min(cents, store["available_credit_capacity_cents"])


def imposed_breach_adjustment(repair):
    return half_up(Decimal(repair["loss_liability_cents"])
                   * Decimal(str(BREACH_COMPENSATION_PCT)))


# ---------------------------------------------------------------------------
# trade_up_credit_basis / balance_due_after_trade_up
# ---------------------------------------------------------------------------

def trade_up_credit_basis(origin):
    """SINGLE_ROUND over credited_base (the authoritative reading)."""
    bonus = half_up(Decimal(origin.get("trade_up_credit_cents") or 0)
                    * Decimal(str(TRADE_UP_BONUS_PCT)))
    credited_base = origin["base_price_cents"] + bonus
    return half_up(Decimal(credited_base) * Decimal(str(TRADE_UP_CREDIT_PCT)))


def trade_up_floor(origin):
    return TRADE_UP_CREDIT_CAP_MULTIPLIER * origin["base_price_cents"]


def resolve_origin(purchase):
    origin_id = purchase.get("origin_purchase_id")
    if not origin_id:
        return None
    return DB.get("purchases", origin_id)


def balance_due_after_trade_up(purchase, origin):
    if origin is not None:
        credit = min(trade_up_credit_basis(origin), trade_up_floor(origin))
    else:
        credit = 0
    net = max(0, purchase["base_price_cents"] - credit)
    fee = purchase_protection_fee(purchase)
    return credit, net, fee, net + fee


def recompute_purchase_amounts(purchase, internal_credit=None):
    """The ticket's derived figures.  Without an origin no credit is applied.

    `internal_credit` carries the credit a declared cascade assigns directly
    (the replacement purchase opened when a repair is verified); a client
    supplied trade_up_credit_cents is never honoured.
    """
    origin = resolve_origin(purchase)
    credit, net, fee, _due = balance_due_after_trade_up(purchase, origin)
    if origin is None and internal_credit is not None:
        credit = internal_credit
        net = max(0, purchase["base_price_cents"] - credit)
    purchase["trade_up_credit_cents"] = credit
    purchase["trade_up_floor_cents"] = trade_up_floor(origin) if origin is not None else 0
    purchase["net_amount_cents"] = net
    purchase["protection_fee_cents"] = fee
    return purchase


# ---------------------------------------------------------------------------
# replacement_appraised_value / replacement_appraisal_valuation
# ---------------------------------------------------------------------------

def replacement_appraised_value(repair, diamond):
    base = repair["customer_parts_cents"] + repair["customer_labor_cents"]
    if repair["repair_status"] == "UNREPAIRABLE":
        value = half_up(Decimal(base) * Decimal(str(APPRAISAL_MULTIPLIER_UNREPAIRABLE)))
    else:
        value = half_up(Decimal(base) * Decimal(str(APPRAISAL_MULTIPLIER_DEFAULT)))
    if diamond is not None and diamond["stone_kind"] == "LAB_GROWN":
        value = half_up(Decimal(value) * Decimal(str(LAB_GROWN_FACTOR)))
    return value


def issue_appraisal(repair, customer_id, appraisal_kind, insurance_schedule_ref=None):
    diamond = DB.get("diamonds", repair["diamond_id"])
    appraisal = new_row(
        "appraisals",
        repair_id=repair["id"],
        customer_id=customer_id,
        appraised_value_cents=replacement_appraised_value(repair, diamond),
        traceability_document_url=(diamond.get("origin_registry") if diamond else None),
        appraisal_kind=appraisal_kind,
        insurance_schedule_ref=insurance_schedule_ref,
        appraisal_status="ISSUED",
        circulated_at=iso(DB.now()),
    )
    if appraisal_kind == "REPLACEMENT":
        for other in DB.all("appraisals"):
            if (other["id"] != appraisal["id"] and other["repair_id"] == repair["id"]
                    and other["appraisal_kind"] == "REPLACEMENT"
                    and other["appraisal_status"] != "SUPERSEDED"):
                other["appraisal_status"] = "SUPERSEDED"
                touch(other)
        repair["stored_appraisal_id"] = appraisal["id"]
    return appraisal


# ---------------------------------------------------------------------------
# inspection_reminder_scheduling
# ---------------------------------------------------------------------------

def inspection_interval(registration):
    bundle = bundle_of(registration)
    return bundle["inspection_interval_days"] if bundle else 180


def cure_days(registration):
    store = store_of(registration["store_id"])
    regulation = regulation_for_state(store["state_code"]) if store else None
    if regulation is not None:
        return regulation["lapse_cure_days"]
    bundle = bundle_of(registration)
    return bundle["inspection_cure_days"] if bundle else 30


def schedule_registration(registration, base_instant):
    interval = inspection_interval(registration)
    due = base_instant + timedelta(days=interval)
    registration["registered_at"] = iso(base_instant)
    registration["inspection_due_at"] = iso(due)
    registration["cure_expires_at"] = iso(base_instant + timedelta(days=interval + cure_days(registration)))
    return registration


def reminder_due(registration):
    """Whole elapsed days against the first-cycle reminder window."""
    start = parse_dt(registration.get("registered_at"))
    if start is None:
        return False
    elapsed = days_between(DB.now(), start)
    interval = inspection_interval(registration)
    if elapsed < interval - REMINDER_LEAD_DAYS:
        return False
    if elapsed < interval:
        return True
    return elapsed <= interval + cure_days(registration)


# ---------------------------------------------------------------------------
# custom_design_deposit_and_forfeit
# ---------------------------------------------------------------------------

def design_deposit(estimate_amount_cents, deposit_pct):
    return half_up(Decimal(estimate_amount_cents) * Decimal(str(deposit_pct)))


def non_refundable_for(design, status):
    if status in ("COMPLETED", "IN_PRODUCTION", "CANCELLED"):
        return design["deposit_cents"]
    return 0


def cancellation_fee_for(design, status_before_cancel):
    """Once the design has been cancelled out of IN_PRODUCTION the fee is the
    greater of the two candidates: the costs incurred once three revisions have
    been taken, and the whole deposit otherwise.  The fee is not capped at the
    deposit -- any excess is billed to the customer as a balance due."""
    if status_before_cancel != "IN_PRODUCTION":
        return 0
    if design["revision_count"] >= 3:
        return design["deposit_cents"] + design["revision_fee_cents"] - MATERIAL_RECOVERY_CENTS
    return design["deposit_cents"]


def design_derived(design):
    """Refresh the deposit split for the design's current status."""
    non_refundable = non_refundable_for(design, design["design_status"])
    design["non_refundable_deposit_cents"] = non_refundable
    design["refundable_deposit_cents"] = design["deposit_cents"] - non_refundable
    if design["design_status"] != "CANCELLED":
        design["cancellation_fee_cents"] = 0
    return design


# ---------------------------------------------------------------------------
# statement_balance_rollup / payment_allocation_waterfall
# ---------------------------------------------------------------------------

def statement_rollup(lines):
    """SUM_THEN_TIER: one rounding over the aggregate, tier selected on it."""
    subtotal = 0
    for line in lines:
        if line.get("line_status") != "BILLABLE":
            continue
        subtotal += half_up(Decimal(line["amount_cents"]) * Decimal(str(line["billable_pct"])))
    if subtotal >= TIER_BOUNDARY_HIGH_CENTS:
        pct = TIER_FEE_PCT_HIGH
    elif subtotal >= TIER_BOUNDARY_MID_CENTS:
        pct = TIER_FEE_PCT_MID
    else:
        pct = TIER_FEE_PCT_LOW
    return half_up(Decimal(subtotal) * (Decimal(1) + Decimal(str(pct))))


def bucket_capacity(customer):
    """The bucket capacities available from the customer's own carried balances.

    No endpoint or entity declares a promotional/retail/new-account balance
    field, so the only balance the system actually carries is the customer's
    outstanding promotional obligation.
    """
    return {
        "PROMOTIONAL": sum(max(0, final_settlement(plan))
                           for plan in customer_plans(customer["id"])
                           if plan["plan_status"] != "PAID"),
        "STANDARD_RETAIL": 0,
        "NEW_ACCOUNT": 0,
    }


def payment_allocation_waterfall(customer, payment_cents):
    """PROMOTIONAL, then STANDARD_RETAIL, then NEW_ACCOUNT; the last absorbs."""
    capacity = bucket_capacity(customer)
    allocated = {"PROMOTIONAL": 0, "STANDARD_RETAIL": 0, "NEW_ACCOUNT": 0}
    remaining = payment_cents
    for bucket in ("PROMOTIONAL", "STANDARD_RETAIL", "NEW_ACCOUNT"):
        take = min(remaining, capacity[bucket])
        allocated[bucket] = take
        remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        raise ApiError(Err.STATEMENT_OVERPAYMENT)
    return allocated


def reported_bucket_totals(allocated):
    """The stored object is keyed by the three reported bucket labels."""
    return {
        "PROMOTIONAL": allocated.get("PROMOTIONAL", 0),
        "CUSTOM_DESIGN": allocated.get("CUSTOM_DESIGN", 0),
        "RETAIL": allocated.get("STANDARD_RETAIL", 0) + allocated.get("NEW_ACCOUNT", 0),
    }


def min_payment_due(allocated, capacity):
    total = 0
    for bucket, amount in allocated.items():
        if amount <= 0:
            continue
        band = MIN_BASE_PCT_HIGH if capacity.get(bucket, 0) >= HIGH_BALANCE_THRESHOLD_CENTS \
            else MIN_BASE_PCT_LOW
        total += half_up(Decimal(amount) * Decimal(str(band)))
    return max(MIN_FLOOR_CENTS, total)