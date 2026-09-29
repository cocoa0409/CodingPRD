"""Multi-register cascades (PRD section 2.11): every mutated row is versioned."""

from decimal import Decimal

import lookups
from db import add_days, base_row, dec, fmt_ts, now, now_iso, q2, store, touch

REPLACEMENT_WINDOW_DAYS = 60

LIVE_AGREEMENT_STATUSES = ("ACTIVE", "HOLD_IN", "SUSPENDED")


def new_solicitation(community_id, closes_at_iso, created_reason):
    row = base_row(True)
    row.update({
        "community_id": community_id,
        "closes_at": closes_at_iso,
        "round_number": 1,
        "created_reason": created_reason,
        "status": "OPEN",
        "preference_filing_count": 0,
        "selected_proposal_id": None,
        "candidate_count_at_award": None,
    })
    store.solicitations[row["id"]] = row
    return row


def open_replacement_solicitation(community_id):
    """A replacement round closing 60 days after the current logical clock."""
    closes_at = fmt_ts(add_days(now(), REPLACEMENT_WINDOW_DAYS))
    return new_solicitation(community_id, closes_at, "REPLACEMENT")


def decrement_active_agreements(community):
    count = community.get("active_agreement_count") or 0
    community["active_agreement_count"] = count - 1 if count > 0 else 0


def increment_active_agreements(community):
    community["active_agreement_count"] = (community.get("active_agreement_count") or 0) + 1


def has_live_agreement(community_id, ignore_id=None):
    for row in lookups.agreements_of_community(community_id):
        if ignore_id is not None and row["id"] == ignore_id:
            continue
        if row["status"] in LIVE_AGREEMENT_STATUSES:
            return True
    return False


def settle_community_after_release(community):
    """Once nothing live is left, the community follows its latest determination."""
    if has_live_agreement(community["id"]):
        return
    if community["status"] != "SUBSIDIZED":
        return
    outcome = community.get("latest_determination_outcome")
    if outcome in ("ELIGIBLE", "ELIGIBLE_WITH_WAIVER"):
        community["status"] = "ELIGIBLE"
    elif outcome in ("INELIGIBLE_DISTANCE", "INELIGIBLE_ENPLANEMENTS"):
        community["status"] = "TERMINATED"


def release_obligation(agreement):
    """Terminating releases the unspent obligation and keeps the identity true."""
    agreement["total_committed_usd"] = q2(agreement["disbursed_to_date_usd"])
    agreement["obligated_remaining_usd"] = Decimal("0.00")


def terminate_agreement(agreement):
    agreement["status"] = "TERMINATED"
    agreement["terminated_at"] = now_iso()
    release_obligation(agreement)
    touch(agreement)


def hold_in_petition(agreement_id):
    rows = [p for p in store.petitions.values()
            if p["agreement_id"] == agreement_id
            and p["status"] == "GRANTED_WITH_HOLD_IN"]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows[0] if rows else None


def release_hold_in_predecessor(predecessor, community):
    """The statutory hold-in release, run as a cascade of the replacement award."""
    terminate_agreement(predecessor)
    petition = hold_in_petition(predecessor["id"])
    if petition is not None:
        petition["status"] = "CLOSED"
        touch(petition)


def refresh_carrier_headline(carrier):
    """Headline figures follow the newest review across all of the carrier's agreements."""
    agreement_ids = set(a["id"] for a in lookups.agreements_of_carrier(carrier["id"]))
    reviews = [r for r in store.reviews.values() if r["agreement_id"] in agreement_ids]
    reviews.sort(key=lambda r: (r["created_at"], r["_seq"]))
    if not reviews:
        carrier["latest_completion_factor"] = None
        carrier["latest_quality_score"] = None
        carrier["latest_performance_tier"] = None
        carrier["consecutive_watch_count"] = 0
        return 0
    newest = reviews[-1]
    carrier["latest_completion_factor"] = newest["completion_factor"]
    carrier["latest_quality_score"] = newest["quality_score"]
    carrier["latest_performance_tier"] = newest["tier"]
    streak = 0
    for row in reversed(reviews):
        if row["tier"] == "WATCH":
            streak += 1
        else:
            break
    carrier["consecutive_watch_count"] = streak
    return streak


def recompute_obligation(agreement):
    agreement["obligated_remaining_usd"] = q2(
        dec(agreement["total_committed_usd"]) - dec(agreement["disbursed_to_date_usd"]))
