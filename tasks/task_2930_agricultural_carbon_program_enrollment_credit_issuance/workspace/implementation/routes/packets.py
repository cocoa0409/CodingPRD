"""Data packet filing and quality control (section 3.5)."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware as mw
import response as resp
import validators as v
from services import calc, common, serialize

bp = Blueprint("packets", __name__)

SOURCES = ("FARM_RECORD", "EQUIPMENT_TELEMETRY", "REMOTE_SENSING")

FILTERS = {
    "enrollment_id": ("enrollment_id", "str"),
    "crop_year": ("crop_year", "int"),
    "source": ("source", "str"),
    "qc_status": ("qc_status", "str"),
    "completeness_status": ("completeness_status", "str"),
}

READ_ROLES = (mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER, mw.ROLE_VERIFIER)


def _rescore(packet, enrollment):
    packet["qc_score"] = calc.qc_score(
        packet["coverage_pct"],
        packet["reported_acres"],
        packet["source"],
        enrollment["enrolled_acres"],
    )
    packet["completeness_status"] = calc.completeness_status(packet["coverage_pct"])


@bp.route("/enrollments/<enrollment_id>/data-packets", methods=["POST"])
def create_packet(enrollment_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER)
    enrollment = common.get_enrollment(enrollment_id)
    mw.require_grower_owner(enrollment["grower_id"])
    body = v.json_body()
    crop_year = v.v_crop_year(body, "crop_year")
    source = v.v_enum(body, "source", SOURCES)
    reported_acres = v.v_dec(body, "reported_acres", 2, minimum=0, exclusive_min=True)
    coverage_pct = v.v_dec(body, "coverage_pct", 2, minimum=0, maximum=100)
    measured_value = v.v_dec(body, "measured_value", 4, required=False, minimum=0)

    grower = db.growers.get(enrollment["grower_id"])
    if grower is not None and grower["status"] == "SUSPENDED":
        common.fail("ERR_GROWER_SUSPENDED")

    for other in db.sorted_rows(db.data_packets):
        if (
            other["enrollment_id"] == enrollment["id"]
            and other["crop_year"] == crop_year
            and other["source"] == source
            and other["qc_status"] != "REJECTED"
        ):
            common.fail("ERR_DUPLICATE_DATA_PACKET")

    row = db.common_fields()
    row.update({
        "enrollment_id": enrollment["id"],
        "crop_year": crop_year,
        "source": source,
        "reported_acres": reported_acres,
        "measured_value": measured_value if measured_value is not None else Decimal("0.0000"),
        "coverage_pct": coverage_pct,
        "qc_score": None,
        "qc_status": "PENDING",
        "completeness_status": None,
        "flag_reason": None,
        "correction_count": 0,
    })
    _rescore(row, enrollment)
    db.data_packets[row["id"]] = row
    return resp.object_response(serialize.data_packet(row), 201)


@bp.route("/data-packets", methods=["GET"])
def list_packets():
    mw.authorize(*READ_ROLES)
    rows = common.apply_filters(db.data_packets.values(), FILTERS)
    return resp.paginate(rows, serialize.data_packet)


@bp.route("/data-packets/<data_packet_id>", methods=["GET"])
def read_packet(data_packet_id):
    mw.authorize(*READ_ROLES)
    row = common.get_data_packet(data_packet_id)
    enrollment = db.enrollments.get(row["enrollment_id"])
    if enrollment is not None:
        mw.require_grower_owner(enrollment["grower_id"])
    return resp.object_response(serialize.data_packet(row))


@bp.route("/data-packets/<data_packet_id>/qc", methods=["POST"])
def qc_packet(data_packet_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    packet = common.get_data_packet(data_packet_id)
    body = v.json_body()
    decision = v.v_enum(body, "decision", ("PASS", "FLAG"))
    flag_reason = None
    if decision == "FLAG":
        flag_reason = v.v_str(body, "flag_reason")
    if packet["qc_status"] != "PENDING":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Only a PENDING packet may be quality-controlled."
        )
    if decision == "PASS":
        if Decimal(packet["qc_score"]) < calc.QC_PASS_MIN_SCORE:
            common.fail("ERR_QC_SCORE_BELOW_THRESHOLD")
        packet["qc_status"] = "PASSED"
    else:
        packet["flag_reason"] = flag_reason
        packet["qc_status"] = "FLAGGED"
    db.touch(packet)
    return resp.object_response(serialize.data_packet(packet))


@bp.route("/data-packets/<data_packet_id>/correct", methods=["POST"])
def correct_packet(data_packet_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER)
    packet = common.get_data_packet(data_packet_id)
    enrollment = db.enrollments[packet["enrollment_id"]]
    mw.require_grower_owner(enrollment["grower_id"])
    body = v.json_body()
    reported_acres = v.v_dec(body, "reported_acres", 2, required=False, minimum=0,
                             exclusive_min=True)
    coverage_pct = v.v_dec(body, "coverage_pct", 2, required=False, minimum=0, maximum=100)
    measured_value = v.v_dec(body, "measured_value", 4, required=False, minimum=0)

    grower = db.growers.get(enrollment["grower_id"])
    if grower is not None and grower["status"] == "SUSPENDED":
        common.fail("ERR_GROWER_SUSPENDED")

    if packet["qc_status"] != "FLAGGED" or enrollment["status"] != "ACTIVE":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "A FLAGGED packet on an ACTIVE enrollment is required for a correction.",
        )

    if reported_acres is not None:
        packet["reported_acres"] = reported_acres
    if coverage_pct is not None:
        packet["coverage_pct"] = coverage_pct
    if measured_value is not None:
        packet["measured_value"] = measured_value
    _rescore(packet, enrollment)
    packet["correction_count"] = packet["correction_count"] + 1
    packet["flag_reason"] = None
    packet["qc_status"] = "PENDING"
    db.touch(packet)
    return resp.object_response(serialize.data_packet(packet))


@bp.route("/data-packets/<data_packet_id>/reject", methods=["POST"])
def reject_packet(data_packet_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    packet = common.get_data_packet(data_packet_id)
    body = v.json_body()
    flag_reason = v.v_str(body, "flag_reason", required=False)
    if packet["qc_status"] != "FLAGGED":
        common.fail("ERR_INVALID_STATE_TRANSITION", "Only a FLAGGED packet may be rejected.")
    if flag_reason is not None:
        packet["flag_reason"] = flag_reason
    packet["qc_status"] = "REJECTED"
    db.touch(packet)
    return resp.object_response(serialize.data_packet(packet))
