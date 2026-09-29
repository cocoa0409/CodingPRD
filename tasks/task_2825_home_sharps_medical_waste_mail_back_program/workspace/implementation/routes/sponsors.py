"""Sponsors, funded programs, funding adjustments and the ledger (PRD 3.2)."""
from flask import Blueprint

import constants
import db
import middleware
import response
import validate
from errors import (
    ERR_FUNDING_BELOW_OBLIGATIONS,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SPONSOR_NOT_ACTIVE,
    ERR_STALE_PROGRAM_VERSION,
    fail,
)
from middleware import endpoint
from routes.common import page
from services import accounting, lookup
from validate import Field

bp = Blueprint("sponsors", __name__)

SPONSOR_READ_ROLES = ("ProgramAdmin", "SponsorRepresentative")

SPONSOR_SCHEMA = [
    Field("legal_name", "string", required=True, min_len=1),
    Field("sponsor_type", "enum", required=True, values=constants.SPONSOR_TYPES),
    Field("contact_email", "string", required=True, min_len=1),
    Field("status", "enum", default="ACTIVE", values=constants.SPONSOR_STATUSES),
]

STATUS_ACTION_SCHEMA = [
    Field("action", "enum", required=True, values=["SUSPEND", "REINSTATE"]),
    Field("reason", "string"),
]

PROGRAM_SCHEMA = [
    Field("program_code", "string", required=True, min_len=1, max_len=32),
    Field("funding_ceiling_cents", "int", required=True, minimum=1, maximum=100000000),
    Field("per_kit_allowance_cents", "int", required=True, minimum=1, maximum=100000000),
]

FUNDING_SCHEMA = [
    Field("delta_cents", "int", required=True),
    Field("expected_program_version", "int", required=True),
    Field("memo", "string"),
]


@bp.post("/sharps/sponsors")
@endpoint(["ProgramAdmin"])
def create_sponsor():
    body, _provided = validate.parse_body(SPONSOR_SCHEMA)
    row = db.create_row("sponsors", body)
    return response.created(response.view("sponsor", row))


@bp.post("/sharps/sponsors/<sponsor_id>/status-actions")
@endpoint(["ProgramAdmin"])
def sponsor_status_action(sponsor_id):
    body, _provided = validate.parse_body(STATUS_ACTION_SCHEMA)
    sponsor = lookup.require("sponsor", sponsor_id)
    if body["action"] == "SUSPEND":
        if sponsor["status"] != "ACTIVE":
            fail(ERR_SPONSOR_NOT_ACTIVE)
        sponsor["status"] = "SUSPENDED"
    else:
        if sponsor["status"] != "SUSPENDED":
            fail(ERR_SPONSOR_NOT_ACTIVE)
        sponsor["status"] = "ACTIVE"
    db.bump(sponsor)
    return response.ok(response.view("sponsor", sponsor))


@bp.get("/sharps/sponsors/<sponsor_id>")
@endpoint(SPONSOR_READ_ROLES, mutating=False)
def get_sponsor(sponsor_id):
    row = lookup.require("sponsor", sponsor_id)
    return response.ok(response.view("sponsor", row))


@bp.get("/sharps/sponsors")
@endpoint(SPONSOR_READ_ROLES, mutating=False)
def list_sponsors():
    limit, offset = validate.pagination()
    sponsor_type = validate.qs_enum("sponsor_type", constants.SPONSOR_TYPES)
    status = validate.qs_enum("status", constants.SPONSOR_STATUSES)
    rows = db.ordered("sponsors")
    if sponsor_type is not None:
        rows = [r for r in rows if r["sponsor_type"] == sponsor_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page("sponsor", rows, limit, offset)


# ---- programs -----------------------------------------------------------

@bp.post("/sharps/sponsors/<sponsor_id>/programs")
@endpoint(["ProgramAdmin"])
def create_program(sponsor_id):
    body, _provided = validate.parse_body(PROGRAM_SCHEMA)
    sponsor = lookup.require("sponsor", sponsor_id)
    if sponsor["status"] != "ACTIVE":
        fail(ERR_SPONSOR_NOT_ACTIVE)
    ceiling = body["funding_ceiling_cents"]
    row = db.create_row(
        "programs",
        {
            "sponsor_id": sponsor_id,
            "program_code": body["program_code"],
            "funding_ceiling_cents": ceiling,
            "per_kit_allowance_cents": body["per_kit_allowance_cents"],
            "reserved_cents": 0,
            "committed_cents": 0,
            "available_cents": ceiling,
            "kits_issued_count": 0,
            "kits_settled_count": 0,
            "provisional_total_cents": 0,
            "final_total_cents": 0,
            "status": "ACTIVE" if ceiling > 0 else "EXHAUSTED",
        },
    )
    return response.created(response.view("program", row))


@bp.get("/sharps/sponsors/<sponsor_id>/programs")
@endpoint(SPONSOR_READ_ROLES, mutating=False)
def list_sponsor_programs(sponsor_id):
    limit, offset = validate.pagination()
    status = validate.qs_enum("status", constants.PROGRAM_STATUSES)
    lookup.require("sponsor", sponsor_id)
    rows = db.ordered("programs", lambda p: p["sponsor_id"] == sponsor_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page("program", rows, limit, offset)


@bp.get("/sharps/programs/<program_id>")
@endpoint(SPONSOR_READ_ROLES, mutating=False)
def get_program(program_id):
    row = lookup.require("program", program_id)
    return response.ok(response.view("program", row))


@bp.get("/sharps/programs")
@endpoint(SPONSOR_READ_ROLES, mutating=False)
def list_programs():
    limit, offset = validate.pagination()
    sponsor_id = validate.qs_str("sponsor_id")
    status = validate.qs_enum("status", constants.PROGRAM_STATUSES)
    rows = db.ordered("programs")
    if sponsor_id is not None:
        rows = [r for r in rows if r["sponsor_id"] == sponsor_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page("program", rows, limit, offset)


@bp.post("/sharps/programs/<program_id>/funding-adjustments")
@endpoint(["ProgramAdmin", "SponsorRepresentative"])
def adjust_funding(program_id):
    body, _provided = validate.parse_body(FUNDING_SCHEMA)
    program = lookup.require("program", program_id)
    if middleware.role() == "SponsorRepresentative" and middleware.user_id() != program["sponsor_id"]:
        fail(ERR_NOT_RESOURCE_OWNER)
    if body["expected_program_version"] != program["version"]:
        fail(ERR_STALE_PROGRAM_VERSION)

    new_ceiling = program["funding_ceiling_cents"] + body["delta_cents"]
    if new_ceiling < program["reserved_cents"] + program["committed_cents"]:
        fail(ERR_FUNDING_BELOW_OBLIGATIONS)

    program["funding_ceiling_cents"] = new_ceiling
    accounting.append_entry(
        program,
        accounting.FUNDING_ADJUSTMENT,
        body["delta_cents"],
        None,
        body["memo"],
    )
    accounting.recompute_program(program, count_flip=False)
    db.bump(program)
    return response.ok(response.view("program", program))


# ---- ledger -------------------------------------------------------------

@bp.get("/sharps/ledger-entries/<entry_id>")
@endpoint(SPONSOR_READ_ROLES, mutating=False)
def get_ledger_entry(entry_id):
    row = lookup.require("ledger_entry", entry_id)
    return response.ok(response.view("ledger_entry", row))


@bp.get("/sharps/ledger-entries")
@endpoint(SPONSOR_READ_ROLES, mutating=False)
def list_ledger_entries():
    limit, offset = validate.pagination()
    entry_type = validate.qs_enum("entry_type", constants.LEDGER_ENTRY_TYPES)
    program_id = validate.qs_str("sponsorship_program_id")
    kit_id = validate.qs_str("kit_id")
    lookup.require_filter("program", program_id)
    lookup.require_filter("kit", kit_id)
    rows = db.ordered("ledger_entries")
    if program_id is not None:
        rows = [r for r in rows if r["sponsorship_program_id"] == program_id]
    if kit_id is not None:
        rows = [r for r in rows if r["kit_id"] == kit_id]
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    rows.sort(key=lambda r: r["sequence_no"])
    return page("ledger_entry", rows, limit, offset)
