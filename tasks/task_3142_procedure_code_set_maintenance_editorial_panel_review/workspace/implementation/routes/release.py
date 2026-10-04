"""Annual release cycles, their descriptor pools and publication."""

from flask import Blueprint, request

import auth
import parsers as P
import resolvers as R
import store
from clock import logical_now
from errors import (
    ERR_COMMENT_PERIOD_TOO_SHORT,
    ERR_EDITORIAL_BUDGET_EXHAUSTED,
    ERR_INVALID_STATE,
    ERR_SPONSOR_REQUIRED,
    ERR_STALE_VERSION,
    ApiError,
)
from money import dec
from response import object_response
from routes.common import guard, list_response, one
from services import changes as CH
from services import cycles as CY

bp = Blueprint("release", __name__)

STAFF = (auth.EDITORIAL_STAFF,)
READERS = (auth.EDITORIAL_STAFF, auth.EDITORIAL_PANEL_CHAIR, auth.LICENSING_OFFICER)
BOUND_READERS = (auth.EDITORIAL_STAFF, auth.EDITORIAL_PANEL_CHAIR)

DISCRETIONARY_FLOOR = dec("40")


@bp.post("/release-cycles")
@guard(STAFF)
def create_cycle(actor):
    data = P.body()
    year = P.integer(data.get("year"), 0)
    for existing in store.release_cycles.values():
        if int(existing.get("year") or 0) == year:
            raise ApiError(ERR_INVALID_STATE, "year must be unique across release cycles")

    meeting_ids = P.id_list(data.get("meeting_ids"))
    for meeting_id in meeting_ids:
        R.meeting(meeting_id)

    cycle = store.create(store.release_cycles, {
        "year": year,
        "comment_open": P.dt(data.get("comment_open")),
        "comment_close": P.dt(data.get("comment_close")),
        "addendum_comment_close": P.dt(data.get("addendum_comment_close")),
        "meeting_ids": meeting_ids,
        "code_set_capacity": P.integer(data.get("code_set_capacity"), 0),
        "submission_count": 0,
        "editorial_reserved_codes": 0,
        "additions_pool_codes": 0,
        "catiii_pool_codes": 0,
        "discretionary_codes": 0,
        "budget_gate_status": "OPEN",
        "single_floor_budgeting": P.boolean(data.get("single_floor_budgeting"), False),
        "released_at": None,
        "errata_deadline": P.dt(data.get("errata_deadline")) or P.dt("2027-06-30"),
        "cycle_status": "PLANNING",
        "effective_date": CY.effective_date_for_year(year) if year else None,
        "released_code_values": [],
    })
    CY.recompute_pools(cycle)
    return object_response(one(cycle), 201)


@bp.get("/release-cycles")
@guard(READERS)
def list_cycles(actor):
    rows = store.sorted_rows(store.release_cycles)
    for field in ("cycle_status", "year"):
        wanted = request.args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if str(r.get(field)) == str(wanted)]
    return list_response(rows)


@bp.get("/release-cycles/<cycle_id>")
@guard(READERS)
def read_cycle(actor, cycle_id):
    cycle = R.release_cycle(cycle_id)
    CY.recompute_pools(cycle)
    return object_response(one(cycle))


@bp.post("/release-cycles/<cycle_id>/openings")
@guard(STAFF)
def open_cycle(actor, cycle_id):
    cycle = R.release_cycle(cycle_id)
    if cycle.get("cycle_status") != "PLANNING":
        raise ApiError(ERR_INVALID_STATE, "the cycle is not in planning")
    if not CY.window_acceptable(cycle.get("comment_open"), cycle.get("comment_close")):
        raise ApiError(ERR_COMMENT_PERIOD_TOO_SHORT,
                       "the cycle comment window must span at least 30 whole days")
    if not (cycle.get("meeting_ids") or []):
        raise ApiError(ERR_INVALID_STATE, "the cycle must be bounded by at least one meeting")

    cycle["cycle_status"] = "OPEN"
    store.bump(cycle)
    return object_response(one(cycle), 200)


@bp.post("/release-cycles/<cycle_id>/submissions")
@guard(STAFF)
def submit_changes(actor, cycle_id):
    cycle = R.release_cycle(cycle_id)
    data = P.body()

    close_at = cycle.get("comment_close")
    if close_at is None or logical_now() > close_at:
        raise ApiError(ERR_INVALID_STATE, "the cycle comment period has closed")

    change_ids = P.id_list(data.get("change_ids"))
    changes = [R.code_change(change_id) for change_id in change_ids]

    expected = data.get("expected_change_version")
    if expected is None or expected == "":
        raise ApiError(ERR_STALE_VERSION, "expected_change_version is required")
    for change in changes:
        if int(change.get("version") or 0) != int(expected):
            raise ApiError(ERR_STALE_VERSION,
                           "the change has moved since the submitter last observed it")
    # PRD SS2.12: "A cascade is not a partial write - a request that requires a
    # cascade either performs all of its hops or fails." The sponsor gate is
    # therefore evaluated for the whole request before any change is enrolled.
    for change in changes:
        if change.get("society_id") is None:
            raise ApiError(ERR_SPONSOR_REQUIRED,
                           "a change entering the pool must carry a sponsoring society")

    for change in changes:
        change["cycle_id"] = cycle["id"]
        change["effective_date"] = CY.effective_date_for_year(cycle.get("year"))
        store.bump(change)

    CY.recompute_pools(cycle)
    store.bump(cycle)
    return object_response(one(cycle), 200)


@bp.post("/release-cycles/<cycle_id>/returns")
@guard(STAFF)
def return_cycle(actor, cycle_id):
    cycle = R.release_cycle(cycle_id)
    if cycle.get("cycle_status") != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "the cycle is not open")
    CY.recompute_pools(cycle)
    if int(cycle.get("submission_count") or 0) != 0:
        raise ApiError(ERR_INVALID_STATE,
                       "a populated cycle cannot be returned to planning")

    cycle["cycle_status"] = "PLANNING"
    store.bump(cycle)
    return object_response(one(cycle), 200)


@bp.post("/release-cycles/<cycle_id>/closures")
@guard(STAFF)
def close_cycle(actor, cycle_id):
    cycle = R.release_cycle(cycle_id)
    CY.recompute_pools(cycle)

    if int(cycle.get("submission_count") or 0) <= 0:
        raise ApiError(ERR_INVALID_STATE, "the cycle has no submissions")
    close_at = cycle.get("comment_close")
    if close_at is None or logical_now() < close_at:
        raise ApiError(ERR_INVALID_STATE,
                       "the logical clock has not reached the cycle comment close")
    if dec(cycle.get("discretionary_codes")) < DISCRETIONARY_FLOOR:
        raise ApiError(ERR_EDITORIAL_BUDGET_EXHAUSTED,
                       "the discretionary descriptor pool is below 40")

    cycle["budget_gate_status"] = "OPEN"
    cycle["cycle_status"] = "CLOSED"
    store.bump(cycle)
    return object_response(one(cycle), 200)


@bp.post("/release-cycles/<cycle_id>/releases")
@guard(STAFF)
def release_code_set(actor, cycle_id):
    cycle = R.release_cycle(cycle_id)

    bound = [v for v in store.code_values.values() if v.get("release_id") == cycle["id"]]
    if not bound:
        raise ApiError(ERR_INVALID_STATE, "at least one code value must carry this cycle")
    close_at = cycle.get("comment_close")
    if close_at is None or logical_now() < close_at:
        raise ApiError(ERR_INVALID_STATE,
                       "the logical clock has not reached the cycle comment close")
    if CH.missing_descriptor_present(cycle["id"]):
        CH.missing_descriptor_error()

    bound.sort(key=lambda v: (v.get("code") or "", v.get("created_at")))
    cycle["released_code_values"] = [v["id"] for v in bound]
    for value in bound:
        value["value_status"] = "ACTIVE"
        store.bump(value)
    cycle["released_at"] = logical_now()
    cycle["cycle_status"] = "RELEASED"
    store.bump(cycle)
    return object_response(one(cycle), 200)


@bp.get("/release-cycles/<cycle_id>/code-changes")
@guard(BOUND_READERS)
def list_cycle_changes(actor, cycle_id):
    cycle = R.release_cycle(cycle_id)
    rows = [c for c in store.sorted_rows(store.code_changes)
            if c.get("cycle_id") == cycle["id"]]
    return list_response(rows)