"""Candidate endpoints: admission, readiness gate, licensure, state report."""

from datetime import timedelta

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import shapes
import store
import views
from auth import endpoint
from errors import ApiError

bp = Blueprint("candidates", __name__)


def _new_candidate_row(body):
    return store.new_row({
        "candidate_code": shapes.req_str(body, "candidate_code", 1, 32),
        "full_name": shapes.req_str(body, "full_name", 1, 120),
        "program_track": shapes.req_enum(body, "program_track",
                                         shapes.PROGRAM_TRACKS),
        "home_grid_x": shapes.req_int(body, "home_grid_x", -500, 500),
        "home_grid_y": shapes.req_int(body, "home_grid_y", -500, 500),
        "readiness_score": 0,
        "readiness_status": "NOT_READY",
        "readiness_variant_used": None,
        "licensure_status": "PENDING",
        "report_status": "UNREPORTED",
        "recommended_by_user_id": None,
        "recommended_at": None,
        "denial_reason": None,
        "reported_by_user_id": None,
        "reported_at": None,
        "reporting_cycle": None,
        "state_report_deadline": None,
    })


@bp.post("/epp/candidates")
@endpoint(["ProgramAdmin"])
def admit_candidate():
    body = shapes.body_of(request)
    candidate_code = shapes.req_str(body, "candidate_code", 1, 32)
    shapes.req_str(body, "full_name", 1, 120)
    shapes.req_enum(body, "program_track", shapes.PROGRAM_TRACKS)
    shapes.req_int(body, "home_grid_x", -500, 500)
    shapes.req_int(body, "home_grid_y", -500, 500)

    for existing in store.CANDIDATES.values():
        if existing["candidate_code"] == candidate_code:
            raise ApiError("ERR_CANDIDATE_CODE_TAKEN",
                           "candidate_code is already admitted.")

    row = _new_candidate_row(body)
    store.CANDIDATES[row["id"]] = row
    return envelope.created(views.dump(row, views.CANDIDATE))


@bp.get("/epp/candidates/<candidate_id>")
@endpoint(["ProgramAdmin", "PlacementCoordinator", "CredentialAnalyst",
           "CandidateUser"])
def read_candidate(candidate_id):
    row = store.get_candidate(candidate_id)
    derive.evaluate_readiness(row, "STRICT")
    return envelope.ok(views.dump(row, views.CANDIDATE))


@bp.get("/epp/candidates")
@endpoint(["ProgramAdmin", "PlacementCoordinator", "CredentialAnalyst"])
def list_candidates():
    page, page_size = shapes.pagination(request.args)
    readiness = shapes.query_enum(request.args, "readiness_status",
                                  shapes.READINESS_STATUSES)
    licensure = shapes.query_enum(request.args, "licensure_status",
                                  shapes.LICENSURE_STATUSES)
    report = shapes.query_enum(request.args, "report_status",
                               shapes.REPORT_STATUSES)
    track = shapes.query_enum(request.args, "program_track",
                              shapes.PROGRAM_TRACKS)
    rows = []
    for row in store.all_of(store.CANDIDATES):
        if readiness is not None and row["readiness_status"] != readiness:
            continue
        if licensure is not None and row["licensure_status"] != licensure:
            continue
        if report is not None and row["report_status"] != report:
            continue
        if track is not None and row["program_track"] != track:
            continue
        rows.append(row)
    sliced, total = shapes.paginate(rows, page, page_size)
    return envelope.listing(views.dump_all(sliced, views.CANDIDATE),
                            page, page_size, total)


@bp.post("/epp/candidates/<candidate_id>/readiness-evaluate")
@endpoint(["CredentialAnalyst", "ProgramAdmin"])
def readiness_evaluate(candidate_id):
    row = store.get_candidate(candidate_id)
    body = shapes.body_of(request)
    variant = shapes.opt_enum(body, "variant", shapes.READINESS_VARIANTS,
                              "STRICT")
    derive.evaluate_readiness(row, variant, force_touch=True)
    return envelope.ok(views.dump(row, views.CANDIDATE))


@bp.post("/epp/candidates/<candidate_id>/licensure-recommendation")
@endpoint(["ProgramAdmin"])
def licensure_recommendation(candidate_id):
    row = store.get_candidate(candidate_id)
    body = shapes.body_of(request)
    decision = shapes.req_enum(body, "decision", ("RECOMMENDED", "DENIED"))
    denial_reason = shapes.opt_str(body, "denial_reason", 1, None)

    if row["licensure_status"] != "PENDING":
        raise ApiError("ERR_NO_COMPLETER_RECORD",
                       "The licensure decision is already terminal.")

    placements = store.placements_of_candidate(candidate_id)
    if decision == "RECOMMENDED":
        qualifying = False
        for placement in placements:
            if placement["placement_status"] != "COMPLETED":
                continue
            assessment = store.assessment_of_placement(placement["id"])
            if assessment is not None and assessment["status"] == "PASSED":
                qualifying = True
        if not qualifying:
            raise ApiError("ERR_NO_COMPLETER_RECORD",
                           "The candidate holds no completed placement with a "
                           "passed performance assessment.")
        status = derive.evaluate_readiness(row, "ROLLING")
        if status != "READY":
            raise ApiError("ERR_NO_COMPLETER_RECORD",
                           "The rolling readiness re-evaluation did not leave "
                           "the candidate READY.")
        row["licensure_status"] = "RECOMMENDED"
    else:
        if not any(p["placement_status"] in ("COMPLETED", "REMOVED")
                   for p in placements):
            raise ApiError("ERR_NO_COMPLETER_RECORD",
                           "The candidate holds no completed or removed "
                           "placement.")
        derive.evaluate_readiness(row, "ROLLING")
        row["licensure_status"] = "DENIED"
        row["denial_reason"] = denial_reason

    row["recommended_by_user_id"] = auth.user_id()
    row["recommended_at"] = clock.now()
    store.touch(row)
    return envelope.ok(views.dump(row, views.CANDIDATE))


@bp.post("/epp/candidates/<candidate_id>/state-report")
@endpoint(["ProgramAdmin"])
def state_report(candidate_id):
    row = store.get_candidate(candidate_id)
    body = shapes.body_of(request)
    reporting_cycle = shapes.req_str(body, "reporting_cycle", 1, None)

    if (row["recommended_by_user_id"] is not None
            and row["recommended_by_user_id"] == auth.user_id()):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The filing principal recommended this candidate.")

    if (row["licensure_status"] != "RECOMMENDED"
            or row["report_status"] != "UNREPORTED"
            or row["state_report_deadline"] is None):
        raise ApiError("ERR_LICENSURE_NOT_RECOMMENDED",
                       "The candidate is not in a reportable state.")

    on_time = clock.today() <= row["state_report_deadline"]
    row["report_status"] = "REPORTED_ON_TIME" if on_time else "REPORTED_LATE"
    row["reported_by_user_id"] = auth.user_id()
    row["reported_at"] = clock.now()
    row["reporting_cycle"] = reporting_cycle
    store.touch(row)
    return envelope.ok(views.dump(row, views.CANDIDATE))


def set_state_report_deadline(candidate, term_end_date):
    candidate["state_report_deadline"] = term_end_date + timedelta(
        days=calc.STATE_REPORT_GRACE_DAYS)
