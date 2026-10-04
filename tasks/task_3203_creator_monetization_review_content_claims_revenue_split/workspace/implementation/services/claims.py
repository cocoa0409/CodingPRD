"""Claims, disputes, the appeal ladder and takedown.

Claim-level bookkeeping follows PRD section 3.4: appeal_attempts counts appeals
lodged, appeal_count counts those still PENDING, and lock_reason drives the
derived revenue_locked flag.
"""

import db
from db import add_days, now, parse_iso8601, to_iso8601, touch
from errors import raise_error
from services import channel as channel_svc
from services import content as content_svc
from services.money import APPEAL_LOCKOUT_DAYS, DISPUTE_WINDOW_DAYS, floor_confidence

DISPUTE_REASON_CODES = {"FAIR_USE", "LICENSED", "PUBLIC_DOMAIN", "MISMATCH", "OWNERSHIP"}
APPEAL_GROUNDS_CODES = {"REVIEW_ERROR", "NEW_EVIDENCE", "MISIDENTIFIED"}


def refresh_claim_derived(claim):
    """Recompute appeal_attempts, appeal_count and revenue_locked."""
    appeals = appeals_of(claim["id"])
    claim["appeal_attempts"] = len(appeals)
    claim["appeal_count"] = sum(1 for a in appeals if a["status"] == "PENDING")
    claim["revenue_locked"] = claim.get("lock_reason", "NONE") != "NONE"
    return claim


def appeals_of(claim_id):
    return [a for a in db.all_of("claim_appeals") if a["claim_id"] == claim_id]


def disputes_of(claim_id):
    return [d for d in db.all_of("claim_disputes") if d["claim_id"] == claim_id]


def locked_claims_of(item_id):
    return [
        c
        for c in db.all_of("claims")
        if c["content_item_id"] == item_id and c.get("lock_reason", "NONE") != "NONE"
    ]


def pending_appeal(claim_id):
    for appeal in appeals_of(claim_id):
        if appeal["status"] == "PENDING":
            return appeal
    return None


def latest_appeal(claim_id):
    appeals = appeals_of(claim_id)
    if not appeals:
        return None
    return max(appeals, key=lambda a: (a["created_at"], a["id"]))


def create_claim(content_item, reference_file, match_confidence, source,
                 claim_level="STANDARD"):
    """Materialise a Claim row and, on an OPEN channel, lock the item's revenue."""
    channel = db.get("channels", content_item["channel_id"])
    posture = channel.get("monetization_posture") if channel else None

    # A claim is born ACTIVE; its lock_reason is PENDING_RETRO only while the
    # owning channel's posture is OPEN (PRD section 3.4).
    status = "ACTIVE"
    lock_reason = "PENDING_RETRO" if posture == "OPEN" else "NONE"

    claim = db.common_fields(
        {
            "content_item_id": content_item["id"],
            "reference_file_id": reference_file["id"] if reference_file else None,
            "match_confidence": floor_confidence(match_confidence),
            "source": source,
            "status": status,
            "claim_level": claim_level or "STANDARD",
            "lock_reason": lock_reason,
            "revenue_locked": lock_reason != "NONE",
            "taken_down_at": None,
            "dispute_deadline_at": None,
            "appeal_attempts": 0,
            "appeal_count": 0,
            "copyright_counter_notified": False,
        }
    )
    db.insert("claims", claim)

    if lock_reason != "NONE":
        content_svc.lock_item_revenue(content_item, reason_code="PENDING_RETRO")
        touch(content_item)
    return claim


def file_dispute(claim, expected_claim_version, reason_code, narrative):
    """POST /claims/{id}/dispute -- OCC-guarded on the claim."""
    if expected_claim_version is not None and int(expected_claim_version) != claim["version"]:
        raise_error("ERR_STALE_VERSION")

    if claim["status"] == "TAKEN_DOWN":
        raise_error("ERR_CLAIM_TERMINAL")
    if claim["status"] == "DISPUTED":
        raise_error("ERR_CLAIM_ALREADY_DISPUTED")
    if claim["status"] != "ACTIVE":
        raise_error("ERR_INVALID_STATE")

    item = db.get("content_items", claim["content_item_id"])
    channel = db.get("channels", item["channel_id"])
    if channel.get("monetization_posture") == "FROZEN":
        raise_error("ERR_POSTURE_FROZEN")
    if channel.get("monetization_posture") == "RESTRICTED":
        raise_error("ERR_POSTURE_RESTRICTED")

    # Business-temporal: the thirty-day dispute window.
    created_at = parse_iso8601(claim["created_at"])
    if created_at is None or created_at < add_days(now(), -DISPUTE_WINDOW_DAYS):
        raise_error("ERR_DISPUTE_WINDOW_CLOSED")

    dispute = db.subresource_fields(
        {
            "claim_id": claim["id"],
            "reason_code": reason_code,
            "narrative": narrative,
            "status": "FILED",
        }
    )
    db.insert("claim_disputes", dispute)

    claim["dispute_deadline_at"] = to_iso8601(add_days(created_at, DISPUTE_WINDOW_DAYS))
    claim["status"] = "DISPUTED"
    claim["lock_reason"] = "RETROACTIVE_OWED"
    refresh_claim_derived(claim)
    touch(claim)

    content_svc.lock_item_revenue(item, reason_code="RETROACTIVE_OWED")
    touch(item)
    return claim


def resolve_dispute(claim, resolution):
    """POST /claims/{id}/dispute/resolve -- RELEASE on a DISPUTED or TAKEN_DOWN claim."""
    status = claim["status"]
    if status == "TAKEN_DOWN":
        if not claim.get("copyright_counter_notified"):
            raise_error("ERR_CONTENT_ITEM_NOT_TAKEN_DOWN")
        if resolution != "RELEASE":
            raise_error("ERR_INVALID_STATE")
    elif status == "DISPUTED":
        if resolution != "RELEASE":
            raise_error("ERR_INVALID_STATE")
    else:
        raise_error("ERR_INVALID_STATE")

    if status == "DISPUTED":
        for dispute in disputes_of(claim["id"]):
            if dispute["status"] == "FILED":
                dispute["status"] = "RELEASED"

    claim["status"] = "RELEASED"
    claim["lock_reason"] = "NONE"
    refresh_claim_derived(claim)
    touch(claim)

    # PRD section 3.5: the release "recomputes the content item's holds_revenue
    # to false and its routed_revenue_cents to its restored figure".  The money
    # the release covers is the item's parked creator share, which is put back to
    # the split the applicable stream rate produces for each row's gross.
    item = db.get("content_items", claim["content_item_id"])
    content_svc.release_item_revenue(item)
    touch(item)
    return claim


def file_appeal(claim, grounds_code):
    """POST /claims/{id}/appeals -- FIRST, SECOND or the post-reinstatement rung."""
    if claim["status"] == "TAKEN_DOWN":
        raise_error("ERR_CLAIM_TERMINAL")

    existing = appeals_of(claim["id"])
    if len(existing) >= 2:
        raise_error("ERR_APPEAL_LIMIT_REACHED")

    if pending_appeal(claim["id"]) is not None:
        raise_error("ERR_APPEAL_ALREADY_PENDING")

    # The referenced content item must not currently be taken down
    # (PRD section 3.6).
    item = db.get("content_items", claim["content_item_id"])
    if item is not None and item.get("takedown_flag"):
        raise_error("ERR_CLAIM_TERMINAL")

    status = claim["status"]
    if status == "ACTIVE":
        raise_error("ERR_INVALID_STATE")

    if status == "REINSTATED":
        reinstating = None
        for appeal in existing:
            if appeal["status"] == "UPHELD" and appeal["appeal_level"] == "FIRST":
                if reinstating is None or appeal["created_at"] > reinstating["created_at"]:
                    reinstating = appeal
        if reinstating is None:
            raise_error("ERR_INVALID_STATE")
        unlocks_at = add_days(parse_iso8601(reinstating["created_at"]), APPEAL_LOCKOUT_DAYS)
        if now() < unlocks_at:
            raise_error("ERR_APPEAL_LOCKOUT")
        level = "FIRST"
    elif status == "DISPUTED":
        if len(existing) == 0:
            level = "FIRST"
        else:
            previous = latest_appeal(claim["id"])
            if (
                len(existing) == 1
                and previous is not None
                and previous["status"] in ("DENIED", "UPHELD")
                and previous["appeal_level"] == "FIRST"
            ):
                level = "SECOND"
            else:
                raise_error("ERR_APPEAL_LIMIT_REACHED")
    else:
        raise_error("ERR_INVALID_STATE")

    appeal = db.subresource_fields(
        {
            "claim_id": claim["id"],
            "appeal_level": level,
            "grounds_code": grounds_code,
            "status": "PENDING",
        }
    )
    db.insert("claim_appeals", appeal)

    claim["status"] = "APPEALED"
    claim["lock_reason"] = "RETROACTIVE_OWED"
    refresh_claim_derived(claim)
    touch(claim)
    return appeal


def decide_appeal(claim, appeal, decision):
    """POST /claims/{id}/appeals/{appealId}/decide."""
    if appeal["status"] != "PENDING":
        raise_error("ERR_INVALID_STATE")
    if claim["status"] != "APPEALED":
        raise_error("ERR_INVALID_STATE")

    item = db.get("content_items", claim["content_item_id"])

    if decision == "UPHOLD":
        appeal["status"] = "UPHELD"
        claim["status"] = "REINSTATED"
        claim["lock_reason"] = "NONE"
        refresh_claim_derived(claim)
        touch(claim)
        if item is not None:
            content_svc.release_item_revenue(item)
            touch(item)
    elif decision == "DENY":
        appeal["status"] = "DENIED"
        claim["status"] = "DISPUTED"
        claim["lock_reason"] = "RETROACTIVE_OWED"
        refresh_claim_derived(claim)
        touch(claim)
        if item is not None:
            touch(item)
    else:
        raise_error("ERR_INVALID_STATE")
    return appeal


def file_counter_notification(claim, statement):
    """POST /claims/{id}/counter-notifications."""
    if claim["status"] != "TAKEN_DOWN":
        raise_error("ERR_CONTENT_ITEM_NOT_TAKEN_DOWN")
    claim["copyright_counter_notified"] = True
    touch(claim)
    return claim


def take_down(claim):
    """POST /claims/{id}/takedown -- the four-hop copyright cascade."""
    if claim["status"] == "TAKEN_DOWN":
        raise_error("ERR_CLAIM_TERMINAL")

    item = db.get("content_items", claim["content_item_id"])
    channel = db.get("channels", item["channel_id"])

    if claim["status"] != "APPEALED":
        raise_error("ERR_INVALID_STATE")
    appeal = pending_appeal(claim["id"])
    if appeal is None or appeal["appeal_level"] != "SECOND":
        raise_error("ERR_INVALID_STATE")

    if channel.get("monetization_posture") == "FROZEN":
        raise_error("ERR_POSTURE_FROZEN")
    if channel.get("monetization_posture") == "RESTRICTED":
        raise_error("ERR_POSTURE_RESTRICTED")

    # hop 1: the claim goes down and one CopyrightStrike is created.
    stamps = now()
    claim["status"] = "TAKEN_DOWN"
    claim["taken_down_at"] = to_iso8601(stamps)
    refresh_claim_derived(claim)
    touch(claim)
    channel_svc.issue_copyright_strike(channel["id"], item["id"], claim["id"])

    # hop 2: the channel's strike counters are remeasured.
    channel_svc.refresh_copyright_strike_count(channel["id"])

    # hop 3: the strike thresholds are applied.
    channel_svc.apply_copyright_strike_thresholds(channel["id"])
    touch(channel)

    # hop 4: the item is forced unsuitable and hidden.
    item["ad_suitability"] = "NO_ADS"
    item["takedown_flag"] = True
    content_svc.mark_view_invisible(item)
    touch(item)
    return claim