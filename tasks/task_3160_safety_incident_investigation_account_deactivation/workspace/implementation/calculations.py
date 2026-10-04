"""Every derived quantity the PRD pins.

Severity classification, evidence admissibility, risk contagion, the graduated
decision criteria, the graduated deactivation rollup, the expiry projection and
the cluster aggregates all live here. Rounding is round-half-up throughout, the
per-item-then-sum-then-final order is honoured exactly, and money-free numerics
still go through Decimal so no binary-float drift leaks into a comparison.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, add_days, now

# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------

SEVERITY_BASE = {
    "PHYSICAL_ASSAULT": 4,
    "SEXUAL_MISCONDUCT": 4,
    "HARASSMENT": 2,
    "SAFETY_VIOLATION": 2,
    "FRAUD_IDENTITY": 2,
    "DISCRIMINATION": 2,
    "PROPERTY_DAMAGE": 1,
}

AGGRAVATOR_LEVELS = {
    "S3_INJURY": 1,
    "S3_LAW_ENFORCEMENT_SEVERITY": 1,
}

BAND_MAX_LEVEL = 4
BAND_MIN_LEVEL = 1

CATEGORY_RANK = {
    "PHYSICAL_ASSAULT": 0,
    "SEXUAL_MISCONDUCT": 1,
    "HARASSMENT": 2,
    "SAFETY_VIOLATION": 3,
    "FRAUD_IDENTITY": 4,
    "DISCRIMINATION": 5,
    "PROPERTY_DAMAGE": 6,
}

SEVERITY_ORDER = {"S1": 1, "S2": 2, "S3": 3, "S4": 4}


def severity_level(value):
    return SEVERITY_ORDER.get(value, 0)


def round_half_up(value, places):
    """Round with ROUND_HALF_UP (never banker's rounding)."""
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def derive_severity(incident_category, aggravator_codes, prior_incident_count_at_intake):
    """Return (severity, derivative_severity_flagged) for an intake."""
    base = SEVERITY_BASE.get(incident_category, 1)
    codes = [c for c in (aggravator_codes or [])]
    applied_levels = 0
    applied_count = 0
    seen = set()
    for code in codes:
        if code in AGGRAVATOR_LEVELS and code not in seen:
            seen.add(code)
            applied_levels += AGGRAVATOR_LEVELS[code]
            applied_count += 1
    raw_level = base + applied_levels
    band_level = min(raw_level, BAND_MAX_LEVEL)

    if not codes and base == 1 and (prior_incident_count_at_intake or 0) >= 1:
        # With no aggravator codes supplied at all the band floors at S2 for a
        # base-level-1 category when the account already carries a prior
        # incident, so a second-report PROPERTY_DAMAGE lands on S2 rather than
        # the S1 the base level alone would give.
        band_level = max(band_level, 2)

    severity = "S" + str(max(band_level, BAND_MIN_LEVEL))
    derivative = (raw_level >= 4 and applied_count >= 1)
    return severity, derivative


# ---------------------------------------------------------------------------
# Cluster resolution
# ---------------------------------------------------------------------------

def _dedupe_links(account_id):
    """Deduplicate the account's links by cluster, keeping the newest row."""
    best = {}
    for link in STORE.account_links(account_id):
        cluster_id = link.get("device_cluster_id")
        candidate = (link.get("last_seen_at"), link.get("created_at"), link.get("id"))
        current = best.get(cluster_id)
        if current is None:
            best[cluster_id] = link
            continue
        cur_key = (current.get("last_seen_at"), current.get("created_at"), current.get("id"))
        # greatest last_seen_at wins; ties broken by created_at ascending (then id,
        # so the choice is deterministic when both are identical).
        if candidate[0] > cur_key[0] or (candidate[0] == cur_key[0] and candidate[1] < cur_key[1]):
            best[cluster_id] = link
    return list(best.values())


def resolve_cluster_for_account(account_id):
    """The cluster term's resolution: newest surviving LINKED/DORMANT row."""
    survivors = [l for l in _dedupe_links(account_id)
                 if l.get("link_status") in ("LINKED", "DORMANT")]
    if not survivors:
        return None
    survivors.sort(key=lambda l: (l.get("last_seen_at"), l.get("created_at"), l.get("id") or ""))
    best = survivors[-1]
    return STORE.clusters.get(best.get("device_cluster_id"))


def cluster_risk_multiplier_pct(account_id):
    """clamp(100 + floor(aggregate_cluster_risk / 50), 100, 300)."""
    cluster = resolve_cluster_for_account(account_id)
    if cluster is None:
        return 100
    aggregate = cluster.get("aggregate_cluster_risk", 0) or 0
    value = 100 + int(math.floor(aggregate / 50))
    return max(100, min(300, value))


# ---------------------------------------------------------------------------
# Risk contagion propagation
# ---------------------------------------------------------------------------

BASE_RISK = {"S1": 20, "S2": 60, "S3": 140, "S4": 260}
DECAY_STEP_1_DAYS = 90
DECAY_STEP_2_DAYS = 180
ENFORCEMENT_WEIGHT = 180
CLUSTER_COEFFICIENT = 0.25
SCORE_CEILING = 1000
TIER_SEVERE_CUTOFF = 640
TIER_HIGH_CUTOFF = 420
TIER_ELEVATED_CUTOFF = 210

COUNTED_INCIDENT_STATUSES = (
    "OPEN", "INVESTIGATING", "PENDING_DECISION", "MANDATORY_REPORTED_BLOCKED", "DECIDED",
)
COUNTED_SEVERITIES = ("S2", "S3", "S4")
STANDING_ENFORCEMENT_STATUSES = ("ACTIVE", "MANDATORY_REPORTED", "APPEAL_PENDING")
SEVERE_RESCUE_CEILING = 400


def decay_factor(incident, instant):
    created = incident.get("created_at")
    if created is None:
        return 1.00
    age = (instant - created).total_seconds()
    if age < DECAY_STEP_1_DAYS * 86400:
        return 1.00
    if age < DECAY_STEP_2_DAYS * 86400:
        return 0.50
    return 0.00


def _counted_incidents(account_id):
    out = []
    for incident in STORE.account_incidents(account_id):
        if incident.get("incident_status") not in COUNTED_INCIDENT_STATUSES:
            continue
        if incident.get("severity") not in COUNTED_SEVERITIES:
            continue
        if (incident.get("incident_status") == "DECIDED"
                and incident.get("decision_category") == "WARNING"):
            # A decided WARNING row is carved out of the incident term.
            continue
        out.append(incident)
    return out


def incident_risk(account_id, instant=None):
    instant = instant or now()
    total = 0.0
    for incident in _counted_incidents(account_id):
        base = BASE_RISK.get(incident.get("severity"), 0)
        multiplier = (incident.get("cluster_risk_multiplier_pct") or 100) / 100.0
        total += base * decay_factor(incident, instant) * multiplier
    return total


def enforcement_risk(account_id, exclude_action_id=None):
    total = 0
    for action in STORE.account_actions(account_id):
        if exclude_action_id is not None and action.get("id") == exclude_action_id:
            continue
        if action.get("enforcement_status") in STANDING_ENFORCEMENT_STATUSES:
            total += ENFORCEMENT_WEIGHT
    return total


def non_cluster_risk(account_id):
    """The member's incident + enforcement components, clamped 0..1000."""
    raw = incident_risk(account_id) + enforcement_risk(account_id)
    return max(0.0, min(1000.0, round_half_up(raw, 2)))


def tier_from_score(score):
    if score >= TIER_SEVERE_CUTOFF:
        return "TIER_SEVERE"
    if score >= TIER_HIGH_CUTOFF:
        return "TIER_HIGH"
    if score >= TIER_ELEVATED_CUTOFF:
        return "TIER_ELEVATED"
    return "TIER_LOW"


def _tier_with_escape_hatch(account_id, score):
    tier = tier_from_score(score)
    sev_a = 0
    sev_b = None
    for incident in STORE.account_incidents(account_id):
        if incident.get("severity") not in ("S3", "S4"):
            continue
        level = severity_level(incident.get("severity"))
        if level > sev_a:
            sev_a = level
        if incident.get("incident_status") in ("OPEN", "INVESTIGATING",
                                               "PENDING_DECISION",
                                               "MANDATORY_REPORTED_BLOCKED"):
            if sev_b is None or level > sev_b:
                sev_b = level
    if sev_a >= 3 and sev_b is None and score < SEVERE_RESCUE_CEILING:
        return "TIER_SEVERE"
    return tier


def tier_with_escape_hatch(account_id, score):
    """Public alias for the plus-hatch tier banding used by the ancillary adjustments."""
    return _tier_with_escape_hatch(account_id, score)


def compute_risk(account_id, instant=None, exclude_action_id=None):
    """The full projection, returned without mutating anything."""
    instant = instant or now()
    raw = incident_risk(account_id, instant) + enforcement_risk(account_id, exclude_action_id)
    cluster = resolve_cluster_for_account(account_id)
    if cluster is not None:
        raw += CLUSTER_COEFFICIENT * (cluster.get("aggregate_cluster_risk", 0) or 0)
    score = round_half_up(raw, 2)
    score = max(0.0, min(float(SCORE_CEILING), score))
    return score, _tier_with_escape_hatch(account_id, score)


def propagate_risk(account, exclude_action_id=None):
    """Recompute and write the account's risk_score / risk_tier."""
    score, tier = compute_risk(account.get("id"), exclude_action_id=exclude_action_id)
    account["risk_score"] = score
    account["risk_tier"] = tier
    return account


def recompute_cluster_aggregate(cluster):
    """Sum every member's non-cluster risk; the cluster term is excluded."""
    total = 0.0
    for account_id in STORE.cluster_member_accounts(cluster.get("id")):
        total += non_cluster_risk(account_id)
    cluster["aggregate_cluster_risk"] = round_half_up(total, 2)
    cluster["clustered_actor_incident_count"] = clustered_actor_incident_count(cluster)
    return cluster


def clustered_actor_incident_count(cluster):
    """Clustered S3/S4 incidents still inside the investigation lifecycle."""
    member_ids = set(STORE.cluster_member_accounts(cluster.get("id")))
    count = 0
    for incident in STORE.incidents.values():
        if incident.get("account_id") not in member_ids:
            continue
        if incident.get("severity") not in ("S3", "S4"):
            continue
        if incident.get("incident_status") in (
                "OPEN", "INVESTIGATING", "PENDING_DECISION",
                "MANDATORY_REPORTED_BLOCKED", "DECIDED"):
            count += 1
    return count


def recompute_linked_clusters(account_id):
    """Recompute the aggregate of every cluster the account touches."""
    seen = set()
    for link in STORE.account_links(account_id):
        cluster_id = link.get("device_cluster_id")
        if cluster_id in seen:
            continue
        seen.add(cluster_id)
        cluster = STORE.clusters.get(cluster_id)
        if cluster is not None:
            recompute_cluster_aggregate(cluster)


# ---------------------------------------------------------------------------
# Evidence admissibility
# ---------------------------------------------------------------------------

RELIABILITY_EXTERNAL_RECORD = 0.75
RELIABILITY_MESSAGE_OR_RATINGS = 0.90
RELIABILITY_DEFAULT = 0.95

WEIGHT_BASE = {"WEAK": 0.40, "STANDARD": 0.70, "STRONG": 1.00, "DISPOSITIVE": 1.50}

CAP_IN_APP_OR_RATINGS = 0.80
CAP_LAW_ENFORCEMENT = 0.70
CAP_DEFAULT = 1.00

CAP_PENALTY_PER_MISSING_SOURCE = 0.15
DISPOSITIVE_PROMOTION_SCORE = 3.00
DISPOSITIVE_CONFIDENCE_FLOOR = 0.80
DISPOSITIVE_MIN_DISTINCT_SOURCES = 2
STALE_LINK_MAX_AGE_DAYS = 180


def unconditional_exclusion_reason(evidence):
    """The three exclusions applied ahead of the scoring pass."""
    etype = evidence.get("evidence_type")
    if etype == "LAW_ENFORCEMENT_CONTACT" and not evidence.get("source_entity_id"):
        # "An otherwise empty source_entity_id" is excluded as STALE_SOURCE, which
        # covers the omitted member as well as an explicit null.
        return "STALE_SOURCE"
    if etype == "IN_APP_MESSAGE":
        trip = STORE.trips.get(evidence.get("source_entity_id"))
        if trip is None or (trip.get("in_app_message_count") or 0) == 0:
            return "NO_MESSAGE_HISTORY"
    if etype == "DEVICE_LINK":
        link = STORE.links.get(evidence.get("source_entity_id"))
        if link is None:
            return "STALE_LINK"
        last_seen = link.get("last_seen_at")
        if last_seen is not None:
            boundary = add_days(now(), -STALE_LINK_MAX_AGE_DAYS)
            if last_seen < boundary:
                return "STALE_LINK"
    return None


def _per_item(evidence):
    etype = evidence.get("evidence_type")
    if etype == "EXTERNAL_RECORD":
        reliability = RELIABILITY_EXTERNAL_RECORD
    elif etype in ("IN_APP_MESSAGE", "RATINGS_HISTORY"):
        reliability = RELIABILITY_MESSAGE_OR_RATINGS
    else:
        reliability = RELIABILITY_DEFAULT
    base = WEIGHT_BASE.get(evidence.get("evidence_weight"), 0.40)
    if etype in ("IN_APP_MESSAGE", "RATINGS_HISTORY"):
        type_cap = CAP_IN_APP_OR_RATINGS
    elif etype == "LAW_ENFORCEMENT_CONTACT":
        type_cap = CAP_LAW_ENFORCEMENT
    else:
        type_cap = CAP_DEFAULT
    return round_half_up(reliability * base, 3), type_cap


def admitted_evidence(incident_id):
    """Rows that are not EXCLUDED and survive the unconditional exclusions."""
    out = []
    for evidence in STORE.evidence.values():
        if evidence.get("incident_id") != incident_id:
            continue
        if evidence.get("evidence_status") == "EXCLUDED":
            continue
        if unconditional_exclusion_reason(evidence) is not None:
            continue
        out.append(evidence)
    out.sort(key=lambda e: (e.get("recorded_at"), e.get("created_at"), e.get("id") or ""))
    return out


def evidence_scores(incident_id, per_item_rounded=True):
    """Return the full scoring view for an incident's admitted evidence.

    per_item_rounded=True is the pinned freeze path; False is the triage reading
    that sums the items unrounded and rounds only at the end.
    """
    incident = STORE.incidents.get(incident_id) or {}
    admitted = admitted_evidence(incident_id)
    items = [_per_item(e) for e in admitted]

    if per_item_rounded:
        raw_contribution = sum(value for value, _ in items)
    else:
        raw_contribution = 0.0
        for evidence in admitted:
            etype = evidence.get("evidence_type")
            if etype == "EXTERNAL_RECORD":
                reliability = RELIABILITY_EXTERNAL_RECORD
            elif etype in ("IN_APP_MESSAGE", "RATINGS_HISTORY"):
                reliability = RELIABILITY_MESSAGE_OR_RATINGS
            else:
                reliability = RELIABILITY_DEFAULT
            base = WEIGHT_BASE.get(evidence.get("evidence_weight"), 0.40)
            raw_contribution += reliability * base

    distinct_types = sorted({e.get("evidence_type") for e in admitted})
    required_sources = int(math.ceil(severity_level(incident.get("severity")) * 0.5)) or 1
    missing_sources = max(0, required_sources - len(distinct_types))
    cap_penalty = CAP_PENALTY_PER_MISSING_SOURCE * missing_sources
    cap_ceiling = sum(cap for _, cap in items)

    rounded_raw = round_half_up(raw_contribution, 3)
    continuous_score = round_half_up(min(rounded_raw - cap_penalty, cap_ceiling), 2)

    confidence_ratio = raw_contribution / (RELIABILITY_DEFAULT * WEIGHT_BASE["DISPOSITIVE"])
    has_dispositive = any(e.get("evidence_weight") == "DISPOSITIVE" for e in admitted)
    promotable = (has_dispositive
                  and confidence_ratio >= DISPOSITIVE_CONFIDENCE_FLOOR
                  and len(distinct_types) >= DISPOSITIVE_MIN_DISTINCT_SOURCES)

    support_score = len({e.get("evidence_type") for e in admitted
                         if e.get("evidence_type") in
                         ("TRIP_DATA", "RATINGS_HISTORY", "LAW_ENFORCEMENT_CONTACT")})

    return {
        "evidence_score": continuous_score,
        "raw_contribution": raw_contribution,
        "support_score": support_score,
        "distinct_evidence_source_count": len(distinct_types),
        "applied_evidence_cap": cap_ceiling,
        "confidence_ratio": round_half_up(confidence_ratio, 2),
        "dispositive_promotable": promotable,
        "cap_penalty": cap_penalty,
    }


# ---------------------------------------------------------------------------
# Decision criteria
# ---------------------------------------------------------------------------

SCORE_DEACTIVATION = 4.00
SCORE_PROVISIONAL_DEACTIVATION = 2.50
MIN_DISTINCT_SOURCES = 2
PROPERTY_DAMAGE_WARNING_SCORE = 1.50
WARNING_SUPPORT_FLOOR = 2.0
INVESTIGATION_SCOPE_DIVISOR = 5
INVESTIGATION_SCOPE_RATIO_FLOOR = 0.70

DECISION_ORDER = {"NO_ACTION": 0, "WARNING": 1, "RESTRICTED": 2, "DEACTIVATED": 3}


def prior_serious_count(account_id, created_at, minimum=None):
    count = 0
    for incident in STORE.account_incidents(account_id):
        if incident.get("severity") not in ("S3", "S4"):
            continue
        other = incident.get("created_at")
        if other is None or created_at is None or other >= created_at:
            continue
        count += 1
    return count


def investigation_scope_ratio(incident):
    account_id = incident.get("account_id")
    created_at = incident.get("created_at")
    if created_at is None:
        return 0.0
    lower = add_days(created_at, -30)
    count = 0
    for other in STORE.account_incidents(account_id):
        other_created = other.get("created_at")
        if other_created is None:
            continue
        if lower <= other_created < created_at:
            count += 1
    return count / float(INVESTIGATION_SCOPE_DIVISOR)


def category_tier(incident):
    """The category tier floor, read top to bottom exactly as the PRD pins it."""
    category = incident.get("incident_category")
    score = incident.get("decision_evidence_score") or 0
    support = incident.get("decision_support") or 0

    if category in ("PHYSICAL_ASSAULT", "SEXUAL_MISCONDUCT"):
        return "DEACTIVATED"
    if category in ("HARASSMENT", "DISCRIMINATION") and support >= WARNING_SUPPORT_FLOOR:
        return "RESTRICTED"
    if category == "HARASSMENT" and prior_serious_count(
            incident.get("account_id"), incident.get("created_at")) >= 2:
        return "DEACTIVATED"
    if category == "FRAUD_IDENTITY" and investigation_scope_ratio(incident) >= INVESTIGATION_SCOPE_RATIO_FLOOR:
        return "DEACTIVATED"
    if category == "SAFETY_VIOLATION" and prior_serious_count(
            incident.get("account_id"), incident.get("created_at")) >= 3:
        return "DEACTIVATED"
    if category == "PROPERTY_DAMAGE" and score >= PROPERTY_DAMAGE_WARNING_SCORE:
        return "WARNING"
    if category in ("SAFETY_VIOLATION", "FRAUD_IDENTITY", "PROPERTY_DAMAGE",
                    "DISCRIMINATION", "HARASSMENT"):
        return "NO_ACTION"
    return "NO_ACTION"


def higher_decision(a, b):
    return a if DECISION_ORDER.get(a, 0) >= DECISION_ORDER.get(b, 0) else b


def evidence_tier(incident):
    """The reading the continuous-evidence overrides alone would produce."""
    score = incident.get("decision_evidence_score") or 0
    distinct = incident.get("decision_distinct_evidence_sources") or 0
    if score >= SCORE_DEACTIVATION or (score >= SCORE_PROVISIONAL_DEACTIVATION
                                       and distinct >= MIN_DISTINCT_SOURCES):
        return "DEACTIVATED"
    if score >= SCORE_PROVISIONAL_DEACTIVATION:
        return "RESTRICTED"
    return "NO_ACTION"


def proposed_decision(incident):
    """The graduated decision the criteria project right now."""
    floor = category_tier(incident)
    score = incident.get("decision_evidence_score") or 0
    support = incident.get("decision_support") or 0
    distinct = incident.get("decision_distinct_evidence_sources") or 0

    if score >= SCORE_DEACTIVATION or (score >= SCORE_PROVISIONAL_DEACTIVATION
                                       and distinct >= MIN_DISTINCT_SOURCES):
        decision = "DEACTIVATED"
    elif score >= SCORE_PROVISIONAL_DEACTIVATION and distinct < MIN_DISTINCT_SOURCES:
        # A provisional deactivation cannot fire for want of a second source, so
        # the reading settles at RESTRICTED rather than escaping to DEACTIVATED
        # however the category floor ranks -- the PRD's own worked example has a
        # PHYSICAL_ASSAULT incident "resolves to RESTRICTED rather than escaping
        # all the way to DEACTIVATED".
        decision = "RESTRICTED"
    else:
        decision = floor

    if decision == "NO_ACTION" and support >= WARNING_SUPPORT_FLOOR:
        # NO_ACTION is permitted only while the support score sits below 2.0.
        decision = "RESTRICTED"
    return decision


def regulator_report_required(incident):
    return (incident.get("incident_category") in ("PHYSICAL_ASSAULT", "SEXUAL_MISCONDUCT")
            and incident.get("severity") in ("S3", "S4"))


# ---------------------------------------------------------------------------
# Graduated deactivation rollup
# ---------------------------------------------------------------------------

ROLLUP_COUNT = 5


def graduated_rollup(account_id):
    """The standing graduated cumulative rollup for an account."""
    ordered = [i for i in STORE.account_incidents(account_id)
               if i.get("incident_status") in ("DECIDED", "APPEAL_UPHELD")
               and i.get("severity") in ("S3", "S4")]
    ordered.sort(key=lambda i: (
        i.get("decided_at") or i.get("created_at"),
        i.get("created_at"),
        CATEGORY_RANK.get(i.get("incident_category"), 99),
    ))
    ordered = ordered[:ROLLUP_COUNT]

    rollup = None
    idx = 0
    for incident in ordered:
        severity = incident.get("severity")
        if severity == "S4" and idx == 0:
            rollup = "PERMANENT_DEACTIVATION"
        elif severity == "S4" and idx == 1:
            rollup = "SIX_MONTH_RESTRICTION"
        elif severity == "S4" and idx == 2:
            rollup = "TWELVE_MONTH_RESTRICTION"
        elif severity == "S3" and idx == 0:
            rollup = "THIRTY_DAY_SUSPENSION"
        elif severity == "S3" and idx == 1:
            rollup = "TWELVE_MONTH_SUSPENSION"
        else:
            rollup = "PERMANENT_DEACTIVATION"
        idx += 1
    return rollup


# ---------------------------------------------------------------------------
# Expiry projection
# ---------------------------------------------------------------------------

EXPIRY_SIMULATION_PENALTY = 30


def expiry_projection(account, action):
    """(regression, projected_score, projected_tier) for the expiry sweep.

    The projected tier is read off the plain score cutoffs the PRD names — the
    pre-sweep tier is "exactly `TIER_SEVERE`", and the escape hatch that promotes
    a low score to `TIER_SEVERE` is not part of this projection.
    """
    projected = compute_risk(account.get("id"), exclude_action_id=action.get("id"))[0]
    projected = max(0.0, min(float(SCORE_CEILING), projected))
    projected = round_half_up(projected - EXPIRY_SIMULATION_PENALTY, 2)
    projected = max(0.0, min(float(SCORE_CEILING), projected))
    projected_tier = tier_from_score(projected)
    pre_tier = account.get("risk_tier")
    regression = (pre_tier == "TIER_SEVERE" and projected_tier != "TIER_SEVERE")
    return regression, projected, projected_tier


# ---------------------------------------------------------------------------
# Rescreen cadence
# ---------------------------------------------------------------------------

ANCHOR_DAYS = 548
DRIFT_INDEX_DIVISOR = 3


def drift_step(review_generation_index):
    return int(math.floor((int(review_generation_index) - 1) / DRIFT_INDEX_DIVISOR))


def rescreen_anchor(account_id):
    completed = [c for c in STORE.account_checks(account_id)
                 if c.get("check_status") == "COMPLETED" and c.get("completed_at")]
    if not completed:
        account = STORE.accounts.get(account_id) or {}
        return account.get("created_at")
    completed.sort(key=lambda c: (c.get("completed_at"), c.get("created_at"), c.get("id") or ""))
    return completed[-1].get("completed_at")


def policy_for_region(region_code):
    policy = STORE.policy_for_region(region_code)
    if policy is None:
        return _fallback_policy(region_code)
    return policy


_DEFAULTS = {
    "sd_floor_severity": "S3",
    "sd_floor_enabled": True,
    "rollup_window_days": 30,
    "rollup_threshold": 3,
    "cluster_watchlist_threshold": 2,
    "cluster_purge_threshold": 2400,
    "escalation_enabled": True,
    "expedite_appeal_baseline_count": 5,
    "expedite_review_days": 14,
    "standard_review_days": 30,
    "appeal_window_days": 30,
    "rescreen_refresh_days": 548,
    "continuous_monitor_ack_deadline_days": 7,
    "review_generation_index": 1,
    "knob_generation_index": 1,
}


def _fallback_policy(region_code):
    """Documented defaults, used only when a region has no policy row yet."""
    policy = dict(_DEFAULTS)
    policy["region_code"] = region_code
    return policy


def projected_rescreen_due_at(account_id, review_generation_index=None, refresh_days=None):
    account = STORE.accounts.get(account_id) or {}
    policy = policy_for_region(account.get("home_region_code"))
    if review_generation_index is None:
        review_generation_index = policy.get("review_generation_index", 1)
    if refresh_days is None:
        refresh_days = policy.get("rescreen_refresh_days", 548)
    steps = drift_step(review_generation_index)
    total_days = (steps + 1) * int(refresh_days)
    anchor = rescreen_anchor(account_id)
    if anchor is None:
        return None
    return add_days(anchor, total_days)


# ---------------------------------------------------------------------------
# Appeal review deadline
# ---------------------------------------------------------------------------

def appeal_track(incident):
    account = STORE.accounts.get(incident.get("account_id")) or {}
    policy = policy_for_region(account.get("home_region_code"))
    if (incident.get("prior_incident_count_at_intake") or 0) >= policy.get(
            "expedite_appeal_baseline_count", 5):
        return "EXPEDITED", int(policy.get("expedite_review_days", 14))
    return "STANDARD", int(policy.get("standard_review_days", 30))


def appeal_review_due_at(incident, past=None):
    """appeal_committed_at (the arrival instant of the first committed appeal)."""
    if past is None:
        past = now()
    account = STORE.accounts.get(incident.get("account_id")) or {}
    policy = policy_for_region(account.get("home_region_code"))
    _, review_days = appeal_track(incident)
    return add_days(past, review_days)