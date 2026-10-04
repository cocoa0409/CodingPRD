"""Shared helpers: parsing, validation, serialization, money math, sweeps."""
import math
import uuid
from datetime import datetime, date, timezone, time

import errors as err
from errors import ApiError
from db import db, now, today_date

# ---------------------------------------------------------------- constants
FREIGHT_SURCHARGE_CENTS_PER_LOT = 150000
WEIGHT_MARGIN = 0.6
WEIGHT_SELL_THROUGH = 0.4
DISCRETION_PENALTY = {"CONFIDENTIAL": 15, "QUIET": 25, "STANDARD": 0}
LOT_TYPE_BONUS = {"CLOSEOUT": 10, "CANCELLATION": 5, "PACKAWAY": 0}
MARKDOWN_STEP_RATE = 0.20
CLEARANCE_FLOOR_MULTIPLIER = 0.30
CASCADE_RECOVERY_RATE_PCT = 0.25
AGING_REVIEW_DAYS = 90
STALE_DAYS = 270
DAYS_PER_BILLING_MONTH = 30
ZONE_BOOK_ZONES = {"NE", "WC"}

MISSING = object()

SEASON_STATUSES = ("DRAFT", "OPEN", "CLOSED")
LOT_TYPES = ("CLOSEOUT", "CANCELLATION", "PACKAWAY")
DISPOSITIONS = ("IMMEDIATE", "PACKAWAY")
LOT_STATUSES = ("OFFERED", "EVALUATED", "ACCEPTED", "PASSED", "CANCELLED")
CANCEL_REASONS = ("VENDOR_PULL", "BUYER_WITHDRAW", "OFFER_EXPIRED")
DISCRETION_LEVELS = ("STANDARD", "CONFIDENTIAL", "QUIET")
VENDOR_TIERS = ("A", "B", "C")
ZONE_CODES = ("NE", "MW", "SE", "TX", "MT", "WC")
DEPARTMENTS = ("APPAREL", "HOME", "BEAUTY", "ACCESSORIES")
CLUSTERS = ("URBAN_PREMIUM", "SUBURBAN_FAMILY", "VALUE_RURAL")
PLAN_STATUSES = ("DRAFT", "APPROVED", "EXECUTED", "SUPERSEDED", "CANCELLED")
SKU_STATUSES = ("ON_FLOOR", "MARKED_DOWN", "CLEARANCE", "SOLD_OUT", "LIQUIDATED")
TICKET_STATUSES = ("ACTIVE", "VOIDED")
RECEIPT_STATUSES = ("OPEN", "RECEIVED")
SHRINK_TYPES = ("UNSCANNED_UNIT", "MIXED_LOT_OVERAGE", "MIXED_LOT_SHORTAGE", "DAMAGE")
MERGE_MODES = ("FIFO", "HIGH_VALUE_SORT")
SHRINK_STATUSES = ("OPEN", "CONFIRMED", "VOIDED")
LIQ_REASONS = ("CLEARANCE_WEEKS_EXCEEDED", "PACKAWAY_STALE")
LIQ_STATUSES = ("DRAFT", "APPROVED", "EXECUTED", "CANCELLED")
HOLD_STATUSES = ("STORED", "AGING_REVIEW", "RELEASED", "LIQUIDATED")
AGE_BUCKETS = ("FRESH", "AGING", "STALE")
TRIGGER_REASONS = ("AGING_THRESHOLD", "DECISION_KEEP", "DECISION_RELEASE", "DECISION_LIQUIDATE")

LIVE_SKU_STATUSES = ("ON_FLOOR", "MARKED_DOWN", "CLEARANCE")


# ---------------------------------------------------------------- ids / time
def new_id():
    return str(uuid.uuid4())


def iso_z(dt):
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, time.min, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
    return s + f"{dt.microsecond // 1000:03d}Z"


def wall_now_iso():
    return iso_z(datetime.now(timezone.utc))


def parse_datetime(value, field):
    """Parse a full ISO 8601 datetime; a bare date is UTC midnight."""
    if not isinstance(value, str):
        raise err.invalid_request(f"{field} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err.invalid_request(f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    """Date-only input -> UTC midnight datetime."""
    return parse_datetime(value, field)


# ---------------------------------------------------------------- numbers
def round_half_up(value):
    """Round a numeric value to an integer, half-up. Accepts int/float/Decimal."""
    return math.floor(float(value) + 0.5)


def round_half_up_2dp(value):
    """Round to 2 decimal places, half-up; returns float."""
    return math.floor(float(value) * 100 + 0.5) / 100.0


def adjust_to_nine_ending(cents):
    """Adjust an integer-cent price down to the nearest price ending in 9."""
    cents = int(cents)
    if cents % 10 == 9:
        return cents
    down = cents - ((cents % 10) + 1)
    if down < 0:
        return 0
    return down


def price_point(value):
    """Round half-up to integer cents, then adjust down to the nearest price
    strictly below that ends in 9."""
    return adjust_to_nine_ending(round_half_up(value))


# ---------------------------------------------------------------- body validation
def get_body(required=False):
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise err.invalid_request("a JSON request body is required")
        return {}
    if not isinstance(data, dict):
        raise err.invalid_request("request body must be a JSON object")
    return data


def validate_body(body, spec):
    """spec: dict field -> (kind, required, extra) where kind in
    str/int/float/bool/datetime/enum/object; extra is the enum tuple for enum.
    Returns dict of parsed values."""
    unknown = set(body) - set(spec)
    if unknown:
        raise err.invalid_request(f"unknown field(s): {sorted(unknown)}")
    out = {}
    for name, rule in spec.items():
        kind, required = rule[0], rule[1]
        extra = rule[2] if len(rule) > 2 else None
        value = body.get(name, MISSING)
        if value is MISSING or value is None:
            if required:
                raise err.invalid_request(f"missing required field: {name}")
            continue
        if kind == "str":
            if not isinstance(value, str) or value == "":
                raise err.invalid_request(f"{name} must be a non-empty string")
            out[name] = value
        elif kind == "bool":
            if not isinstance(value, bool):
                raise err.invalid_request(f"{name} must be a boolean")
            out[name] = value
        elif kind == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                raise err.invalid_request(f"{name} must be an integer")
            out[name] = value
        elif kind == "float":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise err.invalid_request(f"{name} must be a number")
            out[name] = float(value)
        elif kind == "datetime":
            out[name] = parse_datetime(value, name)
        elif kind == "enum":
            if value not in extra:
                raise err.invalid_request(f"{name} must be one of {list(extra)}")
            out[name] = value
        elif kind == "object":
            if not isinstance(value, dict) or not value:
                raise err.invalid_request(f"{name} must be a non-empty object")
            out[name] = value
        else:  # pragma: no cover
            out[name] = value
    return out


def require_range(value, lo=None, hi=None, lo_exclusive=False, hi_exclusive=False, field="value"):
    bad = False
    if lo is not None:
        bad |= value <= lo if lo_exclusive else value < lo
    if hi is not None:
        bad |= value >= hi if hi_exclusive else value > hi
    if bad:
        raise err.invalid_request(f"{field} is out of range")
    return value


# ---------------------------------------------------------------- entity plumbing
def new_common():
    return {
        "id": new_id(),
        "created_at": wall_now_iso(),
        "updated_at": wall_now_iso(),
        "version": 1,
    }


def touch(entity):
    entity["updated_at"] = wall_now_iso()
    entity["version"] += 1


def get_or_404(collection, entity_id, msg="resource not found"):
    entity = db[collection].get(entity_id)
    if entity is None:
        raise err.not_found(msg)
    return entity


def find_by(collection, key, value):
    return [e for e in db[collection].values() if e.get(key) == value]


def check_unique(collection, key, value, message):
    if any(e.get(key) == value for e in db[collection].values()):
        raise ApiError("ERR_DUPLICATE_CODE", message)


def _parse_ts(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _stable_sorted(entities):
    """created_at ascending; wall-clock timestamp ties broken by creation order
    so that same-millisecond bulk creations keep a deterministic order."""
    return [e for _ts, _idx, e in sorted(
        (_parse_ts(e["created_at"]), i, e) for i, e in enumerate(entities))]


def sorted_list(entities):
    return _stable_sorted(entities)


def paginate(entities, filters=None):
    """Apply equality filters then limit/offset; return (page, limit, offset, total)."""
    from flask import request
    if filters:
        for key, value in filters.items():
            if value is not None:
                entities = [e for e in entities if str(e.get(key)) == str(value)]
    entities = _stable_sorted(entities)
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise err.invalid_request("limit and offset must be integers")
    if limit < 1 or limit > 100:
        raise err.invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err.invalid_request("offset must be >= 0")
    total = len(entities)
    return entities[offset:offset + limit], limit, offset, total


# ---------------------------------------------------------------- open-to-buy
def otb_caps(season):
    budget = season["department_otb_budget_cents"]
    packaway_cap = math.floor(budget * season["packaway_reserve_ratio"])
    forward_cap = budget - packaway_cap
    return forward_cap, packaway_cap


def otb_forward_available(season):
    forward_cap, _ = otb_caps(season)
    return forward_cap - season["committed_forward_cents"]


def otb_packaway_available(season):
    _, packaway_cap = otb_caps(season)
    return packaway_cap - season["committed_packaway_cents"]


def refresh_availability(season):
    """Refresh the season's availability read-model cache (§3.1)."""
    season["forward_available_cents"] = otb_forward_available(season)
    season["packaway_available_cents"] = otb_packaway_available(season)


def recompute_spend(season):
    """Recompute spent_* from RECEIVED receipts against the season's lots."""
    lot_ids = {l["id"] for l in db["lots"].values() if l["season_id"] == season["id"]}
    forward = 0
    packaway = 0
    for rl in db["receipt_lines"].values():
        receipt = db["receipts"].get(rl["receipt_id"])
        if receipt is None or receipt["status"] != "RECEIVED":
            continue
        if receipt["lot_id"] not in lot_ids:
            continue
        lot = db["lots"][receipt["lot_id"]]
        ext = rl.get("extended_cost_cents")
        if ext is None:
            continue
        if lot["disposition"] == "IMMEDIATE":
            forward += ext
        else:
            packaway += ext
    season["spent_forward_cents"] = forward
    season["spent_packaway_cents"] = packaway


def season_view(season):
    refresh_availability(season)
    view = serialize("season", season)
    view["forward_available_cents"] = season["forward_available_cents"]
    view["packaway_available_cents"] = season["packaway_available_cents"]
    view["over_spend_alert"] = (
        season["spent_forward_cents"] > season["committed_forward_cents"]
        or season["spent_packaway_cents"] > season["committed_packaway_cents"]
    )
    view["projected_holding_cents"] = projected_holding_reservation(season)
    return view


def projected_holding_reservation(season):
    """Informational projected holding cost over the season's ACCEPTED PACKAWAY
    lots that have a hold: pallets * warehouse rate * months-to-target."""
    total = 0
    today = today_date()
    for lot in db["lots"].values():
        if lot["season_id"] != season["id"] or lot["status"] != "ACCEPTED":
            continue
        if lot["disposition"] != "PACKAWAY":
            continue
        holds = find_by("holds", "lot_id", lot["id"])
        if not holds:
            continue
        hold = holds[0]
        warehouse = db["warehouses"].get(hold["warehouse_id"])
        target = db["seasons"].get(hold["target_season_id"])
        if warehouse is None or target is None:
            continue
        days = max(0, (target["start_date"].date() - today).days)
        months = math.ceil(days / DAYS_PER_BILLING_MONTH)
        total += hold["pallet_count"] * warehouse["monthly_holding_rate_per_pallet_cents"] * months
    return total


# ---------------------------------------------------------------- calculations
def deal_quality_score(lot, vendor, landed_cost_cents):
    unit_cost_basis = landed_cost_cents / lot["unit_count"]
    margin_pct = (lot["estimated_unit_retail_cents"] - unit_cost_basis) / lot["estimated_unit_retail_cents"]
    margin_pct = max(0.0, margin_pct)
    sell_through = min(lot["expected_sell_through_pct"], 1.0)
    penalty = DISCRETION_PENALTY[vendor["discretion_level"]]
    bonus = LOT_TYPE_BONUS[lot["lot_type"]]
    raw = 100 * (WEIGHT_MARGIN * margin_pct + WEIGHT_SELL_THROUGH * sell_through) - penalty + bonus
    return min(100.0, max(0.0, raw))


def age_bucket_for(hold, on_date=None):
    on_date = on_date or today_date()
    entry = hold["entry_date"].date() if isinstance(hold["entry_date"], datetime) else hold["entry_date"]
    days = (on_date - entry).days
    if days < AGING_REVIEW_DAYS:
        return "FRESH"
    if days < STALE_DAYS:
        return "AGING"
    return "STALE"


def holding_cost_accrual(hold, as_of_date=None):
    as_of_date = as_of_date or today_date()
    entry = hold["entry_date"].date() if isinstance(hold["entry_date"], datetime) else hold["entry_date"]
    days_held = max(0, (as_of_date - entry).days)
    full_months = days_held // DAYS_PER_BILLING_MONTH
    remainder = days_held - DAYS_PER_BILLING_MONTH * full_months
    warehouse = db["warehouses"].get(hold["warehouse_id"])
    rate = warehouse["monthly_holding_rate_per_pallet_cents"] if warehouse else 0
    pallets = hold["pallet_count"]
    if warehouse and warehouse["zone_code"] == "WC":
        months = full_months + (1 if remainder > 0 else 0)
        return pallets * rate * months
    return pallets * rate * full_months + math.floor(pallets * rate * remainder / DAYS_PER_BILLING_MONTH)


def weeks_on_floor(sku, on_date=None):
    on_date = on_date or today_date()
    floor_d = sku["floor_date"].date() if isinstance(sku["floor_date"], datetime) else sku["floor_date"]
    return max(0, (on_date - floor_d).days // 7)


def base_price_cents(sku):
    ticket = db["tickets"].get(sku["ticket_id"])
    return ticket["ticket_retail_cents"] if ticket else sku["current_price_cents"]


# ---------------------------------------------------------------- sweeps
def run_sweeps():
    """Aging sweep + offer-expiry + markdown sweep, driven by a clock advance."""
    # offer expiry: OFFERED lots whose deadline has been reached lapse
    for lot in db["lots"].values():
        if lot["status"] == "OFFERED" and now() >= lot["offer_expires_at"]:
            lot["status"] = "CANCELLED"
            lot["cancel_reason"] = "OFFER_EXPIRED"
            touch(lot)
    # aging sweep: recompute the age bucket and the running holding-cost
    # accrual (§3.4: accrual runs at creation, at every aging review, and as a
    # final computation at release or liquidation — the sweep keeps the running
    # figure current as the logical clock advances)
    for hold in db["holds"].values():
        if hold["status"] in ("STORED", "AGING_REVIEW"):
            bucket = age_bucket_for(hold)
            accrual = holding_cost_accrual(hold)
            if bucket != hold["age_bucket"] or accrual != hold["accrued_holding_cost_cents"]:
                hold["age_bucket"] = bucket
                hold["accrued_holding_cost_cents"] = accrual
                touch(hold)
    # markdown sweep: cadence and force-clearance over live floor stock
    for sku in list(db["store_skus"].values()):
        if sku["status"] not in ("ON_FLOOR", "MARKED_DOWN"):
            continue
        season = db["seasons"].get(sku["season_id"])
        if season is None or season["status"] != "OPEN":
            continue
        store = db["stores"].get(sku["store_id"])
        zone = next((z for z in db["zones"].values()
                     if store and z["zone_code"] == store["zone_code"]), None)
        if zone is None:
            continue
        wof = weeks_on_floor(sku)
        changed = wof != sku["weeks_on_floor"]
        sku["weeks_on_floor"] = wof
        # The cadence step count is derived from the append-only event ledger so
        # a multi-week jump never skips or double-counts boundaries.
        step = sum(1 for e in db["markdown_events"].values()
                   if e["store_sku_id"] == sku["id"] and e["event_type"] == "CADENCE")
        sku["markdown_step"] = step
        if wof >= zone["clearance_weeks"]:
            # Clearance stores skip the cadence but still move to CLEARANCE at
            # the clearance threshold; ordinary stores are likewise forced over.
            old_price = sku["current_price_cents"]
            new_price = price_point(base_price_cents(sku) * CLEARANCE_FLOOR_MULTIPLIER)
            sku["current_price_cents"] = new_price
            sku["status"] = "CLEARANCE"
            _markdown_event(sku, old_price, new_price, "FORCE_CLEARANCE")
            changed = True
        elif not store["clearance_outlet"]:
            if wof >= (step + 1) * zone["markdown_cadence_weeks"]:
                # The reduction applies to the pre-adjustment price: the 9-ending
                # adjustment is a shelf convention on the printed price, not part
                # of the markdown basis.
                if "_pre9_price" not in sku:
                    sku["_pre9_price"] = float(base_price_cents(sku))
                old_price = sku["current_price_cents"]
                sku["_pre9_price"] = sku["_pre9_price"] * (1 - MARKDOWN_STEP_RATE)
                new_price = price_point(sku["_pre9_price"])
                sku["current_price_cents"] = new_price
                sku["status"] = "MARKED_DOWN"
                sku["markdown_step"] = step + 1
                _markdown_event(sku, old_price, new_price, "CADENCE")
                changed = True
        if changed:
            touch(sku)


def _markdown_event(sku, old_price, new_price, event_type):
    db["markdown_events"][new_id()] = {
        "id": new_id(),
        "created_at": wall_now_iso(),
        "store_sku_id": sku["id"],
        "step_number": sku["markdown_step"],
        "old_price_cents": old_price,
        "new_price_cents": new_price,
        "markdown_cents": old_price - new_price,
        "event_type": event_type,
        "effective_date": iso_z(now()),
    }


def recompute_weeks_on_floor(season_id):
    """Season close: recompute weeks_on_floor only, no price changes (§3.1).
    Stock already forced to CLEARANCE is included — its cadence lifecycle is
    complete but its weeks-on-floor figure is still part of the close-out read."""
    for sku in db["store_skus"].values():
        if sku["season_id"] == season_id and sku["status"] in ("ON_FLOOR", "MARKED_DOWN", "CLEARANCE"):
            sku["weeks_on_floor"] = weeks_on_floor(sku)


# ---------------------------------------------------------------- serializers
def _common(entity):
    return {
        "id": entity["id"],
        "created_at": entity["created_at"],
        "updated_at": entity["updated_at"],
        "version": entity["version"],
    }


def serialize(kind, e):
    if kind == "season":
        d = _common(e)
        d.update({
            "season_code": e["season_code"],
            "start_date": iso_z(e["start_date"]),
            "end_date": iso_z(e["end_date"]),
            "department_otb_budget_cents": e["department_otb_budget_cents"],
            "packaway_reserve_ratio": e["packaway_reserve_ratio"],
            "status": e["status"],
            "committed_forward_cents": e["committed_forward_cents"],
            "committed_packaway_cents": e["committed_packaway_cents"],
            "spent_forward_cents": e["spent_forward_cents"],
            "spent_packaway_cents": e["spent_packaway_cents"],
            "forward_available_cents": e.get("forward_available_cents"),
            "packaway_available_cents": e.get("packaway_available_cents"),
        })
        return d
    if kind == "vendor":
        d = _common(e)
        d.update({k: e[k] for k in ("legal_name", "vendor_code", "discretion_level",
                                    "ticket_discretion_required", "default_zone_code",
                                    "vendor_tier")})
        return d
    if kind == "zone":
        d = _common(e)
        d.update({k: e[k] for k in ("zone_code", "compare_at_multiplier",
                                    "markdown_cadence_weeks", "clearance_weeks")})
        return d
    if kind == "lot":
        d = _common(e)
        d.update({k: e[k] for k in ("lot_code", "vendor_id", "season_id", "lot_type",
                                    "disposition", "asking_price_cents", "mixed_lot",
                                    "unit_count", "expected_sell_through_pct",
                                    "estimated_unit_retail_cents", "landed_cost_cents",
                                    "status", "cancel_reason",
                                    "target_season_id")})
        # The deal quality score is carried at 2 decimal places (§2.7).
        d["deal_quality_score"] = (
            round_half_up_2dp(e["deal_quality_score"])
            if e["deal_quality_score"] is not None else None)
        d["offer_expires_at"] = iso_z(e["offer_expires_at"])
        return d
    if kind == "lot_line":
        d = _common(e)
        d.update({k: e[k] for k in ("lot_id", "style_code", "department", "quantity",
                                    "unit_cost_cents", "compare_at_claim_cents",
                                    "target_retail_cents")})
        return d
    if kind == "warehouse":
        d = _common(e)
        d.update({k: e[k] for k in ("warehouse_code", "pallet_capacity", "zone_code",
                                    "monthly_holding_rate_per_pallet_cents")})
        return d
    if kind == "hold":
        d = _common(e)
        d.update({k: e[k] for k in ("lot_id", "warehouse_id", "season_id",
                                    "target_season_id", "pallet_count",
                                    "accrued_holding_cost_cents", "review_count",
                                    "age_bucket", "status")})
        d["entry_date"] = iso_z(e["entry_date"])
        d["release_window_start"] = iso_z(e["release_window_start"])
        d["release_window_end"] = iso_z(e["release_window_end"])
        d["release_date"] = iso_z(e["release_date"]) if e["release_date"] else None
        return d
    if kind == "store":
        d = _common(e)
        d.update({k: e[k] for k in ("store_code", "cluster_code", "zone_code",
                                    "storage_capacity_units", "clearance_outlet")})
        return d
    if kind == "plan":
        d = _common(e)
        d.update({k: e[k] for k in ("lot_id", "season_id", "total_units",
                                    "cluster_weights", "status", "superseded_by_id")})
        return d
    if kind == "store_sku":
        d = _common(e)
        d.update({k: e[k] for k in ("store_id", "lot_line_id", "ticket_id", "season_id",
                                    "allocation_plan_id", "units_on_hand",
                                    "weeks_on_floor", "markdown_step",
                                    "current_price_cents", "status")
                  if k in e})
        d["floor_date"] = iso_z(e["floor_date"])
        return d
    if kind == "ticket":
        return {
            "id": e["id"], "created_at": e["created_at"],
            "lot_line_id": e["lot_line_id"], "zone_code": e["zone_code"],
            "ticket_retail_cents": e["ticket_retail_cents"],
            "compare_at_cents": e["compare_at_cents"],
            "compare_at_omitted": e["compare_at_omitted"],
            "vendor_name_on_ticket": e["vendor_name_on_ticket"],
            "substantiation_notes": e["substantiation_notes"],
            "status": e["status"],
        }
    if kind == "receipt":
        d = _common(e)
        d.update({k: e[k] for k in ("lot_id", "warehouse_id", "status")})
        d["receipt_date"] = iso_z(e["receipt_date"])
        return d
    if kind == "receipt_line":
        return {
            "id": e["id"], "created_at": e["created_at"],
            "receipt_id": e["receipt_id"], "lot_line_id": e["lot_line_id"],
            "declared_qty": e["declared_qty"], "received_qty": e["received_qty"],
            "variance_qty": e["variance_qty"],
            "variance_value_cents": e["variance_value_cents"],
            "extended_cost_cents": e.get("extended_cost_cents"),
        }
    if kind == "shrink_case":
        d = _common(e)
        d.update({k: e[k] for k in ("store_id", "store_sku_id", "lot_id", "shrink_type",
                                    "merge_mode", "units_lost", "units_untraceable",
                                    "shrink_value_cents", "status")})
        return d
    if kind == "markdown_event":
        return {
            "id": e["id"], "created_at": e["created_at"],
            "store_sku_id": e["store_sku_id"], "step_number": e["step_number"],
            "old_price_cents": e["old_price_cents"], "new_price_cents": e["new_price_cents"],
            "markdown_cents": e["markdown_cents"], "event_type": e["event_type"],
            "effective_date": e["effective_date"],
        }
    if kind == "liquidation_order":
        d = _common(e)
        d.update({k: e[k] for k in ("store_id", "lot_id", "reason", "recovery_rate_pct",
                                    "expected_units", "actual_units",
                                    "recovery_value_cents", "status")})
        return d
    raise ValueError(f"unknown kind {kind}")  # pragma: no cover
