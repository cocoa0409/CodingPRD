"""Credit allocations: awards, deliveries, closures, rescissions, distributions."""

from flask import Blueprint, request

import calc
import clock
import errors
import response
import state
import store
import validate

bp = Blueprint("allocations", __name__)

READ_ALLOCATIONS = ("Underwriter", "AssetManager", "Investor", "ComplianceOfficer", "PlatformAdmin")
WRITE_ALLOCATIONS = ("Underwriter", "AssetManager")

ACTIONS = ("CREATE", "CLOSE", "RESCIND", "RECORD_DELIVERY", "DISTRIBUTE")


def _action(payload):
    raw = validate.as_string(payload, "action")
    action = raw.strip().upper()
    if action not in ACTIONS:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "action must be one of %s." % ", ".join(ACTIONS))
    return action


def _overlap_exists(project_id, state_agency, start, end, exclude_id=None):
    """Overlap against every non-terminal allocation of the same (project, agency)."""
    for other in state.allocations_of_project(project_id):
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["state_agency"] != state_agency:
            continue
        if other["status"] in ("CLOSED", "RESCINDED"):
            continue
        other_start = clock._parse(other["awarded_date"])
        other_end = clock._parse(other["placed_in_service_deadline"])
        if start < other_end and other_start < end:
            return True
    return False


@bp.get("/projects/<project_id>/allocations")
def list_allocations(project_id):
    role, user_id = validate.authenticate(request)
    validate.require_role(role, READ_ALLOCATIONS)
    project = validate.get_project(project_id)
    if role == "Investor" and not validate.investor_holds_fund(user_id, project["fund_id"]):
        errors.fail(errors.ERR_FORBIDDEN_SCOPE,
                    "An Investor may read only projects of funds it subscribes to.")
    rows = store.listing(store.allocations, {"project_id": project_id,
                                             "status": request.args.get("status")})
    limit, offset = response.pagination_args(request)
    window, meta = response.paginate(rows, limit, offset)
    return response.array([store.public(a) for a in window], 200, meta)


@bp.post("/projects/<project_id>/allocations")
def write_allocation(project_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, WRITE_ALLOCATIONS)
    payload = validate.body(request)
    action = _action(payload)
    project = validate.get_project(project_id)

    if action == "CREATE":
        return _create(project, payload)
    if action == "RECORD_DELIVERY":
        return _record_delivery(project, payload)
    if action == "CLOSE":
        return _close(project, payload)
    if action == "RESCIND":
        return _rescind(project, payload)
    return _distribute(project, payload)


def _create(project, payload):
    state_agency = validate.as_string(payload, "state_agency")
    awarded = validate.non_negative(validate.as_int(payload, "awarded_credit_dollars_cents"),
                                    "awarded_credit_dollars_cents")
    fee = validate.non_negative(validate.as_number(payload, "commitment_fee_pct"),
                                "commitment_fee_pct")
    awarded_date = validate.as_datetime(payload, "awarded_date")
    deadline = validate.as_datetime(payload, "placed_in_service_deadline")

    start = clock._parse(awarded_date)
    end = clock._parse(deadline)
    if _overlap_exists(project["id"], state_agency, start, end):
        errors.fail(errors.ERR_DUPLICATE_ALLOCATION_PERIOD,
                    "The award interval overlaps another live allocation.")

    allocation = store.create(store.allocations, {
        "project_id": project["id"],
        "state_agency": state_agency,
        "awarded_credit_dollars_cents": awarded,
        "commitment_fee_pct": fee,
        "awarded_date": awarded_date,
        "placed_in_service_deadline": deadline,
        "status": "AWARDED",
        "delivered_credit_dollars_cents": 0,
        "delivery_ratio": 0.0,
    })
    state.recompute_allocation(allocation["id"])
    state.recompute_project(project["id"])
    return response.ok(store.public(allocation), 201)


def _record_delivery(project, payload):
    allocation = validate.get_child(store.allocations, validate.as_string(payload, "allocation_id"),
                                    project["id"], errors.ERR_ALLOCATION_NOT_FOUND)
    delivered = validate.non_negative(
        validate.as_int(payload, "delivered_credit_dollars_cents"),
        "delivered_credit_dollars_cents")
    if allocation["status"] in ("CLOSED", "RESCINDED"):
        errors.fail(errors.ERR_INVALID_ALLOCATION_STATE,
                    "A terminal allocation accepts no further delivery.")
    allocation["delivered_credit_dollars_cents"] = delivered
    store.touch(allocation)
    state.recompute_allocation(allocation["id"])
    state.recompute_project(project["id"])
    state.recompute_fund(project["fund_id"])
    return response.ok(store.public(allocation), 200)


def _close(project, payload):
    allocation = validate.get_child(store.allocations, validate.as_string(payload, "allocation_id"),
                                    project["id"], errors.ERR_ALLOCATION_NOT_FOUND)
    if allocation["status"] != "COMMITTED":
        errors.fail(errors.ERR_INVALID_ALLOCATION_STATE, "Only a COMMITTED allocation may close.")
    if int(allocation["delivered_credit_dollars_cents"]) > int(allocation["awarded_credit_dollars_cents"]):
        errors.fail(errors.ERR_INVALID_ALLOCATION_STATE,
                    "Delivered credit exceeds the awarded credit.")
    allocation["status"] = "CLOSED"
    store.touch(allocation)
    state.recompute_allocation(allocation["id"])
    state.recompute_project(project["id"])
    state.recompute_fund(project["fund_id"])
    return response.ok(store.public(allocation), 200)


def _rescind(project, payload):
    allocation = validate.get_child(store.allocations, validate.as_string(payload, "allocation_id"),
                                    project["id"], errors.ERR_ALLOCATION_NOT_FOUND)
    if allocation["status"] not in ("AWARDED", "RESERVED", "COMMITTED"):
        errors.fail(errors.ERR_INVALID_ALLOCATION_STATE,
                    "Only a non-terminal allocation may be rescinded.")
    if int(allocation["delivered_credit_dollars_cents"]) >= int(allocation["awarded_credit_dollars_cents"]):
        errors.fail(errors.ERR_INVALID_ALLOCATION_STATE,
                    "A fully delivered allocation cannot be rescinded.")
    allocation["status"] = "RESCINDED"
    store.touch(allocation)
    state.recompute_allocation(allocation["id"])
    state.recompute_project(project["id"])
    state.recompute_fund(project["fund_id"])
    return response.ok(store.public(allocation), 200)


def _distribute(project, payload):
    allocation = validate.get_child(store.allocations, validate.as_string(payload, "allocation_id"),
                                    project["id"], errors.ERR_ALLOCATION_NOT_FOUND)
    delivered = int(allocation["delivered_credit_dollars_cents"])
    awarded = int(allocation["awarded_credit_dollars_cents"])
    requested = payload.get("amount_cents")
    if requested is None:
        requested = payload.get("distribution_amount_cents")
    if requested is None:
        payable = min(delivered, awarded)
    else:
        requested = validate.non_negative(validate.as_int(payload, "amount_cents"), "amount_cents")
        if requested > delivered:
            errors.fail(errors.ERR_DISTRIBUTION_EXCEEDS_DELIVERED,
                        "The distribution exceeds the allocation's delivered credit dollars.")
        payable = min(requested, awarded)

    subscriptions = [s for s in state.subscriptions_of_fund(project["fund_id"])
                     if s["status"] != "DEFAULTED"]
    ordered = calc.waterfall_order(subscriptions, store.investors)
    shares = calc.credit_shortfall_waterfall(payable, ordered)

    view = store.public(allocation)
    view["distributions"] = [
        {"subscription_id": sub["id"], "investor_id": sub["investor_id"], "amount_cents": amount}
        for sub, amount in shares
    ]
    view["distributed_cents"] = payable
    return response.ok(view, 200)
