"""Posts, reports, automated detection, brigading and content decisions.

§1.2 transitions (4), (5), (7), §3.3 (posts, reports, detection, legitimacy),
§3.4 (decisions, sanction registry), §3.5 (brigading, health).
"""

from decimal import Decimal
from math import ceil, floor

import db
from db import dec, round2, iso, now, parse_dt, days_between, at_least_days
from errors import fail
from services import community as community_svc
from services import teams

POST_TYPES = ("TEXT", "LINK", "IMAGE", "CROSSPOST")
SOURCE_TYPES = ("POST", "COMMENT", "ACCOUNT")
REPORT_REASONS = ("SPAM", "HARASSMENT", "HATE_SPEECH", "VIOLENCE", "MINOR_SAFETY",
                  "BRIGADING", "VOTE_MANIPULATION", "IMPERSONATION")
DECISION_OUTCOMES = ("KEEP", "REMOVE", "LOCK", "REPORT_REJECTED", "WARNING_ISSUED",
                     "MUTE_ISSUED", "BAN_ISSUED")
SANCTION_OUTCOMES = ("WARNING_ISSUED", "MUTE_ISSUED", "BAN_ISSUED")

OUTCOME_BASE = {
    "KEEP": 0,
    "REPORT_REJECTED": 0,
    "WARNING_ISSUED": 1,
    "REMOVE": 2,
    "LOCK": 3,
    "MUTE_ISSUED": 4,
    "BAN_ISSUED": 5,
}

BAND_WEIGHT = {"HIGH": Decimal("1.0"), "MID": Decimal("1.5"), "LOW": Decimal("2.0")}
PENALTY_CAP = 40
LOW_SCORE_CEILING = 30
MID_SCORE_CEILING = 60


# --------------------------------------------------------------------------
# Posts
# --------------------------------------------------------------------------
def create_post(community, data):
    community_svc.guard_mutable(community)
    post_type = data["post_type"]
    if post_type not in POST_TYPES:
        fail("ERR_INVALID_REQUEST", "post_type is not a recognised value")
    record = {
        "community_id": community["id"],
        "author_account_id": data["author_account_id"],
        "title": data.get("title"),
        "body": data.get("body"),
        "post_type": post_type,
        "is_over_18": bool(data.get("is_over_18", False)),
        "status": "PUBLISHED",
        "removal_count": 0,
    }
    db.insert("Post", record)
    return record


# --------------------------------------------------------------------------
# Content reports
# --------------------------------------------------------------------------
def create_report(community, data):
    community_svc.guard_mutable(community)
    source_type = data["content_source_type"]
    if source_type not in SOURCE_TYPES:
        fail("ERR_INVALID_REQUEST", "content_source_type is not a recognised value")
    reason = data["report_reason_code"]
    if reason not in REPORT_REASONS:
        fail("ERR_INVALID_REQUEST", "report_reason_code is not a recognised value")
    tier = data["resolution_tier"]
    if tier not in (1, 2, 3):
        fail("ERR_INVALID_REQUEST", "resolution_tier must be 1, 2 or 3")

    backlog_match = None
    for item in db.children("AutoDetectionBacklogItem", "community_id", community["id"]):
        if (item["status"] == "OPEN"
                and item["source_type"] == source_type
                and item["source_id"] == data["content_source_id"]):
            backlog_match = item["id"]
            break

    record = {
        "community_id": community["id"],
        "content_source_type": source_type,
        "content_source_id": data["content_source_id"],
        "reporter_account_id": data.get("reporter_account_id"),
        "report_reason_code": reason,
        "resolution_tier": tier,
        "status": "OPEN",
        "detection_backlog_item_id": backlog_match,
    }
    db.insert("ContentReport", record)
    community_svc.recompute(community)
    return record


def dismiss_report(community, report):
    if report["status"] == "RESOLVED_LOCKED":
        fail("ERR_INVALID_STATE")
    report["status"] = "DISMISSED"
    db.touch(report)
    community_svc.recompute(community)
    return report


def maybe_autodismiss_duplicates(community, report):
    """A duplicate report may be dismissed during a decision sweep."""
    cluster = [r for r in db.children("ContentReport", "community_id", community["id"])
               if r.get("content_source_type") == report.get("content_source_type")
               and r.get("content_source_id") == report.get("content_source_id")]
    return cluster


# --------------------------------------------------------------------------
# Automated detection and the legitimacy score (§3.3)
# --------------------------------------------------------------------------
def legitimacy_score(community_id, source_type, source_id, published_at):
    """Pinned order: band_pre from the OPEN report count FIRST, then the score.

    `report_count` is the number of OPEN ContentReports on the detected content,
    so the report created for this very detection is already among them.
    """
    report_count = 0
    for report in db.children("ContentReport", "community_id", community_id):
        if (report["status"] == "OPEN"
                and report["content_source_type"] == source_type
                and report["content_source_id"] == source_id):
            report_count += 1

    age_days = days_between(parse_dt(published_at), now())
    auto_flag = source_type != "ACCOUNT"

    band_pre = "HIGH" if report_count == 0 else ("MID" if report_count <= 3 else "LOW")
    age_weight = Decimal("1.0") if age_days >= 365 else Decimal("1.5")
    type_weight = Decimal("1.0") if not auto_flag else Decimal("1.5")
    band_weight = BAND_WEIGHT[band_pre]
    penalty = min(PENALTY_CAP,
                  floor(Decimal(report_count) * band_weight * age_weight * type_weight))
    base = 70 if age_days >= 30 else 50
    score = max(0, base - penalty)
    band_final = "LOW" if score < LOW_SCORE_CEILING else (
        "MID" if score < MID_SCORE_CEILING else "HIGH")
    return score, band_final, report_count


def create_backlog_item(community, data):
    community_svc.guard_mutable(community)
    source_type = data["source_type"]
    if source_type not in SOURCE_TYPES:
        fail("ERR_INVALID_REQUEST", "source_type is not a recognised value")
    published = data["published_at_utc"]
    if parse_dt(published) is None:
        fail("ERR_INVALID_REQUEST", "published_at_utc is required")

    for existing in db.children("AutoDetectionBacklogItem", "community_id", community["id"]):
        if (existing["source_type"] == source_type
                and existing["source_id"] == data["source_id"]
                and existing["status"] == "OPEN"):
            fail("ERR_INVALID_STATE", "an OPEN detection already covers this content")

    record = {
        "community_id": community["id"],
        "source_type": source_type,
        "source_id": data["source_id"],
        "subject_account_id": data["subject_account_id"],
        "signal_severity_band": data["signal_severity_band"],
        "detection_confidence": data["detection_confidence"],
        "overlap_ratio": data["overlap_ratio"],
        "published_at_utc": iso(parse_dt(published)),
        "status": "OPEN",
    }
    db.insert("AutoDetectionBacklogItem", record)

    account = ensure_account(record["subject_account_id"])
    account["account_state"] = "WARNED"
    db.touch(account)
    return record


def backlog_response(record):
    """The detection response carries legitimacy_score and legitimacy_band."""
    payload = db_to_json(record)
    score, band, _count = legitimacy_score(
        record["community_id"], record["source_type"], record["source_id"],
        record["published_at_utc"])
    payload["legitimacy_score"] = score
    payload["legitimacy_band"] = band
    return payload


def db_to_json(record):
    """Legitimacy-derived fields must not persist on the stored item."""
    out = {}
    for key, value in record.items():
        if key.startswith("_") or key in ("legitimacy_score", "legitimacy_band"):
            continue
        out[key] = float(value) if hasattr(value, "quantize") else value
    return out


def backlog_json(record, community_id, source_type, source_id, published_at):
    """The detection response carries legitimacy_score and legitimacy_band."""
    payload = db_to_json(record)
    score, band, _count = legitimacy_score(community_id, source_type, source_id, published_at)
    payload["legitimacy_score"] = score
    payload["legitimacy_band"] = band
    return payload


# --------------------------------------------------------------------------
# Accounts (referenced by opaque identifiers, materialized on first reference)
# --------------------------------------------------------------------------
def ensure_account(account_id):
    if account_id is None:
        return None
    account = db.find("Account", account_id)
    if account is not None:
        return account
    record = {
        "id": account_id,
        "handle": account_id,
        "home_community_id": None,
        "account_state": "HONORED",
        "karma_points": 100,
    }
    stamp = iso(now())
    record["created_at"] = stamp
    record["updated_at"] = stamp
    record["version"] = 1
    db.bucket("Account")[account_id] = record
    return record


def load_account(account_id):
    account = db.find("Account", account_id)
    if account is None:
        fail("ERR_ACCOUNT_NOT_FOUND")
    return account


def recompute_account(account_id, touch=True):
    """Derive karma_points and account_sanction_index from the sanction rows.

    A read of the account projects the same values without mutating the row.
    """
    account = db.find("Account", account_id)
    if account is None:
        return None
    rows = [s for s in db.all_of("AccountSanction") if s["account_id"] == account_id]
    active = [s for s in rows if s["status"] == "ACTIVE"]

    communities = set()
    for row in active:
        if row["decision_outcome"] in ("MUTE_ISSUED", "BAN_ISSUED"):
            communities.add(row["community_id"])
    karma = 100 - 3 * len(communities)
    account["karma_points"] = max(50, karma)

    if any(s["decision_outcome"] == "BAN_ISSUED" for s in active):
        account["account_state"] = "BANNED"
    elif any(s["decision_outcome"] == "MUTE_ISSUED" for s in active):
        account["account_state"] = "MUTED"
    elif any(s["decision_outcome"] == "WARNING_ISSUED" for s in active):
        account["account_state"] = "WARNED"
    else:
        account["account_state"] = "HONORED"

    account["account_sanction_index"] = round2(community_svc.sanction_index_ratio(account_id))
    if touch:
        db.touch(account)
    return account


# --------------------------------------------------------------------------
# Sanction registry points (§3.4)
# --------------------------------------------------------------------------
def sanction_award_points(account_id, already_counted=False):
    """Tiered award points over the sanctioned account's sanction registry.

    The PRD's worked anchors (first offence 150, second 250, fourth 400) pin the
    tier to the registry as it stands BEFORE the current sanction is recorded,
    so `registry_size_pre` is the number of rows already present.
    """
    rows = [s for s in db.all_of("AccountSanction") if s["account_id"] == account_id]

    armor_points = 30 if any(
        s["status"] == "LIFTED" and s["account_wide_enforcement_counted"] for s in rows) else 0
    premature = any(
        s["status"] == "ACTIVE" and db.parse_dt(s["sanction_date_utc"]) is not None
        and (now() - db.parse_dt(s["sanction_date_utc"])).days < 30
        for s in rows)
    if armor_points != 0 and premature:
        refund = min(150, 30 + 120)
    else:
        refund = 0

    registry_size_pre = len(rows)
    if registry_size_pre == 0:
        tier_base = 150
    elif registry_size_pre <= 2:
        tier_base = 250
    else:
        tier_base = 400
    return tier_base - refund


def create_sanction(account_id, community_id, decision_id, outcome,
                    account_wide=False, award_points=None):
    if award_points is None:
        award_points = sanction_award_points(account_id)
    record = {
        "community_id": community_id,
        "account_id": account_id,
        "decision_id": decision_id,
        "decision_outcome": outcome,
        "status": "ACTIVE",
        "account_wide_enforcement_counted": bool(account_wide),
        "award_points": award_points,
        "sanction_date_utc": iso(now()),
        "sanitized_on_utc": None,
    }
    db.insert("AccountSanction", record)
    return record


# --------------------------------------------------------------------------
# Content decisions (§3.4)
# --------------------------------------------------------------------------
def effective_enforcement_tier(outcome, band, confidence, precedent):
    base = OUTCOME_BASE[outcome] + band
    if band >= 3:
        credit = 1 if confidence >= 0.60 else 0
    else:
        credit = 0
    tier = min(5, base - credit)
    if tier == 5 and precedent >= 3:
        tier = 4
    return tier


def create_decision(community, data, actor):
    community_svc.guard_mutable(community)
    outcome = data["decision_outcome"]
    if outcome not in DECISION_OUTCOMES:
        fail("ERR_INVALID_REQUEST", "decision_outcome is not a recognised value")
    band = data["dissection_band"]
    if band < 0 or band > 5:
        fail("ERR_INVALID_REQUEST", "dissection_band must be 0..5")
    confidence = data["decision_confidence"]
    if confidence < 0.0 or confidence > 1.0:
        fail("ERR_INVALID_REQUEST", "decision_confidence must be 0.0..1.0")
    precedent = data["precedent_approval_count"]

    item = db.find("AutoDetectionBacklogItem", data["auto_detection_backlog_item_id"])
    if item is None:
        fail("ERR_NOT_FOUND")
    if item["status"] != "OPEN":
        fail("ERR_NOT_FOUND")

    tier = effective_enforcement_tier(outcome, band, confidence, precedent)
    record = {
        "community_id": community["id"],
        "auto_detection_backlog_item_id": item["id"],
        "decision_outcome": outcome,
        "decision_confidence": confidence,
        "dissection_band": band,
        "precedent_approval_count": precedent,
        "community_health_index_override_present": bool(
            data.get("community_health_index_override_present", False)),
        "overlap_ratio": item["overlap_ratio"],
        "is_account_wide": False,
        "effective_enforcement_tier": tier,
        "community_safety_override": (tier == 5
                                      and not bool(data.get(
                                          "community_health_index_override_present", False))),
        "requires_cross_power_approval": (tier == 5 and precedent < 3),
        "status": "RECORDED",
        "audit_log_ref": "aud_" + db.new_id(),
        "_moved_report_ids": [],
        "subject_account_id": item["subject_account_id"],
    }
    db.insert("ContentDecision", record)

    item["status"] = "CONSUMED"
    db.touch(item)

    _cascade_reports(community, item, record)
    if outcome in SANCTION_OUTCOMES:
        sanction = create_sanction(item["subject_account_id"], community["id"],
                                   record["id"], outcome)
        record["sanction_id"] = sanction["id"]
        recompute_account(item["subject_account_id"])

    teams.mark_action(community["id"], "CONTENT_DECISION")
    community_svc.refresh_derived(community)
    db.touch(community)
    community_svc.apply_sanction_posture(community, item["subject_account_id"])
    community_svc.settle_health_posture(community)
    _auto_settle(record)
    return record


def _cascade_reports(community, item, decision):
    outcome = decision["decision_outcome"]
    moved = []
    for report in db.children("ContentReport", "community_id", community["id"]):
        if report["content_source_type"] != item["source_type"]:
            continue
        if report["content_source_id"] != item["source_id"]:
            continue
        if report["status"] == "RESOLVED_LOCKED":
            continue
        if outcome == "LOCK":
            report["status"] = "RESOLVED_LOCKED"
        elif outcome == "REPORT_REJECTED":
            if report["status"] == "RESOLVED":
                report["status"] = "OPEN"
        else:
            if report["status"] == "OPEN":
                report["status"] = "RESOLVED"
        moved.append(report["id"])
        db.touch(report)
    decision["_moved_report_ids"] = moved
    return moved


def _auto_settle(decision):
    if decision["effective_enforcement_tier"] <= 3 and decision["status"] == "RECORDED":
        decision["status"] = "SETTLED"
        decision["audit_log_ref"] = decision["audit_log_ref"] + ":sealed"
        db.touch(decision)


def audit_decision(decision):
    if decision["status"] != "RECORDED":
        fail("ERR_INVALID_STATE")
    if not decision["requires_cross_power_approval"]:
        fail("ERR_INVALID_STATE")
    decision["status"] = "AUDITED"
    decision["audit_log_ref"] = decision["audit_log_ref"] + ":audit+" + db.new_id()[:8]
    db.touch(decision)
    community = db.find("Community", decision["community_id"])
    if community is not None:
        community_svc.recompute(community)
    return decision


def revise_decision(decision):
    if decision["status"] != "AUDITED":
        fail("ERR_INVALID_STATE")
    decision["status"] = "REVISED"
    decision["audit_log_ref"] = decision["audit_log_ref"] + ":revision+" + db.new_id()[:8]
    db.touch(decision)

    sanction = db.find("AccountSanction", decision.get("sanction_id"))
    if sanction is not None and sanction["status"] == "ACTIVE":
        sanction["status"] = "LIFTED"
        sanction["sanitized_on_utc"] = iso(now())
        db.touch(sanction)
        recompute_account(sanction["account_id"])

    for report_id in decision.get("_moved_report_ids", []):
        report = db.find("ContentReport", report_id)
        if report is None:
            continue
        if report["status"] == "RESOLVED_LOCKED":
            continue
        report["status"] = "OPEN"
        db.touch(report)

    community = db.find("Community", decision["community_id"])
    if community is not None:
        community_svc.recompute(community)
    return decision


def reaudit_decision(decision):
    if decision["status"] != "REVISED":
        fail("ERR_INVALID_STATE")
    decision["status"] = "AUDITED"
    decision["audit_log_ref"] = decision["audit_log_ref"] + ":reaudit+" + db.new_id()[:8]
    db.touch(decision)
    return decision


def account_wide_sanction(data, actor):
    account_id = data["account_id"]
    community_id = data["community_id"]
    outcome = data["decision_outcome"]
    if outcome not in DECISION_OUTCOMES:
        fail("ERR_INVALID_REQUEST", "decision_outcome is not a recognised value")
    community = community_svc.fetch_or_404(community_id)
    community_svc.guard_mutable(community)
    ensure_account(account_id)

    # §2.6 ranks the sanction-reinstatement conflict ahead of community-name and
    # rule-code uniqueness, but §3.4 names this duplicate case explicitly as
    # ERR_ACCOUNT_WIDE_CONFLICT, which owns it.
    for existing in db.all_of("AccountSanction"):
        if (existing["account_id"] == account_id
                and existing["community_id"] == community_id
                and existing["status"] == "ACTIVE"
                and existing["account_wide_enforcement_counted"]
                and existing["decision_outcome"] == outcome):
            fail("ERR_ACCOUNT_WIDE_CONFLICT")

    decision = {
        "community_id": community_id,
        "auto_detection_backlog_item_id": None,
        "decision_outcome": outcome,
        "decision_confidence": None,
        "dissection_band": None,
        "precedent_approval_count": None,
        "community_health_index_override_present": False,
        "overlap_ratio": None,
        "is_account_wide": True,
        "effective_enforcement_tier": None,
        "community_safety_override": False,
        "requires_cross_power_approval": False,
        "status": "SETTLED",
        "audit_log_ref": "aud_" + db.new_id() + ":sealed",
        "_moved_report_ids": [],
        "subject_account_id": account_id,
    }
    db.insert("ContentDecision", decision)

    sanction = create_sanction(account_id, community_id, decision["id"], outcome,
                               account_wide=True)
    decision["sanction_id"] = sanction["id"]
    db.touch(decision)

    recompute_account(account_id)
    community_svc.refresh_derived(community)
    db.touch(community)
    community_svc.apply_sanction_posture(community, account_id)
    community_svc.settle_health_posture(community)
    return sanction


def reinstate_sanction(sanction):
    if sanction["status"] != "LIFTED":
        fail("ERR_INVALID_STATE")
    community = community_svc.fetch(sanction["community_id"])
    if community is None or community["state"] not in ("ACTIVE", "RESTRICTED"):
        fail("ERR_ACTIVE_SANCTION_CONFLICT")
    if community["state"] == "QUARANTINED":
        fail("ERR_ACTIVE_SANCTION_CONFLICT")
    sanction["status"] = "ACTIVE"
    sanction["sanitized_on_utc"] = None
    db.touch(sanction)
    recompute_account(sanction["account_id"])
    community_svc.recompute(community)
    return sanction


# --------------------------------------------------------------------------
# Brigading clusters (§3.5)
# --------------------------------------------------------------------------
def overlap_ratio(participant_count, legitimate_participant_count):
    if participant_count < 1:
        fail("ERR_INVALID_REQUEST", "participant_count must be at least 1")
    raw = Decimal(1) - Decimal(legitimate_participant_count) / Decimal(participant_count)
    if raw < 0:
        raw = Decimal(0)
    return round2(raw)


def signal_severity_band(internal_links, external_links, participant_count, overlap):
    breadth = internal_links + external_links
    severity = 1
    if breadth >= 5:
        severity += 1
    if breadth >= 10:
        severity += 1
    if breadth >= 20:
        severity += 1
    if participant_count >= 50:
        severity += 1
    if dec(overlap) >= Decimal("0.60"):
        severity += 1
    return min(5, severity)


def create_cluster(community, data):
    community_svc.guard_mutable(community)
    internal = data["internal_link_count"]
    external = data["external_link_count"]
    participants = data["participant_count"]
    legitimate = data["legitimate_participant_count"]
    for name, value in (("internal_link_count", internal),
                        ("external_link_count", external),
                        ("participant_count", participants),
                        ("legitimate_participant_count", legitimate)):
        if value < 0:
            fail("ERR_INVALID_REQUEST", f"{name} must not be negative")
    overlap = overlap_ratio(participants, legitimate)
    record = {
        "community_id": community["id"],
        "internal_link_count": internal,
        "external_link_count": external,
        "participant_count": participants,
        "legitimate_participant_count": legitimate,
        "overlap_ratio": overlap,
        "signal_severity_band": signal_severity_band(internal, external, participants, overlap),
        "evidence_complete": overlap >= Decimal("0.30"),
        "escalation_severity": None,
        "status": "DETECTED",
        "detected_at_utc": iso(now()),
    }
    db.insert("BrigadingCluster", record)
    teams.mark_action(community["id"], "BRIGADE_CLUSTER")
    return record


def brigade_penalty_points(community_id):
    """§3.5 per-cluster penalty: min(band * (1 + floor(overlap * 10)), 30)."""
    from services import community as community_svc
    total = 0
    for cluster in community_svc.escalated_clusters(community_id):
        per = cluster["signal_severity_band"] * (
            1 + floor(dec(cluster["overlap_ratio"]) * Decimal(10)))
        total += min(30, per)
    return total


def _refresh_health_only(community):
    """Recompute the health index without firing the self-loop recompute."""
    from services import community as community_svc
    community["health_index"] = community_svc.compute_health_index(
        community["id"], community["inactive_moderator_count"])


def brigade_escalation_severity(cluster, health):
    base = floor(Decimal(cluster["signal_severity_band"]) * (Decimal(1) + dec(cluster["overlap_ratio"])))
    bump = 1 if dec(health) >= Decimal(60) else 0
    return min(5, base + bump)


def escalate_cluster(cluster, sanction_ladder=None):
    from services import community as community_svc
    community = community_svc.fetch_or_404(cluster["community_id"])
    community_svc.guard_mutable(community)
    if cluster["status"] != "DETECTED":
        fail("ERR_INVALID_STATE")
    if not cluster["evidence_complete"]:
        fail("ERR_BRIGADE_EVIDENCE_INCOMPLETE")
    if cluster["signal_severity_band"] < 3:
        fail("ERR_BRIGADE_SEVERITY_TOO_LOW")

    cluster["status"] = "ESCALATED"
    cluster["_sanction_ladder"] = sanction_ladder
    db.touch(cluster)

    # §3.5: the escalation's own health recompute is the preparation step, so the
    # severity is read against the health index that recompute produced.
    community_svc.refresh_derived(community)
    severity = brigade_escalation_severity(cluster, community["health_index"])
    cluster["escalation_severity"] = severity
    db.touch(cluster)

    community_svc.recompute(community)
    return cluster


def revive_cluster(cluster):
    community = community_svc.fetch_or_404(cluster["community_id"])
    community_svc.guard_mutable(community)
    if cluster["status"] != "ESCALATED":
        fail("ERR_INVALID_STATE")
    if not at_least_days(parse_dt(cluster["detected_at_utc"]), 7):
        fail("ERR_COOLING_OFF_ACTIVE")
    cluster["status"] = "DETECTED"
    cluster["escalation_severity"] = None
    db.touch(cluster)
    community_svc.recompute(community)
    return cluster


def dismiss_cluster(community, cluster):
    community_svc.guard_mutable(community)
    if cluster["status"] != "DETECTED":
        fail("ERR_INVALID_STATE")
    if cluster["evidence_complete"]:
        fail("ERR_INVALID_STATE")
    cluster["status"] = "DISMISSED"
    cluster["escalation_severity"] = None
    db.touch(cluster)
    community_svc.recompute(community)
    return cluster