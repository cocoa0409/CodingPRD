"""Configuration surface: seasons, suppression rules, logical clock, order feed."""

from flask import Blueprint

import validate as v
from db import db, new_row, now, rows
from errors import ApiError
from middleware import ALL_ROLES, NO_BROKER, PLATFORM_ADMIN, auth
from response import entity_response, list_response, object_response
from util import fmt_dt

bp = Blueprint("config", __name__)

SEASON_RATE_CARD = (
    # (field, default, minimum, maximum)
    ("print_cost_per_page_per_thousand_cents", 2600, 0, None),
    ("paper_cost_per_lb_cents", 92, 0, None),
    ("paper_oz_per_page_milli", 40, 1, None),
    ("usable_sq_in_per_page", 88, 1, None),
    ("default_postage_estimate_cents_per_piece", 55, 0, None),
    ("cogs_rate_bps", 5800, 0, 10000),
    ("prospect_base_response_bps", 110, 0, None),
    ("prospect_avg_order_value_cents", 11800, 0, None),
    ("min_inhome_gap_days", 21, 0, None),
    ("fatigue_window_days", 90, 1, None),
    ("fatigue_suppression_threshold", 100, 1, None),
)

CHANNEL_SCOPES = ("MAIL", "EMAIL", "DIGITAL", "ALL")


def find_season(season_id):
    season = db.seasons.get(season_id)
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    return season


@bp.post("/seasons")
def create_season():
    auth(PLATFORM_ADMIN)
    body = v.json_body()
    season_code = v.get_str(body, "season_code", min_len=1, max_len=32)
    fiscal_year = v.get_int(body, "fiscal_year", minimum=2020, maximum=2100)
    card = {}
    for field, default, minimum, maximum in SEASON_RATE_CARD:
        card[field] = v.get_int(
            body, field, required=False, default=default, minimum=minimum, maximum=maximum
        )
    for existing in db.seasons.values():
        if existing["season_code"] == season_code:
            raise ApiError("ERR_DUPLICATE_SEASON_CODE")
    row = new_row()
    row["season_code"] = season_code
    row["fiscal_year"] = fiscal_year
    row.update(card)
    db.seasons[row["id"]] = row
    return entity_response(row, 201)


@bp.get("/seasons/<season_id>")
def read_season(season_id):
    auth(*ALL_ROLES)
    return entity_response(find_season(season_id))


@bp.post("/seasons/<season_id>/suppression-rules")
def create_suppression_rule(season_id):
    auth(PLATFORM_ADMIN)
    season = find_season(season_id)
    body = v.json_body()
    rule_code = v.get_str(body, "rule_code", min_len=1)
    channel_scope = v.get_enum(body, "channel_scope", CHANNEL_SCOPES)
    window_days = v.get_int(body, "window_days", minimum=1, maximum=365)
    max_contacts = v.get_int(body, "max_contacts_per_window", minimum=0)
    priority = v.get_int(body, "priority", minimum=1)
    is_enabled = v.get_bool(body, "is_enabled", default=True)
    for existing in db.suppression_rules.values():
        if existing["season_id"] == season["id"] and existing["rule_code"] == rule_code:
            raise ApiError("ERR_DUPLICATE_SUPPRESSION_RULE_CODE")
    row = new_row()
    row.update(
        {
            "season_id": season["id"],
            "rule_code": rule_code,
            "channel_scope": channel_scope,
            "window_days": window_days,
            "max_contacts_per_window": max_contacts,
            "priority": priority,
            "is_enabled": is_enabled,
        }
    )
    db.suppression_rules[row["id"]] = row
    return entity_response(row, 201)


@bp.get("/seasons/<season_id>/suppression-rules")
def list_suppression_rules(season_id):
    auth(*NO_BROKER)
    season = find_season(season_id)
    limit, offset = v.pagination()
    scope = v.filter_enum("channel_scope", CHANNEL_SCOPES)
    enabled = v.filter_bool("is_enabled")
    matching = [
        r for r in db.suppression_rules.values() if r["season_id"] == season["id"]
    ]
    if scope is not None:
        matching = [r for r in matching if r["channel_scope"] == scope]
    if enabled is not None:
        matching = [r for r in matching if r["is_enabled"] == enabled]
    matching.sort(key=lambda r: (r["priority"], r["rule_code"], r["created_at"], r["_seq"]))
    page, total = v.paginate(matching, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(PLATFORM_ADMIN)
    body = v.json_body()
    current_utc = v.get_dt(body, "current_utc")
    db.clock = current_utc
    return object_response({"current_utc": fmt_dt(db.clock)})


@bp.post("/_online-orders/ingest")
def ingest_online_orders():
    auth(PLATFORM_ADMIN)
    body = v.json_body()
    orders = body.get("orders")
    if orders is None or not isinstance(orders, list):
        v.invalid("Field 'orders' must be an array.")

    # Ladder step 4: body foreign keys resolve before the schema pass.
    for element in orders:
        if not isinstance(element, dict):
            continue
        segment_id = element.get("housefile_segment_id")
        if isinstance(segment_id, str) and segment_id.strip() != "":
            if segment_id not in db.segments:
                raise ApiError("ERR_SEGMENT_NOT_FOUND")

    accepted = []
    for element in orders:
        if not isinstance(element, dict):
            v.invalid("Every element of 'orders' must be a JSON object.")
        external_order_id = v.get_str(element, "external_order_id", min_len=1)
        segment_id = v.get_id(element, "housefile_segment_id")
        order_date = v.get_dt(element, "order_date")
        demand_cents = v.get_int(element, "demand_cents", minimum=0)
        accepted.append(
            {
                "external_order_id": external_order_id,
                "housefile_segment_id": segment_id,
                "order_date": order_date,
                "demand_cents": demand_cents,
            }
        )

    for order in accepted:
        existing = db.online_orders.get(order["external_order_id"])
        if existing is None:
            row = new_row(with_version=False)
            row.update(order)
            db.online_orders[order["external_order_id"]] = row
        else:
            existing.update(order)
    return object_response(
        {
            "ingested_count": len(accepted),
            "external_order_ids": [o["external_order_id"] for o in accepted],
        }
    )
