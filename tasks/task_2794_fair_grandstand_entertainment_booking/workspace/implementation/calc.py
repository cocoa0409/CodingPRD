"""Money, rounding and every derived calculation (PRD sections 2.6, 3.6-3.10)."""

from decimal import Decimal, ROUND_HALF_UP

from db import db, sort_key

# --- pinned constants ------------------------------------------------------

ADMISSION_TAX_RATE = Decimal("0.0575")
BUNDLE_CREDIT_RATIO = Decimal("0.60")

SPONSOR_OFFSET_SHARE = Decimal("0.25")
FLAT_PROMOTER_EXPENSE_CENTS = 2500000
PRODUCTION_SURCHARGE_PCT = Decimal("0.035")

MERCH_ARTIST_SELLS_RATE = Decimal("0.20")
MERCH_VENUE_SELLS_RATE = Decimal("0.30")
MERCH_TIER_BUMP = Decimal("0.05")
MERCH_ATTENDANCE_TIER_SEATS = 2500
MERCH_FEE_FLOOR_CENTS = 25000
MERCH_FEE_CAP_CENTS = 750000

STAGE_NAMING_PREMIUM = Decimal("0.25")
HIGH_DEMAND_PREMIUM = Decimal("0.10")
PRESENTING_TIER_PREMIUM = Decimal("0.05")
HIGH_DEMAND_GROSS_THRESHOLD_CENTS = 10000000
MAX_PREMIUM_MULTIPLIER = Decimal("1.30")

ATT_BASE_WEIGHT = Decimal("0.60")
ATT_SELL_THROUGH_WEIGHT = Decimal("40.0")
REV_BASE_WEIGHT = Decimal("0.40")
REV_PER_SEAT_DIVISOR = Decimal("500")
REV_CONTRIBUTION_CAP = Decimal("60.0")

GENRE_UNIVERSE_SIZE = Decimal("7")
SEGMENT_UNIVERSE_SIZE = Decimal("4")
NEXT_YEAR_UPLIFT = Decimal("1.10")
MAX_SINGLE_SHOW_SHARE = Decimal("0.35")

MAX_NEGOTIATION_ROUNDS = 3
GENRE_ADJACENCY_GAP_DAYS = 1

ONE = Decimal("1")
ZERO = Decimal("0")


# --- rounding --------------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def rhu(value, places=0):
    """Round half up to the requested number of decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half up to whole cents, returned as a Python int."""
    return int(rhu(value, 0))


def rhu_float(value, places):
    return float(rhu(value, places))


# --- ticket scaling --------------------------------------------------------

def bundle_credit_cents(edition):
    """Sixty percent of the edition's gate admission price, rounded half up."""
    return rhu_int(dec(edition["gate_admission_price_cents"]) * BUNDLE_CREDIT_RATIO)


def artist_face_cents(scale, edition):
    """The artist-facing face value of one ticket in this tier."""
    face = dec(scale["face_price_cents"])
    if scale.get("bundled_with_gate_admission"):
        face = face - dec(bundle_credit_cents(edition))
    return face


def scale_gross_potential_cents(scale, edition):
    face = artist_face_cents(scale, edition)
    return rhu_int(face * dec(scale["allotment_seats"]) * (ONE - ADMISSION_TAX_RATE))


def batch_gross_cents(scale, edition, quantity, channel):
    if channel == "COMP":
        return 0
    face = artist_face_cents(scale, edition)
    return rhu_int(face * dec(quantity) * (ONE - ADMISSION_TAX_RATE))


# --- batch folds -----------------------------------------------------------

def scale_batches(scale_id):
    """This tier's batches in the chronological replay order the fold uses."""
    rows = [b for b in db.batches.values() if b.get("ticket_scale_id") == scale_id]
    rows.sort(key=lambda r: sort_key(r, "recorded_at_utc"))
    return rows


def fold_units(batches):
    units = 0
    for batch in batches:
        if batch.get("batch_kind") == "SALE":
            units += int(batch.get("quantity", 0))
        else:
            units -= int(batch.get("quantity", 0))
    return units


def net_units_all(scale_id):
    """Net units over every batch of the tier, complimentary batches included."""
    return fold_units(scale_batches(scale_id))


def net_units_paid(scale_id):
    """Net units over the tier's batches that count toward paid attendance."""
    rows = [b for b in scale_batches(scale_id) if b.get("counts_toward_paid_attendance")]
    return fold_units(rows)


def net_units_eligible(scale_id, basis, doors_time_utc):
    """Net units for the settlement fold under the requested basis."""
    rows = []
    for batch in scale_batches(scale_id):
        if batch.get("channel") == "COMP":
            continue
        if basis == "PROVISIONAL" and doors_time_utc is not None:
            if not (batch.get("recorded_at_utc") < doors_time_utc):
                continue
        rows.append(batch)
    return fold_units(rows)


def net_units_up_to(scale_id, cutoff_utc):
    """Net non-complimentary units recorded at or before the cutoff instant."""
    rows = [
        b for b in scale_batches(scale_id)
        if b.get("channel") != "COMP" and b.get("recorded_at_utc") <= cutoff_utc
    ]
    return fold_units(rows)


# --- settlement waterfall --------------------------------------------------

def settlement_adjusted_gross(booking, scales, edition, basis):
    """Step one of the waterfall: per-tier round, then sum."""
    total = 0
    doors = booking.get("doors_time_utc")
    for scale in scales:
        units = net_units_eligible(scale["id"], basis, doors)
        face = artist_face_cents(scale, edition)
        total += rhu_int(face * dec(units) * (ONE - ADMISSION_TAX_RATE))
    return total


def settlement_waterfall(booking, scales, edition, advance, basis, merch_gross_cents, merch_seller):
    """The whole pinned waterfall: adjusted gross, artist payout, merchandise split."""
    adjusted_gross = settlement_adjusted_gross(booking, scales, edition, basis)

    sponsorship_offset = rhu_int(dec(booking.get("sponsorship_revenue_cents", 0)) * SPONSOR_OFFSET_SHARE)

    rider_component = 0
    if advance is not None and advance.get("status") != "ADVANCE_CANCELLED":
        rider_component = int(advance.get("approved_rider_cost_cents", 0))
    base_promoter_expense = rider_component + FLAT_PROMOTER_EXPENSE_CENTS

    provisional_net_pool = adjusted_gross + sponsorship_offset - base_promoter_expense
    if provisional_net_pool < 0:
        provisional_net_pool = 0

    split = dec(booking.get("agreed_backend_split_pct", 0))
    guarantee = int(booking.get("agreed_guarantee_cents", 0))
    if booking.get("agreed_deal_type") == "VERSUS":
        backend = rhu_int(dec(provisional_net_pool) * split)
        artist_payout = guarantee if guarantee >= backend else backend
    else:
        overage = provisional_net_pool - int(booking.get("agreed_breakeven_cents", 0))
        if overage < 0:
            overage = 0
        artist_payout = guarantee + rhu_int(dec(overage) * split)

    production_surcharge = rhu_int(dec(artist_payout) * PRODUCTION_SURCHARGE_PCT)
    promoter_expense = base_promoter_expense + production_surcharge
    net_pool = provisional_net_pool - production_surcharge

    hall_rate = MERCH_ARTIST_SELLS_RATE if merch_seller == "ARTIST" else MERCH_VENUE_SELLS_RATE
    if int(booking.get("paid_attendance", 0)) >= MERCH_ATTENDANCE_TIER_SEATS:
        hall_rate = hall_rate + MERCH_TIER_BUMP
    hall_fee = rhu_int(dec(merch_gross_cents) * hall_rate)
    if hall_fee < MERCH_FEE_FLOOR_CENTS:
        hall_fee = MERCH_FEE_FLOOR_CENTS
    if hall_fee > MERCH_FEE_CAP_CENTS:
        hall_fee = MERCH_FEE_CAP_CENTS
    merch_artist_share = merch_gross_cents - hall_fee

    total_artist_settlement = (
        artist_payout + merch_artist_share - int(booking.get("recoupable_production_cost_cents", 0))
    )

    return {
        "adjusted_gross_cents": adjusted_gross,
        "sponsorship_offset_cents": sponsorship_offset,
        "base_promoter_expense_cents": base_promoter_expense,
        "provisional_net_pool_cents": provisional_net_pool,
        "artist_payout_cents": artist_payout,
        "production_surcharge_cents": production_surcharge,
        "promoter_expense_cents": promoter_expense,
        "net_pool_cents": net_pool,
        "merch_hall_fee_cents": hall_fee,
        "merch_artist_share_cents": merch_artist_share,
        "total_artist_settlement_cents": total_artist_settlement,
    }


# --- refund liability ------------------------------------------------------

def refund_rate(action_type, refund_policy, pre_doors, seating_type):
    """The exhaustive rate table of PRD section 3.9."""
    if action_type == "POSTPONE" and refund_policy == "RAIN_CHECK":
        return ZERO
    if refund_policy == "RAIN_CHECK":
        return ZERO
    if refund_policy == "FULL_REFUND":
        return ONE
    if pre_doors:
        return ONE
    if seating_type == "RESERVED":
        return Decimal("0.5")
    return ZERO


def refundable_base_cents(scale, edition):
    base = dec(scale["face_price_cents"]) + dec(scale.get("facility_fee_cents", 0))
    if scale.get("bundled_with_gate_admission"):
        base = base - dec(bundle_credit_cents(edition))
    return base


def refund_liability_cents(scales, edition, action_type, refund_policy, pre_doors, decided_at_utc):
    total = 0
    for scale in scales:
        rate = refund_rate(action_type, refund_policy, pre_doors, scale.get("seating_type"))
        units = net_units_up_to(scale["id"], decided_at_utc)
        total += rhu_int(refundable_base_cents(scale, edition) * dec(units) * rate)
    return total


# --- sponsorship pricing ---------------------------------------------------

def activation_net_fee_cents(base_fee_cents, rights, booking, sponsor):
    premium = ZERO
    if rights == "STAGE_NAMING":
        premium = premium + STAGE_NAMING_PREMIUM
    if int(booking.get("gross_potential_cents", 0)) >= HIGH_DEMAND_GROSS_THRESHOLD_CENTS:
        premium = premium + HIGH_DEMAND_PREMIUM
    if sponsor.get("exclusivity_tier") == "PRESENTING":
        premium = premium + PRESENTING_TIER_PREMIUM
    premium_fee = rhu_int(dec(base_fee_cents) * (ONE + premium))
    ceiling = rhu_int(dec(base_fee_cents) * MAX_PREMIUM_MULTIPLIER)
    return premium_fee if premium_fee <= ceiling else ceiling


# --- artist rescoring ------------------------------------------------------

def artist_draw_score(artist, booking, settlement, scales, edition):
    base = dec(artist.get("base_draw_score", 0))
    total_allotment = sum(int(s.get("allotment_seats", 0)) for s in scales)
    if total_allotment == 0:
        return float(rhu(base, 2))
    sell_through = rhu(dec(booking.get("paid_attendance", 0)) / dec(total_allotment), 4)
    net_pool_per_seat = rhu(dec(settlement.get("net_pool_cents", 0)) / dec(total_allotment), 0)
    if edition.get("strategy_basis") == "REVENUE_WEIGHTED":
        contribution = net_pool_per_seat / REV_PER_SEAT_DIVISOR
        if contribution > REV_CONTRIBUTION_CAP:
            contribution = REV_CONTRIBUTION_CAP
        raw = REV_BASE_WEIGHT * base + contribution
    else:
        raw = ATT_BASE_WEIGHT * base + ATT_SELL_THROUGH_WEIGHT * sell_through
    score = rhu(raw, 2)
    if score < Decimal("0.00"):
        score = Decimal("0.00")
    if score > Decimal("100.00"):
        score = Decimal("100.00")
    return float(score)


# --- buying strategy report -----------------------------------------------

def buying_strategy_report(edition, shows, artists_by_booking, settlements):
    count = len(shows)
    genres = set()
    segments = set()
    total_paid = 0
    for booking in shows:
        artist = artists_by_booking.get(booking["id"])
        if artist is not None:
            genres.add(artist.get("genre"))
            segments.add(artist.get("audience_segment"))
        total_paid += int(booking.get("paid_attendance", 0))
    diversity = rhu(
        Decimal("0.5") * dec(len(genres)) / GENRE_UNIVERSE_SIZE
        + Decimal("0.5") * dec(len(segments)) / SEGMENT_UNIVERSE_SIZE,
        4,
    )
    total_net_pool = sum(int(s.get("net_pool_cents", 0)) for s in settlements)
    if total_paid == 0:
        revenue_per_attendee = 0
    else:
        revenue_per_attendee = rhu_int(dec(total_net_pool) / dec(total_paid))
    uplift = rhu_int(dec(total_net_pool) * NEXT_YEAR_UPLIFT)
    share = rhu_int(dec(edition.get("talent_budget_cap_cents", 0)) * MAX_SINGLE_SHOW_SHARE)
    ceiling = uplift if uplift <= share else share
    return {
        "announced_show_count": count,
        "distinct_genre_count": len(genres),
        "distinct_segment_count": len(segments),
        "genre_diversity_index": float(diversity),
        "total_paid_attendance": total_paid,
        "total_net_pool_cents": total_net_pool,
        "revenue_per_paid_attendee_cents": revenue_per_attendee,
        "recommended_guarantee_ceiling_cents": ceiling,
    }
