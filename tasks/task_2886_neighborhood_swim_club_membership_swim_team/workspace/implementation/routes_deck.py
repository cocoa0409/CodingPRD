"""The gate and the deck: guest visits, lifeguards, certifications and shifts.

PRD §3.5 and §3.8.
"""
from datetime import timedelta

from flask import Blueprint, request

import clock
import constants as C
import engine as E
import validation as V
from auth import guard, require_owner
from envelope import created, ok, ok_list
from errors import fail
from money import duration_hours_2dp
from store import DB, serialize, serialize_many

bp = Blueprint("deck", __name__)

VISIT_READ_ROLES = ("PoolManager", "Treasurer", "MembershipChair", "BoardPresident", "Member")
DECK_READ_ROLES = ("PoolManager", "BoardPresident", "HealthInspector")

# ------------------------------------------------------------- the gate §3.5
VISIT_SPECS = [
    V.f("membership_id", "string"),
    V.f("sponsor_name", "string"),
    V.f("guest_count", "int", minimum=1),
    V.f("visit_start_iso", "instant"),
    V.f("expected_household_version", "int", minimum=0),
]


@bp.route("/guest-visits", methods=["POST"])
def record_visit():
    caller = guard(("Member", "PoolManager"))
    body = V.body_of(request)
    values = V.validate(body, VISIT_SPECS)
    known = DB.get("memberships", values["membership_id"])
    if known is not None:
        require_owner(caller, known["household_id"])
    membership = E.need("memberships", values["membership_id"])
    season = E.season_of_membership(membership)
    household = E.household_of_membership(membership)

    if household is not None and values["expected_household_version"] != household["version"]:
        fail(
            "ERR_STALE_HOUSEHOLD_VERSION",
            "The sponsoring household has moved since it was last read.",
        )

    if season is None or season["status"] != "OPEN":
        fail("ERR_SEASON_NOT_OPEN", "The season is not open for swimming.")
    if season["facility_posture"] == "CLOSED":
        fail("ERR_FACILITY_CLOSED", "The facility is closed.")
    if (
        season["facility_posture"] == "RESTRICTED"
        and values["guest_count"] > C.RESTRICTED_MAX_GUESTS_PER_VISIT
    ):
        fail(
            "ERR_FACILITY_RESTRICTED",
            "A restricted facility admits at most %d guests per visit."
            % C.RESTRICTED_MAX_GUESTS_PER_VISIT,
        )
    if household["standing"] in ("SUSPENDED", "EXPELLED"):
        fail("ERR_HOUSEHOLD_SUSPENDED", "A suspended household may not sponsor guests.")
    if membership["access_status"] != "ACTIVE":
        fail(
            "ERR_MEMBERSHIP_NOT_IN_GOOD_STANDING",
            "Only an active membership may sponsor a guest visit.",
        )

    visit_dt = clock.parse_instant(values["visit_start_iso"])
    visit_date = visit_dt.date()
    if visit_date < clock.parse_date(season["open_date"]) or visit_date > clock.parse_date(
        season["close_date"]
    ):
        fail("ERR_OUTSIDE_SEASON_WINDOW", "The visit falls outside the season window.")
    if visit_dt > clock.now():
        fail("ERR_VISIT_IN_FUTURE", "The visit has not happened yet.")

    if values["guest_count"] > C.MAX_GUESTS_PER_VISIT:
        fail(
            "ERR_GUEST_LIMIT_EXCEEDED",
            "At most %d guests may be signed in on one visit." % C.MAX_GUESTS_PER_VISIT,
        )
    if E.household_is_delinquent(household, season["id"]):
        fail("ERR_DUES_DELINQUENT", "The household is behind on its obligations.")

    variant = season["guest_settlement_policy"]
    is_weekend = visit_dt.weekday() >= 5
    unit = C.GUEST_FEE_WEEKEND_CENTS if is_weekend else C.GUEST_FEE_WEEKDAY_CENTS
    if variant == "FEE_FIRST_ON_WEEKEND" and is_weekend:
        passes_used = 0
    else:
        passes_used = min(household["guest_pass_balance"], values["guest_count"])
    billable = values["guest_count"] - passes_used
    fee = billable * unit

    visit = DB.insert(
        "guest_visits",
        {
            "membership_id": membership["id"],
            "sponsor_name": values["sponsor_name"],
            "guest_count": values["guest_count"],
            "visit_start_iso": values["visit_start_iso"],
            "is_weekend": is_weekend,
            "settlement_variant": variant,
            "passes_used": passes_used,
            "fee_charged_cents": fee,
            "status": "RECORDED",
            "voided_at": None,
        },
    )
    household["guest_pass_balance"] -= passes_used
    household["guest_passes_consumed"] += passes_used
    household["guest_fee_owed_cents"] += fee
    DB.touch(household)
    return created(serialize(visit))


VOID_SPECS = [V.f("reason", "string")]


@bp.route("/guest-visits/<visit_id>/void", methods=["POST"])
def void_visit(visit_id):
    guard(("PoolManager",))
    body = V.body_of(request)
    V.validate(body, VOID_SPECS)
    visit = E.need("guest_visits", visit_id)
    if visit["status"] == "VOIDED":
        fail("ERR_ALREADY_TERMINAL", "The visit is already voided.")

    visit["status"] = "VOIDED"
    visit["voided_at"] = clock.now_iso()
    DB.touch(visit)

    membership = DB.get("memberships", visit["membership_id"])
    household = E.household_of_membership(membership) if membership else None
    if household is not None:
        household["guest_passes_consumed"] -= visit["passes_used"]
        household["guest_pass_balance"] += visit["passes_used"]
        household["guest_fee_owed_cents"] -= visit["fee_charged_cents"]
        DB.touch(household)
    return ok(serialize(visit))


@bp.route("/guest-visits/<visit_id>", methods=["GET"])
def read_visit(visit_id):
    caller = guard(VISIT_READ_ROLES)
    known = DB.get("guest_visits", visit_id)
    if known is not None:
        membership = DB.get("memberships", known["membership_id"])
        if membership is not None:
            require_owner(caller, membership["household_id"])
    return ok(serialize(E.need("guest_visits", visit_id)))


@bp.route("/guest-visits", methods=["GET"])
def list_visits():
    guard(VISIT_READ_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("guest_visits"),
        request,
        string_fields=("membership_id", "status", "settlement_variant"),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)


# ------------------------------------------------------------ lifeguards §3.8
LIFEGUARD_SPECS = [V.f("full_name", "string"), V.f("hire_date", "date")]


@bp.route("/lifeguards", methods=["POST"])
def hire_lifeguard():
    guard(("PoolManager",))
    body = V.body_of(request)
    values = V.validate(body, LIFEGUARD_SPECS)
    lifeguard = DB.insert(
        "lifeguards",
        {
            "full_name": values["full_name"],
            "hire_date": values["hire_date"],
            "employment_status": "ACTIVE",
            "scheduled_hours": 0,
            "has_valid_lifeguard_cert": False,
            "has_valid_cpr_cert": False,
        },
    )
    return created(serialize(lifeguard))


@bp.route("/lifeguards/<lifeguard_id>", methods=["GET"])
def read_lifeguard(lifeguard_id):
    guard(DECK_READ_ROLES)
    return ok(serialize(E.need("lifeguards", lifeguard_id)))


@bp.route("/lifeguards", methods=["GET"])
def list_lifeguards():
    guard(DECK_READ_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("lifeguards"),
        request,
        string_fields=("employment_status",),
        bool_fields=("has_valid_lifeguard_cert",),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)


# -------------------------------------------------------- certifications §3.8
CERT_SPECS = [
    V.f("lifeguard_id", "string"),
    V.f("cert_type", "enum", enum=C.CERT_TYPE),
    V.f("issued_on", "date"),
    V.f("expires_on", "date"),
]


@bp.route("/certifications", methods=["POST"])
def create_certification():
    guard(("PoolManager",))
    body = V.body_of(request)
    values = V.validate(body, CERT_SPECS)
    V.require_range(values["issued_on"], values["expires_on"], kind="date")
    lifeguard = E.need("lifeguards", values["lifeguard_id"])

    for existing in E.rows_where("certifications", lifeguard_id=lifeguard["id"]):
        if existing["cert_type"] != values["cert_type"]:
            continue
        if existing["status"] in ("VALID", "EXPIRED"):
            existing["status"] = "SUPERSEDED"
            DB.touch(existing)

    cert = DB.insert(
        "certifications",
        {
            "lifeguard_id": lifeguard["id"],
            "cert_type": values["cert_type"],
            "issued_on": values["issued_on"],
            "expires_on": values["expires_on"],
            "status": "VALID",
            "revoked_reason": None,
        },
    )
    if E.recompute_cert_flags(lifeguard):
        DB.touch(lifeguard)
    return created(serialize(cert))


REVOKE_SPECS = [V.f("revoked_reason", "string")]


@bp.route("/certifications/<cert_id>/revoke", methods=["POST"])
def revoke_certification(cert_id):
    guard(("PoolManager",))
    body = V.body_of(request)
    values = V.validate(body, REVOKE_SPECS)
    cert = E.need("certifications", cert_id)

    if cert["status"] in ("REVOKED", "SUPERSEDED"):
        fail("ERR_ALREADY_TERMINAL", "This certification is already in a terminal state.")
    if cert["status"] != "VALID":
        fail("ERR_INVALID_TRANSITION", "Only a valid certification may be revoked.")

    cert["status"] = "REVOKED"
    cert["revoked_reason"] = values["revoked_reason"]
    DB.touch(cert)

    lifeguard = DB.get("lifeguards", cert["lifeguard_id"])
    if lifeguard is not None:
        changed = E.apply_cert_change(lifeguard, cert["cert_type"])
        now = clock.now()
        for shift in E.rows_where("guard_shifts", lifeguard_id=lifeguard["id"]):
            if shift["status"] not in ("SCHEDULED", "CONFIRMED"):
                continue
            if clock.parse_instant(shift["end_iso"]) <= now:
                continue
            shift["status"] = "CANCELLED"
            DB.touch(shift)
        changed = E.recompute_scheduled_hours(lifeguard) or changed
        if changed:
            DB.touch(lifeguard)
    return ok(serialize(cert))


@bp.route("/certifications/<cert_id>", methods=["GET"])
def read_certification(cert_id):
    guard(DECK_READ_ROLES)
    return ok(serialize(E.need("certifications", cert_id)))


@bp.route("/certifications", methods=["GET"])
def list_certifications():
    guard(DECK_READ_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("certifications"),
        request,
        string_fields=("lifeguard_id", "cert_type", "status"),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)


# --------------------------------------------------------- guard shifts §3.8
SHIFT_SPECS = [
    V.f("lifeguard_id", "string"),
    V.f("season_id", "string"),
    V.f("shift_role", "enum", enum=C.SHIFT_ROLE),
    V.f("start_iso", "instant"),
    V.f("end_iso", "instant"),
]
SHIFT_TERMINAL = ("COMPLETED", "CANCELLED", "NO_SHOW", "CANCELLED_BY_CLOSURE")


@bp.route("/guard-shifts", methods=["POST"])
def create_shift():
    guard(("PoolManager",))
    body = V.body_of(request)
    values = V.validate(body, SHIFT_SPECS)
    V.require_range(values["start_iso"], values["end_iso"])
    season = E.need("seasons", values["season_id"])
    lifeguard = E.need("lifeguards", values["lifeguard_id"])

    if season["status"] != "OPEN":
        fail("ERR_SEASON_NOT_OPEN", "Shifts are scheduled only against an open season.")
    if not E.cert_wall_ok(lifeguard["id"], values["end_iso"]):
        fail(
            "ERR_CERT_NOT_VALID_FOR_SHIFT",
            "The guard lacks a valid lifeguard and CPR certification for this shift.",
        )

    start_dt = clock.parse_instant(values["start_iso"])
    end_dt = clock.parse_instant(values["end_iso"])
    open_date = clock.parse_date(season["open_date"])
    close_date = clock.parse_date(season["close_date"])
    if start_dt.date() < open_date or end_dt.date() > close_date:
        fail("ERR_OUTSIDE_SEASON_WINDOW", "The shift falls outside the season window.")

    buffer_gap = timedelta(minutes=C.SHIFT_REST_BUFFER_MINUTES)
    for other in E.rows_where("guard_shifts", lifeguard_id=lifeguard["id"]):
        if other["status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        other_start = clock.parse_instant(other["start_iso"])
        other_end = clock.parse_instant(other["end_iso"])
        if start_dt >= other_end:
            gap = start_dt - other_end
        elif other_start >= end_dt:
            gap = other_start - end_dt
        else:
            gap = timedelta(0)
        if gap < buffer_gap:
            fail(
                "ERR_SHIFT_REST_BUFFER_VIOLATION",
                "The guard needs %d minutes of rest between shifts."
                % C.SHIFT_REST_BUFFER_MINUTES,
            )

    shift = DB.insert(
        "guard_shifts",
        {
            "lifeguard_id": lifeguard["id"],
            "season_id": season["id"],
            "shift_role": values["shift_role"],
            "start_iso": values["start_iso"],
            "end_iso": values["end_iso"],
            "duration_hours": duration_hours_2dp(start_dt, end_dt),
            "counts_toward_ratio": values["shift_role"] in ("PRIMARY", "SECONDARY"),
            "status": "SCHEDULED",
        },
    )
    if E.recompute_scheduled_hours(lifeguard):
        DB.touch(lifeguard)
    return created(serialize(shift))


TRANSITION_SPECS = lambda enum: [V.f("to_status", "enum", enum=enum)]


@bp.route("/guard-shifts/<shift_id>/transitions", methods=["POST"])
def transition_shift(shift_id):
    guard(("PoolManager",))
    body = V.body_of(request)
    values = V.validate(body, TRANSITION_SPECS(C.SHIFT_STATUS))
    shift = E.need("guard_shifts", shift_id)
    target = values["to_status"]
    current = shift["status"]
    lifeguard = DB.get("lifeguards", shift["lifeguard_id"])
    season = DB.get("seasons", shift["season_id"])

    if current in SHIFT_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "This shift is already in a terminal state.")

    allowed = {
        "SCHEDULED": ("CONFIRMED", "CANCELLED"),
        "CONFIRMED": ("COMPLETED", "NO_SHOW", "CANCELLED"),
    }
    if target not in allowed.get(current, ()):
        fail("ERR_INVALID_TRANSITION", "%s is not an edge from %s." % (target, current))

    now = clock.now()
    if target == "CONFIRMED":
        if lifeguard is None or lifeguard["employment_status"] != "ACTIVE":
            fail("ERR_CERT_NOT_VALID_FOR_SHIFT", "The guard is not active on the roster.")
        if not E.cert_wall_ok(shift["lifeguard_id"], shift["end_iso"]):
            fail(
                "ERR_CERT_NOT_VALID_FOR_SHIFT",
                "The certification wall no longer holds for this shift.",
            )
    elif target == "COMPLETED":
        if now < clock.parse_instant(shift["end_iso"]):
            fail("ERR_INVALID_TRANSITION", "The shift has not finished yet.")
    elif target == "NO_SHOW":
        if now < clock.parse_instant(shift["start_iso"]):
            fail("ERR_INVALID_TRANSITION", "The shift has not started yet.")
    elif target == "CANCELLED":
        if season is not None and not E.cancellation_preserves_ratio(shift, season):
            fail(
                "ERR_GUARD_RATIO_NOT_MET",
                "Cancelling this shift would strand a confirmed party.",
            )

    shift["status"] = target
    DB.touch(shift)
    if lifeguard is not None and E.recompute_scheduled_hours(lifeguard):
        DB.touch(lifeguard)
    return ok(serialize(shift))


@bp.route("/guard-shifts/<shift_id>", methods=["GET"])
def read_shift(shift_id):
    guard(DECK_READ_ROLES)
    return ok(serialize(E.need("guard_shifts", shift_id)))


@bp.route("/guard-shifts", methods=["GET"])
def list_shifts():
    guard(DECK_READ_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("guard_shifts"),
        request,
        string_fields=("lifeguard_id", "season_id", "status", "shift_role"),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)
