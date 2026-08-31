"""Option agreements: windows, escalation and the net purchase price."""

from flask import Blueprint

import calc
from core import (
    Field, add_months, authenticate, collection_rows, created, db, fail, filter_eq,
    fmt_dt, json_body, lookup, new_row, now, now_str, ok, ok_list, paginate,
    pagination, parse_dt, parse_fields, qp, touch,
)

bp = Blueprint("option", __name__)

OPTION_READ_ROLES = ("SlateAdmin", "BusinessAffairs", "DevelopmentExec", "StoryEditor")


@bp.post("/option-agreements")
def create_option():
    authenticate(("BusinessAffairs",))
    body = json_body()
    prop = None
    if body.get("property_id") is not None:
        prop = lookup("properties", body.get("property_id"), "ERR_PROPERTY_NOT_FOUND")
    data = parse_fields(body, [
        Field("property_id", "string", required=True),
        Field("expected_property_version", "integer", required=True),
        Field("option_fee_cents", "integer", required=True, lo=1),
        Field("purchase_price_cents", "integer", required=True, lo=1),
        Field("initial_period_months", "integer", required=True, lo=1, hi=36),
        Field("option_start_at", "datetime", required=True),
        Field("extension_period_months", "integer", default=0, lo=0, hi=24),
        Field("extension_fee_cents", "integer", default=0),
        Field("applicable_to_purchase", "boolean", default=True),
    ])
    start = parse_dt(data["option_start_at"])
    if data["expected_property_version"] != prop["version"]:
        fail("ERR_STALE_VERSION", "The property has changed since it was last observed.")
    for existing in calc.rows_where("options", property_id=prop["id"]):
        if existing["status"] == "EXERCISED":
            fail("ERR_INVALID_STATE",
                 "This property already carries an exercised option agreement.")
    row = new_row("options", {
        "property_id": prop["id"],
        "option_fee_cents": data["option_fee_cents"],
        "purchase_price_cents": data["purchase_price_cents"],
        "initial_period_months": data["initial_period_months"],
        "extension_period_months": data["extension_period_months"],
        "extension_fee_cents": data["extension_fee_cents"],
        "applicable_to_purchase": data["applicable_to_purchase"],
        "option_start_at": fmt_dt(start),
        "option_end_at": None,
        "extension_exercised": False,
        "escalation_bps": 0,
        "adjusted_purchase_price_cents": None,
        "applicable_credit_cents": 0,
        "net_purchase_due_cents": None,
        "status": "DRAFTED",
        "termination_reason": None,
        "exercise_notice_at": None,
    })
    for existing in calc.rows_where("options", property_id=prop["id"]):
        if existing["id"] == row["id"]:
            continue
        if existing["status"] == "DRAFTED":
            existing["status"] = "TERMINATED"
            existing["termination_reason"] = "SUPERSEDED_BY_NEW_DRAFT"
            touch(existing)
    touch(prop)
    return created(row)


@bp.get("/option-agreements/<oid>")
def read_option(oid):
    authenticate(OPTION_READ_ROLES)
    return ok(lookup("options", oid, "ERR_OPTION_NOT_FOUND"))


@bp.get("/option-agreements")
def list_options():
    authenticate(OPTION_READ_ROLES)
    limit, offset = pagination()
    rows = collection_rows("options")
    rows = filter_eq(rows, "property_id", qp("property_id"))
    rows = filter_eq(rows, "status", qp("status"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/option-agreements/<oid>/execute")
def execute_option(oid):
    authenticate(("BusinessAffairs",))
    option = lookup("options", oid, "ERR_OPTION_NOT_FOUND")
    if option["status"] != "DRAFTED":
        fail("ERR_INVALID_STATE", "Only a DRAFTED option agreement may be executed.")
    prop = db.properties.get(option["property_id"])
    if prop is None or prop["rights_chain_status"] != "CLEAR":
        fail("ERR_RIGHTS_CHAIN_INCOMPLETE", "The property's chain of title is not CLEAR.")
    start = parse_dt(option["option_start_at"])
    end = add_months(start, option["initial_period_months"])
    option["option_end_at"] = fmt_dt(end)
    if calc.option_period_conflict(option):
        option["option_end_at"] = None
        fail("ERR_OPTION_PERIOD_OVERLAP", "The option window intersects an incumbent option.")
    option["status"] = "ACTIVE"
    calc.option_pricing(option)
    touch(option)
    calc.recompute_encumbrance(prop)
    touch(prop)
    return ok(option)


@bp.post("/option-agreements/<oid>/extend")
def extend_option(oid):
    authenticate(("BusinessAffairs",))
    option = lookup("options", oid, "ERR_OPTION_NOT_FOUND")
    if option["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE option agreement may be extended.")
    if option["extension_exercised"]:
        fail("ERR_INVALID_STATE", "The single permitted extension has already been taken.")
    if (option["extension_period_months"] or 0) < 1:
        fail("ERR_INVALID_STATE", "This agreement carries no extension period.")
    if now() >= parse_dt(option["option_end_at"]):
        fail("ERR_OPTION_EXPIRED", "The option window has closed.")
    option["extension_exercised"] = True
    option["option_end_at"] = fmt_dt(
        add_months(parse_dt(option["option_end_at"]), option["extension_period_months"]))
    option["status"] = "EXTENDED"
    calc.option_pricing(option)
    touch(option)
    return ok(option)


@bp.post("/option-agreements/<oid>/exercise")
def exercise_option(oid):
    authenticate(("BusinessAffairs",))
    option = lookup("options", oid, "ERR_OPTION_NOT_FOUND")
    if option["status"] not in ("ACTIVE", "EXTENDED"):
        fail("ERR_INVALID_STATE", "Only an ACTIVE or EXTENDED option may be exercised.")
    if now() >= parse_dt(option["option_end_at"]):
        fail("ERR_OPTION_EXPIRED", "The option window has closed.")
    project = calc.project_for_option(option["id"])
    if project is None or project["rights_status"] != "OPTIONED":
        fail("ERR_INVALID_STATE",
             "No development project with rights_status OPTIONED is linked to this option.")
    option["status"] = "EXERCISED"
    option["exercise_notice_at"] = now_str()
    calc.option_pricing(option)
    touch(option)
    project["rights_status"] = "OWNED"
    calc.recompute_greenlight_ready(project)
    touch(project)
    return ok(option)


@bp.post("/option-agreements/<oid>/lapse")
def lapse_option(oid):
    authenticate(("BusinessAffairs",))
    option = lookup("options", oid, "ERR_OPTION_NOT_FOUND")
    if option["status"] not in ("ACTIVE", "EXTENDED"):
        fail("ERR_INVALID_STATE", "Only an ACTIVE or EXTENDED option may lapse.")
    if now() < parse_dt(option["option_end_at"]):
        fail("ERR_INVALID_STATE", "The option window has not yet closed.")
    option["status"] = "LAPSED"
    touch(option)
    # link one
    prop = db.properties.get(option["property_id"])
    if prop is not None:
        calc.recompute_encumbrance(prop)
        touch(prop)
    # links two and three
    project = calc.project_for_option(option["id"])
    if project is not None:
        project["rights_status"] = "LAPSED_RIGHTS"
        project["development_status"] = "DEAD"
        calc.recompute_greenlight_ready(project)
        # links three, four and five
        calc.terminate_open_engagements(project, None)
        touch(project)
    return ok(option)


@bp.post("/option-agreements/<oid>/terminate")
def terminate_option(oid):
    authenticate(("BusinessAffairs",))
    option = lookup("options", oid, "ERR_OPTION_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [Field("reason", "string", required=True)])
    if option["status"] in calc.OPTION_TERMINAL:
        fail("ERR_TERMINAL_STATE", "This option agreement is already in a terminal state.")
    if option["status"] != "DRAFTED":
        fail("ERR_INVALID_STATE", "Only a DRAFTED option agreement may be torn up.")
    option["status"] = "TERMINATED"
    option["termination_reason"] = data["reason"]
    touch(option)
    return ok(option)
