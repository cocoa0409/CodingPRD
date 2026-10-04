"""Topic-routing and briefing-routing selectors (PRD 3.2, 3.8)."""

from db import db
from services.state import open_briefing_count, open_inquiry_count

SENIORITY_RANK = {
    "DISTINGUISHED": 4,
    "VP": 3,
    "SENIOR": 2,
    "ASSOCIATE": 1,
}


def topic_route_candidates(topic_route, excluded_ids):
    """Eligible analysts for an inquiry, best candidate first.

    Eligibility: status ACTIVE, the topic route is listed, the analyst has not
    already declined, and the integrity flag is not CONFLICT_BLOCKED.
    Ranking: seniority DESC, open_inquiry_count ASC, created_at ASC.
    """
    excluded = set(excluded_ids or [])
    eligible = [
        a
        for a in db.analysts.values()
        if a.get("status") == "ACTIVE"
        and topic_route in (a.get("topic_routes") or [])
        and a.get("id") not in excluded
        and a.get("integrity_flag") != "CONFLICT_BLOCKED"
    ]
    eligible.sort(
        key=lambda a: (
            -SENIORITY_RANK.get(a.get("seniority"), 0),
            open_inquiry_count(a["id"]),
            a.get("created_at") or "",
        )
    )
    return eligible


def topic_route_winner(topic_route, excluded_ids):
    candidates = topic_route_candidates(topic_route, excluded_ids)
    return candidates[0] if candidates else None


def briefing_candidates(briefing_topic):
    """Eligibility: status ACTIVE, topic listed, integrity flag CLEAR.

    Ranking: open briefing count ASC, then created_at ASC.
    """
    eligible = [
        a
        for a in db.analysts.values()
        if a.get("status") == "ACTIVE"
        and briefing_topic in (a.get("topic_routes") or [])
        and a.get("integrity_flag") == "CLEAR"
    ]
    eligible.sort(
        key=lambda a: (open_briefing_count(a["id"]), a.get("created_at") or "")
    )
    return eligible


def briefing_winner(briefing_topic):
    candidates = briefing_candidates(briefing_topic)
    return candidates[0] if candidates else None
