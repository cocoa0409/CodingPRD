"""Production run endpoints: schedule (with the gate chain), advance, rework,
qa-release, reject.

Creation precedence (PRD 2.10): shape (4) -> existence in declared input order
line/spec/agreement/lots (5) -> state: spec LOCKED, agreement ACTIVE, lots
IN_STORAGE (6) -> quarantine (7) -> structural: cut-family capability, stale
pin, line schedule with changeover buffer (8).
"""

from datetime import timedelta
from decimal import Decimal

import calcs
import domain
from db import store
from errors import ApiError
from flask import Blueprint, request
from middleware import ANY_ROLES, require_roles
from response import list_response, sort_default, success_object
from util import D, body_json, req_dt, req_number, req_present, req_str
from constants import CHANGEOVER_MINUTES, COLOR_TOLERANCE, RUN_REJECT_DISPOSITIONS

bp = Blueprint("runs", __name__)

_ADVANCE_MAP = {
    "SCHEDULED": "CUTTING",
    "CUTTING": "BLANCHING",
    "BLANCHING": "COATING",
    "COATING": "FREEZING",
    "FREEZING": "QA_HOLD",
    "REWORK": "COATING",
}
_TERMINAL_RUN_STATUSES = ("RELEASED", "REJECTED", "CANCELLED")


def _check_schedule_conflict(line_id, cut_family, start, end):
    """line_schedule_conflict: strict overlap always conflicts; disjoint or
    touching windows need a >= 60-minute gap when the cut family changes."""
    for e in store.runs.values():
        if e["line_id"] != line_id or e["status"] in _TERMINAL_RUN_STATUSES:
            continue
        if e["scheduled_start"] < end and start < e["scheduled_end"]:
            raise ApiError(
                "ERR_LINE_SCHEDULE_CONFLICT",
                "Run window overlaps a non-terminal run on the same line",
                409,
            )
        if e["cut_family"] != cut_family:
            if start >= e["scheduled_end"]:
                gap = start - e["scheduled_end"]
            else:
                gap = e["scheduled_start"] - end
            if gap < timedelta(minutes=CHANGEOVER_MINUTES):
                raise ApiError(
                    "ERR_LINE_SCHEDULE_CONFLICT",
                    "Cut-family changeover requires a gap of at least 60 minutes",
                    409,
                )


@bp.route("/potato-ops/production-runs", methods=["POST"])
@require_roles("ProductionPlanner")
def create_run():
    body = body_json()
    # Priority 4: shape.
    line_id = req_str(body, "line_id")
    spec_id = req_str(body, "spec_id")
    agreement_id = req_str(body, "agreement_id")
    lot_ids = req_present(body, "input_lot_ids")
    if (
        not isinstance(lot_ids, list)
        or not lot_ids
        or any(not isinstance(x, str) for x in lot_ids)
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'input_lot_ids': must be a non-empty array of lot ids",
            400,
        )
    start = req_dt(body, "scheduled_start")
    end = req_dt(body, "scheduled_end")
    if not end > start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'scheduled_end': must be strictly after scheduled_start",
            400,
        )
    # Priority 5: existence in declared input order.
    line = domain.get_line_or_404(line_id)
    spec = domain.get_spec_or_404(spec_id)
    agreement = domain.get_agreement_or_404(agreement_id)
    lots = [domain.get_lot_or_404(x) for x in lot_ids]
    # Priority 6: state preconditions.
    if spec["status"] != "LOCKED":
        raise ApiError(
            "ERR_SPEC_NOT_LOCKED", "run creation requires the spec LOCKED", 409
        )
    if agreement["status"] != "ACTIVE":
        raise ApiError(
            "ERR_AGREEMENT_NOT_ACTIVE",
            "run creation requires the agreement ACTIVE",
            409,
        )
    for lot in lots:
        if lot["status"] != "IN_STORAGE":
            raise ApiError(
                "ERR_LOT_NOT_AVAILABLE",
                "every input lot must be IN_STORAGE",
                409,
            )
    # Priority 7: quarantine isolation.
    for lot in lots:
        if store.facilities[lot["facility_id"]]["posture"] == "QUARANTINED":
            raise ApiError(
                "ERR_FACILITY_QUARANTINED",
                "Run cannot consume a lot stored in a QUARANTINED facility",
                409,
            )
    # Priority 8: structural constraints.
    if spec["cut_family"] not in line["supported_cut_families"]:
        raise ApiError(
            "ERR_CUT_FAMILY_UNSUPPORTED",
            "The line does not support the spec's cut_family",
            409,
        )
    if agreement["spec_stale"]:
        raise ApiError(
            "ERR_SPEC_REVISION_STALE",
            "Run creation with an agreement whose pinned spec is under revision",
            409,
        )
    _check_schedule_conflict(line_id, spec["cut_family"], start, end)

    total_input = Decimal(0)
    for lot in lots:
        total_input += lot["net_weight_cwt"]
    run = domain.new_entity()
    run.update({
        "line_id": line_id,
        "spec_id": spec_id,
        "agreement_id": agreement_id,
        "input_lot_ids": list(lot_ids),
        "scheduled_start": start,
        "scheduled_end": end,
        "cut_family": spec["cut_family"],
        "total_input_cwt": total_input,
        "actual_cases": None,
        "rework_count": 0,
        "status": "SCHEDULED",
    })
    store.runs[run["id"]] = run
    for lot in lots:
        lot["status"] = "ALLOCATED"
        domain.touch(lot)
        domain.touch(store.facilities[lot["facility_id"]])  # stock decreased
    return success_object(domain.run_view(run), 201)


@bp.route("/potato-ops/production-runs", methods=["GET"])
@require_roles(*ANY_ROLES)
def list_runs():
    items = list(store.runs.values())
    line_id = request.args.get("line_id")
    spec_id = request.args.get("spec_id")
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    if line_id is not None:
        items = [r for r in items if r["line_id"] == line_id]
    if spec_id is not None:
        items = [r for r in items if r["spec_id"] == spec_id]
    if agreement_id is not None:
        items = [r for r in items if r["agreement_id"] == agreement_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(sort_default(items), domain.run_view)


@bp.route("/potato-ops/production-runs/<rid>", methods=["GET"])
@require_roles(*ANY_ROLES)
def get_run(rid):
    return success_object(domain.run_view(domain.get_run_or_404(rid)), 200)


@bp.route("/potato-ops/production-runs/<rid>/advance", methods=["POST"])
@require_roles("ProductionPlanner")
def advance_run(rid):
    run = domain.get_run_or_404(rid)
    nxt = _ADVANCE_MAP.get(run["status"])
    if nxt is None:
        raise ApiError(
            "ERR_RUN_INVALID_STAGE",
            "advance called from a stage where it is not defined, or from a terminal stage",
            409,
        )
    run["status"] = nxt
    if nxt == "QA_HOLD":
        if run["rework_count"] == 0:
            run["actual_cases"] = calcs.actual_cases_first_pass(
                run["total_input_cwt"], run["cut_family"]
            )
        else:
            run["actual_cases"] = calcs.actual_cases_rework_pass(run["actual_cases"])
    domain.touch(run)
    return success_object(domain.run_view(run), 200)


@bp.route("/potato-ops/production-runs/<rid>/rework", methods=["POST"])
@require_roles("QualityAssuranceLead")
def rework_run(rid):
    run = domain.get_run_or_404(rid)
    if run["status"] != "QA_HOLD":
        raise ApiError(
            "ERR_RUN_INVALID_STAGE", "rework requires the run in QA_HOLD", 409
        )
    run["status"] = "REWORK"
    run["rework_count"] += 1
    domain.touch(run)
    return success_object(domain.run_view(run), 200)


@bp.route("/potato-ops/production-runs/<rid>/qa-release", methods=["POST"])
@require_roles("QualityAssuranceLead")
def qa_release_run(rid):
    body = body_json()
    measured = req_number(body, "measured_color_units")
    run = domain.get_run_or_404(rid)
    if run["status"] != "QA_HOLD":
        raise ApiError(
            "ERR_RUN_INVALID_STAGE", "qa-release requires the run in QA_HOLD", 409
        )
    spec = store.specs[run["spec_id"]]
    if abs(measured - D(spec["target_color_units"])) > Decimal(COLOR_TOLERANCE):
        raise ApiError(
            "ERR_COLOR_OUT_OF_TOLERANCE",
            "Measured cook color outside target_color_units +/- 0.5",
            422,
        )
    run["status"] = "RELEASED"
    domain.touch(run)
    for lot_id in run["input_lot_ids"]:
        lot = store.lots[lot_id]
        if lot["status"] == "ALLOCATED":
            lot["status"] = "CONSUMED"
            domain.touch(lot)
    # lifetime_released_cases increased on the agreement (derived-field reconciliation).
    domain.touch(store.agreements[run["agreement_id"]])
    return success_object(domain.run_view(run), 200)


@bp.route("/potato-ops/production-runs/<rid>/reject", methods=["POST"])
@require_roles("QualityAssuranceLead")
def reject_run(rid):
    body = body_json()
    disposition = None
    if "disposition" not in body or body["disposition"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'disposition': is required", 400)
    if body["disposition"] not in RUN_REJECT_DISPOSITIONS:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'disposition': must be one of CONDEMNED_WASTE, CATTLE_FEED",
            400,
        )
    disposition = body["disposition"]
    run = domain.get_run_or_404(rid)
    if run["status"] != "QA_HOLD":
        raise ApiError(
            "ERR_RUN_INVALID_STAGE", "reject requires the run in QA_HOLD", 409
        )
    run["status"] = "REJECTED"
    domain.touch(run)
    for lot_id in run["input_lot_ids"]:
        lot = store.lots[lot_id]
        if lot["status"] == "ALLOCATED":
            lot["status"] = "CONSUMED"
            domain.touch(lot)
    domain.new_batch(
        source_lot_id=None,
        source_run_id=run["id"],
        stream="REJECTED_PRODUCT",
        routing=disposition,
        weight_cwt=run["total_input_cwt"],
    )
    return success_object(domain.run_view(run), 200)
