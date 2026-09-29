"""Every calculation, rollup and derived figure in the PRD.

Derived figures are computed on demand so that "a read therefore never serves a
figure that lags the underlying charges" (PRD 2.10).
"""
from decimal import Decimal

from db import db, now_iso, today, current_year
from money import ZERO2, ZERO4, d, q2, q4

# ---------------------------------------------------------------------------
# Pinned constants
# ---------------------------------------------------------------------------
# PRD 3.5 -- consultant markup
MARKUP_STANDARD = Decimal("0.1000")
MARKUP_TIER2 = Decimal("0.0600")
MARKUP_TIER2_THRESHOLD = Decimal("250000.00")
MARKUP_FIXED_FEE_BONUS = Decimal("0.0200")
MARKUP_PUBLIC_CAP = Decimal("0.0500")

# PRD 3.7 -- invoice volume discount
DISCOUNT_TIER1_THRESHOLD = Decimal("100000.00")
DISCOUNT_TIER1_PCT = Decimal("0.0100")
DISCOUNT_TIER2_THRESHOLD = Decimal("250000.00")
DISCOUNT_TIER2_PCT = Decimal("0.0200")

# PRD 3.8 -- write-off approval routing
WRITE_OFF_CONTROLLER_AMOUNT = Decimal("5000.00")
WRITE_OFF_CONTROLLER_AGING_DAYS = 90

# PRD 3.9 -- overhead rate certification
MONTHS_PER_YEAR = Decimal("12")
PROFIT_MARGIN_CAP = Decimal("0.1000")

DEFAULT_WIP_ALERT_THRESHOLD = Decimal("50000.00")


# ---------------------------------------------------------------------------
# Mutation bookkeeping (PRD 2.4)
# ---------------------------------------------------------------------------
def touch(row):
    """"version is an integer that starts at 1 when the resource is created and
    increments by exactly 1 on each mutation of that resource." updated_at is
    refreshed alongside it, "including changes to purely derived figures"."""
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1


def stamp_new(row, mutable=True):
    row["created_at"] = now_iso()
    row["_seq"] = db.next_seq()
    if mutable:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------
def client_of(project):
    return db.clients.get(project["client_id"])


def project_of_phase(phase):
    return db.projects.get(phase["project_id"])


def subcontract_of(consultant_invoice):
    return db.subcontracts.get(consultant_invoice["subcontract_id"])


def project_of_consultant_invoice(consultant_invoice):
    sub = subcontract_of(consultant_invoice)
    if sub is None:
        return None
    return db.projects.get(sub["project_id"])


def project_time_entries(project_id):
    return [e for e in db.time_entries.values() if e["project_id"] == project_id]


def project_expenses(project_id):
    return [e for e in db.expenses.values() if e["project_id"] == project_id]


def project_subcontracts(project_id):
    return [s for s in db.subcontracts.values() if s["project_id"] == project_id]


def project_consultant_invoices(project_id):
    ids = set(s["id"] for s in project_subcontracts(project_id))
    return [c for c in db.consultant_invoices.values() if c["subcontract_id"] in ids]


def project_invoices(project_id):
    return [i for i in db.invoices.values() if i["project_id"] == project_id]


def project_phases(project_id):
    return [p for p in db.phases.values() if p["project_id"] == project_id]


def phase_time_entries(phase_id):
    return [e for e in db.time_entries.values() if e["phase_id"] == phase_id]


def phase_expenses(phase_id):
    return [e for e in db.expenses.values() if e["phase_id"] == phase_id]


def phase_subcontracts(phase_id):
    return [s for s in db.subcontracts.values() if s["phase_id"] == phase_id]


def subcontract_consultant_invoices(subcontract_id):
    return [c for c in db.consultant_invoices.values() if c["subcontract_id"] == subcontract_id]


# ---------------------------------------------------------------------------
# Dates and aging
# ---------------------------------------------------------------------------
def age_days(charge_date):
    """PRD 3.8: "an age measured in whole calendar days between its own charge
    date and as_of_date, floored at zero"."""
    delta = (today() - charge_date).days
    return delta if delta > 0 else 0


def raw_age_days(charge_date):
    return (today() - charge_date).days


# ---------------------------------------------------------------------------
# Phase derived figures (PRD 3.6, phase_earned_value)
# ---------------------------------------------------------------------------
def phase_is_leaf(phase):
    """"true exactly when no other phase declares this phase as its parent_phase_id"."""
    for other in db.phases.values():
        if other.get("parent_phase_id") == phase["id"]:
            return False
    return True


def phase_depth(phase):
    depth = 0
    cursor = phase
    seen = set()
    while cursor.get("parent_phase_id"):
        if cursor["id"] in seen:
            break
        seen.add(cursor["id"])
        parent = db.phases.get(cursor["parent_phase_id"])
        if parent is None:
            break
        depth += 1
        cursor = parent
    return depth


def phase_actual_labor_cost(phase):
    """Sum of raw_cost over the phase's entries in {APPROVED, BILLED, WRITTEN_OFF}."""
    total = ZERO2
    for e in phase_time_entries(phase["id"]):
        if e["status"] in ("APPROVED", "BILLED", "WRITTEN_OFF"):
            total += e["raw_cost"]
    return q2(total)


def phase_effort_percent_complete(phase):
    budget = phase["budget_labor_cost"]
    if budget == ZERO2:
        return ZERO4
    value = q4(phase_actual_labor_cost(phase) / budget)
    one = Decimal("1.0000")
    return value if value < one else one


def phase_effort_earned_value(phase):
    return q2(phase["phase_fee"] * phase_effort_percent_complete(phase))


def phase_assessed_earned_value(phase):
    return q2(phase["phase_fee"] * phase["assessed_percent_complete"])


def phase_recognized_earned_value(phase, project=None):
    """PRD 3.6: full phase_fee whenever COMPLETE; otherwise the variant the
    project's percent_complete_method selects."""
    if phase["status"] == "COMPLETE":
        return q2(phase["phase_fee"])
    if project is None:
        project = project_of_phase(phase)
    if project is not None and project["percent_complete_method"] == "EFFORT_BASED":
        return phase_effort_earned_value(phase)
    return phase_assessed_earned_value(phase)


def phase_consultant_committed_open(phase):
    total = ZERO2
    for s in phase_subcontracts(phase["id"]):
        if s["status"] == "EXECUTED":
            total += s["committed_amount"]
    return q2(total)


# ---------------------------------------------------------------------------
# Subcontract commitment rollup (PRD 3.5)
# ---------------------------------------------------------------------------
def subcontract_approved_to_date(sub):
    total = ZERO2
    for c in subcontract_consultant_invoices(sub["id"]):
        if c["approval_status"] == "APPROVED":
            total += c["amount"]
    return q2(total)


def subcontract_released_to_date(sub):
    total = ZERO2
    for c in subcontract_consultant_invoices(sub["id"]):
        if c["payment_status"] == "RELEASED":
            total += c["amount"]
    return q2(total)


def subcontract_committed_remaining(sub):
    """"committed_remaining is always the committed_amount less approved_to_date"."""
    return q2(sub["committed_amount"] - subcontract_approved_to_date(sub))


# ---------------------------------------------------------------------------
# Project rollups -- the conserved charge ledger (PRD 2.10)
# ---------------------------------------------------------------------------
def project_raw_labor_cost_to_date(project):
    total = ZERO2
    for e in project_time_entries(project["id"]):
        if e["status"] in ("APPROVED", "BILLED", "WRITTEN_OFF"):
            total += e["raw_cost"]
    return q2(total)


def project_labor_billable_total(project):
    total = ZERO2
    for e in project_time_entries(project["id"]):
        if e["status"] in ("APPROVED", "BILLED", "WRITTEN_OFF"):
            total += e["billable_amount"]
    return q2(total)


def unbilled_labor_entries(project_id):
    return [e for e in project_time_entries(project_id)
            if e["status"] == "APPROVED" and e["billed_invoice_id"] is None]


def unbilled_expense_items(project_id):
    return [e for e in project_expenses(project_id)
            if e["allowability_status"] == "ALLOWED" and e["billing_status"] == "UNBILLED"]


def unbilled_consultant_invoices(project_id):
    return [c for c in project_consultant_invoices(project_id)
            if c["approval_status"] == "APPROVED" and c["billing_status"] == "UNBILLED"]


def project_unbilled_wip(project):
    total = ZERO2
    for e in unbilled_labor_entries(project["id"]):
        total += e["billable_amount"]
    for e in unbilled_expense_items(project["id"]):
        total += e["billable_amount"]
    for c in unbilled_consultant_invoices(project["id"]):
        total += c["billable_amount"]
    return q2(total)


def project_billed_open(project):
    total = ZERO2
    for inv in project_invoices(project["id"]):
        if inv["status"] in ("DRAFT", "PENDING_CLIENT_REVIEW", "REVISION_REQUESTED", "APPROVED"):
            total += inv["gross_billed"]
    return q2(total)


def project_paid_gross_to_date(project):
    total = ZERO2
    for inv in project_invoices(project["id"]):
        if inv["status"] == "PAID":
            total += inv["gross_billed"]
    return q2(total)


def project_written_off_gross(project):
    total = ZERO2
    for inv in project_invoices(project["id"]):
        if inv["status"] == "WRITTEN_OFF":
            total += inv["gross_billed"]
    for e in project_time_entries(project["id"]):
        if e["status"] == "WRITTEN_OFF":
            total += e["billable_amount"]
    return q2(total)


def project_total_charge_value(project):
    return q2(project_unbilled_wip(project) + project_billed_open(project)
              + project_paid_gross_to_date(project) + project_written_off_gross(project))


def project_earned_revenue_to_date(project):
    """"the sum of recognized_earned_value over the project's leaf phases only"."""
    total = ZERO2
    for ph in project_phases(project["id"]):
        if phase_is_leaf(ph):
            total += phase_recognized_earned_value(ph, project)
    return q2(total)


def project_net_multiplier_achieved(project):
    raw = project_raw_labor_cost_to_date(project)
    if raw == ZERO2:
        return ZERO4
    return q4(project_labor_billable_total(project) / raw)


# ---------------------------------------------------------------------------
# Overhead certification in force (PRD 3.9)
# ---------------------------------------------------------------------------
def certified_certification_for_current_year():
    year = current_year()
    for c in db.certifications.values():
        if c["status"] == "CERTIFIED" and c["fiscal_year"] == year:
            return c
    return None


def project_certified_multiplier_ceiling(project):
    """PRD 3.9: the ceiling published by the CERTIFIED certification whose
    fiscal_year matches the calendar year of the logical clock; null whenever no
    such certification exists. PRD 3.1/3.9 hop 2 scope it to public-agency
    projects."""
    client = client_of(project)
    if client is None or not client["is_public_agency"]:
        return None
    cert = certified_certification_for_current_year()
    if cert is None:
        return None
    return cert["certified_multiplier_ceiling"]


# ---------------------------------------------------------------------------
# Billing posture (PRD 2.11) -- ordered, first matching clause wins
# ---------------------------------------------------------------------------
def project_billing_posture(project):
    if project["status"] == "CLOSED":
        return "OPEN"
    client = client_of(project)
    if client is not None and client["is_public_agency"]:
        if certified_certification_for_current_year() is None:
            return "HOLD"
    if project_unbilled_wip(project) > project["wip_alert_threshold"]:
        return "REVIEW_REQUIRED"
    return "OPEN"


# ---------------------------------------------------------------------------
# Project closure bubble-up (PRD 3.6)
# ---------------------------------------------------------------------------
def maybe_close_project(project):
    """Re-evaluated at the end of any transition that changes a phase's status,
    an invoice's status or a write-off's status."""
    if project["status"] != "ACTIVE":
        return
    leaves = [p for p in project_phases(project["id"]) if phase_is_leaf(p)]
    if not leaves:
        return
    for ph in leaves:
        if ph["status"] != "COMPLETE":
            return
    if project_unbilled_wip(project) != ZERO2:
        return
    for inv in project_invoices(project["id"]):
        if inv["status"] not in ("PAID", "WRITTEN_OFF", "VOID"):
            return
    project["status"] = "CLOSED"
    touch(project)


# ---------------------------------------------------------------------------
# Effective rate / multiplier lookup (PRD 3.3)
# ---------------------------------------------------------------------------
def _covers(row, on_date):
    """Half-open interval [effective_from, effective_to)."""
    if row["effective_from"] > on_date:
        return False
    if row["effective_to"] is not None and on_date >= row["effective_to"]:
        return False
    return True


def effective_labor_rate(role_code, work_date):
    matches = [r for r in db.labor_rates.values()
               if r["role_code"] == role_code and _covers(r, work_date)]
    if not matches:
        return None
    matches.sort(key=lambda x: (x["created_at"], x["_seq"]))
    return matches[0]


def effective_billing_multiplier(project_id, work_date):
    """"multiplier resolution considers every multiplier of the project in ACTIVE
    or SUPERSEDED status"."""
    matches = [m for m in db.billing_multipliers.values()
               if m["project_id"] == project_id and _covers(m, work_date)]
    if not matches:
        return None
    matches.sort(key=lambda x: (x["created_at"], x["_seq"]))
    return matches[0]


def labor_rate_windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open intervals overlap when a_from < b_to and b_from < a_to."""
    if a_to is not None and b_from >= a_to:
        return False
    if b_to is not None and a_from >= b_to:
        return False
    return True


# ---------------------------------------------------------------------------
# labor_charge_computation (PRD 3.3) -- PINNED two-stage rounding
# ---------------------------------------------------------------------------
def labor_charge(hours, raw_cost_rate, multiplier):
    """First raw_cost = round_half_up(hours * raw_cost_rate, 2). Second
    applied_multiplier at 4dp. Third billable_amount = round_half_up(
    already-rounded raw_cost * applied_multiplier, 2). Multiplying all three
    factors and rounding once is explicitly the wrong answer."""
    raw_cost = q2(d(hours) * d(raw_cost_rate))
    applied = q4(multiplier)
    billable = q2(raw_cost * applied)
    return raw_cost, applied, billable


# ---------------------------------------------------------------------------
# expense_allowability_and_markup (PRD 3.4) -- ordered, first clause wins
# ---------------------------------------------------------------------------
def expense_markup_amount(amount, client):
    return q2(d(amount) * (Decimal("1") + client["expense_markup_pct"]))


def expense_is_excluded(category, client):
    """The two non-overridable exclusions, in PRD clause order."""
    if client["is_public_agency"] and category in ("MEALS", "ENTERTAINMENT"):
        return "STATUTORY_UNALLOWABLE"
    if category in client["disallowed_categories"]:
        return "CLIENT_EXCLUDED"
    return None


def adjudicate_expense(amount, category, receipt_attached, client):
    """Returns (allowability_status, allowability_reason, billable_amount)."""
    # Clause 1 -- the missing-receipt clause outranks both exclusion clauses.
    if d(amount) >= client["receipt_required_above"] and not receipt_attached:
        return "PENDING_REVIEW", "RECEIPT_MISSING", ZERO2
    excluded = expense_is_excluded(category, client)
    if excluded is not None:
        return "DISALLOWED", excluded, ZERO2
    return "ALLOWED", "ALLOWED_BY_RULE", expense_markup_amount(amount, client)


# ---------------------------------------------------------------------------
# consultant_markup_computation (PRD 3.5)
# ---------------------------------------------------------------------------
def consultant_markup(consultant_invoice, subcontract, project, client):
    """The tier is a project-level cumulative volume measured BEFORE this
    approval is applied, so the row being approved is excluded from its own base."""
    approved_cost_to_date = ZERO2
    for c in project_consultant_invoices(project["id"]):
        if c["id"] == consultant_invoice["id"]:
            continue
        if c["approval_status"] == "APPROVED":
            approved_cost_to_date += c["amount"]
    approved_cost_to_date = q2(approved_cost_to_date)
    base_pct = MARKUP_TIER2 if approved_cost_to_date >= MARKUP_TIER2_THRESHOLD else MARKUP_STANDARD
    if project["contract_type"] == "FIXED_FEE":
        base_pct = base_pct + MARKUP_FIXED_FEE_BONUS
    if client["is_public_agency"]:
        applied = base_pct if base_pct < MARKUP_PUBLIC_CAP else MARKUP_PUBLIC_CAP
    else:
        applied = base_pct
    applied = q4(applied)
    markup_amount = q2(consultant_invoice["amount"] * applied)
    billable = q2(consultant_invoice["amount"] + markup_amount)
    return applied, markup_amount, billable


# ---------------------------------------------------------------------------
# consultant_commitment_overlap_exposure (PRD 3.5) -- CLOSED-INCLUSIVE windows
# ---------------------------------------------------------------------------
def consultant_overlap_exposure(candidate, phase):
    exposure = ZERO2
    for s in phase_subcontracts(phase["id"]):
        if s["id"] == candidate["id"]:
            continue
        if s["status"] != "EXECUTED":
            continue
        if s["commitment_start"] <= candidate["commitment_end"] and \
           s["commitment_end"] >= candidate["commitment_start"]:
            exposure += s["committed_amount"]
    return q2(exposure + candidate["committed_amount"])


# ---------------------------------------------------------------------------
# invoice_totals_computation (PRD 3.7) -- PINNED evaluation order
# ---------------------------------------------------------------------------
def volume_discount_pct(gross_billed):
    """The tier is keyed on the PRE-discount gross_billed; both comparisons
    inclusive."""
    if gross_billed >= DISCOUNT_TIER2_THRESHOLD:
        return DISCOUNT_TIER2_PCT
    if gross_billed >= DISCOUNT_TIER1_THRESHOLD:
        return DISCOUNT_TIER1_PCT
    return ZERO4


def invoice_money_figures(gross_billed, client):
    """STEP 1 tier on pre-discount gross. STEP 2 retainage on the POST-discount
    base, never on gross_billed itself. STEP 3 net_due."""
    gross_billed = q2(gross_billed)
    pct = volume_discount_pct(gross_billed)
    discount_amount = q2(gross_billed * pct)
    retainage_amount = q2((gross_billed - discount_amount) * client["retainage_pct"])
    net_due = q2(gross_billed - discount_amount - retainage_amount)
    return pct, discount_amount, retainage_amount, net_due


def sweep_candidates(project, period_end, invoice_id=None):
    """The sweep gathers only charges of the invoice's own project that no other
    invoice has claimed and that are dated on or before period_end. On a revise,
    the charges already attached to this same invoice stay attached."""
    labor = []
    for e in project_time_entries(project["id"]):
        if invoice_id is not None and e["billed_invoice_id"] == invoice_id:
            labor.append(e)
            continue
        if e["status"] == "APPROVED" and e["billed_invoice_id"] is None \
                and e["work_date"] <= period_end:
            labor.append(e)
    expenses = []
    for x in project_expenses(project["id"]):
        if invoice_id is not None and x["billed_invoice_id"] == invoice_id:
            expenses.append(x)
            continue
        if x["allowability_status"] == "ALLOWED" and x["billing_status"] == "UNBILLED" \
                and x["incurred_on"] <= period_end:
            expenses.append(x)
    payables = []
    for c in project_consultant_invoices(project["id"]):
        if invoice_id is not None and c["client_invoice_id"] == invoice_id:
            payables.append(c)
            continue
        if c["approval_status"] == "APPROVED" and c["billing_status"] == "UNBILLED" \
                and c["invoice_date"] <= period_end:
            payables.append(c)
    return labor, expenses, payables


def already_billed_excluding(project, exclude_invoice_id):
    """PRD 3.7: billed_open + paid_gross_to_date + written_off_gross measured
    EXCLUDING the invoice under construction; VOID invoices excluded entirely."""
    counted = ("DRAFT", "PENDING_CLIENT_REVIEW", "REVISION_REQUESTED", "APPROVED",
               "PAID", "WRITTEN_OFF")
    total = ZERO2
    for inv in project_invoices(project["id"]):
        if exclude_invoice_id is not None and inv["id"] == exclude_invoice_id:
            continue
        if inv["status"] in counted:
            total += inv["gross_billed"]
    return q2(total)


def fixed_fee_headroom(project, exclude_invoice_id):
    already = already_billed_excluding(project, exclude_invoice_id)
    return q2(project_earned_revenue_to_date(project) - already)


# ---------------------------------------------------------------------------
# write_off_wip_allocation + routing (PRD 3.8)
# ---------------------------------------------------------------------------
def allocate_write_off(project, amount):
    """Ordered by work_date ASC then created_at ASC -- never by id. The amount
    must equal an exact prefix sum of that ordered candidate list."""
    candidates = unbilled_labor_entries(project["id"])
    candidates.sort(key=lambda e: (e["work_date"], e["created_at"], e["_seq"]))
    running = ZERO2
    allocated = []
    for e in candidates:
        running = q2(running + e["billable_amount"])
        allocated.append(e["id"])
        if running == amount:
            return allocated
        if running > amount:
            return None
    return None


def write_off_routing(target_type, amount, aging_days):
    """Both thresholds inclusive. An INVOICE_RECEIVABLE write-off always routes
    to CONTROLLER regardless of its amount or age."""
    if target_type == "INVOICE_RECEIVABLE":
        return "CONTROLLER", "PENDING_CONTROLLER_APPROVAL"
    if amount >= WRITE_OFF_CONTROLLER_AMOUNT or aging_days >= WRITE_OFF_CONTROLLER_AGING_DAYS:
        return "CONTROLLER", "PENDING_CONTROLLER_APPROVAL"
    return "PROJECT_MANAGER", "PENDING_PM_APPROVAL"


# ---------------------------------------------------------------------------
# overhead_rate_computation (PRD 3.9)
# ---------------------------------------------------------------------------
def provisional_overhead_rate(indirect_cost_pool, direct_labor_base, ytd_months):
    """Annualise the year-to-date figures and keep unallowable costs in the pool."""
    pool_annualized = q2(d(indirect_cost_pool) * MONTHS_PER_YEAR / Decimal(ytd_months))
    base_annualized = q2(d(direct_labor_base) * MONTHS_PER_YEAR / Decimal(ytd_months))
    return q4(pool_annualized / base_annualized)


def final_overhead_rate(indirect_cost_pool, unallowable_costs, direct_labor_base):
    """Actual basis, unallowable costs removed, no annualisation."""
    return q4((d(indirect_cost_pool) - d(unallowable_costs)) / d(direct_labor_base))


def certified_ceiling(final_rate):
    return q4((Decimal("1") + d(final_rate)) * (Decimal("1") + PROFIT_MARGIN_CAP))


# ---------------------------------------------------------------------------
# wip_aging_buckets (PRD 3.8)
# ---------------------------------------------------------------------------
def wip_aging(project):
    b0, b31, b61, b90 = ZERO2, ZERO2, ZERO2, ZERO2
    rows = []
    for e in unbilled_labor_entries(project["id"]):
        rows.append((e["work_date"], e["billable_amount"]))
    for x in unbilled_expense_items(project["id"]):
        rows.append((x["incurred_on"], x["billable_amount"]))
    for c in unbilled_consultant_invoices(project["id"]):
        rows.append((c["invoice_date"], c["billable_amount"]))
    for charge_date, value in rows:
        age = age_days(charge_date)
        if age <= 30:
            b0 += value
        elif age <= 60:
            b31 += value
        elif age <= 90:
            b61 += value
        else:
            b90 += value
    b0, b31, b61, b90 = q2(b0), q2(b31), q2(b61), q2(b90)
    return {
        "bucket_0_30": b0,
        "bucket_31_60": b31,
        "bucket_61_90": b61,
        "bucket_over_90": b90,
        "total_unbilled": q2(b0 + b31 + b61 + b90),
        "write_off_eligible_amount": b90,
    }
