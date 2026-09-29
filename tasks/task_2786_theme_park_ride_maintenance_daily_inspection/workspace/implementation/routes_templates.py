"""Inspection template revisions and their immutable checklist lines."""

from flask import Blueprint

import derive
import fetch
import store
import validate
from auth import ALL_ROLES, require_roles
from envelope import list_response
from errors import (
    fail,
    invalid,
    ERR_COMPONENT_ATTRACTION_MISMATCH,
    ERR_STALE_ATTRACTION_VERSION,
    ERR_TEMPLATE_HAS_NO_ITEMS,
    ERR_TEMPLATE_STATE_INVALID,
)
from reply import computed, made, saved

bp = Blueprint("templates", __name__)

SEVERITY_CLASSES = ("SAFETY_CRITICAL", "ESSENTIAL", "ADVISORY")


@bp.post("/park-ops/inspection-templates")
@require_roles("ParkOpsAdmin")
def create_template():
    data = validate.body()
    attraction = fetch.fk("attractions", data.get("attraction_id"))
    validate.id_field(data, "attraction_id")
    effective_from = validate.date_field(data, "effective_from_date")
    siblings = [t for t in store.rows("templates")
                if t["attraction_id"] == attraction["id"]]
    revision = max([t["revision"] for t in siblings], default=0) + 1
    row = store.create(
        "templates",
        attraction_id=attraction["id"],
        revision=revision,
        effective_from_date=effective_from.isoformat(),
        status="DRAFT",
        activated_at=None,
    )
    return made(derive.ser_template, row)


@bp.get("/park-ops/inspection-templates/<template_id>")
@require_roles(*ALL_ROLES)
def read_template(template_id):
    return computed(derive.ser_template(fetch.template(template_id)))


@bp.get("/park-ops/inspection-templates")
@require_roles(*ALL_ROLES)
def list_templates():
    return list_response(
        store.rows("templates"),
        derive.ser_template,
        filters=(("attraction_id", "str"), ("status", "str")),
        order=("attraction_id", "revision"),
    )


@bp.post("/park-ops/inspection-templates/<template_id>/items")
@require_roles("ParkOpsAdmin")
def append_checklist_item(template_id):
    template = fetch.template(template_id)
    data = validate.body()
    component = fetch.fk("components", data.get("component_id"))
    sequence_no = validate.int_field(data, "sequence_no", minimum=1)
    description = validate.str_field(data, "description")
    severity_class = validate.enum_field(data, "severity_class",
                                         SEVERITY_CLASSES)
    requires_photo = validate.bool_field(data, "requires_photo", default=False)
    for existing in derive.checklist_items_of(template["id"]):
        if existing["sequence_no"] == sequence_no:
            invalid("sequence_no must not repeat within a template.")
    if template["status"] != "DRAFT":
        fail(ERR_TEMPLATE_STATE_INVALID,
             "Checklist lines may only be appended to a DRAFT revision.")
    if component is not None:
        if component["attraction_id"] != template["attraction_id"]:
            fail(ERR_COMPONENT_ATTRACTION_MISMATCH,
                 "The component is installed on a different attraction.")
    row = store.create(
        "checklist_items",
        versioned=False,
        template_id=template["id"],
        component_id=component["id"] if component else None,
        sequence_no=sequence_no,
        description=description,
        severity_class=severity_class,
        requires_photo=requires_photo,
    )
    return made(derive.ser_checklist_item, row)


@bp.post("/park-ops/inspection-templates/<template_id>/activate")
@require_roles("ParkOpsAdmin")
def activate_template(template_id):
    template = fetch.template(template_id)
    data = validate.body()
    expected = validate.int_field(data, "expected_attraction_version")
    attraction = store.db.attractions.get(template["attraction_id"])
    if attraction is None or expected != attraction["version"]:
        fail(ERR_STALE_ATTRACTION_VERSION,
             "expected_attraction_version does not match the attraction.")
    if template["status"] != "DRAFT":
        fail(ERR_TEMPLATE_STATE_INVALID,
             "Only a DRAFT revision may be activated.")
    if derive.item_count(template) < 1:
        fail(ERR_TEMPLATE_HAS_NO_ITEMS,
             "A revision must carry at least one checklist line.")
    previous = derive.active_template(attraction)
    if previous is not None and previous["id"] != template["id"]:
        previous["status"] = "SUPERSEDED"
    template["status"] = "ACTIVE"
    template["activated_at"] = store.now_iso()
    return saved(derive.ser_template, template)


@bp.get("/park-ops/checklist-items/<item_id>")
@require_roles(*ALL_ROLES)
def read_checklist_item(item_id):
    return computed(derive.ser_checklist_item(fetch.checklist_item(item_id)))


@bp.get("/park-ops/checklist-items")
@require_roles(*ALL_ROLES)
def list_checklist_items():
    return list_response(
        store.rows("checklist_items"),
        derive.ser_checklist_item,
        filters=(("template_id", "str"), ("component_id", "str"),
                 ("severity_class", "str")),
        order=("sequence_no",),
    )
