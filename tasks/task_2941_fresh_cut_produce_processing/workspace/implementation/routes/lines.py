"""Lines, sanitation shifts, environmental monitoring and corrective actions."""

from flask import Blueprint

import db
import enums
import serializers
from envelope import (
    actor,
    enum_param,
    listing,
    object_response,
    read_body,
    require,
)
from errors import ApiError
from services import cascades, posture
from util import now_dt

bp = Blueprint("lines", __name__)

CHANGEOVER_SWAB_RESULT = "NEGATIVE"

CREATE_LINE = (
    ("line_code", "str", True),
    ("required_disassembly_component_count", "int", True, {"ge": 0}),
    ("max_atp_rlu", "int", True, {"ge": 0}),
)

CREATE_SANITATION = (
    ("shift", "enum", True, {"values": enums.SHIFT}),
    ("scheduled_for", "datetime", True),
    ("is_allergen_changeover", "bool", False, {"default": False}),
)

SUBMIT_SANITATION = (
    ("disassembled_component_count", "int", True, {"ge": 0}),
    ("atp_rlu", "int", True, {"ge": 0}),
    ("allergen_swab_result", "enum", True, {"values": enums.ALLERGEN_SWAB_RESULT}),
)

OUTCOME_BODY = (("outcome", "enum", True, {"values": enums.OUTCOME}),)

CREATE_SWAB = (
    ("zone", "enum", True, {"values": enums.ZONE}),
    ("site_code", "str", True),
    ("organism", "enum", True, {"values": enums.ORGANISM}),
    ("collected_at", "datetime", True),
)

SWAB_RESULT_BODY = (("result", "enum", True, {"values": enums.SWAB_RESULT}),)

SWAB_TRANSITIONS = {
    "PENDING": ("NEGATIVE", "PRESUMPTIVE_POSITIVE"),
    "PRESUMPTIVE_POSITIVE": ("CONFIRMED_POSITIVE", "NEGATIVE"),
    "NEGATIVE": (),
    "CONFIRMED_POSITIVE": (),
}

VERIFY_ACTION = (("outcome", "enum", True, {"values": enums.OUTCOME}),)


@bp.post("/lines")
@require("PlantAdmin")
def create_line():
    body = read_body(CREATE_LINE)
    for existing in db.rows("lines"):
        if existing["line_code"] == body["line_code"]:
            raise ApiError("ERR_DUPLICATE_CODE", "line_code is already registered")
    row = db.new_row(
        "lines",
        {
            "line_code": body["line_code"],
            "required_disassembly_component_count": body[
                "required_disassembly_component_count"
            ],
            "max_atp_rlu": body["max_atp_rlu"],
            "posture": "RESTRICTED",
            "open_corrective_action_count": 0,
            "last_validated_sanitation_at": None,
            "_dt_last_validated_sanitation_at": None,
            "last_run_allergen_group": None,
            "last_run_ended_at": None,
            "_dt_last_run_ended_at": None,
        },
    )
    return object_response(serializers.line(row), 201)


@bp.get("/lines")
@require(
    "PlantAdmin", "QAManager", "QATechnician", "LineOperator", "SanitationTech"
)
def list_lines():
    want = enum_param("posture", enums.POSTURE)
    rows = db.rows("lines")
    if want is not None:
        rows = [r for r in rows if r["posture"] == want]
    return listing(rows, serializers.line)


@bp.get("/lines/<line_id>")
@require(
    "PlantAdmin", "QAManager", "QATechnician", "LineOperator", "SanitationTech"
)
def get_line(line_id):
    return object_response(serializers.line(db.get_or_404("lines", line_id)))


# --------------------------------------------------------------------------
# sanitation events
# --------------------------------------------------------------------------


@bp.post("/lines/<line_id>/sanitation-events")
@require("SanitationTech", "QATechnician")
def create_sanitation(line_id):
    body = read_body(CREATE_SANITATION)
    db.get_or_404("lines", line_id)
    sequence_no = 1 + len(posture.sanitation_events(line_id))
    row = db.new_row(
        "sanitation_events",
        {
            "line_id": line_id,
            "shift": body["shift"],
            "is_allergen_changeover": body["is_allergen_changeover"],
            "sequence_no": sequence_no,
            "status": "SCHEDULED",
            "performed_by_user_id": None,
            "validated_by_user_id": None,
            "disassembled_component_count": None,
            "atp_rlu": None,
            "allergen_swab_result": None,
            "attempt_count": 0,
            "failed_reason": None,
            "validated_at": None,
            "_dt_validated_at": None,
            "started_at": None,
            "completed_at": None,
        },
    )
    db.set_instant(row, "scheduled_for", body["scheduled_for"])
    return object_response(serializers.sanitation_event(row), 201)


@bp.get("/lines/<line_id>/sanitation-events")
@require("PlantAdmin", "QAManager", "QATechnician", "SanitationTech")
def list_sanitation(line_id):
    status = enum_param("status", enums.SANITATION_STATUS)
    shift = enum_param("shift", enums.SHIFT)
    db.get_or_404("lines", line_id)
    rows = posture.sanitation_events(line_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if shift is not None:
        rows = [r for r in rows if r["shift"] == shift]
    rows.sort(key=lambda r: (db.dt_of(r, "scheduled_for"), r["sequence_no"]), reverse=True)
    return listing(rows, serializers.sanitation_event)


@bp.post("/sanitation-events/<event_id>/start")
@require("SanitationTech")
def start_sanitation(event_id):
    event = db.get_or_404("sanitation_events", event_id)
    if event["status"] not in ("SCHEDULED", "FAILED"):
        raise ApiError(
            "ERR_SANITATION_INVALID_STATE",
            "only a SCHEDULED or FAILED sanitation event may be started",
        )
    line = db.get_or_404("lines", event["line_id"])
    for run in cascades.runs_of_line(line["id"]):
        if run["run_status"] == "RUNNING":
            raise ApiError(
                "ERR_LINE_RUN_IN_PROGRESS",
                "a run is still RUNNING on this line",
            )
    event["status"] = "IN_PROGRESS"
    db.stamp(event, "started_at", now_dt())
    event["performed_by_user_id"] = actor()
    event["attempt_count"] = event["attempt_count"] + 1
    event["disassembled_component_count"] = 0
    event["atp_rlu"] = None
    event["allergen_swab_result"] = None
    event["failed_reason"] = None
    db.touch(event)
    return object_response(serializers.sanitation_event(event))


@bp.post("/sanitation-events/<event_id>/submit")
@require("SanitationTech")
def submit_sanitation(event_id):
    body = read_body(SUBMIT_SANITATION)
    event = db.get_or_404("sanitation_events", event_id)
    if event["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_SANITATION_INVALID_STATE",
            "only an IN_PROGRESS sanitation event may be submitted",
        )
    line = db.get_or_404("lines", event["line_id"])
    if body["disassembled_component_count"] < line[
        "required_disassembly_component_count"
    ]:
        raise ApiError(
            "ERR_DISASSEMBLY_INCOMPLETE",
            "disassembled_component_count is below the line requirement",
        )
    event["disassembled_component_count"] = body["disassembled_component_count"]
    event["atp_rlu"] = body["atp_rlu"]
    event["allergen_swab_result"] = body["allergen_swab_result"]
    event["status"] = "AWAITING_VALIDATION"
    db.stamp(event, "completed_at", now_dt())
    db.touch(event)
    return object_response(serializers.sanitation_event(event))


@bp.post("/sanitation-events/<event_id>/validate")
@require("QATechnician")
def validate_sanitation(event_id):
    body = read_body(OUTCOME_BODY)
    event = db.get_or_404("sanitation_events", event_id)
    if event["status"] != "AWAITING_VALIDATION":
        raise ApiError(
            "ERR_SANITATION_INVALID_STATE",
            "only an AWAITING_VALIDATION sanitation event may be validated",
        )
    if actor() == event["performed_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the validator must differ from performed_by_user_id",
        )
    line = db.get_or_404("lines", event["line_id"])
    now = now_dt()
    atp_over = event["atp_rlu"] is not None and event["atp_rlu"] > line["max_atp_rlu"]
    allergen_positive = event["allergen_swab_result"] != CHANGEOVER_SWAB_RESULT
    if body["outcome"] == "PASS" and not atp_over and not allergen_positive:
        event["status"] = "VALIDATED"
        db.stamp(event, "validated_at", now)
        event["validated_by_user_id"] = actor()
        db.touch(event)
        posture.recompute(line)
        return object_response(serializers.sanitation_event(event))
    event["status"] = "FAILED"
    if atp_over:
        event["failed_reason"] = "ATP_ABOVE_LIMIT"
    elif allergen_positive:
        event["failed_reason"] = "ALLERGEN_POSITIVE"
    else:
        event["failed_reason"] = "MANUAL_FAIL"
    db.touch(event)
    cascades.sanitation_failure(event, line, now)
    return object_response(serializers.sanitation_event(event))


# --------------------------------------------------------------------------
# environmental swabs
# --------------------------------------------------------------------------


@bp.post("/lines/<line_id>/environmental-swabs")
@require("QATechnician")
def create_swab(line_id):
    body = read_body(CREATE_SWAB)
    db.get_or_404("lines", line_id)
    row = db.new_row(
        "environmental_swabs",
        {
            "line_id": line_id,
            "zone": body["zone"],
            "site_code": body["site_code"],
            "organism": body["organism"],
            "result": "PENDING",
            "resulted_at": None,
            "_dt_resulted_at": None,
            "resulted_by_user_id": None,
        },
    )
    db.set_instant(row, "collected_at", body["collected_at"])
    return object_response(serializers.environmental_swab(row), 201)


@bp.get("/lines/<line_id>/environmental-swabs")
@require("PlantAdmin", "QAManager", "QATechnician")
def list_swabs(line_id):
    result = enum_param("result", enums.SWAB_RESULT)
    zone = enum_param("zone", enums.ZONE)
    organism = enum_param("organism", enums.ORGANISM)
    db.get_or_404("lines", line_id)
    rows = posture.swabs(line_id)
    if result is not None:
        rows = [r for r in rows if r["result"] == result]
    if zone is not None:
        rows = [r for r in rows if r["zone"] == zone]
    if organism is not None:
        rows = [r for r in rows if r["organism"] == organism]
    return listing(rows, serializers.environmental_swab)


@bp.post("/environmental-swabs/<swab_id>/result")
@require("QATechnician")
def record_swab_result(swab_id):
    body = read_body(SWAB_RESULT_BODY)
    swab = db.get_or_404("environmental_swabs", swab_id)
    if body["result"] not in SWAB_TRANSITIONS[swab["result"]]:
        raise ApiError(
            "ERR_SWAB_INVALID_RESULT_TRANSITION",
            "a " + swab["result"] + " swab cannot advance to " + body["result"],
        )
    line = db.get_or_404("lines", swab["line_id"])
    now = now_dt()
    swab["result"] = body["result"]
    db.stamp(swab, "resulted_at", now)
    swab["resulted_by_user_id"] = actor()
    db.touch(swab)
    if body["result"] == "CONFIRMED_POSITIVE":
        cascades.environmental_confirmation(swab, line, now)
    else:
        posture.recompute(line)
    return object_response(serializers.environmental_swab(swab))


# --------------------------------------------------------------------------
# corrective actions
# --------------------------------------------------------------------------


@bp.get("/lines/<line_id>/corrective-actions")
@require("PlantAdmin", "QAManager", "QATechnician", "SanitationTech")
def list_corrective_actions(line_id):
    status = enum_param("status", enums.CAPA_STATUS)
    severity = enum_param("severity", enums.CAPA_SEVERITY)
    source_type = enum_param("source_type", enums.CAPA_SOURCE_TYPE)
    db.get_or_404("lines", line_id)
    rows = posture.corrective_actions(line_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    if source_type is not None:
        rows = [r for r in rows if r["source_type"] == source_type]
    return listing(rows, serializers.corrective_action)


@bp.post("/corrective-actions/<action_id>/start")
@require("QATechnician")
def start_corrective_action(action_id):
    action = db.get_or_404("corrective_actions", action_id)
    if action["status"] != "OPEN":
        raise ApiError(
            "ERR_CORRECTIVE_ACTION_INVALID_STATE",
            "only an OPEN corrective action may be started",
        )
    action["status"] = "IN_PROGRESS"
    action["implemented_by_user_id"] = actor()
    db.touch(action)
    return object_response(serializers.corrective_action(action))


@bp.post("/corrective-actions/<action_id>/submit-verification")
@require("QATechnician")
def submit_corrective_action(action_id):
    body = read_body((("action_taken", "str", True),))
    action = db.get_or_404("corrective_actions", action_id)
    if action["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_CORRECTIVE_ACTION_INVALID_STATE",
            "only an IN_PROGRESS corrective action may be submitted",
        )
    action["action_taken"] = body["action_taken"]
    action["status"] = "VERIFICATION_PENDING"
    db.touch(action)
    return object_response(serializers.corrective_action(action))


@bp.post("/corrective-actions/<action_id>/verify")
@require("QAManager")
def verify_corrective_action(action_id):
    body = read_body(VERIFY_ACTION)
    action = db.get_or_404("corrective_actions", action_id)
    if action["status"] != "VERIFICATION_PENDING":
        raise ApiError(
            "ERR_CORRECTIVE_ACTION_INVALID_STATE",
            "only a VERIFICATION_PENDING corrective action may be verified",
        )
    if actor() == action["implemented_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the verifier must differ from implemented_by_user_id",
        )
    line = db.find("lines", action["line_id"])
    if body["outcome"] == "PASS":
        action["status"] = "VERIFIED"
        db.stamp(action, "verified_at", now_dt())
        action["verified_by_user_id"] = actor()
        db.touch(action)
        if line is not None:
            posture.recompute(line)
    else:
        action["status"] = "IN_PROGRESS"
        action["reopen_count"] = action["reopen_count"] + 1
        action["action_taken"] = None
        db.touch(action)
    return object_response(serializers.corrective_action(action))
