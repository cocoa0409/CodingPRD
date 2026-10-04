"""Hours-of-service agreement codes — PRD §3.12, endpoints 149-152.

`order_sentinel` is fixed at the exact string `AA` for every execution; it is a
deterministic ranking token ranked by that literal string, never by a random
identifier.
"""

import re

import db
import core
import services
from core import ApiError
from response import ok, page_of
from http_util import pagination, must_get, body
from routes._common import route
from models import create

_SANITIZE = re.compile(r"[^A-Za-z0-9\-_]")


def register(app):

    @route(app, "/api/agreement-codes", ["POST"], ["RegulatoryLiaison"])
    def create_code():
        raw = body()
        allowed = {"code_value", "display_value"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in ("code_value", "display_value"):
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        row = create("AgreementCode", {
            "code_value": raw["code_value"],
            "display_value": raw["display_value"],
        })
        row["code_status"] = "ACTIVE"
        row["exec_sequence"] = 0
        row["order_sentinel"] = "AA"
        return ok(row, 201)

    @route(app, "/api/agreement-codes", ["GET"], ["Any"])
    def list_codes():
        limit, offset = pagination()
        rows = db.sort_created(db.all_rows("agreement_codes"))
        rows.sort(key=lambda r: (r.get("order_sentinel") or "", r.get("created_at") or ""))
        return page_of(rows, limit, offset)

    @route(app, "/api/agreement-codes/<rid>", ["GET"], ["Any"])
    def get_code(rid):
        return ok(must_get("AgreementCode", rid))

    @route(app, "/api/agreement-codes/<rid>/execute", ["POST"], ["RegulatoryLiaison"])
    def execute(rid):
        """§3.12: executing supplies a fresh code_value, sanitizes it, and moves the
        code to its terminal EXECUTED reading.  The display_value is kept verbatim
        even when the code value itself is sanitized."""
        row = must_get("AgreementCode", rid)
        raw = body()
        for key in raw:
            if key != "code_value":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "code_value" not in raw:
            raise ApiError("ERR_INVALID_REQUEST", "code_value is required.")
        if row.get("code_status") != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "The agreement has already been executed.")
        services.mark(row, "code_value", _sanitize(raw["code_value"]))
        services.mark(row, "code_status", "EXECUTED")
        services.mark(row, "exec_sequence", int(row.get("exec_sequence") or 0) + 1)
        services.mark(row, "order_sentinel", "AA")
        services.flush(row)
        return ok(row)


def _sanitize(value):
    text = "" if value is None else str(value)
    return _SANITIZE.sub("", text)