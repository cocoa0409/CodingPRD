"""Business logic: calculations, state machines, cascades."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, new_entity, touch, iso_from_dt
from errors import (
    ApiError,
    ERR_CLUB_NOT_FOUND,
    ERR_MEMBER_NOT_FOUND,
    ERR_CATALOG_ITEM_NOT_FOUND,
    ERR_OFFER_NOT_FOUND,
    ERR_SCAN_SESSION_NOT_FOUND,
    ERR_SCAN_LINE_NOT_FOUND,
    ERR_INTERCEPT_NOT_FOUND,
    ERR_EXIT_VERIFICATION_NOT_FOUND,
    ERR_LP_CASE_NOT_FOUND,
    ERR_CURBSIDE_ORDER_NOT_FOUND,
    ERR_INVALID_REQUEST,
)

LB_GRAMS = 454
REWARD_RATE = 2

# States that still block a new session for the same member at the same club.
# Only the still-active shopping states do: OPEN, REVIEW_HOLD, OFFLINE_PAUSED.
# Once a session has been paid (PAID), is at the exit door (EXIT_PENDING), or
# has been stopped by loss prevention (FLAGGED), the member's in-store shopping
# for that visit is over and they may start a fresh session; EXITED, ABANDONED,
# and VOIDED are terminal in every sense.
SESSION_TERMINAL = {"PAID", "EXIT_PENDING", "FLAGGED", "EXITED", "ABANDONED", "VOIDED"}
SESSION_SCANNABLE = {"OPEN", "REVIEW_HOLD", "OFFLINE_PAUSED"}
RESTRICTED_CLASSES = {"ALCOHOL", "TOBACCO", "PHARMACY"}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def parse_iso(value, field="timestamp"):
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 string.", 400)
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is not a valid ISO 8601 timestamp.", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_items(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def get_club(cid):
    club = STORE.clubs.get(cid)
    if not club:
        raise ApiError(ERR_CLUB_NOT_FOUND, "Club id does not exist.", 404)
    return club


def get_member(mid):
    m = STORE.members.get(mid)
    if not m:
        raise ApiError(ERR_MEMBER_NOT_FOUND, "Member id does not exist.", 404)
    return m


def get_catalog_item(iid):
    it = STORE.catalog_items.get(iid)
    if not it:
        raise ApiError(ERR_CATALOG_ITEM_NOT_FOUND, "Catalog item id does not exist.", 404)
    return it


def get_offer(oid):
    o = STORE.offers.get(oid)
    if not o:
        raise ApiError(ERR_OFFER_NOT_FOUND, "Instant savings offer id does not exist.", 404)
    return o


def get_session(sid):
    s = STORE.sessions.get(sid)
    if not s:
        raise ApiError(ERR_SCAN_SESSION_NOT_FOUND, "Scan session id does not exist.", 404)
    return s


def get_scan_line(lid):
    l = STORE.scan_lines.get(lid)
    if not l:
        raise ApiError(ERR_SCAN_LINE_NOT_FOUND, "Scan line id does not exist.", 404)
    return l


def get_intercept(iid):
    i = STORE.intercepts.get(iid)
    if not i:
        raise ApiError(ERR_INTERCEPT_NOT_FOUND, "Restricted intercept id does not exist.", 404)
    return i


def get_verification(vid):
    v = STORE.exit_verifications.get(vid)
    if not v:
        raise ApiError(ERR_EXIT_VERIFICATION_NOT_FOUND, "Exit verification id does not exist.", 404)
    return v


def get_lp_case(cid):
    c = STORE.lp_cases.get(cid)
    if not c:
        raise ApiError(ERR_LP_CASE_NOT_FOUND, "Loss prevention case id does not exist.", 404)
    return c


def get_curbside_order(oid):
    o = STORE.curbside_orders.get(oid)
    if not o:
        raise ApiError(ERR_CURBSIDE_ORDER_NOT_FOUND, "Curbside order id does not exist.", 404)
    return o


# ---------------------------------------------------------------------------
# Time gates
# ---------------------------------------------------------------------------

def minute_of_day():
    now = STORE.now()
    return now.hour * 60 + now.minute


def shopping_window(club):
    """Returns 'NORMAL', 'EARLY', or 'CLOSED' for the current logical clock."""
    m = minute_of_day()
    if m >= club["open_minute"]:
        return "NORMAL"
    if m >= club["early_shopping_start_minute"]:
        return "EARLY"
    return "CLOSED"


# ---------------------------------------------------------------------------
# Pricing calculations
# ---------------------------------------------------------------------------

def commenced_pounds(weight_grams):
    return (weight_grams + LB_GRAMS - 1) // LB_GRAMS


def compute_gross(pricing_mode, unit_price_cents, price_per_pound_cents, quantity, weight_grams):
    if pricing_mode == "UNIT":
        return quantity * unit_price_cents
    # WEIGHTED: round_half_up(weight_grams * price_per_pound_cents / 454), per line
    raw = Decimal(weight_grams * price_per_pound_cents) / Decimal(LB_GRAMS)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def find_applicable_offer(club_id, catalog_item_id):
    now = STORE.now()
    for o in STORE.offers.values():
        if o["club_id"] != club_id or o["catalog_item_id"] != catalog_item_id:
            continue
        if parse_iso(o["valid_from_iso"]) <= now <= parse_iso(o["valid_to_iso"]):
            return o
    return None


def redeemed_units(offer_id, member_id, exclude_line_id=None):
    total = 0
    for line in STORE.scan_lines.values():
        if line["offer_id_applied"] != offer_id:
            continue
        if line["status"] == "REMOVED":
            continue
        if exclude_line_id is not None and line["id"] == exclude_line_id:
            continue
        session = STORE.sessions.get(line["session_id"])
        if not session or session["member_id"] != member_id:
            continue
        if session["status"] == "VOIDED":
            continue
        total += line["offer_units_applied"]
    return total


def evaluate_offer(club, member, catalog_item_id, pricing_mode, quantity, weight_grams,
                   exclude_line_id=None):
    """Returns (offer_id_applied, offer_units_applied, line_savings_cents)."""
    if club["connectivity_posture"] != "ONLINE":
        return None, 0, 0
    offer = find_applicable_offer(club["id"], catalog_item_id)
    if not offer:
        return None, 0, 0
    if offer["tier_eligibility"] == "PLUS_ONLY" and member["tier"] != "PLUS":
        return None, 0, 0
    redeemed = redeemed_units(offer["id"], member["id"], exclude_line_id=exclude_line_id)
    line_units = quantity if pricing_mode == "UNIT" else commenced_pounds(weight_grams)
    applied = min(offer["per_member_limit"] - redeemed, line_units)
    if applied < 0:
        applied = 0
    savings = applied * offer["discount_cents"]
    return offer["id"], applied, savings


def session_lines(session_id, include_removed=False):
    out = []
    for line in STORE.scan_lines.values():
        if line["session_id"] != session_id:
            continue
        if not include_removed and line["status"] == "REMOVED":
            continue
        out.append(line)
    return out


def recompute_session(session):
    lines = session_lines(session["id"])
    session["provisional_total_cents"] = sum(l["line_total_cents"] for l in lines)
    count = 0
    for l in lines:
        if l["pricing_mode_snapshot"] == "UNIT":
            count += l["quantity"]
        else:
            count += 1
    session["scanned_item_count"] = count


def pending_intercepts(session_id):
    return [i for i in STORE.intercepts.values()
            if i["session_id"] == session_id and i["status"] == "PENDING"]


# ---------------------------------------------------------------------------
# Intercept lifecycle
# ---------------------------------------------------------------------------

def reopen_session_if_clear(session):
    if session["status"] == "REVIEW_HOLD" and not pending_intercepts(session["id"]):
        session["status"] = "OPEN"


def deny_intercept(intercept, new_status):
    """Shared cascade for DENIED / EXPIRED intercepts."""
    intercept["status"] = new_status
    touch(intercept)
    line = STORE.scan_lines[intercept["scan_line_id"]]
    if line["status"] == "INTERCEPTED":
        line["status"] = "REMOVED"
        touch(line)
    session = STORE.sessions[intercept["session_id"]]
    recompute_session(session)
    reopen_session_if_clear(session)
    touch(session)


# ---------------------------------------------------------------------------
# Loss prevention
# ---------------------------------------------------------------------------

def open_lp_case(session, source, unscanned_count, flagging_associate_id):
    club = STORE.clubs[session["club_id"]]
    member = STORE.members[session["member_id"]]
    tier = "SEVERE" if unscanned_count >= 2 * club["lp_unscanned_threshold"] else "REVIEW"
    case = new_entity()
    case.update({
        "session_id": session["id"],
        "member_id": session["member_id"],
        "club_id": session["club_id"],
        "source": source,
        "unscanned_count": unscanned_count,
        "tier": tier,
        "flagging_associate_id": flagging_associate_id,
        "outcome": None,
        "status": "OPEN",
    })
    STORE.lp_cases[case["id"]] = case
    member["unscanned_strikes"] += 1
    if member["unscanned_strikes"] >= club["lp_suspend_strikes"]:
        member["status"] = "SUSPENDED"
    touch(member)
    return case


# ---------------------------------------------------------------------------
# Payment re-pricing
# ---------------------------------------------------------------------------

def reprice_line_at_pay(line, club, member):
    """Returns pay-time line_total_cents for a non-REMOVED line using current
    catalog prices and pay-time offer evaluation."""
    item = STORE.catalog_items.get(line["catalog_item_id"])
    if line["pricing_mode_snapshot"] == "UNIT":
        unit_price = item["unit_price_cents"] if item else line["unit_price_cents_snapshot"]
        gross = compute_gross("UNIT", unit_price, None, line["quantity"], None)
        offer_id, applied, savings = evaluate_offer(
            club, member, line["catalog_item_id"], "UNIT", line["quantity"], None,
            exclude_line_id=line["id"])
    else:
        ppp = item["price_per_pound_cents"] if item else line["price_per_pound_cents_snapshot"]
        gross = compute_gross("WEIGHTED", None, ppp, None, line["weight_grams"])
        offer_id, applied, savings = evaluate_offer(
            club, member, line["catalog_item_id"], "WEIGHTED", None, line["weight_grams"],
            exclude_line_id=line["id"])
    return max(0, gross - savings)


# ---------------------------------------------------------------------------
# Closeout sweep
# ---------------------------------------------------------------------------

def run_closeout(club):
    now = STORE.now()

    # Pass 1: expire stale PENDING intercepts at this club.
    for intercept in list(STORE.intercepts.values()):
        if intercept["club_id"] != club["id"] or intercept["status"] != "PENDING":
            continue
        created = parse_iso(intercept["created_at"])
        if created + timedelta(minutes=club["intercept_ttl_minutes"]) < now:
            deny_intercept(intercept, "EXPIRED")

    # Pass 2: expire receipt codes past TTL on EXIT_PENDING sessions.
    for session in list(STORE.sessions.values()):
        if session["club_id"] != club["id"] or session["status"] != "EXIT_PENDING":
            continue
        paid_at = parse_iso(session["paid_at"])
        if paid_at + timedelta(minutes=club["receipt_code_ttl_minutes"]) < now:
            for v in STORE.exit_verifications.values():
                if v["session_id"] == session["id"] and v["status"] == "PENDING":
                    v["status"] = "EXPIRED"
                    touch(v)
            session["status"] = "FLAGGED"
            touch(session)
            open_lp_case(session, "RECEIPT_EXPIRY", 0, None)

    # Pass 3: expire STAGED curbside orders past window_end + 60 minutes.
    for order in list(STORE.curbside_orders.values()):
        if order["club_id"] != club["id"] or order["status"] != "STAGED":
            continue
        window_end = parse_iso(order["window_end_iso"])
        if window_end + timedelta(minutes=60) < now:
            order["status"] = "EXPIRED"
            touch(order)


# ---------------------------------------------------------------------------
# Curbside slot occupancy (half-open windows)
# ---------------------------------------------------------------------------

def slot_occupancy(club_id, slot_label, window_start, window_end, exclude_order_id=None):
    count = 0
    for o in STORE.curbside_orders.values():
        if o["club_id"] != club_id:
            continue
        if o["status"] not in ("STAGING", "STAGED"):
            continue
        if o["staging_slot_label"] != slot_label:
            continue
        if exclude_order_id is not None and o["id"] == exclude_order_id:
            continue
        a_start = parse_iso(o["window_start_iso"])
        a_end = parse_iso(o["window_end_iso"])
        # Half-open overlap: a.start < W.end AND W.start < a.end
        if a_start < window_end and window_start < a_end:
            count += 1
    return count
