"""Consultations, sample check-outs and openings."""

from datetime import timedelta

from flask import Blueprint

import calc
from core import (ROLE_DESIGNER, ROLE_FRANCHISEE, ROLE_FRANCHISOR, append_ledger, auth,
                  check_range, dec_places, fail, free_lead_capacity, get_body,
                  get_checkout, get_consultation, get_designer, get_kit, get_lead,
                  get_opening, list_response, new_row, opt_enum, rederive_consultation,
                  rederive_kit, rederive_territory, recompute_designer_score, req_enum,
                  req_fk, req_instant, req_num, req_postal, req_str, respond_object,
                  require_designer_active, require_designer_assignment,
                  require_territory_active, require_territory_ownership, serialize,
                  store, territory_of_consultation, territory_of_lead, touch,
                  check_calendar_conflict)

bp = Blueprint("consult", __name__)

CONSULTATION_OPEN_STATES = ("SCHEDULED", "COMPLETED")


# --------------------------------------------------------------------------
# Consultations
# --------------------------------------------------------------------------
@bp.route("/blinds/consultations", methods=["POST"])
def create_consultation():
    actor = auth(ROLE_FRANCHISEE, ROLE_DESIGNER)
    body = get_body()
    lead = req_fk(body, "lead_id", get_lead)
    designer = req_fk(body, "designer_id", get_designer)
    if lead is not None and lead.get("territory_id"):
        require_territory_ownership(actor, lead["territory_id"])
    if designer is not None:
        require_territory_ownership(actor, designer["territory_id"])
    lead = get_lead(req_str(body, "lead_id", 1, None))
    designer = get_designer(req_str(body, "designer_id", 1, None))
    start = req_instant(body, "scheduled_start_at")
    end = req_instant(body, "scheduled_end_at")
    postal_code = req_postal(body, "service_postal_code")
    if postal_code != lead["postal_code"]:
        fail("ERR_INVALID_REQUEST",
             "service_postal_code must equal the lead's postal_code")
    check_range(end > start, "scheduled_end_at must be strictly after scheduled_start_at")
    if designer["territory_id"] != lead.get("territory_id"):
        fail("ERR_CROSS_TERRITORY_FORBIDDEN",
             "designer territory differs from the lead's territory")
    territory = territory_of_lead(lead)
    require_territory_active(territory)
    require_designer_active(designer)
    check_calendar_conflict(designer["id"], start, end, postal_code)
    row = new_row({
        "lead_id": lead["id"],
        "designer_id": designer["id"],
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "service_postal_code": postal_code,
        "status": "SCHEDULED",
        "measured_opening_count": 0,
        "configured_opening_count": 0,
        "open_sample_loan_count": 0,
        "completed_at": None,
    })
    store.consultations[row["id"]] = row
    return respond_object(serialize(row), 201)


@bp.route("/blinds/consultations/<consultation_id>", methods=["GET"])
def read_consultation(consultation_id):
    auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    return respond_object(serialize(get_consultation(consultation_id)), 200)


@bp.route("/blinds/consultations", methods=["GET"])
def list_consultations():
    auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    return list_response(store.consultations.values(),
                         ("lead_id", "designer_id", "status"))


@bp.route("/blinds/consultations/<consultation_id>/complete", methods=["POST"])
def complete_consultation(consultation_id):
    actor = auth(ROLE_DESIGNER)
    consultation = get_consultation(consultation_id)
    require_designer_assignment(actor, consultation["designer_id"])
    if consultation["status"] != "SCHEDULED":
        fail("ERR_CONSULTATION_NOT_SCHEDULED",
             "consultation status is %s" % consultation["status"])
    rederive_consultation(consultation, bump=False)
    if consultation["measured_opening_count"] < 1:
        fail("ERR_CONSULTATION_NOT_SCHEDULED",
             "at least one measured opening is required to close out")
    if consultation["open_sample_loan_count"] != 0:
        fail("ERR_CONSULTATION_NOT_SCHEDULED",
             "a sample kit is still on loan against this consultation")
    consultation["status"] = "COMPLETED"
    consultation["completed_at"] = store.clock
    touch(consultation)
    lead = store.leads.get(consultation["lead_id"])
    if lead is not None and lead["status"] == "ROUTED":
        lead["status"] = "CONSULT_COMPLETE"
        touch(lead)
    return respond_object(serialize(consultation), 200)


@bp.route("/blinds/consultations/<consultation_id>/no-show", methods=["POST"])
def no_show_consultation(consultation_id):
    actor = auth(ROLE_DESIGNER)
    consultation = get_consultation(consultation_id)
    require_designer_assignment(actor, consultation["designer_id"])
    if consultation["status"] != "SCHEDULED":
        fail("ERR_CONSULTATION_NOT_SCHEDULED",
             "consultation status is %s" % consultation["status"])
    if store.clock < consultation["scheduled_start_at"]:
        fail("ERR_CONSULTATION_NOT_SCHEDULED",
             "the appointment window has not started yet")
    consultation["status"] = "NO_SHOW"
    touch(consultation)
    lead = store.leads.get(consultation["lead_id"])
    if lead is not None and lead["status"] == "ROUTED":
        territory = territory_of_lead(lead)
        lead["status"] = "LOST"
        touch(lead)
        free_lead_capacity(territory)
    return respond_object(serialize(consultation), 200)


# --------------------------------------------------------------------------
# Sample check-outs
# --------------------------------------------------------------------------
@bp.route("/blinds/sample-checkouts", methods=["POST"])
def create_sample_checkout():
    actor = auth(ROLE_DESIGNER)
    body = get_body()
    kit = req_fk(body, "sample_kit_id", get_kit)
    consultation = req_fk(body, "consultation_id", get_consultation)
    if consultation is not None:
        require_designer_assignment(actor, consultation["designer_id"])
    kit = get_kit(req_str(body, "sample_kit_id", 1, None))
    consultation = get_consultation(req_str(body, "consultation_id", 1, None))
    hold_start = req_instant(body, "hold_start_at")
    hold_end = req_instant(body, "hold_end_at")
    check_range(hold_end > hold_start, "hold_end_at must be strictly after hold_start_at")
    check_range(hold_end - hold_start <= timedelta(days=calc.SAMPLE_MAX_HOLD_DAYS),
                "a hold may span no more than fourteen days")
    check_range(hold_start >= store.clock,
                "hold_start_at must be at or after the logical clock")
    territory = territory_of_consultation(consultation)
    if kit["territory_id"] != (territory["id"] if territory else None):
        fail("ERR_CROSS_TERRITORY_FORBIDDEN",
             "the kit and the appointment belong to different franchises")
    require_territory_active(store.territories.get(kit["territory_id"]))
    if consultation["status"] != "SCHEDULED":
        fail("ERR_CONSULTATION_NOT_SCHEDULED",
             "consultation status is %s" % consultation["status"])
    if kit["status"] != "AVAILABLE":
        fail("ERR_KIT_NOT_AVAILABLE", "kit status is %s" % kit["status"])
    for other in store.sample_checkouts.values():
        if other["sample_kit_id"] != kit["id"]:
            continue
        if other["status"] not in ("OPEN", "RETURNED"):
            continue
        if hold_start <= other["hold_end_at"] and other["hold_start_at"] <= hold_end:
            fail("ERR_SAMPLE_KIT_HOLD_CONFLICT",
                 "the hold interval overlaps a recorded hold on this kit")
    row = new_row({
        "sample_kit_id": kit["id"],
        "consultation_id": consultation["id"],
        "hold_start_at": hold_start,
        "hold_end_at": hold_end,
        "checked_out_at": store.clock,
        "due_at": hold_end,
        "returned_at": None,
        "status": "OPEN",
        "days_late": 0,
        "late_fee_cents": 0,
    })
    store.sample_checkouts[row["id"]] = row
    kit["status"] = "ON_LOAN"
    rederive_kit(kit)
    rederive_territory(store.territories[kit["territory_id"]])
    rederive_consultation(consultation)
    return respond_object(serialize(row), 201)


@bp.route("/blinds/sample-checkouts/<checkout_id>", methods=["GET"])
def read_sample_checkout(checkout_id):
    auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    return respond_object(serialize(get_checkout(checkout_id)), 200)


@bp.route("/blinds/sample-checkouts", methods=["GET"])
def list_sample_checkouts():
    auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    return list_response(store.sample_checkouts.values(),
                         ("sample_kit_id", "consultation_id", "status"))


@bp.route("/blinds/sample-checkouts/<checkout_id>/return", methods=["POST"])
def return_sample_checkout(checkout_id):
    actor = auth(ROLE_DESIGNER)
    checkout = get_checkout(checkout_id)
    consultation = store.consultations.get(checkout["consultation_id"])
    require_designer_assignment(
        actor, consultation["designer_id"] if consultation else None)
    if checkout["status"] != "OPEN":
        fail("ERR_CHECKOUT_NOT_OPEN", "check-out status is %s" % checkout["status"])
    kit = store.sample_kits[checkout["sample_kit_id"]]
    territory = store.territories.get(kit["territory_id"])
    returned_at = store.clock
    days_late = calc.days_late_for(returned_at, checkout["due_at"])
    checkout["returned_at"] = returned_at
    checkout["days_late"] = days_late
    if days_late > calc.SAMPLE_LOST_THRESHOLD_DAYS:
        checkout["late_fee_cents"] = kit["replacement_value_cents"]
        checkout["status"] = "LOST"
        touch(checkout)
        kit["status"] = "LOST"
        rederive_kit(kit)
        append_ledger(territory, "SAMPLE_REPLACEMENT", kit["replacement_value_cents"],
                      kit["replacement_value_cents"], "SAMPLE_CHECKOUT",
                      checkout["id"], "sample_lost")
    else:
        fee = calc.sample_late_fee_cents(days_late, kit["replacement_value_cents"])
        checkout["late_fee_cents"] = fee
        checkout["status"] = "RETURNED"
        touch(checkout)
        kit["status"] = "AVAILABLE"
        rederive_kit(kit)
        if fee > 0:
            append_ledger(territory, "SAMPLE_LATE_FEE", fee,
                          kit["replacement_value_cents"], "SAMPLE_CHECKOUT",
                          checkout["id"], "sample_late")
    rederive_territory(territory)
    if consultation is not None:
        rederive_consultation(consultation)
    if days_late > 0 and consultation is not None:
        designer = store.designers.get(consultation["designer_id"])
        if designer is not None:
            recompute_designer_score(designer)
    return respond_object(serialize(checkout), 200)


# --------------------------------------------------------------------------
# Openings
# --------------------------------------------------------------------------
WIDTH_KEYS = ("width_top_in", "width_middle_in", "width_bottom_in")
HEIGHT_KEYS = ("height_left_in", "height_center_in", "height_right_in")
MAX_READING = calc.Decimal("300.000")


@bp.route("/blinds/openings", methods=["POST"])
def create_opening():
    actor = auth(ROLE_DESIGNER)
    body = get_body()
    consultation = req_fk(body, "consultation_id", get_consultation)
    replaces = req_fk(body, "replaces_opening_id", get_opening)
    if consultation is not None:
        require_designer_assignment(actor, consultation["designer_id"])
    consultation = get_consultation(req_str(body, "consultation_id", 1, None))
    label = req_str(body, "label", 1, 80)
    room_type = req_enum(body, "room_type", calc.ROOM_TYPES)
    mount_type = req_enum(body, "mount_type", calc.MOUNT_TYPES)
    readings = {}
    for key in WIDTH_KEYS + HEIGHT_KEYS + ("depth_in",):
        readings[key] = req_num(body, key)
    for key in WIDTH_KEYS + HEIGHT_KEYS + ("depth_in",):
        value = readings[key]
        check_range(value > 0, "%s must be strictly greater than zero" % key)
        check_range(value <= MAX_READING, "%s may not exceed 300.000" % key)
        check_range(dec_places(value) <= 3,
                    "%s carries at most three decimal places" % key)
    if replaces is not None and replaces["consultation_id"] != consultation["id"]:
        fail("ERR_OPENING_NOT_ON_QUOTE",
             "replaces_opening_id belongs to another consultation")
    require_territory_active(territory_of_consultation(consultation))
    if consultation["status"] not in CONSULTATION_OPEN_STATES:
        fail("ERR_CONSULTATION_CLOSED",
             "consultation status is %s" % consultation["status"])
    if mount_type == "INSIDE" and readings["depth_in"] < calc.MIN_INSIDE_DEPTH_IN:
        fail("ERR_INSUFFICIENT_MOUNT_DEPTH",
             "an inside mount requires a pocket depth of at least 2.500 inches")
    widths = [readings[k] for k in WIDTH_KEYS]
    heights = [readings[k] for k in HEIGHT_KEYS]
    out_of_square, ordered_width, ordered_height = calc.ordered_dimensions(
        mount_type, widths, heights)
    row = new_row({
        "consultation_id": consultation["id"],
        "quote_id": None,
        "replaces_opening_id": replaces["id"] if replaces is not None else None,
        "label": label,
        "room_type": room_type,
        "mount_type": mount_type,
        "width_top_in": readings["width_top_in"],
        "width_middle_in": readings["width_middle_in"],
        "width_bottom_in": readings["width_bottom_in"],
        "height_left_in": readings["height_left_in"],
        "height_center_in": readings["height_center_in"],
        "height_right_in": readings["height_right_in"],
        "depth_in": readings["depth_in"],
        "out_of_square_in": out_of_square,
        "ordered_width_in": ordered_width,
        "ordered_height_in": ordered_height,
        "billable_sqft": calc.Decimal("0"),
        "fabric_code": None,
        "lift_system": None,
        "motorization_option": "NONE",
        "list_price_cents": 0,
        "measure_status": "MEASURED",
        "install_outcome": "PENDING",
        "credited": False,
    })
    store.openings[row["id"]] = row
    rederive_consultation(consultation)
    return respond_object(serialize(row), 201)


@bp.route("/blinds/openings/<opening_id>", methods=["GET"])
def read_opening(opening_id):
    auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    return respond_object(serialize(get_opening(opening_id)), 200)


@bp.route("/blinds/openings", methods=["GET"])
def list_openings():
    auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    return list_response(store.openings.values(),
                         ("consultation_id", "quote_id", "replaces_opening_id",
                          "measure_status", "install_outcome"))


@bp.route("/blinds/openings/<opening_id>/configuration", methods=["PATCH"])
def configure_opening(opening_id):
    actor = auth(ROLE_DESIGNER)
    opening = get_opening(opening_id)
    consultation = store.consultations.get(opening["consultation_id"])
    require_designer_assignment(
        actor, consultation["designer_id"] if consultation else None)
    body = get_body()
    fabric_code = req_enum(body, "fabric_code", calc.FABRIC_CODES)
    lift_system = req_enum(body, "lift_system", calc.LIFT_SYSTEMS)
    motorization_option = opt_enum(body, "motorization_option", calc.MOTOR_OPTIONS,
                                   "NONE")
    if consultation is not None and consultation["status"] not in CONSULTATION_OPEN_STATES:
        fail("ERR_CONSULTATION_CLOSED",
             "consultation status is %s" % consultation["status"])
    if opening["measure_status"] not in ("MEASURED", "CONFIGURED"):
        fail("ERR_OPENING_NOT_MEASURED",
             "opening measure_status is %s" % opening["measure_status"])
    if lift_system == "MOTORIZED" and motorization_option == "NONE":
        fail("ERR_MOTOR_OPTION_MISMATCH",
             "a motorized lift system requires a motor package")
    if lift_system != "MOTORIZED" and motorization_option != "NONE":
        fail("ERR_MOTOR_OPTION_MISMATCH",
             "a motor package requires the MOTORIZED lift system")
    sqft, list_price = calc.price_opening(
        opening["ordered_width_in"], opening["ordered_height_in"], fabric_code,
        lift_system, motorization_option)
    opening["fabric_code"] = fabric_code
    opening["lift_system"] = lift_system
    opening["motorization_option"] = motorization_option
    opening["billable_sqft"] = sqft
    opening["list_price_cents"] = list_price
    opening["measure_status"] = "CONFIGURED"
    touch(opening)
    if consultation is not None:
        rederive_consultation(consultation)
    return respond_object(serialize(opening), 200)
