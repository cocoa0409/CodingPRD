"""Business logic: pricing, refunds, royalties, escalations, governance caps,
circulation, standing, audience snapshots, and session overlap rules.

Every constant below is taken verbatim from PRD.md / SCAFFOLD.yaml.
"""

from datetime import date, timedelta
from decimal import Decimal

from db import store, touch
from util import err, parse_datetime_lenient, round_down, round_half_up

# --- membership pricing (membership_term_pricing) ---
BASE_ANNUAL_CENTS = 1600
BASE_MONTHLY_CENTS = 133  # round_half_up(1600 / 12), pinned by PRD
MULTI_YEAR_DISCOUNT = {1: Decimal("0.0"), 3: Decimal("0.10"), 5: Decimal("0.20")}
LOYALTY_RENEWAL_DISCOUNT = Decimal("0.05")
DISCOUNT_CAP = Decimal("0.25")

# --- royalty marginal tiers (royalty_marginal_tiers) ---
TIER1_CAP_CENTS = 100_000_000
TIER1_RATE = Decimal("0.08")
TIER2_CAP_CENTS = 500_000_000
TIER2_RATE = Decimal("0.10")
TIER3_RATE = Decimal("0.12")

# --- escalation thresholds (escalation_threshold_eval) ---
AGREEMENT_PROBATION_THRESHOLD = 3
PROVIDER_SUSPENSION_THRESHOLD = 5
TRAILING_WINDOW_DAYS = 365

# --- governance caps (fund_transfer_governance) ---
FOUNDATION_PER_TRANSFER_CAP_PCT = Decimal("0.05")
FOUNDATION_ANNUAL_OUTFLOW_CAP_PCT = Decimal("0.15")
LOBBYING_ANNUAL_DUES_CAP_PCT = Decimal("0.20")

# --- course sessions ---
ROOM_TURNOVER_BUFFER_MINUTES = 30

# --- member data usage (§2.11) ---
RESTRICTED_AUDIENCE_KEYS = {"owns_licensed_product", "benefit_product_category", "provider_customer"}
ALLOWED_AUDIENCE_KEYS = {"state_code", "min_age"}

# --- advertising standards ---
RESTRICTED_AD_CATEGORIES = {"TOBACCO", "FIREARMS", "POLITICAL"}


def clock_date():
    return store.clock_dt.date()


# ---------------------------------------------------------------------------
# Membership: age, pricing, refunds, standing
# ---------------------------------------------------------------------------

def compute_age_years(dob, on_date=None):
    """Whole years; a birthday exactly on the clock date counts as reached."""
    on = on_date or clock_date()
    return on.year - dob.year - (1 if (on.month, on.day) < (dob.month, dob.day) else 0)


def add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap target years
        return d.replace(year=d.year + years, month=2, day=28)


def price_term_cents(term_years, is_renewal):
    discount = MULTI_YEAR_DISCOUNT[term_years]
    if is_renewal:
        discount = discount + LOYALTY_RENEWAL_DISCOUNT
    effective_discount = min(DISCOUNT_CAP, discount)
    amount = Decimal(BASE_ANNUAL_CENTS) * Decimal(term_years) * (Decimal(1) - effective_discount)
    return round_half_up(amount)


def cancel_refund_cents(term, reason):
    """months_used counts calendar months started, including the cancel month."""
    on = clock_date()
    start = date.fromisoformat(term["start_date"])
    months_used = (on.year - start.year) * 12 + (on.month - start.month) + 1
    paid = term["paid_cents"]
    total_months = term["term_years"] * 12
    if reason == "VOLUNTARY":
        # Short-rate clawback of the multi-year discount.
        return max(0, paid - months_used * BASE_MONTHLY_CENTS)
    # DECEASED: pro-rata at the effective discounted monthly rate.
    effective_monthly = round_half_up(Decimal(paid) / Decimal(total_months))
    return min(paid, (total_months - months_used) * effective_monthly)


def household_terms(household_id):
    return sorted(
        (t for t in store.terms.values() if t["household_id"] == household_id),
        key=lambda r: r["_seq"],
    )


def household_status(household_id):
    """ACTIVE iff an ACTIVE term covers the clock date (half-open window)."""
    on = clock_date()
    for t in store.terms.values():
        if t["household_id"] != household_id or t["status"] != "ACTIVE":
            continue
        if date.fromisoformat(t["start_date"]) <= on < date.fromisoformat(t["end_date"]):
            return "ACTIVE"
    return "LAPSED"


def member_in_good_standing(member):
    return household_status(member["household_id"]) == "ACTIVE"


# ---------------------------------------------------------------------------
# Royalty marginal tiers
# ---------------------------------------------------------------------------

def _effective_sales(stmt):
    return stmt["audited_sales_cents"] if stmt["status"] == "FINALIZED" else stmt["reported_sales_cents"]


def _ytd_before_cents(agreement_id, year, quarter):
    """Same-calendar-year statements in strictly earlier quarters.

    SUPERSEDED statements are excluded entirely; FINALIZED contribute audited
    sales, PROVISIONAL contribute reported sales.
    """
    total = 0
    for s in store.statements.values():
        if s["license_agreement_id"] != agreement_id:
            continue
        if s["status"] not in ("PROVISIONAL", "FINALIZED"):
            continue
        if s["period_year"] == year and s["period_quarter"] < quarter:
            total += _effective_sales(s)
    return total


def marginal_royalty_cents(ytd_before, sales_cents):
    remaining = sales_cents
    total = Decimal(0)
    room1 = max(0, TIER1_CAP_CENTS - ytd_before)
    amt1 = min(remaining, room1)
    total += Decimal(amt1) * TIER1_RATE
    remaining -= amt1
    room2 = max(0, TIER2_CAP_CENTS - max(ytd_before, TIER1_CAP_CENTS))
    amt2 = min(remaining, room2)
    total += Decimal(amt2) * TIER2_RATE
    remaining -= amt2
    if remaining > 0:
        total += Decimal(remaining) * TIER3_RATE
    # round_half_up exactly once per statement
    return round_half_up(total)


def compute_royalty_cents(agreement_id, year, quarter, sales_cents):
    return marginal_royalty_cents(_ytd_before_cents(agreement_id, year, quarter), sales_cents)


# ---------------------------------------------------------------------------
# Escalation trailing counts and the oversight cascade
# ---------------------------------------------------------------------------

def _trailing_cutoff():
    return store.clock_dt - timedelta(days=TRAILING_WINDOW_DAYS)


def _counts_toward_threshold(complaint):
    if complaint["status"] != "ESCALATED":
        return False
    escalated_at = parse_datetime_lenient(complaint["escalated_at"])
    if escalated_at is None:
        return False
    # Inclusive bound: an escalation exactly 365 days old still counts.
    return escalated_at >= _trailing_cutoff()


def agreement_trailing_count(agreement_id):
    return sum(
        1
        for c in store.complaints.values()
        if c["license_agreement_id"] == agreement_id and _counts_toward_threshold(c)
    )


def provider_trailing_count(provider_id):
    count = 0
    for c in store.complaints.values():
        if not _counts_toward_threshold(c):
            continue
        agreement = store.agreements.get(c["license_agreement_id"])
        if agreement is not None and agreement["provider_id"] == provider_id:
            count += 1
    return count


def run_escalation_cascade(complaint):
    """Links 1-3 of the complaint-escalation cascade (same request)."""
    agreement = store.agreements.get(complaint["license_agreement_id"])
    if agreement is None:
        return
    provider = store.providers.get(agreement["provider_id"])
    # Link 1: agreement probation (at-least threshold; exactly 3 fires).
    if (
        agreement["status"] == "ACTIVE"
        and agreement_trailing_count(agreement["id"]) >= AGREEMENT_PROBATION_THRESHOLD
    ):
        agreement["status"] = "PROBATION"
        agreement["probation_count"] += 1
        touch(agreement)
    # Link 2: provider suspension.
    if (
        provider is not None
        and provider["status"] == "LICENSED"
        and provider_trailing_count(provider["id"]) >= PROVIDER_SUSPENSION_THRESHOLD
    ):
        provider["status"] = "SUSPENDED"
        touch(provider)
        # Link 3: every still-ACTIVE agreement of the provider -> PROBATION.
        for other in store.agreements.values():
            if other["provider_id"] == provider["id"] and other["status"] == "ACTIVE":
                other["status"] = "PROBATION"
                other["probation_count"] += 1
                touch(other)


# ---------------------------------------------------------------------------
# Fund-transfer governance
# ---------------------------------------------------------------------------

_PERMITTED_DIRECTIONS = {
    ("MEMBERSHIP_ORG", "FOUNDATION"),    # grant-making, uncapped
    ("MEMBERSHIP_ORG", "LOBBY_ARM"),     # annual lobbying cap
    ("FOUNDATION", "MEMBERSHIP_ORG"),    # per-transfer + annual caps
}


def direction_permitted(from_entity, to_entity):
    if from_entity["id"] == to_entity["id"]:
        return False
    return (from_entity["kind"], to_entity["kind"]) in _PERMITTED_DIRECTIONS


def _executed_transfers_in_clock_year(from_id=None, from_kind=None, to_kind=None):
    year = store.clock_dt.year
    matched = []
    for t in store.transfers.values():
        if t["status"] != "EXECUTED":
            continue
        executed_at = parse_datetime_lenient(t["executed_at"])
        if executed_at is None or executed_at.year != year:
            continue
        if from_id is not None and t["from_entity_id"] != from_id:
            continue
        if from_kind is not None:
            frm = store.entities.get(t["from_entity_id"])
            if frm is None or frm["kind"] != from_kind:
                continue
        if to_kind is not None:
            to = store.entities.get(t["to_entity_id"])
            if to is None or to["kind"] != to_kind:
                continue
        matched.append(t)
    return matched


def _dues_revenue_ytd_cents():
    """sum(paid_cents - refunded_cents) over terms purchased in the clock year."""
    year = store.clock_dt.year
    total = 0
    for t in store.terms.values():
        purchased_at = parse_datetime_lenient(t["purchased_at"])
        if purchased_at is None or purchased_at.year != year:
            continue
        total += t["paid_cents"] - t["refunded_cents"]
    return total


def check_fiscal_rules(transfer, from_entity, to_entity):
    """Pinned fiscal order: balance, then per-transfer cap, then annual cap."""
    amount = transfer["amount_cents"]
    if amount > from_entity["balance_cents"]:
        err("ERR_INSUFFICIENT_ENTITY_BALANCE", 422, "Transfer amount exceeds the source entity's balance")
    pair = (from_entity["kind"], to_entity["kind"])
    if pair == ("FOUNDATION", "MEMBERSHIP_ORG"):
        per_cap = round_down(Decimal(from_entity["balance_cents"]) * FOUNDATION_PER_TRANSFER_CAP_PCT)
        if amount > per_cap:
            err("ERR_PER_TRANSFER_CAP_EXCEEDED", 422, "Amount exceeds 5% of the foundation's current balance")
        annual_cap = round_down(Decimal(from_entity["balance_cents"]) * FOUNDATION_ANNUAL_OUTFLOW_CAP_PCT)
        used = sum(t["amount_cents"] for t in _executed_transfers_in_clock_year(from_id=from_entity["id"]))
        if used + amount > annual_cap:
            err("ERR_ANNUAL_CAP_EXCEEDED", 422, "Foundation annual outflow cap (15%) exceeded")
    elif pair == ("MEMBERSHIP_ORG", "LOBBY_ARM"):
        dues_ytd = _dues_revenue_ytd_cents()
        annual_cap = round_down(Decimal(dues_ytd) * LOBBYING_ANNUAL_DUES_CAP_PCT)
        used = sum(
            t["amount_cents"]
            for t in _executed_transfers_in_clock_year(from_kind="MEMBERSHIP_ORG", to_kind="LOBBY_ARM")
        )
        if used + amount > annual_cap:
            err("ERR_ANNUAL_CAP_EXCEEDED", 422, "Annual lobbying cap (20% of net dues YTD) exceeded")


# ---------------------------------------------------------------------------
# Publications / circulation
# ---------------------------------------------------------------------------

def circulation_count(publication_date_str):
    """Distinct households with an ACTIVE or RENEWED term covering the date."""
    pub_date = date.fromisoformat(publication_date_str)
    households = set()
    for t in store.terms.values():
        if t["status"] not in ("ACTIVE", "RENEWED"):
            continue
        if date.fromisoformat(t["start_date"]) <= pub_date < date.fromisoformat(t["end_date"]):
            households.add(t["household_id"])
    return len(households)


# ---------------------------------------------------------------------------
# Course sessions: lazy status + overlap rules
# ---------------------------------------------------------------------------

def session_status(session):
    end_time = parse_datetime_lenient(session["end_time"])
    return "HELD" if store.clock_dt >= end_time else "SCHEDULED"


def room_conflict(chapter_id, new_start, new_end):
    """Chapter-room rule with a 30-minute turnover buffer (any status session)."""
    buffer = timedelta(minutes=ROOM_TURNOVER_BUFFER_MINUTES)
    for s in store.sessions.values():
        if s["chapter_id"] != chapter_id:
            continue
        s_start = parse_datetime_lenient(s["start_time"])
        s_end = parse_datetime_lenient(s["end_time"])
        if (new_end + buffer) <= s_start or (s_end + buffer) <= new_start:
            continue
        return True
    return False


def instructor_conflict(instructor_name, new_start, new_end):
    """Case-sensitive instructor, all chapters, plain half-open overlap."""
    for s in store.sessions.values():
        if s["instructor_name"] != instructor_name:
            continue
        s_start = parse_datetime_lenient(s["start_time"])
        s_end = parse_datetime_lenient(s["end_time"])
        if new_start < s_end and s_start < new_end:
            return True
    return False


# ---------------------------------------------------------------------------
# Campaigns / mobilization
# ---------------------------------------------------------------------------

def campaign_status(campaign):
    today = clock_date()
    start = date.fromisoformat(campaign["start_date"])
    end = date.fromisoformat(campaign["end_date"])
    if today < start:
        return "UPCOMING"
    if today > end:
        return "CLOSED"
    return "ACTIVE"


def audience_count(spec):
    """Snapshot: good standing, not opted out, matching state_code / min_age."""
    count = 0
    for m in store.members.values():
        if not member_in_good_standing(m):
            continue
        if m["benefit_marketing_opt_out"]:
            continue
        state_code = spec.get("state_code")
        if state_code is not None:
            household = store.households.get(m["household_id"])
            if household is None or household["state_code"] != state_code:
                continue
        min_age = spec.get("min_age")
        if min_age is not None:
            dob = date.fromisoformat(m["date_of_birth"])
            if compute_age_years(dob) < min_age:
                continue
        count += 1
    return count
