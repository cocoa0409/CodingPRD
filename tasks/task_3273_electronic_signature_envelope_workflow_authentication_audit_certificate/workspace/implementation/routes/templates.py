"""Template and bulk-send routes."""

from flask import Blueprint, request

from db import db
from errors import ApiError, ERR_TEMPLATE_NOT_FOUND
from middleware import authenticate, owned_by_account, ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN
from response import ok, ok_array, paginate, read_pagination
from services.account import (
    archive_template,
    create_bulk_send,
    create_template,
    instantiate_template,
    process_bulk_send,
    publish_template,
)

bp = Blueprint("templates", __name__)


def load_template_or_404(template_id):
    template = db.template(template_id)
    if template is None:
        raise ApiError(
            ERR_TEMPLATE_NOT_FOUND[0],
            "no template matches id %s" % template_id,
            ERR_TEMPLATE_NOT_FOUND[1],
        )
    return template


def load_bulk_send_or_404(batch_id):
    batch = db.bulk_send(batch_id)
    if batch is None:
        raise ApiError(
            "ERR_BULK_ROW_INVALID",
            "no bulk send batch matches id %s" % batch_id,
            422,
        )
    return batch


@bp.route("/esign/templates", methods=["POST"])
def post_template():
    actor = authenticate([ROLE_ACCOUNT])
    body = request.get_json(silent=True) or {}
    owned_by_account(actor, body.get("owning_account_id"))
    template = create_template(body)
    return ok(template, 201)


@bp.route("/esign/templates", methods=["GET"])
def list_templates():
    authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    limit, offset = read_pagination(request.args)
    owning_account_id = request.args.get("owning_account_id")
    status = request.args.get("status")
    templates = list(db.templates.values())
    if owning_account_id:
        templates = [
            t for t in templates if t["owning_account_id"] == owning_account_id
        ]
    if status:
        templates = [t for t in templates if t["status"] == status]
    templates.sort(key=lambda t: t.get("_ord", 0))
    window, limit, offset, total = paginate(templates, limit, offset)
    return ok_array(window, limit, offset, total, 200)


@bp.route("/esign/templates/<template_id>", methods=["GET"])
def get_template(template_id):
    authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    template = load_template_or_404(template_id)
    return ok(template, 200)


@bp.route("/esign/templates/<template_id>/publish", methods=["POST"])
def post_publish(template_id):
    actor = authenticate([ROLE_ACCOUNT])
    template = load_template_or_404(template_id)
    owned_by_account(actor, template["owning_account_id"])
    template = publish_template(template)
    return ok(template, 200)


@bp.route("/esign/templates/<template_id>/archive", methods=["POST"])
def post_archive(template_id):
    actor = authenticate([ROLE_ACCOUNT])
    template = load_template_or_404(template_id)
    owned_by_account(actor, template["owning_account_id"])
    template = archive_template(template)
    return ok(template, 200)


@bp.route("/esign/templates/<template_id>/instantiate", methods=["POST"])
def post_instantiate(template_id):
    actor = authenticate([ROLE_ACCOUNT])
    template = load_template_or_404(template_id)
    body = request.get_json(silent=True) or {}
    owned_by_account(actor, body.get("sender_account_id"))
    envelope = instantiate_template(template, body)
    return ok(envelope, 201)


# --- bulk send ----------------------------------------------------------

@bp.route("/esign/bulk-sends", methods=["POST"])
def post_bulk_send():
    actor = authenticate([ROLE_ACCOUNT])
    body = request.get_json(silent=True) or {}
    owned_by_account(actor, body.get("account_id"))
    batch = create_bulk_send(body)
    return ok(batch, 201)


@bp.route("/esign/bulk-sends", methods=["GET"])
def list_bulk_sends():
    authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    limit, offset = read_pagination(request.args)
    account_id = request.args.get("account_id")
    template_id = request.args.get("template_id")
    status = request.args.get("status")
    batches = list(db.bulk_sends.values())
    if account_id:
        batches = [b for b in batches if b["account_id"] == account_id]
    if template_id:
        batches = [b for b in batches if b["template_id"] == template_id]
    if status:
        batches = [b for b in batches if b["status"] == status]
    batches.sort(key=lambda b: b.get("_ord", 0))
    window, limit, offset, total = paginate(batches, limit, offset)
    return ok_array(window, limit, offset, total, 200)


@bp.route("/esign/bulk-sends/<batch_id>", methods=["GET"])
def get_bulk_send(batch_id):
    authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    batch = load_bulk_send_or_404(batch_id)
    return ok(batch, 200)


@bp.route("/esign/bulk-sends/<batch_id>/process", methods=["POST"])
def post_bulk_send_process(batch_id):
    actor = authenticate([ROLE_ACCOUNT])
    batch = load_bulk_send_or_404(batch_id)
    owned_by_account(actor, batch["account_id"])
    body = request.get_json(silent=True) or {}
    batch = process_bulk_send(batch, body)
    return ok(batch, 200)