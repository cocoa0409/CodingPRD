"""Arbitration clause variants — PRD §3.13, endpoints 144-148.

`variant_code` is derived rather than supplied: when `wildcard` is true the code
is the clause stem with its wildcard segment — the first digit-to-digit segment
in the stem — removed, and when `wildcard` is false the code is the clause stem
verbatim.
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

_DIGIT_SEGMENT = re.compile(r"\d+\D+\d+")


def register(app):

    @route(app, "/api/clause-variants", ["POST"], ["ComplianceOfficer"])
    def create_variant():
        raw = body()
        allowed = {"clause_stem", "wildcard", "variant_code"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "clause_stem" not in raw:
            raise ApiError("ERR_INVALID_REQUEST", "clause_stem is required.")
        stem = raw["clause_stem"]
        if not isinstance(stem, str) or not stem:
            raise ApiError("ERR_INVALID_REQUEST", "clause_stem must be a non-empty string.")
        wildcard = bool(raw.get("wildcard", False))
        row = create("ClauseVariant", {
            "clause_stem": stem,
            "wildcard": wildcard,
            "decline_reason": None,
        })
        row["variant_status"] = "PENDING"
        services.mark(row, "variant_code", _derive_code(stem, wildcard))
        services.mark(row, "variant_status_summary", _summary(row))
        services.flush(row)
        return ok(row, 201)

    @route(app, "/api/clause-variants", ["GET"], ["Any"])
    def list_variants():
        limit, offset = pagination()
        return page_of(db.sort_created(db.all_rows("clause_variants")), limit, offset)

    @route(app, "/api/clause-variants/<rid>", ["GET"], ["Any"])
    def get_variant(rid):
        return ok(must_get("ClauseVariant", rid))

    @route(app, "/api/clause-variants/<rid>/elect", ["POST"], ["ComplianceOfficer"])
    def elect(rid):
        """§3.13: electing the wildcard reading sets wildcard true, recomputes
        variant_status to ELECTED, and recomputes variant_status_summary."""
        row = must_get("ClauseVariant", rid)
        raw = body()
        for key in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % key)
        if row.get("variant_status") == "DECLINED":
            raise ApiError("ERR_INVALID_STATE", "A declined variant cannot be elected.")
        services.mark(row, "wildcard", True)
        services.mark(row, "variant_status", "ELECTED")
        services.mark(row, "variant_code",
                      _derive_code(row.get("clause_stem"), True))
        services.mark(row, "variant_status_summary", _summary(row))
        services.flush(row)
        return ok(row)

    @route(app, "/api/clause-variants/<rid>/decline", ["POST"], ["ComplianceOfficer"])
    def decline(rid):
        """§3.13: declining records a decline_reason and moves variant_status to
        DECLINED."""
        row = must_get("ClauseVariant", rid)
        raw = body()
        for key in raw:
            if key != "decline_reason":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "decline_reason" not in raw:
            raise ApiError("ERR_INVALID_REQUEST", "decline_reason is required.")
        if row.get("variant_status") == "DECLINED":
            raise ApiError("ERR_INVALID_STATE", "The variant is already declined.")
        services.mark(row, "decline_reason", raw["decline_reason"])
        services.mark(row, "variant_status", "DECLINED")
        services.mark(row, "variant_status_summary", _summary(row))
        services.flush(row)
        return ok(row)


def _derive_code(clause_stem, wildcard):
    """The first digit-to-digit segment in the stem is removed under the wildcard
    reading; otherwise the stem is returned verbatim."""
    stem = clause_stem or ""
    if not wildcard:
        return stem
    match = _DIGIT_SEGMENT.search(stem)
    if not match:
        return stem
    return stem[:match.start()] + stem[match.end():]


def _summary(row):
    """NOT_ELECTED | ELECTED | DECLINED_PENDING — distinct from the raw
    variant_status reading."""
    status = row.get("variant_status")
    if status == "ELECTED":
        return "ELECTED"
    if status == "DECLINED":
        return "DECLINED_PENDING"
    return "NOT_ELECTED"