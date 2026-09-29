"""Practice hierarchy and skill taxonomy (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint

import serial
from derive import ancestor_chain, child_groups
from envelope import collection, obj
from errors import fail
from ops import need, settle
from reqctx import (
    GEOGRAPHIES,
    POSTURES,
    SKILL_FAMILIES,
    begin,
    body,
    filter_bool,
    filter_enum,
    filter_value,
    opt_bool,
    opt_dec,
    opt_id,
    opt_level_targets,
    opt_str,
    pagination,
    req_code,
    req_enum,
    req_str,
    window,
)
from store import bump, db

bp = Blueprint("taxonomy", __name__)

READ_ROLES = ("PracticePartner", "ResourceManager", "FinanceController", "SalesLead")
SKILL_READ_ROLES = READ_ROLES + ("Consultant",)


def _unique_group_name(name, skip=None):
    for group in db.all("practice_groups"):
        if group["name"] == name and group["id"] != skip:
            fail("ERR_UNIQUENESS_CONFLICT", "Another practice group already carries that name.")


def _guard_cycle(group_id, parent_id):
    if parent_id is None:
        return
    if parent_id == group_id:
        fail("ERR_GROUP_CYCLE", "A practice group may not be its own parent.")
    for ancestor in ancestor_chain(parent_id):
        if ancestor["id"] == group_id:
            fail("ERR_GROUP_CYCLE", "That parent would close a cycle in the practice hierarchy.")


# --------------------------------------------------------------- practice groups
@bp.post("/practice-groups")
def create_practice_group():
    begin("PracticePartner")
    payload = body(
        allowed=("name", "geography_code", "parent_group_id", "external_sourcing_cap_pct", "level_targets"),
        required=("name", "geography_code"),
    )
    name = req_str(payload, "name", 1, 120)
    geography = req_enum(payload, "geography_code", GEOGRAPHIES)
    parent_id = opt_id(payload, "parent_group_id")
    cap = opt_dec(
        payload, "external_sourcing_cap_pct", Decimal("0.00"), Decimal("100.00"), 2, Decimal("20.00")
    )
    targets = opt_level_targets(payload, default={}) or {}
    if parent_id is not None:
        need("practice_groups", parent_id)
    _unique_group_name(name)
    row = db.new_row("practice_groups")
    row.update(
        {
            "name": name,
            "geography_code": geography,
            "parent_group_id": parent_id,
            "external_sourcing_cap_pct": cap,
            "level_targets": targets,
        }
    )
    db.insert("practice_groups", row)
    settle()
    return obj(serial.practice_group(row), 201)


@bp.get("/practice-groups")
def list_practice_groups():
    begin(*READ_ROLES)
    limit, offset = pagination()
    geography = filter_enum("geography_code", GEOGRAPHIES)
    posture = filter_enum("posture", POSTURES)
    parent_id = filter_value("parent_group_id")
    rows = db.all("practice_groups")
    if geography is not None:
        rows = [r for r in rows if r["geography_code"] == geography]
    if parent_id is not None:
        rows = [r for r in rows if r.get("parent_group_id") == parent_id]
    if posture is not None:
        rows = [r for r in rows if serial.practice_group(r)["posture"] == posture]
    page, total = window(rows, limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


@bp.get("/practice-groups/<group_id>")
def read_practice_group(group_id):
    begin(*READ_ROLES)
    return obj(serial.practice_group(need("practice_groups", group_id)))


@bp.patch("/practice-groups/<group_id>")
def update_practice_group(group_id):
    begin("PracticePartner")
    group = need("practice_groups", group_id)
    payload = body(allowed=("name", "external_sourcing_cap_pct", "level_targets", "parent_group_id"))
    name = opt_str(payload, "name", 1, 120)
    cap = opt_dec(payload, "external_sourcing_cap_pct", Decimal("0.00"), Decimal("100.00"), 2)
    targets = opt_level_targets(payload)
    parent_supplied = "parent_group_id" in payload
    parent_id = opt_id(payload, "parent_group_id")
    if parent_id is not None:
        need("practice_groups", parent_id)
    if name is not None:
        _unique_group_name(name, skip=group["id"])
    if parent_supplied:
        _guard_cycle(group["id"], parent_id)
    if name is not None:
        group["name"] = name
    if cap is not None:
        group["external_sourcing_cap_pct"] = cap
    if targets is not None:
        group["level_targets"] = targets
    if parent_supplied:
        group["parent_group_id"] = parent_id
    bump(group)
    settle()
    return obj(serial.practice_group(group))


@bp.get("/practice-groups/<group_id>/child-groups")
def list_child_groups(group_id):
    begin(*READ_ROLES)
    need("practice_groups", group_id)
    limit, offset = pagination()
    page, total = window(child_groups(group_id), limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


# ----------------------------------------------------------------------- skills
@bp.post("/skills")
def create_skill():
    begin("PracticePartner")
    payload = body(
        allowed=("code", "name", "family", "scarcity_index", "retired"),
        required=("code", "name", "family"),
    )
    code = req_code(payload, "code")
    name = req_str(payload, "name", 1, 120)
    family = req_enum(payload, "family", SKILL_FAMILIES)
    scarcity = opt_dec(payload, "scarcity_index", Decimal("0.0000"), Decimal("1.0000"), 4, Decimal("0.5000"))
    retired = opt_bool(payload, "retired", False)
    for skill in db.all("skills"):
        if skill["code"] == code:
            fail("ERR_UNIQUENESS_CONFLICT", "Another skill already carries that code.")
    row = db.new_row("skills")
    row.update(
        {"code": code, "name": name, "family": family, "scarcity_index": scarcity, "retired": retired}
    )
    db.insert("skills", row)
    return obj(serial.skill(row), 201)


@bp.get("/skills")
def list_skills():
    begin(*SKILL_READ_ROLES)
    limit, offset = pagination()
    family = filter_enum("family", SKILL_FAMILIES)
    retired = filter_bool("retired")
    code = filter_value("code")
    rows = db.all("skills")
    if family is not None:
        rows = [r for r in rows if r["family"] == family]
    if retired is not None:
        rows = [r for r in rows if r["retired"] is retired]
    if code is not None:
        rows = [r for r in rows if r["code"] == code]
    page, total = window(rows, limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


@bp.get("/skills/<skill_id>")
def read_skill(skill_id):
    begin(*SKILL_READ_ROLES)
    return obj(serial.skill(need("skills", skill_id)))


@bp.patch("/skills/<skill_id>")
def update_skill(skill_id):
    begin("PracticePartner")
    skill = need("skills", skill_id)
    payload = body(allowed=("name", "scarcity_index", "retired"))
    name = opt_str(payload, "name", 1, 120)
    scarcity = opt_dec(payload, "scarcity_index", Decimal("0.0000"), Decimal("1.0000"), 4)
    retired = opt_bool(payload, "retired")
    if name is not None:
        skill["name"] = name
    if scarcity is not None:
        skill["scarcity_index"] = scarcity
    if retired is not None:
        skill["retired"] = retired
    bump(skill)
    return obj(serial.skill(skill))
