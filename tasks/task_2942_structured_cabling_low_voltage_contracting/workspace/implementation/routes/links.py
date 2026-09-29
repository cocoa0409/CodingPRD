"""PRD 3.4, 3.6 and 3.7 — link design, installation, administration and Cascade A."""

from flask import Blueprint, g, request

import calc
import identifiers
import lookup
import rollups
import serial
from auth import (ALL_ROLES, CERTIFIER, CLIENT, DESIGN_ENGINEER, INSTALLER,
                  MANUFACTURER_AGENT, PROJECT_MANAGER, TEST_TECHNICIAN, require)
from envelope import created, enum_filter, ok, paginate
from errors import ApiError
from store import D, base_record, db, touch
from validation import Field, body, no_body

links_bp = Blueprint("links", __name__)

INSTALL_STATES = ("DESIGNED", "PULLED", "TERMINATED", "TESTED_PASS", "TESTED_FAIL",
                  "CERTIFIED")
RECORD_STATES = ("UNLABELED", "LABELED", "RECORDED")
LABELABLE_INSTALL_STATES = ("TERMINATED", "TESTED_PASS", "TESTED_FAIL")

READ_ROLES = ALL_ROLES
REPORT_ROLES = (PROJECT_MANAGER, DESIGN_ENGINEER, TEST_TECHNICIAN, CERTIFIER,
                MANUFACTURER_AGENT, CLIENT)


@links_bp.route("/cabling/links", methods=["POST"])
@require(DESIGN_ENGINEER)
def design_link():
    values = body([
        Field("project_id", "string"),
        Field("telecom_room_id", "string"),
        Field("cable_type_id", "string"),
        Field("identifier", "string"),
        Field("application", "enum", enum=calc.APPLICATIONS),
        Field("horizontal_length_m", "number", exclusive_min=0),
        Field("consolidation_point_stub_m", "number", required=False, default=0,
              minimum=0),
        Field("patch_cord_allowance_m", "number", required=False, default=0, minimum=0),
    ])
    project = lookup.project(values["project_id"])
    room = lookup.room(values["telecom_room_id"])
    cable_type = lookup.cable_type(values["cable_type_id"])
    if room["project_id"] != project["id"]:
        raise ApiError("ERR_CROSS_PROJECT_REFERENCE",
                       "telecom_room_id belongs to a different project.")
    identifiers.screen_identifier(project, values["identifier"])
    if values["application"] not in cable_type["applications"]:
        raise ApiError("ERR_APPLICATION_NOT_SUPPORTED",
                       "The cable type is not approved for that application.")

    permanent = calc.permanent_link_length_m(values["horizontal_length_m"],
                                            values["consolidation_point_stub_m"])
    channel = calc.channel_length_m(permanent, values["patch_cord_allowance_m"])
    link = base_record()
    link.update({
        "project_id": project["id"],
        "telecom_room_id": room["id"],
        "cable_type_id": cable_type["id"],
        "identifier": values["identifier"],
        "application": values["application"],
        "horizontal_length_m": values["horizontal_length_m"],
        "consolidation_point_stub_m": values["consolidation_point_stub_m"],
        "patch_cord_allowance_m": values["patch_cord_allowance_m"],
        "permanent_link_length_m": permanent,
        "channel_length_m": channel,
        "install_state": "DESIGNED",
        "record_state": "UNLABELED",
        "applied_identifier": None,
        "drawing_sheet_ref": None,
        "installer_user_id": None,
        "certifier_user_id": None,
        "routed_segment_count": 0,
        "test_attempt_count": 0,
        "latest_test_outcome": None,
        "material_cost_cents": calc.material_cost_cents(
            cable_type["cost_per_meter_cents"], channel),
    })
    db.links[link["id"]] = link
    # A freshly designed link dilutes both completeness variants (PRD 3.4).
    rollups.refresh_project(project)
    return created(serial.public(link))


@links_bp.route("/cabling/links/<link_id>", methods=["GET"])
@require(*READ_ROLES)
def read_link(link_id):
    return ok(serial.public(lookup.link(link_id)))


@links_bp.route("/cabling/links", methods=["GET"])
@require(*READ_ROLES)
def list_links():
    project_id = request.args.get("project_id")
    telecom_room_id = request.args.get("telecom_room_id")
    cable_type_id = request.args.get("cable_type_id")
    install_state = enum_filter(request.args, "install_state", INSTALL_STATES)
    record_state = enum_filter(request.args, "record_state", RECORD_STATES)
    application = enum_filter(request.args, "application", calc.APPLICATIONS)
    rows = []
    for link in db.links.values():
        if project_id is not None and link["project_id"] != project_id:
            continue
        if telecom_room_id is not None and link["telecom_room_id"] != telecom_room_id:
            continue
        if cable_type_id is not None and link["cable_type_id"] != cable_type_id:
            continue
        if install_state is not None and link["install_state"] != install_state:
            continue
        if record_state is not None and link["record_state"] != record_state:
            continue
        if application is not None and link["application"] != application:
            continue
        rows.append(link)
    return paginate(rows, request.args, serial.public)


@links_bp.route("/cabling/links/<link_id>/pull", methods=["POST"])
@require(INSTALLER)
def pull_link(link_id):
    no_body()
    link = lookup.link(link_id)
    if link["install_state"] != "DESIGNED":
        raise ApiError("ERR_INVALID_LINK_STATE", "Only a DESIGNED link can be pulled.")
    occupying = [r for r in rollups.link_routes(link["id"])
                 if r["route_state"] == "OCCUPYING"]
    for route in occupying:
        segment = db.segments.get(route["pathway_segment_id"])
        if segment is not None and segment["pathway_state"] == "CONDEMNED":
            raise ApiError("ERR_SEGMENT_CONDEMNED",
                           "A routing of this link sits on a condemned segment.")
    if link["routed_segment_count"] < 1:
        raise ApiError("ERR_LINK_NOT_ROUTED",
                       "There is no pathway to pull the cable through.")
    coordinated = [c for c in rollups.project_coordinations(link["project_id"])
                   if c["trade"] == "CEILING" and c["milestone"] == "PATHWAY_ROUGH_IN"
                   and c["coordination_state"] in ("CONFIRMED", "RELEASED")]
    if not coordinated:
        raise ApiError("ERR_TRADE_NOT_COORDINATED",
                       "A CONFIRMED or RELEASED CEILING / PATHWAY_ROUGH_IN coordination "
                       "is required before the pull.")
    cable_type = db.cable_types.get(link["cable_type_id"])
    if cable_type is not None:
        limit = calc.permanent_link_limit_m(cable_type)
        if D(link["permanent_link_length_m"]) > limit:
            raise ApiError("ERR_LINK_LENGTH_EXCEEDED",
                           "permanent_link_length_m exceeds the limit for this category.")
    link["install_state"] = "PULLED"
    touch(link)
    return ok(serial.public(link))


@links_bp.route("/cabling/links/<link_id>/terminate", methods=["POST"])
@require(INSTALLER)
def terminate_link(link_id):
    no_body()
    link = lookup.link(link_id)
    if link["install_state"] not in ("PULLED", "TESTED_FAIL"):
        raise ApiError("ERR_INVALID_LINK_STATE",
                       "Termination is declared from PULLED or TESTED_FAIL only.")
    room = db.rooms.get(link["telecom_room_id"])
    if room is None or room["grounding_status"] != "COMPLIANT":
        raise ApiError("ERR_ROOM_NOT_GROUNDED",
                       "The link's telecom room must be graded COMPLIANT.")
    link["install_state"] = "TERMINATED"
    link["installer_user_id"] = g.user_id
    touch(link)
    project = db.projects.get(link["project_id"])
    if project is not None:
        rollups.refresh_project(project)
    return ok(serial.public(link))


@links_bp.route("/cabling/links/<link_id>/label", methods=["POST"])
@require(INSTALLER)
def label_link(link_id):
    values = body([Field("applied_identifier", "string")])
    link = lookup.link(link_id)
    if link["record_state"] != "UNLABELED":
        raise ApiError("ERR_INVALID_RECORD_STATE",
                       "Only an UNLABELED link can be labelled.")
    if link["install_state"] not in LABELABLE_INSTALL_STATES:
        raise ApiError("ERR_INVALID_LINK_STATE",
                       "A label goes on cable that has actually been landed.")
    if values["applied_identifier"] != link["identifier"]:
        raise ApiError("ERR_LABEL_MISMATCH",
                       "applied_identifier must equal the link's designed identifier.")
    link["applied_identifier"] = values["applied_identifier"]
    link["record_state"] = "LABELED"
    touch(link)
    return ok(serial.public(link))


@links_bp.route("/cabling/links/<link_id>/record", methods=["POST"])
@require(DESIGN_ENGINEER, PROJECT_MANAGER)
def record_link(link_id):
    values = body([Field("drawing_sheet_ref", "string")])
    link = lookup.link(link_id)
    if link["record_state"] != "LABELED":
        raise ApiError("ERR_INVALID_RECORD_STATE",
                       "Only a LABELED link can be filed on an as-built sheet.")
    link["drawing_sheet_ref"] = values["drawing_sheet_ref"]
    link["record_state"] = "RECORDED"
    touch(link)
    return ok(serial.public(link))


@links_bp.route("/cabling/links/<link_id>/certify", methods=["POST"])
@require(CERTIFIER)
def certify_link(link_id):
    no_body()
    link = lookup.link(link_id)
    if link["install_state"] != "TESTED_PASS":
        raise ApiError("ERR_LINK_NOT_TESTED",
                       "Certification requires install_state TESTED_PASS.")
    if link["record_state"] != "RECORDED":
        raise ApiError("ERR_LINK_NOT_RECORDED",
                       "Certification requires record_state RECORDED.")
    latest = rollups.latest_test_result(link["id"])
    if link["installer_user_id"] is not None and g.user_id == link["installer_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The installer of a link may not certify it.")
    if latest is not None and g.user_id == latest["tester_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The tester of a link may not certify it.")
    if link["latest_test_outcome"] != "PASS":
        raise ApiError("ERR_MARGINAL_TEST_NOT_CERTIFIABLE",
                       "Only a strict PASS is certifiable.")
    # Cascade A, hop 1.
    link["install_state"] = "CERTIFIED"
    link["certifier_user_id"] = g.user_id
    touch(link)
    # Hops 2, 3 and 4.
    project = db.projects.get(link["project_id"])
    if project is not None:
        rollups.refresh_project(project)
    return ok(serial.public(link))


@links_bp.route("/cabling/links/<link_id>/certification-report", methods=["GET"])
@require(*REPORT_ROLES)
def read_certification_report(link_id):
    link = lookup.link(link_id)
    return ok(serial.certification_report(link))
