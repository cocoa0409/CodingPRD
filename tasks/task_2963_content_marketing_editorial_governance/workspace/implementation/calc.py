"""Every calculation in PRD section 3, with its literal constants and pinned
arithmetic order.  All money/percentage arithmetic is Decimal + ROUND_HALF_UP
(PRD section 2.7)."""

import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

import timeutil

ZERO2 = Decimal("0.00")

# --- brief_effort_points -----------------------------------------------------
INTENT_BASE = {
    "INFORMATIONAL": 4,
    "COMMERCIAL": 6,
    "TRANSACTIONAL": 8,
    "NAVIGATIONAL": 3,
}
WORDCOUNT_STEP_WORDS = 500
WORDCOUNT_STEP_POINTS = 2
FUNNEL_UPLIFT = {
    "AWARENESS": 0,
    "CONSIDERATION": 2,
    "DECISION": 4,
    "RETENTION": 1,
}
REGULATED_UPLIFT = 5
EFFORT_MIN = 6
EFFORT_MAX = 40
HOURS_PER_EFFORT_POINT = Decimal("0.5")

# --- slot_capacity_commit ----------------------------------------------------
TIER_HIGH_PCT = Decimal("80.00")
TIER_MEDIUM_PCT = Decimal("50.00")
TIER_SURCHARGE = {"LOW": 0, "MEDIUM": 1, "HIGH": 3}

# --- review_gate_sla_due_at --------------------------------------------------
GATE_BASE_HOURS = {"SME": 24, "LEGAL": 48, "BRAND": 24, "ACCESSIBILITY": 36}
DECISION_STAGE_FACTOR = Decimal("1.25")
EXECUTIVE_PERSONA_FACTOR = Decimal("1.15")
REGULATED_CLAIM_EXTRA_HOURS = 12

# --- claim_evidence_score ----------------------------------------------------
EVIDENCE_SOURCE_WEIGHT = {
    "INTERNAL_STUDY": Decimal("1.00"),
    "THIRD_PARTY_TEST": Decimal("2.00"),
    "CUSTOMER_DATA": Decimal("0.50"),
    "REGULATORY_FILING": Decimal("2.50"),
}
REQUIRED_SCORE = {
    "PERFORMANCE": Decimal("2.00"),
    "COMPARISON": Decimal("3.00"),
    "REGULATED": Decimal("4.00"),
}
STANDARD_RECENCY_DAYS = 730
STANDARD_STALE_FACTOR = Decimal("0.5")
STRICT_RECENCY_DAYS = 365
STRICT_STALE_FACTOR = Decimal("0.0")
STRICT_ADMISSIBLE = ("THIRD_PARTY_TEST", "REGULATORY_FILING")

# --- content_pipeline_attribution -------------------------------------------
TOUCH_WEIGHT = {
    "FIRST": Decimal("0.40"),
    "MIDDLE": Decimal("0.20"),
    "LAST": Decimal("0.40"),
}

# --- content_decay_pct ------------------------------------------------------
DECAY_WINDOW_DAYS = 28
REFRESH_THRESHOLD_PCT = {
    "AWARENESS": Decimal("55.00"),
    "CONSIDERATION": Decimal("50.00"),
    "DECISION": Decimal("45.00"),
    "RETENTION": Decimal("60.00"),
}
PRUNE_DECAY_PCT = Decimal("85.00")

# --- campaign_governance_posture --------------------------------------------
FREEZE_CLAIM_COUNT = 1
FREEZE_USAGE_COUNT = 2
RESTRICT_GATE_COUNT = 2
RESTRICT_USAGE_COUNT = 1
UNSUBSTANTIATED_STATES = ("DRAFT", "EVIDENCE_PENDING", "REJECTED", "EXPIRED")
PUBLISHED_LIKE = ("PUBLISHED", "NEEDS_REFRESH")

# --- asset_license_status ---------------------------------------------------
ASSET_EXPIRY_WARNING_DAYS = 30
TALENT_EXCLUSIVITY_BUFFER_DAYS = 7

# --- accessibility ----------------------------------------------------------
MIN_META_DESCRIPTION_CHARS = 50
MIN_PUBLISH_TAGS = 2

BRIEF_COUNTED_STATES = ("SME_ASSIGNED", "APPROVED")


def rhu(value, places):
    """Round half up to the given number of decimal places."""
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def brief_effort_points(search_intent, target_word_count, funnel_stage,
                        requires_regulated_review):
    points = INTENT_BASE[search_intent]
    points += WORDCOUNT_STEP_POINTS * int(
        math.ceil(Decimal(target_word_count) / Decimal(WORDCOUNT_STEP_WORDS)))
    points += FUNNEL_UPLIFT[funnel_stage]
    if requires_regulated_review:
        points += REGULATED_UPLIFT
    if points < EFFORT_MIN:
        points = EFFORT_MIN
    if points > EFFORT_MAX:
        points = EFFORT_MAX
    return points


def sme_reserved_hours(effort_points):
    return int(math.ceil(Decimal(effort_points) * HOURS_PER_EFFORT_POINT))


def utilization_pct(committed_points, capacity_points):
    if capacity_points == 0:
        return ZERO2
    return rhu(Decimal(committed_points) * 100 / Decimal(capacity_points), 2)


def capacity_tier(pct):
    if pct >= TIER_HIGH_PCT:
        return "HIGH"
    if pct >= TIER_MEDIUM_PCT:
        return "MEDIUM"
    return "LOW"


def gate_sla_hours(gate_type, brief_funnel_stage, campaign_persona,
                   open_regulated_claim_count):
    base = Decimal(GATE_BASE_HOURS[gate_type])
    factor = Decimal("1.0")
    if brief_funnel_stage == "DECISION":
        factor = factor * DECISION_STAGE_FACTOR
    if campaign_persona == "EXECUTIVE":
        factor = factor * EXECUTIVE_PERSONA_FACTOR
    hours = rhu_int(base * factor)
    if gate_type == "LEGAL":
        hours += REGULATED_CLAIM_EXTRA_HOURS * open_regulated_claim_count
    return hours


def turnaround_hours(opened_at, decided_at):
    seconds = Decimal((decided_at - opened_at).total_seconds())
    return rhu(seconds / Decimal(3600), 2)


def evidence_contribution(evidence_row, claim_type, clock):
    """Weight contributed by one evidence row under the claim's scoring variant."""
    age_days = timeutil.whole_days_between(evidence_row["collected_at"], clock)
    weight = EVIDENCE_SOURCE_WEIGHT[evidence_row["source_type"]]
    if claim_type == "REGULATED":
        if evidence_row["source_type"] not in STRICT_ADMISSIBLE:
            return Decimal("0")
        factor = Decimal("1.0") if age_days <= STRICT_RECENCY_DAYS else STRICT_STALE_FACTOR
    else:
        factor = Decimal("1.0") if age_days <= STANDARD_RECENCY_DAYS else STANDARD_STALE_FACTOR
    return weight * factor


def claim_evidence_score(rows, claim_type, clock):
    """Returns (score rounded once to 2dp, list of contributing rows)."""
    total = Decimal("0")
    contributing = []
    for row in rows:
        share = evidence_contribution(row, claim_type, clock)
        total += share
        if share > 0:
            contributing.append(row)
    return rhu(total, 2), contributing


def attribution(snapshots):
    engaged = 0
    conversions = 0
    last_touch = 0
    assisted = 0
    for snap in snapshots:
        engaged += snap["engaged_sessions"]
        conversions += snap["conversions"]
        amount = snap["influenced_opportunity_amount_cents"]
        if snap["touch_position"] == "LAST":
            last_touch += amount
        assisted += rhu_int(Decimal(amount) * TOUCH_WEIGHT[snap["touch_position"]])
    return engaged, conversions, last_touch, assisted


def _window_sessions(snapshots, start, end):
    total = 0
    for snap in snapshots:
        if snap["period_start"] >= start and snap["period_end"] <= end:
            total += snap["engaged_sessions"]
    return total


def decay_pct(snapshots, published_at, clock):
    """DECAY_WINDOW_DAYS baseline from published_at versus the trailing window."""
    window = timedelta(days=DECAY_WINDOW_DAYS)
    if published_at is None:
        baseline = 0
    else:
        baseline = _window_sessions(snapshots, published_at, published_at + window)
    trailing = _window_sessions(snapshots, clock - window, clock)
    if baseline == 0:
        return ZERO2
    ratio = Decimal(trailing) / Decimal(baseline)
    value = rhu((Decimal(1) - ratio) * Decimal(100), 2)
    if value < ZERO2:
        return ZERO2
    return value


def refresh_required(decay_value, funnel_stage, accuracy_status):
    if accuracy_status == "INACCURATE":
        return True
    return decay_value >= REFRESH_THRESHOLD_PCT[funnel_stage]


def governance_posture(unsubstantiated_claims, expired_usages, breached_gates):
    if unsubstantiated_claims >= FREEZE_CLAIM_COUNT or expired_usages >= FREEZE_USAGE_COUNT:
        return "FROZEN"
    if breached_gates >= RESTRICT_GATE_COUNT or expired_usages >= RESTRICT_USAGE_COUNT:
        return "RESTRICTED"
    return "OPEN"


def asset_status(license_end, clock):
    if license_end <= clock:
        return "EXPIRED"
    if (license_end - clock) <= timedelta(days=ASSET_EXPIRY_WARNING_DAYS):
        return "EXPIRING"
    return "LICENSED"
