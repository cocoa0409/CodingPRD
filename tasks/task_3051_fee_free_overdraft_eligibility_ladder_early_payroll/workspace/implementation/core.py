"""Core business logic: serializers, computed fields, calculations,
state-machine helpers, and cross-entity cascades.

All datetimes are stored internally as timezone-aware datetimes and
serialized via clock.fmt(). Every function assumes the caller holds
store.lock.
"""
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import errors
from db import store

# ---------------------------------------------------------------------------
# Constants from the scaffold / PRD
# ---------------------------------------------------------------------------
ROLES = {"Member", "ProgramOps", "SponsorBankOps", "DisputesAgent"}
ACCOUNT_TYPES = {"SPENDING", "SAVINGS"}
CURRENCIES = {"USD"}
ORIGINATOR_TYPES = {"PAYROLL", "OTHER"}
RETURN_CODES = {"R01_INSUFFICIENT", "R02_CLOSED", "R03_NO_ACCOUNT",
                "R07_REVOKED", "R08_STOPPED"}
EVENT_TYPES = {"DEPOSIT_REROUTE", "CUSHION_CYCLING", "FIRST_PARTY_FRAUD"}
DISPUTE_TYPES = {"EARLY_POSTING_REVERSAL", "DEPOSIT_RETURN_CLAIM"}
EVALUATION_MODES = {"BATCH", "REALTIME"}
DISPUTE_OUTCOMES = {"MEMBER", "BANK"}
MEMBER_STATUSES = {"ENROLLED", "ELIGIBLE", "RESTRICTED", "SUSPENDED", "CLOSED"}
ADVANCE_STATUSES = {"OPEN", "PARTIALLY_REPAID", "REPAID", "WRITTEN_OFF"}
DEPOSIT_STATUSES = {"RECEIVED_FILE", "POSTED_EARLY", "SETTLED", "RETURNED"}
ADJUSTMENT_STATUSES = {"PENDING_NOTICE", "NOTIFIED", "EFFECTIVE", "SUPERSEDED"}
RUN_STATUSES = {"OPEN", "BALANCED", "DISCREPANCY", "RESOLVED"}
CASE_STATUSES = {"FILED", "UNDER_REVIEW", "RESOLVED_MEMBER", "RESOLVED_BANK"}
ENTRY_TYPES = {"ADVANCE_CREDIT", "ADVANCE_REPAYMENT_DEBIT", "EARLY_POSTING_CREDIT",
               "EARLY_POSTING_REVERSAL", "DEPOSIT_SETTLEMENT", "DEPOSIT_RETURN_DEBIT",
               "PROVISIONAL_CREDIT", "PROVISIONAL_REVERSAL", "ADJUSTMENT"}
ENTRY_STATUSES = {"PENDING", "SETTLED", "VOIDED"}

ON_TIME_DAYS = 35
WRITE_OFF_DAYS = 60
QUALIFYING_MIN_CENTS = 10000
NOTICE_DAYS = 7
WINDOW_DAYS = 90


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def bump(entity):
    """Refresh updated_at and increment version on a versioned resource."""
    entity["updated_at"] = clock.now()
    entity["version"] += 1


def get_body():
    from flask import request
    if not request.is_json:
        return {}
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _req_str(body, field, lo=None, hi=None):
    v = body.get(field)
    if not isinstance(v, str) or (lo is not None and len(v) < lo) or \
            (hi is not None and len(v) > hi):
        raise errors.invalid_request(f"Field '{field}' must be a string of {lo}..{hi} chars.")
    return v


def _opt_str(body, field, hi=None):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or (hi is not None and len(v) > hi):
        raise errors.invalid_request(f"Field '{field}' is invalid.")
    return v


def _req_int(body, field, positive=False):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Field '{field}' must be an integer.")
    if positive and v <= 0:
        raise errors.invalid_request(f"Field '{field}' must be positive.")
    return v


def _req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise errors.invalid_request(f"Field '{field}' must be one of {sorted(allowed)}.")
    return v


def _req_dt(body, field):
    v = body.get(field)
    try:
        return clock.parse_iso(v)
    except Exception:
        raise errors.invalid_request(f"Field '{field}' must be an ISO 8601 timestamp.")


def require_occ(body, field, entity):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Field '{field}' must be an integer.")
    if v != entity["version"]:
        raise errors.stale_version(
            f"{field} ({v}) does not match current version ({entity['version']}).")


def paginate(items):
    """Apply limit/offset query params with defaults 10/0 (min 1, max 100)."""
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


# ---------------------------------------------------------------------------
# Lookups (raise ERR_NOT_FOUND when missing)
# ---------------------------------------------------------------------------
def find_member(mid):
    m = store.members.get(mid)
    if m is None:
        raise errors.not_found("Member not found.")
    return m


def find_account(aid):
    a = store.accounts.get(aid)
    if a is None:
        raise errors.not_found("DepositAccount not found.")
    return a


def find_deposit(did):
    d = store.deposits.get(did)
    if d is None:
        raise errors.not_found("DirectDeposit not found.")
    return d


def find_advance(aid):
    a = store.advances.get(aid)
    if a is None:
        raise errors.not_found("OverdraftAdvance not found.")
    return a


def find_adjustment(aid):
    a = store.adjustments.get(aid)
    if a is None:
        raise errors.not_found("CushionLimitAdjustment not found.")
    return a


def find_run(rid):
    r = store.runs.get(rid)
    if r is None:
        raise errors.not_found("ReconciliationRun not found.")
    return r


def find_dispute(did):
    d = store.disputes.get(did)
    if d is None:
        raise errors.not_found("Dispute not found.")
    return d


def member_of_account(account):
    return store.members.get(account["member_id"])


def member_of_deposit(deposit):
    account = store.accounts.get(deposit["account_id"])
    return store.members.get(account["member_id"]) if account else None


def member_of_advance(advance):
    account = store.accounts.get(advance["account_id"])
    return store.members.get(account["member_id"]) if account else None


def account_of_deposit(deposit):
    return store.accounts.get(deposit["account_id"])


def account_of_advance(advance):
    return store.accounts.get(advance["account_id"])


def _consume_provisional(account, amount):
    """Mark early-posted money spent by a debit, oldest posting first.

    Early-posted funds sit in provisional_early_cents (outside the settled
    balance). A debit spends them before touching posted_balance_cents, so the
    consumed portion must stop counting as provisional — otherwise a later
    return would claw back money the member already spent, double-counting the
    shortfall. The posted record's `posted_amount_cents` is untouched (it is
    the deposit's full early-posted amount); consumption is tracked on the
    internal `spent_cents` field. Returns the portion of the debit left to
    draw from the settled balance (and, beyond that, the cushion).
    """
    remaining = amount
    postings = sorted(
        (ep for ep in store.early_postings.values()
         if ep["status"] == "PROVISIONAL"
         and store.deposits.get(ep["deposit_id"]) is not None
         and store.deposits[ep["deposit_id"]]["account_id"] == account["id"]),
        key=lambda ep: ep["created_at"],
    )
    for ep in postings:
        if remaining <= 0:
            break
        available = ep["posted_amount_cents"] - ep.get("spent_cents", 0)
        take = min(available, remaining)
        if take > 0:
            ep["spent_cents"] = ep.get("spent_cents", 0) + take
            remaining -= take
            bump(ep)
    return remaining


def member_of_dispute(dispute):
    return store.members.get(dispute["member_id"])


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def auth():
    """Validate headers; return (user_id, role). Priority 1 + 2 role check."""
    from flask import request
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise errors.unauthenticated()
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise errors.forbidden()


def check_member_ownership(uid, role, owning_member_id):
    """Member role must act only on its own resources (priority 2)."""
    if role == "Member" and uid != owning_member_id:
        raise errors.forbidden("Member role may only act on its own resources.")


# ---------------------------------------------------------------------------
# Time-based transitions (fired on every read of relevant resources and on
# clock set)
# ---------------------------------------------------------------------------
def apply_time_transitions():
    now = clock.now()
    for adj in store.adjustments.values():
        if adj["status"] == "NOTIFIED" and now >= adj["effective_at"]:
            adj["status"] = "EFFECTIVE"
            bump(adj)
            member = store.members.get(adj["member_id"])
            if member is not None:
                member["current_limit_cents"] = adj["new_limit_cents"]
                bump(member)


# ---------------------------------------------------------------------------
# Member computed fields
# ---------------------------------------------------------------------------
def tenure_days(member):
    delta = clock.now() - member["enrolled_at"]
    days = delta.days
    return days if days > 0 else 0


def abuse_counts(member_id):
    now = clock.now()
    total = 0
    in_90d = 0
    lower = now - timedelta(days=WINDOW_DAYS)
    for ev in store.abuse_events.values():
        if ev["member_id"] != member_id:
            continue
        total += 1
        if lower < ev["created_at"] <= now:
            in_90d += 1
    return total, in_90d


# ---------------------------------------------------------------------------
# Account computed fields
# ---------------------------------------------------------------------------
def account_computed(account):
    """Return dict of computed balance fields for an account."""
    prov = sum(ep["posted_amount_cents"] - ep.get("spent_cents", 0)
               for ep in store.early_postings.values()
               if ep["status"] == "PROVISIONAL"
               and store.deposits.get(ep["deposit_id"]) is not None
               and store.deposits[ep["deposit_id"]]["account_id"] == account["id"])
    holds = account.get("holds_cents", 0)
    outstanding = sum(a["outstanding_cents"] for a in store.advances.values()
                      if a["account_id"] == account["id"]
                      and a["status"] in ("OPEN", "PARTIALLY_REPAID"))
    member = member_of_account(account)
    limit = member["current_limit_cents"] if member else 0
    if member is None or member["status"] != "ELIGIBLE" or member["deposit_reroute_flag"]:
        usable = 0
    else:
        usable = max(0, min(limit, limit - outstanding))
    posted = account["posted_balance_cents"]
    optimistic = posted + prov - holds + usable
    conservative = posted - holds
    return {
        "provisional_early_cents": prov,
        "holds_cents": holds,
        "outstanding_cushion_cents": outstanding,
        "usable_cushion_cents": usable,
        "available_optimistic_cents": optimistic,
        "available_conservative_cents": conservative,
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def serialize_member(m):
    total_abuse, abuse_90d = abuse_counts(m["id"])
    return {
        "id": m["id"],
        "external_ref": m["external_ref"],
        "full_name": m["full_name"],
        "enrolled_at": clock.fmt(m["enrolled_at"]),
        "status": m["status"],
        "tenure_days": tenure_days(m),
        "current_limit_cents": m["current_limit_cents"],
        "consecutive_on_time_repayments": m["consecutive_on_time_repayments"],
        "restricted_consecutive_repayments": m["restricted_consecutive_repayments"],
        "abuse_event_count": total_abuse,
        "abuse_events_90d": abuse_90d,
        "deposit_reroute_flag": m["deposit_reroute_flag"],
        "created_at": clock.fmt(m["created_at"]),
        "updated_at": clock.fmt(m["updated_at"]),
        "version": m["version"],
    }


def serialize_account(a):
    c = account_computed(a)
    return {
        "id": a["id"],
        "member_id": a["member_id"],
        "account_type": a["account_type"],
        "currency": a["currency"],
        "sponsor_bank_code": a["sponsor_bank_code"],
        "posted_balance_cents": a["posted_balance_cents"],
        "provisional_early_cents": c["provisional_early_cents"],
        "holds_cents": c["holds_cents"],
        "outstanding_cushion_cents": c["outstanding_cushion_cents"],
        "usable_cushion_cents": c["usable_cushion_cents"],
        "available_optimistic_cents": c["available_optimistic_cents"],
        "available_conservative_cents": c["available_conservative_cents"],
        "created_at": clock.fmt(a["created_at"]),
        "updated_at": clock.fmt(a["updated_at"]),
        "version": a["version"],
    }


def serialize_deposit(d):
    repaid = sum(al["amount_cents"] for al in store.allocations.values()
                 if al["deposit_id"] == d["id"])
    return {
        "id": d["id"],
        "account_id": d["account_id"],
        "originator_id": d["originator_id"],
        "originator_type": d["originator_type"],
        "amount_cents": d["amount_cents"],
        "settlement_date": clock.fmt(d["settlement_date"]),
        "trace_id": d["trace_id"],
        "status": d["status"],
        "qualifying": d["qualifying"],
        "repaid_cents": repaid,
        "settled_at": clock.fmt(d["settled_at"]),
        "created_at": clock.fmt(d["created_at"]),
        "updated_at": clock.fmt(d["updated_at"]),
        "version": d["version"],
    }


def serialize_early_posting(ep):
    return {
        "id": ep["id"],
        "deposit_id": ep["deposit_id"],
        "posted_amount_cents": ep["posted_amount_cents"],
        "reversal_window_end": clock.fmt(ep["reversal_window_end"]),
        "status": ep["status"],
        "created_at": clock.fmt(ep["created_at"]),
        "updated_at": clock.fmt(ep["updated_at"]),
        "version": ep["version"],
    }


def serialize_return(r):
    return {
        "id": r["id"],
        "deposit_id": r["deposit_id"],
        "return_code": r["return_code"],
        "amount_cents": r["amount_cents"],
        "shortfall_cents": r["shortfall_cents"],
        "created_at": clock.fmt(r["created_at"]),
    }


def serialize_advance(a):
    return {
        "id": a["id"],
        "account_id": a["account_id"],
        "origin": a["origin"],
        "principal_cents": a["principal_cents"],
        "outstanding_cents": a["outstanding_cents"],
        "status": a["status"],
        "repaid_at": clock.fmt(a["repaid_at"]),
        "on_time": a["on_time"],
        "created_at": clock.fmt(a["created_at"]),
        "updated_at": clock.fmt(a["updated_at"]),
        "version": a["version"],
    }


def serialize_allocation(al):
    return {
        "id": al["id"],
        "advance_id": al["advance_id"],
        "deposit_id": al["deposit_id"],
        "amount_cents": al["amount_cents"],
        "allocation_mode": al["allocation_mode"],
        "created_at": clock.fmt(al["created_at"]),
    }


def serialize_profile(p):
    return {
        "id": p["id"],
        "member_id": p["member_id"],
        "evaluation_mode": p["evaluation_mode"],
        "score": p["score"],
        "regularity_points": p["regularity_points"],
        "tenure_points": p["tenure_points"],
        "repayment_points": p["repayment_points"],
        "abuse_penalty": p["abuse_penalty"],
        "computed_limit_cents": p["computed_limit_cents"],
        "delta_vs_current_cents": p["delta_vs_current_cents"],
        "status": p["status"],
        "created_at": clock.fmt(p["created_at"]),
        "updated_at": clock.fmt(p["updated_at"]),
        "version": p["version"],
    }


def serialize_adjustment(adj):
    return {
        "id": adj["id"],
        "member_id": adj["member_id"],
        "old_limit_cents": adj["old_limit_cents"],
        "new_limit_cents": adj["new_limit_cents"],
        "direction": adj["direction"],
        "status": adj["status"],
        "effective_at": clock.fmt(adj["effective_at"]),
        "notified_at": clock.fmt(adj["notified_at"]),
        "created_at": clock.fmt(adj["created_at"]),
        "updated_at": clock.fmt(adj["updated_at"]),
        "version": adj["version"],
    }


def serialize_abuse_event(ev):
    return {
        "id": ev["id"],
        "member_id": ev["member_id"],
        "event_type": ev["event_type"],
        "evidence_note": ev["evidence_note"],
        "created_at": clock.fmt(ev["created_at"]),
    }


def serialize_ledger_entry(le):
    return {
        "id": le["id"],
        "account_id": le["account_id"],
        "reconciliation_run_id": le["reconciliation_run_id"],
        "entry_type": le["entry_type"],
        "program_leg_cents": le["program_leg_cents"],
        "bank_leg_cents": le["bank_leg_cents"],
        "status": le["status"],
        "posted_at": clock.fmt(le["posted_at"]),
        "created_at": clock.fmt(le["created_at"]),
    }


def serialize_run(run):
    return {
        "id": run["id"],
        "sponsor_bank_code": run["sponsor_bank_code"],
        "period_start": clock.fmt(run["period_start"]),
        "period_end": clock.fmt(run["period_end"]),
        "bank_reported_net_cents": run["bank_reported_net_cents"],
        "program_net_cents": run["program_net_cents"],
        "bank_net_cents": run["bank_net_cents"],
        "discrepancy_cents": run["discrepancy_cents"],
        "status": run["status"],
        "created_at": clock.fmt(run["created_at"]),
        "updated_at": clock.fmt(run["updated_at"]),
        "version": run["version"],
    }


def serialize_dispute(d):
    now = clock.now()
    return {
        "id": d["id"],
        "member_id": d["member_id"],
        "deposit_id": d["deposit_id"],
        "dispute_type": d["dispute_type"],
        "amount_cents": d["amount_cents"],
        "statement": d["statement"],
        "case_status": d["case_status"],
        "provisional_status": d["provisional_status"],
        "provisional_due_at": clock.fmt(d["provisional_due_at"]),
        "resolution_due_at": clock.fmt(d["resolution_due_at"]),
        "provisional_overdue": now > d["provisional_due_at"] and d["provisional_status"] == "NONE",
        "created_at": clock.fmt(d["created_at"]),
        "updated_at": clock.fmt(d["updated_at"]),
        "version": d["version"],
    }


# ---------------------------------------------------------------------------
# Ledger entries
# ---------------------------------------------------------------------------
def create_ledger_entry(account_id, entry_type, program_leg, status, run_id=None,
                        posted_at=None):
    le = {
        "id": new_id(),
        "account_id": account_id,
        "reconciliation_run_id": run_id,
        "entry_type": entry_type,
        "program_leg_cents": program_leg,
        "bank_leg_cents": -program_leg,
        "status": status,
        "posted_at": posted_at if posted_at is not None else clock.now(),
        "created_at": clock.now(),
    }
    store.ledger_entries[le["id"]] = le
    return le


# ---------------------------------------------------------------------------
# Advances
# ---------------------------------------------------------------------------
def create_advance(account_id, origin, principal):
    now = clock.now()
    adv = {
        "id": new_id(),
        "account_id": account_id,
        "origin": origin,
        "principal_cents": principal,
        "outstanding_cents": principal,
        "status": "OPEN",
        "repaid_at": None,
        "on_time": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.advances[adv["id"]] = adv
    return adv


def _advance_repaid(advance):
    """Handle the transition into REPAID: counters, rehabilitation."""
    now = clock.now()
    advance["status"] = "REPAID"
    advance["repaid_at"] = now
    advance["on_time"] = (now - advance["created_at"]) <= timedelta(days=ON_TIME_DAYS)
    bump(advance)
    member = member_of_advance(advance)
    if member is None:
        return
    if advance["on_time"]:
        member["consecutive_on_time_repayments"] += 1
        if member["status"] == "RESTRICTED":
            member["restricted_consecutive_repayments"] += 1
            if member["restricted_consecutive_repayments"] == 3:
                member["status"] = "ELIGIBLE"
                member["deposit_reroute_flag"] = False
    else:
        member["consecutive_on_time_repayments"] = 0
    bump(member)


def apply_allocation(advance, amount):
    """Apply a repayment allocation to an advance (state transitions)."""
    advance["outstanding_cents"] -= amount
    if advance["outstanding_cents"] == 0:
        _advance_repaid(advance)
    else:
        advance["status"] = "PARTIALLY_REPAID"
        bump(advance)


# ---------------------------------------------------------------------------
# Repayment waterfall (calc_repayment_waterfall)
# ---------------------------------------------------------------------------
def run_waterfall(account, deposit):
    """Run repayment waterfall against the account's open advances.

    Returns total allocated cents. Creates RepaymentAllocation rows and
    ADVANCE_REPAYMENT_DEBIT ledger entries (SETTLED).
    """
    open_advances = sorted(
        (a for a in store.advances.values()
         if a["account_id"] == account["id"]
         and a["status"] in ("OPEN", "PARTIALLY_REPAID")),
        key=lambda a: a["created_at"],
    )
    total_allocated = 0
    if deposit["qualifying"]:
        remaining = deposit["amount_cents"]
        for adv in open_advances:
            alloc = min(adv["outstanding_cents"], remaining)
            if alloc > 0:
                _record_allocation(adv, deposit, alloc, "WATERFALL", account)
                total_allocated += alloc
                remaining -= alloc
            if remaining == 0:
                break
    else:
        total_out = sum(a["outstanding_cents"] for a in open_advances)
        if total_out > 0:
            pool = min(deposit["amount_cents"], total_out)
            shares = []
            for adv in open_advances:
                share = int((Decimal(pool) * Decimal(adv["outstanding_cents"])
                             / Decimal(total_out)).quantize(Decimal("1"),
                                                           rounding=ROUND_HALF_UP))
                shares.append(share)
            diff = pool - sum(shares)
            if open_advances:
                shares[0] += diff
            for adv, share in zip(open_advances, shares):
                if share > 0:
                    _record_allocation(adv, deposit, share, "PRO_RATA", account)
                    total_allocated += share
    return total_allocated


def _record_allocation(advance, deposit, amount, mode, account):
    al = {
        "id": new_id(),
        "advance_id": advance["id"],
        "deposit_id": deposit["id"],
        "amount_cents": amount,
        "allocation_mode": mode,
        "created_at": clock.now(),
    }
    store.allocations[al["id"]] = al
    apply_allocation(advance, amount)
    create_ledger_entry(account["id"], "ADVANCE_REPAYMENT_DEBIT", -amount, "SETTLED")


# ---------------------------------------------------------------------------
# Eligibility scoring (calc_eligibility_score / calc_ladder_limit)
# ---------------------------------------------------------------------------
def _member_account_ids(member_id):
    return {a["id"] for a in store.accounts.values() if a["member_id"] == member_id}


def compute_score(member, mode):
    now = clock.now()
    lower = now - timedelta(days=WINDOW_DAYS)
    acct_ids = _member_account_ids(member["id"])
    n = 0
    returned_in_window = False
    for d in store.deposits.values():
        if d["account_id"] not in acct_ids or not d["qualifying"]:
            continue
        if mode == "BATCH":
            if d["settled_at"] is not None and lower < d["settled_at"] <= now:
                if d["status"] == "SETTLED":
                    n += 1
                elif d["status"] == "RETURNED":
                    returned_in_window = True
        else:  # REALTIME
            if lower < d["created_at"] <= now and d["status"] in (
                    "RECEIVED_FILE", "POSTED_EARLY", "SETTLED"):
                n += 1
            if d["settled_at"] is not None and lower < d["settled_at"] <= now \
                    and d["status"] == "RETURNED":
                returned_in_window = True
    if n >= 6:
        bucket = 400
    elif n >= 4:
        bucket = 300
    elif n >= 2:
        bucket = 150
    else:
        bucket = 0
    if returned_in_window:
        if bucket == 400:
            bucket = 300
        elif bucket == 300:
            bucket = 150
        elif bucket == 150:
            bucket = 0
    regularity_points = bucket
    t_days = tenure_days(member)
    tenure_points = int((Decimal(min(t_days, 365)) * Decimal(250)
                         / Decimal(365)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    repayment_points = min(member["consecutive_on_time_repayments"], 10) * 25
    _, abuse_90d = abuse_counts(member["id"])
    abuse_penalty = 150 * min(abuse_90d, 3)
    score = regularity_points + tenure_points + repayment_points - abuse_penalty
    score = max(0, min(1000, score))
    return {
        "score": score,
        "regularity_points": regularity_points,
        "tenure_points": tenure_points,
        "repayment_points": repayment_points,
        "abuse_penalty": abuse_penalty,
    }


def compute_ladder_limit(score, consecutive_on_time_repayments, t_days):
    if score >= 750:
        score_cap = 20000
    elif score >= 500:
        score_cap = 10000
    elif score >= 300:
        score_cap = 5000
    elif score >= 200:
        score_cap = 2000
    else:
        score_cap = 0
    if consecutive_on_time_repayments >= 5:
        repay_cap = 20000
    elif consecutive_on_time_repayments >= 3:
        repay_cap = 10000
    elif consecutive_on_time_repayments >= 1:
        repay_cap = 5000
    else:
        repay_cap = 2000
    if t_days >= 180:
        tenure_cap = 20000
    elif t_days >= 90:
        tenure_cap = 10000
    elif t_days >= 30:
        tenure_cap = 5000
    else:
        tenure_cap = 2000
    return min(score_cap, repay_cap, tenure_cap)


# ---------------------------------------------------------------------------
# Dispute deadlines (calc_dispute_deadlines)
# ---------------------------------------------------------------------------
def add_business_days(start, days):
    current = start
    added = 0
    while added < days:
        current = current + timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri
            added += 1
    return current


# ---------------------------------------------------------------------------
# Deposit early-posting gate: DISCREPANCY run window containing now
# ---------------------------------------------------------------------------
def discrepancy_blocks(sponsor_bank_code):
    now = clock.now()
    for run in store.runs.values():
        if run["sponsor_bank_code"] != sponsor_bank_code:
            continue
        if run["status"] == "DISCREPANCY" \
                and run["period_start"] <= now < run["period_end"]:
            return True
    return False
