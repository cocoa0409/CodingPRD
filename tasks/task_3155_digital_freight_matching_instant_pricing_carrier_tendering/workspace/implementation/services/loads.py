"""Load lifecycle: create, post, reprice, repost, cancel, void (PRD 3.2-3.7, 3.10)."""

from constants import (
    COMMODITIES, COMMODITY_LIABILITY_CAP, EQUIPMENT_TYPES, MARKET_BANDS,
    MIN_RATE_FLOOR_CENTS, PRICING_MODES, QUOTE_TTL_HOURS, d, plus_hours,
    round_half_up, round4, utc,
)
from db import clock_now, db, mint_id, touch
from errors import ApiError
from services.common import (
    append_status_event, get_carrier, get_contract, get_equipment, get_facility,
    get_load, get_shipper, load_effective_rate, refresh_contract, refresh_load_derived,
    refresh_quote, refresh_shipper,
)
from services import pricing
from services.settlements import reverse_settlement


def create_load(body):
    shipper = get_shipper(body.get("shipper_id"))
    origin = get_facility(body.get("origin_facility_id"))
    destination = get_facility(body.get("destination_facility_id"))
    contract_id = body.get("lane_contract_id")
    contract = None
    if contract_id is not None:
        contract = get_contract(contract_id)

    pricing_mode = body.get("pricing_mode")
    if pricing_mode not in PRICING_MODES:
        raise ApiError("ERR_INVALID_REQUEST", "pricing_mode must be SPOT or CONTRACT.")
    equipment_type = body.get("equipment_type")
    if equipment_type not in EQUIPMENT_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown equipment_type.")
    commodity = body.get("commodity")
    if commodity not in COMMODITIES:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown commodity.")
    market_band = body.get("market_band", "BALANCED")
    if market_band not in MARKET_BANDS:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown market_band.")

    weight_lbs = body.get("weight_lbs")
    if not isinstance(weight_lbs, int) or isinstance(weight_lbs, bool) or weight_lbs < 1:
        raise ApiError("ERR_INVALID_REQUEST", "weight_lbs must be at least 1.")
    declared_value = body.get("declared_cargo_value_cents")
    if not isinstance(declared_value, int) or isinstance(declared_value, bool) or declared_value < 0:
        raise ApiError("ERR_INVALID_REQUEST", "declared_cargo_value_cents must be a non-negative integer.")
    distance_miles = body.get("distance_miles")
    if isinstance(distance_miles, bool) or not isinstance(distance_miles, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "distance_miles must be a number.")

    window_start = _instant(body, "pickup_window_start")
    window_end = _instant(body, "pickup_window_end")
    deadline = _instant(body, "delivery_deadline")
    if not window_end > window_start:
        raise ApiError("ERR_WINDOW_ORDER")

    now = clock_now()
    load = {
        "id": mint_id(),
        "shipper_id": shipper["id"],
        "origin_facility_id": origin["id"],
        "destination_facility_id": destination["id"],
        "lane_contract_id": contract["id"] if contract else None,
        "lane_key": "%s>%s" % (origin["state_code"], destination["state_code"]),
        "pricing_mode": pricing_mode,
        "market_band": market_band,
        "equipment_type": equipment_type,
        "commodity": commodity,
        "weight_lbs": weight_lbs,
        "declared_cargo_value_cents": declared_value,
        "distance_miles": float(distance_miles),
        "pickup_window_start": window_start,
        "pickup_window_end": window_end,
        "delivery_deadline": deadline,
        "posted_rate_cents": None,
        "booked_rate_cents": None,
        "reprice_count": 0,
        "repost_count": 0,
        "carrier_id": None,
        "equipment_id": None,
        "accessorial_total_cents": 0,
        "actual_pickup_at": None,
        "pickup_breach_flag": False,
        "tracking_status_rank": 0,
        "shipper_version": shipper["version"],
        "projected_delay_minutes": 0,
        "actual_delivery_at": None,
        "delivered_at": None,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.loads[load["id"]] = load
    return load


def _instant(body, field):
    from constants import parse_instant
    if field not in body or body[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
    return parse_instant(body[field], field)


def synthesize_quote(load, contract):
    now = clock_now()
    base_rate, level = pricing.quote_price(load, contract)
    quote = {
        "id": mint_id(),
        "load_id": load["id"],
        "quote_kind": "INITIAL",
        "base_rate_cents": base_rate,
        "repriced_rate_cents": None,
        "effective_miles": pricing.effective_miles(load["distance_miles"]),
        "quoted_cents_per_mile": 0.0,
        "market_level_cents_per_mile": level,
        "acceptance_deadline": plus_hours(now, QUOTE_TTL_HOURS),
        "viewed_carrier_ids": [],
        "declined_carrier_ids": [],
        "min_rate_cents": pricing.min_rate_for(base_rate),
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    refresh_quote(quote)
    db.quotes[quote["id"]] = quote
    return quote


def expire_quotes(load_id):
    """Delegates to the shared reconciliation helper."""
    from services.common import expire_quotes_for
    return expire_quotes_for(load_id)


def live_quotes_for(load_id):
    """Delegates to the shared helper so every caller shares one definition."""
    from services.common import live_quotes_for as _live
    return _live(load_id)


def post_load(load_id):
    load = get_load(load_id)
    shipper = get_shipper(load["shipper_id"])
    refresh_shipper(shipper)
    if load["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if shipper["load_credits_available"] < 1:
        raise ApiError("ERR_LOAD_CREDIT_EXHAUSTED")
    contract = None
    if load["pricing_mode"] == "CONTRACT":
        contract = _active_contract(load)

    quote = synthesize_quote(load, contract)
    load["posted_rate_cents"] = quote["base_rate_cents"]
    load["booked_rate_cents"] = quote["base_rate_cents"]
    load["status"] = "POSTED"
    shipper["load_credits_committed"] += 1
    touch(shipper)
    refresh_shipper(shipper)
    touch(load)
    refresh_load_derived(load)
    append_status_event(load["id"], "POSTED", "PLATFORM")
    return load


def _active_contract(load):
    contract_id = load.get("lane_contract_id")
    if contract_id is None:
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    contract = get_contract(contract_id)
    refresh_contract(contract)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    now = clock_now()
    if not (utc(contract["start_date"]) <= now < utc(contract["end_date"])):
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    return contract


def reprice_load(load_id, body):
    """PRD 3.7 — posted_rate_cents is never touched by a reprice."""
    load = get_load(load_id)
    new_band = body.get("new_market_band")
    if new_band not in MARKET_BANDS:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown market_band.")
    if load["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE")
    quote = newest_quote(load["id"])
    if quote is None:
        raise ApiError("ERR_QUOTE_NOT_FOUND")
    amount = pricing.reprice_rate(load, quote, new_band)
    quote["repriced_rate_cents"] = amount
    quote["quote_kind"] = "REPRICED"
    touch(quote)
    load["booked_rate_cents"] = amount
    load["market_band"] = new_band
    load["reprice_count"] += 1
    shipper = db.shippers.get(load["shipper_id"])
    if shipper is not None:
        shipper["last_repriced_lane"] = load["lane_key"]
        touch(shipper)
    touch(load)
    refresh_load_derived(load)
    return load


def newest_quote(load_id):
    rows = [quote for quote in db.quotes.values() if quote["load_id"] == load_id]
    if not rows:
        return None
    rows.sort(key=lambda row: (row["created_at"], row["version"]))
    return rows[-1]


def repost_load(load_id, body):
    """PRD 3.4 — the thorough reset, guarded by repost history then staleness."""
    load = get_load(load_id)
    shipper = get_shipper(load["shipper_id"])
    if load["status"] != "UNCOVERED":
        raise ApiError("ERR_INVALID_STATE")
    if load["repost_count"] >= 3:
        raise ApiError("ERR_REPOST_LIMIT_REACHED")
    expected = body.get("expected_shipper_version")
    if expected is not None and int(expected) != int(shipper["version"]):
        raise ApiError("ERR_STALE_VERSION")

    contract = None
    if load["pricing_mode"] == "CONTRACT":
        contract = _active_contract(load)
    fresh = synthesize_quote(load, contract)
    for quote in db.quotes.values():
        if quote["load_id"] != load["id"] or quote["id"] == fresh["id"]:
            continue
        if quote["status"] in ("ACTIVE", "VIEWED", "DECLINED", "EXPIRED", "SUPERSEDED"):
            quote["status"] = "SUPERSEDED"
            touch(quote)

    load["repost_count"] += 1
    load["posted_rate_cents"] = fresh["base_rate_cents"]
    load["booked_rate_cents"] = fresh["base_rate_cents"]
    load["status"] = "POSTED"
    touch(shipper)
    refresh_shipper(shipper)
    touch(load)
    refresh_load_derived(load)
    append_status_event(load["id"], "POSTED", "PLATFORM")
    return load


def cancel_load(load_id):
    load = get_load(load_id)
    shipper = get_shipper(load["shipper_id"])
    status = load["status"]
    if status in ("CANCELLED", "VOIDED", "PAID"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status in ("IN_TRANSIT", "DELIVERED", "INVOICED"):
        raise ApiError("ERR_INVALID_STATE")
    if status == "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    return _apply_cancellation(load, shipper, status)


def _apply_cancellation(load, shipper, status):
    held = active_booking_for_load(load["id"])
    if status == "BOOKED":
        pings = [p for p in db.tracking_pings.values() if p["load_id"] == load["id"]]
        if pings:
            raise ApiError("ERR_INVALID_STATE")
        if held is not None:
            held["status"] = "CANCELLED"
            touch(held)
            equipment = db.equipment.get(held["equipment_id"])
            if equipment is not None:
                equipment["status"] = "AVAILABLE"
                touch(equipment)
            appointment = db.appointments.get(held.get("appointment_id"))
            if appointment is not None and appointment["status"] == "SCHEDULED":
                appointment["status"] = "CANCELLED"
                touch(appointment)
                facility = db.facilities.get(appointment["facility_id"])
                if facility is not None:
                    from services.docks import release_dock
                    release_dock(facility)
    # PRD 2.8 — the booked-rate reservation is released when the load is
    # cancelled before it moves, whether the cancel arrives while the load is
    # BOOKED or after it has been returned to the board as UNCOVERED.
    if held is not None:
        shipper["credit_used_cents"] -= held["agreed_rate_cents"]
    if status in ("POSTED", "UNCOVERED", "BOOKED"):
        shipper["load_credits_committed"] -= 1
    for quote in db.quotes.values():
        if quote["load_id"] == load["id"] and quote["status"] in ("ACTIVE", "VIEWED"):
            quote["status"] = "SUPERSEDED"
            touch(quote)
    load["status"] = "CANCELLED"
    touch(shipper)
    refresh_shipper(shipper)
    touch(load)
    refresh_load_derived(load)
    return load


def active_booking_for_load(load_id):
    rows = [booking for booking in db.bookings.values()
            if booking["load_id"] == load_id
            and booking["status"] in ("PENDING_APPOINTMENT", "IN_TRANSIT")]
    if not rows:
        return None
    rows.sort(key=lambda row: row["created_at"])
    return rows[-1]


def void_load(load_id, body):
    """PRD 3.10 — the heaviest correction, idempotent on retry_idempotency_key."""
    load = get_load(load_id)
    key = body.get("retry_idempotency_key")
    if not key:
        raise ApiError("ERR_INVALID_REQUEST", "retry_idempotency_key is required.")
    stored = db.void_keys.get(load["id"])
    if stored is not None and stored["key"] == key:
        return load
    if load["status"] not in ("DELIVERED", "INVOICED", "PAID"):
        if load["status"] in ("CANCELLED", "VOIDED"):
            raise ApiError("ERR_ALREADY_TERMINAL")
        raise ApiError("ERR_INVALID_STATE")
    for settlement in list(db.settlements.values()):
        if settlement["load_id"] != load["id"]:
            continue
        if settlement["reversal_of_settlement_id"] is not None:
            continue
        if settlement["settlement_status"] in ("ACCRUED", "READY", "PAID"):
            reverse_settlement(settlement)
            break
    shipper = db.shippers.get(load["shipper_id"])
    if shipper is not None:
        shipper["load_credits_committed"] -= 1
        touch(shipper)
        refresh_shipper(shipper)
    load["status"] = "VOIDED"
    touch(load)
    refresh_load_derived(load)
    db.void_keys[load["id"]] = {"key": key, "outcome": load["id"]}
    return load


def refresh_all_settlements():
    from services.settlements import refresh_live_settlement_for_load
    for settlement in list(db.settlements.values()):
        if settlement["settlement_status"] in ("ACCRUED", "READY"):
            refresh_live_settlement_for_load(settlement["load_id"])


def load_list(loads, filters):
    rows = list(loads)
    for field in ("shipper_id", "carrier_id", "origin_facility_id",
                  "destination_facility_id", "lane_contract_id", "equipment_id",
                  "status", "equipment_type", "lane_key"):
        value = filters.get(field)
        if value is None or value == "":
            continue
        rows = [row for row in rows if row.get(field) == value]
    rows.sort(key=lambda row: row["created_at"])
    return rows