"""Distributors, coverage assignments, sell-through reports (PRD §3.5, §3.6)."""
from flask import Blueprint, request

from core import (
    STORE, err, ok, stamp_new, touch, new_id, now_iso, current_month,
)
from derived import (
    rebate_for, recompute_attainment, suspend_distributor, terminate_distributor,
)
from validate import (
    CHANNELS,
    as_bool, as_date, as_enum, as_enum_list, as_int, as_month, as_str,
    authenticate, authorize, body, filter_eq, get_or_404, need, opt_bool, paginate,
)

bp = Blueprint("distribution", __name__)

DIST_FIELDS = [
    "id", "legal_name", "home_market_id", "channels_served", "credit_limit_cents",
    "status", "suspension_count", "attainment_actual_bps", "attainment_projected_bps",
    "quota_compliance_tier", "created_at", "updated_at", "version",
]
ASSIGN_FIELDS = [
    "id", "distributor_id", "market_id", "product_line_id", "channel", "exclusive",
    "starts_on", "ends_on", "annual_quota_units", "status", "supersedes_assignment_id",
    "created_at", "updated_at", "version",
]
REPORT_FIELDS = [
    "id", "distributor_id", "coverage_assignment_id", "period_month", "units_sold",
    "units_returned", "net_units", "created_at",
]


def dist_json(d):
    return {k: d.get(k) for k in DIST_FIELDS}


def assign_json(a):
    return {k: a.get(k) for k in ASSIGN_FIELDS}


def report_json(r):
    return {k: r.get(k) for k in REPORT_FIELDS}


def _cell_overlap(a_starts, a_ends, b_starts, b_ends):
    """Closed-interval overlap: touching endpoints already conflict."""
    return a_starts <= b_ends and b_starts <= a_ends


def _exclusive_conflict(candidate, exclude_id=None):
    if not candidate["exclusive"]:
        return False
    for other in STORE["assignments"].values():
        if other["id"] == exclude_id:
            continue
        if not other["exclusive"]:
            continue
        if other["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if (
            other["market_id"] == candidate["market_id"]
            and other["channel"] == candidate["channel"]
            and other["product_line_id"] == candidate["product_line_id"]
            and _cell_overlap(
                _d(candidate["starts_on"]), _d(candidate["ends_on"]),
                _d(other["starts_on"]), _d(other["ends_on"]),
            )
        ):
            return True
    return False


def _d(s):
    from core import parse_date
    return parse_date(s)


def _cell_active_count(assignment, exclude_id=None):
    count = 0
    for other in STORE["assignments"].values():
        if other["id"] == exclude_id:
            continue
        if other["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if (
            other["market_id"] == assignment["market_id"]
            and other["channel"] == assignment["channel"]
            and other["product_line_id"] == assignment["product_line_id"]
        ):
            count += 1
    return count


def _activation_gates(a, check_line_launch):
    """Shared gates for activate/resume in §2.6 category order (8,9,10,11,12)."""
    dist = STORE["distributors"].get(a["distributor_id"])
    market = STORE["markets"].get(a["market_id"])
    line = STORE["product_lines"].get(a["product_line_id"])
    # 8: distributor state
    if dist is None or dist["status"] != "APPROVED":
        err("ERR_DISTRIBUTOR_NOT_APPROVED", "Distributor is not APPROVED")
    brand = None
    if line is not None:
        brand = STORE["brands"].get(line["brand_id"])
    # 9: exclusive assignments need an OPERATING, non-CRITICAL brand (activate only)
    if check_line_launch and a["exclusive"] and brand is not None:
        if brand["status"] != "OPERATING":
            err("ERR_BRAND_IN_LOCKDOWN", "Brand is in PROTECTIVE_LOCKDOWN")
        if brand["protection_posture"] == "CRITICAL":
            err("ERR_POSTURE_CRITICAL", "Brand protection posture is CRITICAL")
    # 10: window live + exclusivity
    from core import today
    cur = today()
    if not (_d(a["starts_on"]) <= cur <= _d(a["ends_on"])):
        err("ERR_WINDOW_INVALID", "Current date is outside the coverage window")
    if a["exclusive"] and _exclusive_conflict(a, exclude_id=a["id"]):
        err("ERR_EXCLUSIVE_OVERLAP", "Overlapping exclusive assignment on the cell")
    # 11: line launched (activate only) + registration active where required
    if check_line_launch and (line is None or line["status"] != "LAUNCHED"):
        err("ERR_LINE_NOT_LAUNCHED", "Line is not LAUNCHED")
    if market is not None and market["registration_required"]:
        active_reg = any(
            r["market_id"] == a["market_id"]
            and r["product_line_id"] == a["product_line_id"]
            and r["status"] == "ACTIVE"
            for r in STORE["registrations"].values()
        )
        if not active_reg:
            err("ERR_REGISTRATION_NOT_ACTIVE", "No ACTIVE registration for market and line")
    # 12: cell capacity: a third coexists, a fourth is refused
    if _cell_active_count(a, exclude_id=a["id"]) >= 3:
        err("ERR_CELL_CAPACITY_EXCEEDED", "Cell already holds 3 active/suspended assignments")


# ---------------------------------------------------------------------------
# Distributors
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/distributors")
def create_distributor():
    _, role = authenticate()
    authorize(role, ["ChannelManager"])
    b = body()
    legal = as_str(need(b, "legal_name"), "legal_name")
    home_market_id = as_str(need(b, "home_market_id"), "home_market_id")
    channels = as_enum_list(need(b, "channels_served"), "channels_served", CHANNELS)
    credit = as_int(need(b, "credit_limit_cents"), "credit_limit_cents", minimum=1)
    if home_market_id not in STORE["markets"]:
        err("ERR_INVALID_REFERENCE", "home_market_id does not exist")
    dist = stamp_new({
        "legal_name": legal,
        "home_market_id": home_market_id,
        "channels_served": channels,
        "credit_limit_cents": credit,
        "status": "APPLICANT",
        "suspension_count": 0,
        "attainment_actual_bps": None,
        "attainment_projected_bps": None,
        "quota_compliance_tier": None,
    })
    STORE["distributors"][dist["id"]] = dist
    return ok(dist_json(dist), code=201)


@bp.get("/brand-ops/distributors")
def list_distributors():
    authenticate()
    items = list(STORE["distributors"].values())
    items = filter_eq(items, "home_market_id", request.args.get("home_market_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([dist_json(d) for d in page], response_type="array", pagination=pagination)


@bp.get("/brand-ops/distributors/<did>")
def get_distributor(did):
    authenticate()
    return ok(dist_json(get_or_404("distributors", did, "distributor")))


@bp.post("/brand-ops/distributors/<did>/approve")
def approve_distributor(did):
    _, role = authenticate()
    authorize(role, ["ChannelManager"])
    dist = get_or_404("distributors", did, "distributor")
    body()
    if dist["status"] != "APPLICANT":
        err("ERR_INVALID_STATE_TRANSITION", "Distributor is not APPLICANT")
    market = STORE["markets"].get(dist["home_market_id"])
    if market is None or market["status"] != "OPEN":
        err("ERR_MARKET_NOT_OPEN", "Home market is not OPEN")
    dist["status"] = "APPROVED"
    touch(dist)
    return ok(dist_json(dist))


@bp.post("/brand-ops/distributors/<did>/suspend")
def suspend_distributor_ep(did):
    _, role = authenticate()
    authorize(role, ["ChannelManager"])
    dist = get_or_404("distributors", did, "distributor")
    body()
    if dist["status"] != "APPROVED":
        err("ERR_INVALID_STATE_TRANSITION", "Distributor is not APPROVED")
    suspend_distributor(dist)
    return ok(dist_json(dist))


@bp.post("/brand-ops/distributors/<did>/reinstate")
def reinstate_distributor(did):
    _, role = authenticate()
    authorize(role, ["ChannelManager"])
    dist = get_or_404("distributors", did, "distributor")
    body()
    if dist["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE_TRANSITION", "Distributor is not SUSPENDED")
    dist["status"] = "APPROVED"
    touch(dist)
    return ok(dist_json(dist))


@bp.post("/brand-ops/distributors/<did>/terminate")
def terminate_distributor_ep(did):
    _, role = authenticate()
    authorize(role, ["ChannelManager"])
    dist = get_or_404("distributors", did, "distributor")
    body()
    if dist["status"] == "TERMINATED":
        err("ERR_INVALID_STATE_TRANSITION", "Distributor is already TERMINATED")
    terminate_distributor(dist)
    return ok(dist_json(dist))


@bp.get("/brand-ops/distributors/<did>/rebate-preview")
def rebate_preview(did):
    _, role = authenticate()
    authorize(role, ["ChannelManager", "PricingAnalyst", "PlatformAdmin"])
    dist = get_or_404("distributors", did, "distributor")
    raw = request.args.get("reference_unit_price_cents")
    if raw is None:
        err("ERR_INVALID_REQUEST", "reference_unit_price_cents is required")
    try:
        ref_price = int(raw)
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", "reference_unit_price_cents must be an integer")
    if ref_price < 0:
        err("ERR_INVALID_REQUEST", "reference_unit_price_cents must be >= 0")
    rebate_bps, net, estimate = rebate_for(dist, ref_price)
    return ok({
        "attainment_actual_bps": dist["attainment_actual_bps"],
        "attainment_projected_bps": dist["attainment_projected_bps"],
        "quota_compliance_tier": dist["quota_compliance_tier"],
        "rebate_bps": rebate_bps,
        "window_net_units": net,
        "rebate_estimate_cents": estimate,
    })


# ---------------------------------------------------------------------------
# Coverage assignments
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/distributors/<distributorId>/coverage-assignments")
def create_assignment(distributorId):
    _, role = authenticate()
    authorize(role, ["ChannelManager"])
    dist = get_or_404("distributors", distributorId, "distributor")
    b = body()
    market_id = as_str(need(b, "market_id"), "market_id")
    product_line_id = as_str(need(b, "product_line_id"), "product_line_id")
    channel = as_enum(need(b, "channel"), "channel", CHANNELS)
    exclusive = opt_bool(b, "exclusive", False)
    starts_on = as_date(need(b, "starts_on"), "starts_on")
    ends_on = as_date(need(b, "ends_on"), "ends_on")
    quota = as_int(need(b, "annual_quota_units"), "annual_quota_units", minimum=1)
    expected = as_int(need(b, "expected_distributor_version"), "expected_distributor_version")
    # 5: body references
    market = STORE["markets"].get(market_id)
    if market is None:
        err("ERR_INVALID_REFERENCE", "market_id does not exist")
    line = STORE["product_lines"].get(product_line_id)
    if line is None:
        err("ERR_INVALID_REFERENCE", "product_line_id does not exist")
    # 7: optimistic concurrency on the parent distributor
    if expected != dist["version"]:
        err("ERR_STALE_VERSION", "Distributor version is stale")
    # 8: distributor state
    if dist["status"] != "APPROVED":
        err("ERR_DISTRIBUTOR_NOT_APPROVED", "Distributor is not APPROVED")
    # 10: window sanity + exclusive overlap
    from core import today
    if not starts_on < ends_on:
        err("ERR_WINDOW_INVALID", "starts_on must be strictly before ends_on")
    if ends_on < today():
        err("ERR_WINDOW_INVALID", "ends_on is already past")
    cand = {
        "market_id": market_id, "channel": channel, "product_line_id": product_line_id,
        "exclusive": exclusive, "starts_on": b["starts_on"], "ends_on": b["ends_on"],
    }
    if exclusive and _exclusive_conflict(cand):
        err("ERR_EXCLUSIVE_OVERLAP", "Overlapping exclusive assignment on the cell")
    # 11: referential compatibility
    if market["status"] != "OPEN":
        err("ERR_MARKET_NOT_OPEN", "Market is not OPEN")
    if line["status"] not in ("PILOT", "LAUNCHED"):
        err("ERR_LINE_STAGE_TOO_EARLY", "Line must be PILOT or LAUNCHED")
    # 12: channel membership checks
    if channel not in dist["channels_served"]:
        err("ERR_CHANNEL_NOT_SERVED", "Channel is not served by the distributor")
    if channel not in market["allowed_channels"]:
        err("ERR_CHANNEL_NOT_ALLOWED", "Channel is not allowed by the market")
    if channel not in line["target_channels"]:
        err("ERR_CHANNEL_OUTSIDE_LINE_SCOPE", "Channel is outside the line's target channels")
    # Side effect: supersede pending proposals on the same cell
    superseded = [
        o for o in STORE["assignments"].values()
        if o["market_id"] == market_id
        and o["channel"] == channel
        and o["product_line_id"] == product_line_id
        and o["status"] == "PROPOSED"
    ]
    superseded.sort(key=lambda o: (o["created_at"], o["_seq"]))
    supersedes_id = superseded[-1]["id"] if superseded else None
    for o in superseded:
        o["status"] = "SUPERSEDED"
        touch(o)
    assignment = stamp_new({
        "distributor_id": dist["id"],
        "market_id": market_id,
        "product_line_id": product_line_id,
        "channel": channel,
        "exclusive": exclusive,
        "starts_on": b["starts_on"],
        "ends_on": b["ends_on"],
        "annual_quota_units": quota,
        "status": "PROPOSED",
        "supersedes_assignment_id": supersedes_id,
    })
    STORE["assignments"][assignment["id"]] = assignment
    touch(dist)  # OCC: successful create increments the distributor's version
    return ok(assign_json(assignment), code=201)


@bp.get("/brand-ops/coverage-assignments")
def list_assignments():
    authenticate()
    items = list(STORE["assignments"].values())
    items = filter_eq(items, "distributor_id", request.args.get("distributor_id"))
    items = filter_eq(items, "market_id", request.args.get("market_id"))
    items = filter_eq(items, "product_line_id", request.args.get("product_line_id"))
    items = filter_eq(items, "channel", request.args.get("channel"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([assign_json(a) for a in page], response_type="array", pagination=pagination)


@bp.get("/brand-ops/coverage-assignments/<aid>")
def get_assignment(aid):
    authenticate()
    return ok(assign_json(get_or_404("assignments", aid, "assignment")))


@bp.post("/brand-ops/coverage-assignments/<aid>/activate")
def activate_assignment(aid):
    _, role = authenticate()
    authorize(role, ["ChannelManager"])
    a = get_or_404("assignments", aid, "assignment")
    body()
    if a["status"] != "PROPOSED":
        err("ERR_INVALID_STATE_TRANSITION", "Assignment is not PROPOSED")
    _activation_gates(a, check_line_launch=True)
    a["status"] = "ACTIVE"
    touch(a)
    return ok(assign_json(a))


@bp.post("/brand-ops/coverage-assignments/<aid>/suspend")
def suspend_assignment(aid):
    _, role = authenticate()
    authorize(role, ["ChannelManager"])
    a = get_or_404("assignments", aid, "assignment")
    body()
    if a["status"] != "ACTIVE":
        err("ERR_INVALID_STATE_TRANSITION", "Assignment is not ACTIVE")
    a["status"] = "SUSPENDED"
    touch(a)
    dist = STORE["distributors"].get(a["distributor_id"])
    if dist is not None:
        recompute_attainment(dist)  # quota basis unchanged: SUSPENDED still counts
    return ok(assign_json(a))


@bp.post("/brand-ops/coverage-assignments/<aid>/resume")
def resume_assignment(aid):
    _, role = authenticate()
    authorize(role, ["ChannelManager"])
    a = get_or_404("assignments", aid, "assignment")
    body()
    if a["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE_TRANSITION", "Assignment is not SUSPENDED")
    # Resume re-applies the activation gates minus the line-launch and
    # exclusive-brand gates (scaffold: distributor, window, registration,
    # exclusivity, capacity).
    _activation_gates(a, check_line_launch=False)
    a["status"] = "ACTIVE"
    touch(a)
    return ok(assign_json(a))


@bp.post("/brand-ops/coverage-assignments/<aid>/withdraw")
def withdraw_assignment(aid):
    _, role = authenticate()
    authorize(role, ["ChannelManager"])
    a = get_or_404("assignments", aid, "assignment")
    body()
    if a["status"] != "PROPOSED":
        err("ERR_INVALID_STATE_TRANSITION", "Assignment is not PROPOSED")
    a["status"] = "WITHDRAWN"
    touch(a)
    return ok(assign_json(a))


# ---------------------------------------------------------------------------
# Sell-through reports
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/distributors/<distributorId>/sell-through-reports")
def create_report(distributorId):
    user_id, role = authenticate()
    authorize(role, ["DistributorContact"])
    dist = get_or_404("distributors", distributorId, "distributor")
    b = body()
    assignment_id = as_str(need(b, "coverage_assignment_id"), "coverage_assignment_id")
    period = as_month(need(b, "period_month"), "period_month")
    sold = as_int(need(b, "units_sold"), "units_sold", minimum=0)
    returned = 0
    if "units_returned" in b and b["units_returned"] is not None:
        returned = as_int(b["units_returned"], "units_returned", minimum=0)
    # 5: the assignment must exist and belong to the path distributor
    assignment = STORE["assignments"].get(assignment_id)
    if assignment is None or assignment["distributor_id"] != dist["id"]:
        err("ERR_INVALID_REFERENCE", "coverage_assignment_id does not resolve for this distributor")
    # 6: ownership
    if user_id != dist["id"]:
        err("ERR_NOT_RESOURCE_OWNER", "X-User-ID must equal the path distributor id")
    # 8: assignment state
    if assignment["status"] not in ("ACTIVE", "SUSPENDED", "CLOSED"):
        err("ERR_INVALID_STATE_TRANSITION", "Assignment is not reportable")
    # 10: period must be a completed month
    if period >= current_month():
        err("ERR_PERIOD_NOT_COMPLETED", "period_month is not a completed month")
    # 12: one report per assignment per month
    for r in STORE["reports"].values():
        if r["coverage_assignment_id"] == assignment_id and r["period_month"] == period:
            err("ERR_DUPLICATE_REPORT", "A report already exists for this month")
    report = {
        "id": new_id(),
        "distributor_id": dist["id"],
        "coverage_assignment_id": assignment_id,
        "period_month": period,
        "units_sold": sold,
        "units_returned": returned,
        "net_units": max(0, sold - returned),
        "created_at": now_iso(),
        "_seq": None,
    }
    from core import next_seq
    report["_seq"] = next_seq()
    STORE["reports"][report["id"]] = report
    recompute_attainment(dist)
    return ok(report_json(report), code=201)


@bp.get("/brand-ops/sell-through-reports")
def list_reports():
    authenticate()
    items = list(STORE["reports"].values())
    items = filter_eq(items, "distributor_id", request.args.get("distributor_id"))
    items = filter_eq(items, "coverage_assignment_id", request.args.get("coverage_assignment_id"))
    items = filter_eq(items, "period_month", request.args.get("period_month"))
    page, pagination = paginate(items)
    return ok([report_json(r) for r in page], response_type="array", pagination=pagination)


@bp.get("/brand-ops/sell-through-reports/<rid>")
def get_report(rid):
    authenticate()
    return ok(report_json(get_or_404("reports", rid, "report")))
