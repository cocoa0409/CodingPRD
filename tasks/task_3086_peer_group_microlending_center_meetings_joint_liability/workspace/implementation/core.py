"""Core store, logical clock, envelope helpers, serializers, and domain logic.

Implements PRD.md for task_3086 (peer-group microlending). Storage is
in-memory only; the store starts completely empty on every boot.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# ---------------------------------------------------------------------------
# Constants (PRD / scaffold)
# ---------------------------------------------------------------------------
ROLES = {"ProgramAdmin", "BranchManager", "CenterManager", "FieldOfficer", "Member"}

TIER_MEDIUM_MIN = 200
TIER_LARGE_MIN = 500
MEMBER_CAP = {"SMALL": 60, "MEDIUM": 80, "LARGE": 100}
CENTER_CAP = {"SMALL": 3, "MEDIUM": 4, "LARGE": 5}
COUNTED_MEMBER_STATUSES = ("IN_TRAINING", "ELIGIBLE", "ACTIVE_BORROWER", "DELINQUENT")

FLAT_RATE = Decimal("0.004")
REHAB_RATE_STEP_1 = Decimal("0.001")
REHAB_RATE_STEP_2 = Decimal("0.002")
MIN_SAVINGS_CENTS = 200
SAVINGS_PCT = {1: Decimal("0.02"), 2: Decimal("0.03"), 3: Decimal("0.04"),
               4: Decimal("0.05"), 5: Decimal("0.05")}
CYCLE_CEILING_CENTS = {1: 100000, 2: 200000, 3: 300000, 4: 400000, 5: 500000}
LOCK_PCT = Decimal("0.10")

SCORE_BASE = 600
PER_ON_TIME = 10
PER_PROJECTED = 5
PER_MISSED = 30
PER_ATTENDED_MEETING = 2
PER_STRIKE = 15
SCORE_FLOOR = 300
SCORE_CEILING = 850

ALLOWED_RESTRUCTURE_TERMS = (12, 24, 36, 48)
TRAINING_BUFFER_MINUTES = 30

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, status, error_id, message):
        super().__init__(message)
        self.status = status
        self.error_id = error_id
        self.message = message


ERR = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_BRANCH_NOT_FOUND": 404,
    "ERR_CENTER_MANAGER_NOT_FOUND": 404,
    "ERR_CENTER_NOT_FOUND": 404,
    "ERR_PEER_GROUP_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_LOAN_NOT_FOUND": 404,
    "ERR_MEETING_NOT_FOUND": 404,
    "ERR_TRAINING_SESSION_NOT_FOUND": 404,
    "ERR_TRANSACTION_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_TIME_RANGE": 400,
    "ERR_STALE_LOAN_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_APPLICATION_NOT_DRAFT": 409,
    "ERR_APPLICATION_NOT_APPROVED": 409,
    "ERR_APPLICATION_NOT_VOTING": 409,
    "ERR_MEETING_NOT_SCHEDULED": 409,
    "ERR_MEETING_NOT_OPEN": 409,
    "ERR_MEETING_NOT_CLOSED": 409,
    "ERR_ALREADY_RECONCILED": 409,
    "ERR_MEETING_ALREADY_RECONCILED": 409,
    "ERR_TXN_NOT_POSTED": 409,
    "ERR_ACCOUNT_NOT_OPEN": 409,
    "ERR_ACCOUNT_NOT_FROZEN": 409,
    "ERR_ACCOUNT_NOT_EMPTY": 409,
    "ERR_ALREADY_VOTED": 409,
    "ERR_PLAN_NOT_SUBMITTED": 409,
    "ERR_TRAINING_NOT_SCHEDULED": 409,
    "ERR_LOAN_NOT_REPAYABLE": 409,
    "ERR_MEMBER_BLACKLISTED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_MEMBER_ALREADY_IN_GROUP": 422,
    "ERR_VOTER_NOT_GROUP_PEER": 422,
    "ERR_VOTER_IS_APPLICANT": 422,
    "ERR_LOAN_MEMBER_MISMATCH": 422,
    "ERR_MEMBER_NOT_AT_CENTER": 422,
    "ERR_MANAGER_CENTER_MISMATCH": 422,
    "ERR_MEETING_OVERLAP": 409,
    "ERR_TRAINING_SLOT_OVERLAP": 409,
    "ERR_VOTING_WINDOW_EXPIRED": 409,
    "ERR_MEETING_DAY_MISMATCH": 422,
    "ERR_GROUP_NOT_FORMING": 409,
    "ERR_GROUP_SIZE_INVALID": 409,
    "ERR_GROUP_FULL": 409,
    "ERR_GROUP_NOT_ACTIVE": 409,
    "ERR_GROUP_RESTRICTED": 409,
    "ERR_GROUP_HAS_ACTIVE_LOANS": 409,
    "ERR_MEMBER_NOT_RECRUITED": 409,
    "ERR_MEMBER_NOT_ELIGIBLE": 409,
    "ERR_MEMBER_HAS_OPEN_APPLICATION": 409,
    "ERR_MEMBER_HAS_ACTIVE_LOAN": 409,
    "ERR_ATTENDANCE_INELIGIBLE": 409,
    "ERR_NOT_CENTER_MANAGER": 409,
    "ERR_CASELOAD_CAP_EXCEEDED": 409,
    "ERR_EXPANSION_INFEASIBLE": 409,
    "ERR_LADDER_CEILING_EXCEEDED": 422,
    "ERR_COLLECTION_BELOW_SAVINGS_MINIMUM": 422,
    "ERR_COLLECTION_EXCEEDS_OUTSTANDING": 422,
    "ERR_WITHDRAWAL_EXCEEDS_AVAILABLE": 422,
    "ERR_RECONCILIATION_MISMATCH": 409,
}


def err(error_id, message):
    return ApiError(ERR[error_id], error_id, message)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


def now_dt():
    return datetime.now(timezone.utc)


def fmt_created(dt):
    """ISO 8601 UTC with exactly three fractional digits (created_at/updated_at)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def fmt_domain(dt):
    """Domain timestamps: no fractional seconds when the microsecond component
    is 0, otherwise three fractional digits."""
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Store (in-memory only; starts empty)
# ---------------------------------------------------------------------------
STORE = {
    "branches": {},
    "center_managers": {},
    "centers": {},
    "peer_groups": {},
    "members": {},
    "training_sessions": {},
    "loan_applications": {},
    "consensus_votes": {},
    "loans": {},
    "loan_restructures": {},
    "center_meetings": {},
    "meeting_attendance": {},
    "repayment_transactions": {},
    "savings_accounts": {},
    "credit_bureau_reports": {},
    "branch_expansion_plans": {},
    "withdrawals": [],
}

CLOCK = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}


def logical_now():
    return CLOCK["now"]


def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    rec["id"] = new_id()
    ts = fmt_created(now_dt())
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1


def touch(rec):
    rec["updated_at"] = fmt_created(now_dt())
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def lookup(kind, rid, error_id):
    rec = STORE[kind].get(rid)
    if rec is None:
        raise err(error_id, "Resource not found")
    return rec


def group_center(group):
    return STORE["centers"].get(group["center_id"])


def member_group(member):
    gid = member.get("peer_group_id")
    return STORE["peer_groups"].get(gid) if gid else None


def group_members(group_id, exclude_blacklisted=False):
    out = []
    for m in STORE["members"].values():
        if m.get("peer_group_id") == group_id:
            if exclude_blacklisted and m["status"] == "BLACKLISTED":
                continue
            out.append(m)
    return out


def member_savings_account(member_id):
    for a in STORE["savings_accounts"].values():
        if a["member_id"] == member_id:
            return a
    return None


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------


def require_fields(body, fields):
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_bool(v):
    return isinstance(v, bool)


def is_str(v):
    return isinstance(v, str)


def require_int(body, field):
    if not is_int(body.get(field)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return body[field]


def require_str(body, field, non_empty=True):
    v = body.get(field)
    if not is_str(v) or (non_empty and v.strip() == ""):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return v


# ---------------------------------------------------------------------------
# Pagination / envelope
# ---------------------------------------------------------------------------


def paginate(items):
    from flask import request

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset out of range")
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": has_more}


# ---------------------------------------------------------------------------
# Derived counters
# ---------------------------------------------------------------------------


def branch_tier(branch):
    m = branch["active_member_count"]
    if m >= TIER_LARGE_MIN:
        return "LARGE"
    if m >= TIER_MEDIUM_MIN:
        return "MEDIUM"
    return "SMALL"


def recompute_group_member_count(group):
    group["member_count"] = len(group_members(group["id"], exclude_blacklisted=True))


def recompute_group_delinquent_count(group):
    n = 0
    for m in group_members(group["id"]):
        for l in STORE["loans"].values():
            if l["member_id"] == m["id"] and l["status"] in ("DELINQUENT", "DEFAULTED"):
                n += 1
    group["delinquent_loan_count"] = n


def recompute_caseloads(branch_id):
    """Recompute every manager's current_caseload and the branch's
    active_member_count and total_manager_caseload (PRD 3.1)."""
    branch = STORE["branches"].get(branch_id)
    if branch is None:
        return
    branch["active_member_count"] = sum(
        1 for m in STORE["members"].values()
        if m["branch_id"] == branch_id and m["status"] in COUNTED_MEMBER_STATUSES
    )
    total = 0
    for mg in STORE["center_managers"].values():
        if mg["branch_id"] != branch_id:
            continue
        caseload = 0
        for c in STORE["centers"].values():
            if c["center_manager_id"] != mg["id"]:
                continue
            for g in STORE["peer_groups"].values():
                if g["center_id"] == c["id"]:
                    caseload += sum(
                        1 for m in group_members(g["id"])
                        if m["status"] in COUNTED_MEMBER_STATUSES
                    )
        mg["current_caseload"] = caseload
        total += caseload
    branch["total_manager_caseload"] = total


def recompute_member_streak(member):
    rows = []
    for a in STORE["meeting_attendance"].values():
        if a["member_id"] == member["id"]:
            mtg = STORE["center_meetings"].get(a["center_meeting_id"])
            if mtg and mtg["status"] == "CLOSED" and mtg.get("closed_at_dt"):
                rows.append((mtg["closed_at_dt"], a["created_at"], a["present"]))
    rows.sort(key=lambda r: (r[0], r[1]))
    streak = 0
    for _, _, present in rows:
        streak = 0 if present else streak + 1
    member["consecutive_absence_streak"] = streak


def attendance_record(meeting_id, member_id):
    for a in STORE["meeting_attendance"].values():
        if a["center_meeting_id"] == meeting_id and a["member_id"] == member_id:
            return a
    return None


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------


def rhu(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def current_rate(member):
    c = member["cured_delinquency_count"]
    if c >= 3:
        return FLAT_RATE + REHAB_RATE_STEP_2
    if c >= 1:
        return FLAT_RATE + REHAB_RATE_STEP_1
    return FLAT_RATE


def split_amounts(principal_cents, term_weeks, cycle_level, member):
    rate = current_rate(member)
    gross = Decimal(principal_cents) * (Decimal(1) + rate * term_weeks)
    weekly = rhu(gross / term_weeks)
    savings = max(MIN_SAVINGS_CENTS, rhu(SAVINGS_PCT[cycle_level] * weekly))
    return weekly, savings


def next_loan_ceiling(member):
    standard = CYCLE_CEILING_CENTS[member["cycle_level"]]
    if member["cured_delinquency_count"] >= 1:
        paid_off = [l for l in STORE["loans"].values()
                    if l["member_id"] == member["id"] and l["status"] == "PAID_OFF"]
        paid_off.sort(key=lambda l: l["created_at"], reverse=True)
        last_principal = paid_off[0]["principal_cents"]
        cap = int((Decimal("1.5") * last_principal).quantize(Decimal("1"),
                                                             rounding=ROUND_FLOOR))
        return min(standard, cap)
    return standard


def count_consumed_unpaid(loan):
    return min(loan["installments_missed"] - loan.get("arrears_retired", 0),
               loan["installments_missed"])


def clamp_score(s):
    return max(SCORE_FLOOR, min(SCORE_CEILING, s))


def provisional_score(member):
    open_loans = [l for l in STORE["loans"].values()
                  if l["member_id"] == member["id"] and l["status"] in ("ACTIVE", "DELINQUENT")]
    if not open_loans:
        return None
    loan = open_loans[0]
    remaining = loan["term_weeks"] - (loan["installments_on_time"] + loan["installments_missed"])
    if remaining < 0:
        remaining = 0
    score = (SCORE_BASE + PER_ON_TIME * loan["installments_on_time"]
             + PER_PROJECTED * remaining
             - PER_MISSED * loan["installments_missed"]
             - PER_STRIKE * member["attendance_strikes"])
    return clamp_score(score)


def final_score(member, loan):
    # The loan's lifetime window runs on the logical clock (PRD 2.4: every
    # time-dependent rule reads it): from the disbursement instant through the
    # terminal transition, inclusive at both ends.
    start = loan.get("disbursed_at_dt") or parse_iso(loan["created_at"])
    end = loan.get("terminal_at_dt") or logical_now()
    attended = 0
    for a in STORE["meeting_attendance"].values():
        if a["member_id"] != member["id"] or not a["present"]:
            continue
        mtg = STORE["center_meetings"].get(a["center_meeting_id"])
        if not mtg or mtg["status"] != "CLOSED":
            continue
        closed_marker = mtg.get("closed_at_dt") or parse_iso(mtg["updated_at"])
        if start <= closed_marker <= end:
            attended += 1
    score = (SCORE_BASE + PER_ON_TIME * loan["installments_on_time"]
             - PER_MISSED * loan["installments_missed"]
             + PER_ATTENDED_MEETING * attended
             - PER_STRIKE * member["attendance_strikes"])
    return clamp_score(score)


def compute_credit_score(member):
    loans = [l for l in STORE["loans"].values() if l["member_id"] == member["id"]]
    if not loans:
        return SCORE_BASE
    open_loans = [l for l in loans if l["status"] in ("ACTIVE", "DELINQUENT")]
    if open_loans:
        return provisional_score(member)
    terminated = [l for l in loans if l["status"] in ("PAID_OFF", "DEFAULTED")]
    terminated.sort(key=lambda l: (l.get("terminal_at_dt") or parse_iso(l["updated_at"]),
                                   l["created_at"]))
    return final_score(member, terminated[-1])


def recompute_savings(account):
    member_id = account["member_id"]
    deposits = sum(t["savings_applied_cents"]
                   for t in STORE["repayment_transactions"].values()
                   if t["member_id"] == member_id and t["status"] == "POSTED")
    withdrawn = sum(w["amount_cents"] for w in STORE["withdrawals"]
                    if w["member_id"] == member_id)
    outstanding = sum(l["principal_outstanding_cents"]
                      for l in STORE["loans"].values()
                      if l["member_id"] == member_id and l["status"] in ("ACTIVE", "DELINQUENT"))
    account["balance_cents"] = deposits - withdrawn
    account["locked_cents"] = rhu(LOCK_PCT * outstanding)
    account["withdrawable_cents"] = max(0, account["balance_cents"] - account["locked_cents"])


def last_repaid_final_score(member):
    """The FINAL report of the member's most recent terminated loan (by
    terminal time, then created_at), used by savings close precondition."""
    loans = [l for l in STORE["loans"].values()
             if l["member_id"] == member["id"] and l["status"] in ("PAID_OFF", "DEFAULTED")]
    if not loans:
        return None
    loans.sort(key=lambda l: (l.get("terminal_at_dt") or parse_iso(l["updated_at"]),
                              l["created_at"]))
    return final_score(member, loans[-1])


# ---------------------------------------------------------------------------
# Contagion / lifecycle cascades
# ---------------------------------------------------------------------------


def expire_group_voting_applications(group_id):
    for a in STORE["loan_applications"].values():
        if a["peer_group_id"] == group_id and a["status"] == "VOTING":
            a["status"] = "EXPIRED"
            touch(a)


def mark_group_restricted(group):
    if group["status"] == "ACTIVE":
        group["status"] = "RESTRICTED"
        touch(group)
        expire_group_voting_applications(group["id"])


def maybe_lift_group_restriction(group):
    recompute_group_delinquent_count(group)
    if group["status"] == "RESTRICTED" and group["delinquent_loan_count"] == 0:
        group["status"] = "ACTIVE"
        touch(group)


def freeze_account_for_blacklist(member):
    account = member_savings_account(member["id"])
    if account is not None:
        recompute_savings(account)
        account["status"] = "FROZEN"
        touch(account)


def file_bureau_report(member, loan, report_type, score):
    rec = {
        "member_id": member["id"],
        "loan_id": loan["id"],
        "report_type": report_type,
        "score_reported": score,
    }
    rec["id"] = new_id()
    rec["created_at"] = fmt_created(now_dt())
    STORE["credit_bureau_reports"][rec["id"]] = rec
    return rec


def open_savings_account_if_absent(member):
    account = member_savings_account(member["id"])
    if account is None:
        account = {
            "member_id": member["id"],
            "balance_cents": 0,
            "locked_cents": 0,
            "withdrawable_cents": 0,
            "status": "OPEN",
        }
        stamp_new(account)
        STORE["savings_accounts"][account["id"]] = account
    return account


def loan_payoff(loan):
    """Drive loan -> PAID_OFF with all side effects (PRD 3.4/3.6)."""
    member = STORE["members"][loan["member_id"]]
    loan["status"] = "PAID_OFF"
    loan["terminal_at_dt"] = logical_now()
    # Remaining scheduled installments not yet consumed count as on-time when
    # the payoff posting time is on/before their due dates.
    remaining = loan["term_weeks"] - (loan["installments_on_time"] + loan["installments_missed"])
    if remaining > 0:
        future_due = loan["next_due_dt"]
        now = logical_now()
        for _ in range(remaining):
            if now <= future_due:
                loan["installments_on_time"] += 1
            future_due = future_due + timedelta(days=7)
    touch(loan)
    report_score = final_score(member, loan)
    file_bureau_report(member, loan, "FINAL", report_score)
    group = member_group(member)
    group_restricted = group is not None and group["status"] == "RESTRICTED"
    if loan["installments_missed"] == 0 and not group_restricted:
        member["cycle_level"] = min(member["cycle_level"] + 1, 5)
    touch(member)
    account = member_savings_account(member["id"])
    if account is not None:
        recompute_savings(account)
        touch(account)


def cure_loan(loan):
    """DELINQUENT -> ACTIVE cure chain (PRD 3.6)."""
    member = STORE["members"][loan["member_id"]]
    loan["status"] = "ACTIVE"
    touch(loan)
    remaining_delinquent = any(
        l["member_id"] == member["id"] and l["status"] == "DELINQUENT"
        for l in STORE["loans"].values())
    if not remaining_delinquent and member["status"] == "DELINQUENT":
        member["status"] = "ACTIVE_BORROWER"
        member["cured_delinquency_count"] += 1
        touch(member)
    group = member_group(member)
    if group is not None:
        maybe_lift_group_restriction(group)


def sweep(now):
    """Delinquency + voting-expiry sweeps. Returns tally dict."""
    tally = {"loans_delinquent": 0, "loans_defaulted": 0, "applications_expired": 0}
    open_loans = [l for l in STORE["loans"].values() if l["status"] in ("ACTIVE", "DELINQUENT")]
    open_loans.sort(key=lambda l: (l["next_due_dt"], l["created_at"]))
    for loan in open_loans:
        was_active = loan["status"] == "ACTIVE"
        consumed = 0
        while (now - loan["next_due_dt"]).total_seconds() >= 8 * 86400:
            loan["installments_missed"] += 1
            loan["next_due_dt"] = loan["next_due_dt"] + timedelta(days=7)
            consumed += 1
        if consumed:
            if was_active:
                loan["status"] = "DELINQUENT"
                tally["loans_delinquent"] += 1
                touch(loan)
                member = STORE["members"][loan["member_id"]]
                if member["status"] == "ACTIVE_BORROWER":
                    member["status"] = "DELINQUENT"
                    touch(member)
                group = member_group(member)
                if group is not None:
                    recompute_group_delinquent_count(group)
                    mark_group_restricted(group)
            else:
                touch(loan)
        if loan["status"] == "DELINQUENT":
            consumed_unpaid = loan["installments_missed"] - loan.get("arrears_retired", 0)
            if consumed_unpaid > 0:
                oldest_unpaid_due = loan["next_due_dt"] - timedelta(days=7 * consumed_unpaid)
                if (now - oldest_unpaid_due).total_seconds() >= 30 * 86400:
                    loan["status"] = "DEFAULTED"
                    loan["terminal_at_dt"] = now
                    tally["loans_defaulted"] += 1
                    touch(loan)
                    member = STORE["members"][loan["member_id"]]
                    if member["status"] in ("ACTIVE_BORROWER", "DELINQUENT"):
                        member["status"] = "BLACKLISTED"
                        touch(member)
                    freeze_account_for_blacklist(member)
                    file_bureau_report(member, loan, "FINAL", final_score(member, loan))
                    group = member_group(member)
                    if group is not None:
                        recompute_group_member_count(group)
                        touch(group)
                        recompute_caseloads(group_center(group)["branch_id"])
    for a in STORE["loan_applications"].values():
        if a["status"] == "VOTING" and a.get("voting_deadline_dt") is not None \
                and now > a["voting_deadline_dt"]:
            a["status"] = "EXPIRED"
            touch(a)
            tally["applications_expired"] += 1
    return tally


def record_strike(member):
    """An attendance strike: recompute credit score; reject applicant's VOTING
    applications (PRD 3.7 hop 3)."""
    if member["status"] in ("ACTIVE_BORROWER", "DELINQUENT"):
        touch(member)
    for a in STORE["loan_applications"].values():
        if a["member_id"] == member["id"] and a["status"] == "VOTING":
            a["status"] = "REJECTED"
            touch(a)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def ser_branch(b):
    return {
        "id": b["id"], "name": b["name"], "tier": branch_tier(b),
        "active_member_count": b["active_member_count"],
        "total_manager_caseload": b["total_manager_caseload"],
        "created_at": b["created_at"], "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_manager(mg):
    tier = branch_tier(STORE["branches"][mg["branch_id"]])
    return {
        "id": mg["id"], "branch_id": mg["branch_id"], "full_name": mg["full_name"],
        "hired_on": mg["hired_on"], "current_caseload": mg["current_caseload"],
        "center_cap": CENTER_CAP[tier], "member_cap": MEMBER_CAP[tier],
        "created_at": mg["created_at"], "updated_at": mg["updated_at"],
        "version": mg["version"],
    }


def ser_center(c):
    return {
        "id": c["id"], "branch_id": c["branch_id"],
        "center_manager_id": c["center_manager_id"], "name": c["name"],
        "meeting_day_of_week": c["meeting_day_of_week"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_group(g):
    return {
        "id": g["id"], "center_id": g["center_id"], "name": g["name"],
        "status": g["status"], "member_count": g["member_count"],
        "completed_training_sessions": g["completed_training_sessions"],
        "delinquent_loan_count": g["delinquent_loan_count"],
        "created_at": g["created_at"], "updated_at": g["updated_at"],
        "version": g["version"],
    }


def ser_member(m):
    return {
        "id": m["id"], "branch_id": m["branch_id"], "full_name": m["full_name"],
        "national_id": m["national_id"], "peer_group_id": m.get("peer_group_id"),
        "status": m["status"], "cycle_level": m["cycle_level"],
        "cured_delinquency_count": m["cured_delinquency_count"],
        "consecutive_absence_streak": m["consecutive_absence_streak"],
        "attendance_strikes": m["attendance_strikes"],
        "credit_score": compute_credit_score(m),
        "created_at": m["created_at"], "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_session(s):
    return {
        "id": s["id"], "peer_group_id": s["peer_group_id"],
        "center_manager_id": s["center_manager_id"],
        "start_time": fmt_domain(s["start_dt"]), "end_time": fmt_domain(s["end_dt"]),
        "status": s["status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_application(a):
    return {
        "id": a["id"], "peer_group_id": a["peer_group_id"],
        "member_id": a["member_id"],
        "requested_amount_cents": a["requested_amount_cents"],
        "status": a["status"],
        "voting_deadline": (fmt_domain(a["voting_deadline_dt"])
                            if a.get("voting_deadline_dt") else None),
        "applied_ceiling_cents": a.get("applied_ceiling_cents"),
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_vote(v):
    return {
        "id": v["id"], "loan_application_id": v["loan_application_id"],
        "voter_member_id": v["voter_member_id"], "decision": v["decision"],
        "created_at": v["created_at"],
    }


def ser_loan(l):
    return {
        "id": l["id"], "member_id": l["member_id"],
        "loan_application_id": l["loan_application_id"],
        "cycle_level": l["cycle_level"], "principal_cents": l["principal_cents"],
        "term_weeks": l["term_weeks"],
        "weekly_installment_cents": l["weekly_installment_cents"],
        "savings_required_cents": l["savings_required_cents"],
        "principal_outstanding_cents": l["principal_outstanding_cents"],
        "next_due_date": fmt_domain(l["next_due_dt"]),
        "installments_on_time": l["installments_on_time"],
        "installments_missed": l["installments_missed"],
        "status": l["status"],
        "created_at": l["created_at"], "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_restructure(r):
    return {
        "id": r["id"], "loan_id": r["loan_id"],
        "new_term_weeks": r["new_term_weeks"], "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_meeting(mtg):
    return {
        "id": mtg["id"], "center_id": mtg["center_id"],
        "scheduled_start": fmt_domain(mtg["start_dt"]),
        "scheduled_end": fmt_domain(mtg["end_dt"]),
        "status": mtg["status"], "settlement_status": mtg["settlement_status"],
        "declared_cash_cents": mtg.get("declared_cash_cents"),
        "closer_user_id": mtg.get("closer_user_id"),
        "created_at": mtg["created_at"], "updated_at": mtg["updated_at"],
        "version": mtg["version"],
    }


def ser_attendance(a):
    return {
        "id": a["id"], "center_meeting_id": a["center_meeting_id"],
        "member_id": a["member_id"], "present": a["present"],
        "created_at": a["created_at"],
    }


def ser_txn(t):
    return {
        "id": t["id"], "center_meeting_id": t["center_meeting_id"],
        "loan_id": t["loan_id"], "member_id": t["member_id"],
        "amount_cents": t["amount_cents"],
        "savings_applied_cents": t["savings_applied_cents"],
        "installment_applied_cents": t["installment_applied_cents"],
        "principal_applied_cents": t["principal_applied_cents"],
        "status": t["status"],
        "created_at": t["created_at"], "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_account(a):
    recompute_savings(a)
    return {
        "id": a["id"], "member_id": a["member_id"],
        "balance_cents": a["balance_cents"], "locked_cents": a["locked_cents"],
        "withdrawable_cents": a["withdrawable_cents"], "status": a["status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_report(r):
    return {
        "id": r["id"], "member_id": r["member_id"], "loan_id": r["loan_id"],
        "report_type": r["report_type"], "score_reported": r["score_reported"],
        "created_at": r["created_at"],
    }


def ser_plan(p):
    return {
        "id": p["id"], "branch_id": p["branch_id"], "new_centers": p["new_centers"],
        "new_managers_hired": p["new_managers_hired"],
        "target_new_members": p["target_new_members"],
        "feasibility": p["feasibility"], "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }
