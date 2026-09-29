"""Venue inventory, section pricing and the renovation pipeline (PRD 3.7)."""
from flask import Blueprint

import auth
import calc
import clock
import derive
import envelope
import enums
import num
import serial
import validation as v
from errors import err, invalid, invalid_state
from store import DB, by_created_at, check_version, get_body_ref, get_path, new_row, touch

bp = Blueprint("sections", __name__)


def _section_code_taken(code):
    for row in DB.sections.values():
        if row["section_code"] == code:
            return True
    return False


def _seat_taken(section_id, row_label, seat_number):
    for row in DB.seats.values():
        if (row["section_id"] == section_id
                and row["row_label"] == row_label
                and int(row["seat_number"]) == int(seat_number)):
            return True
    return False


def _require_open_section(section):
    """PRD section 2.8 step 11."""
    if section["status"] != "OPEN":
        raise err("ERR_SECTION_UNDER_RENOVATION",
                  "section '%s' is %s and does not accept this operation"
                  % (section["id"], section["status"]))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/athletics/sections")
def list_sections():
    auth.require(auth.NO_ANALYST)
    status = v.q_enum("status", enums.SECTION_STATUSES)
    renovation_status = v.q_enum("renovation_status", enums.RENOVATION_STATUSES)
    posture = v.q_enum("pricing_posture", enums.PRICING_POSTURES)
    reseating_id = v.q_str("reseating_recalculation_id")
    venue_code = v.q_str("venue_code")
    rows = list(DB.sections.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if renovation_status is not None:
        rows = [r for r in rows if r["renovation_status"] == renovation_status]
    if posture is not None:
        rows = [r for r in rows if r["pricing_posture"] == posture]
    if reseating_id is not None:
        rows = [r for r in rows if r["reseating_recalculation_id"] == reseating_id]
    if venue_code is not None:
        rows = [r for r in rows if r["venue_code"] == venue_code]
    return envelope.paginated(by_created_at(rows), serial.section)


@bp.get("/athletics/sections/<section_id>")
def get_section(section_id):
    auth.require(auth.NO_ANALYST)
    section = get_path("section", section_id)
    return envelope.ok(serial.section(section))


@bp.get("/athletics/sections/<section_id>/seats")
def list_section_seats(section_id):
    auth.require(auth.NO_ANALYST)
    section = get_path("section", section_id)
    seat_status = v.q_enum("seat_status", enums.SEAT_STATUSES)
    row_label = v.q_str("row_label")
    rows = derive.section_seats(section)
    if seat_status is not None:
        rows = [r for r in rows if r["seat_status"] == seat_status]
    if row_label is not None:
        rows = [r for r in rows if r["row_label"] == row_label]
    return envelope.paginated(rows, serial.seat)


@bp.get("/athletics/sections/<section_id>/pricing-sensitivity")
def pricing_sensitivity(section_id):
    auth.require(auth.SECTION_READERS)
    section = get_path("section", section_id)
    ratio = calc.underwater_ratio(section["underwater_seat_count"],
                                  section["assigned_seat_count"])
    return envelope.ok({
        "section_code": section["section_code"],
        "per_seat_requirement_cents": int(section["per_seat_requirement_cents"]),
        "required_points_per_seat": num.points_out(section["required_points_per_seat"]),
        "assigned_seat_count": int(section["assigned_seat_count"]),
        "underwater_seat_count": int(section["underwater_seat_count"]),
        "underwater_ratio": num.ratio_out(ratio),
        "pricing_posture": section["pricing_posture"],
        "requirement_history": [
            {"cycle_year": int(e["cycle_year"]),
             "per_seat_requirement_cents": int(e["per_seat_requirement_cents"])}
            for e in section["requirement_history"]
        ],
        "recommended_requirement_cents": calc.recommended_requirement_cents(section),
    })


@bp.get("/athletics/seats/<seat_id>")
def get_seat(seat_id):
    auth.require(auth.NO_ANALYST)
    seat = get_path("seat", seat_id)
    return envelope.ok(serial.seat(seat))


# ---------------------------------------------------------------------------
# Inventory writes
# ---------------------------------------------------------------------------
@bp.post("/athletics/sections")
def create_section():
    auth.require(auth.ADMIN_ONLY)
    body = v.body_dict()
    section_code = v.str_field(body, "section_code", min_len=1, max_len=16)
    venue_code = v.str_field(body, "venue_code", min_len=1, max_len=32)
    seat_capacity = v.int_field(body, "seat_capacity", minimum=1)
    requirement = v.int_field(body, "per_seat_requirement_cents", minimum=1)
    required_points = v.num_field(body, "required_points_per_seat", minimum=0)
    if _section_code_taken(section_code):
        raise invalid("'section_code' must be unique across all sections")
    cycle_year = clock.utc_year(clock.now())
    row = new_row(
        section_code=section_code,
        venue_code=venue_code,
        seat_capacity=seat_capacity,
        per_seat_requirement_cents=requirement,
        required_points_per_seat=required_points,
        requirement_history=[{"cycle_year": cycle_year,
                              "per_seat_requirement_cents": requirement}],
        status="OPEN",
        renovation_status="NONE",
        post_renovation_capacity=None,
        post_renovation_requirement_cents=None,
        reseating_recalculation_id=None,
        reseated_donor_count=0,
        reseating_invoice_total_cents=0,
        seat_row_count=0,
        seats_available=0,
        seats_committed_count=0,
        decommissioned_seat_count=0,
        assigned_seat_count=0,
        underwater_seat_count=0,
        pricing_posture="NORMAL",
    )
    DB.sections[row["id"]] = row
    return envelope.created(serial.section(row))


@bp.post("/athletics/sections/<section_id>/seats")
def create_seat(section_id):
    auth.require(auth.ADMIN_ONLY)
    section = get_path("section", section_id)
    body = v.body_dict()
    row_label = v.str_field(body, "row_label", min_len=1, max_len=8)
    seat_number = v.int_field(body, "seat_number", minimum=1)
    max_holds = v.int_field(body, "max_concurrent_holds", required=False,
                            minimum=1, default=1)
    if _seat_taken(section["id"], row_label, seat_number):
        raise invalid("this section already has seat %s%s" % (row_label, seat_number))
    _require_open_section(section)
    if int(section["seat_row_count"]) + 1 > int(section["seat_capacity"]):
        raise err("ERR_SECTION_CAPACITY_EXCEEDED",
                  "the section's seat_capacity of %d is already filled"
                  % int(section["seat_capacity"]))
    seat = new_row(
        section_id=section["id"],
        row_label=row_label,
        seat_number=seat_number,
        seat_status="AVAILABLE",
        max_concurrent_holds=max_holds,
    )
    DB.seats[seat["id"]] = seat
    derive.recompute_section(section)
    touch(section)
    return envelope.created(serial.seat(seat))


@bp.post("/athletics/sections/<section_id>/reprice")
def reprice_section(section_id):
    auth.require(auth.ADMIN_ONLY)
    section = get_path("section", section_id)
    body = v.body_dict()
    requirement = v.int_field(body, "per_seat_requirement_cents", minimum=1)
    cycle_year = v.year_field(body, "cycle_year")
    expected = v.version_field(body, "expected_section_version")
    check_version(section, expected, "section")
    section["per_seat_requirement_cents"] = requirement
    section["requirement_history"].append(
        {"cycle_year": cycle_year, "per_seat_requirement_cents": requirement})
    touch(section)
    return envelope.ok(serial.section(section))


# ---------------------------------------------------------------------------
# The renovation pipeline
# ---------------------------------------------------------------------------
def _start_reseating(section, recalc):
    """The heavy action: retire surplus seats, then reprice and re-invoice."""
    cycle_year = int(recalc["cycle_year"])
    capacity = int(section["post_renovation_capacity"])
    requirement = int(section["post_renovation_requirement_cents"])
    section["seat_capacity"] = capacity
    section["per_seat_requirement_cents"] = requirement
    section["requirement_history"].append(
        {"cycle_year": cycle_year, "per_seat_requirement_cents": requirement})
    # Seats beyond the new capacity retire, taken in created_at ascending order.
    for ordinal, seat in enumerate(derive.section_seats(section), start=1):
        if ordinal > capacity and seat["seat_status"] == "AVAILABLE":
            seat["seat_status"] = "DECOMMISSIONED"
            touch(seat)
    # Each live row is repriced under its own pricing_mode, then prorated at
    # seven twelfths and rounded BEFORE it joins the running total.
    total = 0
    count = 0
    for row in derive.section_assignments(section):
        base = calc.seat_requirement_cents(
            section, row["pricing_mode"], row["grandfathered_requirement_cents"],
            cycle_year, row["first_occupied_cycle_year"])
        share = calc.reseating_share_cents(base)
        row["requirement_cents"] = share
        total += share
        count += 1
        row["total_due_cents"] = share + int(row["handling_fee_cents"])
        row["payment_status"] = "INVOICED"
        touch(row)
    section["reseating_recalculation_id"] = recalc["id"]
    section["reseated_donor_count"] = count
    section["reseating_invoice_total_cents"] = total


@bp.post("/athletics/sections/<section_id>/renovation")
def renovate_section(section_id):
    auth.require(auth.ADMIN_ONLY)
    section = get_path("section", section_id)
    body = v.body_dict()
    action = v.enum_field(body, "renovation_action", enums.RENOVATION_ACTIONS)
    capacity = v.int_field(body, "post_renovation_capacity", required=False, minimum=1)
    requirement = v.int_field(body, "post_renovation_requirement_cents",
                              required=False, minimum=1)
    recalc_id = v.id_field(body, "reseating_recalculation_id", required=False)
    expected = v.version_field(body, "expected_section_version")
    recalc = get_body_ref("recalculation", recalc_id) if recalc_id is not None else None
    check_version(section, expected, "section")
    current = section["renovation_status"]
    if action == "SURVEY":
        if current != "NONE":
            raise invalid_state("a survey requires renovation_status NONE")
        if section["status"] != "OPEN":
            raise invalid_state("a survey requires the section's status to be OPEN")
        section["renovation_status"] = "SURVEYED"
        section["status"] = "UNDER_RENOVATION"
    elif action == "REPRICE":
        if current != "SURVEYED":
            raise invalid_state("a reprice requires renovation_status SURVEYED")
        if capacity is None or requirement is None:
            raise invalid_state(
                "a reprice requires both post_renovation_capacity and "
                "post_renovation_requirement_cents")
        section["renovation_status"] = "REPRICED"
        section["post_renovation_capacity"] = capacity
        section["post_renovation_requirement_cents"] = requirement
    elif action == "START_RESEATING":
        if current != "REPRICED":
            raise invalid_state("starting a reseating requires renovation_status REPRICED")
        if recalc is None:
            raise invalid_state(
                "starting a reseating requires a reseating_recalculation_id")
        if recalc["status"] != "CERTIFIED":
            raise err("ERR_RECALCULATION_NOT_CERTIFIED",
                      "the reseating recalculation must be in CERTIFIED")
        section["renovation_status"] = "RESEATING"
        _start_reseating(section, recalc)
    elif action == "COMPLETE":
        if current != "RESEATING":
            raise invalid_state("completing a renovation requires renovation_status RESEATING")
        section["renovation_status"] = "COMPLETED"
        section["status"] = "OPEN"
    else:
        if current not in ("SURVEYED", "REPRICED"):
            raise invalid_state(
                "a renovation may only be abandoned from SURVEYED or REPRICED")
        section["renovation_status"] = "ABANDONED"
        section["status"] = "OPEN"
        section["post_renovation_capacity"] = None
        section["post_renovation_requirement_cents"] = None
    derive.recompute_section(section)
    touch(section)
    return envelope.ok(serial.section(section))
