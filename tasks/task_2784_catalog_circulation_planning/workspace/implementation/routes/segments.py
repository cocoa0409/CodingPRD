"""Housefile segmentation hierarchy."""

from flask import Blueprint

import validate as v
from db import db, new_row, touch
from errors import ApiError
from middleware import ALL_ROLES, CIRCULATION_PLANNER, NO_BROKER, auth
from response import entity_response, list_response
from services import calc, domain

bp = Blueprint("segments", __name__)

CONTACT_STRATEGIES = ("PREMIUM_FULL", "STANDARD", "REACTIVATION", "SUPPRESS_ONLY")
SEGMENT_TIERS = ("BEST", "CORE", "OCCASIONAL", "LAPSED", "DORMANT")
CHANNELS = ("MAIL", "EMAIL", "DIGITAL")

SCORING_FIELDS = (
    ("recency_days", 0, None),
    ("orders_12mo", 0, None),
    ("ltv_cents", 0, None),
    ("housefile_count", 0, None),
    ("avg_order_value_cents", 0, None),
    ("historical_response_rate_bps", 0, 10000),
)


def find_segment(segment_id):
    segment = db.segments.get(segment_id)
    if segment is None:
        raise ApiError("ERR_SEGMENT_NOT_FOUND")
    return segment


def _assert_parent_link(season_id, child_id, parent_id):
    """Same season, no self-parenting, no cycle."""
    parent = db.segments.get(parent_id)
    if parent is None or parent["season_id"] != season_id:
        raise ApiError("ERR_SEGMENT_CYCLE")
    if child_id is not None and parent_id == child_id:
        raise ApiError("ERR_SEGMENT_CYCLE")
    cursor = parent
    seen = set()
    while cursor is not None:
        if cursor["id"] in seen:
            raise ApiError("ERR_SEGMENT_CYCLE")
        seen.add(cursor["id"])
        if child_id is not None and cursor["id"] == child_id:
            raise ApiError("ERR_SEGMENT_CYCLE")
        next_id = cursor["parent_segment_id"]
        cursor = db.segments.get(next_id) if next_id else None


@bp.post("/housefile-segments")
def create_segment():
    auth(CIRCULATION_PLANNER)
    body = v.json_body()

    # Ladder step 4 — body foreign keys.
    season_id = body.get("season_id")
    if isinstance(season_id, str) and season_id.strip() != "":
        if season_id not in db.seasons:
            raise ApiError("ERR_SEASON_NOT_FOUND")
    parent_id = body.get("parent_segment_id")
    if isinstance(parent_id, str) and parent_id.strip() != "":
        if parent_id not in db.segments:
            raise ApiError("ERR_SEGMENT_NOT_FOUND")

    # Ladder step 5 — schema.
    season_id = v.get_id(body, "season_id")
    if season_id not in db.seasons:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    season = db.seasons[season_id]
    segment_code = v.get_str(body, "segment_code", min_len=1)
    parent_id = v.get_id(body, "parent_segment_id", required=False)
    values = {}
    for field, minimum, maximum in SCORING_FIELDS:
        values[field] = v.get_int(body, field, minimum=minimum, maximum=maximum)
    strategy = v.get_enum(body, "contact_strategy", CONTACT_STRATEGIES, required=False)

    # Ladder step 7 — hierarchy acyclic and same-season.
    if parent_id is not None:
        _assert_parent_link(season_id, None, parent_id)

    # Ladder step 19 — code uniqueness.
    for existing in db.segments.values():
        if existing["season_id"] == season_id and existing["segment_code"] == segment_code:
            raise ApiError("ERR_DUPLICATE_SEGMENT_CODE")

    row = new_row()
    row.update(
        {
            "season_id": season_id,
            "parent_segment_id": parent_id,
            "segment_code": segment_code,
            "rfm_score": 0,
            "segment_tier": None,
            "contact_strategy": None,
            "rollup_housefile_count": 0,
            "is_leaf": True,
            "fatigue_score": 0,
            "suppressed_at": None,
        }
    )
    row.update(values)
    domain.score_segment(row)
    if strategy is not None:
        row["contact_strategy"] = strategy
    else:
        row["contact_strategy"] = calc.TIER_STRATEGY_DEFAULT[row["segment_tier"]]
    db.segments[row["id"]] = row
    domain.refresh_segment_tree(skip_touch_ids=(row["id"],))
    return entity_response(row, 201)


@bp.patch("/housefile-segments/<segment_id>")
def amend_segment(segment_id):
    auth(CIRCULATION_PLANNER)
    segment = find_segment(segment_id)
    body = v.json_body()

    if "parent_segment_id" in body and body["parent_segment_id"] is not None:
        candidate = body["parent_segment_id"]
        if isinstance(candidate, str) and candidate.strip() != "":
            if candidate not in db.segments:
                raise ApiError("ERR_SEGMENT_NOT_FOUND")

    updates = {}
    for field, minimum, maximum in SCORING_FIELDS:
        if field in body:
            updates[field] = v.get_int(
                body, field, minimum=minimum, maximum=maximum
            )
    strategy = None
    if "contact_strategy" in body:
        strategy = v.get_enum(body, "contact_strategy", CONTACT_STRATEGIES)
    reparent = "parent_segment_id" in body
    new_parent = None
    if reparent:
        new_parent = v.get_id(body, "parent_segment_id", required=False)

    if reparent and new_parent is not None:
        _assert_parent_link(segment["season_id"], segment["id"], new_parent)

    segment.update(updates)
    if reparent:
        segment["parent_segment_id"] = new_parent
    domain.score_segment(segment)
    if strategy is not None:
        # An explicit contact_strategy overrides the tier default, and it is the
        # only way to lift a suppression the fatigue cascade imposed.
        segment["contact_strategy"] = strategy
    elif segment["contact_strategy"] != "SUPPRESS_ONLY":
        # The re-scored tier supplies its default again; a SUPPRESS_ONLY segment
        # is never reverted by a recency-frequency-monetary re-score.
        segment["contact_strategy"] = calc.TIER_STRATEGY_DEFAULT[segment["segment_tier"]]
    touch(segment)
    domain.refresh_segment_tree(skip_touch_ids=(segment["id"],))
    return entity_response(segment)


@bp.get("/housefile-segments/<segment_id>")
def read_segment(segment_id):
    auth(*ALL_ROLES)
    return entity_response(find_segment(segment_id))


@bp.get("/housefile-segments")
def list_segments():
    auth(*ALL_ROLES)
    limit, offset = v.pagination()
    season_id = v.filter_str("season_id")
    parent_id = v.filter_str("parent_segment_id")
    tier = v.filter_enum("segment_tier", SEGMENT_TIERS)
    strategy = v.filter_enum("contact_strategy", CONTACT_STRATEGIES)
    is_leaf = v.filter_bool("is_leaf")
    matching = list(db.segments.values())
    if season_id is not None:
        matching = [s for s in matching if s["season_id"] == season_id]
    if parent_id is not None:
        matching = [s for s in matching if s["parent_segment_id"] == parent_id]
    if tier is not None:
        matching = [s for s in matching if s["segment_tier"] == tier]
    if strategy is not None:
        matching = [s for s in matching if s["contact_strategy"] == strategy]
    if is_leaf is not None:
        matching = [s for s in matching if s["is_leaf"] == is_leaf]
    matching.sort(key=lambda s: (s["segment_code"], s["created_at"], s["_seq"]))
    page, total = v.paginate(matching, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/housefile-segments/<segment_id>/contact-events")
def list_segment_contact_events(segment_id):
    auth(*NO_BROKER)
    segment = find_segment(segment_id)
    limit, offset = v.pagination()
    channel = v.filter_enum("channel", CHANNELS)
    matching = [
        e
        for e in db.contact_events.values()
        if e["housefile_segment_id"] == segment["id"]
    ]
    if channel is not None:
        matching = [e for e in matching if e["channel"] == channel]
    matching.sort(key=lambda e: (e["contact_date"], e["created_at"], e["_seq"]))
    page, total = v.paginate(matching, limit, offset)
    return list_response(page, limit, offset, total)
