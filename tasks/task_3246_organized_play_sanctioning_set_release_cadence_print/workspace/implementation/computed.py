"""Calculation rules (§1.3).

Every derived figure is computed at integer precision (§2.9). Where a division
appears, the result is floored at one single named point and the floored value
is carried forward; several unrounded values are never summed and the total
floored afterwards.
"""

import db as _db

# --------------------------------------------------------------------------
# Constants, verbatim from §1.3
# --------------------------------------------------------------------------

TIER_BASE_TP = {"LOCAL": 16, "QUALIFIER": 48, "CHAMPIONSHIP": 96}
POD_BUNDLE_MINIMUM = 4
POD_BUNDLE_TP = {"LOCAL": 3, "QUALIFIER": 6, "CHAMPIONSHIP": 12}
POD_TP_PER_MEMBER = 4

PACK_COUNT_BY_TIER = {"LOCAL": 6, "QUALIFIER": 12, "CHAMPIONSHIP": 24}
PACK_VALUE_NUM = 27
PACK_VALUE_DEN = 4

REPORTING_WINDOW_DAYS = 18
EVENT_COMPLETION_DAYS_AFTER_STREET = 7
QUALIFIED_THRESHOLD = 24

WOW_ADDENDUM_NUMERATOR = 64
WOW_ADDENDUM_DENOMINATOR = 137
REPRINT_CEILING_INDEX = 42

ENHANCED_REPORTING_THRESHOLD = 5

CLASS_POINTS = {"MINOR": 2, "MAJOR": 5, "SEVERE": 11}
LEVEL_MULTIPLIER = {"REGULAR": 1, "COMPETITIVE": 2, "PROFESSIONAL": 3}
REPEAT_MULTIPLIER = 3
ESCALATION_INCREMENT = 4


# --------------------------------------------------------------------------
# tier_prize_support_pool (§3.5)
# --------------------------------------------------------------------------

def count_redeemed_digital_members(application_id):
    """Rows with status REDEEMED AND code_kind DIGITAL bound to this application.

    AVAILABLE rows, DECLINED rows and every PHYSICAL row are excluded. The
    count is taken fresh at each approval and is never revisited afterwards.
    """
    return sum(
        1 for c in _db.db.code_redemptions.values()
        if c["event_application_id"] == application_id
        and c["status"] == "REDEEMED"
        and c["code_kind"] == "DIGITAL"
    )


def tier_prize_support_pool(tier, member_count, pool_mode):
    """base_tp for a newly approved application.

    BUNDLED:    base + POD_BUNDLE_TP[tier] * (member_count - 4) when
                member_count >= 4, otherwise base. The first four members are
                absorbed by the tier base.
    UNBUNDLED:  base + POD_TP_PER_MEMBER * member_count, including the first four.

    Every addition is computed at integer precision and summed before any
    rounding step; no intermediate rounding is performed.
    """
    base = TIER_BASE_TP[tier]
    if pool_mode == "UNBUNDLED":
        return base + POD_TP_PER_MEMBER * member_count
    if member_count >= POD_BUNDLE_MINIMUM:
        return base + POD_BUNDLE_TP[tier] * (member_count - POD_BUNDLE_MINIMUM)
    return base


# --------------------------------------------------------------------------
# prize_pool_remaining — the conserved ledger (§1.3 / §2.4)
# --------------------------------------------------------------------------

def physical_grant_value(pool_tier):
    """floor(PACK_COUNT_BY_TIER[tier] * 27 / 4), floored ONCE per grant."""
    return (PACK_COUNT_BY_TIER[pool_tier] * PACK_VALUE_NUM) // PACK_VALUE_DEN


def voided_distribution_total(allocation_id):
    return sum(
        d["quantity"] for d in _db.db.prize_distributions.values()
        if d["prize_allocation_id"] == allocation_id and d["status"] == "VOIDED"
    )


def report_restore_total(allocation_id):
    return sum(
        r["unclaimed_tp"] for r in _db.db.prize_reports.values()
        if r["prize_allocation_id"] == allocation_id
        and r["status"] in ("FILED", "OVERDUE")
    )


def disbursed_grant_total(allocation_id, tier):
    return sum(
        physical_grant_value(tier) for c in _db.db.code_redemptions.values()
        if c["prize_allocation_id"] == allocation_id
        and c["status"] == "REDEEMED"
        and c["physical_grant_status"] == "DISBURSED"
    )


def rederived_restored_total(allocation_id, tier):
    """The authoritative restore figure used by the close and suspend cascades.

    total_restored_tp is re-derived as the sum over all VOIDED distributions
    plus all filed/overdue reports plus all disbursed physical grants, rather
    than incremented, so that ALLOC_INVARIANT = base_tp - total_drawn_tp +
    total_restored_tp returns to its pre-draw figure for every affected
    allocation. Re-deriving is idempotent: voiding a distribution that had
    already been voided by hand yields the same figure.
    """
    return (voided_distribution_total(allocation_id)
            + report_restore_total(allocation_id)
            + disbursed_grant_total(allocation_id, tier))


def prize_pool_remaining(allocation):
    """base_tp - total_drawn_tp + total_restored_tp.

    Computed once from the two integer sums and never itself rounded. Both
    counters are materialized and move by explicit increments: a PASS raises
    total_drawn_tp and leaves it raised even if the distribution is later
    voided, which is what lets a void-then-pass cycle return the balance to
    precisely the figure it held before the void.
    """
    return (allocation["base_tp"]
            - allocation["total_drawn_tp"]
            + allocation["total_restored_tp"])


def prize_pool_invariant(allocation):
    """The audit anchor; identical to remaining_tp, materialized for clarity."""
    return prize_pool_remaining(allocation)


# --------------------------------------------------------------------------
# reporting_due_deadline (§3.4)
# --------------------------------------------------------------------------

def reporting_due_by(tier, street_date):
    """LOCAL carries no deadline at all; competitive tiers get street + 18 days."""
    if tier == "LOCAL":
        return None
    if street_date is None:
        return None
    from datetime import timedelta
    return street_date + timedelta(days=REPORTING_WINDOW_DAYS)


# --------------------------------------------------------------------------
# qualified_headcount_gate (§3.13)
# --------------------------------------------------------------------------

def submitted_reports_for(application_id):
    """Reports that have actually been filed against the application.

    A report marked OVERDUE is still a filed report — it just carries the
    late-filing mark — so it counts here alongside FILED rows.
    """
    return [
        r for r in _db.db.prize_reports.values()
        if r["event_application_id"] == application_id
        and r["status"] in ("FILED", "OVERDUE")
    ]


def headcount_gate(application):
    """Returns (report_status, qualified, gate_error).

    Applications with no submitted report are excluded from the gate entirely
    and surface as NOT_FILED rather than as a gate failure. The comparison is
    >=, so a headcount exactly equal to the threshold qualifies.
    """
    reports = submitted_reports_for(application["id"])
    if not reports:
        return "NOT_FILED", False, None
    latest = max(reports, key=lambda r: r["created_at"])
    qualified = latest["reported_headcount"] >= QUALIFIED_THRESHOLD
    if application["tier"] == "LOCAL":
        return "FILED", qualified, None
    if qualified:
        return "FILED", True, None
    return "FILED", False, "ERR_HEADCOUNT_BELOW_THRESHOLD"


# --------------------------------------------------------------------------
# reprint_policy_verdict (§3.9)
# --------------------------------------------------------------------------

def wow_index(secondary_market_index):
    """index + floor(64 * index / 137). The addendum is floored exactly once."""
    return secondary_market_index + (WOW_ADDENDUM_NUMERATOR * secondary_market_index
                                     // WOW_ADDENDUM_DENOMINATOR)


def reprint_policy_verdict(secondary_market_index):
    """REPRINT_DENIED when the addendum-adjusted index exceeds the ceiling."""
    if wow_index(secondary_market_index) > REPRINT_CEILING_INDEX:
        return "REPRINT_DENIED"
    return "REPRINT_ALLOWED"


# --------------------------------------------------------------------------
# store_reporting_tier (§3.1)
# --------------------------------------------------------------------------

def reported_event_count(store_id):
    return sum(
        1 for a in _db.db.event_applications.values()
        if a["store_id"] == store_id and a["status"] == "REPORTED"
    )


def store_reporting_tier(store_id):
    """ENHANCED from the fifth reported event on, and never before it."""
    if reported_event_count(store_id) >= ENHANCED_REPORTING_THRESHOLD:
        return "ENHANCED"
    return "STANDARD"


# --------------------------------------------------------------------------
# Store rollups (§2.7)
# --------------------------------------------------------------------------

def store_tp_balance(store_id):
    """Sum of remaining_tp across every allocation the store owns."""
    return sum(
        prize_pool_remaining(a) for a in _db.db.prize_allocations.values()
        if a["store_id"] == store_id
    )


def store_reporting_violation_points(store_id):
    """Sum of current_points over every case arising from the store's events.

    Closed and reduced cases keep contributing their current_points.
    """
    return sum(c["current_points"] for c in _db.cases_of_store(store_id))


# --------------------------------------------------------------------------
# enforcement_penalty_points (§3.10)
# --------------------------------------------------------------------------

def penalty_points_for(offense_class, rules_enforcement_level):
    """CLASS_POINTS x LEVEL_MULTIPLIER; integer multiply, no rounding."""
    return CLASS_POINTS[offense_class] * LEVEL_MULTIPLIER[rules_enforcement_level]


def current_points_on_filing(penalty_points):
    return penalty_points


def current_points_on_escalate(penalty_points, repeated_offense):
    """The one branch that consults repeated_offense."""
    if repeated_offense:
        return penalty_points * REPEAT_MULTIPLIER
    return penalty_points + ESCALATION_INCREMENT


def current_points_on_close(penalty_points):
    return penalty_points


def current_points_on_reduce(penalty_points):
    """floor(penalty_points / 2), floored once before summing into the store total."""
    return penalty_points // 2