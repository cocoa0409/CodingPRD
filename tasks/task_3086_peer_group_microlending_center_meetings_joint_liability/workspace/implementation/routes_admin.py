"""Routes: clock, branches, center managers, centers, peer groups, members,
training sessions, expansion plans."""
from flask import Blueprint, request

import core as C

bp = Blueprint("admin", __name__)


def ok(data, status=200, meta_extra=None):
    from app import envelope_ok
    return envelope_ok(data, status=status, meta_extra=meta_extra)


def list_response(items, serializer):
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    page, meta = C.paginate(items)
    return ok([serializer(r) for r in page], meta_extra=meta)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_clock():
    body = request.get_json(silent=True)
    C.require_fields(body, ["to_iso8601"])
    dt = C.parse_iso(body.get("to_iso8601"))
    if dt is None:
        raise C.err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO8601 timestamp")
    C.CLOCK["now"] = dt
    tally = C.sweep(dt)
    return ok({
        "current_utc": C.fmt_domain(dt),
        "loans_delinquent": tally["loans_delinquent"],
        "loans_defaulted": tally["loans_defaulted"],
        "applications_expired": tally["applications_expired"],
    })


# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------


@bp.post("/branches")
def create_branch():
    body = request.get_json(silent=True)
    C.require_fields(body, ["name"])
    name = C.require_str(body, "name")
    b = {"name": name, "active_member_count": 0, "total_manager_caseload": 0}
    C.stamp_new(b)
    C.STORE["branches"][b["id"]] = b
    return ok(C.ser_branch(b), status=201)


@bp.get("/branches/<bid>")
def get_branch(bid):
    b = C.lookup("branches", bid, "ERR_BRANCH_NOT_FOUND")
    return ok(C.ser_branch(b))


@bp.get("/branches/<bid>/center-managers")
def list_branch_managers(bid):
    C.lookup("branches", bid, "ERR_BRANCH_NOT_FOUND")
    mgs = [m for m in C.STORE["center_managers"].values() if m["branch_id"] == bid]
    return list_response(mgs, C.ser_manager)


@bp.get("/branches/<bid>/expansion-plans")
def list_branch_plans(bid):
    C.lookup("branches", bid, "ERR_BRANCH_NOT_FOUND")
    plans = [p for p in C.STORE["branch_expansion_plans"].values() if p["branch_id"] == bid]
    return list_response(plans, C.ser_plan)


@bp.post("/branches/<bid>/expansion-plans")
def create_plan(bid):
    b = C.lookup("branches", bid, "ERR_BRANCH_NOT_FOUND")
    body = request.get_json(silent=True)
    C.require_fields(body, ["new_centers", "new_managers_hired", "target_new_members"])
    new_centers = C.require_int(body, "new_centers")
    new_managers = C.require_int(body, "new_managers_hired")
    target_members = C.require_int(body, "target_new_members")
    if new_centers < 1 or new_managers < 0 or target_members < 0:
        raise C.err("ERR_INVALID_REQUEST", "Expansion plan inputs out of range")
    m = b["active_member_count"]
    tier = C.branch_tier(b)
    member_cap = C.MEMBER_CAP[tier]
    center_cap = C.CENTER_CAP[tier]
    mgrs = sum(1 for mg in C.STORE["center_managers"].values()
               if mg["branch_id"] == bid) + new_managers
    current_centers = sum(1 for c in C.STORE["centers"].values() if c["branch_id"] == bid)
    available_member_capacity = mgrs * member_cap
    available_center_slots = mgrs * center_cap - current_centers
    required_member_capacity = m + target_members
    required_center_slots = new_centers
    feasible = (required_member_capacity <= available_member_capacity
                and required_center_slots <= available_center_slots)
    if not feasible:
        raise C.err("ERR_EXPANSION_INFEASIBLE", "Expansion plan is not feasible")
    p = {
        "branch_id": bid,
        "new_centers": new_centers,
        "new_managers_hired": new_managers,
        "target_new_members": target_members,
        "feasibility": {
            "required_member_capacity": required_member_capacity,
            "available_member_capacity": available_member_capacity,
            "required_center_slots": required_center_slots,
            "available_center_slots": available_center_slots,
            "feasible": True,
        },
        "status": "SUBMITTED",
    }
    C.stamp_new(p)
    C.STORE["branch_expansion_plans"][p["id"]] = p
    return ok(C.ser_plan(p), status=201)


@bp.post("/expansion-plans/<pid>/decide")
def decide_plan(pid):
    p = C.lookup("branch_expansion_plans", pid, "ERR_PLAN_NOT_FOUND")
    if p["status"] != "SUBMITTED":
        raise C.err("ERR_PLAN_NOT_SUBMITTED", "Plan is not SUBMITTED")
    body = request.get_json(silent=True)
    C.require_fields(body, ["decision"])
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise C.err("ERR_INVALID_REQUEST", "decision must be APPROVE or REJECT")
    p["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    C.touch(p)
    return ok(C.ser_plan(p))


# ---------------------------------------------------------------------------
# Center managers
# ---------------------------------------------------------------------------


@bp.post("/center-managers")
def create_manager():
    body = request.get_json(silent=True)
    C.require_fields(body, ["branch_id", "full_name", "hired_on"])
    branch_id = body.get("branch_id")
    if not C.is_str(branch_id):
        raise C.err("ERR_INVALID_REQUEST", "branch_id must be a string")
    full_name = C.require_str(body, "full_name")
    hired_on = body.get("hired_on")
    if not C.is_str(hired_on):
        raise C.err("ERR_INVALID_REQUEST", "hired_on must be a string")
    C.lookup("branches", branch_id, "ERR_BRANCH_NOT_FOUND")
    mg = {"branch_id": branch_id, "full_name": full_name, "hired_on": hired_on,
          "current_caseload": 0}
    C.stamp_new(mg)
    C.STORE["center_managers"][mg["id"]] = mg
    return ok(C.ser_manager(mg), status=201)


@bp.get("/center-managers/<mid>")
def get_manager(mid):
    mg = C.lookup("center_managers", mid, "ERR_CENTER_MANAGER_NOT_FOUND")
    return ok(C.ser_manager(mg))


@bp.get("/center-managers/<mid>/training-sessions")
def list_manager_sessions(mid):
    C.lookup("center_managers", mid, "ERR_CENTER_MANAGER_NOT_FOUND")
    sessions = [s for s in C.STORE["training_sessions"].values()
                if s["center_manager_id"] == mid]
    return list_response(sessions, C.ser_session)


# ---------------------------------------------------------------------------
# Centers
# ---------------------------------------------------------------------------


def check_manager_caps(branch, manager_id, excluding_center_id=None):
    tier = C.branch_tier(branch)
    center_count = sum(1 for c in C.STORE["centers"].values()
                       if c["center_manager_id"] == manager_id
                       and c["id"] != excluding_center_id)
    if center_count + 1 > C.CENTER_CAP[tier]:
        raise C.err("ERR_CASELOAD_CAP_EXCEEDED", "Manager center cap exceeded")
    caseload = 0
    for c in C.STORE["centers"].values():
        if c["center_manager_id"] == manager_id and c["id"] != excluding_center_id:
            for g in C.STORE["peer_groups"].values():
                if g["center_id"] == c["id"]:
                    caseload += sum(1 for m in C.group_members(g["id"])
                                    if m["status"] in C.COUNTED_MEMBER_STATUSES)
    if caseload > C.MEMBER_CAP[tier]:
        raise C.err("ERR_CASELOAD_CAP_EXCEEDED", "Manager member cap exceeded")


@bp.post("/centers")
def create_center():
    body = request.get_json(silent=True)
    C.require_fields(body, ["branch_id", "center_manager_id", "name", "meeting_day_of_week"])
    branch_id = body.get("branch_id")
    manager_id = body.get("center_manager_id")
    if not C.is_str(branch_id) or not C.is_str(manager_id):
        raise C.err("ERR_INVALID_REQUEST", "branch_id and center_manager_id must be strings")
    name = C.require_str(body, "name")
    mdow = C.require_int(body, "meeting_day_of_week")
    if mdow < 0 or mdow > 6:
        raise C.err("ERR_INVALID_REQUEST", "meeting_day_of_week must be 0..6")
    branch = C.lookup("branches", branch_id, "ERR_BRANCH_NOT_FOUND")
    mg = C.lookup("center_managers", manager_id, "ERR_CENTER_MANAGER_NOT_FOUND")
    if mg["branch_id"] != branch_id:
        raise C.err("ERR_INVALID_REQUEST", "center_manager_id does not belong to branch_id")
    check_manager_caps(branch, manager_id)
    c = {"branch_id": branch_id, "center_manager_id": manager_id, "name": name,
         "meeting_day_of_week": mdow}
    C.stamp_new(c)
    C.STORE["centers"][c["id"]] = c
    return ok(C.ser_center(c), status=201)


@bp.get("/centers")
def list_centers():
    items = list(C.STORE["centers"].values())
    branch_id = request.args.get("branch_id")
    manager_id = request.args.get("center_manager_id")
    if branch_id is not None:
        items = [c for c in items if c["branch_id"] == branch_id]
    if manager_id is not None:
        items = [c for c in items if c["center_manager_id"] == manager_id]
    return list_response(items, C.ser_center)


@bp.get("/centers/<cid>")
def get_center(cid):
    c = C.lookup("centers", cid, "ERR_CENTER_NOT_FOUND")
    return ok(C.ser_center(c))


@bp.patch("/centers/<cid>")
def reassign_center(cid):
    c = C.lookup("centers", cid, "ERR_CENTER_NOT_FOUND")
    body = request.get_json(silent=True)
    C.require_fields(body, ["center_manager_id"])
    manager_id = body.get("center_manager_id")
    if not C.is_str(manager_id):
        raise C.err("ERR_INVALID_REQUEST", "center_manager_id must be a string")
    mg = C.lookup("center_managers", manager_id, "ERR_CENTER_MANAGER_NOT_FOUND")
    if mg["branch_id"] != c["branch_id"]:
        raise C.err("ERR_INVALID_REQUEST", "center_manager_id does not belong to the center's branch")
    branch = C.STORE["branches"][c["branch_id"]]
    check_manager_caps(branch, manager_id, excluding_center_id=cid)
    c["center_manager_id"] = manager_id
    C.touch(c)
    C.recompute_caseloads(branch["id"])
    return ok(C.ser_center(c))


@bp.get("/centers/<cid>/peer-groups")
def list_center_groups(cid):
    C.lookup("centers", cid, "ERR_CENTER_NOT_FOUND")
    groups = [g for g in C.STORE["peer_groups"].values() if g["center_id"] == cid]
    return list_response(groups, C.ser_group)


# ---------------------------------------------------------------------------
# Peer groups
# ---------------------------------------------------------------------------


@bp.post("/peer-groups")
def create_group():
    body = request.get_json(silent=True)
    C.require_fields(body, ["center_id", "name"])
    center_id = body.get("center_id")
    if not C.is_str(center_id):
        raise C.err("ERR_INVALID_REQUEST", "center_id must be a string")
    name = C.require_str(body, "name")
    C.lookup("centers", center_id, "ERR_CENTER_NOT_FOUND")
    g = {"center_id": center_id, "name": name, "status": "FORMING",
         "member_count": 0, "completed_training_sessions": 0,
         "delinquent_loan_count": 0}
    C.stamp_new(g)
    C.STORE["peer_groups"][g["id"]] = g
    return ok(C.ser_group(g), status=201)


@bp.get("/peer-groups")
def list_groups():
    items = list(C.STORE["peer_groups"].values())
    center_id = request.args.get("center_id")
    status = request.args.get("status")
    if center_id is not None:
        items = [g for g in items if g["center_id"] == center_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    return list_response(items, C.ser_group)


@bp.get("/peer-groups/<gid>")
def get_group(gid):
    g = C.lookup("peer_groups", gid, "ERR_PEER_GROUP_NOT_FOUND")
    return ok(C.ser_group(g))


@bp.get("/peer-groups/<gid>/members")
def list_group_members(gid):
    C.lookup("peer_groups", gid, "ERR_PEER_GROUP_NOT_FOUND")
    members = C.group_members(gid)
    return list_response(members, C.ser_member)


@bp.get("/peer-groups/<gid>/training-sessions")
def list_group_sessions(gid):
    C.lookup("peer_groups", gid, "ERR_PEER_GROUP_NOT_FOUND")
    sessions = [s for s in C.STORE["training_sessions"].values()
                if s["peer_group_id"] == gid]
    return list_response(sessions, C.ser_session)


def is_blacklist_screened(member):
    if member["status"] == "BLACKLISTED":
        return True
    for r in C.STORE["credit_bureau_reports"].values():
        if r["member_id"] == member["id"] and r["report_type"] == "FINAL" \
                and r["score_reported"] < 300:
            return True
    return False


@bp.post("/peer-groups/<gid>/members")
def add_group_member(gid):
    g = C.lookup("peer_groups", gid, "ERR_PEER_GROUP_NOT_FOUND")
    body = request.get_json(silent=True)
    C.require_fields(body, ["member_id"])
    member_id = body.get("member_id")
    if not C.is_str(member_id):
        raise C.err("ERR_INVALID_REQUEST", "member_id must be a string")
    m = C.lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    # Compliance gate: blacklist screen fires before any membership check.
    if is_blacklist_screened(m):
        raise C.err("ERR_MEMBER_BLACKLISTED", "Member is blacklisted")
    if m["status"] != "RECRUITED":
        raise C.err("ERR_MEMBER_NOT_RECRUITED", "Member is not RECRUITED")
    if m.get("peer_group_id") is not None:
        raise C.err("ERR_MEMBER_ALREADY_IN_GROUP", "Member already belongs to a group")
    if g["status"] not in ("FORMING", "TRAINING"):
        raise C.err("ERR_GROUP_NOT_FORMING", "Group is not FORMING or TRAINING")
    if g["member_count"] >= 5:
        raise C.err("ERR_GROUP_FULL", "Group already has 5 members")
    m["peer_group_id"] = g["id"]
    m["status"] = "IN_TRAINING"
    C.touch(m)
    C.recompute_group_member_count(g)
    C.touch(g)
    C.recompute_caseloads(m["branch_id"])
    return ok(C.ser_member(m), status=201)


@bp.post("/peer-groups/<gid>/dissolve")
def dissolve_group(gid):
    g = C.lookup("peer_groups", gid, "ERR_PEER_GROUP_NOT_FOUND")
    if g["status"] not in ("ACTIVE", "RESTRICTED"):
        raise C.err("ERR_INVALID_STATE", "Only ACTIVE or RESTRICTED groups may be dissolved")
    for m in C.group_members(gid):
        for l in C.STORE["loans"].values():
            if l["member_id"] == m["id"] and l["status"] in ("ACTIVE", "DELINQUENT"):
                raise C.err("ERR_GROUP_HAS_ACTIVE_LOANS",
                            "A group member has a loan in ACTIVE or DELINQUENT")
    g["status"] = "DISSOLVED"
    C.touch(g)
    center = C.group_center(g)
    if center is not None:
        C.recompute_caseloads(center["branch_id"])
    return ok(C.ser_group(g))


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


@bp.post("/members")
def create_member():
    body = request.get_json(silent=True)
    C.require_fields(body, ["branch_id", "full_name", "national_id"])
    branch_id = body.get("branch_id")
    if not C.is_str(branch_id):
        raise C.err("ERR_INVALID_REQUEST", "branch_id must be a string")
    full_name = C.require_str(body, "full_name")
    national_id = C.require_str(body, "national_id")
    C.lookup("branches", branch_id, "ERR_BRANCH_NOT_FOUND")
    for m in C.STORE["members"].values():
        if m["national_id"] == national_id:
            raise C.err("ERR_INVALID_REQUEST", "national_id must be globally unique")
    m = {"branch_id": branch_id, "full_name": full_name, "national_id": national_id,
         "peer_group_id": None, "status": "RECRUITED", "cycle_level": 1,
         "cured_delinquency_count": 0, "consecutive_absence_streak": 0,
         "attendance_strikes": 0}
    C.stamp_new(m)
    C.STORE["members"][m["id"]] = m
    return ok(C.ser_member(m), status=201)


@bp.get("/members")
def list_members():
    items = list(C.STORE["members"].values())
    branch_id = request.args.get("branch_id")
    group_id = request.args.get("peer_group_id")
    status = request.args.get("status")
    if branch_id is not None:
        items = [m for m in items if m["branch_id"] == branch_id]
    if group_id is not None:
        items = [m for m in items if m.get("peer_group_id") == group_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return list_response(items, C.ser_member)


@bp.get("/members/<mid>")
def get_member(mid):
    m = C.lookup("members", mid, "ERR_MEMBER_NOT_FOUND")
    return ok(C.ser_member(m))


@bp.get("/members/<mid>/votes")
def list_member_votes(mid):
    C.lookup("members", mid, "ERR_MEMBER_NOT_FOUND")
    votes = [v for v in C.STORE["consensus_votes"].values() if v["voter_member_id"] == mid]
    return list_response(votes, C.ser_vote)


@bp.get("/members/<mid>/attendance")
def list_member_attendance(mid):
    C.lookup("members", mid, "ERR_MEMBER_NOT_FOUND")
    rows = [a for a in C.STORE["meeting_attendance"].values() if a["member_id"] == mid]
    return list_response(rows, C.ser_attendance)


@bp.get("/members/<mid>/bureau-reports")
def list_member_reports(mid):
    C.lookup("members", mid, "ERR_MEMBER_NOT_FOUND")
    reports = [r for r in C.STORE["credit_bureau_reports"].values() if r["member_id"] == mid]
    return list_response(reports, C.ser_report)


# ---------------------------------------------------------------------------
# Savings accounts
# ---------------------------------------------------------------------------


@bp.get("/members/<mid>/savings-account")
def get_member_account(mid):
    C.lookup("members", mid, "ERR_MEMBER_NOT_FOUND")
    account = C.member_savings_account(mid)
    items = [account] if account is not None else []
    return list_response(items, C.ser_account)


@bp.post("/members/<mid>/savings/withdrawals")
def withdraw(mid):
    m = C.lookup("members", mid, "ERR_MEMBER_NOT_FOUND")
    body = request.get_json(silent=True)
    C.require_fields(body, ["amount_cents"])
    amount = C.require_int(body, "amount_cents")
    account = C.member_savings_account(mid)
    if account is None:
        raise C.err("ERR_ACCOUNT_NOT_FOUND", "Member has no SavingsAccount")
    if account["status"] != "OPEN":
        raise C.err("ERR_ACCOUNT_NOT_OPEN", "Savings account is not OPEN")
    C.recompute_savings(account)
    if amount > account["withdrawable_cents"]:
        raise C.err("ERR_WITHDRAWAL_EXCEEDS_AVAILABLE",
                    "amount_cents exceeds withdrawable_cents")
    C.STORE["withdrawals"].append({"member_id": mid, "amount_cents": amount})
    C.recompute_savings(account)
    C.touch(account)
    return ok(C.ser_account(account))


@bp.post("/members/<mid>/savings/unfreeze")
def unfreeze(mid):
    m = C.lookup("members", mid, "ERR_MEMBER_NOT_FOUND")
    account = C.member_savings_account(mid)
    if account is None:
        raise C.err("ERR_ACCOUNT_NOT_FOUND", "Member has no SavingsAccount")
    if account["status"] != "FROZEN":
        raise C.err("ERR_ACCOUNT_NOT_FROZEN", "Savings account is not FROZEN")
    account["status"] = "OPEN"
    C.recompute_savings(account)
    C.touch(account)
    return ok(C.ser_account(account))


@bp.post("/members/<mid>/savings/close")
def close_account(mid):
    m = C.lookup("members", mid, "ERR_MEMBER_NOT_FOUND")
    account = C.member_savings_account(mid)
    if account is None:
        raise C.err("ERR_ACCOUNT_NOT_FOUND", "Member has no SavingsAccount")
    if account["status"] != "OPEN":
        raise C.err("ERR_ACCOUNT_NOT_OPEN", "Savings account is not OPEN")
    for l in C.STORE["loans"].values():
        if l["member_id"] == mid and l["status"] in ("ACTIVE", "DELINQUENT"):
            raise C.err("ERR_MEMBER_HAS_ACTIVE_LOAN",
                        "Member has a loan in ACTIVE or DELINQUENT")
    C.recompute_savings(account)
    if account["balance_cents"] != 0:
        raise C.err("ERR_ACCOUNT_NOT_EMPTY", "Savings account balance is not zero")
    account["status"] = "CLOSED"
    C.touch(account)
    return ok(C.ser_account(account))


# ---------------------------------------------------------------------------
# Group training sessions
# ---------------------------------------------------------------------------


def training_overlaps(manager_id, start_dt, end_dt, excluding_id=None):
    from datetime import timedelta
    pad = timedelta(minutes=C.TRAINING_BUFFER_MINUTES)
    new_lo = start_dt - pad
    new_hi = end_dt + pad
    for s in C.STORE["training_sessions"].values():
        if s["center_manager_id"] != manager_id or s["id"] == excluding_id:
            continue
        if s["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        ex_lo = s["start_dt"] - pad
        ex_hi = s["end_dt"] + pad
        if new_lo <= ex_hi and ex_lo <= new_hi:
            return True
    return False


@bp.post("/group-training-sessions")
def create_session():
    body = request.get_json(silent=True)
    C.require_fields(body, ["peer_group_id", "center_manager_id", "start_time", "end_time"])
    group_id = body.get("peer_group_id")
    manager_id = body.get("center_manager_id")
    if not C.is_str(group_id) or not C.is_str(manager_id):
        raise C.err("ERR_INVALID_REQUEST",
                    "peer_group_id and center_manager_id must be strings")
    start_dt = C.parse_iso(body.get("start_time"))
    end_dt = C.parse_iso(body.get("end_time"))
    if start_dt is None or end_dt is None:
        raise C.err("ERR_INVALID_REQUEST", "start_time and end_time must be ISO8601 timestamps")
    g = C.lookup("peer_groups", group_id, "ERR_PEER_GROUP_NOT_FOUND")
    C.lookup("center_managers", manager_id, "ERR_CENTER_MANAGER_NOT_FOUND")
    center = C.group_center(g)
    if center is None or center["center_manager_id"] != manager_id:
        raise C.err("ERR_MANAGER_CENTER_MISMATCH",
                    "center_manager_id differs from the group center's manager")
    if end_dt <= start_dt:
        raise C.err("ERR_INVALID_TIME_RANGE", "end_time must be strictly after start_time")
    if training_overlaps(manager_id, start_dt, end_dt):
        raise C.err("ERR_TRAINING_SLOT_OVERLAP", "Training slot overlaps an existing session")
    first_session = not any(s for s in C.STORE["training_sessions"].values()
                            if s["peer_group_id"] == group_id)
    if first_session:
        if g["status"] != "FORMING":
            raise C.err("ERR_GROUP_NOT_FORMING", "First training session requires group FORMING")
        if g["member_count"] != 5:
            raise C.err("ERR_GROUP_SIZE_INVALID", "First training session requires exactly 5 members")
    s = {"peer_group_id": group_id, "center_manager_id": manager_id,
         "start_dt": start_dt, "end_dt": end_dt, "status": "SCHEDULED"}
    C.stamp_new(s)
    C.STORE["training_sessions"][s["id"]] = s
    if first_session:
        g["status"] = "TRAINING"
        C.touch(g)
    return ok(C.ser_session(s), status=201)


@bp.get("/group-training-sessions")
def list_sessions():
    items = list(C.STORE["training_sessions"].values())
    group_id = request.args.get("peer_group_id")
    manager_id = request.args.get("center_manager_id")
    if group_id is not None:
        items = [s for s in items if s["peer_group_id"] == group_id]
    if manager_id is not None:
        items = [s for s in items if s["center_manager_id"] == manager_id]
    return list_response(items, C.ser_session)


@bp.post("/group-training-sessions/<sid>/complete")
def complete_session(sid):
    s = C.lookup("training_sessions", sid, "ERR_TRAINING_SESSION_NOT_FOUND")
    if s["status"] != "SCHEDULED":
        raise C.err("ERR_TRAINING_NOT_SCHEDULED", "Session is not SCHEDULED")
    s["status"] = "COMPLETED"
    C.touch(s)
    g = C.STORE["peer_groups"].get(s["peer_group_id"])
    if g is not None:
        g["completed_training_sessions"] += 1
        C.touch(g)
        if g["completed_training_sessions"] >= 2 and g["member_count"] == 5 \
                and g["status"] == "TRAINING":
            g["status"] = "ACTIVE"
            C.touch(g)
            for m in C.group_members(g["id"]):
                if m["status"] == "IN_TRAINING":
                    m["status"] = "ELIGIBLE"
                    C.touch(m)
    return ok(C.ser_session(s))


@bp.post("/group-training-sessions/<sid>/cancel")
def cancel_session(sid):
    s = C.lookup("training_sessions", sid, "ERR_TRAINING_SESSION_NOT_FOUND")
    if s["status"] != "SCHEDULED":
        raise C.err("ERR_TRAINING_NOT_SCHEDULED", "Session is not SCHEDULED")
    s["status"] = "CANCELLED"
    C.touch(s)
    return ok(C.ser_session(s))
