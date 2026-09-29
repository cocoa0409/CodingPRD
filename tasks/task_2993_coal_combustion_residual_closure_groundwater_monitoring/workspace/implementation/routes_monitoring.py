"""Wells, monitoring programs, sampling rounds and analytical results."""
from flask import Blueprint

import calc
import common
import derive
import envelope
import shape
import store
from errors import ApiError
from guards import authenticate, require_discipline, require_license_active
from routes_units import CODE_RE

bp = Blueprint("monitoring", __name__)

WELL_SPEC = {
    "unit_id": {"t": "id", "req": True},
    "well_code": {"t": "str", "req": True, "min": 3, "max": 16, "re": CODE_RE},
    "well_role": {"t": "enum", "req": True, "vals": ("BACKGROUND", "DOWNGRADIENT")},
    "aquifer_zone": {"t": "str", "req": True, "min": 1, "max": 40},
    "screen_top_ft": {"t": "num", "req": True, "min": 0, "dp": 2},
    "screen_bottom_ft": {"t": "num", "req": True, "min": 0, "dp": 2},
    "installed_on": {"t": "date", "req": True},
}


@bp.post("/ccr/wells")
def create_well():
    actor = authenticate(("Hydrogeologist",))
    data = shape.read_body(WELL_SPEC)
    if data["screen_bottom_ft"] <= data["screen_top_ft"]:
        raise shape.bad("screen_bottom_ft must be deeper than screen_top_ft.")
    unit = common.get_unit(data["unit_id"])
    common.no_future_date(data["installed_on"])
    common.unique_code(store.wells, "well_code", data["well_code"],
                       "unit_id", data["unit_id"])
    require_license_active(actor)
    require_discipline(actor, common.D_HYDRO)
    common.unit_not_care_complete(unit)
    record = dict(data)
    record["well_status"] = "CERTIFIED"
    record["decommissioned_on"] = None
    record["decommission_reason"] = None
    store.stamp_new(record)
    store.wells[record["id"]] = record
    program = calc.unit_program(unit["id"])
    if program is not None:
        derive.refresh_program(program)
    return envelope.created(derive.well(record))


DECOMMISSION_SPEC = {
    "decommissioned_on": {"t": "date", "req": True},
    "decommission_reason": {"t": "str", "req": True, "min": 1},
}


@bp.post("/ccr/wells/<well_id>/decommission")
def decommission_well(well_id):
    actor = authenticate(("Hydrogeologist",))
    data = shape.read_body(DECOMMISSION_SPEC)
    well = common.get_well(well_id)
    unit = common.get_unit(well["unit_id"])
    require_license_active(actor)
    require_discipline(actor, common.D_HYDRO)
    common.unit_not_care_complete(unit)
    if well["well_status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_WELL_STATE",
                       "The well is not CERTIFIED.")
    program = calc.unit_program(unit["id"])
    if program is not None and program["network_certified"]:
        background, downgradient = calc.certified_well_counts(unit["id"])
        if well["well_role"] == "BACKGROUND":
            background -= 1
        else:
            downgradient -= 1
        if background < calc.MIN_BACKGROUND_WELLS:
            raise ApiError("ERR_NO_BACKGROUND_WELL",
                           "The remaining network has no certified background well.")
        if downgradient < calc.MIN_DOWNGRADIENT_WELLS:
            raise ApiError("ERR_INSUFFICIENT_DOWNGRADIENT_WELLS",
                           "The remaining network has too few certified "
                           "downgradient wells.")
    well["well_status"] = "DECOMMISSIONED"
    well["decommissioned_on"] = data["decommissioned_on"]
    well["decommission_reason"] = data["decommission_reason"]
    store.touch(well)
    if program is not None:
        derive.refresh_program(program)
    return envelope.ok(derive.well(well))


PROGRAM_PATCH_SPEC = {
    "statistical_method": {"t": "enum",
                          "vals": ("PARAMETRIC_PREDICTION_INTERVAL",
                                   "NONPARAMETRIC_PREDICTION_INTERVAL")},
    "comparison_basis": {"t": "enum", "vals": ("INTERWELL", "INTRAWELL")},
    "background_window_start_on": {"t": "date"},
    "background_window_end_on": {"t": "date"},
}


@bp.patch("/ccr/monitoring-programs/<program_id>")
def patch_program(program_id):
    actor = authenticate(("Hydrogeologist",))
    payload = shape.body()
    data = shape.validate(payload, PROGRAM_PATCH_SPEC)
    program = common.get_program(program_id)
    unit = common.get_unit(program["unit_id"])
    require_license_active(actor)
    require_discipline(actor, common.D_HYDRO)
    common.unit_not_care_complete(unit)
    common.program_phase(program, ("DETECTION",))
    start = data["background_window_start_on"]
    end = data["background_window_end_on"]
    if start is None:
        start = program["background_window_start_on"]
    if end is None:
        end = program["background_window_end_on"]
    shape.require_order(start, end, "background_window_start_on",
                        "background_window_end_on")
    for name in PROGRAM_PATCH_SPEC:
        if name in payload and payload[name] is not None:
            program[name] = data[name]
    store.touch(program)
    return envelope.ok(derive.program(program))


CERTIFY_SPEC = {"certified_on": {"t": "date", "req": True}}


@bp.post("/ccr/monitoring-programs/<program_id>/certify-network")
def certify_network(program_id):
    actor = authenticate(("Hydrogeologist",))
    data = shape.read_body(CERTIFY_SPEC)
    program = common.get_program(program_id)
    unit = common.get_unit(program["unit_id"])
    require_license_active(actor)
    require_discipline(actor, common.D_HYDRO)
    common.unit_not_care_complete(unit)
    background, downgradient = calc.certified_well_counts(unit["id"])
    if background < calc.MIN_BACKGROUND_WELLS:
        raise ApiError("ERR_NO_BACKGROUND_WELL",
                       "The network has no certified background well.")
    if downgradient < calc.MIN_DOWNGRADIENT_WELLS:
        raise ApiError("ERR_INSUFFICIENT_DOWNGRADIENT_WELLS",
                       "The network has too few certified downgradient wells.")
    if (program["background_window_start_on"] is None
            or program["background_window_end_on"] is None):
        raise shape.bad("The background window bounds must be configured "
                        "before the network can be certified.")
    program["network_certified"] = True
    program["network_certified_on"] = data["certified_on"]
    program["network_certified_by"] = actor.user_id
    store.touch(program)
    return envelope.ok(derive.program(program))


ASSURANCE_SPEC = {
    "remedy_base_cost_usd_cents": {"t": "int", "req": True, "min": 1},
    "remedy_duration_years": {"t": "int", "req": True, "min": 1, "max": 60},
    "remedy_description": {"t": "str", "req": True, "min": 1, "max": 500},
}


@bp.post("/ccr/monitoring-programs/<program_id>/corrective-action-assurance")
def corrective_action_assurance(program_id):
    authenticate(("ComplianceOfficer",))
    data = shape.read_body(ASSURANCE_SPEC)
    program = common.get_program(program_id)
    unit = common.get_unit(program["unit_id"])
    common.unit_not_care_complete(unit)
    common.program_phase(program, ("ASSESSMENT", "CORRECTIVE_ACTION"))
    program["remedy_base_cost_usd_cents"] = data["remedy_base_cost_usd_cents"]
    program["remedy_duration_years"] = data["remedy_duration_years"]
    program["remedy_description"] = data["remedy_description"]
    totals = calc.corrective_action_assurance_amount(
        data["remedy_base_cost_usd_cents"])
    program["assurance_amount_usd_cents"] = totals["assurance_amount_usd_cents"]
    store.touch(program)
    return envelope.ok(derive.program(program))


EVENT_SPEC = {
    "program_id": {"t": "id", "req": True},
    "event_code": {"t": "str", "req": True, "min": 3, "max": 20, "re": CODE_RE},
    "event_type": {"t": "enum", "req": True,
                   "vals": ("BACKGROUND", "DETECTION", "ASSESSMENT")},
    "sampled_on": {"t": "date", "req": True},
}


@bp.post("/ccr/sampling-events")
def create_event():
    actor = authenticate(("Hydrogeologist",))
    data = shape.read_body(EVENT_SPEC)
    program = common.get_program(data["program_id"])
    unit = common.get_unit(program["unit_id"])
    common.no_future_date(data["sampled_on"])
    common.unique_code(store.sampling_events, "event_code", data["event_code"],
                       "program_id", data["program_id"])
    require_license_active(actor)
    require_discipline(actor, common.D_HYDRO)
    common.unit_not_care_complete(unit)
    if not program["network_certified"]:
        raise ApiError("ERR_NETWORK_NOT_CERTIFIED",
                       "The monitoring network is not certified.")
    last = calc.latest_validated_sampled_on(program["id"])
    if last is not None:
        if store.day_diff(data["sampled_on"], last) < calc.MIN_SAMPLE_INTERVAL_DAYS:
            raise ApiError("ERR_SAMPLE_INTERVAL_TOO_SHORT",
                           "The sampling interval is shorter than 90 days.")
    record = dict(data)
    record["submitted_by_professional_id"] = actor.user_id
    record["status"] = "DRAFT"
    record["result_count"] = 0
    record["validated_on"] = None
    record["rejection_reason"] = None
    store.stamp_new(record)
    store.sampling_events[record["id"]] = record
    return envelope.created(derive.event(record))


PARAMETERS = ("BORON", "SULFATE", "CHLORIDE", "ARSENIC", "LITHIUM",
              "MOLYBDENUM", "RADIUM_226_228")

RESULT_SPEC = {
    "sampling_event_id": {"t": "id", "req": True},
    "well_id": {"t": "id", "req": True},
    "parameter_code": {"t": "enum", "req": True, "vals": PARAMETERS},
    "concentration": {"t": "num", "req": True, "min": 0, "dp": 4},
    "unit_of_measure": {"t": "enum", "req": True, "vals": ("MG_PER_L", "PCI_PER_L")},
    "detection_flag": {"t": "enum", "req": True, "vals": ("DETECTED", "NON_DETECT")},
    "reporting_limit": {"t": "num", "dp": 4},
    "expected_sampling_event_version": {"t": "int", "req": True, "min": 0},
}


@bp.post("/ccr/analytical-results")
def create_result():
    actor = authenticate(("Hydrogeologist",))
    data = shape.read_body(RESULT_SPEC)
    if data["reporting_limit"] is not None and data["reporting_limit"] <= 0:
        raise shape.bad("Field 'reporting_limit' must be greater than 0.")
    if data["detection_flag"] == "NON_DETECT" and data["reporting_limit"] is None:
        raise shape.bad("Field 'reporting_limit' is required for a NON_DETECT "
                        "result.")
    event = common.get_event(data["sampling_event_id"])
    well = common.get_well(data["well_id"])
    program = common.get_program(event["program_id"])
    unit = common.get_unit(program["unit_id"])
    require_license_active(actor)
    require_discipline(actor, common.D_HYDRO)
    if data["expected_sampling_event_version"] != event["version"]:
        raise ApiError("ERR_STALE_EVENT_VERSION",
                       "The sampling round has been modified by another writer.")
    common.unit_not_care_complete(unit)
    if event["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_EVENT_STATE",
                       "The sampling round is not DRAFT.")
    if well["unit_id"] != program["unit_id"]:
        raise ApiError("ERR_RESULT_WELL_NOT_IN_PROGRAM",
                       "The well does not belong to the program's unit.")
    for row in store.analytical_results.values():
        if (row["sampling_event_id"] == event["id"]
                and row["well_id"] == well["id"]
                and row["parameter_code"] == data["parameter_code"]):
            raise ApiError("ERR_DUPLICATE_RESULT_FOR_WELL_PARAMETER",
                           "A result for this well and parameter already exists "
                           "on this round.")
    record = {name: data[name] for name in
              ("sampling_event_id", "well_id", "parameter_code", "concentration",
               "unit_of_measure", "detection_flag", "reporting_limit")}
    record["effective_value"] = calc.analytical_effective_value(
        data["detection_flag"], data["concentration"], data["reporting_limit"])
    store.stamp_new(record, versioned=False)
    store.analytical_results[record["id"]] = record
    event["result_count"] = event["result_count"] + 1
    store.touch(event)
    return envelope.created(derive.result(record))


VALIDATE_SPEC = {"validated_on": {"t": "date", "req": True}}


@bp.post("/ccr/sampling-events/<event_id>/validate")
def validate_event(event_id):
    actor = authenticate(("Hydrogeologist",))
    data = shape.read_body(VALIDATE_SPEC)
    event = common.get_event(event_id)
    program = common.get_program(event["program_id"])
    unit = common.get_unit(program["unit_id"])
    require_license_active(actor)
    require_discipline(actor, common.D_HYDRO)
    common.unit_not_care_complete(unit)
    if event["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_EVENT_STATE",
                       "The sampling round is not DRAFT.")
    derive.refresh_event(event)
    rows = [r for r in store.analytical_results.values()
            if r["sampling_event_id"] == event["id"]]
    decommissioned = any(
        store.wells[r["well_id"]]["well_status"] == "DECOMMISSIONED"
        for r in rows if r["well_id"] in store.wells)
    if not rows:
        event["status"] = "REJECTED"
        event["rejection_reason"] = "NO_RESULTS"
    elif decommissioned:
        event["status"] = "REJECTED"
        event["rejection_reason"] = "WELL_DECOMMISSIONED"
    else:
        event["status"] = "VALIDATED"
        event["validated_on"] = data["validated_on"]
    store.touch(event)
    derive.refresh_program(program)
    return envelope.ok(derive.event(event))


@bp.post("/ccr/sampling-events/<event_id>/reopen")
def reopen_event(event_id):
    actor = authenticate(("Hydrogeologist",))
    shape.read_body({})
    event = common.get_event(event_id)
    program = common.get_program(event["program_id"])
    unit = common.get_unit(program["unit_id"])
    require_license_active(actor)
    require_discipline(actor, common.D_HYDRO)
    common.unit_not_care_complete(unit)
    if event["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_EVENT_STATE",
                       "The sampling round is not REJECTED.")
    event["status"] = "DRAFT"
    event["rejection_reason"] = None
    event["validated_on"] = None
    store.touch(event)
    return envelope.ok(derive.event(event))
