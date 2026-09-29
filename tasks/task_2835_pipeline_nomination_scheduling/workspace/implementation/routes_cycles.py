"""Nomination cycle lifecycle (PRD 3.3, 3.4, 3.5, 3.6, 3.9)."""
from flask import Blueprint

import cascades
import serializers as ser
from calc import (apply_effective_capacity, cycle_nominations, cycle_tickets,
                  freeze_history, pin_candidates, recompute_totals, segment_of)
from core import (ZERO, apply_filters, authenticate, acting_user, bad_request, db,
                  fail, field_enum, field_instant, field_string, get_body,
                  lookup_path, new_row, now, paginate, respond_object, resolve_ref,
                  r2, touch)

bp = Blueprint("cycles", __name__)

ALL_ROLES = ("PipelineScheduler", "TariffAdministrator", "TerminalOperator", "Shipper")


def get_cycle(row_id):
    return lookup_path(db.cycles, row_id, "ERR_CYCLE_NOT_FOUND")


@bp.route("/pipeline/cycles", methods=["POST"])
def create_cycle():
    authenticate(("PipelineScheduler",))
    body = get_body()
    segment = resolve_ref(body, "segment_id", db.segments)
    code = field_string(body, "cycle_code")
    if segment is None:
        bad_request("Required field 'segment_id' is missing.")
    window_open = field_instant(body, "window_open_at")
    window_close = field_instant(body, "window_close_at")
    ship_start = field_instant(body, "ship_start_at")
    ship_end = field_instant(body, "ship_end_at")
    for existing in db.cycles.values():
        if existing["segment_id"] == segment["id"] and existing["cycle_code"] == code:
            bad_request("cycle_code '{}' is already used on this segment.".format(code))
    if not (window_open < window_close and window_close <= ship_start and ship_start < ship_end):
        fail("ERR_INVALID_WINDOW",
             "Cycle instants must satisfy window_open_at < window_close_at <= "
             "ship_start_at < ship_end_at.")
    row = new_row({
        "cycle_code": code,
        "segment_id": segment["id"],
        "window_open_at": window_open,
        "window_close_at": window_close,
        "ship_start_at": ship_start,
        "ship_end_at": ship_end,
        "status": "OPEN",
        "effective_capacity_bbl": ZERO,
        "derate_pct_applied": r2(0),
        "nominated_total_bbl": r2(0),
        "allocated_total_bbl": ZERO,
        "unallocated_capacity_bbl": ZERO,
        "proration_factor": None,
        "total_transmix_bbl": ZERO,
        "schedule_version": 0,
        "schedule_published_at": None,
        "schedule_published_by_user_id": None,
        "settled_at": None,
    })
    db.cycles[row["id"]] = row
    return respond_object(ser.cycle_json(row), 201)


@bp.route("/pipeline/cycles/<row_id>/close", methods=["POST"])
def close_cycle(row_id):
    authenticate(("PipelineScheduler",))
    cycle = get_cycle(row_id)
    get_body()
    if cycle["status"] != "OPEN":
        fail("ERR_CYCLE_INVALID_STATE",
             "A cycle in {} cannot be closed.".format(cycle["status"]))
    segment = segment_of(cycle)
    submitted = [n for n in cycle_nominations(cycle) if n["status"] == "SUBMITTED"]

    # all-or-nothing tariff resolvability gate
    pinned = {}
    for nomination in submitted:
        candidates = pin_candidates(cycle, nomination)
        if not candidates:
            fail("ERR_NO_EFFECTIVE_TARIFF",
                 "No EFFECTIVE tariff covers nomination {} at the closing instant.".format(
                     nomination["id"]))
        pinned[nomination["id"]] = candidates[0]

    accepted = []
    for nomination in submitted:
        tariff = pinned[nomination["id"]]
        nomination["pinned_tariff_id"] = tariff["id"]
        if nomination["nominated_bbl"] >= tariff["tender_minimum_bbl"]:
            nomination["status"] = "ACCEPTED"
            accepted.append(nomination)
        else:
            nomination["status"] = "REJECTED"
            nomination["rejection_reason"] = "BELOW_TENDER_MINIMUM"
            nomination["allocated_bbl"] = ZERO
        touch(nomination)

    apply_effective_capacity(cycle, segment)
    freeze_history(cycle, accepted)
    cycle["status"] = "CLOSED"
    recompute_totals(cycle, factor=True)
    return respond_object(ser.cycle_json(cycle))


@bp.route("/pipeline/cycles/<row_id>/prorate", methods=["POST"])
def prorate(row_id):
    authenticate(("PipelineScheduler",))
    cycle = get_cycle(row_id)
    get_body()
    if cycle["status"] not in ("CLOSED", "RESEQUENCING"):
        fail("ERR_CYCLE_INVALID_STATE",
             "A cycle in {} cannot be prorated.".format(cycle["status"]))
    cascades.prorate_cycle(cycle, segment_of(cycle))
    return respond_object(ser.cycle_json(cycle))


@bp.route("/pipeline/cycles/<row_id>/build-schedule", methods=["POST"])
def build_schedule(row_id):
    authenticate(("PipelineScheduler",))
    cycle = get_cycle(row_id)
    get_body()
    if cycle["status"] != "PRORATED":
        fail("ERR_CYCLE_INVALID_STATE",
             "A schedule can only be built from PRORATED, not {}.".format(cycle["status"]))
    cascades.build_schedule(cycle, segment_of(cycle))
    return respond_object(ser.cycle_json(cycle))


@bp.route("/pipeline/cycles/<row_id>/publish-schedule", methods=["POST"])
def publish_schedule(row_id):
    authenticate(("PipelineScheduler",))
    cycle = get_cycle(row_id)
    get_body()
    if cycle["status"] != "SCHEDULED":
        fail("ERR_CYCLE_INVALID_STATE",
             "A schedule can only be published from SCHEDULED, not {}.".format(cycle["status"]))
    segment = segment_of(cycle)
    if segment["linefill_bbl"] < segment["linefill_requirement_bbl"]:
        fail("ERR_LINEFILL_REQUIREMENT_NOT_MET",
             "Segment linefill of {} bbl is below the requirement of {} bbl.".format(
                 segment["linefill_bbl"], segment["linefill_requirement_bbl"]))
    cycle["status"] = "PUBLISHED"
    cycle["schedule_version"] = cycle["schedule_version"] + 1
    cycle["schedule_published_at"] = now()
    cycle["schedule_published_by_user_id"] = acting_user()
    touch(cycle)
    for nomination in cycle_nominations(cycle):
        if nomination["status"] == "PRORATED":
            nomination["status"] = "SCHEDULED"
            touch(nomination)
    recompute_totals(cycle)
    return respond_object(ser.cycle_json(cycle))


@bp.route("/pipeline/cycles/<row_id>/settle", methods=["POST"])
def settle(row_id):
    authenticate(("PipelineScheduler",))
    cycle = get_cycle(row_id)
    body = get_body()
    basis_mode = field_enum(body, "basis_mode", ("SCHEDULED", "DELIVERED"))
    if cycle["status"] != "PUBLISHED":
        fail("ERR_CYCLE_INVALID_STATE",
             "A cycle in {} cannot be settled.".format(cycle["status"]))
    for ticket in cycle_tickets(cycle["id"]):
        if ticket["movement_status"] not in ("DELIVERED", "CANCELLED"):
            fail("ERR_BATCHES_IN_TRANSIT",
                 "Batch ticket {} is still {}.".format(ticket["id"], ticket["movement_status"]))
    cascades.settle_cycle(cycle, basis_mode, acting_user())
    return respond_object(ser.cycle_json(cycle))


@bp.route("/pipeline/cycles/<row_id>", methods=["GET"])
def read_cycle(row_id):
    authenticate(ALL_ROLES)
    cycle = get_cycle(row_id)
    return respond_object(ser.cycle_json(cycle))


@bp.route("/pipeline/cycles", methods=["GET"])
def list_cycles():
    authenticate(ALL_ROLES)
    rows = apply_filters(list(db.cycles.values()), [
        ("segment_id", "segment_id", "str"),
        ("status", "status", "str"),
    ])
    rows.sort(key=lambda r: (r["window_open_at"], r["created_at"], r["_seq"]))
    return paginate(rows, ser.cycle_json)
