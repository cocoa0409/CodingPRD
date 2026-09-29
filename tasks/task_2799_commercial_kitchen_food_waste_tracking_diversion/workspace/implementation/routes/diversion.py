"""Diversion consignments, allocation lines and weigh tickets."""
from flask import Blueprint

from db import base_row, db, iso, new_id, parse_ts, plus_hours, touch
from errors import fail
from middleware import (ALL_READERS, HAULER_OPERATOR, HAULER_READERS, SHIFT_LEAD,
                        SITE_MANAGER, authenticate, require_hauler_scope,
                        require_site_scope)
from response import object_response, row_response
from routes.common import filtered, must_exist, respond_list
from services import calc, derive
from services.calc import D, num
from validation import (bad, body_json, field_date, field_enum, field_int,
                       field_str, field_ts, query_date, query_enum, query_str)

bp = Blueprint("diversion", __name__)

CHANNELS = ("DONATION", "ANIMAL_FEED", "COMPOST", "LANDFILL")
LOGISTICS_STATUSES = ("DRAFT", "STAGED", "DISPATCHED", "COMPLETED", "CANCELLED")
SETTLEMENT_STATUSES = ("UNBILLED", "TICKET_SUBMITTED", "SETTLED", "DISPUTED")
TICKET_STATUSES = ("SUBMITTED", "ACCEPTED", "DISPUTED")


def _posture_block(consignment, site):
    if (consignment["channel"] == "DONATION"
            and site["coaching_posture"] == "ESCALATED"):
        fail("ERR_SITE_POSTURE_BLOCKS_DONATION",
             "A donation may not move while the site's posture is ESCALATED.")


# ------------------------------------------------------------- consignments
@bp.route("/diversion-consignments", methods=["POST"])
def create_consignment():
    caller = authenticate((SITE_MANAGER,))
    body = body_json()
    site_id = field_str(body, "site_id")
    hauler_id = field_str(body, "hauler_id")
    channel = field_enum(body, "channel", CHANNELS)
    window_start = field_ts(body, "pickup_window_start")
    window_end = field_ts(body, "pickup_window_end")
    if not window_end > window_start:
        bad("pickup_window_end must be strictly after pickup_window_start.")
    tare = field_int(body, "container_tare_grams", required=False, minimum=0,
                     default=0)
    must_exist(db.sites, site_id, "ERR_SITE_NOT_FOUND")
    hauler = must_exist(db.haulers, hauler_id, "ERR_HAULER_NOT_FOUND")
    require_site_scope(caller, site_id)

    # Step 20: half-open windows that merely touch do not intersect.
    overlapping = 0
    for row in db.consignments.values():
        if row["hauler_id"] != hauler_id:
            continue
        if row["logistics_status"] not in ("DRAFT", "STAGED", "DISPATCHED"):
            continue
        other_start = parse_ts(row["pickup_window_start"])
        other_end = parse_ts(row["pickup_window_end"])
        if other_start < window_end and window_start < other_end:
            overlapping += 1
    if overlapping >= hauler["max_concurrent_pickups"]:
        fail("ERR_HAULER_WINDOW_CAPACITY",
             "The hauler already holds its maximum concurrent pickups.")
    # Step 22
    if channel not in hauler["channels"]:
        fail("ERR_HAULER_CHANNEL_UNSUPPORTED",
             "The hauler is not contracted for the %s channel." % channel)

    consignment = base_row(
        site_id=site_id,
        hauler_id=hauler_id,
        channel=channel,
        pickup_window_start=iso(window_start),
        pickup_window_end=iso(window_end),
        container_tare_grams=tare,
        logistics_status="DRAFT",
        settlement_status="UNBILLED",
        staged_weight_grams=0,
        line_count=0,
        cancel_reason=None,
        staged_at=None,
        dispatched_at=None,
    )
    db.consignments[consignment["id"]] = consignment
    return row_response(consignment, 201)


@bp.route("/diversion-consignments/<consignment_id>/stage", methods=["POST"])
def stage_consignment(consignment_id):
    caller = authenticate((SITE_MANAGER,))
    body_json()
    consignment = must_exist(db.consignments, consignment_id,
                             "ERR_CONSIGNMENT_NOT_FOUND")
    require_site_scope(caller, consignment["site_id"])
    if consignment["logistics_status"] != "DRAFT":
        fail("ERR_INVALID_CONSIGNMENT_STATE",
             "Only a DRAFT consignment may be staged.")
    site = db.sites[consignment["site_id"]]
    _posture_block(consignment, site)
    hauler = db.haulers[consignment["hauler_id"]]
    capacity_grams = D(hauler["capacity_kg_per_pickup"]) * D(1000)
    if D(consignment["staged_weight_grams"]) > capacity_grams:
        fail("ERR_HAULER_CAPACITY_EXCEEDED",
             "The staged load exceeds the hauler's per-pickup capacity.")
    if consignment["line_count"] < 1:
        fail("ERR_CONSIGNMENT_EMPTY",
             "A consignment needs at least one allocation line to be staged.")
    consignment["logistics_status"] = "STAGED"
    consignment["staged_at"] = db.now_iso()
    touch(consignment)
    return row_response(consignment)


@bp.route("/diversion-consignments/<consignment_id>/dispatch", methods=["POST"])
def dispatch_consignment(consignment_id):
    caller = authenticate((SITE_MANAGER, HAULER_OPERATOR))
    body_json()
    consignment = must_exist(db.consignments, consignment_id,
                             "ERR_CONSIGNMENT_NOT_FOUND")
    require_site_scope(caller, consignment["site_id"])
    require_hauler_scope(caller, consignment["hauler_id"])
    if consignment["logistics_status"] != "STAGED":
        fail("ERR_INVALID_CONSIGNMENT_STATE",
             "Only a STAGED consignment may be dispatched.")
    hauler = db.haulers[consignment["hauler_id"]]
    if hauler["status"] != "APPROVED":
        fail("ERR_HAULER_NOT_APPROVED",
             "A pending hauler may never receive a dispatch.")
    _posture_block(consignment, db.sites[consignment["site_id"]])
    consignment["logistics_status"] = "DISPATCHED"
    consignment["dispatched_at"] = db.now_iso()
    touch(consignment)
    return row_response(consignment)


@bp.route("/diversion-consignments/<consignment_id>/cancel", methods=["POST"])
def cancel_consignment(consignment_id):
    caller = authenticate((SITE_MANAGER,))
    body = body_json()
    cancel_reason = field_str(body, "cancel_reason")
    consignment = must_exist(db.consignments, consignment_id,
                             "ERR_CONSIGNMENT_NOT_FOUND")
    require_site_scope(caller, consignment["site_id"])
    if consignment["logistics_status"] not in ("DRAFT", "STAGED", "DISPATCHED"):
        fail("ERR_INVALID_CONSIGNMENT_STATE",
             "A completed or cancelled consignment may not be cancelled.")
    if consignment["settlement_status"] == "SETTLED":
        fail("ERR_INVALID_CONSIGNMENT_STATE",
             "Money that has settled cannot be un-shipped.")
    consignment["logistics_status"] = "CANCELLED"
    consignment["cancel_reason"] = cancel_reason
    touch(consignment)
    # The lines are retained for audit and simply stop counting.
    seen = set()
    for line in derive.lines_of_consignment(consignment["id"]):
        entry_id = line["waste_entry_id"]
        if entry_id in seen:
            continue
        seen.add(entry_id)
        entry = db.entries.get(entry_id)
        if entry is not None:
            derive.recompute_entry_routing(entry, bump=True)
    derive.recompute_site(db.sites[consignment["site_id"]])
    return row_response(consignment)


@bp.route("/diversion-consignments/<consignment_id>", methods=["GET"])
def get_consignment(consignment_id):
    authenticate(HAULER_READERS)
    return row_response(must_exist(db.consignments, consignment_id,
                                   "ERR_CONSIGNMENT_NOT_FOUND"))


@bp.route("/diversion-consignments", methods=["GET"])
def list_consignments():
    authenticate(HAULER_READERS)
    rows = filtered(list(db.consignments.values()),
                    site_id=query_str("site_id"),
                    hauler_id=query_str("hauler_id"),
                    channel=query_enum("channel", CHANNELS),
                    logistics_status=query_enum("logistics_status",
                                                LOGISTICS_STATUSES),
                    settlement_status=query_enum("settlement_status",
                                                 SETTLEMENT_STATUSES))
    return respond_list(rows)


# ---------------------------------------------------------- allocation lines
@bp.route("/consignment-lines", methods=["POST"])
def create_line():
    caller = authenticate((SITE_MANAGER, SHIFT_LEAD))
    body = body_json()
    consignment_id = field_str(body, "consignment_id")
    waste_entry_id = field_str(body, "waste_entry_id")
    allocated = field_int(body, "allocated_weight_grams", minimum=1)
    consignment = must_exist(db.consignments, consignment_id,
                             "ERR_CONSIGNMENT_NOT_FOUND")
    entry = must_exist(db.entries, waste_entry_id, "ERR_ENTRY_NOT_FOUND")
    require_site_scope(caller, consignment["site_id"])
    if consignment["logistics_status"] != "DRAFT":
        fail("ERR_INVALID_CONSIGNMENT_STATE",
             "Lines may only be attached while the consignment is DRAFT.")
    if entry["status"] in ("VOIDED", "SUPERSEDED"):
        fail("ERR_INVALID_ENTRY_STATE",
             "A voided or superseded capture may not be routed.")
    # Step 14: channel eligibility of the routed food.
    food_type = db.food_types[entry["food_type_id"]]
    channel = consignment["channel"]
    if channel == "DONATION":
        if not food_type["donation_eligible"] or entry["stream"] != "PRE_CONSUMER":
            fail("ERR_CHANNEL_INELIGIBLE_FOOD",
                 "Only donation-eligible pre-consumer material may be donated.")
    elif channel == "ANIMAL_FEED":
        if not food_type["animal_feed_eligible"]:
            fail("ERR_CHANNEL_INELIGIBLE_FOOD",
                 "This food type is not eligible for animal feed.")
    # Step 16
    if entry["site_id"] != consignment["site_id"]:
        fail("ERR_ENTRY_SITE_MISMATCH",
             "The capture and the consignment belong to different sites.")
    # Step 18
    if channel == "DONATION":
        deadline = plus_hours(parse_ts(entry["captured_at"]),
                              food_type["donation_shelf_life_hours"])
        if parse_ts(consignment["pickup_window_start"]) > deadline:
            fail("ERR_DONATION_WINDOW_EXPIRED",
                 "The pickup window opens after the food's shelf life ends.")
    # Step 21
    if allocated > entry["unrouted_weight_grams"]:
        fail("ERR_ALLOCATION_EXCEEDS_UNROUTED",
             "The allocation exceeds the capture's unrouted grams.")

    line = {
        "id": new_id(),
        "consignment_id": consignment["id"],
        "waste_entry_id": entry["id"],
        "allocated_weight_grams": allocated,
        "created_by_user_id": caller.user_id,
        "created_at": db.now_iso(),
        "_seq": db.next_seq(),
    }
    db.lines[line["id"]] = line
    derive.recompute_entry_routing(entry, bump=True)
    derive.recompute_consignment_totals(consignment, bump=True)
    derive.recompute_site(db.sites[consignment["site_id"]])
    return row_response(line, 201)


@bp.route("/consignment-lines/<line_id>", methods=["DELETE"])
def delete_line(line_id):
    caller = authenticate((SITE_MANAGER, SHIFT_LEAD))
    line = must_exist(db.lines, line_id, "ERR_LINE_NOT_FOUND")
    consignment = db.consignments[line["consignment_id"]]
    require_site_scope(caller, consignment["site_id"])
    if consignment["logistics_status"] != "DRAFT":
        fail("ERR_INVALID_CONSIGNMENT_STATE",
             "Lines may only be removed while the consignment is DRAFT.")
    entry = db.entries.get(line["waste_entry_id"])
    del db.lines[line_id]
    if entry is not None:
        derive.recompute_entry_routing(entry, bump=True)
    derive.recompute_consignment_totals(consignment, bump=True)
    derive.recompute_site(db.sites[consignment["site_id"]])
    return object_response({})


@bp.route("/consignment-lines/<line_id>", methods=["GET"])
def get_line(line_id):
    authenticate(HAULER_READERS)
    return row_response(must_exist(db.lines, line_id, "ERR_LINE_NOT_FOUND"))


@bp.route("/consignment-lines", methods=["GET"])
def list_lines():
    authenticate(HAULER_READERS)
    rows = filtered(list(db.lines.values()),
                    consignment_id=query_str("consignment_id"),
                    waste_entry_id=query_str("waste_entry_id"))
    return respond_list(rows)


# --------------------------------------------------------------- weigh tickets
@bp.route("/hauler-tickets", methods=["POST"])
def create_ticket():
    caller = authenticate((HAULER_OPERATOR,))
    body = body_json()
    consignment_id = field_str(body, "consignment_id")
    ticket_number = field_str(body, "ticket_number")
    gross = field_int(body, "gross_weight_grams", minimum=1)
    ticket_date = field_date(body, "ticket_date")
    supplied_hauler_id = field_str(body, "hauler_id", required=False)
    consignment = must_exist(db.consignments, consignment_id,
                             "ERR_CONSIGNMENT_NOT_FOUND")
    if supplied_hauler_id is not None:
        must_exist(db.haulers, supplied_hauler_id, "ERR_HAULER_NOT_FOUND")
    resolved_hauler_id = supplied_hauler_id or consignment["hauler_id"]
    require_hauler_scope(caller, resolved_hauler_id)
    # Step 11: the only coupling point between the two consignment dimensions.
    if consignment["logistics_status"] != "DISPATCHED":
        fail("ERR_INVALID_CONSIGNMENT_STATE",
             "A ticket may only be filed against a DISPATCHED consignment.")
    if consignment["settlement_status"] not in ("UNBILLED", "DISPUTED"):
        fail("ERR_TICKET_ALREADY_SUBMITTED",
             "The consignment already carries a live ticket.")
    for row in db.tickets.values():
        if (row["consignment_id"] == consignment["id"]
                and row["status"] in ("SUBMITTED", "ACCEPTED")):
            fail("ERR_TICKET_ALREADY_SUBMITTED",
                 "The consignment already carries a live ticket.")
    # Step 16
    if (supplied_hauler_id is not None
            and supplied_hauler_id != consignment["hauler_id"]):
        fail("ERR_TICKET_HAULER_MISMATCH",
             "hauler_id does not match the consignment's hauler.")
    # Step 24
    for row in db.tickets.values():
        if (row["hauler_id"] == resolved_hauler_id
                and row["ticket_number"] == ticket_number):
            fail("ERR_DUPLICATE_TICKET_NUMBER",
                 "This ticket number is already used by the hauler.")

    hauler = db.haulers[resolved_hauler_id]
    figures = calc.settlement_figures(
        gross, consignment["container_tare_grams"],
        hauler["rate_cents_per_tonne"], hauler["stop_fee_cents"],
        consignment["staged_weight_grams"])
    ticket = base_row(
        consignment_id=consignment["id"],
        hauler_id=resolved_hauler_id,
        ticket_number=ticket_number,
        gross_weight_grams=gross,
        ticket_date=ticket_date,
        status="SUBMITTED",
        net_weight_grams=figures["net_weight_grams"],
        billable_tonnes=num(figures["billable_tonnes"]),
        base_haul_fee_cents=figures["base_haul_fee_cents"],
        fuel_surcharge_pct=num(figures["fuel_surcharge_pct"]),
        fuel_surcharge_cents=figures["fuel_surcharge_cents"],
        settlement_subtotal_cents=figures["settlement_subtotal_cents"],
        variance_pct=num(figures["variance_pct"]),
        variance_credit_cents=figures["variance_credit_cents"],
        settlement_total_cents=figures["settlement_total_cents"],
        dispute_note=None,
        accepted_at=None,
    )
    db.tickets[ticket["id"]] = ticket
    consignment["settlement_status"] = "TICKET_SUBMITTED"
    touch(consignment)
    return row_response(ticket, 201)


@bp.route("/hauler-tickets/<ticket_id>/accept", methods=["POST"])
def accept_ticket(ticket_id):
    caller = authenticate((SITE_MANAGER,))
    body_json()
    ticket = must_exist(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    consignment = db.consignments[ticket["consignment_id"]]
    require_site_scope(caller, consignment["site_id"])
    if ticket["status"] != "SUBMITTED":
        fail("ERR_INVALID_TICKET_STATE", "Only a SUBMITTED ticket may be accepted.")
    if (consignment["logistics_status"] != "DISPATCHED"
            or consignment["settlement_status"] != "TICKET_SUBMITTED"):
        fail("ERR_INVALID_CONSIGNMENT_STATE",
             "The consignment is no longer in a settleable state.")
    ticket["status"] = "ACCEPTED"
    ticket["accepted_at"] = db.now_iso()
    touch(ticket)
    # Hop 1: both dimensions flip in the same request.
    consignment["settlement_status"] = "SETTLED"
    consignment["logistics_status"] = "COMPLETED"
    touch(consignment)
    # Hop 2
    site = db.sites[consignment["site_id"]]
    derive.recompute_site(site)
    touch(site)
    # Hop 3
    for target in derive.active_targets_of_site(site["id"]):
        derive.apply_attainment(target, bump=True)
    return row_response(ticket)


@bp.route("/hauler-tickets/<ticket_id>/dispute", methods=["POST"])
def dispute_ticket(ticket_id):
    caller = authenticate((SITE_MANAGER,))
    body = body_json()
    dispute_note = field_str(body, "dispute_note")
    ticket = must_exist(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    consignment = db.consignments[ticket["consignment_id"]]
    require_site_scope(caller, consignment["site_id"])
    if ticket["status"] != "SUBMITTED":
        fail("ERR_INVALID_TICKET_STATE", "Only a SUBMITTED ticket may be disputed.")
    ticket["status"] = "DISPUTED"
    ticket["dispute_note"] = dispute_note
    touch(ticket)
    consignment["settlement_status"] = "DISPUTED"
    touch(consignment)
    return row_response(ticket)


@bp.route("/hauler-tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    authenticate(HAULER_READERS)
    return row_response(must_exist(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND"))


@bp.route("/hauler-tickets", methods=["GET"])
def list_tickets():
    authenticate(HAULER_READERS)
    rows = filtered(list(db.tickets.values()),
                    consignment_id=query_str("consignment_id"),
                    hauler_id=query_str("hauler_id"),
                    status=query_enum("status", TICKET_STATUSES),
                    ticket_date=query_date("ticket_date"))
    return respond_list(rows)
