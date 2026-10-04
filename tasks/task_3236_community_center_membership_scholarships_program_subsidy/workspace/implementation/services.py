"""Shared domain services: computed counters, sliding scale, drafts, cascades,
and the clock-driven transition engine."""
import calendar
from datetime import timedelta
from decimal import Decimal

import db
from common import (
    now_dt, today, parse_date, round_cents, round4, household_multiplier,
)

HOLD_ALLOWANCE_DAYS = 120
TRAILING_WINDOW_DAYS = 365
DOC_KINDS = {"TAX_RETURN", "PAY_STUB", "BENEFITS_LETTER"}


def age_on(birth_date_str, on_date):
    bd = parse_date(birth_date_str)
    if bd is None or on_date is None:
        return 0
    years = on_date.year - bd.year
    if (on_date.month, on_date.day) < (bd.month, bd.day):
        years -= 1
    return years


# ---------------------------------------------------------------------------
# Branch computed counters
# ---------------------------------------------------------------------------

def recompute_branch(branch):
    received = 0
    for d in db.STORES["donations"].values():
        if d["branch_id"] == branch["id"] and d["status"] == "RECEIVED" and d["designation"] == "SCHOLARSHIP":
            received += d["amount_cents"]
    obligated = 0
    for a in db.STORES["applications"].values():
        if a["branch_id"] == branch["id"] and a["status"] == "APPROVED":
            obligated += a.get("award_obligation_cents", 0) or 0
    active_count = 0
    for m in db.STORES["memberships"].values():
        if m["branch_id"] == branch["id"] and m["status"] in ("ACTIVE", "ON_HOLD"):
            active_count += 1
    changed = (
        branch.get("scholarship_pool_received_cents") != received
        or branch.get("scholarship_pool_obligated_cents") != obligated
        or branch.get("scholarship_pool_available_cents") != received - obligated
        or branch.get("active_membership_count") != active_count
    )
    branch["scholarship_pool_received_cents"] = received
    branch["scholarship_pool_obligated_cents"] = obligated
    branch["scholarship_pool_available_cents"] = received - obligated
    branch["active_membership_count"] = active_count
    if changed:
        db.touch(branch, bump=False)


# ---------------------------------------------------------------------------
# Campaign computed fields
# ---------------------------------------------------------------------------

def recompute_campaign(campaign):
    base = 0
    for d in db.STORES["donations"].values():
        if d["campaign_id"] == campaign["id"] and d["status"] == "RECEIVED":
            base += d["amount_cents"]
    campaign["base_raised_cents"] = base
    if campaign["status"] == "CLOSED":
        return  # match_pct / matched_raised_cents frozen at close
    goal = campaign["goal_cents"]
    if goal and goal > 0:
        attainment = round4(Decimal(base) / Decimal(goal))
    else:
        attainment = Decimal("0")
    if attainment < Decimal("0.50"):
        match = 0
    elif attainment < Decimal("1"):
        match = 0.10
    else:
        match = 0.25
    campaign["match_pct"] = match
    campaign["matched_raised_cents"] = round_cents(Decimal(base) * (Decimal(1) + Decimal(str(match))))


# ---------------------------------------------------------------------------
# Sliding scale
# ---------------------------------------------------------------------------

def compute_income_ratio(annual_income_cents, household_size, ami_base_cents):
    mult = household_multiplier(household_size)
    denom = Decimal(ami_base_cents) * mult
    return round4(Decimal(annual_income_cents) / denom)


def award_pct_for_ratio(ratio):
    """ratio is a Decimal rounded to 4dp. Returns 0.75/0.50/0.25 or None if ineligible."""
    if ratio < Decimal("0.30"):
        return 0.75
    if ratio < Decimal("0.50"):
        return 0.50
    if ratio < Decimal("0.80"):
        return 0.25
    return None


def association_for_branch(branch):
    return db.STORES["associations"].get(branch["association_id"])


# ---------------------------------------------------------------------------
# Draft amount calculation
# ---------------------------------------------------------------------------

def draft_amount_and_kind(membership, category, prorate=False, activation_date=None):
    if membership["status"] == "ON_HOLD":
        base = category["hold_fee_cents"]
        kind = "HOLD_FEE"
    else:
        base = category["monthly_dues_cents"]
        kind = "REGULAR"
    amount = round_cents(Decimal(base) * (Decimal(1) - Decimal(str(membership["assistance_pct"]))))
    if prorate and activation_date is not None:
        days_in_month = calendar.monthrange(activation_date.year, activation_date.month)[1]
        remaining = days_in_month - activation_date.day + 1  # inclusive from activation day
        amount = round_cents(Decimal(amount) * Decimal(remaining) / Decimal(days_in_month))
    return amount, kind


def reprice_pending_drafts(membership):
    """Recompute amount_cents of PENDING drafts under current status/assistance."""
    category = db.STORES["categories"].get(membership["category_id"])
    if category is None:
        return
    for d in db.STORES["drafts"].values():
        if d["membership_id"] == membership["id"] and d["status"] == "PENDING" and d["kind"] != "JOINING_FEE":
            amount, kind = draft_amount_and_kind(membership, category)
            d["amount_cents"] = amount
            d["kind"] = kind
            db.touch(d, bump=False)


# ---------------------------------------------------------------------------
# Session roster counters
# ---------------------------------------------------------------------------

def refresh_session_counts(session):
    enrolled = 0
    waitlisted = []
    for r in db.STORES["registrations"].values():
        if r["session_id"] != session["id"]:
            continue
        if r["status"] == "REGISTERED":
            enrolled += 1
        elif r["status"] == "WAITLISTED":
            waitlisted.append(r)
    # FIFO order: existing positions define the queue; never-positioned entries
    # (freshly waitlisted) append at the tail in arrival order. The logical
    # clock makes created_at ties common, so id is never used to order the
    # waitlist ("ties broken by earliest created_at, never by id").
    waitlisted.sort(key=lambda r: (
        r["waitlist_position"] if r.get("waitlist_position") is not None else 1_000_000,
        r["created_at"],
    ))
    for idx, r in enumerate(waitlisted, start=1):
        r["waitlist_position"] = idx
    session["enrolled_count"] = enrolled
    session["waitlist_count"] = len(waitlisted)


def effective_capacity(session):
    program = db.STORES["programs"].get(session["program_id"])
    if program is None:
        return session["capacity"]
    if program.get("is_licensed_childcare"):
        ratio = program.get("licensed_children_per_staff") or 0
        return min(session["capacity"], ratio * len(session.get("staff_member_ids") or []))
    return session["capacity"]


# ---------------------------------------------------------------------------
# Registration fee
# ---------------------------------------------------------------------------

def classify_registrant(member, session, branch):
    """Return (registrant_class, membership_at_branch_or_None)."""
    mid = member["id"]
    memberships = [m for m in db.STORES["memberships"].values()
                   if mid in (m.get("member_ids") or []) and m["status"] in ("ACTIVE", "ON_HOLD")]
    home = [m for m in memberships if m["branch_id"] == branch["id"]]
    if home:
        return "HOME_MEMBER", home[0]
    if memberships:
        return "ASSOCIATION_MEMBER", None
    if member.get("visiting_association_name"):
        return "RECIPROCITY_VISITOR", None
    return "NON_MEMBER", None


def compute_registration_fee(registrant_class, membership, program):
    base = program["base_fee_cents"]
    if registrant_class in ("HOME_MEMBER", "ASSOCIATION_MEMBER"):
        gross = base
    elif registrant_class == "RECIPROCITY_VISITOR":
        gross = round_cents(Decimal(base) * Decimal("1.25"))
    else:  # NON_MEMBER
        gross = round_cents(Decimal(base) * Decimal(str(program["non_member_multiplier"])))
    if membership is not None:
        return round_cents(Decimal(gross) * (Decimal(1) - Decimal(str(membership["assistance_pct"]))))
    return gross


# ---------------------------------------------------------------------------
# Waitlist promotion
# ---------------------------------------------------------------------------

def promote_waitlist(session):
    """Promote waitlisted registrations while capacity allows. For licensed
    sessions, a candidate that would break the ratio is skipped (not an error)
    and the next eligible candidate is tried."""
    program = db.STORES["programs"].get(session["program_id"])
    refresh_session_counts(session)
    waiting = [r for r in db.STORES["registrations"].values()
               if r["session_id"] == session["id"] and r["status"] == "WAITLISTED"]
    waiting.sort(key=lambda r: (r.get("waitlist_position") or 0, r["created_at"]))
    for reg in waiting:
        if session["enrolled_count"] + 1 > session["capacity"]:
            break  # absolute capacity reached
        if program is not None and program.get("is_licensed_childcare"):
            ratio = program.get("licensed_children_per_staff") or 0
            max_children = ratio * len(session.get("staff_member_ids") or [])
            if session["enrolled_count"] + 1 > max_children:
                continue  # skip this candidate, seat stays open
        branch = db.STORES["branches"].get(session["branch_id"])
        member = db.STORES["members"].get(reg["member_id"])
        klass, mship = classify_registrant(member, session, branch) if member else ("NON_MEMBER", None)
        reg["status"] = "REGISTERED"
        reg["waitlist_position"] = None
        reg["registrant_class"] = klass
        reg["fee_charged_cents"] = compute_registration_fee(klass, mship, program)
        db.touch(reg, bump=False)
        session["enrolled_count"] += 1
    refresh_session_counts(session)


# ---------------------------------------------------------------------------
# Award expiry cascade
# ---------------------------------------------------------------------------

def expire_award(app):
    """APPROVED -> EXPIRED with pool release and assistance_pct reset (unless a
    renewal application is already APPROVED)."""
    if app["status"] != "APPROVED":
        return
    app["status"] = "EXPIRED"
    db.touch(app, bump=False)
    branch = db.STORES["branches"].get(app["branch_id"])
    if branch is not None:
        recompute_branch(branch)
    membership = db.STORES["memberships"].get(app["membership_id"])
    if membership is not None and membership["status"] in ("ACTIVE", "ON_HOLD"):
        renewal = None
        for other in db.STORES["applications"].values():
            if (other.get("renews_application_id") == app["id"]
                    and other["status"] == "APPROVED"
                    and other["id"] != app["id"]):
                renewal = other
                break
        if renewal is not None:
            membership["assistance_pct"] = renewal["award_pct"]
        else:
            membership["assistance_pct"] = 0
        reprice_pending_drafts(membership)


# ---------------------------------------------------------------------------
# Hold allowance interval merge
# ---------------------------------------------------------------------------

def hold_days_used(membership, current_date):
    """Merge clipped hold windows over the trailing 365 days."""
    windows = list(membership.get("hold_windows") or [])
    # The currently open hold window, if any, counts up to today.
    if membership["status"] == "ON_HOLD" and membership.get("hold_started_on"):
        start = parse_date(membership["hold_started_on"])
        if start is not None:
            windows.append((start, min(current_date, parse_date(membership["hold_until"]) or current_date)))
    lo = current_date - timedelta(days=TRAILING_WINDOW_DAYS)
    clipped = []
    for (s, e) in windows:
        cs = max(s, lo)
        ce = min(e, current_date)
        if ce > cs:
            clipped.append((cs, ce))
    clipped.sort()
    merged = []
    for (s, e) in clipped:
        if merged and s <= merged[-1][1]:  # gap of zero days merges
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    total = sum((e - s).days for (s, e) in merged)
    return total


# ---------------------------------------------------------------------------
# Clock-driven transitions
# ---------------------------------------------------------------------------

def tick_clock():
    """Evaluate every clock-driven transition against the logical clock.
    Called lazily before each request is handled, and after the clock is set."""
    now = now_dt()
    today_d = now.date()

    # 1. Reservations: APPROVED -> COMPLETED once the clock passes end_at.
    from common import parse_datetime
    for r in db.STORES["reservations"].values():
        if r["status"] == "APPROVED":
            end_at = parse_datetime(r["end_at"])
            if end_at is not None and now >= end_at:
                r["status"] = "COMPLETED"
                db.touch(r, bump=False)

    # 2. Scholarship awards: APPROVED -> EXPIRED at award_end_on.
    for a in db.STORES["applications"].values():
        if a["status"] == "APPROVED" and a.get("award_end_on"):
            end_d = parse_date(a["award_end_on"])
            if end_d is not None and today_d >= end_d:
                expire_award(a)

    # 3. Sessions: SCHEDULED -> REG_OPEN -> REG_CLOSED -> COMPLETED.
    for s in db.STORES["sessions"].values():
        member_open = parse_date(s.get("member_opens_on"))
        start_on = parse_date(s.get("start_on"))
        end_on = parse_date(s.get("end_on"))
        if s["status"] == "SCHEDULED":
            if member_open is not None and today_d >= member_open:
                s["status"] = "REG_OPEN"
                db.touch(s, bump=False)
        if s["status"] == "REG_OPEN":
            if start_on is not None and today_d > start_on:
                s["status"] = "REG_CLOSED"
                db.touch(s, bump=False)
                for reg in db.STORES["registrations"].values():
                    if reg["session_id"] == s["id"] and reg["status"] == "WAITLISTED":
                        reg["status"] = "EXPIRED"
                        reg["waitlist_position"] = None
                        db.touch(reg, bump=False)
                refresh_session_counts(s)
        if s["status"] == "REG_CLOSED":
            if end_on is not None and today_d > end_on:
                s["status"] = "COMPLETED"
                db.touch(s, bump=False)

    # 4. Memberships: auto-resume holds at hold_until; lapse after 45 days DELINQUENT.
    for m in db.STORES["memberships"].values():
        if m["status"] == "ON_HOLD" and m.get("hold_until"):
            hold_until = parse_date(m["hold_until"])
            if hold_until is not None and today_d >= hold_until:
                hs = parse_date(m["hold_started_on"])
                if hs is not None:
                    m.setdefault("hold_windows", []).append((hs, hold_until))
                m["status"] = "ACTIVE"
                m["hold_started_on"] = None
                m["hold_until"] = None
                m["hold_days_used_trailing_12mo"] = hold_days_used(m, today_d)
                db.touch(m, bump=False)
        if m["status"] == "ACTIVE" and m["draft_status"] == "DELINQUENT" and m.get("delinquent_since"):
            ds = parse_date(m["delinquent_since"])
            if ds is not None and (today_d - ds).days >= 45:
                m["status"] = "LAPSED"
                m["lapsed_on"] = today_d.isoformat()
                db.touch(m, bump=False)
                for a in db.STORES["applications"].values():
                    if a["membership_id"] == m["id"] and a["status"] == "APPROVED":
                        expire_award(a)
                branch = db.STORES["branches"].get(m["branch_id"])
                if branch is not None:
                    recompute_branch(branch)
