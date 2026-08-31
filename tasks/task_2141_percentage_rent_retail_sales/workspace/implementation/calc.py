"""Domain calculations (SCAFFOLD 1.3 / PRD section 3) and the cascades that
apply them. All arithmetic is whole integer cents; round-half-up and floor are
applied exactly where the PRD names them.
"""

from core import (
    DB,
    ApiError,
    add_days,
    all_of,
    clock_now,
    fdiv,
    find,
    make_record,
    rhu,
    touch,
)

# --- constants -------------------------------------------------------------

COUNTED_REPORT_STATUSES = ("ACCEPTED", "UNDER_AUDIT", "DISPUTED", "ADJUSTED", "ESTIMATED")

AGGREGATE_EXCLUSION_CAP_BPS = 1500

EXCLUSION_CODES = (
    "RETURNS_AND_ALLOWANCES",
    "SALES_TAX",
    "GIFT_CARD_ISSUANCE",
    "INTERCOMPANY_TRANSFER",
    "EMPLOYEE_DISCOUNT",
    "ONLINE_SHIP_FROM_STORE",
    "VENDING_AND_SERVICE",
)

EXCLUSION_CAP_BPS = {
    "STANDARD": {
        "RETURNS_AND_ALLOWANCES": 1200,
        "SALES_TAX": 10000,
        "GIFT_CARD_ISSUANCE": 500,
        "INTERCOMPANY_TRANSFER": 10000,
        "EMPLOYEE_DISCOUNT": 300,
        "ONLINE_SHIP_FROM_STORE": 10000,
        "VENDING_AND_SERVICE": 200,
    },
    "RESTRICTIVE": {
        "RETURNS_AND_ALLOWANCES": 800,
        "SALES_TAX": 10000,
        "GIFT_CARD_ISSUANCE": 0,
        "INTERCOMPANY_TRANSFER": 10000,
        "EMPLOYEE_DISCOUNT": 100,
        "ONLINE_SHIP_FROM_STORE": 0,
        "VENDING_AND_SERVICE": 200,
    },
}

EXCLUSION_HARD_CAP_CENTS = {
    "GIFT_CARD_ISSUANCE": 500000,
    "EMPLOYEE_DISCOUNT": 250000,
}

ESTIMATE_LOOKBACK_PERIODS = 3
ESTIMATE_UPLIFT_BPS = 11000
ESTIMATE_NO_HISTORY_FACTOR_BPS = 8000

CO_TENANCY_DEFAULT_RELIEF_BPS = 5000
ALTERNATIVE_RENT_LOOKBACK_PERIODS = 3

OCR_WATCHLIST_BPS = 1500
DELINQUENCY_STRIKE_LIMIT = 3

AUDIT_COOLDOWN_DAYS = 30
MAX_AMENDMENT_ROUNDS = 2

LEDGER_ENTRY_TYPES = (
    "REPORT_ACCEPTED",
    "REPORT_WITHDRAWN",
    "ESTIMATE_ISSUED",
    "ESTIMATE_VOIDED",
    "PERIODIC_CHARGE_ISSUED",
    "TRUE_UP_ISSUED",
    "CREDIT_ISSUED",
    "AUDIT_ADJUSTMENT",
    "AUDIT_RESCINDED",
)


# --- navigation helpers ----------------------------------------------------


def lease_of_year(ly):
    return DB["leases"].get(ly["lease_id"])


def year_of_report(report):
    return DB["lease_years"].get(report["lease_year_id"])


def lease_of_report(report):
    ly = year_of_report(report)
    return lease_of_year(ly) if ly else None


def lease_of_charge(charge):
    ly = DB["lease_years"].get(charge["lease_year_id"])
    return lease_of_year(ly) if ly else None


def reports_of_year(ly):
    return find("sales_reports", lease_year_id=ly["id"])


def charges_of_year(ly):
    return find("charges", lease_year_id=ly["id"])


def years_of_lease(lease):
    return find("lease_years", lease_id=lease["id"])


def exclusions_of_report(report):
    return find("sales_exclusions", sales_report_id=report["id"])


def periods_per_year(lease):
    return 12 if lease["reporting_frequency"] == "MONTHLY" else 4


def base_monthly_rent(lease):
    return rhu(lease["annual_base_rent_cents"], 12)


# --- ledger ----------------------------------------------------------------


def append_ledger(ly, entry_type, delta_net=0, delta_billed=0, note=""):
    return make_record(
        "ledger_entries",
        {
            "lease_year_id": ly["id"],
            "entry_type": entry_type,
            "delta_net_sales_cents": int(delta_net),
            "delta_billed_cents": int(delta_billed),
            "note": note,
        },
        versioned=False,
    )


def move_net(ly, delta, entry_type, note):
    ly["cumulative_net_sales_cents"] += int(delta)
    touch(ly)
    append_ledger(ly, entry_type, delta_net=delta, delta_billed=0, note=note)


def move_billed(ly, delta, entry_type, note):
    ly["cumulative_billed_cents"] += int(delta)
    touch(ly)
    append_ledger(ly, entry_type, delta_net=0, delta_billed=delta, note=note)


# --- calculations.net_reported_sales --------------------------------------


def net_reported_sales(report):
    """Three-step exclusion capping waterfall (PRD 3.4)."""
    lease = lease_of_report(report)
    gross = report["gross_sales_cents"] or 0
    lines = exclusions_of_report(report)
    profile = lease["exclusion_profile"]

    # STEP 1 - per-line capping, created_at ASC
    for line in lines:
        cap_bps = EXCLUSION_CAP_BPS[profile][line["code"]]
        hard_cap = EXCLUSION_HARD_CAP_CENTS.get(line["code"])
        pct_cap = fdiv(gross * cap_bps, 10000)
        raw_cap = pct_cap if hard_cap is None else min(pct_cap, hard_cap)
        line["allowed_cents"] = max(0, min(line["claimed_cents"], raw_cap))

    # STEP 2 - aggregate cap trimmed by waterfall (NOT pro-rated)
    allowed_total = sum(l["allowed_cents"] for l in lines)
    aggregate_cap = fdiv(gross * AGGREGATE_EXCLUSION_CAP_BPS, 10000)
    if allowed_total > aggregate_cap:
        overage = allowed_total - aggregate_cap
        for line in sorted(lines, key=lambda l: (-l["allowed_cents"], l["_seq"])):
            take = min(line["allowed_cents"], overage)
            line["allowed_cents"] -= take
            overage -= take
            if overage == 0:
                break

    # STEP 3 - line statuses, then report totals
    for line in lines:
        if line["allowed_cents"] == line["claimed_cents"]:
            line["status"] = "ALLOWED"
        elif line["allowed_cents"] == 0:
            line["status"] = "DISALLOWED"
        else:
            line["status"] = "PARTIALLY_ALLOWED"
        touch(line)

    report["allowed_exclusions_cents"] = sum(l["allowed_cents"] for l in lines)
    report["net_sales_cents"] = gross - report["allowed_exclusions_cents"]
    return report["net_sales_cents"]


# --- calculations.percentage_rent_charge ----------------------------------


def percentage_rent_amount(ly, report):
    """Returns the amount to bill; variant pinned by billing_mode_snapshot."""
    lease = lease_of_year(ly)
    rate = ly["percentage_rate_bps_snapshot"]
    if ly["billing_mode_snapshot"] == "CUMULATIVE_YTD":
        prior_net = sum(
            r["net_sales_cents"]
            for r in reports_of_year(ly)
            if r["status"] in COUNTED_REPORT_STATUSES and r["id"] != report["id"]
        )
        cum_net = prior_net + report["net_sales_cents"]
        excess = max(0, cum_net - ly["breakpoint_cents"])
        gross_due = rhu(excess * rate, 10000)
        prior_billed = sum(
            c["amount_cents"] for c in charges_of_year(ly) if c["billing_status"] == "ISSUED"
        )
        return gross_due - prior_billed

    period_months = 1 if lease["reporting_frequency"] == "MONTHLY" else 3
    period_breakpoint = rhu(ly["breakpoint_cents"] * period_months, 12)
    excess = max(0, report["net_sales_cents"] - period_breakpoint)
    return rhu(excess * rate, 10000)


def create_charge(ly, charge_type, amount, sales_report_id=None, billing_status="DRAFT",
                  settlement_audit_id=None):
    fields = {
        "lease_year_id": ly["id"],
        "sales_report_id": sales_report_id,
        "supersedes_charge_id": None,
        "charge_type": charge_type,
        "amount_cents": int(amount),
        "billing_status": billing_status,
        "collection_status": "UNPAID",
        "paid_cents": 0,
        "issued_at": clock_now() if billing_status == "ISSUED" else None,
    }
    charge = make_record("charges", fields)
    charge["_settlement_audit_id"] = settlement_audit_id
    return charge


def bill_percentage_rent(ly, report, charge_type_positive, charge_type_negative,
                         entry_type_positive, entry_type_negative, note,
                         settlement_audit_id=None):
    """Runs the percentage-rent computation and issues a charge when non-zero."""
    amount = percentage_rent_amount(ly, report)
    if amount == 0:
        return None
    charge_type = charge_type_positive if amount > 0 else charge_type_negative
    charge = create_charge(
        ly,
        charge_type,
        amount,
        sales_report_id=report["id"],
        billing_status="ISSUED",
        settlement_audit_id=settlement_audit_id,
    )
    entry_type = entry_type_positive if amount > 0 else entry_type_negative
    move_billed(ly, amount, entry_type, note)
    return charge


# --- calculations.annual_true_up ------------------------------------------


def annual_true_up(ly):
    annual_net = sum(
        r["net_sales_cents"] for r in reports_of_year(ly) if r["status"] in COUNTED_REPORT_STATUSES
    )
    annual_excess = max(0, annual_net - ly["breakpoint_cents"])
    annual_due = rhu(annual_excess * ly["percentage_rate_bps_snapshot"], 10000)
    billed = sum(c["amount_cents"] for c in charges_of_year(ly) if c["billing_status"] == "ISSUED")
    return annual_due - billed


# --- calculations.delinquency_estimate ------------------------------------


def delinquency_estimate(ly, report):
    lease = lease_of_year(ly)
    history = [
        r
        for r in reports_of_year(ly)
        if r["source"] == "TENANT_REPORTED"
        and r["status"] in ("ACCEPTED", "ADJUSTED")
        and r["period_end"] <= report["period_start"]
    ]
    history.sort(key=lambda r: (r["period_end"], r["_seq"]), reverse=True)
    window = history[:ESTIMATE_LOOKBACK_PERIODS]
    ppy = periods_per_year(lease)
    if not window:
        return rhu(ly["breakpoint_cents"] * ESTIMATE_NO_HISTORY_FACTOR_BPS, ppy * 10000)
    base = rhu(sum(w["gross_sales_cents"] or 0 for w in window), len(window))
    return rhu(base * ESTIMATE_UPLIFT_BPS, 10000)


# --- calculations.co_tenancy_relief ---------------------------------------


def co_tenancy_relief(lease, clause):
    base = base_monthly_rent(lease)
    if clause["relief_type"] == "RENT_REDUCTION":
        relief_monthly = rhu(base * clause["relief_pct_bps"], 10000)
        effective = base - relief_monthly
    else:
        window = []
        for ly in years_of_lease(lease):
            for r in reports_of_year(ly):
                if r["status"] in ("ACCEPTED", "ADJUSTED"):
                    window.append(r)
        window.sort(key=lambda r: (r["period_end"], r["_seq"]), reverse=True)
        window = window[:ALTERNATIVE_RENT_LOOKBACK_PERIODS]
        if not window:
            relief_monthly = rhu(base * CO_TENANCY_DEFAULT_RELIEF_BPS, 10000)
            effective = base - relief_monthly
        else:
            avg_net = rhu(sum(w["net_sales_cents"] for w in window), len(window))
            alt_rent = rhu(avg_net * clause["relief_pct_bps"], 10000)
            effective = min(base, alt_rent)
    lease["effective_monthly_rent_cents"] = effective
    lease["relief_monthly_credit_cents"] = base - effective
    return effective


# --- calculations.occupancy_and_co_tenancy_monitor ------------------------


def run_monitor(center, trigger_tenant=None):
    """Recomputes center occupancy figures and re-evaluates co-tenancy clauses."""
    tenants = find("tenants", center_id=center["id"])
    leases = find("leases", center_id=center["id"])

    open_anchor_count = sum(1 for t in tenants if t["is_anchor"] and t["status"] == "OPERATING")
    occupied = sum(
        l["leased_sqft"]
        for l in leases
        if l["status"] in ("ACTIVE", "RELIEF_ACTIVE", "TERMINATION_PENDING")
    )
    occupancy_bps = 0 if center["total_gla_sqft"] == 0 else fdiv(occupied * 10000, center["total_gla_sqft"])

    if (
        center["open_anchor_count"] != open_anchor_count
        or center["occupied_gla_sqft"] != occupied
        or center["occupancy_bps"] != occupancy_bps
    ):
        center["open_anchor_count"] = open_anchor_count
        center["occupied_gla_sqft"] = occupied
        center["occupancy_bps"] = occupancy_bps
        touch(center)

    lease_by_id = {l["id"]: l for l in leases}
    clauses = [
        c
        for c in all_of("co_tenancy_clauses")
        if c["lease_id"] in lease_by_id
        and lease_by_id[c["lease_id"]]["status"] in ("ACTIVE", "RELIEF_ACTIVE")
    ]

    for clause in clauses:
        lease = lease_by_id[clause["lease_id"]]
        anchor_leg = open_anchor_count < clause["required_open_anchor_count"]
        occupancy_leg = occupancy_bps < clause["required_occupancy_bps"]
        violated = anchor_leg or occupancy_leg
        new_status = "VIOLATED" if violated else "SATISFIED"
        if clause["monitoring_status"] != new_status:
            clause["monitoring_status"] = new_status
            touch(clause)
        if not violated:
            continue
        existing = [
            e
            for e in find("co_tenancy_events", clause_id=clause["id"])
            if e["status"] in ("OPEN", "CURE_PENDING", "RELIEF_ACTIVE")
        ]
        if existing:
            continue
        observed_at = clock_now()
        trigger_id = None
        if trigger_tenant is not None and trigger_tenant.get("is_anchor"):
            trigger_id = trigger_tenant["id"]
        make_record(
            "co_tenancy_events",
            {
                "clause_id": clause["id"],
                "trigger_tenant_id": trigger_id,
                "event_type": "ANCHOR_WENT_DARK" if anchor_leg else "OCCUPANCY_BELOW_FLOOR",
                "observed_at": observed_at,
                "cure_deadline_at": add_days(observed_at, clause["cure_period_days"]),
                "relief_started_at": None,
                "relief_ended_at": None,
                "status": "OPEN",
            },
        )
        if lease["co_tenancy_status"] == "COMPLIANT":
            lease["co_tenancy_status"] = "VIOLATION_OPEN"
            touch(lease)


# --- calculations.occupancy_cost_ratio ------------------------------------


def occupancy_cost_ratio(lease):
    candidates = [ly for ly in years_of_lease(lease) if ly["status"] != "CLOSED"]
    if not candidates:
        return
    ly = max(candidates, key=lambda y: (y["year_index"], y["_seq"]))
    elapsed = sum(1 for r in reports_of_year(ly) if r["status"] in COUNTED_REPORT_STATUSES)
    ppy = periods_per_year(lease)
    ytd = rhu(lease["annual_base_rent_cents"] * elapsed, ppy) + ly["cumulative_billed_cents"]
    if ly["cumulative_net_sales_cents"] == 0:
        ratio = 0
    else:
        ratio = fdiv(ytd * 10000, ly["cumulative_net_sales_cents"])
    watchlist = (
        "WATCHLIST"
        if ratio >= OCR_WATCHLIST_BPS or lease["delinquency_strikes"] >= DELINQUENCY_STRIKE_LIMIT
        else "NORMAL"
    )
    if (
        lease["ytd_occupancy_cost_cents"] != ytd
        or lease["occupancy_cost_ratio_bps"] != ratio
        or lease["watchlist_status"] != watchlist
    ):
        lease["ytd_occupancy_cost_cents"] = ytd
        lease["occupancy_cost_ratio_bps"] = ratio
        lease["watchlist_status"] = watchlist
        touch(lease)


# --- calculations.kick_out_evaluation -------------------------------------


def kick_out_evaluation(ly):
    lease = lease_of_year(ly)
    clauses = [
        k
        for k in find("kick_out_clauses", lease_id=lease["id"])
        if k["status"] == "ARMED" and k["measurement_year_index"] == ly["year_index"]
    ]
    for clause in clauses:
        if ly["cumulative_net_sales_cents"] < clause["threshold_sales_cents"]:
            now = clock_now()
            clause["status"] = "TRIGGERED"
            clause["triggered_at"] = now
            clause["election_deadline_at"] = add_days(now, clause["election_window_days"])
        else:
            clause["status"] = "EXPIRED"
        touch(clause)


# --- calculations.reporting_interval_conflicts ----------------------------


def report_period_conflicts(ly, new_start, new_end, exclude_id=None):
    for r in reports_of_year(ly):
        if r["status"] == "VOID" or r["id"] == exclude_id:
            continue
        if new_start < r["period_end"] and r["period_start"] < new_end:
            return True
    return False


def audit_window_conflicts(lease, new_start, new_end):
    for a in find("audits", lease_id=lease["id"]):
        if a["status"] == "RESCINDED":
            continue
        if (
            new_start <= add_days(a["audit_window_end"], AUDIT_COOLDOWN_DAYS)
            and add_days(a["audit_window_start"], -AUDIT_COOLDOWN_DAYS) <= new_end
        ):
            return True
    return False


# --- calculations.center_sales_trend --------------------------------------


def center_sales_trend(center, year_index):
    comp_set = []
    for lease in find("leases", center_id=center["id"]):
        if lease["status"] not in ("ACTIVE", "RELIEF_ACTIVE", "TERMINATION_PENDING"):
            continue
        years = years_of_lease(lease)
        current = next(
            (y for y in years if y["year_index"] == year_index and y["status"] == "RECONCILED"), None
        )
        prior = next(
            (y for y in years if y["year_index"] == year_index - 1 and y["status"] == "RECONCILED"),
            None,
        )
        if current is None or prior is None:
            continue
        comp_set.append((lease, current, prior))

    tenant_count = len(comp_set)
    comp_sqft = sum(l["leased_sqft"] for l, _, _ in comp_set)
    current_net = sum(c["cumulative_net_sales_cents"] for _, c, _ in comp_set)
    prior_net = sum(p["cumulative_net_sales_cents"] for _, _, p in comp_set)
    percentage_rent = sum(c["cumulative_billed_cents"] for _, c, _ in comp_set)
    occupancy_cost = sum(l["annual_base_rent_cents"] for l, _, _ in comp_set) + percentage_rent

    comp_growth_bps = 0 if prior_net == 0 else rhu((current_net - prior_net) * 10000, prior_net)
    sales_psf_cents = 0 if comp_sqft == 0 else fdiv(current_net, comp_sqft)
    ocr_bps = 0 if current_net == 0 else fdiv(occupancy_cost * 10000, current_net)

    return {
        "tenant_count": tenant_count,
        "comp_sqft": comp_sqft,
        "current_net_sales_cents": current_net,
        "prior_net_sales_cents": prior_net,
        "comp_growth_bps": comp_growth_bps,
        "percentage_rent_cents": percentage_rent,
        "sales_psf_cents": sales_psf_cents,
        "occupancy_cost_ratio_bps": ocr_bps,
    }


# --- shared state gates ---------------------------------------------------


def require_year_status(ly, allowed, ):
    if ly["status"] not in allowed:
        raise ApiError("ERR_LEASE_YEAR_STATE_INVALID", 409)


def require_year_not_closed(ly):
    if ly["status"] == "CLOSED":
        raise ApiError("ERR_LEASE_YEAR_STATE_INVALID", 409)
