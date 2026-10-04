"""Rate sheets, the pricing engine and the quote guards (PRD 3.5)."""

import re

import db
from constants import (
    CREDIT_ADJUSTMENTS,
    GOLD_MAX_POINTS,
    LOCK_BOUNDARY_LONG_DAYS,
    LOCK_BOUNDARY_SHORT_DAYS,
    LOCK_SURCHARGE_15D,
    LOCK_SURCHARGE_30D,
    LOCK_SURCHARGE_60D,
    LOAN_PURPOSES,
    LTV_ADJUSTMENTS,
    LTV_BAND_COUNT,
    OCCUPANCY_ADJUSTMENTS,
    OCCUPANCY_TYPES,
    PLATINUM_MAX_POINTS,
    PRICE_TABLE_ROWS,
    PRODUCT_ADJUSTMENTS,
    PRODUCT_CODES,
    SILVER_MAX_POINTS,
    TIER_DISCOUNT,
)
from errors import ApiError
from numeric import ONE, ZERO, quantize, round_half_up, to_decimal
from services import shared

DIM_ORDER = ["credit", "ltv", "occupancy", "product"]


# ---------------------------------------------------------------------------
# Band selection
# ---------------------------------------------------------------------------
def credit_band_index(fico):
    """Half-open bands, last one open: [760,inf), [740,760), ... (-inf,680)."""
    score = to_decimal(fico, ZERO)
    if score >= 760:
        return 0
    if score >= 740:
        return 1
    if score >= 720:
        return 2
    if score >= 700:
        return 3
    if score >= 680:
        return 4
    return 5


def ltv_band_index(ltv_ratio):
    """Open on the left, closed on the right except the last."""
    ratio = to_decimal(ltv_ratio, ZERO)
    if ratio <= to_decimal("0.60"):
        return 0
    if ratio <= to_decimal("0.70"):
        return 1
    if ratio <= to_decimal("0.80"):
        return 2
    if ratio <= to_decimal("0.90"):
        return 3
    if ratio <= to_decimal("0.95"):
        return 4
    return 5


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


CREDIT_LABELS = [
    {"760plus", "760andabove", "760ormore", "760up", "over760", "atleast760", "760"},
    {"740759", "740to759", "740up", "740"},
    {"720739", "720to739", "720up", "720"},
    {"700719", "700to719", "700up", "700"},
    {"680699", "680to699", "680up", "680"},
    {"under680", "below680", "lessthan680", "sub680", "680minus", "lower680"},
]

LTV_LABELS = [
    {"upto60", "upto060", "60andbelow", "060andbelow", "0060", "060", "000060", "0to60", "atmost60"},
    {"6070", "060070", "0060070", "60to70", "over60upto70", "60upto70"},
    {"7080", "070080", "0070080", "70to80", "over70upto80"},
    {"8090", "080090", "0080090", "80to90", "over80upto90"},
    {"9095", "090095", "0090095", "90to95", "over90upto95"},
    {"over95", "above95", "95plus", "greaterthan95", "95"},
]

CREDIT_BUCKET_LABELS = ["760-plus", "740-759", "720-739", "700-719", "680-699", "under-680"]
LTV_BUCKET_LABELS = ["up-to-60", "60-70", "70-80", "80-90", "90-95", "over-95"]


def credit_bucket_label(fico):
    return CREDIT_BUCKET_LABELS[credit_band_index(fico)]


def ltv_band_label(ltv_ratio):
    return LTV_BUCKET_LABELS[ltv_band_index(ltv_ratio)]


def _rows_for_dim(sheet, dim):
    return [row for row in sheet.get("adjustment_table", []) if row.get("dim") == dim]


def _pick_row(sheet, dim, index, label_sets, enum_value=None):
    rows = _rows_for_dim(sheet, dim)
    if enum_value is not None:
        for row in rows:
            if _norm(row.get("bucket")) == _norm(enum_value):
                return row
        return None
    if index is not None and 0 <= index < len(label_sets):
        accepted = label_sets[index]
        for row in rows:
            if _norm(row.get("bucket")) in accepted:
                return row
        if index < len(rows):
            return rows[index]
    return None


def _dimension_row(sheet, dim, credit_index=None, ltv_index=None, enum_value=None):
    if dim == "credit":
        row = _pick_row(sheet, "credit", credit_index, CREDIT_LABELS)
        fallback_bucket = CREDIT_BUCKET_LABELS[credit_index] if credit_index is not None else "credit"
        fallback_adjust = CREDIT_ADJUSTMENTS[credit_index] if credit_index is not None else ZERO
    elif dim == "ltv":
        row = _pick_row(sheet, "ltv", ltv_index, LTV_LABELS)
        fallback_bucket = LTV_BUCKET_LABELS[ltv_index] if ltv_index is not None else "ltv"
        fallback_adjust = LTV_ADJUSTMENTS[ltv_index] if ltv_index is not None else ZERO
    elif dim == "occupancy":
        row = _pick_row(sheet, "occupancy", None, None, enum_value=enum_value)
        fallback_bucket = enum_value
        fallback_adjust = OCCUPANCY_ADJUSTMENTS.get(enum_value, ZERO)
    else:
        row = _pick_row(sheet, "product", None, None, enum_value=enum_value)
        fallback_bucket = enum_value
        fallback_adjust = PRODUCT_ADJUSTMENTS.get(enum_value, ZERO)

    if row is None:
        return {"dim": dim, "bucket": fallback_bucket, "adjust_pct": fallback_adjust}
    adjust = to_decimal(row.get("adjust_pct"), ZERO)
    return {"dim": dim, "bucket": row.get("bucket"), "adjust_pct": adjust}


# ---------------------------------------------------------------------------
# overall_rate_adjustment (PRD 3.5)
# ---------------------------------------------------------------------------
def compute_adjustment_trace(sheet, representative_fico, ltv_ratio, occupancy_type, product_code):
    credit_row = _dimension_row(sheet, "credit", credit_index=credit_band_index(representative_fico))
    ltv_row = _dimension_row(sheet, "ltv", ltv_index=ltv_band_index(ltv_ratio))
    occupancy_row = _dimension_row(sheet, "occupancy", enum_value=occupancy_type)
    product_row = _dimension_row(sheet, "product", enum_value=product_code)
    trace = [credit_row, ltv_row, occupancy_row, product_row]
    total = ZERO
    for row in trace:
        total = total + row["adjust_pct"]
    return total, trace


# ---------------------------------------------------------------------------
# lock_adjustment / pricing_quote_note_rate (PRD 3.5)
# ---------------------------------------------------------------------------
def lock_adjustment(lock_period_days):
    days = int(lock_period_days)
    if days < LOCK_BOUNDARY_SHORT_DAYS:
        return LOCK_SURCHARGE_15D
    if days < LOCK_BOUNDARY_LONG_DAYS:
        return LOCK_SURCHARGE_30D
    return LOCK_SURCHARGE_60D


def note_rate(base_rate_pct, overall_adjustment_pct, lock_adjustment_pct):
    """Sum the three components at full precision, round once at the end."""
    raw = to_decimal(base_rate_pct, ZERO) + overall_adjustment_pct + lock_adjustment_pct
    return round_half_up(raw, 3)


# ---------------------------------------------------------------------------
# pricing_quote_price_points (PRD 3.5)
# ---------------------------------------------------------------------------
def fico_bucket(representative_fico):
    score = to_decimal(representative_fico, ZERO)
    return round_half_up(score / to_decimal(10), 0) * to_decimal(10)


def _grid_row_key(bucket):
    if bucket >= 760:
        return "760+"
    if bucket >= 740:
        return "740"
    if bucket >= 720:
        return "720"
    if bucket >= 700:
        return "700"
    if bucket >= 680:
        return "680"
    if bucket >= 660:
        return "660"
    return "<660"


def base_grid_points(representative_fico, ltv_ratio):
    key = _grid_row_key(fico_bucket(representative_fico))
    column = ltv_band_index(ltv_ratio)
    return PRICE_TABLE_ROWS[key][column]


def discount_tier(provisional_points):
    if provisional_points <= PLATINUM_MAX_POINTS:
        return "PLATINUM"
    if provisional_points <= GOLD_MAX_POINTS:
        return "GOLD"
    if provisional_points <= SILVER_MAX_POINTS:
        return "SILVER"
    return "BRONZE"


def price_points(representative_fico, ltv_ratio, overall_adjustment_pct):
    base = base_grid_points(representative_fico, ltv_ratio)
    provisional = base + overall_adjustment_pct
    tier = discount_tier(provisional)
    final = provisional + TIER_DISCOUNT[tier]
    return round_half_up(final, 3)


# ---------------------------------------------------------------------------
# Rate sheets
# ---------------------------------------------------------------------------
def publish_rate_sheet(broker_id, body):
    broker = shared.get_broker(broker_id)
    product_code = shared.require_enum(body, "product_code", PRODUCT_CODES)
    base_rate = shared.require_decimal(body, "base_rate_pct")
    table = shared.field(body, "adjustment_table", None)
    if not isinstance(table, list) or not table:
        raise ApiError("ERR_INVALID_REQUEST", "adjustment_table must be a non-empty array.")
    normalised = []
    for entry in table:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each adjustment_table row must be an object.")
        dim = entry.get("dim")
        if dim not in DIM_ORDER:
            raise ApiError("ERR_INVALID_REQUEST",
                           "adjustment_table dim %r is not one of %s." % (dim, DIM_ORDER))
        adjust = to_decimal(entry.get("adjust_pct"))
        if adjust is None:
            raise ApiError("ERR_INVALID_REQUEST", "adjust_pct must be a number.")
        normalised.append({"dim": dim, "bucket": entry.get("bucket"), "adjust_pct": adjust})

    highest = 0
    for row in db.rate_sheets.values():
        if row["broker_id"] == broker["id"] and row["product_code"] == product_code:
            highest = max(highest, int(row["publish_sequence"]))

    row = db.base_row()
    row.update({
        "broker_id": broker["id"],
        "product_code": product_code,
        "base_rate_pct": base_rate,
        "status": "PUBLISHED",
        "superseded_by_sheet_id": None,
        "published_at": db.now_iso(),
        "publish_sequence": highest + 1,
        "adjustment_table": normalised,
    })
    db.rate_sheets[row["id"]] = row

    for prior in db.rate_sheets.values():
        if prior["id"] == row["id"]:
            continue
        if prior["broker_id"] != broker["id"] or prior["product_code"] != product_code:
            continue
        if prior["status"] == "PUBLISHED":
            prior["status"] = "SUPERSEDED"
            prior["superseded_by_sheet_id"] = row["id"]
            db.touch(prior)

    db.touch(broker)
    return row


def retire_rate_sheet(broker_id, sheet_id):
    broker = shared.get_broker(broker_id)
    sheet = shared.get_rate_sheet(sheet_id)
    if sheet["broker_id"] != broker["id"]:
        raise ApiError("ERR_RATE_SHEET_NOT_FOUND",
                       "Rate sheet %s does not belong to broker %s." % (sheet_id, broker_id))
    for quote in db.pricing_quotes.values():
        if quote["rate_sheet_id"] == sheet["id"]:
            raise ApiError("ERR_SHEET_IN_USE",
                           "Rate sheet %s already has pricing quotes." % sheet_id)
    if sheet["status"] == "RETIRED":
        raise ApiError("ERR_SHEET_IN_USE", "Rate sheet %s is already retired." % sheet_id)
    sheet["status"] = "RETIRED"
    db.touch(sheet)
    db.touch(broker)
    return sheet


def published_sheet_for(broker_id, product_code):
    newest = None
    for row in db.rate_sheets.values():
        if row["broker_id"] != broker_id or row["product_code"] != product_code:
            continue
        if row["status"] != "PUBLISHED":
            continue
        if newest is None or int(row["publish_sequence"]) > int(newest["publish_sequence"]):
            newest = row
    return newest


def is_repriced(quote):
    published = published_sheet_for(quote["broker_id"], quote["product_code"])
    if published is None:
        return False
    sheet = db.rate_sheets.get(quote["rate_sheet_id"])
    if sheet is None:
        return False
    return int(published["publish_sequence"]) > int(sheet["publish_sequence"])


def serialize_quote(row):
    from serializers import pricing_quote
    payload = pricing_quote(row)
    payload["is_repriced"] = is_repriced(row)
    return payload


# ---------------------------------------------------------------------------
# Pricing quote creation (PRD 3.5, guards per 1.4 priority order)
# ---------------------------------------------------------------------------
def create_pricing_quote(sheet_id, caller, body):
    sheet = shared.get_rate_sheet(sheet_id)          # priority 3
    broker = shared.get_broker(sheet["broker_id"])

    # priority 5 - rate sheet version guard
    if isinstance(body, dict) and "expected_rate_sheet_version" in body:
        expected = body.get("expected_rate_sheet_version")
        if expected is None or int(expected) != int(sheet["version"]):
            raise ApiError("ERR_STALE_VERSION",
                           "expected_rate_sheet_version %r no longer matches version %s."
                           % (expected, sheet["version"]))

    # priority 11 - exclusivity breach (only when the scenario discloses one)
    disclosed = shared.field(body, "competitor_channel_identifier", None)
    if disclosed:
        breach_policy = find_active_policy_by_competitor(broker["id"], disclosed)
        if breach_policy is not None:
            record_breach(breach_policy)
            shared.recompute_exclusivity_status(broker)
            raise ApiError("ERR_EXCLUSIVITY_POLICY_BREACH",
                           "competitor_channel_identifier is listed on an ACTIVE policy.")

    # priority 12 - a RESTRICTED broker is held back on covered operations
    if shared.exclusivity_scope_covers(broker, "RATE_LOCK"):
        raise ApiError("ERR_BROKER_EXCLUSIVITY_RESTRICTED",
                       "The breached policy's restriction_scope covers rate locking.")

    # priority 15 - only a PUBLISHED sheet may be priced
    if sheet["status"] != "PUBLISHED":
        raise ApiError("ERR_PRICING_QUOTE_SUPERSEDED",
                       "The rate sheet is %s and may no longer be priced." % sheet["status"])

    # priority 29 - body well-formedness
    representative_fico = shared.require_int(body, "representative_fico")
    ltv_ratio = shared.require_decimal(body, "ltv_ratio")
    occupancy_type = shared.require_enum(body, "occupancy_type", OCCUPANCY_TYPES)
    loan_amount_cents = shared.require_int(body, "loan_amount_cents")
    lock_period_days = shared.require_int(body, "lock_period_days")
    loan_purpose = shared.require_enum(body, "loan_purpose", LOAN_PURPOSES)
    if not isinstance(body, dict) or "expected_rate_sheet_version" not in body:
        raise ApiError("ERR_INVALID_REQUEST",
                       "expected_rate_sheet_version is required on this endpoint.")

    # priority 31 - BrokerUser ownership
    if caller.role == "BrokerUser" and caller.user_id != broker["id"]:
        raise ApiError("ERR_BROKER_RESOURCE_FORBIDDEN",
                       "BrokerUser %s may not price for broker %s." % (caller.user_id, broker["id"]))

    # priority 34 - the broker must be APPROVED
    if broker["status"] != "APPROVED":
        raise ApiError("ERR_BROKER_NOT_APPROVED",
                       "Broker %s is %s." % (broker["id"], broker["status"]))

    overall, trace = compute_adjustment_trace(
        sheet, representative_fico, ltv_ratio, occupancy_type, sheet["product_code"])
    lock = lock_adjustment(lock_period_days)
    note = note_rate(sheet["base_rate_pct"], overall, lock)
    points = price_points(representative_fico, ltv_ratio, overall)

    row = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "rate_sheet_id": sheet["id"],
        "broker_id": broker["id"],
        "product_code": sheet["product_code"],
        "representative_fico": representative_fico,
        "ltv_ratio": ltv_ratio,
        "occupancy_type": occupancy_type,
        "loan_amount_cents": loan_amount_cents,
        "lock_period_days": lock_period_days,
        "loan_purpose": loan_purpose,
        "overall_adjustment_pct": overall,
        "lock_adjustment_pct": lock,
        "note_rate_pct": note,
        "price_points": points,
        "adjustment_trace": trace,
    }
    db.pricing_quotes[row["id"]] = row
    db.touch(sheet)
    return row


# ---------------------------------------------------------------------------
# Exclusivity helpers used by the pricing and submission paths
# ---------------------------------------------------------------------------
def find_active_policy_by_competitor(broker_id, competitor_identifier):
    if not competitor_identifier:
        return None
    needle = str(competitor_identifier).strip().lower()
    now = db.clock.now
    for row in db.exclusivity_policies.values():
        if row["broker_id"] != broker_id:
            continue
        if row["status"] != "ACTIVE":
            continue
        # The window is half-open: effective_from is inclusive, effective_to is
        # exclusive (PRD 3.4). A disclosure outside it is not a breach.
        start = db.parse_instant(row.get("effective_from"))
        end = db.parse_instant(row.get("effective_to"))
        if start is not None and now < start:
            continue
        if end is not None and now >= end:
            continue
        if str(row["competitor_identifier"]).strip().lower() == needle:
            return row
    return None


def record_breach(policy, loan=None):
    if loan is not None:
        recorded = policy.setdefault("breached_loan_ids", set())
        if loan["id"] in recorded:
            return policy
        recorded.add(loan["id"])
    policy["breach_count"] = int(policy["breach_count"]) + 1
    db.touch(policy)
    return policy


def sheet_for_quote(quote):
    return db.rate_sheets.get(quote["rate_sheet_id"])


def quote_note_rate(quote):
    return to_decimal(quote["note_rate_pct"], ZERO)


def products_deliverable(broker):
    return list(broker["approved_product_codes"])


def quote_sheet_is_live(quote):
    sheet = sheet_for_quote(quote)
    return sheet is not None and sheet["status"] == "PUBLISHED"


ONE_QUANTUM = quantize(ONE, 0)