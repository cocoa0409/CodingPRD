"""Policy-level operations: proration, earned premium, clock-driven transitions."""
from datetime import timedelta
from decimal import Decimal

import db
import errors
from services import underwriting as uw


def round_half_up(dec):
    return uw.round_half_up(dec)


# ---------------------------------------------------------------------------
# Derived counters
# ---------------------------------------------------------------------------
OPEN_CLAIM_STATUSES = ("SUBMITTED", "IN_REVIEW", "APPROVED")


def recompute_open_claims(policy):
    n = sum(1 for c in db.claims.values()
            if c["policy_id"] == policy["id"] and c["status"] in OPEN_CLAIM_STATUSES)
    policy["open_claim_count"] = n
    acct = db.business_accounts.get(policy["business_account_id"])
    if acct:
        an = sum(1 for c in db.claims.values()
                 if c.get("reported_by") == acct["id"] and c["status"] in OPEN_CLAIM_STATUSES)
        acct["open_claim_count"] = an
        ever_paid = any(c.get("reported_by") == acct["id"] and c["status"] == "PAID"
                        for c in db.claims.values())
        acct["claims_free_flag"] = (an == 0) and not ever_paid


# ---------------------------------------------------------------------------
# Mid-term proration (scaffold calculation 4)
# ---------------------------------------------------------------------------
def remaining_days(effective_dt, term_end_dt):
    return db.day_of(term_end_dt) - db.day_of(effective_dt)


def midterm_delta(new_annual, base_annual, eff_days, term_days=365):
    diff = Decimal(int(new_annual)) - Decimal(int(base_annual))
    return round_half_up(diff * Decimal(eff_days) / Decimal(term_days))


def cancellation_credit(base_annual, rem_days, term_days=365):
    return round_half_up(
        Decimal(int(base_annual)) * Decimal("0.90") * Decimal(rem_days) / Decimal(term_days))


# ---------------------------------------------------------------------------
# Earned premium reconciliation (scaffold calculation 5)
# ---------------------------------------------------------------------------
def policy_in_force_lines(policy):
    """Current in-force lines = quote selected lines adjusted by EFFECTIVE
    endorsements in chronological order."""
    quote = db.quotes.get(policy["quote_id"])
    lines = list(quote["selected_lines"]) if quote else []
    effs = effective_endorsements(policy["id"])
    for e in effs:
        for ln in e.get("removed_lines") or []:
            if ln in lines:
                lines.remove(ln)
        for ln in e.get("added_lines") or []:
            if ln not in lines:
                lines.append(ln)
    return lines


def effective_endorsements(policy_id):
    effs = [e for e in db.endorsements.values()
            if e["policy_id"] == policy_id and e["status"] == "EFFECTIVE"]
    effs.sort(key=lambda e: (db.parse_iso(e["effective_at"]) if isinstance(e["effective_at"], str)
                             else e["effective_at"], e["_seq"]))
    return effs


def segment_bases(policy):
    """Ordered (start_day, annual_basis_cents) segments. First segment starts
    at term_start at base premium; each effective premium-affecting
    endorsement opens a new segment at its effective day."""
    term_start = db.parse_iso(policy["term_start"]) if isinstance(policy["term_start"], str) else policy["term_start"]
    segments = [(db.day_of(term_start), policy["base_annual_premium_cents"])]
    for e in effective_endorsements(policy["id"]):
        basis = e.get("new_annual_premium_cents")
        if basis is None:
            # ADDITIONAL_INSURED and LIMIT_CHANGE with no premium impact keep basis
            continue
        eff_dt = db.parse_iso(e["effective_at"]) if isinstance(e["effective_at"], str) else e["effective_at"]
        segments.append((db.day_of(eff_dt), basis))
    return segments


def earned_premium(policy):
    """Earned premium through min(clock_day, end_day)."""
    term_start = db.parse_iso(policy["term_start"]) if isinstance(policy["term_start"], str) else policy["term_start"]
    term_end = db.parse_iso(policy["term_end"]) if isinstance(policy["term_end"], str) else policy["term_end"]
    now = db.clock_now()
    start_day = db.day_of(term_start)
    end_day = db.day_of(term_end)
    if policy["status"] == "CANCELLED" and policy.get("cancelled_at"):
        cancel_dt = db.parse_iso(policy["cancelled_at"]) if isinstance(policy["cancelled_at"], str) else policy["cancelled_at"]
        end_day = db.day_of(cancel_dt)
    horizon = min(db.day_of(now), end_day)

    segments = segment_bases(policy)
    total = Decimal(0)
    for i, (seg_start, basis) in enumerate(segments):
        seg_end = segments[i + 1][0] - 1 if i + 1 < len(segments) else end_day
        # days of this segment intersecting [start_day, horizon]
        lo = max(seg_start, start_day)
        hi = min(seg_end, horizon)
        if hi >= lo:
            days = hi - lo + 1
            total += Decimal(int(basis)) * Decimal(days) / Decimal(policy["term_day_count"])
    return round_half_up(total)


# ---------------------------------------------------------------------------
# Clock-driven transitions
# ---------------------------------------------------------------------------
def advance_transitions():
    """Evaluate all pending time-driven transitions after a clock move.
    Returns list of (entity_type, entity, action) for audit."""
    now = db.clock_now()
    events = []

    # QUOTED quotes past expiry -> EXPIRED
    for q in db.quotes.values():
        if q["status"] == "QUOTED" and q.get("expires_at"):
            exp = db.parse_iso(q["expires_at"]) if isinstance(q["expires_at"], str) else q["expires_at"]
            if now >= exp:
                q["status"] = "EXPIRED"
                _touch(q)
                events.append(("Quote", q, "expire"))

    # Policies BOUND -> ACTIVE at term_start; term_end handling
    for p in db.policies.values():
        ts = db.parse_iso(p["term_start"]) if isinstance(p["term_start"], str) else p["term_start"]
        te = db.parse_iso(p["term_end"]) if isinstance(p["term_end"], str) else p["term_end"]
        if p["status"] == "BOUND" and now >= ts:
            p["status"] = "ACTIVE"
            _touch(p)
            events.append(("Policy", p, "activate"))
        if p["status"] in ("BOUND", "ACTIVE", "NON_RENEWAL_PENDING") and now >= te:
            if p["status"] == "NON_RENEWAL_PENDING":
                p["status"] = "NON_RENEWED"
                events.append(("Policy", p, "non_renewed"))
            elif p["status"] in ("BOUND", "ACTIVE"):
                p["status"] = "EXPIRED"
                events.append(("Policy", p, "expire"))
            _touch(p)

    # PENDING risk signals older than 90 days -> STALE
    for s in db.risk_signals.values():
        if s["status"] == "PENDING":
            created = db.parse_iso(s["created_at"]) if isinstance(s["created_at"], str) else s["created_at"]
            if (now - created) > timedelta(days=90):
                s["status"] = "STALE"
                _touch(s)
                events.append(("RiskSignalReport", s, "stale"))

    return events


def _touch(rec):
    rec["updated_at"] = db.fmt_iso(db.clock_now())
    if "version" in rec:
        rec["version"] += 1
