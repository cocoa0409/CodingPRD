"""Shared business logic: resource factory, territory math, pricing, cascades."""
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, parse_iso, format_iso
from errors import (
    err_not_found, err_occupancy_cap, err_feature_not_entitled,
)

VENUE_TIERS = [(100, "T1", 500000), (500, "T2", 2000000)]
VENUE_T3_FEE = 6000000
MAX_MULTIVIEW_SESSIONS = 2


def new_id():
    return str(uuid.uuid4())


def new_resource(common=True):
    """Base field dict for a new resource."""
    r = {"id": new_id()}
    if common:
        r["created_at"] = db.clock.now_iso()
        r["updated_at"] = db.clock.now_iso()
        r["version"] = 1
    else:
        r["created_at"] = db.clock.now_iso()
    return r


def touch(res):
    """Refresh updated_at and bump version after a mutation."""
    res["updated_at"] = db.clock.now_iso()
    if "version" in res:
        res["version"] += 1


def get_or_404(store, key):
    res = store.get(key)
    if res is None:
        raise err_not_found()
    return res


# ---------------------------------------------------------------- markets
def resolve_market(zip_code):
    """Resolve a 5-digit ZIP to a Market.code via 3-digit prefix; None if unmapped."""
    prefix = zip_code[:3]
    for m in db.markets.values():
        if prefix in m["zip_prefixes"]:
            return m["code"]
    return None


# ---------------------------------------------------------------- weeks
def week_window(season, week_index):
    """Return (start, end_exclusive) datetimes for a 1-based week index."""
    start = parse_iso(season["season_start_date"]) + timedelta(days=7 * (week_index - 1))
    end = start + timedelta(days=7)
    return start, end


def week_index_for_instant(season, dt):
    """1-based season week containing dt, clamped to [1, regular_season_weeks]."""
    W = season["regular_season_weeks"]
    start = parse_iso(season["season_start_date"])
    idx = (dt - start).days // 7 + 1
    if idx < 1:
        idx = 1
    if idx > W:
        idx = W
    return idx


# ---------------------------------------------------------------- slates
def week_games(slate):
    """Games of the slate's (season, week), ordered kickoff_at then created_at."""
    games = [
        g for g in db.games.values()
        if g["season_id"] == slate["season_id"] and g["week_index"] == slate["week_index"]
    ]
    games.sort(key=lambda g: (g["kickoff_at"], g["created_at"]))
    return games


def package_game_ids(slate):
    """Package-eligible game ids: week games minus national selections,
    ordered kickoff_at then created_at."""
    national = set(slate["national_game_ids"])
    return [g["id"] for g in week_games(slate) if g["id"] not in national]


def recompute_slate_count(slate):
    """Recompute package_game_count from live inputs. Does not touch updated_at/version."""
    if slate["slate_status"] in ("FINALIZED", "LOCKED"):
        slate["package_game_count"] = len(slate["finalized_game_ids"])
    else:
        slate["package_game_count"] = len(package_game_ids(slate))


def find_slate(season_id, week_index):
    for s in db.week_slates.values():
        if s["season_id"] == season_id and s["week_index"] == week_index:
            return s
    return None


# ---------------------------------------------------------------- accounts / markets
def effective_market(account, device_market_code):
    """Dual-variant effective market selection (scaffold effective_market)."""
    if account["status"] == "SUSPENDED":
        return account["billing_market_code"]
    if device_market_code is not None:
        return device_market_code
    return account["billing_market_code"]


# ---------------------------------------------------------------- entitlements
def withdraw_entitlements(subscription, reason):
    """WITHDRAW all GRANTED entitlements under a subscription with the given reason."""
    for ent in db.game_entitlements.values():
        if ent["subscription_id"] == subscription["id"] and ent["status"] == "GRANTED":
            ent["status"] = "WITHDRAWN"
            ent["withdrawn_reason"] = reason
            touch(ent)


def sweep_national_selection(slate, game_id, action):
    """GameEntitlement sweep on a national-selection move.

    Add: GRANTED -> WITHDRAWN (NATIONAL_SELECTION) for the moved game under
    ACTIVE subscriptions of the slate's season.
    Remove: WITHDRAWN -> GRANTED (reason cleared) when the existing reason was
    NATIONAL_SELECTION; other withdrawal reasons untouched.
    """
    season_id = slate["season_id"]
    for sub in db.subscriptions.values():
        if sub["season_id"] != season_id or sub["status"] != "ACTIVE":
            continue
        for ent in db.game_entitlements.values():
            if ent["subscription_id"] != sub["id"] or ent["game_id"] != game_id:
                continue
            if action == "add":
                if ent["status"] == "GRANTED":
                    ent["status"] = "WITHDRAWN"
                    ent["withdrawn_reason"] = "NATIONAL_SELECTION"
                    touch(ent)
            else:  # remove
                if ent["status"] == "WITHDRAWN" and ent["withdrawn_reason"] == "NATIONAL_SELECTION":
                    ent["status"] = "GRANTED"
                    ent["withdrawn_reason"] = None
                    touch(ent)


# ---------------------------------------------------------------- cascades
def cascade_grant_end(grant):
    """Depth-4 cascade when a grant leaves ACTIVE (TERMINATED or EXPIRED)."""
    for season in db.seasons.values():
        if season["rights_grant_id"] != grant["id"]:
            continue
        if season["phase"] != "POST":
            season["phase"] = "POST"
            touch(season)
    for sub in db.subscriptions.values():
        season = db.seasons.get(sub["season_id"])
        if season is None or season["rights_grant_id"] != grant["id"]:
            continue
        if sub["status"] == "ACTIVE":
            sub["status"] = "CANCELLED"
            sub["cancelled_at"] = db.clock.now_iso()
            sub["entitlement_state"] = "REVOKED"
            touch(sub)
            withdraw_entitlements(sub, "ENTITLEMENT_REVOKED")
    # Venue licenses held by accounts of this distributor.
    # An account is linked to a grant via its subscriptions into seasons of
    # that grant. Commercial accounts cannot hold subscriptions, so a
    # venue-holding account with no subscription linkage to any other grant
    # operates under this grant's umbrella and is swept up as well.
    linked = {}
    for sub in db.subscriptions.values():
        season = db.seasons.get(sub["season_id"])
        if season:
            linked.setdefault(sub["account_id"], set()).add(season["rights_grant_id"])
    account_ids = {
        aid for aid, gids in linked.items() if grant["id"] in gids
    }
    for lic in db.venue_licenses.values():
        aid = lic["account_id"]
        if aid in account_ids or not linked.get(aid):
            account_ids.add(aid)
    for lic in db.venue_licenses.values():
        if lic["account_id"] in account_ids and lic["status"] != "REVOKED":
            lic["status"] = "REVOKED"
            touch(lic)


def cascade_season_post(season):
    """Season REGULAR->POST cascade."""
    for sub in db.subscriptions.values():
        if sub["season_id"] != season["id"] or sub["status"] != "ACTIVE":
            continue
        sub["status"] = "EXPIRED"
        touch(sub)
        withdraw_entitlements(sub, "ENTITLEMENT_REVOKED")


def run_auto_transitions():
    """Evaluate time-based auto-transitions against the logical clock."""
    now = db.clock.now()
    for grant in db.rights_grants.values():
        if grant["status"] == "ACTIVE":
            until = parse_iso(grant["effective_until"])
            if until is not None and now >= until:
                grant["status"] = "EXPIRED"
                touch(grant)
                cascade_grant_end(grant)
    for sv in db.student_verifications.values():
        if sv["status"] == "VERIFIED":
            vt = parse_iso(sv["valid_through"])
            if vt is not None and now >= vt:
                sv["status"] = "EXPIRED"
                touch(sv)


# ---------------------------------------------------------------- pricing
def _round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_charged_price(offer, season, purchase_week_index):
    """charged_price: student discount on full-season base BEFORE proration."""
    W = season["regular_season_weeks"]
    if offer["plan_tier"] == "STUDENT":
        tier_base = _round_half_up(
            Decimal(offer["base_price_cents"])
            * Decimal(100 - season["student_discount_pct"])
            / Decimal(100)
        )
    else:
        tier_base = offer["base_price_cents"]
    prorated = _round_half_up(
        Decimal(tier_base) * Decimal(W - purchase_week_index + 1) / Decimal(W)
    )
    return prorated


def weekly_value_cents(subscription, season):
    """Weekly value basis for the refund waterfall (remaining-weeks anchor)."""
    weeks_received = season["regular_season_weeks"] - subscription["purchase_week_index"] + 1
    if weeks_received <= 0:
        weeks_received = 1
    return _round_half_up(Decimal(subscription["price_charged_cents"]) / Decimal(weeks_received))


# ---------------------------------------------------------------- venue fees
def venue_fee(occupancy):
    """Derive (occupancy_tier, annual_fee_cents) from fire_code_occupancy."""
    if occupancy <= 100:
        return "T1", 500000
    if occupancy <= 500:
        return "T2", 2000000
    return "T3", 6000000


def venue_grant_cap(account):
    """Smallest max_commercial_occupancy_cap across grants that parent the
    account's activity. Commercial accounts can never hold subscriptions
    (ERR_ACCOUNT_KIND_MISMATCH), so subscription linkage alone would make the
    cap vacuous; when no subscription links the account to a grant, the cap of
    every grant in the system binds (the account operates under the platform's
    grant umbrella)."""
    caps = []
    for sub in db.subscriptions.values():
        if sub["account_id"] != account["id"]:
            continue
        season = db.seasons.get(sub["season_id"])
        if not season:
            continue
        grant = db.rights_grants.get(season["rights_grant_id"])
        if grant:
            caps.append(grant["max_commercial_occupancy_cap"])
    if not caps:
        caps = [g["max_commercial_occupancy_cap"] for g in db.rights_grants.values()]
    return min(caps) if caps else None


def enforce_occupancy_cap(occupancy, account):
    if occupancy is None or occupancy <= 0:
        raise err_occupancy_cap()
    cap = venue_grant_cap(account)
    if cap is not None and occupancy > cap:
        raise err_occupancy_cap()


# ---------------------------------------------------------------- territory checks
def compute_verdict(account, subscription, game, eff_market):
    """game_availability.per_subscriber_availability chain + override final step."""
    if subscription["entitlement_state"] != "ENABLED":
        verdict = "NO_ENTITLEMENT"
    else:
        slate = find_slate(game["season_id"], game["week_index"])
        if slate is not None and slate["slate_status"] in ("FINALIZED", "LOCKED"):
            if game["id"] not in slate["finalized_game_ids"]:
                verdict = "NOT_IN_PACKAGE"
            elif game["home_market_code"] == eff_market:
                verdict = "BLACKED_OUT"
            else:
                verdict = "AVAILABLE"
        elif slate is not None and slate["slate_status"] == "PRELIMINARY":
            if game["id"] in slate["national_game_ids"]:
                verdict = "NOT_IN_PACKAGE"
            elif game["home_market_code"] == eff_market:
                verdict = "BLACKED_OUT"
            else:
                verdict = "AVAILABLE"
        else:
            # No slate exists for the week: game cannot be in the package.
            verdict = "NOT_IN_PACKAGE"
    # EntitlementOverride (ACTIVE) forces AVAILABLE as the final step.
    for ov in db.entitlement_overrides.values():
        if (
            ov["account_id"] == account["id"]
            and ov["game_id"] == game["id"]
            and ov["status"] == "ACTIVE"
        ):
            verdict = "AVAILABLE"
            break
    return verdict


# ---------------------------------------------------------------- payments / activation
def append_payment(subscription, kind, amount_cents, reason=None):
    pay = new_resource(common=False)
    pay["subscription_id"] = subscription["id"]
    pay["kind"] = kind
    pay["amount_cents"] = amount_cents
    pay["reason"] = reason
    db.payments[pay["id"]] = pay
    return pay


def entitlement_fanout(subscription):
    """Create GRANTED GameEntitlement rows for every package-eligible game of
    every WeekSlate in the season, skipping games national-selected at
    creation time."""
    season_id = subscription["season_id"]
    slates = [s for s in db.week_slates.values() if s["season_id"] == season_id]
    for slate in slates:
        if slate["slate_status"] in ("FINALIZED", "LOCKED"):
            eligible = list(slate["finalized_game_ids"])
        else:
            eligible = package_game_ids(slate)
        for game_id in eligible:
            game = db.games.get(game_id)
            if game is None:
                continue
            ent = new_resource()
            ent["subscription_id"] = subscription["id"]
            ent["game_id"] = game_id
            ent["week_index"] = game["week_index"]
            ent["status"] = "GRANTED"
            ent["withdrawn_reason"] = None
            db.game_entitlements[ent["id"]] = ent


def multiview_check_eligibility(subscription):
    """Raise ERR_FEATURE_NOT_ENTITLED unless the subscription is multiview-eligible."""
    offer = db.offers.get(subscription["offer_id"])
    includes_multiview = offer["includes_multiview"] if offer else False
    if not (
        subscription["status"] == "ACTIVE"
        and subscription["entitlement_state"] == "ENABLED"
        and includes_multiview
    ):
        raise err_feature_not_entitled()


def active_multiview_sessions(account_id):
    """Active multiview sessions for the account, ordered by created_at ASC."""
    sessions = [
        s for s in db.multiview_sessions.values()
        if s["account_id"] == account_id and s["status"] == "ACTIVE"
    ]
    sessions.sort(key=lambda s: s["created_at"])
    return sessions
