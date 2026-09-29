"""Programming templates and their lineage."""
from flask import Blueprint

import common
import db
import enums
import response
import serialize
import validate
from errors import ApiError
from validate import FLEET_ENGINEER

bp = Blueprint("templates", __name__, url_prefix=common.PREFIX)


def _content(body):
    return (
        validate.req_str(body, "template_name", 1, 80),
        validate.req_enum(body, "target_standard", enums.TARGET_STANDARDS),
        validate.req_int(body, "talkgroup_slot_count", 1, 512),
        validate.opt_bool(body, "encryption_required", False),
    )


def _new_template(name, standard, slots, encrypted, actor, lineage, parent_id):
    row = db.base_row({
        "template_name": name,
        "template_version": lineage,
        "supersedes_template_id": parent_id,
        "target_standard": standard,
        "talkgroup_slot_count": slots,
        "encryption_required": encrypted,
        "status": "DRAFT",
        "created_by_user_id": actor.user_id,
        "deployed_unit_count": 0,
    })
    db.store.templates[row["id"]] = row
    return row


@bp.post("/templates")
def create_template():
    actor = validate.authenticate([FLEET_ENGINEER])
    body = validate.get_body()
    name, standard, slots, encrypted = _content(body)
    row = _new_template(name, standard, slots, encrypted, actor, 1, None)
    return response.ok(serialize.template(row), 201)


@bp.post("/templates/<template_id>/revisions")
def create_revision(template_id):
    actor = validate.authenticate([FLEET_ENGINEER])
    parent = validate.lookup("templates", template_id)
    body = validate.get_body()
    name, standard, slots, encrypted = _content(body)
    common.check_occ(parent, "expected_template_version", body)
    row = _new_template(
        name, standard, slots, encrypted, actor,
        parent["template_version"] + 1, parent["id"],
    )
    parent["status"] = "RETIRED"
    db.touch(parent)
    return response.ok(serialize.template(row), 201)


@bp.get("/templates")
def list_templates():
    validate.authenticate(common.ANY_ROLE)
    filters = (
        ("status", validate.filter_enum("status", enums.TEMPLATE_STATUSES)),
        ("target_standard", validate.filter_enum("target_standard", enums.TARGET_STANDARDS)),
        ("supersedes_template_id", validate.filter_str("supersedes_template_id")),
    )
    return common.list_endpoint("templates", serialize.template, filters)


@bp.get("/templates/<template_id>")
def read_template(template_id):
    validate.authenticate(common.ANY_ROLE)
    template = validate.lookup("templates", template_id)
    return response.ok(serialize.template(template))


@bp.post("/templates/<template_id>/publish")
def publish_template(template_id):
    validate.authenticate([FLEET_ENGINEER])
    template = validate.lookup("templates", template_id)
    if template["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT template may be published.")
    template["status"] = "PUBLISHED"
    db.touch(template)
    return response.ok(serialize.template(template))
