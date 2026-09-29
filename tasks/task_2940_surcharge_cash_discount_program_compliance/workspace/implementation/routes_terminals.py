"""Terminal configuration, enforcement and the quarantine cycle."""

from flask import Blueprint

import auth
import listing
import serialize
import validation as v
from auth import authorize, check_action_role, check_merchant_ownership
from envelope import ok
from errors import ApiError
from store import db, touch
from validation import MISSING, as_bool, as_enum, as_string, field, parse_body

bp = Blueprint("terminals", __name__)

TERMINAL_STATES = ("PROVISIONED", "CONFIGURED", "ENFORCING", "QUARANTINED", "DISABLED")
TERMINAL_ACTIONS = ("ENFORCE", "QUARANTINE", "RESTORE")


@bp.post("/terminals/<terminal_id>/configure")
def configure_terminal(terminal_id):
    actor = authorize(["MerchantOperator"])
    term = auth.get_terminal(terminal_id)
    check_merchant_ownership(actor, term["merchant_id"])
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["program_id", "debit_exclusion_enabled", "bin_table_version"])
    program_id = as_string(body["program_id"], "program_id", 1)
    debit_exclusion_enabled = as_bool(body["debit_exclusion_enabled"], "debit_exclusion_enabled")
    bin_table_version = as_string(body["bin_table_version"], "bin_table_version", 1, 100)

    program = auth.get_program(program_id)

    if term["state"] == "DISABLED":
        raise ApiError("ERR_INVALID_TERMINAL_STATE",
                       "A DISABLED terminal can no longer be configured.")
    if program["status"] == "WITHDRAWN":
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "A terminal cannot be bound to a WITHDRAWN program.")
    if program["merchant_id"] != term["merchant_id"]:
        raise ApiError("ERR_TERMINAL_PROGRAM_MISMATCH",
                       "The named program belongs to another merchant.")

    term["program_id"] = program["id"]
    term["debit_exclusion_enabled"] = debit_exclusion_enabled
    term["bin_table_version"] = bin_table_version
    term["state"] = "CONFIGURED"
    term["quarantine_reason"] = "NONE"
    term["last_configured_at"] = db.now()
    touch(term)
    return ok(serialize.terminal(term))


@bp.post("/terminals/<terminal_id>/state-actions")
def terminal_state_action(terminal_id):
    actor = authorize(["MerchantOperator", "ComplianceOfficer"])
    body, malformed = parse_body()
    raw_action = None if malformed else field(body, "action")
    check_action_role("terminal_state", raw_action, actor)
    term = auth.get_terminal(terminal_id)
    check_merchant_ownership(actor, term["merchant_id"])
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["action"])
    action = as_enum(body["action"], "action", TERMINAL_ACTIONS)
    note_raw = field(body, "note")
    if note_raw is not MISSING and note_raw is not None:
        as_string(note_raw, "note", 1, 1000)

    program = db.programs.get(term.get("program_id"))

    if action == "ENFORCE":
        if term["state"] != "CONFIGURED":
            raise ApiError("ERR_INVALID_TERMINAL_STATE",
                           "Only a CONFIGURED terminal can be driven to enforcement.")
        if program is None or program["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_PROGRAM_STATE",
                           "The bound program must be ACTIVE before a terminal may enforce.")
        if program["program_type"] == "SURCHARGE" and not term["debit_exclusion_enabled"]:
            raise ApiError("ERR_DEBIT_EXCLUSION_NOT_ENABLED",
                           "The terminal's BIN table does not exclude debit and prepaid ranges.")
        if not program["disclosure_ready"]:
            raise ApiError("ERR_DISCLOSURE_INCOMPLETE",
                           "The bound program's disclosures are not complete.")
        term["state"] = "ENFORCING"
        term["quarantine_reason"] = "NONE"
        touch(term)
    elif action == "QUARANTINE":
        if term["state"] != "ENFORCING":
            raise ApiError("ERR_INVALID_TERMINAL_STATE",
                           "Only an ENFORCING terminal can be quarantined.")
        term["state"] = "QUARANTINED"
        term["quarantine_reason"] = "OPERATOR_ACTION"
        touch(term)
    else:
        if term["state"] != "QUARANTINED":
            raise ApiError("ERR_INVALID_TERMINAL_STATE",
                           "Only a QUARANTINED terminal can be restored.")
        healthy = (program is not None and program["status"] == "ACTIVE"
                   and bool(program["disclosure_ready"]))
        if healthy:
            # Branch A -- back to enforcement.
            if program["program_type"] == "SURCHARGE" and not term["debit_exclusion_enabled"]:
                raise ApiError("ERR_DEBIT_EXCLUSION_NOT_ENABLED",
                               "The terminal's BIN table does not exclude debit and prepaid ranges.")
            term["state"] = "ENFORCING"
        else:
            # Branch B -- back to configuration only.
            if program is None or program["status"] in ("DISABLED", "WITHDRAWN"):
                raise ApiError("ERR_INVALID_PROGRAM_STATE",
                               "A terminal bound to a prohibited or withdrawn program cannot be restored.")
            term["state"] = "CONFIGURED"
        term["quarantine_reason"] = "NONE"
        touch(term)

    return ok(serialize.terminal(term))


@bp.get("/terminals/<terminal_id>")
def read_terminal(terminal_id):
    authorize(auth.READ_ROLES)
    return ok(serialize.terminal(auth.get_terminal(terminal_id)))


@bp.get("/terminals")
def list_terminals():
    authorize(auth.READ_ROLES)
    rows = listing.filtered(list(db.terminals.values()), [
        (listing.arg("merchant_id"), "merchant_id"),
        (listing.arg("program_id"), "program_id"),
        (listing.enum_arg("state", TERMINAL_STATES), "state"),
    ])
    return listing.list_response(rows, serialize.terminal)
