"""Community lifecycle, derived posture fields and the recompute self-loop.

§1.1 Community fields, §1.2 transitions (1), §2.9 posture propagation, §3.1,
§3.5 (health index), §3.8 (posture), §3.9 (inactivity).
"""

from decimal import Decimal
from math import floor

import db
from db import dec, round2, iso, now, advance, at_least_days, days_between
from errors import fail

TIER_WEIGHT = {1: Decimal("1.0"), 2: Decimal("1.5"), 3: Decimal("2.0")}
INACTIVITY_WINDOW_DAYS = 90
QUARANTINE_HEALTH_LINE = Decimal("40.00")
REINSTATEMENT_HEALTH_FLOOR = Decimal("70.00")
RESTRICT_GATE = Decimal("0.60")
NEGOTIATION_GATE = Decimal("0.80")
HEALTH_MIN = Decimal("0.00")
HEALTH_MAX = Decimal("100.00")


# --------------------------------------------------------------------------
# Derived aggregates
# --------------------------------------------------------------------------
def open_reports(community_id):
    return [r for r in db.children("ContentReport", "community_id", community_id)
            if r["status"] == "OPEN"]


def effective_open_report_weight(community_id):
    total = Decimal("0.00")
    for report in open_reports(community_id):
        total += round2(TIER_WEIGHT[report["resolution_tier"]] / Decimal(3))
    return round2(total)


def escalated_clusters(community_id):
    return [c for c in db.children("BrigadingCluster", "community_id", community_id)
            if c["status"] == "ESCALATED"]


def brigade_health_penalty(community_id):
    """STEP 2 of community_health_index: sum of the per-cluster brigade penalty.

    §3.5 pins the per-cluster penalty as `min(signal_severity_band *
    (1 + floor(overlap_ratio * 10)), 30)` and §3.5's aggregation is the sum of
    those caps — not the lesser of the summed raw products and 30.
    """
    total = 0
    for cluster in escalated_clusters(community_id):
        per = cluster["signal_severity_band"] * (
            1 + floor(dec(cluster["overlap_ratio"]) * Decimal(10)))
        total += min(30, per)
    return round2(Decimal(total))


def active_moderators(community_id):
    return [m for m in db.children("Moderator", "community_id", community_id)
            if m["status"] == "ACTIVE"]


def inactivity_anchor(moderator):
    """First non-null of: own last action, community restricted_since, created_at."""
    if moderator.get("last_moderation_action_at_utc") is not None:
        return db.parse_dt(moderator["last_moderation_action_at_utc"])
    community = db.find("Community", moderator.get("community_id"))
    if community is not None and community.get("restricted_since_utc") is not None:
        return db.parse_dt(community["restricted_since_utc"])
    return db.parse_dt(moderator.get("created_at"))


def is_inactive(moderator):
    anchor = inactivity_anchor(moderator)
    return anchor is not None and at_least_days(anchor, INACTIVITY_WINDOW_DAYS)


def inactive_moderator_count(community_id):
    return sum(1 for m in active_moderators(community_id) if is_inactive(m))


def applying_sanction_count(community_id):
    return sum(1 for s in db.children("AccountSanction", "community_id", community_id)
               if s["status"] == "ACTIVE")


def active_rule_count(community_id):
    return sum(1 for r in db.children("CommunityRule", "community_id", community_id)
               if r["status"] == "ACTIVE")


def enforcement_tier_for(count):
    if count <= 1:
        return 1
    if count == 2:
        return 2
    return 3


def compute_health_index(community_id, inactive_count):
    """Pinned order: per-report rounding, then per-cluster rounding, then STEP 3."""
    open_weight = effective_open_report_weight(community_id)
    brigade = brigade_health_penalty(community_id)
    inactivity = Decimal("2.5") * Decimal(inactive_count)
    raw = round2(Decimal(100) - open_weight - brigade - inactivity)
    if raw < HEALTH_MIN:
        return HEALTH_MIN
    if raw > HEALTH_MAX:
        return HEALTH_MAX
    return raw


# --------------------------------------------------------------------------
# Moderator projection
# --------------------------------------------------------------------------
def refresh_team_projection(community_id):
    """Recompute is_top_moderator and the inactivity projection across the team."""
    team = db.children("Moderator", "community_id", community_id)
    top_rows = [m for m in team if m["moderator_role"] == "TOP_MODERATOR" and m["status"] == "ACTIVE"]
    lowest = min((m["top_rank"] for m in top_rows), default=None)
    clock_stamp = iso(now())
    for row in team:
        was_top = row.get("is_top_moderator", False)
        is_top = (row["moderator_role"] == "TOP_MODERATOR"
                  and row["status"] == "ACTIVE"
                  and lowest is not None
                  and row["top_rank"] == lowest)
        row["is_top_moderator"] = is_top
        if is_top and not was_top:
            row["promoted_at_utc"] = clock_stamp
        elif not is_top:
            row["promoted_at_utc"] = None
        if row["status"] == "ACTIVE":
            anchor = inactivity_anchor(row)
            row["inactivity_basis_utc"] = iso(anchor)
        else:
            row["inactivity_basis_utc"] = None
    return team


def require_team_projection(community_id):
    """Refresh the projection only when an ACTIVE top-moderator seat may move."""
    refresh_team_projection(community_id)


# --------------------------------------------------------------------------
# The recompute self-loop (§1.2 transition (1), §2.9)
# --------------------------------------------------------------------------
def refresh_derived(community):
    """Recompute every derived community field; does not touch version."""
    community_id = community["id"]
    refresh_team_projection(community_id)
    community["open_report_weight"] = effective_open_report_weight(community_id)
    inactive = inactive_moderator_count(community_id)
    community["inactive_moderator_count"] = inactive
    team = db.children("Moderator", "community_id", community_id)
    community["active_moderator_count"] = sum(1 for m in team if m["status"] == "ACTIVE")
    community["active_top_moderator_count"] = sum(
        1 for m in team if m["status"] == "ACTIVE" and m.get("is_top_moderator"))
    community["active_rule_count"] = active_rule_count(community_id)
    applying = applying_sanction_count(community_id)
    community["applying_sanction_count"] = applying
    community["enforcement_tier"] = enforcement_tier_for(applying)
    community["health_index"] = compute_health_index(community_id, inactive)
    return community


def bump(community):
    """A plain community mutation: refresh updated_at and advance version."""
    db.touch(community)
    return community


def recompute(community, bump_version=True):
    """The ACTIVE->ACTIVE self-loop: recompute derived fields and mutate."""
    refresh_derived(community)
    if bump_version:
        db.touch(community)
    settle_health_posture(community)
    return community


# --------------------------------------------------------------------------
# Posture transitions driven by health
# --------------------------------------------------------------------------
def settle_health_posture(community):
    """Automatic RESTRICTED/INSTITUTION_NEGOTIATION -> QUARANTINED moves."""
    if community["state"] == "RESTRICTED":
        if community["health_index"] <= QUARANTINE_HEALTH_LINE:
            enter_quarantine(community)
    elif community["state"] == "INSTITUTION_NEGOTIATION":
        if community["health_index"] <= QUARANTINE_HEALTH_LINE and _negotiation_lapsed(community):
            enter_quarantine(community)
    return community


def _negotiation_lapsed(community):
    if not at_least_days(db.parse_dt(community.get("restricted_since_utc")), 30):
        return False
    since = community.get("_negotiation_since_utc")
    cadence = latest_cadence(community["id"])
    if cadence is None:
        return True
    if since is None:
        return True
    return cadence <= since


def latest_cadence(community_id):
    rows = [r for r in db.all_of("RegulationCadence") if r["community_id"] == community_id]
    if not rows:
        return None
    return max(db.parse_dt(r["cadence_at_utc"]) for r in rows)


def record_cadence(community_id):
    record = {"community_id": community_id, "cadence_at_utc": iso(now())}
    db.insert("RegulationCadence", record)
    return record


def enter_quarantine(community):
    """RESTRICTED / INSTITUTION_NEGOTIATION -> QUARANTINED; restricted_since preserved."""
    community["state"] = "QUARANTINED"
    refresh_derived(community)
    db.touch(community)
    return community


# --------------------------------------------------------------------------
# Posture transitions driven by the sanction index (§3.8)
# --------------------------------------------------------------------------
def sanction_index_ratio(account_id):
    """Unrounded numerator/denominator of account_sanction_index."""
    rows = [s for s in db.all_of("AccountSanction") if s["account_id"] == account_id]
    if not rows:
        return Decimal("0")
    numerator = 0
    for row in rows:
        if row["status"] != "ACTIVE":
            continue
        if row["account_wide_enforcement_counted"]:
            numerator += 1
        elif at_least_days(db.parse_dt(row["sanction_date_utc"]), 30):
            numerator += 1
    return Decimal(numerator) / Decimal(len(rows))


def apply_sanction_posture(community, account_id):
    """RESTRICTED then INSTITUTION_NEGOTIATION when the pinned gates are met."""
    if community["state"] != "ACTIVE" or account_id is None:
        return community
    ratio = sanction_index_ratio(account_id)
    if ratio >= RESTRICT_GATE:
        community["state"] = "RESTRICTED"
        community["restricted_since_utc"] = iso(now())
        refresh_derived(community)
        db.touch(community)
        if ratio >= NEGOTIATION_GATE:
            community["state"] = "INSTITUTION_NEGOTIATION"
            community["_negotiation_since_utc"] = iso(now())
            refresh_derived(community)
            db.touch(community)
    return community


# --------------------------------------------------------------------------
# Time-driven settling (handover deadlines, watchdog, negotiation lapse)
# --------------------------------------------------------------------------
def settle_time_driven(community):
    from services import teams, appeals

    teams.settle_completions(community)
    appeals.settle_watchdog(community)
    if community["state"] == "INSTITUTION_NEGOTIATION":
        refresh_derived(community)
        if (community["health_index"] <= QUARANTINE_HEALTH_LINE
                and _negotiation_lapsed(community)):
            enter_quarantine(community)
    return community


def settle_if_clock_moved():
    """Sweep every community's time-driven transitions once per clock value."""
    current = db.now()
    if db.settle["clock"] == current:
        return
    db.settle["clock"] = current
    for community in db.all_of("Community"):
        settle_time_driven(community)


def fetch(community_id):
    """Load a community and settle its time-driven automatic transitions."""
    community = db.find("Community", community_id)
    if community is not None:
        settle_time_driven(community)
    return community


def fetch_or_404(community_id):
    community = fetch(community_id)
    if community is None:
        fail("ERR_COMMUNITY_NOT_FOUND")
    return community


def guard_mutable(community):
    """Once ARCHIVED, every mutating operation against the community is refused."""
    if community["state"] == "ARCHIVED":
        fail("ERR_ARCHIVED_COMMUNITY")
    return community


# --------------------------------------------------------------------------
# Creation (§3.1)
# --------------------------------------------------------------------------
def create_community(data, actor):
    name = data["name"]
    for existing in db.all_of("Community"):
        if existing["name"] == name and existing["state"] != "CLOSED":
            fail("ERR_DUPLICATE_COMMUNITY_NAME")

    record = {
        "name": name,
        "description": data.get("description"),
        "is_over_18": bool(data.get("is_over_18", False)),
        "state": "ACTIVE",
        "enforcement_tier": 1,
        "health_index": round2(Decimal("100.00")),
        "open_report_weight": Decimal("0.00"),
        "inactive_moderator_count": 0,
        "active_top_moderator_count": 1,
        "active_moderator_count": 1,
        "active_rule_count": 0,
        "applying_sanction_count": 0,
        "quarantine_approval_count": 0,
        "quarantine_reinstatement_count": 0,
        "restricted_since_utc": None,
        "protest_exemption_until_utc": None,
        "_negotiation_since_utc": None,
    }
    db.insert("Community", record)

    founder = data.get("founding_moderator_account_id")
    if founder is None:
        founder = actor.user_id
    moderator = {
        "community_id": record["id"],
        "moderator_account_id": founder,
        "display_name": data.get("founding_moderator_display_name") or "Founder",
        "moderator_role": "TOP_MODERATOR",
        "is_top_moderator": True,
        "top_rank": 1,
        "last_moderation_action_at_utc": None,
        "inactivity_basis_utc": None,
        "status": "ACTIVE",
        "moderator_version": 1,
        "promoted_at_utc": iso(now()),
        "removal_reason_code": None,
    }
    db.insert("Moderator", moderator)
    refresh_derived(record)
    return record


# --------------------------------------------------------------------------
# Reinstatement (§3.8)
# --------------------------------------------------------------------------
def reinstatement_request(community_id, actor):
    from services import teams

    community = fetch_or_404(community_id)
    guard_mutable(community)
    state = community["state"]
    if state not in ("QUARANTINED", "RESTRICTED"):
        fail("ERR_INVALID_STATE")

    refresh_derived(community)
    if community["health_index"] < REINSTATEMENT_HEALTH_FLOOR:
        fail("ERR_REINSTATEMENT_CONDITIONS_UNMET")
    if community["inactive_moderator_count"] != 0:
        fail("ERR_REINSTATEMENT_CONDITIONS_UNMET")
    if community["active_top_moderator_count"] < 1:
        fail("ERR_REINSTATEMENT_CONDITIONS_UNMET")
    if state == "QUARANTINED":
        if not at_least_days(db.parse_dt(community.get("restricted_since_utc")), 90):
            fail("ERR_REINSTATEMENT_CONDITIONS_UNMET")
    if any(r["resolution_tier"] == 3 for r in open_reports(community_id)):
        fail("ERR_REINSTATEMENT_CONDITIONS_UNMET")

    if state == "QUARANTINED":
        community["state"] = "RESTRICTED"
        community["quarantine_reinstatement_count"] += 1
        community["restricted_since_utc"] = iso(now())
    else:
        community["state"] = "ACTIVE"
        community["restricted_since_utc"] = None
    teams.reanchor_inactivity(community)
    refresh_derived(community)
    db.touch(community)
    return community


# --------------------------------------------------------------------------
# Administrator posture instruments (§3.8)
# --------------------------------------------------------------------------
def policy_advisory(community_id):
    community = fetch_or_404(community_id)
    guard_mutable(community)
    if community["state"] != "PROTEST_RESTRICTED":
        fail("ERR_INVALID_STATE")
    community["protest_exemption_until_utc"] = iso(advance(now(), 7))
    for protest in db.children("ProtestEvent", "community_id", community_id):
        if protest["status"] == "COORDINATED":
            protest["exemption_granted_until_utc"] = community["protest_exemption_until_utc"]
            db.touch(protest)
    db.touch(community)
    return community


def regulation_cadence(community_id):
    community = fetch_or_404(community_id)
    guard_mutable(community)
    record_cadence(community_id)
    db.touch(community)
    return community


def institution_negotiation(community_id):
    community = fetch_or_404(community_id)
    guard_mutable(community)
    if community["state"] != "RESTRICTED":
        fail("ERR_INVALID_STATE")
    community["state"] = "INSTITUTION_NEGOTIATION"
    community["_negotiation_since_utc"] = iso(now())
    db.touch(community)
    return community


def archive(community_id):
    from services import teams, protests

    community = fetch_or_404(community_id)
    if community["state"] == "ARCHIVED":
        fail("ERR_ARCHIVED_COMMUNITY")
    if community["state"] != "QUARANTINED":
        fail("ERR_INVALID_STATE")

    for row in db.children("Moderator", "community_id", community_id):
        if row["status"] == "ACTIVE":
            row["status"] = "RESIGNED"
            row["removal_reason_code"] = "ADMIN_ARCHIVAL"
            row["inactivity_basis_utc"] = None
            row["is_top_moderator"] = False
            row["promoted_at_utc"] = None
            db.touch(row)
            row["moderator_version"] = row.get("moderator_version", 1) + 1
    for succession in db.children("TeamSuccession", "community_id", community_id):
        if succession["state"] != "COMPLETED":
            succession["previous_state"] = succession["state"]
            succession["state"] = "COMPLETED"
            succession["completion_reason"] = "ALL_MODERATORS_INACTIVE"
            db.touch(succession)
    for post in db.children("Post", "community_id", community_id):
        post["status"] = "LOCKED"
        db.touch(post)
    for protest in db.children("ProtestEvent", "community_id", community_id):
        if protest["status"] in ("REQUESTED", "COORDINATED"):
            protest["status"] = "ENDED"
            protest["ended_at_utc"] = iso(now())
            db.touch(protest)

    community["state"] = "ARCHIVED"
    refresh_derived(community)
    db.touch(community)
    return community


def all_fetched():
    """Every community, with time-driven transitions settled."""
    for community in db.all_of("Community"):
        settle_time_driven(community)
    return db.all_of("Community")