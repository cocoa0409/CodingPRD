"""Shared lookups, domain helpers, and cascade / estimate / report logic."""
from datetime import timedelta

from core import ApiError, db, dump, rhu, sort_created, touch

# ---------------------------------------------------------------------------
# Domain enums
# ---------------------------------------------------------------------------
FAMILIES = ("CARDIAC", "ORTHO_JOINT", "BARIATRIC", "SPINE")
READMIT_POLICIES = ("RELATED_ONLY", "ALL_CAUSE")
DOC_TYPES = ("IMAGING", "LAB", "NOTE", "CONSENT")
SCREEN_RESULTS = ("CANDIDATE", "NOT_A_CANDIDATE")
CONCLUSIONS = ("SURGERY_INDICATED", "SURGERY_UNNECESSARY", "MORE_INFO_NEEDED")
CLAIM_TYPES = ("BUNDLE_CASE", "RELATED_CARE", "TRAVEL", "LODGING", "READMISSION")
SUBMITTING_ENTITIES = ("HOSPITAL", "SURGERY_CENTER", "ANESTHESIA_GROUP", "TRAVEL_VENDOR")
BENEFIT_KINDS = ("TRAVEL", "LODGING")
TRAVELERS = ("PATIENT", "COMPANION")
CARE_PHASES = ("PRE_OP", "POST_OP")
EPISODE_STATUSES = (
    "INTAKE_PENDING",
    "SCREENING",
    "SOR_PENDING",
    "SOR_REVIEW",
    "APPROVED",
    "SCHEDULING",
    "PRE_OP",
    "SURGERY_DONE",
    "POST_OP_TRACKING",
    "CLOSED",
    "AVOIDED",
    "CANCELLED",
)
EPISODE_TERMINAL = ("CLOSED", "AVOIDED", "CANCELLED")
EPISODE_PRE_APPROVAL = ("INTAKE_PENDING", "SCREENING", "SOR_PENDING", "SOR_REVIEW")
EPISODE_MONTHLY_SCOPE = ("APPROVED", "SCHEDULING", "PRE_OP", "SURGERY_DONE", "POST_OP_TRACKING", "CLOSED")
EPISODE_CONCURRENT_SCOPE = ("APPROVED", "SCHEDULING", "PRE_OP", "SURGERY_DONE", "POST_OP_TRACKING")
CONTRACT_STATUSES = ("DRAFT", "ACTIVE", "TERMINATED")
EMPLOYER_STATUSES = ("ACTIVE", "TERMINATED")
TEMPLATE_STATUSES = ("ACTIVE", "RETIRED")

REPRICE_NOTICE_DAYS = 30
QUIET_TAIL_DAYS = 7


# ---------------------------------------------------------------------------
# Generic lookups / serializers
# ---------------------------------------------------------------------------
def get_or_404(collection, row_id):
    row = getattr(db, collection).get(row_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "No %s record exists with id '%s'." % (collection, row_id))
    return row


def estimate_safe(ep, view="employer"):
    """Estimate, or None when the employer rate book lacks the family."""
    try:
        return estimate(ep, view)
    except ApiError:
        return None


def dump_episode(ep):
    """Serialize an episode with estimated_total_billed_cents (default view).

    Used by mutation responses and intake; per PRD S3.9 the estimate is
    computed on read of the episode. A missing baseline family rate yields
    a null estimate rather than failing a non-GET response.
    """
    return dump(ep, {"estimated_total_billed_cents": estimate_safe(ep)})


# ---------------------------------------------------------------------------
# Business helpers
# ---------------------------------------------------------------------------
def template_of(contract):
    return db.templates.get(contract["template_id"])


def employer_of_episode(ep):
    contract = db.contracts.get(ep["contract_id"])
    if contract is None:
        return None
    return db.employers.get(contract["employer_id"])


def episode_template(ep):
    contract = db.contracts.get(ep["contract_id"])
    return template_of(contract) if contract else None


def baseline_rate(ep):
    """Employer baseline rate (cents) for the episode's family; None when missing."""
    employer = employer_of_episode(ep)
    if employer is None:
        return None
    book = db.rate_books.get(employer["baseline_rate_book"])
    if book is None:
        return None
    rates = book.get("rates") or {}
    if ep["family"] not in rates:
        return None
    return rates[ep["family"]]


def unreleased_accrual(ep_id):
    return sum(
        b["amount_cents"]
        for b in db.benefits.values()
        if b["episode_id"] == ep_id and b["status"] == "ADMINISTERED"
    )


def estimate(ep, view):
    """estimated_total_billed_cents per PRD S3.9 (employer_baseline / provider_cost)."""
    base = baseline_rate(ep)
    if base is None:
        raise ApiError(
            "ERR_RATE_FAMILY_MISSING",
            "Employer baseline rate book has no rate for family '%s'." % ep["family"],
        )
    accrual = unreleased_accrual(ep["id"])
    if view == "employer":
        return base + accrual
    # clinic view: applied bundle price + outlier projection - accrual
    applied = ep.get("applied_bundle_price_cents") or 0
    projection = 0
    if ep.get("_outlier_flag"):
        contract = db.contracts.get(ep["contract_id"])
        expected = ep.get("_outlier_expected") or 0
        excess = max(0, expected - contract["outlier_threshold_cents"])
        projection = (excess * contract["outlier_share_pct"]) // 100
    return applied + projection - accrual


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def release_benefits(ep):
    for b in db.benefits.values():
        if b["episode_id"] == ep["id"] and b["status"] == "ADMINISTERED":
            b["status"] = "RELEASED"
            touch(b)


def waive_open_care_items(ep):
    for item in db.care_items.values():
        if item["episode_id"] == ep["id"] and item["status"] == "OPEN":
            item["status"] = "WAIVED"
            touch(item)


def cancel_episode(ep):
    """Contract-termination cascade: pre-approval episode -> CANCELLED."""
    ep["status"] = "CANCELLED"
    ep["screen_seq"] += 1
    ep["_terminal_seq"] = ep["screen_seq"]
    ep["_terminal_clock"] = db.clock
    touch(ep)
    waive_open_care_items(ep)


def terminate_contract(contract):
    contract["status"] = "TERMINATED"
    touch(contract)
    for ep in db.episodes.values():
        if ep["contract_id"] == contract["id"] and ep["status"] in EPISODE_PRE_APPROVAL:
            cancel_episode(ep)


# ---------------------------------------------------------------------------
# Benefit pool ledger (PRD S3.8)
# ---------------------------------------------------------------------------
def pool_remaining(ep, kind):
    contract = db.contracts[ep["contract_id"]]
    pool = contract["travel_benefit_cents"] if kind == "TRAVEL" else contract["lodging_benefit_cents"]
    used = sum(
        b["amount_cents"]
        for b in db.benefits.values()
        if b["episode_id"] == ep["id"] and b["kind"] == kind and b["status"] == "ADMINISTERED"
    )
    used += sum(
        c["adjudicated_payable_cents"] or 0
        for c in db.claims.values()
        if c["episode_id"] == ep["id"] and c["claim_type"] == kind and c["status"] in ("APPROVED", "PAID")
    )
    return pool - used


# ---------------------------------------------------------------------------
# Reports (PRD S3.9)
# ---------------------------------------------------------------------------
def month_bounds(period_month):
    year, month = (int(part) for part in period_month.split("-"))
    from datetime import datetime

    first = datetime(year, month, 1, tzinfo=db.clock.tzinfo)
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=db.clock.tzinfo)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=db.clock.tzinfo)
    return first, nxt


def in_month(stamp, bounds):
    if stamp is None:
        return False
    first, nxt = bounds
    return first <= stamp < nxt


def compute_report(employer_id, period_month):
    bounds = month_bounds(period_month)
    episodes = [
        ep
        for ep in db.episodes.values()
        if (db.contracts.get(ep["contract_id"]) or {}).get("employer_id") == employer_id
    ]

    avoided = [
        ep for ep in episodes
        if ep["status"] == "AVOIDED" and in_month(ep.get("_terminal_clock"), bounds)
    ]
    avoided_count = len(avoided)
    avoided_cost = 0
    for ep in avoided:
        rate = baseline_rate(ep)
        if rate is None:
            raise ApiError(
                "ERR_RATE_FAMILY_MISSING",
                "Employer baseline rate book has no rate for family '%s'." % ep["family"],
            )
        avoided_cost += rate

    closed = [
        ep for ep in episodes
        if ep["status"] == "CLOSED"
        and ep["surgery_done_seq"] > 0
        and in_month(ep.get("_terminal_clock"), bounds)
    ]
    closed_with_readmit = 0
    for ep in closed:
        if any(
            r["episode_id"] == ep["id"] and not r["out_of_window"]
            for r in db.readmissions.values()
        ):
            closed_with_readmit += 1
    if len(closed) == 0:
        readmit_rate = rhu(0, 2)
    else:
        readmit_rate = rhu(100 * closed_with_readmit / len(closed), 2)

    absorbed_total = sum(
        r["absorbed_cents"]
        for r in db.readmissions.values()
        if any(r["episode_id"] == ep["id"] for ep in closed)
    )

    scheduled = [
        ep for ep in episodes
        if ep.get("_first_scheduled_clock") is not None
        and in_month(ep["_first_scheduled_clock"], bounds)
    ]
    if not scheduled:
        avg_days = rhu(0, 2)
    else:
        gaps = [ep["_first_scheduled_start"] - ep["_approve_seq"] for ep in scheduled]
        avg_days = rhu(sum(gaps) / len(gaps), 2)

    return {
        "avoided_procedures_count": avoided_count,
        "avoided_cost_estimate_cents": avoided_cost,
        "readmission_rate_pct": readmit_rate,
        "warranty_absorbed_total_cents": absorbed_total,
        "avg_days_to_schedule": avg_days,
        "computed_seq": max((ep["screen_seq"] for ep in episodes), default=0),
    }
