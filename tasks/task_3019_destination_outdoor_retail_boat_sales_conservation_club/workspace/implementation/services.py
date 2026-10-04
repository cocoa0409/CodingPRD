"""Shared lookups, request-shape checking, allocation and the ops-run sweep."""
from decimal import Decimal

from core import (DB, ApiError, err, get, find, find_one, new_id, now, iso, norm_now,
                  parse_dt, touch, create_row, table)
import calc
from calc import _parse_iso, rhu, refresh_posture, refresh_strikes


# ---------------------------------------------------------------------------
# Request shape checking (priority 24). Records the first violation and keeps
# going with a safe default so that higher-priority checks can still run; the
# recorded violation is raised at its declared priority position.
# ---------------------------------------------------------------------------
class Shape:
    def __init__(self):
        self.error = None

    def _record(self, msg):
        if self.error is None:
            self.error = msg

    def required(self, body, name):
        if name not in body or body.get(name) is None:
            self._record("The required field '%s' is absent." % name)
            return None
        return body.get(name)

    def int(self, body, name, required=False, minimum=None):
        if name not in body or body.get(name) is None:
            if required:
                self._record("The required field '%s' is absent." % name)
            return None
        value = body.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            self._record("The field '%s' must be an integer." % name)
            return None
        if minimum is not None and value < minimum:
            self._record("The field '%s' must be at least %d." % (name, minimum))
        return value

    def str(self, body, name, required=False):
        if name not in body or body.get(name) is None:
            if required:
                self._record("The required field '%s' is absent." % name)
            return None
        value = body.get(name)
        if not isinstance(value, str):
            self._record("The field '%s' must be a string." % name)
            return None
        if required and value == "":
            self._record("The field '%s' must not be empty." % name)
        return value

    def enum(self, body, name, allowed, required=True):
        value = self.str(body, name, required=required)
        if value is None:
            return None
        if value not in allowed:
            self._record("The field '%s' has an invalid value." % name)
        return value

    def boolean(self, body, name, default=False):
        if name not in body or body.get(name) is None:
            return default
        value = body.get(name)
        if not isinstance(value, bool):
            self._record("The field '%s' must be a boolean." % name)
            return default
        return value

    def dt(self, body, name, required=False):
        if name not in body or body.get(name) is None:
            if required:
                self._record("The required field '%s' is absent." % name)
            return None
        try:
            return parse_dt(body.get(name), name)
        except ApiError:
            self._record("The field '%s' is not a valid ISO 8601 instant." % name)
            return None

    def raise_now(self):
        if self.error is not None:
            err("ERR_INVALID_REQUEST", self.error)


# ---------------------------------------------------------------------------
# Existence / ownership helpers
# ---------------------------------------------------------------------------
def require_store(store_id):
    row = DB.tables["stores"].get(store_id)
    if row is None:
        err("ERR_STORE_NOT_FOUND")
    return row


def require_row(table_name, rid, error_id="ERR_RESOURCE_NOT_FOUND"):
    if rid is None:
        return None
    row = DB.tables[table_name].get(rid)
    if row is None:
        err(error_id)
    return row


def softly(table_name, rid):
    if rid is None:
        return None
    return DB.tables[table_name].get(rid)


STORE_OF = {
    "members": lambda r: r.get("store_id"),
    "attractions": lambda r: r.get("store_id"),
    "sessions": lambda r: (softly("attractions", r.get("attraction_id")) or {}).get("store_id"),
    "boat_units": lambda r: r.get("store_id"),
    "appraisals": lambda r: r.get("store_id"),
    "service_orders": lambda r: r.get("store_id"),
    "title_filings": lambda r: r.get("store_id"),
    "boat_deals": lambda r: r.get("store_id"),
    "permit_sales": lambda r: r.get("store_id"),
    "remit_batches": lambda r: r.get("store_id"),
    "club_card_applications": lambda r: r.get("store_id"),
    "point_events": lambda r: r.get("store_id"),
    "event_offerings": lambda r: r.get("store_id"),
    "event_registrations": lambda r: (softly("event_offerings", r.get("event_offering_id")) or {}).get("store_id"),
    "bay_bookings": lambda r: r.get("store_id"),
    "order_fulfillments": lambda r: r.get("store_id"),
    "service_intakes": lambda r: r.get("store_id"),
    "waivers": lambda r: r.get("store_id"),
}


def ensure_belongs(table_name, row, store_id):
    """Priority 5: the named child must belong to the store in the path."""
    if row is None:
        return row
    owner = STORE_OF.get(table_name, lambda r: r.get("store_id"))(row)
    if owner != store_id:
        err("ERR_PARENT_MISMATCH")
    return row


def page(rows, limit, offset, sort_key=None):
    if sort_key is not None:
        rows = sorted(rows, key=sort_key)
    else:
        rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    total = len(rows)
    limit = 10 if limit is None else int(limit)
    offset = 0 if offset is None else int(offset)
    window = rows[offset:offset + limit]
    has_more = offset + limit < total
    return window, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}


def pagination_args(args):
    """limit defaults to 10 and is clamped to [1, 100]; offset defaults to 0."""
    limit = args.get("limit")
    offset = args.get("offset")
    limit = 10 if limit in (None, "") else int(limit)
    offset = 0 if offset in (None, "") else max(0, int(offset))
    limit = max(1, min(100, limit))
    return limit, offset


# ---------------------------------------------------------------------------
# Attraction session allocation
# ---------------------------------------------------------------------------
def overlapping(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


def confirm_session(session, attraction, store, shape=None, allow_restricted=False):
    """Apply the REQUESTED -> CONFIRMED allocation precondition set."""
    if attraction.get("status") != "OPEN":
        err("ERR_INVALID_STATE", "The venue is not OPEN.")
    _check_venue_capacity(session, attraction)
    _check_overlap(session, attraction)
    if not allow_restricted:
        if store.get("attraction_posture") == "FROZEN":
            err("ERR_POSTURE_FROZEN")
        if store.get("attraction_posture") == "RESTRICTED":
            err("ERR_POSTURE_RESTRICTED")
    session["status"] = "CONFIRMED"
    session["dwell_charge_minutes"] = calc.attraction_dwell_charge(attraction, session)
    attraction["in_use_units"] = int(attraction.get("in_use_units", 0) or 0) + int(session.get("party_size", 0) or 0)
    touch(attraction)
    refresh_posture(store)
    touch(store)


def _venue_capacity_ok(session, attraction):
    return (int(attraction.get("in_use_units", 0) or 0) + int(session.get("party_size", 0) or 0)
            <= int(attraction.get("capacity_units", 0) or 0))


def _check_venue_capacity(session, attraction):
    if not _venue_capacity_ok(session, attraction):
        err("ERR_VENUE_CAPACITY_EXCEEDED")


def _check_overlap(session, attraction):
    s_start = _parse_iso(session.get("slot_start_utc"))
    s_end = _parse_iso(session.get("slot_end_utc"))
    if s_start is None or s_end is None:
        return
    for other in DB.tables["sessions"].values():
        if other["id"] == session["id"]:
            continue
        if other.get("attraction_id") != attraction["id"]:
            continue
        if other.get("status") not in ("CONFIRMED", "IN_PROGRESS"):
            continue
        o_start = _parse_iso(other.get("slot_start_utc"))
        o_end = _parse_iso(other.get("slot_end_utc"))
        if o_start is None or o_end is None:
            continue
        if not overlapping(s_start, s_end, o_start, o_end):
            continue
        if (int(other.get("party_size", 0) or 0) + int(session.get("party_size", 0) or 0)
                > int(attraction.get("capacity_units", 0) or 0)):
            err("ERR_SESSION_OVERLAP")


def release_session_capacity(session, attraction):
    attraction["in_use_units"] = max(
        0, int(attraction.get("in_use_units", 0) or 0) - int(session.get("party_size", 0) or 0))
    touch(attraction)


def reject_requested_siblings(store):
    """Sessions still REQUESTED after the store turned RESTRICTED are rejected."""
    if store.get("attraction_posture") != "RESTRICTED":
        return
    for s in list(DB.tables["sessions"].values()):
        if s.get("status") != "REQUESTED":
            continue
        att = softly("attractions", s.get("attraction_id"))
        if att is None or att.get("store_id") != store["id"]:
            continue
        s["status"] = "CANCELLED"
        touch(s)


# ---------------------------------------------------------------------------
# Points plumbing
# ---------------------------------------------------------------------------
def post_point_event(store_id, member, event_kind, points_delta, boat_deal_id=None,
                     allowance=None):
    event = create_row("point_events", {
        "member_id": member["id"],
        "store_id": store_id,
        "boat_deal_id": boat_deal_id,
        "event_kind": event_kind,
        "points_delta": int(points_delta),
        "donation_match_cents": 0,
        "created_seq": DB.next_seq(),
    }, version=0)
    calc.tier_threshold_eval(member)
    if event_kind == "REDEEM":
        calc.conservation_match_accrue(event, member)
        touch(event)
    touch(event)
    return event


def maybe_attach_pending_club_card(member, previous_tier):
    """A settlement-driven tier crossing attaches a pending club card application."""
    if member.get("club_tier") == previous_tier:
        return None
    if member.get("club_tier") == "BASE":
        return None
    if member.get("club_card_status") != "NONE":
        return None
    existing = find_one("club_card_applications",
                        lambda a: a.get("member_id") == member["id"]
                        and a.get("status") in ("PENDING", "UNDERWRITING", "APPROVED", "ACTIVATED"))
    if existing is not None:
        return None
    return create_row("club_card_applications", {
        "store_id": member.get("store_id"),
        "member_id": member["id"],
        "card_product": "CLASSIC",
        "donation_match_bps": 0,
        "underwriter_user_id": None,
        "decision_user_id": None,
        "decision_reason": None,
        "credit_limit_cents": 0,
        "status": "PENDING",
    })


# ---------------------------------------------------------------------------
# Boat deal cascades
# ---------------------------------------------------------------------------
def deal_rigging_complete(deal):
    if deal.get("deal_stage") != "CONTRACTED":
        return
    if deal.get("funding_status") == "FUNDED" and deal.get("title_status") == "ISSUED":
        auto_deliver(deal)


def deal_ready_to_deliver(deal):
    return (deal.get("deal_stage") == "CONTRACTED"
            and deal.get("funding_status") == "FUNDED"
            and deal.get("title_status") == "ISSUED"
            and deal.get("rigging_status") == "COMPLETE")


def auto_deliver(deal):
    """CONTRACTED -> DELIVERED. The fee relay is not re-run here: its declared
    triggers are the contract, funding and settlement transitions only, so the
    delivered basis is used by delivery_settlement_variance alone and the
    balance due is left where funding put it."""
    if not deal_ready_to_deliver(deal):
        return False
    unit = softly("boat_units", deal.get("boat_unit_id"))
    if unit is not None:
        unit["status"] = "SOLD"
        touch(unit)
    deal["deal_stage"] = "DELIVERED"
    deal["settlement_variance_cents"] = calc.delivery_settlement_variance(deal)
    store = softly("stores", deal.get("store_id"))
    if store is not None:
        touch(store)
    touch(deal)
    return True


def maybe_auto_deliver(deal):
    """Delivery is not client-requested: it fires on the next call made against
    the deal once funding, title and rigging have all landed."""
    if deal is None:
        return False
    return auto_deliver(deal)


def deal_auto_revert(deal):
    """A DELIVERED deal with no funded basis falls back to CONTRACTED."""
    if deal.get("deal_stage") != "DELIVERED":
        return
    if deal.get("funding_status") != "REFUNDED":
        return
    deal["deal_stage"] = "CONTRACTED"
    deal["settlement_variance_cents"] = 0
    calc.recompute_deal_money(deal)
    touch(deal)


def apply_deal_title_rejection(filing):
    """TitleFiling REJECTED -> the cyclic revert on the owning delivered deal."""
    if filing.get("filing_kind") != "BOAT_TITLE":
        return
    deal = find_one("boat_deals", lambda d: d.get("title_filing_id") == filing["id"])
    if deal is None:
        return
    if deal.get("deal_stage") != "DELIVERED":
        return
    deal["deal_stage"] = "CONTRACTED"
    deal["title_status"] = "NOT_STARTED"
    unit = softly("boat_units", deal.get("boat_unit_id"))
    if unit is not None:
        unit["status"] = "DEAL_PENDING"
        touch(unit)
    for order in DB.tables["service_orders"].values():
        if order.get("boat_unit_id") == deal.get("boat_unit_id") \
                and order.get("order_kind") == "RIGGING" and order.get("status") == "DELIVERED":
            order["status"] = "COMPLETED"
            touch(order)
            deal["rigging_status"] = "SCHEDULED"
    deal["settlement_variance_cents"] = 0
    calc.recompute_deal_money(deal)
    store = softly("stores", deal.get("store_id"))
    if store is not None:
        touch(store)
    touch(deal)


# ---------------------------------------------------------------------------
# Ops-run checkpoint
# ---------------------------------------------------------------------------
def ops_run(store):
    result = {
        "promoted_sessions": 0,
        "promoted_registrations": 0,
        "expired_waivers": 0,
    }
    store["permit_remit_epoch"] = int(store.get("permit_remit_epoch", 0) or 0) + 1
    store["last_ops_run_at"] = iso(norm_now())
    touch(store)

    # 1. expire overdue waivers
    for w in DB.tables["waivers"].values():
        if w.get("store_id") != store["id"] or w.get("status") != "SIGNED":
            continue
        exp = _parse_iso(w.get("expires_on"))
        if exp is not None and exp < now():
            w["status"] = "EXPIRED"
            touch(w)
            result["expired_waivers"] += 1

    # 2. no-shows for occupancy whose slot ended unchecked
    for s in list(DB.tables["sessions"].values()):
        att = softly("attractions", s.get("attraction_id"))
        if att is None or att.get("store_id") != store["id"]:
            continue
        if s.get("status") not in ("CONFIRMED", "IN_PROGRESS"):
            continue
        end = _parse_iso(s.get("slot_end_utc"))
        if end is None or end >= now():
            continue
        s["status"] = "NO_SHOW"
        release_session_capacity(s, att)
        member = softly("members", s.get("member_id"))
        if member is not None:
            refresh_strikes(member, att["id"])
        touch(s)

    # 3. promote or cancel parked sessions
    refresh_posture(store)
    parked = sorted(
        [s for s in DB.tables["sessions"].values() if s.get("status") == "WAITLIST_FALLBACK"],
        key=lambda s: (s.get("created_at") or "", s.get("id") or ""))
    for s in parked:
        att = softly("attractions", s.get("attraction_id"))
        if att is None or att.get("store_id") != store["id"]:
            continue
        start = _parse_iso(s.get("slot_start_utc"))
        if store.get("attraction_posture") == "FROZEN" or (start is not None and start < now()):
            s["status"] = "CANCELLED"
            touch(s)
            continue
        if store.get("attraction_posture") != "OPEN":
            continue
        if not _venue_capacity_ok(s, att):
            continue
        s_start = _parse_iso(s.get("slot_start_utc"))
        s_end = _parse_iso(s.get("slot_end_utc"))
        blocked = False
        for other in parked:
            if other["id"] == s["id"] or other.get("status") != "WAITLIST_FALLBACK":
                continue
            if other.get("attraction_id") != att["id"]:
                continue
            o_key = (other.get("created_at") or "", other.get("id") or "")
            if o_key >= (s.get("created_at") or "", s.get("id") or ""):
                continue
            o_start = _parse_iso(other.get("slot_start_utc"))
            o_end = _parse_iso(other.get("slot_end_utc"))
            if o_start is None or o_end is None or s_start is None or s_end is None:
                continue
            if overlapping(s_start, s_end, o_start, o_end):
                blocked = True
                break
        if blocked:
            continue
        s["status"] = "CONFIRMED"
        att["in_use_units"] = int(att.get("in_use_units", 0) or 0) + int(s.get("party_size", 0) or 0)
        touch(att)
        touch(s)
        result["promoted_sessions"] += 1
        refresh_posture(store)

    # 4. promote parked event registrations
    waiting = sorted(
        [r for r in DB.tables["event_registrations"].values() if r.get("status") == "WAITLISTED"],
        key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    for reg in waiting:
        offering = softly("event_offerings", reg.get("event_offering_id"))
        if offering is None or offering.get("store_id") != store["id"]:
            continue
        cap = int(offering.get("registration_cap", 0) or 0)
        seats = int(reg.get("seats", 0) or 0)
        if int(offering.get("confirmed_count", 0) or 0) + seats > cap:
            continue
        earlier = False
        for other in waiting:
            if other["id"] == reg["id"] or other.get("status") != "WAITLISTED":
                continue
            if other.get("event_offering_id") != offering["id"]:
                continue
            o_key = (other.get("created_at") or "", other.get("id") or "")
            if o_key < (reg.get("created_at") or "", reg.get("id") or ""):
                earlier = True
                break
        if earlier:
            continue
        reg["status"] = "CONFIRMED"
        offering["confirmed_count"] = int(offering.get("confirmed_count", 0) or 0) + seats
        touch(offering)
        touch(reg)
        result["promoted_registrations"] += 1

    # 5. complete finished events
    for offering in DB.tables["event_offerings"].values():
        if offering.get("store_id") != store["id"] or offering.get("status") != "PUBLISHED":
            continue
        end = _parse_iso(offering.get("ends_at_utc"))
        if end is None or end >= now():
            continue
        complete_event_offering(offering)

    # 6. abandon stale intakes
    for intake in DB.tables["service_intakes"].values():
        if intake.get("store_id") != store["id"] or intake.get("status") != "READY_FOR_PICKUP":
            continue
        order = softly("service_orders", intake.get("service_order_id"))
        if order is None or not order.get("completed_at_utc"):
            continue
        done = _parse_iso(order.get("completed_at_utc"))
        if done is None:
            continue
        if (now() - done).total_seconds() > 90 * 86400:
            intake["status"] = "ABANDONED"
            touch(intake)

    # 7. projected lead-time readings for in-flight orders
    for order in DB.tables["service_orders"].values():
        if order.get("store_id") != store["id"] or order.get("status") != "IN_PROGRESS":
            continue
        calc.lead_time_actual(order, endpoint=now())

    # 8. re-derive the posture
    refresh_posture(store)
    result["permit_remit_epoch"] = int(store.get("permit_remit_epoch", 0) or 0)
    result["posture"] = store.get("attraction_posture")
    return result


def complete_event_offering(offering):
    offering["status"] = "COMPLETED"
    for reg in DB.tables["event_registrations"].values():
        if reg.get("event_offering_id") != offering["id"]:
            continue
        if reg.get("status") != "CONFIRMED":
            continue
        if reg.get("attendance_marked"):
            reg["status"] = "ATTENDED"
            member = softly("members", reg.get("member_id"))
            if member is not None and int(reg.get("seats", 0) or 0) >= 1:
                post_point_event(offering.get("store_id"), member, "AWARD", 100)
        else:
            reg["status"] = "CANCELLED"
        touch(reg)
    offering["confirmed_count"] = 0
    touch(offering)
    store = softly("stores", offering.get("store_id"))
    if store is not None:
        refresh_posture(store)
        touch(store)


def cancel_event_offering(offering):
    offering["status"] = "CANCELLED"
    for reg in DB.tables["event_registrations"].values():
        if reg.get("event_offering_id") != offering["id"]:
            continue
        if reg.get("status") not in ("REGISTERED", "CONFIRMED", "WAITLISTED"):
            continue
        reg["status"] = "CANCELLED"
        member = softly("members", reg.get("member_id"))
        if member is not None and int(reg.get("seats", 0) or 0) >= 2:
            post_point_event(offering.get("store_id"), member, "ADJUST", 250)
        touch(reg)
    offering["confirmed_count"] = 0
    touch(offering)
    store = softly("stores", offering.get("store_id"))
    if store is not None:
        refresh_posture(store)
        touch(store)