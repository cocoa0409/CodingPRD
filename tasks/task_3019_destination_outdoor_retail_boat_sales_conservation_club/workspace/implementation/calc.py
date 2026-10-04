"""Business calculations (§1.3 / PRD §2.8.1). All money is integer cents."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from core import DB, get, find, find_one, now, days_between, err, touch

D = Decimal


def rhu(value):
    """round_half_up to an integer (values are cents / points / minutes)."""
    return int(D(str(value)).quantize(D("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """round_half_up to 2 decimal places."""
    return D(str(value)).quantize(D("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Constants (§1.3)
# ---------------------------------------------------------------------------
RIGGING_FEE_CENTS = 95000
ACCESSORY_DISCOUNT_CAP_CENTS = 500000
ACCESSORY_DISCOUNT_BPS_NEW = 500
ACCESSORY_DISCOUNT_BPS_USED = 250
TIER_CREDIT_BPS_BY_CARD_STATUS = {"NONE": 0, "PENDING": 100, "ACTIVE": 500, "SUSPENDED": 0}
FLOOR_PRICE_CENTS = 1

DOC_FEE_CENTS = 59900
TITLE_FEE_BOAT_CENTS = 4500
TITLE_FEE_OTHER_CENTS = 2500
SALES_TAX_BPS = 725
DELIVERY_PREP_CENTS = 25000

POINTS_BAND_BPS_LOW = 8
POINTS_BAND_BPS_MID = 12
POINTS_BAND_BPS_HIGH = 18
POINTS_BAND_LOW_MAX_CENTS = 5000000
POINTS_BAND_MID_MAX_CENTS = 15000000
POINTS_BPS_DENOMINATOR = 100000
ACTIVE_CARD_MULTIPLIER = 2
POINTS_AWARD_CAP = 20000

ACTIVE_CARD_REBATE_BPS = 300
PRIOR_TITLE_PENALTY_BPS = 200

TIER_FEE_CENTS = {
    "FISHING": {"RESIDENT": 3200, "NON_RESIDENT": 8400, "SENIOR": 1500, "YOUTH": 800},
    "HUNTING": {"RESIDENT": 4500, "NON_RESIDENT": 12000, "SENIOR": 2200, "YOUTH": 900},
    "ARCHERY_RANGE": {"RESIDENT": 2100, "NON_RESIDENT": 3900, "SENIOR": 1100, "YOUTH": 600},
    "BOAT_REGISTRATION": {"RESIDENT": 6500, "NON_RESIDENT": 6500, "SENIOR": 6500, "YOUTH": 6500},
}
TERM_BUCKET_STEP_BPS = {"LE_7": 10000, "LE_30": 12500, "LE_365": 10000, "GT_365": 15000}
# A land-access unit adds 1.25 cents, carried as 125 units of 1e-4 cent.
# The scaffold's constant (125000) and the PRD's own prose spellings both
# contradict the pinned worked example stated in the same PRD sentence: a
# FISHING/RESIDENT/LE_7 sale with three land-access units prices at 3204 under
# exact_rational against 3203 under per_unit_rounded. Only 1.25 cents per unit
# reproduces that pair (base 3200 + 3 * 1.25 = 3203.75 -> half-up 3204; the
# per-unit variant rounds the add-on to 1 cent per unit -> 3203), so the worked
# example governs over the inconsistent spellings of the constant.
LAND_ACCESS_UNIT_UNITS_1E4 = 12500    # 1.25 cents, in units of 1e-4 cent
MICRO_CENTS_PER_CENT = 10000
LC_FLOOR_UNIT_UNITS = 10000     # floor(1.25 cents) == 1 cent

DWELL_CRITICAL_MINUTES = 30
GROUP_BAND_LOW_MIN_SIZE = 5
GROUP_BAND_HIGH_MIN_SIZE = 10
GROUP_MULTIPLIER_LOW = 2
GROUP_MULTIPLIER_HIGH = 3
LONG_SLOT_MINUTES = 90
LONG_SLOT_SURCHARGE_MINUTES = 20

EVENT_BASE_MINUTES_PER_SEAT = D("0.5")
FREE_DEMO_FLAT_MINUTES = 15

STRIKE_DECAY_PER_QUARTER = D("0.5")
STRIKE_QUARTER_DAYS = 90
STRIKE_LIMIT = 3

SILVER_MIN = 8000
GOLD_MIN = 25000
PATRON_MIN = 60000
TIER_RETAIN_POINTS = {"BASE": 0, "SILVER": 500, "GOLD": 1500, "PATRON": 4000}

POINTS_PER_DOLLAR = 20
CENTS_PER_POINT = 5
MATCH_ANNUAL_CAP_CENTS = 500

SECONDS_PER_DAY = 86400

INTAKE_BASE_CENTS = {"TAXIDERMY": 45000, "OUTFITTING": 12000, "BOAT_SERVICE": 8000}
STAGE_UPLIFT_CENTS = {
    "INTAKE_QUOTED": 0, "PERMIT_VERIFIED": 0, "MATERIALS_ORDERED": 15000,
    "CURING": 25000, "READY_FOR_PICKUP": 25000,
}
SPECIMEN_UNIT_CENTS = 3500
INTAKE_STAGE_ORDER = [
    "INTAKE_QUOTED", "PERMIT_VERIFIED", "MATERIALS_ORDERED", "CURING",
    "READY_FOR_PICKUP", "RELEASED", "ABANDONED",
]
CURING_EXTRA_LEAD_DAYS = 21

WAIVER_REQUIRED_TYPES = {"FISHING_POND", "ARCHERY_RANGE", "SIMULATOR"}
WAIVER_SCOPE_BY_TYPE = {
    "FISHING_POND": "CATCH_AND_RELEASE_POND",
    "ARCHERY_RANGE": "ARCHERY_RANGE",
    "SIMULATOR": "SIMULATOR",
}


# ---------------------------------------------------------------------------
# boat_deal_contract_price
# ---------------------------------------------------------------------------
def is_provisional(deal):
    # §3.4: "Quoting computes the provisional contract price under the quote
    # variant ... Contracting ... The contract price is recomputed under the
    # contracted variant — the rigging fee restored and the full tier credit
    # applied", so the quote variant is the QUOTED reading only and the price
    # settles permanently once the deal is contracted.
    return deal.get("deal_stage") == "QUOTED"


def card_credit_bps(deal):
    member = get("members", deal.get("member_id"))
    status = member.get("club_card_status", "NONE") if member else "NONE"
    return TIER_CREDIT_BPS_BY_CARD_STATUS.get(status, 0)


def accepted_trade_credit(deal):
    """Accepted appraisal credit for this deal's member, or 0."""
    aid = deal.get("trade_in_appraisal_id")
    if not aid:
        return 0
    ap = get("appraisals", aid)
    if ap is None or ap["status"] != "ACCEPTED":
        return 0
    if ap.get("member_id") != deal.get("member_id"):
        return 0
    return int(ap.get("accepted_credit_cents", 0))


def boat_deal_contract_price(deal, variant=None):
    unit = get("boat_units", deal.get("boat_unit_id"))
    if unit is None:
        return 0
    hull = int(unit.get("unit_price_cents", 0) or 0)
    motor = int(unit.get("motor_price_cents", 0) or 0)
    trailer = int(unit.get("trailer_price_cents", 0) or 0)

    if variant is not None:
        provisional = (variant == "provisional_quote_price")
    else:
        provisional = is_provisional(deal)

    rigging_fee = 0 if provisional else RIGGING_FEE_CENTS
    base = hull + motor + trailer + rigging_fee

    acc_amt = min(motor + trailer, ACCESSORY_DISCOUNT_CAP_CENTS)
    acc_bps = ACCESSORY_DISCOUNT_BPS_NEW if unit.get("unit_condition") == "NEW" else ACCESSORY_DISCOUNT_BPS_USED
    acc_disc = rhu(D(acc_amt) * D(acc_bps) / D(10000))

    credit_bps = card_credit_bps(deal)
    if provisional:
        credit_bps = credit_bps // 2 if credit_bps % 2 == 0 else D(credit_bps) / D(2)
    tier_credit = rhu(D(base) * D(str(credit_bps)) / D(10000))
    trade_credit = min(accepted_trade_credit(deal), tier_credit)

    return max(FLOOR_PRICE_CENTS, base - acc_disc - trade_credit)


def deal_title_fee(deal):
    fid = deal.get("title_filing_id")
    filing = get("title_filings", fid) if fid else None
    if filing is not None and filing.get("filing_kind") == "BOAT_TITLE":
        return TITLE_FEE_BOAT_CENTS
    if filing is not None:
        return TITLE_FEE_OTHER_CENTS
    return TITLE_FEE_OTHER_CENTS


def deal_fee_and_tax_relay(deal, basis=None):
    price = int(deal.get("contract_price_cents", 0) or 0)
    if basis is None:
        basis = "delivered_settlement" if deal.get("deal_stage") in ("DELIVERED", "SETTLED") else "contract_price"
    fee_base = price + (DELIVERY_PREP_CENTS if basis == "delivered_settlement" else 0)
    doc_fee = DOC_FEE_CENTS
    title_fee = deal_title_fee(deal)
    taxable = fee_base + doc_fee
    tax = rhu(D(taxable) * D(SALES_TAX_BPS) / D(10000))
    return doc_fee + title_fee + tax


def recompute_deal_money(deal, bump=True):
    """Recompute contract price, fees and balance for a deal."""
    deal["contract_price_cents"] = boat_deal_contract_price(deal)
    deal["total_fee_cents"] = deal_fee_and_tax_relay(deal)
    deal["balance_due_cents"] = (
        int(deal["contract_price_cents"])
        + int(deal["total_fee_cents"])
        - int(deal.get("funded_amount_cents", 0) or 0)
        - int(deal.get("deposit_cents", 0) or 0)
    )
    if bump:
        touch(deal)
    return deal


def delivery_settlement_variance(deal):
    provisional = boat_deal_contract_price(deal, variant="provisional_quote_price")
    final = boat_deal_contract_price(deal, variant="contracted_settlement_price")
    final += deal_fee_and_tax_relay(deal, basis="delivered_settlement")
    return final - provisional


def deal_list_value(deal):
    unit = get("boat_units", deal.get("boat_unit_id"))
    if unit is None:
        return 0
    return (int(unit.get("unit_price_cents", 0) or 0)
            + int(unit.get("motor_price_cents", 0) or 0)
            + int(unit.get("trailer_price_cents", 0) or 0))


def deal_points_award(deal):
    member = get("members", deal.get("member_id"))
    card_active = bool(member and member.get("club_card_status") == "ACTIVE")
    use_msrp = bool(deal.get("_contract_card_active"))
    p = deal_list_value(deal) if use_msrp else int(deal.get("contract_price_cents", 0) or 0)
    if p < POINTS_BAND_LOW_MAX_CENTS:
        band_bps = POINTS_BAND_BPS_LOW
    elif p < POINTS_BAND_MID_MAX_CENTS:
        band_bps = POINTS_BAND_BPS_MID
    else:
        band_bps = POINTS_BAND_BPS_HIGH
    points = rhu(D(p) * D(band_bps) / D(POINTS_BPS_DENOMINATOR))
    if card_active:
        points = rhu(D(points) * D(ACTIVE_CARD_MULTIPLIER))
    return min(points, POINTS_AWARD_CAP)


# ---------------------------------------------------------------------------
# trade_in_credit
# ---------------------------------------------------------------------------
def trade_in_credit(appraisal, unit=None, member=None):
    offer = int(appraisal.get("offer_amount_cents", 0) or 0)
    if member is None:
        member = get("members", appraisal.get("member_id"))
    if unit is None:
        unit = get("boat_units", appraisal.get("boat_unit_id"))
    rebate_bps = ACTIVE_CARD_REBATE_BPS if (member and member.get("club_card_status") == "ACTIVE") else 0
    title_penalty_bps = PRIOR_TITLE_PENALTY_BPS if (unit and unit.get("prior_title_no")) else 0
    rebate = rhu(D(offer) * D(rebate_bps) / D(10000))
    penalty = rhu(D(offer) * D(title_penalty_bps) / D(10000))
    return offer + rebate - penalty


# ---------------------------------------------------------------------------
# permit_fee
# ---------------------------------------------------------------------------
def term_bucket(term_days):
    if term_days <= 7:
        return "LE_7"
    if term_days <= 30:
        return "LE_30"
    if term_days <= 365:
        return "LE_365"
    return "GT_365"


def permit_fee(permit_type, residency_class, term_days, land_access_units, variant="exact_rational"):
    table = TIER_FEE_CENTS.get(permit_type, {})
    tier = table.get(residency_class)
    if tier is None:
        err("ERR_INVALID_REQUEST", "Unknown permit type or residency class.")
    step = TERM_BUCKET_STEP_BPS[term_bucket(int(term_days))]
    units = int(land_access_units)
    # Tier base is carried in units of 1e-4 cent (tier cents * step bps).
    base_units_1e4 = tier * step
    if variant == "per_unit_rounded":
        # The add-on is rounded per unit before summation: floor(1.25 cents)
        # == 1 cent == 10000 units of 1e-4 cent.
        addon_units_1e4 = units * LC_FLOOR_UNIT_UNITS
    else:
        addon_units_1e4 = units * LAND_ACCESS_UNIT_UNITS_1E4
    return rhu(D(base_units_1e4 + addon_units_1e4) / D(MICRO_CENTS_PER_CENT))


# ---------------------------------------------------------------------------
# attraction_posture  (§2.7)
# ---------------------------------------------------------------------------
def store_dwell_figures(store, checkpoint=False):
    committed = 0
    for s in DB.tables["sessions"].values():
        att = get("attractions", s.get("attraction_id"))
        if att is None or att.get("store_id") != store["id"]:
            continue
        if s.get("status") not in ("CONFIRMED", "IN_PROGRESS"):
            continue
        if checkpoint and s.get("slot_start_utc") is not None:
            start = _parse_iso(s["slot_start_utc"])
            if start is not None and start > now():
                continue
        committed += int(s.get("dwell_charge_minutes", 0) or 0)
    for o in DB.tables["event_offerings"].values():
        if o.get("store_id") != store["id"]:
            continue
        if o.get("status") != "PUBLISHED":
            continue
        committed += int(o.get("dwell_charge_minutes", 0) or 0)

    capacity = int(store.get("dwell_capacity_minutes", 0) or 0)
    free = capacity - committed

    over_capacity_venues = 0
    expired_waiver_venues = 0
    for att in DB.tables["attractions"].values():
        if att.get("store_id") != store["id"]:
            continue
        if int(att.get("in_use_units", 0) or 0) > int(att.get("capacity_units", 0) or 0):
            over_capacity_venues += 1
        if not att.get("requires_waiver"):
            continue
        if _has_expired_waiver_session(att, checkpoint):
            expired_waiver_venues += 1
    return {
        "dwell_capacity_minutes": capacity,
        "dwell_committed_minutes": committed,
        "dwell_free_minutes": free,
        "over_capacity_venues": over_capacity_venues,
        "expired_waiver_venues": expired_waiver_venues,
    }


def _has_expired_waiver_session(att, checkpoint=False):
    for s in DB.tables["sessions"].values():
        if s.get("attraction_id") != att["id"] or s.get("status") != "CONFIRMED":
            continue
        if checkpoint and s.get("slot_start_utc") is not None:
            start = _parse_iso(s["slot_start_utc"])
            if start is not None and start > now():
                continue
        w = get("waivers", s.get("waiver_id")) if s.get("waiver_id") else None
        if w is None or w.get("expires_on") is None:
            continue
        exp = _parse_iso(w["expires_on"])
        if exp is not None and exp < now():
            return True
    return False


def _parse_iso(value):
    from datetime import datetime, timezone
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def derive_posture(store, checkpoint=False):
    f = store_dwell_figures(store, checkpoint=checkpoint)
    if f["dwell_free_minutes"] < 0 or f["over_capacity_venues"] > 0:
        return "FROZEN", f
    if f["dwell_free_minutes"] < DWELL_CRITICAL_MINUTES or f["expired_waiver_venues"] > 0:
        return "RESTRICTED", f
    return "OPEN", f


def refresh_posture(store, checkpoint=False):
    posture, figures = derive_posture(store, checkpoint=checkpoint)
    store["dwell_committed_minutes"] = figures["dwell_committed_minutes"]
    store["dwell_free_minutes"] = figures["dwell_free_minutes"]
    store["attraction_posture"] = posture
    return posture


# ---------------------------------------------------------------------------
# attraction_dwell_charge
# ---------------------------------------------------------------------------
def attraction_dwell_charge(attraction, session):
    per_guest = int(attraction.get("dwell_cost_minutes", 0) or 0)
    size = int(session.get("party_size", 0) or 0)
    if size >= GROUP_BAND_HIGH_MIN_SIZE:
        mult = GROUP_MULTIPLIER_HIGH
    elif size >= GROUP_BAND_LOW_MIN_SIZE:
        mult = GROUP_MULTIPLIER_LOW
    else:
        mult = 1
    if session.get("session_kind") == "POND_CLINIC" and size < 3:
        mult = 1
    base = per_guest * mult
    start = _parse_iso(session.get("slot_start_utc"))
    end = _parse_iso(session.get("slot_end_utc"))
    surcharge = 0
    if start is not None and end is not None:
        if (end - start).total_seconds() > LONG_SLOT_MINUTES * 60:
            surcharge = LONG_SLOT_SURCHARGE_MINUTES
    return base + surcharge


# ---------------------------------------------------------------------------
# event_dwell_charge
# ---------------------------------------------------------------------------
def event_dwell_charge(offering):
    cap = int(offering.get("registration_cap", 0) or 0)
    if cap == 0:
        return FREE_DEMO_FLAT_MINUTES
    base_half = (cap + 1) // 2
    overflow = cap - base_half
    raw = (D(base_half) * EVENT_BASE_MINUTES_PER_SEAT
           + D(overflow) * EVENT_BASE_MINUTES_PER_SEAT * D(2))
    return rhu(raw)


# ---------------------------------------------------------------------------
# no_show_strike  (§1.3 / PRD §3.2)
# ---------------------------------------------------------------------------
def effective_strikes(member, attraction_id):
    epoch = _parse_iso(member.get("strike_epoch_started_at"))
    raw = 0
    for s in DB.tables["sessions"].values():
        if s.get("attraction_id") != attraction_id:
            continue
        if s.get("member_id") != member["id"]:
            continue
        if s.get("status") != "NO_SHOW":
            continue
        start = _parse_iso(s.get("slot_start_utc"))
        if epoch is not None and start is not None and start < epoch:
            continue
        raw += 1
    if epoch is None:
        return raw
    quarters = int((now() - epoch).total_seconds() // (STRIKE_QUARTER_DAYS * SECONDS_PER_DAY))
    decay = STRIKE_DECAY_PER_QUARTER * quarters
    return max(0, int(D(raw) - decay))


def refresh_strikes(member, attraction_id):
    value = effective_strikes(member, attraction_id)
    for s in DB.tables["sessions"].values():
        if s.get("attraction_id") == attraction_id and s.get("member_id") == member["id"]:
            if int(s.get("no_show_strikes", 0) or 0) != value:
                s["no_show_strikes"] = value
                touch(s)
    return value


# ---------------------------------------------------------------------------
# club_points_apply / tier_threshold_eval
# ---------------------------------------------------------------------------
def club_points_apply(member_id):
    rows = [e for e in DB.tables["point_events"].values() if e.get("member_id") == member_id]
    rows.sort(key=lambda e: (e.get("created_at") or "", int(e.get("created_seq", 0) or 0)))
    balance = 0
    lifetime = 0
    for ev in rows:
        kind = ev.get("event_kind")
        delta = int(ev.get("points_delta", 0) or 0)
        if kind in ("AWARD", "ADJUST"):
            balance += delta
            lifetime += delta
        elif kind == "REDEEM":
            balance -= abs(delta)
        elif kind == "REVERSAL":
            balance += delta
            lifetime -= abs(delta)
        balance = max(balance, 0)
        lifetime = max(lifetime, 0)
    return balance, lifetime


def tier_for_lifetime(lifetime):
    if lifetime >= PATRON_MIN:
        return "PATRON"
    if lifetime >= GOLD_MIN:
        return "GOLD"
    if lifetime >= SILVER_MIN:
        return "SILVER"
    return "BASE"


def tier_threshold_eval(member, bump=True):
    balance, lifetime = club_points_apply(member["id"])
    member["points_balance"] = balance
    member["points_lifetime_earned"] = lifetime
    tier = tier_for_lifetime(lifetime)
    member["club_tier"] = tier
    member["redeemable_points"] = max(0, balance - TIER_RETAIN_POINTS[tier])
    if bump:
        touch(member)
    return member


# ---------------------------------------------------------------------------
# conservation_match_accrue
# ---------------------------------------------------------------------------
def match_application_for(member):
    apps = [a for a in DB.tables["club_card_applications"].values()
            if a.get("member_id") == member["id"]]
    if not apps:
        return None
    live = [a for a in apps if a.get("status") in ("ACTIVATED", "APPROVED")]
    pool = live or apps
    pool.sort(key=lambda a: (a.get("created_at") or "", a.get("id")))
    return pool[-1]


def conservation_match_accrue(event, member):
    if event.get("event_kind") != "REDEEM":
        return 0
    if not member.get("donation_opt_in"):
        return 0
    if member.get("club_card_status") != "ACTIVE":
        return 0
    app = match_application_for(member)
    bps = int(app.get("donation_match_bps", 0) or 0) if app else 0
    matchable_cents = rhu(D(abs(int(event.get("points_delta", 0) or 0))) * D(100) / D(POINTS_PER_DOLLAR))
    proposed = rhu(D(matchable_cents) * D(bps) / D(10000))
    remaining = MATCH_ANNUAL_CAP_CENTS - int(member.get("conservation_match_cents", 0) or 0)
    if proposed > remaining:
        granted = max(remaining, 0)
    else:
        granted = proposed
    event["donation_match_cents"] = granted
    member["conservation_match_cents"] = int(member.get("conservation_match_cents", 0) or 0) + granted
    touch(member)
    return granted


# ---------------------------------------------------------------------------
# lead_time_actual
# ---------------------------------------------------------------------------
def lead_time_actual(order, endpoint=None, bump=True):
    started = _parse_iso(order.get("started_at_utc"))
    if started is None:
        return None
    end = endpoint
    if end is None and order.get("completed_at_utc"):
        end = _parse_iso(order["completed_at_utc"])
    projected = False
    if end is None:
        end = now()
        projected = True
    days = int((end - started).total_seconds() // SECONDS_PER_DAY)
    if bump:
        order["actual_lead_days"] = days
        order["is_late"] = days > int(order.get("promised_lead_days", 0) or 0)
        touch(order)
    return days


def projected_lead_days(order):
    started = _parse_iso(order.get("started_at_utc"))
    if started is None:
        return None
    return int((now() - started).total_seconds() // SECONDS_PER_DAY)


# ---------------------------------------------------------------------------
# intake_project_charge
# ---------------------------------------------------------------------------
def intake_project_charge(intake, stage):
    base = INTAKE_BASE_CENTS.get(intake.get("intake_kind"), 0)
    uplift = STAGE_UPLIFT_CENTS.get(stage, 0)
    at_or_after_curing = INTAKE_STAGE_ORDER.index(stage) >= INTAKE_STAGE_ORDER.index("CURING")
    specimen = int(intake.get("specimen_quantity", 0) or 0) * (SPECIMEN_UNIT_CENTS if at_or_after_curing else 0)
    charge = base + uplift + specimen
    return max(charge, int(intake.get("deposit_cents", 0) or 0))


# ---------------------------------------------------------------------------
# permit_remit_snapshot
# ---------------------------------------------------------------------------
def batch_window_sales(batch, fees_override=None):
    store_id = batch.get("store_id")
    start = _parse_iso(batch.get("window_start_utc"))
    end = _parse_iso(batch.get("window_end_utc"))
    out = []
    for s in DB.tables["permit_sales"].values():
        if s.get("store_id") != store_id:
            continue
        if s.get("status") not in ("ISSUED", "VOIDED", "REMITTED", "CORRECTED"):
            continue
        created = _parse_iso(s.get("created_at"))
        if start is not None and created is not None and created < start:
            continue
        if end is not None and created is not None and created >= end:
            continue
        out.append(s)
    return out


def permit_remit_snapshot(batch, frozen=None):
    if frozen is None:
        frozen = int(batch.get("gross_fee_cents", 0) or 0)
    live = 0
    for s in batch_window_sales(batch):
        live += int(s.get("fee_cents", 0) or 0)
    batch["gross_fee_cents"] = frozen
    batch["interpretative_gross_cents"] = live
    batch["remit_variance_cents"] = live - frozen
    return batch


# ---------------------------------------------------------------------------
# waiver_expiry
# ---------------------------------------------------------------------------
def waiver_expiry(signed_at, term_days):
    return signed_at + timedelta(days=int(term_days))