"""Interface channels and messages (PRD §4.7, §3.6)."""

from decimal import Decimal

from flask import Blueprint

from db import DB, VALID_MESSAGE_CODES, now_iso, parse_iso
from errors import (
    ERR_CHANNEL_NOT_FOUND,
    ERR_CHANNEL_NOT_VALIDATED,
    ERR_INTERFACE_LATENCY_EXCEEDED,
    ERR_INTERFACE_MESSAGE_INVALID,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    fail,
    q2,
)
from request_utils import (
    actor,
    body_fields,
    collection,
    enum_member,
    filter_args,
    pagination,
    payload,
    require_role,
)
from response import ok
from services import lookups as L
from services import recompute as R
from services.core import serialize, stamp_created

bp = Blueprint("interfaces", __name__)

READ_ROLES = ["ImplementationAnalyst", "InterfaceEngineer"]
CHANNEL_TYPES = {"LAB", "IMAGING", "PHARMACY", "DEVICE"}
MESSAGE_FORMATS = {"HL7_V2", "FHIR", "DICOM", "CSV"}
MESSAGE_CODES = {"ADT_A01", "ORM_O01", "ORU_R01", "RDE_O11", "DICOM_STOW"}
DIRECTIONS = {"INBOUND", "OUTBOUND"}


def get_program(program_id):
    from errors import ERR_EHR_IMPLEMENTATION_NOT_FOUND

    program = DB.ehr_implementations.get(program_id)
    if program is None:
        fail(ERR_EHR_IMPLEMENTATION_NOT_FOUND, "No implementation program matches the id.")
    return program


def get_channel(channel_id):
    channel = DB.interface_channels.get(channel_id)
    if channel is None:
        fail(ERR_CHANNEL_NOT_FOUND, "No interface channel matches the id.")
    return channel


def get_message(message_id):
    message = DB.interface_messages.get(message_id)
    if message is None:
        fail(ERR_INVALID_REQUEST, "No interface message matches the id.")
    return message


def channel_view(channel):
    return serialize("InterfaceChannel", channel)


def message_view(message):
    data = serialize("InterfaceMessage", message)
    data.pop("decided_epoch", None)
    return data


@bp.route("/ehr-implementations/<program_id>/interface-channels", methods=["POST"])
def create_channel(program_id):
    uid, role = actor()
    require_role(role, ["InterfaceEngineer"])
    program = get_program(program_id)
    data = body_fields(
        [
            ("channel_type", "enum", True),
            ("external_system", "string", True),
            ("message_format", "enum", True),
            ("throughput_per_hour", "int", True),
            ("max_latency_minutes", "number", True),
        ],
        payload(),
    )
    enum_member("channel_type", data["channel_type"], CHANNEL_TYPES)
    enum_member("message_format", data["message_format"], MESSAGE_FORMATS)
    if data["throughput_per_hour"] <= 0:
        fail(ERR_INVALID_REQUEST, "throughput_per_hour must be a positive integer.")
    if data["max_latency_minutes"] < 0:
        fail(ERR_INVALID_REQUEST, "max_latency_minutes must be a non-negative number.")
    channel = {
        "id": DB.new_id(),
        "ehr_implementation_id": program["id"],
        "channel_type": data["channel_type"],
        "external_system": data["external_system"],
        "message_format": data["message_format"],
        "throughput_per_hour": data["throughput_per_hour"],
        "max_latency_minutes": float(data["max_latency_minutes"]),
        "validated_message_count": 0,
        "rejected_message_count": 0,
        "interface_message_validation_pass_rate": 0.0,
        "status": "DEFINED",
        "_cycle": 0,
    }
    stamp_created(channel)
    DB.interface_channels[channel["id"]] = channel
    DB.register_created(channel)
    DB.register_ref(channel["id"], "InterfaceChannel")
    R.recompute_program_tree(program["id"])
    return ok(channel_view(channel), status=201)


@bp.route("/ehr-implementations/<program_id>/interface-channels", methods=["GET"])
def list_program_channels(program_id):
    uid, role = actor()
    require_role(role, READ_ROLES)
    program = get_program(program_id)
    rows = L.program_channels(program["id"])
    filters = filter_args(["channel_type", "status"])
    for key, value in filters.items():
        rows = [c for c in rows if c.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([channel_view(c) for c in window], pagination=page)


@bp.route("/interface-channels", methods=["GET"])
def list_channels():
    uid, role = actor()
    require_role(role, READ_ROLES)
    rows = list(DB.interface_channels.values())
    filters = filter_args(["ehr_implementation_id", "channel_type", "status"])
    for key, value in filters.items():
        rows = [c for c in rows if c.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([channel_view(c) for c in window], pagination=page)


@bp.route("/interface-channels/<channel_id>", methods=["GET"])
def get_channel_endpoint(channel_id):
    uid, role = actor()
    require_role(role, READ_ROLES)
    channel = get_channel(channel_id)
    R.recompute_channel(channel)
    return ok(channel_view(channel))


def _channel_transition(channel_id, allowed_from, mutate):
    uid, role = actor()
    require_role(role, ["InterfaceEngineer"])
    channel = get_channel(channel_id)
    R.recompute_program_tree(channel["ehr_implementation_id"])
    if channel["status"] not in allowed_from:
        fail(
            ERR_INVALID_STATE,
            "The interface channel is in status %s; this operation requires %s."
            % (channel["status"], " or ".join(allowed_from)),
        )
    mutate(uid, channel)
    DB.touch(channel, common=True)
    R.recompute_program_tree(channel["ehr_implementation_id"])
    return ok(channel_view(channel))


@bp.route("/interface-channels/<channel_id>/begin-build", methods=["POST"])
def begin_channel_build(channel_id):
    def mutate(uid, channel):
        channel["status"] = "BUILDING"

    return _channel_transition(channel_id, ["DEFINED", "VALIDATION_FAILED"], mutate)


@bp.route("/interface-channels/<channel_id>/begin-validation", methods=["POST"])
def begin_channel_validation(channel_id):
    def mutate(uid, channel):
        channel["status"] = "IN_MESSAGE_VALIDATION"

    return _channel_transition(channel_id, ["BUILDING"], mutate)


@bp.route("/interface-channels/<channel_id>/complete-validation", methods=["POST"])
def complete_channel_validation(channel_id):
    def mutate(uid, channel):
        R.recompute_channel(channel)
        if not channel.get("_validation_passes"):
            # PRD §3.6: "No facility may be granted cutover readiness, no
            # program may finalize its validation phase, and no cutover step may
            # complete while any interface channel of the program remains short
            # of VALIDATED; the refusal carries ERR_CHANNEL_NOT_VALIDATED."
            fail(
                ERR_CHANNEL_NOT_VALIDATED,
                "The interface message validation pass rate has not reached 95.00.",
            )
        channel["status"] = "VALIDATED"

    return _channel_transition(channel_id, ["IN_MESSAGE_VALIDATION"], mutate)


@bp.route("/interface-channels/<channel_id>/return-to-build", methods=["POST"])
def return_channel_to_build(channel_id):
    def mutate(uid, channel):
        channel["status"] = "BUILDING"
        channel["validated_message_count"] = 0
        channel["rejected_message_count"] = 0
        channel["interface_message_validation_pass_rate"] = 0.0
        # Validation restarts cleanly: every message already decided against the
        # discarded cycle stops counting toward the current epoch tallies.
        channel["_cycle"] = int(channel.get("_cycle") or 0) + 1

    return _channel_transition(channel_id, ["VALIDATION_FAILED"], mutate)


# --------------------------------------------------------------------------
# InterfaceMessage
# --------------------------------------------------------------------------
@bp.route("/interface-channels/<channel_id>/messages", methods=["POST"])
def receive_message(channel_id):
    uid, role = actor()
    require_role(role, ["InterfaceEngineer"])
    channel = get_channel(channel_id)
    data = body_fields(
        [("message_code", "enum", True), ("direction", "enum", True), ("sent_utc", "datetime", True)],
        payload(),
    )
    enum_member("message_code", data["message_code"], MESSAGE_CODES)
    enum_member("direction", data["direction"], DIRECTIONS)
    sent = parse_iso(data["sent_utc"])
    received = DB.clock.get()
    latency = q2(Decimal(str((received - sent).total_seconds())) / Decimal(60))
    message = {
        "id": DB.new_id(),
        "interface_channel_id": channel["id"],
        "ehr_implementation_id": channel["ehr_implementation_id"],
        "message_code": data["message_code"],
        "direction": data["direction"],
        "received_utc": received,
        "latency_minutes": float(latency),
        "validation_status": "RECEIVED",
        "validation_error_code": None,
        "created_at": None,
        "decided_epoch": None,
        "_cycle": int(channel.get("_cycle") or 0),
    }
    message["created_at"] = now_iso()
    DB.interface_messages[message["id"]] = message
    DB.register_created(message)

    _validate_message(channel, message)
    return ok(message_view(message), status=201)


def _validate_message(channel, message):
    valid_codes = VALID_MESSAGE_CODES.get(channel["channel_type"], [])
    if message["message_code"] not in valid_codes:
        message["validation_status"] = "REJECTED"
        message["validation_error_code"] = "ERR_INTERFACE_MESSAGE_INVALID"
        _cascade_rejection(channel, message)
        return "ERR_INTERFACE_MESSAGE_INVALID"
    if Decimal(str(message["latency_minutes"])) > Decimal(str(channel["max_latency_minutes"])):
        message["validation_status"] = "REJECTED"
        message["validation_error_code"] = "ERR_INTERFACE_LATENCY_EXCEEDED"
        _cascade_rejection(channel, message)
        return "ERR_INTERFACE_LATENCY_EXCEEDED"
    return None


def _cascade_rejection(channel, message):
    message["decided_epoch"] = DB.ehr_implementations[channel["ehr_implementation_id"]][
        "current_epoch_index"
    ]
    R.recompute_channel(channel)
    if channel["status"] == "IN_MESSAGE_VALIDATION":
        channel["status"] = "VALIDATION_FAILED"
        DB.touch(channel, common=True)


@bp.route("/interface-channels/<channel_id>/messages", methods=["GET"])
def list_channel_messages(channel_id):
    uid, role = actor()
    require_role(role, READ_ROLES)
    channel = get_channel(channel_id)
    rows = L.channel_messages(channel["id"])
    filters = filter_args(["validation_status"])
    if "validation_status" in filters:
        rows = [m for m in rows if m["validation_status"] == filters["validation_status"]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([message_view(m) for m in window], pagination=page)


@bp.route("/interface-messages", methods=["GET"])
def list_messages():
    uid, role = actor()
    require_role(role, READ_ROLES)
    rows = list(DB.interface_messages.values())
    filters = filter_args(["interface_channel_id", "ehr_implementation_id", "validation_status"])
    for key, value in filters.items():
        rows = [m for m in rows if m.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([message_view(m) for m in window], pagination=page)


@bp.route("/interface-messages/<message_id>", methods=["GET"])
def get_message_endpoint(message_id):
    uid, role = actor()
    require_role(role, READ_ROLES)
    return ok(message_view(get_message(message_id)))


@bp.route("/interface-messages/<message_id>/validate", methods=["POST"])
def validate_message_endpoint(message_id):
    uid, role = actor()
    require_role(role, ["InterfaceEngineer"])
    message = get_message(message_id)
    channel = DB.interface_channels[message["interface_channel_id"]]
    if message["validation_status"] != "RECEIVED":
        fail(ERR_INVALID_STATE, "Validating requires validation_status RECEIVED.")
    error_code = _validate_message(channel, message)
    if error_code is not None:
        R.recompute_program_tree(channel["ehr_implementation_id"])
        fail(
            ERR_INTERFACE_MESSAGE_INVALID
            if error_code == "ERR_INTERFACE_MESSAGE_INVALID"
            else ERR_INTERFACE_LATENCY_EXCEEDED,
            "The message failed interface validation.",
        )
    message["validation_status"] = "VALIDATED"
    message["decided_epoch"] = DB.ehr_implementations[channel["ehr_implementation_id"]][
        "current_epoch_index"
    ]
    R.recompute_program_tree(channel["ehr_implementation_id"])
    return ok(message_view(message))