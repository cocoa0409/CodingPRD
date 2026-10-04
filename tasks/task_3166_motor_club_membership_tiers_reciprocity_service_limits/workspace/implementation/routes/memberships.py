"""Memberships: enrollment, lifecycle actions, tier changes, reverse lookups,
membership events, household member add."""

from datetime import timedelta

from flask import Blueprint

from db import DB, CLOCK, new_id, stamp_new, touch, fmt_ts, parse_iso
from errors import (
    not_found, invalid_request, invalid_state, stale_version, business,
    ERR_CLUB_SUSPENDED, ERR_OPEN_SERVICE_CALLS, ERR_REINSTATEMENT_WINDOW_EXPIRED,
    ERR_TIER_MOVE_INVALID, ERR_HOUSEHOLD_LIMIT,
)
from middleware import require_auth
from response import ok_obj
from routes._common import list_response
from services.calculations import (
    tier_by_code, tier_change_proration, household_proration_credit,
    NON_TERMINAL_CALL_STATES, TERM_DAYS, GRACE_DAYS, REINSTATEMENT_WINDOW_DAYS,
    HOUSEHOLD_MAX_ACTIVE, CHILD_MAX_AGE,
)
from services.events import append_event
from services.serialize import public
from services.validate import (
    body_json, req_string, req_enum, opt_bool, parse_iso_field,
)

bp = Blueprint("memberships", __name__)

MS_READ = {"MemberServicesRep", "Dispatcher", "SettlementClerk", "FederationFinance"}
RELATIONSHIPS = {"SPOUSE", "CHILD", "PARENT", "OTHER"}


def _get_membership(membership_id):
    m = DB.memberships.get(membership_id)
    if m is None:
        raise not_found("membership not found")
    return m


def _get_tier_by_code_or_400(code):
    t = tier_by_code(code)
    if t is None:
        raise invalid_request("tier_code is unknown")
    return t


def _has_open_calls(membership_id):
    for c in DB.service_calls.values():
        if c["membership_id"] == membership_id and c["status"] in NON_TERMINAL_CALL_STATES:
            return True
    return False


def _renew_term(m):
    new_start = m["_term_end_dt"]
    new_end = new_start + timedelta(days=TERM_DAYS)
    m["_term_start_dt"] = new_start
    m["_term_end_dt"] = new_end
    m["term_start_date"] = fmt_ts(new_start)
    m["term_end_date"] = fmt_ts(new_end)
    m["calls_used_current_term"] = 0


# ------------------------------------------------------------- enrollment ---

@bp.post("/motor-club/memberships")
def create_membership():
    require_auth({"MemberServicesRep"})
    data = body_json()
    home_club_id = req_string(data, "home_club_id")
    name = req_string(data, "primary_member_name")
    email = req_string(data, "primary_member_email")
    tier_code = req_enum(data, "tier_code", {"CLASSIC", "PLUS", "PREMIER"})
    # referential integrity: home club and tier must exist
    club = DB.clubs.get(home_club_id)
    if club is None:
        raise not_found("home club not found")
    tier = _get_tier_by_code_or_400(tier_code)
    for m in DB.memberships.values():
        if m["primary_member_email"] == email:
            raise invalid_request("primary_member_email must be unique")
    # business: home club must be ACTIVE
    if club["status"] != "ACTIVE":
        raise business(ERR_CLUB_SUSPENDED, "home club is not ACTIVE")

    now = CLOCK.now()
    term_end = now + timedelta(days=TERM_DAYS)
    membership = {
        "id": new_id(),
        "home_club_id": home_club_id,
        "primary_member_name": name,
        "primary_member_email": email,
        "tier_code": tier_code,
        "status": "ACTIVE",
        "enrolled_at": fmt_ts(now),
        "term_start_date": fmt_ts(now),
        "term_end_date": fmt_ts(term_end),
        "lapse_at": None,
        "reinstatement_count": 0,
        "calls_used_current_term": 0,
        "account_credit_cents": 0,
        "tier_upgrade_effective_at": None,
        "_term_start_dt": now,
        "_term_end_dt": term_end,
        "_lapse_dt": None,
        "_tier_upgrade_effective_dt": None,
        "_waiting_satisfied_logged": False,
        "_tier_history": [tier_code],
    }
    stamp_new(membership)
    DB.memberships[membership["id"]] = membership
    append_event(membership["id"], "ENROLLMENT", None, tier_code, "")
    return ok_obj(public(membership), 201)


@bp.get("/motor-club/memberships")
def list_memberships():
    require_auth(MS_READ)
    from flask import request
    status = request.args.get("status")
    home_club_id = request.args.get("home_club_id")

    def filt(m):
        if status is not None and m["status"] != status:
            return False
        if home_club_id is not None and m["home_club_id"] != home_club_id:
            return False
        return True

    return list_response(list(DB.memberships.values()), filt)


@bp.get("/motor-club/memberships/<membershipId>")
def get_membership(membershipId):
    require_auth(MS_READ)
    return ok_obj(public(_get_membership(membershipId)))


# ---------------------------------------------------------- tier changes ---

def _tier_move(membership_id, direction):
    require_auth({"MemberServicesRep"})
    m = _get_membership(membership_id)
    data = body_json()
    target_code = data.get("target_tier_code")
    if target_code is None or not isinstance(target_code, str):
        raise invalid_request("missing required field: target_tier_code")
    target = tier_by_code(target_code)
    current = tier_by_code(m["tier_code"])
    # state precondition: membership must not be CANCELLED/LAPSED for a tier move
    if m["status"] not in {"ACTIVE", "GRACE", "REINSTATED"}:
        raise invalid_state("membership is not in a state permitting tier change")
    # business: tier move validity
    if target is None or target_code == m["tier_code"]:
        raise business(ERR_TIER_MOVE_INVALID, "invalid tier move target")
    if direction == "upgrade" and target["rank"] <= current["rank"]:
        raise business(ERR_TIER_MOVE_INVALID, "upgrade requires a higher-rank tier")
    if direction == "downgrade" and target["rank"] >= current["rank"]:
        raise business(ERR_TIER_MOVE_INVALID, "downgrade requires a lower-rank tier")
    # OCC checked last among validations
    expected = data.get("expected_membership_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise invalid_request("expected_membership_version must be an integer")
        if expected != m["version"]:
            raise stale_version()

    now = CLOCK.now()
    prorated_new, prorated_old = tier_change_proration(m, current, target, now)
    if direction == "upgrade":
        charge = prorated_new - prorated_old
        if charge > 0:
            m["account_credit_cents"] -= charge
        effective_dt = now + timedelta(days=target["upgrade_waiting_days"])
        m["_tier_upgrade_effective_dt"] = effective_dt
        m["tier_upgrade_effective_at"] = fmt_ts(effective_dt)
        m["_waiting_satisfied_logged"] = False
    else:
        credit = prorated_old - prorated_new
        if credit > 0:
            m["account_credit_cents"] += credit
        # downgrade carries no waiting period; clear any pending upgrade marker
        m["_tier_upgrade_effective_dt"] = None
        m["tier_upgrade_effective_at"] = None
        m["_waiting_satisfied_logged"] = False
    from_tier = m["tier_code"]
    m["tier_code"] = target_code
    m["_tier_history"].append(target_code)
    touch(m)
    append_event(m["id"], "UPGRADE" if direction == "upgrade" else "DOWNGRADE",
                 from_tier, target_code, "")
    return ok_obj(public(m))


@bp.post("/motor-club/memberships/<membershipId>/upgrade")
def upgrade_membership(membershipId):
    return _tier_move(membershipId, "upgrade")


@bp.post("/motor-club/memberships/<membershipId>/downgrade")
def downgrade_membership(membershipId):
    return _tier_move(membershipId, "downgrade")


# --------------------------------------------------------------- lifecycle ---

@bp.post("/motor-club/memberships/<membershipId>/renew")
def renew_membership(membershipId):
    require_auth({"MemberServicesRep"})
    m = _get_membership(membershipId)
    now = CLOCK.now()
    if m["status"] == "GRACE":
        grace_deadline = m["_term_end_dt"] + timedelta(days=GRACE_DAYS)
        if now > grace_deadline:
            raise invalid_state("grace deadline has passed")
        _renew_term(m)
        m["status"] = "ACTIVE"
    elif m["status"] == "REINSTATED":
        _renew_term(m)
        m["status"] = "ACTIVE"
    else:
        raise invalid_state("renew is permitted only from GRACE or REINSTATED")
    touch(m)
    append_event(m["id"], "RENEWAL", m["tier_code"], None, "")
    return ok_obj(public(m))


@bp.post("/motor-club/memberships/<membershipId>/lapse")
def lapse_membership(membershipId):
    require_auth({"MemberServicesRep"})
    m = _get_membership(membershipId)
    if m["status"] != "ACTIVE":
        raise invalid_state("administrative lapse requires an ACTIVE membership")
    if _has_open_calls(m["id"]):
        raise business(ERR_OPEN_SERVICE_CALLS, "membership has non-terminal service calls")
    now = CLOCK.now()
    m["status"] = "LAPSED"
    m["_lapse_dt"] = now
    m["lapse_at"] = fmt_ts(now)
    touch(m)
    append_event(m["id"], "LAPSE", m["tier_code"], None, "ADMIN_LAPSE")
    return ok_obj(public(m))


@bp.post("/motor-club/memberships/<membershipId>/reinstate")
def reinstate_membership(membershipId):
    require_auth({"MemberServicesRep"})
    m = _get_membership(membershipId)
    data = body_json()
    if m["status"] != "LAPSED":
        raise invalid_state("reinstate requires a LAPSED membership")
    now = CLOCK.now()
    if m["_lapse_dt"] is None or now > m["_lapse_dt"] + timedelta(days=REINSTATEMENT_WINDOW_DAYS):
        raise business(ERR_REINSTATEMENT_WINDOW_EXPIRED,
                       "reinstatement window (90 days from lapse) has expired")
    dues_paid = data.get("dues_paid")
    if dues_paid is not True:
        raise invalid_request("dues_paid must be true to reinstate")
    term_end = now + timedelta(days=TERM_DAYS)
    m["_term_start_dt"] = now
    m["_term_end_dt"] = term_end
    m["term_start_date"] = fmt_ts(now)
    m["term_end_date"] = fmt_ts(term_end)
    m["calls_used_current_term"] = 0
    m["reinstatement_count"] += 1
    m["_lapse_dt"] = None
    m["lapse_at"] = None
    m["status"] = "REINSTATED"
    touch(m)
    append_event(m["id"], "REINSTATEMENT", m["tier_code"], None, "")
    return ok_obj(public(m))


@bp.post("/motor-club/memberships/<membershipId>/cancel")
def cancel_membership(membershipId):
    require_auth({"MemberServicesRep"})
    m = _get_membership(membershipId)
    if m["status"] not in {"ACTIVE", "GRACE", "REINSTATED"}:
        raise invalid_state("cancel is permitted only from ACTIVE, GRACE or REINSTATED")
    if _has_open_calls(m["id"]):
        raise business(ERR_OPEN_SERVICE_CALLS, "membership has non-terminal service calls")
    # cascade: household members -> REMOVED
    for h in DB.household_members.values():
        if h["membership_id"] == m["id"] and h["status"] == "ACTIVE":
            h["status"] = "REMOVED"
            touch(h)
    # cascade: ancillary sales -> REFUNDED with full price credit
    for s in DB.ancillary_sales.values():
        if s["membership_id"] == m["id"] and s["status"] == "ACTIVE":
            s["status"] = "REFUNDED"
            touch(s)
            m["account_credit_cents"] += s["price_cents"]
    m["status"] = "CANCELLED"
    touch(m)
    append_event(m["id"], "CANCELLATION", m["tier_code"], None, "")
    return ok_obj(public(m))


# -------------------------------------------------------- reverse lookups ---

@bp.get("/motor-club/memberships/<mid>/membershipEvents")
def list_membership_events(mid):
    require_auth({"MemberServicesRep", "FederationFinance"})
    _get_membership(mid)
    rows = [e for e in DB.membership_events.values() if e["membership_id"] == mid]
    return list_response(rows)


@bp.get("/motor-club/memberships/<mid>/householdMembers")
def list_household_of_membership(mid):
    require_auth({"MemberServicesRep", "Dispatcher"})
    from flask import request
    _get_membership(mid)
    status = request.args.get("status")
    rows = [h for h in DB.household_members.values() if h["membership_id"] == mid]
    if status is not None:
        rows = [h for h in rows if h["status"] == status]
    return list_response(rows)


@bp.get("/motor-club/memberships/<membershipId>/service-calls")
def list_calls_of_membership(membershipId):
    require_auth({"MemberServicesRep", "Dispatcher", "SettlementClerk"})
    from flask import request
    _get_membership(membershipId)
    status = request.args.get("status")
    rows = [c for c in DB.service_calls.values() if c["membership_id"] == membershipId]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return list_response(rows)


@bp.get("/motor-club/memberships/<membershipId>/ancillary-sales")
def list_sales_of_membership(membershipId):
    require_auth({"MemberServicesRep", "Agent"})
    from flask import request
    _get_membership(membershipId)
    status = request.args.get("status")
    rows = [s for s in DB.ancillary_sales.values() if s["membership_id"] == membershipId]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return list_response(rows)


# ------------------------------------------------------------ flat lists ---

@bp.get("/motor-club/membership-events")
def list_membership_events_flat():
    require_auth({"MemberServicesRep", "FederationFinance"})
    from flask import request
    membership_id = request.args.get("membership_id")
    event_type = request.args.get("event_type")

    def filt(e):
        if membership_id is not None and e["membership_id"] != membership_id:
            return False
        if event_type is not None and e["event_type"] != event_type:
            return False
        return True

    return list_response(list(DB.membership_events.values()), filt)


# ------------------------------------------------------ household add ---

@bp.post("/motor-club/memberships/<membershipId>/household-members")
def add_household_member(membershipId):
    require_auth({"MemberServicesRep"})
    m = _get_membership(membershipId)
    data = body_json()
    full_name = req_string(data, "full_name")
    relationship = req_enum(data, "relationship", RELATIONSHIPS)
    if "date_of_birth" not in data or data["date_of_birth"] is None:
        raise invalid_request("missing required field: date_of_birth")
    dob = parse_iso_field(data["date_of_birth"], "date_of_birth")
    is_primary = opt_bool(data, "is_primary", False)

    # household capacity and CHILD age bound
    active_count = sum(
        1 for h in DB.household_members.values()
        if h["membership_id"] == m["id"] and h["status"] == "ACTIVE"
    )
    if active_count >= HOUSEHOLD_MAX_ACTIVE:
        raise business(ERR_HOUSEHOLD_LIMIT, "household exceeds 4 ACTIVE members")
    if is_primary:
        for h in DB.household_members.values():
            if (h["membership_id"] == m["id"] and h["status"] == "ACTIVE"
                    and h["is_primary"]):
                raise business(ERR_HOUSEHOLD_LIMIT, "at most one primary household row per membership")
    if relationship == "CHILD":
        now = CLOCK.now()
        age_days = (now - dob).total_seconds() / 86400.0
        if age_days >= CHILD_MAX_AGE * 365:
            raise business(ERR_HOUSEHOLD_LIMIT, "CHILD relationship requires age < 21")

    hm = {
        "id": new_id(),
        "membership_id": m["id"],
        "full_name": full_name,
        "relationship": relationship,
        "is_primary": is_primary,
        "date_of_birth": data["date_of_birth"],
        "status": "ACTIVE",
    }
    stamp_new(hm)
    DB.household_members[hm["id"]] = hm
    # full-year dues debit for non-primary household additions
    if not is_primary:
        tier = tier_by_code(m["tier_code"])
        if tier is not None:
            m["account_credit_cents"] -= tier["household_member_price_cents"]
            touch(m)
    return ok_obj(public(hm), 201)
