"""Members, advocate selection, intake and surrender routes (PRD 3.2, 3.8)."""

from flask import request

from body import body, opt, require, require_enum, require_dt
from bp import api
from clock import parse_dt
from db import db
from errors import APIError
from helpers import (
    derive_advocate_status,
    employer_of_member,
    recompute_advocate,
    recompute_employer,
    recompute_member,
)
from calculations import surrender_route_cost
from listing import apply_filters, ordered, paginate
from lookups import clinic as clinic_lookup, member as member_lookup
from middleware import require_member_ownership, resolve_actor
from response import ok, created
from serializers import serialize

DEFAULT_MIN_INTER_CYCLE_DAYS = 0


def _select_advocate(store, member, strategy):
    """The eligible pool, ordered by the effective allocation strategy."""
    pool = [
        a for a in store.all("care_advocates")
        if member["state_code"] in (a.get("states_licensed") or [])
        and member["required_track"] in (a.get("specializations") or [])
        and derive_advocate_status(store, a) in ("ACTIVE", "AT_CAPACITY")
    ]
    if not pool:
        raise APIError("ERR_NO_ADVOCATE_CANDIDATE", "The advocate selector's pool is empty.")
    if strategy == "LEAST_LOADED":
        pool.sort(key=lambda a: (a["current_caseload"], a["id"]))
    else:
        # ROUND_ROBIN and every other named strategy walk the pool in creation order.
        pool.sort(key=lambda a: (store.created_key(a), a["id"]))
    return pool[0]


@api.route("/members", methods=["POST"])
def create_member():
    resolve_actor()
    data = body()
    account_id = require(data, "employer_account_id")
    external_ref = require(data, "external_ref")
    full_name = require(data, "full_name")
    state_code = require(data, "state_code")
    required_track = require_enum(data, "required_track")

    account = db.find("employer_accounts", account_id)
    if account is None:
        raise APIError("ERR_NOT_FOUND", "The employer_account_id does not resolve.")

    duplicate = [
        m for m in db.all("members")
        if m["employer_account_id"] == account_id and m["external_ref"] == external_ref
    ]
    if duplicate:
        raise APIError("ERR_INVALID_REQUEST", "external_ref must be unique within the account.")

    row = db.common()
    row.update({
        "_collection": "members",
        "employer_account_id": account_id,
        "external_ref": external_ref,
        "full_name": full_name,
        "state_code": state_code,
        "required_track": required_track,
        "member_status": "INTAKE",
        "care_advocate_id": None,
        "clinic_id": None,
        "pathway_selected": "NONE",
        "completed_cycles": 0,
        "live_births_recorded": 0,
        "intake_completed_at": None,
    })
    db.add(row)

    recompute_employer(db, account)
    db.touch(account)
    return created(serialize("members", row))


@api.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    actor = resolve_actor()
    row = member_lookup(member_id)
    require_member_ownership(actor, row["id"])
    return ok(serialize("members", row))


@api.route("/members", methods=["GET"])
def list_members():
    actor = resolve_actor()
    rows = ordered(db.all("members"))
    if actor.role == "Member":
        rows = [r for r in rows if r["id"] == actor.user_id]
    rows = apply_filters(rows, {
        "employer_account_id": "employer_account_id",
        "care_advocate_id": "care_advocate_id",
        "member_status": "member_status",
        "state_code": "state_code",
        "pathway_selected": "pathway_selected",
        "clinic_id": "clinic_id",
    })
    return paginate(rows, "members")


@api.route("/members/<member_id>/assign-advocate", methods=["POST"])
def assign_advocate(member_id):
    resolve_actor()
    member = member_lookup(member_id)
    data = body()

    strategy = opt(data, "allocation_strategy")
    if strategy is None:
        account = employer_of_member(db, member)
        strategy = account["allocation_method"] if account else "ROUND_ROBIN"

    selected = _select_advocate(db, member, strategy)
    previous = db.find("care_advocates", member["care_advocate_id"]) if member.get("care_advocate_id") else None
    member["care_advocate_id"] = selected["id"]

    if previous is not None:
        recompute_advocate(db, previous)
    recompute_advocate(db, selected)

    account = employer_of_member(db, member)
    if account is not None:
        db.touch(account)
    db.touch(member)
    return ok(serialize("members", member))


@api.route("/members/<member_id>/complete-intake", methods=["POST"])
def complete_intake(member_id):
    resolve_actor()
    member = member_lookup(member_id)
    if member["member_status"] != "INTAKE":
        raise APIError("ERR_INVALID_STATE", "The member is not in INTAKE.")

    if not member.get("care_advocate_id"):
        raise APIError("ERR_INVALID_STATE", "No care advocate is assigned to this member.")

    advocate = db.find("care_advocates", member["care_advocate_id"])
    if advocate is None:
        raise APIError("ERR_INVALID_STATE", "The assigned care advocate does not resolve.")

    # The credential gate is read continuously: a lapsed credential and a
    # caseload at the ceiling both refuse the close, and both report the
    # window-specific error the PRD §2.10 governance clause names.
    if derive_advocate_status(db, advocate) != "ACTIVE":
        raise APIError("ERR_ADVOCATE_CREDENTIAL_LAPSED",
                       "The assigned advocate's credential has lapsed or its ceiling is reached.")
    if advocate["current_caseload"] >= advocate["caseload_limit"]:
        raise APIError("ERR_ADVOCATE_CREDENTIAL_LAPSED",
                       "The assigned advocate has reached their caseload ceiling.")

    account = employer_of_member(db, member)
    if account is None or account["account_status"] != "ACTIVE":
        raise APIError("ERR_BENEFIT_INACTIVE", "The sponsoring account is not ACTIVE.")

    member["member_status"] = "CARE_ACTIVE"
    member["intake_completed_at"] = db.now()

    recompute_advocate(db, advocate)
    if account is not None:
        recompute_employer(db, account)
        db.touch(account)
    db.touch(member)
    return ok(serialize("members", member))


@api.route("/members/<member_id>/complete-care", methods=["POST"])
def complete_care(member_id):
    resolve_actor()
    member = member_lookup(member_id)
    if member["member_status"] != "CARE_ACTIVE":
        raise APIError("ERR_INVALID_STATE", "The member is not CARE_ACTIVE.")

    live_plan_states = ("PLAN_DRAFT", "CLINIC_SELECTED", "AUTHORIZATION_PENDING", "IN_PROGRESS", "PLANNING_REVISION")
    live_plans = [
        p for p in db.all("treatment_plans")
        if p["member_id"] == member["id"] and p["plan_status"] in live_plan_states
    ]
    if live_plans:
        raise APIError("ERR_INVALID_STATE", "A treatment plan of this member is still live.")

    live_pathways = [
        r for r in db.all("pathway_requests")
        if r["member_id"] == member["id"] and r["pathway_status"] in ("DRAFT", "CLINICAL_REVIEW", "APPROVED", "ACTIVE")
    ]
    if live_pathways:
        raise APIError("ERR_INVALID_STATE", "A pathway request of this member is still live.")

    member["member_status"] = "CARE_COMPLETE"

    advocate = db.find("care_advocates", member["care_advocate_id"]) if member.get("care_advocate_id") else None
    if advocate is not None:
        recompute_advocate(db, advocate)
    account = employer_of_member(db, member)
    if account is not None:
        recompute_employer(db, account)
        db.touch(account)
    db.touch(member)
    return ok(serialize("members", member))


@api.route("/members/<member_id>/select-clinic", methods=["POST"])
def select_member_clinic(member_id):
    resolve_actor()
    member = member_lookup(member_id)
    data = body()
    clinic_id = require(data, "clinic_id")
    clinic_lookup(clinic_id)

    member["clinic_id"] = clinic_id
    db.touch(member)
    return ok(serialize("members", member))


# --------------------------------------------------------------------------
# Surrender routes
# --------------------------------------------------------------------------

def _occupied_routes(store, member_id):
    return [
        r for r in store.all("surrender_routes")
        if r["member_id"] == member_id and r["route_status"] in ("SUBMITTED", "ROUTED")
    ]


def _route_interval(route):
    """[route_from, route_to) followed by the storage retention tail."""
    from clock import STORAGE_RETENTION_DAYS
    from datetime import timedelta
    start = parse_dt(route["route_from"])
    end = parse_dt(route["route_to"])
    if route["route_status"] == "ROUTED":
        end = end + timedelta(days=STORAGE_RETENTION_DAYS)
    return start, end


def _overlapping_route(store, member_id, route_from, route_to):
    """A route whose occupied interval shares any instant with the requested one."""
    for route in _occupied_routes(store, member_id):
        start, end = _route_interval(route)
        if start < route_to and route_from < end:
            return route
    return None


@api.route("/members/<member_id>/surrender-routes", methods=["POST"])
def create_surrender_route(member_id):
    resolve_actor()
    member = member_lookup(member_id)
    data = body()

    pathway_type = require_enum(data, "pathway_type")
    carrier_kind = require_enum(data, "carrier_kind")
    route_from = require_dt(data, "route_from")
    route_to = require_dt(data, "route_to")
    raw_cost_cents = opt(data, "raw_cost_cents")
    expected_member_version = data.get("expected_member_version")

    if route_to < route_from:
        raise APIError("ERR_INVALID_REQUEST", "The route interval end precedes its start.")

    from lookups import resolve_member_version
    resolve_member_version(expected_member_version, member["version"])

    # The acting advocate's credential and caseload ceiling gate the filing.
    acting_id = request.headers.get("X-User-ID")
    acting = db.find("care_advocates", acting_id)
    candidates = [acting] if acting is not None else []
    if member.get("care_advocate_id"):
        assigned = db.find("care_advocates", member["care_advocate_id"])
        if assigned is not None and assigned not in candidates:
            candidates.append(assigned)
    for advocate in candidates:
        status = derive_advocate_status(db, advocate)
        if status == "INACTIVE":
            raise APIError("ERR_ADVOCATE_CREDENTIAL_LAPSED", "The advocate's credential has lapsed.")
        if advocate["current_caseload"] >= advocate["caseload_limit"]:
            raise APIError("ERR_ADVOCATE_CREDENTIAL_LAPSED", "The advocate has reached caseload_limit.")

    existing = _overlapping_route(db, member["id"], route_from, route_to)
    if existing is not None and existing["carrier_kind"] != carrier_kind:
        raise APIError("ERR_SURRENDER_ROUTE_CONFLICT", "The route disagrees with an overlapping route on file.")

    row = db.common()
    row.update({
        "_collection": "surrender_routes",
        "member_id": member["id"],
        "pathway_type": pathway_type,
        "carrier_kind": carrier_kind,
        "route_from": route_from,
        "route_to": route_to,
        "route_status": "SUBMITTED",
        "surrender_cost_cents": surrender_route_cost(carrier_kind, raw_cost_cents),
        "raw_cost_cents": raw_cost_cents if raw_cost_cents is not None else 0,
    })
    db.add(row)

    recompute_member(db, member)
    db.touch(member)
    # PRD 2.2: an operation that creates a resource returns the created resource
    # object, so the route row is what the caller reads back. PRD section 4's
    # 201-Created list does not name surrender routes, so this stays a 200.
    return ok(serialize("surrender_routes", row), "object", 200)


@api.route("/members/<member_id>/surrender-routes", methods=["GET"])
def list_member_surrender_routes(member_id):
    actor = resolve_actor()
    member = member_lookup(member_id)
    require_member_ownership(actor, member["id"])
    rows = ordered([r for r in db.all("surrender_routes") if r["member_id"] == member["id"]])
    rows = apply_filters(rows, {
        "pathway_type": "pathway_type",
        "carrier_kind": "carrier_kind",
        "route_status": "route_status",
    })
    return paginate(rows, "surrender_routes")


@api.route("/surrender-routes", methods=["GET"])
def list_surrender_routes():
    resolve_actor()
    rows = ordered(db.all("surrender_routes"))
    rows = apply_filters(rows, {
        "member_id": "member_id",
        "pathway_type": "pathway_type",
        "carrier_kind": "carrier_kind",
        "route_status": "route_status",
    })
    return paginate(rows, "surrender_routes")


@api.route("/surrender-routes/<route_id>", methods=["GET"])
def get_surrender_route(route_id):
    resolve_actor()
    row = db.find("surrender_routes", route_id)
    if row is None:
        raise APIError("ERR_NOT_FOUND", "The surrender route does not resolve.")
    return ok(serialize("surrender_routes", row))


@api.route("/members/<member_id>/surrender-routes/withdraw", methods=["POST"])
def withdraw_surrender_route(member_id):
    resolve_actor()
    member = member_lookup(member_id)
    data = body()
    route_id = require(data, "route_id")
    route = db.find("surrender_routes", route_id)
    if route is None or route["member_id"] != member["id"]:
        raise APIError("ERR_NOT_FOUND", "The surrender route does not resolve.")

    if route["route_status"] != "SUBMITTED":
        raise APIError("ERR_INVALID_STATE", "The route is not SUBMITTED.")

    route["route_status"] = "WITHDRAWN"
    db.touch(route)
    db.touch(member)
    return ok(serialize("surrender_routes", route))


@api.route("/members/<member_id>/surrender-routes/retire", methods=["POST"])
def retire_surrender_route(member_id):
    resolve_actor()
    member = member_lookup(member_id)
    data = body()
    route_id = require(data, "route_id")
    route = db.find("surrender_routes", route_id)
    if route is None or route["member_id"] != member["id"]:
        raise APIError("ERR_NOT_FOUND", "The surrender route does not resolve.")

    if route["route_status"] != "ROUTED":
        raise APIError("ERR_INVALID_STATE", "The route is not ROUTED.")

    from clock import STORAGE_RETENTION_DAYS
    from datetime import timedelta
    if db.now() < parse_dt(route["route_to"]) + timedelta(days=STORAGE_RETENTION_DAYS):
        raise APIError("ERR_INVALID_STATE", "The storage retention period has not closed.")

    route["route_status"] = "RETIRED"
    db.touch(route)
    db.touch(member)
    return ok(serialize("surrender_routes", route))