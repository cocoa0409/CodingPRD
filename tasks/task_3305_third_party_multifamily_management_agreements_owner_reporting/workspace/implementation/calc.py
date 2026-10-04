"""Calculation engine per PRD §3 and SCAFFOLD §1.3. All money in whole cents,
round-half-up; pinned intermediate rounding points are normative."""

from decimal import Decimal, ROUND_HALF_UP

from db import db
from middleware import month_of, month_add

# Constants (PRD §3 + scaffold §1.3 + constants_note)
WEEKS_PER_MONTH = 4
REGIONAL_OVERHEAD_PCT = Decimal("0.20")
LOAD_PCT = Decimal("0.32")
PROPERTY_RESERVE_FLOOR_CENTS = 20000000
LENDER_ESCROW_HOLDBACK_CENTS = 15000000
TAIL_LOOKBACK_MONTHS = 6
MANAGER_INDEMNITY_CAP_CENTS = 100000000
SHARED_MANAGER_PCT = Decimal("0.25")
MAX_OVERRIDE_BAND_PCT = Decimal("0.10")


def round_half_up_cents(x):
    """Round a Decimal to whole cents (0 dp) using ROUND_HALF_UP; return int."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- Revenue ----

def basis_revenue_cents(prop, period_month, basis):
    """Sum of POSTED ledger RENT|FEE|RECOVERY minus CONCESSION for the month.

    CASH basis: collected_month == period_month.
    ACCRUAL basis: accrual_month == period_month (regardless of collection).
    """
    total = 0
    for e in db.ledger.values():
        if e["property_id"] != prop["id"] or e["status"] != "POSTED":
            continue
        if basis == "CASH":
            if e.get("collected_month") != period_month:
                continue
        else:  # ACCRUAL
            if e.get("accrual_month") != period_month:
                continue
        kind = e["kind"]
        if kind in ("RENT", "FEE", "RECOVERY"):
            total += e["amount_cents"]
        elif kind == "CONCESSION":
            total += e["amount_cents"]  # signed: credits negative reduce RENT revenue
        # EXPENSE and PAYROLL never enter revenue
    return total


# ---- Statement computations ----

def find_active_agreement(property_id):
    """Agreement for the property (any status), most recently created."""
    matches = [a for a in db.agreements.values() if a.get("property_id") == property_id]
    if not matches:
        return None
    matches.sort(key=lambda a: a["created_at"])
    return matches[-1]


def compute_statement_fields(stmt):
    """Compute collected_revenue/base/incentive/payroll for a statement dict.

    Returns dict of computed fields (not persisted by this function).
    """
    prop = db.properties[stmt["property_id"]]
    agreement = find_active_agreement(stmt["property_id"])
    revenue = basis_revenue_cents(prop, stmt["period_month"], stmt["basis"])

    base_fee = 0
    incentive_fee = 0
    if agreement is not None:
        pct_amt = Decimal(str(agreement["base_fee_pct"])) * Decimal(revenue)
        pct_amt_cents = round_half_up_cents(pct_amt)
        base_fee = max(agreement["minimum_monthly_fee_cents"], pct_amt_cents)
        if revenue > agreement["incentive_threshold_egi_cents"]:
            excess = revenue - agreement["incentive_threshold_egi_cents"]
            incentive_fee = round_half_up_cents(
                Decimal(str(agreement["incentive_tier1_rate"])) * Decimal(excess)
            )

    payroll = staffing_cost_allocation(stmt["property_id"])

    return {
        "collected_revenue_cents": revenue,
        "base_fee_cents": base_fee,
        "incentive_fee_cents": incentive_fee,
        "payroll_charge_cents": payroll,
        "management_fee_total_cents": base_fee + incentive_fee,
    }


def staffing_cost_allocation(property_id):
    """Payroll charge per §3.6 with two pinned rounding points.

    direct_total = sum(hours * 4 * hourly) over ACTIVE positions of the property.
    regional pool = same over all ACTIVE positions sharing the region code(s) of
      this property's positions.
    property_share = round(pool * 0.20 * (direct_total / region_direct_total))
    loaded = round((direct_total + property_share) * 0.32)
    payroll_charge = direct_total + property_share + loaded
    """
    positions = [
        p for p in db.staff.values()
        if p["property_id"] == property_id and p["status"] == "ACTIVE"
    ]
    direct_total = sum(
        p["scheduled_hours_per_week"] * WEEKS_PER_MONTH * p["hourly_cost_cents"]
        for p in positions
    )
    if not positions or direct_total == 0:
        return 0

    # Region codes used by this property's active positions
    region_codes = {p["shared_region_code"] for p in positions}
    region_positions = [
        p for p in db.staff.values()
        if p["status"] == "ACTIVE" and p["shared_region_code"] in region_codes
    ]
    region_direct_total = sum(
        p["scheduled_hours_per_week"] * WEEKS_PER_MONTH * p["hourly_cost_cents"]
        for p in region_positions
    )
    if region_direct_total == 0:
        return 0

    # First rounding point: regional allocation
    property_share = round_half_up_cents(
        Decimal(region_direct_total)
        * REGIONAL_OVERHEAD_PCT
        * (Decimal(direct_total) / Decimal(region_direct_total))
    )
    # Second rounding point: load
    loaded = round_half_up_cents(
        (Decimal(direct_total) + Decimal(property_share)) * LOAD_PCT
    )
    return direct_total + property_share + loaded


# ---- Cash position (PRD §2.9) ----

def cash_available_cents(prop):
    """Ledger-derived cash: credits (negative amounts of revenue kinds when
    collected) minus charges, minus fees/payroll paid, minus reserves held.

    Implementation: cash flows are recorded as EXPENSE (fees paid out,
    distributions) and PAYROLL; revenue counts toward cash only when
    collected_month is set. We track cash explicitly on the property dict.
    """
    return prop.get("cash_available_cents", 0)


def adjust_cash(prop, delta):
    prop["cash_available_cents"] = prop.get("cash_available_cents", 0) + delta


# ---- Fee tail (§3.7) ----

def fee_tail_cents(agreement):
    """Average of base_fee_cents over up to TAIL_LOOKBACK_MONTHS most recent
    CLOSED statements for the property (period_month desc), then
    round(avg * tail_rate_pct * tail_months)."""
    stmts = [
        s for s in db.statements.values()
        if s["property_id"] == agreement["property_id"] and s["status"] == "CLOSED"
    ]
    if not stmts:
        return 0
    stmts.sort(key=lambda s: s["period_month"], reverse=True)
    window = stmts[:TAIL_LOOKBACK_MONTHS]
    avg = round_half_up_cents(
        Decimal(sum(s["base_fee_cents"] for s in window)) / Decimal(len(window))
    )
    return round_half_up_cents(
        Decimal(avg)
        * Decimal(str(agreement["tail_rate_pct"]))
        * Decimal(agreement["tail_months"])
    )


# ---- Owner distribution waterfall (§3.8) ----

def owner_distribution_cents(prop, period_month):
    cash = cash_available_cents(prop)
    lender_due = any(
        r for r in db.reports.values()
        if r["property_id"] == prop["id"]
        and r["period_month"] == period_month
        and r["package_type"] == "LENDER"
    )
    lender_holdback = LENDER_ESCROW_HOLDBACK_CENTS if lender_due else 0
    claim_holds = sum(
        c["reserved_amount_cents"]
        for c in db.claims.values()
        if c["property_id"] == prop["id"] and c["status"] in ("OPEN", "UNDER_REVIEW")
    )
    dist = cash - PROPERTY_RESERVE_FLOOR_CENTS - lender_holdback - claim_holds
    return max(0, dist)


# ---- Annual NOI incentive (§3.6) ----

def annual_noi_incentive_cents(prop, fiscal_year):
    agreement = find_active_agreement(prop["id"])
    if agreement is None:
        return 0
    year_str = f"{fiscal_year:04d}"
    stmts = [
        s for s in db.statements.values()
        if s["property_id"] == prop["id"]
        and s["status"] == "CLOSED"
        and s["period_month"].startswith(year_str)
    ]
    if len(stmts) < 12:
        return 0

    # Majority basis
    cash_count = sum(1 for s in stmts if s["basis"] == "CASH")
    accrual_count = sum(1 for s in stmts if s["basis"] == "ACCRUAL")
    majority_basis = "CASH" if cash_count >= accrual_count else "ACCRUAL"
    revenue_sum = sum(
        s["collected_revenue_cents"] for s in stmts if s["basis"] == majority_basis
    )

    expense_sum = sum(
        e["amount_cents"]
        for e in db.ledger.values()
        if e["property_id"] == prop["id"]
        and e["status"] == "POSTED"
        and e["kind"] == "EXPENSE"
        and (e.get("accrual_month") or "").startswith(year_str)
    )
    actual_noi = revenue_sum - expense_sum

    budgets = [
        b for b in db.budgets.values()
        if b["property_id"] == prop["id"]
        and b["fiscal_year"] == fiscal_year
        and b["kind"] == "ANNUAL"
        and b["status"] == "APPROVED"
    ]
    if not budgets:
        return 0
    budget = sorted(budgets, key=lambda b: b["created_at"])[-1]
    budget_noi = budget["operating_revenue_cents"] - budget["operating_expense_cents"]

    hurdle_base = round_half_up_cents(
        Decimal(budget_noi) * (Decimal(1) + Decimal(str(agreement["noi_hurdle_pct"])))
    )
    if actual_noi > hurdle_base:
        return round_half_up_cents(
            Decimal(str(agreement["incentive_noi_share_pct"]))
            * Decimal(actual_noi - hurdle_base)
        )
    return 0


# ---- Claim settlement shares (§3.9) ----

def claim_settlement_shares(claim, amount_cents):
    if claim["indemnified_by"] == "MANAGER":
        manager = min(amount_cents, MANAGER_INDEMNITY_CAP_CENTS)
    elif claim["indemnified_by"] == "OWNER":
        manager = 0
    else:  # SHARED
        manager = round_half_up_cents(Decimal(amount_cents) * SHARED_MANAGER_PCT)
    owner = amount_cents - manager
    return manager, owner
