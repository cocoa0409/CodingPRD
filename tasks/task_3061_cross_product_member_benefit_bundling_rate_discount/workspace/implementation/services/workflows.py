"""Business workflows and the cascading side-effect chains (PRD section 3)."""

from db import DB, stamp_create, touch
from errors import (
    ERR_BENEFIT_ALREADY_GRANTED,
    ERR_ENROLLMENT_NOT_ACTIVE,
    ERR_GRACE_PERIOD_NOT_ELAPSED,
    ERR_HOLDING_HAS_ACTIVE_LOAN,
    ERR_HOLDING_NOT_ADOPTED,
    ERR_INSUFFICIENT_POINTS,
    ERR_INVALID_STATE,
    ERR_OVERRIDE_NOT_PERMITTED,
    ERR_PRINCIPAL_BELOW_ZERO,
    ERR_REDEMPTION_LIMIT_EXCEEDED,
    ERR_REQUALIFICATION_WINDOW_OPEN,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SESSION_CAPACITY_SATURATED,
    ERR_SESSION_OVERLAP,
    ApiError,
)
from services import calc, recompute
from timeutil import fmt_ts, month_index, month_start, parse_ts

CHURN_AT_RISK = calc.CHURN_AT_RISK_SCORE
CHURN_LAPSE = calc.CHURN_LAPSE_SCORE
DEPOSIT_STEP_DOWN_BPS = 50
GRACE_PERIOD_DAYS = 30
REQUALIFICATION_WINDOW_DAYS = 90
REQUALIFICATION_WINDOW_MONTHS = 3
REMEDIATION_WINDOW_DAYS = 30
CONSECUTIVE_DEPOSIT_MONTHS_REQUIRED = 3
CAREER_SESSION_POINTS = 250
MIN_REDEEM_POINTS = 1000
MAX_REDEEM_POINTS_PER_ENTRY = 500000
POINTS_PER_CENT = 100

SAFE_LEDGER_TYPES = ("EARN", "REDEEM_PRINCIPAL", "ADJUST")


def _now():
    return DB.clock()


def _days(dt, days):
    from datetime import timedelta

    return dt + timedelta(days=days)


def _notice(member_id, notice_type, reason_code=None, related_entitlement_id=None):
    now = _now()
    notice = {
        "id": DB.next_id(),
        "member_id": member_id,
        "notice_type": notice_type,
        "status": "QUEUED",
        "issued_at": fmt_ts(now),
        "effective_at": fmt_ts(now),
        "related_entitlement_id": related_entitlement_id,
        "reason_code": reason_code,
    }
    stamp_create(notice, now)
    DB.put("notices", notice)
    return notice


def _full_magnitude(ent):
    """The entitlement's full magnitude: the governing rule's, else its declared value."""
    magnitude = calc.governing_rule_magnitude(ent)
    if magnitude is not None:
        return magnitude
    return int(ent.get("_declared_value_bps", ent.get("value_bps", 0)))


def _has_queued_step_up(member_id):
    return any(
        n["member_id"] == member_id
        and n["status"] == "QUEUED"
        and n["notice_type"] == "RATE_STEP_UP"
        for n in DB.notices.values()
    )


def _has_queued_step_down(member_id):
    return any(
        n["member_id"] == member_id
        and n["status"] == "QUEUED"
        and n["notice_type"] == "RATE_STEP_DOWN"
        for n in DB.notices.values()
    )


def _void_queued_step_down(member_id):
    now = _now()
    for n in DB.notices.values():
        if (
            n["member_id"] == member_id
            and n["status"] == "QUEUED"
            and n["notice_type"] == "RATE_STEP_DOWN"
        ):
            n["status"] = "VOIDED"
            touch(n, now)


# ---------------------------------------------------------------------------
# Member lifecycle
# ---------------------------------------------------------------------------
def adopt_holding(holding):
    """PENDING/SUSPENDED -> ADOPTED with the full adoption cascade."""
    now = _now()
    member = DB.members.get(holding["member_id"])
    was_first = member["member_since_at"] is None
    holding["adoption_status"] = "ADOPTED"
    holding["adopted_at"] = fmt_ts(now)
    touch(holding, now)

    if was_first:
        member["member_since_at"] = fmt_ts(now)
        member["member_status"] = "MEMBER_ACTIVE"

    for ent in calc.entitlements_of_holding(holding["id"]):
        if ent["entitlement_status"] == "PENDING" and calc.entitlement_unlocked(ent):
            recompute.grant_entitlement(ent, now)

    recompute.recompute_member(holding["member_id"], bump=False)
    recompute.materialise_live_applications(holding["member_id"])
    if was_first or member["member_status"] == "MEMBER_AT_RISK":
        _maybe_restore_active(member)
    return holding


def suspend_holding(holding):
    now = _now()
    holding["adoption_status"] = "SUSPENDED"
    touch(holding, now)
    for ent in calc.entitlements_of_holding(holding["id"]):
        if ent["entitlement_status"] in ("GRANTED", "PENDING_REQUALIFICATION"):
            ent["entitlement_status"] = "PENDING_REQUALIFICATION"
            touch(ent, now)
    recompute.recompute_member(holding["member_id"], bump=False)
    return holding


def close_holding(holding):
    now = _now()
    holding["adoption_status"] = "CLOSED"
    holding["closed_at"] = fmt_ts(now)
    touch(holding, now)
    for ent in calc.entitlements_of_holding(holding["id"]):
        if ent["entitlement_status"] in ("GRANTED", "PENDING_REQUALIFICATION"):
            recompute.revoke_entitlement(ent, now)
            _notice(
                holding["member_id"],
                "BENEFIT_REVOCATION",
                reason_code="HOLDING_CLOSED",
                related_entitlement_id=ent["id"],
            )
    recompute.recompute_member(holding["member_id"], bump=False)
    return holding


def _maybe_restore_active(member):
    if member["member_status"] != "MEMBER_AT_RISK":
        return
    score = calc.churn_risk_score(member["id"])
    if score < CHURN_AT_RISK:
        member["member_status"] = "MEMBER_ACTIVE"
        _void_queued_step_down(member["id"])


def detect_churn(member):
    now = _now()
    member["churn_risk_score"] = calc.churn_risk_score(member["id"])
    score = member["churn_risk_score"]
    if score >= CHURN_AT_RISK and member["member_status"] == "MEMBER_ACTIVE":
        # Entering MEMBER_AT_RISK queues a RATE_STEP_DOWN notice with a
        # deposit-stopped reason, whether the crossing stops there or the member
        # then continues straight into the lapse band.
        member["member_status"] = "MEMBER_AT_RISK"
        if not _has_queued_step_down(member["id"]):
            _notice(member["id"], "RATE_STEP_DOWN", reason_code="DEPOSIT_STOPPED")
    if score >= CHURN_LAPSE and member["member_status"] in ("MEMBER_ACTIVE", "MEMBER_AT_RISK"):
        member["member_status"] = "MEMBER_LAPSED"
        for ent in calc.entitlements_of(member["id"]):
            if ent["entitlement_status"] in ("GRANTED", "PENDING_REQUALIFICATION"):
                ent["entitlement_status"] = "STEPPED_DOWN"
                ent["stepped_down_at"] = fmt_ts(now)
                touch(ent, now)
        recompute.refresh_member_derived(member["id"])
        return member
    touch(member, now)
    return member


def reinstate_member(member):
    now = _now()
    member["member_status"] = "MEMBER_ACTIVE"
    touch(member, now)
    recompute.refresh_member_derived(member["id"])
    return member


def reset_to_prospect(member):
    now = _now()
    member["member_status"] = "PROSPECT"
    member["member_since_at"] = None
    member["member_tier"] = "NONE"
    touch(member, now)
    recompute.recompute_member(member["id"])
    return member


# ---------------------------------------------------------------------------
# Deposit enrolment lifecycle
# ---------------------------------------------------------------------------
def _qualifying_postings(enrollment_id, after=None):
    enr = DB.enrollments.get(enrollment_id)
    required = int(enr["required_monthly_amount_cents"])
    now = _now()
    out = []
    for p in calc.postings_of(enrollment_id):
        if p["posting_status"] != "POSTED":
            continue
        if int(p["amount_cents"]) < required:
            continue
        dt = parse_ts(p["posted_at"])
        if dt is None or dt > now:
            continue
        if after is not None and dt < after:
            continue
        out.append(p)
    return out


def activate_enrollment(enr):
    from_state = enr["status"]
    now = _now()
    member = DB.members.get(enr["member_id"])

    if from_state == "PENDING_VERIFICATION":
        if not _qualifying_postings(enr["id"]):
            raise ApiError(ERR_INVALID_STATE)
    elif from_state == "LAPSED":
        # A lapsed enrolment is re-activated by a qualifying deposit posted after
        # the retry window opened — the grace deadline it lapsed past (PRD §3.3).
        window = parse_ts(enr.get("grace_deadline_at")) or parse_ts(enr.get("_lapsed_at"))
        if not _qualifying_postings(enr["id"], after=window):
            raise ApiError(ERR_INVALID_STATE)
    else:
        raise ApiError(ERR_INVALID_STATE)

    enr["status"] = "ACTIVE"
    enr["qualified_at"] = fmt_ts(now)
    enr["missed_cycle_count"] = 0
    enr["_lapsed_at"] = None
    touch(enr, now)
    recompute.recompute_enrollment_rollups(enr["id"])

    for ent in calc.entitlements_of(enr["member_id"]):
        if ent["benefit_code"] != "DIRECT_DEPOSIT":
            continue
        if ent["entitlement_status"] in ("PENDING", "PENDING_REQUALIFICATION", "STEPPED_DOWN"):
            ent["value_bps"] = _full_magnitude(ent)
            recompute.grant_entitlement(ent, now)

    recompute.refresh_member_derived(enr["member_id"])
    recompute.reprice_member_loans(enr["member_id"])
    _void_queued_step_down(enr["member_id"])
    _notice(enr["member_id"], "RATE_STEP_UP", reason_code="DEPOSIT_RESUMED")
    if member is not None:
        _maybe_restore_active(member)
    return enr


def lapse_enrollment(enr):
    now = _now()
    member = DB.members.get(enr["member_id"])

    if enr["status"] == "ACTIVE":
        recompute.recompute_enrollment_rollups(enr["id"])
        if int(enr["missed_cycle_count"]) < 1:
            raise ApiError(ERR_INVALID_STATE)
        earliest = _earliest_missed_month(enr)
        if earliest is None:
            raise ApiError(ERR_INVALID_STATE)
        deadline = _days(month_start(earliest + 1), GRACE_PERIOD_DAYS)
        enr["status"] = "GRACE"
        enr["grace_deadline_at"] = fmt_ts(deadline)
        touch(enr, now)
        for ent in calc.entitlements_of(enr["member_id"]):
            if ent["benefit_code"] == "DIRECT_DEPOSIT" and ent["entitlement_status"] in (
                "GRANTED",
                "PENDING_REQUALIFICATION",
            ):
                ent["entitlement_status"] = "PENDING_REQUALIFICATION"
                touch(ent, now)
        _notice(enr["member_id"], "REQUALIFICATION_REMINDER", reason_code="DEPOSIT_STOPPED")
        recompute.refresh_member_derived(enr["member_id"])
        return enr

    if enr["status"] == "GRACE":
        deadline = parse_ts(enr.get("grace_deadline_at"))
        if deadline is not None and now < deadline:
            raise ApiError(ERR_GRACE_PERIOD_NOT_ELAPSED)
        enr["status"] = "LAPSED"
        enr["_lapsed_at"] = fmt_ts(now)
        touch(enr, now)
        primary = None
        for ent in calc.entitlements_of(enr["member_id"]):
            if ent["benefit_code"] != "DIRECT_DEPOSIT":
                continue
            if ent["entitlement_status"] in ("GRANTED", "PENDING_REQUALIFICATION"):
                ent["entitlement_status"] = "STEPPED_DOWN"
                ent["value_bps"] = max(0, int(ent["value_bps"]) - DEPOSIT_STEP_DOWN_BPS)
                ent["stepped_down_at"] = fmt_ts(now)
                touch(ent, now)
                if primary is None:
                    primary = ent
        _lapse_loans(enr["member_id"])
        _notice(
            enr["member_id"],
            "RATE_STEP_DOWN",
            reason_code="DEPOSIT_STOPPED",
            related_entitlement_id=primary["id"] if primary else None,
        )
        recompute.refresh_member_derived(enr["member_id"])
        if member is not None and member["member_status"] == "MEMBER_ACTIVE":
            if member["churn_risk_score"] >= CHURN_AT_RISK:
                member["member_status"] = "MEMBER_AT_RISK"
        return enr

    raise ApiError(ERR_INVALID_STATE)


def _earliest_missed_month(enr):
    qualified = parse_ts(enr.get("qualified_at"))
    if qualified is None:
        return None
    for m in range(month_index(qualified), month_index(_now())):
        if not calc.month_qualifies(enr["id"], m):
            return m
    return None


def _lapse_loans(member_id):
    now = _now()
    for loan in calc.loans_of(member_id):
        if loan["pricing_status"] not in ("PROVISIONAL", "FINAL"):
            continue
        rolled = False
        for app in calc.applications_of(loan["id"]):
            rule = DB.rules.get(app["rule_id"])
            if rule is None or app["application_state"] != "APPLIED":
                continue
            if rule.get("requires_direct_deposit"):
                app["application_state"] = "ROLLED_BACK"
                app["preempted_by_application_id"] = None
                touch(app, now)
                rolled = True
        if loan["pricing_status"] == "FINAL":
            loan["pricing_status"] = "STEPPED_DOWN"
        recompute.reprice_loan(loan["id"])
        del rolled


def post_deposit(enr, amount_cents, posted_at, holding=None):
    now = _now()
    posting = {
        "id": DB.next_id(),
        "enrollment_id": enr["id"],
        "member_id": enr["member_id"],
        "holding_id": holding["id"] if holding is not None else None,
        "amount_cents": int(amount_cents),
        "posted_at": posted_at,
        "posting_status": "POSTED",
    }
    stamp_create(posting, now)
    DB.put("deposit_postings", posting)

    if holding is not None:
        holding["balance_cents"] = int(holding.get("balance_cents") or 0) + int(amount_cents)
        touch(holding, now)

    required = int(enr["required_monthly_amount_cents"])
    if int(amount_cents) >= required:
        enr["last_deposit_at"] = posted_at
        enr["missed_cycle_count"] = 0
        touch(enr, now)
        # A qualifying posting resets the missed-cycle counter (PRD §3.3); that
        # reset is the stored value, not a re-derivation of the historical count.
        recompute.recompute_enrollment_rollups(enr["id"], include_missed=False)
    else:
        recompute.recompute_enrollment_rollups(enr["id"])

    if enr["status"] == "GRACE":
        deadline = parse_ts(enr.get("grace_deadline_at"))
        if int(amount_cents) >= required and (deadline is None or now < deadline):
            _resume_from_grace(enr, now)
    elif enr["status"] == "ACTIVE":
        # a posting that qualifies returns a stepped-down deposit benefit to
        # full value and lifts the member's deposit-rate eligibility
        for ent in calc.entitlements_of(enr["member_id"]):
            if (
                ent["benefit_code"] == "DIRECT_DEPOSIT"
                and ent["entitlement_status"] == "STEPPED_DOWN"
                and int(amount_cents) >= required
            ):
                ent["value_bps"] = _full_magnitude(ent)
                recompute.grant_entitlement(ent, now)
        _void_queued_step_down(enr["member_id"])

    recompute.refresh_member_derived(enr["member_id"])
    return enr


def _resume_from_grace(enr, now):
    enr["status"] = "ACTIVE"
    enr["missed_cycle_count"] = 0
    touch(enr, now)
    recompute.recompute_enrollment_rollups(enr["id"], include_missed=False)
    for ent in calc.entitlements_of(enr["member_id"]):
        if ent["benefit_code"] == "DIRECT_DEPOSIT" and ent["entitlement_status"] == "PENDING_REQUALIFICATION":
            recompute.grant_entitlement(ent, now)
    _void_queued_step_down(enr["member_id"])
    if not _has_queued_step_up(enr["member_id"]):
        _notice(enr["member_id"], "RATE_STEP_UP", reason_code="DEPOSIT_RESUMED")
    member = DB.members.get(enr["member_id"])
    if member is not None:
        _maybe_restore_active(member)


def reverse_deposit(posting):
    now = _now()
    posting["posting_status"] = "REVERSED"
    touch(posting, now)
    enr = DB.enrollments.get(posting["enrollment_id"])
    if enr is not None:
        recompute.recompute_enrollment_rollups(enr["id"])
        recompute.refresh_member_derived(enr["member_id"])
    return enr


# ---------------------------------------------------------------------------
# Requalification cycles
# ---------------------------------------------------------------------------
def evaluate_cycle(cycle):
    now = _now()
    recompute.recompute_cycle_rollups(cycle["id"])
    member_id = cycle["member_id"]
    due = parse_ts(cycle.get("due_at"))
    count = int(cycle["qualifying_month_count"])
    member = DB.members.get(member_id)

    if cycle["status"] == "OPEN":
        if due is not None and now < due:
            raise ApiError(ERR_REQUALIFICATION_WINDOW_OPEN)
        if count >= CONSECUTIVE_DEPOSIT_MONTHS_REQUIRED:
            return _cycle_passed(cycle, now, finalize_loans=True)
        return _cycle_failed(cycle, now)

    if cycle["status"] == "REMEDIATION":
        if count >= CONSECUTIVE_DEPOSIT_MONTHS_REQUIRED:
            return _cycle_passed(cycle, now, finalize_loans=True)
        if due is not None and now >= due:
            return _cycle_failed(cycle, now)
        raise ApiError(ERR_REQUALIFICATION_WINDOW_OPEN)

    del member
    raise ApiError(ERR_INVALID_STATE)


def _cycle_passed(cycle, now, finalize_loans=True):
    member_id = cycle["member_id"]
    cycle["status"] = "PASSED"
    cycle["evaluated_at"] = fmt_ts(now)
    touch(cycle, now)

    enr = calc.enrollment_of(member_id)
    if enr is not None and enr["status"] in ("ACTIVE", "GRACE"):
        enr["status"] = "ACTIVE"
        touch(enr, now)

    for ent in calc.entitlements_of(member_id):
        if ent["entitlement_status"] in ("PENDING_REQUALIFICATION", "STEPPED_DOWN"):
            recompute.grant_entitlement(ent, now)
        elif ent["entitlement_status"] == "PENDING" and calc.entitlement_unlocked(ent):
            recompute.grant_entitlement(ent, now)

    if finalize_loans:
        for loan in calc.loans_of(member_id):
            if loan["pricing_status"] in ("PROVISIONAL", "STEPPED_DOWN"):
                loan["pricing_status"] = "FINAL"
                recompute.reprice_loan(loan["id"])

    member = DB.members.get(member_id)
    if member is not None:
        recompute.recompute_member(member_id)
        _maybe_restore_active(member)
        recompute.recompute_member(member_id)
    return cycle


def _cycle_failed(cycle, now):
    member_id = cycle["member_id"]
    cycle["status"] = "FAILED"
    cycle["evaluated_at"] = fmt_ts(now)
    touch(cycle, now)

    for loan in calc.loans_of(member_id):
        if loan["pricing_status"] == "FINAL":
            loan["pricing_status"] = "PROVISIONAL"
            recompute.reprice_loan(loan["id"])

    for ent in calc.entitlements_of(member_id):
        if ent["benefit_code"] == "LOAN_RATE_DISCOUNT" and ent["entitlement_status"] == "GRANTED":
            ent["entitlement_status"] = "PENDING_REQUALIFICATION"
            touch(ent, now)

    recompute.recompute_member(member_id)
    return cycle


def open_remediation(cycle):
    now = _now()
    cycle["status"] = "REMEDIATION"
    due = parse_ts(cycle.get("due_at")) or now
    cycle["due_at"] = fmt_ts(_days(due, REMEDIATION_WINDOW_DAYS))
    touch(cycle, now)
    _notice(cycle["member_id"], "REQUALIFICATION_REMINDER", reason_code="TIER_DOWNGRADE")
    return cycle


def close_cycle(cycle):
    now = _now()
    cycle["status"] = "CLOSED"
    cycle["evaluated_at"] = fmt_ts(now)
    touch(cycle, now)
    recompute.recompute_cycle_indexes(cycle["member_id"])
    successor = {
        "id": DB.next_id(),
        "member_id": cycle["member_id"],
        "cycle_index": int(cycle["cycle_index"]) + 1,
        "opened_at": fmt_ts(now),
        "due_at": fmt_ts(_days(now, REQUALIFICATION_WINDOW_DAYS)),
        "evaluated_at": None,
        "status": "OPEN",
        "qualifying_month_count": 0,
        "qualifying_deposit_total_cents": 0,
    }
    stamp_create(successor, now)
    DB.put("cycles", successor)
    recompute.recompute_cycle_indexes(cycle["member_id"])
    return successor


# ---------------------------------------------------------------------------
# Loan pricing
# ---------------------------------------------------------------------------
def apply_waterfall(loan):
    """Re-derive PREEMPTED/APPLIED bookkeeping and reprice the loan."""
    now = _now()
    survivors = {r["stacking_class"]: r for r in calc.survivor_rules(loan)}
    for app in calc.applications_of(loan["id"]):
        if app["application_state"] != "APPLIED":
            continue
        rule = DB.rules.get(app["rule_id"])
        if rule is None:
            continue
        survivor = survivors.get(rule["stacking_class"])
        if survivor is None or survivor["id"] != app["rule_id"]:
            app["application_state"] = "PREEMPTED"
            touch(app, now)
    recompute.reprice_loan(loan["id"])
    return loan


def finalize_pricing(loan):
    now = _now()
    member = DB.members.get(loan["member_id"])
    cycle = latest_cycle(loan["member_id"])
    if cycle is not None and cycle["status"] != "PASSED":
        raise ApiError(ERR_INVALID_STATE)
    if member["member_status"] not in ("MEMBER_ACTIVE", "MEMBER_AT_RISK"):
        raise ApiError(ERR_INVALID_STATE)
    enr = calc.enrollment_of(loan["member_id"])
    for app in calc.applications_of(loan["id"]):
        if app["application_state"] != "APPLIED":
            continue
        rule = DB.rules.get(app["rule_id"])
        if rule is not None and rule.get("requires_direct_deposit"):
            if not (enr and enr["status"] == "ACTIVE"):
                raise ApiError(ERR_ENROLLMENT_NOT_ACTIVE)
    loan["pricing_status"] = "FINAL"
    touch(loan, now)
    recompute.reprice_loan(loan["id"])
    holding = DB.holdings.get(loan["holding_id"])
    if holding is not None:
        recompute.recompute_holding(holding["id"])
    return loan


def latest_cycle(member_id):
    rows = [c for c in DB.cycles.values() if c["member_id"] == member_id]
    if not rows:
        return None
    rows.sort(key=lambda c: (c.get("opened_at") or "", c.get("created_at") or "", c["id"]))
    return rows[-1]


def attach_application(loan, rule, preempt_apps):
    now = _now()
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
        "_auto": False,
    }
    stamp_create(app, now)
    DB.put("applications", app)
    for prior in preempt_apps:
        prior["application_state"] = "PREEMPTED"
        prior["preempted_by_application_id"] = app["id"]
        touch(prior, now)
    recompute.reprice_loan(loan["id"])
    loan["version"] = int(loan["version"]) + 1
    return app


def rollback_application(app):
    now = _now()
    app["application_state"] = "ROLLED_BACK"
    app["preempted_by_application_id"] = None
    touch(app, now)
    recompute.reprice_loan(app["loan_account_id"])
    return app


# ---------------------------------------------------------------------------
# Rewards
# ---------------------------------------------------------------------------
def append_ledger_entry(member_id, entry_type, points_delta, loan_account_id=None,
                        source_event_code=None, principal_reduction_cents=0):
    now = _now()
    entry = {
        "id": DB.next_id(),
        "member_id": member_id,
        "loan_account_id": loan_account_id,
        "entry_type": entry_type,
        "points_delta": int(points_delta),
        "principal_reduction_cents": int(principal_reduction_cents),
        "entry_status": "POSTED",
        "source_event_code": source_event_code,
        "reversed_by_entry_id": None,
    }
    stamp_create(entry, now)
    DB.put("ledger", entry)
    return entry


def redeem_principal(member, loan, points, source_event_code):
    now = _now()
    reduction = int(points) // POINTS_PER_CENT
    entry = append_ledger_entry(
        member["id"],
        "REDEEM_PRINCIPAL",
        -int(points),
        loan_account_id=loan["id"],
        source_event_code=source_event_code,
        principal_reduction_cents=reduction,
    )
    loan["principal_cents"] = int(loan["principal_cents"]) - reduction
    loan["last_priced_at"] = fmt_ts(now)
    touch(loan, now)
    recompute.recompute_member(member["id"])
    return entry


def reconcile_rewards(member_id):
    rows = [
        e
        for e in calc.ledger_of(member_id)
        if e["entry_type"] == "REDEEM_PRINCIPAL" and e["entry_status"] == "POSTED"
    ]
    if not rows:
        return {"entries_adjusted": 0, "cumulative_reduction_cents": 0}
    total_points = sum(-int(e["points_delta"]) for e in rows)
    cumulative = total_points // POINTS_PER_CENT
    current = sum(int(e["principal_reduction_cents"]) for e in rows)
    delta = cumulative - current
    adjusted = 0
    if delta != 0:
        newest = rows[-1]
        newest["principal_reduction_cents"] = int(newest["principal_reduction_cents"]) + delta
        touch(newest, _now())
        adjusted = 1
    return {"entries_adjusted": adjusted, "cumulative_reduction_cents": cumulative}


def reverse_ledger_entry(entry):
    now = _now()
    original = entry
    compensating = append_ledger_entry(
        original["member_id"],
        "REVERSE",
        -int(original["points_delta"]),
        loan_account_id=original.get("loan_account_id"),
        source_event_code=original.get("source_event_code"),
    )
    original["entry_status"] = "REVERSED"
    original["reversed_by_entry_id"] = compensating["id"]
    touch(original, now)
    if original["entry_type"] == "REDEEM_PRINCIPAL" and original.get("loan_account_id"):
        loan = DB.loan_accounts.get(original["loan_account_id"])
        if loan is not None:
            loan["principal_cents"] = int(loan["principal_cents"]) + int(
                original["principal_reduction_cents"]
            )
            recompute.reprice_loan(loan["id"])
    recompute.recompute_member(original["member_id"])
    return original


def complete_career_session(session):
    now = _now()
    if session["session_kind"] == "CAREER_COACHING" and session.get("_earned_at") is None:
        session["_earned_at"] = fmt_ts(now)
        append_ledger_entry(
            session["member_id"],
            "EARN",
            CAREER_SESSION_POINTS,
            source_event_code="CAREER_SESSION_COMPLETED",
        )
    recompute.recompute_member(session["member_id"])
    return session


def refresh_seats(session):
    for s in DB.sessions.values():
        if s["coach_ref"] == session["coach_ref"]:
            s["seats_reserved"] = calc.session_seats_reserved(s)
    return session


def validate_career_overlap(coach_ref, starts_at, ends_at, exclude_id=None):
    if calc.sessions_overlapping(
        coach_ref, "CAREER_COACHING", starts_at, ends_at, exclude_id=exclude_id, half_open=False
    ):
        raise ApiError(ERR_SESSION_OVERLAP)


def validate_event_capacity(coach_ref, starts_at, ends_at, capacity_total, exclude_id=None):
    rows = calc.sessions_overlapping(
        coach_ref, "MEMBER_EVENT", starts_at, ends_at, exclude_id=exclude_id, half_open=True
    )
    if not rows:
        return
    rows.sort(key=lambda s: (s.get("created_at") or "", s["id"]))
    venue_capacity = int(rows[0].get("capacity_total") or 1)
    if len(rows) >= venue_capacity:
        raise ApiError(ERR_SESSION_CAPACITY_SATURATED)


def decide_check(check, outcome, actor):
    now = _now()
    if outcome == "CLEARED":
        if check["conditioning_blocked"]:
            from errors import ERR_CREDIT_CONDITIONING_BLOCKED

            raise ApiError(ERR_CREDIT_CONDITIONING_BLOCKED)
        if not check["consent_recorded"] and check["target_product_line"] != "LENDING":
            from errors import ERR_CONSENT_REQUIRED

            raise ApiError(ERR_CONSENT_REQUIRED)
        for row in DB.checks.values():
            if (
                row["id"] != check["id"]
                and row["member_id"] == check["member_id"]
                and row["target_product_line"] == check["target_product_line"]
                and row["status"] == "CLEARED"
            ):
                raise ApiError(ERR_INVALID_STATE)
        check["status"] = "CLEARED"
    elif outcome == "BLOCKED":
        if not check["conditioning_blocked"]:
            from errors import ERR_CREDIT_CONDITIONING_BLOCKED

            raise ApiError(ERR_CREDIT_CONDITIONING_BLOCKED)
        check["status"] = "BLOCKED"
    elif outcome == "REUSE_PROHIBITED":
        if check["target_product_line"] != "LENDING" or check["underwriting_reuse_permitted"]:
            from errors import ERR_REUSE_UNDERWRITING_PROHIBITED

            raise ApiError(ERR_REUSE_UNDERWRITING_PROHIBITED)
        check["status"] = "REUSE_PROHIBITED"
    else:
        raise ApiError(ERR_INVALID_STATE)

    check["decided_at"] = fmt_ts(now)
    check["decided_by"] = actor
    touch(check, now)

    if check["status"] == "CLEARED" or check["status"] == "BLOCKED":
        target = check["status"] == "CLEARED"
        for h in calc.holdings_of(check["member_id"]):
            if h["product_line"] == check["target_product_line"]:
                h["cross_sell_eligible"] = target
                touch(h, now)
    else:
        for h in calc.holdings_of(check["member_id"]):
            if h["product_line"] == "LENDING":
                h["reunderwriting_permitted"] = False
                touch(h, now)
    return check


def refresh_check_derived(check):
    member_id = check["member_id"]
    reuse = False
    for h in calc.holdings_of(member_id):
        if h["product_line"] == "LENDING" and h["adoption_status"] == "ADOPTED":
            if calc.reunderwriting_permitted(h["id"]):
                reuse = True
                break
    check["underwriting_reuse_permitted"] = reuse
    check["conditioning_blocked"] = (
        check["target_product_line"] in ("BANKING", "INVESTING")
        and not check["consent_recorded"]
    )
    return check


# ---------------------------------------------------------------------------
# Entitlement operations
# ---------------------------------------------------------------------------
def entitlement_guard_holding(ent):
    holding = DB.holdings.get(ent["source_holding_id"])
    if holding is None:
        return
    if ent["benefit_code"] == "DIRECT_DEPOSIT":
        return
    if holding["adoption_status"] != "ADOPTED":
        raise ApiError(ERR_HOLDING_NOT_ADOPTED)


def step_down_entitlement(ent):
    now = _now()
    entitlement_guard_holding(ent)
    ent["entitlement_status"] = "STEPPED_DOWN"
    if ent["benefit_code"] == "DIRECT_DEPOSIT":
        ent["value_bps"] = max(0, int(ent["value_bps"]) - DEPOSIT_STEP_DOWN_BPS)
    elif ent.get("governing_rule_id"):
        ent["value_bps"] = max(0, int(ent["value_bps"]))
    ent["stepped_down_at"] = fmt_ts(now)
    touch(ent, now)
    recompute.reprice_member_loans(ent["member_id"])
    recompute.recompute_member(ent["member_id"])
    return ent


def restore_entitlement(ent):
    now = _now()
    entitlement_guard_holding(ent)
    if not calc.entitlement_unlocked(ent):
        raise ApiError(ERR_INVALID_STATE)
    ent["value_bps"] = _full_magnitude(ent)
    recompute.grant_entitlement(ent, now)
    for loan in calc.loans_of(ent["member_id"]):
        if loan["pricing_status"] == "STEPPED_DOWN":
            loan["pricing_status"] = "FINAL"
            recompute.reprice_loan(loan["id"])
    recompute.reprice_member_loans(ent["member_id"])
    recompute.recompute_member(ent["member_id"])
    return ent


def request_override(ent, actor, reason):
    """Queue a compliance override on a stepped-down entitlement.

    The override window is open only while the step-down is still the live
    position of a member in good standing: once the member has lapsed the
    entitlement state is SUSPENDED and no override may be queued.
    """
    now = _now()
    if ent["entitlement_status"] != "STEPPED_DOWN":
        raise ApiError(ERR_OVERRIDE_NOT_PERMITTED)
    if ent.get("override_approved_by"):
        raise ApiError(ERR_OVERRIDE_NOT_PERMITTED)
    ent["override_requested_by"] = actor
    ent["override_reason"] = reason
    touch(ent, now)
    return ent


def approve_override(ent, actor):
    now = _now()
    if not ent.get("override_requested_by"):
        raise ApiError(ERR_INVALID_STATE)
    if actor == ent["override_requested_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES)
    ent["override_approved_by"] = actor
    ent["value_bps"] = _full_magnitude(ent)
    recompute.grant_entitlement(ent, now)
    recompute.reprice_member_loans(ent["member_id"])
    recompute.recompute_member(ent["member_id"])
    return ent


def reconcile_entitlements(member_id):
    now = _now()
    rows = calc.entitlements_of(member_id)
    for ent in rows:
        ent["entitlement_status"] = guard_verdict(ent)
        ent["reconciliation_state"] = "RECONCILED"
        ent["_reconciled"] = True
        touch(ent, now)
    recompute.recompute_member(member_id)
    return rows


def guard_verdict(ent):
    if ent["benefit_code"] == "DIRECT_DEPOSIT":
        enr = calc.enrollment_of(ent["member_id"])
        return "GRANTED" if (enr and enr["status"] == "ACTIVE") else "PENDING_REQUALIFICATION"
    holding = DB.holdings.get(ent["source_holding_id"])
    if holding is None:
        return "PENDING"
    if holding["adoption_status"] == "ADOPTED":
        return "GRANTED"
    if holding["adoption_status"] == "SUSPENDED":
        return "PENDING_REQUALIFICATION"
    if holding["adoption_status"] == "CLOSED":
        return "REVOKED"
    return "PENDING"


__all__ = [
    "adopt_holding",
    "suspend_holding",
    "close_holding",
    "detect_churn",
    "reinstate_member",
    "reset_to_prospect",
    "activate_enrollment",
    "lapse_enrollment",
    "post_deposit",
    "reverse_deposit",
    "evaluate_cycle",
    "open_remediation",
    "close_cycle",
    "finalize_pricing",
    "attach_application",
    "rollback_application",
    "redeem_principal",
    "reconcile_rewards",
    "reverse_ledger_entry",
    "complete_career_session",
    "refresh_seats",
    "validate_career_overlap",
    "validate_event_capacity",
    "decide_check",
    "refresh_check_derived",
    "step_down_entitlement",
    "restore_entitlement",
    "request_override",
    "approve_override",
    "reconcile_entitlements",
    "guard_verdict",
    "latest_cycle",
    "apply_waterfall",
    "append_ledger_entry",
    "ApiError",
    "ERR_BENEFIT_ALREADY_GRANTED",
    "ERR_INVALID_STATE",
]