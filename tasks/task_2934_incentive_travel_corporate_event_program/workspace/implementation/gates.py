"""Shared ladder helpers: path existence (4), program lifecycle (10), filters."""

from flask import request

from errors import fail
from store import db

PROGRAM_TABLES = {
    "program": ("programs", "ERR_PROGRAM_NOT_FOUND"),
    "tier": ("award_tiers", "ERR_TIER_NOT_FOUND"),
    "qualifier": ("qualifiers", "ERR_QUALIFIER_NOT_FOUND"),
    "destination": ("destinations", "ERR_DESTINATION_NOT_FOUND"),
    "contract": ("supplier_contracts", "ERR_CONTRACT_NOT_FOUND"),
    "milestone": ("deposit_milestones", "ERR_MILESTONE_NOT_FOUND"),
    "registration": ("registrations", "ERR_REGISTRATION_NOT_FOUND"),
    "activity": ("onsite_activities", "ERR_ACTIVITY_NOT_FOUND"),
    "signup": ("activity_signups", "ERR_SIGNUP_NOT_FOUND"),
    "report": ("tax_award_reports", "ERR_TAX_REPORT_NOT_FOUND"),
}


def lookup(kind, row_id):
    """Priority 4 / 5: resolve an id or raise the entity's own 404."""
    table_name, error_id = PROGRAM_TABLES[kind]
    row = getattr(db, table_name).get(row_id)
    if row is None:
        fail(error_id)
    return row


def program_gate(program, allowed):
    """Priority 10: the program's status must permit the operation."""
    if program["status"] not in allowed:
        fail("ERR_PROGRAM_STATE_INVALID")
    return program


def program_of_qualifier(qualifier):
    return db.programs.get(qualifier["program_id"])


def _as_text(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return None
    return str(value)


def filtered(rows, spec):
    """Apply the endpoint's declared query filters by string comparison."""
    out = rows
    for param, field in spec:
        raw = request.args.get(param)
        if raw is None:
            continue
        wanted = raw.strip()
        out = [r for r in out if _as_text(r.get(field)) == wanted]
    return out
