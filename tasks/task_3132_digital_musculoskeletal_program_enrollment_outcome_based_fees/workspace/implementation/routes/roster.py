"""Roster files, members and care-track configuration."""

from flask import Blueprint, request

from db import STORE
from middleware import body, query, require
from response import array_response, object_response, page
from services import billing, intake

bp = Blueprint("roster", __name__)

READ_ROLES = ["EnrollmentOps", "ClinicalOps", "BillingOps"]


# --- eligibility files -----------------------------------------------------
@bp.route("/msk/eligibility-files", methods=["POST"])
def create_file():
    require(["EnrollmentOps"], "POST /msk/eligibility-files")
    return object_response(dict(intake.create_roster_file(body())), 201)


@bp.route("/msk/eligibility-files", methods=["GET"])
def list_files():
    require(READ_ROLES, "GET /msk/eligibility-files")
    rows = STORE.all("EligibilityFile")
    client_id = query("client_account_id")
    if client_id:
        rows = [r for r in rows if r["client_account_id"] == client_id]
    status = query("file_status")
    if status:
        rows = [r for r in rows if r["file_status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/eligibility-files/<file_id>", methods=["GET"])
def read_file(file_id):
    require(READ_ROLES, "GET /msk/eligibility-files/{id}")
    row = STORE.need("EligibilityFile", file_id, "EligibilityFile")
    return object_response(dict(row))


@bp.route("/msk/eligibility-files/<file_id>/screen", methods=["POST"])
def screen_file(file_id):
    require(["EnrollmentOps"], "POST /msk/eligibility-files/{id}/screen")
    return object_response(dict(intake.screen_eligibility_file(file_id)))


@bp.route("/msk/eligibility-files/<file_id>/assign-tracks", methods=["POST"])
def assign_tracks(file_id):
    require(["EnrollmentOps"], "POST /msk/eligibility-files/{id}/assign-tracks")
    return object_response(dict(intake.assign_tracks(file_id, body())))


@bp.route("/msk/eligibility-files/<file_id>/close-file", methods=["POST"])
def close_file(file_id):
    require(["EnrollmentOps"], "POST /msk/eligibility-files/{id}/close-file")
    return object_response(dict(intake.close_file(file_id)))


# --- members ---------------------------------------------------------------
@bp.route("/msk/members", methods=["POST"])
def create_member():
    require(["EnrollmentOps"], "POST /msk/members")
    return object_response(dict(intake.create_member(body())), 201)


@bp.route("/msk/members", methods=["GET"])
def list_members():
    require(READ_ROLES, "GET /msk/members")
    rows = STORE.all("Member")
    client_id = query("client_account_id")
    if client_id:
        rows = [r for r in rows if r["client_account_id"] == client_id]
    file_id = query("eligibility_file_id")
    if file_id:
        rows = [r for r in rows if r["eligibility_file_id"] == file_id]
    status = query("member_status")
    if status:
        rows = [r for r in rows if r["member_status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/members/<member_id>", methods=["GET"])
def read_member(member_id):
    require(READ_ROLES, "GET /msk/members/{id}")
    row = STORE.need("Member", member_id, "Member")
    from db import member_red_flag_weight

    row["red_flag_weight"] = member_red_flag_weight(row)
    return object_response(dict(row))


@bp.route("/msk/members/<member_id>/recompute_eligibility", methods=["POST"])
def recompute_eligibility(member_id):
    require(
        ["EligibilityService"], "POST /msk/members/{id}/recompute_eligibility"
    )
    return object_response(dict(intake.recompute_eligibility(member_id)))


# --- program tracks --------------------------------------------------------
@bp.route("/msk/program-tracks", methods=["POST"])
def create_track():
    require(["ClinicalOps"], "POST /msk/program-tracks")
    payload = body()
    owner = None
    if payload.get("client_account_id"):
        owner = intake.client(payload["client_account_id"])["id"]
    return object_response(dict(intake.create_track(payload, owner=owner)), 201)


@bp.route("/msk/program-tracks", methods=["GET"])
def list_tracks():
    require(["ClinicalOps", "EnrollmentOps", "BillingOps"], "GET /msk/program-tracks")
    rows = STORE.all("ProgramTrack")
    code = query("track_code")
    if code:
        rows = [r for r in rows if r["track_code"] == code]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/program-tracks/<track_id>", methods=["GET"])
def read_track(track_id):
    require(["ClinicalOps", "EnrollmentOps", "BillingOps"], "GET /msk/program-tracks/{id}")
    row = STORE.need("ProgramTrack", track_id, "ProgramTrack")
    return object_response(dict(row))