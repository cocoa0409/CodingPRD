"""Derived-field recomputation and the cascading repricing helpers."""

from db import DB, stamp_create, touch
from services import calc
from timeutil import fmt_ts, month_start, parse_ts


def utcnow():
    return DB.clock()


# ---------------------------------------------------------------------------
# Rollups
# ---------------------------------------------------------------------------
def recompute_member(member_id, bump=True):
    member = DB.members.get(member_id)
    if member is None:
        return None
    now = utcnow()
    member["product_adoption_count"] = calc.product_adoption_count(member_id)
    member["product_line_set"] = calc.product_line_set(member_id)
    member["member_tier"] = calc.member_tier_for(member_id)
    member["qualifying_deposit_balance_cents"] = calc.qualifying_deposit_balance_cents(member_id)
    member["rewards_points_balance"] = calc.rewards_points_balance(member_id)
    member["churn_risk_score"] = calc.churn_risk_score(member_id)
    member["last_qualifying_deposit_at"] = calc.last_qualifying_deposit_at(member_id)
    member["benefit_entitlement_state"] = calc.benefit_entitlement_state(member_id)
    touch(member, now, bump=bump)
    return member


def recompute_holding(holding_id, bump=True):
    holding = DB.holdings.get(holding_id)
    if holding is None:
        return None
    now = utcnow()
    holding["deposit_rate_eligible"] = calc.deposit_rate_eligible(holding_id)
    holding["cross_sell_eligible"] = calc.cross_sell_eligible(holding_id)
    holding["reunderwriting_permitted"] = calc.reunderwriting_permitted(holding_id)
    touch(holding, now, bump=bump)
    return holding


def recompute_enrollment_rollups(enrollment_id, include_missed=True):
    enr = DB.enrollments.get(enrollment_id)
    if enr is None:
        return None
    enr["consecutive_qualifying_months"] = calc.consecutive_qualifying_months(enrollment_id)
    if include_missed:
        enr["missed_cycle_count"] = calc.missed_cycle_count(enrollment_id)
    enr["requalification_due_at"] = calc.requalification_due_at(enrollment_id)
    return enr


def recompute_all_enrollments():
    for enr in DB.enrollments.values():
        recompute_enrollment_rollups(enr["id"])


def recompute_cycle_rollups(cycle_id):
    cycle = DB.cycles.get(cycle_id)
    if cycle is None:
        return None
    open_dt = parse_ts(cycle.get("opened_at"))
    due_dt = parse_ts(cycle.get("due_at"))
    if open_dt is None or due_dt is None:
        cycle["qualifying_month_count"] = 0
        cycle["qualifying_deposit_total_cents"] = 0
        return cycle
    enr = calc.enrollment_of(cycle["member_id"])
    months = []
    m = open_dt.year * 12 + (open_dt.month - 1)
    while month_start(m) < due_dt:
        months.append(m)
        m += 1
        if m - (open_dt.year * 12 + open_dt.month - 1) > 600:
            break
    count = 0
    total = 0
    if enr is not None:
        required = int(enr["required_monthly_amount_cents"])
        for m in months:
            mstart = month_start(m)
            mend = month_start(m + 1)
            qualifying = 0
            for p in calc.postings_of(enr["id"]):
                if p["posting_status"] == "REVERSED":
                    continue
                dt = parse_ts(p["posted_at"])
                if dt is None:
                    continue
                if mstart <= dt < mend and int(p["amount_cents"]) >= required:
                    qualifying += int(p["amount_cents"])
            if qualifying > 0:
                count += 1
                total += qualifying
    cycle["qualifying_month_count"] = count
    cycle["qualifying_deposit_total_cents"] = total
    return cycle


def recompute_cycle_indexes(member_id):
    rows = [c for c in DB.cycles.values() if c["member_id"] == member_id]
    rows.sort(key=lambda c: (c.get("opened_at") or "", c.get("created_at") or "", c["id"]))
    for idx, row in enumerate(rows, start=1):
        row["cycle_index"] = idx
    return rows


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
def materialise_application(loan, rule, now):
    return _create_application(loan, rule, now)


def _find_application(loan_id, rule_id):
    for a in DB.applications.values():
        if a["loan_account_id"] == loan_id and a["rule_id"] == rule_id:
            return a
    return None


def _create_application(loan, rule, now, auto=False):
    app = {
        "id": DB.next_id(),
        "loan_account_id": loan["id"],
        "rule_id": rule["id"],
        "applied_bps": int(rule["discount_bps"]),
        "application_state": "APPLIED",
        "applied_at": fmt_ts(now),
        "window_from": rule.get("effective_from"),
        "window_to": rule.get("effective_to"),
        "preempted_by_application_id": None,
        "_auto": auto,
    }
    stamp_create(app, now)
    DB.put("applications", app)
    return app


def reprice_loan(loan_id):
    """Recompute a loan's capped stack and effective rate, refreshing the stamp.

    Discount applications are attached explicitly through the declared endpoint;
    the loan's stack is the capped sum of the ones currently APPLIED. The floor
    is absolute. Before summing, any row the waterfall materialised on the
    caller's behalf is re-examined against the current candidate pool, so a rule
    that has since left the pool (an autopay rule on a loan no longer enrolled,
    a direct-deposit rule whose enrolment is no longer active) stops pricing.
    """
    loan = DB.loan_accounts.get(loan_id)
    if loan is None:
        return None
    now = utcnow()
    replenish_provisional_applications(loan)
    _demote_preempted(loan, now)
    loan["discount_stack_bps"] = calc.discount_stack_total_bps(loan)
    loan["effective_apr_bps"] = calc.loan_effective_apr_bps(loan)
    loan["last_priced_at"] = fmt_ts(now)
    touch(loan, now)
    return loan


def replenish_provisional_applications(loan):
    """Re-derive the auto-materialised slice of a provisional loan's stack.

    A provisional loan re-derives its stack on every mutation. Rows the
    waterfall wrote for the caller (never attached explicitly) track the live
    candidate pool: they are created for a rule that has just joined the pool,
    and they are removed when the rule is no longer a candidate (for example an
    autopay rule on a loan that is no longer enrolled, or a direct-deposit rule
    whose enrolment is no longer active). Rows an operator attached explicitly
    remain the caller's own record and are never discarded here.
    """
    if loan["pricing_status"] != "PROVISIONAL":
        return
    now = utcnow()
    holding = DB.holdings.get(loan.get("holding_id"))
    hold_adopted = holding is not None and holding["adoption_status"] == "ADOPTED"
    # A discount application is only admitted against an adopted holding (§3.5,
    # ladder rung 7), so the waterfall's own materialisation honours the same gate.
    candidates = calc.live_candidates(loan) if hold_adopted else []
    live = {r["id"] for r in candidates}
    for rule in candidates:
        _ensure_application(loan, rule, now)
    for app in list(calc.applications_of(loan["id"])):
        if not app.get("_auto"):
            continue
        if app["application_state"] != "APPLIED":
            continue
        if app["rule_id"] in live:
            continue
        app["application_state"] = "ROLLED_BACK"
        app["preempted_by_application_id"] = None
        touch(app, now)


def _ensure_application(loan, rule, now):
    app = _find_application(loan["id"], rule["id"])
    if app is None:
        app = _create_application(loan, rule, now, auto=True)
    elif app.get("_auto") and app["application_state"] == "ROLLED_BACK":
        # the rule has rejoined the candidate pool, so its materialised row
        # resumes pricing (an explicitly attached row is never revived here)
        app["application_state"] = "APPLIED"
        app["preempted_by_application_id"] = None
        touch(app, now)
    return app


def materialise_live_applications(member_id):
    """Price every live discount rule against a member's adopted loan holdings.

    The waterfall is evaluated when the relationship that admits the discounts
    is established — a holding becomes adopted, a loan is originated against an
    adopted holding, or a rule is activated — so the rules live at that instant
    produce their applications without the caller attaching each one by hand.
    An explicit attach remains how a caller adds one named rule.
    """
    now = utcnow()
    for loan in calc.loans_of(member_id):
        if loan["pricing_status"] != "PROVISIONAL":
            continue
        holding = DB.holdings.get(loan.get("holding_id"))
        if holding is None or holding["adoption_status"] != "ADOPTED":
            continue
        for rule in calc.live_candidates(loan):
            _ensure_application(loan, rule, now)


def _demote_preempted(loan, now):
    """Exactly one application per stacking class stays APPLIED after the waterfall.

    The winner is the class survivor chosen by the pinned sort key; every other
    candidate of that class is PREEMPTED and names the application that displaced
    it. ROLLED_BACK rows are terminal and are never revived. A loan whose pricing
    is FINAL holds its stack frozen at its application snapshots, so the
    bookkeeping is re-derived only while the loan is provisional.
    """
    if loan["pricing_status"] != "PROVISIONAL":
        return
    survivors = {r["stacking_class"]: r for r in calc.survivor_rules(loan)}
    for app in calc.applications_of(loan["id"]):
        if app["application_state"] == "ROLLED_BACK":
            continue
        rule = DB.rules.get(app["rule_id"])
        if rule is None:
            continue
        winner = survivors.get(rule["stacking_class"])
        if winner is not None and winner["id"] == app["rule_id"]:
            if app["application_state"] != "APPLIED":
                app["application_state"] = "APPLIED"
                app["preempted_by_application_id"] = None
                touch(app, now)
        else:
            winner_app = None
            if winner is not None:
                for cand in DB.applications.values():
                    if (
                        cand["loan_account_id"] == loan["id"]
                        and cand["rule_id"] == winner["id"]
                        and cand["application_state"] == "APPLIED"
                    ):
                        winner_app = cand
                        break
            if app["application_state"] != "PREEMPTED":
                app["application_state"] = "PREEMPTED"
            app["preempted_by_application_id"] = winner_app["id"] if winner_app else None
            touch(app, now)


def reprice_all_loans():
    for loan_id in list(DB.loan_accounts.keys()):
        reprice_loan(loan_id)


def reprice_member_loans(member_id):
    for loan in calc.loans_of(member_id):
        reprice_loan(loan["id"])


def refresh_member_derived(member_id):
    """Recompute holdings, enrollment rollups, entitlements and loan pricing."""
    for h in calc.holdings_of(member_id):
        recompute_holding(h["id"], bump=False)
    enr = calc.enrollment_of(member_id)
    if enr is not None:
        # The stored missed-cycle counter is a machine value: a qualifying posting
        # or a reactivation zeroes it (PRD §3.3), so a later derived refresh must
        # not re-derive the historical count over that reset.
        recompute_enrollment_rollups(enr["id"], include_missed=False)
    reprice_member_loans(member_id)
    recompute_member(member_id)


def refresh_all_members():
    for member_id in list(DB.members.keys()):
        refresh_member_derived(member_id)


# ---------------------------------------------------------------------------
# Entitlement transitions
# ---------------------------------------------------------------------------
def grant_entitlement(ent, now):
    ent["entitlement_status"] = "GRANTED"
    ent["granted_at"] = fmt_ts(now)
    ent["reconciliation_state"] = "IN_SYNC"
    touch(ent, now)
    return ent


def rollback_rule_applications(member_id, rule_id, now, only_applied=True):
    """Roll back this member's applications of a rule, then reprice the loans."""
    if not rule_id:
        return []
    touched_loans = set()
    for loan in calc.loans_of(member_id):
        for app in calc.applications_of(loan["id"]):
            if app["rule_id"] != rule_id:
                continue
            states = ("APPLIED",) if only_applied else ("APPLIED", "PREEMPTED")
            if app["application_state"] in states:
                app["application_state"] = "ROLLED_BACK"
                app["preempted_by_application_id"] = None
                touch(app, now)
                touched_loans.add(loan["id"])
    for loan_id in touched_loans:
        reprice_loan(loan_id)
    return list(touched_loans)


def revoke_entitlement(ent, now):
    ent["entitlement_status"] = "REVOKED"
    touch(ent, now)
    if ent.get("governing_rule_id"):
        rollback_rule_applications(ent["member_id"], ent["governing_rule_id"], now,
                                   only_applied=False)


def mark_entitlements_pending_requalification(member_id, holding_id=None):
    now = utcnow()
    for e in calc.entitlements_of(member_id):
        if holding_id is not None and e["source_holding_id"] != holding_id:
            continue
        if e["entitlement_status"] in ("GRANTED", "PENDING_REQUALIFICATION"):
            if holding_id is not None and e["entitlement_status"] == "GRANTED":
                e["entitlement_status"] = "PENDING_REQUALIFICATION"
                touch(e, now)
            elif holding_id is None and e["entitlement_status"] == "GRANTED":
                e["entitlement_status"] = "PENDING_REQUALIFICATION"
                touch(e, now)