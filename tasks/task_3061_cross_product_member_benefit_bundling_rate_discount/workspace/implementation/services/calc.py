"""Calculation rules (SCAFFOLD section 1.3) and the pure derived readers."""

from db import DB, PRODUCT_LINE_ORDER, TIER_ORDER, created_key, parse_dt
from timeutil import month_index, month_start, parse_ts


def utcnow():
    return DB.clock()


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------
def tier_rank(tier):
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else 0


def holdings_of(member_id):
    return [h for h in DB.holdings.values() if h["member_id"] == member_id]


def loans_of(member_id):
    return [a for a in DB.loan_accounts.values() if a["member_id"] == member_id]


def applications_of(loan_id):
    return [a for a in DB.applications.values() if a["loan_account_id"] == loan_id]


def applications_of_rule(rule_id):
    return [a for a in DB.applications.values() if a["rule_id"] == rule_id]


def entitlements_of(member_id):
    return [e for e in DB.entitlements.values() if e["member_id"] == member_id]


def entitlements_of_holding(holding_id):
    return [e for e in DB.entitlements.values() if e["source_holding_id"] == holding_id]


def enrollment_of(member_id):
    rows = [e for e in DB.enrollments.values() if e["member_id"] == member_id]
    rows.sort(key=created_key)
    return rows[-1] if rows else None


def postings_of(enrollment_id):
    rows = [p for p in DB.deposit_postings.values() if p["enrollment_id"] == enrollment_id]
    rows.sort(key=lambda p: (p["posted_at"] or "", p["id"]))
    return rows


def ledger_of(member_id):
    rows = [e for e in DB.ledger.values() if e["member_id"] == member_id]
    rows.sort(key=created_key)
    return rows


# ---------------------------------------------------------------------------
# Tier, adoption breadth
# ---------------------------------------------------------------------------
def adoption_counts(member_id, include_pending=False):
    statuses = {"ADOPTED"}
    if include_pending:
        statuses.add("PENDING")
    rows = [h for h in holdings_of(member_id) if h["adoption_status"] in statuses]
    lines = sorted({h["product_line"] for h in rows}, key=lambda l: PRODUCT_LINE_ORDER.index(l))
    return len(rows), lines


def product_adoption_count(member_id):
    return adoption_counts(member_id)[0]


def product_line_set(member_id):
    return adoption_counts(member_id)[1]


def member_tier_for(member_id, forward_looking=False):
    count, lines = adoption_counts(member_id, include_pending=forward_looking)
    if count >= 3 and len(lines) >= 3:
        return "PREMIER"
    if count >= 2 and len(lines) >= 2:
        return "PLUS"
    if count >= 1:
        return "BASE"
    return "NONE"


# ---------------------------------------------------------------------------
# Deposit aggregates
# ---------------------------------------------------------------------------
def qualifying_deposit_balance_cents(member_id, include_suspended=False):
    total = 0
    for h in holdings_of(member_id):
        if h["product_line"] != "BANKING":
            continue
        if h["adoption_status"] == "ADOPTED" or (
            include_suspended and h["adoption_status"] == "SUSPENDED"
        ):
            total += int(h.get("balance_cents") or 0)
    return total


def last_qualifying_deposit_at(member_id):
    enr = enrollment_of(member_id)
    if enr is None:
        return None
    required = int(enr["required_monthly_amount_cents"])
    stamps = [
        p["posted_at"]
        for p in postings_of(enr["id"])
        if p["posting_status"] == "POSTED" and int(p["amount_cents"]) >= required
    ]
    return max(stamps) if stamps else None


def month_qualifies(enrollment_id, m_index):
    enr = DB.enrollments.get(enrollment_id)
    if enr is None:
        return False
    start = month_start(m_index)
    end = month_start(m_index + 1)
    total = 0
    now = utcnow()
    for p in postings_of(enrollment_id):
        if p["posting_status"] == "REVERSED":
            continue
        dt = parse_ts(p["posted_at"])
        if dt is None or dt > now:
            continue
        if start <= dt < end:
            total += int(p["amount_cents"])
    return total >= int(enr["required_monthly_amount_cents"])


def consecutive_qualifying_months(enrollment_id):
    """The maximal trailing run of qualifying months, ending at the current month.

    The run ends at the logical month containing the current instant; a month
    whose posted deposits did not meet the threshold breaks the run, and a month
    that has not yet elapsed cannot qualify, so an unfunded current month reads as
    a zero run rather than extending the preceding months' run.
    """
    enr = DB.enrollments.get(enrollment_id)
    if enr is None:
        return 0
    current = month_index(utcnow())
    count = 0
    m = current
    while m >= 0 and month_qualifies(enrollment_id, m):
        count += 1
        m -= 1
    return count


def missed_cycle_count(enrollment_id):
    enr = DB.enrollments.get(enrollment_id)
    if enr is None:
        return 0
    qualified = parse_dt(enr, "qualified_at")
    if qualified is None:
        return 0
    start = month_index(qualified)
    end = month_index(utcnow())
    if end <= start:
        return 0
    return sum(1 for m in range(start, end) if not month_qualifies(enrollment_id, m))


def requalification_due_at(enrollment_id):
    enr = DB.enrollments.get(enrollment_id)
    if enr is None:
        return None
    qualified = parse_dt(enr, "qualified_at")
    if qualified is None:
        return None
    due = month_start(month_index(qualified) + 3)
    from timeutil import fmt_ts

    return fmt_ts(due)


BANDS = [
    (100000, 25),
    (500000, 50),
    (2500000, 75),
]


def deposit_rate_boost_bps(member_id, balance=None):
    enr = enrollment_of(member_id)
    if enr is None or enr["status"] != "ACTIVE":
        return 0
    if balance is None:
        balance = qualifying_deposit_balance_cents(member_id)
    boost = 0
    for min_balance, bps in BANDS:
        if balance >= min_balance:
            boost = bps
    return boost


def trailing_average_balance_cents(member_id):
    """Mean qualifying balance across the trailing three logical months."""
    current = month_index(utcnow())
    months = [current - 2, current - 1, current]
    samples = []
    balance = qualifying_deposit_balance_cents(member_id)
    for m in months:
        total = 0
        for h in holdings_of(member_id):
            if h["product_line"] != "BANKING" or h["adoption_status"] != "ADOPTED":
                continue
            created = parse_ts(h.get("created_at"))
            if created is None or month_index(created) <= m:
                total += int(h.get("balance_cents") or 0)
        samples.append(total)
    # the current month carries the live balance, earlier months the recorded one
    samples[-1] = balance
    return sum(samples) // len(samples)


# ---------------------------------------------------------------------------
# Booleans
# ---------------------------------------------------------------------------
def deposit_rate_eligible(holding_id):
    h = DB.holdings.get(holding_id)
    if h is None or h["product_line"] != "BANKING" or h["adoption_status"] != "ADOPTED":
        return False
    enr = enrollment_of(h["member_id"])
    return bool(enr and enr["status"] == "ACTIVE")


def latest_cross_sell_check(member_id, product_line):
    rows = [
        c
        for c in DB.checks.values()
        if c["member_id"] == member_id and c["target_product_line"] == product_line
    ]
    if not rows:
        return None
    rows.sort(key=lambda c: (c.get("created_at") or "", c.get("decided_at") or ""))
    return rows[-1]


def cross_sell_eligible(holding_id):
    h = DB.holdings.get(holding_id)
    if h is None or h["adoption_status"] not in ("ADOPTED", "SUSPENDED"):
        return False
    latest = latest_cross_sell_check(h["member_id"], h["product_line"])
    return bool(latest and latest["status"] == "CLEARED")


def reunderwriting_permitted(holding_id):
    h = DB.holdings.get(holding_id)
    if h is None or h["product_line"] != "LENDING" or h["adoption_status"] != "ADOPTED":
        return False
    for a in DB.loan_accounts.values():
        if a["holding_id"] == holding_id and a["pricing_status"] in ("FINAL", "STEPPED_DOWN"):
            return True
    return False


def rewards_points_balance(member_id):
    """Posted points balance: the non-negative sum of the member's point deltas.

    A reversal moves the original row to REVERSED (dropping it out of the sum)
    and appends a compensating REVERSE row that is an audit companion linked back
    to the original, so the compensation restores the balance exactly rather than
    counting the negated delta a second time.
    """
    total = 0
    for e in ledger_of(member_id):
        if e["entry_status"] == "POSTED" and e["entry_type"] != "REVERSE":
            total += int(e["points_delta"])
    return max(0, total)


# ---------------------------------------------------------------------------
# Churn
# ---------------------------------------------------------------------------
DEPOSIT_STOP_WEIGHT = 40
MISSED_CYCLE_WEIGHT = 20
MISSED_CYCLE_SATURATION = 2
TIER_DOWN_WEIGHT = 25
BALANCE_DROP_WEIGHT = 15
BALANCE_DROP_FLOOR_CENTS = 500000
CHURN_AT_RISK_SCORE = 60
CHURN_LAPSE_SCORE = 85

APR_FLOOR_BPS = 199
STACK_CAP_BPS = 400


def churn_factors(member_id):
    enr = enrollment_of(member_id)
    member = DB.members.get(member_id)
    f_deposit = 1 if (enr and enr["status"] in ("GRACE", "LAPSED")) else 0
    # A completed logical month that failed to qualify counts as a missed cycle;
    # the stored counter is not the measure, because opening a grace window
    # resets it (PRD §3.3), while the missed months themselves do not disappear.
    f_cycles = min(MISSED_CYCLE_SATURATION, missed_cycle_count(enr["id"]) if enr else 0)
    tier = member["member_tier"] if member else "NONE"
    f_tier = 1 if tier in ("NONE", "BASE") else 0
    balance = member["qualifying_deposit_balance_cents"] if member else 0
    f_balance = 1 if balance < BALANCE_DROP_FLOOR_CENTS else 0
    return {
        "deposit_factor": DEPOSIT_STOP_WEIGHT * f_deposit,
        "missed_cycle_factor": MISSED_CYCLE_WEIGHT * f_cycles,
        "tier_factor": TIER_DOWN_WEIGHT * f_tier,
        "balance_factor": BALANCE_DROP_WEIGHT * f_balance,
    }


def churn_raw_score(member_id):
    return sum(churn_factors(member_id).values())


def churn_risk_score(member_id):
    """Clamped stored score, built from each factor's saturated contribution."""
    raw = churn_raw_score(member_id)
    return min(100, max(0, raw))


# ---------------------------------------------------------------------------
# Discount stack waterfall
# ---------------------------------------------------------------------------
def live_candidates(loan):
    now = utcnow()
    member = DB.members.get(loan["member_id"])
    if member is None:
        return []
    enr = enrollment_of(member["id"])
    tier_rank_now = tier_rank(member["member_tier"])
    out = []
    for r in DB.rules.values():
        if r["status"] != "ACTIVE":
            continue
        start = parse_ts(r.get("effective_from"))
        end = parse_ts(r.get("effective_to"))
        if start is None or end is None:
            continue
        if not (start <= now < end):
            continue
        if tier_rank_now < tier_rank(r.get("min_member_tier") or "NONE"):
            continue
        if r.get("requires_direct_deposit") and not (enr and enr["status"] == "ACTIVE"):
            continue
        if r["discount_kind"] == "AUTOPAY" and loan["autopay_status"] != "ENROLLED":
            continue
        out.append(r)
    return out


def survivor_key(rule):
    return (
        int(rule["discount_bps"]),
        rule.get("effective_from") or "",
        rule.get("created_at") or "",
    )


def survivor_rules(loan):
    """Top one rule per stacking_class; ties resolved without consulting the id."""
    by_class = {}
    order = []
    for r in live_candidates(loan):
        cls = r["stacking_class"]
        if cls not in by_class:
            by_class[cls] = r
            order.append(cls)
        elif survivor_key(r) > survivor_key(by_class[cls]):
            by_class[cls] = r
    return [by_class[c] for c in order]


def applied_applications(loan_id):
    return [
        a for a in applications_of(loan_id) if a["application_state"] == "APPLIED"
    ]


def stack_sum_bps(loan):
    """Raw sum of the applied discount basis points; before the ceiling."""
    if loan is None:
        return 0
    return sum(int(a["applied_bps"]) for a in applied_applications(loan["id"]))


def uncapped_stack_bps(loan):
    """The diagnostic (pre-ceiling) value surfaced by the pricing breakdown."""
    return stack_sum_bps(loan)


def discount_stack_total_bps(loan):
    return min(STACK_CAP_BPS, stack_sum_bps(loan))


def loan_effective_apr_bps(loan):
    return max(APR_FLOOR_BPS, int(loan["base_apr_bps"]) - int(loan["discount_stack_bps"]))


def rewards_principal_reduction_cents(points):
    return int(points) // 100


# ---------------------------------------------------------------------------
# Session geometry
# ---------------------------------------------------------------------------
def sessions_overlapping(coach_ref, session_kind, starts_at, ends_at, exclude_id=None,
                         half_open=True):
    start = parse_ts(starts_at)
    end = parse_ts(ends_at)
    out = []
    for s in DB.sessions.values():
        if s["id"] == exclude_id:
            continue
        if s["coach_ref"] != coach_ref or s["session_kind"] != session_kind:
            continue
        if s["status"] == "CANCELLED":
            continue
        s_start = parse_ts(s["starts_at"])
        s_end = parse_ts(s["ends_at"])
        if half_open:
            if s_start < end and start < s_end:
                out.append(s)
        else:
            if s_start < end and start < s_end:
                out.append(s)
            elif s_end == start or s_start == end:
                out.append(s)
    return out


def session_seats_reserved(session):
    """Reserved seats for a member event: the count of overlapping bookings.

    The interval is the session's own, so the session counts as one of the
    bookings it reports.
    """
    if session["session_kind"] != "MEMBER_EVENT":
        return 0
    return len(
        sessions_overlapping(
            session["coach_ref"],
            "MEMBER_EVENT",
            session["starts_at"],
            session["ends_at"],
            exclude_id=None,
            half_open=True,
        )
    )


def event_capacity_total(session):
    """Venue capacity declared by the earliest-created overlapping session."""
    rows = sessions_overlapping(
        session["coach_ref"],
        "MEMBER_EVENT",
        session["starts_at"],
        session["ends_at"],
        half_open=True,
    )
    if not rows:
        return int(session.get("capacity_total") or 1)
    rows.sort(key=created_key)
    return int(rows[0].get("capacity_total") or 1)


# ---------------------------------------------------------------------------
# Entitlement reconciliation
# ---------------------------------------------------------------------------
def guard_status(entitlement):
    code = entitlement["benefit_code"]
    if code == "DIRECT_DEPOSIT":
        enr = enrollment_of(entitlement["member_id"])
        return "GRANTED" if (enr and enr["status"] == "ACTIVE") else "NONE"
    holding = DB.holdings.get(entitlement["source_holding_id"])
    return "GRANTED" if (holding and holding["adoption_status"] == "ADOPTED") else "NONE"


def entitlement_unlocked(entitlement):
    """True when the unlocking condition for the benefit code currently holds."""
    code = entitlement["benefit_code"]
    if code == "DIRECT_DEPOSIT":
        enr = enrollment_of(entitlement["member_id"])
        return bool(enr and enr["status"] == "ACTIVE")
    holding = DB.holdings.get(entitlement["source_holding_id"])
    return bool(holding and holding["adoption_status"] == "ADOPTED")


def reconciliation_state(entitlement):
    """IN_SYNC when the stored status agrees with the guard verdict, else DRIFT.

    The guard verdict is the status the unlocking condition implies right now
    (GRANTED when a non-deposit benefit's source holding is adopted; GRANTED when
    a direct-deposit benefit's enrolment is active; PENDING_REQUALIFICATION while a
    suspended holding or an inactive enrolment blocks it; REVOKED once the holding
    is closed; PENDING before the holding unlocks it). A row rewritten by the
    reconciliation operation reports RECONCILED.
    """
    if entitlement.get("_reconciled"):
        return "RECONCILED"
    return (
        "IN_SYNC"
        if entitlement["entitlement_status"] == guard_verdict(entitlement)
        else "DRIFT_REPORTED"
    )


def guard_verdict(entitlement):
    """The status the entitlement's unlocking condition implies at this instant."""
    if entitlement["benefit_code"] == "DIRECT_DEPOSIT":
        enr = enrollment_of(entitlement["member_id"])
        return "GRANTED" if (enr and enr["status"] == "ACTIVE") else "PENDING_REQUALIFICATION"
    holding = DB.holdings.get(entitlement["source_holding_id"])
    if holding is None:
        return "PENDING"
    if holding["adoption_status"] == "ADOPTED":
        return "GRANTED"
    if holding["adoption_status"] == "SUSPENDED":
        return "PENDING_REQUALIFICATION"
    if holding["adoption_status"] == "CLOSED":
        return "REVOKED"
    return "PENDING"


def counted_entitlements(member_id):
    out = []
    for e in entitlements_of(member_id):
        holding = DB.holdings.get(e["source_holding_id"])
        if holding is not None and holding["adoption_status"] == "CLOSED":
            continue
        if holding is None and e["benefit_code"] != "DIRECT_DEPOSIT":
            continue
        out.append(e)
    return out


def benefit_entitlement_state(member_id):
    member = DB.members.get(member_id)
    if member is not None and member["member_status"] == "MEMBER_LAPSED":
        return "SUSPENDED"
    rows = counted_entitlements(member_id)
    if not rows:
        return "NONE"
    granted = [e for e in rows if e["entitlement_status"] == "GRANTED"]
    if len(granted) == len(rows) and len(rows) > 0:
        return "FULL"
    if granted:
        return "PARTIAL"
    return "NONE"


def governing_rule_magnitude(entitlement):
    rule = DB.rules.get(entitlement.get("governing_rule_id"))
    if rule is None:
        return None
    return int(rule["discount_bps"])