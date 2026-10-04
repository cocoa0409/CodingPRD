# Core business logic: lazy clock transitions, cachet, P&A reconciliation,
# participation waterfall, talent conflict detection.

from datetime import timedelta, timezone
from decimal import Decimal

from flask import request

import db
from errors import ApiError
from util import fmt_dt, now_utc, parse_dt, clock_dt, round_half_up_cents, touch

# --- enums ------------------------------------------------------------------

GENRES = {"DRAMA", "COMEDY", "HORROR", "DOCUMENTARY", "THRILLER"}
PRESTIGE_TIERS = {"A_LIST", "B_LIST", "REGIONAL"}
SECTIONS = {"COMPETITION", "MIDNIGHT", "PREMIERES", "NEXT"}
WINDOWS = {"THEATRICAL", "STREAMING", "HOME_ENT", "TV"}
STRATEGIES = {"LIMITED_4", "LIMITED_8", "WIDE_DIRECT"}
AWARDS_BODIES = {"OSCARS", "GOLDEN_GLOBES", "INDEPENDENT_SPIRIT", "BAFTA"}
SPEND_CATEGORIES = {"SCREENING", "GUILD_MAILER", "PUBLICITY", "TRAVEL", "EVENT"}
OBLIGATION_KINDS = {"TRAVEL", "PRESS_JUNKET", "SCREENING_QA", "AWARDS_SHOW", "PHOTO_SHOOT"}
BASES = {"GROSS_RECEIPTS", "NET_PROFITS"}

OFFER_TERMINAL = {"ACCEPTED", "REJECTED", "WITHDRAWN", "EXPIRED"}

PRESTIGE_POINTS = {"A_LIST": 100, "B_LIST": 60, "REGIONAL": 30}
SECTION_BONUS = {"COMPETITION": 40, "PREMIERES": 25, "MIDNIGHT": 15, "NEXT": 10}

CAP_PCT = {
    "SCREENING": Decimal("0.40"),
    "GUILD_MAILER": Decimal("0.25"),
    "PUBLICITY": Decimal("0.30"),
    "TRAVEL": Decimal("0.15"),
    "EVENT": Decimal("0.20"),
}
INDIE_TRAVEL_CAP_CENTS = 25000000

WIDE_SCREEN_THRESHOLD = 600
BREACH_PENALTY_CENTS = 0
TRAVEL_BUFFER_HOURS = 6
TEN_YEARS_DAYS = 365 * 10

DIST_FEE_PCT_GROSS = Decimal("0.15")
DIST_FEE_PCT_NET = Decimal("0.30")


# --- request body helpers ----------------------------------------------------

def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError("ERR_INVALID_REQUEST", "%s is required" % field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a non-empty string" % field)
    return v


def req_int(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError("ERR_INVALID_REQUEST", "%s is required" % field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    return v


def req_bool(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError("ERR_INVALID_REQUEST", "%s is required" % field)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean" % field)
    return v


def req_num(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError("ERR_INVALID_REQUEST", "%s is required" % field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a number" % field)
    return v


def req_list(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError("ERR_INVALID_REQUEST", "%s is required" % field)
    if not isinstance(v, list):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a list" % field)
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, sorted(allowed)))
    return v


def opt_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        return None
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, sorted(allowed)))
    return v


# --- existence helpers ---------------------------------------------------------

def get_or_404(store_name, rid, what):
    row = db.stores[store_name].get(rid)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "%s not found" % what)
    return row


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


# --- lazy clock-driven transitions ----------------------------------------------

def expire_offer(offer):
    """Flip OPEN offer to EXPIRED if expiry passed. Returns True if flipped."""
    if offer["status"] == "OPEN" and parse_dt(offer["expiry_at"]) < clock_dt():
        offer["status"] = "EXPIRED"
        touch(offer)
        _maybe_collapse_negotiation(offer["film_id"])
        return True
    return False


def refresh_offer(offer):
    expire_offer(offer)
    return offer


def _maybe_collapse_negotiation(film_id):
    """If no OPEN offers and no live deal, film UNDER_NEGOTIATION -> SHOPPING."""
    film = db.stores["films"].get(film_id)
    if film is None or film["acquisition_status"] != "UNDER_NEGOTIATION":
        return
    has_open = any(
        o["status"] == "OPEN"
        for o in db.stores["offers"].values()
        if o["film_id"] == film_id
    )
    if has_open:
        return
    has_live_deal = any(
        d["status"] in ("EXECUTED", "IN_RELEASE")
        for d in db.stores["deals"].values()
        if d["film_id"] == film_id
    )
    if has_live_deal:
        return
    film["acquisition_status"] = "SHOPPING"
    touch(film)


def breach_obligation(ob):
    """CONFIRMED obligation past window end -> BREACHED, with campaign penalty."""
    if ob["status"] != "CONFIRMED":
        return False
    # PRD: breach only when the clock has *passed* window_ends_at (strictly
    # greater); at exact equality the window has been *reached* and the
    # obligation is still fulfillable.
    if parse_dt(ob["window_ends_at"]) >= clock_dt():
        return False
    ob["status"] = "BREACHED"
    touch(ob)
    campaign_id = ob.get("campaign_id")
    if campaign_id:
        campaign = db.stores["awards_campaigns"].get(campaign_id)
        if campaign is not None and campaign["status"] == "ACTIVE":
            penalty = BREACH_PENALTY_CENTS
            old_pub = campaign["budget_publicity_cents"]
            reduction = min(old_pub, penalty)
            campaign["budget_publicity_cents"] = old_pub - reduction
            campaign["budget_remaining_cents"] += reduction
            touch(campaign)
    return True


def refresh_obligation(ob):
    breach_obligation(ob)
    return ob


def promote_home_window(film):
    """WIDE -> HOME_WINDOW when earliest GRANTED HOME_ENT window has opened."""
    if film["release_posture"] != "WIDE" or film["acquisition_status"] != "ACQUIRED":
        return False
    grants = [
        g for g in db.stores["rights_grants"].values()
        if g["window"] == "HOME_ENT" and g["status"] == "GRANTED"
    ]
    if not grants:
        return False
    # Scope to this film's deals
    film_deal_ids = {
        d["id"] for d in db.stores["deals"].values() if d["film_id"] == film["id"]
    }
    grants = [g for g in grants if g["deal_id"] in film_deal_ids]
    if not grants:
        return False
    earliest = min(parse_dt(g["window_starts_at"]) for g in grants)
    if earliest <= clock_dt():
        film["release_posture"] = "HOME_WINDOW"
        touch(film)
        return True
    return False


def refresh_film(film):
    promote_home_window(film)
    return film


def reevaluate_clock_transitions():
    """Run all lazy clock-dependent transitions. Called on clock advance."""
    for offer in list(db.stores["offers"].values()):
        expire_offer(offer)
    for ob in list(db.stores["talent_obligations"].values()):
        breach_obligation(ob)
    for film in list(db.stores["films"].values()):
        promote_home_window(film)


# --- premiere cachet --------------------------------------------------------------

def compute_cachet(slot, festival):
    base = PRESTIGE_POINTS[festival["prestige_tier"]]
    bonus = SECTION_BONUS[slot["section"]]
    ends = parse_dt(slot["screening_ends_at"])
    lifts = parse_dt(slot["review_embargo_lifts_at"])
    delay_seconds = (lifts - ends).total_seconds()
    delay_hours = int(delay_seconds // 3600)
    if delay_hours <= 12:
        mult = Decimal("1.25")
    elif delay_hours <= 48:
        mult = Decimal("1.00")
    else:
        mult = Decimal("0.75")
    return round_half_up_cents(Decimal(base + bonus) * mult)


# --- deal P&A reconciliation ----------------------------------------------------------

def recalc_deal_pa(deal):
    awards_total = 0
    for campaign in db.stores["awards_campaigns"].values():
        if campaign["deal_id"] != deal["id"]:
            continue
        for spend in db.stores["campaign_spends"].values():
            if spend["campaign_id"] == campaign["id"]:
                awards_total += spend["amount_cents"]
    deal["pa_spent_awards_cents"] = awards_total
    shortfall = deal["prints_advertising_commit_cents"] - (
        deal["pa_spent_theatrical_cents"] + awards_total
    )
    deal["pa_shortfall_cents"] = max(0, shortfall)
    touch(deal)


# --- release plan aggregates -------------------------------------------------------------

def recalc_plan(plan):
    gross = 0
    screens = 0
    for s in db.stores["market_screenings"].values():
        if s["release_plan_id"] == plan["id"] and s["status"] != "PULLED":
            gross += s["weekend_gross_cents"]
            screens += s["screen_count"]
    plan["cumulative_gross_cents"] = gross
    plan["current_screen_count"] = screens
    touch(plan)


# --- campaign budgets ------------------------------------------------------------------------

def recalc_campaign_budgets(campaign):
    screenings = mailers = publicity = 0
    total = 0
    for spend in db.stores["campaign_spends"].values():
        if spend["campaign_id"] != campaign["id"]:
            continue
        total += spend["amount_cents"]
        if spend["category"] == "SCREENING":
            screenings += spend["amount_cents"]
        elif spend["category"] == "GUILD_MAILER":
            mailers += spend["amount_cents"]
        elif spend["category"] == "PUBLICITY":
            publicity += spend["amount_cents"]
    campaign["budget_screenings_cents"] = screenings
    campaign["budget_mailers_cents"] = mailers
    campaign["budget_publicity_cents"] = publicity
    campaign["budget_remaining_cents"] = campaign["budget_total_cents"] - total
    touch(campaign)


# --- campaign eligible spend ------------------------------------------------------------

def compute_eligible_spend(campaign, category, amount_cents):
    eligible = amount_cents
    cap = round_half_up_cents(Decimal(campaign["budget_total_cents"]) * CAP_PCT[category])
    prior = sorted(
        (s for s in db.stores["campaign_spends"].values()
         if s["campaign_id"] == campaign["id"] and s["category"] == category),
        key=lambda s: (s["created_at"], s["id"]),
    )
    already = sum(s["eligible_amount_cents"] for s in prior)
    if already + eligible > cap:
        eligible = max(0, cap - already)
    if campaign["awards_body"] == "INDEPENDENT_SPIRIT" and category == "TRAVEL":
        eligible = min(eligible, INDIE_TRAVEL_CAP_CENTS)
    return eligible


# --- participation waterfall -------------------------------------------------------------

def compute_waterfall(film, deal, basis, gross_receipts_cents):
    g = Decimal(gross_receipts_cents)
    pct = Decimal(str(deal["backend_participation_pct"]))
    if basis == "GROSS_RECEIPTS":
        fee = round_half_up_cents(g * DIST_FEE_PCT_GROSS)
        recoup = 0
        participation = round_half_up_cents((Decimal(gross_receipts_cents) - Decimal(fee)) * pct)
    else:
        fee = round_half_up_cents(g * DIST_FEE_PCT_NET)
        awards_eligible_total = 0
        for campaign in db.stores["awards_campaigns"].values():
            if campaign["deal_id"] != deal["id"]:
                continue
            for spend in db.stores["campaign_spends"].values():
                if spend["campaign_id"] == campaign["id"]:
                    awards_eligible_total += spend["eligible_amount_cents"]
        recoup = (
            deal["upfront_price_cents"]
            + film["production_budget_cents"]
            + deal["pa_spent_theatrical_cents"]
            + awards_eligible_total
        )
        net = gross_receipts_cents - fee - recoup
        if net <= 0:
            participation = 0
        else:
            participation = round_half_up_cents(Decimal(net) * pct)
    return fee, recoup, participation


# --- talent conflict detection --------------------------------------------------------------

def _half_open_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def check_talent_conflicts(candidate):
    """Returns (error_id, conflicting_obligation_id) or (None, None)."""
    a_start = parse_dt(candidate["window_starts_at"])
    a_end = parse_dt(candidate["window_ends_at"])
    for other in db.stores["talent_obligations"].values():
        if other["id"] == candidate["id"]:
            continue
        if other["status"] != "CONFIRMED":
            continue
        if other["talent_name"] != candidate["talent_name"]:
            continue
        b_start = parse_dt(other["window_starts_at"])
        b_end = parse_dt(other["window_ends_at"])
        # Direct half-open overlap
        if _half_open_overlap(a_start, a_end, b_start, b_end):
            return "ERR_WINDOW_CONFLICT", other["id"]
        # Travel-buffer aggregate: same city only
        if other["city_code"] == candidate["city_code"]:
            if b_start >= a_end:
                gap = b_start - a_end
            elif a_start >= b_end:
                gap = a_start - b_end
            else:
                gap = timedelta(0)
            gap_seconds = max(0, gap.total_seconds())
            gap_hours = int(gap_seconds // 3600)
            if 0 < gap_hours < TRAVEL_BUFFER_HOURS:
                return "ERR_TRAVEL_BUFFER_VIOLATION", other["id"]
    return None, None
