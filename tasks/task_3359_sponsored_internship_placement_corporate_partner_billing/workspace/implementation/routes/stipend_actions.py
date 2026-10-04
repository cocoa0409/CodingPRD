"""Stipend payment and void (PRD 3.5)."""

from flask import Blueprint

import db
import middleware
import response
from errors import ERR_ALREADY_TERMINAL, ApiError
from routes.common import must_get
from services import stipend_svc

TERMINAL_STATUSES = ("PAID", "VOID")

bp = Blueprint("stipend_actions", __name__)


def _guard_terminal(statement):
    if statement["status"] in TERMINAL_STATUSES:
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "stipend statement %s is already %s" % (statement["id"], statement["status"]),
            409,
        )


@bp.post("/stipend-statements/<statement_id>/payments")
def pay_stipend_statement(statement_id):
    middleware.require(("ProgramStaff",))
    statement = must_get("stipend_statements", statement_id, "stipend statement")
    _guard_terminal(statement)

    statement["status"] = "PAID"
    db.touch(statement)
    stipend_svc.apply_payment(statement)
    return response.success(statement)


@bp.post("/stipend-statements/<statement_id>/voids")
def void_stipend_statement(statement_id):
    middleware.require(("ProgramStaff",))
    statement = must_get("stipend_statements", statement_id, "stipend statement")
    _guard_terminal(statement)

    statement["status"] = "VOID"
    db.touch(statement)
    stipend_svc.apply_void(statement)
    return response.success(statement)
