"""Store, member, attraction, session, waiver and event routes."""
from core import (DB, err, get, find, find_one, create_row, touch, iso, norm_now,
                  parse_dt, new_id, CLOCK)
import calc
from calc import _parse_iso, rhu
import services as S
from services import Shape, require_store, require_row, ensure_belongs, page, pagination_args
from app import route, ok, ok_list, created

ALL = None  # placeholder


# ---------------------------------------------------------------------------
# Platform: logical clock
# ---------------------------------------------------------------------------
@route("POST", "/_clock/set_current_utc", ["PlatformAdmin"])
def clock_set(ctx):
    body = ctx.body
    target = body.get("to_iso8601")
    if target is None or target == "":
        err("ERR_INVALID_REQUEST", "to_iso8601 is required.")
    CLOCK.set(target)
    return ok({"current_utc": iso(CLOCK.now)})


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
@route("POST", "/stores", ["PlatformAdmin"])
def store_create(ctx):
    body = ctx.body
    shape = Shape()
    name = shape.str(body, "name", required=True)
    state_code = shape.str(body, "state_code", required=True)
    dealer_license_no = shape.str(body, "dealer_license_no", required=True)
    dwell_capacity_minutes = shape.int(body, "dwell_capacity_minutes", required=True, minimum=0)
    load_bays_total = shape.int(body, "load_bays_total", required=True, minimum=0)
    shape.raise_now()
    row = create_row("stores", {
        "name": name,
        "state_code": state_code,
        "dealer_license_no": dealer_license_no,
        "dwell_capacity_minutes": dwell_capacity_minutes,
        "dwell_committed_minutes": 0,
        "dwell_free_minutes": dwell_capacity_minutes,
        "attraction_posture": "OPEN",
        "remit_ledger_cents": 0,
        "permit_remit_epoch": 0,
        "load_bays_total": load_bays_total,
        "last_ops_run_at": None,
    })
    return created(row)


@route("GET", "/stores/{store_id}", ["PlatformAdmin", "StoreManager", "Anonymous"])
def store_read(ctx):
    store = require_store(ctx.p("store_id"))
    calc.refresh_posture(store)
    return ok(store)


@route("GET", "/stores", ["PlatformAdmin", "StoreManager"])
def store_list(ctx):
    state_code = ctx.args.get("state_code")
    rows = list(DB.tables["stores"].values())
    if state_code:
        rows = [r for r in rows if r.get("state_code") == state_code]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("POST", "/stores/{store_id}/ops-run", ["PlatformAdmin", "StoreManager"])
def store_ops_run(ctx):
    store = require_store(ctx.p("store_id"))
    result = S.ops_run(store)
    return ok(result)


@route("GET", "/stores/{store_id}/dwell-summary",
       ["StoreManager", "PlatformAdmin", "EventsCoordinator"])
def store_dwell_summary(ctx):
    store = require_store(ctx.p("store_id"))
    figures = calc.store_dwell_figures(store)
    posture, _ = calc.derive_posture(store)
    return ok({
        "dwell_capacity_minutes": figures["dwell_capacity_minutes"],
        "dwell_committed_minutes": figures["dwell_committed_minutes"],
        "dwell_free_minutes": figures["dwell_free_minutes"],
        "attraction_posture": posture,
        "over_capacity_venues": figures["over_capacity_venues"],
        "expired_waiver_venues": figures["expired_waiver_venues"],
    })


# ---------------------------------------------------------------------------
# Member
# ---------------------------------------------------------------------------
@route("POST", "/stores/{store_id}/members",
       ["Anonymous", "StoreManager", "PermitClerk", "DealDeskClerk"])
def member_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    email = shape.str(body, "email", required=True)
    full_name = shape.str(body, "full_name", required=True)
    donation_opt_in = shape.boolean(body, "donation_opt_in", False)
    shape.raise_now()
    duplicate = find_one("members", lambda m: m.get("store_id") == store["id"]
                         and m.get("email") == email)
    if duplicate is not None:
        err("ERR_DUPLICATE_MEMBER_EMAIL")
    row = create_row("members", {
        "store_id": store["id"],
        "email": email,
        "full_name": full_name,
        "club_card_status": "NONE",
        "points_balance": 0,
        "points_lifetime_earned": 0,
        "club_tier": "BASE",
        "redeemable_points": 0,
        "conservation_match_cents": 0,
        "donation_opt_in": bool(donation_opt_in),
        # §3.2 names exactly two resets — completing a session at the attraction
        # and activating the club card — so a freshly enrolled member has no
        # recorded epoch and every no-show counts until one of those fires.
        "strike_epoch_started_at": None,
    })
    return created(row)


@route("GET", "/stores/members/{member_id}",
       ["StoreManager", "PlatformAdmin", "Member", "PermitClerk"])
def member_read(ctx):
    member = require_row("members", ctx.p("member_id"))
    _member_owns(ctx, member)
    calc.tier_threshold_eval(member, bump=False)
    return ok(member)


@route("GET", "/stores/members", ["StoreManager", "PlatformAdmin"])
def member_list(ctx):
    rows = list(DB.tables["members"].values())
    store_id = ctx.args.get("store_id")
    if store_id:
        rows = [r for r in rows if r.get("store_id") == store_id]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("PATCH", "/stores/members/{member_id}", ["StoreManager", "Member"])
def member_patch(ctx):
    member = require_row("members", ctx.p("member_id"))
    _member_owns(ctx, member)
    body = ctx.body
    if "full_name" in body:
        if not isinstance(body.get("full_name"), str):
            err("ERR_INVALID_REQUEST", "full_name must be a string.")
        member["full_name"] = body["full_name"]
    if "donation_opt_in" in body:
        if not isinstance(body.get("donation_opt_in"), bool):
            err("ERR_INVALID_REQUEST", "donation_opt_in must be a boolean.")
        member["donation_opt_in"] = body["donation_opt_in"]
    calc.tier_threshold_eval(member)
    return ok(member)


def _member_owns(ctx, member):
    """Ownership: the Member role may only act on their own record."""
    if ctx.role == "Member" and ctx.user_id != member["id"]:
        err("ERR_FORBIDDEN_ROLE")


# ---------------------------------------------------------------------------
# Attraction
# ---------------------------------------------------------------------------
@route("POST", "/stores/{store_id}/attractions", ["StoreManager"])
def attraction_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    attraction_type = shape.enum(body, "attraction_type", (
        "AQUARIUM", "MUSEUM", "FISHING_POND", "ARCHERY_RANGE", "SIMULATOR",
        "TAXIDERMY_GALLERY"))
    capacity_units = shape.int(body, "capacity_units", required=True, minimum=0)
    dwell_cost_minutes = shape.int(body, "dwell_cost_minutes", required=True, minimum=0)
    shape.raise_now()
    row = create_row("attractions", {
        "store_id": store["id"],
        "attraction_type": attraction_type,
        "capacity_units": capacity_units,
        "dwell_cost_minutes": dwell_cost_minutes,
        "requires_waiver": attraction_type in calc.WAIVER_REQUIRED_TYPES,
        "in_use_units": 0,
        "status": "PLANNED",
    })
    return created(row)


@route("GET", "/stores/attractions/{attraction_id}",
       ["StoreManager", "AttractionHost", "PlatformAdmin", "Anonymous"])
def attraction_read(ctx):
    row = require_row("attractions", ctx.p("attraction_id"))
    return ok(row)


@route("GET", "/stores/attractions", ["StoreManager", "AttractionHost", "PlatformAdmin"])
def attraction_list(ctx):
    rows = list(DB.tables["attractions"].values())
    store_id = ctx.args.get("store_id")
    attraction_type = ctx.args.get("attraction_type")
    status = ctx.args.get("status")
    if store_id:
        rows = [r for r in rows if r.get("store_id") == store_id]
    if attraction_type:
        rows = [r for r in rows if r.get("attraction_type") == attraction_type]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("POST", "/stores/attractions/{attraction_id}/open", ["StoreManager"])
def attraction_open(ctx):
    att = require_row("attractions", ctx.p("attraction_id"))
    if att.get("status") != "PLANNED":
        err("ERR_INVALID_STATE")
    att["status"] = "OPEN"
    touch(att)
    store = get("stores", att.get("store_id"))
    if store is not None:
        calc.refresh_posture(store)
        touch(store)
    return ok(att)


@route("GET", "/stores/attractions/{attraction_id}/sessions",
       ["StoreManager", "AttractionHost", "PlatformAdmin"])
def attraction_sessions(ctx):
    att = require_row("attractions", ctx.p("attraction_id"))
    rows = [s for s in DB.tables["sessions"].values() if s.get("attraction_id") == att["id"]]
    status = ctx.args.get("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


# ---------------------------------------------------------------------------
# LiabilityWaiver
# ---------------------------------------------------------------------------
@route("POST", "/stores/{store_id}/waivers", ["Member", "AttractionHost", "StoreManager"])
def waiver_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    member_id = shape.str(body, "member_id", required=True)
    activity_scope = shape.enum(body, "activity_scope", (
        "CATCH_AND_RELEASE_POND", "ARCHERY_RANGE", "SIMULATOR",
        "BOAT_DELIVERY_ORIENTATION"))
    signed_at = shape.dt(body, "signed_at_utc", required=True)
    term = shape.int(body, "waiver_term_days", minimum=0)
    shape.raise_now()
    member = require_row("members", member_id)
    if ctx.role == "Member" and ctx.user_id != member["id"]:
        err("ERR_FORBIDDEN_ROLE")
    term_days = 365 if term is None else term
    expires = calc.waiver_expiry(signed_at, term_days)
    for prior in DB.tables["waivers"].values():
        if prior.get("member_id") == member["id"] and prior.get("activity_scope") == activity_scope \
                and prior.get("status") == "SIGNED":
            prior["status"] = "SUPERSEDED"
            touch(prior)
    row = create_row("waivers", {
        "member_id": member["id"],
        "store_id": store["id"],
        "activity_scope": activity_scope,
        "signed_at_utc": iso(signed_at),
        "waiver_term_days": term_days,
        "expires_on": iso(expires),
        "status": "SIGNED",
    })
    return created(row)


@route("GET", "/stores/waivers/{waiver_id}",
       ["AttractionHost", "StoreManager", "PlatformAdmin", "Member"])
def waiver_read(ctx):
    return ok(require_row("waivers", ctx.p("waiver_id")))


@route("GET", "/stores/waivers", ["AttractionHost", "StoreManager", "PlatformAdmin"])
def waiver_list(ctx):
    rows = list(DB.tables["waivers"].values())
    for key, field in (("member_id", "member_id"), ("activity_scope", "activity_scope"),
                       ("store_id", "store_id")):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("GET", "/stores/waivers/{waiver_id}/sessions",
       ["AttractionHost", "StoreManager", "PlatformAdmin"])
def waiver_sessions(ctx):
    waiver = require_row("waivers", ctx.p("waiver_id"))
    rows = [s for s in DB.tables["sessions"].values() if s.get("waiver_id") == waiver["id"]]
    status = ctx.args.get("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("GET", "/stores/waivers/{waiver_id}/fulfillments",
       ["ReceivingManager", "StoreManager", "PlatformAdmin"])
def waiver_fulfillments(ctx):
    waiver = require_row("waivers", ctx.p("waiver_id"))
    rows = [f for f in DB.tables["order_fulfillments"].values() if f.get("waiver_id") == waiver["id"]]
    status = ctx.args.get("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


# ---------------------------------------------------------------------------
# AttractionSession
# ---------------------------------------------------------------------------
SESSION_KINDS = ("GENERAL_ADMISSION", "ARCHERY_LANE", "SIMULATOR", "POND_CLINIC")


@route("POST", "/stores/{store_id}/attraction-sessions",
       ["AttractionHost", "StoreManager", "Anonymous"])
def session_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    attraction_id = shape.str(body, "attraction_id", required=True)
    member_id = shape.str(body, "member_id", required=True)
    session_kind = shape.enum(body, "session_kind", SESSION_KINDS)
    party_size = shape.int(body, "party_size", required=True, minimum=0)
    slot_start = shape.dt(body, "slot_start_utc", required=True)
    slot_end = shape.dt(body, "slot_end_utc", required=True)
    waiver_id = shape.str(body, "waiver_id")
    lane_no = shape.int(body, "lane_no", minimum=0)

    attraction = None
    if attraction_id is not None:
        attraction = get("attractions", attraction_id)
        if attraction is None:
            shape.raise_now()
            err("ERR_RESOURCE_NOT_FOUND")
    member = require_row("members", member_id)
    if not shape.error and waiver_id is not None and get("waivers", waiver_id) is None:
        err("ERR_RESOURCE_NOT_FOUND")
    shape.raise_now()

    ensure_belongs("attractions", attraction, store["id"])

    # Only an OPEN venue will confirm a new session (p6 state layer).
    if attraction.get("status") != "OPEN":
        err("ERR_INVALID_STATE", "The venue is not OPEN.")

    # p14 malformed slot window
    if slot_end is None or slot_start is None or slot_end <= slot_start:
        err("ERR_INVALID_SLOT_WINDOW")

    # p8 posture gates
    posture = calc.refresh_posture(store)
    if posture == "FROZEN":
        err("ERR_POSTURE_FROZEN")

    # p9 waiver presence
    waiver = None
    if attraction.get("requires_waiver"):
        expected_scope = calc.WAIVER_SCOPE_BY_TYPE.get(attraction.get("attraction_type"))
        waiver = get("waivers", waiver_id) if waiver_id else None
        if waiver is None or waiver.get("activity_scope") != expected_scope \
                or waiver.get("member_id") != member["id"]:
            err("ERR_WAIVER_REQUIRED")

    # p10 waiver liveness + lane ceiling. §3.2: "A LiabilityWaiver ... must
    # have an expires_on instant at or after the store clock's current instant",
    # so a waiver lapsing exactly on the current instant is no longer live.
    if waiver is not None:
        expires = _parse_iso(waiver.get("expires_on"))
        if waiver.get("status") != "SIGNED" or expires is None or expires <= CLOCK.now:
            err("ERR_WAIVER_EXPIRED")
    if session_kind == "ARCHERY_LANE" and (lane_no is None or lane_no > 12):
        err("ERR_LANE_CAPACITY_EXCEEDED")
    if session_kind == "SIMULATOR" and (lane_no is None or lane_no > 6):
        err("ERR_LANE_CAPACITY_EXCEEDED")

    # p12 strike limit
    if calc.effective_strikes(member, attraction["id"]) >= calc.STRIKE_LIMIT:
        err("ERR_NO_SHOW_STRIKE_LIMIT")

    # p8 posture gate: a FROZEN store blocks any operation that moves an
    # attraction session toward CONFIRMED or IN_PROGRESS.
    if posture == "FROZEN":
        err("ERR_POSTURE_FROZEN")

    # p13 vs p17. PRD §3.1 renders both readings: "two parties may share a venue
    # only while their combined size stays within the venue's capacity", and an
    # "overlapping-interval collision that would breach capacity is reported with
    # ERR_SESSION_OVERLAP". So an interval that collides with a confirmed party
    # is judged on the shared capacity alone — the colliding pair fits and both
    # stand, or it does not and the collision is an overlap violation. Only a
    # request that collides with nobody falls to the aggregate venue measure,
    # where an overshoot parks in the waitlist while the store is OPEN.
    if _has_interval_collision(attraction, slot_start, slot_end):
        if _overlap_capacity_breach(attraction, slot_start, slot_end, party_size):
            err("ERR_SESSION_OVERLAP")
    elif _venue_capacity_overflow(attraction, party_size):
        if posture == "OPEN":
            return created(_park_session(attraction, member, waiver, session_kind,
                                         party_size, lane_no, slot_start, slot_end))
        err("ERR_VENUE_CAPACITY_EXCEEDED")

    if posture == "RESTRICTED":
        err("ERR_POSTURE_RESTRICTED")

    row = create_row("sessions", {
        "attraction_id": attraction["id"],
        "member_id": member["id"],
        "waiver_id": waiver["id"] if waiver is not None else None,
        "session_kind": session_kind,
        "party_size": party_size,
        "lane_no": lane_no,
        "slot_start_utc": iso(slot_start),
        "slot_end_utc": iso(slot_end),
        "dwell_charge_minutes": 0,
        "overrun_minutes": 0,
        "no_show_strikes": 0,
        "status": "CONFIRMED",
    }, version=0)
    row["no_show_strikes"] = calc.effective_strikes(member, attraction["id"])
    row["dwell_charge_minutes"] = calc.attraction_dwell_charge(attraction, row)
    attraction["in_use_units"] = int(attraction.get("in_use_units", 0) or 0) + party_size
    touch(attraction)
    calc.refresh_posture(store)
    S.reject_requested_siblings(store)
    touch(store)
    touch(row)
    return created(row)


def _park_session(attraction, member, waiver, session_kind, party_size, lane_no,
                  slot_start, slot_end):
    """A session parked from the OPEN posture: consumes nothing, pins its charge."""
    row = create_row("sessions", {
        "attraction_id": attraction["id"],
        "member_id": member["id"],
        "waiver_id": waiver["id"] if waiver is not None else None,
        "session_kind": session_kind,
        "party_size": party_size,
        "lane_no": lane_no,
        "slot_start_utc": iso(slot_start),
        "slot_end_utc": iso(slot_end),
        "dwell_charge_minutes": 0,
        "overrun_minutes": 0,
        "no_show_strikes": 0,
        "status": "WAITLIST_FALLBACK",
    }, version=0)
    row["no_show_strikes"] = calc.effective_strikes(member, attraction["id"])
    row["dwell_charge_minutes"] = calc.attraction_dwell_charge(attraction, row)
    touch(row)
    return row


def _venue_capacity_overflow(attraction, party_size):
    """The venue's current occupancy plus this party would exceed its cap."""
    return (int(attraction.get("in_use_units", 0) or 0) + int(party_size)
            > int(attraction.get("capacity_units", 0) or 0))


def _interval_collisions(attraction, slot_start, slot_end):
    """The venue's confirmed parties whose intervals overlap the request."""
    out = []
    for other in DB.tables["sessions"].values():
        if other.get("attraction_id") != attraction["id"]:
            continue
        if other.get("status") not in ("CONFIRMED", "IN_PROGRESS"):
            continue
        o_start = _parse_iso(other.get("slot_start_utc"))
        o_end = _parse_iso(other.get("slot_end_utc"))
        if o_start is None or o_end is None:
            continue
        if S.overlapping(slot_start, slot_end, o_start, o_end):
            out.append(other)
    return out


def _has_interval_collision(attraction, slot_start, slot_end):
    return bool(_interval_collisions(attraction, slot_start, slot_end))


def _overlap_capacity_breach(attraction, slot_start, slot_end, party_size):
    """A colliding confirmed party whose size the shared capacity cannot also
    hold alongside this one."""
    cap = int(attraction.get("capacity_units", 0) or 0)
    return any(int(other.get("party_size", 0) or 0) + int(party_size) > cap
               for other in _interval_collisions(attraction, slot_start, slot_end))


def _overlap_check(session, attraction):
    s_start = _parse_iso(session.get("slot_start_utc"))
    s_end = _parse_iso(session.get("slot_end_utc"))
    if s_start is None or s_end is None:
        return
    for other in DB.tables["sessions"].values():
        if other.get("id") == session.get("id"):
            continue
        if other.get("attraction_id") != attraction["id"]:
            continue
        if other.get("status") not in ("CONFIRMED", "IN_PROGRESS"):
            continue
        o_start = _parse_iso(other.get("slot_start_utc"))
        o_end = _parse_iso(other.get("slot_end_utc"))
        if o_start is None or o_end is None:
            continue
        if not S.overlapping(s_start, s_end, o_start, o_end):
            continue
        if (int(other.get("party_size", 0) or 0) + int(session.get("party_size", 0) or 0)
                > int(attraction.get("capacity_units", 0) or 0)):
            err("ERR_SESSION_OVERLAP")


@route("GET", "/stores/sessions/{session_id}",
       ["AttractionHost", "StoreManager", "PlatformAdmin", "Member"])
def session_read(ctx):
    return ok(require_row("sessions", ctx.p("session_id")))


@route("GET", "/stores/sessions", ["AttractionHost", "StoreManager", "PlatformAdmin"])
def session_list(ctx):
    rows = list(DB.tables["sessions"].values())
    for key, field in (("attraction_id", "attraction_id"), ("member_id", "member_id"),
                       ("waiver_id", "waiver_id"), ("status", "status")):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    store_id = ctx.args.get("store_id")
    if store_id:
        rows = [r for r in rows
                if (get("attractions", r.get("attraction_id")) or {}).get("store_id") == store_id]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


def _session_store(session):
    att = get("attractions", session.get("attraction_id"))
    if att is None:
        err("ERR_RESOURCE_NOT_FOUND")
    return att, get("stores", att.get("store_id"))


@route("POST", "/stores/attraction-sessions/{session_id}/check-in", ["AttractionHost"])
def session_check_in(ctx):
    session = require_row("sessions", ctx.p("session_id"))
    att, store = _session_store(session)
    if session.get("status") == "CANCELLED":
        err("ERR_ALREADY_TERMINAL")
    if session.get("status") != "CONFIRMED":
        err("ERR_INVALID_STATE")
    posture = calc.refresh_posture(store)
    if posture == "FROZEN":
        err("ERR_POSTURE_FROZEN")
    if posture == "RESTRICTED":
        err("ERR_POSTURE_RESTRICTED")
    start = _parse_iso(session.get("slot_start_utc"))
    if start is not None and start > CLOCK.now:
        err("ERR_INVALID_STATE", "The slot has not started yet.")
    session["status"] = "IN_PROGRESS"
    touch(session)
    return ok(session)


@route("POST", "/stores/attraction-sessions/{session_id}/complete", ["AttractionHost"])
def session_complete(ctx):
    session = require_row("sessions", ctx.p("session_id"))
    att, store = _session_store(session)
    if session.get("status") in ("COMPLETED", "NO_SHOW", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL")
    if session.get("status") != "IN_PROGRESS":
        err("ERR_INVALID_STATE")
    end = _parse_iso(session.get("slot_end_utc"))
    overrun = 0
    if end is not None:
        overrun = max(0, int((CLOCK.now - end).total_seconds() // 60))
    session["overrun_minutes"] = overrun
    session["status"] = "COMPLETED"
    S.release_session_capacity(session, att)
    member = get("members", session.get("member_id"))
    if member is not None:
        if overrun > 30:
            for other in DB.tables["sessions"].values():
                if other.get("attraction_id") == att["id"] and other.get("member_id") == member["id"] \
                        and other["id"] != session["id"]:
                    other["no_show_strikes"] = int(other.get("no_show_strikes", 0) or 0) + 1
                    touch(other)
        member["strike_epoch_started_at"] = session.get("slot_start_utc")
        touch(member)
        calc.refresh_strikes(member, att["id"])
    calc.refresh_posture(store)
    touch(store)
    touch(session)
    return ok(session)


@route("POST", "/stores/attraction-sessions/{session_id}/cancel",
       ["AttractionHost", "PlatformAdmin"])
def session_cancel(ctx):
    session = require_row("sessions", ctx.p("session_id"))
    att, store = _session_store(session)
    if session.get("status") in ("COMPLETED", "NO_SHOW", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL")
    if session.get("status") != "CONFIRMED":
        err("ERR_INVALID_STATE")
    session["status"] = "CANCELLED"
    S.release_session_capacity(session, att)
    calc.refresh_posture(store)
    touch(store)
    touch(session)
    return ok(session)


# ---------------------------------------------------------------------------
# EventOffering
# ---------------------------------------------------------------------------
OFFERING_KINDS = ("SEMINAR", "KIDS_WORKSHOP", "FREE_DEMO")


@route("POST", "/stores/{store_id}/event-offerings", ["EventsCoordinator"])
def offering_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    offering_kind = shape.enum(body, "offering_kind", OFFERING_KINDS)
    title = shape.str(body, "title", required=True)
    starts_at = shape.dt(body, "starts_at_utc", required=True)
    ends_at = shape.dt(body, "ends_at_utc", required=True)
    registration_cap = shape.int(body, "registration_cap", required=True, minimum=0)
    attraction_id = shape.str(body, "attraction_id")
    attraction = get("attractions", attraction_id) if attraction_id else None
    shape.raise_now()

    if ends_at is None or starts_at is None or ends_at <= starts_at:
        err("ERR_INVALID_SLOT_WINDOW")

    if attraction_id is not None:
        if attraction is None:
            err("ERR_RESOURCE_NOT_FOUND")
        ensure_belongs("attractions", attraction, store["id"])
        _event_venue_conflict(attraction["id"], starts_at, ends_at)

    row = create_row("event_offerings", {
        "store_id": store["id"],
        "attraction_id": attraction_id,
        "offering_kind": offering_kind,
        "title": title,
        "starts_at_utc": iso(starts_at),
        "ends_at_utc": iso(ends_at),
        "registration_cap": registration_cap,
        "confirmed_count": 0,
        "dwell_charge_minutes": 0,
        "status": "DRAFT",
    })
    return created(row)


def _event_venue_conflict(attraction_id, starts_at, ends_at, exclude=None):
    for o in DB.tables["event_offerings"].values():
        if exclude is not None and o["id"] == exclude:
            continue
        if o.get("attraction_id") != attraction_id or o.get("status") != "PUBLISHED":
            continue
        o_start = _parse_iso(o.get("starts_at_utc"))
        o_end = _parse_iso(o.get("ends_at_utc"))
        if o_start is None or o_end is None:
            continue
        if S.overlapping(starts_at, ends_at, o_start, o_end):
            err("ERR_EVENT_VENUE_CONFLICT")


@route("GET", "/stores/event-offerings/{offering_id}",
       ["EventsCoordinator", "StoreManager", "PlatformAdmin", "Anonymous"])
def offering_read(ctx):
    return ok(require_row("event_offerings", ctx.p("offering_id")))


@route("GET", "/stores/event-offerings", ["EventsCoordinator", "StoreManager", "PlatformAdmin"])
def offering_list(ctx):
    rows = list(DB.tables["event_offerings"].values())
    for key in ("store_id", "attraction_id", "offering_kind", "status"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("GET", "/stores/attractions/{attraction_id}/event-offerings",
       ["EventsCoordinator", "StoreManager", "PlatformAdmin"])
def attraction_offerings(ctx):
    att = require_row("attractions", ctx.p("attraction_id"))
    rows = [o for o in DB.tables["event_offerings"].values() if o.get("attraction_id") == att["id"]]
    status = ctx.args.get("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("POST", "/stores/event-offerings/{offering_id}/publish", ["EventsCoordinator"])
def offering_publish(ctx):
    offering = require_row("event_offerings", ctx.p("offering_id"))
    if offering.get("status") in ("COMPLETED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL")
    if offering.get("status") != "DRAFT":
        err("ERR_INVALID_STATE")
    store = get("stores", offering.get("store_id"))
    if store is None:
        err("ERR_STORE_NOT_FOUND")

    starts = _parse_iso(offering.get("starts_at_utc"))
    ends = _parse_iso(offering.get("ends_at_utc"))
    if ends is None or starts is None or ends <= starts:
        err("ERR_INVALID_SLOT_WINDOW")

    cap = int(offering.get("registration_cap", 0) or 0)
    if offering.get("offering_kind") == "FREE_DEMO":
        if cap != 0:
            err("ERR_INVALID_REQUEST", "A free demo must carry registration_cap 0.")
    elif cap <= 0:
        err("ERR_INVALID_REQUEST", "A capped offering must carry a positive registration_cap.")

    attraction_id = offering.get("attraction_id")
    if attraction_id is not None:
        att = get("attractions", attraction_id)
        if att is None:
            err("ERR_RESOURCE_NOT_FOUND")
        if att.get("status") not in ("PLANNED", "OPEN"):
            err("ERR_INVALID_STATE", "The venue cannot host this event.")
        _event_venue_conflict(attraction_id, starts, ends, exclude=offering["id"])

    charge = calc.event_dwell_charge(offering)
    figures = calc.store_dwell_figures(store)
    if figures["dwell_free_minutes"] - charge < 0:
        err("ERR_DWELL_BUDGET_EXCEEDED")

    offering["dwell_charge_minutes"] = charge
    offering["status"] = "PUBLISHED"
    touch(offering)
    calc.refresh_posture(store)
    touch(store)
    return ok(offering)


@route("POST", "/stores/event-offerings/{offering_id}/cancel",
       ["EventsCoordinator", "PlatformAdmin"])
def offering_cancel(ctx):
    offering = require_row("event_offerings", ctx.p("offering_id"))
    if offering.get("status") in ("COMPLETED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL")
    if offering.get("status") != "PUBLISHED":
        err("ERR_INVALID_STATE")
    S.cancel_event_offering(offering)
    return ok(offering)


# ---------------------------------------------------------------------------
# EventRegistration
# ---------------------------------------------------------------------------
@route("POST", "/stores/{store_id}/event-offerings/{offering_id}/registrations",
       ["Anonymous", "EventsCoordinator", "StoreManager"])
def registration_create(ctx):
    store = require_store(ctx.p("store_id"))
    offering = require_row("event_offerings", ctx.p("offering_id"))
    ensure_belongs("event_offerings", offering, store["id"])
    body = ctx.body
    shape = Shape()
    member_id = shape.str(body, "member_id", required=True)
    seats = shape.int(body, "seats", required=True, minimum=0)
    shape.raise_now()
    member = require_row("members", member_id)

    cap = int(offering.get("registration_cap", 0) or 0)
    if cap > 0 and int(offering.get("confirmed_count", 0) or 0) + seats > cap:
        err("ERR_REGISTRATION_CAP_EXCEEDED")

    row = create_row("event_registrations", {
        "event_offering_id": offering["id"],
        "member_id": member["id"],
        "seats": seats,
        "attendance_marked": False,
        "status": "REGISTERED",
    })
    return created(row)


@route("GET", "/stores/event-registrations/{registration_id}",
       ["EventsCoordinator", "StoreManager", "PlatformAdmin", "Member"])
def registration_read(ctx):
    return ok(require_row("event_registrations", ctx.p("registration_id")))


@route("GET", "/stores/event-registrations",
       ["EventsCoordinator", "StoreManager", "PlatformAdmin"])
def registration_list(ctx):
    rows = list(DB.tables["event_registrations"].values())
    for key in ("event_offering_id", "member_id", "status"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("POST", "/stores/event-offerings/{offering_id}/registrations/{registration_id}/confirm",
       ["EventsCoordinator"])
def registration_confirm(ctx):
    offering = require_row("event_offerings", ctx.p("offering_id"))
    reg = require_row("event_registrations", ctx.p("registration_id"))
    if reg.get("event_offering_id") != offering["id"]:
        err("ERR_RESOURCE_NOT_FOUND")
    if reg.get("status") in ("CANCELLED", "ATTENDED"):
        err("ERR_ALREADY_TERMINAL")
    if reg.get("status") != "REGISTERED":
        err("ERR_INVALID_STATE")
    if offering.get("status") != "PUBLISHED":
        err("ERR_INVALID_STATE")
    cap = int(offering.get("registration_cap", 0) or 0)
    seats = int(reg.get("seats", 0) or 0)
    if cap > 0 and int(offering.get("confirmed_count", 0) or 0) + seats > cap:
        # No seat inventory remains: the registration parks, consuming nothing.
        reg["status"] = "WAITLISTED"
        touch(reg)
        return ok(reg)
    if _workshop_material_shortfall(offering, seats) is not None:
        # Materials short of the workshop's need are brought in through the
        # service pipeline, and the registration parks rather than confirming.
        reg["status"] = "WAITLISTED"
        touch(reg)
        return ok(reg)
    reg["status"] = "CONFIRMED"
    offering["confirmed_count"] = int(offering.get("confirmed_count", 0) or 0) + seats
    touch(offering)
    touch(reg)
    return ok(reg)


def _workshop_material_shortfall(offering, seats):
    """A KIDS_WORKSHOP without material stock synthesises an OUTFITTING order."""
    if offering.get("offering_kind") != "KIDS_WORKSHOP":
        return None
    store = get("stores", offering.get("store_id"))
    # Neither the offering nor the store declares a materials quantity in the
    # contract, so a store that never declares a stock has nothing the workshop
    # can exceed; the shortfall branch only bites a declared finite stock.
    declared = store.get("workshop_material_stock") if store else None
    if declared is None:
        return None
    if int(seats) <= int(declared or 0):
        return None
    return create_row("service_orders", {
        "store_id": offering.get("store_id"),
        "boat_unit_id": None,
        "deal_id": None,
        "boat_deal_id": None,
        "order_kind": "OUTFITTING",
        "promised_lead_days": 7,
        "started_at_utc": None,
        "completed_at_utc": None,
        "actual_lead_days": 0,
        "is_late": False,
        "status": "INTAKE",
    })


@route("POST", "/stores/event-offerings/{offering_id}/registrations/{registration_id}/cancel",
       ["EventsCoordinator", "StoreManager", "PlatformAdmin"])
def registration_cancel(ctx):
    offering = require_row("event_offerings", ctx.p("offering_id"))
    reg = require_row("event_registrations", ctx.p("registration_id"))
    if reg.get("event_offering_id") != offering["id"]:
        err("ERR_RESOURCE_NOT_FOUND")
    if reg.get("status") in ("CANCELLED", "ATTENDED"):
        err("ERR_ALREADY_TERMINAL")
    if reg.get("status") not in ("REGISTERED", "CONFIRMED", "WAITLISTED"):
        err("ERR_INVALID_STATE")
    prior = reg.get("status")
    reg["status"] = "CANCELLED"
    if prior == "CONFIRMED":
        seats = int(reg.get("seats", 0) or 0)
        offering["confirmed_count"] = max(0, int(offering.get("confirmed_count", 0) or 0) - seats)
        touch(offering)
        member = get("members", reg.get("member_id"))
        if member is not None and seats >= 2:
            S.post_point_event(offering.get("store_id"), member, "ADJUST", 250)
    touch(reg)
    return ok(reg)