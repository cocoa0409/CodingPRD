"""Domain services: pricing, invoice lines, tax filing status, rule matching."""
from datetime import timedelta
import db
from helpers import round_half_up_int

TIER_CEILINGS = {"SILVER": 0.20, "GOLD": 0.35, "PLATINUM": 0.50}
TAX_RATES = {"US": 0.0, "UK": 0.20, "EU": 0.21}
PAYROLL_RATE_CARD = {
    "SELF_SERVICE": {"base_fee_cents": 4500, "per_employee_fee_cents": 600},
    "FULL_SERVICE": {"base_fee_cents": 8500, "per_employee_fee_cents": 1000},
}
LIST_LIMIT = 750000


def plan_for(sub):
    return db.TABLES["SubscriptionPlan"].get(sub["plan_id"])


def monthly_price_cents(sub):
    """Effective monthly price after wholesale discount when billed to a firm."""
    plan = plan_for(sub)
    if plan is None:
        return 0
    list_cents = plan["list_price_cents"]
    if sub.get("billing_owner") == "FIRM" and sub.get("billing_firm_id"):
        firm = db.TABLES["AccountantFirm"].get(sub["billing_firm_id"])
        if firm is not None:
            ceiling = TIER_CEILINGS.get(firm["proadvisor_tier"], 0)
            eff = min(firm["wholesale_discount_pct"], ceiling)
            return round_half_up_int(list_cents * (1 - eff))
    return list_cents


def payroll_active_employee_count(addon):
    n = 0
    for e in db.TABLES["PayrollEmployee"].values():
        if e["payroll_addon_id"] == addon["id"] and e["employment_status"] == "ACTIVE":
            n += 1
    return n


def payroll_provisional_cents(addon):
    """base_fee + n_active * per_employee (current-count provisional estimate)."""
    if addon is None or addon["addon_status"] != "ACTIVE":
        return 0
    return addon["base_fee_cents"] + payroll_active_employee_count(addon) * addon["per_employee_fee_cents"]


def payroll_per_employee_fee_for_period(addon, period_start, period_end):
    """Day-by-day proration with per-line rounding then sum. Half-open [start, end)."""
    if addon is None:
        return 0
    employees = [e for e in db.TABLES["PayrollEmployee"].values()
                 if e["payroll_addon_id"] == addon["id"]]
    total = 0
    day = period_start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = period_end
    while day < end:
        n = 0
        for e in employees:
            hire = db.parse_iso(e["hire_date"])
            term = db.parse_iso(e.get("terminated_at")) if e.get("terminated_at") else None
            if hire is not None and hire.date() <= day.date():
                if term is None or term.date() > day.date():
                    n += 1
        line = round_half_up_int(n * addon["per_employee_fee_cents"] / 30)
        total += line
        day = day + timedelta(days=1)
    return total


def tax_rate_for_company(company):
    return TAX_RATES.get(company.get("data_region"), 0.0)


def compute_invoice_lines(company, sub, period_start, period_end):
    """Returns dict of invoice line fields."""
    plan = plan_for(sub)
    list_cents = plan["list_price_cents"] if plan else 0
    billed_to = sub["billing_owner"]
    discount = 0
    if billed_to == "FIRM" and sub.get("billing_firm_id"):
        firm = db.TABLES["AccountantFirm"].get(sub["billing_firm_id"])
        if firm is not None and firm.get("firm_status") == "ACTIVE":
            ceiling = TIER_CEILINGS.get(firm["proadvisor_tier"], 0)
            eff = min(firm["wholesale_discount_pct"], ceiling)
            net = round_half_up_int(list_cents * (1 - eff))
            discount = list_cents - net
    addon = None
    for p in db.TABLES["PayrollAddon"].values():
        if p["subscription_id"] == sub["id"]:
            addon = p
            break
    payroll_base = 0
    payroll_per_emp = 0
    if addon is not None and addon["addon_status"] in ("ACTIVE", "PAUSED"):
        # active any day in period -> base fee (simple: include base fee)
        payroll_base = addon["base_fee_cents"]
        payroll_per_emp = payroll_per_employee_fee_for_period(addon, period_start, period_end)
    subtotal = list_cents - discount + payroll_base + payroll_per_emp
    rate = tax_rate_for_company(company)
    tax = round_half_up_int(subtotal * rate)
    total = subtotal + tax
    return {
        "billed_to": billed_to,
        "list_subscription_cents": list_cents,
        "wholesale_discount_cents": discount,
        "payroll_base_cents": payroll_base,
        "payroll_per_employee_cents": payroll_per_emp,
        "tax_cents": tax,
        "total_cents": total,
    }


def payroll_tax_filing_status(addon, company_id):
    """Derived status; evaluated in the pinned order from the PRD."""
    employees_active = any(
        e["payroll_addon_id"] == addon["id"] and e["employment_status"] == "ACTIVE"
        for e in db.TABLES["PayrollEmployee"].values())
    if not employees_active:
        return "NOT_READY"
    for c in db.TABLES["BankConnection"].values():
        if c["company_id"] == company_id and c["connection_status"] in ("STALE", "REVOKED"):
            return "NOT_READY"
    now = db.now()
    for r in db.TABLES["Reconciliation"].values():
        if r["company_id"] == company_id and r["recon_status"] == "IN_PROGRESS":
            end = db.parse_iso(r["statement_period_end"])
            if end is not None and (now - end).days > 45:
                return "PENALTY_RISK"
    # trailing 3 months all paid?
    invoices = [i for i in db.TABLES["Invoice"].values() if i["company_id"] == company_id]
    if invoices and all(i["invoice_status"] == "PAID" for i in invoices):
        return "FILED_CURRENT"
    return "READY"


def rule_matches(rule, txn):
    mf = rule["match_field"]
    mv = rule["match_value"]
    if mf == "PAYEE_CONTAINS":
        return str(mv).lower() in (txn.get("payee_raw") or "").lower()
    if mf == "AMOUNT_EQUALS":
        try:
            return int(mv) == txn["amount_cents"]
        except (TypeError, ValueError):
            return False
    if mf == "AMOUNT_GREATER_THAN":
        try:
            return txn["amount_cents"] > int(mv)
        except (TypeError, ValueError):
            return False
    return False


def select_winning_rule(company_id, txn):
    rules = [r for r in db.TABLES["CategorizationRule"].values()
             if r["company_id"] == company_id and r["rule_status"] == "ACTIVE"
             and rule_matches(r, txn)]
    if not rules:
        return None
    rules.sort(key=lambda r: (r["priority"], r["created_at"]))
    return rules[0]


def apply_rule_selector(company_id, txn):
    """Run the rule selector against a single UNCATEGORIZED txn, mutating it."""
    if txn["txn_status"] != "UNCATEGORIZED":
        return
    winner = select_winning_rule(company_id, txn)
    if winner is None:
        return
    txn["matched_rule_id"] = winner["id"]
    if winner.get("auto_apply", True):
        txn["txn_status"] = "CATEGORIZED"
        txn["category_id"] = winner["assign_category_id"]
    else:
        txn["txn_status"] = "RULE_SUGGESTED"


def reeval_uncategorized_txns(company_id):
    """When a rule is created/resumed, re-evaluate all UNCATEGORIZED txns."""
    for txn in db.TABLES["BankTransaction"].values():
        conn = db.TABLES["BankConnection"].get(txn["bank_connection_id"])
        if conn is None or conn["company_id"] != company_id:
            continue
        if txn["txn_status"] == "UNCATEGORIZED":
            apply_rule_selector(company_id, txn)


def recon_recompute(recon, projected=None):
    """Compute cleared_cents and difference_cents.
    projected=True -> include RULE_SUGGESTED as if accepted (DRAFT/IN_PROGRESS).
    projected=False -> only CATEGORIZED + MATCHED_RECONCILED (COMPLETED).
    Default None -> derive from current status."""
    if projected is None:
        projected = recon["recon_status"] in ("DRAFT", "IN_PROGRESS")
    start = db.parse_iso(recon["statement_period_start"])
    end = db.parse_iso(recon["statement_period_end"])
    cleared = 0
    statuses = ("CATEGORIZED", "MATCHED_RECONCILED", "RULE_SUGGESTED") if projected \
        else ("CATEGORIZED", "MATCHED_RECONCILED")
    for txn in db.TABLES["BankTransaction"].values():
        if txn["bank_connection_id"] != recon["bank_connection_id"]:
            continue
        if txn["txn_status"] not in statuses:
            continue
        posted = db.parse_iso(txn["posted_at"])
        if posted is None:
            continue
        if start.date() <= posted.date() <= end.date():
            cleared += txn["amount_cents"]
    recon["cleared_cents"] = cleared
    recon["difference_cents"] = (
        recon["statement_ending_balance_cents"]
        - (recon["beginning_balance_cents"] + cleared)
    )


def transfer_proforma(transfer):
    """Projected price under to_owner at BillingTransfer creation."""
    sub = db.TABLES["Subscription"].get(transfer["subscription_id"])
    if sub is None:
        return 0
    plan = plan_for(sub)
    list_cents = plan["list_price_cents"] if plan else 0
    firm = db.TABLES["AccountantFirm"].get(transfer["initiating_firm_id"])
    if transfer["to_owner"] == "FIRM" and firm is not None:
        ceiling = TIER_CEILINGS.get(firm["proadvisor_tier"], 0)
        eff = min(firm["wholesale_discount_pct"], ceiling)
        base = round_half_up_int(list_cents * (1 - eff))
    else:
        base = list_cents
    payroll = 0
    for p in db.TABLES["PayrollAddon"].values():
        if p["subscription_id"] == sub["id"] and p["addon_status"] == "ACTIVE":
            n = payroll_active_employee_count(p)
            payroll = p["base_fee_cents"] + n * p["per_employee_fee_cents"]
            break
    return base + payroll
