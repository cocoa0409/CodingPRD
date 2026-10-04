"""Folder, folder-grant and join-row routes."""
from flask import Blueprint, request

from common import account_or_404, folder_or_404, make_join, member_or_404, \
    require_folder_visibility
from db import db
from errors import ApiError
from middleware import require
from models import new_folder, new_folder_grant, public, touch
from response import paginate, success

bp = Blueprint("folders", __name__)


@bp.route("/folders", methods=["POST"])
@require("Member")
def create_folder():
    body = request.get_json(silent=True) or {}
    account = account_or_404(body.get("account_id"))
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ApiError("ERR_DUPLICATE_FOLDER_NAME", "name must be non-empty.")
    for folder in db.folders.values():
        if folder["account_id"] == account["id"] and folder["name"] == name:
            raise ApiError("ERR_DUPLICATE_FOLDER_NAME")
    rec = new_folder(account["id"], name)
    db.folders[rec["id"]] = rec
    grant = new_folder_grant(rec["id"], request.actor_id, "MANAGE")
    db.folder_grants[grant["id"]] = grant
    make_join(rec["id"], grant["id"])
    return success(public(rec), 201)


@bp.route("/folders", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_folders():
    account_id = request.args.get("account_id")
    items = [public(f) for f in db.folders.values()
             if account_id is None or f["account_id"] == account_id]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/folders/<folder_id>", methods=["GET"])
@require("Member", "PlatformAdmin")
def read_folder(folder_id):
    return success(public(folder_or_404(folder_id)))


@bp.route("/folders/<folder_id>/grants", methods=["POST"])
@require("Member")
def create_grant(folder_id):
    folder = folder_or_404(folder_id)
    require_folder_visibility(folder)
    body = request.get_json(silent=True) or {}
    member = member_or_404(body.get("member_id"))
    grant_role = body.get("grant_role")
    if grant_role not in ("READ", "EDIT", "MANAGE"):
        raise ApiError("ERR_FORBIDDEN", "grant_role must be one of READ, EDIT, MANAGE.")
    for grant in db.folder_grants.values():
        if grant["folder_id"] == folder["id"] and grant["member_id"] == member["id"]:
            raise ApiError("ERR_DUPLICATE_GRANT")
    rec = new_folder_grant(folder["id"], member["id"], grant_role)
    db.folder_grants[rec["id"]] = rec
    make_join(folder["id"], rec["id"])
    return success(public(rec), 201)


@bp.route("/folders/<folder_id>/grants", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_folder_grants(folder_id):
    folder_or_404(folder_id)
    items = [public(g) for g in db.folder_grants.values() if g["folder_id"] == folder_id]
    return success(items)


@bp.route("/members/<member_id>/grants", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_member_grants(member_id):
    member_or_404(member_id)
    items = [public(g) for g in db.folder_grants.values() if g["member_id"] == member_id]
    return success(items)


@bp.route("/folder-grants", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_all_grants():
    member_id = request.args.get("member_id")
    items = [public(g) for g in db.folder_grants.values()
             if member_id is None or g["member_id"] == member_id]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/folder-grants/<grant_id>", methods=["GET"])
@require("Member", "PlatformAdmin")
def read_grant(grant_id):
    rec = db.folder_grants.get(grant_id)
    if rec is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "The referenced folder grant does not exist.", 404)
    return success(public(rec))


@bp.route("/folder-folder-grants", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_joins():
    folder_id = request.args.get("folder_id")
    grant_id = request.args.get("grant_id")
    items = [public(j) for j in db.folder_folder_grants.values()
             if (folder_id is None or j["folder_id"] == folder_id)
             and (grant_id is None or j["grant_id"] == grant_id)]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/folder-folder-grants/<join_id>", methods=["GET"])
@require("Member", "PlatformAdmin")
def read_join(join_id):
    rec = db.folder_folder_grants.get(join_id)
    if rec is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "The referenced join row does not exist.", 404)
    return success(public(rec))