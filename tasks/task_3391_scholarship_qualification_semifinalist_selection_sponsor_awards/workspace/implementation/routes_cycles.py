"""Program cycle endpoints: creation, posture transitions, selection,
publish-finalists, award matching, and state-allocation listing."""

from flask import Blueprint, g

import constants as C
import services
from errors import err
from helpers import (
    body,
    check_datetime_field,
    check_int_field,
    created_key,
    is_int,
    paginate,
    require_present,
    require_roles,
    resp_object,
    bad,
)
from serializers import ser_allocation, ser_cycle
from store import base_record, db, touch

bp = Blueprint("cycles", __name__)

_ALL = C.ALL_ROLES


def _get_cycle_or_404(cycle_id):
    cycle = db["cycles"].get(cycle_id)
    if cycle is None:
        err("ERR_NOT_FOUND", "program cycle not found")
    return cycle


@bp.route("/api/program-cycles", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def create_cycle():
    b = body()
    # Field-shape validation (priority 10); cycle creation has no higher-tier
    # domain checks, so every rejection here is ERR_INVALID_REQUEST.
    require_present(
        b,
        "name",
        "target_graduation_year",
        "total_semifinalist_slots",
        "national_award_slots",
        "national_award_amount_cents",
        "confirming_floor",
        "application_deadline",
        "semifinalist_embargo_until",
        "finalist_embargo_until",
        "award_embargo_until",
        "public_embargo_until",
        "state_populations",
    )
    if not isinstance(b["name"], str):
        bad("name must be a string")
    check_int_field(b, "target_graduation_year")
    check_int_field(b, "total_semifinalist_slots", minimum=1)
    check_int_field(b, "national_award_slots", minimum=0)
    check_int_field(b, "national_award_amount_cents", minimum=1)
    check_int_field(b, "confirming_floor", minimum=C.CONFIRMING_MIN, maximum=C.CONFIRMING_MAX)
    for f in (
        "application_deadline",
        "semifinalist_embargo_until",
        "finalist_embargo_until",
        "award_embargo_until",
        "public_embargo_until",
    ):
        check_datetime_field(b, f)
    if not isinstance(b["state_populations"], list):
        bad("state_populations must be a list")
    for item in b["state_populations"]:
        if not isinstance(item, dict):
            bad("state_populations entries must be objects")
        if not isinstance(item.get("state_code"), str) or not item.get("state_code"):
            bad("state_populations entries require a state_code")
        if not is_int(item.get("graduating_population")) or item["graduating_population"] < 0:
            bad("graduating_population must be an integer >= 0")
    populated = sum(1 for item in b["state_populations"] if item["graduating_population"] > 0)
    if populated > b["total_semifinalist_slots"]:
        bad("count of states with population > 0 may not exceed total_semifinalist_slots")

    rec = base_record()
    rec.update(
        {
            "name": b["name"],
            "target_graduation_year": b["target_graduation_year"],
            "total_semifinalist_slots": b["total_semifinalist_slots"],
            "national_award_slots": b["national_award_slots"],
            "national_award_amount_cents": b["national_award_amount_cents"],
            "confirming_floor": b["confirming_floor"],
            "application_deadline": b["application_deadline"],
            "semifinalist_embargo_until": b["semifinalist_embargo_until"],
            "finalist_embargo_until": b["finalist_embargo_until"],
            "award_embargo_until": b["award_embargo_until"],
            "public_embargo_until": b["public_embargo_until"],
            "status": "SETUP",
            "matching_run": False,
        }
    )
    db["cycles"][rec["id"]] = rec
    for item in b["state_populations"]:
        alloc = base_record()
        alloc.update(
            {
                "cycle_id": rec["id"],
                "state_code": item["state_code"],
                "graduating_population": item["graduating_population"],
                "quota_raw": None,
                "slots_provisional": None,
                "slots_final": None,
                "threshold_selection_index": None,
                "selected_count": 0,
                "status": "PENDING",
            }
        )
        db["allocations"][alloc["id"]] = alloc
    return resp_object(ser_cycle(rec), code=201)


@bp.route("/api/program-cycles/<cycle_id>", methods=["GET"])
@require_roles(*_ALL)
def get_cycle(cycle_id):
    return resp_object(ser_cycle(_get_cycle_or_404(cycle_id)))


@bp.route("/api/program-cycles/<cycle_id>/state-allocations", methods=["GET"])
@require_roles(*_ALL)
def list_state_allocations(cycle_id):
    _get_cycle_or_404(cycle_id)
    allocs = sorted(services.cycle_allocations(cycle_id), key=lambda a: a["state_code"])
    return paginate(allocs, ser_allocation)


@bp.route("/api/program-cycles/<cycle_id>/open-entries", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def open_entries(cycle_id):
    cycle = _get_cycle_or_404(cycle_id)
    if cycle["status"] != "SETUP":
        err("ERR_INVALID_STATE", "open-entries requires SETUP posture")
    cycle["status"] = "ENTRY_OPEN"
    touch(cycle)
    return resp_object(ser_cycle(cycle))


@bp.route("/api/program-cycles/<cycle_id>/close-entries", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def close_entries(cycle_id):
    cycle = _get_cycle_or_404(cycle_id)
    if cycle["status"] != "ENTRY_OPEN":
        err("ERR_INVALID_STATE", "close-entries requires ENTRY_OPEN posture")
    services.close_entries(cycle)
    return resp_object(ser_cycle(cycle))


@bp.route("/api/program-cycles/<cycle_id>/run-semifinalist-selection", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def run_selection(cycle_id):
    cycle = _get_cycle_or_404(cycle_id)
    if cycle["status"] != "ENTRY_CLOSED":
        err("ERR_INVALID_STATE", "run-semifinalist-selection requires ENTRY_CLOSED posture")
    for e in db["entries"].values():
        if e["cycle_id"] == cycle["id"] and e["status"] == "SUBMITTED":
            err("ERR_UNSCORED_ENTRIES_REMAIN", "entries of this cycle remain unscored")
    summary = services.run_semifinalist_selection(cycle)
    return resp_object(summary)


@bp.route("/api/program-cycles/<cycle_id>/publish-finalists", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def publish(cycle_id):
    cycle = _get_cycle_or_404(cycle_id)
    if cycle["status"] != "SEMIFINALISTS_SELECTED":
        err("ERR_CYCLE_POSTURE_INVALID", "publish-finalists requires SEMIFINALISTS_SELECTED posture")
    for app in db["applications"].values():
        entry = db["entries"][app["entry_id"]]
        if entry["cycle_id"] == cycle["id"] and app["status"] in (
            "UNDER_REVIEW",
            "RETURNED_FOR_CORRECTION",
        ):
            err("ERR_PENDING_APPLICATIONS_REMAIN", "applications remain under review or returned")
    services.publish_finalists(cycle)
    return resp_object(ser_cycle(cycle))


@bp.route("/api/program-cycles/<cycle_id>/run-award-matching", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def run_matching(cycle_id):
    cycle = _get_cycle_or_404(cycle_id)
    if cycle["status"] != "FINALISTS_SELECTED":
        err("ERR_CYCLE_POSTURE_INVALID", "run-award-matching requires FINALISTS_SELECTED posture")
    if cycle["matching_run"]:
        err("ERR_MATCHING_ALREADY_RUN", "award matching already ran for this cycle")
    summary = services.run_award_matching(cycle)
    return resp_object(summary)
