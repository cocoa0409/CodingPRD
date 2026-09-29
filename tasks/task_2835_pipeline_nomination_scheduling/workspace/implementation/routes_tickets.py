"""Batch tickets: injection, quality refusal, delivery, cancellation, reschedule."""
from decimal import Decimal

from flask import Blueprint

import calc
import serializers as ser
from calc import (bay_occupancy, cycle_tickets, pinned_tariff, recompute_total_transmix,
                  recompute_totals, refresh_exposure, shipper_exposure, ticket_line_value)
from core import (ZERO, acting_role, acting_user, apply_filters, authenticate,
                  bad_request, db, fail, field_decimal, field_instant, field_string,
                  get_body, lookup_path, paginate, respond_object, r2, touch)

bp = Blueprint("tickets", __name__)

ALL_ROLES = ("PipelineScheduler", "TariffAdministrator", "TerminalOperator", "Shipper")
STAFF = ("PipelineScheduler", "TariffAdministrator", "TerminalOperator")


def get_ticket(row_id):
    return lookup_path(db.batch_tickets, row_id, "ERR_BATCH_TICKET_NOT_FOUND")


def context(ticket):
    nomination = db.nominations[ticket["nomination_id"]]
    cycle = db.cycles[ticket["cycle_id"]]
    segment = db.segments[cycle["segment_id"]]
    shipper = db.shippers[nomination["shipper_id"]]
    grade = db.product_grades[nomination["grade_id"]]
    return nomination, cycle, segment, shipper, grade


@bp.route("/pipeline/batch-tickets/<row_id>/inject", methods=["POST"])
def inject(row_id):
    authenticate(("TerminalOperator",))
    ticket = get_ticket(row_id)
    body = get_body()
    sulfur = field_decimal(body, "measured_sulfur_ppm", non_negative=True)
    rvp = field_decimal(body, "measured_rvp_psi", non_negative=True)
    volume = field_decimal(body, "injected_bbl", positive=True)
    nomination, cycle, segment, shipper, grade = context(ticket)

    if cycle["status"] != "PUBLISHED":
        fail("ERR_CYCLE_INVALID_STATE",
             "An injection requires a PUBLISHED cycle, not {}.".format(cycle["status"]))
    quality_ok_to_try = (ticket["quality_status"] == "PENDING"
                         or (ticket["quality_status"] == "REJECTED"
                             and ticket["retest_count"] < 2))
    if ticket["movement_status"] != "PLANNED" or not quality_ok_to_try:
        fail("ERR_TICKET_INVALID_STATE",
             "This batch ticket cannot be injected from movement {} / quality {}.".format(
                 ticket["movement_status"], ticket["quality_status"]))

    off_spec = sulfur > grade["max_sulfur_ppm"] or rvp > grade["max_rvp_psi"]
    if off_spec:
        ticket["quality_status"] = "REJECTED"
        ticket["measured_sulfur_ppm"] = sulfur
        ticket["measured_rvp_psi"] = rvp
        ticket["retest_count"] = ticket["retest_count"] + 1
        touch(ticket)
        if ticket["retest_count"] >= 2:
            ticket["movement_status"] = "CANCELLED"
            ticket["cancel_reason"] = "QUALITY_RETEST_LIMIT"
            if nomination["status"] == "SCHEDULED":
                nomination["status"] = "REVISION_REQUESTED"
            nomination["revision_count"] = nomination["revision_count"] + 1
            nomination["allocated_bbl"] = ZERO
            touch(nomination)
            recompute_totals(cycle)
            recompute_total_transmix(cycle)
        fail("ERR_QUALITY_SPEC_VIOLATION",
             "Measured quality is outside the specification ceilings of grade {}.".format(
                 grade["grade_code"]))

    if segment["operational_status"] == "SHUT":
        fail("ERR_SEGMENT_UNAVAILABLE", "Segment {} is SHUT.".format(segment["segment_code"]))
    if shipper["status"] != "ACTIVE":
        fail("ERR_SHIPPER_NOT_ACTIVE", "Shipper {} is not ACTIVE.".format(shipper["id"]))

    origin = db.terminals[nomination["origin_terminal_id"]]
    debit = volume + ticket["transmix_bbl"]
    if origin["inventory_bbl"] - debit < origin["min_operating_inventory_bbl"]:
        fail("ERR_INSUFFICIENT_ORIGIN_INVENTORY",
             "Origin terminal would fall below its minimum operating inventory.")

    line_value = ticket_line_value(ticket)
    if shipper_exposure(shipper) + line_value > shipper["credit_limit_usd"]:
        fail("ERR_CREDIT_LIMIT_EXCEEDED",
             "The injection would exceed the shipper's credit limit.")

    ticket["quality_status"] = "PASSED"
    ticket["measured_sulfur_ppm"] = sulfur
    ticket["measured_rvp_psi"] = rvp
    ticket["injected_bbl"] = r2(volume)
    ticket["movement_status"] = "INJECTED"
    touch(ticket)
    origin["inventory_bbl"] = r2(origin["inventory_bbl"] - debit)
    touch(origin)
    segment["in_transit_bbl"] = r2(segment["in_transit_bbl"] + volume)
    segment["transmix_inventory_bbl"] = r2(
        segment["transmix_inventory_bbl"] + ticket["transmix_bbl"])
    touch(segment)
    refresh_exposure(shipper)
    return respond_object(ser.ticket_json(ticket))


@bp.route("/pipeline/batch-tickets/<row_id>/deliver", methods=["POST"])
def deliver(row_id):
    authenticate(("TerminalOperator",))
    ticket = get_ticket(row_id)
    body = get_body()
    volume = field_decimal(body, "delivered_bbl", positive=True)
    nomination, cycle, segment, shipper, grade = context(ticket)
    if ticket["movement_status"] != "INJECTED":
        fail("ERR_TICKET_INVALID_STATE",
             "A delivery requires an INJECTED ticket, not {}.".format(ticket["movement_status"]))
    injected = ticket["injected_bbl"] or ZERO
    if volume > injected:
        bad_request("'delivered_bbl' may not exceed the injected volume of {} bbl.".format(
            injected))
    destination = db.terminals[nomination["destination_terminal_id"]]
    if destination["inventory_bbl"] + volume > destination["shell_capacity_bbl"]:
        fail("ERR_DESTINATION_CAPACITY_EXCEEDED",
             "The destination terminal has no room for {} bbl.".format(volume))
    ticket["delivered_bbl"] = r2(volume)
    ticket["movement_status"] = "DELIVERED"
    touch(ticket)
    destination["inventory_bbl"] = r2(destination["inventory_bbl"] + volume)
    touch(destination)
    segment["in_transit_bbl"] = r2(segment["in_transit_bbl"] - injected)
    segment["system_loss_bbl"] = r2(segment["system_loss_bbl"] + (injected - volume))
    touch(segment)
    refresh_exposure(shipper)
    return respond_object(ser.ticket_json(ticket))


@bp.route("/pipeline/batch-tickets/<row_id>/cancel", methods=["POST"])
def cancel(row_id):
    authenticate(("PipelineScheduler", "TerminalOperator"))
    ticket = get_ticket(row_id)
    body = get_body()
    reason = field_string(body, "cancel_reason")
    nomination, cycle, segment, shipper, grade = context(ticket)
    previous = ticket["movement_status"]
    if previous not in ("PLANNED", "INJECTED"):
        fail("ERR_TICKET_INVALID_STATE",
             "A {} ticket cannot be cancelled.".format(previous))
    ticket["movement_status"] = "CANCELLED"
    ticket["cancel_reason"] = reason
    touch(ticket)
    if previous == "INJECTED":
        injected = ticket["injected_bbl"] or ZERO
        origin = db.terminals[nomination["origin_terminal_id"]]
        origin["inventory_bbl"] = r2(origin["inventory_bbl"] + injected + ticket["transmix_bbl"])
        touch(origin)
        segment["in_transit_bbl"] = r2(segment["in_transit_bbl"] - injected)
        segment["transmix_inventory_bbl"] = r2(
            segment["transmix_inventory_bbl"] - ticket["transmix_bbl"])
        touch(segment)
    recompute_total_transmix(cycle)
    refresh_exposure(shipper)
    return respond_object(ser.ticket_json(ticket))


@bp.route("/pipeline/batch-tickets/<row_id>/reschedule-window", methods=["POST"])
def reschedule_window(row_id):
    authenticate(("PipelineScheduler",))
    ticket = get_ticket(row_id)
    body = get_body()
    start = field_instant(body, "injection_window_start")
    end = field_instant(body, "injection_window_end")
    nomination, cycle, segment, shipper, grade = context(ticket)
    if ticket["movement_status"] != "PLANNED":
        fail("ERR_TICKET_INVALID_STATE",
             "Only a PLANNED ticket can be rescheduled, not {}.".format(
                 ticket["movement_status"]))
    if end <= start:
        fail("ERR_INVALID_WINDOW",
             "'injection_window_end' must be strictly later than 'injection_window_start'.")
    if start < cycle["ship_start_at"] or end > cycle["ship_end_at"]:
        fail("ERR_INVALID_WINDOW",
             "The requested window must lie inside the cycle's shipping window.")
    if segment["operational_status"] == "SHUT":
        fail("ERR_SEGMENT_UNAVAILABLE", "Segment {} is SHUT.".format(segment["segment_code"]))
    peers = bay_occupancy(ticket, nomination["origin_terminal_id"], start, end)
    origin = db.terminals[nomination["origin_terminal_id"]]
    if peers >= origin["injection_bays"]:
        fail("ERR_TERMINAL_BAY_CONFLICT",
             "{} planned batches already occupy the {} injection bay(s).".format(
                 peers, origin["injection_bays"]))
    ticket["injection_window_start"] = start
    ticket["injection_window_end"] = end
    touch(ticket)
    return respond_object(ser.ticket_json(ticket))


@bp.route("/pipeline/batch-tickets/<row_id>", methods=["GET"])
def read_ticket(row_id):
    authenticate(ALL_ROLES)
    ticket = get_ticket(row_id)
    if acting_role() == "Shipper":
        nomination = db.nominations.get(ticket["nomination_id"])
        if nomination is None or nomination["shipper_id"] != acting_user():
            fail("ERR_NOT_RESOURCE_OWNER", "This batch ticket belongs to another shipper.")
    return respond_object(ser.ticket_json(ticket))


@bp.route("/pipeline/batch-tickets", methods=["GET"])
def list_tickets():
    authenticate(STAFF)
    rows = apply_filters(list(db.batch_tickets.values()), [
        ("cycle_id", "cycle_id", "str"),
        ("nomination_id", "nomination_id", "str"),
        ("predecessor_batch_id", "predecessor_batch_id", "str"),
        ("movement_status", "movement_status", "str"),
        ("quality_status", "quality_status", "str"),
    ])
    rows.sort(key=lambda r: (r["sequence_position"], r["created_at"], r["_seq"]))
    return paginate(rows, ser.ticket_json)
