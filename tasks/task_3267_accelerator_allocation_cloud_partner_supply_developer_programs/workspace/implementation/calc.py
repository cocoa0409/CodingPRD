"""Every calculation from SCAFFOLD `calculations:` / PRD sections 2 and 3.

Pure functions where possible; the few that need the store take it as an
argument so they stay easy to reason about.
"""

from decimal import Decimal, ROUND_HALF_EVEN, ROUND_CEILING

import constants as K
from util import add_days, days_between, format_utc, parse_utc, q, qi

_HALF = Decimal("0.5")


def _r(value, places):
    exp = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(exp, rounding=ROUND_HALF_EVEN)


# --------------------------------------------------------- subscription ----
def subscription_fee_provisional(sub):
    per_seat = K.TIER_SEAT_FEE[sub["support_tier"]]
    return per_seat, qi(sub["seat_count"] * per_seat)


def subscription_fee_final(sub):
    per_seat = K.TIER_SEAT_FEE[sub["support_tier"]]
    billable = max(min(int(sub["seat_count"]), K.SEAT_CAP), K.SEAT_MIN)
    return billable, qi(billable * per_seat)


def support_tier_credit(seat_count):
    if int(seat_count) < K.SEAT_MIN:
        return int(seat_count) * K.CREDIT_BELOW_MIN
    return int(seat_count) * K.CREDIT_AT_OR_ABOVE_MIN


# ------------------------------------------------------------ allocation ---
def _gap_days(partner, clock):
    deadline = partner.get("eligibility_deadline_at")
    if not deadline:
        return 0
    raw = int((parse_utc(deadline) - clock).total_seconds()) // K.SECONDS_PER_DAY
    return max(0, raw)


def allocation_value_estimate(partner, quantity_units, clock):
    gap = min(_gap_days(partner, clock), K.TIME_MAX)
    units = min(int(quantity_units), K.UNIT_MAX)
    return q(K.W_TIME * gap + K.W_UNIT * units, 1)


def allocation_value_confirm(partner, quantity_units, clock):
    gap = _gap_days(partner, clock)
    units = min(int(quantity_units), K.UNIT_MAX)
    return q(K.W_TIME * gap + K.W_UNIT * units, 1)


def allocation_priority_ranking(db, candidates):
    """Rank REQUESTED holds per allocation_priority_ranking.

    Each entry is (hold, node).  Score = confirm(h) - 0.5 * estimate(h)
    - 5.0 * partner.qualification_attempt_count, with zero-product terms
    omitted, then ordered by score DESC, then by the earliest creation
    timestamp among that partner's holds on the SKU, then by the hold's own
    created_at.  The random id is never consulted.
    """
    rows = []
    for hold, node in candidates:
        partner = db.partners.get(hold["partner_id"])
        if partner is None:
            continue
        confirm = allocation_value_confirm(partner, hold["quantity_units"], db.clock)
        estimate = allocation_value_estimate(partner, hold["quantity_units"], db.clock)
        score = Decimal(str(confirm))
        half_estimate = Decimal(str(estimate)) * _HALF
        if half_estimate != 0:
            score -= half_estimate
        attempts = int(partner.get("qualification_attempt_count", 0) or 0)
        penalty = Decimal(str(K.PENALTY_ATTEMPT)) * attempts
        if penalty != 0:
            score -= penalty
        anchor = min(
            h.get("created_at", "") for h in db.holds.values()
            if h.get("partner_id") == hold["partner_id"]
            and h.get("product_sku_id") == hold.get("product_sku_id")
        )
        rows.append((float(_r(score, 1)), anchor, hold.get("created_at", ""), hold))
    rows.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [item[3] for item in rows]


def committed_rate_v2(partner, quantity_units):
    """Return (rate, fee_cents) under the variant the partner's origin selects."""
    quantity = int(quantity_units)
    origin = int(partner.get("origin_epoch_index", 0) or 0)
    if origin < K.CUTOVER_EPOCH_INDEX:
        total = Decimal(str(K.RATE_PER_UNIT)) * quantity
        return round(K.RATE_PER_UNIT, 4), qi(total * K.CENT_SCALE)
    total = Decimal("0")
    remaining = quantity
    band = 0
    while remaining > 0:
        band_units = min(remaining, K.RATE_BAND_WIDTH_UNITS)
        band_rate = min(K.RATE_PER_UNIT + band * K.RATE_BAND_STEP, K.RATE_CAP)
        total += Decimal(str(band_rate)) * band_units
        remaining -= band_units
        band += 1
    if quantity == 0:
        return round(K.RATE_PER_UNIT, 4), 0
    rate = float(_r(total / Decimal(quantity), 4))
    fee_cents = qi(total * K.CENT_SCALE)
    return rate, fee_cents


def hold_commitment_fee_cents(hold):
    """Per-allocation half-even rounding, then summed by the caller."""
    rate = Decimal(str(hold.get("committed_rate_v2", 0)))
    quantity = Decimal(str(hold.get("quantity_units", 0)))
    band = "SHORT"
    forecast_id = hold.get("forecast_id")
    if forecast_id:
        band = hold.get("forecast_horizon_band") or "SHORT"
    multiplier = Decimal(str(K.COMMITMENT_RATE_TABLE.get(band, 0.2)))
    return int(_r(rate * quantity * multiplier * K.CENT_SCALE, 0))


def allocation_commitment_fee(db, node):
    total = 0
    for hold in db.holds.values():
        if hold.get("supply_node_id") != node["id"]:
            continue
        if hold.get("state") not in ("COMMITTED", "REQUESTED"):
            continue
        total += hold_commitment_fee_cents(hold)
    return total


def total_committed_rate(db, node):
    total = Decimal("0")
    for hold in db.holds.values():
        if hold.get("supply_node_id") != node["id"]:
            continue
        if hold.get("state") not in ("COMMITTED", "REQUESTED"):
            continue
        total += Decimal(str(hold.get("committed_rate_v2", 0)))
    return total


def band_for_rate(rate):
    value = Decimal(str(rate))
    if value >= Decimal(str(K.HOTNESS_SCALDING_RATE)):
        return "SCALDING"
    if value >= Decimal(str(K.HOTNESS_HOT_RATE)):
        return "HOT"
    if value >= Decimal(str(K.HOTNESS_WARM_RATE)):
        return "WARM"
    return "COOL"


def decay_factor(epochs=1):
    return Decimal("0.5") ** (Decimal(epochs) / Decimal(K.HALF_LIFE_EPOCHS))


def supply_hotness_tier(db, node):
    """Return (hotness_tier, temp_band_ceiling, half_life_next, total_rate)."""
    total = total_committed_rate(db, node)
    tier = band_for_rate(total)
    ceiling = K.BAND_CEILING[tier]
    decayed = total * decay_factor(K.HALF_LIFE_EPOCHS)
    return tier, ceiling, band_for_rate(decayed), total


def qualification_attempt_penalty(attempt_count):
    return min(int(attempt_count) * K.ATTEMPT_PENALTY_BASE, K.ATTEMPT_PENALTY_CAP)


def friction_penalty_score(engaged_tier, ceiling_tier):
    engaged = K.TIER_INDEX[engaged_tier]
    ceiling = K.TIER_INDEX[ceiling_tier]
    # A penalty at or below the ceiling is minimal (index 0) and each tier of
    # overshoot doubles the score from there (PRD 3.3).
    index = max(0, engaged - ceiling)
    return q(K.SCORE_BASE * (2 ** index), 1)


# --------------------------------------------------------------- export ----
def declared_density_band(tdp_watts):
    density = int(tdp_watts)
    band = "HIGH" if density >= K.DENSITY_BOUNDARY else "LOW"
    return density, band


def computed_density_band(tdp_watts):
    density = qi(-(-int(tdp_watts) // K.DENSITY_STEP) * K.DENSITY_STEP)
    band = "HIGH" if density >= K.DENSITY_BOUNDARY else "LOW"
    return density, band


def export_control_classification(destination_country_code, density_band):
    if destination_country_code in K.PROHIBITED_DESTINATIONS:
        return "TIER_3_PROHIBITED"
    if destination_country_code == "US":
        return "TIER_1_CLEARED"
    # The destinations an export licence grant may unlock are the
    # licence-required band (PRD 2.5 names DE, FR, SG and CA), so they resolve
    # to TIER_2_LICENSE_REQUIRED; any other permitted destination falls back to
    # the density-derived band.
    if destination_country_code in K.LICENSE_REQUIRED_DESTINATIONS:
        return "TIER_2_LICENSE_REQUIRED"
    if density_band == "HIGH":
        return "TIER_2_LICENSE_REQUIRED"
    return "TIER_1_CLEARED"


# ----------------------------------------------------------- forecasting ---
def third_saturday(year, month):
    day = K.FORECAST_BOUNDARY_DAY
    while True:
        candidate = parse_utc("%04d-%02d-%02dT00:00:00Z" % (year, month, day))
        if candidate.weekday() == 5:
            return candidate
        day += 1


def forecast_commitment_deadline(acknowledged_at):
    """Return (horizon_band, eligibility_deadline_at)."""
    ack = parse_utc(acknowledged_at)
    boundary = third_saturday(ack.year, ack.month)
    after_boundary = add_days(boundary, K.SHORT_DEADLINE_OFFSET_DAYS)
    day_of_month = ack.day
    if day_of_month >= K.FORECAST_BOUNDARY_DAY and ack <= after_boundary:
        return "SHORT", format_utc(after_boundary)
    if ack <= add_days(boundary, 7):
        return "MEDIUM", format_utc(add_days(ack, K.MEDIUM_GAP_DAYS))
    return "LONG", format_utc(add_days(ack, K.LONG_GAP_DAYS))


def forecast_forfeit_rate(horizon_band, committed_volume_units, requested_quantity_units):
    base = Decimal(str(K.FORFEIT_BAND_RATE[horizon_band]))
    excess = max(0, int(committed_volume_units) - int(requested_quantity_units))
    ratio = Decimal(excess) / Decimal(max(1, int(requested_quantity_units)))
    surcharge = min(Decimal(str(K.FORFEIT_OVERAGE_PENALTY)), ratio)
    total = min(base + surcharge, Decimal(str(K.OVERAGE_CAP)))
    return float(_r(total, 4))


# ------------------------------------------------------------ evaluation ---
def ring_fence_for_ratio(supply_ceiling_units):
    """ceil(supply_ceiling_units * EVAL_RESERVE_RATIO) as an integer."""
    numerator = Decimal(int(supply_ceiling_units)) * Decimal(str(K.EVAL_RESERVE_RATIO))
    return int(numerator.to_integral_value(rounding=ROUND_CEILING))


def loan_late_fee(days_late):
    days = max(0, int(days_late))
    raw = Decimal(days) * Decimal(str(K.LATE_FEE_PER_DAY_UNITS))
    capped = min(raw, Decimal(str(K.LATE_FEE_CAP_UNITS)))
    return float(_r(capped, 1))


# ------------------------------------------------------------ membership ---
def tier_index(tier):
    if tier not in K.TIER_ORDER:
        return 0
    return K.TIER_ORDER.index(tier)


def advance_tier(stored_tier, requested_tier):
    stored = tier_index(stored_tier)
    requested = tier_index(requested_tier)
    if requested <= stored:
        return K.TIER_ORDER[stored]
    return K.TIER_ORDER[stored + 1]


def accepted_evidence_minutes(db, partner_id):
    """Minutes of ACCEPTED evidence in the blueprint's current era."""
    total = 0
    for evidence in db.evidences.values():
        if evidence.get("partner_id") != partner_id:
            continue
        if evidence.get("evidence_pack_status") != "ACCEPTED":
            continue
        blueprint = db.blueprints.get(evidence.get("blueprint_id"))
        if blueprint is None:
            continue
        if int(evidence.get("era_index", 1)) != int(blueprint.get("era_index", 1)):
            continue
        total += int(evidence.get("validation_minutes", 0))
    return total


def developer_tier_provision(db, membership, partner):
    """Return (preview_kit_units, support_incidents_included)."""
    stored = membership.get("stored_tier", "COMMUNITY")
    minutes = accepted_evidence_minutes(db, membership.get("partner_id"))
    kits = K.TIER_KIT_UNITS[stored] + -(-minutes // K.ELITE_ADVANCE_MINUTES)
    incidents = K.TIER_INCIDENT_UNITS[stored]
    latest = latest_active_subscription(db, membership.get("partner_id"))
    if latest is not None:
        incidents += int(latest.get("support_credit_units", 0)) // 100
    return kits, incidents


def latest_active_subscription(db, partner_id):
    candidates = [
        sub for sub in db.subscriptions.values()
        if sub.get("partner_id") == partner_id
        and sub.get("status") in ("ACTIVE", "SUSPENDED", "RECLAIMED", "EXPIRED")
        and sub.get("activated_at")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda row: row.get("activated_at", ""))
    return candidates[-1]


# ------------------------------------------------------------- lifecycle ---
def lifecycle_commitment_floor(partner, product, availability_through, clock):
    """Pinned four-step evaluation order (PRD 3.9)."""
    step1 = int((parse_utc(availability_through) - clock).total_seconds()) // K.SECONDS_PER_DAY
    extension = K.EMBEDDED_EXTENSION_DAYS if partner.get("partner_type") == "EMBEDDED_VENDOR" else 0
    floor_days = max(step1, K.COMMITMENT_FLOOR_MIN_DAYS + extension)
    if product.get("lifecycle_stage") in K.MATURE_STAGES:
        product_min = floor_days
    else:
        product_min = min(floor_days, K.COMMITMENT_FLOOR_MIN_DAYS)
    return floor_days, product_min


# ------------------------------------------------------ partner priority ---
def on_time_ratio(partner):
    total = int(partner.get("total_deliveries", 0) or 0)
    on_time = int(partner.get("on_time_deliveries", 0) or 0)
    if total <= 0:
        return 1.0
    return float(_r(Decimal(on_time) / Decimal(max(1, total)), 4))


def partner_priority_class(partner):
    if partner.get("qualification_status") != "QUALIFIED":
        return "UNQUALIFIED"
    held = int(partner.get("entitlement_units_held", 0) or 0)
    attempts = int(partner.get("qualification_attempt_count", 0) or 0)
    ratio = on_time_ratio(partner)
    if (
        held >= K.TIER1_ENTITLEMENT_MIN
        and ratio >= K.TIER1_ON_TIME_RATIO_MIN
        and attempts == 0
    ):
        return "TIER_1"
    if held >= K.TIER2_ENTITLEMENT_MIN:
        return "TIER_2"
    return "TIER_3"


# ------------------------------------------------------------ pool release --
def released_entitlement_units(db, deployment):
    """Step 1 of entitlement_pool_release."""
    total = 0
    for sub in db.subscriptions.values():
        if sub.get("deployment_id") != deployment["id"]:
            continue
        if sub.get("status") not in ("ACTIVE", "SUSPENDED"):
            continue
        for license_id in sub.get("bound_stack_ids", []) or []:
            license_row = db.stack_licenses.get(license_id)
            if license_row is not None:
                total += int(license_row.get("entitlement_units", 0))
                break
    return total