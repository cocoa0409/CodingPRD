"""Content items, advertiser classification and the rights scan.

The classification rule is the threshold rule of PRD section 3.3; the rights
scan resolves an item down the CLASSIFIED / CLAIM_SCAN_COMPLETE branch.
"""

import hashlib

import db
from db import now, to_iso8601, touch
from errors import raise_error
from services import channel as channel_svc
from services.money import STREAM_CREATOR_RATES, split_amount

# The recognised advertiser category vocabulary (PRD section 3.3).
LIMITED_ELIGIBLE = {"GAMBLING", "ALCOHOL", "POLITICS", "NEWS", "TRAGEDY", "MILDLANGUAGE"}
CATEGORY_VOCABULARY = LIMITED_ELIGIBLE

MILDLANGUAGE_SUPPRESSION_ENGAGEMENT_THRESHOLD = 1000

# The rights-scan match threshold (PRD section 3.3 / 3.4).
MATCH_THRESHOLD = 0.500


def classify(submitted_categories, like_count, comment_count):
    """Return (outcome, matched_sorted, reason_codes_sorted)."""
    matched = sorted(c for c in submitted_categories if c in LIMITED_ELIGIBLE)
    like_comments = int(like_count or 0) + int(comment_count or 0)
    if "MILDLANGUAGE" in matched and like_comments >= MILDLANGUAGE_SUPPRESSION_ENGAGEMENT_THRESHOLD:
        matched = [c for c in matched if c != "MILDLANGUAGE"]
    if len(matched) == 0:
        outcome = "AD_FRIENDLY"
    elif len(matched) == 1:
        outcome = "LIMITED_ADS"
    else:
        outcome = "NO_ADS"
    reason_codes = list(matched) if outcome != "AD_FRIENDLY" else []
    return outcome, matched, reason_codes


def validate_categories(categories):
    for code in categories:
        if code not in CATEGORY_VOCABULARY:
            raise_error("ERR_INVALID_CATEGORY_CODE")


def create_ad_review(item, outcome, matched_categories, reason_codes, like_count, comment_count):
    review = db.subresource_fields(
        {
            "content_item_id": item["id"],
            "outcome": outcome,
            "reason_codes": reason_codes,
            "matched_categories": sorted(matched_categories),
            "like_count": int(like_count or 0),
            "comment_count": int(comment_count or 0),
            "appeal_outcome": "NONE",
            "is_visible": True,
        }
    )
    db.insert("ad_reviews", review)
    item["ad_suitability"] = outcome
    item["limited_ads_reasons"] = reason_codes
    return review


def latest_ad_review(item_id):
    reviews = [r for r in db.all_of("ad_reviews") if r["content_item_id"] == item_id]
    if not reviews:
        return None
    return max(reviews, key=lambda r: (r["created_at"], r["id"]))


def reference_match_score(item, reference_file):
    """The rights-scan score for an item/reference pair.

    Any registered fingerprint that reaches the scan renders a score in the
    inclusive band [0.500, 1.000]; the score is derived deterministically from
    the fingerprint so that it is stable for the life of a reference file.
    """
    digest = hashlib.sha256(reference_file["reference_fingerprint"].encode("utf-8")).digest()
    fraction = int.from_bytes(digest[:4], "big") / float(0xFFFFFFFF)
    score = MATCH_THRESHOLD + (1.0 - MATCH_THRESHOLD) * fraction
    return round(score, 3)


def matching_references(item):
    if item.get("channel_id") is None:
        return []
    matches = []
    for reference in db.all_of("reference_files"):
        score = reference_match_score(item, reference)
        if score >= MATCH_THRESHOLD:
            matches.append((reference, score))
    return matches


def run_rights_scan(item, actor_notes=None):
    """Resolve an item out of CLASSIFYING (or CLASSIFIED) after a rights scan."""
    matches = matching_references(item)
    if matches:
        for reference, score in matches:
            create_auto_claim(item, reference, score)
        item["upload_status"] = "CLAIM_SCAN_COMPLETE"
    else:
        item["upload_status"] = "CLASSIFIED"
    return item


def create_auto_claim(item, reference, score):
    from services import claims as claim_svc

    return claim_svc.create_claim(
        content_item=item,
        reference_file=reference,
        match_confidence=score,
        source="REFERENCE_AUTO",
        claim_level="STANDARD",
    )


def revenue_routings_of(item_id):
    return [r for r in db.all_of("revenue_routings") if r["content_item_id"] == item_id]


def claims_of(item_id):
    return [c for c in db.all_of("claims") if c["content_item_id"] == item_id]


def recompute_item(item):
    """Recompute routed_revenue_cents, holds_revenue and takedown_flag.

    `holds_revenue` is true while the item's money is parked, which is either
    because a routing row sits in `ESCROW` or `RETROACTIVE_OWED`, or because a
    claim on the item still carries a `lock_reason` other than `NONE`.  PRD
    section 3.2 hop 4 and section 3.5 both state that the claim-revenue-lock
    cascade recomputes `holds_revenue` to true, including when a claim arrives
    before any revenue has been routed, and section 3.4 defines
    `revenue_locked` as true exactly while `lock_reason` is not `NONE`.
    """
    routings = revenue_routings_of(item["id"])
    item["routed_revenue_cents"] = sum(int(r["creator_share_cents"]) for r in routings)
    # PRD section 3.4 defines a claim's `revenue_locked` as true exactly while its
    # `lock_reason` is not `NONE`, and sections 3.2 and 3.5 both state that the
    # claim-revenue-lock cascade recomputes the item's `holds_revenue` to true --
    # so an item whose money is parked by a live claim lock is holding revenue
    # even before any routing row exists.  A released claim has answered the
    # question and no longer parks anything (section 3.5).
    parked_routing = any(
        r["status"] in ("ESCROW", "RETROACTIVE_OWED") for r in routings
    )
    live_claim_lock = any(
        c.get("lock_reason", "NONE") != "NONE" and c.get("status") != "RELEASED"
        for c in claims_of(item["id"])
    )
    item["holds_revenue"] = parked_routing or live_claim_lock
    item["takedown_flag"] = any(c["status"] == "TAKEN_DOWN" for c in claims_of(item["id"]))
    return item


def lock_item_revenue(item, reason_code):
    """The claim-revenue-lock cascade (PRD section 3.8).

    Every PAID_CREATOR routing of the item moves to RETROACTIVE_OWED with the
    creator share zeroed and the partner share raised to the full gross.
    """
    for routing in revenue_routings_of(item["id"]):
        if routing["status"] == "PAID_CREATOR":
            routing["status"] = "RETROACTIVE_OWED"
            routing["creator_share_cents"] = 0
            routing["partner_share_cents"] = int(routing["gross_revenue_cents"])
    recompute_item(item)
    return item


def release_item_revenue(item):
    """Restore RETROACTIVE_OWED routings to RELEASED_TO_CREATOR at the split rates."""
    for routing in revenue_routings_of(item["id"]):
        if routing["status"] == "RETROACTIVE_OWED":
            rate = STREAM_CREATOR_RATES[routing["stream_type"]]
            creator, partner = split_amount(routing["gross_revenue_cents"], rate)
            routing["creator_share_cents"] = creator
            routing["partner_share_cents"] = partner
            routing["status"] = "RELEASED_TO_CREATOR"
    recompute_item(item)
    return item


def mark_view_invisible(item):
    review = latest_ad_review(item["id"])
    if review is not None:
        review["is_visible"] = False


def take_down_item_claims(item):
    """The NO_ADS / takedown cascade shared by both entry points.

    hop 1: every claim of the item -> TAKEN_DOWN, one CopyrightStrike per claim
    hop 2: the channel's strike counters are remeasured
    hop 3: the channel thresholds are applied
    hop 4: the item is forced to NO_ADS with takedown_flag true
    """
    stamps = now()
    for claim in claims_of(item["id"]):
        if claim["status"] == "TAKEN_DOWN":
            continue
        claim["status"] = "TAKEN_DOWN"
        claim["taken_down_at"] = to_iso8601(stamps)
        touch(claim)
        channel_svc.issue_copyright_strike(item["channel_id"], item["id"], claim["id"])

    channel_svc.refresh_copyright_strike_count(item["channel_id"])
    channel_svc.apply_copyright_strike_thresholds(item["channel_id"])

    item["ad_suitability"] = "NO_ADS"
    item["takedown_flag"] = True
    mark_view_invisible(item)
    return item