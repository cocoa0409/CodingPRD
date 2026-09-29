"""Seasons, the billing checkpoint, the reserve booking and the logical clock.

PRD §3.1 plus the clock endpoint of §2.5.
"""
from flask import Blueprint, request

import clock
import constants as C
import engine as E
import validation as V
from auth import guard
from envelope import created, ok, ok_list
from errors import fail
from money import round_half_up
from store import DB, serialize, serialize_many

bp = Blueprint("seasons", __name__)

SEASON_READ_ROLES = (
    "BoardPresident",
    "Treasurer",
    "PoolManager",
    "MembershipChair",
    "SwimTeamCoach",
    "HealthInspector",
    "Member",
)

SEASON_CREATE_SPECS = [
    V.f("year", "int", minimum=C.SEASON_YEAR_MIN, maximum=C.SEASON_YEAR_MAX),
    V.f("open_date", "date"),
    V.f("close_date", "date"),
    V.f("dues_due_date", "date"),
    V.f("baseline_bather_load", "int", required=False,
        default=C.BASELINE_BATHER_LOAD_DEFAULT, minimum=0),
    V.f("bather_load_capacity", "int", required=False,
        default=C.BATHER_LOAD_CAPACITY_DEFAULT, minimum=1),
    V.f("proration_basis", "enum", required=False, default="CALENDAR_DAY",
        enum=C.PRORATION_BASIS),
    V.f("guest_settlement_policy", "enum", required=False, default="PASS_FIRST",
        enum=C.GUEST_SETTLEMENT_POLICY),
]


@bp.route("/seasons", methods=["POST"])
def create_season():
    guard(("BoardPresident",))
    body = V.body_of(request)
    values = V.validate(body, SEASON_CREATE_SPECS)
    V.require_range(values["open_date"], values["close_date"], kind="date")
    for existing in DB.all("seasons"):
        if existing["year"] == values["year"]:
            fail("ERR_VALIDATION", "A season for year %d already exists." % values["year"])

    season = DB.insert(
        "seasons",
        {
            "year": values["year"],
            "open_date": values["open_date"],
            "close_date": values["close_date"],
            "dues_due_date": values["dues_due_date"],
            "baseline_bather_load": values["baseline_bather_load"],
            "bather_load_capacity": values["bather_load_capacity"],
            "proration_basis": values["proration_basis"],
            "guest_settlement_policy": values["guest_settlement_policy"],
            "status": "PLANNED",
            "facility_posture": "CLOSED",
            "open_critical_finding_count": 0,
            "open_major_finding_count": 0,
            "closure_started_at": None,
            "reserve_contributions_cents": 0,
            "reserve_unallocated_cents": 0,
        },
    )
    return created(serialize(season))


@bp.route("/seasons/<season_id>/open", methods=["POST"])
def open_season(season_id):
    guard(("PoolManager",))
    season = E.need("seasons", season_id)
    if season["status"] == "CLOSED":
        fail("ERR_ALREADY_TERMINAL", "A closed season cannot be reopened.")
    if season["status"] != "PLANNED":
        fail("ERR_INVALID_TRANSITION", "Only a PLANNED season may be opened.")
    season["status"] = "OPEN"
    E.derive_posture(season)
    DB.touch(season)
    return ok(serialize(season))


@bp.route("/seasons/<season_id>/close", methods=["POST"])
def close_season(season_id):
    guard(("PoolManager",))
    season = E.need("seasons", season_id)
    if season["status"] == "CLOSED":
        fail("ERR_ALREADY_TERMINAL", "The season is already closed.")
    if season["status"] != "OPEN":
        fail("ERR_INVALID_TRANSITION", "Only an OPEN season may be closed.")

    season["status"] = "CLOSED"
    E.derive_posture(season)
    season["facility_posture"] = "CLOSED"
    DB.touch(season)

    memberships = [m for m in DB.all("memberships") if m["season_id"] == season["id"]]
    for membership in memberships:
        if membership["access_status"] in ("ACTIVE", "SUSPENDED"):
            membership["access_status"] = "LAPSED"
            DB.touch(membership)

    for reg in DB.all("swim_team_registrations"):
        if reg["season_id"] != season["id"]:
            continue
        if reg["status"] == "CONFIRMED":
            reg["status"] = "COMPLETED"
            DB.touch(reg)

    for membership in memberships:
        if membership["dues_status"] == "WRITTEN_OFF":
            continue
        changed = E.recompute_credits_required(membership)
        changed = E.recompute_credits_earned(membership) or changed
        buyout = E.buyout_for(membership)
        if membership["volunteer_buyout_cents"] != buyout:
            delta = buyout - membership["volunteer_buyout_cents"]
            membership["volunteer_buyout_cents"] = buyout
            new_balance = membership["balance_due_cents"] + delta
            membership["balance_due_cents"] = new_balance if new_balance > 0 else 0
            changed = True
        if membership["balance_due_cents"] > 0 and membership["dues_status"] == "PAID":
            membership["dues_status"] = "INVOICED"
            changed = True
        if changed:
            DB.touch(membership)

    return ok(serialize(season))


BILLING_SPECS = [V.f("as_of_date", "date", required=False)]


@bp.route("/seasons/<season_id>/billing-runs", methods=["POST"])
def billing_run(season_id):
    guard(("Treasurer",))
    body = V.body_of(request)
    values = V.validate(body, BILLING_SPECS)
    season = E.need("seasons", season_id)

    if values["as_of_date"]:
        effective = clock.parse_date(values["as_of_date"])
    else:
        effective = clock.today()

    # Step one: expire certifications.
    for cert in DB.all("certifications"):
        if cert["status"] != "VALID":
            continue
        expires = clock.parse_date(cert["expires_on"])
        if expires is None or not expires < effective:
            continue
        cert["status"] = "EXPIRED"
        DB.touch(cert)
        lifeguard = DB.get("lifeguards", cert["lifeguard_id"])
        if lifeguard is not None and E.apply_cert_change(lifeguard, cert["cert_type"]):
            DB.touch(lifeguard)

    # Step two: expire stale waitlist offers.
    now = clock.now()
    vacated = []
    for entry in DB.all("waitlist_entries"):
        if entry["status"] != "OFFERED":
            continue
        if not entry["offer_expires_at"]:
            continue
        if clock.parse_instant(entry["offer_expires_at"]) < now:
            entry["status"] = "EXPIRED"
            DB.touch(entry)
            vacated.append(entry)

    # Step three: refill each vacated slot by re-running the offer selector.
    for entry in vacated:
        winner = E.select_offer_candidate(entry["membership_category_id"])
        if winner is not None:
            E.make_offer(winner)

    # Step four: age the money.
    for membership in DB.all("memberships"):
        if membership["dues_status"] != "INVOICED":
            continue
        if membership["balance_due_cents"] <= 0:
            continue
        owning_season = E.season_of_membership(membership)
        if owning_season is None:
            continue
        due = clock.parse_date(owning_season["dues_due_date"])
        if due is not None and due < effective:
            membership["dues_status"] = "DELINQUENT"
            DB.touch(membership)

    DB.touch(season)
    return ok(serialize(season))


RESERVE_SPECS = [
    V.f("amount_cents", "int", minimum=0),
    V.f("note", "string", required=False),
]


@bp.route("/seasons/<season_id>/reserve-contributions", methods=["POST"])
def reserve_contribution(season_id):
    guard(("Treasurer",))
    body = V.body_of(request)
    values = V.validate(body, RESERVE_SPECS)
    season = E.need("seasons", season_id)
    amount = values["amount_cents"]
    season["reserve_contributions_cents"] += amount
    season["reserve_unallocated_cents"] += amount
    DB.touch(season)
    return ok(serialize(season))


@bp.route("/seasons/<season_id>", methods=["GET"])
def read_season(season_id):
    guard(SEASON_READ_ROLES)
    season = E.need("seasons", season_id)
    return ok(serialize(season))


@bp.route("/seasons", methods=["GET"])
def list_seasons():
    guard(SEASON_READ_ROLES)
    limit, offset = V.pagination(request)
    rows = DB.all("seasons")
    rows = V.apply_filters(rows, request, string_fields=("status", "facility_posture"))
    rows = V.int_filter(rows, request, "year")
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)


@bp.route("/seasons/<season_id>/staffing-window", methods=["GET"])
def staffing_window(season_id):
    guard(("PoolManager", "BoardPresident", "HealthInspector"))
    raw = request.args.get("at_iso")
    if raw is None or not str(raw).strip():
        fail("ERR_VALIDATION", "Query parameter 'at_iso' is required.")
    at_dt = clock.parse_instant(raw)
    if at_dt is None:
        fail("ERR_VALIDATION", "Query parameter 'at_iso' must be an ISO 8601 UTC instant.")
    season = E.need("seasons", season_id)
    return ok(E.staffing_ratio(season, at_dt))


CLOCK_SPECS = [V.f("to_iso8601", "instant")]


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    guard(("SystemOperator",))
    body = V.body_of(request)
    values = V.validate(body, CLOCK_SPECS)
    clock.CLOCK.set(clock.parse_instant(values["to_iso8601"]))
    return ok({})
