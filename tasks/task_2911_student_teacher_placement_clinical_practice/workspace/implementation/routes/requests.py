"""Placement request endpoints: opening, routing and rerouting (PRD 3.5)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import derive
import envelope
import matcher
import shapes
import store
import views
from auth import endpoint
from errors import ApiError

bp = Blueprint("requests", __name__)

READERS = ["PlacementCoordinator", "ProgramAdmin", "CandidateUser"]


def _request_state_invalid(message):
    return ApiError("ERR_REQUEST_STATE_INVALID", message)


def create_placement(request_row, pair, replaces_placement_id):
    teacher, agreement, supervisor, commute, travel = pair
    row = store.new_row({
        "request_id": request_row["id"],
        "candidate_id": request_row["candidate_id"],
        "cooperating_teacher_id": teacher["id"],
        "agreement_id": agreement["id"],
        "supervisor_id": supervisor["id"],
        "replaces_placement_id": replaces_placement_id,
        "subject": request_row["requested_subject"],
        "grade_band": request_row["requested_grade_band"],
        "start_date": request_row["term_start_date"],
        "end_date": request_row["term_end_date"],
        "weeks_scheduled": request_row["weeks_scheduled"],
        "commute_miles": commute,
        "supervisor_points": calc.stage_points("PROPOSED", travel),
        "placement_status": "PROPOSED",
        "stipend_status": "NOT_ACCRUED",
        "stipend_variant": None,
        "stipend_weekly_cents": 0,
        "weeks_credited": 0,
        "stipend_gross_cents": 0,
        "travel_reimbursement_cents": 0,
        "observation_compliance_ratio": calc.compliance_ratio(0, 0),
        "summative_completed_count": 0,
        "removal_reason": None,
        "removal_requested_by_role": None,
        "removal_requested_by_user_id": None,
        "removal_decided_by_user_id": None,
        "removal_narrative": None,
        "voided_reason": None,
        "settlement_date": None,
        "completed_at": None,
    })
    store.PLACEMENTS[row["id"]] = row
    return row


def _recount(placement):
    agreement = store.AGREEMENTS.get(placement["agreement_id"])
    if agreement is not None:
        derive.derive_agreement_ledger(agreement)
    teacher = store.TEACHERS.get(placement["cooperating_teacher_id"])
    if teacher is not None:
        derive.derive_teacher_counters(teacher)
    supervisor = store.SUPERVISORS.get(placement["supervisor_id"])
    if supervisor is not None:
        derive.derive_supervisor(supervisor)


@bp.post("/epp/placement-requests")
@endpoint(["PlacementCoordinator"])
def open_request():
    body = shapes.body_of(request)
    candidate_id = shapes.req_str(body, "candidate_id", 1, None)
    term = shapes.req_enum(body, "term", shapes.TERMS)
    subject = shapes.req_enum(body, "requested_subject", shapes.SUBJECTS)
    grade_band = shapes.req_enum(body, "requested_grade_band",
                                 shapes.GRADE_BANDS)
    term_start = shapes.req_date(body, "term_start_date")
    weeks = shapes.req_int(body, "weeks_scheduled", 1, 20)
    max_commute = shapes.req_int(body, "max_commute_miles", 1, 200)
    preferred_district_id = shapes.opt_str(body, "preferred_district_id",
                                           1, None)

    candidate = store.get_candidate(candidate_id)
    if preferred_district_id is not None:
        store.get_district(preferred_district_id)

    if max_commute > calc.COMMUTE_CEILING_MILES:
        raise ApiError("ERR_COMMUTE_LIMIT_EXCEEDED",
                       "max_commute_miles may not exceed the program ceiling "
                       "of %d miles." % calc.COMMUTE_CEILING_MILES)

    term_end = term_start + timedelta(days=weeks * 7 - 1)
    row = store.new_row({
        "candidate_id": candidate["id"],
        "preferred_district_id": preferred_district_id,
        "term": term,
        "requested_subject": subject,
        "requested_grade_band": grade_band,
        "max_commute_miles": max_commute,
        "term_start_date": term_start,
        "weeks_scheduled": weeks,
        "term_end_date": term_end,
        "status": "SUBMITTED",
        "routing_round": 0,
        "reroute_count": 0,
        "excluded_cooperating_teacher_ids": [],
        "current_placement_id": None,
    })
    store.REQUESTS[row["id"]] = row
    return envelope.created(views.dump(row, views.REQUEST))


@bp.get("/epp/placement-requests/<request_id>")
@endpoint(READERS)
def read_request(request_id):
    row = store.get_request(request_id)
    derive.derive_request_current_placement(row)
    return envelope.ok(views.dump(row, views.REQUEST))


@bp.get("/epp/placement-requests")
@endpoint(["PlacementCoordinator", "ProgramAdmin"])
def list_requests():
    page, page_size = shapes.pagination(request.args)
    candidate_id = request.args.get("candidate_id") or None
    district_id = request.args.get("preferred_district_id") or None
    status = shapes.query_enum(request.args, "status", shapes.REQUEST_STATUSES)
    term = shapes.query_enum(request.args, "term", shapes.TERMS)
    rows = []
    for row in store.all_of(store.REQUESTS):
        if candidate_id is not None and row["candidate_id"] != candidate_id:
            continue
        if (district_id is not None
                and row["preferred_district_id"] != district_id):
            continue
        if status is not None and row["status"] != status:
            continue
        if term is not None and row["term"] != term:
            continue
        rows.append(row)
    sliced, total = shapes.paginate(rows, page, page_size)
    return envelope.listing(views.dump_all(sliced, views.REQUEST),
                            page, page_size, total)


@bp.post("/epp/placement-requests/<request_id>/route")
@endpoint(["PlacementCoordinator"])
def route_request(request_id):
    row = store.get_request(request_id)
    candidate = store.CANDIDATES.get(row["candidate_id"])

    # Rung 14 -- lazy agreement expiry precedes every other agreement check.
    scope = matcher.agreement_scope(row)
    if not any(a["status"] == "ACTIVE" for a in scope):
        if any(a["status"] == "EXPIRED" for a in scope):
            raise ApiError("ERR_AGREEMENT_EXPIRED",
                           "The backing partnership agreement has expired.")

    # Rung 16 -- request state.
    if row["status"] != "SUBMITTED":
        raise _request_state_invalid("Only a SUBMITTED request may be routed.")
    if row["routing_round"] >= calc.MAX_ROUTING_ROUNDS:
        raise _request_state_invalid(
            "The request has exhausted its routing rounds.")

    # Rung 25 -- STRICT readiness gate.
    if candidate is not None:
        if derive.evaluate_readiness(candidate, "STRICT") != "READY":
            raise ApiError("ERR_CANDIDATE_NOT_READY",
                           "The candidate is not READY under the STRICT "
                           "readiness evaluation.")

    # Rungs 29 and 30 -- subject / band envelope, then the term window.
    matcher.routing_envelope_check(row, scope)

    # Rung 43 -- the match selector.
    pair = matcher.select_pair(row, candidate)
    if pair is None:
        raise ApiError("ERR_NO_ELIGIBLE_PLACEMENT",
                       "No eligible teacher-and-supervisor pair survives the "
                       "eligibility filter.")

    new_round = row["routing_round"] + 1
    replaces_placement_id = None
    if new_round >= 2:
        for placement in store.placements_of_request(row["id"]):
            if placement["placement_status"] in ("REMOVED", "VOIDED"):
                replaces_placement_id = placement["id"]

    placement = create_placement(row, pair, replaces_placement_id)
    row["status"] = "ROUTED"
    row["routing_round"] = new_round
    row["reroute_count"] = 0
    row["current_placement_id"] = placement["id"]
    store.touch(row)
    _recount(placement)
    return envelope.created(views.dump(placement, views.PLACEMENT))


@bp.post("/epp/placement-requests/<request_id>/reroute")
@endpoint(["PlacementCoordinator"])
def reroute_request(request_id):
    row = store.get_request(request_id)
    body = shapes.body_of(request)
    expected_version = shapes.req_int(body, "expected_request_version", None,
                                      None)
    exclude_current = shapes.opt_bool(body, "exclude_current_teacher", False)

    # Rung 12 -- optimistic concurrency on the request.
    if expected_version != row["version"]:
        raise ApiError("ERR_STALE_REQUEST_VERSION",
                       "expected_request_version does not match the request's "
                       "current version.")

    # Rung 16 -- request state.
    if row["status"] != "ROUTED":
        raise _request_state_invalid("Only a ROUTED request may be rerouted.")
    current_id = row["current_placement_id"]
    current = store.PLACEMENTS.get(current_id) if current_id else None
    if current is None or current["placement_status"] != "PROPOSED":
        raise _request_state_invalid(
            "The request has no PROPOSED placement to supersede.")

    # Rung 36 -- reroute ceiling.
    if row["reroute_count"] >= calc.MAX_REROUTES_PER_REQUEST:
        raise ApiError("ERR_REROUTE_LIMIT_REACHED",
                       "The request has reached its reroute ceiling.")

    candidate = store.CANDIDATES.get(row["candidate_id"])
    outgoing_teacher_id = current["cooperating_teacher_id"]

    # The supersede is evaluated as if the current proposal were already gone,
    # and is rolled back when the exclusions leave no eligible pair.
    current["placement_status"] = "VOIDED"
    added_exclusion = False
    if exclude_current and outgoing_teacher_id not in row[
            "excluded_cooperating_teacher_ids"]:
        row["excluded_cooperating_teacher_ids"].append(outgoing_teacher_id)
        added_exclusion = True

    pair = matcher.select_pair(row, candidate)
    if pair is None:
        current["placement_status"] = "PROPOSED"
        if added_exclusion:
            row["excluded_cooperating_teacher_ids"].remove(outgoing_teacher_id)
        _recount(current)
        raise ApiError("ERR_NO_ELIGIBLE_PLACEMENT",
                       "No eligible teacher-and-supervisor pair survives the "
                       "exclusions.")

    current["voided_reason"] = "REROUTED"
    store.touch(current)

    placement = create_placement(row, pair, None)
    row["reroute_count"] = row["reroute_count"] + 1
    row["current_placement_id"] = placement["id"]
    store.touch(row)
    _recount(current)
    _recount(placement)
    return envelope.created(views.dump(placement, views.PLACEMENT))
