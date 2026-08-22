"""Pieces: creation, run assignment and erection (PRD 3.2, 3.8)."""
from flask import Blueprint

import auth
import cascade
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("pieces", __name__)


@bp.post("/pieces")
def create_piece():
    auth.require(constants.ROLE_PRODUCTION_SUPERVISOR)
    body = validation.get_body()
    project_id = validation.req_id(body, "project_id")
    mix_id = validation.req_id(body, "mix_design_id")
    piece_mark = validation.req_str(body, "piece_mark")
    sequence_no = validation.req_int(body, "erection_sequence_no", exclusive_min=0)
    length_ft = validation.req_number(body, "length_ft", exclusive_min=0)
    width_ft = validation.req_number(body, "width_ft", exclusive_min=0)
    height_ft = validation.req_number(body, "height_ft", exclusive_min=0)
    weight_lb = validation.req_number(body, "weight_lb", exclusive_min=0)
    volume_cy = validation.req_number(body, "concrete_volume_cy", exclusive_min=0)
    replaces_piece_id = validation.opt_id(body, "replaces_piece_id")

    project = lookup.project(project_id)
    lookup.mix_design(mix_id)
    if replaces_piece_id is not None:
        lookup.piece(replaces_piece_id)

    for existing in db.store.pieces.values():
        if existing["project_id"] == project_id and existing["piece_mark"] == piece_mark:
            errors.fail(errors.ERR_DUPLICATE_PIECE_MARK,
                        "piece_mark %s is already used in this project." % piece_mark)

    requires_permit = (width_ft > constants.LEGAL_WIDTH_FT
                       or height_ft > constants.LEGAL_HEIGHT_FT
                       or length_ft > constants.LEGAL_LENGTH_FT)

    row = db.new_row(db.store.pieces, {
        "project_id": project_id,
        "mix_design_id": mix_id,
        "bed_run_id": None,
        "replaces_piece_id": replaces_piece_id,
        "piece_mark": piece_mark,
        "erection_sequence_no": sequence_no,
        "length_ft": length_ft,
        "width_ft": width_ft,
        "height_ft": height_ft,
        "weight_lb": weight_lb,
        "concrete_volume_cy": volume_cy,
        "production_status": "PLANNED",
        "qc_status": "PENDING",
        "qc_hold_reason": None,
        "requires_haul_permit": bool(requires_permit),
        "allocated_cost_cents": None,
    })
    db.mark_fresh(row)
    db.touch(project)
    return response.object_response(serialize.piece(row), 201)


@bp.get("/pieces/<piece_id>")
def get_piece(piece_id):
    auth.require_any()
    row = lookup.piece(piece_id)
    return response.object_response(serialize.piece(row), 200)


@bp.get("/pieces")
def list_pieces():
    auth.require_any()
    project_id = validation.query_filter("project_id")
    bed_run_id = validation.query_filter("bed_run_id")
    mix_id = validation.query_filter("mix_design_id")
    replaces_id = validation.query_filter("replaces_piece_id")
    production_status = validation.query_filter("production_status")
    qc_status = validation.query_filter("qc_status")
    rows = [p for p in db.store.pieces.values()
            if (project_id is None or p["project_id"] == project_id)
            and (bed_run_id is None or p["bed_run_id"] == bed_run_id)
            and (mix_id is None or p["mix_design_id"] == mix_id)
            and (replaces_id is None or p["replaces_piece_id"] == replaces_id)
            and (production_status is None or p["production_status"] == production_status)
            and (qc_status is None or p["qc_status"] == qc_status)]
    return listing.list_response(rows, serialize.piece)


@bp.post("/pieces/<piece_id>/assign-run")
def assign_run(piece_id):
    auth.require(constants.ROLE_PRODUCTION_SUPERVISOR)
    piece = lookup.piece(piece_id)
    body = validation.get_body()
    run_id = validation.req_id(body, "bed_run_id")
    run = lookup.bed_run(run_id)

    if piece["production_status"] != "PLANNED":
        errors.fail(errors.ERR_PIECE_INVALID_STATE,
                    "Only a PLANNED piece may be assigned to a run.")
    if run["status"] not in ("SCHEDULED", "TENSIONED"):
        errors.fail(errors.ERR_BED_RUN_INVALID_STATE,
                    "The run does not accept new pieces.")
    if piece["mix_design_id"] != run["mix_design_id"]:
        errors.fail(errors.ERR_MIX_CLASS_MISMATCH,
                    "The piece's mix design differs from the run's.")

    piece["bed_run_id"] = run["id"]
    piece["production_status"] = "SCHEDULED"
    db.touch(piece)
    db.touch(run)
    return response.object_response(serialize.piece(piece), 200)


@bp.post("/pieces/<piece_id>/confirm-erected")
def confirm_erected(piece_id):
    user_id, _role = auth.require(constants.ROLE_PROJECT_OWNER)
    piece = lookup.piece(piece_id)

    if user_id != piece["project_id"]:
        errors.fail(errors.ERR_PROJECT_SCOPE_FORBIDDEN,
                    "This project owner does not own the targeted piece.")
    if piece["production_status"] != "SHIPPED":
        errors.fail(errors.ERR_PIECE_INVALID_STATE,
                    "Only a SHIPPED piece may be confirmed erected.")
    for sibling in db.store.pieces.values():
        if (sibling["project_id"] == piece["project_id"]
                and sibling["erection_sequence_no"] < piece["erection_sequence_no"]
                and sibling["production_status"] not in ("ERECTED", "SCRAPPED")):
            errors.fail(errors.ERR_ERECTION_PREDECESSOR_PENDING,
                        "A lower-sequence sibling has not been erected yet.")

    piece["production_status"] = "ERECTED"
    db.touch(piece)
    cascade.touch_project_of(piece)
    return response.object_response(serialize.piece(piece), 200)


@bp.get("/pieces/<piece_id>/yard-placements")
def list_piece_placements(piece_id):
    auth.require_any()
    lookup.piece(piece_id)
    status = validation.query_filter("status")
    rows = [p for p in db.store.yard_placements.values()
            if p["piece_id"] == piece_id
            and (status is None or p["status"] == status)]
    return listing.list_response(rows, serialize.yard_placement)


@bp.get("/pieces/<piece_id>/shipment-lines")
def list_piece_shipment_lines(piece_id):
    auth.require_any()
    lookup.piece(piece_id)
    rows = [l for l in db.store.shipment_lines.values() if l["piece_id"] == piece_id]
    return listing.list_response(rows, serialize.shipment_line)


@bp.get("/pieces/<piece_id>/repair-dispositions")
def list_piece_dispositions(piece_id):
    auth.require_any()
    lookup.piece(piece_id)
    status = validation.query_filter("status")
    rows = [d for d in db.store.repair_dispositions.values()
            if d["piece_id"] == piece_id
            and (status is None or d["status"] == status)]
    return listing.list_response(rows, serialize.repair_disposition)
