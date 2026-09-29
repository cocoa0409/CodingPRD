"""Nominations: submission, withdrawal, revision request, resubmission."""
from flask import Blueprint

import cascades
import serializers as ser
from calc import (cycle_nominations, nomination_tickets, recompute_total_transmix,
                  recompute_totals, segment_of)
from core import (ZERO, apply_filters, authenticate, acting_user, bad_request, db,
                  fail, field_decimal, field_int, get_body, lookup_path, new_row,
                  now, paginate, present, resolve_ref, respond_object, r2, touch)

bp = Blueprint("nominations", __name__)

ALL_ROLES = ("PipelineScheduler", "TariffAdministrator", "TerminalOperator", "Shipper")
STAFF = ("PipelineScheduler", "TariffAdministrator", "TerminalOperator")

TWIN_OPEN_STATUSES = ("SUBMITTED", "ACCEPTED", "WITHDRAWN", "SUPERSEDED", "REJECTED")
LOCKED_STATUSES = ("PRORATED", "SCHEDULED", "REVISION_REQUESTED", "COMPLETED")

WITHDRAW_CYCLE_STATES = {
    "SUBMITTED": ("OPEN", "CLOSED", "PRORATED"),
    "ACCEPTED": ("CLOSED", "PRORATED"),
    "PRORATED": ("PRORATED",),
}


def get_nomination(row_id):
    return lookup_path(db.nominations, row_id, "ERR_NOMINATION_NOT_FOUND")


def own_nomination_or_fail(nomination):
    from core import acting_role
    if acting_role() == "Shipper" and nomination["shipper_id"] != acting_user():
        fail("ERR_NOT_RESOURCE_OWNER", "This nomination belongs to another shipper.")


def in_window(cycle):
    clock = now()
    return cycle["window_open_at"] <= clock < cycle["window_close_at"]


@bp.route("/pipeline/nominations", methods=["POST"])
def submit_nomination():
    authenticate(("Shipper",))
    body = get_body()
    if present(body, "shipper_id") and body["shipper_id"] != acting_user():
        fail("ERR_NOT_RESOURCE_OWNER",
             "A shipper may only nominate on its own behalf.")
    cycle = resolve_ref(body, "cycle_id", db.cycles)
    shipper = resolve_ref(body, "shipper_id", db.shippers)
    grade = resolve_ref(body, "grade_id", db.product_grades)
    origin = resolve_ref(body, "origin_terminal_id", db.terminals)
    destination = resolve_ref(body, "destination_terminal_id", db.terminals)
    supersedes = resolve_ref(body, "supersedes_nomination_id", db.nominations)
    for key, value in (("cycle_id", cycle), ("shipper_id", shipper), ("grade_id", grade),
                       ("origin_terminal_id", origin),
                       ("destination_terminal_id", destination)):
        if value is None:
            bad_request("Required field '{}' is missing.".format(key))
    volume = field_decimal(body, "nominated_bbl", positive=True)
    expected = field_int(body, "expected_cycle_version")

    if cycle["status"] != "OPEN":
        fail("ERR_CYCLE_NOT_OPEN",
             "Cycle {} is {} and no longer collecting nominations.".format(
                 cycle["id"], cycle["status"]))
    if expected != cycle["version"]:
        fail("ERR_STALE_CYCLE_VERSION",
             "Cycle version {} does not match the expected {}.".format(
                 cycle["version"], expected))
    segment = segment_of(cycle)
    if (origin["id"] != segment["origin_terminal_id"]
            or destination["id"] != segment["destination_terminal_id"]):
        fail("ERR_ROUTE_NOT_SERVED",
             "The nominated route is not the cycle segment's origin/destination pair.")
    if not in_window(cycle):
        fail("ERR_NOMINATION_WINDOW_CLOSED",
             "The logical clock is outside the cycle's nomination window.")

    twins = [n for n in cycle_nominations(cycle)
             if n["shipper_id"] == shipper["id"]
             and n["grade_id"] == grade["id"]
             and n["origin_terminal_id"] == origin["id"]
             and n["destination_terminal_id"] == destination["id"]]
    for twin in twins:
        if twin["status"] in LOCKED_STATUSES:
            fail("ERR_NOMINATION_LOCKED",
                 "An existing nomination for this twin key is {}.".format(twin["status"]))
    if shipper["status"] != "ACTIVE":
        fail("ERR_SHIPPER_NOT_ACTIVE", "Shipper {} is not ACTIVE.".format(shipper["id"]))
    if volume < segment["min_tender_bbl"]:
        fail("ERR_TENDER_MINIMUM_NOT_MET",
             "nominated_bbl is below the segment minimum tender of {} bbl.".format(
                 segment["min_tender_bbl"]))

    open_twins = [t for t in twins if t["status"] in ("SUBMITTED", "ACCEPTED")]
    open_twins.sort(key=lambda n: (n["created_at"], n["_seq"]))
    derived = open_twins[-1] if open_twins else None
    targets = []
    if supersedes is not None:
        targets.append(supersedes)
    if derived is not None and (supersedes is None or derived["id"] != supersedes["id"]):
        targets.append(derived)
    for target in targets:
        if target["status"] in ("SUBMITTED", "ACCEPTED"):
            target["status"] = "SUPERSEDED"
            target["allocated_bbl"] = ZERO
            touch(target)
    if supersedes is not None:
        supersedes_id = supersedes["id"]
    elif derived is not None:
        supersedes_id = derived["id"]
    else:
        supersedes_id = None

    row = new_row({
        "cycle_id": cycle["id"],
        "shipper_id": shipper["id"],
        "grade_id": grade["id"],
        "origin_terminal_id": origin["id"],
        "destination_terminal_id": destination["id"],
        "supersedes_nomination_id": supersedes_id,
        "pinned_tariff_id": None,
        "nominated_bbl": r2(volume),
        "allocated_bbl": ZERO,
        "history_base_bbl": r2(0),
        "allocation_class": "NEW_SHIPPER",
        "status": "SUBMITTED",
        "rejection_reason": None,
        "revision_count": 0,
    })
    db.nominations[row["id"]] = row
    touch(cycle)
    recompute_totals(cycle)
    return respond_object(ser.nomination_json(row), 201)


@bp.route("/pipeline/nominations/<row_id>/withdraw", methods=["POST"])
def withdraw(row_id):
    authenticate(("Shipper",))
    nomination = get_nomination(row_id)
    own_nomination_or_fail(nomination)
    get_body()
    if nomination["status"] not in WITHDRAW_CYCLE_STATES:
        fail("ERR_NOMINATION_INVALID_STATE",
             "A nomination in {} cannot be withdrawn.".format(nomination["status"]))
    cycle = db.cycles[nomination["cycle_id"]]
    if cycle["status"] not in WITHDRAW_CYCLE_STATES[nomination["status"]]:
        fail("ERR_NOMINATION_LOCKED",
             "A {} nomination cannot be withdrawn while its cycle is {}.".format(
                 nomination["status"], cycle["status"]))
    was_prorated = cycle["status"] == "PRORATED"
    nomination["status"] = "WITHDRAWN"
    nomination["allocated_bbl"] = ZERO
    touch(nomination)
    if was_prorated:
        cascades.reprorate_after_withdrawal(cycle, segment_of(cycle))
    else:
        recompute_totals(cycle, factor=True)
    return respond_object(ser.nomination_json(nomination))


@bp.route("/pipeline/nominations/<row_id>/request-revision", methods=["POST"])
def request_revision(row_id):
    authenticate(("PipelineScheduler",))
    nomination = get_nomination(row_id)
    get_body()
    if nomination["status"] not in ("PRORATED", "SCHEDULED"):
        fail("ERR_NOMINATION_INVALID_STATE",
             "A nomination in {} cannot be sent back for revision.".format(
                 nomination["status"]))
    cycle = db.cycles[nomination["cycle_id"]]
    allowed = ("PRORATED", "RESEQUENCING") if nomination["status"] == "PRORATED" \
        else ("PUBLISHED", "RESEQUENCING")
    if cycle["status"] not in allowed:
        fail("ERR_NOMINATION_LOCKED",
             "A {} nomination cannot be revised while its cycle is {}.".format(
                 nomination["status"], cycle["status"]))
    tickets = nomination_tickets(nomination["id"])
    for ticket in tickets:
        if ticket["movement_status"] in ("INJECTED", "DELIVERED"):
            fail("ERR_NOMINATION_LOCKED",
                 "Batch ticket {} has already left PLANNED.".format(ticket["id"]))
    nomination["status"] = "REVISION_REQUESTED"
    nomination["allocated_bbl"] = ZERO
    nomination["revision_count"] = nomination["revision_count"] + 1
    touch(nomination)
    for ticket in tickets:
        if ticket["movement_status"] == "PLANNED":
            ticket["movement_status"] = "CANCELLED"
            ticket["cancel_reason"] = "REVISION_REQUESTED"
            touch(ticket)
    recompute_totals(cycle)
    recompute_total_transmix(cycle)
    return respond_object(ser.nomination_json(nomination))


@bp.route("/pipeline/nominations/<row_id>/resubmit", methods=["POST"])
def resubmit(row_id):
    authenticate(("Shipper",))
    nomination = get_nomination(row_id)
    own_nomination_or_fail(nomination)
    body = get_body()
    volume = field_decimal(body, "nominated_bbl", positive=True)
    if nomination["status"] != "REVISION_REQUESTED":
        fail("ERR_NOMINATION_INVALID_STATE",
             "A nomination in {} cannot be resubmitted.".format(nomination["status"]))
    cycle = db.cycles[nomination["cycle_id"]]
    segment = segment_of(cycle)
    if (nomination["origin_terminal_id"] != segment["origin_terminal_id"]
            or nomination["destination_terminal_id"] != segment["destination_terminal_id"]):
        fail("ERR_ROUTE_NOT_SERVED",
             "The nomination's route is not the cycle segment's origin/destination pair.")
    if not in_window(cycle):
        fail("ERR_NOMINATION_WINDOW_CLOSED",
             "The logical clock is outside the cycle's nomination window.")
    shipper = db.shippers[nomination["shipper_id"]]
    if shipper["status"] != "ACTIVE":
        fail("ERR_SHIPPER_NOT_ACTIVE", "Shipper {} is not ACTIVE.".format(shipper["id"]))
    if volume < segment["min_tender_bbl"]:
        fail("ERR_TENDER_MINIMUM_NOT_MET",
             "nominated_bbl is below the segment minimum tender of {} bbl.".format(
                 segment["min_tender_bbl"]))
    if volume > nomination["nominated_bbl"]:
        fail("ERR_REVISION_VOLUME_INCREASE",
             "A resubmission may not exceed the nominated volume of {} bbl.".format(
                 nomination["nominated_bbl"]))
    nomination["nominated_bbl"] = r2(volume)
    nomination["allocated_bbl"] = ZERO
    nomination["status"] = "SUBMITTED"
    touch(nomination)
    recompute_totals(cycle)
    return respond_object(ser.nomination_json(nomination))


@bp.route("/pipeline/nominations/<row_id>", methods=["GET"])
def read_nomination(row_id):
    authenticate(ALL_ROLES)
    nomination = get_nomination(row_id)
    own_nomination_or_fail(nomination)
    return respond_object(ser.nomination_json(nomination))


@bp.route("/pipeline/nominations", methods=["GET"])
def list_nominations():
    authenticate(STAFF)
    rows = apply_filters(list(db.nominations.values()), [
        ("cycle_id", "cycle_id", "str"),
        ("shipper_id", "shipper_id", "str"),
        ("grade_id", "grade_id", "str"),
        ("origin_terminal_id", "origin_terminal_id", "str"),
        ("destination_terminal_id", "destination_terminal_id", "str"),
        ("supersedes_nomination_id", "supersedes_nomination_id", "str"),
        ("pinned_tariff_id", "pinned_tariff_id", "str"),
        ("status", "status", "str"),
    ])
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate(rows, ser.nomination_json)
