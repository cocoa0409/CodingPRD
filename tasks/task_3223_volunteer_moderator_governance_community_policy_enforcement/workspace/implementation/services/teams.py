"""Local rules, the volunteer team and team succession.

§1.2 transitions (2) and (3), §3.1 (local law), §3.2 (team, seniority, handover),
§3.9 (inactivity anchor).
"""

from db import iso, now, advance, parse_dt, at_least_days
from errors import fail
import db
from services import community as community_svc

MODERATOR_ROLES = ("TOP_MODERATOR", "REGULAR_MODERATOR")
MODERATOR_STATUSES = ("ACTIVE", "REMOVED_FOR_INACTIVITY", "RESIGNED", "DEMOTED")
FLOOR_BAND_DEFAULT = 2
FLOOR_BAND_OVER_18 = 3


def floor_band(community):
    """The sitewide floor band for the community's declared maturity."""
    return FLOOR_BAND_OVER_18 if community.get("is_over_18") else FLOOR_BAND_DEFAULT


# --------------------------------------------------------------------------
# Moderation attribution log (§2.10)
# --------------------------------------------------------------------------
def log_action(moderator_row, kind):
    record = {
        "moderator_id": moderator_row["id"],
        "community_id": moderator_row["community_id"],
        "action_kind": kind,
        "action_at_utc": iso(now()),
    }
    db.insert("ModerationAction", record)
    return record


def mark_action(community_id, kind):
    """Refresh the acting Moderator row's last_moderation_action_at_utc."""
    from middleware import acting_moderator_row

    row = acting_moderator_row(community_id)
    if row is None:
        return None
    row["last_moderation_action_at_utc"] = iso(now())
    row["inactivity_basis_utc"] = iso(community_svc.inactivity_anchor(row))
    log_action(row, kind)
    return row


# --------------------------------------------------------------------------
# Local rules (§3.1)
# --------------------------------------------------------------------------
def create_rule(community, data, actor):
    community_svc.guard_mutable(community)
    code = data["rule_code"]
    for existing in db.children("CommunityRule", "community_id", community["id"]):
        if existing["rule_code"] == code and existing["status"] == "ACTIVE":
            fail("ERR_DUPLICATE_RULE_CODE")

    band = data["rule_band"]
    is_floor = bool(data.get("is_sitewide_floor", False))
    if band < 1 or band > 3:
        fail("ERR_INVALID_REQUEST", "rule_band must be 1, 2 or 3")
    if is_floor and band < floor_band(community):
        fail("ERR_RULE_CONFLICT", "a sitewide floor rule may not declare a band below the floor")

    record = {
        "community_id": community["id"],
        "rule_code": code,
        "rule_text": data.get("rule_text"),
        "rule_band": band,
        "is_sitewide_floor": is_floor,
        "status": "ACTIVE",
    }
    db.insert("CommunityRule", record)
    mark_action(community["id"], "RULE_AUTHORED")
    community["active_rule_count"] = community_svc.active_rule_count(community["id"])
    db.touch(community)
    return record


def update_rule(community, rule, data):
    community_svc.guard_mutable(community)
    if rule["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")

    band = data.get("rule_band", rule["rule_band"])
    is_floor = data.get("is_sitewide_floor", rule["is_sitewide_floor"])
    if band < 1 or band > 3:
        fail("ERR_INVALID_REQUEST", "rule_band must be 1, 2 or 3")
    if is_floor and band < floor_band(community):
        fail("ERR_RULE_CONFLICT", "a sitewide floor rule may not declare a band below the floor")

    if "rule_text" in data and data["rule_text"] is not None:
        rule["rule_text"] = data["rule_text"]
    rule["rule_band"] = band
    rule["is_sitewide_floor"] = bool(is_floor)
    db.touch(rule)
    mark_action(community["id"], "RULE_AMENDED")
    community["active_rule_count"] = community_svc.active_rule_count(community["id"])
    db.touch(community)
    return rule


def escalate_rule(community, rule, note):
    community_svc.guard_mutable(community)
    if rule is None:
        fail("ERR_NOT_FOUND")
    if rule["community_id"] != community["id"]:
        fail("ERR_NOT_FOUND")
    if rule["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    rule["status"] = "RETIRED"
    db.touch(rule)
    record = {
        "community_id": community["id"],
        "rule_id": rule["id"],
        "escalation_note": note,
        "escalated_at_utc": iso(now()),
    }
    db.insert("EscalationRecord", record)
    community["active_rule_count"] = community_svc.active_rule_count(community["id"])
    db.touch(community)
    return rule, record


# --------------------------------------------------------------------------
# Appointments (§3.2)
# --------------------------------------------------------------------------
def appoint_moderator(community, data):
    community_svc.guard_mutable(community)
    role = data["moderator_role"]
    if role not in MODERATOR_ROLES:
        fail("ERR_INVALID_REQUEST", "moderator_role is not a recognised value")

    team = db.children("Moderator", "community_id", community["id"])
    highest = max((m.get("top_rank") or 0) for m in team) if team else 0
    record = {
        "community_id": community["id"],
        "moderator_account_id": data["moderator_account_id"],
        "display_name": data.get("display_name"),
        "moderator_role": role,
        "is_top_moderator": False,
        "top_rank": highest + 1,
        "last_moderation_action_at_utc": None,
        "inactivity_basis_utc": None,
        "status": "ACTIVE",
        "moderator_version": 1,
        "promoted_at_utc": None,
        "removal_reason_code": None,
    }
    db.insert("Moderator", record)
    community_svc.refresh_derived(community)
    db.touch(community)
    return record


# --------------------------------------------------------------------------
# Team mutations (§3.2)
# --------------------------------------------------------------------------
def _sod_self_demotion(actor, moderator):
    if actor.user_id == moderator["id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "a moderator may not demote itself")
    if actor.user_id == moderator.get("moderator_account_id"):
        fail("ERR_SEGREGATION_OF_DUTIES", "a moderator may not demote itself")


def touch_moderator(moderator):
    """A moderator-row mutation advances both its generic and OCC versions."""
    db.touch(moderator)
    moderator["moderator_version"] = moderator.get("moderator_version", 1) + 1
    return moderator


def remove_moderator(community, moderator):
    community_svc.guard_mutable(community)
    if moderator["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    if moderator.get("is_top_moderator"):
        completed = [s for s in db.children("TeamSuccession", "community_id", community["id"])
                     if s["state"] == "COMPLETED"]
        if not completed:
            fail("ERR_TOP_MODERATOR_REMOVAL_FORBIDDEN")
    remaining = [m for m in community_svc.active_moderators(community["id"])
                 if m["id"] != moderator["id"]]
    if not remaining:
        fail("ERR_FINAL_MODERATOR_REMOVAL")
    if not at_least_days(community_svc.inactivity_anchor(moderator), 90):
        fail("ERR_INACTIVITY_REMOVAL_NOT_JUSTIFIED")

    moderator["status"] = "REMOVED_FOR_INACTIVITY"
    moderator["removal_reason_code"] = "INACTIVITY"
    touch_moderator(moderator)
    community_svc.recompute(community)
    return moderator


def resign_moderator(community, moderator):
    community_svc.guard_mutable(community)
    if moderator["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    moderator["status"] = "RESIGNED"
    moderator["removal_reason_code"] = "RESIGNATION"
    touch_moderator(moderator)
    community_svc.recompute(community)
    return moderator


def demote_moderator(community, moderator, actor):
    community_svc.guard_mutable(community)
    # §3.2 lists three demotion preconditions — the distinct-account segregation
    # of duties, the TOP_MODERATOR role, and the moderator version — and states
    # that the segregation check is evaluated after the state check.
    if moderator["status"] != "ACTIVE" or moderator["moderator_role"] != "TOP_MODERATOR":
        fail("ERR_INVALID_STATE")
    _sod_self_demotion(actor, moderator)
    moderator["status"] = "DEMOTED"
    moderator["moderator_role"] = "REGULAR_MODERATOR"
    moderator["removal_reason_code"] = "TOP_DISPUTE_LOSS"
    touch_moderator(moderator)
    community_svc.refresh_derived(community)
    db.touch(community)
    return moderator


def reinstate_moderator(community, moderator):
    community_svc.guard_mutable(community)
    if moderator["status"] != "DEMOTED":
        fail("ERR_INVALID_STATE")
    if community["active_top_moderator_count"] < 1:
        fail("ERR_PENDING_HANDOVER")
    moderator["status"] = "ACTIVE"
    moderator["moderator_role"] = "REGULAR_MODERATOR"
    moderator["removal_reason_code"] = None
    touch_moderator(moderator)
    community_svc.refresh_derived(community)
    db.touch(community)
    return moderator


def reanchor_inactivity(community):
    """Re-derive every moderator's inactivity projection for this community."""
    community_svc.refresh_team_projection(community["id"])


# --------------------------------------------------------------------------
# Succession (§3.2)
# --------------------------------------------------------------------------
SUCCESSION_STATES = ("PENDING_HANDOVER", "DISCUSSION", "HANDOVER_BLOCKED", "COMPLETED")


def open_succession(community):
    community_svc.guard_mutable(community)
    initiated = now()
    record = {
        "community_id": community["id"],
        "state": "PENDING_HANDOVER",
        "initiated_at_utc": iso(initiated),
        "previous_state": "PENDING_HANDOVER",
        "discussion_round_count": 0,
        "handover_deadline_utc": iso(advance(initiated, 30)),
        "blocked_by_moderator_id": None,
        "completion_reason": None,
        "_last_discussion_actor_id": None,
    }
    db.insert("TeamSuccession", record)
    community["_succession_discussion_actor_id"] = None
    community["_succession_discussion_succession_id"] = None
    db.touch(community)
    return record


def record_discussion(community, succession, actor, note):
    community_svc.guard_mutable(community)
    if succession["state"] not in ("PENDING_HANDOVER", "DISCUSSION"):
        fail("ERR_INVALID_STATE")
    succession["previous_state"] = succession["state"]
    succession["state"] = "DISCUSSION"
    succession["discussion_round_count"] += 1
    succession["last_discussion_note"] = note
    succession["_last_discussion_actor_id"] = actor.user_id
    db.touch(succession)
    community["_succession_discussion_actor_id"] = actor.user_id
    community["_succession_discussion_succession_id"] = succession["id"]
    db.touch(community)
    return succession


def dispute_succession(community, succession, actor, note):
    community_svc.guard_mutable(community)
    if succession["state"] != "DISCUSSION":
        fail("ERR_INVALID_STATE")
    succession["previous_state"] = "DISCUSSION"
    succession["state"] = "HANDOVER_BLOCKED"
    succession["blocked_by_moderator_id"] = actor.user_id
    succession["_dispute_note"] = note
    db.touch(succession)
    db.touch(community)
    return succession


def succession_sod_violation(community, succession_id, actor):
    """§2.6 priority 3: evaluated before the existence check for the succession."""
    if community is None:
        return False
    if community.get("_succession_discussion_actor_id") is None:
        return False
    if actor.user_id != community["_succession_discussion_actor_id"]:
        return False
    recorded = community.get("_succession_discussion_succession_id")
    if succession_id == recorded:
        return True
    return db.find("TeamSuccession", succession_id) is None


def prevent_succession(community, succession):
    community_svc.guard_mutable(community)
    if succession["state"] != "HANDOVER_BLOCKED":
        fail("ERR_INVALID_STATE")
    succession["previous_state"] = "HANDOVER_BLOCKED"
    succession["state"] = "PENDING_HANDOVER"
    succession["blocked_by_moderator_id"] = None
    succession["discussion_round_count"] = 0
    db.touch(succession)
    db.touch(community)
    return succession


def settle_completions(community):
    """The three automatic completions of §3.2, evaluated against the clock."""
    community_svc.refresh_derived(community)
    for succession in db.children("TeamSuccession", "community_id", community["id"]):
        state = succession["state"]
        if state == "COMPLETED":
            continue
        deadline = parse_dt(succession.get("handover_deadline_utc"))
        if deadline is None or now() < deadline:
            continue
        if state == "PENDING_HANDOVER":
            if (community["active_top_moderator_count"] >= 1
                    and community["inactive_moderator_count"] == 0):
                _complete(succession, "HANDOVER_ACCEPTED")
        elif state == "DISCUSSION":
            team = db.children("Moderator", "community_id", community["id"])
            if (community["active_top_moderator_count"] == 0
                    and all(m["status"] != "ACTIVE" for m in team)):
                _complete(succession, "ALL_MODERATORS_INACTIVE")
        elif state == "HANDOVER_BLOCKED":
            _complete(succession, "PREVENTED_BY_DISPUTE")
    return community


def _complete(succession, reason):
    succession["previous_state"] = succession["state"]
    succession["state"] = "COMPLETED"
    succession["completion_reason"] = reason
    db.touch(succession)
    return succession