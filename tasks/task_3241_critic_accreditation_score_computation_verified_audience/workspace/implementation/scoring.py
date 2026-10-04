"""Score computation: tomatometer, certification, audience score, snapshots.

All percentage math rounds half-up exactly once at the end via Decimal.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from db import db, _parse_iso
from helpers import new_entity, touch

POSITIVE_STAR_THRESHOLD = 4
MIN_REVIEWS_CERTIFIED = 5
MIN_TOP_CRITIC_REVIEWS = 2
CERTIFIED_FRESH_PCT = 75
CERTIFIED_ROTTEN_PCT = 60

DETECTION_WINDOW_HOURS = 24
VELOCITY_WEIGHT = 20
NEW_ACCOUNT_WEIGHT = 40
NEG_SKEW_WEIGHT = 30
NEGATIVE_STAR_MAX = 2
BOMBING_THRESHOLD_BPS = 6000

DISPUTE_PENALTY_BPS = 1500
PENDING_PENALTY_BPS = 500


def round_half_up_pct(numerator, denominator):
    """round_half_up(100 * numerator / denominator) as an int, exact rational."""
    val = (Decimal(100) * Decimal(numerator)) / Decimal(denominator)
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _append_snapshot(release, scope, variant, positive_count, total_count, pct):
    """Mark the previous same release+scope+variant snapshot superseded; append new."""
    for snap in db.score_snapshots.values():
        if (snap["release_id"] == release["id"] and snap["scope"] == scope
                and snap["variant"] == variant and not snap["superseded"]):
            snap["superseded"] = True
            touch(snap)
    snap = new_entity(db.score_snapshots, {
        "release_id": release["id"],
        "scope": scope,
        "variant": variant,
        "positive_count": positive_count,
        "total_count": total_count,
        "pct": pct,
        "superseded": False,
    })
    return snap


def _live_reviews(release_id):
    return [r for r in db.reviews.values()
            if r["release_id"] == release_id and r["status"] in ("PUBLISHED", "FLAGGED")]


def _certified_input_set(release_id):
    out = []
    for r in _live_reviews(release_id):
        critic = db.critics.get(r["critic_id"])
        if critic and critic["accreditation_status"] in ("ACCREDITED", "PROBATION"):
            out.append((r, critic))
    return out


def recompute_tomatometer(release):
    """Recompute both tomatometer variants, append snapshots, refresh release."""
    # PROVISIONAL: all PUBLISHED/FLAGGED reviews regardless of critic status.
    prov = _live_reviews(release["id"])
    prov_total = len(prov)
    prov_pos = sum(1 for r in prov if r["classification"] == "FRESH")
    prov_pct = round_half_up_pct(prov_pos, prov_total) if prov_total else None
    _append_snapshot(release, "TOMATOMETER", "PROVISIONAL", prov_pos, prov_total, prov_pct)

    # CERTIFIED: only reviews whose critic is ACCREDITED or PROBATION at compute time.
    cert_pairs = _certified_input_set(release["id"])
    cert_total = len(cert_pairs)
    cert_pos = sum(1 for r, _c in cert_pairs if r["classification"] == "FRESH")
    cert_pct = round_half_up_pct(cert_pos, cert_total) if cert_total else None
    _append_snapshot(release, "TOMATOMETER", "CERTIFIED", cert_pos, cert_total, cert_pct)

    # Certification evaluation (pinned order; gates stop early).
    if cert_total < MIN_REVIEWS_CERTIFIED:
        certification = "NONE"
    else:
        top_count = sum(1 for _r, c in cert_pairs if c.get("is_top_critic"))
        if top_count < MIN_TOP_CRITIC_REVIEWS:
            certification = "NONE"
        elif cert_pct >= CERTIFIED_FRESH_PCT:
            certification = "CERTIFIED_FRESH"
        elif cert_pct <= CERTIFIED_ROTTEN_PCT:
            certification = "CERTIFIED_ROTTEN"
        else:
            certification = "NONE"

    release["tomatometer_pct"] = cert_pct
    release["certification"] = certification
    touch(release)


def _audience_counts(release_id, statuses):
    ratings = [r for r in db.audience_ratings.values()
               if r["release_id"] == release_id and r["status"] in statuses]
    total = len(ratings)
    positive = sum(1 for r in ratings if r["stars"] >= POSITIVE_STAR_THRESHOLD)
    return positive, total


def recompute_audience_score(release):
    """Recompute verified-only (public) and all-ratings (diagnostic) variants."""
    pos_v, total_v = _audience_counts(release["id"], ("VERIFIED",))
    pct_v = round_half_up_pct(pos_v, total_v) if total_v else None
    _append_snapshot(release, "AUDIENCE_VERIFIED", "VERIFIED_ONLY", pos_v, total_v, pct_v)

    pos_a, total_a = _audience_counts(release["id"], ("VERIFIED", "UNVERIFIED"))
    pct_a = round_half_up_pct(pos_a, total_a) if total_a else None
    _append_snapshot(release, "AUDIENCE_VERIFIED", "ALL_RATINGS", pos_a, total_a, pct_a)

    release["audience_score_pct"] = pct_v
    touch(release)


def recompute_all_scores(release):
    """Full recompute: tomatometer + certification + audience score."""
    recompute_tomatometer(release)
    recompute_audience_score(release)


def compute_bombing_index(release_id):
    """Detection index in basis points over the trailing 24h half-open window."""
    now = db.logical_clock
    window_start = now - timedelta(hours=DETECTION_WINDOW_HOURS)
    in_window = []
    for r in db.audience_ratings.values():
        if r["release_id"] != release_id:
            continue
        created = _parse_iso(r["created_at"])
        # Entities are stamped at the logical clock, so `created` can equal
        # `now`; that activity belongs to the trailing window (closed at the
        # present instant, half-open only on the past side).
        if window_start <= created <= now:
            in_window.append(r)
    v = len(in_window)
    denom = v if v > 0 else 1
    n = 0
    s = 0
    for r in in_window:
        member = db.audience_members.get(r["audience_member_id"])
        if member is not None:
            acc_created = _parse_iso(member["account_created_at"])
            if window_start <= acc_created <= now:
                n += 1
        if r["stars"] <= NEGATIVE_STAR_MAX:
            s += 1
    new_account_pct = round_half_up_pct(n, denom)
    neg_skew_pct = round_half_up_pct(s, denom)
    index = VELOCITY_WEIGHT * v + NEW_ACCOUNT_WEIGHT * new_account_pct + NEG_SKEW_WEIGHT * neg_skew_pct
    return min(10000, index)


def critic_standing_final(critic_id, period_start, period_end):
    """Final standing variant over the half-open review window."""
    start = _parse_iso(period_start)
    end = _parse_iso(period_end)
    upheld = 0
    for dispute in db.disputes.values():
        if dispute.get("dispute_kind") != "CLASSIFICATION":
            continue
        if dispute.get("status") != "UPHELD":
            continue
        review = db.reviews.get(dispute.get("subject_review_id") or "")
        if review is None or review["critic_id"] != critic_id:
            continue
        pub = review.get("published_at")
        if not pub:
            continue
        pub_dt = _parse_iso(pub)
        if start <= pub_dt < end:
            upheld += 1
    base = 10000 - DISPUTE_PENALTY_BPS * upheld
    return max(0, min(10000, base))


def critic_standing_provisional(critic_id):
    """Provisional preview over trailing 365 days ending at the logical clock."""
    end = db.logical_clock
    start = end - timedelta(days=365)
    flagged = 0
    for dispute in db.disputes.values():
        if dispute.get("dispute_kind") != "CLASSIFICATION":
            continue
        if dispute.get("status") in ("UPHELD", "REJECTED"):
            continue
        review = db.reviews.get(dispute.get("subject_review_id") or "")
        if review is None or review["critic_id"] != critic_id:
            continue
        if review["status"] != "FLAGGED":
            continue
        pub = review.get("published_at")
        if not pub:
            continue
        pub_dt = _parse_iso(pub)
        if start <= pub_dt < end:
            flagged += 1
    base = 10000 - PENDING_PENALTY_BPS * flagged
    return max(0, min(10000, base))
