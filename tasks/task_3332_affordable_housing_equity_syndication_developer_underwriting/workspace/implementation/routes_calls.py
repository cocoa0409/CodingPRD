"""Capital calls: scheduling, issuance, settlement, adjustment and re-issue."""

from flask import Blueprint, request

import calc
import clock
import errors
import response
import state
import store
import validate

bp = Blueprint("calls", __name__)

READ_CALLS = ("Investor", "AssetManager", "Underwriter", "PlatformAdmin")
WRITE_CALLS = ("AssetManager", "Underwriter")

MILESTONES = ("CONSTRUCTION_START", "CONSTRUCTION_50PCT", "LEASE_UP_50PCT",
              "LEASE_UP_STABILIZED", "PLACED_IN_SERVICE")
ACTIONS = ("ISSUE", "SETTLE", "ADJUST", "REISSUE")
BUFFER_DAYS = 30


def _paid_or_deficient_calls(project_id):
    rows = [c for c in state.calls_of_project(project_id) if c["status"] in ("PAID", "DEFICIENT")]
    return sorted(rows, key=lambda c: (c["due_date"], c.get("_seq", 0)))


@bp.get("/projects/<project_id>/capital-calls")
def list_calls(project_id):
    role, user_id = validate.authenticate(request)
    validate.require_role(role, READ_CALLS)
    project = validate.get_project(project_id)
    if role == "Investor" and not validate.investor_holds_fund(user_id, project["fund_id"]):
        errors.fail(errors.ERR_FORBIDDEN_SCOPE,
                    "An Investor may read only projects of funds it subscribes to.")
    rows = store.listing(store.calls, {"project_id": project_id,
                                       "milestone": request.args.get("milestone"),
                                       "status": request.args.get("status")})
    limit, offset = response.pagination_args(request)
    window, meta = response.paginate(rows, limit, offset)
    return response.array([store.public(c) for c in window], 200, meta)


@bp.post("/projects/<project_id>/capital-calls")
def create_call(project_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, WRITE_CALLS)
    payload = validate.body(request)
    milestone = validate.in_enum(validate.as_string(payload, "milestone"), MILESTONES, "milestone")
    scheduled = validate.as_datetime(payload, "scheduled_date")
    due = validate.as_datetime(payload, "due_date")
    share = validate.non_negative(validate.as_number(payload, "milestone_share"), "milestone_share")
    expected = validate.as_int(payload, "expected_project_version")

    if clock._parse(scheduled) > clock._parse(due):
        errors.fail(errors.ERR_INVALID_REQUEST, "scheduled_date must not be after due_date.")

    project = validate.get_project(project_id)
    fund = validate.get_fund(project["fund_id"])

    # tier 8 — revision band, posture gate and fund state.
    if int(project["version"]) != int(expected):
        errors.fail(errors.ERR_STALE_VERSION, "expected_project_version is not current.")
    if fund["posture"] == "FROZEN":
        errors.fail(errors.ERR_FUND_POSTURE_FROZEN, "The fund's posture is FROZEN.")
    if fund["status"] in ("TERMINATED", "WOUND_DOWN"):
        errors.fail(errors.ERR_FUND_NOT_FORMING, "The fund can no longer fund capital calls.")

    call = store.create(store.calls, {
        "project_id": project["id"],
        "milestone": milestone,
        "scheduled_date": scheduled,
        "due_date": due,
        "_milestone_share": share,
        "base_call_cents": 0,
        "credit_delivery_adjuster_pct": 0.0,
        "called_amount_cents": 0,
        "settled_amount_cents": 0,
        "shortfall_cents": 0,
        "status": "SCHEDULED",
    })
    store.touch(project)
    return response.ok(store.public(call), 201)


@bp.post("/capital-calls/<call_id>/transitions")
def transition_call(call_id):
    role, user_id = validate.authenticate(request)
    validate.require_role(role, ("Investor", "AssetManager"))
    payload = validate.body(request)
    action = validate.as_string(payload, "action").strip().upper()
    if action not in ACTIONS:
        errors.fail(errors.ERR_INVALID_REQUEST, "action must be one of %s." % ", ".join(ACTIONS))

    call = validate.get_call(call_id)
    project = validate.get_project(call["project_id"])
    fund = validate.get_fund(project["fund_id"])

    # Within-role action restriction: settlement belongs to the Investor alone.
    if role == "Investor" and action != "SETTLE":
        errors.fail(errors.ERR_FORBIDDEN, "An Investor may only settle a capital call.")
    if action == "SETTLE":
        if role != "Investor":
            errors.fail(errors.ERR_FORBIDDEN, "Only an Investor may settle a capital call.")
        if not validate.investor_holds_fund(user_id, fund["id"]):
            errors.fail(errors.ERR_FORBIDDEN_SCOPE,
                        "The investor holds no subscription in the call's fund.")

    if action == "ISSUE":
        return _issue(call, project)
    if action == "SETTLE":
        return _settle(call, project, fund, payload)
    if action == "ADJUST":
        return _adjust(call, project, fund)
    return _reissue(call, project)


def _issue(call, project):
    if call["status"] != "SCHEDULED":
        errors.fail(errors.ERR_CALL_NOT_ISSUED, "Only a SCHEDULED call may be issued.")

    # tier 8 — one call per milestone, and the 30-day buffer.
    for other in state.calls_of_project(project["id"]):
        if other["id"] != call["id"] and other["milestone"] == call["milestone"]:
            errors.fail(errors.ERR_DUPLICATE_CALL_MILESTONE,
                        "A call already exists for this project and milestone.")
    prior = _paid_or_deficient_calls(project["id"])
    if prior:
        earliest = clock.add_days(clock._parse(prior[-1]["due_date"]), BUFFER_DAYS)
        if clock._parse(call["scheduled_date"]) < earliest:
            errors.fail(errors.ERR_CALL_BUFFER_TOO_SHORT,
                        "scheduled_date is fewer than 30 days after the prior call's due date.")

    # tier 10 — the call may only issue at or after its scheduled date.
    if clock.now() < clock._parse(call["scheduled_date"]):
        errors.fail(errors.ERR_CALL_NOT_DUE, "The logical clock precedes scheduled_date.")

    adjuster, base_call, called = calc.capital_call_amount(
        project, state.committed_allocations(project["id"]),
        call.get("_milestone_share", 0), call["credit_delivery_adjuster_pct"])
    call["credit_delivery_adjuster_pct"] = adjuster
    call["base_call_cents"] = base_call
    call["called_amount_cents"] = called
    call["status"] = "ISSUED"
    store.touch(call)
    return response.ok(store.public(call), 200)


def _settle(call, project, fund, payload):
    if call["status"] != "ISSUED":
        errors.fail(errors.ERR_CALL_NOT_ISSUED, "Only an ISSUED call may be settled.")
    funded = validate.non_negative(validate.as_int(payload, "funded_amount_cents"),
                                   "funded_amount_cents")
    called = int(call["called_amount_cents"])
    call["settled_amount_cents"] = funded
    if funded == called:
        call["shortfall_cents"] = 0
        call["status"] = "PAID"
    else:
        call["shortfall_cents"] = max(0, called - funded)
        call["status"] = "DEFICIENT"
    store.touch(call)

    for subscription in state.subscriptions_of_fund(fund["id"]):
        state.recompute_subscription(subscription["id"])
    state.recompute_fund(fund["id"])
    state.propagate(project["id"])
    return response.ok(store.public(call), 200)


def _adjust(call, project, fund):
    if call["status"] not in ("ISSUED", "PAID"):
        errors.fail(errors.ERR_CALL_NOT_ISSUED, "Only an ISSUED or PAID call may be adjusted.")

    committed = state.committed_allocations(project["id"])
    band = calc.adjuster_band(calc.delivery_ratio_of(committed))
    current = calc.dec(call["credit_delivery_adjuster_pct"])
    if band <= current:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "The delivery-ratio band selects no larger adjuster than the one pinned.")

    adjuster, base_call, called = calc.capital_call_amount(
        project, committed, call.get("_milestone_share", 0), call["credit_delivery_adjuster_pct"])
    call["credit_delivery_adjuster_pct"] = adjuster
    call["base_call_cents"] = base_call
    call["called_amount_cents"] = called

    if call["status"] == "PAID":
        delta = int(called) - int(call["settled_amount_cents"])
        if delta > 0:
            for subscription in state.subscriptions_of_fund(fund["id"]):
                paid_in = max(0, int(subscription["paid_in_cents"]) - delta)
                subscription["paid_in_cents"] = paid_in
                committed_cents = int(subscription["committed_cents"])
                if paid_in == committed_cents and committed_cents > 0:
                    subscription["status"] = "FULLY_FUNDED"
                elif paid_in > 0:
                    subscription["status"] = "PARTIALLY_FUNDED"
                store.touch(subscription)
    call["shortfall_cents"] = max(0, int(called) - int(call["settled_amount_cents"]))
    call["status"] = "ADJUSTED"
    store.touch(call)

    for subscription in state.subscriptions_of_fund(fund["id"]):
        state.recompute_subscription(subscription["id"])
    state.recompute_fund(fund["id"])
    state.propagate(project["id"])
    return response.ok(store.public(call), 200)


def _reissue(call, project):
    if call["status"] != "ADJUSTED":
        errors.fail(errors.ERR_CALL_NOT_ISSUED, "Only an ADJUSTED call may be re-issued.")
    committed = state.committed_allocations(project["id"])
    band = calc.adjuster_band(calc.delivery_ratio_of(committed))
    if band != calc.dec(call["credit_delivery_adjuster_pct"]):
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "The delivery-ratio band does not match the adjuster pinned on the call.")
    call["status"] = "ISSUED"
    store.touch(call)
    return response.ok(store.public(call), 200)
