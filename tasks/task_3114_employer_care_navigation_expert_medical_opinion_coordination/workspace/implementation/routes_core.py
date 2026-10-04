"""Routes: clock, employers, members, coverage windows, providers, snapshots, matches, consents."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, _parse_dt
from errors import fail
from common import (envelope, paginate, body, auth, require_role,
                    check_member_scope, sweep_consent_expiry, refresh_consent,
                    cascade_record_retrieval_loss, touch, clock_iso)
from helpers import (new_entity, get_or_404, req_str, opt_str, req_int, req_bool,
                     req_num, req_enum, opt_enum, parse_date)
from calcs import provider_quality_score, provider_matches

bp = Blueprint("core", __name__)


# ---- logical clock ---------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth_user, role = auth()
    require_role(role, {"PlatformAdmin"})
    data = body()
    to = req_str(data, "to_iso8601")
    db.clock = _parse_dt(to)
    sweep_consent_expiry()
    return envelope({"current_utc": clock_iso()})


# ---- employers -------------------------------------------------------------

@bp.post("/care/employers")
def create_employer():
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin"})
    data = body()
    e = new_entity({
        "name": req_str(data, "name"),
        "pepm_fee_cents": req_int(data, "pepm_fee_cents"),
        "avg_in_out_cost_delta_cents": req_int(data, "avg_in_out_cost_delta_cents"),
        "emo_benefit_enabled": req_bool(data, "emo_benefit_enabled"),
    })
    db.employers[e["id"]] = e
    return envelope(e, status=201)


@bp.get("/care/employers/<eid>")
def get_employer(eid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin", "EmployerAdmin"})
    return envelope(get_or_404(db.employers, eid, "employer"))


@bp.get("/care/employers/<eid>/members")
def list_employer_members(eid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin", "EmployerAdmin"})
    get_or_404(db.employers, eid, "employer")
    items = [m for m in db.members.values() if m["employer_id"] == eid]
    es = request.args.get("eligibility_status")
    if es is not None:
        if es not in ("ACTIVE", "INACTIVE"):
            fail("ERR_INVALID_REQUEST", "invalid eligibility_status filter")
        items = [m for m in items if m["eligibility_status"] == es]
    rel = request.args.get("relationship")
    if rel is not None:
        if rel not in ("SELF", "SPOUSE", "CHILD"):
            fail("ERR_INVALID_REQUEST", "invalid relationship filter")
        items = [m for m in items if m["relationship"] == rel]
    items.sort(key=lambda m: m["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


# ---- members ---------------------------------------------------------------

@bp.post("/care/employers/<eid>/members")
def create_member(eid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin"})
    data = body()
    relationship = req_enum(data, "relationship", {"SELF", "SPOUSE", "CHILD"})
    subscriber_id = opt_str(data, "subscriber_id")
    if relationship != "SELF" and not subscriber_id:
        fail("ERR_INVALID_REQUEST", "subscriber_id required for dependents")
    full_name = req_str(data, "full_name")
    dob = req_str(data, "date_of_birth")
    ext_ref = req_str(data, "external_member_ref")
    ded_limit = req_int(data, "deductible_limit_cents")
    oop_max = req_int(data, "oop_max_cents")
    employer = get_or_404(db.employers, eid, "employer")
    if subscriber_id is not None:
        sub = db.members.get(subscriber_id)
        if sub is None:
            fail("ERR_NOT_FOUND", "subscriber not found")
    for m in db.members.values():
        if m["employer_id"] == eid and m["external_member_ref"] == ext_ref:
            fail("ERR_DUPLICATE_MEMBER_REF", "external_member_ref already loaded for this employer")
    m = new_entity({
        "employer_id": eid,
        "subscriber_id": subscriber_id,
        "relationship": relationship,
        "full_name": full_name,
        "date_of_birth": dob,
        "external_member_ref": ext_ref,
        "eligibility_status": "ACTIVE",
        "deductible_limit_cents": ded_limit,
        "oop_max_cents": oop_max,
        "deductible_used_cents": 0,
        "oop_used_cents": 0,
    })
    db.members[m["id"]] = m
    return envelope(m, status=201)


@bp.get("/care/members/<mid>")
def get_member(mid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "EmployerAdmin", "Member", "NurseNavigator",
                        "CareAdvocate", "PhysicianAdvisor", "RecordsSpecialist",
                        "ExpertReviewer", "BillingAdvocate", "PlanAdministrator"})
    m = get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    return envelope(m)


@bp.get("/care/members/<mid>/dependents")
def list_dependents(mid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "EmployerAdmin", "Member", "NurseNavigator", "CareAdvocate"})
    get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    items = [m for m in db.members.values() if m.get("subscriber_id") == mid]
    items.sort(key=lambda m: m["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.post("/care/members/<mid>/deactivate")
def deactivate_member(mid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin"})
    m = get_or_404(db.members, mid, "member")
    if m["eligibility_status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "member is not ACTIVE")
    m["eligibility_status"] = "INACTIVE"
    touch(m)
    return envelope(m)


@bp.post("/care/members/<mid>/reactivate")
def reactivate_member(mid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin"})
    m = get_or_404(db.members, mid, "member")
    if m["eligibility_status"] != "INACTIVE":
        fail("ERR_INVALID_STATE", "member is not INACTIVE")
    m["eligibility_status"] = "ACTIVE"
    touch(m)
    return envelope(m)


# ---- coverage windows ------------------------------------------------------

@bp.post("/care/members/<mid>/coverage-windows")
def create_coverage_window(mid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin"})
    data = body()
    tier = req_enum(data, "coverage_tier",
                    {"EMPLOYEE_ONLY", "EMPLOYEE_SPOUSE", "EMPLOYEE_CHILDREN", "FAMILY"})
    start_s = req_str(data, "effective_start")
    end_s = opt_str(data, "effective_end")
    if "expected_member_version" not in data or not isinstance(data["expected_member_version"], int):
        fail("ERR_INVALID_REQUEST", "expected_member_version is required")
    expected_version = data["expected_member_version"]
    start = parse_date(start_s, "effective_start")
    end = parse_date(end_s, "effective_end") if end_s is not None else None
    m = get_or_404(db.members, mid, "member")
    # overlap check (closed-interval semantics) against ALL existing windows
    for w in db.coverage_windows.values():
        if w["member_id"] != mid:
            continue
        w_start = parse_date(w["effective_start"], "effective_start")
        w_end = parse_date(w["effective_end"], "effective_end") if w["effective_end"] else None
        new_end = end  # None = open-ended, extends forever
        overlap = (new_end is None or w_start <= new_end) and (w_end is None or start <= w_end)
        if overlap:
            # open-ended supersede of the prior OPEN window is legitimate: the
            # prior OPEN window is auto-closed the day before the new start, so
            # a new open-ended window overlapping ONLY that prior OPEN window is
            # allowed; overlapping CLOSED windows is never allowed.
            if end_s is None and w["status"] == "OPEN":
                continue
            fail("ERR_COVERAGE_OVERLAP", "coverage window overlaps an existing window")
    # OCC
    if expected_version != m["version"]:
        fail("ERR_STALE_VERSION", "expected_member_version does not match current member version")
    # supersede prior OPEN window when new window is open-ended
    if end_s is None:
        for w in db.coverage_windows.values():
            if w["member_id"] == mid and w["status"] == "OPEN":
                prior_start = parse_date(w["effective_start"], "effective_start")
                if start > prior_start:
                    w["effective_end"] = (start - timedelta(days=1)).isoformat()
                    w["status"] = "CLOSED"
                    touch(w)
    w = new_entity({
        "member_id": mid,
        "coverage_tier": tier,
        "effective_start": start_s,
        "effective_end": end_s,
        "status": "OPEN",
    })
    db.coverage_windows[w["id"]] = w
    touch(m)
    return envelope(w, status=201)


@bp.get("/care/members/<mid>/coverage-windows")
def list_coverage_windows(mid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "EmployerAdmin", "Member", "CareAdvocate"})
    get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    items = [w for w in db.coverage_windows.values() if w["member_id"] == mid]
    st = request.args.get("status")
    if st is not None:
        if st not in ("OPEN", "CLOSED"):
            fail("ERR_INVALID_REQUEST", "invalid status filter")
        items = [w for w in items if w["status"] == st]
    items.sort(key=lambda w: w["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.post("/care/coverage-windows/<wid>/terminate")
def terminate_window(wid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin"})
    data = body()
    terminated_on_s = req_str(data, "terminated_on")
    terminated_on = parse_date(terminated_on_s, "terminated_on")
    w = get_or_404(db.coverage_windows, wid, "coverage window")
    if w["status"] != "OPEN":
        fail("ERR_WINDOW_NOT_OPEN", "coverage window is not OPEN")
    if terminated_on < parse_date(w["effective_start"], "effective_start"):
        fail("ERR_INVALID_REQUEST", "terminated_on precedes effective_start")
    w["effective_end"] = terminated_on_s
    w["status"] = "CLOSED"
    touch(w)
    return envelope(w)


# ---- providers / snapshots / matches ---------------------------------------

@bp.post("/care/providers")
def create_provider():
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin"})
    data = body()
    p = new_entity({
        "name": req_str(data, "name"),
        "specialty": req_str(data, "specialty"),
        "network_status": req_enum(data, "network_status", {"IN_NETWORK", "OUT_OF_NETWORK"}),
    })
    db.providers[p["id"]] = p
    return envelope(p, status=201)


@bp.get("/care/providers/<pid>")
def get_provider(pid):
    auth()
    require_role(request.headers.get("X-User-Role"),
                 {"PlatformAdmin", "EmployerAdmin", "Member", "NurseNavigator",
                  "CareAdvocate", "PhysicianAdvisor"})
    return envelope(get_or_404(db.providers, pid, "provider"))


@bp.post("/care/providers/<pid>/quality-snapshots")
def create_snapshot(pid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin"})
    data = body()
    period_start = req_str(data, "period_start")
    period_end = req_str(data, "period_end")
    outcome = req_num(data, "outcome_score")
    cost_eff = req_num(data, "cost_efficiency_score")
    access = req_num(data, "access_score")
    volume = req_int(data, "claims_volume")
    get_or_404(db.providers, pid, "provider")
    for s in db.quality_snapshots.values():
        if s["provider_id"] == pid and s["period_start"] == period_start:
            fail("ERR_DUPLICATE_SNAPSHOT", "snapshot already exists for (provider_id, period_start)")
    composite = provider_quality_score(outcome, cost_eff, access, volume)
    s = new_entity({
        "provider_id": pid,
        "period_start": period_start,
        "period_end": period_end,
        "outcome_score": outcome,
        "cost_efficiency_score": cost_eff,
        "access_score": access,
        "claims_volume": volume,
        "composite_quality_score": composite,
    })
    db.quality_snapshots[s["id"]] = s
    return envelope(s, status=201)


@bp.get("/care/providers/<pid>/quality-snapshots")
def list_snapshots(pid):
    auth()
    require_role(request.headers.get("X-User-Role"),
                 {"PlatformAdmin", "NurseNavigator", "CareAdvocate", "PhysicianAdvisor", "Member"})
    get_or_404(db.providers, pid, "provider")
    items = [s for s in db.quality_snapshots.values() if s["provider_id"] == pid]
    items.sort(key=lambda s: s["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.get("/care/members/<mid>/provider-matches")
def get_provider_matches(mid):
    user_id, role = auth()
    require_role(role, {"Member", "NurseNavigator", "CareAdvocate", "PhysicianAdvisor"})
    get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    specialty = request.args.get("specialty")
    if not specialty:
        fail("ERR_INVALID_REQUEST", "specialty query parameter is required")
    rows = provider_matches(mid, specialty)
    page, meta = paginate(rows)
    return envelope(page, "array", meta)


# ---- consents --------------------------------------------------------------

@bp.post("/care/members/<mid>/consents")
def create_consent(mid):
    user_id, role = auth()
    require_role(role, {"Member"})
    data = body()
    scope = req_enum(data, "scope", {"RECORD_RETRIEVAL", "APPOINTMENT_BOOKING", "EMO_REVIEW", "BILLING_ADVOCACY"})
    expires_at = req_str(data, "expires_at")
    m = get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    if m["eligibility_status"] != "ACTIVE":
        fail("ERR_MEMBER_INELIGIBLE", "member is not ACTIVE")
    sweep_consent_expiry()
    for c in db.consents.values():
        if c["member_id"] == mid and c["scope"] == scope and c["status"] == "ACTIVE":
            fail("ERR_CONSENT_ALREADY_ACTIVE", "an ACTIVE consent already exists for this scope")
    c = new_entity({
        "member_id": mid,
        "scope": scope,
        "expires_at": expires_at,
        "status": "ACTIVE",
        "revoked_at": None,
    })
    db.consents[c["id"]] = c
    refresh_consent(c)
    return envelope(c, status=201)


@bp.get("/care/members/<mid>/consents")
def list_consents(mid):
    user_id, role = auth()
    require_role(role, {"Member", "PlatformAdmin", "NurseNavigator", "CareAdvocate",
                        "RecordsSpecialist", "BillingAdvocate"})
    get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    sweep_consent_expiry()
    items = [c for c in db.consents.values() if c["member_id"] == mid]
    scope = request.args.get("scope")
    if scope is not None:
        items = [c for c in items if c["scope"] == scope]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    items.sort(key=lambda c: c["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.post("/care/consents/<cid>/revoke")
def revoke_consent(cid):
    user_id, role = auth()
    require_role(role, {"Member"})
    c = get_or_404(db.consents, cid, "consent")
    check_member_scope(c["member_id"], user_id, role)
    refresh_consent(c)
    if c["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "consent is not ACTIVE")
    c["status"] = "REVOKED"
    from common import clock_iso
    c["revoked_at"] = clock_iso()
    touch(c)
    if c["scope"] == "RECORD_RETRIEVAL":
        cascade_record_retrieval_loss(c["member_id"])
    return envelope(c)
