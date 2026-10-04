"""Cycle endpoints: POST /cycles, GET /cycles/{id}, POST /cycles/{id}/transition
(PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint

import constants as C
import errors as E
import serializers as ser
from response import ok
from store import DB, new_id, stamp_new, touch, now
from validation import (auth_headers, require_role, body, req_field,
                        parse_dt_field, as_number, as_int)

bp = Blueprint("cycles", __name__)

_ALL_READERS = [C.ROLE_CANDIDATE, C.ROLE_ASSESSOR, C.ROLE_SCORING_ADMIN,
                C.ROLE_BOARD_ADMIN, C.ROLE_INCENTIVE_ADMIN]


def _validate_components(components):
    """Exactly one ASSESSMENT component; weights sum to exactly 1.000."""
    if not isinstance(components, list):
        E.fail(E.ERR_INVALID_REQUEST, 400, "components must be an array")
    assessment_count = 0
    weight_sum = Decimal("0")
    for comp in components:
        if not isinstance(comp, dict):
            E.fail(E.ERR_INVALID_REQUEST, 400, "each component must be an object")
        code = comp.get("code")
        kind = comp.get("kind")
        weight = comp.get("weight")
        if code is None or kind is None or weight is None:
            E.fail(E.ERR_INVALID_REQUEST, 400,
                   "each component requires code, kind and weight")
        if kind not in ("ASSESSMENT", "PORTFOLIO"):
            E.fail(E.ERR_INVALID_REQUEST, 400,
                   "component kind must be ASSESSMENT or PORTFOLIO")
        if kind == "ASSESSMENT":
            assessment_count += 1
        weight_sum += Decimal(str(as_number(weight, "weight")))
    if assessment_count != 1 or weight_sum != C.WEIGHT_SUM_REQUIRED:
        E.fail(E.ERR_WEIGHT_SUM_INVALID, 422,
               "Components must contain exactly one ASSESSMENT entry and "
               "weights must sum to exactly 1.000")


def _check_window_overlap(window_open, window_close):
    """Half-open [open, close) overlap against DRAFT/OPEN/SCORING cycles;
    touching endpoints are allowed (PRD 2.7)."""
    for other in DB.cycles.values():
        if other["status"] not in ("DRAFT", "OPEN", "SCORING"):
            continue
        if (window_open < other["submission_window_close"]
                and other["submission_window_open"] < window_close):
            E.fail(E.ERR_CYCLE_WINDOW_OVERLAP, 409,
                   "Submission window overlaps an existing cycle window")


@bp.post("/cycles")
def create_cycle():
    _, role = auth_headers()
    require_role(role, [C.ROLE_BOARD_ADMIN])
    data = body()
    code = req_field(data, "code")
    components = req_field(data, "components")
    window_open = parse_dt_field(req_field(data, "submission_window_open"),
                                 "submission_window_open")
    window_close = parse_dt_field(req_field(data, "submission_window_close"),
                                  "submission_window_close")
    retake_close = parse_dt_field(req_field(data, "retake_window_close"),
                                  "retake_window_close")
    threshold = as_number(req_field(data, "certification_threshold"),
                          "certification_threshold")
    max_attempts = as_int(data.get("max_attempts_per_component",
                                   C.DEFAULT_MAX_ATTEMPTS_PER_COMPONENT),
                          "max_attempts_per_component")
    _validate_components(components)
    if retake_close < window_close:
        E.fail(E.ERR_INVALID_REQUEST, 400,
               "retake_window_close must be at or after submission_window_close")
    _check_window_overlap(window_open, window_close)
    cycle = {
        "id": new_id(),
        "code": code,
        "components": [
            {"code": comp["code"], "kind": comp["kind"], "weight": comp["weight"]}
            for comp in components
        ],
        "submission_window_open": window_open,
        "submission_window_close": window_close,
        "retake_window_close": retake_close,
        "certification_threshold": threshold,
        "max_attempts_per_component": max_attempts,
        "status": "DRAFT",
    }
    stamp_new(cycle)
    DB.cycles[cycle["id"]] = cycle
    return ok(ser.cycle(cycle), 201)


@bp.get("/cycles/<cycle_id>")
def get_cycle(cycle_id):
    _, role = auth_headers()
    require_role(role, _ALL_READERS)
    cycle = DB.cycles.get(cycle_id)
    if cycle is None:
        E.fail(E.ERR_CYCLE_NOT_FOUND, 404, "Cycle not found: %s" % cycle_id)
    return ok(ser.cycle(cycle))


@bp.post("/cycles/<cycle_id>/transition")
def transition_cycle(cycle_id):
    _, role = auth_headers()
    require_role(role, [C.ROLE_BOARD_ADMIN])
    cycle = DB.cycles.get(cycle_id)
    if cycle is None:
        E.fail(E.ERR_CYCLE_NOT_FOUND, 404, "Cycle not found: %s" % cycle_id)
    data = body()
    target = req_field(data, "to")
    # Pinned order (PRD 2.8): the state gate is checked before the window gate.
    legal_next = {"DRAFT": "OPEN", "OPEN": "SCORING", "SCORING": "CLOSED"}
    if legal_next.get(cycle["status"]) != target:
        E.fail(E.ERR_INVALID_CYCLE_TRANSITION, 409,
               "Cycle in %s cannot transition to %s" % (cycle["status"], target))
    if cycle["status"] == "OPEN":  # -> SCORING
        if now() < cycle["submission_window_close"]:
            E.fail(E.ERR_CYCLE_WINDOW_STILL_OPEN, 422,
                   "Submission window is still open")
        for sub in DB.submissions.values():
            if (sub["cycle_id"] == cycle["id"]
                    and sub["status"] in ("IN_PROGRESS", "SUBMITTED", "RETURNED")):
                sub["status"] = "EXPIRED"
                touch(sub)
    elif cycle["status"] == "SCORING":  # -> CLOSED
        for sub in DB.submissions.values():
            if (sub["cycle_id"] == cycle["id"]
                    and sub["status"] in ("SCORING", "ADJUDICATION_REQUIRED")):
                sub["status"] = "EXPIRED"
                touch(sub)
    cycle["status"] = target
    touch(cycle)
    return ok(ser.cycle(cycle))
